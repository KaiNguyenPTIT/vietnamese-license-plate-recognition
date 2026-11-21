"""Chuẩn hóa ký tự và nhận dạng bằng Template Matching.

Phương pháp chính theo đặc tả: ``cv2.matchTemplate`` với ``TM_CCOEFF_NORMED``.
Ngoài ra hỗ trợ ``pixel`` (1 - tỷ lệ pixel khác nhau) và ``hybrid`` để phục vụ
thực nghiệm so sánh. Không có mô hình học máy nào được sử dụng.
"""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from .config import Config, RecognitionConfig
from .io_utils import ImageIOError, read_image


class TemplateError(RuntimeError):
    """Bộ template thiếu hoặc không đọc được."""


class EmptyCharacterError(ValueError):
    """Ảnh ký tự không có điểm ảnh foreground."""


# ----------------------------------------------------------------------
# Chuẩn hóa
# ----------------------------------------------------------------------
def _to_ink_binary(image: np.ndarray) -> np.ndarray:
    """Chuyển ảnh ký tự về nhị phân với ký tự màu trắng."""
    if image is None or image.size == 0:
        raise EmptyCharacterError("Ảnh ký tự rỗng")
    if image.ndim == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image.copy()
    if gray.ndim != 2:
        raise EmptyCharacterError("Ảnh ký tự phải là ảnh xám hoặc BGR")

    unique = np.unique(gray)
    is_binary = len(unique) <= 2 and np.all(np.isin(unique, [0, 255]))
    if is_binary:
        binary = gray.copy()
        # Không dùng mean toàn ảnh: ký tự đậm (0, 8, M...) có thể chiếm hơn
        # 50% diện tích và sẽ bị đảo sai. Xét viền ảnh — nền thường nằm ở viền.
        border = np.concatenate(
            [binary[0, :], binary[-1, :], binary[:, 0], binary[:, -1]]
        )
        if float(np.mean(border)) > 127:
            binary = cv2.bitwise_not(binary)
        return binary

    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    _, binary = cv2.threshold(
        blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )
    border = np.concatenate(
        [binary[0, :], binary[-1, :], binary[:, 0], binary[:, -1]]
    )
    if float(np.mean(border)) > 127:
        binary = cv2.bitwise_not(binary)
    return binary


def normalize_character(
    image: np.ndarray,
    width: int = 32,
    height: int = 48,
    padding: int = 2,
    upscale: bool = True,
    mode: str = "stretch",
) -> np.ndarray:
    """Cắt sát ink box rồi đưa về canvas cố định.

    ``mode="stretch"`` kéo giãn ink box vừa khít vùng trong padding. Cách này
    làm mất tỷ lệ riêng của từng ký tự nhưng bù lại giảm mạnh ảnh hưởng của
    độ dày nét và font: biển thật thường dùng font rất đậm, trong khi template
    có cả font mảnh. ``mode="aspect"`` giữ tỷ lệ như phiên bản cũ.
    """
    binary = _to_ink_binary(image)
    ys, xs = np.where(binary > 0)
    if len(xs) == 0 or len(ys) == 0:
        raise EmptyCharacterError("Ký tự không có điểm ảnh foreground")
    x1, x2 = int(xs.min()), int(xs.max()) + 1
    y1, y2 = int(ys.min()), int(ys.max()) + 1
    ink = binary[y1:y2, x1:x2]
    ih, iw = ink.shape[:2]
    if ih <= 0 or iw <= 0:
        raise EmptyCharacterError("Ký tự có kích thước 0")

    pad = max(0, int(padding))
    inner_w = max(1, int(width) - 2 * pad)
    inner_h = max(1, int(height) - 2 * pad)
    mode = (mode or "stretch").lower()
    if mode not in {"stretch", "aspect"}:
        raise ValueError(f"Kiểu chuẩn hóa không hợp lệ: {mode}")

    if mode == "stretch":
        if upscale:
            new_w, new_h = inner_w, inner_h
        else:
            scale = min(1.0, inner_w / float(iw), inner_h / float(ih))
            new_w = max(1, int(round(iw * scale)))
            new_h = max(1, int(round(ih * scale)))
    else:
        scale = min(inner_w / float(iw), inner_h / float(ih))
        if not upscale:
            scale = min(1.0, scale)
        new_w = max(1, int(round(iw * scale)))
        new_h = max(1, int(round(ih * scale)))

    scale = max(new_w / float(iw), new_h / float(ih))
    interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC
    resized = cv2.resize(ink, (new_w, new_h), interpolation=interp)
    _, resized = cv2.threshold(resized, 127, 255, cv2.THRESH_BINARY)

    canvas = np.zeros((int(height), int(width)), dtype=np.uint8)
    ox = pad + (inner_w - new_w) // 2
    oy = pad + (inner_h - new_h) // 2
    ox = max(0, min(ox, int(width) - new_w))
    oy = max(0, min(oy, int(height) - new_h))
    canvas[oy : oy + new_h, ox : ox + new_w] = resized
    return canvas


def _count_holes(image: np.ndarray, min_area: float = 0.0) -> int:
    """Đếm số lỗ (vùng nền kín) bên trong ký tự.

    Lỗ nhỏ do nhiễu nhị phân được bỏ qua bằng ngưỡng diện tích. Trên canvas
    32x48, lỗ thật của ký tự thường có diện tích trên 30 px, trong khi đốm
    nhiễu chỉ vài px.
    """
    binary = (image > 0).astype(np.uint8)
    contours, hierarchy = cv2.findContours(
        binary, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE
    )
    if hierarchy is None:
        return 0
    count = 0
    for index, item in enumerate(hierarchy[0]):
        if int(item[3]) == -1:
            continue
        if cv2.contourArea(contours[index]) >= float(min_area):
            count += 1
    return count


# ----------------------------------------------------------------------
# Bộ template
# ----------------------------------------------------------------------
@dataclass
class TemplateLibrary:
    templates: Dict[str, List[np.ndarray]] = field(default_factory=dict)
    coarse_templates: Dict[str, List[np.ndarray]] = field(default_factory=dict)
    labels: List[str] = field(default_factory=list)
    template_count: int = 0
    raw_template_count: int = 0
    missing_labels: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    load_time_ms: float = 0.0
    root: str = ""
    # Số lỗ phổ biến nhất của từng nhãn, dùng làm prior topology.
    hole_counts: Dict[str, int] = field(default_factory=dict)

    def has(self, label: str) -> bool:
        return label.upper() in self.templates

    def stats(self) -> Dict[str, object]:
        return {
            "labels": len(self.labels),
            "templates": self.template_count,
            "coarse_templates": sum(
                len(v) for v in self.coarse_templates.values()
            ),
            "raw_templates": self.raw_template_count,
            "missing_labels": list(self.missing_labels),
            "hole_counts": dict(self.hole_counts),
            "warnings": list(self.warnings),
            "load_time_ms": round(self.load_time_ms, 3),
        }


EXPECTED_LABELS = list("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ")


def _select_diverse_templates(
    images: List[np.ndarray], max_keep: int = 12, min_diff_ratio: float = 0.02
) -> List[np.ndarray]:
    """Giữ các template đủ khác nhau để giảm thời gian và tăng độ phân biệt.

    Nhiều font/variant cho ra ảnh gần như trùng nhau sau chuẩn hóa. Loại bớt
    các ảnh trùng lặp là bước chuẩn bị dữ liệu, không phải học máy.
    """
    if not images:
        return []
    kept: List[np.ndarray] = [images[0]]
    for image in images[1:]:
        if len(kept) >= max_keep:
            break
        is_new = True
        for existing in kept:
            if image.shape != existing.shape:
                diff_ratio = 1.0
            else:
                diff_ratio = float(
                    np.count_nonzero(image != existing) / image.size
                )
            if diff_ratio < min_diff_ratio:
                is_new = False
                break
        if is_new:
            kept.append(image)
    return kept


def _open_top_four_variants(
    templates: Sequence[np.ndarray],
) -> List[np.ndarray]:
    """Sinh biến thể chữ 4 hở đỉnh từ các template hiện có.

    Một số font biển thật vẽ chữ 4 với nét dọc bên phải chỉ bắt đầu từ
    khoảng giữa chiều cao, tạo khoảng trống ở góc trên bên phải. Template
    font thông thường có nét dọc chạy suốt từ trên xuống nên dễ bị xếp sau
    L/A/C. Biến thể này xóa vùng trên bên phải của ink box, giữ nguyên nét
    chéo và chân chữ.
    """
    variants: List[np.ndarray] = []
    for template in templates:
        variant = template.copy()
        h, w = variant.shape[:2]
        variant[: int(0.50 * h), int(0.50 * w) :] = 0
        variants.append(variant)
    return variants


def load_templates(
    templates_dir: str | Path | None,
    config: Config,
) -> TemplateLibrary:
    """Nạp toàn bộ template từ cấu trúc ``templates/<nhãn>/*.png``."""
    t0 = time.perf_counter()
    if templates_dir is None:
        root = config.templates_dir
    else:
        root = Path(templates_dir)
        if not root.is_absolute():
            root = config.project_root / root
    rc = config.recognition
    library = TemplateLibrary(root=str(root))
    if not root.exists() or not root.is_dir():
        raise TemplateError(f"Không tìm thấy thư mục template: {root}")

    extensions = {e.lower() for e in rc.template_extensions}
    for label_dir in sorted([p for p in root.iterdir() if p.is_dir()]):
        label = label_dir.name.upper()
        if len(label) != 1 or not label.isalnum():
            library.warnings.append(f"Bỏ qua thư mục nhãn không hợp lệ: {label_dir.name}")
            continue
        normalized: List[np.ndarray] = []
        for file in sorted(label_dir.iterdir()):
            if not file.is_file() or file.suffix.lower() not in extensions:
                continue
            try:
                image = read_image(file)
                norm = normalize_character(
                    image,
                    width=rc.normalized_width,
                    height=rc.normalized_height,
                    padding=rc.padding,
                    upscale=rc.upscale_templates,
                    mode=rc.normalize_mode,
                )
                normalized.append(norm)
            except (ImageIOError, EmptyCharacterError) as exc:
                library.warnings.append(f"Bỏ qua template lỗi {file.name}: {exc}")
        if normalized:
            selected = _select_diverse_templates(
                normalized,
                max_keep=rc.max_templates_per_label,
                min_diff_ratio=rc.template_min_diff_ratio,
            )
            # Coarse templates giữ bộ gốc để không làm chậm tầng lọc nhanh.
            library.coarse_templates[label] = _select_diverse_templates(
                selected,
                max_keep=rc.coarse_templates_per_label,
                min_diff_ratio=0.02,
            )
            holes = [_count_holes(item, rc.hole_min_area) for item in selected]
            if holes:
                library.hole_counts[label] = Counter(holes).most_common(1)[0][0]
            if label == "4" and rc.open_top_four_variant:
                selected = selected + _open_top_four_variants(selected)
            library.templates[label] = selected
            library.template_count += len(selected)
            library.raw_template_count += len(normalized)
        else:
            library.warnings.append(f"Nhãn {label} không có template hợp lệ.")

    library.labels = sorted(library.templates.keys())
    library.missing_labels = [
        label for label in EXPECTED_LABELS if label not in library.templates
    ]
    if not library.templates:
        raise TemplateError(
            f"Bộ template rỗng tại {root}. Hãy chạy tools/build_templates.py "
            "hoặc thêm ảnh mẫu vào từng thư mục nhãn."
        )
    if rc.require_all_labels and library.missing_labels:
        raise TemplateError(
            "Thiếu template cho các nhãn: " + ", ".join(library.missing_labels)
        )
    library.load_time_ms = (time.perf_counter() - t0) * 1000.0
    return library


# ----------------------------------------------------------------------
# So khớp
# ----------------------------------------------------------------------
def _similarity(
    query: np.ndarray, template: np.ndarray, method: str, blur_sigma: float = 0.0
) -> float:
    """Điểm tương đồng giữa hai ảnh cùng kích thước.

    Với ảnh nhị phân, làm mờ nhẹ trước khi tương quan giúp giảm ảnh hưởng của
    độ dày nét và sai lệch căn chỉnh nhỏ giữa các font.
    """
    if query.shape[:2] != template.shape[:2]:
        template = cv2.resize(
            template,
            (query.shape[1], query.shape[0]),
            interpolation=cv2.INTER_AREA,
        )
    method = (method or "TM_CCOEFF_NORMED").upper()

    def _prep(img: np.ndarray) -> np.ndarray:
        if blur_sigma and blur_sigma > 0:
            return cv2.GaussianBlur(img.astype(np.float32), (0, 0), blur_sigma)
        return img.astype(np.float32)

    if method in {"PIXEL", "MISMATCH"}:
        diff = np.count_nonzero(query != template)
        return float(1.0 - diff / float(max(1, query.size)))
    if method == "HYBRID":
        qf, tf = _prep(query), _prep(template)
        ccoeff = float(cv2.matchTemplate(qf, tf, cv2.TM_CCOEFF_NORMED)[0, 0])
        ccoeff01 = max(0.0, min(1.0, (ccoeff + 1.0) / 2.0))
        pixel = 1.0 - np.count_nonzero(query != template) / float(
            max(1, query.size)
        )
        return float(0.5 * ccoeff01 + 0.5 * pixel)
    if method == "TM_SQDIFF_NORMED":
        qf, tf = _prep(query), _prep(template)
        value = float(cv2.matchTemplate(qf, tf, cv2.TM_SQDIFF_NORMED)[0, 0])
        return float(max(0.0, min(1.0, 1.0 - value)))
    # Mặc định: normalized correlation
    qf, tf = _prep(query), _prep(template)
    value = float(cv2.matchTemplate(qf, tf, cv2.TM_CCOEFF_NORMED)[0, 0])
    if not np.isfinite(value):
        return 0.0
    return float(max(-1.0, min(1.0, value)))


@dataclass
class CharacterPrediction:
    label: str  # nhãn được khẳng định, "?" nếu UNKNOWN/AMBIGUOUS
    status: str  # OK | UNKNOWN | AMBIGUOUS | EMPTY
    score: float
    margin: float
    best_label: str
    second_label: str
    second_score: float
    ranked: List[Tuple[str, float]] = field(default_factory=list)
    normalized_image: Optional[np.ndarray] = None
    method: str = ""
    message: str = ""

    @property
    def is_confident(self) -> bool:
        return self.status == "OK"

    def as_dict(self) -> Dict[str, object]:
        return {
            "label": self.label,
            "status": self.status,
            "score": round(self.score, 4),
            "margin": round(self.margin, 4),
            "best_label": self.best_label,
            "second_label": self.second_label,
            "second_score": round(self.second_score, 4),
            "ranked": [(lbl, round(s, 4)) for lbl, s in self.ranked[:5]],
            "method": self.method,
            "message": self.message,
        }


def _score_by_label(
    query: np.ndarray,
    library: TemplateLibrary,
    method: str,
    blur_sigma: float = 0.0,
    excluded: Sequence[str] = (),
) -> List[Tuple[str, float]]:
    excluded_set = {label.upper() for label in excluded}
    scores: List[Tuple[str, float]] = []
    for label in library.labels:
        if label in excluded_set:
            continue
        best = -1e9
        for template in library.templates[label]:
            s = _similarity(query, template, method, blur_sigma)
            if s > best:
                best = s
        scores.append((label, float(best)))
    scores.sort(key=lambda x: x[1], reverse=True)
    return scores


def _score_by_label_two_stage(
    query: np.ndarray,
    library: TemplateLibrary,
    method: str,
    blur_sigma: float = 0.0,
    excluded: Sequence[str] = (),
    top_labels: int = 6,
) -> List[Tuple[str, float]]:
    """Chấm điểm hai tầng: coarse toàn bộ nhãn, fine cho các nhãn dẫn đầu.

    Tầng coarse dùng ít template/nhãn để lọc nhanh. Tầng fine dùng toàn bộ
    template của các nhãn có khả năng cao, nhờ đó vẫn đạt độ chính xác của bộ
    template đầy đủ mà giảm số phép so khớp.
    """
    excluded_set = {label.upper() for label in excluded}
    labels = [l for l in library.labels if l not in excluded_set]
    coarse_scores: Dict[str, float] = {}
    for label in labels:
        pool = library.coarse_templates.get(label) or library.templates[label]
        best = -1e9
        for template in pool:
            s = _similarity(query, template, method, blur_sigma)
            if s > best:
                best = s
        coarse_scores[label] = float(best)
    top = sorted(coarse_scores, key=lambda l: coarse_scores[l], reverse=True)[
        : max(1, int(top_labels))
    ]
    top_set = set(top)
    scores: List[Tuple[str, float]] = []
    for label in labels:
        if label in top_set:
            best = -1e9
            for template in library.templates[label]:
                s = _similarity(query, template, method, blur_sigma)
                if s > best:
                    best = s
            best = max(best, coarse_scores[label])
        else:
            best = coarse_scores[label]
        scores.append((label, float(best)))
    scores.sort(key=lambda x: x[1], reverse=True)
    return scores


def recognize_character(
    character_image: np.ndarray,
    library: TemplateLibrary,
    config: Config,
) -> CharacterPrediction:
    """Nhận dạng một ký tự, có cơ chế từ chối UNKNOWN/AMBIGUOUS."""
    rc = config.recognition
    method = rc.method
    t0 = time.perf_counter()
    if character_image is None or character_image.size == 0:
        return CharacterPrediction(
            label="?",
            status="EMPTY",
            score=0.0,
            margin=0.0,
            best_label="?",
            second_label="?",
            second_score=0.0,
            method=method,
            message="Ảnh ký tự rỗng.",
        )
    try:
        query = normalize_character(
            character_image,
            width=rc.normalized_width,
            height=rc.normalized_height,
            padding=rc.padding,
            upscale=rc.upscale_templates,
            mode=rc.normalize_mode,
        )
    except EmptyCharacterError as exc:
        return CharacterPrediction(
            label="?",
            status="EMPTY",
            score=0.0,
            margin=0.0,
            best_label="?",
            second_label="?",
            second_score=0.0,
            method=method,
            message=str(exc),
        )
    if not library.templates:
        return CharacterPrediction(
            label="?",
            status="UNKNOWN",
            score=0.0,
            margin=0.0,
            best_label="?",
            second_label="?",
            second_score=0.0,
            normalized_image=query,
            method=method,
            message="Bộ template rỗng.",
        )
    ranked = _score_by_label_two_stage(
        query,
        library,
        method,
        blur_sigma=rc.match_blur_sigma,
        excluded=rc.excluded_labels,
        top_labels=rc.coarse_top_labels,
    )
    if not ranked:
        return CharacterPrediction(
            label="?",
            status="UNKNOWN",
            score=0.0,
            margin=0.0,
            best_label="?",
            second_label="?",
            second_score=0.0,
            normalized_image=query,
            method=method,
            message="Không còn nhãn hợp lệ sau khi loại trừ.",
        )
    hole_penalized = False
    if rc.hole_prior and library.hole_counts:
        query_holes = _count_holes(query, rc.hole_min_area)
        adjusted: List[Tuple[str, float]] = []
        for label, score in ranked:
            expected_holes = library.hole_counts.get(label)
            if expected_holes is not None and query_holes != expected_holes:
                # Mất lỗ có thể do nhị phân làm đứt nét mảnh, nên khi query
                # không có lỗ mà template chỉ có 1 lỗ thì không trừ điểm.
                # Ngược lại, lỗ thừa hoặc thiếu so với ký tự 2 lỗ vẫn là
                # bằng chứng đủ mạnh để hạ ứng viên.
                if not (query_holes == 0 and expected_holes == 1):
                    score -= rc.hole_penalty
                    hole_penalized = True
            adjusted.append((label, float(score)))
        adjusted.sort(key=lambda item: item[1], reverse=True)
        ranked = adjusted
    best_label, best_score = ranked[0]
    second_label, second_score = ranked[1] if len(ranked) > 1 else ("?", -1.0)
    margin = float(best_score - second_score)
    if best_score < rc.score_threshold:
        status = "UNKNOWN"
        label = "?"
        message = (
            f"Điểm cao nhất {best_score:.3f} < ngưỡng {rc.score_threshold:.3f}"
        )
    elif margin < rc.min_margin:
        status = "AMBIGUOUS"
        label = "?"
        message = (
            f"Khoảng cách top-1/top-2 {margin:.3f} < {rc.min_margin:.3f} "
            f"({best_label} vs {second_label})"
        )
    else:
        status = "OK"
        label = best_label
        message = "Đạt ngưỡng điểm và margin."
        if hole_penalized:
            message += " Có áp dụng prior số lỗ."
    return CharacterPrediction(
        label=label,
        status=status,
        score=float(best_score),
        margin=margin,
        best_label=best_label,
        second_label=second_label,
        second_score=float(second_score),
        ranked=ranked,
        normalized_image=query,
        method=method,
        message=message,
    )


def recognize_characters(
    character_images: Sequence[np.ndarray],
    library: TemplateLibrary,
    config: Config,
) -> Tuple[List[CharacterPrediction], Dict[str, float]]:
    """Nhận dạng danh sách ký tự, trả kèm thời gian."""
    t0 = time.perf_counter()
    predictions = [
        recognize_character(ch, library, config) for ch in character_images
    ]
    elapsed = (time.perf_counter() - t0) * 1000.0
    return predictions, {"recognition_total_ms": elapsed}

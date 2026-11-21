"""Phát hiện vùng biển số bằng morphology, contour và đặc trưng hình học.

Pipeline của module:
    ảnh cạnh Canny -> morphological closing (nhiều kernel) -> findContours
    -> lọc diện tích / tỷ lệ / mật độ cạnh / độ kín -> chấm điểm -> xếp hạng.

Không sử dụng mô hình học máy. Điểm "giống vùng chữ" (text-likeness) là một
phần mở rộng có trọng số nhỏ, có thể đặt bằng 0 trong config.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from .config import Config, DetectionConfig
from .io_utils import bbox_iou, bbox_to_int, is_convex_quad
from .preprocessing import PreprocessResult, ensure_odd


@dataclass
class PlateCandidate:
    bbox: Tuple[float, float, float, float]  # tọa độ trên ảnh work
    bbox_original: Tuple[float, float, float, float]
    area: float
    area_ratio: float
    ratio: float
    edge_density: float
    fill_ratio: float
    text_likeness: float
    score: float
    score_components: Dict[str, float]
    source: str
    passed: bool = True
    # Hộp hình học bao trọn ứng viên cụm chữ, dùng để báo cáo vị trí biển.
    # Vùng cắt dùng cho phân đoạn/nhận dạng vẫn là ``bbox`` của ứng viên này.
    bbox_hint: Optional[Tuple[float, float, float, float]] = None
    bbox_hint_original: Optional[Tuple[float, float, float, float]] = None

    @property
    def width(self) -> float:
        return self.bbox[2] - self.bbox[0]

    @property
    def height(self) -> float:
        return self.bbox[3] - self.bbox[1]

    def as_dict(self) -> Dict[str, float | str | bool | None | List[float]]:
        return {
            "bbox": [round(v, 2) for v in self.bbox],
            "bbox_original": [round(v, 2) for v in self.bbox_original],
            "bbox_hint": [round(v, 2) for v in self.bbox_hint]
            if self.bbox_hint is not None
            else None,
            "bbox_hint_original": [round(v, 2) for v in self.bbox_hint_original]
            if self.bbox_hint_original is not None
            else None,
            "area": round(self.area, 2),
            "area_ratio": round(self.area_ratio, 6),
            "ratio": round(self.ratio, 4),
            "edge_density": round(self.edge_density, 4),
            "fill_ratio": round(self.fill_ratio, 4),
            "text_likeness": round(self.text_likeness, 4),
            "score": round(self.score, 4),
            "source": self.source,
            "passed": self.passed,
        }


@dataclass
class DetectionResult:
    candidates: List[PlateCandidate] = field(default_factory=list)
    all_candidates: List[PlateCandidate] = field(default_factory=list)
    closed: Optional[np.ndarray] = None
    maps: Dict[str, np.ndarray] = field(default_factory=dict)
    timings_ms: Dict[str, float] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)


# ----------------------------------------------------------------------
# Các hàm điểm thành phần
# ----------------------------------------------------------------------
def ratio_score(ratio: float, targets: Sequence[float], tolerance: float) -> float:
    """Điểm tỷ lệ: lấy max của các hàm Gauss quanh tỷ lệ mục tiêu."""
    if not targets:
        return 0.0
    tau = max(1e-6, float(tolerance))
    return float(max(math.exp(-abs(ratio - t) / tau) for t in targets))


def area_score(area_ratio: float, ideal: float, sigma: float) -> float:
    if area_ratio <= 0 or ideal <= 0:
        return 0.0
    z = math.log(area_ratio / ideal) / max(1e-6, sigma)
    return float(math.exp(-0.5 * z * z))


def edge_density_score(density: float, low: float, ideal: float, high: float) -> float:
    """Hàm hình thang: thấp -> tăng -> 1 -> giảm về 0."""
    if density <= 0:
        return 0.0
    if density < low:
        return float(max(0.0, density / max(1e-6, low)))
    if density < ideal:
        return float(
            0.5 + 0.5 * (density - low) / max(1e-6, ideal - low)
        )
    if density <= high:
        return 1.0
    return float(max(0.0, 1.0 - (density - high) / max(1e-6, high)))


def fill_score(fill: float, minimum: float) -> float:
    if fill <= minimum:
        return 0.0
    return float(min(1.0, (fill - minimum) / max(1e-6, 1.0 - minimum)))


def _remove_border_components(binary: np.ndarray, margin: int = 1) -> np.ndarray:
    """Xóa các thành phần là viền biển, khung ảnh hoặc đường kẻ dài.

    Quan trọng: phải xét thành phần trên ảnh gốc *trước* khi xóa margin, vì
    viền biển kín thường không chạm biên sau khi đã cắt margin và sẽ che toàn
    bộ ký tự bên trong nếu dùng ``RETR_EXTERNAL``.
    """
    h, w = binary.shape
    num, labels, stats, _ = cv2.connectedComponentsWithStats(
        binary, connectivity=8
    )
    out = np.zeros_like(binary)
    for idx in range(1, num):
        x, y, ww, hh, area = stats[idx]
        if area < 3:
            continue
        touches = x <= 1 or y <= 1 or x + ww >= w - 1 or y + hh >= h - 1
        # Khung/biển kín: hộp lớn theo cả hai chiều (kể cả không chạm biên)
        if ww >= 0.60 * w and hh >= 0.60 * h:
            continue
        # Đường kẻ dài, mảnh, chạm biên
        if touches and ww >= 0.75 * w and hh <= 0.16 * h:
            continue
        if touches and hh >= 0.75 * h and ww <= 0.16 * w:
            continue
        if touches and (ww >= 0.85 * w or hh >= 0.85 * h):
            continue
        out[labels == idx] = 255
    if margin > 0:
        out[:margin, :] = 0
        out[-margin:, :] = 0
        out[:, :margin] = 0
        out[:, -margin:] = 0
    return out


def _count_character_like(binary: np.ndarray) -> int:
    """Đếm ký tự ứng viên có bố cục dòng hợp lý.

    Chỉ đếm các thành phần cùng nằm trên một dòng có ít nhất 3 ký tự, chiều
    cao tương đồng và khoảng cách ngang hợp lý. Cách này loại được nhiễu JPEG
    trong các vùng sáng đồng nhất (đèn xe, nền trời) vốn có thể tạo ra nhiều
    mảnh nhỏ nhưng không xếp thành dòng chữ.
    """
    binary = _remove_border_components(binary, margin=2)
    if binary.size == 0:
        return 0
    ink_fraction = float(np.count_nonzero(binary)) / float(binary.size)
    if ink_fraction < 0.02 or ink_fraction > 0.45:
        return 0
    binary = cv2.morphologyEx(
        binary, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8), iterations=1
    )
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    rh, rw = binary.shape[:2]
    boxes: List[Tuple[int, int, int, int]] = []
    for c in contours:
        x, y, ww, hh = cv2.boundingRect(c)
        if hh < 0.10 * rh or hh > 0.95 * rh:
            continue
        if ww < 0.008 * rw or ww > 0.40 * rw:
            continue
        if ww * hh < 0.00025 * rw * rh:
            continue
        fill = cv2.contourArea(c) / max(1.0, ww * hh)
        if fill < 0.06:
            continue
        boxes.append((x, y, ww, hh))
    if len(boxes) < 3:
        return 0

    # Loại các hộp có chiều cao lệch xa trung vị (nhiễu, mảnh vụn)
    heights = np.array([b[3] for b in boxes], dtype=np.float32)
    median_h = float(np.median(heights))
    if median_h <= 0:
        return 0
    boxes = [
        b
        for b in boxes
        if 0.60 * median_h <= b[3] <= 1.55 * median_h
    ]
    if len(boxes) < 3:
        return 0

    # Gom thành dòng theo tâm dọc
    boxes.sort(key=lambda b: b[1] + b[3] / 2.0)
    rows: List[List[Tuple[int, int, int, int]]] = []
    for box in boxes:
        cy = box[1] + box[3] / 2.0
        placed = False
        for row in rows:
            row_cy = float(
                np.mean([b[1] + b[3] / 2.0 for b in row])
            )
            if abs(cy - row_cy) <= 0.45 * median_h:
                row.append(box)
                placed = True
                break
        if not placed:
            rows.append([box])

    total = 0
    for row in rows:
        if len(row) < 3:
            continue
        row.sort(key=lambda b: b[0])
        widths = np.array([b[2] for b in row], dtype=np.float32)
        median_w = float(np.median(widths))
        if median_w <= 0:
            continue
        gaps = [
            row[i + 1][0] - (row[i][0] + row[i][2])
            for i in range(len(row) - 1)
        ]
        span = (row[-1][0] + row[-1][2]) - row[0][0]
        # Dòng chữ thật phải trải rộng và khoảng cách không quá lớn. Dấu gạch
        # ngang trên biển tạo một khoảng hở lớn hơn bình thường nên ngưỡng
        # được nới theo chiều rộng trung vị thay vì theo trung vị khoảng hở.
        if span < 3.0 * median_w:
            continue
        if gaps and max(gaps) > max(2.0 * float(np.median(gaps)), 1.5 * median_w):
            continue
        total += len(row)
    return total


def character_like_count(gray_roi: np.ndarray) -> int:
    """Đếm số thành phần có hình dáng giống ký tự trong ROI.

    Thử cả hai cực tính (nền sáng/chữ tối và nền tối/chữ sáng) rồi lấy kết quả
    cao hơn, vì ảnh biển số có thể là biển trắng hoặc biển vàng, thậm chí ảnh
    bị đảo màu. Đây là đặc trưng hỗ trợ xếp hạng, không phải nhận dạng.
    """
    if gray_roi is None or gray_roi.size == 0:
        return 0
    h, w = gray_roi.shape[:2]
    if h < 12 or w < 20:
        return 0
    target_w = 300
    scale = target_w / float(w)
    roi = cv2.resize(
        gray_roi,
        (target_w, max(1, int(round(h * scale)))),
        interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC,
    )
    roi = cv2.GaussianBlur(roi, (3, 3), 0)
    _, raw = cv2.threshold(roi, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    best = 0
    for invert in (False, True):
        binary = cv2.bitwise_not(raw) if invert else raw
        best = max(best, _count_character_like(binary))
    return best


def text_likeness_score(count: int, expected_min: int = 7) -> float:
    """Chuyển số thành phần giống ký tự thành điểm [0, 1]."""
    if count < 3:
        return 0.0
    if count < expected_min:
        return float((count - 2) / max(1, expected_min - 2))
    if count <= 14:
        return 1.0
    return float(max(0.0, 1.0 - (count - 14) / 14.0))


# ----------------------------------------------------------------------
# Ứng viên từ cụm chữ
# ----------------------------------------------------------------------
def _text_components(
    binary: np.ndarray,
) -> List[Tuple[int, int, int, int, int]]:
    """Lấy các thành phần giống ký tự, bỏ viền và đường kẻ dài."""
    h, w = binary.shape[:2]
    num, _, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    components: List[Tuple[int, int, int, int, int]] = []
    min_area = max(3, int(0.00004 * h * w))
    for idx in range(1, num):
        x, y, ww, hh, area = (int(v) for v in stats[idx])
        if area < min_area:
            continue
        if hh < max(2, int(0.025 * h)) or hh > 0.72 * h:
            continue
        if ww < max(1, int(0.003 * w)) or ww > 0.42 * w:
            continue
        aspect = ww / max(1, hh)
        if aspect < 0.07 or aspect > 3.5:
            continue
        if area / max(1.0, ww * hh) < 0.10:
            continue
        if ww > 0.50 * w and hh < 0.06 * h:
            continue
        if hh > 0.50 * h and ww < 0.03 * w:
            continue
        components.append((x, y, ww, hh, area))
    return components


def _weighted_median_height(
    components: Sequence[Tuple[int, int, int, int, int]],
) -> float:
    if not components:
        return 0.0
    ordered = sorted(components, key=lambda c: c[3])
    total = sum(max(0, c[4]) for c in ordered)
    if total <= 0:
        return float(np.median([c[3] for c in ordered]))
    accumulated = 0
    for component in ordered:
        accumulated += max(0, component[4])
        if accumulated >= 0.5 * total:
            return float(component[3])
    return float(ordered[-1][3])


def _trim_text_runs(
    boxes: Sequence[Tuple[int, int, int, int]], width: int
) -> List[List[Tuple[int, int, int, int]]]:
    """Gộp mảnh chồng lấn rồi cắt thành các cụm cách xa nhau."""
    if not boxes:
        return []
    ordered = sorted(boxes, key=lambda b: b[0])
    merged: List[Tuple[int, int, int, int]] = []
    for box in ordered:
        x, y, w, h = box
        if merged:
            px, py, pw, ph = merged[-1]
            vertical_overlap = min(py + ph, y + h) - max(py, y)
            gap = x - (px + pw)
            if vertical_overlap > 0.5 * min(ph, h) and gap <= 2:
                nx1, ny1 = min(px, x), min(py, y)
                nx2, ny2 = max(px + pw, x + w), max(py + ph, y + h)
                merged[-1] = (nx1, ny1, nx2 - nx1, ny2 - ny1)
                continue
        merged.append((x, y, w, h))
    if not merged:
        return []
    median_w = float(np.median([b[2] for b in merged]))
    max_gap = max(2.0 * median_w, 0.035 * width)
    runs: List[List[Tuple[int, int, int, int]]] = [[merged[0]]]
    for box in merged[1:]:
        previous = runs[-1][-1]
        gap = box[0] - (previous[0] + previous[2])
        if gap <= max_gap:
            runs[-1].append(box)
        else:
            runs.append([box])
    return runs


def _text_rows(binary: np.ndarray) -> List[Tuple[int, int, int, int, int]]:
    """Trả về các cụm chữ theo dòng: (x1, y1, x2, y2, số thành phần)."""
    h, w = binary.shape[:2]
    if h < 12 or w < 20:
        return []
    components = _text_components(binary)
    if len(components) < 3:
        return []
    median_h = _weighted_median_height(components)
    if median_h <= 0:
        return []
    components = [
        c for c in components if 0.45 * median_h <= c[3] <= 1.9 * median_h
    ]
    if len(components) < 3:
        return []

    median_h = float(np.median([c[3] for c in components]))
    components.sort(key=lambda c: c[1] + c[3] / 2.0)
    groups: List[List[Tuple[int, int, int, int, int]]] = []
    for component in components:
        cy = component[1] + component[3] / 2.0
        placed = False
        for group in groups:
            row_cy = float(np.mean([c[1] + c[3] / 2.0 for c in group]))
            row_h = float(np.median([c[3] for c in group]))
            if (
                abs(cy - row_cy) <= 0.48 * max(median_h, row_h)
                and 0.60 <= component[3] / max(1.0, row_h) <= 1.70
            ):
                group.append(component)
                placed = True
                break
        if not placed:
            groups.append([component])

    rows: List[Tuple[int, int, int, int, int]] = []
    for group in groups:
        if len(group) < 3:
            continue
        boxes = [(c[0], c[1], c[2], c[3]) for c in group]
        for run in _trim_text_runs(boxes, w):
            if len(run) < 3:
                continue
            x1 = min(b[0] for b in run)
            y1 = min(b[1] for b in run)
            x2 = max(b[0] + b[2] for b in run)
            y2 = max(b[1] + b[3] for b in run)
            median_w = float(np.median([b[2] for b in run]))
            if median_w <= 0 or (x2 - x1) < 1.8 * median_w:
                continue
            rows.append((int(x1), int(y1), int(x2), int(y2), len(run)))
    return rows


def _text_cluster_boxes(
    pre: PreprocessResult, config: Config
) -> List[Tuple[str, str, Tuple[int, int, int, int], int]]:
    """Sinh hộp ứng viên từ cụm ký tự ở nhiều ngưỡng khác nhau."""
    dc = config.detection
    gray = pre.enhanced
    if gray is None or gray.size == 0:
        return []
    h, w = gray.shape[:2]
    binary_variants: List[Tuple[str, np.ndarray]] = []
    _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    binary_variants.append(("otsu", otsu))
    for block in (21, 31, 41, 51):
        if block >= min(h, w):
            continue
        adaptive = cv2.adaptiveThreshold(
            gray,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            block,
            5,
        )
        binary_variants.append((f"ad{block}", adaptive))

    raw_boxes: List[Tuple[str, str, Tuple[int, int, int, int], int]] = []
    for name, base in binary_variants:
        for invert in (False, True):
            binary = cv2.bitwise_not(base) if invert else base.copy()
            binary = _remove_border_components(binary, margin=1)
            rows = _text_rows(binary)
            for index, (x1, y1, x2, y2, count) in enumerate(rows):
                row_h = y2 - y1
                pad_x = int(0.25 * row_h)
                pad_y = int(0.18 * row_h)
                box = (
                    max(0, x1 - pad_x),
                    max(0, y1 - pad_y),
                    min(w, x2 + pad_x),
                    min(h, y2 + pad_y),
                )
                raw_boxes.append((name, "row", box, count))
                for other in rows[index + 1 :]:
                    ox1, oy1, ox2, oy2, ocount = other
                    overlap = min(x2, ox2) - max(x1, ox1)
                    min_width = min(x2 - x1, ox2 - ox1)
                    if min_width <= 0 or overlap / float(min_width) < 0.35:
                        continue
                    gap = max(y1, oy1) - min(y2, oy2)
                    max_h = max(row_h, oy2 - oy1)
                    if gap < 0 or gap > 0.90 * max_h:
                        continue
                    ux1, uy1 = min(x1, ox1), min(y1, oy1)
                    ux2, uy2 = max(x2, ox2), max(y2, oy2)
                    union_h = uy2 - uy1
                    pad_x = int(0.20 * union_h)
                    pad_y = int(0.10 * union_h)
                    box = (
                        max(0, ux1 - pad_x),
                        max(0, uy1 - pad_y),
                        min(w, ux2 + pad_x),
                        min(h, uy2 + pad_y),
                    )
                    raw_boxes.append((name, "pair", box, count + ocount))

    if not raw_boxes:
        return []
    # Loại hộp trùng nhau, ưu tiên hộp lớn (thường là cả biển hai dòng).
    raw_boxes.sort(
        key=lambda item: (item[2][2] - item[2][0]) * (item[2][3] - item[2][1]),
        reverse=True,
    )
    kept: List[Tuple[str, str, Tuple[int, int, int, int], int]] = []
    for item in raw_boxes:
        x1, y1, x2, y2 = item[2]
        duplicate = False
        for existing in kept:
            ex1, ey1, ex2, ey2 = existing[2]
            inter = max(0, min(x2, ex2) - max(x1, ex1)) * max(
                0, min(y2, ey2) - max(y1, ey1)
            )
            union = (x2 - x1) * (y2 - y1) + (ex2 - ex1) * (ey2 - ey1) - inter
            if union > 0 and inter / union > 0.55:
                duplicate = True
                break
        if not duplicate:
            kept.append(item)
    return kept


def _text_cluster_candidates(
    pre: PreprocessResult, config: Config
) -> List[PlateCandidate]:
    """Tạo ứng viên biển từ các cụm ký tự đã được nhóm theo dòng."""
    dc = config.detection
    candidates: List[PlateCandidate] = []
    for name, kind, (x1, y1, x2, y2), count in _text_cluster_boxes(pre, config):
        if count < (5 if kind == "row" else 7):
            continue
        w, h = x2 - x1, y2 - y1
        if w < 8 or h < 4:
            continue
        rect = np.array(
            [[x1, y1], [x2, y1], [x2, y2], [x1, y2]], dtype=np.int32
        ).reshape(-1, 1, 2)
        candidate = _candidate_from_rect(
            rect,
            (x1, y1, w, h),
            pre,
            config,
            source=f"text_{kind}_{name}",
            gray_for_text=pre.gray,
        )
        if candidate is None:
            continue
        # Cụm chữ chỉ là gợi ý vị trí; vẫn phải có bằng chứng chữ đủ mạnh
        # để tránh biến nền/đèn xe thành biển số.
        if not candidate.passed or candidate.text_likeness < 0.5:
            continue
        candidates.append(candidate)
    return candidates


def _attach_text_bbox_hints(
    text_candidates: List[PlateCandidate],
    geometric_candidates: List[PlateCandidate],
    config: Config,
) -> List[PlateCandidate]:
    """Gắn hộp hình học bao trọn cho ứng viên cụm chữ.

    Cụm chữ cho vùng cắt sát ký tự nên nhận dạng tốt, nhưng hộp báo cáo
    thường nhỏ hơn biển thật. Nếu một ứng viên hình học đã vượt ngưỡng bao
    trọn cụm chữ, hộp hình học là ước lượng vị trí biển tốt hơn. Hàm chỉ
    gắn metadata; vùng cắt dùng cho OCR không thay đổi.
    """
    dc = config.detection
    if not dc.text_bbox_hint or not text_candidates:
        return text_candidates
    eligible = [
        candidate
        for candidate in geometric_candidates
        if not candidate.source.startswith("text_")
        and candidate.passed
        and candidate.score >= dc.text_bbox_hint_min_score
    ]
    if not eligible:
        return text_candidates
    for candidate in text_candidates:
        if candidate.text_likeness < 0.5:
            continue
        tx1, ty1, tx2, ty2 = candidate.bbox
        text_area = max(1.0, (tx2 - tx1) * (ty2 - ty1))
        best: Optional[PlateCandidate] = None
        best_key: Optional[Tuple[float, float]] = None
        for geometric in eligible:
            gx1, gy1, gx2, gy2 = geometric.bbox
            inter_w = max(0.0, min(tx2, gx2) - max(tx1, gx1))
            inter_h = max(0.0, min(ty2, gy2) - max(ty1, gy1))
            containment = (inter_w * inter_h) / text_area
            if containment < dc.text_bbox_hint_min_containment:
                continue
            geometric_area = max(1.0, (gx2 - gx1) * (gy2 - gy1))
            if geometric_area / text_area > dc.text_bbox_hint_max_area_ratio:
                continue
            key = (containment, geometric.score)
            if best_key is None or key > best_key:
                best_key = key
                best = geometric
        if best is not None:
            candidate.bbox_hint = best.bbox
            candidate.bbox_hint_original = best.bbox_original
    return text_candidates


# ----------------------------------------------------------------------
# Sinh bản đồ morphology
# ----------------------------------------------------------------------
def _unique_kernels(kernels: Iterable[Sequence[int]]) -> List[Tuple[int, int]]:
    seen = set()
    result = []
    for k in kernels:
        key = (int(k[0]), int(k[1]))
        if key[0] <= 0 or key[1] <= 0 or key in seen:
            continue
        seen.add(key)
        result.append(key)
    return result


def build_morphology_maps(
    pre: PreprocessResult, config: Config
) -> Dict[str, np.ndarray]:
    """Tạo các ảnh nhị phân sau closing từ cạnh và từ ảnh ink."""
    dc = config.detection
    kernels = _unique_kernels([dc.close_kernel, *dc.extra_close_kernels])
    maps: Dict[str, np.ndarray] = {}

    for i, (kw, kh) in enumerate(kernels):
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kw, kh))
        closed = cv2.morphologyEx(
            pre.edges, cv2.MORPH_CLOSE, kernel, iterations=1
        )
        maps[f"edges_close_{kw}x{kh}"] = closed
        # Closing dọc thêm một lần giúp nối hai dòng của biển
        if kh < 9 and i == 0:
            vertical = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 7))
            maps["edges_close_vertical"] = cv2.morphologyEx(
                closed, cv2.MORPH_CLOSE, vertical, iterations=1
            )

    # Nguồn bổ sung: vùng mực (ký tự) sau threshold, phù hợp ảnh tương phản thấp.
    ink = cv2.bitwise_not(pre.binary_adaptive)
    ink = _remove_border_components(ink, margin=1)
    ink_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernels[0][0], 3))
    maps["ink_adaptive_close"] = cv2.morphologyEx(
        ink, cv2.MORPH_CLOSE, ink_kernel, iterations=1
    )

    # Nguồn bổ sung: vùng sáng (biển trắng/vàng) - rất hữu ích khi biển nằm
    # trên cản xe tối và bị nối với các cạnh ngang của thân xe.
    hsv = cv2.cvtColor(pre.work_image, cv2.COLOR_BGR2HSV)
    bright_white = cv2.inRange(hsv, (0, 0, 115), (180, 72, 255))
    bright_yellow = cv2.inRange(hsv, (12, 60, 90), (42, 255, 255))
    bright = cv2.bitwise_or(bright_white, bright_yellow)
    _, otsu_bright = cv2.threshold(
        pre.enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )
    # Chỉ bổ sung vùng Otsu nếu nó không chiếm gần như toàn ảnh
    if float(np.count_nonzero(otsu_bright)) < 0.75 * otsu_bright.size:
        bright = cv2.bitwise_or(bright, otsu_bright)
    bright = cv2.morphologyEx(
        bright,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (15, 5)),
        iterations=2,
    )
    bright = cv2.morphologyEx(
        bright,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)),
        iterations=1,
    )
    maps["bright_plate"] = bright

    # Nguồn bổ sung: top-hat làm nổi bật vùng sáng cục bộ (biển trên nền tối).
    tophat = cv2.morphologyEx(
        pre.enhanced,
        cv2.MORPH_TOPHAT,
        cv2.getStructuringElement(cv2.MORPH_RECT, (31, 17)),
    )
    _, tophat_binary = cv2.threshold(
        tophat, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )
    tophat_binary = cv2.morphologyEx(
        tophat_binary,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (9, 5)),
        iterations=1,
    )
    maps["tophat"] = tophat_binary

    # Bản đồ cạnh ít closing, dùng để tìm contour 4 đỉnh của viền biển.
    maps["edges_quads"] = cv2.morphologyEx(
        pre.edges,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)),
        iterations=1,
    )
    return maps


def _candidate_from_rect(
    contour: np.ndarray,
    bbox: Tuple[int, int, int, int],
    pre: PreprocessResult,
    config: Config,
    source: str,
    gray_for_text: np.ndarray,
) -> Optional[PlateCandidate]:
    dc = config.detection
    x, y, w, h = bbox
    if w <= 0 or h <= 0:
        return None
    img_h, img_w = pre.edges.shape[:2]
    area = float(w * h)
    area_ratio = area / float(img_w * img_h)
    if area_ratio < dc.min_area_ratio or area_ratio > dc.max_area_ratio:
        return None
    ratio = float(w) / float(h)
    if ratio < dc.min_ratio or ratio > dc.max_ratio:
        return None

    x2, y2 = min(img_w, x + w), min(img_h, y + h)
    x, y = max(0, x), max(0, y)
    if x2 <= x or y2 <= y:
        return None
    edge_roi = pre.edges[y:y2, x:x2]
    edge_density = float(np.count_nonzero(edge_roi)) / float(max(1, edge_roi.size))
    contour_area = float(cv2.contourArea(contour))
    fill = float(min(1.0, contour_area / max(1.0, area)))

    gray_roi = gray_for_text[y:y2, x:x2]
    n_chars = character_like_count(gray_roi)
    text_score = text_likeness_score(n_chars)

    wts = dc.weights.normalized()
    sr = ratio_score(ratio, dc.ratio_targets, dc.ratio_tolerance)
    sa = area_score(area_ratio, dc.ideal_area_ratio, dc.area_sigma)
    se = edge_density_score(
        edge_density, dc.edge_density_min, dc.edge_density_ideal, dc.edge_density_max
    )
    sq = fill_score(fill, dc.fill_ratio_min)
    spec_score = wts.ratio * sr + wts.area * sa + wts.edge * se + wts.fill * sq
    tw = float(np.clip(dc.text_likeness_weight, 0.0, 1.0))
    score = (1.0 - tw) * spec_score + tw * text_score
    text_ok = text_score >= dc.min_text_likeness
    passed = score >= dc.min_score and (
        text_ok or not dc.require_text_evidence
    )

    scale = pre.scale if pre.scale > 0 else 1.0
    bbox_orig = (x / scale, y / scale, x2 / scale, y2 / scale)
    return PlateCandidate(
        bbox=(float(x), float(y), float(x2), float(y2)),
        bbox_original=tuple(float(v) for v in bbox_orig),
        area=area,
        area_ratio=area_ratio,
        ratio=ratio,
        edge_density=edge_density,
        fill_ratio=fill,
        text_likeness=text_score,
        score=float(score),
        score_components={
            "ratio": sr,
            "area": sa,
            "edge": se,
            "fill": sq,
            "text": text_score,
            "spec_score": spec_score,
        },
        source=source,
        passed=bool(passed),
    )


def _deduplicate(
    candidates: List[PlateCandidate], merge_iou: float
) -> List[PlateCandidate]:
    """Gộp các ứng viên trùng nhau, giữ ứng viên điểm cao hơn."""
    if not candidates:
        return []

    def rank(c: PlateCandidate) -> Tuple[int, float]:
        # Ứng viên đã vượt ngưỡng phải được ưu tiên hơn ứng viên bị loại,
        # kể cả khi ứng viên bị loại có điểm thô cao hơn. Ngoài ra, khi hai
        # ứng viên gần như trùng nhau, hộp "đặc" hơn thường là chính biển số
        # thay vì cả cụm đèn/thân xe bao quanh nó.
        compactness_bonus = 0.10 * (float(c.fill_ratio) - 0.5)
        return (1 if c.passed else 0, float(c.score) + compactness_bonus)

    ordered = sorted(candidates, key=rank, reverse=True)
    kept: List[PlateCandidate] = []
    for cand in ordered:
        duplicate = False
        for existing in kept:
            inter = bbox_iou(cand.bbox, existing.bbox)
            if inter >= merge_iou:
                duplicate = True
                break
            # Trường hợp một box nằm gần như trọn trong box khác
            ax1, ay1, ax2, ay2 = cand.bbox
            bx1, by1, bx2, by2 = existing.bbox
            inter_area = max(0.0, min(ax2, bx2) - max(ax1, bx1)) * max(
                0.0, min(ay2, by2) - max(ay1, by1)
            )
            small_area = min(
                (ax2 - ax1) * (ay2 - ay1), (bx2 - bx1) * (by2 - by1)
            )
            if small_area > 0 and inter_area / small_area > 0.85:
                duplicate = True
                break
        if not duplicate:
            kept.append(cand)
    return kept


def _add_stacked_merges(
    candidates: List[PlateCandidate], pre: PreprocessResult, config: Config
) -> List[PlateCandidate]:
    """Gộp hai ứng viên xếp trên/dưới có khả năng là hai dòng của một biển."""
    dc = config.detection
    extra: List[PlateCandidate] = []
    n = len(candidates)
    for i in range(n):
        for j in range(i + 1, n):
            a, b = candidates[i], candidates[j]
            ax1, ay1, ax2, ay2 = a.bbox
            bx1, by1, bx2, by2 = b.bbox
            overlap = min(ax2, bx2) - max(ax1, bx1)
            min_w = min(ax2 - ax1, bx2 - bx1)
            if min_w <= 0 or overlap / min_w < 0.70:
                continue
            # Kiểm tra xếp chồng theo trục dọc, không chồng lấn nhiều
            vertical_overlap = min(ay2, by2) - max(ay1, by1)
            if vertical_overlap > 0.25 * min(ay2 - ay1, by2 - by1):
                continue
            gap = max(ay1, by1) - min(ay2, by2)
            max_h = max(ay2 - ay1, by2 - by1)
            if gap < 0 or gap > 0.60 * max_h:
                continue
            union = (
                min(ax1, bx1),
                min(ay1, by1),
                max(ax2, bx2),
                max(ay2, by2),
            )
            uw, uh = union[2] - union[0], union[3] - union[1]
            if uw <= 0 or uh <= 0:
                continue
            ratio = uw / uh
            if ratio < dc.min_ratio or ratio > dc.max_ratio:
                continue
            # Tạo contour chữ nhật để tái sử dụng hàm tính điểm
            rect = np.array(
                [
                    [union[0], union[1]],
                    [union[2], union[1]],
                    [union[2], union[3]],
                    [union[0], union[3]],
                ],
                dtype=np.int32,
            )
            merged = _candidate_from_rect(
                rect,
                (int(union[0]), int(union[1]), int(uw), int(uh)),
                pre,
                config,
                source="stacked_merge",
                gray_for_text=pre.gray,
            )
            if merged and merged.passed:
                # Chỉ thêm nếu vùng gộp thực sự có nhiều ký tự
                if merged.text_likeness >= 0.5:
                    extra.append(merged)
    return candidates + extra


def _candidates_from_quads(
    morph: np.ndarray,
    pre: PreprocessResult,
    config: Config,
    source: str = "edges_quads",
) -> List[PlateCandidate]:
    """Tìm ứng viên từ các contour xấp xỉ 4 đỉnh (viền biển bị nghiêng).

    Bản đồ ``edges_quads`` giữ ít morphology nên contour viền biển thường còn
    nguyên 4 góc. Ta dùng ``RETR_LIST`` để không bỏ sót contour nằm trong
    contour khác, xấp xỉ đa giác với nhiều epsilon, rồi chỉ nhận tứ giác lồi.
    """
    dc = config.detection
    img_h, img_w = morph.shape[:2]
    contours, _ = cv2.findContours(morph, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    # Ưu tiên contour lớn để giảm chi phí và tránh nhiễu nhỏ
    contours = sorted(contours, key=cv2.contourArea, reverse=True)[:80]

    result: List[PlateCandidate] = []
    seen: set[Tuple[int, int, int, int]] = set()
    for contour in contours:
        area = float(cv2.contourArea(contour))
        if area < dc.min_area_ratio * img_w * img_h:
            continue
        peri = cv2.arcLength(contour, True)
        if peri <= 0:
            continue
        quad: Optional[np.ndarray] = None
        for eps in (0.02, 0.03, 0.04, 0.05, 0.07, 0.10):
            approx = cv2.approxPolyDP(contour, eps * peri, True)
            if len(approx) == 4 and is_convex_quad(approx):
                quad = approx.reshape(4, 2).astype(np.float32)
                break
        if quad is None:
            continue
        x, y, w, h = cv2.boundingRect(quad.astype(np.int32).reshape(-1, 1, 2))
        if w < 8 or h < 4:
            continue
        # Bỏ qua tứ giác gần như trùng nhau (nhiều epsilon cho cùng một viền)
        key = (x // 4, y // 4, w // 4, h // 4)
        if key in seen:
            continue
        seen.add(key)
        cand = _candidate_from_rect(
            quad.astype(np.int32).reshape(-1, 1, 2),
            (x, y, w, h),
            pre,
            config,
            source=source,
            gray_for_text=pre.gray,
        )
        if cand is not None:
            result.append(cand)
    return result


def _padded_crop_size(
    bbox: Sequence[float],
    padding_ratio: float,
    shape: Tuple[int, int],
    vertical_padding_ratio: float = 0.0,
) -> Tuple[int, int, int, int]:
    x1, y1, x2, y2 = bbox
    w, h = x2 - x1, y2 - y1
    pad_x = int(round(w * padding_ratio))
    # Biển một dòng rất rộng nhưng thấp: khi nghiêng, góc biển có thể vượt
    # khỏi bounding box theo trục dọc. Pad dọc theo chiều rộng bù cho trường
    # hợp này mà không cần tăng quá nhiều padding ngang.
    pad_y = int(round(max(h * padding_ratio, w * vertical_padding_ratio)))
    return bbox_to_int((x1 - pad_x, y1 - pad_y, x2 + pad_x, y2 + pad_y), shape)


def crop_candidate(
    image: np.ndarray,
    candidate: PlateCandidate,
    padding_ratio: float,
    vertical_padding_ratio: float = 0.0,
) -> Tuple[np.ndarray, Tuple[int, int, int, int]]:
    h, w = image.shape[:2]
    box = _padded_crop_size(
        candidate.bbox, padding_ratio, (h, w), vertical_padding_ratio
    )
    x1, y1, x2, y2 = box
    return image[y1:y2, x1:x2].copy(), box


# ----------------------------------------------------------------------
# API chính
# ----------------------------------------------------------------------
def detect_plates(pre: PreprocessResult, config: Config) -> DetectionResult:
    t0 = time.perf_counter()
    dc = config.detection
    maps = build_morphology_maps(pre, config)
    if not maps:
        return DetectionResult(timings_ms={"detection_total_ms": 0.0})

    candidates: List[PlateCandidate] = []
    for source, morph in maps.items():
        if source == "edges_quads":
            candidates.extend(_candidates_from_quads(morph, pre, config, source=source))
            continue
        contours, _ = cv2.findContours(
            morph, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            if w < 8 or h < 4:
                continue
            cand = _candidate_from_rect(
                contour,
                (x, y, w, h),
                pre,
                config,
                source=source,
                gray_for_text=pre.gray,
            )
            if cand is not None:
                candidates.append(cand)

    candidates = _deduplicate(candidates, dc.merge_iou)
    candidates = _add_stacked_merges(candidates, pre, config)
    candidates = _deduplicate(candidates, dc.merge_iou)

    # Bổ sung ứng viên từ cụm ký tự: hữu ích khi viền biển bị mất hoặc biển
    # được chụp cận cảnh đến mức morphology không tạo được contour kín.
    # Không gộp các ứng viên này với ứng viên hình học: hai cách cắt có thể
    # trùng vị trí nhưng cho chất lượng nhị phân khác nhau, và pipeline cần
    # thử cả hai trước khi kết luận.
    text_candidates = _deduplicate(_text_cluster_candidates(pre, config), dc.merge_iou)
    text_candidates = _attach_text_bbox_hints(text_candidates, candidates, config)
    candidates.extend(text_candidates)
    candidates.sort(key=lambda c: c.score, reverse=True)

    warnings: List[str] = []
    passed = [c for c in candidates if c.passed]
    if not passed:
        warnings.append("Không có ứng viên nào vượt ngưỡng điểm tối thiểu.")
    passed = passed[: max(1, dc.max_candidates)]

    # Ảnh closing tốt nhất để hiển thị: lấy map chứa nhiều ứng viên điểm cao
    best_source = passed[0].source if passed else next(iter(maps))
    closed = maps.get(best_source)
    timings = {"detection_total_ms": (time.perf_counter() - t0) * 1000.0}
    return DetectionResult(
        candidates=passed,
        all_candidates=candidates,
        closed=closed,
        maps=maps,
        timings_ms=timings,
        warnings=warnings,
    )


def select_top_candidates(
    detection: DetectionResult, top_k: Optional[int] = None
) -> List[PlateCandidate]:
    if top_k is None:
        return list(detection.candidates)
    return list(detection.candidates[: max(1, int(top_k))])

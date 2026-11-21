"""Phân đoạn ký tự trên ảnh biển số đã cắt/hiệu chỉnh.

Các bước:
    - Chuẩn hóa kích thước vùng biển, tăng tương phản, threshold.
    - Chuẩn hóa cực tính để ký tự là foreground (trắng).
    - Loại viền biển / ốc vít bằng connected components.
    - Tách dòng bằng projection profile ngang.
    - Tách ký tự bằng contour + projection profile dọc.
    - Lọc hình học, sắp xếp theo thứ tự đọc.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from .config import Config, SegmentationConfig
from .preprocessing import apply_clahe, ensure_odd


@dataclass
class SegmentedCharacter:
    image: np.ndarray  # ảnh nhị phân, ký tự màu trắng
    bbox: Tuple[float, float, float, float]  # tọa độ trên ảnh work của segmentation
    bbox_plate: Tuple[float, float, float, float]  # tọa độ trên ảnh biển gốc
    row_index: int
    order: int
    area: float = 0.0

    def as_dict(self) -> Dict[str, object]:
        return {
            "bbox": [round(v, 2) for v in self.bbox],
            "bbox_plate": [round(v, 2) for v in self.bbox_plate],
            "row_index": self.row_index,
            "order": self.order,
            "area": round(self.area, 2),
            "width": int(self.bbox[2] - self.bbox[0]),
            "height": int(self.bbox[3] - self.bbox[1]),
        }


@dataclass
class RowInfo:
    bbox: Tuple[int, int, int, int]
    mask: np.ndarray
    char_count: int = 0


@dataclass
class SegmentationResult:
    characters: List[SegmentedCharacter] = field(default_factory=list)
    binary: Optional[np.ndarray] = None
    plate_work: Optional[np.ndarray] = None
    plate_gray_work: Optional[np.ndarray] = None
    rows: List[RowInfo] = field(default_factory=list)
    row_boxes: List[Tuple[int, int, int, int]] = field(default_factory=list)
    scale: float = 1.0
    threshold_method_used: str = ""
    status: str = "EMPTY"  # OK | IMPLAUSIBLE | EMPTY
    score: float = 0.0
    warnings: List[str] = field(default_factory=list)
    timings_ms: Dict[str, float] = field(default_factory=dict)

    @property
    def count(self) -> int:
        return len(self.characters)

    @property
    def is_plausible(self) -> bool:
        return self.status == "OK"


# ----------------------------------------------------------------------
# Tiền xử lý nhị phân
# ----------------------------------------------------------------------
def _resize_plate(
    plate: np.ndarray, target_width: int
) -> Tuple[np.ndarray, float]:
    h, w = plate.shape[:2]
    if w <= 0:
        return plate, 1.0
    scale = float(target_width) / float(w)
    # Không phóng quá 4 lần để tránh khuếch đại nhiễu
    scale = min(scale, 4.0)
    nw = max(1, int(round(w * scale)))
    nh = max(1, int(round(h * scale)))
    interp = cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC
    resized = cv2.resize(plate, (nw, nh), interpolation=interp)
    return resized, scale


def _adaptive_block_sizes(
    cfg: SegmentationConfig, shape: Tuple[int, int]
) -> List[int]:
    """Chọn các kích thước cửa sổ adaptive threshold theo chiều cao ảnh.

    Cửa sổ nhỏ (21) giữ nét tốt trên biển một dòng nhưng có thể làm nét chữ
    dày bị đứt trên biển hai dòng chụp cận cảnh. Thêm một cửa sổ động theo
    chiều cao và một cửa sổ lớn cho ảnh cao giúp tách đủ cả hai dòng.
    """
    h, w = shape[:2]
    max_block = min(max(3, int(cfg.adaptive_block_max)), min(h, w) - 1)
    if max_block < 3:
        return []
    proposals = [ensure_odd(cfg.adaptive_block_size, 3)]
    proposals.append(ensure_odd(int(round(0.11 * h)), 3))
    if h >= 250:
        proposals.append(41)
    blocks: List[int] = []
    for block in proposals:
        block = ensure_odd(block, 3)
        if block < 3 or block > max_block:
            continue
        if block not in blocks:
            blocks.append(block)
    return blocks


def _remove_frame_and_specks(binary: np.ndarray, margin_ratio: float) -> np.ndarray:
    """Xóa viền biển, đường kẻ dài và các thành phần nhiễu nhỏ."""
    h, w = binary.shape[:2]
    if h < 5 or w < 5:
        return binary
    mask = binary.copy()
    margin = max(1, int(round(min(h, w) * margin_ratio)))
    mask[:margin, :] = 0
    mask[-margin:, :] = 0
    mask[:, :margin] = 0
    mask[:, -margin:] = 0

    num, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    out = np.zeros_like(binary)
    min_area = max(2, int(0.00002 * h * w))
    for idx in range(1, num):
        x, y, ww, hh, area = stats[idx]
        if area < min_area:
            continue
        touches = x <= 1 or y <= 1 or x + ww >= w - 1 or y + hh >= h - 1
        # Thành phần chiếm gần cả ảnh: viền biển
        if ww >= 0.88 * w and hh >= 0.88 * h:
            continue
        # Đường kẻ ngang/dọc dài, mảnh: viền hoặc gạch phân cách
        if touches and ww >= 0.75 * w and hh <= 0.14 * h:
            continue
        if touches and hh >= 0.75 * h and ww <= 0.14 * w:
            continue
        if touches and ww >= 0.85 * w and hh <= 0.22 * h:
            continue
        if touches and hh >= 0.85 * h and ww <= 0.22 * w:
            continue
        # Mảng nền/viền lớn sau khi cắt margin có thể không còn chạm biên
        # nhưng vẫn chiếm một vùng rất lớn. Ký tự đơn lẻ không bao giờ có
        # bounding box vừa rộng vừa cao như vậy trong ảnh biển chuẩn hóa.
        bbox_ratio = (ww * hh) / float(max(1, w * h))
        if bbox_ratio >= 0.10 and (ww >= 0.30 * w or hh >= 0.55 * h):
            continue
        out[labels == idx] = 255
    return out


def _ensure_polarity(raw: np.ndarray, invert: bool) -> np.ndarray:
    binary = cv2.bitwise_not(raw) if invert else raw.copy()
    return binary


def _ink_fraction(binary: np.ndarray) -> float:
    return float(np.count_nonzero(binary)) / float(max(1, binary.size))


def _ink_is_plausible(binary: np.ndarray) -> bool:
    frac = _ink_fraction(binary)
    return 0.015 <= frac <= 0.55


# ----------------------------------------------------------------------
# Tách dòng
# ----------------------------------------------------------------------
def _find_rows(
    binary: np.ndarray, cfg: SegmentationConfig, central: bool = False
) -> List[RowInfo]:
    h, w = binary.shape[:2]
    if h < 8 or w < 8:
        return []
    # Với ảnh có tay người/viền biển ở hai mép, projection toàn chiều rộng có
    # thể bị nối liền và gộp hai dòng thành một dải. Lần thử thứ hai chỉ lấy
    # vùng giữa ảnh để tránh các thành phần nhiễu đó.
    if central:
        cx1, cx2 = int(0.12 * w), int(0.88 * w)
        if cx2 - cx1 < 10:
            cx1, cx2 = 0, w
    else:
        cx1, cx2 = 0, w
    row_region = binary[:, cx1:cx2]
    proj = np.count_nonzero(row_region, axis=1).astype(np.float32) / float(
        max(1, cx2 - cx1)
    )
    if proj.max() <= 0:
        return []
    # Làm mượt projection
    kernel = np.ones(5, np.float32) / 5.0
    smooth = np.convolve(proj, kernel, mode="same")
    max_val = float(smooth.max())
    threshold = max(float(cfg.row_projection_threshold), 0.08 * max_val)
    active = smooth > threshold

    bands: List[Tuple[int, int]] = []
    start = None
    for y, val in enumerate(active):
        if val and start is None:
            start = y
        elif not val and start is not None:
            bands.append((start, y))
            start = None
    if start is not None:
        bands.append((start, h))

    # Gộp các khoảng hở rất nhỏ bên trong một dòng ký tự
    merge_gap = max(1, int(round(0.015 * h)))
    merged: List[Tuple[int, int]] = []
    for band in bands:
        if merged and band[0] - merged[-1][1] <= merge_gap:
            merged[-1] = (merged[-1][0], band[1])
        else:
            merged.append(band)
    bands = merged

    # Tinh chỉnh mỗi dải về đúng vùng có mực ở phần giữa ảnh. Viền dọc và
    # ốc vít ở hai mép có thể kéo dài dải và làm sai tỷ lệ chiều cao ký tự.
    cx1, cx2 = int(0.15 * w), int(0.85 * w)
    if cx2 - cx1 >= 10:
        refined: List[Tuple[int, int]] = []
        for (by1, by2) in bands:
            center = binary[by1:by2, cx1:cx2]
            if center.size == 0:
                refined.append((by1, by2))
                continue
            row_counts = np.count_nonzero(center, axis=1)
            active_rows = row_counts >= max(2, int(0.006 * (cx2 - cx1)))
            if not active_rows.any():
                refined.append((by1, by2))
                continue
            # Lấy đoạn liên tục dài nhất (nối các lỗ nhỏ bên trong ký tự)
            pad = max(1, int(round(0.008 * h)))
            idx = np.where(active_rows)[0]
            segments: List[Tuple[int, int]] = []
            start = int(idx[0])
            prev = int(idx[0])
            for val in idx[1:]:
                val = int(val)
                if val - prev <= pad:
                    prev = val
                else:
                    segments.append((start, prev + 1))
                    start, prev = val, val
            segments.append((start, prev + 1))
            seg = max(segments, key=lambda s: s[1] - s[0])
            ty1 = by1 + seg[0]
            ty2 = by1 + seg[1]
            # Giữ nguyên nếu đoạn tìm được quá nhỏ so với dải ban đầu
            if (ty2 - ty1) >= 0.35 * (by2 - by1):
                refined.append((ty1, ty2))
            else:
                refined.append((by1, by2))
        bands = refined

    min_h = max(4, int(round(cfg.row_min_height_ratio * h)))
    bands = [b for b in bands if (b[1] - b[0]) >= min_h]
    if not bands:
        # Fallback: toàn bộ vùng có ink
        ys = np.where(proj > 0)[0]
        if len(ys) == 0:
            return []
        bands = [(int(ys.min()), int(ys.max()) + 1)]
    if len(bands) > 2:
        # Giữ tối đa hai dải cao nhất, không chồng lấn
        bands = sorted(bands, key=lambda b: b[1] - b[0], reverse=True)[:2]
        bands.sort(key=lambda b: b[0])

    rows: List[RowInfo] = []
    pad = max(1, int(round(0.02 * h)))
    for index, (y1, y2) in enumerate(bands):
        # Chia đôi khoảng hở giữa hai dòng để padding không chồng lấn, tránh
        # một ký tự bị cắt cụt hoặc bị đưa vào cả hai dòng.
        top = (bands[index - 1][1] + y1) // 2 if index > 0 else 0
        bottom = (
            (y2 + bands[index + 1][0]) // 2 if index + 1 < len(bands) else h
        )
        yy1 = max(0, top, y1 - pad)
        yy2 = min(h, bottom, y2 + pad)
        row_mask = binary[yy1:yy2, :].copy()
        rows.append(RowInfo(bbox=(0, yy1, w, yy2 - yy1), mask=row_mask))
    return rows


def _area_weighted_median_height(
    components: Sequence[Tuple[int, int, int, int, int]],
) -> float:
    """Trung vị chiều cao có trọng số diện tích.

    Trung vị thường bị các mảnh nhiễu nhỏ kéo lệch; dùng diện tích làm trọng
    số giúp ước lượng chiều cao ký tự thật ổn định hơn trên biển thật.
    """
    if not components:
        return 0.0
    ordered = sorted(components, key=lambda c: c[3])
    total = sum(max(0, int(c[4])) for c in ordered)
    if total <= 0:
        return float(np.median([c[3] for c in ordered]))
    accumulated = 0
    for component in ordered:
        accumulated += max(0, int(component[4]))
        if accumulated >= 0.5 * total:
            return float(component[3])
    return float(ordered[-1][3])


def _find_component_rows(
    binary: np.ndarray, cfg: SegmentationConfig
) -> List[Tuple[int, int]]:
    """Tìm dải dòng bằng connected components.

    Projection profile có thể gộp hai dòng sát nhau thành một dải cao khi
    biển được chụp cận cảnh. Gom các thành phần giống ký tự theo tâm dọc rồi
    lấy dải y của từng nhóm là phương án dự phòng độc lập với projection.
    """
    h, w = binary.shape[:2]
    if h < 12 or w < 20:
        return []
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
        # Đường kẻ dài hoặc viền dọc mảnh không phải ký tự.
        if ww > 0.50 * w and hh < 0.06 * h:
            continue
        if hh > 0.50 * h and ww < 0.03 * w:
            continue
        components.append((x, y, ww, hh, area))
    if len(components) < 3:
        return []

    median_h = _area_weighted_median_height(components)
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

    bands: List[Tuple[int, int, int, int, int, float]] = []
    for group in groups:
        if len(group) < 3:
            continue
        ordered = sorted(group, key=lambda c: c[0])
        row_median_w = float(np.median([c[2] for c in ordered]))
        if row_median_w <= 0:
            continue
        x1 = min(c[0] for c in ordered)
        x2 = max(c[0] + c[2] for c in ordered)
        span = float(x2 - x1)
        if span < max(1.8 * row_median_w, 0.10 * w):
            continue
        y1 = min(c[1] for c in ordered)
        y2 = max(c[1] + c[3] for c in ordered)
        if (y2 - y1) < cfg.row_min_height_ratio * h:
            continue
        bands.append((int(y1), int(y2), int(x1), int(x2), len(ordered), span))

    if len(bands) > 2:
        bands = sorted(bands, key=lambda b: b[4], reverse=True)[:2]
    bands.sort(key=lambda b: b[0])

    if len(bands) == 2:
        first, second = bands
        # Hai dòng của cùng một biển phải chồng lên nhau theo trục ngang.
        # Một nhóm nhiễu lệch hẳn sang bên là dấu hiệu không phải dòng chữ.
        overlap = min(first[3], second[3]) - max(first[2], second[2])
        min_width = min(first[3] - first[2], second[3] - second[2])
        if min_width <= 0 or overlap / float(min_width) < 0.30:
            return []
        # Hai dải không được chồng lấn theo trục dọc quá nhiều; nếu có, rất
        # có thể một thành phần lớn bị gán sai vào cả hai dòng.
        vertical_overlap = min(first[1], second[1]) - max(first[0], second[0])
        min_height = min(first[1] - first[0], second[1] - second[0])
        if min_height > 0 and vertical_overlap > 0.25 * min_height:
            return []
    return [(y1, y2) for (y1, y2, _, _, _, _) in bands]


def _rows_from_bands(
    bands: Sequence[Tuple[int, int]],
    binary: np.ndarray,
    cfg: SegmentationConfig,
) -> List[RowInfo]:
    """Tạo RowInfo từ các dải y, không để padding của hai dòng chồng nhau."""
    h, w = binary.shape[:2]
    pad = max(1, int(round(0.02 * h)))
    rows: List[RowInfo] = []
    for index, (y1, y2) in enumerate(bands):
        top = (bands[index - 1][1] + y1) // 2 if index > 0 else 0
        bottom = (
            (y2 + bands[index + 1][0]) // 2 if index + 1 < len(bands) else h
        )
        yy1 = max(0, top, y1 - pad)
        yy2 = min(h, bottom, y2 + pad)
        if yy2 - yy1 < max(2, int(round(0.5 * cfg.row_min_height_ratio * h))):
            continue
        rows.append(
            RowInfo(bbox=(0, yy1, w, yy2 - yy1), mask=binary[yy1:yy2, :].copy())
        )
    return rows


def _find_rows_with_fallback(
    binary: np.ndarray, cfg: SegmentationConfig
) -> List[RowInfo]:
    """Dùng projection trước, chỉ fallback khi projection thiếu dòng."""
    rows = _find_rows(binary, cfg)
    if len(rows) >= 2:
        return rows
    if not cfg.component_row_fallback:
        return rows
    central_rows = _find_rows(binary, cfg, central=True)
    if len(central_rows) >= 2:
        return central_rows
    bands = _find_component_rows(binary, cfg)
    if len(bands) < 2:
        return rows
    alternative = _rows_from_bands(bands, binary, cfg)
    return alternative if len(alternative) >= 2 else rows


# ----------------------------------------------------------------------
# Tách ký tự trong một dòng
# ----------------------------------------------------------------------
def _box_height_ok(box: Sequence[float], row_h: int, cfg: SegmentationConfig) -> bool:
    hh = box[3] - box[1]
    ratio = hh / max(1, row_h)
    return cfg.min_char_height_ratio <= ratio <= cfg.max_char_height_ratio


def _filter_boxes(
    boxes: List[Tuple[int, int, int, int]],
    row_shape: Tuple[int, int],
    plate_shape: Tuple[int, int],
    cfg: SegmentationConfig,
) -> List[Tuple[int, int, int, int]]:
    rh, rw = row_shape
    ph, pw = plate_shape
    valid: List[Tuple[int, int, int, int]] = []
    for (x, y, w, h) in boxes:
        if w <= 1 or h <= 1:
            continue
        if not _box_height_ok((x, y, x + w, y + h), rh, cfg):
            continue
        # Không loại cứng ký tự nằm sát mép: ảnh biển được cắt sát có thể
        # khiến ký tự đầu tiên bắt đầu ngay tại x=0. Chỉ loại mảnh mỏng ở
        # mép, còn ký tự thật thường đủ rộng và đủ cao để đi tiếp.
        edge_zone = 0.02 * pw
        near_edge = x <= edge_zone or x + w >= pw - edge_zone
        if near_edge and (w < 0.32 * rh or h < 0.30 * rh):
            continue
        # Ốc vít/viền dọc rất hẹp so với chiều cao dòng
        if w < 0.16 * rh:
            continue
        # Gạch ngang phân cách: thấp và dài
        if h < 0.32 * rh and w > 1.8 * h:
            continue
        # Viền dọc/ốc vít: rất cao và hẹp (h/w lớn). Ký tự "1" có chân đế
        # thường có tỷ lệ thấp hơn nhiều so với một vạch viền.
        if h > 4.2 * w and h > 0.60 * rh:
            continue
        if w / max(1.0, pw) < cfg.min_char_width_ratio:
            continue
        if w / max(1.0, pw) > cfg.max_char_width_ratio:
            # Vẫn giữ để bước split_wide xử lý, trừ khi quá lớn
            if w > 0.45 * pw:
                continue
        if (w * h) / max(1.0, pw * ph) < cfg.min_char_area_ratio:
            continue
        # Chỉ bỏ hộp gần như phủ cả dòng (viền/gạch), không bỏ hộp dính mép.
        if w >= 0.60 * rw and h <= 0.20 * rh:
            continue
        valid.append((x, y, w, h))
    return valid


def _merge_fragments(
    boxes: List[Tuple[int, int, int, int]], gap_px: int
) -> List[Tuple[int, int, int, int]]:
    """Gộp các mảnh của cùng một ký tự bị đứt nét."""
    if len(boxes) <= 1:
        return boxes
    ordered = sorted(boxes, key=lambda b: (b[0], b[1]))
    changed = True
    while changed:
        changed = False
        result: List[Tuple[int, int, int, int]] = []
        for box in ordered:
            merged = False
            for i, existing in enumerate(result):
                ex1, ey1, ex2, ey2 = existing
                x1, y1, x2, y2 = box
                # Chồng lấn theo trục x đủ lớn
                inter_x = min(ex2, x2) - max(ex1, x1)
                min_w = min(ex2 - ex1, x2 - x1)
                vertical_overlap = min(ey2, y2) - max(ey1, y1)
                min_h = min(ey2 - ey1, y2 - y1)
                gap = max(x1, ex1) - min(x2, ex2)
                if (
                    min_w > 0
                    and min_h > 0
                    and inter_x > 0.45 * min_w
                    and vertical_overlap > 0.30 * min_h
                ) or (gap <= gap_px and vertical_overlap > 0.5 * min_h):
                    nx1, ny1 = min(ex1, x1), min(ey1, y1)
                    nx2, ny2 = max(ex2, x2), max(ey2, y2)
                    result[i] = (nx1, ny1, nx2 - nx1, ny2 - ny1)
                    changed = True
                    merged = True
                    break
            if not merged:
                result.append(box)
        ordered = sorted(result, key=lambda b: (b[0], b[1]))
    return ordered


def _dedupe_boxes(
    boxes: List[Tuple[int, int, int, int]], iou_threshold: float = 0.55
) -> List[Tuple[int, int, int, int]]:
    ordered = sorted(boxes, key=lambda b: b[2] * b[3], reverse=True)
    kept: List[Tuple[int, int, int, int]] = []
    for box in ordered:
        x1, y1, w1, h1 = box
        duplicate = False
        for (x2, y2, w2, h2) in kept:
            ix1, iy1 = max(x1, x2), max(y1, y2)
            ix2, iy2 = min(x1 + w1, x2 + w2), min(y1 + h1, y2 + h2)
            inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
            union = w1 * h1 + w2 * h2 - inter
            if union > 0 and inter / union >= iou_threshold:
                duplicate = True
                break
        if not duplicate:
            kept.append(box)
    return kept


def _split_wide_box(
    box: Tuple[int, int, int, int],
    row_mask: np.ndarray,
    plate_shape: Tuple[int, int],
    cfg: SegmentationConfig,
    median_width: float,
    depth: int = 0,
) -> List[Tuple[int, int, int, int]]:
    """Tách hộp quá rộng bằng projection dọc nếu tìm thấy điểm thắt."""
    if depth >= 3 or not cfg.split_wide:
        return [box]
    x, y, w, h = box
    ph, pw = plate_shape
    if w < 1.55 * median_width:
        return [box]
    if w > cfg.max_char_width_ratio * pw and w < 1.75 * median_width:
        return [box]
    roi = row_mask[y : y + h, x : x + w]
    if roi.size == 0:
        return [box]
    proj = np.count_nonzero(roi, axis=0).astype(np.float32)
    smooth = np.convolve(proj, np.ones(3, np.float32) / 3.0, mode="same")
    max_proj = float(smooth.max())
    min_proj = float(smooth.min())
    if max_proj <= 0:
        return [box]
    # Tìm điểm thắt mạnh gần giữa hộp
    x0 = int(0.25 * w)
    x1 = int(0.75 * w)
    if x1 <= x0:
        return [box]
    segment = smooth[x0:x1]
    rel = segment / max_proj
    candidates = np.where(rel <= cfg.split_valley_ratio)[0]
    if len(candidates) == 0:
        # Hai ký tự dính nhau có thể không tạo điểm thắt rõ ràng. Nếu hộp
        # rộng gần gấp đôi chiều rộng trung vị, tách đôi tại vị trí có
        # projection thấp nhất quanh tâm thay vì bỏ nguyên một hộp lớn.
        if w >= 1.60 * median_width:
            center_idx = int(np.argmin(smooth[x0:x1])) + x0
            split_abs = x + center_idx
            min_part_w = max(3, int(0.40 * median_width))
            if (
                split_abs - x >= min_part_w
                and x + w - split_abs >= min_part_w
            ):
                return [
                    (x, y, split_abs - x, h),
                    (split_abs, y, x + w - split_abs, h),
                ]
        return [box]
    center = (x0 + x1) / 2.0
    distances = np.abs((candidates + x0) - center)
    split_rel = int(candidates[int(np.argmin(distances))]) + x0
    split_abs = x + split_rel
    # Kiểm tra hai phần tạo ra đủ lớn
    left = (x, y, split_abs - x, h)
    right = (split_abs, y, x + w - split_abs, h)
    min_part_w = max(3, int(0.12 * median_width))
    if left[2] < min_part_w or right[2] < min_part_w:
        return [box]
    # Điểm thắt phải thấp hơn đáng kể so với hai bên. Với hộp rộng gần gấp
    # đôi chiều rộng một ký tự, ký tự dính nhau có thể chỉ tạo rãnh nông;
    # vẫn tách tại điểm thấp nhất thay vì bỏ nguyên một hộp chứa hai ký tự.
    if min_proj > 0.45 * max_proj and w < 1.60 * median_width:
        return [box]
    parts: List[Tuple[int, int, int, int]] = []
    for part in (left, right):
        parts.extend(
            _split_wide_box(
                part, row_mask, plate_shape, cfg, median_width, depth + 1
            )
        )
    return parts


def _filter_row_edge_fragments(
    boxes: List[Tuple[int, int, int, int]],
    row_shape: Tuple[int, int],
    plate_shape: Tuple[int, int],
) -> List[Tuple[int, int, int, int]]:
    """Loại mảnh viền/ốc vít ở mép dựa trên chiều cao của chính dòng đó."""
    if len(boxes) < 4:
        return boxes
    rh, rw = row_shape
    ph, pw = plate_shape
    median_h = float(np.median([b[3] for b in boxes]))
    median_w = float(np.median([b[2] for b in boxes]))
    if median_h <= 0 or median_w <= 0:
        return boxes
    edge = 0.10 * pw
    kept: List[Tuple[int, int, int, int]] = []
    for (x, y, w, h) in boxes:
        near_left = x <= edge
        near_right = x + w >= pw - edge
        if near_left or near_right:
            if h < 0.88 * median_h and w < 1.40 * median_w:
                continue
            if w < 0.45 * median_w and h < 0.95 * median_h:
                continue
        kept.append((x, y, w, h))
    return kept if len(kept) >= 3 else boxes


def _filter_edge_fragments(
    boxes: List[Tuple[int, int, int, int]],
    plate_shape: Tuple[int, int],
) -> List[Tuple[int, int, int, int]]:
    """Loại mảnh viền/ốc vít còn sót ở hai mép sau khi đã tách hộp rộng."""
    if len(boxes) < 4:
        return boxes
    ph, pw = plate_shape
    widths = np.array([b[2] for b in boxes], dtype=np.float32)
    heights = np.array([b[3] for b in boxes], dtype=np.float32)
    median_w = float(np.median(widths))
    median_h = float(np.median(heights))
    if median_w <= 0 or median_h <= 0:
        return boxes
    edge = 0.11 * pw
    kept: List[Tuple[int, int, int, int]] = []
    for (x, y, w, h) in boxes:
        near_left = x <= edge
        near_right = x + w >= pw - edge
        if near_left and (
            h > 1.12 * median_h
            or (w < 0.45 * median_w and h < 0.90 * median_h)
        ):
            continue
        if near_right and (
            h > 1.12 * median_h
            or (w < 0.45 * median_w and h < 0.90 * median_h)
        ):
            continue
        kept.append((x, y, w, h))
    # Không được xóa quá nhiều: nếu chỉ còn dưới 3 hộp, giữ nguyên ban đầu.
    return kept if len(kept) >= 3 else boxes


def _boxes_in_row(
    row: RowInfo,
    plate_shape: Tuple[int, int],
    cfg: SegmentationConfig,
) -> List[Tuple[int, int, int, int]]:
    mask = row.mask
    rh, rw = mask.shape
    # Đóng nhỏ để nối nét đứt, sau đó tìm contour ngoài
    if cfg.close_kernel and cfg.close_kernel[0] > 0 and cfg.close_kernel[1] > 0:
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, cfg.close_kernel)
        mask_proc = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)
    else:
        mask_proc = mask
    contours, _ = cv2.findContours(
        mask_proc, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    boxes: List[Tuple[int, int, int, int]] = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if w <= 1 or h <= 1:
            continue
        area = cv2.contourArea(contour)
        fill = area / max(1.0, w * h)
        if fill < cfg.min_fill_ratio:
            continue
        boxes.append((x, y, w, h))
    boxes = _filter_boxes(boxes, (rh, rw), plate_shape, cfg)
    boxes = _merge_fragments(boxes, max(0, int(cfg.merge_gap_px)))
    boxes = _filter_boxes(boxes, (rh, rw), plate_shape, cfg)
    boxes = _dedupe_boxes(boxes)
    if boxes:
        widths = [b[2] for b in boxes if b[3] >= 0.5 * rh]
        median_width = float(np.median(widths)) if widths else float(rw) / 8.0
        # Khi một số ký tự dính nhau, hộp ghép rất rộng sẽ làm trung vị bị
        # kéo lên và khiến các hộp ghép không được tách. Ước lượng lại chiều
        # rộng của MỘT ký tự từ nhóm hộp hẹp hơn trung vị; chỉ dùng giá trị
        # này làm mốc tách, không thay đổi hình học của hộp.
        narrow_widths = [w for w in widths if w <= 1.40 * median_width]
        single_width = (
            float(np.median(narrow_widths)) if narrow_widths else median_width
        )
        single_width = max(1.0, min(single_width, median_width))
        split_boxes: List[Tuple[int, int, int, int]] = []
        for box in boxes:
            split_boxes.extend(
                _split_wide_box(box, mask, plate_shape, cfg, single_width)
            )
        boxes = split_boxes
    boxes = _dedupe_boxes(boxes)
    boxes = _filter_row_edge_fragments(boxes, (rh, rw), plate_shape)
    boxes = _filter_edge_fragments(boxes, plate_shape)
    boxes.sort(key=lambda b: b[0])
    return boxes


# ----------------------------------------------------------------------
# Đánh giá tính hợp lý của một phương án phân đoạn
# ----------------------------------------------------------------------
def _is_balanced_long_plate(
    count: int, rows: Sequence[RowInfo], cfg: SegmentationConfig
) -> bool:
    """Biển 10 ký tự chỉ hợp lệ khi hai dòng cân bằng (thường 5/5).

    Biển đặc biệt có thể dài hơn 9 ký tự, nhưng nếu một dòng có 4 và dòng
    kia có 6 thì nhiều khả năng có mảnh nhiễu ở mép được ghép vào. Chỉ chấp
    nhận trường hợp ngoại lệ khi hai dòng có cùng số ký tự và mỗi dòng đủ
    dài để không phải viền/ốc vít.
    """
    if not cfg.allow_balanced_long_plate:
        return False
    _lo, hi = cfg.expected_chars
    if count != hi + 1 or len(rows) != 2:
        return False
    counts = [row.char_count for row in rows]
    return counts[0] >= 5 and counts[0] == counts[1]


def _plausibility_score(
    boxes: List[Tuple[int, int, int, int]],
    rows: List[RowInfo],
    plate_shape: Tuple[int, int],
    cfg: SegmentationConfig,
) -> Tuple[float, str]:
    n = len(boxes)
    if n == 0:
        return 0.0, "EMPTY"
    ph, pw = plate_shape
    lo, hi = cfg.expected_chars
    balanced_long = _is_balanced_long_plate(n, rows, cfg)
    if lo <= n <= hi or balanced_long:
        count_score = 1.0
    else:
        count_score = max(0.0, 1.0 - abs(n - lo if n < lo else n - hi) / 4.0)

    heights = [b[3] for b in boxes]
    median_h = float(np.median(heights)) if heights else 1.0
    if median_h <= 0:
        height_score = 0.0
    else:
        cv = float(np.std(heights) / max(1.0, median_h))
        height_score = max(0.0, 1.0 - min(1.0, cv / 0.65))

    row_score = 0.6
    if len(rows) == 2:
        counts = [r.char_count for r in rows]
        if (
            3 <= counts[0] <= 4
            and 4 <= counts[1] <= 5
        ) or (3 <= counts[0] <= 4 and 3 <= counts[1] <= 5):
            row_score = 1.0
        elif balanced_long:
            row_score = 1.0
        else:
            row_score = 0.4
    elif len(rows) == 1:
        row_score = 1.0 if lo <= n <= hi else 0.4

    edge_frac = 0.0
    for (x, y, w, h) in boxes:
        if x <= 1 or x + w >= pw - 1:
            edge_frac += 1.0
    edge_frac /= max(1, n)
    score = (
        0.50 * count_score
        + 0.25 * height_score
        + 0.15 * row_score
        + 0.10 * (1.0 - edge_frac)
    )
    if n < cfg.min_chars or n == 0:
        status = "IMPLAUSIBLE"
    elif n > hi + 1:
        status = "IMPLAUSIBLE"
    elif count_score < 0.75:
        status = "IMPLAUSIBLE"
    else:
        status = "OK"
    return float(score), status


def _analyze_binary(
    raw: np.ndarray,
    invert: bool,
    cfg: SegmentationConfig,
    plate_shape: Tuple[int, int],
    margin_ratio: float,
) -> Optional[Dict[str, object]]:
    binary = _ensure_polarity(raw, invert)
    if not _ink_is_plausible(binary):
        return None
    binary = _remove_frame_and_specks(binary, margin_ratio)
    if not _ink_is_plausible(binary):
        return None

    rows = _find_rows_with_fallback(binary, cfg)
    if not rows:
        return None
    row_boxes: List[Tuple[RowInfo, List[Tuple[int, int, int, int]]]] = []
    for row in rows:
        boxes = _boxes_in_row(row, plate_shape, cfg)
        row.char_count = len(boxes)
        row_boxes.append((row, boxes))

    # Một dải chỉ có 1-2 thành phần trong khi dòng còn lại có đủ ký tự
    # thường là viền/ốc vít hoặc nhiễu, không phải dòng chữ thật. Loại bỏ
    # dải đó để tránh ghép thêm ký tự rác vào chuỗi.
    if len(row_boxes) > 1:
        max_count = max(len(boxes) for _, boxes in row_boxes)
        if max_count >= 5:
            filtered = [
                (row, boxes) for row, boxes in row_boxes if len(boxes) >= 3
            ]
            if filtered and len(filtered) < len(row_boxes):
                row_boxes = filtered
                rows = [row for row, _ in row_boxes]

    all_boxes: List[Tuple[int, int, int, int]] = []
    for row, boxes in row_boxes:
        # Chuyển tọa độ từ hệ tọa độ của dòng sang hệ tọa độ ảnh biển work
        oy = row.bbox[1]
        all_boxes.extend((x, y + oy, w, h) for (x, y, w, h) in boxes)
    score, status = _plausibility_score(all_boxes, rows, plate_shape, cfg)
    return {
        "binary": binary,
        "rows": rows,
        "boxes": all_boxes,
        "score": score,
        "status": status,
        "invert": invert,
    }


def segment_characters(
    plate_image: np.ndarray, config: Config
) -> SegmentationResult:
    """Phân đoạn ký tự từ ảnh biển số (BGR hoặc grayscale)."""
    t0 = time.perf_counter()
    timings: Dict[str, float] = {}
    sc = config.segmentation
    warnings: List[str] = []
    if plate_image is None or plate_image.size == 0:
        return SegmentationResult(
            status="EMPTY", warnings=["Ảnh biển số rỗng."],
            timings_ms={"segmentation_total_ms": 0.0},
        )
    if plate_image.ndim == 2:
        plate_bgr = cv2.cvtColor(plate_image, cv2.COLOR_GRAY2BGR)
    else:
        plate_bgr = plate_image
    h, w = plate_bgr.shape[:2]
    if w < 30 or h < 12:
        return SegmentationResult(
            status="EMPTY",
            plate_work=plate_bgr,
            warnings=["Ảnh biển số quá nhỏ để phân đoạn."],
            timings_ms={"segmentation_total_ms": 0.0},
        )

    t_resize = time.perf_counter()
    work, scale = _resize_plate(plate_bgr, sc.plate_width)
    timings["resize_ms"] = (time.perf_counter() - t_resize) * 1000.0
    gray = cv2.cvtColor(work, cv2.COLOR_BGR2GRAY)
    if sc.use_clahe:
        gray = apply_clahe(gray, sc.clahe_clip_limit, sc.clahe_tile_grid)
    gray = cv2.GaussianBlur(gray, (ensure_odd(sc.blur_kernel, 3),) * 2, 0)

    t_thr = time.perf_counter()
    _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    base_block = ensure_odd(sc.adaptive_block_size, 3)
    adaptive_variants: List[Tuple[str, np.ndarray]] = []
    for block in _adaptive_block_sizes(sc, gray.shape):
        adaptive = cv2.adaptiveThreshold(
            gray,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            block,
            int(sc.adaptive_c),
        )
        name = "adaptive" if block == base_block else f"adaptive_{block}"
        adaptive_variants.append((name, adaptive))
    timings["threshold_ms"] = (time.perf_counter() - t_thr) * 1000.0

    method = (sc.threshold_method or "auto").lower()
    raw_candidates: List[Tuple[str, np.ndarray]] = []
    if method in {"auto", "otsu", "both"}:
        raw_candidates.append(("otsu", otsu))
    if method in {"auto", "adaptive", "both"}:
        raw_candidates.extend(adaptive_variants)

    t_analyze = time.perf_counter()
    analyses: List[Tuple[str, Dict[str, object]]] = []
    plate_shape = gray.shape[:2]
    for name, raw in raw_candidates:
        for invert in (False, True):
            analysis = _analyze_binary(
                raw, invert, sc, plate_shape, sc.border_margin_ratio
            )
            if analysis is not None:
                analyses.append((name, analysis))
    timings["segment_analyze_ms"] = (time.perf_counter() - t_analyze) * 1000.0
    if not analyses:
        timings["segmentation_total_ms"] = (time.perf_counter() - t0) * 1000.0
        return SegmentationResult(
            status="EMPTY",
            binary=otsu,
            plate_work=work,
            plate_gray_work=gray,
            scale=scale,
            threshold_method_used=method,
            warnings=warnings + ["Không tìm thấy vùng mực ký tự hợp lệ."],
            timings_ms=timings,
        )

    # Ưu tiên điểm hợp lý, sau đó đến phương pháp chỉ định
    def rank(item: Tuple[str, Dict[str, object]]) -> Tuple[float, float]:
        name, analysis = item
        preference = 0.0
        if method == name or (method == "adaptive" and name.startswith("adaptive")):
            preference = 0.01
        elif method == "auto" and name == "otsu":
            # Otsu thường cho nét sạch hơn trên biển tương phản cao. Khi điểm
            # hợp lý xấp xỉ nhau, ưu tiên nhẹ để tránh đổi sang adaptive chỉ
            # vì chênh lệch rất nhỏ.
            preference = 0.005
        return float(analysis["score"]) + preference, float(analysis["score"])

    name, best = max(analyses, key=rank)
    binary = best["binary"]
    rows: List[RowInfo] = best["rows"]  # type: ignore[assignment]
    boxes: List[Tuple[int, int, int, int]] = best["boxes"]  # type: ignore[assignment]
    score = float(best["score"])
    status = str(best["status"])
    invert = bool(best["invert"])
    # Lưu ý: với biển nền sáng, đảo cực tính là bước chuẩn hóa bình thường,
    # không phải cảnh báo lỗi.

    # Sắp xếp theo dòng rồi theo x, gán order
    characters: List[SegmentedCharacter] = []
    order = 0
    for row_idx, row in enumerate(rows):
        rx, ry, rw, rh = row.bbox
        row_boxes = [
            b
            for b in boxes
            if ry <= b[1] + b[3] / 2.0 < ry + rh + 1
        ]
        row_boxes.sort(key=lambda b: b[0])
        for (bx, by, bw, bh) in row_boxes:
            # Tọa độ tương đối trong ảnh work
            x1, y1 = bx, by
            x2, y2 = bx + bw, by + bh
            char_img = binary[y1:y2, x1:x2].copy()
            if char_img.size == 0 or np.count_nonzero(char_img) < 4:
                continue
            characters.append(
                SegmentedCharacter(
                    image=char_img,
                    bbox=(float(x1), float(y1), float(x2), float(y2)),
                    bbox_plate=(
                        x1 / scale,
                        y1 / scale,
                        x2 / scale,
                        y2 / scale,
                    ),
                    row_index=row_idx,
                    order=order,
                    area=float(np.count_nonzero(char_img)),
                )
            )
            order += 1

    # Kiểm tra số lượng ký tự mỗi dòng
    if len(rows) == 2:
        counts = [r.char_count for r in rows]
        if not (3 <= counts[0] <= 4 and 4 <= counts[1] <= 5):
            warnings.append(
                f"Số ký tự mỗi dòng không điển hình: {counts}."
            )
    if status == "OK" and not (sc.expected_chars[0] <= len(characters) <= sc.expected_chars[1]):
        if not _is_balanced_long_plate(len(characters), rows, sc):
            status = "IMPLAUSIBLE"
            warnings.append(
                f"Số ký tự phân đoạn được ({len(characters)}) nằm ngoài khoảng "
                f"kỳ vọng {list(sc.expected_chars)}."
            )
    if status == "OK" and len(rows) == 2 and len(characters) >= 7:
        top_count = rows[0].char_count
        bottom_count = rows[1].char_count
        if bottom_count < 4:
            status = "IMPLAUSIBLE"
            warnings.append("Dòng dưới có ít hơn 4 ký tự.")

    timings["segmentation_total_ms"] = (time.perf_counter() - t0) * 1000.0
    return SegmentationResult(
        characters=characters,
        binary=binary,
        plate_work=work,
        plate_gray_work=gray,
        rows=rows,
        row_boxes=[r.bbox for r in rows],
        scale=scale,
        threshold_method_used=name,
        status=status,
        score=score,
        warnings=warnings,
        timings_ms=timings,
    )


def characters_as_dicts(result: SegmentationResult) -> List[Dict[str, object]]:
    return [c.as_dict() for c in result.characters]

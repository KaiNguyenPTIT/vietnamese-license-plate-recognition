"""Cắt vùng biển số và hiệu chỉnh phối cảnh.

Quy trình:
    1. Mở rộng bounding box, cắt ROI.
    2. Tìm contour có 4 đỉnh hợp lệ (approxPolyDP / minAreaRect).
    3. Sắp xếp 4 góc và warpPerspective.
    4. Nếu thất bại: giữ crop bounding box hoặc xoay nhẹ (deskew).

Mọi kết quả đều kèm ma trận thuận/nghịch để có thể ánh xạ tọa độ ký tự ngược
về ảnh gốc khi cần đánh giá.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from .config import Config
from .io_utils import bbox_to_int, is_convex_quad, order_quad_points
from .plate_detection import PlateCandidate, crop_candidate


@dataclass
class RectificationResult:
    plate_image: np.ndarray
    plate_gray: np.ndarray
    method: str
    crop_image: np.ndarray
    roi_bbox: Tuple[int, int, int, int]
    matrix: np.ndarray  # ROI (padded crop) -> plate_image
    inverse_matrix: np.ndarray  # plate_image -> ROI
    quad: Optional[np.ndarray] = None  # tọa độ trên ảnh work
    angle: float = 0.0
    output_size: Tuple[int, int] = (0, 0)
    timings_ms: Dict[str, float] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    def map_points_to_work(self, points: np.ndarray) -> np.ndarray:
        """Ánh xạ các điểm trong ảnh biển đã hiệu chỉnh về ảnh work."""
        pts = np.asarray(points, dtype=np.float32).reshape(-1, 1, 2)
        mapped = cv2.perspectiveTransform(pts, self.inverse_matrix)
        mapped = mapped.reshape(-1, 2)
        mapped[:, 0] += self.roi_bbox[0]
        mapped[:, 1] += self.roi_bbox[1]
        return mapped


def _side_lengths(quad: np.ndarray) -> Tuple[float, float, float, float]:
    top = float(np.linalg.norm(quad[1] - quad[0]))
    right = float(np.linalg.norm(quad[2] - quad[1]))
    bottom = float(np.linalg.norm(quad[3] - quad[2]))
    left = float(np.linalg.norm(quad[0] - quad[3]))
    return top, right, bottom, left


def _valid_quad(
    quad: np.ndarray, roi_shape: Tuple[int, int], config: Config
) -> bool:
    h, w = roi_shape
    pts = np.asarray(quad, dtype=np.float32).reshape(-1, 2)
    if pts.shape[0] != 4:
        return False
    if not is_convex_quad(pts):
        return False
    area = float(cv2.contourArea(pts.reshape(-1, 1, 2)))
    if area < config.rectification.min_quad_area_ratio * w * h:
        return False
    top, right, bottom, left = _side_lengths(pts)
    if min(top, right, bottom, left) < 8:
        return False
    avg_w = (top + bottom) / 2.0
    avg_h = (left + right) / 2.0
    if avg_h <= 1:
        return False
    ratio = avg_w / avg_h
    if ratio < 0.8 or ratio > config.rectification.max_output_ratio:
        return False
    # Quad phải bao gần hết ROI (tránh bắt nhầm một ô nhỏ bên trong)
    x, y, bw, bh = cv2.boundingRect(pts.reshape(-1, 1, 2))
    if bw < 0.70 * w or bh < 0.60 * h:
        return False
    return True


def _find_quad_in_roi(
    roi: np.ndarray, config: Config
) -> Tuple[Optional[np.ndarray], str]:
    """Tìm tứ giác biển số trong ROI. Trả về (quad, phương pháp)."""
    rc = config.rectification
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape[:2]
    if w < 20 or h < 10:
        return None, "none"
    scale = 1.0
    if w < 220:
        scale = min(2.0, 300.0 / max(1, w))
        gray = cv2.resize(
            gray,
            (int(round(w * scale)), int(round(h * scale))),
            interpolation=cv2.INTER_CUBIC,
        )
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blur, 50, 150, L2gradient=True)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 3))
    closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=2)
    contours, _ = cv2.findContours(closed, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    contours = sorted(contours, key=cv2.contourArea, reverse=True)[:20]
    rh, rw = gray.shape[:2]
    best: Optional[np.ndarray] = None
    best_area = 0.0
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < 0.20 * rw * rh:
            continue
        peri = cv2.arcLength(contour, True)
        for eps_ratio in (rc.approx_epsilon_ratio, 0.03, 0.05, 0.08):
            approx = cv2.approxPolyDP(contour, eps_ratio * peri, True)
            if len(approx) == 4:
                quad = approx.reshape(4, 2).astype(np.float32) / scale
                if _valid_quad(quad, (h, w), config) and area > best_area:
                    best = order_quad_points(quad)
                    best_area = area
                break
        if best is not None:
            continue
        # Fallback: hình chữ nhật xoay của contour lớn
        rect = cv2.minAreaRect(contour)
        (cx, cy), (rwid, rhei), angle = rect
        if rwid <= 1 or rhei <= 1:
            continue
        # Chuẩn hóa góc về [-45, 45]
        norm_angle = angle
        if norm_angle > 45:
            norm_angle -= 90
        if abs(norm_angle) > 20:
            continue
        box = cv2.boxPoints(((cx, cy), (rwid, rhei), angle)).astype(np.float32)
        quad = box / scale
        if _valid_quad(quad, (h, w), config):
            best = order_quad_points(quad)
            best_area = area
    if best is None:
        return None, "none"
    return best, "perspective"


def _compute_output_size(
    quad: np.ndarray, config: Config
) -> Tuple[int, int]:
    tl, tr, br, bl = order_quad_points(quad)
    width = max(float(np.linalg.norm(tr - tl)), float(np.linalg.norm(br - bl)))
    height = max(float(np.linalg.norm(bl - tl)), float(np.linalg.norm(br - tr)))
    rc = config.rectification
    width = max(width, rc.output_min_width)
    height = max(height, rc.output_min_height)
    ratio = width / max(1.0, height)
    if ratio > rc.max_output_ratio:
        height = width / rc.max_output_ratio
    return int(round(width)), int(round(height))


def _deskew_fallback(
    roi: np.ndarray, config: Config
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, float, str]:
    """Xoay nhẹ ROI nếu phát hiện biển bị nghiêng nhưng không đủ 4 góc."""
    h, w = roi.shape[:2]
    identity = np.eye(3, dtype=np.float64)
    if not config.rectification.fallback_deskew or w < 20 or h < 10:
        return roi.copy(), identity, identity.copy(), 0.0, "bbox"

    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    _, binary = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # Đảm bảo foreground là vùng tối (ký tự/viền) để tìm góc xoay
    border = np.concatenate([binary[0, :], binary[-1, :], binary[:, 0], binary[:, -1]])
    if float(np.mean(border)) > 127:
        binary = cv2.bitwise_not(binary)
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return roi.copy(), identity, identity.copy(), 0.0, "bbox"
    contour = max(contours, key=cv2.contourArea)
    if cv2.contourArea(contour) < 0.10 * w * h:
        return roi.copy(), identity, identity.copy(), 0.0, "bbox"
    (cx, cy), (rw, rh), angle = cv2.minAreaRect(contour)
    if rw < 1 or rh < 1:
        return roi.copy(), identity, identity.copy(), 0.0, "bbox"
    if rw < rh:
        rw, rh = rh, rw
        angle += 90.0
    while angle > 45:
        angle -= 90
    while angle < -45:
        angle += 90
    if abs(angle) < config.rectification.deskew_min_angle:
        return roi.copy(), identity, identity.copy(), 0.0, "bbox"
    if abs(angle) > config.rectification.deskew_max_angle:
        return roi.copy(), identity, identity.copy(), 0.0, "bbox"

    matrix = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), angle, 1.0)
    cos, sin = abs(matrix[0, 0]), abs(matrix[0, 1])
    new_w = int(math.ceil(h * sin + w * cos))
    new_h = int(math.ceil(h * cos + w * sin))
    matrix[0, 2] += new_w / 2.0 - w / 2.0
    matrix[1, 2] += new_h / 2.0 - h / 2.0
    rotated = cv2.warpAffine(
        roi,
        matrix,
        (new_w, new_h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )
    m3 = np.vstack([matrix, [0, 0, 1]]).astype(np.float64)
    inv = cv2.invertAffineTransform(matrix)
    inv3 = np.vstack([inv, [0, 0, 1]]).astype(np.float64)
    return rotated, m3, inv3, float(angle), "deskew"


def rectify_plate(
    image: np.ndarray, candidate: PlateCandidate, config: Config
) -> RectificationResult:
    """Cắt và hiệu chỉnh vùng biển số ứng viên."""
    t0 = time.perf_counter()
    timings: Dict[str, float] = {}
    warnings: List[str] = []
    rc = config.rectification

    t_crop = time.perf_counter()
    crop, roi_bbox = crop_candidate(image, candidate, rc.padding_ratio)
    timings["crop_ms"] = (time.perf_counter() - t_crop) * 1000.0
    if crop.size == 0 or crop.shape[0] < 8 or crop.shape[1] < 16:
        return RectificationResult(
            plate_image=crop,
            plate_gray=cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            if crop.size
            else np.zeros((0, 0), np.uint8),
            method="invalid",
            crop_image=crop,
            roi_bbox=roi_bbox,
            matrix=np.eye(3),
            inverse_matrix=np.eye(3),
            timings_ms={"rectification_total_ms": 0.0},
            warnings=["Vùng cắt quá nhỏ để hiệu chỉnh."],
        )

    t_quad = time.perf_counter()
    quad_local, method = _find_quad_in_roi(crop, config)
    timings["quad_search_ms"] = (time.perf_counter() - t_quad) * 1000.0

    if quad_local is not None and method == "perspective":
        t_warp = time.perf_counter()
        ordered = order_quad_points(quad_local)
        out_w, out_h = _compute_output_size(ordered, config)
        dst = np.array(
            [[0, 0], [out_w - 1, 0], [out_w - 1, out_h - 1], [0, out_h - 1]],
            dtype=np.float32,
        )
        matrix = cv2.getPerspectiveTransform(ordered, dst)
        warped = cv2.warpPerspective(
            crop,
            matrix,
            (out_w, out_h),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_REPLICATE,
        )
        inverse = np.linalg.inv(matrix)
        quad_work = ordered.copy()
        quad_work[:, 0] += roi_bbox[0]
        quad_work[:, 1] += roi_bbox[1]
        timings["warp_ms"] = (time.perf_counter() - t_warp) * 1000.0
        timings["rectification_total_ms"] = (time.perf_counter() - t0) * 1000.0
        return RectificationResult(
            plate_image=warped,
            plate_gray=cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY),
            method="perspective",
            crop_image=crop,
            roi_bbox=roi_bbox,
            matrix=matrix.astype(np.float64),
            inverse_matrix=inverse.astype(np.float64),
            quad=quad_work,
            angle=0.0,
            output_size=(out_w, out_h),
            timings_ms=timings,
            warnings=warnings,
        )

    # Phương án dự phòng: crop bbox hoặc xoay nhẹ
    t_deskew = time.perf_counter()
    plate, matrix, inverse, angle, fallback_method = _deskew_fallback(crop, config)
    timings["deskew_ms"] = (time.perf_counter() - t_deskew) * 1000.0
    if fallback_method == "bbox":
        warnings.append("Không tìm được 4 góc tin cậy; dùng crop bounding box.")
    else:
        warnings.append(
            f"Không tìm được 4 góc tin cậy; dùng hiệu chỉnh xoay nhẹ ({angle:.1f}°)."
        )
    timings["rectification_total_ms"] = (time.perf_counter() - t0) * 1000.0
    return RectificationResult(
        plate_image=plate,
        plate_gray=cv2.cvtColor(plate, cv2.COLOR_BGR2GRAY),
        method=fallback_method,
        crop_image=crop,
        roi_bbox=roi_bbox,
        matrix=matrix,
        inverse_matrix=inverse,
        quad=None,
        angle=angle,
        output_size=(plate.shape[1], plate.shape[0]),
        timings_ms=timings,
        warnings=warnings,
    )


def map_rectified_bbox_to_work(
    result: RectificationResult, bbox: Sequence[float]
) -> Tuple[float, float, float, float]:
    """Ánh xạ bbox trong ảnh biển đã hiệu chỉnh về ảnh work."""
    x1, y1, x2, y2 = [float(v) for v in bbox]
    pts = np.array(
        [[x1, y1], [x2, y1], [x2, y2], [x1, y2]], dtype=np.float32
    )
    mapped = result.map_points_to_work(pts)
    return (
        float(mapped[:, 0].min()),
        float(mapped[:, 1].min()),
        float(mapped[:, 0].max()),
        float(mapped[:, 1].max()),
    )

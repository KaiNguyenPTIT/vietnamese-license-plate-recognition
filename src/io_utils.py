"""Các tiện ích đọc/ghi ảnh và hình học dùng chung.

Lưu ý: ``cv2.imread``/``cv2.imwrite`` không xử lý tốt đường dẫn Unicode trên
Windows, vì vậy module này dùng ``np.fromfile`` + ``cv2.imdecode`` và
``cv2.imencode`` + ``Path.write_bytes``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, Optional, Sequence, Tuple

import cv2
import numpy as np


class ImageIOError(RuntimeError):
    """Không đọc/ghi được ảnh."""


def read_image(path: str | Path) -> np.ndarray:
    """Đọc ảnh màu BGR, hỗ trợ đường dẫn Unicode."""
    p = Path(path)
    if not p.exists() or not p.is_file():
        raise ImageIOError(f"Không tìm thấy tệp ảnh: {p}")
    try:
        data = np.fromfile(str(p), dtype=np.uint8)
    except OSError as exc:  # pragma: no cover - phụ thuộc hệ thống
        raise ImageIOError(f"Không đọc được tệp: {p} ({exc})") from exc
    if data.size == 0:
        raise ImageIOError(f"Tệp rỗng hoặc không phải ảnh: {p}")
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None or image.size == 0:
        raise ImageIOError(f"OpenCV không giải mã được ảnh: {p}")
    return image


def write_image(path: str | Path, image: np.ndarray, jpeg_quality: int = 95) -> Path:
    """Ghi ảnh, hỗ trợ đường dẫn Unicode. Trả về đường dẫn đã ghi."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if image is None or image.size == 0:
        raise ImageIOError(f"Ảnh rỗng, không thể ghi: {p}")
    ext = p.suffix.lower()
    if ext not in {".jpg", ".jpeg", ".png", ".bmp"}:
        ext = ".png"
        p = p.with_suffix(".png")
    params: list[int] = []
    if ext in {".jpg", ".jpeg"}:
        params = [cv2.IMWRITE_JPEG_QUALITY, int(jpeg_quality)]
    ok, buf = cv2.imencode(ext, image, params)
    if not ok:
        raise ImageIOError(f"Không mã hóa được ảnh để ghi: {p}")
    p.write_bytes(buf.tobytes())
    return p


def ensure_bgr(image: np.ndarray) -> np.ndarray:
    """Chuẩn hóa ảnh về 3 kênh BGR."""
    if image is None:
        raise ValueError("Ảnh đầu vào là None")
    if image.ndim == 2:
        return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    if image.shape[2] == 4:
        return cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
    return image


def ensure_gray(image: np.ndarray) -> np.ndarray:
    if image is None:
        raise ValueError("Ảnh đầu vào là None")
    if image.ndim == 2:
        return image
    if image.shape[2] == 4:
        return cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY)
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def resize_keep_aspect(
    image: np.ndarray, width: Optional[int] = None, height: Optional[int] = None,
    interp: int = cv2.INTER_AREA,
) -> np.ndarray:
    """Resize giữ tỷ lệ theo một cạnh cho trước."""
    h, w = image.shape[:2]
    if width is None and height is None:
        return image.copy()
    if width is not None:
        scale = float(width) / max(1, w)
    else:
        scale = float(height) / max(1, h)
    nw = max(1, int(round(w * scale)))
    nh = max(1, int(round(h * scale)))
    return cv2.resize(image, (nw, nh), interpolation=interp)


def bbox_area(bbox: Sequence[float]) -> float:
    x1, y1, x2, y2 = bbox
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def bbox_iou(a: Sequence[float], b: Sequence[float]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    if inter <= 0:
        return 0.0
    union = bbox_area(a) + bbox_area(b) - inter
    return float(inter / union) if union > 0 else 0.0


def bbox_to_int(bbox: Sequence[float], shape: Tuple[int, int]) -> Tuple[int, int, int, int]:
    """Chuyển bbox float sang int và kẹp trong kích thước ảnh (h, w)."""
    h, w = shape
    x1, y1, x2, y2 = [int(round(v)) for v in bbox]
    x1, x2 = sorted((max(0, min(x1, w)), max(0, min(x2, w))))
    y1, y2 = sorted((max(0, min(y1, h)), max(0, min(y2, h))))
    return x1, y1, x2, y2


def order_quad_points(points: np.ndarray) -> np.ndarray:
    """Sắp 4 điểm theo thứ tự trái-trên, phải-trên, phải-dưới, trái-dưới.

    Dùng tổng và hiệu tọa độ, sau đó kiểm tra lại để tránh trường hợp suy biến.
    """
    pts = np.asarray(points, dtype=np.float32).reshape(4, 2)
    order = np.argsort(pts[:, 0])
    left = pts[order[:2]]
    right = pts[order[2:]]
    left = left[np.argsort(left[:, 1])]
    right = right[np.argsort(right[:, 1])]
    tl, bl = left[0], left[1]
    tr, br = right[0], right[1]
    return np.array([tl, tr, br, bl], dtype=np.float32)


def is_convex_quad(points: np.ndarray) -> bool:
    pts = np.asarray(points, dtype=np.float32).reshape(-1, 2)
    if len(pts) != 4:
        return False
    contour = pts.reshape(-1, 1, 2)
    if not cv2.isContourConvex(contour):
        return False
    area = cv2.contourArea(contour)
    if area <= 1:
        return False
    # Kiểm tra đa giác không tự cắt thông qua dấu của tích chéo
    signs = []
    for i in range(4):
        p0 = pts[i]
        p1 = pts[(i + 1) % 4]
        p2 = pts[(i + 2) % 4]
        cross = (p1[0] - p0[0]) * (p2[1] - p1[1]) - (p1[1] - p0[1]) * (
            p2[0] - p1[0]
        )
        if abs(cross) < 1e-6:
            return False
        signs.append(np.sign(cross))
    return len(set(signs)) == 1


def expand_bbox(
    bbox: Sequence[float], ratio: float, shape: Tuple[int, int]
) -> Tuple[int, int, int, int]:
    x1, y1, x2, y2 = bbox
    w, h = x2 - x1, y2 - y1
    pad_x, pad_y = w * ratio, h * ratio
    return bbox_to_int((x1 - pad_x, y1 - pad_y, x2 + pad_x, y2 + pad_y), shape)


def safe_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_") or "image"


def list_images(directory: str | Path, extensions: Iterable[str]) -> list[Path]:
    exts = {e.lower() if e.startswith(".") else "." + e.lower() for e in extensions}
    p = Path(directory)
    if not p.exists():
        return []
    return sorted(
        [f for f in p.iterdir() if f.is_file() and f.suffix.lower() in exts]
    )


def crop_safe(image: np.ndarray, bbox: Sequence[int]) -> np.ndarray:
    h, w = image.shape[:2]
    x1, y1, x2, y2 = bbox_to_int(bbox, (h, w))
    if x2 <= x1 or y2 <= y1:
        return image[0:0, 0:0].copy()
    return image[y1:y2, x1:x2].copy()

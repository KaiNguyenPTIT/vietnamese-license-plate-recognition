"""Tiền xử lý ảnh: đọc, resize, grayscale, khử nhiễu, CLAHE, Canny, threshold.

Mỗi bước đều ghi lại thời gian để phục vụ đánh giá hiệu năng.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from .config import Config, PreprocessingConfig
from .io_utils import ImageIOError, read_image


class InvalidImageError(RuntimeError):
    """Ảnh đầu vào không hợp lệ (không đọc được, quá nhỏ, sai định dạng...)."""


@dataclass
class PreprocessResult:
    image_path: str
    original: np.ndarray
    work_image: np.ndarray
    gray: np.ndarray
    blurred: np.ndarray
    enhanced: np.ndarray
    edges: np.ndarray
    binary: np.ndarray
    binary_otsu: np.ndarray
    binary_adaptive: np.ndarray
    scale: float
    timings_ms: Dict[str, float] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    image_size: Tuple[int, int] = (0, 0)
    work_size: Tuple[int, int] = (0, 0)


def ensure_odd(value: int, minimum: int = 3) -> int:
    value = int(max(minimum, value))
    return value if value % 2 == 1 else value + 1


def gaussian_blur(gray: np.ndarray, kernel: int) -> np.ndarray:
    k = ensure_odd(kernel, 3)
    return cv2.GaussianBlur(gray, (k, k), 0)


def median_blur(gray: np.ndarray, kernel: int) -> np.ndarray:
    k = ensure_odd(kernel, 3)
    return cv2.medianBlur(gray, k)


def bilateral_filter(gray: np.ndarray) -> np.ndarray:
    return cv2.bilateralFilter(gray, d=7, sigmaColor=50, sigmaSpace=50)


def apply_blur(gray: np.ndarray, method: str, gaussian_kernel: int, median_kernel: int) -> np.ndarray:
    method = (method or "gaussian").lower()
    if method == "gaussian":
        return gaussian_blur(gray, gaussian_kernel)
    if method == "median":
        return median_blur(gray, median_kernel)
    if method == "bilateral":
        return bilateral_filter(gray)
    if method in {"none", "no", "off"}:
        return gray.copy()
    raise ValueError(f"Phương pháp khử nhiễu không hợp lệ: {method}")


def apply_clahe(
    gray: np.ndarray, clip_limit: float = 2.0, tile_grid: Tuple[int, int] = (8, 8)
) -> np.ndarray:
    tile = (max(1, int(tile_grid[0])), max(1, int(tile_grid[1])))
    clahe = cv2.createCLAHE(clipLimit=float(clip_limit), tileGridSize=tile)
    return clahe.apply(gray)


def auto_canny_thresholds(gray: np.ndarray) -> Tuple[int, int]:
    med = float(np.median(gray))
    sigma = 0.33
    low = int(max(0, (1.0 - sigma) * med))
    high = int(min(255, (1.0 + sigma) * med))
    if high <= low:
        high = min(255, low + 30)
    return low, high


def detect_edges(
    gray: np.ndarray,
    canny_low: int,
    canny_high: int,
    auto_canny: bool = False,
) -> np.ndarray:
    low, high = canny_low, canny_high
    if auto_canny:
        low, high = auto_canny_thresholds(gray)
    return cv2.Canny(gray, int(low), int(high), L2gradient=True)


def threshold_otsu(gray: np.ndarray) -> Tuple[np.ndarray, float]:
    value, binary = cv2.threshold(
        gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )
    return binary, float(value)


def threshold_adaptive(
    gray: np.ndarray, block_size: int = 11, c: int = 2
) -> np.ndarray:
    block = ensure_odd(block_size, 3)
    return cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        block,
        int(c),
    )


def binarize(
    gray: np.ndarray,
    method: str = "otsu",
    adaptive_block_size: int = 11,
    adaptive_c: int = 2,
) -> Tuple[np.ndarray, np.ndarray]:
    """Trả về (binary chính, binary otsu). Luôn tính Otsu để làm fallback."""
    otsu, _ = threshold_otsu(gray)
    method = (method or "otsu").lower()
    if method == "adaptive":
        return threshold_adaptive(gray, adaptive_block_size, adaptive_c), otsu
    return otsu, otsu


def resize_for_processing(
    image: np.ndarray, max_side: int
) -> Tuple[np.ndarray, float]:
    """Thu nhỏ nếu cạnh dài vượt ngưỡng; trả về ảnh và hệ số scale."""
    h, w = image.shape[:2]
    longest = max(h, w)
    if longest <= max_side:
        return image.copy(), 1.0
    scale = float(max_side) / float(longest)
    new_w = max(1, int(round(w * scale)))
    new_h = max(1, int(round(h * scale)))
    resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)
    return resized, scale


def preprocess_image(image: np.ndarray, config: Config) -> PreprocessResult:
    """Tiền xử lý một ảnh BGR đã đọc sẵn (dùng cho test và pipeline)."""
    if image is None or image.size == 0:
        raise InvalidImageError("Ảnh rỗng hoặc không giải mã được")
    if image.ndim not in (2, 3):
        raise InvalidImageError("Số chiều ảnh không hợp lệ")
    if image.ndim == 2:
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    elif image.shape[2] == 4:
        image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
    elif image.shape[2] != 3:
        raise InvalidImageError("Số kênh màu không hợp lệ")

    h, w = image.shape[:2]
    if min(h, w) < config.image.min_side:
        raise InvalidImageError(
            f"Ảnh quá nhỏ ({w}x{h}px), cần cạnh nhỏ nhất >= "
            f"{config.image.min_side}px"
        )
    if h * w > 60_000_000:
        raise InvalidImageError("Ảnh quá lớn để xử lý an toàn (> 60MP)")

    timings: Dict[str, float] = {}
    warnings: List[str] = []
    t_all = time.perf_counter()

    t0 = time.perf_counter()
    work, scale = resize_for_processing(image, config.image.max_side)
    timings["resize_ms"] = (time.perf_counter() - t0) * 1000.0

    t0 = time.perf_counter()
    gray = cv2.cvtColor(work, cv2.COLOR_BGR2GRAY)
    timings["gray_ms"] = (time.perf_counter() - t0) * 1000.0

    pc = config.preprocessing
    t0 = time.perf_counter()
    blurred = apply_blur(gray, pc.blur_method, pc.gaussian_kernel, pc.median_kernel)
    timings["blur_ms"] = (time.perf_counter() - t0) * 1000.0

    t0 = time.perf_counter()
    if pc.use_clahe:
        enhanced = apply_clahe(blurred, pc.clahe_clip_limit, pc.clahe_tile_grid)
    else:
        enhanced = blurred.copy()
        if float(np.std(gray)) < 35.0:
            warnings.append(
                "Ảnh có độ tương phản thấp; nên bật CLAHE để cải thiện kết quả."
            )
    timings["enhance_ms"] = (time.perf_counter() - t0) * 1000.0

    t0 = time.perf_counter()
    edges = detect_edges(
        enhanced, pc.canny_low, pc.canny_high, pc.auto_canny
    )
    timings["canny_ms"] = (time.perf_counter() - t0) * 1000.0

    t0 = time.perf_counter()
    binary_otsu, _ = threshold_otsu(enhanced)
    binary_adaptive = threshold_adaptive(
        enhanced, pc.adaptive_block_size, pc.adaptive_c
    )
    if pc.threshold_method.lower() == "adaptive":
        binary = binary_adaptive
    else:
        binary = binary_otsu
    timings["threshold_ms"] = (time.perf_counter() - t0) * 1000.0

    timings["preprocess_total_ms"] = (time.perf_counter() - t_all) * 1000.0
    return PreprocessResult(
        image_path="",
        original=image,
        work_image=work,
        gray=gray,
        blurred=blurred,
        enhanced=enhanced,
        edges=edges,
        binary=binary,
        binary_otsu=binary_otsu,
        binary_adaptive=binary_adaptive,
        scale=scale,
        timings_ms=timings,
        warnings=warnings,
        image_size=(w, h),
        work_size=(work.shape[1], work.shape[0]),
    )


def preprocess(image_path: str | Path, config: Config) -> PreprocessResult:
    """Đọc và tiền xử lý ảnh từ đường dẫn."""
    path = Path(image_path)
    if path.suffix.lower() not in {e.lower() for e in config.image.allowed_extensions}:
        # Vẫn thử đọc, nhưng cảnh báo để người dùng biết ngoài phạm vi hỗ trợ.
        pass
    try:
        image = read_image(path)
    except ImageIOError as exc:
        raise InvalidImageError(str(exc)) from exc
    result = preprocess_image(image, config)
    result.image_path = str(path)
    if path.suffix.lower() not in {e.lower() for e in config.image.allowed_extensions}:
        result.warnings.append(
            f"Định dạng {path.suffix} ngoài danh sách hỗ trợ "
            f"{config.image.allowed_extensions}; vẫn xử lý nhưng không khuyến nghị."
        )
    return result


def compute_contrast(gray: np.ndarray) -> float:
    return float(np.std(gray))


def apply_histogram_equalization(gray: np.ndarray) -> np.ndarray:
    return cv2.equalizeHist(gray)

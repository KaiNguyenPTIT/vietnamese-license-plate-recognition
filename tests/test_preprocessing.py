"""Kiểm thử tiền xử lý ảnh."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from src.config import Config
from src.preprocessing import (
    InvalidImageError,
    preprocess,
    preprocess_image,
)


def _make_image(height: int = 120, width: int = 320) -> np.ndarray:
    image = np.full((height, width, 3), 230, dtype=np.uint8)
    cv2.rectangle(image, (20, 20), (width - 20, height - 20), (20, 20, 20), 2)
    cv2.putText(
        image,
        "51F12345",
        (30, height - 40),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.9,
        (10, 10, 10),
        2,
        cv2.LINE_AA,
    )
    return image


def test_preprocess_image_returns_all_stages(config: Config) -> None:
    result = preprocess_image(_make_image(), config)
    assert result.original.shape[:2] == (120, 320)
    assert result.work_image.ndim == 3
    assert result.gray.ndim == 2
    assert result.edges.ndim == 2
    assert result.binary_otsu.ndim == 2
    assert result.binary_adaptive.ndim == 2
    assert result.scale > 0
    assert "preprocess_total_ms" in result.timings_ms


def test_grayscale_input_is_converted_to_bgr(config: Config) -> None:
    gray = cv2.cvtColor(_make_image(), cv2.COLOR_BGR2GRAY)
    result = preprocess_image(gray, config)
    assert result.work_image.ndim == 3
    assert result.work_image.shape[2] == 3


def test_large_image_is_scaled_to_max_side(config: Config) -> None:
    image = _make_image(height=1000, width=2000)
    result = preprocess_image(image, config)
    max_side = max(result.work_image.shape[:2])
    assert max_side <= config.image.max_side
    assert result.scale < 1.0


def test_too_small_image_raises(config: Config) -> None:
    image = np.zeros((20, 30, 3), dtype=np.uint8)
    with pytest.raises(InvalidImageError):
        preprocess_image(image, config)


def test_none_image_raises(config: Config) -> None:
    with pytest.raises(InvalidImageError):
        preprocess_image(None, config)  # type: ignore[arg-type]


def test_missing_file_raises(config: Config, tmp_path: Path) -> None:
    with pytest.raises(InvalidImageError):
        preprocess(tmp_path / "khong_co.jpg", config)


def test_preprocess_sample_file(config: Config, samples_dir: Path) -> None:
    result = preprocess(samples_dir / "dev_clear_001.jpg", config)
    assert result.image_path.endswith("dev_clear_001.jpg")
    assert result.original.size > 0
    assert result.work_size[0] > 0 and result.work_size[1] > 0

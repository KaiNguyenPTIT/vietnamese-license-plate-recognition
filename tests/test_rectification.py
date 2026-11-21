"""Kiểm thử hiệu chỉnh phối cảnh."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from src.config import Config
from src.plate_detection import detect_plates
from src.plate_rectification import (
    map_rectified_bbox_to_work,
    rectify_plate,
)
from src.preprocessing import preprocess


@pytest.fixture(scope="module")
def rectified(config: Config, samples_dir: Path):
    pre = preprocess(samples_dir / "dev_clear_001.jpg", config)
    detection = detect_plates(pre, config)
    candidate = detection.candidates[0]
    return rectify_plate(pre.work_image, candidate, config), candidate


def test_rectification_returns_plate_image(rectified) -> None:
    result, candidate = rectified
    assert result.method in {"perspective", "deskew", "bbox"}
    assert result.plate_image.size > 0
    assert result.plate_image.ndim == 3
    assert result.plate_gray.ndim == 2
    height, width = result.plate_image.shape[:2]
    assert width >= 60 and height >= 20
    ratio = width / height
    assert 1.0 < ratio <= 8.0
    assert result.output_size == (width, height)


def test_rectification_has_invertible_matrix(rectified) -> None:
    result, _ = rectified
    identity = result.matrix @ result.inverse_matrix
    identity = identity / identity[2, 2]
    assert np.allclose(identity, np.eye(3), atol=1e-5)


def test_map_points_back_to_work_image(rectified) -> None:
    result, _ = rectified
    height, width = result.plate_image.shape[:2]
    mapped = result.map_points_to_work(
        np.array([[0, 0], [width - 1, height - 1]], dtype=np.float32)
    )
    assert mapped.shape == (2, 2)
    roi_x1, roi_y1, roi_x2, roi_y2 = result.roi_bbox
    assert roi_x1 <= mapped[0, 0] <= roi_x2
    assert roi_y1 <= mapped[0, 1] <= roi_y2
    assert roi_x1 <= mapped[1, 0] <= roi_x2
    assert roi_y1 <= mapped[1, 1] <= roi_y2


def test_map_bbox_to_work(rectified) -> None:
    result, _ = rectified
    height, width = result.plate_image.shape[:2]
    bbox = map_rectified_bbox_to_work(
        result, (0, 0, width - 1, height - 1)
    )
    x1, y1, x2, y2 = bbox
    assert x2 > x1 and y2 > y1
    assert x1 >= result.roi_bbox[0] - 1
    assert y1 >= result.roi_bbox[1] - 1
    assert x2 <= result.roi_bbox[2] + 1
    assert y2 <= result.roi_bbox[3] + 1


def test_quad_has_four_points_when_perspective(rectified) -> None:
    result, _ = rectified
    if result.method == "perspective":
        assert result.quad is not None
        assert result.quad.shape == (4, 2)
    else:
        # Phương án deskew/bbox vẫn phải có ma trận hợp lệ.
        assert result.matrix.shape == (3, 3)

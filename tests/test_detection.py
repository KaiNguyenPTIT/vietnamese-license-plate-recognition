"""Kiểm thử phát hiện biển số và cắt ứng viên."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from src.config import Config
from src.io_utils import bbox_iou
from src.plate_detection import (
    PlateCandidate,
    _attach_text_bbox_hints,
    character_like_count,
    crop_candidate,
    detect_plates,
    select_top_candidates,
)
from src.preprocessing import preprocess


@pytest.fixture(scope="module")
def clear_detection(config: Config, samples_dir: Path):
    pre = preprocess(samples_dir / "dev_clear_001.jpg", config)
    return pre, detect_plates(pre, config)


def test_detects_plate_in_clear_image(clear_detection) -> None:
    pre, detection = clear_detection
    assert detection.candidates, "Ảnh biển rõ phải có ít nhất một ứng viên"
    best = detection.candidates[0]
    assert best.passed
    assert best.score > 0.5
    assert detection.closed is not None
    assert detection.timings_ms.get("detection_total_ms", -1) >= 0
    # Ứng viên tốt nhất phải trùng vị trí biển thật (nhãn trong labels.csv).
    assert bbox_iou(best.bbox_original, (339.0, 455.0, 622.0, 517.0)) >= 0.5
    assert pre.work_size[0] > 0


def test_candidate_has_explainable_scores(clear_detection) -> None:
    _, detection = clear_detection
    candidate = detection.candidates[0]
    assert set(candidate.score_components) >= {"ratio", "area", "edge", "fill"}
    assert 0.0 <= candidate.score <= 1.0
    assert candidate.width > 0 and candidate.height > 0
    assert candidate.ratio == pytest.approx(candidate.width / candidate.height)


def test_select_top_candidates(clear_detection) -> None:
    _, detection = clear_detection
    top = select_top_candidates(detection, top_k=1)
    assert len(top) == 1
    assert top[0] is detection.candidates[0]
    assert len(select_top_candidates(detection)) == len(detection.candidates)


def _make_candidate(
    bbox: tuple[float, float, float, float],
    source: str,
    *,
    passed: bool = True,
    score: float = 0.9,
    text_likeness: float = 1.0,
) -> PlateCandidate:
    x1, y1, x2, y2 = bbox
    return PlateCandidate(
        bbox=bbox,
        bbox_original=bbox,
        area=(x2 - x1) * (y2 - y1),
        area_ratio=0.05,
        ratio=(x2 - x1) / max(1.0, y2 - y1),
        edge_density=0.2,
        fill_ratio=0.8,
        text_likeness=text_likeness,
        score=score,
        score_components={},
        source=source,
        passed=passed,
    )


def test_text_candidate_gets_geometric_bbox_hint(config: Config) -> None:
    geometric = _make_candidate((0.0, 0.0, 200.0, 100.0), "edges_quads")
    text = _make_candidate((20.0, 20.0, 180.0, 80.0), "text_row_otsu")
    hints = _attach_text_bbox_hints([text], [geometric], config)
    assert hints[0].bbox_hint == geometric.bbox
    assert hints[0].bbox_hint_original == geometric.bbox_original
    assert hints[0].bbox == (20.0, 20.0, 180.0, 80.0)

    oversized = _make_candidate((0.0, 0.0, 2000.0, 1000.0), "edges_quads")
    text2 = _make_candidate((20.0, 20.0, 40.0, 40.0), "text_row_otsu")
    assert _attach_text_bbox_hints([text2], [oversized], config)[0].bbox_hint is None


def test_crop_candidate_respects_padding(clear_detection, config: Config) -> None:
    pre, detection = clear_detection
    candidate = detection.candidates[0]
    crop, box = crop_candidate(
        pre.work_image,
        candidate,
        config.rectification.padding_ratio,
        config.rectification.vertical_padding_ratio,
    )
    assert crop.size > 0
    x1, y1, x2, y2 = box
    assert 0 <= x1 < x2 <= pre.work_image.shape[1]
    assert 0 <= y1 < y2 <= pre.work_image.shape[0]
    # Cắt có padding phải rộng hơn bounding box gốc.
    assert x2 - x1 >= candidate.width
    assert y2 - y1 >= candidate.height


def test_character_like_count_is_nonnegative(clear_detection) -> None:
    pre, detection = clear_detection
    x1, y1, x2, y2 = [int(v) for v in detection.candidates[0].bbox]
    roi = pre.gray[y1:y2, x1:x2]
    count = character_like_count(roi)
    assert isinstance(count, int)
    assert count >= 0
    assert count >= 5, "Vùng biển rõ phải có nhiều thành phần giống ký tự"


def test_no_plate_image_has_no_candidates(config: Config, samples_dir: Path) -> None:
    pre = preprocess(samples_dir / "dev_no_plate_001.jpg", config)
    detection = detect_plates(pre, config)
    # Ảnh không biển có thể còn vài ứng viên hình học, nhưng không được có
    # ứng viên đã vượt kiểm tra hình học/text-likeness.
    assert not any(c.passed for c in detection.candidates)

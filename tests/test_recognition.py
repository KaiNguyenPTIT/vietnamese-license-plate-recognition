"""Kiểm thử chuẩn hóa ký tự và Template Matching."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from src.character_recognition import (
    EmptyCharacterError,
    TemplateLibrary,
    _count_holes,
    _open_top_four_variants,
    load_templates,
    normalize_character,
    recognize_character,
    recognize_characters,
)
from src.config import Config
from src.io_utils import read_image


def test_template_library_is_complete(template_library: TemplateLibrary) -> None:
    stats = template_library.stats()
    assert stats["labels"] == 36
    assert stats["missing_labels"] == []
    assert stats["templates"] > 1000
    assert stats["coarse_templates"] > 0
    for label in "0123456789ABCDEFGHKLMNPSTUVXYZ":
        assert label in template_library.templates
        assert len(template_library.templates[label]) > 0


@pytest.mark.parametrize("label", ["A", "7", "8"])
def test_template_recognizes_itself(
    label: str, config: Config, template_library: TemplateLibrary
) -> None:
    template_path = config.templates_dir / label / "arial_bold_normal.png"
    assert template_path.exists()
    image = read_image(template_path)
    prediction = recognize_character(image, template_library, config)
    assert prediction.status == "OK"
    assert prediction.best_label == label
    assert prediction.score > 0.95
    assert prediction.margin >= 0
    assert prediction.ranked
    assert prediction.normalized_image is not None
    assert prediction.normalized_image.shape == (
        config.recognition.normalized_height,
        config.recognition.normalized_width,
    )


def test_normalize_character_output_shape(config: Config) -> None:
    image = np.zeros((40, 30), dtype=np.uint8)
    image[5:35, 8:22] = 255
    normalized = normalize_character(
        image,
        width=config.recognition.normalized_width,
        height=config.recognition.normalized_height,
        padding=config.recognition.padding,
    )
    assert normalized.shape == (
        config.recognition.normalized_height,
        config.recognition.normalized_width,
    )
    assert normalized.dtype == np.uint8
    assert np.count_nonzero(normalized) > 0


def test_normalize_empty_character_raises() -> None:
    with pytest.raises(EmptyCharacterError):
        normalize_character(np.zeros((20, 20), dtype=np.uint8))


def test_count_holes_distinguishes_ring_from_solid() -> None:
    ring = np.zeros((40, 30), dtype=np.uint8)
    ring[4:36, 4:26] = 255
    ring[12:28, 10:20] = 0
    assert _count_holes(ring, min_area=25.0) == 1

    solid = np.zeros((40, 30), dtype=np.uint8)
    solid[4:36, 4:26] = 255
    assert _count_holes(solid, min_area=25.0) == 0


def test_open_top_four_variant_clears_only_top_right() -> None:
    template = np.zeros((48, 32), dtype=np.uint8)
    template[4:44, 4:28] = 255
    variants = _open_top_four_variants([template])
    assert len(variants) == 1
    variant = variants[0]
    assert variant.shape == template.shape
    assert np.count_nonzero(variant[:24, 16:]) == 0
    assert np.count_nonzero(variant[24:, 16:]) > 0
    # Không làm thay đổi template gốc.
    assert np.count_nonzero(template[:24, 16:]) > 0


def test_empty_character_returns_empty_status(
    config: Config, template_library: TemplateLibrary
) -> None:
    prediction = recognize_character(
        np.zeros((20, 20), dtype=np.uint8), template_library, config
    )
    assert prediction.status == "EMPTY"
    assert prediction.label == "?"
    assert prediction.score == 0.0


def test_empty_library_returns_unknown(config: Config) -> None:
    image = np.zeros((40, 30), dtype=np.uint8)
    image[5:35, 8:22] = 255
    prediction = recognize_character(image, TemplateLibrary(), config)
    assert prediction.status == "UNKNOWN"
    assert prediction.label == "?"


def test_recognize_characters_batch(
    config: Config, template_library: TemplateLibrary
) -> None:
    image = read_image(config.templates_dir / "A" / "arial_bold_normal.png")
    predictions, timings = recognize_characters([image, image], template_library, config)
    assert len(predictions) == 2
    assert timings["recognition_total_ms"] >= 0
    assert all(p.best_label == "A" for p in predictions)


def test_missing_template_directory_raises(config: Config, tmp_path: Path) -> None:
    from src.character_recognition import TemplateError

    with pytest.raises(TemplateError):
        load_templates(tmp_path / "khong_co_template", config)

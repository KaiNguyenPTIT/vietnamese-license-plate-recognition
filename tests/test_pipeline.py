"""Kiểm thử tích hợp pipeline nhận dạng."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.config import Config, load_config
from src.pipeline import LicensePlateRecognizer
from src.postprocessing import normalize_ground_truth


def test_recognize_clear_sample(recognizer: LicensePlateRecognizer, config: Config) -> None:
    result = recognizer.recognize(config.samples_dir / "dev_clear_001.jpg")
    assert result.status == "SUCCESS"
    assert normalize_ground_truth(result.detected_text) == "88Y79730"
    assert result.text is not None and result.text.validation.is_valid
    assert result.detection is not None and result.detection.candidates
    assert result.selected_attempt is not None
    assert result.plate_image is not None and result.plate_image.size > 0
    assert result.segmentation is not None
    assert result.segmentation.count == 8
    assert result.bbox_original is not None
    assert result.timings_ms.get("recognition", 0) > 0


def test_result_as_dict_is_json_serializable(
    recognizer: LicensePlateRecognizer, config: Config
) -> None:
    result = recognizer.recognize(config.samples_dir / "dev_clear_001.jpg")
    payload = result.as_dict()
    encoded = json.dumps(payload, ensure_ascii=False)
    assert "88Y" in encoded
    assert payload["status"] == "SUCCESS"
    assert payload["attempts"]


def test_no_plate_sample(recognizer: LicensePlateRecognizer, config: Config) -> None:
    result = recognizer.recognize(config.samples_dir / "dev_no_plate_001.jpg")
    assert result.status == "PLATE_NOT_FOUND"
    assert result.bbox_original is None
    assert result.text is None
    assert "Không tìm thấy" in result.message


def test_invalid_image_path(recognizer: LicensePlateRecognizer, tmp_path: Path) -> None:
    result = recognizer.recognize(tmp_path / "khong_ton_tai.jpg")
    assert result.status == "INVALID_IMAGE"
    assert result.errors


def test_corrupt_image_file(recognizer: LicensePlateRecognizer, tmp_path: Path) -> None:
    path = tmp_path / "hong.jpg"
    path.write_bytes(b"day khong phai la anh JPEG")
    result = recognizer.recognize(path)
    assert result.status == "INVALID_IMAGE"
    assert result.errors


def test_missing_templates_returns_config_error(
    config: Config, tmp_path: Path
) -> None:
    broken = LicensePlateRecognizer(config, templates_dir=tmp_path / "khong_co")
    assert broken.template_error
    result = broken.recognize(config.samples_dir / "dev_clear_001.jpg")
    assert result.status == "CONFIG_ERROR"
    assert "template" in result.message.lower()


def test_config_can_disable_template_failure(config: Config, tmp_path: Path) -> None:
    cfg = load_config(overrides={"pipeline.fail_on_missing_templates": False})
    broken = LicensePlateRecognizer(cfg, templates_dir=tmp_path / "khong_co")
    result = broken.recognize(cfg.samples_dir / "dev_clear_001.jpg")
    # Không còn CONFIG_ERROR; pipeline vẫn chạy và từ chối ở mức ký tự.
    assert result.status != "CONFIG_ERROR"


def test_debug_saving(
    recognizer: LicensePlateRecognizer, config: Config, tmp_path: Path
) -> None:
    result = recognizer.recognize(
        config.samples_dir / "dev_clear_001.jpg",
        save_debug=True,
        debug_dir=tmp_path / "debug",
    )
    assert result.debug_dir is not None
    debug_dir = Path(result.debug_dir)
    assert debug_dir.exists()
    files = sorted(p.name for p in debug_dir.iterdir())
    assert any(name.startswith("01_original") for name in files)
    assert any(name.startswith("12_plate_rectified") for name in files)

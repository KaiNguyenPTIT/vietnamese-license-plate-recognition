"""Kiểm thử cấu hình tập trung."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.config import Config, load_config, save_config


def test_load_default_config(config: Config) -> None:
    assert isinstance(config, Config)
    assert config.config_path is not None and config.config_path.exists()
    assert config.image.allowed_extensions == [".jpg", ".jpeg", ".png", ".webp"]
    assert 0 < config.evaluation.iou_threshold <= 1
    assert config.rectification.padding_ratio >= 0
    assert config.rectification.vertical_padding_ratio >= 0
    # Trọng số phát hiện phải được chuẩn hóa về 1.
    weights = config.detection.weights.normalized()
    assert abs(weights.ratio + weights.area + weights.edge + weights.fill - 1.0) < 1e-9


def test_dotted_override_is_applied() -> None:
    cfg = load_config(
        overrides={
            "recognition.method": "pixel",
            "rectification.padding_ratio": 0.2,
        }
    )
    assert cfg.recognition.method == "pixel"
    assert cfg.rectification.padding_ratio == pytest.approx(0.2)


def test_section_override_is_merged() -> None:
    cfg = load_config(overrides={"recognition": {"coarse_top_labels": 12}})
    assert cfg.recognition.coarse_top_labels == 12
    # Các khóa không ghi đè vẫn giữ giá trị gốc.
    assert cfg.recognition.normalized_width == 32


def test_missing_config_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "khong_ton_tai.yaml")


def test_invalid_yaml_structure_raises(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("- 1\n- 2\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(path)


def test_save_and_reload_roundtrip(config: Config, tmp_path: Path) -> None:
    out = tmp_path / "saved.yaml"
    save_config(config, out)
    assert out.exists()
    reloaded = load_config(out)
    assert reloaded.recognition.method == config.recognition.method
    assert reloaded.segmentation.plate_width == config.segmentation.plate_width
    assert reloaded.postprocessing.patterns == config.postprocessing.patterns


def test_resolve_paths_are_absolute(config: Config) -> None:
    assert config.templates_dir.is_absolute()
    assert config.samples_dir.is_absolute()
    assert config.labels_file.is_absolute()

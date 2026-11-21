"""Kiểm thử đánh giá, căn chỉnh chuỗi và xuất báo cáo."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from src.config import Config
from src.evaluation import (
    LabelRow,
    align_strings,
    compute_summary,
    load_labels,
    run_evaluation,
    write_evaluation_csv,
    write_summary_json,
    write_summary_markdown,
)
from src.pipeline import LicensePlateRecognizer


def test_align_identical_strings() -> None:
    stats = align_strings("51F12345", "51F12345")
    assert stats == {
        "matches": 8,
        "substitutions": 0,
        "insertions": 0,
        "deletions": 0,
    }


def test_align_substitution_insertion_deletion() -> None:
    sub = align_strings("51F12346", "51F12345")
    assert sub["matches"] == 7 and sub["substitutions"] == 1
    ins = align_strings("51F123456", "51F12345")
    assert ins["matches"] == 8 and ins["insertions"] == 1
    dele = align_strings("51F1234", "51F12345")
    assert dele["matches"] == 7 and dele["deletions"] == 1


def test_load_labels_has_expected_columns(config: Config) -> None:
    labels = load_labels(config.labels_file)
    assert len(labels) >= 20
    first = next(row for row in labels if row.image_name == "dev_clear_001.jpg")
    assert first.ground_truth == "88Y79730"
    assert first.split == "dev"
    assert first.bbox is not None
    assert len(first.char_boxes) == 8


@pytest.fixture(scope="module")
def small_evaluation(recognizer: LicensePlateRecognizer, config: Config):
    labels = [
        LabelRow(
            image_name="dev_clear_001.jpg",
            ground_truth="88Y79730",
            split="dev",
            condition="clear",
            bbox=(339.0, 455.0, 622.0, 517.0),
        ),
        LabelRow(
            image_name="dev_no_plate_001.jpg",
            ground_truth="",
            split="dev",
            condition="no_plate",
            bbox=None,
        ),
    ]
    return run_evaluation(recognizer, labels, config.samples_dir, config, split="dev")


def test_run_evaluation_rows(small_evaluation) -> None:
    rows, summary = small_evaluation
    assert len(rows) == 2
    first = next(row for row in rows if row.image_name == "dev_clear_001.jpg")
    assert first.status == "SUCCESS"
    assert first.exact_match is True
    assert first.char_accuracy == pytest.approx(1.0)
    assert first.detection_correct is True
    assert first.detection_iou is not None and first.detection_iou >= 0.5
    second = next(row for row in rows if row.image_name == "dev_no_plate_001.jpg")
    assert second.status == "PLATE_NOT_FOUND"
    assert second.has_gt_plate is False
    assert second.predicted_plate is False


def test_compute_summary_metrics(small_evaluation) -> None:
    _, summary = small_evaluation
    assert summary["num_images"] == 2
    assert summary["num_with_plate"] == 1
    assert summary["num_without_plate"] == 1
    assert summary["plate_detection_rate"] == pytest.approx(1.0)
    assert summary["detection_precision"] == pytest.approx(1.0)
    assert summary["detection_recall"] == pytest.approx(1.0)
    assert summary["detection_true_negative"] == 1
    assert summary["exact_plate_accuracy"] == pytest.approx(1.0)
    assert summary["status_counts"]["SUCCESS"] == 1
    assert summary["status_counts"]["PLATE_NOT_FOUND"] == 1
    assert summary["average_processing_time_ms"] > 0
    assert summary["split"] == "dev"


def test_summary_recomputation_is_stable(small_evaluation) -> None:
    rows, summary = small_evaluation
    assert compute_summary(rows)["num_images"] == summary["num_images"]


def test_write_evaluation_csv(small_evaluation, tmp_path: Path) -> None:
    rows, _ = small_evaluation
    out = write_evaluation_csv(rows, tmp_path / "eval.csv")
    assert out.exists()
    with out.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        data = list(reader)
    assert len(data) == 2
    assert "detected_text" in reader.fieldnames
    assert "segmentation_accuracy" in reader.fieldnames
    assert data[0]["image_name"] == "dev_clear_001.jpg"
    assert float(data[0]["char_accuracy"]) == pytest.approx(1.0)


def test_write_summary_json_and_markdown(small_evaluation, tmp_path: Path) -> None:
    _, summary = small_evaluation
    json_path = write_summary_json(summary, tmp_path / "summary.json")
    md_path = write_summary_markdown(summary, tmp_path / "summary.md")
    loaded = json.loads(json_path.read_text(encoding="utf-8"))
    assert loaded["num_images"] == 2
    text = md_path.read_text(encoding="utf-8")
    assert "Kết quả đánh giá" in text
    assert "Exact Plate Accuracy" in text


def test_empty_rows_csv_has_header(tmp_path: Path) -> None:
    out = write_evaluation_csv([], tmp_path / "empty.csv")
    content = out.read_text(encoding="utf-8-sig")
    assert content.startswith("image_name")

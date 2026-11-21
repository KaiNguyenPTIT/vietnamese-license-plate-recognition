"""Kiểm thử hậu xử lý chuỗi và quyết định trạng thái."""

from __future__ import annotations

import pytest

from src.character_recognition import CharacterPrediction
from src.config import Config
from src.postprocessing import (
    build_text_result,
    compact_from_predictions,
    decide_status,
    format_plate_text,
    normalize_ground_truth,
    resolve_position_constraints,
    validate_format,
)


def make_prediction(
    label: str,
    status: str = "OK",
    score: float = 0.9,
    margin: float = 0.2,
) -> CharacterPrediction:
    return CharacterPrediction(
        label=label if status == "OK" else "?",
        status=status,
        score=score,
        margin=margin,
        best_label=label,
        second_label="?",
        second_score=max(0.0, score - margin),
    )


def predictions_from_text(text: str) -> list[CharacterPrediction]:
    return [make_prediction(char) for char in text]


def test_normalize_ground_truth() -> None:
    assert normalize_ground_truth("51F-123.45") == "51F12345"
    assert normalize_ground_truth(" 30a 123 45 ") == "30A12345"
    assert normalize_ground_truth(None) == ""
    assert normalize_ground_truth("") == ""


def test_format_plate_text(config: Config) -> None:
    assert format_plate_text("88Y79730", config) == "88Y-797.30"
    assert format_plate_text("60F3499", config) == "60F-3499"
    assert format_plate_text("?", config) == "?"


def test_validate_valid_plate(config: Config) -> None:
    result = validate_format("51F12345", config)
    assert result.is_valid
    assert result.normalized_text == "51F12345"
    assert result.matched_pattern is not None
    assert result.checks["length"]
    assert result.checks["pattern"]


def test_validate_invalid_series_letter(config: Config) -> None:
    # I không nằm trong tập series hợp lệ của biển Việt Nam.
    result = validate_format("51I12345", config)
    assert not result.is_valid
    assert result.checks["series_letters"] is False
    assert any("series" in issue.lower() for issue in result.issues)
    # Không tự đổi I thành ký tự khác.
    assert result.normalized_text == "51I12345"


def test_validate_province_code(config: Config) -> None:
    result = validate_format("00A12345", config)
    assert not result.is_valid
    assert result.checks["province_code"] is False


def test_validate_unknown_is_not_guessed(config: Config) -> None:
    result = validate_format("51F?2345", config)
    assert not result.is_valid
    assert result.normalized_text == "51F?2345"
    assert result.checks["no_unknown"] is False
    assert any("?" in issue for issue in result.issues)


def test_compact_keeps_question_mark() -> None:
    predictions = [
        make_prediction("4"),
        make_prediction("3"),
        make_prediction("S", status="AMBIGUOUS"),
        make_prediction("8"),
    ]
    assert compact_from_predictions(predictions) == "43?8"


def test_decide_success(config: Config) -> None:
    predictions = predictions_from_text("51F12345")
    validation = validate_format("51F12345", config)
    status = decide_status(predictions, validation, "OK", config)
    assert status == "SUCCESS"


def test_decide_low_confidence_on_ambiguous(config: Config) -> None:
    predictions = predictions_from_text("51F12345")
    predictions[3] = make_prediction("1", status="AMBIGUOUS")
    validation = validate_format("51F?2345", config)
    status = decide_status(predictions, validation, "OK", config)
    assert status == "LOW_CONFIDENCE"


def test_decide_low_confidence_on_bad_segmentation(config: Config) -> None:
    predictions = predictions_from_text("51F12345")
    validation = validate_format("51F12345", config)
    assert decide_status(predictions, validation, "IMPLAUSIBLE", config) == "LOW_CONFIDENCE"


def test_decide_format_warning_without_rewriting(config: Config) -> None:
    predictions = predictions_from_text("1A12345")
    validation = validate_format("1A12345", config)
    assert not validation.is_valid
    status = decide_status(predictions, validation, "OK", config)
    assert status == "FORMAT_WARNING"


def test_validate_ten_char_special_plate(config: Config) -> None:
    result = validate_format("17MD799999", config)
    assert result.is_valid
    assert result.checks["length"]
    assert result.checks["pattern"]
    assert result.normalized_text == "17MD799999"


def test_position_min_margin_allows_close_same_type_candidate(
    config: Config,
) -> None:
    predictions = predictions_from_text("17?D799999")
    predictions[2] = CharacterPrediction(
        label="?",
        status="AMBIGUOUS",
        score=0.86,
        margin=0.025,
        best_label="M",
        second_label="N",
        second_score=0.835,
        ranked=[("M", 0.86), ("N", 0.835), ("H", 0.78)],
    )
    resolved = resolve_position_constraints(predictions, config)
    assert resolved[2].label == "M"
    assert resolved[2].status == "OK"

    predictions[2] = CharacterPrediction(
        label="?",
        status="AMBIGUOUS",
        score=0.86,
        margin=0.01,
        best_label="M",
        second_label="N",
        second_score=0.85,
        ranked=[("M", 0.86), ("N", 0.85)],
    )
    resolved = resolve_position_constraints(predictions, config)
    assert resolved[2].label == "?"
    assert resolved[2].status == "AMBIGUOUS"


def test_decide_success_for_ten_char_plate(config: Config) -> None:
    predictions = predictions_from_text("17MD799999")
    validation = validate_format("17MD799999", config)
    assert decide_status(predictions, validation, "OK", config) == "SUCCESS"
    predictions = [
        make_prediction("4"),
        make_prediction("3"),
        make_prediction("S", status="AMBIGUOUS", score=0.9, margin=0.02),
        make_prediction("8"),
        make_prediction("2"),
        make_prediction("4"),
        make_prediction("5"),
        make_prediction("8"),
    ]
    text = build_text_result(predictions, "OK", config)
    assert text.raw_text == "43?82458"
    assert text.normalized_text == "43?82458"
    assert text.formatted_text == "43?82458"
    assert text.status == "LOW_CONFIDENCE"
    assert text.unknown_count == 1
    assert text.has_unknown


def test_build_text_result_success(config: Config) -> None:
    predictions = predictions_from_text("88Y79730")
    text = build_text_result(predictions, "OK", config)
    assert text.status == "SUCCESS"
    assert text.raw_text == "88Y79730"
    assert text.formatted_text == "88Y-797.30"
    assert text.validation.is_valid
    assert text.char_count == 8
    assert text.unknown_count == 0


def test_build_text_result_empty(config: Config) -> None:
    text = build_text_result([], "EMPTY", config)
    assert text.char_count == 0
    assert text.status == "LOW_CONFIDENCE"
    assert text.raw_text == ""

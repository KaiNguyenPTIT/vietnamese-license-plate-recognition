"""Kiểm thử phân đoạn ký tự trên ảnh tổng hợp có kiểm soát."""

from __future__ import annotations

import cv2
import numpy as np

from src.character_segmentation import (
    RowInfo,
    _is_balanced_long_plate,
    characters_as_dicts,
    segment_characters,
)
from src.config import Config


def _one_line_plate() -> np.ndarray:
    image = np.full((120, 520, 3), 245, dtype=np.uint8)
    cv2.rectangle(image, (0, 0), (519, 119), (0, 0, 0), 2)
    for index, char in enumerate("51F12345"):
        cv2.putText(
            image,
            char,
            (25 + index * 60, 95),
            cv2.FONT_HERSHEY_SIMPLEX,
            2.0,
            (20, 20, 20),
            4,
            cv2.LINE_AA,
        )
    return image


def _two_line_plate() -> np.ndarray:
    image = np.full((200, 420, 3), 250, dtype=np.uint8)
    cv2.rectangle(image, (0, 0), (419, 199), (0, 0, 0), 3)
    for index, char in enumerate("30A"):
        cv2.putText(
            image,
            char,
            (40 + index * 48, 85),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.7,
            (10, 10, 10),
            4,
            cv2.LINE_AA,
        )
    for index, char in enumerate("12345"):
        cv2.putText(
            image,
            char,
            (30 + index * 38, 175),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.4,
            (10, 10, 10),
            3,
            cv2.LINE_AA,
        )
    return image


def test_one_line_segmentation(config: Config) -> None:
    result = segment_characters(_one_line_plate(), config)
    assert result.status == "OK"
    assert 7 <= result.count <= 9
    assert len(result.rows) == 1
    assert result.binary is not None
    assert result.binary.ndim == 2
    widths = [c.bbox[2] - c.bbox[0] for c in result.characters]
    assert all(width > 0 for width in widths)
    assert all(c.row_index == 0 for c in result.characters)
    assert [c.order for c in result.characters] == list(range(result.count))


def test_is_balanced_long_plate(config: Config) -> None:
    mask = np.zeros((10, 10), dtype=np.uint8)
    top = RowInfo(bbox=(0, 0, 10, 5), mask=mask, char_count=5)
    bottom = RowInfo(bbox=(0, 5, 10, 5), mask=mask, char_count=5)
    assert _is_balanced_long_plate(10, [top, bottom], config.segmentation)

    unbalanced = RowInfo(bbox=(0, 5, 10, 5), mask=mask, char_count=6)
    assert not _is_balanced_long_plate(10, [top, unbalanced], config.segmentation)
    assert not _is_balanced_long_plate(9, [top, bottom], config.segmentation)



def test_two_line_segmentation_has_two_rows(config: Config) -> None:
    result = segment_characters(_two_line_plate(), config)
    assert result.status == "OK"
    assert len(result.rows) == 2
    assert result.count == 8
    row_counts = [row.char_count for row in result.rows]
    assert row_counts == [3, 5]
    assert [c.row_index for c in result.characters] == [0, 0, 0, 1, 1, 1, 1, 1]


def test_characters_are_sorted_left_to_right(config: Config) -> None:
    result = segment_characters(_one_line_plate(), config)
    centers = [(c.bbox[0] + c.bbox[2]) / 2 for c in result.characters]
    assert centers == sorted(centers)


def test_characters_as_dicts_serializable(config: Config) -> None:
    result = segment_characters(_one_line_plate(), config)
    payload = characters_as_dicts(result)
    assert len(payload) == result.count
    for item in payload:
        assert {"order", "row_index", "bbox", "area"} <= set(item)
        assert isinstance(item["bbox"], list)


def test_empty_plate_returns_empty_status(config: Config) -> None:
    blank = np.full((80, 300, 3), 255, dtype=np.uint8)
    result = segment_characters(blank, config)
    assert result.count == 0
    assert result.status in {"EMPTY", "IMPLAUSIBLE"}

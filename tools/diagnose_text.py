"""Kiểm tra nhanh character_like_count trên vùng biển cắt tay."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402

from src.io_utils import read_image  # noqa: E402
from src.plate_detection import (  # noqa: E402
    _count_character_like,
    character_like_count,
    text_likeness_score,
)


def main() -> int:
    name = sys.argv[1] if len(sys.argv) > 1 else "dev_two_line_001.jpg"
    with open(ROOT / "data/labels.csv", encoding="utf-8-sig") as fh:
        row = next(r for r in csv.DictReader(fh) if r["image_name"] == name)
    img = read_image(ROOT / "data/samples" / name)
    x1, y1, x2, y2 = (int(float(row[k])) for k in ("x1", "y1", "x2", "y2"))
    roi = cv2.cvtColor(img[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
    print(f"{name}: roi={roi.shape} count={character_like_count(roi)}")
    target_w = 300
    scale = target_w / roi.shape[1]
    small = cv2.resize(roi, (target_w, int(round(roi.shape[0] * scale))))
    small = cv2.GaussianBlur(small, (3, 3), 0)
    _, raw = cv2.threshold(small, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    cv2.imwrite(str(ROOT / "results/diagnose/roi.png"), small)
    for invert in (False, True):
        b = cv2.bitwise_not(raw) if invert else raw.copy()
        cv2.imwrite(
            str(ROOT / f"results/diagnose/roi_bin_invert{int(invert)}.png"), b
        )
        print(f"  invert={invert}: count={_count_character_like(b)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

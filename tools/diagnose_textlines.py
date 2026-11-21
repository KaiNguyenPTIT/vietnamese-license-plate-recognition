"""Chẩn đoán text-likeness: in các thành phần và nhóm dòng."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from src.io_utils import read_image  # noqa: E402
from src.plate_detection import _remove_border_components  # noqa: E402


def main() -> int:
    name = sys.argv[1] if len(sys.argv) > 1 else "dev_clear_003.jpg"
    with open(ROOT / "data/labels.csv", encoding="utf-8-sig") as fh:
        row = next(r for r in csv.DictReader(fh) if r["image_name"] == name)
    img = read_image(ROOT / "data/samples" / name)
    x1, y1, x2, y2 = (int(float(row[k])) for k in ("x1", "y1", "x2", "y2"))
    roi = cv2.cvtColor(img[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
    h, w = roi.shape
    scale = 300.0 / w
    roi = cv2.resize(roi, (300, int(round(h * scale))))
    roi = cv2.GaussianBlur(roi, (3, 3), 0)
    _, raw = cv2.threshold(roi, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    for invert in (False, True):
        b = cv2.bitwise_not(raw) if invert else raw
        b = _remove_border_components(b, 2)
        frac = float(np.count_nonzero(b)) / b.size
        print(f"invert={invert} ink={frac:.3f} shape={b.shape}")
        b = cv2.morphologyEx(b, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8))
        contours, _ = cv2.findContours(
            b, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        rh, rw = b.shape
        boxes = []
        for c in contours:
            x, y, ww, hh = cv2.boundingRect(c)
            fill = cv2.contourArea(c) / max(1.0, ww * hh)
            ok = (
                0.10 * rh <= hh <= 0.95 * rh
                and 0.008 * rw <= ww <= 0.40 * rw
                and ww * hh >= 0.00025 * rw * rh
                and fill >= 0.06
            )
            if ok:
                boxes.append((x, y, ww, hh))
            print(
                f"  x={x:4d} y={y:4d} w={ww:3d} h={hh:3d} "
                f"fill={fill:.2f} keep={ok}"
            )
        print("  boxes:", boxes)
        if len(boxes) >= 3:
            med = float(np.median([bb[3] for bb in boxes]))
            filt = [bb for bb in boxes if 0.6 * med <= bb[3] <= 1.55 * med]
            print(f"  median_h={med:.1f} filtered={filt}")
            gaps = [
                filt[i + 1][0] - (filt[i][0] + filt[i][2])
                for i in range(len(filt) - 1)
            ]
            print("  gaps:", gaps)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

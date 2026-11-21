"""Thử nghiệm đếm thành phần giống ký tự với nhiều ngưỡng hình học."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from src.io_utils import read_image  # noqa: E402


def stats(binary: np.ndarray) -> None:
    h, w = binary.shape
    binary = binary.copy()
    binary[:2, :] = 0
    binary[-2:, :] = 0
    binary[:, :2] = 0
    binary[:, -2:] = 0
    n, labels, st, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    rows = []
    for i in range(1, n):
        x, y, ww, hh, area = st[i]
        if area < 10:
            continue
        rows.append((x, y, ww, hh, area, hh / h, ww / w))
    print(f"  components (area>=10): {len(rows)}")
    for r in rows:
        print(
            f"    x={r[0]:4d} y={r[1]:4d} w={r[2]:3d} h={r[3]:3d} "
            f"area={r[4]:5d} h/h={r[5]:.2f} w/w={r[6]:.3f}"
        )


def main() -> int:
    name = sys.argv[1] if len(sys.argv) > 1 else "dev_two_line_001.jpg"
    with open(ROOT / "data/labels.csv", encoding="utf-8-sig") as fh:
        row = next(r for r in csv.DictReader(fh) if r["image_name"] == name)
    img = read_image(ROOT / "data/samples" / name)
    x1, y1, x2, y2 = (int(float(row[k])) for k in ("x1", "y1", "x2", "y2"))
    roi = cv2.cvtColor(img[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
    scale = 300.0 / roi.shape[1]
    roi = cv2.resize(roi, (300, int(round(roi.shape[0] * scale))))
    roi = cv2.GaussianBlur(roi, (3, 3), 0)
    _, raw = cv2.threshold(roi, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    for invert in (False, True):
        b = cv2.bitwise_not(raw) if invert else raw
        print(f"invert={invert}")
        stats(b)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

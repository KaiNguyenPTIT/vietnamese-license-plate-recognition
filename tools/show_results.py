"""In gọn kết quả đánh giá từ CSV để chẩn đoán nhanh."""

from __future__ import annotations

import csv
import sys
from pathlib import Path


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "results/dev_eval.csv")
    with path.open(encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        print(
            f"{r.get('image_name', ''):30s} "
            f"exp={r.get('ground_truth', ''):12s} "
            f"det={r.get('detected_text', ''):12s} "
            f"PDR={r.get('detection_correct', ''):5s} "
            f"CA={r.get('char_accuracy', ''):6s} "
            f"chars={r.get('seg_pred_count', ''):>3s} "
            f"st={r.get('status', ''):14s}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

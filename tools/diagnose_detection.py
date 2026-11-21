"""Chẩn đoán phát hiện biển số: in toàn bộ ứng viên (kể cả bị loại).

Cách dùng:
    python tools/diagnose_detection.py data/samples/dev_two_line_001.jpg
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402

from src.config import load_config  # noqa: E402
from src.plate_detection import build_morphology_maps, detect_plates  # noqa: E402
from src.preprocessing import preprocess  # noqa: E402


def main() -> int:
    if len(sys.argv) < 2:
        print("Cần đường dẫn ảnh.")
        return 1
    config = load_config()
    path = Path(sys.argv[1])
    pre = preprocess(path, config)
    det = detect_plates(pre, config)
    print(f"Ảnh: {path}  scale={pre.scale:.3f}")
    print(f"Tổng ứng viên (sau gộp): {len(det.all_candidates)}")
    header = (
        f"{'#':>3} {'source':22s} {'bbox':28s} {'ratio':>6} {'area':>7} "
        f"{'edge':>6} {'fill':>6} {'text':>6} {'score':>6} passed"
    )
    print(header)
    for idx, c in enumerate(det.all_candidates[:30]):
        bbox = ",".join(f"{v:.0f}" for v in c.bbox)
        print(
            f"{idx:3d} {c.source:22s} {bbox:28s} {c.ratio:6.2f} "
            f"{c.area_ratio:7.4f} {c.edge_density:6.3f} {c.fill_ratio:6.3f} "
            f"{c.text_likeness:6.2f} {c.score:6.3f} {c.passed}"
        )
    if det.maps:
        out = config.resolve("results/diagnose")
        out.mkdir(parents=True, exist_ok=True)
        for name, img in det.maps.items():
            cv2.imwrite(str(out / f"{name}.png"), img)
        print(f"Đã lưu bản đồ morphology: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

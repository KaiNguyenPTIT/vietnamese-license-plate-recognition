"""Chẩn đoán phân đoạn ký tự trên một ảnh."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402

from src.character_segmentation import segment_characters  # noqa: E402
from src.config import load_config  # noqa: E402
from src.pipeline import LicensePlateRecognizer  # noqa: E402
from src.plate_rectification import rectify_plate  # noqa: E402
from src.preprocessing import preprocess  # noqa: E402


def main() -> int:
    name = sys.argv[1] if len(sys.argv) > 1 else "dev_two_line_001.jpg"
    config = load_config()
    rec = LicensePlateRecognizer(config)
    pre = preprocess(ROOT / "data/samples" / name, config)
    det = rec.config  # noqa: F841
    from src.plate_detection import detect_plates

    result = detect_plates(pre, config)
    print(f"candidates: {len(result.candidates)}")
    for ci, cand in enumerate(result.candidates[:3]):
        print(
            f"#{ci} bbox={tuple(round(v, 1) for v in cand.bbox)} "
            f"score={cand.score:.3f} source={cand.source}"
        )
        rect = rectify_plate(pre.work_image, cand, config)
        print(
            f"  rect method={rect.method} size={rect.output_size} "
            f"crop={rect.crop_image.shape[1]}x{rect.crop_image.shape[0]}"
        )
        seg = segment_characters(rect.plate_image, config)
        print(
            f"  seg status={seg.status} count={seg.count} score={seg.score:.3f} "
            f"threshold={seg.threshold_method_used} scale={seg.scale:.2f}"
        )
        for ri, row in enumerate(seg.rows):
            print(
                f"    row{ri} bbox={row.bbox} char_count={row.char_count} "
                f"mask={row.mask.shape}"
            )
        for ch in seg.characters:
            print(
                f"    char order={ch.order} row={ch.row_index} "
                f"bbox={tuple(round(v) for v in ch.bbox)} "
                f"size={ch.image.shape[1]}x{ch.image.shape[0]}"
            )
        work = f"results/diagnose/seg_{Path(name).stem}_{ci}"
        Path(work).mkdir(parents=True, exist_ok=True)
        if seg.binary is not None:
            cv2.imwrite(str(Path(work) / "binary.png"), seg.binary)
        if seg.plate_work is not None:
            cv2.imwrite(str(Path(work) / "plate_work.png"), seg.plate_work)
        for ri, row in enumerate(seg.rows):
            cv2.imwrite(str(Path(work) / f"row_{ri}.png"), row.mask)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

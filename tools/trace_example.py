"""Ghi lại một lần chạy đầy đủ của pipeline cho một ảnh duy nhất.

Kết quả dùng cho mục "Ví dụ chạy tay" trong báo cáo: mỗi con số trong mục đó
đều đọc từ tệp JSON sinh bởi lệnh này, không chép tay.

    python tools\\trace_example.py
    python tools\\trace_example.py --image data\\user_images\\2.webp \\
        --output results\\walkthrough.json
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import load_config  # noqa: E402
from src.pipeline import LicensePlateRecognizer  # noqa: E402


def _round(value: float, digits: int = 4) -> float:
    return round(float(value), digits)


def _read_ground_truth(image_name: str) -> str:
    for name in ("user_labels.csv", "labels.csv"):
        path = ROOT / "data" / name
        if not path.exists():
            continue
        with path.open(encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                if row.get("image_name") == image_name:
                    return row.get("ground_truth", "")
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="data/user_images/14.webp")
    parser.add_argument("--output", default="results/walkthrough.json")
    parser.add_argument("--top-candidates", type=int, default=3)
    args = parser.parse_args()

    image_path = (ROOT / args.image).resolve()
    config = load_config(ROOT / "config.yaml")
    recognizer = LicensePlateRecognizer(config)
    result = recognizer.recognize(str(image_path))

    attempt = result.selected_attempt
    seg = attempt.segmentation if attempt else None
    text = attempt.text if attempt else None
    rect = attempt.rectification if attempt else None
    validation = getattr(text, "validation", None)

    payload = {
        "image": args.image.replace("\\", "/"),
        "image_name": image_path.name,
        "image_size": [
            int(result.preprocess.original.shape[1]),
            int(result.preprocess.original.shape[0]),
        ],
        "work_size": [
            int(result.preprocess.work_image.shape[1]),
            int(result.preprocess.work_image.shape[0]),
        ],
        "scale": _round(result.preprocess.scale),
        "ground_truth": _read_ground_truth(image_path.name),
        "status": result.status,
        "display_status": result.display_status,
        "message": result.message,
        "raw_text": getattr(text, "raw_text", None),
        "formatted_text": getattr(text, "formatted_text", None),
        "detected_text": result.detected_text,
        "format_valid": bool(getattr(validation, "is_valid", False)),
        "format_issues": list(getattr(validation, "issues", []) or []),
        "bbox_original": [_round(v, 1) for v in result.bbox_original],
        "n_candidates": len(result.detection.candidates),
        "candidates": [
            {
                "source": cand.source,
                "bbox": [_round(v, 1) for v in cand.bbox],
                "score": _round(cand.score),
                "text_likeness": _round(getattr(cand, "text_likeness", 0.0)),
            }
            for cand in result.detection.candidates[: args.top_candidates]
        ],
        "selected_candidate_index": (
            result.detection.candidates.index(attempt.candidate) if attempt else None
        ),
        "n_attempts": len(result.attempts),
        "rectification": {
            "method": getattr(rect, "method", None),
            "plate_size": (
                [int(rect.plate_image.shape[1]), int(rect.plate_image.shape[0])]
                if rect is not None and rect.plate_image is not None
                else None
            ),
        },
        "segmentation": {
            "status": getattr(seg, "status", None),
            "threshold": getattr(seg, "threshold_method_used", None),
            "n_rows": len(getattr(seg, "rows", []) or []),
            "n_chars": len(getattr(seg, "characters", []) or []),
            "score": _round(getattr(seg, "score", 0.0)),
        },
        "characters": [
            {
                "index": index,
                "label": pred.label,
                "best_label": getattr(pred, "best_label", pred.label),
                "score": _round(pred.score),
                "second_label": getattr(pred, "second_label", None),
                "second_score": _round(getattr(pred, "second_score", 0.0)),
                "margin": _round(getattr(pred, "margin", 0.0)),
                "status": pred.status,
            }
            for index, pred in enumerate(attempt.predictions if attempt else [])
        ],
        "scores": {
            "mean": _round(getattr(text, "mean_score", 0.0)),
            "min": _round(getattr(text, "min_score", 0.0)),
            "mean_margin": _round(getattr(text, "mean_margin", 0.0)),
        },
        "thresholds": {
            "score": _round(config.recognition.score_threshold),
            "margin": _round(config.recognition.min_margin),
            "expected_chars": list(config.segmentation.expected_chars),
            "min_chars": config.segmentation.min_chars,
        },
        "timings_ms": {key: _round(value, 1) for key, value in result.timings_ms.items()},
        "total_time_ms": _round(result.total_time_ms, 1),
        "config_sha256": hashlib.sha256(
            (ROOT / "config.yaml").read_bytes()
        ).hexdigest().upper(),
        "generated_by": "python tools\\trace_example.py",
    }

    out = ROOT / args.output
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    print(f"{payload['image']}: {payload['status']} {payload['detected_text']} "
          f"({payload['total_time_ms']:.1f} ms) -> {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

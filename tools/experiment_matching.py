"""Thử nghiệm các biến thể so khớp template trên ký tự đã lưu."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from src.character_recognition import load_templates  # noqa: E402
from src.config import load_config  # noqa: E402

CASES = {
    "dev_clear_003": "60F3499",
    "dev_two_line_001": "80A2504",
    "dev_low_light_001": "29L9151",
}


def prep(img: np.ndarray, sigma: float) -> np.ndarray:
    out = img.astype(np.float32)
    if sigma > 0:
        out = cv2.GaussianBlur(out, (0, 0), sigma)
    return out


def score(q: np.ndarray, t: np.ndarray, sigma: float) -> float:
    qf, tf = prep(q, sigma), prep(t, sigma)
    v = float(cv2.matchTemplate(qf, tf, cv2.TM_CCOEFF_NORMED)[0, 0])
    return max(-1.0, min(1.0, v))


def main() -> int:
    cfg = load_config()
    lib = load_templates(None, cfg)
    for stem, gt in CASES.items():
        char_dir = ROOT / "results/debug" / stem / "characters"
        files = sorted(char_dir.glob("*_normalized.png"))
        print(f"\n{stem} gt={gt} files={len(files)}")
        for f in files:
            q = cv2.imread(str(f), 0)
            print(f"  {f.name}")
            for sigma in (0.0, 0.8, 1.2, 1.8, 2.5):
                ranked = []
                for label in lib.labels:
                    best = max(score(q, t, sigma) for t in lib.templates[label])
                    ranked.append((label, best))
                ranked.sort(key=lambda x: x[1], reverse=True)
                top = ranked[:3]
                print(
                    f"    s={sigma:.1f} "
                    + " ".join(f"{l}:{v:.3f}" for l, v in top)
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

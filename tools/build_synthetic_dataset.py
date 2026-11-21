"""Sinh bộ ảnh biển số Việt Nam tổng hợp để demo/kiểm thử/đánh giá.

Bộ dữ liệu này là DỮ LIỆU TỔNG HỢP, không phải ảnh thực tế. Nó dùng để:
    - kiểm thử pipeline đầu-cuối,
    - đo các chỉ số một cách tái lập,
    - demo giao diện với các tình huống: rõ, nghiêng, thiếu sáng, hai dòng,
      ký tự dính, chất lượng thấp, không có biển, độ phân giải thấp.

Không dùng kết quả trên bộ tổng hợp để tuyên bố độ chính xác thực tế. Muốn
đánh giá thực tế, thay/thêm ảnh vào data/samples và cập nhật data/labels.csv.

Cách dùng:
    python tools/build_synthetic_dataset.py
    python tools/build_synthetic_dataset.py --clean
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import load_config  # noqa: E402
from src.io_utils import is_convex_quad, write_image  # noqa: E402
from src.postprocessing import format_plate_text, normalize_ground_truth  # noqa: E402

# Font dành cho ảnh mẫu, cố ý khác với font sinh template để tránh "học thuộc".
SAMPLE_FONTS = [
    "C:/Windows/Fonts/calibrib.ttf",
    "C:/Windows/Fonts/verdanab.ttf",
    "C:/Windows/Fonts/timesbd.ttf",
    "C:/Windows/Fonts/trebucbd.ttf",
    "C:/Windows/Fonts/calibri.ttf",
    "C:/Windows/Fonts/verdana.ttf",
]

PROVINCES = [29, 30, 43, 51, 59, 60, 65, 79, 80, 88]
SERIES = list("ABCDEFGHKLMNPSTUVXYZ")

CONDITION_PLAN = {
    "dev": [
        ("clear", 5),
        ("tilted", 4),
        ("low_light", 3),
        ("two_line", 4),
        ("touching", 3),
        ("low_quality", 3),
        ("no_plate", 3),
        ("low_resolution", 1),
    ],
    "test": [
        ("clear", 5),
        ("tilted", 4),
        ("low_light", 3),
        ("two_line", 4),
        ("touching", 3),
        ("low_quality", 3),
        ("no_plate", 3),
        ("low_resolution", 1),
    ],
}


@dataclass
class PlateRender:
    compact: str
    texture_bgr: np.ndarray
    char_boxes: List[Tuple[float, float, float, float]]
    char_labels: List[str]
    plate_type: str
    font_name: str


# ----------------------------------------------------------------------
# Render biển số
# ----------------------------------------------------------------------
def _fit_layout(
    draw: ImageDraw.ImageDraw,
    font_path: str,
    glyph_widths: Sequence[float],
    max_width: float,
    initial_size: int,
) -> Tuple[ImageFont.FreeTypeFont, int, List[float]]:
    size = initial_size
    while size > 20:
        font = ImageFont.truetype(font_path, size)
        widths = [float(draw.textlength(ch, font=font)) for ch in glyph_widths]
        # chỗ cho dấu gạch ngang/chấm và khoảng cách
        total = sum(widths) + (len(widths) - 1) * max(3, size * 0.06) + size * 0.9
        if total <= max_width:
            return font, size, widths
        size -= 4
    font = ImageFont.truetype(font_path, 20)
    widths = [float(draw.textlength(ch, font=font)) for ch in glyph_widths]
    return font, 20, widths


def render_plate_texture(
    compact: str,
    plate_type: str,
    font_path: str,
    rng: random.Random,
    touching: bool = False,
    yellow: bool = False,
) -> PlateRender:
    """Vẽ texture biển số và trả về bounding box từng ký tự trong texture."""
    if plate_type == "one_line":
        width, height = 1040, 220
    else:
        width, height = 560, 400
    background = (255, 208, 0) if yellow else (252, 252, 250)
    image = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(image)

    # Gradient nhẹ + nhiễu nhẹ để không quá "sạch"
    arr = np.array(image, dtype=np.float32)
    gradient = np.linspace(1.03, 0.97, height, dtype=np.float32)[:, None, None]
    arr = np.clip(arr * gradient, 0, 255)
    noise = np.random.default_rng(rng.randint(0, 10**9)).normal(0, 1.4, arr.shape)
    arr = np.clip(arr + noise, 0, 255)
    image = Image.fromarray(arr.astype(np.uint8), mode="RGB")
    draw = ImageDraw.Draw(image)

    border_color = (18, 28, 120)
    draw.rounded_rectangle(
        (10, 10, width - 11, height - 11),
        radius=10,
        outline=border_color,
        width=8,
    )
    # Ốc vít (nhiễu hình học có chủ đích)
    screw_r = 7 if plate_type == "one_line" else 8
    for cx, cy in [
        (34, 30),
        (width - 34, 30),
        (34, height - 30),
        (width - 34, height - 30),
    ]:
        draw.ellipse(
            (cx - screw_r, cy - screw_r, cx + screw_r, cy + screw_r),
            fill=(110, 110, 110),
        )

    # Tách prefix và phần số
    import re

    m = re.fullmatch(r"(\d{2})([A-Z]{1,2})(\d{4,5})", compact)
    if not m:
        raise ValueError(f"Chuỗi không hợp lệ: {compact}")
    province, series, digits = m.groups()
    prefix = province + series
    if plate_type == "one_line":
        font_candidates = [ch for ch in prefix] + [ch for ch in digits]
    else:
        # Biển hai dòng: cỡ chữ phải vừa dòng dài hơn, không phải cả 8 ký tự
        longer_row = digits if len(digits) >= len(prefix) else prefix
        font_candidates = [ch for ch in longer_row]
    initial = 150 if plate_type == "one_line" else 118
    max_width = width * 0.84
    font, font_size, widths = _fit_layout(
        draw, font_path, font_candidates, max_width, initial
    )

    char_boxes: List[Tuple[float, float, float, float]] = []
    char_labels: List[str] = []

    def draw_row(
        chars: str, y_center: float, include_dot_after: int = -1
    ) -> None:
        nonlocal char_boxes, char_labels
        gap = font_size * 0.05
        if touching:
            gap = -font_size * 0.14
        char_widths = [float(draw.textlength(ch, font=font)) for ch in chars]
        sep_width = font_size * 0.42
        dot_width = font_size * 0.28
        total = sum(char_widths) + gap * max(0, len(chars) - 1)
        if include_dot_after >= 0:
            total += sep_width + dot_width
        x = (width - total) / 2.0
        for idx, ch in enumerate(chars):
            w = char_widths[idx]
            cx = x + w / 2.0
            draw.text(
                (cx, y_center), ch, font=font, fill=(8, 8, 8), anchor="mm"
            )
            bbox = draw.textbbox(
                (cx, y_center), ch, font=font, anchor="mm"
            )
            x1, y1, x2, y2 = bbox
            char_boxes.append((float(x1), float(y1), float(x2), float(y2)))
            char_labels.append(ch)
            x += w + gap
            if include_dot_after == idx:
                draw.ellipse(
                    (
                        x + sep_width * 0.35,
                        y_center + font_size * 0.28,
                        x + sep_width * 0.35 + dot_width * 0.6,
                        y_center + font_size * 0.28 + dot_width * 0.6,
                    ),
                    fill=(8, 8, 8),
                )
                x += sep_width + dot_width

    if plate_type == "one_line":
        # Layout: prefix - digits.xx
        gap = font_size * 0.05
        if touching:
            gap = -font_size * 0.14
        prefix_widths = [float(draw.textlength(ch, font=font)) for ch in prefix]
        digit_widths = [float(draw.textlength(ch, font=font)) for ch in digits]
        dash_w = font_size * 0.38
        dot_w = font_size * 0.26
        total = (
            sum(prefix_widths)
            + gap * max(0, len(prefix) - 1)
            + dash_w
            + gap
            + sum(digit_widths)
            + gap * max(0, len(digits) - 1)
            + (dot_w + gap if len(digits) == 5 else 0.0)
        )
        x = (width - total) / 2.0
        y_center = height / 2.0 + 4
        for idx, ch in enumerate(prefix):
            w = prefix_widths[idx]
            cx = x + w / 2.0
            draw.text((cx, y_center), ch, font=font, fill=(8, 8, 8), anchor="mm")
            bbox = draw.textbbox(
                (cx, y_center), ch, font=font, anchor="mm"
            )
            char_boxes.append(tuple(float(v) for v in bbox))  # type: ignore[arg-type]
            char_labels.append(ch)
            x += w + gap
        # Gạch ngang phân cách
        draw.rectangle(
            (
                x + dash_w * 0.15,
                y_center - font_size * 0.025,
                x + dash_w * 0.85,
                y_center + font_size * 0.025,
            ),
            fill=(8, 8, 8),
        )
        x += dash_w + gap
        for idx, ch in enumerate(digits):
            w = digit_widths[idx]
            cx = x + w / 2.0
            draw.text((cx, y_center), ch, font=font, fill=(8, 8, 8), anchor="mm")
            bbox = draw.textbbox(
                (cx, y_center), ch, font=font, anchor="mm"
            )
            char_boxes.append(tuple(float(v) for v in bbox))  # type: ignore[arg-type]
            char_labels.append(ch)
            x += w + gap
            if len(digits) == 5 and idx == 2:
                draw.ellipse(
                    (
                        x + dot_w * 0.15,
                        y_center + font_size * 0.28,
                        x + dot_w * 0.85,
                        y_center + font_size * 0.28 + dot_w * 0.7,
                    ),
                    fill=(8, 8, 8),
                )
                x += dot_w + gap
    else:
        draw_row(prefix, height * 0.29, include_dot_after=-1)
        draw_row(digits, height * 0.69, include_dot_after=2 if len(digits) == 5 else -1)

    texture_bgr = cv2.cvtColor(np.array(image, dtype=np.uint8), cv2.COLOR_RGB2BGR)
    # Kiểm tra số box khớp số ký tự
    if len(char_boxes) != len(compact) or "".join(char_labels) != compact:
        raise RuntimeError(
            f"Lỗi layout: {len(char_boxes)} box, chuỗi {compact}, "
            f"nhãn {'|'.join(char_labels)}"
        )
    return PlateRender(
        compact=compact,
        texture_bgr=texture_bgr,
        char_boxes=char_boxes,
        char_labels=char_labels,
        plate_type=plate_type,
        font_name=Path(font_path).stem,
    )


# ----------------------------------------------------------------------
# Scene
# ----------------------------------------------------------------------
def _rounded_rect(
    image: np.ndarray, rect: Tuple[int, int, int, int], color, radius: int = 18
) -> None:
    x1, y1, x2, y2 = rect
    cv2.rectangle(image, (x1 + radius, y1), (x2 - radius, y2), color, -1)
    cv2.rectangle(image, (x1, y1 + radius), (x2, y2 - radius), color, -1)
    for cx, cy in [
        (x1 + radius, y1 + radius),
        (x2 - radius, y1 + radius),
        (x1 + radius, y2 - radius),
        (x2 - radius, y2 - radius),
    ]:
        cv2.circle(image, (cx, cy), radius, color, -1)


def make_scene(rng: random.Random, width: int = 960, height: int = 640) -> np.ndarray:
    image = np.zeros((height, width, 3), dtype=np.uint8)
    horizon = int(height * 0.52)
    sky_top = np.array([180, 170, 150], dtype=np.float32)
    sky_bottom = np.array([230, 225, 215], dtype=np.float32)
    for y in range(horizon):
        t = y / max(1, horizon)
        color = sky_top * (1 - t) + sky_bottom * t
        image[y, :, :] = color.astype(np.uint8)
    road_top = np.array([70, 70, 72], dtype=np.float32)
    road_bottom = np.array([45, 45, 48], dtype=np.float32)
    for y in range(horizon, height):
        t = (y - horizon) / max(1, height - horizon)
        color = road_top * (1 - t) + road_bottom * t
        image[y, :, :] = color.astype(np.uint8)

    # Vạch kẻ đường
    for i in range(6):
        x = int(width * (0.1 + i * 0.16))
        cv2.rectangle(
            image,
            (x, int(height * 0.82)),
            (x + 50, int(height * 0.86)),
            (210, 210, 210),
            -1,
        )
    # Bóng xe
    cv2.ellipse(
        image,
        (width // 2, int(height * 0.93)),
        (int(width * 0.38), 28),
        0,
        0,
        360,
        (25, 25, 25),
        -1,
    )

    body_colors = [
        (40, 42, 48),
        (215, 215, 218),
        (55, 45, 130),
        (35, 40, 110),
        (60, 60, 62),
        (30, 80, 150),
    ]
    body = body_colors[rng.randrange(len(body_colors))]
    _rounded_rect(image, (150, 245, 810, 610), body, radius=36)
    # Kính sau
    _rounded_rect(image, (250, 275, 710, 385), (35, 30, 28), radius=22)
    cv2.rectangle(image, (285, 295, 675, 360), (45, 55, 65), -1)
    # Đèn hậu
    for x1, x2 in ((185, 285), (675, 775)):
        _rounded_rect(image, (x1, 405, x2, 445), (30, 30, 150), radius=8)
        cv2.rectangle(
            image, (x1 + 8, 412, x2 - 8, 438), (60, 60, 210), -1
        )
    # Cản sau + lưới tản nhiệt giả
    cv2.rectangle(image, (165, 455, 795, 600), (body[0] // 2, body[1] // 2, body[2] // 2), -1)
    for i in range(3):
        y = 520 + i * 18
        cv2.line(image, (620, y), (780, y), (90, 90, 90), 2)
    # Logo
    cv2.circle(image, (480, 420), 18, (200, 200, 200), 2)
    cv2.line(image, (470, 420), (490, 420), (200, 200, 200), 2)

    # Biển báo nền (vật thể gây nhiễu hình chữ nhật)
    if rng.random() < 0.45:
        sx = rng.choice([60, 820])
        sy = rng.randint(120, 190)
        cv2.rectangle(image, (sx, sy), (sx + 90, sy + 62), (245, 245, 245), -1)
        cv2.rectangle(image, (sx, sy), (sx + 90, sy + 62), (20, 20, 20), 3)
        cv2.putText(
            image,
            "P",
            (sx + 32, sy + 48),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.2,
            (20, 20, 20),
            3,
            cv2.LINE_AA,
        )
    # Khe gió / chi tiết gây nhiễu
    if rng.random() < 0.5:
        cv2.rectangle(image, (180, 470, 330, 505), (25, 25, 25), -1)
        for i in range(4):
            cv2.line(image, (188, 477 + i * 7), (322, 477 + i * 7), (80, 80, 80), 1)
    return image


# ----------------------------------------------------------------------
# Dán biển và biến đổi phối cảnh
# ----------------------------------------------------------------------
def _make_quad(
    center: Tuple[float, float],
    width: float,
    height: float,
    angle_deg: float,
    skew: float,
    rng: random.Random,
) -> np.ndarray:
    base = np.array(
        [
            [-width / 2, -height / 2],
            [width / 2, -height / 2],
            [width / 2, height / 2],
            [-width / 2, height / 2],
        ],
        dtype=np.float32,
    )
    m = cv2.getRotationMatrix2D((0, 0), angle_deg, 1.0)
    rotated = base @ m[:, :2].T + m[:, 2]
    for _ in range(20):
        offsets = np.array(
            [
                [rng.uniform(-skew, skew) * width, rng.uniform(-skew, skew) * height],
                [rng.uniform(-skew, skew) * width, rng.uniform(-skew, skew) * height],
                [rng.uniform(-skew, skew) * width, rng.uniform(-skew, skew) * height],
                [rng.uniform(-skew, skew) * width, rng.uniform(-skew, skew) * height],
            ],
            dtype=np.float32,
        )
        quad = rotated + offsets + np.array(center, dtype=np.float32)
        if is_convex_quad(quad):
            return quad.astype(np.float32)
    return (rotated + np.array(center, dtype=np.float32)).astype(np.float32)


def composite_plate(
    scene: np.ndarray,
    plate: PlateRender,
    condition: str,
    rng: random.Random,
) -> Tuple[np.ndarray, Tuple[int, int, int, int], List[Tuple[float, float, float, float]], List[Tuple[float, float, float, float]]]:
    h, w = scene.shape[:2]
    if plate.plate_type == "one_line":
        plate_w = rng.uniform(235, 290)
        plate_h = plate_w / 4.73
    else:
        plate_h = rng.uniform(105, 135)
        plate_w = plate_h * 1.40
    center = (w / 2 + rng.uniform(-18, 18), 478 + rng.uniform(-12, 12))
    if condition in {"tilted"}:
        angle = rng.uniform(-8.5, 8.5)
        skew = 0.085
    elif condition in {"two_line"}:
        angle = rng.uniform(-4.0, 4.0)
        skew = 0.035
    elif condition in {"touching"}:
        angle = rng.uniform(-3.0, 3.0)
        skew = 0.035
    else:
        angle = rng.uniform(-1.6, 1.6)
        skew = 0.012
    quad = _make_quad(center, plate_w, plate_h, angle, skew, rng)

    ph, pw = plate.texture_bgr.shape[:2]
    src = np.array(
        [[0, 0], [pw - 1, 0], [pw - 1, ph - 1], [0, ph - 1]], dtype=np.float32
    )
    matrix = cv2.getPerspectiveTransform(src, quad.astype(np.float32))
    warped = cv2.warpPerspective(
        plate.texture_bgr,
        matrix,
        (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0),
    )
    mask_src = np.full((ph, pw), 255, dtype=np.uint8)
    mask = cv2.warpPerspective(
        mask_src, matrix, (w, h), flags=cv2.INTER_LINEAR
    )
    # Bóng đổ
    shadow = cv2.GaussianBlur(mask, (0, 0), 5)
    shadow = cv2.warpAffine(
        shadow, np.float32([[1, 0, 2], [0, 1, 4]]), (w, h)
    )
    scene = scene.astype(np.float32)
    scene *= (1.0 - 0.35 * (shadow.astype(np.float32) / 255.0))[:, :, None]
    alpha = (mask.astype(np.float32) / 255.0)[:, :, None]
    scene = scene * (1 - alpha) + warped.astype(np.float32) * alpha
    scene = np.clip(scene, 0, 255).astype(np.uint8)

    # Bounding box biển và từng ký tự
    xs, ys = quad[:, 0], quad[:, 1]
    plate_bbox = (
        max(0, int(math.floor(xs.min()))),
        max(0, int(math.floor(ys.min()))),
        min(w - 1, int(math.ceil(xs.max()))),
        min(h - 1, int(math.ceil(ys.max()))),
    )
    char_boxes_scene: List[Tuple[float, float, float, float]] = []
    for (x1, y1, x2, y2) in plate.char_boxes:
        corners = np.array(
            [[x1, y1], [x2, y1], [x2, y2], [x1, y2]], dtype=np.float32
        ).reshape(-1, 1, 2)
        mapped = cv2.perspectiveTransform(corners, matrix).reshape(-1, 2)
        bx1, by1 = float(mapped[:, 0].min()), float(mapped[:, 1].min())
        bx2, by2 = float(mapped[:, 0].max()), float(mapped[:, 1].max())
        bx1 = max(0.0, min(w - 1.0, bx1))
        by1 = max(0.0, min(h - 1.0, by1))
        bx2 = max(bx1 + 1.0, min(w - 1.0, bx2))
        by2 = max(by1 + 1.0, min(h - 1.0, by2))
        char_boxes_scene.append((bx1, by1, bx2, by2))
    return scene, plate_bbox, char_boxes_scene, quad.tolist()


def degrade(
    image: np.ndarray, condition: str, rng: random.Random
) -> Tuple[np.ndarray, int]:
    rng_np = np.random.default_rng(rng.randint(0, 10**9))
    quality = 94
    if condition == "low_light":
        factor = rng.uniform(0.36, 0.52)
        image = image.astype(np.float32) * factor
        # Gamma làm tối vùng tối
        gamma = rng.uniform(1.15, 1.45)
        image = 255.0 * np.power(np.clip(image, 0, 255) / 255.0, gamma)
        noise = rng_np.normal(0, 5.5, image.shape)
        image = np.clip(image + noise, 0, 255).astype(np.uint8)
        quality = 88
    elif condition == "low_quality":
        h, w = image.shape[:2]
        small = cv2.resize(
            image, (max(1, int(w * 0.35)), max(1, int(h * 0.35))),
            interpolation=cv2.INTER_AREA,
        )
        image = cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)
        image = cv2.GaussianBlur(image, (0, 0), rng.uniform(0.8, 1.5))
        noise = rng_np.normal(0, 4.0, image.shape)
        image = np.clip(image.astype(np.float32) + noise, 0, 255).astype(np.uint8)
        quality = int(rng.uniform(38, 50))
    elif condition == "low_resolution":
        h, w = image.shape[:2]
        image = cv2.resize(
            image, (max(40, int(w * 0.34)), max(30, int(h * 0.34))),
            interpolation=cv2.INTER_AREA,
        )
        quality = 84

    # Nhiễu nhẹ cho mọi ảnh
    if condition in {"clear", "tilted", "two_line", "touching"}:
        noise = rng_np.normal(0, 1.2, image.shape)
        image = np.clip(image.astype(np.float32) + noise, 0, 255).astype(np.uint8)
    return image, quality


# ----------------------------------------------------------------------
# Sinh dữ liệu
# ----------------------------------------------------------------------
def random_plate_text(rng: random.Random, used: set[str]) -> str:
    for _ in range(1000):
        province = rng.choice(PROVINCES)
        series_len = 2 if rng.random() < 0.22 else 1
        series = "".join(rng.choice(SERIES) for _ in range(series_len))
        digits_len = 5 if rng.random() < 0.65 else 4
        digits = "".join(str(rng.randrange(10)) for _ in range(digits_len))
        text = normalize_ground_truth(f"{province:02d}{series}{digits}")
        if text not in used:
            used.add(text)
            return text
    raise RuntimeError("Không sinh được chuỗi duy nhất")


def main() -> int:
    parser = argparse.ArgumentParser(description="Sinh bộ dữ liệu tổng hợp")
    parser.add_argument("--clean", action="store_true", help="Xóa bộ dữ liệu cũ")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--samples-dir", default=None)
    parser.add_argument("--labels", default=None)
    args = parser.parse_args()

    config = load_config()
    samples_dir = (
        Path(args.samples_dir) if args.samples_dir else config.samples_dir
    )
    samples_dir = samples_dir if samples_dir.is_absolute() else ROOT / samples_dir
    labels_path = Path(args.labels) if args.labels else config.labels_file
    labels_path = labels_path if labels_path.is_absolute() else ROOT / labels_path
    if args.clean and samples_dir.exists():
        shutil.rmtree(samples_dir)
    samples_dir.mkdir(parents=True, exist_ok=True)
    labels_path.parent.mkdir(parents=True, exist_ok=True)

    fonts = [Path(p) for p in SAMPLE_FONTS if Path(p).exists()]
    if not fonts:
        print("LỖI: không tìm thấy font mẫu.", file=sys.stderr)
        return 1

    rows: List[Dict[str, str]] = []
    manifest: List[Dict[str, object]] = []
    used_texts: set[str] = set()
    seed = args.seed

    for split in ("dev", "test"):
        plan = CONDITION_PLAN[split]
        for condition, count in plan:
            for index in range(count):
                rng = random.Random(seed)
                seed += 1
                scene = make_scene(rng)
                if condition == "no_plate":
                    image = scene
                    bbox = None
                    char_boxes: List[Tuple[float, float, float, float]] = []
                    compact = ""
                    plate_type = "none"
                    font_name = ""
                    quality = 90
                    image, quality = degrade(image, "clear", rng)
                else:
                    compact = random_plate_text(rng, used_texts)
                    plate_type = "two_line" if condition == "two_line" else "one_line"
                    font_path = str(rng.choice(fonts))
                    yellow = rng.random() < 0.12
                    plate = render_plate_texture(
                        compact,
                        plate_type,
                        font_path,
                        rng,
                        touching=(condition == "touching"),
                        yellow=yellow,
                    )
                    image, bbox, char_boxes, quad = composite_plate(
                        scene, plate, condition, rng
                    )
                    font_name = plate.font_name
                    image, quality = degrade(image, condition, rng)
                    if condition == "low_resolution":
                        scale = image.shape[1] / 960.0
                        bbox = (
                            int(round(bbox[0] * scale)),
                            int(round(bbox[1] * scale)),
                            int(round(bbox[2] * scale)),
                            int(round(bbox[3] * scale)),
                        )
                        char_boxes = [
                            (
                                b[0] * scale,
                                b[1] * scale,
                                b[2] * scale,
                                b[3] * scale,
                            )
                            for b in char_boxes
                        ]

                name = f"{split}_{condition}_{index + 1:03d}.jpg"
                ext = ".jpg"
                path = samples_dir / name
                write_image(path, image, jpeg_quality=quality)
                # Ghi lại đúng kích thước sau khi lưu (để bbox nhất quán)
                h, w = image.shape[:2]
                row = {
                    "image_name": name,
                    "ground_truth": compact,
                    "plate_type": plate_type,
                    "split": split,
                    "condition": condition,
                    "notes": (
                        f"Tổng hợp; font={font_name}; size={w}x{h}; "
                        f"jpeg_q={quality}"
                    ),
                    "x1": "" if bbox is None else f"{bbox[0]:.2f}",
                    "y1": "" if bbox is None else f"{bbox[1]:.2f}",
                    "x2": "" if bbox is None else f"{bbox[2]:.2f}",
                    "y2": "" if bbox is None else f"{bbox[3]:.2f}",
                    "char_boxes": json.dumps(
                        [[round(v, 2) for v in b] for b in char_boxes],
                        separators=(",", ":"),
                    ),
                }
                rows.append(row)
                manifest.append(
                    {
                        **row,
                        "font": font_name,
                        "image_size": [w, h],
                        "quad": quad if condition != "no_plate" else None,
                        "synthetic": True,
                    }
                )
                print(f"  {name}  GT={compact or '(không biển)'}  {condition}")

    fieldnames = [
        "image_name",
        "ground_truth",
        "plate_type",
        "split",
        "condition",
        "notes",
        "x1",
        "y1",
        "x2",
        "y2",
        "char_boxes",
    ]
    with labels_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    manifest_path = samples_dir.parent / "synthetic_manifest.json"
    with manifest_path.open("w", encoding="utf-8") as fh:
        json.dump(
            {
                "note": (
                    "Dữ liệu tổng hợp cho demo/kiểm thử. Không dùng để tuyên bố "
                    "độ chính xác trên ảnh thực tế."
                ),
                "seed": args.seed,
                "count": len(rows),
                "rows": manifest,
            },
            fh,
            ensure_ascii=False,
            indent=2,
        )

    readme = (
        "# Bộ ảnh mẫu\n\n"
        "Đây là **dữ liệu tổng hợp** do `tools/build_synthetic_dataset.py` sinh ra, "
        "phục vụ demo và kiểm thử tái lập. Không phải ảnh thực tế và không dùng "
        "để tuyên bố độ chính xác thực tế.\n\n"
        "Các tình huống: ảnh rõ, nghiêng, thiếu sáng, biển hai dòng, ký tự dính, "
        "chất lượng thấp, không có biển, độ phân giải thấp.\n\n"
        "Để đánh giá thực tế, thay ảnh tại đây bằng ảnh của bạn và cập nhật "
        "`data/labels.csv` (có thể thêm `char_boxes` dạng JSON nếu có nhãn từng ký tự).\n"
    )
    (samples_dir / "README.md").write_text(readme, encoding="utf-8")
    print(
        f"\nĐã sinh {len(rows)} ảnh tại {samples_dir} và nhãn tại {labels_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

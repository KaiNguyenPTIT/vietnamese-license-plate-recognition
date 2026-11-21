"""Sinh bộ template ký tự từ font hệ thống (xử lý ảnh truyền thống).

Đây là công cụ hỗ trợ chuẩn bị dữ liệu, KHÔNG phải mô hình học máy. Template
được render từ nhiều font, sau đó được kiểm tra/chuẩn hóa bởi chính module
nhận dạng. Người dùng nên bổ sung ảnh ký tự thật đã xác minh vào cùng thư mục
nhãn để tăng độ đa dạng.

Cách dùng:
    python tools/build_templates.py
    python tools/build_templates.py --clean
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import load_config  # noqa: E402
from src.io_utils import write_image  # noqa: E402


LABELS = list("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ")

# Các font dùng để sinh template. Có thể bổ sung font khác trên máy.
FONT_CANDIDATES = [
    ("arial_bold", "C:/Windows/Fonts/arialbd.ttf"),
    ("arial_narrow_bold", "C:/Windows/Fonts/ARIALNB.TTF"),
    ("arial_regular", "C:/Windows/Fonts/arial.ttf"),
    ("arial_narrow", "C:/Windows/Fonts/ARIALN.TTF"),
    ("arial_black", "C:/Windows/Fonts/ariblk.ttf"),
    ("tahoma_bold", "C:/Windows/Fonts/tahomabd.ttf"),
    ("tahoma_regular", "C:/Windows/Fonts/tahoma.ttf"),
    ("segoeui_bold", "C:/Windows/Fonts/segoeuib.ttf"),
    ("segoeui_semibold", "C:/Windows/Fonts/seguisb.ttf"),
    ("consolas_bold", "C:/Windows/Fonts/consolab.ttf"),
    # Nhóm font chân (serif) giúp phủ biển số dùng font có chân.
    # Không dùng đúng các font của bộ dữ liệu tổng hợp để tránh "học thuộc".
    ("cambria_bold", "C:/Windows/Fonts/cambriab.ttf"),
    ("georgia_bold", "C:/Windows/Fonts/georgiab.ttf"),
    ("constantia_bold", "C:/Windows/Fonts/constanb.ttf"),
    ("book_antiqua_bold", "C:/Windows/Fonts/BOOKOSB.TTF"),
    ("palatino_bold", "C:/Windows/Fonts/palab.ttf"),
]

FONT_SIZE = 140
PADDING = 8


def render_character(font_path: Path, character: str) -> np.ndarray:
    """Render một ký tự thành ảnh xám, nền trắng chữ đen."""
    font = ImageFont.truetype(str(font_path), FONT_SIZE)
    probe = Image.new("L", (FONT_SIZE * 3, FONT_SIZE * 3), 255)
    draw = ImageDraw.Draw(probe)
    bbox = draw.textbbox((0, 0), character, font=font)
    if bbox is None:
        raise ValueError(f"Không lấy được bbox cho ký tự {character!r}")
    left, top, right, bottom = bbox
    w = right - left
    h = bottom - top
    if w <= 0 or h <= 0:
        raise ValueError(f"Ký tự {character!r} có kích thước 0")
    canvas_w = w + 2 * PADDING
    canvas_h = h + 2 * PADDING
    image = Image.new("L", (canvas_w, canvas_h), 255)
    draw = ImageDraw.Draw(image)
    draw.text((PADDING - left, PADDING - top), character, font=font, fill=0)
    return np.array(image, dtype=np.uint8)


def make_variants(image: np.ndarray) -> List[Tuple[str, np.ndarray]]:
    """Tạo biến thể nét dày/nét mảnh nhẹ để tăng độ phủ template."""
    variants: List[Tuple[str, np.ndarray]] = [("normal", image)]
    # Ảnh nhị phân để phép giãn/co có ý nghĩa
    _, binary = cv2.threshold(image, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    ink = cv2.bitwise_not(binary)  # chữ trắng
    kernel = np.ones((2, 2), np.uint8)
    thick = cv2.dilate(ink, kernel, iterations=1)
    thin = cv2.erode(ink, kernel, iterations=1)
    for name, variant in (("thick", thick), ("thin", thin)):
        if np.count_nonzero(variant) < 10:
            continue
        variants.append((name, cv2.bitwise_not(variant)))
    return variants


def main() -> int:
    parser = argparse.ArgumentParser(description="Sinh template ký tự từ font")
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Xóa toàn bộ thư mục template trước khi sinh (cẩn thận)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Thư mục đầu ra (mặc định theo config.yaml)",
    )
    args = parser.parse_args()

    config = load_config()
    out_dir = Path(args.output) if args.output else config.templates_dir
    out_dir = out_dir if out_dir.is_absolute() else ROOT / out_dir
    if args.clean and out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    fonts: List[Tuple[str, Path]] = []
    missing_fonts: List[str] = []
    for name, path in FONT_CANDIDATES:
        p = Path(path)
        if p.exists():
            fonts.append((name, p))
        else:
            missing_fonts.append(path)
    if not fonts:
        print("LỖI: không tìm thấy font TrueType nào trong danh sách.", file=sys.stderr)
        return 1

    total = 0
    for label in LABELS:
        label_dir = out_dir / label
        label_dir.mkdir(parents=True, exist_ok=True)
        for font_name, font_path in fonts:
            try:
                image = render_character(font_path, label)
            except Exception as exc:
                print(f"Bỏ qua {label} - {font_name}: {exc}", file=sys.stderr)
                continue
            for variant_name, variant in make_variants(image):
                filename = f"{font_name}_{variant_name}.png"
                write_image(label_dir / filename, variant)
                total += 1

    meta = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "labels": LABELS,
        "fonts": [name for name, _ in fonts],
        "missing_fonts": missing_fonts,
        "font_size": FONT_SIZE,
        "variants": ["normal", "thick", "thin"],
        "total_files": total,
        "note": (
            "Template được render từ font hệ thống, không phải mô hình học máy. "
            "Nên bổ sung ảnh ký tự thật đã được xác minh vào từng thư mục nhãn. "
            "Không tự động đưa dự đoán chưa kiểm chứng vào bộ template."
        ),
    }
    with (out_dir / "meta.json").open("w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)

    readme = (
        "# Bộ template ký tự\n\n"
        "Mỗi thư mục con là một nhãn (0-9, A-Z). Mỗi file PNG/JPG là một mẫu.\n\n"
        "- Template được sinh tự động từ font bằng `tools/build_templates.py`.\n"
        "- Có thể thêm ảnh ký tự thật đã cắt và đã xác minh vào đúng thư mục nhãn.\n"
        "- Không đưa kết quả dự đoán chưa kiểm chứng vào bộ template.\n"
        "- Kích thước template gốc không quan trọng; module nhận dạng sẽ chuẩn hóa "
        "về cùng kích thước với ảnh truy vấn.\n"
    )
    (out_dir / "README.md").write_text(readme, encoding="utf-8")
    print(f"Đã sinh {total} template cho {len(LABELS)} nhãn tại: {out_dir}")
    print(f"Font sử dụng: {', '.join(name for name, _ in fonts)}")
    if missing_fonts:
        print(f"Font không tìm thấy: {', '.join(missing_fonts)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

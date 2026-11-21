"""Sinh các hình minh họa cho báo cáo Word.

Các hình được tạo từ ảnh debug thật của pipeline và từ dữ liệu kết quả,
không vẽ lại bằng tay các số liệu. Chạy:

    python tools\\build_report_assets.py

Đầu ra nằm trong ``reports/assets/``.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "reports" / "assets"
ASSETS.mkdir(parents=True, exist_ok=True)

FONT_REGULAR = Path("C:/Windows/Fonts/arial.ttf")
FONT_BOLD = Path("C:/Windows/Fonts/arialbd.ttf")
FONT_MONO = Path("C:/Windows/Fonts/consola.ttf")

# Ảnh thật dùng cho hình minh họa từng công đoạn và cho mục "ví dụ chạy tay".
WALKTHROUGH_IMAGE = ROOT / "data" / "user_images" / "14.webp"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = FONT_BOLD if bold else FONT_REGULAR
    try:
        return ImageFont.truetype(str(path), size)
    except OSError:
        return ImageFont.load_default()


def fit_image(
    path: Path, box: tuple[int, int], upscale: bool = False
) -> Image.Image:
    image = Image.open(path).convert("RGB")
    if upscale:
        ratio = min(box[0] / image.width, box[1] / image.height)
        size = (
            max(1, int(round(image.width * ratio))),
            max(1, int(round(image.height * ratio))),
        )
        image = image.resize(size, Image.LANCZOS)
    else:
        image.thumbnail(box, Image.LANCZOS)
    return image


def paste_center(
    canvas: Image.Image, image: Image.Image, box: tuple[int, int, int, int]
) -> None:
    x1, y1, x2, y2 = box
    px = x1 + (x2 - x1 - image.width) // 2
    py = y1 + (y2 - y1 - image.height) // 2
    canvas.paste(image, (px, py))


def arrow(
    draw: ImageDraw.ImageDraw,
    start: tuple[int, int],
    end: tuple[int, int],
    color: tuple[int, int, int] = (90, 90, 90),
    width: int = 4,
) -> None:
    draw.line([start, end], fill=color, width=width)
    x1, y1 = start
    x2, y2 = end
    if abs(x2 - x1) >= abs(y2 - y1):
        direction = 1 if x2 > x1 else -1
        points = [
            (x2, y2),
            (x2 - 14 * direction, y2 - 8),
            (x2 - 14 * direction, y2 + 8),
        ]
    else:
        direction = 1 if y2 > y1 else -1
        points = [
            (x2, y2),
            (x2 - 8, y2 - 14 * direction),
            (x2 + 8, y2 - 14 * direction),
        ]
    draw.polygon(points, fill=color)


def build_pipeline() -> None:
    width, height = 1800, 620
    canvas = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(canvas)

    stages = [
        ("1. Ảnh đầu vào", "JPG / JPEG / PNG / WEBP"),
        ("2. Tiền xử lý", "grayscale, blur, Canny, Otsu"),
        ("3. Phát hiện biển", "contour + cụm ký tự + điểm"),
        ("4. Hiệu chỉnh", "perspective / deskew / bbox"),
        ("5. Phân đoạn", "projection + contour + valley"),
        ("6. Nhận dạng", "32×48, TM_CCOEFF_NORMED"),
        ("7. Hậu xử lý", "regex, rerank vị trí, trạng thái"),
        ("8. Kết quả", "chuỗi, bbox, CSV/JSON, UI"),
    ]
    boxes: list[tuple[int, int, int, int]] = []
    box_w, box_h = 380, 150
    xs = [40, 490, 940, 1390]
    ys = [55, 390]
    for i, (title, subtitle) in enumerate(stages):
        row = 0 if i < 4 else 1
        col = i if i < 4 else 7 - i
        x = xs[col]
        y = ys[row]
        boxes.append((x, y, x + box_w, y + box_h))

    for index, (x1, y1, x2, y2) in enumerate(boxes):
        title, subtitle = stages[index]
        draw.rounded_rectangle(
            (x1, y1, x2, y2),
            radius=18,
            fill=(232, 240, 252) if index < 7 else (226, 240, 217),
            outline=(46, 84, 150) if index < 7 else (56, 118, 29),
            width=4,
        )
        f_title = font(30, bold=True)
        f_sub = font(20)
        tb = draw.textbbox((0, 0), title, font=f_title)
        draw.text(
            ((x1 + x2 - (tb[2] - tb[0])) / 2, y1 + 34),
            title,
            fill=(20, 40, 80),
            font=f_title,
        )
        sb = draw.textbbox((0, 0), subtitle, font=f_sub)
        draw.text(
            ((x1 + x2 - (sb[2] - sb[0])) / 2, y1 + 95),
            subtitle,
            fill=(55, 55, 55),
            font=f_sub,
        )

    # Mũi tên hàng trên và hàng dưới
    for i in range(3):
        arrow(draw, (boxes[i][2] + 8, boxes[i][1] + box_h // 2),
              (boxes[i + 1][0] - 8, boxes[i][1] + box_h // 2))
    for i in range(4, 7):
        arrow(draw, (boxes[i][0] - 8, boxes[i][1] + box_h // 2),
              (boxes[i + 1][2] + 8, boxes[i][1] + box_h // 2))
    # Nối hàng trên sang hàng dưới
    arrow(draw, (boxes[3][0] + box_w // 2, boxes[3][3] + 8),
          (boxes[3][0] + box_w // 2, boxes[4][1] - 8))

    canvas.save(ASSETS / "pipeline.png")
    print("pipeline.png", canvas.size)


def build_panel(
    items: list[tuple[str, Path]],
    out_name: str,
    columns: int = 2,
    cell: tuple[int, int] = (660, 360),
    canvas_size: tuple[int, int] | None = None,
    upscale: bool = False,
) -> None:
    rows = (len(items) + columns - 1) // columns
    cw, ch = cell
    margin = 30
    label_h = 44
    width = margin * 2 + columns * cw
    height = margin * 2 + rows * (ch + label_h)
    if canvas_size:
        width, height = canvas_size
    canvas = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(canvas)

    for index, (label, path) in enumerate(items):
        row = index // columns
        col = index % columns
        x = margin + col * cw
        y = margin + row * (ch + label_h)
        draw.rectangle(
            (x, y, x + cw - 10, y + ch + label_h - 10),
            outline=(200, 200, 200),
            width=2,
        )
        draw.text((x + 14, y + 8), label, fill=(25, 25, 25), font=font(24, bold=True))
        if path.exists():
            image = fit_image(path, (cw - 30, ch - 10), upscale=upscale)
            paste_center(
                canvas,
                image,
                (x + 10, y + label_h, x + cw - 20, y + label_h + ch - 10),
            )
        else:
            draw.text(
                (x + 14, y + label_h + 30),
                "(không tìm thấy ảnh)",
                fill=(180, 0, 0),
                font=font(20),
            )
    canvas.save(ASSETS / out_name)
    print(out_name, canvas.size)


def ensure_debug(image: Path) -> Path:
    """Trả về thư mục ảnh debug của một ảnh, sinh lại nếu chưa có.

    Bản phát hành không kèm thư mục debug (nặng và chỉ là sản phẩm phụ),
    nên hàm này chạy lại pipeline với ``save_debug`` để tạo đúng các tệp
    mà các hình minh họa cần.
    """
    out = ROOT / "results" / "debug_after" / image.stem
    if (out / "14_character_strip.png").exists():
        return out

    sys.path.insert(0, str(ROOT))
    from src.config import load_config
    from src.pipeline import LicensePlateRecognizer

    config = load_config(ROOT / "config.yaml")
    recognizer = LicensePlateRecognizer(config)
    result = recognizer.recognize(str(image), save_debug=True, debug_dir=out)
    print(f"debug {image.name}: {result.status} {result.detected_text}")
    return out


def build_preprocess_panel() -> None:
    base = ensure_debug(WALKTHROUGH_IMAGE)
    build_panel(
        [
            ("Ảnh gốc", base / "01_original.png"),
            ("Grayscale", base / "03_gray.png"),
            ("Cạnh Canny", base / "06_edges.png"),
            ("Nhị phân Otsu", base / "07_binary_otsu.png"),
        ],
        "preprocess_panel.png",
        columns=2,
        cell=(670, 360),
    )


def build_segmentation_panel() -> None:
    base = ensure_debug(WALKTHROUGH_IMAGE)
    build_panel(
        [
            ("Vùng cắt có padding", base / "11_plate_crop.png"),
            ("Sau hiệu chỉnh phối cảnh", base / "12_plate_rectified.png"),
            ("Ảnh nhị phân", base / "13_plate_binary.png"),
            ("Dải ký tự sau phân đoạn", base / "14_character_strip.png"),
        ],
        "segmentation_panel.png",
        columns=2,
        cell=(680, 360),
        canvas_size=(1450, 900),
        upscale=True,
    )


def build_candidates() -> None:
    source = ensure_debug(WALKTHROUGH_IMAGE) / "08_candidates.png"
    image = Image.open(source).convert("RGB")
    ratio = 1000 / image.width
    image = image.resize(
        (1000, max(1, int(round(image.height * ratio)))), Image.LANCZOS
    )
    image.save(ASSETS / "candidates.png")
    print("candidates.png", image.size)


def build_walkthrough() -> None:
    """Sáu khung của cùng một ảnh, theo đúng thứ tự tám công đoạn."""
    base = ensure_debug(WALKTHROUGH_IMAGE)
    build_panel(
        [
            ("1. Ảnh gốc và hộp biển được chọn", base / "09_selected_bbox.png"),
            ("2. Ba ứng viên trước khi chọn", base / "08_candidates.png"),
            ("3. Cắt vùng biển có padding", base / "11_plate_crop.png"),
            ("4. Hiệu chỉnh (fallback bbox)", base / "12_plate_rectified.png"),
            ("5. Nhị phân Otsu", base / "13_plate_binary.png"),
            ("6. Tám ký tự sau phân đoạn", base / "14_character_strip.png"),
        ],
        "walkthrough.png",
        columns=3,
        cell=(560, 330),
        upscale=True,
    )



def build_template_grid() -> None:
    labels = ["0", "1", "4", "6", "8", "A"]
    variants = [
        ("arial_regular_normal.png", "Arial Regular"),
        ("arial_black_normal.png", "Arial Black"),
        ("book_antiqua_bold_normal.png", "Book Antiqua Bold"),
        ("consolas_bold_normal.png", "Consolas Bold"),
    ]
    cell_w, cell_h = 150, 170
    margin = 30
    label_w = 210
    width = margin * 2 + label_w + cell_w * len(labels)
    height = margin * 2 + cell_h * len(variants)
    canvas = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(canvas)
    for col, label in enumerate(labels):
        cx = margin + label_w + col * cell_w + cell_w // 2
        draw.text(
            (cx - 12, 8),
            label,
            fill=(20, 40, 80),
            font=font(32, bold=True),
        )
    for row, (variant, title) in enumerate(variants):
        y = margin + row * cell_h
        draw.text(
            (margin + 4, y + cell_h // 2 - 14),
            title,
            fill=(35, 35, 35),
            font=font(23, bold=True),
        )
        for col, label in enumerate(labels):
            path = ROOT / "data" / "templates" / label / variant
            x = margin + label_w + col * cell_w
            draw.rectangle(
                (x, y, x + cell_w - 8, y + cell_h - 8),
                outline=(210, 210, 210),
                width=2,
            )
            if path.exists():
                image = fit_image(path, (cell_w - 30, cell_h - 30))
                paste_center(
                    canvas, image, (x + 8, y + 8, x + cell_w - 12, y + cell_h - 12)
                )
    canvas.save(ASSETS / "template_grid.png")
    print("template_grid.png", canvas.size)


def build_metrics_chart() -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    try:
        font_manager.fontManager.addfont(str(FONT_REGULAR))
        plt.rcParams["font.family"] = "Arial"
    except Exception:
        pass

    summaries = {
        "Dev (26 ảnh)": json.loads(
            (ROOT / "results" / "dev_after_final_summary.json").read_text(
                encoding="utf-8"
            )
        ),
        "Test (26 ảnh)": json.loads(
            (ROOT / "results" / "test_after_final_summary.json").read_text(
                encoding="utf-8"
            )
        ),
    }
    metrics = ["PDR", "CSA", "CA", "EPA", "Success"]
    keys = [
        "plate_detection_rate",
        "character_segmentation_accuracy",
        "character_accuracy",
        "exact_plate_accuracy",
        "success_rate",
    ]
    values = {
        name: [summary[key] * 100.0 for key in keys]
        for name, summary in summaries.items()
    }

    fig, ax = plt.subplots(figsize=(9.2, 5.0), dpi=200)
    x = range(len(metrics))
    width = 0.36
    colors = ["#2E75B6", "#C55A11"]
    bars_list = []
    for index, (name, vals) in enumerate(values.items()):
        bars = ax.bar(
            [i + (index - 0.5) * width for i in x],
            vals,
            width,
            label=name,
            color=colors[index],
        )
        bars_list.append(bars)
    ax.set_ylim(0, 110)
    ax.set_ylabel("Phần trăm (%)")
    ax.set_title("So sánh chỉ số trên hai tập tổng hợp")
    ax.set_xticks(list(x))
    ax.set_xticklabels(metrics)
    ax.grid(axis="y", linestyle="--", alpha=0.35)
    ax.set_axisbelow(True)
    ax.legend(loc="upper right", frameon=False)
    for bars in bars_list:
        for bar in bars:
            value = bar.get_height()
            ax.annotate(
                f"{value:.2f}",
                xy=(bar.get_x() + bar.get_width() / 2, value),
                xytext=(0, 4),
                textcoords="offset points",
                ha="center",
                va="bottom",
                fontsize=8,
            )
    fig.tight_layout()
    fig.savefig(ASSETS / "metrics_chart.png", bbox_inches="tight")
    plt.close(fig)
    print("metrics_chart.png")


def build_condition_chart() -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    try:
        font_manager.fontManager.addfont(str(FONT_REGULAR))
        plt.rcParams["font.family"] = "Arial"
    except Exception:
        pass

    conditions = [
        ("clear", "Rõ"),
        ("tilted", "Nghiêng"),
        ("low_light", "Thiếu sáng"),
        ("two_line", "Hai dòng"),
        ("touching", "Dính ký tự"),
        ("low_quality", "Chất lượng thấp"),
        ("low_resolution", "Độ phân giải thấp"),
    ]
    series = {}
    for split, path in [
        ("Dev", ROOT / "results" / "dev_after_final.csv"),
        ("Test", ROOT / "results" / "test_after_final.csv"),
    ]:
        rows = [
            row
            for row in csv.DictReader(path.open(encoding="utf-8-sig"))
            if row["has_gt_plate"] == "1"
        ]
        by_condition = {}
        for row in rows:
            by_condition.setdefault(row["condition"], []).append(row)
        series[split] = [
            (
                sum(1 for row in by_condition.get(key, []) if row["exact_match"] == "1")
                / max(1, len(by_condition.get(key, [])))
                * 100.0
            )
            for key, _ in conditions
        ]

    fig, ax = plt.subplots(figsize=(10.0, 4.8), dpi=200)
    x = range(len(conditions))
    width = 0.38
    bars1 = ax.bar(
        [i - width / 2 for i in x], series["Dev"], width, label="Dev", color="#2E75B6"
    )
    bars2 = ax.bar(
        [i + width / 2 for i in x], series["Test"], width, label="Test", color="#C55A11"
    )
    ax.set_ylim(0, 105)
    ax.set_ylabel("Tỷ lệ khớp hoàn toàn (%)")
    ax.set_title("Tỷ lệ EPA theo điều kiện (chỉ ảnh có biển)")
    ax.set_xticks(list(x))
    ax.set_xticklabels([label for _, label in conditions], rotation=20, ha="right")
    ax.grid(axis="y", linestyle="--", alpha=0.35)
    ax.set_axisbelow(True)
    ax.legend(loc="upper right", frameon=False)
    for bars in (bars1, bars2):
        for bar in bars:
            value = bar.get_height()
            ax.annotate(
                f"{value:.0f}",
                xy=(bar.get_x() + bar.get_width() / 2, value),
                xytext=(0, 3),
                textcoords="offset points",
                ha="center",
                va="bottom",
                fontsize=8,
            )
    fig.tight_layout()
    fig.savefig(ASSETS / "condition_chart.png", bbox_inches="tight")
    plt.close(fig)
    print("condition_chart.png")


def build_ui_screenshot() -> None:
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass

    import time

    from PIL import ImageGrab

    sys.path.insert(0, str(ROOT))
    from src.config import load_config
    from ui.app import PlateRecognitionApp

    config = load_config(ROOT / "config.yaml")
    app = PlateRecognitionApp(config)
    app.minsize(1, 1)
    app.geometry("1400x820+0+0")
    image_path = ROOT / "data" / "user_images" / "14.webp"
    app.image_path = image_path
    app.file_var.set(str(image_path))
    app._show_original_only()
    app.update_idletasks()
    app.update()
    result = app.recognizer.recognize(str(image_path))
    app.result = result
    app._render_result(result)
    app.status_var.set(
        f"Hoàn tất: {result.display_status} ({result.total_time_ms:.0f} ms)"
    )
    app.lift()
    app.attributes("-topmost", True)
    app.focus_force()
    app.update_idletasks()
    app.update()
    time.sleep(1.0)
    app.update()
    x = app.winfo_rootx()
    y = app.winfo_rooty()
    w = app.winfo_width()
    h = app.winfo_height()
    image = ImageGrab.grab(bbox=(x, y, x + w, y + h))
    image.save(ASSETS / "ui.png")
    print("ui.png", image.size, result.status, result.detected_text)
    app.destroy()


def main() -> int:
    build_pipeline()
    build_preprocess_panel()
    build_segmentation_panel()
    build_candidates()
    build_walkthrough()
    build_template_grid()
    build_metrics_chart()
    build_condition_chart()
    build_ui_screenshot()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

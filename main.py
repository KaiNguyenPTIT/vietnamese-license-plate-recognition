"""Điểm khởi chạy hệ thống nhận dạng biển số xe Việt Nam.

Ví dụ:
    python main.py                       # mở giao diện
    python main.py ui
    python main.py recognize data/samples/dev_clear_001.jpg --save-debug
    python main.py evaluate --split test
    python main.py batch data/samples
    python main.py info
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.config import load_config  # noqa: E402
from src.evaluation import (  # noqa: E402
    format_summary_text,
    load_labels,
    run_evaluation,
    write_evaluation_csv,
    write_summary_json,
    write_summary_markdown,
)
from src.io_utils import list_images, write_image  # noqa: E402
from src.pipeline import (  # noqa: E402
    LicensePlateRecognizer,
    make_character_strip,
    save_debug_artifacts,
)


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--config", default=None, help="Đường dẫn config.yaml (mặc định: ./config.yaml)"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Hệ thống nhận dạng biển số xe Việt Nam bằng xử lý ảnh truyền thống"
    )
    sub = parser.add_subparsers(dest="command")

    ui_parser = sub.add_parser("ui", help="Mở giao diện Tkinter")
    _add_common(ui_parser)

    rec = sub.add_parser("recognize", help="Nhận dạng một ảnh")
    rec.add_argument("image", help="Đường dẫn ảnh JPG/JPEG/PNG")
    rec.add_argument("--save-debug", action="store_true", help="Lưu ảnh trung gian")
    rec.add_argument("--debug-dir", default=None, help="Thư mục lưu ảnh debug")
    rec.add_argument("--json", action="store_true", help="In JSON đầy đủ")
    rec.add_argument(
        "--output-csv", default=None, help="Ghi kết quả một dòng ra CSV"
    )
    _add_common(rec)

    ev = sub.add_parser("evaluate", help="Đánh giá trên bộ dữ liệu có nhãn")
    ev.add_argument("--labels", default=None, help="File labels.csv")
    ev.add_argument(
        "--split",
        default=None,
        help="Tập đánh giá: dev, test, user, ... hoặc all (mặc định: tất cả)",
    )
    ev.add_argument("--samples-dir", default=None, help="Thư mục ảnh")
    ev.add_argument("--output-csv", default=None, help="File CSV kết quả từng ảnh")
    ev.add_argument("--summary-json", default=None, help="File JSON tổng hợp")
    ev.add_argument("--summary-md", default=None, help="File Markdown tổng hợp")
    _add_common(ev)

    batch = sub.add_parser("batch", help="Nhận dạng toàn bộ ảnh trong thư mục")
    batch.add_argument("directory", help="Thư mục chứa ảnh")
    batch.add_argument("--output-csv", default=None, help="File CSV kết quả")
    batch.add_argument("--save-debug", action="store_true", help="Lưu ảnh debug")
    _add_common(batch)

    info = sub.add_parser("info", help="Hiển thị thông tin cấu hình và template")
    _add_common(info)
    return parser


def cmd_recognize(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    recognizer = LicensePlateRecognizer(config)
    result = recognizer.recognize(
        args.image, save_debug=args.save_debug, debug_dir=args.debug_dir
    )
    if args.json:
        print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"Ảnh: {result.image_path}")
        print(f"Trạng thái: {result.status} ({result.display_status})")
        print(f"Chuỗi: {result.detected_text}")
        print(f"Raw: {result.raw_text}")
        print(f"Thông báo: {result.message}")
        if result.text:
            print(
                f"Điểm TB/thấp nhất: {result.text.mean_score:.3f} / "
                f"{result.text.min_score:.3f}"
            )
            print(f"Định dạng hợp lệ: {result.text.validation.is_valid}")
        print(f"Hiệu chỉnh: {result.rectification_method}")
        print(f"Thời gian: {result.total_time_ms:.1f} ms")
        print(
            "Thời gian từng công đoạn: "
            + ", ".join(
                f"{k}={v:.1f}ms" for k, v in result.timings_ms.items()
            )
        )
        if result.warnings:
            print("Cảnh báo:")
            for w in result.warnings:
                print(f"  - {w}")
        if result.char_boxes_original:
            print("Ký tự:")
            for item in result.char_boxes_original:
                print(
                    f"  {item['order'] + 1:02d}. row={item['row_index']} "
                    f"label={item['label']} status={item['status']} "
                    f"score={item['score']:.3f} margin={item['margin']:.3f} "
                    f"second={item['second_label']}:{item['second_score']:.3f}"
                )
        if result.debug_dir:
            print(f"Ảnh debug: {result.debug_dir}")
    if args.output_csv:
        out = Path(args.output_csv)
        out.parent.mkdir(parents=True, exist_ok=True)
        row = result.as_csv_row()
        with out.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(row.keys()))
            writer.writeheader()
            writer.writerow(row)
        print(f"Đã ghi CSV: {out}")
    return 0 if result.status in {"SUCCESS", "FORMAT_WARNING"} else 2


def cmd_evaluate(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    labels_path = Path(args.labels) if args.labels else config.labels_file
    labels = load_labels(labels_path)
    samples_dir = (
        Path(args.samples_dir) if args.samples_dir else config.samples_dir
    )
    recognizer = LicensePlateRecognizer(config)

    def progress(done: int, total: int, name: str) -> None:
        print(f"[{done}/{total}] {name}")

    split = None if args.split in {None, "all"} else args.split
    results, summary = run_evaluation(
        recognizer, labels, samples_dir, config, split=split, progress=progress
    )
    output_csv = (
        Path(args.output_csv)
        if args.output_csv
        else config.resolve(config.evaluation.output_csv)
    )
    summary_json = (
        Path(args.summary_json)
        if args.summary_json
        else config.resolve(config.evaluation.output_summary)
    )
    summary_md = (
        Path(args.summary_md) if args.summary_md else summary_json.with_suffix(".md")
    )
    write_evaluation_csv(results, output_csv)
    write_summary_json(summary, summary_json)
    write_summary_markdown(summary, summary_md)
    print()
    print(format_summary_text(summary))
    print(f"\nCSV: {output_csv}")
    print(f"JSON: {summary_json}")
    print(f"Markdown: {summary_md}")
    return 0


def cmd_batch(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    directory = Path(args.directory)
    paths = list_images(directory, config.image.allowed_extensions)
    if not paths:
        print(f"Không tìm thấy ảnh trong: {directory}", file=sys.stderr)
        return 1
    recognizer = LicensePlateRecognizer(config)
    rows = []
    for idx, path in enumerate(paths, start=1):
        result = recognizer.recognize(path, save_debug=args.save_debug)
        rows.append(result.as_csv_row())
        print(
            f"[{idx}/{len(paths)}] {path.name}: {result.status} "
            f"{result.detected_text!r}"
        )
    output = (
        Path(args.output_csv)
        if args.output_csv
        else config.resolve("results/batch_results.csv")
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Đã ghi: {output}")
    return 0


def cmd_info(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    recognizer = LicensePlateRecognizer(config)
    print(f"File cấu hình: {config.config_path}")
    print(f"Thư mục template: {config.templates_dir}")
    print(f"Thư mục ảnh mẫu: {config.samples_dir}")
    print(f"File nhãn: {config.labels_file}")
    print(f"Template: {recognizer.library.stats()}")
    if recognizer.template_error:
        print(f"LỖI TEMPLATE: {recognizer.template_error}")
    print(f"Số ảnh mẫu: {len(list_images(config.samples_dir, config.image.allowed_extensions))}")
    print(f"Cấu hình: {json.dumps(config.to_dict(), ensure_ascii=False, indent=2)}")
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    command = args.command
    if command is None or command == "ui":
        from ui.app import main as ui_main

        return ui_main(config_path=getattr(args, "config", None))
    if command == "recognize":
        return cmd_recognize(args)
    if command == "evaluate":
        return cmd_evaluate(args)
    if command == "batch":
        return cmd_batch(args)
    if command == "info":
        return cmd_info(args)
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

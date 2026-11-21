"""Giao diện Tkinter cho hệ thống nhận dạng biển số xe.

Giao diện gồm:
    - Chọn ảnh, nhận dạng, lưu ảnh trung gian, xuất CSV.
    - Xem ảnh gốc + bounding box, ảnh tiền xử lý, crop/hiệu chỉnh biển số.
    - Xem từng ký tự đã phân đoạn cùng điểm tương đồng.
    - Bảng kết quả từng ký tự, trạng thái, cảnh báo, thời gian xử lý.
    - Đánh giá hàng loạt bộ dữ liệu và xuất CSV/JSON/Markdown.
"""

from __future__ import annotations

import csv
import queue
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

import cv2
import numpy as np
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    from PIL import Image, ImageTk
except ImportError:  # pragma: no cover
    Image = None
    ImageTk = None

from src.config import Config, load_config
from src.evaluation import (
    format_summary_text,
    load_labels,
    run_evaluation,
    write_evaluation_csv,
    write_summary_json,
    write_summary_markdown,
)
from src.pipeline import (
    LicensePlateRecognizer,
    RecognitionResult,
    make_character_strip,
    save_debug_artifacts,
)
from src.postprocessing import format_plate_text


STATUS_COLORS = {
    "SUCCESS": "#1b7f3a",
    "FORMAT_WARNING": "#b36b00",
    "LOW_CONFIDENCE": "#b3261e",
    "PLATE_NOT_FOUND": "#b3261e",
    "INVALID_IMAGE": "#b3261e",
    "CONFIG_ERROR": "#7a1fa2",
}

STATUS_TEXT = {
    "SUCCESS": "THÀNH CÔNG",
    "FORMAT_WARNING": "CẢNH BÁO ĐỊNH DẠNG",
    "LOW_CONFIDENCE": "KHÔNG ĐỦ TIN CẬY",
    "PLATE_NOT_FOUND": "KHÔNG TÌM THẤY BIỂN SỐ",
    "INVALID_IMAGE": "ẢNH KHÔNG HỢP LỆ",
    "CONFIG_ERROR": "LỖI CẤU HÌNH",
}


def bgr_to_photoimage(
    image: Optional[np.ndarray], max_w: int, max_h: int
) -> Optional[Any]:
    if image is None or image.size == 0 or Image is None or ImageTk is None:
        return None
    if image.ndim == 2:
        rgb = cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)
    else:
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    pil = Image.fromarray(rgb)
    pil.thumbnail((max_w, max_h), Image.LANCZOS)
    return ImageTk.PhotoImage(pil)


def draw_on_canvas(
    canvas: tk.Canvas,
    image: Optional[np.ndarray],
    max_w: Optional[int] = None,
    max_h: Optional[int] = None,
    ref_holder: Optional[Dict[str, Any]] = None,
    key: str = "default",
    text_if_empty: str = "(không có ảnh)",
) -> None:
    canvas.delete("all")
    if max_w is None:
        max_w = max(50, canvas.winfo_width() - 8)
    if max_h is None:
        max_h = max(50, canvas.winfo_height() - 8)
    photo = bgr_to_photoimage(image, max_w, max_h)
    if photo is None:
        canvas.create_text(
            max_w // 2,
            max_h // 2,
            text=text_if_empty,
            fill="#888888",
            font=("Segoe UI", 10),
        )
        return
    if ref_holder is not None:
        ref_holder[key] = photo
    x = max_w // 2
    y = max_h // 2
    canvas.create_image(x, y, anchor="center", image=photo)


class PlateRecognitionApp(tk.Tk):
    def __init__(self, config: Config):
        super().__init__()
        self.config = config
        self.recognizer = LicensePlateRecognizer(config)
        self.result: Optional[RecognitionResult] = None
        self.image_path: Optional[Path] = None
        self._image_refs: Dict[str, Any] = {}
        self._char_refs: List[Any] = []
        self._busy = False
        self._queue: "queue.Queue[Any]" = queue.Queue()

        self.title("Nhận dạng biển số xe Việt Nam - Xử lý ảnh truyền thống")
        self.geometry("1320x820")
        self.minsize(1100, 700)
        self._configure_style()
        self._build_ui()
        self._show_template_warning_if_needed()

    # ------------------------------------------------------------------
    def _configure_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use(self.config.ui.theme)
        except tk.TclError:
            try:
                style.theme_use("clam")
            except tk.TclError:
                pass
        style.configure("TLabelframe.Label", font=("Segoe UI", 10, "bold"))
        style.configure("TButton", padding=6)
        style.configure("Treeview", rowheight=24)

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        toolbar = ttk.Frame(self, padding=(8, 6))
        toolbar.pack(side=tk.TOP, fill=tk.X)
        self.btn_open = ttk.Button(
            toolbar, text="Chọn ảnh...", command=self.on_open_image
        )
        self.btn_open.pack(side=tk.LEFT, padx=(0, 6))
        self.btn_run = ttk.Button(
            toolbar, text="Nhận dạng", command=self.on_recognize
        )
        self.btn_run.pack(side=tk.LEFT, padx=(0, 6))
        self.btn_save_debug = ttk.Button(
            toolbar, text="Lưu ảnh trung gian", command=self.on_save_debug
        )
        self.btn_save_debug.pack(side=tk.LEFT, padx=(0, 6))
        self.btn_export = ttk.Button(
            toolbar, text="Xuất CSV kết quả", command=self.on_export_csv
        )
        self.btn_export.pack(side=tk.LEFT, padx=(0, 6))
        self.btn_eval = ttk.Button(
            toolbar, text="Đánh giá bộ dữ liệu...", command=self.on_evaluate
        )
        self.btn_eval.pack(side=tk.LEFT, padx=(0, 6))
        self.file_var = tk.StringVar(value="Chưa chọn ảnh")
        ttk.Label(toolbar, textvariable=self.file_var).pack(
            side=tk.LEFT, padx=12
        )
        ttk.Button(toolbar, text="Thoát", command=self.destroy).pack(
            side=tk.RIGHT
        )

        main = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        main.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        left = ttk.Frame(main)
        right = ttk.Frame(main, width=430)
        main.add(left, weight=4)
        main.add(right, weight=2)

        self.notebook = ttk.Notebook(left)
        self.notebook.pack(fill=tk.BOTH, expand=True)
        self._build_original_tab()
        self._build_preprocess_tab()
        self._build_plate_tab()
        self._build_char_tab()

        self._build_result_panel(right)

        status_bar = ttk.Frame(self, relief=tk.SUNKEN, padding=(8, 3))
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        self.status_var = tk.StringVar(value="Sẵn sàng.")
        ttk.Label(status_bar, textvariable=self.status_var).pack(side=tk.LEFT)
        self.template_var = tk.StringVar()
        stats = self.recognizer.library.stats()
        self.template_var.set(
            f"Template: {stats['labels']} nhãn / {stats['templates']} mẫu"
        )
        ttk.Label(status_bar, textvariable=self.template_var).pack(side=tk.RIGHT)

    # ------------------------------------------------------------------
    def _build_original_tab(self) -> None:
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text="Ảnh gốc")
        self.canvas_original = tk.Canvas(
            frame, bg="#202124", highlightthickness=0
        )
        self.canvas_original.pack(fill=tk.BOTH, expand=True)
        self.original_hint = tk.StringVar(
            value="Chọn ảnh JPG/JPEG/PNG/WEBP để bắt đầu."
        )
        ttk.Label(frame, textvariable=self.original_hint).pack(pady=2)

    def _build_preprocess_tab(self) -> None:
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text="Tiền xử lý")
        self.pre_canvases: Dict[str, tk.Canvas] = {}
        titles = [
            ("gray", "Grayscale"),
            ("blurred", "Làm mượt"),
            ("enhanced", "CLAHE / tăng tương phản"),
            ("edges", "Canny"),
            ("binary_otsu", "Nhị phân Otsu"),
            ("binary_adaptive", "Nhị phân Adaptive"),
        ]
        for idx, (key, title) in enumerate(titles):
            cell = ttk.LabelFrame(frame, text=title)
            row, col = divmod(idx, 3)
            cell.grid(
                row=row, column=col, sticky="nsew", padx=4, pady=4
            )
            canvas = tk.Canvas(cell, bg="#202124", height=230, highlightthickness=0)
            canvas.pack(fill=tk.BOTH, expand=True)
            self.pre_canvases[key] = canvas
        for i in range(2):
            frame.rowconfigure(i, weight=1)
        for j in range(3):
            frame.columnconfigure(j, weight=1)

    def _build_plate_tab(self) -> None:
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text="Biển số")
        self.plate_canvases: Dict[str, tk.Canvas] = {}
        titles = [
            ("crop", "Crop theo bounding box"),
            ("rectified", "Sau hiệu chỉnh phối cảnh"),
            ("binary", "Nhị phân vùng biển"),
        ]
        for idx, (key, title) in enumerate(titles):
            cell = ttk.LabelFrame(frame, text=title)
            cell.grid(row=0, column=idx, sticky="nsew", padx=4, pady=4)
            canvas = tk.Canvas(cell, bg="#202124", height=340, highlightthickness=0)
            canvas.pack(fill=tk.BOTH, expand=True)
            self.plate_canvases[key] = canvas
        for i in range(3):
            frame.columnconfigure(i, weight=1)
        frame.rowconfigure(0, weight=1)

    def _build_char_tab(self) -> None:
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text="Ký tự")
        outer = ttk.Frame(frame)
        outer.pack(fill=tk.BOTH, expand=True)
        self.char_canvas = tk.Canvas(outer, bg="#f4f4f4", highlightthickness=0)
        scroll_y = ttk.Scrollbar(
            outer, orient=tk.VERTICAL, command=self.char_canvas.yview
        )
        scroll_x = ttk.Scrollbar(
            outer, orient=tk.HORIZONTAL, command=self.char_canvas.xview
        )
        self.char_inner = ttk.Frame(self.char_canvas)
        self.char_canvas.create_window((0, 0), window=self.char_inner, anchor="nw")
        self.char_canvas.configure(
            yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set
        )
        self.char_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        scroll_x.pack(side=tk.BOTTOM, fill=tk.X)
        self.char_inner.bind(
            "<Configure>",
            lambda e: self.char_canvas.configure(
                scrollregion=self.char_canvas.bbox("all")
            ),
        )
        self.char_strip_label = ttk.Label(frame, text="")
        self.char_strip_label.pack(pady=2)

    def _build_result_panel(self, parent: ttk.Frame) -> None:
        self.status_label = tk.Label(
            parent,
            text="CHƯA CÓ KẾT QUẢ",
            bg="#555555",
            fg="white",
            font=("Segoe UI", 12, "bold"),
            pady=8,
        )
        self.status_label.pack(fill=tk.X, padx=6, pady=(6, 4))

        text_frame = ttk.LabelFrame(parent, text="Chuỗi nhận dạng")
        text_frame.pack(fill=tk.X, padx=6, pady=4)
        self.text_var = tk.StringVar(value="-")
        tk.Label(
            text_frame,
            textvariable=self.text_var,
            font=("Consolas", 22, "bold"),
            fg="#0b4f8a",
            pady=4,
        ).pack()
        self.raw_var = tk.StringVar(value="")
        ttk.Label(text_frame, textvariable=self.raw_var).pack(pady=(0, 4))

        info_frame = ttk.LabelFrame(parent, text="Thông tin")
        info_frame.pack(fill=tk.X, padx=6, pady=4)
        self.info_var = tk.StringVar(value="Chưa xử lý ảnh nào.")
        ttk.Label(
            info_frame, textvariable=self.info_var, justify=tk.LEFT
        ).pack(anchor="w", padx=6, pady=4)

        tree_frame = ttk.LabelFrame(parent, text="Điểm từng ký tự")
        tree_frame.pack(fill=tk.BOTH, expand=False, padx=6, pady=4)
        columns = ("order", "row", "label", "score", "margin", "second", "status")
        self.tree = ttk.Treeview(
            tree_frame, columns=columns, show="headings", height=9
        )
        headers = {
            "order": "#",
            "row": "Dòng",
            "label": "Nhãn",
            "score": "Điểm",
            "margin": "Margin",
            "second": "Top-2",
            "status": "Trạng thái",
        }
        widths = {
            "order": 34,
            "row": 44,
            "label": 48,
            "score": 60,
            "margin": 60,
            "second": 70,
            "status": 86,
        }
        for col in columns:
            self.tree.heading(col, text=headers[col])
            self.tree.column(col, width=widths[col], anchor=tk.CENTER)
        self.tree.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

        message_frame = ttk.LabelFrame(parent, text="Thông báo / cảnh báo")
        message_frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=(4, 6))
        self.message_text = tk.Text(
            message_frame, height=7, wrap=tk.WORD, font=("Segoe UI", 9)
        )
        msg_scroll = ttk.Scrollbar(
            message_frame, orient=tk.VERTICAL, command=self.message_text.yview
        )
        self.message_text.configure(yscrollcommand=msg_scroll.set)
        self.message_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        msg_scroll.pack(side=tk.RIGHT, fill=tk.Y)

    # ------------------------------------------------------------------
    def _show_template_warning_if_needed(self) -> None:
        if self.recognizer.template_error:
            self.status_var.set("CẢNH BÁO: bộ template chưa sẵn sàng.")
            messagebox.showwarning(
                "Bộ template",
                "Không nạp được bộ template:\n\n"
                f"{self.recognizer.template_error}\n\n"
                "Hãy chạy: python tools/build_templates.py\n"
                "hoặc thêm ảnh mẫu vào data/templates/<nhãn>/.",
            )
            self.status_label.configure(
                text="LỖI CẤU HÌNH TEMPLATE", bg=STATUS_COLORS["CONFIG_ERROR"]
            )

    def _set_busy(self, busy: bool) -> None:
        state = tk.DISABLED if busy else tk.NORMAL
        for btn in (
            self.btn_open,
            self.btn_run,
            self.btn_save_debug,
            self.btn_export,
            self.btn_eval,
        ):
            btn.configure(state=state)
        self._busy = busy
        self.configure(cursor="watch" if busy else "")

    # ------------------------------------------------------------------
    def on_open_image(self) -> None:
        path = filedialog.askopenfilename(
            title="Chọn ảnh biển số",
            filetypes=[
                ("Ảnh", "*.jpg *.jpeg *.png *.webp"),
                ("JPEG", "*.jpg *.jpeg"),
                ("PNG", "*.png"),
                ("WEBP", "*.webp"),
                ("Tất cả", "*.*"),
            ],
        )
        if not path:
            return
        self.image_path = Path(path)
        self.file_var.set(str(self.image_path))
        self.result = None
        self.original_hint.set("Ảnh đã chọn. Bấm 'Nhận dạng' để xử lý.")
        self._show_original_only()
        self._clear_results()
        self.status_var.set("Đã chọn ảnh. Sẵn sàng nhận dạng.")

    def _show_original_only(self) -> None:
        if self.image_path is None:
            return
        from src.io_utils import read_image

        try:
            image = read_image(self.image_path)
        except Exception as exc:
            messagebox.showerror("Lỗi đọc ảnh", str(exc))
            return
        self._original_image = image
        draw_on_canvas(
            self.canvas_original,
            image,
            ref_holder=self._image_refs,
            key="original",
        )

    def on_recognize(self) -> None:
        if self._busy:
            return
        if self.image_path is None:
            messagebox.showinfo("Chưa chọn ảnh", "Hãy chọn một ảnh trước.")
            return
        self._set_busy(True)
        self.status_var.set("Đang nhận dạng...")
        self._queue = queue.Queue()
        path = str(self.image_path)

        def worker() -> None:
            try:
                result = self.recognizer.recognize(path)
                self._queue.put(("done", result))
            except Exception as exc:  # pragma: no cover
                self._queue.put(("error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()
        self.after(80, self._poll_result)

    def _poll_result(self) -> None:
        try:
            kind, payload = self._queue.get_nowait()
        except queue.Empty:
            self.after(80, self._poll_result)
            return
        self._set_busy(False)
        if kind == "error":
            self.status_var.set("Lỗi xử lý.")
            messagebox.showerror("Lỗi", str(payload))
            return
        self.result = payload
        self._render_result(self.result)
        self.status_var.set(
            f"Hoàn tất: {self.result.display_status} "
            f"({self.result.total_time_ms:.0f} ms)"
        )

    # ------------------------------------------------------------------
    def _render_result(self, result: RecognitionResult) -> None:
        color = STATUS_COLORS.get(result.status, "#555555")
        self.status_label.configure(
            text=STATUS_TEXT.get(result.status, result.status), bg=color
        )
        self.text_var.set(result.detected_text or "-")
        if result.raw_text and result.raw_text != result.detected_text:
            self.raw_var.set(f"Chuỗi thô: {result.raw_text}")
        else:
            self.raw_var.set("")
        attempt = result.selected_attempt
        mean_score = result.text.mean_score if result.text else 0.0
        min_score = result.text.min_score if result.text else 0.0
        plate_score = attempt.candidate.score if attempt else 0.0
        info_lines = [
            f"Thời gian: {result.total_time_ms:.1f} ms",
            f"Hiệu chỉnh: {result.rectification_method}",
            f"Điểm biển: {plate_score:.3f}",
            f"Điểm ký tự TB/thấp nhất: {mean_score:.3f} / {min_score:.3f}",
            f"Số ký tự: {len(result.predictions)}",
        ]
        if result.text:
            valid = "hợp lệ" if result.text.validation.is_valid else "KHÔNG hợp lệ"
            info_lines.append(f"Định dạng: {valid}")
            info_lines.append(
                f"Ký tự tin cậy: {result.text.confident_ratio * 100:.0f}%"
            )
        timings = [
            f"{name}: {value:.1f} ms"
            for name, value in result.timings_ms.items()
            if name != "pipeline_total"
        ]
        info_lines.append("Thời gian công đoạn: " + ", ".join(timings))
        self.info_var.set("\n".join(info_lines))

        for item in self.tree.get_children():
            self.tree.delete(item)
        for item in result.char_boxes_original:
            self.tree.insert(
                "",
                tk.END,
                values=(
                    item["order"] + 1,
                    item["row_index"] + 1,
                    item["label"],
                    f"{item['score']:.3f}",
                    f"{item['margin']:.3f}",
                    f"{item['second_label']}:{item['second_score']:.2f}",
                    item["status"],
                ),
            )

        messages: List[str] = [result.message]
        if result.text:
            messages.extend(result.text.validation.issues)
        messages.extend(result.warnings)
        if result.errors:
            messages.append("Lỗi: " + "; ".join(result.errors))
        self.message_text.delete("1.0", tk.END)
        self.message_text.insert(
            tk.END, "\n".join(f"- {m}" for m in messages if m)
        )
        self._render_images(result)
        self._render_characters(result)

    def _render_images(self, result: RecognitionResult) -> None:
        images = result.debug_images()
        if result.image is not None:
            original_show = images.get("08_candidates", result.image)
            draw_on_canvas(
                self.canvas_original,
                original_show,
                ref_holder=self._image_refs,
                key="original_result",
            )
        pre = result.preprocess
        if pre:
            mapping = {
                "gray": pre.gray,
                "blurred": pre.blurred,
                "enhanced": pre.enhanced,
                "edges": pre.edges,
                "binary_otsu": pre.binary_otsu,
                "binary_adaptive": pre.binary_adaptive,
            }
            for key, image in mapping.items():
                draw_on_canvas(
                    self.pre_canvases[key],
                    image,
                    ref_holder=self._image_refs,
                    key=f"pre_{key}",
                )
        for key in self.plate_canvases:
            draw_on_canvas(
                self.plate_canvases[key],
                None,
                ref_holder=self._image_refs,
                key=f"plate_{key}",
                text_if_empty="(chưa có)",
            )
        attempt = result.selected_attempt
        if attempt and attempt.rectification:
            draw_on_canvas(
                self.plate_canvases["crop"],
                attempt.rectification.crop_image,
                ref_holder=self._image_refs,
                key="plate_crop",
            )
            draw_on_canvas(
                self.plate_canvases["rectified"],
                attempt.rectification.plate_image,
                ref_holder=self._image_refs,
                key="plate_rectified",
            )
        if attempt and attempt.segmentation and attempt.segmentation.binary is not None:
            draw_on_canvas(
                self.plate_canvases["binary"],
                attempt.segmentation.binary,
                ref_holder=self._image_refs,
                key="plate_binary",
            )

    def _render_characters(self, result: RecognitionResult) -> None:
        for child in self.char_inner.winfo_children():
            child.destroy()
        self._char_refs.clear()
        seg = result.segmentation
        preds = result.predictions
        if seg is None or not seg.characters:
            ttk.Label(
                self.char_inner, text="Không có ký tự nào được phân đoạn."
            ).grid(row=0, column=0, padx=12, pady=12)
            self.char_strip_label.configure(text="")
            return
        if Image is None or ImageTk is None:
            self.char_strip_label.configure(text="Thiếu Pillow để hiển thị ảnh.")
            return
        for idx, (char, pred) in enumerate(zip(seg.characters, preds)):
            frame = ttk.Frame(self.char_inner, relief=tk.RIDGE, padding=4)
            frame.grid(row=0, column=idx, padx=4, pady=8, sticky="n")
            img = pred.normalized_image if pred.normalized_image is not None else char.image
            if img is not None:
                rgb = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB) if img.ndim == 2 else img
                pil = Image.fromarray(rgb)
                pil = pil.resize((64, 88), Image.NEAREST)
                photo = ImageTk.PhotoImage(pil)
                self._char_refs.append(photo)
                tk.Label(frame, image=photo, bg="#ffffff").pack()
            label = pred.label if pred.status == "OK" else "?"
            color = "#1b7f3a" if pred.status == "OK" else "#b3261e"
            tk.Label(
                frame,
                text=label,
                font=("Consolas", 16, "bold"),
                fg=color,
            ).pack()
            ttk.Label(frame, text=f"{pred.score:.3f}").pack()
            ttk.Label(
                frame,
                text=f"row {char.row_index + 1}",
                font=("Segoe UI", 7),
            ).pack()
        strip = make_character_strip(preds, seg.characters)
        if strip is not None and strip.size:
            rgb = cv2.cvtColor(strip, cv2.COLOR_BGR2RGB)
            pil = Image.fromarray(rgb)
            pil.thumbnail((720, 120), Image.LANCZOS)
            photo = ImageTk.PhotoImage(pil)
            self._char_refs.append(photo)
            self.char_strip_label.configure(image=photo, text="")
        self.char_canvas.update_idletasks()
        self.char_canvas.configure(scrollregion=self.char_canvas.bbox("all"))

    def _clear_results(self) -> None:
        self.status_label.configure(text="CHƯA CÓ KẾT QUẢ", bg="#555555")
        self.text_var.set("-")
        self.raw_var.set("")
        self.info_var.set("Chưa xử lý ảnh nào.")
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.message_text.delete("1.0", tk.END)
        for canvas in self.pre_canvases.values():
            draw_on_canvas(canvas, None, text_if_empty="")
        for canvas in self.plate_canvases.values():
            draw_on_canvas(canvas, None, text_if_empty="")
        for child in self.char_inner.winfo_children():
            child.destroy()
        self.char_strip_label.configure(text="")

    # ------------------------------------------------------------------
    def on_save_debug(self) -> None:
        if self.result is None:
            messagebox.showinfo("Chưa có kết quả", "Hãy nhận dạng ảnh trước.")
            return
        stem = Path(self.result.image_path).stem if self.result.image_path else "image"
        out = self.config.resolve(self.config.pipeline.debug_dir) / stem
        try:
            path = save_debug_artifacts(self.result, out)
            self.status_var.set(f"Đã lưu ảnh trung gian: {path}")
            messagebox.showinfo(
                "Đã lưu", f"Ảnh trung gian và result.json đã lưu tại:\n{path}"
            )
        except Exception as exc:
            messagebox.showerror("Lỗi lưu ảnh", str(exc))

    def on_export_csv(self) -> None:
        if self.result is None:
            messagebox.showinfo("Chưa có kết quả", "Hãy nhận dạng ảnh trước.")
            return
        default_name = f"result_{Path(self.result.image_path).stem}.csv"
        path = filedialog.asksaveasfilename(
            title="Xuất kết quả ra CSV",
            defaultextension=".csv",
            initialfile=default_name,
            filetypes=[("CSV", "*.csv")],
            initialdir=str(self.config.results_dir),
        )
        if not path:
            return
        row = self.result.as_csv_row()
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(row.keys()))
            writer.writeheader()
            writer.writerow(row)
        self.status_var.set(f"Đã xuất CSV: {out}")
        messagebox.showinfo("Đã xuất CSV", str(out))

    def on_evaluate(self) -> None:
        labels_path = self.config.labels_file
        if not labels_path.exists():
            messagebox.showwarning(
                "Thiếu nhãn",
                f"Không tìm thấy file nhãn:\n{labels_path}\n\n"
                "Hãy chạy tools/build_synthetic_dataset.py hoặc tạo labels.csv.",
            )
            return
        answer = messagebox.askyesno(
            "Đánh giá bộ dữ liệu",
            f"Chạy đánh giá trên toàn bộ ảnh trong:\n{labels_path}\n\n"
            "Quá trình có thể mất vài giây.",
        )
        if not answer:
            return
        EvalWindow(self, self.recognizer, labels_path, self.config)


class EvalWindow(tk.Toplevel):
    def __init__(
        self,
        master: PlateRecognitionApp,
        recognizer: LicensePlateRecognizer,
        labels_path: Path,
        config: Config,
    ):
        super().__init__(master)
        self.title("Đánh giá bộ dữ liệu")
        self.geometry("900x650")
        self.recognizer = recognizer
        self.labels_path = labels_path
        self.config = config
        self._queue: "queue.Queue[Any]" = queue.Queue()
        self._stop = False
        self.text = tk.Text(self, wrap=tk.WORD, font=("Consolas", 9))
        self.text.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        self.progress_var = tk.StringVar(value="Đang chuẩn bị...")
        ttk.Label(self, textvariable=self.progress_var).pack(
            fill=tk.X, padx=8
        )
        self.progress = ttk.Progressbar(self, mode="determinate")
        self.progress.pack(fill=tk.X, padx=8, pady=(0, 8))
        threading.Thread(target=self._run, daemon=True).start()
        self.after(100, self._poll)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _run(self) -> None:
        try:
            labels = load_labels(self.labels_path)
            results, summary = run_evaluation(
                self.recognizer,
                labels,
                self.config.samples_dir,
                self.config,
                split=None,
                progress=lambda d, t, name: self._queue.put(
                    ("progress", d, t, name)
                ),
                stop_flag=lambda: self._stop,
            )
            out_csv = self.config.resolve("results/evaluation_ui.csv")
            out_json = self.config.resolve("results/evaluation_ui_summary.json")
            out_md = self.config.resolve("results/evaluation_ui_summary.md")
            write_evaluation_csv(results, out_csv)
            write_summary_json(summary, out_json)
            write_summary_markdown(summary, out_md)
            self._queue.put(
                ("done", format_summary_text(summary), (out_csv, out_json, out_md))
            )
        except Exception as exc:
            self._queue.put(("error", str(exc)))

    def _poll(self) -> None:
        try:
            while True:
                item = self._queue.get_nowait()
                if item[0] == "progress":
                    _, done, total, name = item
                    self.progress.configure(maximum=max(1, total), value=done)
                    self.progress_var.set(f"[{done}/{total}] {name}")
                elif item[0] == "done":
                    _, text, paths = item
                    self.text.delete("1.0", tk.END)
                    self.text.insert(tk.END, text)
                    self.text.insert(
                        tk.END,
                        "\n\nĐã ghi:\n"
                        + "\n".join(str(p) for p in paths),
                    )
                    self.progress_var.set("Hoàn tất.")
                    return
                elif item[0] == "error":
                    self.progress_var.set("Lỗi.")
                    self.text.insert(tk.END, f"\nLỖI: {item[1]}")
                    return
        except queue.Empty:
            pass
        if not self._stop:
            self.after(100, self._poll)

    def _on_close(self) -> None:
        self._stop = True
        self.destroy()


def main(config_path: Optional[str] = None) -> int:
    config = load_config(config_path)
    app = PlateRecognitionApp(config)
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

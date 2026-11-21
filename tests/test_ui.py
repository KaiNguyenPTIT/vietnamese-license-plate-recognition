"""Smoke test giao diện Tkinter trong tiến trình riêng.

Tk trên Windows đôi khi không cho tạo nhiều ``Tk()`` root trong cùng một tiến
trình pytest (đặc biệt sau khi một root khác đã bị destroy). Vì vậy test dựng
giao diện trong một tiến trình Python con, đúng với cách người dùng chạy
``python main.py ui``. Nếu môi trường không có Tk/display, test được bỏ qua.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

UI_SCRIPT = r"""
import sys

import numpy as np

from src.config import load_config

try:
    from ui.app import PlateRecognitionApp, bgr_to_photoimage
except Exception as exc:  # Không có tkinter (bản Python headless hoặc thiếu gói hệ thống)
    print(f"SKIP_TK {type(exc).__name__}: {exc}")
    sys.exit(3)

try:
    app = PlateRecognitionApp(load_config())
except Exception as exc:  # Tk không khả dụng trong môi trường headless
    message = f"{type(exc).__name__}: {exc}"
    if "TclError" in message or "init.tcl" in message or "no display" in message.lower():
        print("SKIP_TK " + message)
        sys.exit(3)
    raise

try:
    app.withdraw()
    app.update_idletasks()
    assert app.winfo_exists()
    assert "biển số" in app.title().lower()
    assert app.btn_open is not None
    assert app.btn_run is not None
    assert app.recognizer.library.templates

    image = np.full((80, 200, 3), 128, dtype=np.uint8)
    photo = bgr_to_photoimage(image, 120, 60)
    assert photo is not None
    assert photo.width() <= 120 and photo.height() <= 60
    assert bgr_to_photoimage(None, 120, 60) is None
finally:
    app.destroy()

print("UI_OK")
"""


def test_ui_smoke_in_subprocess() -> None:
    completed = subprocess.run(
        [sys.executable, "-c", UI_SCRIPT],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    if completed.returncode == 3:
        pytest.skip(completed.stdout.strip() or "Không có môi trường Tk")
    assert completed.returncode == 0, completed.stderr
    assert "UI_OK" in completed.stdout

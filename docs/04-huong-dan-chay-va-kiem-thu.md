# 04 — Hướng dẫn chạy và kiểm thử

## 1. Yêu cầu môi trường

- Python **3.11+** (đã kiểm thử với 3.13.6 trên Windows).
- Windows có Tk/Tcl nếu muốn dùng giao diện.
- Gói: `opencv-python`, `numpy`, `PyYAML`, `Pillow`, `pytest`.

## 2. Cài đặt

```powershell
cd vietnamese-license-plate-recognition
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python main.py info
```

Nếu PowerShell chặn script kích hoạt:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Hoặc dùng trực tiếp `.venv\Scripts\python.exe` thay cho `python`.

## 3. Các lệnh chính

### 3.1. Giao diện Tkinter

```powershell
python main.py ui
```

Giao diện cho phép chọn ảnh JPG/JPEG/PNG/WEBP, nhận dạng, xem ảnh gốc, ảnh
tiền xử lý, ảnh biển đã hiệu chỉnh, ảnh nhị phân, ảnh từng ký tự, điểm tin cậy,
lưu ảnh trung gian và xuất CSV.

### 3.2. Nhận dạng một ảnh

```powershell
python main.py recognize data\samples\dev_clear_001.jpg
python main.py recognize data\samples\dev_clear_001.jpg --json
python main.py recognize data\samples\dev_clear_001.jpg --save-debug
python main.py recognize data\samples\dev_clear_001.jpg --output-csv results\one.csv
```

Mã thoát: `0` nếu `SUCCESS` hoặc `FORMAT_WARNING`; `2` nếu bị từ chối.

### 3.3. Đánh giá trên bộ nhãn

```powershell
# Dev
python main.py evaluate --split dev `
  --output-csv results\dev_evaluation.csv `
  --summary-json results\dev_summary.json `
  --summary-md results\dev_summary.md

# Test
python main.py evaluate --split test `
  --output-csv results\test_evaluation.csv `
  --summary-json results\test_summary.json `
  --summary-md results\test_summary.md

# Ảnh thật (nhãn chuỗi, chưa có box)
python main.py evaluate --split user `
  --labels data\user_labels.csv --samples-dir data\user_images `
  --output-csv results\user_final.csv `
  --summary-json results\user_final_summary.json `
  --summary-md results\user_final_summary.md

# Ảnh đặc biệt 8.jpg
python main.py evaluate --split special `
  --labels data\user_labels.csv --samples-dir data\user_images `
  --output-csv results\user_special_final.csv `
  --summary-json results\user_special_final_summary.json `
  --summary-md results\user_special_final_summary.md
```

Có thể dùng `run_user_eval.bat` để chạy nhanh phần ảnh thật.

### 3.4. Nhận dạng hàng loạt

```powershell
python main.py batch data\samples --output-csv results\batch_results.csv
```

### 3.5. Thông tin cấu hình

```powershell
python main.py info
```

In ra đường dẫn template, số template, các nhóm cấu hình và cảnh báo nếu thiếu
nhãn.

## 4. Kiểm thử

```powershell
python -m pytest -q
```

Kết quả mong đợi: **78 passed**. Bộ test gồm:

| Tệp | Nội dung |
|---|---|
| `test_config.py` | nạp/ghi cấu hình, override, lỗi |
| `test_preprocessing.py` | đọc ảnh, resize, ảnh quá nhỏ |
| `test_detection.py` | sinh ứng viên, cắt, đếm thành phần chữ |
| `test_rectification.py` | warp phối cảnh, ánh xạ ngược |
| `test_segmentation.py` | biển một dòng, hai dòng, 10 ký tự cân bằng |
| `test_recognition.py` | template library, prior số lỗ, chữ 4 hở đỉnh |
| `test_postprocessing.py` | ghép chuỗi, validate, trạng thái, không tự sửa |
| `test_pipeline.py` | end-to-end, ảnh không biển, lưu debug |
| `test_evaluation.py` | Levenshtein, CSV/JSON/Markdown |
| `test_ui.py` | smoke test Tkinter (bỏ qua nếu không có Tk) |

## 5. Sinh lại template và dữ liệu

```powershell
python tools\build_templates.py --clean
python tools\build_synthetic_dataset.py --clean
```

Lưu ý: sinh lại template có thể thay đổi kết quả đánh giá. Chỉ làm khi có chủ
đích và ghi lại phiên bản.

## 6. Sinh lại báo cáo

```powershell
python tools\build_report_docx.py
powershell -ExecutionPolicy Bypass -File tools\finalize_report.ps1
```

Lệnh thứ hai cần Microsoft Word để cập nhật mục lục, trường số trang và xuất
PDF. Nếu không có Word, vẫn có thể mở `reports/BaoCao.docx` và cập nhật field
thủ công.

## 7. Xử lý lỗi thường gặp

| Hiện tượng | Nguyên nhân | Cách xử lý |
|---|---|---|
| `ModuleNotFoundError: cv2` | Chưa cài requirements | `python -m pip install -r requirements.txt` |
| `No module named tkinter` | Python thiếu Tk | Cài Python bản có Tcl/Tk hoặc dùng CLI |
| `CONFIG_ERROR: Không thể nạp bộ template` | Thiếu `data/templates` | Kiểm tra thư mục, chạy `python main.py info` |
| Kết quả toàn `?` | Ảnh mờ/nghiêng/dính, hoặc template không khớp font | Xem ảnh debug, thử ảnh rõ hơn |
| Chữ tiếng Việt bị lỗi trong console | Console không dùng UTF-8 | `chcp 65001`, đặt `PYTHONIOENCODING=utf-8`, hoặc dùng `run_ui.bat` |
| Lần chạy đầu chậm | Nạp và chuẩn hóa template (~1.4 s) | Bình thường; các ảnh sau nhanh hơn |
| `PermissionError` khi ghi kết quả | File đang mở trong Excel | Đóng file rồi chạy lại |
| Ảnh `.webp` không đọc được | Thiếu codec | Cài `opencv-python` đầy đủ, không dùng bản headless thiếu codec |
| Test UI bị skip | Không có Tk/display | Bình thường trên môi trường không giao diện |

## 8. Mẹo demo

1. Mở sẵn `data/samples/dev_clear_001.jpg` để demo nhanh.
2. Chuẩn bị một ảnh thật rõ (`data/user_images/1.webp`).
3. Bật `--save-debug` để chỉ từng công đoạn khi thuyết trình.
4. Nếu mạng chậm, không cần cài lại; dùng môi trường đã chuẩn bị trước.
5. Luôn nói rõ kết quả 13/13 là kiểm tra hồi quy, không phải holdout.

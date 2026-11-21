# 01 — Kiến trúc và luồng xử lý

## 1. Bài toán

- **Đầu vào:** một ảnh tĩnh JPG/JPEG/PNG/WEBP, có tối đa một biển số chính,
  cạnh ngắn tối thiểu 40 px.
- **Đầu ra:** `RecognitionResult` gồm chuỗi biển số đã chuẩn hóa, hộp bao vùng
  biển, điểm tin cậy từng ký tự, trạng thái quyết định, thời gian từng công
  đoạn và ảnh trung gian (nếu bật debug).
- **Ràng buộc:** chỉ dùng OpenCV/NumPy và thuật toán cổ điển; không học máy,
  không YOLO, không OCR học sẵn, không gọi API nhận dạng.

## 2. Sơ đồ tổng quát

```text
Ảnh vào
  │
  ▼
[1] Tiền xử lý            src/preprocessing.py
  │  đọc an toàn Unicode, resize, gray, blur, CLAHE, Canny, threshold
  ▼
[2] Phát hiện biển        src/plate_detection.py
  │  morphology → contour → lọc hình học → chấm điểm → top 5 ứng viên
  ▼
[3] Vòng lặp ứng viên     src/pipeline.py  (thử tối đa 8 ứng viên)
  │
  ├─► [4] Hiệu chỉnh      src/plate_rectification.py
  │      crop + padding → tứ giác → warpPerspective / deskew / bbox
  │
  ├─► [5] Phân đoạn ký tự src/character_segmentation.py
  │      chuẩn hóa 640 px → nhị phân → tách dòng → tách ký tự → sắp thứ tự
  │
  ├─► [6] Nhận dạng       src/character_recognition.py
  │      chuẩn hóa 32×48 → Template Matching → lọc điểm/margin → hole prior
  │
  └─► [7] Hậu xử lý       src/postprocessing.py
         ghép chuỗi → validate định dạng → rerank theo vị trí → trạng thái
  │
  ▼
Chọn ứng viên tốt nhất (ranking_key) → RecognitionResult
  │
  ▼
[8] Đánh giá (tùy chọn)   src/evaluation.py
      PDR, Precision/Recall, CSA, CA, EPA, thời gian → CSV/JSON/Markdown
```

## 3. Bảng module

| Tệp | Trách nhiệm | Hàm/lớp chính | Dòng |
|---|---|---|---:|
| `src/config.py` | Dataclass cấu hình, nạp/ghi YAML, override, kiểm tra hợp lệ | `Config`, `load_config`, `save_config` | 384 |
| `src/io_utils.py` | Đọc/ghi ảnh Unicode, resize, IoU, hình học, liệt kê ảnh | `read_image`, `bbox_iou`, `order_quad_points` | 157 |
| `src/preprocessing.py` | Resize, xám, blur, CLAHE, Canny, Otsu/adaptive | `preprocess`, `preprocess_image` | 217 |
| `src/plate_detection.py` | Sinh, lọc, chấm điểm và xếp hạng ứng viên biển | `detect_plates`, `select_top_candidates` | 941 |
| `src/plate_rectification.py` | Crop, tìm tứ giác, warp phối cảnh, deskew, fallback bbox | `rectify_plate`, `map_rectified_bbox_to_work` | 303 |
| `src/character_segmentation.py` | Nhị phân, tách dòng, tách ký tự, lọc và sắp thứ tự đọc | `segment_characters` | 1001 |
| `src/character_recognition.py` | Chuẩn hóa ký tự, nạp template, so khớp, prior số lỗ | `TemplateLibrary`, `recognize_characters` | 552 |
| `src/postprocessing.py` | Ghép chuỗi, validate, rerank vị trí, quyết định trạng thái | `build_text_result`, `validate_format` | 343 |
| `src/evaluation.py` | Tính chỉ số, căn chỉnh chuỗi, xuất CSV/JSON/Markdown | `run_evaluation`, `compute_summary` | 541 |
| `src/pipeline.py` | Điều phối 8 công đoạn, thử ứng viên, lưu debug | `LicensePlateRecognizer.recognize` | 681 |
| `ui/app.py` | Giao diện Tkinter: chọn ảnh, xem ảnh trung gian, xuất CSV | `PlateRecognitionApp`, `EvalWindow` | 756 |
| `main.py` | CLI `ui`, `recognize`, `evaluate`, `batch`, `info` | `build_parser` | 224 |

## 4. Chuỗi dữ liệu giữa các công đoạn

Mỗi công đoạn trả về một dataclass, không truyền ảnh trần giữa các bước. Nhờ
vậy có thể kiểm thử riêng từng bước và lưu lại ảnh trung gian.

| Dataclass | Nơi định nghĩa | Trường quan trọng |
|---|---|---|
| `PreprocessResult` | `preprocessing.py` | `original`, `work_image`, `gray`, `blurred`, `edges`, `binary`, `scale`, `warnings`, `timings_ms` |
| `PlateCandidate` | `plate_detection.py` | `bbox`, `score`, `ratio`, `area_ratio`, `edge_density`, `fill_ratio`, `text_likeness`, `source`, `bbox_hint` |
| `DetectionResult` | `plate_detection.py` | `candidates`, `all_candidates`, `maps`, `timings_ms`, `warnings` |
| `RectificationResult` | `plate_rectification.py` | `plate_image`, `plate_gray`, `method`, `matrix`, `inverse_matrix`, `roi_bbox` |
| `SegmentedCharacter` | `character_segmentation.py` | `image`, `bbox`, `row_index`, `order` |
| `SegmentationResult` | `character_segmentation.py` | `characters`, `rows`, `binary`, `status`, `score` |
| `CharacterPrediction` | `character_recognition.py` | `label`, `score`, `margin`, `second_label`, `status` |
| `PlateTextResult` | `postprocessing.py` | `raw_text`, `formatted_text`, `status`, `mean_score`, `min_score`, `validation` |
| `RecognitionResult` | `pipeline.py` | `status`, `text`, `bbox`, `attempts`, `timings_ms`, `warnings`, `errors` |

Luồng gọi thực tế trong `LicensePlateRecognizer.recognize`:

1. `preprocess(path, config)` — lỗi đọc ảnh trả `INVALID_IMAGE`.
2. `detect_plates(pre, config)` — không có ứng viên trả `PLATE_NOT_FOUND`.
3. Với từng ứng viên (tối đa `pipeline.max_candidates_to_try = 8`):
   `rectify_plate` → `segment_characters` → `recognize_characters` →
   `resolve_position_constraints` → `build_text_result`.
4. Chọn ứng viên theo `ranking_key()`:
   `(ưu tiên trạng thái, điểm trung bình chuỗi, điểm phân đoạn, điểm ứng viên,
   số ký tự)`. Gặp `SUCCESS` thì dừng sớm.
5. Gắn hộp bao ký tự về tọa độ ảnh gốc, lưu debug nếu được yêu cầu.

## 5. Mã trạng thái

| Trạng thái | Ý nghĩa | Mã thoát CLI |
|---|---|---:|
| `SUCCESS` | Chuỗi hợp lệ, độ tin cậy đạt | 0 |
| `FORMAT_WARNING` | Đọc được chuỗi nhưng không khớp định dạng cấu hình | 0 |
| `LOW_CONFIDENCE` | Có ký tự chưa chắc chắn, còn `?`, hoặc điểm thấp | 2 |
| `PLATE_NOT_FOUND` | Không có ứng viên biển đủ điều kiện | 2 |
| `INVALID_IMAGE` | Không đọc được ảnh, ảnh quá nhỏ | 2 |
| `CONFIG_ERROR` | Thiếu template hoặc cấu hình sai | 2 |

Thứ tự ưu tiên khi chọn ứng viên: `SUCCESS` > `FORMAT_WARNING` >
`LOW_CONFIDENCE` > `PLATE_NOT_FOUND` > `INVALID_IMAGE` > `CONFIG_ERROR`.

## 6. Cấu hình

Toàn bộ tham số nằm trong `config.yaml`, được ánh xạ sang dataclass trong
`src/config.py`. Có thể ghi đè khi thực nghiệm mà không sửa file:

```python
from src.config import load_config

cfg = load_config(overrides={"recognition.score_threshold": 0.65})
```

Các nhóm cấu hình: `project`, `paths`, `image`, `preprocessing`, `detection`,
`rectification`, `segmentation`, `recognition`, `postprocessing`, `pipeline`,
`evaluation`, `ui`.

## 7. Bốn quyết định thiết kế quan trọng

1. **Tách “hộp báo cáo” và “vùng cắt OCR”.** Ứng viên cụm ký tự cắt sát chữ
   cho OCR tốt nhưng IoU với biển thật thấp. Khi ứng viên hình học bao trọn
   cụm chữ, hệ thống dùng hộp hình học để báo cáo vị trí, còn vùng cắt dùng
   cho nhận dạng vẫn giữ nguyên (`text_bbox_hint`).
2. **Không tự sửa ký tự.** Hậu xử lý chỉ chọn lại trong các nhãn template đã
   chấm điểm; không đổi ký tự chỉ để chuỗi trông hợp lệ.
3. **Từ chối thay vì đoán.** Ký tự dưới ngưỡng hoặc margin quá nhỏ được giữ
   `?`, kéo theo `LOW_CONFIDENCE`.
4. **Biển 10 ký tự có điều kiện.** Chỉ chấp nhận khi hai dòng cân bằng (ví dụ
   5/5), tránh ghép mảnh nhiễu ở mép biển thành chuỗi giả.

## 8. Điểm cần phân biệt khi thuyết trình

- `detect_plates` **không** nhận dạng ký tự; nó chỉ tạo ứng viên hình học.
- `segment_characters` làm việc trên ảnh biển **đã hiệu chỉnh**, không phải
  ảnh gốc.
- `recognize_characters` nhận **danh sách ảnh ký tự**, không nhận chuỗi.
- `postprocessing` không gọi lại template; nó chỉ dùng điểm đã có.
- `evaluation` là công cụ đo, không tham gia vào quyết định nhận dạng.

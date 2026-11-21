# Ôn tập riêng — Bùi Văn Đạt (B23DCCN126)

**Phần phụ trách:** tiền xử lý, tiện ích ảnh, giao diện Tkinter, đánh giá, bộ
kiểm thử, dữ liệu tổng hợp, báo cáo.

> Cách dùng: nắm mục 1–4, tự trả lời mục 5, đọc mục 6 để biết câu hỏi nối sang
> phần của Khải/Tường.

---

## 1. Mình phụ trách những gì

| Tệp | Vai trò | Hàm/lớp chính |
|---|---|---|
| `src/preprocessing.py` | Đọc ảnh, resize, xám, blur, CLAHE, Canny, Otsu/adaptive | `preprocess`, `preprocess_image` |
| `src/io_utils.py` | Đọc/ghi ảnh Unicode, IoU, hình học, liệt kê ảnh | `read_image`, `write_image`, `bbox_iou` |
| `ui/app.py` | Giao diện Tkinter: chọn ảnh, xem ảnh trung gian, xuất CSV, cửa sổ đánh giá | `PlateRecognitionApp`, `EvalWindow` |
| `src/evaluation.py` | PDR, Precision/Recall, CSA, CA, EPA, Levenshtein, xuất báo cáo | `run_evaluation`, `compute_summary` |
| `tests/` | 78 bài pytest cho 10 module và pipeline | `test_*.py` |
| `tools/build_synthetic_dataset.py` | Sinh 52 ảnh tổng hợp kèm nhãn box | `main` |
| `reports/` | Báo cáo, hình, bảng kết quả | `BaoCao.docx`, `BaoCao.pdf`, `REPORT.md` |

---

## 2. Câu chuyện 60 giây

“Phần em phụ trách là đầu vào và đầu ra của hệ thống. Đầu vào: em đọc ảnh an
toàn với đường dẫn Unicode, resize, chuyển xám, làm mờ, tính cạnh và nhị phân.
Đầu ra: em xây giao diện Tkinter để chọn ảnh, xem ảnh trung gian, xem điểm từng
ký tự và xuất CSV; em viết bộ đánh giá PDR/CSA/CA/EPA, sinh CSV/JSON/Markdown,
viết 78 bài pytest, sinh bộ dữ liệu tổng hợp và tổng hợp báo cáo. Em cũng chịu
trách nhiệm bảo đảm số liệu trong báo cáo khớp với file kết quả.”

---

## 3. Sơ đồ phần của mình

```text
ẢNH VÀO
 │
 ▼
preprocess (Đạt)
 │  np.fromfile + cv2.imdecode  (Unicode)
 │  kiểm tra min_side / 60MP
 │  resize max_side 1600 → scale
 │  gray → blur → CLAHE (tùy chọn)
 │  Canny + Otsu/adaptive
 ▼
PreprocessResult ──► detection (Khải)

KẾT QUẢ
 │
 ├─► ui/app.py (Đạt)
 │     chọn ảnh → thread recognize → queue → after(80) → render
 │     4 tab: gốc, tiền xử lý, biển, ký tự
 │     lưu debug, xuất CSV, cửa sổ đánh giá
 │
 └─► evaluation.py (Đạt)
       CSV từng ảnh → summary JSON/MD
       PDR, Precision/Recall, CSA, CA, EPA, thời gian
```

---

## 4. Kiến thức bắt buộc

### 4.1. Đọc ảnh Unicode

`cv2.imread` không xử lý tốt đường dẫn tiếng Việt trên Windows. `io_utils` dùng:

```python
data = np.fromfile(path, dtype=np.uint8)
image = cv2.imdecode(data, cv2.IMREAD_COLOR)
```

Ghi ảnh cũng dùng `cv2.imencode` + `Path.write_bytes`.

### 4.2. Kiểm tra ảnh

- Ảnh rỗng/không giải mã được → `InvalidImageError`.
- Cạnh ngắn < `min_side = 40` → từ chối.
- Diện tích > 60 MP → từ chối để tránh tràn bộ nhớ.
- Chuẩn hóa ảnh xám/4 kênh về BGR.

### 4.3. Resize và `scale`

Nếu cạnh dài > `max_side = 1600`, thu nhỏ bằng `INTER_AREA`, lưu
`scale = 1600 / cạnh_dài`. Mọi tọa độ trên ảnh làm việc được chia cho `scale`
để về ảnh gốc. Nếu quên bước này, hộp bao sẽ lệch.

### 4.4. Blur, CLAHE, Canny, threshold

- Gaussian 5×5 mặc định: giảm nhiễu cao tần.
- Median/bilateral: lựa chọn thay thế khi ảnh nhiễu muối tiêu hoặc cần giữ biên.
- CLAHE: tăng tương phản cục bộ, mặc định tắt; bật khi ảnh thiếu sáng.
- Canny 60/180, `L2gradient=True`; `auto_canny` dùng trung vị ±33%.
- Otsu mặc định; adaptive Gaussian block 11, C = 2.

### 4.5. Giao diện Tkinter

- `PlateRecognitionApp` là cửa sổ chính, 4 tab: ảnh gốc, tiền xử lý, biển, ký tự.
- Nhận dạng chạy trong **thread riêng**, kết quả đưa vào `queue.Queue`.
- UI dùng `self.after(80, self._poll_result)` để kiểm tra queue, tránh treo.
- `EvalWindow` cũng chạy thread riêng và `after(100, self._poll)`.
- Có nút lưu ảnh debug, xuất CSV, chạy đánh giá từ UI.

**Vì sao không gọi trực tiếp `recognize` trong callback nút?**
Vì nó mất 1–2 giây (có ảnh 17 giây), sẽ đóng băng giao diện. Thread + queue giữ
UI phản hồi.

### 4.6. Các chỉ số đánh giá

| Chỉ số | Cách tính |
|---|---|
| PDR | số ảnh có biển phát hiện đúng IoU ≥ 0.5 / tổng ảnh có biển |
| Precision | TP / (TP + FP), có tính ảnh không biển |
| Recall | TP / (TP + FN) |
| CSA | trung bình tỷ lệ hộp ký tự ghép đúng IoU ≥ 0.5 |
| CSA proxy | `1 − |gt_count − pred_count| / max(gt, pred)` khi nhãn không có box |
| CA | `matches / (matches + substitutions + insertions + deletions)` |
| EPA | số chuỗi trùng khớp hoàn toàn / số ảnh có biển |
| Success Rate | số `SUCCESS` / tổng ảnh |

### 4.7. Levenshtein

Căn chỉnh chuỗi dự đoán với nhãn bằng quy hoạch động, cho biết bao nhiêu ký tự
khớp, thay thế, chèn, xóa. CA lấy số khớp chia cho độ dài căn chỉnh.

### 4.8. Vì sao xuất cả CSV, JSON, Markdown?

- CSV: từng ảnh, dễ mở Excel, kiểm tra thủ công.
- JSON: tổng hợp có cấu trúc, dùng lại cho báo cáo.
- Markdown: đọc nhanh trong repo, chèn vào báo cáo.

### 4.9. Bộ kiểm thử 78 bài

| Tệp | Nội dung |
|---|---|
| `test_config.py` | nạp/ghi cấu hình, override, lỗi |
| `test_preprocessing.py` | đọc ảnh, resize, ảnh quá nhỏ |
| `test_detection.py` | ứng viên, cắt, đếm thành phần chữ |
| `test_rectification.py` | warp, ánh xạ ngược |
| `test_segmentation.py` | một dòng, hai dòng, 10 ký tự cân bằng |
| `test_recognition.py` | template, hole prior, chữ 4 hở đỉnh |
| `test_postprocessing.py` | ghép chuỗi, validate, trạng thái |
| `test_pipeline.py` | end-to-end, ảnh không biển, debug |
| `test_evaluation.py` | Levenshtein, CSV/JSON/MD |
| `test_ui.py` | smoke test Tkinter, tự skip nếu không có Tk |

Chạy một tệp:

```powershell
python -m pytest tests\test_evaluation.py -q
```

### 4.10. Bộ dữ liệu tổng hợp

- 52 ảnh: dev 26, test 26.
- Mỗi split: 23 ảnh có biển, 3 ảnh không biển.
- Điều kiện: rõ, nghiêng, hai dòng, thiếu sáng, ký tự dính, chất lượng thấp,
  không biển, độ phân giải thấp.
- Nhãn có box biển và box từng ký tự trong `data/labels.csv`.
- Generator dùng font khác font template (Calibri, Verdana, Times New Roman,
  Trebuchet) để tránh template “học thuộc” font kiểm thử.

### 4.11. Báo cáo và tính tái lập

- Số liệu lấy từ `results/*.csv` và `results/*_summary.json`, không nhập tay.
- `tools/build_report_docx.py` sinh DOCX từ dữ liệu thật.
- `tools/finalize_report.ps1` dùng Word để cập nhật mục lục, số trang và xuất PDF.
- Trước khi nộp, chạy lại đánh giá và đối chiếu bảng trong báo cáo với JSON.

---

## 5. Câu hỏi thầy hay hỏi — trả lời mẫu

**1. Vì sao không dùng `cv2.imread`?**
Vì lỗi với đường dẫn Unicode trên Windows. Dùng `np.fromfile` + `cv2.imdecode`
và `cv2.imencode` + `write_bytes`.

**2. Vì sao giới hạn cạnh dài 1600 px?**
Giảm thời gian và nhiễu, vẫn đủ để biển nhỏ còn nhìn thấy. Ảnh lớn bị resize,
lưu `scale` để quy đổi tọa độ.

**3. Vì sao cạnh ngắn tối thiểu 40 px?**
Dưới ngưỡng đó ký tự không còn đủ pixel để phân đoạn/nhận dạng; trả
`INVALID_IMAGE` thay vì đoán.

**4. `scale` dùng ở đâu?**
Trong detection và ánh xạ hộp ký tự: tọa độ trên ảnh làm việc chia cho `scale`
để về ảnh gốc. Nếu quên, hộp bao bị lệch và đánh giá sai.

**5. Vì sao mặc định Gaussian?**
Nhanh, giảm nhiễu đều, phù hợp ảnh chụp thông thường. Median/bilateral là lựa
chọn khi có nhiễu đặc thù.

**6. Khi nào bật CLAHE?**
Khi ảnh thiếu sáng/tương phản thấp. Hệ thống cảnh báo nếu độ lệch chuẩn < 35.

**7. Otsu và adaptive khác nhau thế nào?**
Otsu chọn một ngưỡng toàn cục; adaptive chọn ngưỡng theo từng vùng, tốt khi sáng
không đều. Hệ thống tính cả hai và dùng theo cấu hình/fallback.

**8. Vì sao lưu nhiều ảnh trung gian?**
Để debug và thuyết trình: thấy ảnh gốc, xám, mờ, cạnh, nhị phân, morphology,
biển đã warp, từng ký tự. Không có các ảnh này thì rất khó giải thích lỗi.

**9. Giao diện có bị treo khi nhận dạng ảnh lớn không?**
Không, vì nhận dạng chạy trong thread riêng; UI chỉ poll queue bằng `after(80)`.

**10. Vì sao dùng `after` thay vì `update()`?**
`after` lên lịch kiểm tra định kỳ, không chặn vòng lặp sự kiện; `update()` dễ
gây re-entrancy và treo.

**11. Cửa sổ đánh giá chạy thế nào?**
`EvalWindow` chạy `run_evaluation` trong thread, cập nhật tiến độ qua queue và
`after(100)`, cho phép đóng/hủy.

**12. PDR tính thế nào?**
Số ảnh có biển được phát hiện đúng (IoU ≥ 0.5) chia tổng số ảnh có biển. Ảnh
không biển không nằm trong mẫu số PDR.

**13. Precision/Recall có tính ảnh không biển không?**
Có. TP/FP/FN/TN được tính cả ảnh không biển, nên Precision phản ánh việc báo
nhầm.

**14. Vì sao CSA trên ảnh thật là proxy?**
Nhãn ảnh thật chỉ có chuỗi, chưa có box ký tự. Khi đó CSA dùng chênh lệch số
lượng, không phải IoU. Không được nói “CSA 100% nghĩa là phân đoạn hoàn hảo”.

**15. CA khác EPA thế nào?**
CA cho điểm từng ký tự; EPA yêu cầu đúng toàn bộ chuỗi. Vì vậy CA 88% nhưng EPA
chỉ 47.83%.

**16. Vì sao EPA có lúc chia 23, có lúc chia 26?**
Mẫu số chuẩn là số ảnh có biển (23). Nếu chia cho toàn bộ 26 ảnh theo công thức
đặc tả thì EPA là 42.31%. Báo cáo ghi rõ mẫu số.

**17. Vì sao xuất cả CSV, JSON, Markdown?**
CSV để kiểm tra từng ảnh; JSON để tái sử dụng; Markdown để đọc nhanh và chèn
báo cáo.

**18. 78 test có ý nghĩa gì?**
Kiểm tra hồi quy từng module và pipeline end-to-end; giúp sửa code mà không làm
hỏng phần khác. Không chứng minh độ chính xác trên ảnh thật.

**19. Vì sao test UI bị skip?**
Môi trường không có Tk/display. Test được thiết kế tự bỏ qua thay vì fail.

**20. Vì sao generator dùng font khác font template?**
Để tránh template “học thuộc” đúng font kiểm thử. Đổi lại bài toán khó hơn và
phản ánh đúng giới hạn Template Matching khi gặp font lạ.

**21. Số liệu trong báo cáo có tự nhập không?**
Không. Sinh từ `results/*.csv` và `*_summary.json` bằng script. Trước khi nộp
phải chạy lại đánh giá và đối chiếu.

**22. Nếu ảnh `.webp` không đọc được thì sao?**
Kiểm tra `opencv-python` có codec; thử chuyển sang PNG. Lỗi được báo
`INVALID_IMAGE`, không làm crash pipeline.

**23. Vì sao console bị lỗi tiếng Việt?**
Console không dùng UTF-8. Dùng `chcp 65001`, đặt `PYTHONIOENCODING=utf-8`, hoặc
chạy `run_ui.bat` (đã set sẵn).

**24. 13/13 ảnh thật có phải độ chính xác tổng quát?**
Không. Đó là kiểm tra hồi quy trên tập đã dùng để tinh chỉnh, không phải holdout
độc lập.

---

## 6. Câu hỏi nối sang phần người khác

**25. Ai dùng `PreprocessResult` của mình?**
Khải, trong `detect_plates`; các trường `edges`, `gray`, `binary`, `scale` được
dùng trực tiếp.

**26. Ai cung cấp box để mình tính PDR/CSA?**
Khải cung cấp `bbox_original`; Tường cung cấp `char_boxes_original`. Mình chỉ
đọc `RecognitionResult`, không tự suy ra box.

**27. Nếu thay đổi ngưỡng detection thì số liệu đánh giá thay đổi thế nào?**
Có thể tăng/giảm PDR, kéo theo CSA/CA/EPA. Phải chạy lại toàn bộ dev/test và
cập nhật báo cáo.

**28. Ai chịu trách nhiệm cấu hình cuối?**
Khải, nhưng mình là người đo và ghi lại kết quả; mọi thay đổi phải được cả nhóm
xác nhận.

**29. Nếu báo cáo và file kết quả lệch nhau thì sao?**
Ưu tiên file kết quả; sinh lại báo cáo. Không sửa CSV bằng tay.

---

## 7. Demo checklist

1. `python main.py ui` — chọn ảnh, nhận dạng, chỉ 4 tab.
2. Chỉ nút lưu ảnh debug và xuất CSV.
3. Mở cửa sổ đánh giá từ UI, chạy dev, xem tiến độ không treo.
4. `python main.py evaluate --split dev ...` — so summary JSON với bảng báo cáo.
5. `python -m pytest -q` — 78 passed.
6. Mở `reports/BaoCao.pdf` — chỉ bảng kết quả và mục hạn chế.

---

## 8. Bẫy cần tránh

- Đừng nói “CSA 100% trên ảnh thật là phân đoạn hoàn hảo”; đó là proxy.
- Đừng nói “EPA 47.83% trên 26 ảnh”; phải nói rõ mẫu số 23 ảnh có biển.
- Đừng nói “bộ dữ liệu tổng hợp đại diện ảnh thật”; nó chỉ để đo có kiểm soát.
- Đừng nói “UI đã kiểm thử thủ công toàn bộ”; mới smoke test.
- Đừng sửa CSV/JSON bằng tay để khớp báo cáo.
- Đừng nhận công việc detection/segmentation; nói rõ mình dùng kết quả của Khải
  và Tường.

---

## 9. Từ khóa phải nhớ

`np.fromfile` + `cv2.imdecode` · `scale` · `max_side 1600` · `min_side 40` ·
`CLAHE` · `Canny 60/180` · `Otsu / adaptive` · `thread + queue + after` ·
`PDR` · `Precision/Recall` · `CSA IoU / proxy` · `Levenshtein` · `EPA` ·
`78 passed` · `dev/test 26 + 26` · `font khác template` · `tái lập bằng CSV/JSON`

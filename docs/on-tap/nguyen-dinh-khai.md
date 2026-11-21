# Ôn tập riêng — Nguyễn Đình Khải (B23DCCN420)

**Phần phụ trách:** kiến trúc pipeline, phát hiện biển, hiệu chỉnh phối cảnh,
cấu hình, CLI, tích hợp. Vai trò nhóm trưởng.

> Cách dùng: đọc mục 1–4 để nắm phần mình, sau đó tự trả lời mục 5 mà không
> nhìn đáp án. Mục 6 là các câu nối sang phần của Tường/Đạt để không bị hỏi
> chéo.

---

## 1. Mình phụ trách những gì

| Tệp | Vai trò | Hàm/lớp chính |
|---|---|---|
| `src/pipeline.py` | Điều phối 8 công đoạn, thử ứng viên, chọn kết quả, lưu debug | `LicensePlateRecognizer.recognize`, `ranking_key` |
| `src/plate_detection.py` | Sinh bản đồ morphology, contour, chấm điểm, gộp trùng, gộp hai dòng | `detect_plates`, `select_top_candidates`, `build_morphology_maps` |
| `src/plate_rectification.py` | Crop, tìm tứ giác, warp phối cảnh, deskew, fallback bbox | `rectify_plate`, `map_rectified_bbox_to_work` |
| `src/config.py` + `config.yaml` | Dataclass cấu hình, nạp/ghi YAML, override, kiểm tra hợp lệ | `load_config`, `save_config` |
| `main.py` | CLI `ui/recognize/evaluate/batch/info`, mã thoát | `build_parser`, `cmd_*` |

---

## 2. Câu chuyện 60 giây (học thuộc ý, không học thuộc chữ)

“Hệ thống của nhóm em nhận ảnh tĩnh, tìm vùng biển bằng cạnh, morphology và
contour, chấm điểm từng ứng viên theo tỷ lệ, diện tích, mật độ cạnh, độ đầy và
bằng chứng ký tự. Sau đó hệ thống thử tối đa 8 ứng viên, cắt và hiệu chỉnh phối
cảnh, phân đoạn ký tự, nhận dạng bằng Template Matching, hậu xử lý chuỗi rồi
chọn kết quả tốt nhất theo thứ tự ưu tiên trạng thái và điểm tin cậy. Phần em
phụ trách là kiến trúc, phát hiện biển, hiệu chỉnh, cấu hình và CLI.”

---

## 3. Sơ đồ phần của mình

```text
ảnh
 │
 ▼
preprocess (Đạt) ──► PreprocessResult
 │
 ▼
detect_plates (Khải)
 │   morphology maps (17×3, 25×5, 15×7)
 │   contour thường / tứ giác / cụm chữ
 │   lọc diện tích + tỷ lệ
 │   chấm điểm → top 5
 ▼
LicensePlateRecognizer.recognize (Khải)
 │   for candidate in top 8:
 │       rectify_plate (Khải)
 │       segment_characters (Tường)
 │       recognize_characters (Tường)
 │       build_text_result (Tường)
 │   chọn theo ranking_key
 ▼
RecognitionResult
```

---

## 4. Kiến thức bắt buộc

### 4.1. Vì sao thử nhiều ứng viên?

Ứng viên điểm cao nhất chưa chắc là biển: có thể là cụm đèn, lưới tản nhiệt,
hoặc cả phần thân xe. Pipeline thử tối đa **8** ứng viên
(`pipeline.max_candidates_to_try`) và chọn theo `ranking_key`:

```text
(ưu tiên trạng thái, điểm trung bình chuỗi, điểm phân đoạn, điểm ứng viên, số ký tự)
```

Gặp `SUCCESS` thì dừng sớm. Nhờ vậy hệ thống không “chết” chỉ vì ứng viên đầu
tiên bị cắt lệch.

### 4.2. Công thức chấm điểm ứng viên

```text
ratio_score = max_t exp(−|ratio − t| / tolerance),  t ∈ {4.6, 1.45}
area_score  = exp(−(ln(area_ratio / 0.05))² / (2·1.7²))
edge_score  = hàm hình thang theo mật độ cạnh
fill_score  = min(1, (fill − 0.30) / 0.70)
spec_score  = trọng số chuẩn hóa của ratio 0.35, area 0.15, edge 0.30, fill 0.15
score       = 0.80·spec_score + 0.20·text_likeness
```

Điều kiện qua: `score ≥ 0.45` **và** `text_likeness ≥ 0.15`.

### 4.3. `text_likeness` là gì?

Là điểm **bằng chứng hình học**, không phải OCR. Hàm đếm số thành phần liên
thông có kích thước giống ký tự bên trong vùng ứng viên:

- < 3 thành phần → 0.
- 3–6 thành phần → tăng dần.
- 7–14 thành phần → 1.0.
- > 14 → giảm dần (có thể là nền rối).

Mục đích: loại vùng nền/đèn xe dù hình chữ nhật đẹp.

### 4.4. Gộp trùng và gộp hai dòng

- **Gộp trùng:** IoU ≥ 0.45 hoặc một hộp nằm trọn trong hộp kia > 85%. Giữ hộp
  điểm cao hơn; cộng ưu tiên cho hộp “đặc” hơn.
- **Gộp hai dòng:** hai ứng viên chồng ngang ≥ 70%, không chồng dọc quá 25%,
  khoảng cách dọc ≤ 60% chiều cao lớn hơn → gộp thành `stacked_merge` nếu vùng
  gộp có `text_likeness ≥ 0.5`.

### 4.5. `text_bbox_hint` — điểm dễ bị hỏi

Ứng viên cụm chữ cắt sát ký tự cho OCR tốt nhưng IoU với biển thật thấp. Khi
một ứng viên hình học bao trọn cụm chữ (containment ≥ 0.80, diện tích không
quá 4×, điểm ≥ 0.50), hệ thống **mượn hộp hình học để báo cáo vị trí**, còn
vùng cắt dùng cho nhận dạng vẫn giữ nguyên.

Nói ngắn: **một vùng để báo vị trí, một vùng để đọc chữ.**

### 4.6. Hiệu chỉnh phối cảnh

1. Crop có padding 10% ngang, 6% chiều rộng theo trục dọc.
2. Canny trên vùng crop, tìm contour, xấp xỉ 4 điểm với epsilon 2% chu vi.
3. Kiểm tra lồi và diện tích ≥ 45% diện tích crop.
4. `getPerspectiveTransform` + `warpPerspective`.
5. Fallback: `minAreaRect` + deskew nếu góc 2.5°–18°; cuối cùng là bounding box.
6. Đầu ra phải ≥ 60×20 px và tỷ lệ ≤ 8.0, nếu không trả `invalid`.

### 4.7. Cấu hình

`config.yaml` → dataclass trong `src/config.py`. Có thể override khi thực nghiệm:

```python
cfg = load_config(overrides={"recognition.score_threshold": 0.65})
```

Không sửa tham số chỉ để đẹp kết quả test; mọi thay đổi phải chạy lại dev và ghi
lý do.

### 4.8. CLI và mã thoát

- `python main.py ui`
- `python main.py recognize <ảnh> [--json] [--save-debug]`
- `python main.py evaluate --split dev|test|user|special`
- `python main.py batch <thư mục>`
- `python main.py info`

Mã thoát: `0` nếu `SUCCESS`/`FORMAT_WARNING`; `2` nếu bị từ chối hoặc lỗi.

---

## 5. Câu hỏi thầy hay hỏi — trả lời mẫu

**1. Vì sao không lấy luôn contour lớn nhất làm biển?**
Vì biển có thể nhỏ, bị chia thành nhiều contour, hoặc contour lớn nhất là cả
đầu xe. Hệ thống sinh nhiều ứng viên, chấm điểm và thử tối đa 8 ứng viên.

**2. Vì sao dùng Canny rồi morphology mà không threshold luôn?**
Canny bắt biên ổn định với ánh sáng; closing nối nét đứt để vùng biển thành
khối liền. Threshold trực tiếp nhạy với nền và dễ dính cả thân xe.

**3. Vì sao có nhiều kernel morphology?**
17×3 hợp biển một dòng; 25×5 và 15×7 bắt biển hai dòng hoặc nét đứt. Nhiều bản
đồ tăng recall, sau đó lọc và gộp trùng.

**4. `score ≥ 0.45` có phải ngưỡng cố định không?**
Là giá trị cấu hình, có thể đổi. Nhưng đổi phải đo lại dev; không tinh chỉnh
theo test.

**5. Vì sao `text_likeness` có trọng số 0.20?**
Nó là bằng chứng bổ sung, không đủ tin cậy một mình. Trọng số 0.20 đủ để loại
vùng nền nhưng không át các đặc trưng hình học.

**6. Nếu ảnh không có biển thì sao?**
Detection không có ứng viên qua ngưỡng → `PLATE_NOT_FOUND`, không tạo chuỗi giả.
Nếu vẫn có ứng viên, hệ thống có thể trả `LOW_CONFIDENCE` thay vì bịa.

**7. Vì sao padding dọc tính theo chiều rộng?**
Biển một dòng rất rộng nhưng thấp; khi nghiêng, góc biển vượt khỏi bounding box
theo trục y. Pad theo chiều rộng bù được mà không tăng quá nhiều padding ngang.

**8. Nếu không tìm được tứ giác thì sao?**
Fallback `minAreaRect` để deskew nếu góc 2.5°–18°; nếu vẫn không được thì dùng
bounding box. Phương án được ghi vào `method` để truy vết.

**9. Vì sao phải ánh xạ hộp ký tự ngược?**
Ký tự được tách trên ảnh đã warp và đã resize. Muốn vẽ lên ảnh gốc phải áp dụng
ma trận nghịch đảo rồi chia cho `scale`.

**10. `ranking_key` gồm những gì?**
Ưu tiên trạng thái, điểm trung bình chuỗi, điểm phân đoạn, điểm ứng viên, số ký
tự. Nghĩa là kết quả `SUCCESS` luôn được ưu tiên hơn kết quả đẹp nhưng
`LOW_CONFIDENCE`.

**11. Vì sao `SUCCESS` thì dừng sớm?**
Để giảm thời gian. Nếu chưa `SUCCESS`, hệ thống vẫn thử tiếp và giữ ứng viên
tốt nhất.

**12. Nếu template bị thiếu thì pipeline làm gì?**
`LicensePlateRecognizer` báo `CONFIG_ERROR` nếu
`pipeline.fail_on_missing_templates = true`. Đây là lỗi cấu hình, không phải lỗi
ảnh.

**13. Vì sao giới hạn cạnh dài 1600 px?**
Giảm thời gian xử lý và nhiễu, vẫn đủ để biển nhỏ nhất còn nhìn thấy. Ảnh lớn
hơn bị resize và lưu `scale` để quy đổi tọa độ.

**14. Làm sao debug khi phát hiện sai?**
Chạy `python main.py recognize <ảnh> --save-debug`, xem `01_original`,
`06_edges`, `10_morphology_closed`, `08_candidates`, `09_selected_bbox`,
`result.json`.

**15. Vì sao ảnh `8.jpg` chậm 17.8 s?**
Ảnh lớn, nhiều contour và nhiều ứng viên; phần lớn thời gian ở phát hiện. Đây là
giới hạn hiệu năng đã nêu, không phải treo.

**16. Nếu ảnh có hai biển thì sao?**
Hệ thống chỉ thiết kế cho một biển chính. Nó chọn ứng viên tốt nhất; biển thứ
hai có thể bị bỏ qua.

**17. Vì sao không dùng `cv2.imread`?**
`cv2.imread` lỗi với đường dẫn Unicode trên Windows. `io_utils.read_image` dùng
`np.fromfile` + `cv2.imdecode`.

**18. Thay đổi tham số detection thì đo ở đâu?**
Chạy `evaluate --split dev`, so PDR/CSA/CA/EPA và thời gian; chỉ chạm test sau
khi cố định cấu hình.

---

## 6. Câu hỏi nối sang phần người khác

**19. Vì sao detection không tự nhận dạng ký tự?**
Vì tách trách nhiệm: detection chỉ tạo vùng; nhận dạng do Tường phụ trách. Nhờ
vậy có thể thay bộ nhận dạng mà không đổi detection.

**20. Vì sao cần phân đoạn trước khi nhận dạng?**
Template Matching so từng ký tự, không so cả chuỗi. Phân đoạn sai thì nhận dạng
sai dù template tốt.

**21. Nếu phân đoạn trả 0 ký tự thì pipeline làm gì?**
Ứng viên đó bị đánh `LOW_CONFIDENCE` và pipeline thử ứng viên tiếp theo.

**22. Ai quyết định trạng thái cuối?**
`postprocessing.build_text_result` (Tường) quyết định `SUCCESS`,
`FORMAT_WARNING`, `LOW_CONFIDENCE`; pipeline chỉ chọn ứng viên theo trạng thái
đó.

**23. Số liệu trong báo cáo do ai đo?**
Đạt phụ trách evaluation và báo cáo; mình phụ trách bảo đảm cấu hình cuối và
pipeline tạo ra kết quả tái lập được.

---

## 7. Demo checklist

1. `python main.py info` — thấy số template và cấu hình.
2. `python main.py recognize data\samples\dev_clear_001.jpg --save-debug` — chỉ
   ảnh gốc, cạnh, morphology, candidates, ảnh biển đã warp.
3. Mở `results\<tên_ảnh>\result.json` — giải thích `attempts` và `ranking_key`.
4. Chạy một ảnh khó (`dev_tilted_001.jpg` hoặc `test_touching_001.jpg`) — nói rõ
   vì sao thất bại thay vì che.
5. `python -m pytest -q` — 78 passed.

---

## 8. Bẫy cần tránh

- Đừng nói “hệ thống chính xác 100%”. Chỉ nói 13/13 là kiểm tra hồi quy.
- Đừng nói `text_likeness` là OCR.
- Đừng nói “thử 8 ứng viên vì 8 là số đẹp”; phải nói vì cân bằng giữa recall và
  thời gian.
- Đừng nói “warp luôn thành công”; phải nhắc fallback deskew/bbox.
- Đừng nhận công việc của Tường/Đạt; nếu bị hỏi sâu, nói “phần này bạn Tường/Đạt
  phụ trách, em nắm interface là ...”.

---

## 9. Từ khóa phải nhớ

`PreprocessResult` · `PlateCandidate` · `DetectionResult` · `RectificationResult`
· `ranking_key` · `text_likeness` · `text_bbox_hint` · `stacked_merge` ·
`min_score 0.45` · `top_k 5` · `max_candidates_to_try 8` · `padding 0.10/0.06` ·
`CONFIG_ERROR` · `PLATE_NOT_FOUND`

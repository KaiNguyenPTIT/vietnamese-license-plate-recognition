# 02 — Chi tiết tám công đoạn

Mỗi mục dưới đây trả lời bốn câu: công đoạn làm gì, đầu vào/ra, hàm nào phụ
trách, và tham số nào quan trọng. Số liệu tham số lấy từ `config.yaml`.

---

## 1. Tiền xử lý — `src/preprocessing.py`

**Mục tiêu:** biến ảnh đầu vào thành các biểu diễn trung gian ổn định để phát
hiện biển: ảnh làm việc, ảnh xám, ảnh mờ, ảnh tăng tương phản, bản đồ cạnh và
ảnh nhị phân.

**Đầu vào:** đường dẫn ảnh hoặc mảng BGR.
**Đầu ra:** `PreprocessResult` gồm `original`, `work_image`, `gray`,
`blurred`, `enhanced`, `edges`, `binary`, `binary_otsu`, `binary_adaptive`,
`scale`, `warnings`, `timings_ms`.

Các bước:

1. **Đọc ảnh an toàn Unicode:** `np.fromfile` + `cv2.imdecode`. Cách này tránh
   lỗi `cv2.imread` với đường dẫn tiếng Việt trên Windows.
2. **Kiểm tra hợp lệ:** ảnh rỗng, sai số chiều/kênh, cạnh ngắn < `min_side = 40`
   hoặc diện tích > 60 MP đều bị từ chối bằng `InvalidImageError`.
3. **Resize:** nếu cạnh dài > `max_side = 1600`, thu nhỏ bằng `INTER_AREA` và
   ghi lại `scale` để quy đổi tọa độ về ảnh gốc.
4. **Grayscale + blur:** mặc định Gaussian 5×5. Có thể đổi sang median,
   bilateral hoặc không blur.
5. **CLAHE (tùy chọn):** mặc định tắt. Nếu ảnh có độ lệch chuẩn < 35, hệ thống
   thêm cảnh báo gợi ý bật CLAHE.
6. **Canny:** mặc định 60/180, `L2gradient=True`; có chế độ `auto_canny` tính
   ngưỡng từ trung vị.
7. **Nhị phân:** luôn tính Otsu; nếu cấu hình `adaptive` thì dùng thêm
   adaptive Gaussian. Otsu được giữ làm fallback.

**Tham số chính:** `image.max_side`, `image.min_side`, `preprocessing.blur_method`,
`gaussian_kernel`, `use_clahe`, `canny_low/high`, `threshold_method`,
`adaptive_block_size`, `adaptive_c`.

**Lưu ý khi bảo vệ:** đây là công đoạn duy nhất đọc file; các công đoạn sau chỉ
làm việc trên mảng NumPy.

---

## 2. Phát hiện biển số — `src/plate_detection.py`

**Mục tiêu:** sinh nhiều ứng viên vùng biển từ cạnh và vùng mực, lọc theo hình
học, chấm điểm và giữ top 5.

**Đầu vào:** `PreprocessResult`.
**Đầu ra:** `DetectionResult` gồm `candidates` (đã xếp hạng), `all_candidates`,
các bản đồ morphology, thời gian và cảnh báo.

Các bước:

1. **Tạo bản đồ morphology** (`build_morphology_maps`): đóng ảnh cạnh với kernel
   chính 17×3 và các kernel phụ 25×5, 15×7 để bắt biển hai dòng hoặc nét đứt.
   Ngoài ra tạo bản đồ từ vùng mực (threshold) để bắt biển nền sáng/tối.
2. **Sinh contour:** contour thường, contour xấp xỉ tứ giác (`approxPolyDP`),
   và contour từ bản đồ mực.
3. **Lọc sơ bộ:** diện tích trong khoảng 0.08%–95% ảnh, tỷ lệ rộng/cao trong
   1.10–7.0, contour phải nằm trong ảnh.
4. **Tính đặc trưng:** tỷ lệ, diện tích, mật độ cạnh, độ đầy (contour area /
   bbox area), và `text_likeness` (đếm thành phần giống ký tự bên trong).
5. **Chấm điểm:**
   `spec = 0.35·ratio + 0.15·area + 0.30·edge + 0.15·fill`,
   sau đó `score = (1 − 0.20)·spec + 0.20·text`.
   Trọng số được chuẩn hóa lại trong `DetectionWeights.normalized()`.
6. **Điều kiện qua:** `score ≥ 0.45` **và** `text_likeness ≥ 0.15` (có thể tắt
   bằng `require_text_evidence: false`).
7. **Gộp trùng:** hai ứng viên có IoU ≥ 0.45 hoặc một hộp nằm trọn trong hộp
   kia > 85% được coi là trùng; giữ hộp điểm cao hơn, cộng thêm điểm ưu tiên
   cho hộp “đặc” hơn.
8. **Gộp hai dòng:** hai ứng viên xếp trên/dưới, chồng ngang ≥ 70%, khoảng cách
   dọc ≤ 60% chiều cao lớn hơn, được gộp thành một ứng viên `stacked_merge`
   nếu vùng gộp có `text_likeness ≥ 0.5`.
9. **Xếp hạng:** giữ tối đa `top_k = 5`; pipeline thử tối đa 8 ứng viên.

**Tham số chính:** `detection.close_kernel`, `extra_close_kernels`,
`min_area_ratio`, `max_area_ratio`, `min_ratio`, `max_ratio`,
`ratio_targets`, `min_score`, `top_k`, `merge_iou`, `text_likeness_weight`.

**Điểm dễ bị hỏi:** `text_likeness` không phải OCR. Nó chỉ đếm các thành phần
liên thông có kích thước giống ký tự để loại vùng nền/đèn xe.

---

## 3. Hiệu chỉnh biển — `src/plate_rectification.py`

**Mục tiêu:** cắt vùng biển và đưa về ảnh phẳng, chữ nằm ngang, phục vụ phân
đoạn.

**Đầu vào:** ảnh làm việc + `PlateCandidate` + `Config`.
**Đầu ra:** `RectificationResult` gồm `plate_image`, `plate_gray`, `method`,
`roi_bbox`, `matrix`, `inverse_matrix`, `quad`, `angle`, `warnings`.

Các bước:

1. **Crop có padding:** 10% theo ngang và 6% chiều rộng theo trục dọc
   (`vertical_padding_ratio`) để không cắt góc biển nghiêng.
2. **Tìm tứ giác:** Canny trên vùng crop, tìm contour lớn, xấp xỉ 4 điểm, kiểm
   tra lồi và diện tích ≥ 45% diện tích crop.
3. **Warp phối cảnh:** `getPerspectiveTransform` + `warpPerspective` từ 4 góc
   đã sắp thứ tự (`order_quad_points`).
4. **Fallback:** nếu không có tứ giác hợp lệ, dùng `minAreaRect` để deskew khi
   góc trong khoảng 2.5°–18°; nếu vẫn không được thì dùng bounding box.
5. **Kiểm tra đầu ra:** chiều rộng ≥ 60 px, chiều cao ≥ 20 px, tỷ lệ không vượt
   8.0; nếu vi phạm, trả `method = "invalid"`.

**Tham số chính:** `rectification.padding_ratio`, `vertical_padding_ratio`,
`approx_epsilon_ratio`, `min_quad_area_ratio`, `deskew_min/max_angle`,
`max_output_ratio`.

**Lưu ý:** `map_rectified_bbox_to_work` ánh xạ hộp ký tự từ ảnh đã warp về ảnh
làm việc, rồi pipeline chia cho `scale` để về ảnh gốc.

---

## 4. Phân đoạn ký tự — `src/character_segmentation.py`

**Mục tiêu:** từ ảnh biển đã hiệu chỉnh, tách từng ký tự theo thứ tự đọc.

**Đầu vào:** ảnh biển BGR.
**Đầu ra:** `SegmentationResult` gồm `characters` (`SegmentedCharacter`),
`rows`, `binary`, `status`, `score`, `threshold_method_used`, `warnings`.

Các bước:

1. **Chuẩn hóa kích thước:** resize chiều rộng về `plate_width = 640`, không
   phóng quá 4 lần để tránh khuếch đại nhiễu.
2. **Tăng tương phản + blur nhẹ:** CLAHE clip 2.0, lưới 8×8; blur kernel 3.
3. **Nhị phân tự động:** thử Otsu và nhiều block size adaptive (tối đa 71).
   Mỗi phương án được chấm `plausibility_score` dựa trên số dòng, số ký tự,
   chiều cao tương đối, độ cân bằng; chọn phương án hợp lý nhất. Có thể ép
   `otsu` hoặc `adaptive`.
4. **Chuẩn hóa cực tính:** đảm bảo ký tự là foreground (mực trắng trên nền
   đen) bằng cách kiểm tra tỷ lệ mực và đảo nếu cần.
5. **Xóa viền và nhiễu:** xóa margin 1.5% quanh biên, xóa thành phần nhỏ,
   xóa ốc vít/gạch phân cách.
6. **Tách dòng:** projection ngang, làm m smooth, gộp khoảng hở nhỏ; nếu
   projection gộp hai dòng, dùng fallback connected components
   (`component_row_fallback`).
7. **Tách ký tự:** trong mỗi dòng, đóng nhỏ 2×2 để nối nét đứt, tìm contour,
   lọc theo chiều cao (42%–102% chiều cao dòng), chiều rộng, diện tích, độ đầy.
8. **Tách hộp quá rộng:** nếu một hộp rộng gần gấp đôi ký tự, tìm điểm thắt
   (valley) trong projection dọc để tách; nếu không đủ điều kiện thì giữ nguyên.
9. **Gộp mảnh và khử trùng:** gộp các mảnh rời của cùng ký tự (dấu, nét đứt),
   khử hộp trùng.
10. **Sắp thứ tự:** theo dòng rồi theo x; gán `order`.
11. **Kiểm tra số lượng:** chuẩn 7–9 ký tự; 10 ký tự chỉ chấp nhận khi hai dòng
    cân bằng (ví dụ 5/5); ngoài khoảng này hoặc dưới `min_chars = 5` bị đánh
    `IMPLAUSIBLE`.

**Tham số chính:** `segmentation.plate_width`, `threshold_method`,
`min/max_char_height_ratio`, `min/max_char_width_ratio`, `split_wide`,
`expected_chars`, `allow_balanced_long_plate`, `min_chars`.

**Điểm dễ bị hỏi:** phân đoạn không dùng học máy; tất cả dựa trên nhị phân,
projection và hình học contour.

---

## 5. Nhận dạng ký tự — `src/character_recognition.py`

**Mục tiêu:** gán nhãn cho từng ảnh ký tự bằng so khớp template.

**Đầu vào:** danh sách ảnh ký tự + `TemplateLibrary` + `Config`.
**Đầu ra:** danh sách `CharacterPrediction` gồm `label`, `status`, `score`,
`margin`, `second_label`, `second_score`, `ranked`.

Các bước:

1. **Chuẩn hóa ký tự:** chuyển về ảnh nhị phân mực trắng, cắt sát ink box, kéo
   giãn về canvas **32×48** (`normalize_mode: stretch`), thêm padding 2 px.
2. **Nạp template:** đọc ảnh trong `data/templates/<label>/`, chuẩn hóa cùng
   kích thước, làm mờ nhẹ σ = 2.0, loại ảnh gần trùng
   (`template_min_diff_ratio = 0.005`), tối đa 60 template/nhãn.
3. **Loại nhãn không hợp lệ:** `I, J, O, Q, W` không được chấm điểm.
4. **Hai tầng:**
   - Tầng coarse: so khớp với 6 template đại diện mỗi nhãn, giữ 6 nhãn tốt nhất.
   - Tầng đầy đủ: chỉ chấm toàn bộ template của các nhãn lọt vào top-6.
5. **So khớp:** `cv2.matchTemplate` với `TM_CCOEFF_NORMED`, cho phép dịch
   ±1 px (`shift_tolerance`), lấy điểm cao nhất.
6. **Hole prior:** đếm số lỗ của ký tự và của template; nếu lệch số lỗ phổ biến
   thì trừ 0.20 điểm. Giúp phân biệt `6/B`, `0/D`, `8/B`.
7. **Biến thể chữ 4 hở đỉnh:** thêm 45 template tổng hợp cho kiểu chữ `4` có
   nét dọc phải bắt đầu từ giữa.
8. **Quyết định:** điểm cao nhất < 0.60 → `LOW_CONFIDENCE`; margin top-1/top-2
   < 0.035 → `LOW_CONFIDENCE`; ngược lại `OK`.

**Tham số chính:** `recognition.method`, `score_threshold`, `min_margin`,
`normalized_width/height`, `match_blur_sigma`, `hole_prior`, `hole_penalty`,
`coarse_templates_per_label`, `coarse_top_labels`.

---

## 6. Hậu xử lý — `src/postprocessing.py`

**Mục tiêu:** ghép ký tự thành chuỗi, kiểm tra định dạng, chọn lại nhãn theo
vị trí và quyết định trạng thái cuối.

**Đầu vào:** danh sách `CharacterPrediction` + trạng thái phân đoạn.
**Đầu ra:** `PlateTextResult` gồm `raw_text`, `formatted_text`, `status`,
`mean_score`, `min_score`, `confident_ratio`, `validation`, `warnings`.

Các bước:

1. **Ghép chuỗi:** nối nhãn theo `order`; ký tự không đạt giữ `?`.
2. **Rerank theo vị trí:** suy ra kiểu ký tự từng vị trí (số/chữ) từ chuỗi
   hiện tại, rồi chọn lại trong danh sách `ranked` của từng ký tự. Chỉ được
   giảm tối đa 0.15 điểm và phải hơn nhãn thứ hai ít nhất 0.02; **không tạo
   nhãn mới**.
3. **Validate định dạng:** mặc định `^[0-9]{2}[A-Z]{1,2}[0-9]{4,6}$`, tức
   2 số tỉnh + 1–2 chữ series + 4–6 số. Series hợp lệ:
   `ABCDEFGHKLMNPSTUVXYZ`.
4. **Quyết định trạng thái:**
   - Còn `?` hoặc điểm trung bình < 0.60 hoặc điểm thấp nhất < 0.50 hoặc tỷ lệ
     ký tự chắc chắn < 0.85 → `LOW_CONFIDENCE`.
   - Chuỗi đủ tin cậy nhưng sai định dạng → `FORMAT_WARNING`.
   - Đủ tin cậy và đúng định dạng → `SUCCESS`.

**Tham số chính:** `postprocessing.patterns`, `allowed_series_letters`,
`position_constraints`, `min_mean_confidence`, `min_char_confidence`,
`min_confident_ratio`.

---

## 7. Điều phối pipeline — `src/pipeline.py`

**Mục tiêu:** ghép các công đoạn, thử nhiều ứng viên và chọn kết quả tốt nhất.

`LicensePlateRecognizer.recognize`:

1. Kiểm tra lỗi nạp template → `CONFIG_ERROR`.
2. `preprocess` → lỗi đọc ảnh `INVALID_IMAGE`.
3. `detect_plates` → không có ứng viên `PLATE_NOT_FOUND`.
4. Với tối đa 8 ứng viên: hiệu chỉnh → phân đoạn → nhận dạng → hậu xử lý.
5. Chọn theo `ranking_key`; gặp `SUCCESS` thì dừng.
6. Gắn hộp ký tự về ảnh gốc; lưu debug nếu bật.

`RecognitionResult` là đầu ra duy nhất mà UI/CLI dùng; nó chứa cả `attempts`
để giải thích vì sao ứng viên khác bị loại.

---

## 8. Đánh giá — `src/evaluation.py`

**Mục tiêu:** đo chất lượng bằng nhãn có sẵn và xuất báo cáo tái lập được.

- **PDR:** tỷ lệ ảnh có biển được phát hiện đúng (IoU ≥ 0.5) trên tổng số ảnh
  có biển.
- **Detection Precision/Recall:** tính cả ảnh không biển (TP/FP/FN/TN).
- **CSA:** nếu nhãn có `char_boxes`, dùng IoU từng hộp; nếu không, dùng proxy
  theo chênh lệch số lượng: `1 − |gt_count − pred_count| / max(gt, pred)`.
- **CA:** số ký tự khớp / độ dài căn chỉnh Levenshtein.
- **EPA:** tỷ lệ chuỗi dự đoán trùng khớp hoàn toàn sau chuẩn hóa.
- **Thời gian:** trung bình từng công đoạn, lấy từ `timings_ms`.

Xuất ra CSV từng ảnh, JSON tổng hợp và Markdown tóm tắt. Đây là công cụ đo,
không tham gia vào quyết định nhận dạng.

# Ôn tập riêng — Nguyễn Trung Tường (B23DCCN909)

**Phần phụ trách:** phân đoạn ký tự, nhận dạng bằng Template Matching, hậu xử
lý chuỗi, sinh template.

> Cách dùng: nắm mục 1–4, tự trả lời mục 5, sau đó đọc mục 6 để biết câu hỏi
> nối sang phần của Khải/Đạt.

---

## 1. Mình phụ trách những gì

| Tệp | Vai trò | Hàm/lớp chính |
|---|---|---|
| `src/character_segmentation.py` | Nhị phân, tách dòng, tách ký tự, lọc, sắp thứ tự | `segment_characters`, `_plausibility_score` |
| `src/character_recognition.py` | Chuẩn hóa 32×48, nạp template, so khớp hai tầng, prior số lỗ | `TemplateLibrary`, `recognize_characters` |
| `src/postprocessing.py` | Ghép chuỗi, validate định dạng, rerank vị trí, quyết định trạng thái | `build_text_result`, `validate_format` |
| `tools/build_templates.py` | Sinh template từ font Windows, biến thể normal/thick/thin | `main` |

---

## 2. Câu chuyện 60 giây

“Phần em phụ trách bắt đầu từ ảnh biển đã được cắt và làm phẳng. Em chuẩn hóa
chiều rộng 640 px, chọn ngưỡng nhị phân bằng điểm hợp lý hình học, tách dòng
bằng projection ngang, tách ký tự bằng contour và projection dọc, rồi lọc theo
chiều cao, chiều rộng, diện tích. Mỗi ký tự được chuẩn hóa về 32×48 và so khớp
template bằng TM_CCOEFF_NORMED theo hai tầng, có prior số lỗ và biến thể chữ 4
hở đỉnh. Cuối cùng em ghép chuỗi, kiểm tra định dạng và quyết định trạng thái,
không tự sửa ký tự.”

---

## 3. Sơ đồ phần của mình

```text
ảnh biển đã hiệu chỉnh (từ Khải)
 │
 ▼
segment_characters
 │   resize width 640
 │   CLAHE + blur + threshold auto (Otsu / adaptive)
 │   chuẩn hóa cực tính (mực = foreground)
 │   xóa viền, ốc vít, gạch phân cách
 │   projection ngang → tách dòng (fallback connected components)
 │   contour trong từng dòng → lọc hình học
 │   tách hộp quá rộng bằng valley dọc
 │   gộp mảnh, khử trùng, sắp thứ tự
 ▼
SegmentationResult (danh sách ảnh ký tự)
 │
 ▼
recognize_characters
 │   normalize 32×48 (stretch)
 │   coarse 6 template/nhãn → top 6 nhãn
 │   full match các nhãn top
 │   hole prior, margin
 ▼
CharacterPrediction[]
 │
 ▼
build_text_result
 │   ghép chuỗi, '?' cho ký tự chưa chắc
 │   rerank theo vị trí (không tạo nhãn mới)
 │   validate regex
 │   SUCCESS / FORMAT_WARNING / LOW_CONFIDENCE
```

---

## 4. Kiến thức bắt buộc

### 4.1. Vì sao resize biển về rộng 640?

Để kích thước ký tự tương đối ổn định giữa ảnh to/nhỏ, giúp tham số chiều cao,
chiều rộng và projection có ý nghĩa. Không phóng quá 4 lần để tránh khuếch đại
nhiễu.

### 4.2. Chọn ngưỡng nhị phân tự động

Hệ thống thử Otsu và nhiều block size adaptive. Mỗi phương án được chấm
`_plausibility_score`:

```text
score = 0.50·count_score + 0.25·height_score + 0.15·row_score + 0.10·(1 − edge_frac)
```

- `count_score`: 1 nếu số ký tự trong 7–9 hoặc 10 cân bằng; giảm nếu lệch.
- `height_score`: 1 trừ độ biến thiên chiều cao (CV/0.65).
- `row_score`: 1 nếu một dòng đủ ký tự, hoặc hai dòng 3–4 / 4–5.
- `edge_frac`: tỷ lệ hộp chạm biên (càng ít càng tốt).

Chọn phương án điểm cao nhất; nếu hòa thì ưu tiên phương pháp cấu hình.

### 4.3. Chuẩn hóa cực tính

Biển có nền sáng chữ tối hoặc nền tối chữ sáng. Hệ thống kiểm tra tỷ lệ mực và
đảo ảnh nếu cần để **ký tự luôn là foreground** (trắng trên nền đen). Đây là
chuẩn hóa bình thường, không phải lỗi.

### 4.4. Xóa viền, ốc vít, gạch phân cách

- Xóa margin 1.5% quanh biên.
- Loại thành phần chạm biên và kéo dài (viền, đường kẻ).
- Loại thành phần quá nhỏ (nhiễu) hoặc quá lớn theo cả hai chiều (khung biển).
- Không xóa quá nhiều: nếu còn dưới 3 hộp thì giữ lại tập ban đầu.

### 4.5. Tách dòng

Projection ngang `p(y) = Σ_x B(x,y)`. Dải có `p(y) > 0.02·max(p)` là một dòng.
Làm mượt projection, gộp khoảng hở nhỏ. Nếu projection gộp hai dòng, dùng
fallback connected components (`component_row_fallback`).

### 4.6. Lọc hộp ký tự

- Chiều cao: 42%–102% chiều cao dòng.
- Chiều rộng: 0.8%–24% chiều rộng biển.
- Diện tích: ≥ 0.03% diện tích biển.
- Độ đầy: ≥ 8%.
- Hộp quá rộng gần gấp đôi → tìm valley dọc để tách (`split_wide`).

### 4.7. Quy tắc 7–9 và 10 ký tự

- Chuẩn: 7–9 ký tự.
- 10 ký tự chỉ chấp nhận khi hai dòng cân bằng (ví dụ 5/5) — ví dụ `8.jpg`.
- Dưới `min_chars = 5` hoặc ngoài khoảng cho phép → `IMPLAUSIBLE`.

Mục đích: tránh ghép mảnh nhiễu ở mép thành chuỗi giả.

### 4.8. Chuẩn hóa ký tự 32×48

Cắt sát ink box, kéo giãn về 32×48 (`stretch`), padding 2 px, làm mờ nhẹ σ = 2.0.
Kéo giãn giúp template và ký tự cùng khung, giảm lệch do font và độ dày nét.

### 4.9. Bộ template

- 36 nhãn `0–9`, `A–Z`.
- 15 font Windows × 3 biến thể (normal/thick/thin) × 36 = **1.620 template thô**.
- Khử gần trùng còn **1.550 template đầy đủ**.
- **216 template coarse** (6 đại diện mỗi nhãn).
- Thêm 45 biến thể chữ `4` hở đỉnh.

### 4.10. Template Matching

`cv2.matchTemplate` với `TM_CCOEFF_NORMED`:

```text
R = Σ T'·I' / √(ΣT'² · ΣI'²)
```

Cho phép dịch ±1 px. Hai tầng: coarse 6 template/nhãn → giữ 6 nhãn → chấm đầy
đủ các nhãn đó.

### 4.11. Hole prior

Đếm số lỗ của ký tự; nếu khác số lỗ phổ biến của nhãn template thì trừ 0.20
điểm. Ví dụ `8` có 2 lỗ, `0` có 1 lỗ, `B` có 2 lỗ. Ngoại lệ: query không có lỗ
mà template 1 lỗ thì không trừ (nhị phân có thể làm mất lỗ).

### 4.12. Ngưỡng và margin

- Điểm cao nhất < 0.60 → `UNKNOWN`, gán `?`.
- Margin top-1/top-2 < 0.035 → `AMBIGUOUS`, gán `?`.
- Ngược lại → `OK`.

### 4.13. Hậu xử lý

1. Ghép chuỗi theo `order`; ký tự không `OK` thành `?`.
2. Rerank theo vị trí: chỉ chọn trong `ranked` đã chấm, giảm tối đa 0.15 điểm,
   phải hơn nhãn thứ hai 0.02. **Không tạo nhãn mới.**
3. Validate regex `^[0-9]{2}[A-Z]{1,2}[0-9]{4,6}$`, series hợp lệ
   `ABCDEFGHKLMNPSTUVXYZ`.
4. Trạng thái: còn `?`, mean < 0.60, min < 0.50 hoặc tỷ lệ chắc chắn < 0.85 →
   `LOW_CONFIDENCE`; đủ tin cậy nhưng sai định dạng → `FORMAT_WARNING`; còn lại
   `SUCCESS`.

---

## 5. Câu hỏi thầy hay hỏi — trả lời mẫu

**1. Vì sao phải phân đoạn trước khi nhận dạng?**
Template Matching so từng ký tự, không so cả chuỗi. Nếu tách sai vị trí hoặc
thiếu ký tự thì nhận dạng sai dù template tốt.

**2. Vì sao chọn ngưỡng tự động thay vì cố định Otsu?**
Ảnh thật có sáng không đều, lóa, nền tối. Otsu tốt với histogram hai đỉnh;
adaptive tốt với nền không đều. Hệ thống thử cả hai và chọn theo điểm hợp lý
hình học.

**3. Vì sao đảo ảnh nhị phân?**
Để ký tự luôn là foreground. Nếu không, contour sẽ bắt nền thay vì chữ.

**4. Làm sao loại ốc vít và viền biển?**
Dựa trên thành phần chạm biên, kích thước quá lớn theo cả hai chiều, hoặc quá
mảnh và dài. Đồng thời xóa margin quanh biên.

**5. Tách dòng thế nào nếu hai dòng dính nhau?**
Projection ngang có thể gộp; khi đó dùng connected components để tìm dòng, hoặc
tách theo khoảng trắng lớn nhất. Đây là fallback có cấu hình.

**6. Vì sao lọc theo chiều cao tương đối của dòng?**
Vì ký tự phải cao gần bằng dòng; hộp quá thấp là nhiễu/gạch, hộp quá cao là
viền hoặc hai dòng dính.

**7. Tách ký tự dính bằng cách nào?**
Tìm điểm thắt (valley) trong projection dọc gần giữa hộp; nếu hai phần đủ lớn và
valley đủ rõ thì tách. Nếu không, giữ nguyên và có thể bị từ chối.

**8. Vì sao 10 ký tự chỉ nhận khi hai dòng cân bằng?**
Vì biển Việt Nam thông thường 7–9 ký tự; 10 ký tự thường là biển đặc biệt hai
dòng 5/5. Nếu không cân bằng, khả năng cao là ghép mảnh nhiễu.

**9. Nếu một dòng chỉ có 1–2 thành phần thì sao?**
Coi là viền/ốc vít/nhiễu và loại dòng đó, tránh ghép ký tự rác.

**10. Vì sao chuẩn hóa `stretch` thay vì giữ tỷ lệ?**
Ký tự biển có nhiều font, chiều rộng/thân khác nhau. Kéo giãn đưa về cùng khung,
giảm lệch; đổi lại có thể méo nhẹ với ký tự quá hẹp.

**11. Vì sao dùng `TM_CCOEFF_NORMED`?**
Bất biến với thay đổi sáng/tương phản tuyến tính, điểm chuẩn hóa dễ đặt ngưỡng.

**12. Vì sao làm mờ template σ = 2.0?**
Giảm nhạy cảm với độ dày nét và lệch căn chỉnh giữa font template và font ảnh.

**13. Hai tầng nhận dạng để làm gì?**
Coarse lọc nhanh bằng 6 template/nhãn, giữ 6 nhãn; full chỉ chấm các nhãn đó.
Giảm số phép so khớp mà gần như không mất độ chính xác.

**14. Hole prior có phải học máy không?**
Không. Đây là prior topology thủ công: đếm số lỗ và trừ điểm nếu lệch. Nó không
tạo ký tự mới, chỉ hạ ứng viên.

**15. Vì sao có biến thể chữ 4 hở đỉnh?**
Font biển thật có kiểu `4` nét dọc phải bắt đầu từ giữa, khác font Windows. Đây
là augmentation thủ công.

**16. Margin dùng để làm gì?**
Nếu top-1 và top-2 gần nhau, hệ thống không đủ tin cậy. Margin nhỏ → `?` thay vì
đoán.

**17. Hậu xử lý có tự sửa ký tự cho đúng định dạng không?**
Không. Chỉ chọn lại trong danh sách đã chấm, có giới hạn điểm. Không đổi ký tự
chỉ để chuỗi trông hợp lệ.

**18. Vì sao loại `I, J, O, Q, W`?**
Đây là các nhãn không dùng trên biển Việt Nam; loại khỏi điểm số để tránh nhầm
`I/1`, `O/0`, `Q/0`.

**19. Vì sao kết quả còn nhiều `?`?**
Do điểm dưới 0.60 hoặc margin nhỏ. Đây là lựa chọn bảo thủ có chủ ý, không phải
lỗi ghép chuỗi.

**20. Nếu thiếu template thì sao?**
`load_templates` báo `TemplateError`; pipeline trả `CONFIG_ERROR` nếu
`fail_on_missing_templates = true`. Có thể kiểm tra bằng `python main.py info`.

---

## 6. Câu hỏi nối sang phần người khác

**21. Vùng biển bị cắt lệch thì phần mình chịu ảnh hưởng thế nào?**
Phân đoạn có thể mất ký tự ở mép hoặc dính viền. Mình không sửa vùng cắt; pipeline
sẽ thử ứng viên khác.

**22. Ai chịu trách nhiệm phát hiện biển?**
Khải. Phần mình nhận `RectificationResult.plate_image` và trả
`SegmentationResult`.

**23. Ai đo CSA/CA?**
Đạt, trong `src/evaluation.py`. Mình cung cấp `char_boxes_original` và chuỗi dự
đoán.

**24. Nếu thay đổi ngưỡng nhận dạng thì ảnh hưởng gì?**
Tăng ngưỡng → ít đoán bừa nhưng nhiều `?`; giảm ngưỡng → nhiều ký tự được điền
nhưng dễ sai. Phải đo lại dev.

**25. Vì sao kết quả 13/13 ảnh thật không chứng minh tổng quát?**
Vì 14 ảnh đã dùng để tinh chỉnh segmentation/recognition. Đó là kiểm tra hồi quy,
không phải holdout.

---

## 7. Demo checklist

1. Chạy một biển một dòng: `python main.py recognize data\samples\dev_clear_001.jpg --save-debug`.
2. Mở `characters/` — chỉ từng ký tự, điểm, margin, nhãn thứ hai.
3. Chạy một biển hai dòng (`dev_two_line_001.jpg`) — giải thích tách dòng.
4. Chạy một ảnh dính (`dev_touching_001.jpg`) — nói rõ vì sao thiếu hộp.
5. Chạy `python main.py info` — nói 1.620 thô → 1.550 đầy đủ → 216 coarse.
6. `python -m pytest -q` — 78 passed.

---

## 8. Bẫy cần tránh

- Đừng nói “template matching hiểu ngữ nghĩa ký tự”; nó chỉ so hình dáng.
- Đừng nói “hole prior là học máy”; đó là quy tắc đếm lỗ.
- Đừng nói “hệ thống tự sửa biển sai thành đúng”; nó chỉ từ chối.
- Đừng nói “10 ký tự luôn được chấp nhận”; chỉ khi hai dòng cân bằng.
- Đừng nhận công đoạn detection/rectification; nói rõ interface nhận từ Khải.

---

## 9. Từ khóa phải nhớ

`SegmentationResult` · `SegmentedCharacter` · `plausibility_score` ·
`projection profile` · `component_row_fallback` · `split_wide` ·
`expected_chars [7, 9]` · `normalize 32×48` · `TM_CCOEFF_NORMED` ·
`coarse_templates 216` · `hole_prior` · `min_margin 0.035` ·
`score_threshold 0.60` · `position_constraints` · `SUCCESS / FORMAT_WARNING /
LOW_CONFIDENCE`

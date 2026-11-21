# Báo cáo thực nghiệm — Nhận dạng biển số xe Việt Nam

- **Ngày đo:** 2026-11-03
- **Cấu hình đo:** `config.yaml`
- **SHA-256 cấu hình:**
  `69C7570BD94D24B9307D711B88C6E1B415DFB28A772A10A8C75D038CACA59DDA`
- **Môi trường:** Windows, Python 3.13.6, OpenCV 4.10.0, NumPy 2.1.3,
  Pillow 11.3.0, PyYAML 6.0.3, pytest 8.3.4.
- **Nguyên tắc số liệu:** các con số dưới đây được tính tự động từ
  `results/user_final.csv`, `results/user_special_final.csv`,
  `results/dev_after_final.csv` và `results/test_after_final.csv`.
  Không có kết quả nào được nhập thủ công hoặc suy đoán.

> **Kết luận ngắn:** 14 ảnh thật do người dùng cung cấp đều cho chuỗi chính xác
> và trạng thái `SUCCESS` (13 ảnh thường + `8.jpg`), nhưng đây là tập **đã
> dùng để tinh chỉnh**, không phải holdout độc lập. Trên tập tổng hợp, dev đạt
> PDR 100% và EPA 47.83%; test đạt PDR 82.61% và EPA 47.83%. Hệ thống **chưa
> đạt mục tiêu tham chiếu EPA ≥ 70%** trên dữ liệu tổng hợp.

---

## 1. Mục tiêu và phạm vi

Hệ thống nhận dạng biển số xe Việt Nam bằng xử lý ảnh truyền thống:

- Không dùng học máy/học sâu, YOLO, KNN, SVM, OCR học sẵn hoặc API ngoài.
- Đầu vào: ảnh JPG/JPEG/PNG/WEBP.
- Hỗ trợ biển một dòng và hai dòng, cấu trúc:
  `2 chữ số tỉnh + 1–2 chữ series + 4–6 chữ số`.
- Biển chuẩn 7–9 ký tự; biển đặc biệt 10 ký tự chỉ được chấp nhận khi hai
  dòng cân bằng (ví dụ 5/5).
- Ảnh tĩnh, mỗi ảnh có tối đa một biển chính.
- Giao diện desktop Tkinter, có file `.bat` để chạy.
- Cấu hình tập trung, tài liệu tiếng Việt, kiểm thử pytest và xuất CSV.

Ngoài phạm vi: video, camera thời gian thực, nhiều biển trong một ảnh, đọc ký
tự tự do ngoài cấu trúc biển Việt Nam.

## 2. Quy trình xử lý

### 2.1. Tiền xử lý

- Đọc ảnh an toàn, kiểm tra định dạng và kích thước tối thiểu.
- Chuyển grayscale, giảm nhiễu, tăng tương phản cục bộ bằng CLAHE.
- Tính cạnh Canny và ảnh nhị phân Otsu để phục vụ phát hiện.

### 2.2. Phát hiện biển

- Sinh ứng viên hình học từ cạnh, morphology, contour và đặc trưng hình học
  (tỷ lệ, diện tích, độ đặc, độ giống văn bản).
- Sinh thêm ứng viên từ cụm thành phần giống ký tự, giúp cứu các biển có
  viền mờ hoặc bị cắt một phần.
- Ứng viên cụm chữ có thể **mượn hộp hình học** của một ứng viên hình học
  chồng lấn để báo cáo vị trí (bbox hint). Việc này chỉ đổi tọa độ báo cáo;
  ảnh crop dùng cho nhận dạng vẫn giữ nguyên.
- Chọn tối đa 8 ứng viên tốt nhất để thử phân đoạn và nhận dạng.

### 2.3. Hiệu chỉnh phối cảnh

- Xấp xỉ tứ giác biển, sắp xếp 4 góc và biến đổi phối cảnh về ảnh thẳng.
- Thêm padding ngang 10% và dọc 6% chiều rộng để hạn chế cắt góc.
- Ánh xạ ngược tọa độ ký tự về ảnh gốc.

### 2.4. Phân đoạn ký tự

- Resize biển về rộng 640 px, tăng tương phản và chuẩn hóa cực tính để ký tự
  là foreground.
- Xóa viền biển, ốc vít, gạch phân cách và nhiễu nhỏ.
- Tách dòng bằng projection ngang; có fallback bằng connected components khi
  hai dòng sát nhau bị gộp.
- Tách ký tự bằng contour + projection dọc, tách box quá rộng theo valley.
- Lọc hình học, sắp xếp theo thứ tự đọc.
- Chấp nhận 7–9 ký tự; ngoại lệ 10 ký tự chỉ khi hai dòng cân bằng 5/5.
  Quy tắc này tránh việc một mảnh nhiễu ở mép tạo thành chuỗi 4/6 giả.

### 2.5. Nhận dạng

- Chuẩn hóa ký tự về canvas **32×48**, kéo giãn ink box (`stretch`).
- `cv2.matchTemplate` với `TM_CCOEFF_NORMED`, làm mờ σ = 2.0.
- Hai tầng:
  1. chấm nhanh trên 6 template đại diện mỗi nhãn,
  2. chấm đầy đủ cho các nhãn tốt nhất.
- Loại `I, J, O, Q, W` khỏi điểm số vì không hợp lệ trên biển Việt Nam.
- Prior số lỗ giúp phân biệt `6/B`, `0/D`, `8/B`.
- Thêm biến thể chữ `4` hở đỉnh cho kiểu biển thật.
- Từ chối ký tự nếu điểm < 0.60 hoặc margin top-1/top-2 < 0.035.

### 2.6. Hậu xử lý

- Ghép chuỗi theo thứ tự đọc; ký tự chưa chắc chắn giữ `?`.
- Validate định dạng bằng regex `2 số + 1–2 chữ + 4–6 số`, độ dài 7–10.
- Rerank theo kiểu ký tự tại từng vị trí, chỉ chọn trong các ứng viên template
  đã được chấm điểm; **không tạo ký tự mới**. Ngưỡng margin riêng cho rerank
  theo vị trí là 0.02.
- **Không sửa ký tự** và không đổi ký tự chỉ để chuỗi trông hợp lệ hơn.
- Quyết định `SUCCESS`, `FORMAT_WARNING`, `LOW_CONFIDENCE`.

### 2.7. Đánh giá

- **PDR:** tỷ lệ ảnh có biển được phát hiện đúng, IoU box biển ≥ 0.5.
- **Detection Precision/Recall:** có tính ảnh không biển là lớp âm.
- **CSA:** tỷ lệ box ký tự ghép được với nhãn ở IoU ≥ 0.5, lấy trung bình
  theo ảnh có biển. Với ảnh thật chưa có box, dùng proxy theo số lượng.
- **CA:** số ký tự khớp / chiều dài căn chỉnh Levenshtein
  (`matches + substitutions + insertions + deletions`).
- **EPA:** chuỗi chuẩn hóa dự đoán trùng hoàn toàn nhãn. Con số chính lấy trên
  các ảnh có biển; báo cáo kèm con số trên toàn bộ ảnh theo công thức
  `N_test_images` của đặc tả.
- **Failure/Rejection Rate:** tỷ lệ ảnh ở trạng thái `LOW_CONFIDENCE`,
  `PLATE_NOT_FOUND`, `INVALID_IMAGE`, `CONFIG_ERROR`.

## 3. Dữ liệu

### 3.1. Bộ dữ liệu tổng hợp

Do `tools/build_synthetic_dataset.py` sinh ra, seed 2026.

| Thuộc tính | Dev | Test | Tổng |
|---|---:|---:|---:|
| Số ảnh | 26 | 26 | 52 |
| Ảnh có biển | 23 | 23 | 46 |
| Ảnh không biển | 3 | 3 | 6 |
| Biển một dòng | 19 | 19 | 38 |
| Biển hai dòng | 4 | 4 | 8 |
| Không biển | 3 | 3 | 6 |

Điều kiện mỗi split:

| Điều kiện | Số ảnh |
|---|---:|
| Rõ (`clear`) | 5 |
| Nghiêng (`tilted`) | 4 |
| Hai dòng (`two_line`) | 4 |
| Thiếu sáng (`low_light`) | 3 |
| Ký tự dính (`touching`) | 3 |
| Chất lượng thấp (`low_quality`) | 3 |
| Không biển (`no_plate`) | 3 |
| Độ phân giải thấp (`low_resolution`) | 1 |

Nhãn gồm box biển, box từng ký tự và metadata. Ảnh mẫu dùng các font
Calibri, Verdana, Times New Roman, Trebuchet — **khác với font sinh
template** — để tránh việc template khớp đúng font của ảnh kiểm thử.

### 3.2. Ảnh thật do người dùng cung cấp

`data/user_images/` có 14 ảnh; nhãn chuỗi nằm trong `data/user_labels.csv`.

| Ảnh | Chuỗi | Loại | Ghi chú |
|---|---|---|---|
| 1.webp | 71C279979 | two_line | Biển vuông 2 dòng |
| 2.webp | 51F97022 | one_line | Ô tô 1 dòng |
| 3.webp | 29C199999 | two_line | Biển vuông 2 dòng |
| 4.webp | 59Y183159 | two_line | Biển vuông 2 dòng |
| 5.webp | 59D266696 | two_line | Biển vuông 2 dòng |
| 6.webp | 73K99999 | two_line | Biển vuông 2 dòng |
| 7.webp | 30G63223 | one_line | Ô tô 1 dòng |
| 8.jpg | 17MD799999 | two_line | Biển đặc biệt 10 ký tự (5/5) |
| 9.webp | 29AA03194 | two_line | Biển vuông 2 dòng |
| 10.webp | 63B999999 | two_line | Biển vuông 2 dòng |
| 11.webp | 29B155555 | two_line | Biển vuông 2 dòng |
| 12.webp | 30G49344 | two_line | Ô tô, dải đỏ VIE |
| 13.webp | 51H48016 | two_line | Ô tô, dải đỏ VIE |
| 14.webp | 51F86699 | one_line | Ô tô 1 dòng |

**Cảnh báo:** nhãn ảnh thật chưa có box biển và box ký tự. Vì vậy PDR/CSA trên
split `user` chỉ là proxy theo sự hiện diện và số lượng, không phải IoU. Toàn
bộ 14 ảnh đã được dùng để tinh chỉnh tham số, nên 14/14 không phải kết quả
trên holdout độc lập.

## 4. Kết quả tổng hợp

### 4.1. Ảnh thật — split `user` (13 ảnh)

| Chỉ số | Giá trị |
|---|---:|
| Plate Detection Rate (proxy) | **100.00%** |
| Detection Precision | **100.00%** (TP=13, FP=0, FN=0, TN=0) |
| Detection Recall (proxy) | **100.00%** |
| Character Segmentation Accuracy (count proxy) | **100.00%** |
| Character Accuracy | **100.00%** |
| Exact Plate Accuracy | **100.00%** (13/13) |
| Thời gian trung bình | **1863.94 ms** |
| Success Rate | **100.00%** (13/13) |
| Trạng thái | SUCCESS 13 |

### 4.2. Ảnh đặc biệt `8.jpg` (split `special`)

| Chỉ số | Giá trị |
|---|---:|
| Plate Detection Rate (proxy) | **100.00%** |
| Detection Precision | **100.00%** (TP=1, FP=0, FN=0, TN=0) |
| Character Segmentation Accuracy (count proxy) | **100.00%** |
| Character Accuracy | **100.00%** (10/10) |
| Exact Plate Accuracy | **100.00%** (1/1) |
| Thời gian | **17822.84 ms** |
| Trạng thái | SUCCESS 1 |

`8.jpg` chậm chủ yếu ở công đoạn phát hiện (16.45 s) do ảnh lớn và nhiều ứng
viên; đây là chi phí thực đo, không phải ước lượng.

### 4.3. Dev tổng hợp (26 ảnh)

| Chỉ số | Giá trị |
|---|---:|
| Plate Detection Rate | **100.00%** (23/23) |
| Detection Precision | **100.00%** (TP=23, FP=0, FN=0, TN=3) |
| Detection Recall | **100.00%** |
| Character Segmentation Accuracy (mean) | **97.67%** |
| CSA đếm gộp (matched/GT) | 171/175 = 97.71% |
| Character Accuracy | **88.00%** |
| Character Accuracy trên tổng ký tự nhãn | 88.00% (154/175) |
| Exact Plate Accuracy (23 ảnh có biển) | **47.83%** (11/23) |
| Exact Plate Accuracy (toàn bộ 26 ảnh) | 42.31% (11/26) |
| Thời gian trung bình | **1498.09 ms** |
| Success Rate | 65.38% (17/26) |
| Failure/Rejection Rate | 26.92% |
| Trạng thái | SUCCESS 17, FORMAT_WARNING 2, LOW_CONFIDENCE 4, PLATE_NOT_FOUND 3 |

### 4.4. Test tổng hợp (26 ảnh)

| Chỉ số | Giá trị |
|---|---:|
| Plate Detection Rate | **82.61%** (19/23) |
| Detection Precision | **100.00%** (TP=19, FP=0, FN=4, TN=3) |
| Detection Recall | **82.61%** |
| Character Segmentation Accuracy (mean) | **80.98%** |
| CSA đếm gộp (matched/GT) | 152/187 = 81.28% |
| Character Accuracy | **71.66%** |
| Character Accuracy trên tổng ký tự nhãn | 71.66% (134/187) |
| Exact Plate Accuracy (23 ảnh có biển) | **47.83%** (11/23) |
| Exact Plate Accuracy (toàn bộ 26 ảnh) | 42.31% (11/26) |
| Thời gian trung bình | **1358.76 ms** |
| Success Rate | 50.00% (13/26) |
| Failure/Rejection Rate | 42.31% |
| Trạng thái | SUCCESS 13, LOW_CONFIDENCE 9, FORMAT_WARNING 2, PLATE_NOT_FOUND 2 |

### 4.5. Thời gian từng công đoạn

| Công đoạn | User (13) | 8.jpg | Dev | Test |
|---|---:|---:|---:|---:|
| Tiền xử lý | 8.50 ms | 38.22 ms | 19.24 ms | 19.28 ms |
| Phát hiện | 623.29 ms | 16450.36 ms | 491.68 ms | 496.25 ms |
| Hiệu chỉnh | 9.46 ms | 39.04 ms | 4.32 ms | 4.48 ms |
| Phân đoạn | 218.03 ms | 279.93 ms | 174.19 ms | 120.99 ms |
| Nhận dạng | 980.51 ms | 968.70 ms | 904.54 ms | 874.18 ms |
| Hậu xử lý | 0.15 ms | 0.95 ms | 0.17 ms | 0.15 ms |
| **Tổng trung bình** | **1863.94 ms** | **17822.84 ms** | **1498.09 ms** | **1358.76 ms** |

Thời gian dao động theo tải máy và số ứng viên; đây không phải benchmark tối
ưu. Template load lúc khởi động khoảng 1.4 s.

## 5. Kết quả từng ảnh

### 5.1. Ảnh thật — split `user`

Dấu `-` và `.` trong cột dự đoán chỉ là định dạng hiển thị; so khớp EPA dùng
chuỗi đã chuẩn hóa.

| Ảnh | GT | Dự đoán | Trạng thái | CA | Seg proxy | ms |
|---|---|---|---:|---:|---:|---:|
| 1.webp | 71C279979 | 71C279979 | SUCCESS | 100.0% | 9/9 | 553 |
| 2.webp | 51F97022 | 51F-970.22 | SUCCESS | 100.0% | 8/8 | 2037 |
| 3.webp | 29C199999 | 29C199999 | SUCCESS | 100.0% | 9/9 | 1751 |
| 4.webp | 59Y183159 | 59Y183159 | SUCCESS | 100.0% | 9/9 | 4457 |
| 5.webp | 59D266696 | 59D266696 | SUCCESS | 100.0% | 9/9 | 2734 |
| 6.webp | 73K99999 | 73K-999.99 | SUCCESS | 100.0% | 8/8 | 1210 |
| 7.webp | 30G63223 | 30G-632.23 | SUCCESS | 100.0% | 8/8 | 1367 |
| 9.webp | 29AA03194 | 29AA-031.94 | SUCCESS | 100.0% | 9/9 | 1789 |
| 10.webp | 63B999999 | 63B999999 | SUCCESS | 100.0% | 9/9 | 1652 |
| 11.webp | 29B155555 | 29B155555 | SUCCESS | 100.0% | 9/9 | 1719 |
| 12.webp | 30G49344 | 30G-493.44 | SUCCESS | 100.0% | 8/8 | 1218 |
| 13.webp | 51H48016 | 51H-480.16 | SUCCESS | 100.0% | 8/8 | 2407 |
| 14.webp | 51F86699 | 51F-866.99 | SUCCESS | 100.0% | 8/8 | 1337 |

`8.jpg` (special): GT `17MD799999`, dự đoán `17MD799999`, `SUCCESS`, CA 100%,
seg proxy 10/10, 17823 ms.

### 5.2. Dev

| Ảnh | GT | Dự đoán | Trạng thái | CA | Seg (match/GT) | IoU | ms |
|---|---|---|---:|---:|---:|---:|---:|
| dev_clear_001.jpg | 88Y79730 | 88Y-797.30 | SUCCESS | 100.0% | 8/8 | 0.980 | 527 |
| dev_clear_002.jpg | 60F59244 | 60F-592.44 | SUCCESS | 100.0% | 8/8 | 0.980 | 1085 |
| dev_clear_003.jpg | 60F3499 | 60F-3499 | SUCCESS | 100.0% | 7/7 | 0.924 | 1203 |
| dev_clear_004.jpg | 43S82458 | 43S-824.58 | SUCCESS | 100.0% | 8/8 | 0.803 | 1234 |
| dev_clear_005.jpg | 65E4196 | 65E-4296 | SUCCESS | 85.7% | 7/7 | 0.910 | 1931 |
| dev_tilted_001.jpg | 79G46182 | 79G46X82 | FORMAT_WARNING | 87.5% | 8/8 | 0.959 | 2092 |
| dev_tilted_002.jpg | 79TH29950 | 7???29950 | LOW_CONFIDENCE | 66.7% | 9/9 | 0.725 | 2238 |
| dev_tilted_003.jpg | 51N6368 | 52N-6368 | SUCCESS | 85.7% | 7/7 | 0.672 | 1226 |
| dev_tilted_004.jpg | 29AN4302 | 29AN-4302 | SUCCESS | 100.0% | 8/8 | 0.822 | 1307 |
| dev_low_light_001.jpg | 29L9151 | 29L925T | FORMAT_WARNING | 71.4% | 7/7 | 0.895 | 4683 |
| dev_low_light_002.jpg | 65XA19061 | 65XA-190.61 | SUCCESS | 100.0% | 9/9 | 0.961 | 2437 |
| dev_low_light_003.jpg | 29E61446 | 29E-644.46 | SUCCESS | 87.5% | 8/8 | 0.948 | 2585 |
| dev_two_line_001.jpg | 80A2504 | 80A-2504 | SUCCESS | 100.0% | 7/7 | 0.801 | 1380 |
| dev_two_line_002.jpg | 65X4959 | 65X-4959 | SUCCESS | 100.0% | 7/7 | 0.946 | 1221 |
| dev_two_line_003.jpg | 79S8522 | 79S-8522 | SUCCESS | 100.0% | 7/7 | 0.714 | 1356 |
| dev_two_line_004.jpg | 30E54194 | 30E-541.94 | SUCCESS | 100.0% | 7/8 | 0.808 | 1578 |
| dev_touching_001.jpg | 43S13778 | 43S237?3 | LOW_CONFIDENCE | 62.5% | 7/8 | 0.996 | 2066 |
| dev_touching_002.jpg | 88X6274 | ????274 | LOW_CONFIDENCE | 42.9% | 5/7 | 0.760 | 1140 |
| dev_touching_003.jpg | 59B61876 | 59B?2876 | LOW_CONFIDENCE | 75.0% | 8/8 | 0.977 | 1257 |
| dev_low_quality_001.jpg | 43U7581 | 43U-7582 | SUCCESS | 85.7% | 7/7 | 0.957 | 1937 |
| dev_low_quality_002.jpg | 30K7504 | 30K-7504 | SUCCESS | 100.0% | 7/7 | 0.836 | 1265 |
| dev_low_quality_003.jpg | 79B23618 | 79B-236.28 | SUCCESS | 87.5% | 8/8 | 0.916 | 1394 |
| dev_no_plate_001.jpg | — | — | PLATE_NOT_FOUND | — | 0/0 | — | 353 |
| dev_no_plate_002.jpg | — | — | PLATE_NOT_FOUND | — | 0/0 | — | 346 |
| dev_no_plate_003.jpg | — | — | PLATE_NOT_FOUND | — | 0/0 | — | 339 |
| dev_low_resolution_001.jpg | 43E2517 | 43E-2527 | SUCCESS | 85.7% | 7/7 | 0.870 | 774 |

### 5.3. Test

| Ảnh | GT | Dự đoán | Trạng thái | CA | Seg (match/GT) | IoU | ms |
|---|---|---|---:|---:|---:|---:|---:|
| test_clear_001.jpg | 51YD28671 | 52YD-286.72 | SUCCESS | 77.8% | 9/9 | 0.874 | 577 |
| test_clear_002.jpg | 29UX78014 | 29UX-780?4 | LOW_CONFIDENCE | 88.9% | 9/9 | 0.947 | 2133 |
| test_clear_003.jpg | 59H28350 | 59H-283.50 | SUCCESS | 100.0% | 8/8 | 0.980 | 1211 |
| test_clear_004.jpg | 88E9731 | 88E-973? | LOW_CONFIDENCE | 85.7% | 7/7 | 0.650 | 1829 |
| test_clear_005.jpg | 59S10631 | 59ST063T | FORMAT_WARNING | 75.0% | 8/8 | 0.917 | 2082 |
| test_tilted_001.jpg | 29X62045 | — | LOW_CONFIDENCE | 0.0% | 0/8 | 0.000 | 458 |
| test_tilted_002.jpg | 60YT67360 | 60YT-673.60 | SUCCESS | 100.0% | 9/9 | 0.793 | 1341 |
| test_tilted_003.jpg | 51UZ1212 | 5YUZ?2Y2 | LOW_CONFIDENCE | 62.5% | 8/8 | 0.670 | 2090 |
| test_tilted_004.jpg | 30A06871 | — | LOW_CONFIDENCE | 0.0% | 0/8 | 0.000 | 557 |
| test_low_light_001.jpg | 60ZS1731 | 60ZS-1731 | SUCCESS | 100.0% | 6/8 | 0.748 | 2467 |
| test_low_light_002.jpg | 43V88552 | 43V-885.52 | SUCCESS | 100.0% | 8/8 | 0.977 | 2715 |
| test_low_light_003.jpg | 30ME74117 | 30ME-741.17 | SUCCESS | 100.0% | 9/9 | 0.979 | 2801 |
| test_two_line_001.jpg | 88T0344 | 88T-0344 | SUCCESS | 100.0% | 7/7 | 0.904 | 1292 |
| test_two_line_002.jpg | 43BP49598 | 43BP-495.98 | SUCCESS | 100.0% | 9/9 | 0.766 | 1448 |
| test_two_line_003.jpg | 79A35633 | 79A-356.33 | SUCCESS | 100.0% | 8/8 | 0.750 | 1398 |
| test_two_line_004.jpg | 29X72319 | 29X-723.29 | SUCCESS | 87.5% | 8/8 | 0.704 | 1451 |
| test_touching_001.jpg | 79D60193 | ???X? | LOW_CONFIDENCE | 0.0% | 5/8 | 0.488 | 1091 |
| test_touching_002.jpg | 59C58382 | ??? | LOW_CONFIDENCE | 0.0% | 1/8 | 0.431 | 889 |
| test_touching_003.jpg | 80V10121 | ??Z | LOW_CONFIDENCE | 0.0% | 1/8 | 0.802 | 725 |
| test_low_quality_001.jpg | 88C51274 | 66C5A274 | FORMAT_WARNING | 62.5% | 8/8 | 0.869 | 2163 |
| test_low_quality_002.jpg | 59Y67876 | 59Y-678.76 | SUCCESS | 100.0% | 8/8 | 0.942 | 1323 |
| test_low_quality_003.jpg | 29GD6529 | 29GD-6529 | SUCCESS | 100.0% | 8/8 | 0.897 | 1342 |
| test_no_plate_001.jpg | — | — | PLATE_NOT_FOUND | — | 0/0 | — | 344 |
| test_no_plate_002.jpg | — | — | PLATE_NOT_FOUND | — | 0/0 | — | 388 |
| test_no_plate_003.jpg | — | — | LOW_CONFIDENCE | — | 0/0 | — | 315 |
| test_low_resolution_001.jpg | 29Z54728 | 29Z-547.28 | SUCCESS | 100.0% | 8/8 | 0.933 | 896 |

## 6. Phân tích lỗi

### 6.1. Phát hiện biển

- Dev: phát hiện đúng 23/23 ảnh có biển, không báo nhầm 3 ảnh không biển.
- Test: 19/23 ảnh có biển đạt IoU ≥ 0.5.
  - `test_tilted_001.jpg` và `test_tilted_004.jpg`: IoU 0, không có text;
    nghiêng mạnh làm pipeline không chọn được vùng biển hợp lệ.
  - `test_touching_001.jpg`: IoU 0.488; `test_touching_002.jpg`: IoU 0.431.
    Hai ca này sát ngưỡng và chuỗi tạo ra rất ngắn.
  - `test_touching_003.jpg` vẫn phát hiện được (IoU 0.802) nhưng phân đoạn
    chỉ còn 1/8 box, nên không tạo được chuỗi hợp lệ.
- Không có false positive trên ảnh không biển ở cả hai split (precision
  100%). Tuy nhiên `test_no_plate_003` trả `LOW_CONFIDENCE` không có box thay
  vì `PLATE_NOT_FOUND`; vẫn được tính là âm đúng nhưng trạng thái chưa gọn.

### 6.2. Phân đoạn ký tự

Các ca làm giảm CSA:

| Ảnh | Seg match/GT | Ghi chú |
|---|---:|---|
| dev_two_line_004.jpg | 7/8 | thiếu một box nhưng chuỗi vẫn đúng |
| dev_touching_001.jpg | 7/8 | ký tự dính, tách thiếu |
| dev_touching_002.jpg | 5/7 | mất/ký tự dính |
| test_low_light_001.jpg | 6/8 | thiếu sáng, mất box |
| test_touching_001.jpg | 5/8 | ký tự dính, tách thiếu |
| test_touching_002.jpg | 1/8 | gần như không tách được |
| test_touching_003.jpg | 1/8 | gần như không tách được |

Các ảnh `touching` là điểm yếu rõ nhất. Fallback tách dòng bằng thành phần
liên thông và vá tách valley đã cải thiện một phần, nhưng chưa đủ cho các ca
dính mạnh.

### 6.3. Nhận dạng và nhầm lẫn ký tự

- Dev: 154/175 ký tự đúng, 21 thay thế, 0 thêm, 0 xóa.
- Test: 134/187 ký tự đúng, 24 thay thế, 0 thêm, 29 xóa. Số xóa lớn đến từ
  các ảnh `touching` chỉ tạo được 1–5 ký tự.

Các nhầm lẫn khi hệ thống **khẳng định** một ký tự sai (bỏ qua `?`):

| Cặp | Dev | Test |
|---|---:|---:|
| `1 → 2` | 8 | 3 |
| `1 → T` | 1 | 2 |
| `1 → Y` | 0 | 2 |
| `8 → 6` | 0 | 2 |
| `1 → X` | 1 | 0 |
| `1 → 4` | 1 | 0 |
| `8 → 3` | 1 | 0 |
| `9 → X` | 0 | 1 |
| `1 → Z` | 0 | 1 |
| `1 → A` | 0 | 1 |

Lỗi chủ đạo là chữ số `1` bị nhận thành `2`, `T`, `Y` hoặc `X`, đặc biệt khi
nét quá mảnh, mất một phần hoặc bị nghiêng. Phần lớn ký tự còn lại bị từ chối
thành `?` vì score hoặc margin không đạt ngưỡng; đây là lựa chọn có chủ ý,
không phải lỗi ghép chuỗi.

### 6.4. Từ chối và trạng thái

- Dev: 17 `SUCCESS`, 2 `FORMAT_WARNING`, 4 `LOW_CONFIDENCE`,
  3 `PLATE_NOT_FOUND`.
- Test: 13 `SUCCESS`, 9 `LOW_CONFIDENCE`, 2 `FORMAT_WARNING`,
  2 `PLATE_NOT_FOUND`.
- Nhiều ảnh có chuỗi gần đúng nhưng còn 1–2 ký tự `?`; hệ thống chủ động
  không đoán.
- `dev_tilted_001` đọc `1` thành `X`; `dev_low_light_001` đọc `1` thành `T`;
  `test_clear_005` đọc `1` thành `T`; `test_low_quality_001` đọc `1` thành
  `A`. Các chuỗi này không khớp regex nên trả `FORMAT_WARNING`. Hệ thống
  không tự sửa ký tự để chuỗi trông hợp lệ.
- Hai ảnh test nghiêng mạnh không có attempt hợp lệ nên trả
  `LOW_CONFIDENCE` với text rỗng, thay vì `PLATE_NOT_FOUND`.

## 7. Các thực nghiệm đã thử và quyết định

Các dòng ghi "số liệu lịch sử" được đo trên cấu hình cũ, không so sánh trực
tiếp với bảng kết quả cuối.

| Thực nghiệm | Kết quả đo / quan sát | Quyết định |
|---|---|---|
| Thêm template Calibri/Verdana/Times/Trebuchet (lần 1) | CA proxy 81.14%, EPA 34.78%, 438 ms (lịch sử) | Loại: thấp hơn baseline và chậm hơn |
| Mở rộng template lần 2 | CA proxy 81.71%, 542 ms (lịch sử) | Loại: không cải thiện, chậm hơn |
| Bright-plate quad (Otsu + approxPolyDP) | Hình học `dev_tilted_002` đẹp hơn nhưng làm hỏng `dev_clear_001/003`, `dev_tilted_004`, `dev_two_line_001` | Loại, giữ hiệu chỉnh Canny |
| Tăng `coarse_top_labels` lên 10 | Top-1 exact 13/23, 9 SUCCESS (lịch sử) | Không dùng: không tăng success đủ, tốn thời gian |
| Tăng `coarse_top_labels` lên 36 | Top-1 exact 14/23, 9 SUCCESS, chậm ~4× (lịch sử) | Không dùng: chậm, lợi ích nhỏ |
| Fallback chấm lại full-res cho ký tự bị từ chối | Sửa top-1 cho `dev_tilted_001`, `dev_low_quality_001`; không tăng số SUCCESS | Không dùng |
| Padding dọc 6% chiều rộng | Giảm cắt góc biển nghiêng | Giữ |
| Vá phân đoạn (ước lượng bề rộng + tách valley) | `dev_touching_002` tăng số box; chỉ số tổng không giảm | Giữ |
| Chuẩn hóa 32×48, `stretch`, blur σ = 2.0 | Cải thiện ổn định trên ảnh thật so với 24×36 giữ tỷ lệ | Giữ |
| Prior số lỗ | Giảm nhầm `6/B`, `0/D`, `8/B` | Giữ |
| Biến thể chữ `4` hở đỉnh | Nhận đúng kiểu chữ `4` trên biển thật | Giữ |
| Rerank theo vị trí + `position_min_margin=0.02` | Chọn đúng ứng viên cùng kiểu ký tự mà không tạo ký tự mới | Giữ |
| `expected_chars=[7,9]` + ngoại lệ 10 ký tự cân bằng | Sửa hồi quy `5.webp` (4/6 giả) và vẫn nhận `8.jpg` (5/5) | Giữ |
| Bbox hint cho ứng viên cụm chữ | Dev recall 82.61% → 100%; test recall 73.91% → 82.61% | Giữ |

## 8. Đối chiếu mục tiêu tham chiếu

Đặc tả nêu mục tiêu tham khảo trên bộ ảnh thuận lợi:

| Mục tiêu | Ngưỡng | Dev | Test | Kết luận |
|---|---:|---:|---:|---|
| Detection Rate | ≥ 90% | 100.00% | 82.61% | Dev đạt, test chưa đạt |
| Segmentation Accuracy | ≥ 85% | 97.67% | 80.98% | Dev đạt, test chưa đạt |
| Exact Plate Accuracy | ≥ 70% | 47.83% | 47.83% | **Chưa đạt ở cả hai split** |

Khoảng cách EPA còn khoảng 22 điểm phần trăm. Nguyên nhân chính:

1. Template từ font không khớp hoàn toàn font ảnh mẫu.
2. Nhiều ký tự bị từ chối bởi ngưỡng margin/score.
3. Phân đoạn yếu trên ảnh ký tự dính và một số ảnh nghiêng mạnh.
4. Tập test có nhiều điều kiện khó hơn "ảnh thuận lợi" mà đặc tả giả định.

Trên 13 ảnh thật thông thường, EPA là 13/13 và trên `8.jpg` là 1/1. Tuy nhiên
đây là tập đã dùng để tinh chỉnh và chưa có box nhãn, nên **không thể coi là
bằng chứng đạt mục tiêu EPA** trên dữ liệu mới.

## 9. Hạn chế

1. **14 ảnh thật không phải holdout độc lập.** Toàn bộ ảnh đã được dùng để
   tinh chỉnh segmentation/recognition; 14/14 chỉ là kết quả hồi quy trên tập
   đã biết.
2. **Chưa có box biển/ký tự cho ảnh thật.** PDR/CSA trên split `user` là proxy
   theo sự hiện diện và số lượng, không phải IoU.
3. **EPA dưới mục tiêu** trên tập tổng hợp: 47.83% ở cả dev và test.
4. **Test tổng hợp không hoàn toàn bị khóa.** Hai ảnh `test_clear_001` và
   `test_no_plate_001` đã được xem trước khi cố định cấu hình. Kết quả test
   không phải đánh giá mù hoàn toàn.
5. **Template không phải crop thật**, dẫn tới lệch miền dữ liệu.
6. **Từ chối bảo thủ** làm giảm success rate dù nhiều chuỗi top-1 đúng.
7. **Phân đoạn ký tự dính** còn yếu, đặc biệt trên test.
8. **Hiệu chỉnh nghiêng mạnh** chưa ổn định; bright-quad đã thử nhưng bị loại.
9. **Trạng thái chưa nhất quán** trong một số ca không có attempt hợp lệ.
10. **Thời gian chưa tối ưu.** Trung bình 1.36–1.50 s/ảnh trên tập tổng hợp;
    `8.jpg` mất khoảng 17.8 s.
11. **UI** mới smoke test tự động, chưa kiểm thử thủ công toàn diện với nhiều
    ảnh thật.
12. **Kích thước mẫu nhỏ.** 52 ảnh tổng hợp và 14 ảnh thật không đủ để ước
    lượng khoảng tin cậy hẹp cho các chỉ số.

## 10. Tái lập kết quả

```powershell
cd vietnamese-license-plate-recognition
python -m pytest -q

python main.py evaluate --split dev `
  --output-csv results\dev_after_final.csv `
  --summary-json results\dev_after_final_summary.json `
  --summary-md results\dev_after_final_summary.md

python main.py evaluate --split test `
  --output-csv results\test_after_final.csv `
  --summary-json results\test_after_final_summary.json `
  --summary-md results\test_after_final_summary.md

python main.py evaluate --split user `
  --labels data\user_labels.csv --samples-dir data\user_images `
  --output-csv results\user_final.csv `
  --summary-json results\user_final_summary.json `
  --summary-md results\user_final_summary.md

python main.py evaluate --split special `
  --labels data\user_labels.csv --samples-dir data\user_images `
  --output-csv results\user_special_final.csv `
  --summary-json results\user_special_final_summary.json `
  --summary-md results\user_special_final_summary.md
```

Có thể chạy nhanh bằng `run_user_eval.bat` (đánh giá ảnh thật) hoặc
`run_user_batch.bat` (nhận dạng hàng loạt ảnh thật).

Sinh lại dữ liệu/template (tùy chọn):

```powershell
python tools\build_templates.py --clean
python tools\build_synthetic_dataset.py --clean
```

Kết quả pytest lần cuối: **78 passed**.

## 11. Kết luận

Hệ thống đã hoàn thành pipeline theo đặc tả, có giao diện desktop, kiểm thử tự
động và báo cáo CSV/JSON/Markdown. Trên 14 ảnh thật do người dùng cung cấp,
hệ thống nhận đúng toàn bộ chuỗi và trả `SUCCESS`; đây là kết quả hồi quy sau
khi tinh chỉnh, không phải độ chính xác tổng quát.

Trên tập tổng hợp, kết quả cuối là: dev PDR 100%, CSA 97.67%, CA 88.00%,
EPA 47.83%; test PDR 82.61%, CSA 80.98%, CA 71.66%, EPA 47.83%. Như vậy
**mục tiêu tham chiếu EPA ≥ 70% vẫn chưa đạt**. Để tiến tới mục tiêu, cần bổ
sung template từ ảnh thật đã xác minh, cải thiện phân đoạn ký tự dính và hiệu
chỉnh nghiêng mạnh, sau đó đánh giá lại trên một bộ test thật độc lập chưa
từng được xem trong quá trình phát triển.

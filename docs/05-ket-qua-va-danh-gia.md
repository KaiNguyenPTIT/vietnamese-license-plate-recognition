# 05 — Kết quả và cách đánh giá

Toàn bộ số liệu dưới đây lấy từ các tệp trong `results/` và `reports/REPORT.md`.
Thời gian phụ thuộc máy; chỉ nên so sánh tương đối giữa các công đoạn.

---

## 1. Bảng tổng hợp

### Tập dev tổng hợp (26 ảnh: 23 có biển, 3 không biển)

| Chỉ số | Giá trị |
|---|---:|
| Plate Detection Rate | 100.00% |
| Detection Precision | 100.00% (TP=23, FP=0, FN=0, TN=3) |
| Character Segmentation Accuracy | 97.67% (IoU hộp ký tự) |
| Character Accuracy | 88.00% |
| Exact Plate Accuracy | 47.83% (11/23) |
| Success Rate | 65.38% (17/26) |
| Thời gian trung bình | 1498.09 ms |

### Tập test tổng hợp (26 ảnh: 23 có biển, 3 không biển)

| Chỉ số | Giá trị |
|---|---:|
| Plate Detection Rate | 82.61% |
| Detection Precision | 100.00% (TP=19, FP=0, FN=4, TN=3) |
| Character Segmentation Accuracy | 80.98% |
| Character Accuracy | 71.66% |
| Exact Plate Accuracy | 47.83% (11/23) |
| Success Rate | 50.00% (13/26) |
| Thời gian trung bình | 1358.76 ms |

### Ảnh thật do người dùng cung cấp

| Tập | Kết quả | Trạng thái | Thời gian |
|---|---:|---|---:|
| `user` (13 ảnh) | 13/13 chuỗi chính xác | SUCCESS 13 | 1863.94 ms |
| `special` (`8.jpg`) | 1/1 chuỗi chính xác | SUCCESS 1 | 17.8 s |

**Cảnh báo:** 14 ảnh này đã được dùng để tinh chỉnh tham số. Đây là **kiểm tra
hồi quy trên tập đã biết**, không phải độ chính xác trên holdout độc lập.

---

## 2. Cách đọc từng chỉ số

| Chỉ số | Công thức / cách tính | Đọc thế nào |
|---|---|---|
| PDR | số ảnh phát hiện đúng (IoU ≥ 0.5) / số ảnh có biển | Cao = tìm được vùng biển |
| Precision | TP / (TP + FP) | Cao = ít báo nhầm ảnh không biển |
| Recall | TP / (TP + FN) | Cao = ít bỏ sót biển |
| CSA | trung bình tỷ lệ hộp ký tự ghép đúng IoU ≥ 0.5 | Cao = tách đúng vị trí ký tự |
| CA | ký tự khớp / độ dài căn chỉnh | Cao = đọc đúng nhiều ký tự |
| EPA | chuỗi trùng khớp hoàn toàn / số ảnh có biển | Cao = đúng cả biển |
| Success Rate | số `SUCCESS` / tổng ảnh | Cao = ít bị từ chối |

**Vì sao CA cao hơn EPA nhiều?** CA cho điểm từng ký tự, sai một ký tự vẫn được
tính; EPA yêu cầu đúng toàn bộ chuỗi. Với biển 8–9 ký tự, chỉ cần sai một ký tự
là EPA = 0 cho ảnh đó.

**Vì sao EPA 47.83% nhưng CA 88%?** Hệ thống đọc đúng phần lớn ký tự nhưng còn
nhầm các cặp giống nhau (`S/5`, `B/8`, `2/Z`, `1/T`, `0/D`) và đôi khi thiếu
hoặc thừa một ký tự do phân đoạn.

---

## 3. Kết quả theo điều kiện

| Điều kiện | Dev | Test | Nhận xét |
|---|---|---|---|
| Ảnh rõ | 4/5 | — | Tốt |
| Biển hai dòng | 4/4 | — | Tốt khi tách được dòng |
| Thiếu sáng | — | 3/3 | Tốt |
| Độ phân giải thấp | — | 1/1 | Tốt |
| Nghiêng | — | 1/4 | Yếu khi nghiêng mạnh |
| Ký tự dính | 0/3 | 0/3 | **Điểm yếu nhất** |

**Ký tự dính** làm projection dọc không tạo đủ điểm thắt, dẫn đến thiếu hộp
hoặc gộp hộp; `test_touching_001/002/003` chỉ còn 1–5 box. **Ảnh nghiêng mạnh**
thường không có ứng viên đạt IoU ≥ 0.5, hoặc tứ giác bao vùng nền.

---

## 4. Phân tích lỗi

### 4.1. Lỗi phân đoạn

- Thiếu hộp ký tự ở ảnh dính, ảnh nghiêng, ảnh có ốc vít/gạch phân cách.
- Tách thừa mảnh ở mép biển, tạo ký tự rác; quy tắc “10 ký tự chỉ khi hai dòng
  cân bằng” giảm lỗi này nhưng không loại bỏ hoàn toàn.
- Ảnh không biển đôi khi vẫn tạo ứng viên và trả `LOW_CONFIDENCE` thay vì
  `PLATE_NOT_FOUND` (ví dụ `test_no_plate_003`).

### 4.2. Lỗi nhận dạng

Các cặp nhầm lẫn được khẳng định trong báo cáo: `S/5`, `B/8`, `2/Z`, `1/T`,
`0/D`. Nguyên nhân: template render từ font Windows, còn ảnh tổng hợp dùng font
khác (Calibri, Verdana, Times New Roman, Trebuchet); độ dày nét và hình dáng
chữ khác nhau.

### 4.3. Lỗi hiệu chỉnh

- Tứ giác chọn sai khi biển nghiêng mạnh hoặc bị cắt góc.
- Fallback bounding box giữ nguyên độ nghiêng, làm phân đoạn kém.
- Thực nghiệm “bright-quad” đã bị loại vì làm giảm kết quả tổng thể.

### 4.4. Lỗi từ chối bảo thủ

Nhiều ảnh có top-1 đúng vẫn bị `LOW_CONFIDENCE` vì điểm dưới 0.60 hoặc margin
nhỏ. Đây là lựa chọn có chủ ý: ưu tiên không đoán bừa.

---

## 5. Thời gian

| Công đoạn | Dev (ms) | Test (ms) | User (ms) |
|---|---:|---:|---:|
| Tiền xử lý | 19.2 | 19.3 | 8.5 |
| Phát hiện | 491.7 | 496.3 | 623.3 |
| Hiệu chỉnh | 4.3 | 4.5 | 9.5 |
| Phân đoạn | 174.2 | 121.0 | 218.0 |
| Nhận dạng | 904.5 | 874.2 | 980.5 |
| Hậu xử lý | 0.2 | 0.2 | 0.2 |
| **Tổng** | **1498.1** | **1358.8** | **1863.9** |

Hai công đoạn tốn thời gian nhất là **nhận dạng** (so khớp template) và **phát
hiện** (nhiều bản đồ morphology + contour). `8.jpg` mất 17.8 s chủ yếu ở phát
hiện do ảnh lớn và nhiều ứng viên.

---

## 6. So với mục tiêu của đặc tả

| Mục tiêu | Ngưỡng | Dev | Test | Kết luận |
|---|---|---:|---:|---|
| PDR | ≥ 90% | 100% | 82.61% | Dev đạt, test chưa |
| CSA | ≥ 85% | 97.67% | 80.98% | Dev đạt, test chưa |
| EPA | ≥ 70% | 47.83% | 47.83% | **Chưa đạt** |

Báo cáo không tô hồng: EPA chưa đạt và nguyên nhân chính là template từ font
khác font ảnh, cùng điểm yếu phân đoạn ký tự dính/nghiêng.

---

## 7. Hạn chế phải nêu trung thực

1. 14 ảnh thật **không phải holdout độc lập**.
2. Nhãn ảnh thật **chưa có box biển/ký tự**, nên PDR/CSA trên `user` là proxy.
3. **EPA < 70%** trên tập tổng hợp.
4. Template **render từ font**, không phải crop ký tự thật.
5. Tập test tổng hợp **không khóa hoàn toàn**: hai ảnh đã được xem để chẩn đoán
   trước khi cố định cấu hình.
6. Hệ thống **từ chối bảo thủ**, nhiều kết quả đúng vẫn bị `LOW_CONFIDENCE`.
7. Phân đoạn **ký tự dính** và hiệu chỉnh **nghiêng mạnh** còn yếu.
8. Giao diện mới **smoke test**, chưa kiểm thử thủ công toàn bộ luồng.
9. Mẫu nhỏ (13 ảnh thật, 52 ảnh tổng hợp) nên khoảng tin cậy rộng.

---

## 8. Cách trình bày khi bảo vệ

Nên nói theo thứ tự:

1. **Kết quả đạt:** pipeline chạy end-to-end, 78 test pass, 13/13 ảnh thật
   (kiểm tra hồi quy), dev PDR/CSA cao.
2. **Kết quả chưa đạt:** EPA 47.83% trên tập tổng hợp, test PDR 82.61%.
3. **Nguyên nhân:** template khác font, ký tự dính, nghiêng mạnh, từ chối bảo
   thủ.
4. **Giới hạn phương pháp:** không học máy nên khó tổng quát; đổi lại minh
   bạch và giải thích được.
5. **Hướng phát triển:** bổ sung crop ký tự thật, cải thiện tách ký tự dính,
   khóa tập test trước khi tinh chỉnh.

Tránh nói “hệ thống chính xác 100%” hoặc “sẵn sàng triển khai”. Câu đúng:
“Trên 13 ảnh thật đã dùng để tinh chỉnh, hệ thống đọc đúng 13/13; đây là kiểm
tra hồi quy, không phải đánh giá độc lập.”

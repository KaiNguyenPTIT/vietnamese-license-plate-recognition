# Dữ liệu

Thư mục này chứa toàn bộ dữ liệu cần để chạy và đánh giá hệ thống. Tất cả tệp
ở đây đều được commit vào repo để người clone về chạy được ngay, không phải
sinh lại.

## Cấu trúc

| Đường dẫn | Nội dung | Số lượng |
|---|---|---:|
| `templates/<nhãn>/` | Ảnh template ký tự đã chuẩn hóa 32×48, mỗi nhãn một thư mục | 1.620 PNG |
| `templates/meta.json` | Metadata bộ template: font, biến thể, số lượng | 1 |
| `templates/README.md` | Giải thích cách sinh template | 1 |
| `samples/` | 52 ảnh tổng hợp (dev 26 + test 26) | 52 JPG |
| `labels.csv` | Nhãn box biển và box từng ký tự cho 52 ảnh tổng hợp | 53 dòng |
| `synthetic_manifest.json` | Thông tin sinh ảnh: font, chuỗi, điều kiện, seed | 1 |
| `user_images/` | 14 ảnh biển số thật do nhóm thu thập | 14 ảnh |
| `user_labels.csv` | Nhãn chuỗi cho 14 ảnh thật (chưa có box) | 15 dòng |

## Ba nguồn dữ liệu

**1. Template — render từ font, không phải crop thật.**
36 nhãn `0–9`, `A–Z` × 15 font Windows × 3 biến thể (`normal`, `thick`, `thin`)
= 1.620 ảnh. Đây là điểm yếu đã biết: font template khác font trên biển thật,
nên hệ thống nhầm các cặp giống nhau như `S/5`, `B/8`, `2/Z`, `1/T`, `0/D`.

**2. Ảnh tổng hợp — có nhãn đầy đủ.**
Sinh bằng `tools/build_synthetic_dataset.py`, có box biển và box ký tự nên đo
được PDR và CSA theo IoU. Generator cố ý dùng font khác font template để tránh
việc template "học thuộc" đúng font kiểm thử.

**3. Ảnh thật — chỉ có nhãn chuỗi.**
14 ảnh chụp thực tế, nhãn do nhóm đọc và xác minh thủ công. Nhãn **chưa có box
biển và box ký tự**, nên PDR/CSA trên tập này chỉ là proxy theo sự hiện diện và
số lượng. Toàn bộ 14 ảnh đã được dùng để tinh chỉnh tham số, vì vậy kết quả
trên tập này là kiểm tra hồi quy, không phải holdout độc lập.

## Sinh lại dữ liệu

```powershell
# Template (cần Windows có font Arial, Times New Roman, ...)
python tools\build_templates.py --clean

# 52 ảnh tổng hợp + labels.csv + synthetic_manifest.json
python tools\build_synthetic_dataset.py --clean
```

Ảnh thật trong `user_images/` là dữ liệu thu thập, không sinh lại được; muốn
đánh giá trên ảnh mới thì thêm ảnh vào thư mục này và bổ sung dòng tương ứng
trong `user_labels.csv`.

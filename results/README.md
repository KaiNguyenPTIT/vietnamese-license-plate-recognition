# Kết quả đánh giá

Mọi tệp trong thư mục này do chương trình sinh ra bằng
`python main.py evaluate ...`, không có số liệu nhập tay. Mỗi lần đo tạo ra ba
tệp cùng tên gốc:

- `*.csv` — kết quả từng ảnh, mở được bằng Excel.
- `*_summary.json` — tổng hợp có cấu trúc, dùng để sinh báo cáo.
- `*_summary.md` — bản đọc nhanh, chèn trực tiếp vào tài liệu.

## Kết quả cuối cùng (dùng trong báo cáo)

| Tập | Tệp | PDR | CSA | CA | EPA | Thời gian |
|---|---|---:|---:|---:|---:|---:|
| dev (26 ảnh) | `dev_after_final.*` | 100.00% | 97.67% | 88.00% | 47.83% (11/23) | 1498.09 ms |
| test (26 ảnh) | `test_after_final.*` | 82.61% | 80.98% | 71.66% | 47.83% (11/23) | 1358.76 ms |
| user (13 ảnh thật) | `user_final.*` | 100.00% | 100.00% | 100.00% | 100.00% (13/13) | 1863.94 ms |
| special (1 ảnh) | `user_special_final.*` | 100.00% | 100.00% | 100.00% | 100.00% (1/1) | 17822.84 ms |

EPA tính trên **23 ảnh có biển** của mỗi split tổng hợp, không phải 26.
PDR/CSA trên tập `user` là proxy theo sự hiện diện và số lượng, vì nhãn ảnh
thật chưa có box. Thời gian đo trên máy phát triển, dao động theo tải máy.

## Các lần đo trước (giữ lại để thấy quá trình tinh chỉnh)

Nhóm giữ nguyên các lần đo cũ thay vì ghi đè, để thấy rõ thay đổi nào có tác
dụng và thay đổi nào không.

| Tệp | Thời điểm | Kết quả chính |
|---|---|---|
| `user_baseline.*` | Trước khi sửa phân đoạn | PDR 76.92%, CSA 65.60%, CA 43.24%, EPA 7.69% |
| `user_after_seg.*` | Sau khi sửa phân đoạn | PDR 100%, CSA 97.41%, CA 83.33%, EPA 30.77% |
| `dev_summary.*`, `dev_evaluation.csv` | Baseline trên dev | CSA 97.67%, CA 82.86%, EPA 34.78% |
| `test_summary.*`, `test_evaluation.csv` | Baseline trên test | PDR 86.96%, CA 65.24%, EPA 30.43% |
| `evaluation_ui.*` | Chạy từ cửa sổ đánh giá trong UI, gộp 52 ảnh | PDR 91.30%, CA 79.56%, EPA 47.83% (22/46) |

Chuỗi `user_baseline` → `user_after_seg` → `user_final` cho thấy phần lớn cải
thiện đến từ phân đoạn ký tự và hậu xử lý, không phải từ phát hiện biển.

## Tệp chẩn đoán

`diag_all_default.json` là kết quả chạy `tools/diagnose_detection.py` trên 14
ảnh thật với cấu hình mặc định, dùng để tìm ảnh nào bị cắt lệch hoặc chọn sai
ứng viên. Đây là công cụ phát triển, không phải kết quả báo cáo.

## Tái lập

```powershell
python main.py evaluate --split dev  --output-csv results\dev_after_final.csv  --summary-json results\dev_after_final_summary.json  --summary-md results\dev_after_final_summary.md
python main.py evaluate --split test --output-csv results\test_after_final.csv --summary-json results\test_after_final_summary.json --summary-md results\test_after_final_summary.md
python main.py evaluate --split user --labels data\user_labels.csv --samples-dir data\user_images --output-csv results\user_final.csv --summary-json results\user_final_summary.json --summary-md results\user_final_summary.md
```

Lưu ý: chạy lại sẽ ghi đè tệp cùng tên. Nếu muốn giữ lịch sử, đặt tên khác
trước khi chạy.

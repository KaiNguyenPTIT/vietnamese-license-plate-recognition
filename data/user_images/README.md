# Ảnh do người dùng cung cấp

Thả ảnh cần kiểm tra vào thư mục này.

## Định dạng
- Chấp nhận: `.jpg`, `.jpeg`, `.png`, `.webp`.
- Nên giữ tên file ngắn, không dấu, không khoảng trắng.
- Ảnh càng rõ và còn nguyên vùng biển càng tốt; không cần cắt sẵn biển.

## Phân loại biển
- Biển **một dòng**: ghi `one_line`.
- Biển **hai dòng**: ghi `two_line`.
- Ảnh **không có biển**: ghi `none`.

## Ghi nhãn
Mở `data/user_labels.csv` và thêm một dòng cho mỗi ảnh:

```csv
image_name,ground_truth,plate_type,condition,notes
anh_01.jpg,51A12345,one_line,real,Anh ro
anh_02.jpg,29X1234,two_line,real,Anh hai dong
anh_03.jpg,,none,real,Khong co bien
```

- `image_name`: tên file ảnh, phải khớp chính xác.
- `ground_truth`: chuỗi biển số viết liền, chỉ gồm chữ và số.
- `plate_type`: `one_line`, `two_line` hoặc `none`.
- `condition`: có thể để `real` hoặc mô tả riêng (mờ, nghiêng, thiếu sáng...).
- `notes`: ghi chú tự do.

Sau khi thả ảnh và điền nhãn, chạy:

```powershell
.\run_user_eval.bat
```

Nếu chỉ muốn xem dự đoán mà chưa có nhãn:

```powershell
python main.py batch data\user_images --output-csv results\user_batch.csv
```

Kết quả đánh giá:
- `results/user_evaluation.csv`
- `results/user_summary.json`
- `results/user_summary.md`

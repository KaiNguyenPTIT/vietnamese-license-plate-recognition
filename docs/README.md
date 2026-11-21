# Tài liệu học tập — Nhận dạng biển số xe Việt Nam

Bộ tài liệu này phục vụ ôn tập, thuyết trình và trả lời câu hỏi bảo vệ đồ án.
Nội dung bám sát mã nguồn trong repo; không mô tả tính năng không tồn tại.

## Đọc theo thứ tự

| # | Tài liệu | Nội dung | Thời gian |
|---|---|---|---|
| 1 | [01-kien-truc-va-pipeline.md](01-kien-truc-va-pipeline.md) | Kiến trúc, luồng dữ liệu, dataclass, mã trạng thái | 20 phút |
| 2 | [02-cac-cong-doan.md](02-cac-cong-doan.md) | Chi tiết 8 công đoạn: đầu vào/ra, hàm chính, tham số | 45 phút |
| 3 | [03-thuat-toan-tom-tat.md](03-thuat-toan-tom-tat.md) | Công thức và cheat sheet thuật toán | 30 phút |
| 4 | [04-huong-dan-chay-va-kiem-thu.md](04-huong-dan-chay-va-kiem-thu.md) | Cài đặt, CLI, UI, pytest, xử lý lỗi | 20 phút |
| 5 | [05-ket-qua-va-danh-gia.md](05-ket-qua-va-danh-gia.md) | Số liệu, cách đọc chỉ số, hạn chế | 25 phút |
| 6 | [06-cau-hoi-on-tap.md](06-cau-hoi-on-tap.md) | Câu hỏi – đáp án thường gặp khi bảo vệ | 40 phút |
| 7 | [PHAN_CONG.md](PHAN_CONG.md) | Thành viên, phân công, tiến độ | 10 phút |

## Tài liệu ôn riêng từng thành viên

Mỗi thành viên có một bản riêng, tập trung đúng phần mình phụ trách và các câu
hỏi thầy thường hỏi:

| Thành viên | Tài liệu | Nội dung chính |
|---|---|---|
| Nguyễn Đình Khải (B23DCCN420) | [on-tap/nguyen-dinh-khai.md](on-tap/nguyen-dinh-khai.md) | Pipeline, phát hiện biển, hiệu chỉnh, cấu hình, CLI |
| Nguyễn Trung Tường (B23DCCN909) | [on-tap/nguyen-trung-tuong.md](on-tap/nguyen-trung-tuong.md) | Phân đoạn ký tự, Template Matching, hậu xử lý |
| Bùi Văn Đạt (B23DCCN126) | [on-tap/bui-van-dat.md](on-tap/bui-van-dat.md) | Tiền xử lý, UI, đánh giá, kiểm thử, dữ liệu, báo cáo |

Mỗi bản gồm: phần phụ trách, câu chuyện 60 giây, sơ đồ, kiến thức bắt buộc,
câu hỏi – đáp án, câu hỏi nối module, demo checklist và bẫy cần tránh.

## Lộ trình ôn 7 ngày

| Ngày | Việc cần làm | Kết quả |
|---|---|---|
| 1 | Đọc `01`, chạy `python main.py info` và `python main.py recognize` một ảnh mẫu | Nắm luồng tổng quát, thấy kết quả thật |
| 2 | Đọc `02` mục 1–4, mở `src/preprocessing.py`, `src/plate_detection.py` | Giải thích được tiền xử lý và phát hiện biển |
| 3 | Đọc `02` mục 5–8, mở `src/character_segmentation.py`, `src/character_recognition.py` | Giải thích được phân đoạn và template matching |
| 4 | Đọc `03`, tự viết lại công thức Otsu, IoU, Template Matching | Trả lời được câu hỏi công thức |
| 5 | Đọc `05`, mở `reports/REPORT.md`, đối chiếu CSV trong `results/` | Biết số nào đạt, số nào chưa, vì sao |
| 6 | Đọc `06`, trả lời thành tiếng, nhờ bạn hỏi chéo | Tự tin phần vấn đáp |
| 7 | Chạy lại `python -m pytest -q`, chạy `python main.py ui`, tổng duyệt | Demo trơn tru |

## Lệnh nhanh

```powershell
python -m pip install -r requirements.txt
python main.py info
python main.py recognize data\samples\dev_clear_001.jpg
python main.py ui
python -m pytest -q
```

## Cấu trúc repo

```text
.
├── main.py                 # CLI: ui | recognize | evaluate | batch | info
├── config.yaml             # toàn bộ tham số
├── src/                    # 10 module xử lý
├── ui/app.py               # giao diện Tkinter
├── tests/                  # 78 bài kiểm thử pytest
├── tools/                  # sinh template, sinh dữ liệu, chẩn đoán, sinh báo cáo
├── data/                   # template, ảnh mẫu, nhãn
├── results/                # CSV/JSON/Markdown kết quả đánh giá
├── reports/                # báo cáo DOCX/PDF/Markdown và hình
└── docs/                   # tài liệu học tập (thư mục này)
```

## Nguyên tắc cần nhớ khi trình bày

1. Hệ thống chỉ dùng **xử lý ảnh truyền thống + Template Matching**, không học
   máy, không OCR học sẵn, không API ngoài.
2. Kết quả **13/13 ảnh thật** là kiểm tra hồi quy trên tập đã dùng để tinh
   chỉnh, **không phải holdout độc lập**.
3. Chỉ số trên ảnh thật là **proxy** vì nhãn chưa có hộp bao biển/ký tự.
4. Hệ thống ưu tiên **từ chối** (`LOW_CONFIDENCE`, giữ `?`) thay vì đoán bừa.
5. Điểm yếu đã biết: ký tự dính, ảnh nghiêng mạnh, khác font template.

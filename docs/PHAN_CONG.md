# Phân công công việc nhóm

## 1. Thành viên

| STT | Họ và tên | MSSV | Vai trò | Tỷ lệ đóng góp |
|---:|---|---|---|---:|
| 1 | Nguyễn Đình Khải | B23DCCN420 | Nhóm trưởng — kiến trúc, phát hiện biển, hiệu chỉnh | 35% |
| 2 | Nguyễn Trung Tường | B23DCCN909 | Phân đoạn ký tự, nhận dạng template, hậu xử lý | 33% |
| 3 | Bùi Văn Đạt | B23DCCN126 | Tiền xử lý, giao diện, đánh giá, kiểm thử, báo cáo | 32% |

Tỷ lệ trên phản ánh khối lượng mã nguồn, thời gian tích hợp và trách nhiệm
báo cáo. Nếu giảng viên yêu cầu chia đều tuyệt đối, có thể ghi 35/33/32 hoặc
điều chỉnh thành 34/33/33 sau khi đối chiếu nhật ký họp nhóm.

**Tài liệu ôn riêng từng người:**

- Nguyễn Đình Khải: [`on-tap/nguyen-dinh-khai.md`](on-tap/nguyen-dinh-khai.md)
- Nguyễn Trung Tường: [`on-tap/nguyen-trung-tuong.md`](on-tap/nguyen-trung-tuong.md)
- Bùi Văn Đạt: [`on-tap/bui-van-dat.md`](on-tap/bui-van-dat.md)

## 2. Phân công theo module

### Nguyễn Đình Khải — Nhóm trưởng (35%)

**Phụ trách chính:**

| Tệp / hạng mục | Nội dung | Sản phẩm |
|---|---|---|
| `src/pipeline.py` | Thiết kế luồng 8 công đoạn, vòng lặp ứng viên, `ranking_key`, lưu debug | Pipeline end-to-end chạy được |
| `src/plate_detection.py` | Sinh bản đồ morphology, contour, chấm điểm, gộp trùng, gộp hai dòng | Bộ phát hiện biển |
| `src/plate_rectification.py` | Crop padding, tìm tứ giác, warp phối cảnh, deskew, fallback bbox | Ảnh biển phẳng |
| `src/config.py` + `config.yaml` | Dataclass cấu hình, nạp/ghi YAML, override, kiểm tra hợp lệ | Cấu hình tập trung |
| `main.py` | CLI `ui/recognize/evaluate/batch/info`, mã thoát | Công cụ dòng lệnh |
| Tích hợp | Ghép module, xử lý lỗi, thống nhất dataclass | Bản chạy ổn định |

**Trách nhiệm nhóm trưởng:** chốt phạm vi, phân công, theo dõi tiến độ, review
pull request, chịu trách nhiệm bản nộp cuối.

### Nguyễn Trung Tường — Phân đoạn và nhận dạng (33%)

**Phụ trách chính:**

| Tệp / hạng mục | Nội dung | Sản phẩm |
|---|---|---|
| `src/character_segmentation.py` | Nhị phân tự động, tách dòng, tách ký tự, tách hộp rộng, lọc và sắp thứ tự | Bộ phân đoạn ký tự |
| `src/character_recognition.py` | Chuẩn hóa 32×48, nạp template, hai tầng coarse/full, hole prior, chữ 4 hở đỉnh | Bộ nhận dạng template |
| `src/postprocessing.py` | Ghép chuỗi, validate định dạng, rerank theo vị trí, quyết định trạng thái | Chuỗi biển và trạng thái |
| `tools/build_templates.py` | Sinh template từ font Windows, biến thể normal/thick/thin, khử trùng | 1.620 template thô |
| Tinh chỉnh | Tham số phân đoạn/nhận dạng trên tập dev | Cấu hình cuối |

**Trách nhiệm:** giải thích được vì sao một ký tự bị từ chối, vì sao chọn nhãn
này thay vì nhãn khác; ghi lại các thực nghiệm bị loại.

### Bùi Văn Đạt — Tiền xử lý, UI, đánh giá, kiểm thử (32%)

**Phụ trách chính:**

| Tệp / hạng mục | Nội dung | Sản phẩm |
|---|---|---|
| `src/preprocessing.py` | Đọc ảnh Unicode, resize, gray, blur, CLAHE, Canny, Otsu/adaptive | Ảnh trung gian ổn định |
| `src/io_utils.py` | Đọc/ghi ảnh, IoU, hình học, liệt kê ảnh | Hàm tiện ích |
| `ui/app.py` | Giao diện Tkinter: chọn ảnh, xem ảnh, xuất CSV, cửa sổ đánh giá | Ứng dụng desktop |
| `src/evaluation.py` | PDR, Precision/Recall, CSA, CA, EPA, Levenshtein, xuất CSV/JSON/MD | Báo cáo đánh giá |
| `tools/build_synthetic_dataset.py` | Sinh 52 ảnh tổng hợp kèm nhãn box biển/ký tự | Bộ dữ liệu dev/test |
| `tests/` | 78 bài pytest cho 10 module và pipeline | Bộ kiểm thử tự động |
| `reports/` | Viết báo cáo, hình, bảng kết quả, rà soát số liệu | Báo cáo DOCX/PDF |

**Trách nhiệm:** bảo đảm số liệu trong báo cáo khớp file CSV/JSON; chạy lại
đánh giá trước khi nộp; kiểm tra giao diện trên máy sạch.

## 3. Phân công theo tuần

| Tuần | Khải | Tường | Đạt | Mốc |
|---|---|---|---|---|
| 1 | Khảo sát bài toán, chốt pipeline, tạo skeleton | Khảo sát Template Matching, thử nghiệm font | Khảo sát bộ dữ liệu, đặc tả yêu cầu | Đặc tả + kiến trúc |
| 2 | Tiền xử lý + phát hiện biển bản đầu | Sinh template, thử nhận dạng ký tự | Dataset tổng hợp bản đầu, đo baseline | Chạy được detect → template |
| 3 | Hiệu chỉnh phối cảnh, gộp ứng viên | Phân đoạn một dòng/hai dòng | Giao diện Tkinter bản đầu | Pipeline end-to-end |
| 4 | Tích hợp, xử lý lỗi, CLI | Nhận dạng hai tầng, hole prior | Đánh giá dev, viết test | 78 test pass |
| 5 | Tinh chỉnh detection/rectification | Tinh chỉnh segmentation/recognition | Đo test, phân tích lỗi, bảng kết quả | Kết quả cuối |
| 6 | Rà soát repo, tài liệu, demo | Rà soát kết quả, trả lời phản biện | Hoàn thiện báo cáo, slide | Bản nộp |

## 4. Cách phối hợp

- **Họp nhóm:** 2 buổi/tuần (đầu tuần chốt việc, cuối tuần review).
- **Review chéo:** mỗi module do một người viết, một người khác đọc và chạy thử.
- **Quy ước dữ liệu:** không sửa `results/*.csv` bằng tay; mọi số liệu phải
  sinh lại được bằng lệnh trong `docs/04-huong-dan-chay-va-kiem-thu.md`.
- **Quy ước cấu hình:** thay đổi tham số phải ghi lý do và chạy lại dev trước
  khi chạm test.
- **Quy ước báo cáo:** mọi bảng kết quả ghi rõ mẫu số (23 ảnh có biển hay 26
  ảnh), ghi rõ tập đã dùng để tinh chỉnh.

## 5. Minh chứng đóng góp

| Thành viên | Minh chứng chính |
|---|---|
| Nguyễn Đình Khải | `src/pipeline.py`, `src/plate_detection.py`, `src/plate_rectification.py`, `src/config.py`, `main.py` |
| Nguyễn Trung Tường | `src/character_segmentation.py`, `src/character_recognition.py`, `src/postprocessing.py`, `tools/build_templates.py` |
| Bùi Văn Đạt | `src/preprocessing.py`, `src/io_utils.py`, `src/evaluation.py`, `ui/app.py`, `tests/`, `tools/build_synthetic_dataset.py`, `reports/` |

Khi bảo vệ, mỗi thành viên nên trình bày được:

1. Module mình phụ trách làm gì, đầu vào/ra.
2. Một tham số quan trọng và lý do chọn.
3. Một lỗi hoặc thực nghiệm thất bại đã gặp và cách xử lý.
4. Một con số kết quả liên quan đến module mình.

## 6. Ghi chú

Bảng phân công này dựa trên cấu trúc module và khối lượng mã nguồn thực tế của
repo. Nếu nhóm có nhật ký họp hoặc cách chia khác, hãy cập nhật lại bảng và tỷ
lệ phần trăm cho khớp trước khi nộp; không nên giữ số liệu không đúng với thực
tế.

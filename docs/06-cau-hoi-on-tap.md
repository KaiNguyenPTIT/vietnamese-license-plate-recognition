# 06 — Câu hỏi ôn tập và gợi ý trả lời

## A. Tổng quan

**1. Vì sao chọn xử lý ảnh truyền thống thay vì học sâu?**
Đề tài muốn thể hiện rõ vai trò từng bước của một pipeline ANPR, không cần dữ
liệu huấn luyện lớn hay GPU, và mọi quyết định đều giải thích được. Đổi lại độ
chính xác thấp hơn học sâu trên ảnh thật đa dạng; báo cáo nêu rõ giới hạn này.

**2. Hệ thống có dùng YOLO, KNN, SVM, OCR học sẵn hoặc API ngoài không?**
Không. Chỉ dùng OpenCV/NumPy: Canny, morphology, contour, warp phối cảnh,
projection, Template Matching.

**3. Pipeline gồm những công đoạn nào?**
Tiền xử lý → phát hiện biển → hiệu chỉnh → phân đoạn ký tự → nhận dạng template
→ hậu xử lý → đánh giá (tùy chọn). Điều phối nằm trong `src/pipeline.py`.

**4. Vì sao phải tách thành nhiều module?**
Mỗi module có đầu vào/ra rõ ràng, kiểm thử riêng được, dễ thay thế và dễ chỉ ra
lỗi nằm ở công đoạn nào.

**5. Đầu ra của hệ thống là gì?**
`RecognitionResult`: chuỗi biển, hộp bao, điểm từng ký tự, trạng thái, thời
gian, cảnh báo/lỗi và ảnh trung gian nếu bật debug.

## B. Tiền xử lý và phát hiện

**6. Vì sao chuyển ảnh xám?**
Giảm dữ liệu từ 3 kênh xuống 1, đủ cho cạnh/nhị phân; màu không cần thiết cho
việc tách ký tự đen–trắng.

**7. Gaussian khác median ở đâu?**
Gaussian làm mượt đều, giảm nhiễu cao tần; median thay bằng trung vị, tốt hơn
với nhiễu muối tiêu và ít làm mờ biên.

**8. Canny gồm những bước nào?**
Làm mờ → gradient Sobel → non-maximum suppression → double threshold →
hysteresis. Ngưỡng mặc định 60/180.

**9. Otsu hoạt động thế nào?**
Chọn ngưỡng `t` tối đa hóa phương sai giữa hai lớp:
`σ²_b(t) = ω0·ω1·(μ0 − μ1)²`. Phù hợp histogram hai đỉnh.

**10. Vì sao dùng morphology closing?**
Closing (giãn rồi co) nối nét đứt và lấp lỗ nhỏ, giúp vùng biển thành một khối
liền để tìm contour.

**11. Vì sao dùng nhiều kernel?**
Biển một dòng cần kernel rộng 17×3; biển hai dòng hoặc nét đứt cần 25×5, 15×7.
Nhiều bản đồ giúp tăng recall, sau đó lọc và gộp trùng.

**12. Ứng viên biển được chấm điểm ra sao?**
Theo tỷ lệ, diện tích, mật độ cạnh, độ đầy và `text_likeness`:
`score = 0.8·spec + 0.2·text`. Điều kiện qua: `score ≥ 0.45` và
`text_likeness ≥ 0.15`.

**13. `text_likeness` có phải nhận dạng ký tự không?**
Không. Nó đếm các thành phần liên thông có kích thước giống ký tự để loại vùng
nền/đèn xe. Đây là bằng chứng hình học, không phải OCR.

**14. Vì sao thử nhiều ứng viên thay vì chỉ ứng viên điểm cao nhất?**
Ứng viên điểm cao có thể là cả cụm đèn hoặc thân xe. Thử tối đa 8 ứng viên và
chọn theo chất lượng nhận dạng giúp tăng độ chính xác.

**15. Hai ứng viên trùng nhau xử lý thế nào?**
Gộp nếu IoU ≥ 0.45 hoặc một hộp nằm trọn trong hộp kia > 85%; giữ hộp điểm cao
hơn, ưu tiên hộp “đặc” hơn.

## C. Hiệu chỉnh và phân đoạn

**16. Vì sao cần hiệu chỉnh phối cảnh?**
Biển chụp nghiêng bị méo; warp về hình chữ nhật giúp ký tự thẳng hàng, projection
tách dòng/ký tự chính xác hơn.

**17. Nếu không tìm được tứ giác thì sao?**
Fallback `minAreaRect` để deskew nếu góc 2.5°–18°; nếu vẫn không được thì dùng
bounding box. Mỗi phương án được ghi vào `method` để truy vết.

**18. Vì sao padding dọc tính theo chiều rộng?**
Biển một dòng rất rộng nhưng thấp; khi nghiêng, góc biển có thể vượt khỏi
bounding box theo trục y. Pad theo chiều rộng bù được trường hợp này.

**19. Tách dòng bằng cách nào?**
Projection ngang `p(y) = Σ_x B(x,y)`; dải có `p(y) > 0.02·max` là một dòng.
Nếu projection gộp hai dòng, dùng fallback connected components.

**20. Tách ký tự bằng cách nào?**
Trong mỗi dòng, đóng nhỏ 2×2, tìm contour, lọc theo chiều cao/chiều rộng/diện
tích/độ đầy, gộp mảnh rời, khử trùng, sắp theo x.

**21. Ký tự dính xử lý ra sao?**
Nếu hộp rộng gần gấp đôi, tìm điểm thắt trong projection dọc gần giữa hộp; nếu
hai phần đủ lớn thì tách. Đây là điểm yếu nhất, đặc biệt khi valley nông.

**22. Vì sao chuẩn hóa về 32×48?**
Đủ nhỏ để so khớp nhanh, đủ lớn để giữ cấu trúc nét; tỷ lệ 2:3 gần với ký tự
biển. Kéo giãn ink box giúp giảm lệch do font và độ dày nét.

**23. Vì sao biển 10 ký tự chỉ chấp nhận khi hai dòng cân bằng?**
Tránh ghép mảnh nhiễu ở mép biển thành chuỗi giả. Ví dụ `8.jpg` có 5/5 nên được
chấp nhận.

## D. Nhận dạng và hậu xử lý

**24. Template Matching hoạt động thế nào?**
Trượt template trên ảnh, tính tương quan chuẩn hóa:
`R = ΣT'I' / √(ΣT'²·ΣI'²)`. `TM_CCOEFF_NORMED` cho điểm càng cao càng giống.

**25. Vì sao dùng `TM_CCOEFF_NORMED`?**
Bất biến với thay đổi độ sáng/tương phản tuyến tính và cho điểm chuẩn hóa, dễ
đặt ngưỡng. `TM_SQDIFF_NORMED` cũng có thể dùng nhưng phải đảo điểm.

**26. Hai tầng nhận dạng để làm gì?**
Tầng coarse so 6 template/nhãn để giữ 6 nhãn tốt nhất; tầng đầy đủ chỉ chấm các
nhãn đó. Giảm chi phí mà gần như không mất độ chính xác.

**27. Hole prior là gì?**
Đếm số lỗ bên trong ký tự; nếu khác số lỗ phổ biến của nhãn template thì trừ
0.20 điểm. Giúp phân biệt `6/B`, `0/D`, `8/B`. Không tạo ký tự mới.

**28. Vì sao thêm biến thể chữ 4 hở đỉnh?**
Font biển thật có kiểu `4` nét dọc phải bắt đầu từ giữa, khác font Windows.
Đây là augmentation thủ công, không học máy.

**29. Margin dùng để làm gì?**
`margin = top1 − top2`. Margin nhỏ nghĩa là hai nhãn gần như tương đương, không
đủ tin cậy, nên từ chối thay vì đoán.

**30. Hậu xử lý có tự sửa ký tự để đúng định dạng không?**
Không. Nó chỉ chọn lại trong danh sách nhãn đã chấm điểm, giảm tối đa 0.15 điểm
và phải hơn nhãn thứ hai 0.02. Không tạo nhãn mới, không đổi ký tự chỉ để hợp lệ.

**31. Các trạng thái có ý nghĩa gì?**
`SUCCESS` đủ tin cậy và đúng định dạng; `FORMAT_WARNING` đủ tin cậy nhưng sai
định dạng; `LOW_CONFIDENCE` còn `?` hoặc điểm thấp; `PLATE_NOT_FOUND` không có
ứng viên; `INVALID_IMAGE` lỗi đọc ảnh; `CONFIG_ERROR` lỗi cấu hình/template.

## E. Đánh giá và kết quả

**32. PDR, CSA, CA, EPA khác nhau thế nào?**
PDR đo phát hiện vùng biển; CSA đo tách đúng hộp ký tự; CA đo đúng từng ký tự;
EPA đo đúng toàn bộ chuỗi. EPA khắt khe nhất.

**33. Vì sao EPA chỉ 47.83% trong khi CA 88%?**
Vì sai một ký tự là cả chuỗi sai. Các cặp `S/5`, `B/8`, `2/Z`, `1/T`, `0/D`
thường bị nhầm do khác font; phân đoạn đôi khi thiếu/thừa ký tự.

**34. Kết quả 13/13 trên ảnh thật có ý nghĩa gì?**
Đó là kiểm tra hồi quy trên tập đã dùng để tinh chỉnh, chứng minh hệ thống không
hỏng sau các thay đổi. **Không phải** độ chính xác trên holdout độc lập.

**35. Vì sao PDR/CSA trên ảnh thật là proxy?**
Nhãn ảnh thật chỉ có chuỗi, chưa có hộp bao biển/ký tự. PDR dựa trên sự hiện
diện, CSA dựa trên chênh lệch số lượng, không phải IoU.

**36. Làm sao biết hệ thống không overfit tập test?**
Không thể khẳng định tuyệt đối. Báo cáo thừa nhận hai ảnh test đã được xem để
chẩn đoán trước khi cố định cấu hình; tập test không khóa hoàn toàn. Đây là một
đe dọa tính hợp lệ đã nêu.

**37. Thời gian xử lý bao nhiêu?**
Trung bình 1.36–1.86 s/ảnh trên tập tổng hợp/ảnh thật trong lần đo cuối; `8.jpg`
khoảng 17.8 s. Phần lớn thời gian ở phát hiện và nhận dạng.

**38. Nút thắt hiệu năng nằm ở đâu?**
Nhận dạng: số ký tự × số template × 32×48 phép so khớp. Phát hiện: nhiều bản đồ
morphology và contour. Có thể giảm template, cache, hoặc song song hóa.

## F. Câu hỏi bẫy và giới hạn

**39. “CSA 100% trên ảnh thật” có nghĩa phân đoạn hoàn hảo?**
Không. Đó là proxy theo số lượng, không phải IoU. Không được dùng để kết luận
vị trí ký tự chính xác tuyệt đối.

**40. Nếu ảnh có hai biển số thì sao?**
Hệ thống chỉ thiết kế cho một biển chính. Ứng viên điểm cao nhất được chọn; biển
thứ hai có thể bị bỏ qua hoặc gây nhầm.

**41. Nếu biển bị che một phần?**
Có thể thiếu ký tự, dẫn đến `LOW_CONFIDENCE` hoặc chuỗi sai. Hệ thống không có
cơ chế suy luận ký tự bị che.

**42. Vì sao không dùng regex để sửa chuỗi cho đúng định dạng?**
Vì như vậy là bịa ký tự, che giấu lỗi và làm sai lệch đánh giá. Hệ thống chỉ
validate và cảnh báo, không tự sửa.

**43. Hướng phát triển hợp lý nhất là gì?**
Bổ sung crop ký tự thật đã xác minh vào template; cải thiện tách ký tự dính
(profile/watershed cổ điển); cải thiện hiệu chỉnh nghiêng mạnh; xây bộ test
holdout thật và khóa trước khi tinh chỉnh.

**44. Nếu được dùng học máy thì làm gì?**
Có thể dùng detector học sâu cho vùng biển và OCR cho ký tự, nhưng sẽ mất tính
“giải thích được từng bước” và cần dữ liệu huấn luyện. Đó là hướng khác, không
phải phạm vi đề tài.

**45. Điều gì khiến bài tập lớn này có giá trị học tập môn Xử lý ảnh?**
Pipeline đầy đủ, cấu hình tập trung, 78 test, công cụ đánh giá tái lập được, báo
cáo nêu cả thất bại và giới hạn thay vì chỉ khoe kết quả.

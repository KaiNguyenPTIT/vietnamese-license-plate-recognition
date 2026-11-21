# 03 — Thuật toán và công thức tóm tắt

Tài liệu này là “cheat sheet” để trả lời nhanh câu hỏi công thức. Ký hiệu:
`I(x, y)` là cường độ ảnh xám, `B(x, y)` là ảnh nhị phân, `T` là template.

---

## 1. Ảnh xám và làm mờ

**Grayscale (OpenCV, chuẩn BT.601):**

```text
Y = 0.299·R + 0.587·G + 0.114·B
```

**Gaussian 5×5:** tích chập với nhân Gauss rời rạc, làm giảm nhiễu cao tần
trước khi tính cạnh. Median 5×5 thay thế pixel bằng trung vị lân cận, tốt với
nhiễu muối tiêu. Bilateral lọc theo cả khoảng cách không gian và chênh lệch
màu, giữ biên tốt hơn nhưng chậm hơn.

**CLAHE:** chia ảnh thành lưới 8×8, cân bằng histogram từng ô với clip limit
2.0, nội suy song tuyến giữa các ô để tránh vệt khối. Dùng khi ảnh thiếu sáng
hoặc tương phản thấp.

---

## 2. Canny

1. Làm mờ Gaussian.
2. Tính gradient Sobel `Gx, Gy`; độ lớn `|G| = √(Gx² + Gy²)`, hướng
   `θ = arctan(Gy/Gx)`.
3. **Non-maximum suppression:** giữ pixel nếu nó lớn hơn hai pixel lân cận
   theo hướng gradient.
4. **Double threshold:** gradient > ngưỡng cao là biên mạnh; trong khoảng
   thấp–cao là biên yếu; dưới ngưỡng thấp bị loại.
5. **Hysteresis:** giữ biên yếu nếu nối với biên mạnh.

Cấu hình: 60/180, `L2gradient=True`. `auto_canny` chọn ngưỡng theo trung vị:
`low = max(0, 0.66·median)`, `high = min(255, 1.33·median)`.

---

## 3. Otsu

Với mỗi ngưỡng `t`, chia pixel thành hai lớp `C0 = {I ≤ t}`, `C1 = {I > t}`.
Gọi `ω0, ω1` là tỷ lệ pixel và `μ0, μ1` là trung bình mỗi lớp. Phương sai
giữa hai lớp:

```text
σ²_b(t) = ω0(t)·ω1(t)·[μ0(t) − μ1(t)]²
t* = argmax_t σ²_b(t)
```

Otsu tự động, phù hợp ảnh có histogram hai đỉnh. Với ảnh sáng không đều,
adaptive Gaussian với block 21 và hằng số C = 5 thường tốt hơn.

---

## 4. Morphology và contour

**Đóng ảnh (closing):** `A • K = (A ⊕ K) ⊖ K` — giãn rồi co, nối nét đứt và
lấp lỗ nhỏ. Kernel 17×3 (rộng theo trục ngang) phù hợp biển một dòng; 25×5 và
15×7 bắt biển hai dòng hoặc nét đứt.

**Contour:** đường bao các thành phần liên thông trên ảnh nhị phân. OpenCV
dùng thuật toán biên theo dõi (border following).

**Xấp xỉ đa giác:** `approxPolyDP` với epsilon `= 0.02 × chu vi`; nếu còn 4
điểm, lồi và đủ diện tích thì coi là tứ giác biển.

---

## 5. Chấm điểm ứng viên biển

Với mỗi ứng viên:

```text
ratio_score  = max_t exp(−|ratio − t| / tolerance)          (t ∈ {4.6, 1.45})
area_score   = exp(−(ln(area_ratio / ideal))² / (2·σ²))
edge_score   = hàm hình thang: thấp → tăng → 1 trong [ideal, high] → giảm
fill_score   = min(1, (fill − min_fill) / (1 − min_fill))   nếu fill > min_fill
spec_score   = Σ w_i · s_i        (ratio 0.35, area 0.15, edge 0.30, fill 0.15)
score        = 0.80 · spec_score + 0.20 · text_likeness
```

Điều kiện qua: `score ≥ 0.45` và `text_likeness ≥ 0.15`.

`text_likeness` = hàm bão hòa theo số thành phần liên thông có kích thước giống
ký tự trong vùng ứng viên. Đây là **bằng chứng hình học**, không phải nhận dạng.

---

## 6. Biến đổi phối cảnh

Cho 4 điểm nguồn `p_i` và 4 điểm đích `q_i`, tìm ma trận đồng nhất 3×3 `H`
sao cho `q_i ~ H·p_i`. OpenCV giải hệ 8 phương trình:

```text
[x']   [h11 h12 h13] [x]
[y'] = [h21 h22 h23] [y]
[w ]   [h31 h32  1 ] [1]
```

Ảnh warp: `I'(x', y') = I(H⁻¹·(x', y'))`, thực hiện bằng nội suy song tuyến.
Trong bài, 4 điểm đích là hình chữ nhật có tỷ lệ theo kích thước thật ước lượng.

**Deskew:** nếu không tìm được tứ giác, dùng `minAreaRect` lấy góc nghiêng
`α`; nếu `2.5° ≤ |α| ≤ 18°` thì xoay ảnh quanh tâm.

---

## 7. Projection profile để tách dòng/ký tự

Chiếu ảnh nhị phân lên trục:

```text
p_row(y) = Σ_x B(x, y)          (tách dòng)
p_col(x) = Σ_y B(x, y)          (tách ký tự trong một dòng)
```

Vùng có `p(y) > 0.02 · max(p)` liên tục được coi là một dòng. Khoảng trắng giữa
hai dòng là valley. Với ký tự dính, tìm cực tiểu địa phương của `p_col` gần
giữa hộp; nếu valley đủ sâu và hai phần đủ lớn thì tách.

---

## 8. Chuẩn hóa ký tự

1. Cắt sát ink box (bounding box của pixel mực).
2. Kéo giãn ink box về canvas 32×48 (`stretch`), thêm padding 2 px.
3. Làm mờ nhẹ σ = 2.0 trước khi so khớp để giảm nhạy cảm với độ dày nét.

Vì sao `stretch` thay vì giữ tỷ lệ: ký tự biển có nhiều font, chiều rộng/thân
khác nhau; kéo giãn giúp template và ký tự cùng “khung”, giảm lệch do font.

---

## 9. Template Matching

Với ảnh `I` và template `T` cùng kích thước:

```text
T'(x,y) = T(x,y) − mean(T)
I'(x,y) = I(x,y) − mean(I)

R(x,y) = Σ T'(x,y)·I'(x,y) / √( Σ T'² · Σ I'² )
```

`TM_CCOEFF_NORMED` cho `R ∈ [−1, 1]`; càng gần 1 càng giống. Hệ thống lấy
`max R` trên mọi template của mỗi nhãn, cho phép dịch ±1 px.

**Hai tầng:** coarse (6 template/nhãn) → giữ 6 nhãn → chấm đầy đủ. Giảm chi phí
mà gần như không mất độ chính xác.

**Margin:** `score(top1) − score(top2)`. Margin nhỏ nghĩa là hai nhãn gần như
tương đương → không đủ tin cậy.

---

## 10. Hole prior

Đếm số lỗ (lỗ hổng nền bên trong ký tự) bằng contour con:

```text
holes(char) = số contour con có diện tích ≥ 25 px
```

Ví dụ `8` có 2 lỗ, `0` có 1 lỗ, `B` có 2 lỗ. Nếu số lỗ của ký tự khác số lỗ
phổ biến của nhãn template, trừ 0.20 điểm. Đây là prior topology thủ công,
không phải học máy.

---

## 11. Khoảng cách Levenshtein và CA

```text
D[0][j] = j
D[i][0] = i
D[i][j] = min(
    D[i−1][j] + 1,                 // xóa
    D[i][j−1] + 1,                 // chèn
    D[i−1][j−1] + (a_i ≠ b_j)      // thay thế hoặc khớp
)
```

`CA = matches / (matches + substitutions + insertions + deletions)`, tức
`1 − khoảng_cách_sửa_đổi / độ_dài_căn_chỉnh`. Khác với “độ chính xác theo
từng vị trí” khi độ dài chuỗi dự đoán khác nhãn.

---

## 12. IoU và các chỉ số

```text
IoU(A, B) = area(A ∩ B) / area(A ∪ B)
```

- **PDR** = số ảnh có biển được phát hiện đúng (IoU ≥ 0.5) / tổng ảnh có biển.
- **Precision** = TP / (TP + FP); **Recall** = TP / (TP + FN), có tính ảnh
  không biển.
- **CSA** = trung bình tỷ lệ hộp ký tự ghép đúng IoU ≥ 0.5; nếu nhãn không có
  hộp, dùng proxy theo chênh lệch số lượng.
- **EPA** = số chuỗi trùng khớp hoàn toàn / tổng số ảnh có biển (mẫu số 23
  trong báo cáo; nếu chia 26 thì thấp hơn).
- **Success Rate** = số ảnh có trạng thái `SUCCESS` / tổng số ảnh.

---

## 13. Độ phức tạp

| Công đoạn | Chi phí chính | Ghi chú |
|---|---|---|
| Tiền xử lý | `O(H·W)` | resize, lọc, Canny |
| Phát hiện | `O(H·W + C·log C)` | `C` là số contour |
| Hiệu chỉnh | `O(h·w)` | warp trên vùng biển |
| Phân đoạn | `O(h·w)` | projection + contour |
| Nhận dạng | `O(n · m · 32·48)` | `n` ký tự, `m` template; coarse giảm `m` |
| Hậu xử lý | `O(n²)` | rerank trong ranked list nhỏ |

Trong thực tế, phát hiện và nhận dạng chiếm phần lớn thời gian (xem
`docs/05-ket-qua-va-danh-gia.md`).

---

## 14. Vì sao không dùng học máy?

- Đề tài giới hạn ở xử lý ảnh truyền thống để thấy rõ vai trò từng bước.
- Không cần dữ liệu huấn luyện lớn, không cần GPU.
- Có thể giải thích từng quyết định: vì sao ứng viên này được chọn, vì sao ký
  tự này bị từ chối.
- Đổi lại, độ chính xác thấp hơn học sâu trên ảnh thật đa dạng; đây là giới
  hạn đã nêu trong báo cáo.

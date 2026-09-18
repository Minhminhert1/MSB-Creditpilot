# HƯỚNG DẪN NGHIỆP VỤ & QUY TẮC XỬ LÝ PHẦN B
## (Nội dung đề xuất cấp tín dụng - Mẫu biểu MB07 MSB)

---

### I. NGUYÊN TẮC CỐT LÕI (CORE PRINCIPLES)

1. **Nguyên tắc "1 Business Fact = 1 Input = N Output Bindings"**:
   - RM chỉ nhập một dữ liệu nghiệp vụ đúng 1 lần duy nhất trên form.
   - Ví dụ: Số tiền hạn mức đề xuất $2.1 = 100$ tỷ VND:
     - Tự động xuất hiện tại Bảng Mục 1 (Dòng ECS1100).
     - Tự động xuất hiện tại Mục 2.1 (Dòng "Số tiền").
     - Tự động tham gia tính toán Tổng HMTD Nhóm A & Tổng hạn mức chung (A+B).
     - Tự động chuyển đổi thành chữ tiếng Việt chuẩn xác: `100.000.000.000 VND (Một trăm tỷ đồng)`.
   - Tuyệt đối không bắt RM nhập lại số tiền ở Mục 1 và Mục 2.

2. **Quy tắc để trống (Zero Boilerplate / Zero Hallucination)**:
   - Nếu RM để trống một trường optional hoặc không có dữ liệu: Giữ nguyên nhãn hàng trong bảng chi tiết, ô giá trị để **TRỐNG (BLANK)**.
   - Tuyệt đối **KHÔNG** tự ý điền các chuỗi ký tự mặc định như: `N/A`, `Không có`, `Không áp dụng`, `Theo quy định MSB`.

3. **Quy tắc Xóa Block & Xóa Hàng không áp dụng**:
   - Nhu cầu không được chọn (ví dụ không chọn 2.3, 2.7, 2.8): Xóa hoàn toàn toàn bộ Block Mục 2 của nhu cầu đó (xóa cả Heading `2.x ...` và Bảng chi tiết kèm theo).
   - Bảng Mục 1: Xóa toàn bộ các dòng (row) của các sản phẩm/mã hạn mức không áp dụng.

4. **Bảo toàn 100% Layout & Format Template gốc**:
   - Sử dụng chính file Word template gốc làm nền.
   - Giữ nguyên Font Times New Roman, cỡ chữ, căn lề, độ rộng cột, borders, merged cells, và checkbox MSB.

---

### II. BẢNG MA TRẬN MAPPING MÃ HẠN MỨC (ECS CODES)

| Nhu cầu Mục 2 | Phân loại / Kỳ hạn / Hình thức | Nhóm Mục 1 | Mã ECS | Tên dòng tương ứng tại Mục 1 |
| :--- | :--- | :---: | :---: | :--- |
| **2.1 Vay VLĐ hạn mức** | Mặc định (Ngắn hạn $\le 12$ tháng) | **Nhóm A** | `ECS1100` | Cho vay ngắn hạn theo hạn mức |
| **2.2 Vay VLĐ > 12 tháng** | Mặc định (Trung hạn $> 12$ tháng) | **Nhóm C** | `ECS1100` | Cho vay VLĐ |
| **2.3 Vay ngắn hạn từng lần**| Cấp từng lần ngắn hạn | **Nhóm D** | `ECS1109` | Vay ngắn hạn cấp từng lần |
| **2.4 Vay trung/dài hạn** | • Loại: Trung hạn<br>• Loại: Dài hạn | **Nhóm D**<br>**Nhóm D** | `ECS2100`<br>`ECS3100` | Vay trung hạn<br>Vay dài hạn |
| **2.5 L/C & Nhờ thu** | • Hạn mức ngắn hạn $\le 12$T<br>• Hạn mức trên 12 tháng<br>• Từng lần trung hạn<br>• Từng lần dài hạn | **Nhóm A**<br>**Nhóm C**<br>**Nhóm D**<br>**Nhóm D** | `ECS1300`<br>`ECS1300`<br>`ECS2300`<br>`ECS3300` | Phát hành L/C<br>Phát hành L/C<br>Phát hành L/C trung hạn<br>Phát hành L/C dài hạn |
| **2.6 Bảo lãnh** | • Hạn mức ngắn hạn $\le 12$T<br>• Hạn mức trên 12 tháng<br>• Từng lần trung hạn<br>• Từng lần dài hạn | **Nhóm A**<br>**Nhóm C**<br>**Nhóm D**<br>**Nhóm D** | `ECS1200`<br>`ECS1200`<br>`ECS2200`<br>`ECS3200` | Bảo lãnh<br>Bảo lãnh<br>Bảo lãnh trung hạn<br>Bảo lãnh dài hạn |
| **2.7 Chiết khấu BCT/BTT** | • Hạn mức ngắn hạn<br>• Hạn mức trên 12 tháng | **Nhóm A**<br>**Nhóm C** | `ECS1400`<br>`ECS1400` | Chiết khấu hoàn hảo<br>Chiết khấu hoàn hảo |
| **2.8 Rủi ro đối tác** | • Ngắn hạn (phái sinh FX/Lãi suất)<br>• Trung hạn<br>• Dài hạn | **Nhóm B**<br>**Nhóm D**<br>**Nhóm D** | `ECS9100`<br>`ECS9200`<br>`ECS9300` | Rủi ro tín dụng đối tác<br>Rủi ro tín dụng đối tác NH<br>Rủi ro tín dụng đối tác TDH |

---

### III. CÁC QUY TẮC RÀ SOÁT LOGIC & VALIDATION (WARNINGS VS BLOCKING)

1. **Kiểm tra thời hạn Mục 2.2**:
   - Nếu `facility_duration_months <= 12`: Cảnh báo Warning (Vàng) — *"Mục 2.2 là Cho vay VLĐ hạn mức trên 12 tháng nhưng thời hạn hiện nhập là <= 12 tháng. Đề xuất RM kiểm tra lại phân loại."* (Không tự ý sửa số tháng).
2. **Kiểm tra Tái cấp vs Hạn mức đã duyệt**:
   - Nếu chọn `Tái cấp` hoặc `Tái cấp tăng` nhưng ô `approved_limit_vnd` để trống: Cảnh báo Warning (Vàng) — *"Khoản vay được đề xuất Tái cấp nhưng chưa có thông tin Hạn mức đã được duyệt."*
3. **Kiểm tra tính đầy đủ của Subtype**:
   - Nếu chọn 2.4 (Vay trung/dài hạn) nhưng chưa chọn phân loại `Trung hạn` hay `Dài hạn`: Báo lỗi Chặn (Blocking Đỏ) — *"Cần chọn loại Trung hạn hoặc Dài hạn để xác định chính xác mã ECS."*
4. **Kiểm tra tính nhất quán 100%**:
   - Bất kỳ thay đổi nào về số tiền tại Mục 2 sẽ lập tức cập nhật đồng bộ sang Mục 1 và tổng hạn mức (không bao giờ có độ lệch giữa Mục 1 và Mục 2).

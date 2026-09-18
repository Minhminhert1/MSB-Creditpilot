# MẪU OUTPUT PHẦN D: PHÂN TÍCH TÀI CHÍNH & TÍNH TOÁN NHU CẦU VỐN

## PHẦN D: PHÂN TÍCH TÌNH HÌNH TÀI CHÍNH & TÍNH TOÁN NHU CẦU TÍN DỤNG

### 1. Phân tích Kết quả Hoạt động Kinh doanh 3 năm
*(Đơn vị: triệu đồng)*
| Chỉ tiêu P&L | Năm 2022 | Năm 2023 | Năm 2024 |
| :--- | :---: | :---: | :---: |
| **1. Doanh thu thuần** | {{rev_2022}} | {{rev_2023}} | {{rev_2024}} |
| **2. Giá vốn hàng bán** | {{cogs_2022}} | {{cogs_2023}} | {{cogs_2024}} |
| **3. Lợi nhuận gộp** | {{gross_2022}} | {{gross_2023}} | {{gross_2024}} |
| *Biên lợi nhuận gộp (%)* | {{gross_margin_2022}} | {{gross_margin_2023}} | {{gross_margin_2024}} |
| **4. Doanh thu hoạt động tài chính** | {{fin_inc_2022}} | {{fin_inc_2023}} | {{fin_inc_2024}} |
| **5. Chi phí tài chính** | {{fin_exp_2022}} | {{fin_exp_2023}} | {{fin_exp_2024}} |
| *Trong đó: Chi phí lãi vay* | {{int_exp_2022}} | {{int_exp_2023}} | {{int_exp_2024}} |
| **6. Chi phí bán hàng & Quản lý DN**| {{sga_2022}} | {{sga_2023}} | {{sga_2024}} |
| **7. Lợi nhuận sau thuế TNDN** | {{npat_2022}} | {{npat_2023}} | {{npat_2024}} |

---

### 2. Phân tích Bảng Cân đối Kế toán & Cơ cấu Tài sản - Nguồn vốn
*(Đơn vị: triệu đồng)*
| Chỉ tiêu Bảng Cân đối Kế toán | Năm 2022 | Năm 2023 | Năm 2024 |
| :--- | :---: | :---: | :---: |
| **A. TÀI SẢN NGẮN HẠN** | {{ca_2022}} | {{ca_2023}} | {{ca_2024}} |
| - Tiền và tương đương tiền / ĐTTC | {{cash_2022}} | {{cash_2023}} | {{cash_2024}} |
| - Các khoản phải thu ngắn hạn | {{ar_2022}} | {{ar_2023}} | {{ar_2024}} |
| - Hàng tồn kho | {{inv_2022}} | {{inv_2023}} | {{inv_2024}} |
| **B. TÀI SẢN DÀI HẠN** | {{nca_2022}} | {{nca_2023}} | {{nca_2024}} |
| - Tài sản cố định | {{fa_2022}} | {{fa_2023}} | {{fa_2024}} |
| **TỔNG CỘNG TÀI SẢN** | **{{ta_2022}}** | **{{ta_2023}}** | **{{ta_2024}}** |
| **A. NỢ PHẢI TRẢ** | {{liab_2022}} | {{liab_2023}} | {{liab_2024}} |
| - Nợ ngắn hạn | {{cl_2022}} | {{cl_2023}} | {{cl_2024}} |
| *Trong đó: Vay ngắn hạn TCTD* | {{debt_st_2022}} | {{debt_st_2023}} | {{debt_st_2024}} |
| - Nợ dài hạn | {{ll_2022}} | {{ll_2023}} | {{ll_2024}} |
| **B. VỐN CHỦ SỞ HỮU** | **{{eq_2022}}** | **{{eq_2023}}** | **{{eq_2024}}** |
| **TỔNG CỘNG NGUỒN VỐN** | **{{ta_2022}}** | **{{ta_2023}}** | **{{ta_2024}}** |

---

### 3. Bảng Tổng hợp Chỉ số Tài chính & Khả năng Thanh toán
| Nhóm chỉ tiêu | Năm 2022 | Năm 2023 | Năm 2024 | Ngưỡng an toàn MSB | Đánh giá của ĐVKD |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **Khả năng thanh toán hiện hành (lần)**| {{cr_2022}} | {{cr_2023}} | {{cr_2024}} | $\ge 1.10$ | Đạt chuẩn thanh khoản tốt |
| **Khả năng thanh toán nhanh (lần)** | {{qr_2022}} | {{qr_2023}} | {{qr_2024}} | $\ge 0.50$ | Đạt chuẩn an toàn |
| **Đòn bẩy nợ D/E (lần)** | {{de_2022}} | {{de_2023}} | {{de_2024}} | $\le 3.00$ | Kiểm soát đòn bẩy tốt |
| **Khả năng chi trả lãi vay ICR (lần)** | {{icr_2022}} | {{icr_2023}} | {{icr_2024}} | $\ge 1.50$ | Dòng tiền đủ trả lãi |

---

### 4. Bảng tính Nhu cầu Vốn lưu động MB09 (Theo Thông tư 39/NHNN)
*(Đơn vị: triệu đồng)*
| TT | Chỉ tiêu tính toán MB09 | Giá trị (triệu VND) | Cơ sở tính toán / Ghi chú |
| :---: | :--- | :---: | :--- |
| 1 | **Doanh thu thuần kế hoạch năm 2025** | {{mb09_target_revenue}} | Kế hoạch tăng trưởng của doanh nghiệp |
| 2 | **Tổng chi phí hoạt động SXKD kế hoạch**| {{mb09_target_costs}} | Giá vốn + Chi phí bán hàng & Quản lý |
| 3 | **Vòng quay Vốn lưu động (vòng/năm)** | **{{mb09_turnover}}** | $DSO + DIO - DPO = {{mb09_ccc}}$ ngày |
| 4 | **Nhu cầu Vốn lưu động 1 chu kỳ kinh doanh**| **{{mb09_demand_cycle}}** | $=(2)/(3)$ |
| 5 | **Vốn tự có tham gia (VLĐ ròng - NWC)** | **{{mb09_nwc}}** | $= TSNH - Nợ ngắn hạn phi tín dụng$ |
| 6 | **Vốn chiếm dụng khác** | {{mb09_other_cap}} | |
| 7 | **TỔNG NHU CẦU VAY VỐN CÁC TCTD** | **{{mb09_total_bank_demand}}** | $=(4)-(5)-(6)$ |
| 8 | **Hạn mức đề xuất cấp tín dụng tại MSB** | **{{mb09_msb_limit}}** | Chiếm {{mb09_msb_share}}% tổng nhu cầu TCTD |

---

### 5. Mô phỏng Lợi nhuận Điều chỉnh Rủi ro Basel II (RORWA / TORWA)
| Tiêu chí | Giá trị mô phỏng | Đánh giá chuẩn MSB |
| :--- | :---: | :--- |
| **Tổng hạn mức cấp tín dụng đề xuất** | **{{rorwa_limit}} triệu VND** | Vay 800 tỷ + L/C 500 tỷ + BL 200 tỷ |
| **Tổng thu nhập hoạt động (TOI)** | **{{rorwa_toi}} triệu VND** | $NII + \text{Thu phí L/C, BL, FX}$ |
| **Tài sản có rủi ro quy đổi (RWA)** | **{{rorwa_rwa}} triệu VND** | Theo hệ số rủi ro Basel II |
| **Chi phí tổn thất rủi ro kỳ vọng (EL)** | **{{rorwa_el}} triệu VND** | $EL = PD \times LGD \times EAD$ |
| **Tỷ suất sinh lời điều chỉnh rủi ro (RORWA)**| **{{rorwa_pct}}%** | **ĐẠT CHUẨN** (Vượt ngưỡng sàn $\ge 2.50\%$) |
| **Tổng lợi nhuận rủi ro TORWA** | **{{rorwa_torwa}} triệu VND** | Đóng góp hiệu quả kinh doanh cho MSB |

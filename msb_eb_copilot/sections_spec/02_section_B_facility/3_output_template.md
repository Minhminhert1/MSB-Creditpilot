# MẪU OUTPUT PHẦN B: NỘI DUNG ĐỀ XUẤT CẤP TÍN DỤNG

## PHẦN B: NỘI DUNG ĐỀ XUẤT CẤP TÍN DỤNG

**Tổng hạn mức cấp tín dụng (A+B) ĐVKD đề xuất**: `{{total_credit_limit_amount_vnd}}` triệu đồng hoặc ngoại tệ tương đương, trong đó mức cho vay tối đa là `{{max_lending_limit_amount_vnd}}` triệu đồng hoặc ngoại tệ tương đương.

---

### 1. BẢNG TỔNG HỢP HẠN MỨC CẤP TÍN DỤNG

| Cụ thể | Mã hạn mức | Hạn mức đã được duyệt | Hạn mức đề xuất mới | Ghi chú |
| :--- | :---: | :---: | :---: | :--- |
| **A. Tín dụng hạn mức ngắn hạn** | **ECS1000** | **{{total_group_a_approved}}** | **{{total_group_a_proposed}}** | `{{group_a_proposal_checkboxes}}` |
| - Cho vay ngắn hạn theo hạn mức | ECS1100 | {{need_2_1_approved}} | {{need_2_1_proposed}} | `[ ] Tái cấp    [X] Duyệt mới` |
| - Bảo lãnh | ECS1200 | {{need_2_6_approved}} | {{need_2_6_proposed}} | `[ ] Tái cấp    [X] Duyệt mới` |
| - Phát hành L/C | ECS1300 | {{need_2_5_approved}} | {{need_2_5_proposed}} | `[ ] Tái cấp    [X] Duyệt mới` |
| **B. Rủi ro tín dụng đối tác** | **ECS9100** | **{{total_group_b_approved}}** | **{{total_group_b_proposed}}** | `{{group_b_proposal_checkboxes}}` |
| **Tổng HMTD** | | **{{grand_total_approved}}** | **{{grand_total_proposed}}** | |

*(Lưu ý: Bảng trên chỉ giữ lại các dòng của nhu cầu thực tế áp dụng. Các dòng không áp dụng sẽ tự động bị xóa bỏ khỏi file Word).*

---

### 2. CHI TIẾT ĐỐI VỚI TỪNG NHU CẦU

#### 2.1 Cho vay VLĐ theo hạn mức: (Mã hạn mức: ECS1101)
| Tiêu chí | Nội dung chi tiết |
| :--- | :--- |
| **Số tiền** | `{{need_2_1_amount_formatted_with_words}}` |
| **Mục đích** | `{{need_2_1_purpose}}` |
| **Thời hạn duy trì hạn mức** | `{{need_2_1_duration}}` |
| **Thời hạn tối đa mỗi khế ước/giấy nhận nợ** | `{{need_2_1_max_promissory_note_duration}}` |
| **Lãi suất cho vay** | `{{need_2_1_interest_rate}}` |
| **Hình thức giải ngân** | `{{need_2_1_disbursement_method}}` |
| **Kỳ hạn trả nợ** | `{{need_2_1_repayment_period}}` |
| **Điều kiện khác (nếu có)** | `{{need_2_1_other_conditions}}` |

---

#### 2.6 Hạn mức/từng lần Bảo lãnh: (Mã hạn mức: ECS1200)
| Tiêu chí | Nội dung chi tiết |
| :--- | :--- |
| **Số tiền** | `{{need_2_6_amount_formatted_with_words}}` |
| **Mục đích** | `{{need_2_6_purpose}}` |
| **Loại bảo lãnh** | `{{need_2_6_guarantee_types}}` |
| **Thời hạn của hạn mức** | `{{need_2_6_duration}}` |
| **Thời hạn từng món BL** | `{{need_2_6_single_guarantee_duration}}` |
| **Tỷ lệ ký quỹ tối thiểu** | `{{need_2_6_min_margin_cash}}` |
| **Điều kiện khác (nếu có)** | `{{need_2_6_other_conditions}}` |

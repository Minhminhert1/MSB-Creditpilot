# 📑 TEMPLATE BẢNG ĐẦU RA CHUẨN: PHẦN A. TÓM TẮT THÔNG TIN CHUNG
> *Được render trực tiếp từ dữ liệu của Agent A vào Tờ trình Word MB07 & Dashboard Web*

---

## BẢNG 1: PHẦN A. TÓM TẮT THÔNG TIN CHUNG

| Tên trường thông tin | Nội dung chi tiết / Lựa chọn | Thông tin bổ sung | Nơi cấp / Ngày |
| :--- | :--- | :--- | :--- |
| **Tên khách hàng doanh nghiệp** | `{{ company_name }}` | | |
| **Viết tắt** | `{{ company_short_name }}` | | |
| **Loại hình doanh nghiệp** | `{{ enterprise_type }}` | | |
| **Tình trạng khách hàng** | `{{ '[X] KH mới    [ ] KH hiện hữu' if customer_status == 'KH mới' else '[ ] KH mới    [X] KH hiện hữu' }}` | **CIF:** `{{ cif_number }}` | |
| **Đối tượng khách hàng** | `{{ '[X] LC    [ ] LMC    [ ] Khác' if customer_segment == 'LC' else '[ ] LC    [X] LMC    [ ] Khác' }}` | | |
| **Thuộc nhóm, tập đoàn** | `{{ group_affiliation }}` | | |
| **Địa chỉ trụ sở chính** | `{{ headquarters_address }}` | | |
| **Số đăng ký kinh doanh** | `{{ tax_code_business_reg_no }}` | **Ngày cấp:** `{{ business_reg_date }}` | **Nơi cấp:** `{{ business_reg_place }}` |
| **Thời gian bắt đầu hoạt động** | `{{ operation_start_date }}` | | |
| **Người đại diện theo pháp luật** | `{{ legal_representative_name }}` | **Chức vụ:** `{{ legal_representative_title }}` | |
| **Người đại diện đề nghị cấp tín dụng** | `{{ credit_applicant_representative }}` | | |
| **Khách hàng thuộc đối tượng hạn chế cấp tín dụng hay không?** | `[ ] Có` | `[X] Không` *(Auto chọn)* | |
| **Quản lý rủi ro MTXH** | `[ ] KH thuộc đối tượng phải đánh giá rủi ro MTXH theo quy định MSB` | `[X] KH không thuộc đối tượng phải đánh giá rủi ro MTXH theo quy định MSB` *(Auto chọn)* | |
| **Doanh thu năm gần nhất** | `{{ "{:,.0f}".format(latest_year_revenue_vnd) }} triệu đồng` *(Nguồn: Excel BCTC sheet "Tờ trình")* | | |

---

### 🏭 Cơ cấu Ngành nghề & Sản phẩm chính:

| Ngành nghề kinh doanh và sản phẩm chính | Mã ngành cấp 5 | Tên ngành | Tỷ trọng / Doanh thu |
| :--- | :---: | :--- | :---: |
| **Ngành nghề kinh doanh chính** | `{{ industry_level_5_code }}` | `{{ industry_level_5_name }}` | `{{ industry_revenue_share }}` |
| **Các sản phẩm chính** | - | `{{ main_products }}` | - |

---

### 💰 Vốn điều lệ & Xếp hạng Tín dụng:

| Chỉ tiêu | Chi tiết số liệu | Ghi chú & Đối chiếu |
| :--- | :--- | :--- |
| **Vốn điều lệ** | • **Vốn đăng ký:** `{{ "{:,.0f}".format(charter_capital_registered_vnd) }} triệu đồng` *(Nguồn: Điều lệ)*<br>• **Vốn thực góp:** `{{ "{:,.0f}".format(actual_contributed_capital_vnd) }} triệu đồng` *(Nguồn: BCTC / RM)* | **Tính đến ngày:** `{{ contributed_capital_as_of_date }}` |
| **Xếp hạng tín dụng nội bộ** *(theo ĐVKD)* | • **Mã ID hồ sơ XHTD:** `{{ internal_rating_dvkd.profile_id }}`<br>• **Hạng:** `{{ internal_rating_dvkd.rating_grade }}` | **Số điểm:** `{{ internal_rating_dvkd.rating_score }}` |
| **Dư nợ cho vay của KH & người liên quan tại MSB** | `{{ "{:,.0f}".format(outstanding_loan_at_msb_vnd) }} triệu đồng` *(Lấy data từ Phần E - CIC)* | **So với quy định của NHNN:**<br>`[ ] Vượt giới hạn`<br>`[X] Trong giới hạn` *(Auto chọn)* |
| **Tổng dư tín dụng của KH & người liên quan tại MSB** | `{{ "{:,.0f}".format(total_credit_exposure_at_msb_vnd) }} triệu đồng` *(Lấy data từ Phần E - CIC)* | |

---

### 🏛️ Thẩm quyền Phê duyệt Tín dụng (Lần này):

| Nội dung | Giá trị tổng HMTD (triệu đồng) | Giá trị HMTD không TSBĐ (triệu đồng) |
| :--- | :---: | :---: |
| **HMTD đã cấp cho KH & nhóm KH liên quan** | `{{ "{:,.0f}".format(approval_authority_matrix.existing_approved_limit_total_vnd) }}` | `{{ "{:,.0f}".format(approval_authority_matrix.existing_approved_limit_unsecured_vnd) }}` |
| **HMTD đề xuất cấp cho KH lần này** | `{{ "{:,.0f}".format(approval_authority_matrix.proposed_limit_total_vnd) }}` | `{{ "{:,.0f}".format(approval_authority_matrix.proposed_limit_unsecured_vnd) }}` |
| **TỔNG CỘNG** | **`{{ "{:,.0f}".format(approval_authority_matrix.existing_approved_limit_total_vnd + approval_authority_matrix.proposed_limit_total_vnd) }} trđ`** | **`{{ "{:,.0f}".format(approval_authority_matrix.existing_approved_limit_unsecured_vnd + approval_authority_matrix.proposed_limit_unsecured_vnd) }} trđ`** |

- **Thẩm quyền phê duyệt đề xuất lần này:** 
  `{{ '[X] HĐTD&ĐT' if approval_authority_matrix.target_approval_level == 'HĐTD&ĐT' else '[ ] HĐTD&ĐT' }}    {{ '[X] HĐTDCC' if approval_authority_matrix.target_approval_level == 'HĐTDCC' else '[ ] HĐTDCC' }}    {{ '[X] HĐQT' if approval_authority_matrix.target_approval_level == 'HĐQT' else '[ ] HĐQT' }}`
- **Kỳ phê duyệt gần nhất (nếu có):** `{{ latest_approval_session }}`
- **Đề xuất nhu cầu tín dụng:** `{{ '[X] Cấp mới    [ ] Tái cấp' if credit_proposal_type == 'Cấp mới' else '[ ] Cấp mới    [X] Tái cấp' }}`

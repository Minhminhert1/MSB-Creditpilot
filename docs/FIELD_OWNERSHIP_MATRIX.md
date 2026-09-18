# Field Ownership Matrix & Duplicate Fact Audit

**Project**: MSB Enterprise Banking AI Credit Proposal Copilot  
**Status**: Authoritative Locked Matrix (Phase 2 - Corrected)  
**Core Principle**: ONE BUSINESS FACT $\to$ ONE CANONICAL PATH $\to$ ONE AUTHORITATIVE OWNER  

---

## 1. DUPLICATE FACT AUDIT & RECONCILIATION TABLE

This table resolves all redundant, conflicting, and multi-homed concepts discovered in the active codebase into a single canonical source of truth.

### Relationship Taxonomy
- **`TRUE_ALIAS`**: Identical business fact bound to multiple output representations (e.g. `customer.tax_code` $\to$ Section A `company.registration_no`).
- **`LEGACY_ALIAS`**: Obsolete path preserved for backward compatibility with old code/tests (e.g. `customer.revenue_2025` $\to$ canonical `section_d.net_revenue[-1]`). Read-only; GreenNode and RM must never write to it.
- **`DERIVED_FROM`**: Value deterministically computed by Python code from source facts (e.g. financial ratios, MB09 outputs, RORWA outputs). GreenNode CANNOT extract or overwrite.
- **`RELATED_DISTINCT`**: Concepts that relate to each other or reconcile, but represent fundamentally distinct business facts (e.g. company total capital vs individual shareholder value; legal rep vs executive management). They MUST NOT share a canonical path or be automatically aliased by position.

| Business Fact / Concept | Relationship | Current Locations in Code | Current Consumers | Chosen Canonical Path | Legacy Adapter Required? | Reconciliation & Semantic Boundary |
|---|---|---|---|---|---|---|
| **Revenue (Doanh thu)** | `LEGACY_ALIAS` | 1. `customer.revenue_2025`<br>2. `section_d.net_revenue`<br>3. `financial.latest_net_revenue` | • `web_copilot_app.py:532`<br>• `test_web_copilot_confirm.py:476`<br>• `MB09` engine | **`section_d.net_revenue`** (`list[float]`, triệu VND) | **Yes**: `CanonicalAdapter.get_latest_revenue()` reads `section_d.net_revenue[-1]`, falls back to legacy field with warning. | Canonical series is `section_d.net_revenue`. GreenNode and RM write ONLY to `section_d.net_revenue`. `customer.revenue_2025` is read-only legacy fallback. |
| **Charter Capital vs Shareholder Equity** | `RELATED_DISTINCT` | 1. `customer.charter_capital`<br>2. `section_c.shareholders[i].val` | • `LegalDocumentMapper`<br>• `web_copilot_app.py:541`<br>• Section C Table 01 | • Total: **`customer.charter_capital`**<br>• Breakdown: **`section_c.shareholders[i].val`** | **No**: Distinct fields. Reconciled via `SUM(shareholders[*].val) == charter_capital`. | `customer.charter_capital` = Tổng vốn điều lệ đăng ký của DN. `shareholders[i].val` = Vốn góp của từng cổ đông. **Tuyệt đối không gộp chung một path; không alias tự động.** |
| **Section A Registered Capital Binding** | `TRUE_ALIAS` | 1. `customer.charter_capital`<br>2. `section_a.capital.registered_capital` | • `web_copilot_app.py:541`<br>• Section A renderer | **`customer.charter_capital`** (`float`, triệu VND) | **No**: Output binding in Section A reads directly from `customer.charter_capital`. | Section A `capital.registered_capital` is an output view of the canonical fact `customer.charter_capital`. |
| **Legal Representative vs Management** | `RELATED_DISTINCT` | 1. `customer.legal_rep_name`<br>2. `section_c.management[i].name` | • `LegalDocumentMapper`<br>• `web_copilot_app.py:520`<br>• Section C Table 02 | • Legal Rep: **`customer.legal_rep_name`**<br>• Management: **`section_c.management`** | **No**: Distinct facts. Never map by list index (e.g. `management[0]`). | `legal_rep_name` là Người đại diện pháp luật theo luật định (ghi trên ĐKKD). `management` là cơ cấu Ban điều hành. Người đại diện có thể kiêm nhiệm điều hành, nhưng đòi hỏi bằng chứng từ tài liệu bổ nhiệm, không gán ngầm. |
| **Parent Group vs Section C Owner** | `RELATED_DISTINCT` | 1. `customer.parent_group`<br>2. `section_c.parent_company_or_owner` | • `web_copilot_app.py:514`<br>• `web_copilot_app.py:645` | • Group: **`customer.parent_group`**<br>• Owner: **`section_c.parent_company_or_owner`** | **No**: Distinct concepts. | `parent_group` là tên Tập đoàn/Tổng công ty mẹ cấp cao. `parent_company_or_owner` trong Section C là chủ sở hữu trực tiếp nắm quyền chi phối kèm tỷ lệ sở hữu. Chỉ liên kết khi có chứng cứ pháp lý xác nhận cùng một pháp nhân. |
| **Tax Code (Mã số thuế)** | `TRUE_ALIAS` | 1. `customer.tax_code`<br>2. `section_a.company.registration_no` | • `web_copilot_app.py:516`<br>• `LegalDocumentMapper`<br>• CIC lookup | **`customer.tax_code`** (`str`) | **No**: Section A binds `company.registration_no` $\leftarrow$ `customer.tax_code`. | Strictly `str` to preserve leading zeros. Extracted by Legal Agent; verified by RM. |
| **Internal Credit Ratings (XHTD)** | `TRUE_ALIAS` | 1. `customer.rating_grade`<br>2. `customer.rating_score`<br>3. `section_a.internal_rating.*` | • `web_copilot_app.py:546-547`<br>• Section A renderer | **`customer.rating_grade`** (`str`) & **`customer.rating_score`** (`float`) | **No**: Direct binding to Section A. | Owned by `RM_INPUT`. GreenNode cannot invent internal bank ratings. |
| **CIC Information & Outstanding (Dư nợ CIC)** | `TRUE_ALIAS` | 1. `section_e.msb_outstanding`<br>2. `section_e.relations[i].short_term_debt_vnd_million`<br>3. Section A credit relations | • `web_copilot_app.py:563-568`<br>• `link_section_e_to_session_a` | **`section_e.msb_outstanding`** (`float`, triệu VND) & **`section_e.relations`** (`list[dict]`) | **No**: Section A reads directly from Section E. | `section_e` is canonical home. |
| **Other Banks Debt for MB09** | `DERIVED_FROM` | 1. `credit_demand_engine.other_debt`<br>2. `section_e.total_debt_other_banks_excluding_msb` | • `CreditDemandEngine` (MB09) | **`CreditDemandEngine.other_debt`** | **No**: Deterministic sum computed from `section_e.relations`. | Derived as: `sum(r.total_debt_million for r in relations if 'MSB' not in r.bank_name) * 1e6`. |
| **Financial Ratios (Chỉ số tài chính)** | `DERIVED_FROM` | 1. `section_d.ratios`<br>2. `FinancialRatios3Y` | • `web_copilot_app.py:722-733`<br>• `SectionDValidator`<br>• MB07 Table 11 | **Calculated in Python runtime (`DERIVED_PYTHON`)** | **No**: Ratios are never stored as raw input facts. | GreenNode MUST NOT extract or write ratios. Python calculates ratios deterministically from raw P&L and Balance Sheet. |
| **Facility Limits (Hạn mức đề xuất)** | `TRUE_ALIAS` | 1. `section_b.total_limit`<br>2. `section_b.loan_limit`<br>3. `section_b.guarantee_limit`<br>4. Section A proposed limits | • `web_copilot_app.py:551-554`<br>• `web_copilot_app.py:588`<br>• `RorwaEngine` | **`section_b.total_limit`**, **`loan_limit`**, **`guarantee_limit`** (`float`, triệu VND) | **No**: Section A and RORWA bind from Section B limits. | Owned 100% by `RM_INPUT`. GreenNode cannot autonomously set limits. |
| **Narrative Fields (Nhận xét / Thuyết minh)** | `TRUE_ALIAS` | 1. `section_c.*_assessment`<br>2. `section_d.*_assessment`<br>3. `section_e.rm_credit_assessment` | • Section C, D, E MB07 mutators | **`section_c.*`**, **`section_d.*`**, **`section_e.*`** | **No**: Stored in respective section containers. | Owner: `AI_NARRATIVE` (grounded with evidence) or `RM_INPUT`. |

---

## 2. COMPREHENSIVE FIELD OWNERSHIP MATRIX

### Ownership Legend
- **`SOURCE_FACT`**: Extracted from documents (GreenNode eligible).
- **`RM_INPUT`**: Credit intent & discretionary parameters (Human authoritative).
- **`DERIVED_PYTHON`**: Deterministically calculated by Python (GreenNode CANNOT overwrite).
- **`AI_NARRATIVE`**: Grounded narrative synthesis generated by GreenNode with evidence.
- **`SYSTEM_METADATA`**: System identifiers and routing keys.

| Canonical Path | Type | Unit | Owner | Primary Source | Extracted by GreenNode? | Consumed By |
|---|---|---|---|---|---|---|
| `id` | `str` | - | `SYSTEM_METADATA` | System / RM | No | Case routing, file naming |
| `name` | `str` | - | `SYSTEM_METADATA` | System / RM | No | Case display banner |
| **SECTION A: CUSTOMER** | | | | | | |
| `customer.name` | `str` | - | `SOURCE_FACT` | ĐKKD / Điều lệ | Yes | Section A, B, C, D, E, MB07 header |
| `customer.short_name` | `str` | - | `SOURCE_FACT` | ĐKKD / Điều lệ | Yes | Section A, B, C |
| `customer.tax_code` | `str` | - | `SOURCE_FACT` | ĐKKD / Đăng ký thuế | Yes | Section A `company.registration_no`, CIC query |
| `customer.cif` | `str` | - | `RM_INPUT` | Core T24 / RM Input | No | Section A `relationship.cif` |
| `customer.segment` | `str` | - | `RM_INPUT` | Phân loại KH | No | Section A `relationship.segment` |
| `customer.address` | `str` | - | `SOURCE_FACT` | ĐKKD | Yes | Section A `company.registered_address` |
| `customer.charter_capital` | `float` | triệu VND | `SOURCE_FACT` | ĐKKD / BCTC | Yes | Section A `capital.registered_capital`, Section D, MB09 |
| `customer.legal_rep_name` | `str` | - | `SOURCE_FACT` | ĐKKD | Yes | Section A `legal_representative.name` (Distinct from Management) |
| `customer.legal_rep_title` | `str` | - | `SOURCE_FACT` | ĐKKD | Yes | Section A `legal_representative.title` |
| `customer.parent_group` | `str` | - | `SOURCE_FACT` | ĐKKD / Điều lệ | Yes | Section A `company.group_name` (Distinct from Direct Owner) |
| `customer.established_year`| `str` | - | `SOURCE_FACT` | ĐKKD | Yes | Section A `operation_start_date_or_year` |
| `customer.rating_grade` | `str` | - | `RM_INPUT` | XHTD nội bộ | No | Section A `internal_rating.grade` |
| `customer.rating_score` | `float` | điểm | `RM_INPUT` | XHTD nội bộ | No | Section A `internal_rating.score` |
| `customer.restricted_subject` | `str` | - | `RM_INPUT` | RM rà soát tuân thủ | No | Section A `compliance.restricted_credit_subject` |
| `customer.esg_status` | `str` | - | `RM_INPUT` | RM rà soát ESG | No | Section A `compliance.esg_assessment_required` |
| **RM METADATA** | | | | | | |
| `rm_metadata.unit_name` | `str` | - | `RM_INPUT` | RM Profile / ĐVKD | No | MB07 Table 00 Đơn vị lập tờ trình |
| `rm_metadata.rm_name` | `str` | - | `RM_INPUT` | RM Profile | No | MB07 Table 00 Cán bộ QHKH |
| `rm_metadata.rm_phone` | `str` | - | `RM_INPUT` | RM Profile | No | MB07 Table 00 Số điện thoại RM |
| `rm_metadata.support_name` | `str` | - | `RM_INPUT` | Support Profile | No | MB07 Table 00 Cán bộ HTQHKH |
| `rm_metadata.support_phone`| `str` | - | `RM_INPUT` | Support Profile | No | MB07 Table 00 Số điện thoại HTQHKH |
| `rm_metadata.manager_name` | `str` | - | `RM_INPUT` | Management Profile| No | MB07 Table 00 Giám đốc ĐVKD |
| `rm_metadata.manager_phone`| `str` | - | `RM_INPUT` | Management Profile| No | MB07 Table 00 Số điện thoại GĐ ĐVKD |
| `rm_metadata.proposal_no` | `str` | - | `RM_INPUT` | Số văn bản ĐVKD | No | MB07 Header / Section A |
| `rm_metadata.proposal_date`| `str` | DD/MM/YYYY | `RM_INPUT` | Ngày lập | No | MB07 Header / Section A |
| `rm_metadata.approval_authority` | `str` | - | `RM_INPUT` | Cấp thẩm quyền | No | Section A `approval.authority` |
| `rm_metadata.request_type` | `str` | - | `RM_INPUT` | Loại đề xuất | No | Section A `proposal.request_type` |
| **SECTION B: CREDIT REQUEST** | | | | | | |
| `section_b.selected_needs` | `list[str]` | - | `RM_INPUT` | RM Lựa chọn | No | Section B engine dispatch |
| `section_b.total_limit` | `float` | triệu VND | `RM_INPUT` | RM Đề xuất | No | Section B, Section A, RORWA |
| `section_b.loan_limit` | `float` | triệu VND | `RM_INPUT` | RM Đề xuất | No | Section B, Section A, MB09 |
| `section_b.guarantee_limit`| `float` | triệu VND | `RM_INPUT` | RM Đề xuất | No | Section B, RORWA |
| `section_b.loan_purpose` | `str` | - | `RM_INPUT` | RM Đề xuất | No | Section B Mục 2.1 |
| `section_b.loan_tenor_months` | `int` | tháng | `RM_INPUT` | RM Đề xuất | No | Section B Mục 2.1 |
| `section_b.disbursement_method` | `str` | - | `RM_INPUT` | RM Đề xuất | No | Section B Mục 2.1 |
| `section_b.collateral_type`| `str` | - | `RM_INPUT` | RM Đề xuất | No | Section B Biện pháp bảo đảm |
| `section_b.cashflow_commitment_pct` | `float` | % | `RM_INPUT` | RM Đề xuất | No | Section B Cam kết dòng tiền |
| `section_b.cashflow_direct_pct` | `float` | % | `RM_INPUT` | RM Đề xuất | No | Section B Dòng tiền về trực tiếp |
| `section_b.ewt_conditions` | `str` | - | `RM_INPUT` | Quy định MSB | No | Section B Điều kiện cảnh báo sớm |
| **SECTION C: BUSINESS** | | | | | | |
| `section_c.history_narrative` | `str` | - | `AI_NARRATIVE` | Hồ sơ DN / Điều lệ | Yes | Section C Mục 1 |
| `section_c.shareholders` | `list[dict]` | - | `SOURCE_FACT` | ĐKKD / Điều lệ / BCTC | Yes | Section C Bảng 01 Cổ đông lớn |
| `section_c.shareholders[i].val` | `float` | triệu VND | `SOURCE_FACT` | ĐKKD | Yes | Section C Bảng 01 (Distinct from Total Capital) |
| `section_c.management` | `list[dict]` | - | `SOURCE_FACT` | Quyết định bổ nhiệm | Yes | Section C Bảng 02 Ban điều hành (Distinct from Legal Rep) |
| `section_c.parent_company_or_owner` | `str` | - | `SOURCE_FACT` | ĐKKD / BCTC | Yes | Section C Mục 2.1 (Distinct from Parent Group) |
| `section_c.business_model` | `str` | - | `SOURCE_FACT` / `RM_INPUT` | BCTC / Khảo sát | Yes | Section C phân loại mô hình |
| `section_c.products` | `list[dict]` | `share: %` | `SOURCE_FACT` | BCTC / Báo cáo KD | Yes | Section C Mục 3 Sản phẩm chính |
| `section_c.suppliers` | `list[dict]` | `share: %` | `SOURCE_FACT` | Hợp đồng mua hàng | Yes | Section C Bảng 04 Top Nhà cung cấp |
| `section_c.customers` | `list[dict]` | `share: %` | `SOURCE_FACT` | Hợp đồng bán hàng | Yes | Section C Bảng 06 Top Khách hàng |
| `section_c.rm_management_assessment` | `str` | - | `AI_NARRATIVE` | RM / AI tổng hợp | Yes | Section C Nhận xét ban lãnh đạo |
| `section_c.rm_market_position` | `str` | - | `AI_NARRATIVE` | RM / AI tổng hợp | Yes | Section C Vị thế thị trường |
| `section_c.rm_risk_mitigation` | `str` | - | `AI_NARRATIVE` | RM / AI tổng hợp | Yes | Section C Biện pháp giảm thiểu |
| **SECTION D: FINANCIAL (RAW FACTS)** | | | | | | |
| `section_d.auditor` | `str` | - | `SOURCE_FACT` | Báo cáo kiểm toán | Yes | Section D Đơn vị kiểm toán |
| `section_d.years` | `list[str]` | - | `SOURCE_FACT` | BCTC 3 năm | Yes | Trục thời gian P&L và CĐKT |
| `section_d.net_revenue` | `list[float]` | triệu VND | `SOURCE_FACT` | BCTC - KQKD (Mã 10)| Yes | Section D P&L, Section A, MB09 (The ONLY canonical revenue series) |
| `section_d.cogs` | `list[float]` | triệu VND | `SOURCE_FACT` | BCTC - KQKD (Mã 11)| Yes | Section D P&L, MB09 |
| `section_d.gross_profit` | `list[float]` | triệu VND | `SOURCE_FACT` | BCTC - KQKD (Mã 20)| Yes | Section D P&L |
| `section_d.financial_income` | `list[float]` | triệu VND | `SOURCE_FACT` | BCTC - KQKD (Mã 21)| Yes | Section D P&L |
| `section_d.financial_expenses` | `list[float]` | triệu VND | `SOURCE_FACT` | BCTC - KQKD (Mã 22)| Yes | Section D P&L |
| `section_d.interest_expenses` | `list[float]` | triệu VND | `SOURCE_FACT` | BCTC - KQKD (Mã 23)| Yes | Section D P&L, DSCR/ICR |
| `section_d.sga_expenses` | `list[float]` | triệu VND | `SOURCE_FACT` | BCTC - KQKD (Mã 25+26)| Yes | Section D P&L, MB09 |
| `section_d.net_profit_before_tax` | `list[float]` | triệu VND | `SOURCE_FACT` | BCTC - KQKD (Mã 50)| Yes | Section D P&L |
| `section_d.net_profit_after_tax` | `list[float]` | triệu VND | `SOURCE_FACT` | BCTC - KQKD (Mã 60)| Yes | Section D P&L, ROS, ROE |
| `section_d.current_assets` | `list[float]` | triệu VND | `SOURCE_FACT` | BCTC - CĐKT (Mã 100)| Yes | Section D CĐKT, CR, QR |
| `section_d.cash` | `list[float]` | triệu VND | `SOURCE_FACT` | BCTC - CĐKT (Mã 110)| Yes | Section D CĐKT, Cash Ratio |
| `section_d.receivables` | `list[float]` | triệu VND | `SOURCE_FACT` | BCTC - CĐKT (Mã 130)| Yes | Section D CĐKT, DSO |
| `section_d.inventories` | `list[float]` | triệu VND | `SOURCE_FACT` | BCTC - CĐKT (Mã 140)| Yes | Section D CĐKT, QR, DIO |
| `section_d.total_assets` | `list[float]` | triệu VND | `SOURCE_FACT` | BCTC - CĐKT (Mã 270)| Yes | Section D CĐKT, D/E |
| `section_d.total_liabilities` | `list[float]` | triệu VND | `SOURCE_FACT` | BCTC - CĐKT (Mã 300)| Yes | Section D CĐKT, D/E |
| `section_d.current_liabilities` | `list[float]` | triệu VND | `SOURCE_FACT` | BCTC - CĐKT (Mã 310)| Yes | Section D CĐKT, CR, QR, Cash Ratio |
| `section_d.short_term_debt` | `list[float]` | triệu VND | `SOURCE_FACT` | BCTC - CĐKT (Mã 320)| Yes | Section D CĐKT, CR, QR |
| `section_d.equity` | `list[float]` | triệu VND | `SOURCE_FACT` | BCTC - CĐKT (Mã 400)| Yes | Section D CĐKT, D/E, ROE |
| `section_d.rm_pnl_assessment` | `str` | - | `AI_NARRATIVE` | RM / AI tổng hợp | Yes | Section D Nhận xét P&L |
| `section_d.rm_balance_sheet_assessment`| `str` | - | `AI_NARRATIVE` | RM / AI tổng hợp | Yes | Section D Nhận xét CĐKT |
| `section_d.rm_cashflow_assessment` | `str` | - | `AI_NARRATIVE` | RM / AI tổng hợp | Yes | Section D Nhận xét Dòng tiền |
| **SECTION D: DERIVED FINANCIAL RATIOS** | | | | | | |
| `gross_profit_margin_pct` | `list[float]` | % | `DERIVED_PYTHON` | Deterministic Formula | **NO** | Section D Table P&L |
| `current_ratio` | `list[float]` | lần | `DERIVED_PYTHON` | Deterministic Formula | **NO** | Section D Table Ratios, Validator |
| `quick_ratio` | `list[float]` | lần | `DERIVED_PYTHON` | Deterministic Formula | **NO** | Section D Table Ratios |
| `cash_ratio` | `list[float]` | lần | `DERIVED_PYTHON` | Deterministic Formula | **NO** | Section D Table Ratios |
| `debt_to_equity` | `list[float]` | lần | `DERIVED_PYTHON` | Deterministic Formula | **NO** | Section D Table Ratios, Validator |
| `dscr_icr` | `list[float]` | lần | `DERIVED_PYTHON` | Deterministic Formula | **NO** | Section D Table Ratios, Validator |
| `ros` | `list[float]` | % | `DERIVED_PYTHON` | Deterministic Formula | **NO** | Section D Table Ratios |
| `roe` | `list[float]` | % | `DERIVED_PYTHON` | Deterministic Formula | **NO** | Section D Table Ratios |
| **SECTION D: MB09 DERIVED METRICS** | | | | | | |
| `mb09.total_operating_expense`| `float` | VND | `DERIVED_PYTHON` | `CreditDemandEngine` | **NO** | MB07 MB09 Table |
| `mb09.ccc_days` | `float` | ngày | `DERIVED_PYTHON` | `CreditDemandEngine` | **NO** | MB07 MB09 Table |
| `mb09.turns_per_year` | `float` | vòng/năm | `DERIVED_PYTHON` | `CreditDemandEngine` | **NO** | MB07 MB09 Table |
| `mb09.working_capital_demand` | `float` | VND | `DERIVED_PYTHON` | `CreditDemandEngine` | **NO** | MB07 MB09 Table |
| `mb09.net_working_capital_demand` | `float` | VND | `DERIVED_PYTHON` | `CreditDemandEngine` | **NO** | MB07 MB09 Table |
| `mb09.loan_limit_total` | `float` | VND | `DERIVED_PYTHON` | `CreditDemandEngine` | **NO** | MB07 MB09 Table |
| `mb09.loan_limit_msb` | `float` | VND | `DERIVED_PYTHON` | `CreditDemandEngine` | **NO** | MB07 MB09 Table |
| `mb09.lc_limit` | `float` | VND | `DERIVED_PYTHON` | `CreditDemandEngine` | **NO** | MB07 MB09 Table |
| `mb09.guarantee_limit` | `float` | VND | `DERIVED_PYTHON` | `CreditDemandEngine` | **NO** | MB07 MB09 Table |
| `mb09.total_credit_facility_msb` | `float` | VND | `DERIVED_PYTHON` | `CreditDemandEngine` | **NO** | MB07 MB09 Table |
| **SECTION D: RORWA DERIVED METRICS** | | | | | | |
| `rorwa.total_rwa` | `float` | VND | `DERIVED_PYTHON` | `RorwaEngine` | **NO** | MB07 RORWA Summary |
| `rorwa.total_income` | `float` | VND | `DERIVED_PYTHON` | `RorwaEngine` | **NO** | MB07 RORWA Summary |
| `rorwa.net_deal_profit` | `float` | VND | `DERIVED_PYTHON` | `RorwaEngine` | **NO** | MB07 RORWA Summary |
| `rorwa.torwa` | `float` | % | `DERIVED_PYTHON` | `RorwaEngine` | **NO** | MB07 RORWA Summary |
| `rorwa.rorwa` | `float` | % | `DERIVED_PYTHON` | `RorwaEngine` | **NO** | MB07 RORWA Summary |
| `rorwa.torwa_passed` | `bool` | - | `DERIVED_PYTHON` | `RorwaEngine` | **NO** | MB07 RORWA Summary |
| `rorwa.rorwa_passed` | `bool` | - | `DERIVED_PYTHON` | `RorwaEngine` | **NO** | MB07 RORWA Summary |
| **SECTION E: CIC & CREDIT RELATIONS** | | | | | | |
| `section_e.cic_date` | `str` | DD/MM/YYYY | `SOURCE_FACT` | Báo cáo CIC | Yes | MB07 Table 07 |
| `section_e.msb_outstanding` | `float` | triệu VND | `SOURCE_FACT` | Báo cáo CIC / T24 | Yes | Section A, Section E Table 07 |
| `section_e.history_status` | `str` | - | `SOURCE_FACT` | Báo cáo CIC | Yes | MB07 Table 07 Nhóm nợ |
| `section_e.rm_credit_assessment`| `str` | - | `AI_NARRATIVE` | RM / AI tổng hợp | Yes | MB07 Table 07 Nhận xét CIC |
| `section_e.relations` | `list[dict]` | triệu VND | `SOURCE_FACT` | Báo cáo CIC | Yes | MB07 Table 07 Danh sách TCTD |
| `section_e.total_debt_other_banks_excluding_msb` | `float` | triệu VND | `DERIVED_PYTHON` | Sum of relations | **NO** | Cung cấp cho `CreditDemandEngine.other_debt` |

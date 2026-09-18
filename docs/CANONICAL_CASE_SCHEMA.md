# Canonical Case Data Contract (Sections A-E)

**Project**: MSB Enterprise Banking AI Credit Proposal Copilot  
**Status**: Authoritative Locked Contract (Phase 2 - Corrected)  
**Core Principle**: ONE BUSINESS FACT $\to$ ONE CANONICAL PATH $\to$ MANY OUTPUT BINDINGS  

---

## 1. Top-Level Conceptual Structure

The competition runtime operates on a single authoritative business state: `case_data`.
Every future GreenNode agent proposes facts into this structure; every deterministic credit engine consumes from this structure; and MB07 Word renderers bind from it.

```json
{
  "id": "PSD",
  "name": "PSD - CTCP Dịch vụ Phân phối TH Dầu khí",
  "customer": { ... },       // Section A: Pháp lý & Định danh khách hàng
  "rm_metadata": { ... },    // Thông tin ĐVKD, Cán bộ QHKH, Tờ trình
  "section_b": { ... },      // Section B: Nhu cầu & Đề xuất cấp tín dụng (Ý chí RM)
  "section_c": { ... },      // Section C: Hoạt động kinh doanh, Cổ đông, Lãnh đạo, NCC, KH
  "section_d": { ... },      // Section D: Báo cáo tài chính & Chỉ số an toàn (BCTC 3 năm)
  "section_e": { ... }       // Section E: Quan hệ tín dụng & Báo cáo CIC
}
```

> **Non-Negotiable Boundary**:
> Workflow metadata (such as `evidence`, `source_document`, `page`, `preview_id`, `warnings`, `conflicts`, `telemetry`, and API request tokens) MUST NEVER be stored inside `case_data`. They belong strictly in external sidecar structures (e.g., `CanonicalMappingResult`, `GreenNodeTelemetryRecord`).

---

## 2. Duplicate Fact vs. Distinct Related Fact Semantics

A critical requirement of the canonical contract is distinguishing:
- **`TRUE_ALIAS`**: Identical business fact bound to multiple output representations (e.g. `customer.tax_code` $\to$ Section A `company.registration_no`).
- **`LEGACY_ALIAS`**: Obsolete path preserved for backward compatibility (e.g. `customer.revenue_2025` $\to$ canonical `section_d.net_revenue[-1]`). Read-only; GreenNode and RM must never write to it.
- **`DERIVED_FROM`**: Value deterministically computed by Python code from source facts (e.g. financial ratios, MB09 outputs, RORWA outputs). GreenNode CANNOT extract or overwrite.
- **`RELATED_DISTINCT`**: Concepts that relate to each other or reconcile, but represent fundamentally distinct business facts. They **MUST NOT share a canonical path or be automatically aliased by position**.

### Key Semantic Distinctions:
1. **Charter Capital vs. Shareholder Equity (`RELATED_DISTINCT`)**:
   - `customer.charter_capital`: Total company registered charter capital (tổng vốn điều lệ đăng ký của doanh nghiệp trên ĐKKD).
   - `section_c.shareholders[i].val`: One individual shareholder's contributed/registered equity value.
   - **Reconciliation rule**: They are reconciled via $\sum \text{shareholders}[*].\text{val} = \text{customer.charter_capital}$, but MUST NOT share a canonical path. No automatic alias adapter between them.
2. **Legal Representative vs. Executive Management (`RELATED_DISTINCT`)**:
   - `customer.legal_rep_name`: Statutory legal representative named on ĐKKD.
   - `section_c.management[i].name`: Members of executive management team (HĐQT, Ban Giám đốc, Kế toán trưởng).
   - **Rule**: Never map by list position (e.g. `management[0]`). Equivalence requires explicit source evidence.
3. **Parent Group vs. Direct Owner (`RELATED_DISTINCT`)**:
   - `customer.parent_group`: Corporate group affiliation (Tập đoàn / Tổng công ty).
   - `section_c.parent_company_or_owner`: Direct majority/controlling owner documented with equity stake.
   - **Rule**: Documented and stored separately. Only linked when proven identical by legal governance documents.
4. **Revenue Series (`LEGACY_ALIAS` vs Canonical)**:
   - `section_d.net_revenue`: The **ONLY** canonical revenue series (3-year array in triệu VND).
   - `customer.revenue_2025`: Legacy compatibility only. `CanonicalAdapter` reads it as fallback with a warning, but GreenNode and RM must NEVER write to it.

---

## 3. Section A Contract — Customer / Legal Identity

| Canonical Field | Type | Unit | Required? | Primary Source | Extracted by GreenNode? | Owner | Consumed By |
|---|---|---|---|---|---|---|---|
| `customer.name` | `str` | - | Required | ĐKKD / Điều lệ | Yes | `SOURCE_FACT` | Section A, B, C, D, E renderers, MB07 header |
| `customer.short_name` | `str` | - | Optional | ĐKKD / Điều lệ | Yes | `SOURCE_FACT` | Section A, B, C renderers |
| `customer.tax_code` | `str` | - | Required | ĐKKD / Đăng ký thuế | Yes | `SOURCE_FACT` | Section A `company.registration_no`, CIC query |
| `customer.cif` | `str` | - | Required (KH hiện hữu) | Core T24 / RM Input | No | `RM_INPUT` | Section A `relationship.cif` |
| `customer.segment` | `str` | - | Required | Phân loại MSB | No | `RM_INPUT` | Section A `relationship.segment` (LC / SME / EB) |
| `customer.parent_group` | `str` | - | Optional | ĐKKD / Điều lệ / BCTC | Yes | `SOURCE_FACT` | Section A `company.group_name` |
| `customer.established_year` | `str` | - | Optional | ĐKKD | Yes | `SOURCE_FACT` | Section A `company.operation_start_date_or_year` |
| `customer.address` | `str` | - | Required | ĐKKD | Yes | `SOURCE_FACT` | Section A `company.registered_address` |
| `customer.legal_rep_name` | `str` | - | Required | ĐKKD | Yes | `SOURCE_FACT` | Section A `company.legal_representative.name` |
| `customer.legal_rep_title` | `str` | - | Required | ĐKKD | Yes | `SOURCE_FACT` | Section A `company.legal_representative.title` |
| `customer.charter_capital` | `float` | triệu VND | Required | ĐKKD / BCTC | Yes | `SOURCE_FACT` | Section A `capital.registered_capital`, Section D, MB09 |
| `customer.rating_grade` | `str` | - | Optional | Hệ thống XHTD nội bộ | No | `RM_INPUT` | Section A `internal_rating.grade` |
| `customer.rating_score` | `float` | điểm | Optional | Hệ thống XHTD nội bộ | No | `RM_INPUT` | Section A `internal_rating.score` |
| `customer.restricted_subject` | `str` | - | Optional | RM rà soát tuân thủ | No | `RM_INPUT` | Section A `compliance.restricted_credit_subject` |
| `customer.esg_status` | `str` | - | Optional | RM rà soát ESG | No | `RM_INPUT` | Section A `compliance.esg_assessment_required` |

*Notes*:
- `customer.tax_code` is strictly a string preserving leading zeros.
- `customer.charter_capital` is normalized and stored in **triệu VND**.

---

## 4. Section B Contract — Credit Request (RM Intent)

Section B represents the credit request and RM intent. **GreenNode must NOT autonomously decide credit limits, interest pricing, loan tenor, or collateral acceptance.**

| Canonical Field | Type | Unit | Required? | Owner | Consumed By |
|---|---|---|---|---|---|
| `section_b.selected_needs` | `list[str]` | - | Required | `RM_INPUT` | Section B engine dispatch (`2.1_vay_vld_han_muc`, `2.6_bao_lanh`, etc.) |
| `section_b.total_limit` | `float` | triệu VND | Required | `RM_INPUT` | Section B aggregate, Section A proposed limit, RORWA engine |
| `section_b.loan_limit` | `float` | triệu VND | Required | `RM_INPUT` | Section B loan limit, Section A unsecured limit, MB09 engine |
| `section_b.guarantee_limit` | `float` | triệu VND | Optional | `RM_INPUT` | Section B guarantee limit, RORWA engine |
| `section_b.loan_purpose` | `str` | - | Required | `RM_INPUT` | Section B narrative, MB07 loan contract terms |
| `section_b.loan_tenor_months`| `int` | tháng | Required | `RM_INPUT` | Section B terms, promissory note rules |
| `section_b.disbursement_method`| `str` | - | Required | `RM_INPUT` | Section B disbursement conditions |
| `section_b.collateral_type` | `str` | - | Required | `RM_INPUT` | Section B security description (Tín chấp / TSBĐ) |
| `section_b.cashflow_commitment_pct` | `float` | % | Optional | `RM_INPUT` | Section B cashflow commitment covenant |
| `section_b.cashflow_direct_pct` | `float` | % | Optional | `RM_INPUT` | Section B direct cashflow covenant |
| `section_b.ewt_conditions` | `str` | - | Optional | `RM_INPUT` | Section B early warning trigger conditions |

---

## 5. Section C Contract — Business Profile & Operations

Structured facts are strictly preferred over unparsed narrative blobs.

| Canonical Field | Type | Unit | Owner | Primary Source | Consumed By |
|---|---|---|---|---|---|
| `section_c.history_narrative` | `str` | - | `AI_NARRATIVE` / `SOURCE_FACT` | Hồ sơ giới thiệu DN / Điều lệ | Section C Mục 1 Lịch sử hình thành |
| `section_c.shareholders` | `list[dict]` | - | `SOURCE_FACT` | ĐKKD / Điều lệ / BCTC | Section C Mục 2.1 Bảng Cổ đông lớn |
| `section_c.shareholders[i].name` | `str` | - | `SOURCE_FACT` | ĐKKD | Tên cổ đông |
| `section_c.shareholders[i].tax_code` | `str` | - | `SOURCE_FACT` | ĐKKD | MST / CCCD |
| `section_c.shareholders[i].pct` | `float` | % | `SOURCE_FACT` | ĐKKD | Tỷ lệ sở hữu |
| `section_c.shareholders[i].val` | `float` | triệu VND | `SOURCE_FACT` | ĐKKD | Giá trị vốn góp (Distinct from Total Charter Capital) |
| `section_c.management` | `list[dict]` | - | `SOURCE_FACT` | ĐKKD / Bổ nhiệm | Section C Mục 2.2 Ban điều hành (Distinct from Legal Rep) |
| `section_c.parent_company_or_owner` | `str` | - | `SOURCE_FACT` | ĐKKD / BCTC | Section C Mục 2.1 (Distinct from Parent Group) |
| `section_c.business_model` | `str` | - | `SOURCE_FACT` / `RM_INPUT` | BCTC / RM khảo sát | Section C phân loại mô hình (THUONG_MAI, SAN_XUAT, HON_HOP) |
| `section_c.products` | `list[dict]` | `share: %` | `SOURCE_FACT` | Báo cáo kinh doanh | Section C Mục 3 Sản phẩm chủ lực |
| `section_c.suppliers` | `list[dict]` | `share: %` | `SOURCE_FACT` | Hợp đồng / BCTC thuyết minh | Section C Bảng 04 Top Nhà cung cấp |
| `section_c.customers` | `list[dict]` | `share: %` | `SOURCE_FACT` | Hợp đồng / Doanh số đầu ra | Section C Bảng 06 Top Khách hàng |
| `section_c.rm_management_assessment`| `str` | - | `AI_NARRATIVE` | Đánh giá RM / AI tổng hợp | Section C nhận xét lãnh đạo |
| `section_c.rm_market_position` | `str` | - | `AI_NARRATIVE` | Đánh giá thị trường | Section C nhận xét vị thế thị trường |
| `section_c.rm_risk_mitigation` | `str` | - | `AI_NARRATIVE` | Biện pháp giảm thiểu | Section C nhận xét quản trị rủi ro |

---

## 6. Section D Contract — Financial Statements & Metrics

### Strict Boundary: RAW FACTS vs CALCULATED METRICS
- **RAW FINANCIAL FACTS**: Extracted from financial reports (BCTC). Unit is **triệu VND**. GreenNode is eligible to extract these facts.
- **CALCULATED METRICS**: Deterministically computed by Python code. **GreenNode CANNOT overwrite or invent calculated metrics.**

| Canonical Field | Type | Unit | Classification | Owner | Description |
|---|---|---|---|---|---|
| `section_d.auditor` | `str` | - | Raw Governance | `SOURCE_FACT` | Đơn vị kiểm toán BCTC |
| `section_d.years` | `list[str]` | - | Period Structure | `SOURCE_FACT` | Danh sách các năm BCTC (vd: `["2023", "2024", "2025"]`) |
| `section_d.net_revenue` | `list[float]` | triệu VND | RAW FACT | `SOURCE_FACT` | Doanh thu thuần 3 năm (The ONLY canonical revenue series) |
| `section_d.cogs` | `list[float]` | triệu VND | RAW FACT | `SOURCE_FACT` | Giá vốn hàng bán 3 năm |
| `section_d.gross_profit` | `list[float]` | triệu VND | RAW FACT | `SOURCE_FACT` | Lợi nhuận gộp 3 năm |
| `section_d.financial_income` | `list[float]` | triệu VND | RAW FACT | `SOURCE_FACT` | Doanh thu hoạt động tài chính |
| `section_d.financial_expenses` | `list[float]` | triệu VND | RAW FACT | `SOURCE_FACT` | Chi phí tài chính |
| `section_d.interest_expenses` | `list[float]` | triệu VND | RAW FACT | `SOURCE_FACT` | Chi phí lãi vay |
| `section_d.sga_expenses` | `list[float]` | triệu VND | RAW FACT | `SOURCE_FACT` | Chi phí bán hàng & quản lý DN |
| `section_d.net_profit_before_tax` | `list[float]` | triệu VND | RAW FACT | `SOURCE_FACT` | Lợi nhuận trước thuế |
| `section_d.net_profit_after_tax` | `list[float]` | triệu VND | RAW FACT | `SOURCE_FACT` | Lợi nhuận sau thuế |
| `section_d.current_assets` | `list[float]` | triệu VND | RAW FACT | `SOURCE_FACT` | Tài sản ngắn hạn |
| `section_d.cash` | `list[float]` | triệu VND | RAW FACT | `SOURCE_FACT` | Tiền & tương đương tiền |
| `section_d.receivables` | `list[float]` | triệu VND | RAW FACT | `SOURCE_FACT` | Phải thu ngắn hạn |
| `section_d.inventories` | `list[float]` | triệu VND | RAW FACT | `SOURCE_FACT` | Hàng tồn kho |
| `section_d.total_assets` | `list[float]` | triệu VND | RAW FACT | `SOURCE_FACT` | Tổng tài sản |
| `section_d.total_liabilities` | `list[float]` | triệu VND | RAW FACT | `SOURCE_FACT` | Nợ phải trả (Mã 300) |
| `section_d.current_liabilities` | `list[float]` | triệu VND | RAW FACT | `SOURCE_FACT` | Nợ ngắn hạn (Mã 310) |
| `section_d.short_term_debt` | `list[float]` | triệu VND | RAW FACT | `SOURCE_FACT` | Vay & nợ thuê tài chính ngắn hạn (Mã 320) |
| `section_d.equity` | `list[float]` | triệu VND | RAW FACT | `SOURCE_FACT` | Vốn chủ sở hữu (Mã 400) |
| **gross_profit_margin_pct** | `list[float]` | % | CALCULATED | `DERIVED_PYTHON` | Biên lợi nhuận gộp = `gross_profit / net_revenue * 100` |
| **current_ratio** | `list[float]` | lần | CALCULATED | `DERIVED_PYTHON` | Tỷ số thanh toán hiện hành = `current_assets / current_liabilities` (hoặc fallback `short_term_debt`) |
| **quick_ratio** | `list[float]` | lần | CALCULATED | `DERIVED_PYTHON` | Tỷ số thanh toán nhanh = `(current_assets - inventories) / current_liabilities` (hoặc fallback `short_term_debt`) |
| **cash_ratio** | `list[float]` | lần | CALCULATED | `DERIVED_PYTHON` | Tỷ số thanh toán tức thời = `cash / current_liabilities` (hoặc fallback `short_term_debt`) |
| **debt_to_equity** | `list[float]` | lần | CALCULATED | `DERIVED_PYTHON` | Nợ / Vốn CSH = `total_liabilities / equity` (hoặc `(total_assets - equity) / equity`) |
| **dscr_icr** | `list[float]` | lần | CALCULATED | `DERIVED_PYTHON` | Khả năng trả lãi = `EBIT / interest_expenses` |
| **ros** | `list[float]` | % | CALCULATED | `DERIVED_PYTHON` | Tỷ suất LNST/Doanh thu = `net_profit_after_tax / net_revenue * 100` |
| **roe** | `list[float]` | % | CALCULATED | `DERIVED_PYTHON` | Tỷ suất LNST/VCSH = `net_profit_after_tax / equity * 100` |

---

## 7. MB09 & RORWA Ownership Boundary

Both engines are **100% DETERMINISTIC PYTHON**. Their outputs are strictly **`DERIVED_PYTHON`** and must NEVER be overwritten by GreenNode.

### MB09 Working Capital Engine (`CreditDemandEngine`)
- **Inputs**:
  - `net_revenue_plan` (VND) $\leftarrow$ from Section D or RM Plan
  - `cogs_plan` (VND) $\leftarrow$ from Section D or RM Plan
  - `operating_cost_plan` (VND) $\leftarrow$ from Section D SGA
  - `dio`, `dso`, `dpo` (days) $\leftarrow$ RM business cycle input
  - `equity_participation` (VND) $\leftarrow$ RM input
  - `other_debt` (VND) $\leftarrow$ from Section E (`total_debt_other_banks_excluding_msb * 1e6`)
- **Outputs (All `DERIVED_PYTHON`)**:
  - `total_operating_expense`, `ccc_days`, `turns_per_year`, `working_capital_demand`, `net_working_capital_demand`, `loan_limit_total`, `loan_limit_msb`, `lc_limit`, `guarantee_limit`, `total_credit_facility_msb`.

### RORWA / TORWA Engine (`RorwaEngine`)
- **Inputs**:
  - `loan_limit`, `lc_limit`, `guarantee_limit` (VND) $\leftarrow$ from Section B
  - Drawdown & pricing parameters $\leftarrow$ MSB policy parameters
- **Outputs (All `DERIVED_PYTHON`)**:
  - `total_rwa`, `total_nii`, `total_non_nii`, `total_income`, `opex`, `credit_cost_el`, `net_deal_profit`, `torwa` (%), `rorwa` (%), `torwa_passed` (bool), `rorwa_passed` (bool).

---

## 8. Section E Contract — CIC & Credit Relations

| Canonical Field | Type | Unit | Required? | Owner | Consumed By |
|---|---|---|---|---|---|
| `section_e.cic_date` | `str` | DD/MM/YYYY | Required | `SOURCE_FACT` | Báo cáo CIC ngày tra cứu |
| `section_e.msb_outstanding` | `float` | triệu VND | Required | `SOURCE_FACT` | Dư nợ hiện hữu tại MSB (Section A, Section E) |
| `section_e.history_status` | `str` | - | Required | `SOURCE_FACT` | Lịch sử nhóm nợ 12/24 tháng |
| `section_e.rm_credit_assessment`| `str` | - | Required | `AI_NARRATIVE` | Nhận xét uy tín giao dịch của RM |
| `section_e.relations` | `list[dict]` | triệu VND | Optional | `SOURCE_FACT` | Bảng 07 quan hệ tín dụng tại từng TCTD |

---

## 9. Units Contract Table

| Domain / Concept | Canonical Field(s) | Canonical Unit | Alternate Units (Converted at Ingestion) |
|---|---|---|---|
| Customer Capital | `customer.charter_capital` | **triệu VND** | VND (tự động chia $10^6$), tỷ đồng (nhân $10^3$) |
| Facility Limits | `section_b.total_limit`, `loan_limit`, `guarantee_limit` | **triệu VND** | In proposal UI/canonical state: triệu VND. Engine B internal: VND ($* 10^6$). |
| Financial Statement Items | `section_d.net_revenue`, `cogs`, `gross_profit`, `assets`, `debt`, `equity` | **triệu VND** | VND (chia $10^6$) |
| Financial Ratios | `current_ratio`, `quick_ratio`, `cash_ratio`, `debt_to_equity`, `dscr_icr` | **lần (times)** | Float ratio |
| Profitability Ratios | `ros`, `roe`, `gross_profit_margin_pct` | **%** | Percentage (e.g. 5.20 = 5.20%) |
| Business Cycle | `dio`, `dso`, `dpo`, `ccc_days` | **ngày (days)** | Days |
| Working Capital Turns | `turns_per_year` | **vòng/năm** | Turns per year |
| Loan Tenor | `loan_tenor_months` | **tháng (months)** | Months |
| Performance Metrics | `torwa`, `rorwa` | **%** | Percentage |

---

## 10. Null & Missing Value Policy

- **No Evidence $\to$ `None`**: When information is missing from documents or unprovided by RM, the field MUST be `None` (or absent).
- **GENUINE ZERO vs UNKNOWN**:
  - `outstanding = 0.0`: Represents a confirmed fact (e.g., zero overdue debt, zero long-term debt).
  - `outstanding = None`: Represents missing/unknown data awaiting extraction or RM input.
- **FORBIDDEN VALUES**: Never populate fake placeholders like `"N/A"`, `"--"`, `"Unknown"`, or synthetic random numbers.

---

## 11. Downstream Readiness vs. Blocking Errors

The contract validator (`validate_case_data_contract`) enforces:
1. **Blocking Structural Errors**:
   - Non-dict root or missing required containers (`customer`, `rm_metadata`, `section_b`, `section_c`, `section_d`, `section_e`).
   - Wrong scalar types (`tax_code` as integer instead of string, negative monetary amounts).
   - Array length mismatches in `section_d`.
2. **Downstream Readiness Warnings**:
   - Partial cases with `None` values are **VALID partial cases**.
   - Warnings alert RMs that downstream steps (e.g. MB09, DOCX generation) require missing fields before final execution.

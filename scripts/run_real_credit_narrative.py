# -*- coding: utf-8 -*-
"""Real Live Execution: GreenNode GLM-5.2 Credit Narrative & Verified Insights Pipeline.

Executes the full Phase 6 pipeline live against GreenNode GLM-5.2:
1. Canonical Facts -> FactPackager -> FactManifest (with SHA-256 hash).
2. FactManifest -> GLMInsightDiscoveryAgent (Live GLM-5.2) -> InsightCandidate[].
3. InsightCandidate[] -> PythonInsightVerifier (Deterministic Python) -> VerifiedInsight[].
4. VerifiedInsight[] + FactManifest -> GLMNarrativeWriterAgent (Live GLM-5.2) -> NarrativeBlock[].
5. NarrativeBlock[] -> DeterministicNarrativeValidator (Deterministic Regex & Grounding).
6. NarrativeDraftManager: Draft Record -> RM Acceptance -> Storage.
7. CreditProposalAssembler -> In-place Mutator -> MB07 DOCX Generation.
8. DOCX Verification: Confirms accepted narrative prose is present in the final document.
"""

import os
import sys
import time
import docx
from decimal import Decimal
from dotenv import load_dotenv

# Ensure root directory in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

load_dotenv()

from msb_eb_copilot.src.narrative.models import (
    FactManifest, InsightCandidate, VerifiedInsight, NarrativeBlock,
    CreditNarrativePackage, NarrativeTargetBinding, VerificationStatus
)
from msb_eb_copilot.src.narrative.fact_packager import FactPackager
from msb_eb_copilot.src.narrative.insight_verifier import PythonInsightVerifier
from msb_eb_copilot.src.narrative.validator import DeterministicNarrativeValidator
from msb_eb_copilot.src.narrative.store import NarrativeDraftManager, NARRATIVE_DRAFT_STORE
from msb_eb_copilot.src.narrative.insight_discovery import GLMInsightDiscoveryAgent
from msb_eb_copilot.src.narrative.narrative_agent import GLMNarrativeWriterAgent
from msb_eb_copilot.src.proposal_assembler import CreditProposalAssembler

from msb_eb_copilot.src.section_a.review_session import SectionAReviewSession
from msb_eb_copilot.src.section_c import (
    BusinessModelType, BlacklistStatus, ShareholderInfo, ManagementMember,
    ProductInfo, WarehouseInfo, EquipmentInfo, SupplierInfo, CustomerInfo, SectionCData
)
from msb_eb_copilot.src.section_d import (
    AccountingGovernance, IncomeStatement3Y, BalanceSheet3Y,
    CashFlowStatement3Y, FinancialRatios3Y, PnLAnalysis, SectionDData
)
from msb_eb_copilot.src.section_e import (
    DebtGroup, CreditInstitutionRelation, SectionEData, link_section_e_to_session_a
)
from msb_eb_copilot.agents.agent_section_b import AgentSectionB


def setup_psd_canonical_data():
    """Builds canonical facts for DEMO DISTRIBUTION JSC."""
    case_id = "CASE-2026-PSD"
    
    # Phân hệ E
    data_e = SectionEData(
        customer_name="CÔNG TY CỔ PHẦN PHÂN PHỐI DEMO (PSD)",
        cic_report_date="20/01/2026",
        relations=[
            CreditInstitutionRelation(1, "Vietcombank - CN TP.HCM", 600000.0, 350000.0, 0.0, 0.0, 350000.0, "HĐTG, Phải thu MWG/FPT", DebtGroup.NHOM_1_DU_TIEU_CHUAN),
            CreditInstitutionRelation(2, "BIDV - CN TP.HCM", 500000.0, 280000.0, 0.0, 0.0, 280000.0, "HĐTG, Hàng tồn kho", DebtGroup.NHOM_1_DU_TIEU_CHUAN),
            CreditInstitutionRelation(3, "VietinBank - CN TP.HCM", 400000.0, 220000.0, 0.0, 0.0, 220000.0, "HĐTG, Hàng điện tử", DebtGroup.NHOM_1_DU_TIEU_CHUAN),
            CreditInstitutionRelation(4, "MSB - CN TP.HCM", 250000.0, 250000.0, 0.0, 0.0, 250000.0, "Tín chấp & HĐTG", DebtGroup.NHOM_1_DU_TIEU_CHUAN),
        ],
        loan_outstanding_at_msb_million=250000.0,
        total_credit_exposure_at_msb_million=400000.0,
        is_overdue_12m=False,
        rm_credit_assessment="Khách hàng có lịch sử trả nợ mẫu mực tại các TCTD lớn, không có nợ quá hạn trong 12 tháng qua."
    )

    # Phân hệ A
    session_a = SectionAReviewSession(case_id)
    session_a.confirm_fact_with_rm("company.legal_name", "CÔNG TY CỔ PHẦN PHÂN PHỐI DEMO")
    session_a.confirm_fact_with_rm("company.short_name", "PSD")
    session_a.confirm_fact_with_rm("company.legal_type", "Công ty Cổ phần")
    session_a.confirm_fact_with_rm("company.group_name", "TỔNG CÔNG TY CỔ PHẦN DỊCH VỤ TỔNG HỢP DẦU KHÍ")
    session_a.confirm_fact_with_rm("company.registered_address", "P.207, Tòa nhà PetroVietnam, Số 1-5 Lê Duẩn, Phường Bến Nghé, Quận 1, TP. Hồ Chí Minh")
    session_a.confirm_fact_with_rm("company.registration_no", "0100000000")
    session_a.confirm_fact_with_rm("company.registration_issue_date", "15/12/2023")
    session_a.confirm_fact_with_rm("company.registration_issue_place", "Sở Kế hoạch và Đầu tư TP. Hồ Chí Minh")
    session_a.confirm_fact_with_rm("company.operation_start_date_or_year", "2008")
    session_a.confirm_fact_with_rm("company.legal_representative.name", "Đại diện Demo")
    session_a.confirm_fact_with_rm("company.legal_representative.title", "Giám đốc")
    session_a.set_rm_selected("relationship.customer_status", "KH_HIEN_HUU")
    session_a.set_rm_provided("relationship.cif", "DEMO001")
    session_a.set_rm_selected("relationship.segment", "LC")
    session_a.set_rm_selected("compliance.restricted_credit_subject", "KHONG")
    session_a.set_rm_selected("compliance.esg_assessment_required", "BAT_BUOC_DANH_GIA")
    session_a.set_rm_selected("credit_relation.regulatory_limit_status", "TRONG_GIOI_HAN")
    session_a.set_rm_selected("approval.authority", "HĐTD&ĐT")
    session_a.set_rm_selected("proposal.request_type", "TAI_CAP")
    session_a.confirm_fact_with_rm("financial.latest_net_revenue", 7819398, unit="triệu đồng")
    session_a.confirm_fact_with_rm("financial.latest_revenue_year", 2025)
    session_a.set_rm_provided("proposal.credit_request_representative.name", "Đại diện Demo")
    session_a.set_rm_provided("proposal.credit_request_representative.title", "Giám đốc")
    session_a.set_rm_provided("business.primary_industry.code_level_5", "46520")
    session_a.set_rm_provided("business.primary_industry.name", "Bán buôn thiết bị và linh kiện điện tử, viễn thông")
    session_a.set_rm_provided("business.primary_industry.revenue_share_pct", 95)
    session_a.set_rm_provided("business.main_products", ("Điện thoại Samsung & Apple", "Máy tính xách tay & máy tính bảng", "Thiết bị viễn thông & tin học"))
    session_a.confirm_fact_with_rm("capital.registered_capital", 518279, unit="triệu đồng")
    session_a.confirm_fact_with_rm("capital.paid_in_capital", 518279, unit="triệu đồng")
    session_a.confirm_fact_with_rm("capital.paid_in_capital_as_of", "2025-12-31")
    session_a.set_rm_provided("internal_rating.case_id", "XHTD-2026-PSD")
    session_a.set_rm_provided("internal_rating.grade", "AAA")
    session_a.set_rm_provided("internal_rating.score", Decimal("95.0"))
    session_a.set_rm_provided("approval.existing_limit.total", 500000, unit="triệu đồng")
    session_a.set_rm_provided("approval.existing_limit.unsecured", 100000, unit="triệu đồng")
    session_a.set_rm_provided("approval.proposed_limit.total", 650000, unit="triệu đồng")
    session_a.set_rm_provided("approval.proposed_limit.unsecured", 120000, unit="triệu đồng")
    session_a.set_rm_provided("approval.aggregate_limit.total", 650000, unit="triệu đồng")
    session_a.set_rm_provided("approval.aggregate_limit.unsecured", 120000, unit="triệu đồng")
    session_a.set_rm_provided("approval.previous_approval_period", "Kỳ phê duyệt năm 2024")
    link_section_e_to_session_a(data_e, session_a)

    # Phân hệ B
    raw_b = {
        "selected_needs": ["2.1_vay_vld_han_muc", "2.5_lc_nho_thu"],
        "general_facility_summary": {"currency": "VND", "credit_proposal_type": "Tái cấp"},
        "facilities_data": {
            "need_2_1": {
                "proposal_type": "Tái cấp tăng",
                "approved_limit_vnd": 250000.0,
                "proposed_limit_vnd": 300000.0,
                "purpose": "Bổ sung vốn lưu động phân phối điện thoại thông minh, laptop và thiết bị tin học",
                "duration_months": 12,
                "effective_date_rule": "Kể từ ngày ký HĐTD",
                "max_promissory_note_duration_months": 4,
                "lending_interest_rate": "Theo quy định MSB từng thời kỳ",
                "disbursement_method": "Chuyển khoản trực tiếp cho bên thụ hưởng",
                "repayment_period": "Lãi trả hàng tháng, gốc trả cuối kỳ",
            },
            "need_2_5": {
                "issuance_structure": "Hạn mức",
                "product_type": "L/C",
                "term_classification": "Ngắn hạn",
                "proposal_type": "Tái cấp tăng",
                "approved_limit_vnd": 250000.0,
                "proposed_limit_vnd": 350000.0,
                "purpose": "Phát hành L/C nhập khẩu thiết bị viễn thông và sản phẩm công nghệ",
                "facility_duration_months": 12,
                "effective_date_rule": "Kể từ ngày ký HĐTD",
                "lc_collection_type": "L/C trả ngay / UPAS tối đa 03 tháng",
                "min_margin_cash_percentage": "0%",
                "financing_rate_per_lc_value": "100%",
                "lc_fee": "Theo biểu phí MSB",
            }
        }
    }
    processed_b = AgentSectionB().validate_and_calculate(raw_b)

    # Phân hệ C
    data_c = SectionCData(
        customer_name="CÔNG TY CỔ PHẦN PHÂN PHỐI DEMO (PSD)",
        history_narrative="Thành lập năm 2008 từ phân hệ kinh doanh của DEMO_GROUP, là nhà phân phối ủy quyền hàng đầu của Samsung, Apple, Dell tại Việt Nam.",
        parent_company_or_owner="TẬP ĐOÀN DEMO nắm 79,89% vốn",
        major_shareholders=[
            ShareholderInfo(1, "TỔNG CÔNG TY DEMO", "0100109789", 79.89, 414053.0),
            ShareholderInfo(2, "Các cổ đông đại chúng khác", "N/A", 20.11, 104226.0),
        ],
        blacklist_status=BlacklistStatus.KHONG_VI_PHAM,
        management_members=[
            ManagementMember("Giám đốc điều hành", "Đại diện Demo", "Thạc sĩ Quản trị, hơn 20 năm kinh nghiệm ngành viễn thông", 16),
            ManagementMember("Kế toán trưởng", "Nguyễn Thị Thanh Hà", "Kế toán trưởng kỳ cựu thuộc Petrovietnam", 12),
        ],
        business_model=BusinessModelType.THUONG_MAI,
        products=[
            ProductInfo(1, "Điện thoại thông minh & Máy tính bảng", "Samsung, Apple", 65.0),
            ProductInfo(2, "Máy tính xách tay & Màn hình", "Dell, HP, Lenovo", 25.0),
            ProductInfo(3, "Linh kiện & Thiết bị viễn thông", "Nhiều thương hiệu", 10.0),
        ],
        production_technology_summary="Mô hình phân phối chuyên nghiệp B2B & B2Retail với hệ thống ERP SAP S/4HANA và phân hệ quản lý kho tự động WMS.",
        warehouses=[
            WarehouseInfo(1, "Tổng kho miền Nam", "KCN Cát Lái, TP. Thủ Đức, TP.HCM", 15000.0, "Thuê dài hạn", "Chứa 500.000 thiết bị"),
            WarehouseInfo(2, "Tổng kho miền Bắc", "KCN Đài Tư, Long Biên, Hà Nội", 10000.0, "Thuê dài hạn", "Chứa 300.000 thiết bị"),
        ],
        equipments=[
            EquipmentInfo(1, "Hệ thống băng chuyền phân loại tự động", "Nhật Bản", "10.000 kiện/ngày", "95%"),
        ],
        suppliers=[
            SupplierInfo(1, "Công ty TNHH Samsung Electronics Vietnam", "Điện thoại Samsung", 42.0, "L/C UPAS 60 ngày"),
            SupplierInfo(2, "Apple Vietnam LLC", "iPhone, iPad, MacBook", 30.0, "TTR trả ngay / L/C"),
            SupplierInfo(3, "Dell Global B.V.", "Máy tính xách tay & PC", 18.0, "L/C 90 ngày"),
        ],
        customers=[
            CustomerInfo(1, "CTCP Đầu tư Thế Giới Di Động (MWG)", "Điện thoại & Laptop", 32.0, "Công nợ 30 ngày có bảo lãnh"),
            CustomerInfo(2, "CTCP Bán lẻ Kỹ thuật số FPT (FPT Shop)", "Thiết bị số", 22.0, "Công nợ 20 ngày"),
            CustomerInfo(3, "Hệ thống đại lý bán lẻ toàn quốc", "Thiết bị công nghệ", 25.0, "Thanh toán trả trước"),
        ],
        market_share_estimate="Top 3 nhà phân phối công nghệ thông tin lớn nhất Việt Nam (thị phần ~25% điện thoại Samsung và laptop Dell)",
        top_competitors=["Synnex FPT", "Digiworld (DGW)", "Viettel Distribution"],
        competitive_advantages="Hệ thống logistics toàn quốc, tài chính vững mạnh từ Petrovietnam, quan hệ độc quyền với các hãng công nghệ lớn.",
        rm_supply_chain_assessment="Mặc dù Samsung chiếm 42% đầu vào và MWG chiếm 32% đầu ra, đây là đặc thù ngành phân phối ICT cấp 1; các đối tác đều là tập đoàn hàng đầu thế giới và chuỗi bán lẻ số 1 Việt Nam với rủi ro công nợ cực thấp.",
        rm_credit_risk_mitigation="Kiểm soát dòng tiền thanh toán từ MWG và FPT Shop chảy trực tiếp về tài khoản PSD tại MSB."
    )

    # Phân hệ D
    data_d = SectionDData(
        customer_name="CÔNG TY CỔ PHẦN PHÂN PHỐI DEMO (PSD)",
        governance=AccountingGovernance(
            mandatory_audit_by_law="Công ty đại chúng quy mô lớn bắt buộc kiểm toán BCTC theo luật",
            audit_firm_name="Công ty TNHH Deloitte Việt Nam",
            audited_years="2022, 2023, 2024 và BCTC soát xét 2025",
            audit_opinion="Ý kiến chấp thuận toàn phần không có ngoại trừ."
        ),
        income_statement=IncomeStatement3Y(
            years=["2023", "2024", "2025"],
            net_revenue=[6755948.0, 5702529.0, 7819398.0],
            cogs=[6480966.0, 5381601.0, 7412589.0],
            gross_profit=[274982.0, 320928.0, 406809.0],
            gross_profit_margin_pct=[4.07, 5.63, 5.20],
            financial_income=[35200.0, 41500.0, 48200.0],
            financial_expenses=[95400.0, 112000.0, 125000.0],
            interest_expenses=[72100.0, 85400.0, 92000.0],
            sga_expenses=[128600.0, 138250.0, 162250.0],
            net_profit_before_tax=[86182.0, 112178.0, 167759.0],
            net_profit_after_tax=[68867.0, 89729.0, 134201.0]
        ),
        pnl_analysis=PnLAnalysis(
            revenue_analysis="Doanh thu năm 2025 bứt phá đạt 7.819,4 tỷ đồng nhờ mở rộng phân phối các dòng sản phẩm iPhone thế hệ mới.",
            gross_margin_analysis="Biên lợi nhuận gộp duy trì trên 5,2%, phản ánh hiệu quả đàm phán chiết khấu thương mại tốt.",
            net_profit_and_dividends_analysis="Lợi nhuận sau thuế năm 2025 đạt 134,2 tỷ đồng, tăng trưởng so với năm 2024."
        ),
        balance_sheet=BalanceSheet3Y(
            years=["2023", "2024", "2025"],
            current_assets=[3034184.0, 2723355.0, 4600702.0],
            cash_and_equivalents=[61883.0, 103169.0, 150200.0],
            short_term_investments=[450000.0, 380000.0, 520000.0],
            accounts_receivable=[1120500.0, 985200.0, 1850000.0],
            inventories=[1350000.0, 1210000.0, 2010000.0],
            other_current_assets=[51801.0, 44986.0, 70502.0],
            non_current_assets=[94772.0, 87081.0, 82721.0],
            fixed_assets=[75000.0, 68000.0, 62000.0],
            construction_in_progress=[5000.0, 4500.0, 6000.0],
            total_assets=[3128956.0, 2810436.0, 4683423.0],
            liabilities=[2567237.0, 2212610.0, 3954080.0],
            short_term_debt=[1250000.0, 1100000.0, 2250000.0],
            long_term_debt=[0.0, 0.0, 0.0],
            owner_equity=[561718.0, 597826.0, 729343.0],
            charter_capital=[518279.0, 518279.0, 518279.0]
        ),
        cash_flow=CashFlowStatement3Y(
            years=["2023", "2024", "2025"],
            ocf_cash_from_operations=[86820.0, 112334.0, 145000.0],
            icf_cash_from_investing=[-15200.0, -18500.0, -22000.0],
            fcf_cash_from_financing=[-75000.0, -92000.0, -85000.0],
            net_cash_flow=[-3380.0, 1834.0, 38000.0],
            cash_beginning=[65263.0, 61883.0, 103169.0],
            cash_ending=[61883.0, 103169.0, 150200.0],
            cash_flow_analysis="Dòng tiền từ hoạt động kinh doanh (OCF) duy trì dương liên tục qua các năm."
        ),
        ratios=FinancialRatios3Y(
            years=["2023", "2024", "2025"],
            current_ratio=[1.18, 1.23, 1.16],
            quick_ratio=[0.66, 0.68, 0.66],
            cash_ratio=[0.20, 0.22, 0.17],
            debt_to_equity=[4.57, 3.70, 5.42],
            total_debt_to_equity=[2.23, 1.84, 3.09],
            dscr_icr=[1.92, 2.31, 2.82],
            ros=[1.02, 1.57, 1.72],
            roe=[12.26, 15.01, 18.40]
        )
    )

    case_data = {
        "id": case_id,
        "name": "CÔNG TY CỔ PHẦN PHÂN PHỐI DEMO",
        "customer": {
            "name": "CÔNG TY CỔ PHẦN PHÂN PHỐI DEMO",
            "short_name": "PSD",
            "tax_code": "0100000000",
            "established_year": 2008,
            "address": "P.207, Tòa nhà PetroVietnam, Số 1-5 Lê Duẩn, Phường Bến Nghé, Quận 1, TP. Hồ Chí Minh",
            "charter_capital": 518279.0,
            "rating_grade": "AAA",
            "rating_score": 95.0,
        },
        "rm_metadata": {
            "unit_name": "ĐVKD TP.HCM",
            "rm_name": "Trần Văn RM",
            "rm_phone": "0901234567",
            "manager_name": "Lê Văn Trưởng phòng",
        },
        "section_b": {
            "total_limit": 650000.0,
            "loan_limit": 300000.0,
            "guarantee_limit": 350000.0,
            "loan_purpose": "Bổ sung vốn lưu động phân phối điện thoại thông minh, laptop và thiết bị tin học",
            "collateral_type": "Tín chấp & HĐTG",
            "cashflow_commitment_pct": 80.0,
            "cashflow_direct_pct": 50.0,
        },
        "section_c": {
            "business_model": "THUONG_MAI",
            "main_products": "Điện thoại Samsung & Apple, Laptop Dell, Thiết bị viễn thông",
            "market_share_position": "Top 3 nhà phân phối công nghệ thông tin lớn nhất Việt Nam",
            "target_customers": "CTCP Đầu tư Thế Giới Di Động (MWG), FPT Shop",
            "warehouses": [
                {"name": "Tổng kho miền Nam", "location": "KCN Cát Lái, TP. Thủ Đức, TP.HCM", "area_sqm": 15000.0},
                {"name": "Tổng kho miền Bắc", "location": "KCN Đài Tư, Long Biên, Hà Nội", "area_sqm": 10000.0}
            ]
        },
        "section_d": {
            "years": ["2023", "2024", "2025"],
            "net_revenue": [6755948.0, 5702529.0, 7819398.0],
            "cogs": [6480966.0, 5381601.0, 7412589.0],
            "gross_profit": [274982.0, 320928.0, 406809.0],
            "financial_expenses": [95400.0, 112000.0, 125000.0],
            "interest_expenses": [72100.0, 85400.0, 92000.0],
            "operating_expenses": [128600.0, 138250.0, 162250.0],
            "net_profit": [68867.0, 89729.0, 134201.0],
            "current_assets": [3034184.0, 2723355.0, 4600702.0],
            "cash_and_equivalents": [61883.0, 103169.0, 150200.0],
            "receivables": [1120500.0, 985200.0, 1850000.0],
            "inventories": [1350000.0, 1210000.0, 2010000.0],
            "total_assets": [3128956.0, 2810436.0, 4683423.0],
            "liabilities": [2567237.0, 2212610.0, 3954080.0],
            "short_term_debt": [1250000.0, 1100000.0, 2250000.0],
            "equity": [561718.0, 597826.0, 729343.0],
            "ocf": [86820.0, 112334.0, 145000.0]
        },
        "section_e": {
            "cic_date": "20/01/2026",
            "msb_outstanding": 250000.0,
            "history_status": "Nhóm 1 (Đủ tiêu chuẩn)",
            "relations": [
                {
                    "bank_name": "Ngân hàng TMCP Ngoại thương Việt Nam (Vietcombank)",
                    "short_term_limit_million_vnd": 600000.0,
                    "short_term_debt_vnd_million": 350000.0,
                    "debt_group": "NHOM_1_DU_TIEU_CHUAN"
                },
                {
                    "bank_name": "Ngân hàng TMCP Đầu tư và Phát triển Việt Nam (BIDV)",
                    "short_term_limit_million_vnd": 500000.0,
                    "short_term_debt_vnd_million": 280000.0,
                    "debt_group": "NHOM_1_DU_TIEU_CHUAN"
                },
                {
                    "bank_name": "Ngân hàng TMCP Công thương Việt Nam (VietinBank)",
                    "short_term_limit_million_vnd": 400000.0,
                    "short_term_debt_vnd_million": 220000.0,
                    "debt_group": "NHOM_1_DU_TIEU_CHUAN"
                },
                {
                    "bank_name": "Ngân hàng TMCP Hàng Hải Việt Nam (MSB)",
                    "short_term_limit_million_vnd": 250000.0,
                    "short_term_debt_vnd_million": 250000.0,
                    "debt_group": "NHOM_1_DU_TIEU_CHUAN"
                }
            ]
        }
    }

    return case_id, case_data, session_a.facts, processed_b, data_c, data_d, data_e


def main():
    print("================================================================================")
    print("PHASE 6: LIVE GREENNODE GLM-5.2 CREDIT NARRATIVE & VERIFIED INSIGHT EXECUTION")
    print("================================================================================")

    api_key = os.getenv("GREENNODE_API_KEY") or os.getenv("AI_PLATFORM_API_KEY")
    base_url = os.getenv("GREENNODE_BASE_URL", "https://maas-llm-aiplatform-hcm.api.vngcloud.vn/v1")
    model = os.getenv("GREENNODE_MODEL", "z-ai/glm-5.2-hackathon")

    if not api_key:
        print("[ERROR] GREENNODE_API_KEY is not configured in .env.")
        sys.exit(1)

    print(f"[*] GreenNode Base URL : {base_url}")
    print(f"[*] GreenNode Model    : {model}")
    print("[*] GreenNode Credentials : CONFIGURED")

    # 1. SETUP CANONICAL FACTS & MANIFEST
    print("\n[STEP 1] Packaging Confirmed Canonical Facts A -> E...")
    case_id, case_data, facts_a, data_b, data_c, data_d, data_e = setup_psd_canonical_data()

    t0 = time.time()
    manifest = FactPackager.package(
        case_id=case_id,
        case_data=case_data
    )
    t_pack = time.time() - t0
    print(f" -> Compiled {len(manifest.facts)} canonical facts in {t_pack:.3f}s")
    print(f" -> Manifest Hash (SHA-256): {manifest.manifest_hash}")
    print(f" -> Data Gaps count: {len(manifest.data_gaps)}")

    # 2. LIVE INSIGHT DISCOVERY (GLM-5.2)
    print("\n[STEP 2] Executing Live GreenNode GLM-5.2 Insight Discovery Agent...")
    discovery_agent = GLMInsightDiscoveryAgent(api_key=api_key, model=model)

    t1 = time.time()
    candidates, disc_telemetry = discovery_agent.discover_insights(manifest)
    t_disc = time.time() - t1

    print(f" -> Live GLM-5.2 completed in {t_disc:.2f}s (telemetry: {disc_telemetry})")
    print(f" -> Discovered {len(candidates)} candidate insights:")
    for i, c in enumerate(candidates, 1):
        print(f"    [{i}] Type: {c.insight_type} | Metric: {c.metric} | Proposed: {c.proposed_value} {c.proposed_unit} | Trend: {c.trend.value if hasattr(c.trend, 'value') else c.trend}")
        print(f"        Facts: {c.related_fact_ids} | Period: {c.from_period} -> {c.to_period}")
        print(f"        Observation: {c.observation}")

    # 3. DETERMINISTIC PYTHON VERIFICATION
    print("\n[STEP 3] Verifying Candidate Insights with Deterministic Python Engine...")
    t2 = time.time()
    verifier = PythonInsightVerifier(manifest)
    verified_insights = verifier.verify_all(candidates)
    t_ver = time.time() - t2

    print(f" -> Python verification completed in {t_ver:.3f}s")
    status_counts = {}
    for vi in verified_insights:
        status_counts[vi.verification_status.value] = status_counts.get(vi.verification_status.value, 0) + 1
        print(f"    - [{vi.verification_status.value}] {vi.metric} ({vi.insight_type}): proposed={vi.model_proposed_value}, verified={vi.verified_value} {vi.unit} (diff={vi.difference_pct}%)")
        if vi.warnings:
            print(f"      Warnings: {vi.warnings}")
    print(f" -> Verification Summary: {status_counts}")

    # Filter only VERIFIED or CORRECTED_AND_VERIFIED insights for trusted narrative
    trusted_insights = [vi for vi in verified_insights if vi.verification_status in (VerificationStatus.VERIFIED, VerificationStatus.CORRECTED_AND_VERIFIED)]
    print(f" -> Trusted Insights forwarded to Narrative Writer: {len(trusted_insights)}")

    # 4. LIVE NARRATIVE GENERATION (GLM-5.2)
    print("\n[STEP 4] Executing Live GreenNode GLM-5.2 Narrative Generation Agent...")
    narrative_agent = GLMNarrativeWriterAgent(api_key=api_key, model=model)

    t3 = time.time()
    blocks, narr_telemetry = narrative_agent.generate_narrative(manifest, trusted_insights)
    t_narr = time.time() - t3

    print(f" -> Live GLM-5.2 narrative generation completed in {t_narr:.2f}s (telemetry: {narr_telemetry})")
    print(f" -> Generated {len(blocks)} narrative blocks:")
    for b in blocks:
        print(f"\n    [BINDING: {b.target_binding.value}] {b.title}")
        print(f"    Text: {b.text[:150]}...")
        print(f"    Facts Used: {b.facts_used}")
        print(f"    Insights Used: {b.insights_used}")

    narrative_package = CreditNarrativePackage(
        case_id=case_id,
        fact_manifest_hash=manifest.manifest_hash,
        narrative_blocks=blocks
    )

    # 5. DETERMINISTIC NARRATIVE VALIDATION
    print("\n[STEP 5] Validating Generated Narrative Blocks with Deterministic Validator...")
    validator = DeterministicNarrativeValidator(manifest, verified_insights)
    val_res = validator.validate_blocks(narrative_package.narrative_blocks)

    print(f" -> Validator result: is_valid={val_res.is_valid}")
    if not val_res.is_valid:
        print(f" -> Validation errors ({len(val_res.errors)}):")
        for err in val_res.errors:
            print(f"    * {err}")
    else:
        print(" -> All narrative blocks passed strict mathematical, causal, and grounding validation!")

    # 6. DRAFT STORE & RM ACCEPTANCE
    print("\n[STEP 6] Saving Draft to External Store & RM Acceptance Flow...")
    draft_record = NarrativeDraftManager.create_draft_record(
        case_id=case_id,
        manifest=manifest,
        insights=verified_insights,
        package=narrative_package
    )
    print(f" -> Draft Record Created: {draft_record.generation_id} (Status: {draft_record.status.value})")

    # Explicitly labeled as simulated RM acceptance for E2E testing
    accepted_record = NarrativeDraftManager.accept_narratives(
        generation_id=draft_record.generation_id,
        case_id=case_id,
        current_manifest=manifest,
        rm_reviewer_name="SIMULATED_RM_ACCEPTANCE_FOR_E2E_TEST"
    )
    print(f" -> [SIMULATED_RM_ACCEPTANCE_FOR_E2E_TEST] Accepted Blocks: {accepted_record.accepted_block_ids}")

    accepted_dict = NarrativeDraftManager.get_accepted_narratives_for_rendering(case_id)
    print(f" -> Retrieved {len(accepted_dict)} accepted narratives ready for MB07 Word rendering:")
    for k in accepted_dict:
        print(f"    - {k}: {len(accepted_dict[k])} characters")

    # 7. ASSEMBLE FULL MB07 WITH ACCEPTED NARRATIVES
    print("\n[STEP 7] Assembling Full MB07 Document with In-Place Narrative Mutation...")
    os.makedirs("output", exist_ok=True)
    out_docx = os.path.join("output", "TO_TRINH_MB07_PSD_LIVE_NARRATIVE.docx")

    assembler = CreditProposalAssembler()
    final_path = assembler.assemble(
        facts_a=facts_a,
        data_b_processed=data_b,
        data_c=data_c,
        data_d=data_d,
        data_e=data_e,
        output_path=out_docx,
        accepted_narratives=accepted_dict
    )
    print(f" -> Assembly complete: {final_path} ({os.path.getsize(final_path):,} bytes)")

    # 8. DOCX INSPECTION & VERIFICATION
    print("\n[STEP 8] Inspecting Generated DOCX to Confirm Accepted Narratives...")
    doc = docx.Document(final_path)
    full_text = " ".join(p.text for p in doc.paragraphs)

    checks = []
    for k, text in accepted_dict.items():
        sample = text[:60].strip()
        found = sample in full_text
        checks.append((k, sample, found))
        status_str = "FOUND (PASS)" if found else "NOT FOUND (WARN)"
        print(f" -> Target '{k}': {status_str}")
        print(f"    Sample: \"{sample}...\"")

    all_found = all(c[2] for c in checks)
    print("\n================================================================================")
    print(f"PHASE 6 LIVE EXECUTION RESULT: {'ALL PASS' if all_found else 'PARTIAL / REVIEW'}")
    print(f"Total Pipeline Latency: {t_pack + t_disc + t_ver + t_narr:.2f}s")
    print(f"Generated Document    : {final_path}")
    print("================================================================================")


if __name__ == "__main__":
    main()

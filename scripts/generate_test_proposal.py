#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script: scripts/generate_test_proposal.py
Description: Generates an authoritative MB07 credit proposal using synthetic business data
and validates exact structural fidelity against the official MSB MB07 template baseline.
"""

import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from decimal import Decimal
from msb_eb_copilot.src.proposal_assembler import CreditProposalAssembler
from msb_eb_copilot.src.section_a.review_session import SectionAReviewSession
from msb_eb_copilot.src.section_c import (
    BusinessModelType,
    BlacklistStatus,
    ShareholderInfo,
    ManagementMember,
    ProductInfo,
    WarehouseInfo,
    EquipmentInfo,
    SupplierInfo,
    CustomerInfo,
    SectionCData,
)
from msb_eb_copilot.src.section_d import (
    AccountingGovernance,
    IncomeStatement3Y,
    BalanceSheet3Y,
    CashFlowStatement3Y,
    FinancialRatios3Y,
    PnLAnalysis,
    SectionDData,
)
from msb_eb_copilot.src.section_e import (
    DebtGroup,
    CreditInstitutionRelation,
    SectionEData,
    link_section_e_to_session_a,
)
from msb_eb_copilot.agents.agent_section_b import AgentSectionB
from msb_eb_copilot.src.template_verification.structure_fingerprint import (
    snapshot_template_structure,
    compare_template_structure,
    DynamicTableRule,
)


def run_test(output_path_override: str | None = None):
    template_file = "MB07 Tờ trình đề xuất cấp tín dụng (ĐVKD) - thực hiện rà soát - tái cấp.docx"
    output_file = output_path_override or os.path.join("output", "DEMO_MB07_TO_TRINH_TIN_DUNG.docx")
    os.makedirs("output", exist_ok=True)

    print("=" * 72)
    print("   MSB CREDITPILOT 360 - TEST GENERATION & FIDELITY AUDIT")
    print("=" * 72)

    # 1. Section E (CIC)
    data_e = SectionEData(
        customer_name="CÔNG TY CỔ PHẦN PHÂN PHỐI DEMO",
        cic_report_date="20/01/2026",
        relations=[
            CreditInstitutionRelation(1, "Vietcombank - CN TP.HCM", 600000.0, 350000.0, 0.0, 0.0, 350000.0, "HĐTG, Phải thu", DebtGroup.NHOM_1_DU_TIEU_CHUAN),
            CreditInstitutionRelation(2, "BIDV - CN TP.HCM", 500000.0, 280000.0, 0.0, 0.0, 280000.0, "HĐTG, Hàng tồn kho", DebtGroup.NHOM_1_DU_TIEU_CHUAN),
            CreditInstitutionRelation(3, "VietinBank - CN TP.HCM", 400000.0, 220000.0, 0.0, 0.0, 220000.0, "HĐTG, Hàng điện tử", DebtGroup.NHOM_1_DU_TIEU_CHUAN),
            CreditInstitutionRelation(4, "MSB - CN TP.HCM", 250000.0, 250000.0, 0.0, 0.0, 250000.0, "Tín chấp / TSBĐ theo quy định", DebtGroup.NHOM_1_DU_TIEU_CHUAN),
        ],
        loan_outstanding_at_msb_million=250000.0,
        total_credit_exposure_at_msb_million=400000.0,
        is_overdue_12m=False,
        rm_credit_assessment="Khách hàng có lịch sử trả nợ mẫu mực, không có nợ quá hạn."
    )

    # 2. Section A (Profile & RM Ingest)
    session_a = SectionAReviewSession("CASE-TEST-2026")
    session_a.confirm_fact_with_rm("company.legal_name", "CÔNG TY CỔ PHẦN PHÂN PHỐI DEMO")
    session_a.confirm_fact_with_rm("company.short_name", "DEMO DISTRIBUTION JSC")
    session_a.confirm_fact_with_rm("company.legal_type", "Công ty Cổ phần")
    session_a.confirm_fact_with_rm("company.group_name", "TẬP ĐOÀN DEMO")
    session_a.confirm_fact_with_rm("company.registered_address", "123 Phố Demo, Quận Hoàn Kiếm, Hà Nội")
    session_a.confirm_fact_with_rm("company.registration_no", "0100000000")
    session_a.confirm_fact_with_rm("company.registration_issue_date", "15/12/2023")
    session_a.confirm_fact_with_rm("company.registration_issue_place", "Sở Kế hoạch và Đầu tư Hà Nội")
    session_a.confirm_fact_with_rm("company.operation_start_date_or_year", "2008")
    session_a.confirm_fact_with_rm("company.legal_representative.name", "Đại diện Demo")
    session_a.confirm_fact_with_rm("company.legal_representative.title", "Tổng Giám đốc")
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
    session_a.set_rm_provided("proposal.credit_request_representative.title", "Tổng Giám đốc")
    session_a.set_rm_provided("business.primary_industry.code_level_5", "46520")
    session_a.set_rm_provided("business.primary_industry.name", "Bán buôn thiết bị viễn thông")
    session_a.set_rm_provided("business.primary_industry.revenue_share_pct", 95)
    session_a.set_rm_provided("business.main_products", ("Điện thoại", "Máy tính xách tay", "Linh kiện điện tử"))
    session_a.confirm_fact_with_rm("capital.paid_in_capital", 518279, unit="triệu đồng")
    session_a.confirm_fact_with_rm("capital.paid_in_capital_as_of", "31/12/2025")
    session_a.set_rm_provided("internal_rating.case_id", "XHTD-2026-001")
    session_a.set_rm_provided("internal_rating.grade", "AAA")
    session_a.set_rm_provided("internal_rating.score", Decimal("95.5"))
    session_a.set_rm_provided("approval.proposed_limit.total", 700000, unit="triệu đồng")
    session_a.set_rm_provided("approval.proposed_limit.unsecured", 500000, unit="triệu đồng")
    session_a.set_rm_provided("approval.aggregate_limit.total", 650000, unit="triệu đồng")
    session_a.set_rm_provided("approval.aggregate_limit.unsecured", 120000, unit="triệu đồng")
    session_a.set_rm_provided("approval.previous_approval_period", "Kỳ phê duyệt năm 2024")
    link_section_e_to_session_a(data_e, session_a)

    facts_a = session_a.facts
    facts_a["submission.unit_name"] = "LC2MN"
    facts_a["submission.rm_name"] = "RM DEMO (CBBH) / RM SUPPORT (RM)"
    facts_a["submission.rm_phone"] = "0900000000"
    facts_a["submission.support_name"] = "SUPPORT DEMO"
    facts_a["submission.support_phone"] = "0900000001"
    facts_a["submission.manager_name"] = "MANAGER DEMO"
    facts_a["submission.manager_phone"] = "0900000002"
    facts_a["submission.proposal_no"] = "01.2026 - DEMO"
    facts_a["submission.proposal_date"] = "18/09/2026"

    # 3. Section B (Facility Proposal)
    raw_b = {
        "selected_needs": ["2.1_vay_vld_han_muc", "2.5_lc_nho_thu"],
        "general_facility_summary": {"currency": "VND", "credit_proposal_type": "Tái cấp"},
        "facilities_data": {
            "need_2_1": {
                "proposal_type": "Tái cấp tăng",
                "approved_limit_vnd": 250000.0,
                "proposed_limit_vnd": 300000.0,
                "purpose": "Bổ sung vốn lưu động phân phối thiết bị tin học",
                "duration_months": 12,
            },
            "need_2_5": {
                "issuance_structure": "Hạn mức",
                "product_type": "L/C",
                "term_classification": "Ngắn hạn",
                "proposal_type": "Tái cấp tăng",
                "approved_limit_vnd": 250000.0,
                "proposed_limit_vnd": 350000.0,
                "purpose": "Phát hành L/C nhập khẩu thiết bị công nghệ",
                "facility_duration_months": 12,
            }
        }
    }
    processed_b = AgentSectionB().validate_and_calculate(raw_b)

    # 4. Section C (Business & Supply Chain)
    data_c = SectionCData(
        customer_name="CÔNG TY CỔ PHẦN PHÂN PHỐI DEMO",
        history_narrative="Thành lập năm 2008, duy trì vị thế phân phối công nghệ hàng đầu.",
        parent_company_or_owner="TẬP ĐOÀN DEMO",
        major_shareholders=[
            ShareholderInfo(1, "TẬP ĐOÀN DEMO", "0100109789", 76.93, 398712.0, True),
            ShareholderInfo(2, "Cổ đông khác", "-", 23.07, 119567.0, False),
        ],
        management_members=[
            ManagementMember("Chủ tịch HĐQT", "Đại diện Demo", "Cử nhân Kinh tế, 20 năm kinh nghiệm"),
            ManagementMember("Kế toán trưởng", "Kế toán Demo", "Thạc sĩ Tài chính, 15 năm kinh nghiệm"),
        ]
    )

    # 5. Section D (Financials)
    data_d = SectionDData(
        customer_name="CÔNG TY CỔ PHẦN PHÂN PHỐI DEMO",
        governance=AccountingGovernance(
            mandatory_audit_by_law="Công ty đại chúng quy mô lớn bắt buộc kiểm toán BCTC theo luật",
            audit_firm_name="Công ty TNHH Kiểm toán độc lập",
            audited_years="2023, 2024, 2025",
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
            revenue_analysis="Doanh thu năm 2025 tăng trưởng +37.1% đạt 7.819 tỷ đồng.",
            gross_margin_analysis="Biên lợi nhuận gộp duy trì 5.2%.",
            net_profit_and_dividends_analysis="Lợi nhuận sau thuế năm 2025 đạt 134.2 tỷ đồng."
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
            cash_flow_analysis="Dòng tiền OCF thặng dư liên tục qua các năm."
        ),
        ratios=FinancialRatios3Y(
            years=["2023", "2024", "2025"],
            current_ratio=[1.18, 1.23, 1.16],
            quick_ratio=[0.66, 0.68, 0.66],
            cash_ratio=[0.20, 0.22, 0.17],
            debt_to_equity=[4.57, 3.70, 5.42],
            total_debt_to_equity=[2.23, 1.84, 3.09],
            dscr_icr=[1.90, 2.31, 2.82],
            ros=[1.02, 1.57, 1.72],
            roe=[12.26, 15.01, 18.40]
        )
    )

    # 6. Execute CreditProposalAssembler with Quality Gate
    assembler = CreditProposalAssembler(template_path=template_file)
    try:
        final_path = assembler.assemble(
            facts_a=facts_a,
            data_b_processed=processed_b,
            data_c=data_c,
            data_d=data_d,
            data_e=data_e,
            output_path=output_file,
            enforce_fidelity=True,
        )
    except Exception as exc:
        if "used by another process" in str(exc) or "PermissionError" in str(type(exc)):
            fallback_file = os.path.join("output", "DEMO_MB07_TO_TRINH_TIN_DUNG_NEW.docx")
            print(f"[!] File {output_file} đang mở trong ứng dụng khác. Ghi sang: {fallback_file}")
            final_path = assembler.assemble(
                facts_a=facts_a,
                data_b_processed=processed_b,
                data_c=data_c,
                data_d=data_d,
                data_e=data_e,
                output_path=fallback_file,
                enforce_fidelity=True,
            )
        else:
            raise

    print(f"[✓] Sinh Tờ trình MB07 thành công tại: {final_path}")

    # 7. Diagnostic Fidelity Verification
    t_snap = snapshot_template_structure(template_file)
    o_snap = snapshot_template_structure(final_path)

    dynamic_rules = [
        DynamicTableRule(table_index=32, binding_id="cic_credit_relations", allow_row_growth=True, max_growth=50)
    ]
    result = compare_template_structure(t_snap, o_snap, allow_table_expansion=False, allow_row_growth=False, dynamic_table_rules=dynamic_rules)

    print("-" * 72)
    print(f"Phôi gốc (Template) : {t_snap.section_count} Section | {t_snap.table_count} Bảng | {t_snap.paragraph_count} Paragraphs")
    print(f"File sinh ra (Output): {o_snap.section_count} Section | {o_snap.table_count} Bảng | {o_snap.paragraph_count} Paragraphs")
    print("-" * 72)

    if result.is_structurally_sound:
        print("KẾT QUẢ KIỂM TRA TEMPLATE FIDELITY: PASS (100% BẢO TOÀN HÌNH HỌC PHÔI)")
    else:
        print("KẾT QUẢ KIỂM TRA TEMPLATE FIDELITY: FAIL")
        for v in result.all_violations:
            print(f"  [!] {v}")

    print("=" * 72)


if __name__ == "__main__":
    run_test()

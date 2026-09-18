"""End-to-End Test: Khách hàng THÉP TÂY ĐÔ hợp nhất toàn diện 5 Phân hệ A -> B -> C -> D -> E."""

import unittest
import os
from decimal import Decimal
import docx

from msb_eb_copilot.src.section_a.review_session import SectionAReviewSession
from msb_eb_copilot.src.section_a.validator import SectionAValidator
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
    SectionCValidator,
)
from msb_eb_copilot.src.section_d import (
    AccountingGovernance,
    IncomeStatement3Y,
    BalanceSheet3Y,
    CashFlowStatement3Y,
    FinancialRatios3Y,
    PnLAnalysis,
    SectionDData,
    SectionDValidator,
    CreditDemandEngine,
    FinancialInput,
    RorwaEngine,
    DealStructure,
)
from msb_eb_copilot.src.section_e import (
    DebtGroup,
    CreditInstitutionRelation,
    SectionEData,
    SectionEValidator,
    link_section_e_to_session_a,
    get_other_debt_for_section_d,
)
from msb_eb_copilot.src.proposal_assembler import CreditProposalAssembler
from msb_eb_copilot.agents.agent_section_b import AgentSectionB


class TestFullProposalThepTayDo(unittest.TestCase):
    """Kiểm thử hợp nhất Tờ trình tín dụng toàn diện cho Thép Tây Đô."""

    def test_assemble_full_proposal_a_to_e(self):
        output_file = os.path.join("output", "TO_TRINH_MB07_THEP_TAY_DO_MASTER_A_TO_E.docx")
        os.makedirs("output", exist_ok=True)

        # -----------------------------------------------------------------
        # 1. PHÂN HỆ E: QUAN HỆ TÍN DỤNG & CIC (Chạy trước để cung cấp dữ liệu chéo)
        # -----------------------------------------------------------------
        data_e = SectionEData(
            customer_name="CÔNG TY TNHH THÉP TÂY ĐÔ",
            cic_report_date="15/08/2025",
            relations=[
                CreditInstitutionRelation(1, "BIDV - CN Cần Thơ", 400000.0, 250000.0, 0.0, 100000.0, 350000.0, "BĐS nhà xưởng KCN Trà Nóc 1", DebtGroup.NHOM_1_DU_TIEU_CHUAN),
                CreditInstitutionRelation(2, "VietinBank - CN Tây Đô", 300000.0, 180000.0, 0.0, 0.0, 180000.0, "HĐTG, Phôi thép", DebtGroup.NHOM_1_DU_TIEU_CHUAN),
                CreditInstitutionRelation(3, "Vietcombank - CN Cần Thơ", 250000.0, 150000.0, 0.0, 0.0, 150000.0, "HĐTG, Phôi thép", DebtGroup.NHOM_1_DU_TIEU_CHUAN),
                CreditInstitutionRelation(4, "Agribank - CN Cần Thơ", 200000.0, 120000.0, 0.0, 0.0, 120000.0, "BĐS, QSD Đất", DebtGroup.NHOM_1_DU_TIEU_CHUAN),
                CreditInstitutionRelation(5, "MSB - CN Cần Thơ", 6500.0, 6500.0, 0.0, 0.0, 6500.0, "Bảo lãnh Quỹ Advance", DebtGroup.NHOM_1_DU_TIEU_CHUAN),
            ],
            loan_outstanding_at_msb_million=6500.0,
            total_credit_exposure_at_msb_million=6500.0,
            is_overdue_12m=False,
            rm_credit_assessment="Khách hàng có lịch sử trả nợ tốt tại các TCTD, không nợ xấu trong 12 tháng qua."
        )
        val_e = SectionEValidator.validate(data_e)
        self.assertTrue(val_e.is_valid)

        # -----------------------------------------------------------------
        # 2. PHÂN HỆ A: TÓM TẮT THÔNG TIN CHUNG (Nhận dữ liệu từ E)
        # -----------------------------------------------------------------
        session_a = SectionAReviewSession("CASE-THEP-TAY-DO")
        session_a.confirm_fact_with_rm("company.legal_name", "CÔNG TY TNHH THÉP TÂY ĐÔ")
        session_a.confirm_fact_with_rm("company.short_name", "CÔNG TY THÉP TÂY ĐÔ")
        session_a.confirm_fact_with_rm("company.legal_type", "Công ty TNHH hai thành viên trở lên")
        session_a.confirm_fact_with_rm("company.group_name", "Không thuộc tập đoàn")
        session_a.confirm_fact_with_rm("company.registered_address", "Lô đất số 45 đường số 2, KCN Trà Nóc 1, P. Thới An Đông, TP. Cần Thơ")
        session_a.confirm_fact_with_rm("company.registration_no", "1800156657")
        session_a.confirm_fact_with_rm("company.registration_issue_date", "27/06/2008")
        session_a.confirm_fact_with_rm("company.registration_issue_place", "Sở Kế hoạch và Đầu tư TP. Cần Thơ")
        session_a.confirm_fact_with_rm("company.operation_start_date_or_year", "2008")
        session_a.confirm_fact_with_rm("company.legal_representative.name", "Huỳnh Trung Quang")
        session_a.confirm_fact_with_rm("company.legal_representative.title", "Tổng Giám đốc")
        session_a.set_rm_selected("relationship.customer_status", "KH_HIEN_HUU")
        session_a.set_rm_provided("relationship.cif", "2411322")
        session_a.set_rm_selected("relationship.segment", "LC")
        session_a.set_rm_selected("compliance.restricted_credit_subject", "KHONG")
        session_a.set_rm_selected("compliance.esg_assessment_required", "BAT_BUOC_DANH_GIA")
        session_a.set_rm_selected("credit_relation.regulatory_limit_status", "TRONG_GIOI_HAN")
        session_a.set_rm_selected("approval.authority", "HĐTD&ĐT")
        session_a.set_rm_selected("proposal.request_type", "CAP_MOI")
        session_a.confirm_fact_with_rm("financial.latest_net_revenue", 4238450, unit="triệu đồng")
        session_a.confirm_fact_with_rm("financial.latest_revenue_year", 2024)
        session_a.set_rm_provided("proposal.credit_request_representative.name", "Huỳnh Trung Quang")
        session_a.set_rm_provided("proposal.credit_request_representative.title", "Tổng Giám đốc")
        session_a.set_rm_provided("business.primary_industry.code_level_5", "24100")
        session_a.set_rm_provided("business.primary_industry.name", "Sản xuất sắt, thép, gang")
        session_a.set_rm_provided("business.primary_industry.revenue_share_pct", 100)
        session_a.set_rm_provided("business.main_products", ("Thép các loại", "Phôi thép", "Thép xây dựng", "Thép mặt bích"))
        session_a.confirm_fact_with_rm("capital.registered_capital", 500000, unit="triệu đồng")
        session_a.confirm_fact_with_rm("capital.paid_in_capital", 500000, unit="triệu đồng")
        session_a.confirm_fact_with_rm("capital.paid_in_capital_as_of", "2025-06-30")
        session_a.set_rm_provided("internal_rating.case_id", "XHTD-2026-TTD")
        session_a.set_rm_provided("internal_rating.grade", "AA")
        session_a.set_rm_provided("internal_rating.score", Decimal("88.5"))
        session_a.set_rm_provided("approval.existing_limit.total", 0, unit="triệu đồng")
        session_a.set_rm_provided("approval.existing_limit.unsecured", 0, unit="triệu đồng")
        session_a.set_rm_provided("approval.proposed_limit.total", 200000, unit="triệu đồng")
        session_a.set_rm_provided("approval.proposed_limit.unsecured", 120000, unit="triệu đồng")
        session_a.set_rm_provided("approval.aggregate_limit.total", 200000, unit="triệu đồng")
        session_a.set_rm_provided("approval.aggregate_limit.unsecured", 120000, unit="triệu đồng")
        session_a.set_rm_provided("approval.previous_approval_period", "-")

        # TỰ ĐỘNG LIÊN KẾT CHÉO TỪ PHẦN E SANG PHẦN A
        link_section_e_to_session_a(data_e, session_a)

        val_a = SectionAValidator().validate(session_a.facts)
        self.assertTrue(val_a.is_valid)

        # -----------------------------------------------------------------
        # 3. PHÂN HỆ B: NỘI DUNG ĐỀ XUẤT CẤP TÍN DỤNG
        # -----------------------------------------------------------------
        raw_b = {
            "selected_needs": ["2.1_vay_vld_han_muc", "2.5_lc_nho_thu"],
            "general_facility_summary": {"currency": "VND", "credit_proposal_type": "Cấp mới"},
            "facilities_data": {
                "need_2_1": {
                    "proposal_type": "Cấp mới",
                    "approved_limit_vnd": 0,
                    "proposed_limit_vnd": 100000.0,
                    "purpose": "Bổ sung vốn lưu động phục vụ sản xuất kinh doanh sắt thép",
                    "duration_months": 12,
                    "effective_date_rule": "Kể từ ngày ký HĐTD",
                    "max_promissory_note_duration_months": 5,
                    "lending_interest_rate": "Theo quy định MSB tại thời điểm nhận nợ",
                    "disbursement_method": "Chuyển khoản trực tiếp cho bên thụ hưởng",
                    "repayment_period": "Lãi trả hàng tháng, gốc trả cuối kỳ",
                },
                "need_2_5": {
                    "issuance_structure": "Hạn mức",
                    "product_type": "L/C",
                    "term_classification": "Ngắn hạn",
                    "proposal_type": "Cấp mới",
                    "approved_limit_vnd": 0,
                    "proposed_limit_vnd": 200000.0,
                    "purpose": "Phát hành L/C phục vụ hoạt động sản xuất kinh doanh thép",
                    "facility_duration_months": 12,
                    "effective_date_rule": "Kể từ ngày ký HĐTD",
                    "lc_collection_type": "L/C trả ngay / UPAS tối đa 05 tháng",
                    "min_margin_cash_percentage": "0%",
                    "financing_rate_per_lc_value": "100%",
                    "lc_fee": "Theo biểu phí MSB",
                }
            }
        }
        processed_b = AgentSectionB().validate_and_calculate(raw_b)

        # -----------------------------------------------------------------
        # 4. PHÂN HỆ C: HOẠT ĐỘNG KINH DOANH & CHUỖI CUNG ỨNG
        # -----------------------------------------------------------------
        data_c = SectionCData(
            customer_name="CÔNG TY TNHH THÉP TÂY ĐÔ",
            history_narrative="Thành lập từ năm 1995, có gần 30 năm kinh nghiệm trong ngành sản xuất và kinh doanh thép.",
            parent_company_or_owner="Ông Huỳnh Trung Quang và các thành viên",
            major_shareholders=[
                ShareholderInfo(1, "Huỳnh Trung Quang", "024088001234", 55.0, 275000.0),
                ShareholderInfo(2, "Nguyễn Thị Kim Loan", "024190005678", 45.0, 225000.0),
            ],
            blacklist_status=BlacklistStatus.KHONG_VI_PHAM,
            management_members=[
                ManagementMember("Tổng Giám đốc", "Huỳnh Trung Quang", "Hơn 30 năm kinh nghiệm trong ngành thép", 20),
            ],
            business_model=BusinessModelType.SAN_XUAT,
            products=[
                ProductInfo(1, "Phôi thép", "Thép Tây Đô", 60.0),
                ProductInfo(2, "Thép xây dựng & mặt bích", "Thép Tây Đô", 40.0),
            ],
            production_technology_summary="Nhà máy luyện phôi thép công nghệ lò trung tần công suất 220.000 tấn/năm.",
            warehouses=[
                WarehouseInfo(1, "Nhà máy & Kho bãi", "KCN Trà Nóc 1, Cần Thơ", 50000.0, "Thuê KCN dài hạn", "Sức chứa 40.000 tấn phôi và thép thành phẩm"),
            ],
            equipments=[
                EquipmentInfo(1, "Dây chuyền lò luyện trung tần", "Công nghệ Nhật Bản", "220.000 tấn/năm", "98%"),
            ],
            suppliers=[
                SupplierInfo(1, "CTCP Thép Pomina", "Phế liệu thép", 25.0, "L/C 90 ngày"),
                SupplierInfo(2, "Mitsui & Co", "Thép phế nhập khẩu", 20.0, "L/C at sight"),
            ],
            customers=[
                CustomerInfo(1, "CTCP Thép Chín Rồng", "Phôi thép", 20.0, "Công nợ 15 ngày"),
                CustomerInfo(2, "Chip Mong Group", "Thép xây dựng", 18.0, "L/C UPAS"),
            ],
            market_share_estimate="15-20% thị phần phôi thép khu vực Tây Nam Bộ",
            top_competitors=["Thép Miền Nam (SSCV)", "Thép Hòa Phát", "Pomina"],
            competitive_advantages="Vị trí nhà máy tại Cần Thơ thuận tiện giao thương đường thủy ĐBSCL, công nghệ lò trung tần chi phí cạnh tranh.",
            rm_supply_chain_assessment="Chuỗi cung ứng đầu vào - đầu ra cân đối, không phụ thuộc vượt ngưỡng 40% vào 1 đối tác."
        )
        val_c = SectionCValidator.validate(data_c)
        self.assertTrue(val_c.is_valid)

        # -----------------------------------------------------------------
        # 5. PHÂN HỆ D: TÌNH HÌNH TÀI CHÍNH & MB09 (Nhận other_debt từ E)
        # -----------------------------------------------------------------
        other_debt_vnd = get_other_debt_for_section_d(data_e)
        self.assertGreater(other_debt_vnd, 0)

        # Tính toán MB09 với other_debt từ E
        fin_inp = FinancialInput(
            net_revenue_plan=6000000000000,
            cogs_plan=5700000000000,
            operating_cost_plan=101272000000,
            dio=88.5,
            dso=39.1,
            dpo=64.0,
            equity_participation=110343000000,
            other_debt=other_debt_vnd
        )
        mb09_res = CreditDemandEngine.calculate_credit_limits(fin_inp)

        data_d = SectionDData(
            customer_name="CÔNG TY TNHH THÉP TÂY ĐÔ",
            governance=AccountingGovernance(
                mandatory_audit_by_law="Doanh nghiệp quy mô lớn bắt buộc kiểm toán theo luật",
                audit_firm_name="Baker Tilly A&C",
                audited_years="2023 - 2024 và 6T/2025",
                audit_opinion="Ý kiến kiểm toán chấp thuận toàn phần không ngoại trừ."
            ),
            income_statement=IncomeStatement3Y(
                years=["2023", "2024", "6T/2025"],
                net_revenue=[2580955.0, 4238450.0, 2719097.0],
                cogs=[2456441.0, 4037955.0, 2613518.0],
                gross_profit=[124514.0, 200495.0, 105578.0],
                gross_profit_margin_pct=[4.82, 4.73, 3.88],
                financial_income=[14846.0, 20890.0, 17501.0],
                financial_expenses=[67825.0, 108844.0, 61212.0],
                interest_expenses=[32157.0, 70347.0, 49784.0],
                sga_expenses=[59905.0, 101555.0, 51487.0],
                net_profit_before_tax=[13267.0, 14532.0, 10505.0],
                net_profit_after_tax=[10324.0, 10082.0, 8301.0]
            ),
            pnl_analysis=PnLAnalysis(
                revenue_analysis="Doanh thu 2024 đạt 4.238,5 tỷ đồng, tăng 64,2% so với 2023.",
                gross_margin_analysis="Biên lợi nhuận gộp duy trì quanh 4.7% - 4.8%.",
            ),
            balance_sheet=BalanceSheet3Y(
                years=["2023", "2024", "6T/2025"],
                current_assets=[1047996.0, 1981919.0, 2045610.0],
                cash_and_equivalents=[33258.0, 30264.0, 39405.0],
                short_term_investments=[173915.0, 351073.0, 320500.0],
                accounts_receivable=[70486.0, 195261.0, 215430.0],
                inventories=[562346.0, 979609.0, 1085200.0],
                other_current_assets=[83374.0, 121771.0, 115200.0],
                non_current_assets=[579052.0, 870829.0, 895400.0],
                fixed_assets=[490090.0, 621381.0, 615200.0],
                construction_in_progress=[57610.0, 203960.0, 225000.0],
                total_assets=[1627048.0, 2852748.0, 2941010.0],
                liabilities=[1353948.0, 2320148.0, 2385000.0],
                short_term_debt=[606840.0, 1417848.0, 1485000.0],
                long_term_debt=[314500.0, 351200.0, 340000.0],
                owner_equity=[273100.0, 532600.0, 556010.0],
                charter_capital=[500000.0, 500000.0, 500000.0],
            ),
            cash_flow=CashFlowStatement3Y(
                years=["2023", "2024", "6T/2025"],
                ocf_cash_from_operations=[-158525.0, -574406.0, 4120.0],
                icf_cash_from_investing=[-151200.0, -465956.0, -390752.0],
                fcf_cash_from_financing=[332339.0, 1036974.0, 395772.0],
                net_cash_flow=[22614.0, -2994.0, 9141.0],
                cash_beginning=[10644.0, 33258.0, 30264.0],
                cash_ending=[33258.0, 30264.0, 39405.0],
                cash_flow_analysis="Dòng tiền OCF đã dương trở lại trong 6T/2025 đạt +4,1 tỷ đồng."
            ),
            ratios=FinancialRatios3Y(
                years=["2023", "2024", "6T/2025"],
                current_ratio=[1.01, 1.06, 1.02],
                quick_ratio=[0.47, 0.54, 0.52],
                cash_ratio=[0.20, 0.30, 0.28],
                debt_to_equity=[4.96, 4.35, 4.29],
                total_debt_to_equity=[2.22, 2.65, 2.67],
                dscr_icr=[2.02, 1.83, 1.79],
                ros=[0.40, 0.24, 0.31],
                roe=[3.78, 1.89, 3.05]
            )
        )
        val_d = SectionDValidator.validate(data_d)
        self.assertTrue(val_d.is_valid)

        # -----------------------------------------------------------------
        # 6. HỢP NHẤT TOÀN DIỆN VÀO FILE TỜ TRÌNH MASTER (A + B + C + D + E)
        # -----------------------------------------------------------------
        assembler = CreditProposalAssembler()
        final_doc_path = assembler.assemble(
            facts_a=session_a.facts,
            data_b_processed=processed_b,
            data_c=data_c,
            data_d=data_d,
            data_e=data_e,
            output_path=output_file
        )

        self.assertTrue(os.path.exists(final_doc_path))
        doc = docx.Document(final_doc_path)
        # Kiểm tra văn bản sinh ra đầy đủ các phân hệ
        full_text = " ".join(p.text for p in doc.paragraphs)
        self.assertIn("TÓM TẮT THÔNG TIN CHUNG", full_text)
        self.assertIn("PHẦN B: NỘI DUNG ĐỀ XUẤT CẤP TÍN DỤNG", full_text)
        self.assertIn("PHẦN C: HOẠT ĐỘNG KINH DOANH CỦA KHÁCH HÀNG", full_text)
        self.assertIn("PHẦN D. TÌNH HÌNH TÀI CHÍNH DOANH NGHIỆP", full_text)
        self.assertIn("PHẦN E. THÔNG TIN QUAN HỆ TÍN DỤNG CỦA KHÁCH HÀNG (CIC)", full_text)
        self.assertGreater(len(doc.tables), 20)


if __name__ == "__main__":
    unittest.main()

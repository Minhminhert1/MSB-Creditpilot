"""End-to-End Test: Khách hàng CÔNG TY CỔ PHẦN PHÂN PHỐI DEMO (PSD).
Dữ liệu nguồn đối chiếu từ folder Test/:
- PSD RL MB09.QT.RR.044 Template BCTC - Q4.25.xlsx
- psd-thay-doi-giay-dang-ky-kinh-doanh-0-495430.pdf
- psd-cong-ty-thong-bao-ieu-le-sua-doi-bo-sung-da-duoc-ai-hoi-dong-co-dong-cong-ty-thong-qua-1-609376.pdf

Hợp nhất toàn diện 5 Phân hệ A -> B -> C -> D -> E vào 1 file Tờ trình Master MB07.
"""

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


class TestFullProposalPSD(unittest.TestCase):
    """Kiểm thử hợp nhất Tờ trình tín dụng toàn diện cho khách hàng PSD."""

    def test_assemble_full_proposal_psd_a_to_e(self):
        output_file = os.path.join("output", "TO_TRINH_MB07_PSD_MASTER_A_TO_E.docx")
        os.makedirs("output", exist_ok=True)

        # -----------------------------------------------------------------
        # 1. PHÂN HỆ E: QUAN HỆ TÍN DỤNG & CIC (Bảng 07)
        # -----------------------------------------------------------------
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
        val_e = SectionEValidator.validate(data_e)
        self.assertTrue(val_e.is_valid)

        # -----------------------------------------------------------------
        # 2. PHÂN HỆ A: TÓM TẮT THÔNG TIN CHUNG (43 Canonical Facts)
        # -----------------------------------------------------------------
        session_a = SectionAReviewSession("CASE-2026-PSD")
        session_a.confirm_fact_with_rm("company.legal_name", "CÔNG TY CỔ PHẦN PHÂN PHỐI DEMO")
        session_a.confirm_fact_with_rm("company.short_name", "DEMO DISTRIBUTION JSC")
        session_a.confirm_fact_with_rm("company.legal_type", "Công ty Cổ phần")
        session_a.confirm_fact_with_rm("company.group_name", "TẬP ĐOÀN DEMO")
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

        # Doanh thu 2025 bóc tách từ BCTC Q4.25
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

        # TỰ ĐỘNG LIÊN KẾT CHÉO TỪ E SANG A
        link_section_e_to_session_a(data_e, session_a)

        val_a = SectionAValidator().validate(session_a.facts)
        self.assertTrue(val_a.is_valid)

        # -----------------------------------------------------------------
        # 3. PHÂN HỆ B: NỘI DUNG ĐỀ XUẤT CẤP TÍN DỤNG
        # -----------------------------------------------------------------
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

        # -----------------------------------------------------------------
        # 4. PHÂN HỆ C: HOẠT ĐỘNG KINH DOANH & CHUỖI CUNG ỨNG
        # -----------------------------------------------------------------
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
        val_c = SectionCValidator.validate(data_c)
        self.assertTrue(val_c.is_valid)

        # -----------------------------------------------------------------
        # 5. PHÂN HỆ D: TÌNH HÌNH TÀI CHÍNH & MB09 (Dữ liệu BCTC thực tế)
        # -----------------------------------------------------------------
        other_debt_vnd = get_other_debt_for_section_d(data_e)
        self.assertGreater(other_debt_vnd, 0)

        # Engine MB09
        fin_inp = FinancialInput(
            net_revenue_plan=8500000000000,     # Kế hoạch 8.500 tỷ VND
            cogs_plan=8100000000000,            # Giá vốn 8.100 tỷ VND
            operating_cost_plan=200000000000,   # Chi phí hoạt động
            dio=45.0,                           # Vòng quay tồn kho điện thoại ngắn (45 ngày)
            dso=35.0,                           # Thu tiền bán lẻ 35 ngày
            dpo=40.0,                           # Trả Samsung/Apple 40 ngày
            equity_participation=511451574646,  # Vốn tự có tham gia ghi trên sheet 05: 511,4 tỷ VND
            other_debt=other_debt_vnd
        )
        mb09_res = CreditDemandEngine.calculate_credit_limits(fin_inp)

        # Engine Basel II
        deal = DealStructure(
            loan_limit=300000000000,            # 300 tỷ cho vay
            lc_limit=350000000000,              # 350 tỷ L/C
            guarantee_limit=0,
            loan_interest_rate=0.075,           # 7.5%
            ftp_cost_rate=0.055,                # 5.5%
            lc_fee_rate=0.010,
            casa_avg_balance=50000000000        # 50 tỷ CASA từ dòng tiền bán buôn
        )
        rorwa_res = RorwaEngine.calculate_deal_profitability(deal)
        self.assertTrue(rorwa_res["torwa_passed"])
        self.assertTrue(rorwa_res["rorwa_passed"])

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
                revenue_analysis="Doanh thu năm 2025 bứt phá đạt 7.819,4 tỷ đồng (tăng 37,1%) nhờ mở rộng phân phối các dòng sản phẩm iPhone thế hệ mới và thiết bị điện toán AI.",
                gross_margin_analysis="Biên lợi nhuận gộp duy trì trên 5,2%, phản ánh hiệu quả đàm phán chiết khấu thương mại tốt với Samsung và Apple.",
                net_profit_and_dividends_analysis="Lợi nhuận sau thuế năm 2025 đạt 134,2 tỷ đồng, tăng trưởng 49,6% so với năm 2024."
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
                cash_flow_analysis="Dòng tiền từ hoạt động kinh doanh (OCF) duy trì dương liên tục qua các năm, phản ánh khả năng thu hồi công nợ vượt trội từ các chuỗi bán lẻ lớn."
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
        val_d = SectionDValidator.validate(data_d)
        self.assertTrue(val_d.is_valid)

        # -----------------------------------------------------------------
        # 6. HỢP NHẤT TOÀN BỘ 5 PHÂN HỆ VÀO MASTER MB07
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
        full_text = " ".join(p.text for p in doc.paragraphs)
        t1_text = " ".join(c.text for row in doc.tables[1].rows for c in row.cells)
        self.assertIn("CÔNG TY CỔ PHẦN PHÂN PHỐI DEMO", t1_text)
        self.assertIn("TÓM TẮT THÔNG TIN CHUNG", full_text)
        self.assertIn("PHẦN B: NỘI DUNG ĐỀ XUẤT CẤP TÍN DỤNG", full_text)
        self.assertIn("PHẦN C: HOẠT ĐỘNG KINH DOANH CỦA KHÁCH HÀNG", full_text)
        self.assertIn("PHẦN D. TÌNH HÌNH TÀI CHÍNH DOANH NGHIỆP", full_text)
        self.assertIn("PHẦN E. THÔNG TIN QUAN HỆ TÍN DỤNG CỦA KHÁCH HÀNG (CIC)", full_text)
        self.assertGreater(len(doc.tables), 25)


if __name__ == "__main__":
    unittest.main()

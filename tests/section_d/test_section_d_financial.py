"""Unit tests cho Phân hệ D - Tài chính doanh nghiệp & Nhu cầu vốn MB09 / Basel II RORWA."""

import unittest
import os
import docx

from msb_eb_copilot.src.section_d import (
    AccountingGovernance,
    IncomeStatement3Y,
    BalanceSheet3Y,
    CashFlowStatement3Y,
    FinancialRatios3Y,
    PnLAnalysis,
    SectionDData,
    SectionDValidator,
    SectionDRenderer,
    CreditDemandEngine,
    FinancialInput,
    RorwaEngine,
    DealStructure,
)


class TestSectionDFinancial(unittest.TestCase):
    """Kiểm thử tính toàn vẹn và các quy tắc kiểm định tài chính Phần D."""

    def setUp(self):
        self.sample_data = SectionDData(
            customer_name="CÔNG TY TNHH THÉP TÂY ĐÔ",
            governance=AccountingGovernance(
                audit_firm_name="Baker Tilly A&C",
                audited_years="2022 - 2024",
                audit_opinion="Ý kiến kiểm toán chấp thuận toàn phần không có ngoại trừ."
            ),
            income_statement=IncomeStatement3Y(
                years=["2023", "2024", "2025"],
                net_revenue=[2580955.0, 4238450.0, 5100000.0],
                cogs=[2456441.0, 4037955.0, 4850000.0],
                gross_profit=[124514.0, 200495.0, 250000.0],
                gross_profit_margin_pct=[4.82, 4.73, 4.90],
                financial_income=[14846.0, 20890.0, 22000.0],
                financial_expenses=[67825.0, 108844.0, 115000.0],
                interest_expenses=[32157.0, 70347.0, 75000.0],
                sga_expenses=[59905.0, 101555.0, 110000.0],
                net_profit_before_tax=[13267.0, 14532.0, 51000.0],
                net_profit_after_tax=[10324.0, 10082.0, 40800.0],
            ),
            pnl_analysis=PnLAnalysis(
                revenue_analysis="Doanh thu tăng trưởng mạnh nhờ mở rộng thị phần phôi thép.",
                gross_margin_analysis="Biên lợi nhuận gộp duy trì ổn định quanh 4.8%.",
            ),
            balance_sheet=BalanceSheet3Y(
                years=["2023", "2024", "2025"],
                current_assets=[1047996.0, 1981919.0, 2100000.0],
                cash_and_equivalents=[33258.0, 30264.0, 35000.0],
                short_term_investments=[173915.0, 351073.0, 360000.0],
                accounts_receivable=[70486.0, 195261.0, 210000.0],
                inventories=[562346.0, 979609.0, 1050000.0],
                other_current_assets=[83374.0, 121771.0, 130000.0],
                non_current_assets=[579052.0, 870829.0, 900000.0],
                fixed_assets=[490090.0, 621381.0, 650000.0],
                construction_in_progress=[57610.0, 203960.0, 210000.0],
                total_assets=[1627048.0, 2852748.0, 3000000.0],
                liabilities=[1353948.0, 2320148.0, 2400000.0],
                short_term_debt=[606840.0, 1417848.0, 1450000.0],
                long_term_debt=[314500.0, 351200.0, 350000.0],
                owner_equity=[273100.0, 532600.0, 600000.0],
                charter_capital=[500000.0, 500000.0, 500000.0],
            ),
            cash_flow=CashFlowStatement3Y(
                years=["2023", "2024", "2025"],
                ocf_cash_from_operations=[-158525.0, -574406.0, 150000.0],
                icf_cash_from_investing=[-151200.0, -465956.0, -200000.0],
                fcf_cash_from_financing=[332339.0, 1036974.0, 55000.0],
                net_cash_flow=[22614.0, -2994.0, 5000.0],
                cash_beginning=[10644.0, 33258.0, 30264.0],
                cash_ending=[33258.0, 30264.0, 35264.0],
                cash_flow_analysis="Dòng tiền OCF đã dương trở lại trong năm 2025.",
            ),
            ratios=FinancialRatios3Y(
                years=["2023", "2024", "2025"],
                current_ratio=[1.01, 1.06, 1.15],
                quick_ratio=[0.47, 0.54, 0.58],
                cash_ratio=[0.20, 0.30, 0.25],
                debt_to_equity=[4.96, 4.35, 4.00],
                total_debt_to_equity=[2.22, 2.65, 2.33],
                dscr_icr=[2.02, 1.83, 1.85],
                ros=[0.40, 0.24, 0.80],
                roe=[3.78, 1.89, 6.80],
            )
        )

    def test_valid_financial_data_passes(self):
        """Dữ liệu tài chính cân đối chuẩn mực phải vượt qua kiểm định."""
        res = SectionDValidator.validate(self.sample_data)
        self.assertTrue(res.is_valid)
        self.assertEqual(len(res.errors), 0)

    def test_unbalanced_balance_sheet_fails(self):
        """Bảng CĐKT không cân đối giữa Tài sản và Nguồn vốn phải báo lỗi nghiêm trọng."""
        self.sample_data.balance_sheet.total_assets[0] += 50000.0  # Lệch 50 tỷ
        res = SectionDValidator.validate(self.sample_data)
        self.assertFalse(res.is_valid)
        self.assertTrue(any("không cân đối" in e for e in res.errors))

    def test_adverse_audit_opinion_warning(self):
        """Ý kiến kiểm toán có ngoại trừ trọng yếu phải phát sinh cảnh báo."""
        self.sample_data.governance.audit_opinion = "Ý kiến kiểm toán có ngoại trừ trọng yếu về trích lập dự phòng nợ xấu."
        res = SectionDValidator.validate(self.sample_data)
        self.assertTrue(res.is_valid)
        self.assertTrue(any("Ý KIẾN KIỂM TOÁN" in w for w in res.warnings))

    def test_low_liquidity_and_high_leverage_warnings(self):
        """Thanh khoản kém (Current < 1.0) và đòn bẩy quá cao (D/E > 5.0) phải phát sinh cảnh báo."""
        self.sample_data.ratios.current_ratio[-1] = 0.85
        self.sample_data.ratios.debt_to_equity[-1] = 5.50
        res = SectionDValidator.validate(self.sample_data)
        self.assertTrue(res.is_valid)
        self.assertTrue(any("thanh toán hiện hành" in w for w in res.warnings))
        self.assertTrue(any("Đòn bẩy tài chính" in w for w in res.warnings))

    def test_renderer_generates_docx(self):
        """Kiểm tra renderer tạo file Word Phần D hợp lệ."""
        test_out = os.path.join("output", "test_section_d_out.docx")
        os.makedirs("output", exist_ok=True)
        SectionDRenderer.generate_docx(self.sample_data, test_out)
        self.assertTrue(os.path.exists(test_out))
        
        doc = docx.Document(test_out)
        self.assertGreater(len(doc.paragraphs), 5)
        self.assertGreater(len(doc.tables), 3)

    def test_credit_demand_engine_mb09_integration(self):
        """Kiểm tra tích hợp engine MB09 tính chu kỳ tiền mặt và nhu cầu VLĐ."""
        inp = FinancialInput(
            net_revenue_plan=6000000000000,
            cogs_plan=5700000000000,
            operating_cost_plan=100000000000,
            dio=80.0,
            dso=35.0,
            dpo=60.0,
            equity_participation=100000000000,
            other_debt=1000000000000
        )
        res = CreditDemandEngine.calculate_credit_limits(inp)
        self.assertEqual(res["ccc_days"], 55.0)
        self.assertGreater(res["turns_per_year"], 0)
        self.assertGreater(res["working_capital_demand"], 0)

    def test_rorwa_engine_basel_ii_integration(self):
        """Kiểm tra tích hợp engine Basel II tính TORWA và RORWA."""
        deal = DealStructure(
            loan_limit=100000000000,
            lc_limit=100000000000,
            guarantee_limit=0
        )
        res = RorwaEngine.calculate_deal_profitability(deal)
        self.assertIn("torwa", res)
        self.assertIn("rorwa", res)
        self.assertIn("torwa_passed", res)
        self.assertIn("rorwa_passed", res)


if __name__ == "__main__":
    unittest.main()

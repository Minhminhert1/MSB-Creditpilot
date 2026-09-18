# -*- coding: utf-8 -*-
"""Unit tests for DeterministicNarrativeValidator in msb_eb_copilot.src.narrative."""

import unittest
from msb_eb_copilot.src.narrative.models import (
    FactItem, FactAuthority, FactNature, FactCompleteness,
    FactManifest, NarrativeBlock, NarrativeTargetBinding,
    NarrativeValidationError, VerificationStatus, VerifiedInsight,
    TrendDirection
)
from msb_eb_copilot.src.narrative.fact_packager import FactPackager
from msb_eb_copilot.src.narrative.validator import DeterministicNarrativeValidator


class TestNarrativeValidator(unittest.TestCase):
    def setUp(self):
        self.sample_case_data = {
            "id": "PSD_TEST",
            "name": "CÔNG TY CỔ PHẦN PHÂN PHỐI",
            "customer": {
                "name": "CÔNG TY CỔ PHẦN PHÂN PHỐI",
                "short_name": "PSD",
                "tax_code": "0102030405",
                "established_year": 2007,
                "address": "TP. Hồ Chí Minh",
                "charter_capital": 518000.0,
            },
            "rm_metadata": {
                "unit_name": "LC2MN",
                "rm_name": "Nguyễn Văn RM",
            },
            "section_b": {
                "total_limit": 500000.0,
                "loan_limit": 500000.0,
                "guarantee_limit": 0.0,
                "loan_purpose": "Bổ sung vốn lưu động",
                "collateral_type": "Tín chấp",
            },
            "section_c": {
                "business_model": "THUONG_MAI",
                "market_share_estimate": "Doanh nghiệp ước tính chiếm 15% thị phần phân phối.",
                "products": [
                    {"name": "Điện thoại Apple", "share": 60.0},
                    {"name": "Laptop Dell", "share": 40.0}
                ]
            },
            "section_d": {
                "years": ["2023", "2024", "2025"],
                "net_revenue": [6755000.0, 5702000.0, 7819000.0],
                "cogs": [6480000.0, 5381000.0, 7412000.0],
                "gross_profit": [275000.0, 321000.0, 407000.0],
                "financial_expenses": [80000.0, 90000.0, 101000.0],
                "interest_expenses": [60000.0, 70000.0, 82000.0],
                "net_profit": [80000.0, 90000.0, 134000.0],
                "current_assets": [3034000.0, 2723000.0, 4600000.0],
                "cash_and_equivalents": [62000.0, 103000.0, 228000.0],
                "receivables": [1120000.0, 985000.0, 1475000.0],
                "inventories": [1350000.0, 1210000.0, 965000.0],
                "total_assets": [3128000.0, 2810000.0, 4683000.0],
                "liabilities": [2567000.0, 2212000.0, 3954000.0],
                "short_term_debt": [1250000.0, 1100000.0, 2572000.0],
                "equity": [561000.0, 598000.0, 729000.0],
                "ocf": [384000.0, 361000.0, 250000.0],
            },
            "section_e": {
                "cic_date": "31/12/2025",
                "msb_outstanding": 500000.0,
                "history_status": "100% Nhóm 1",
                "relations": []
            }
        }
        self.manifest = FactPackager.package_from_case_data(self.sample_case_data, case_id="PSD_TEST")
        self.verified_insights = [
            VerifiedInsight(
                insight_id="INS_REV_GROWTH",
                status=VerificationStatus.VERIFIED,
                insight_type="GROWTH",
                metric="Doanh thu thuần",
                fact_ids=["FIN_REV_2024", "FIN_REV_2025"],
                verified_value=37.13,
                model_proposed_value=37.13,
                unit="PERCENT",
                trend=TrendDirection.INCREASE,
                observation="Doanh thu thuần năm 2025 tăng trưởng 37,13% so với 2024.",
                verification_formula="Formula",
                data_quality="HIGH",
                warnings=[],
                display_representations=["37.13%", "37,13%", "37.1%", "37,1%"]
            )
        ]
        self.validator = DeterministicNarrativeValidator(self.manifest, self.verified_insights)

    def test_valid_narrative_block_passes(self):
        block = NarrativeBlock(
            section="FINANCIAL",
            target_binding=NarrativeTargetBinding.PNL_ANALYSIS,
            title="Phân tích Kết quả Kinh doanh",
            text="Doanh thu thuần năm 2025 đạt 7819000 triệu VND (tăng trưởng 37,1% so với 2024). Lợi nhuận gộp đạt 407000 triệu VND.",
            facts_used=["FIN_REV_2024", "FIN_REV_2025", "FIN_GP_2025"],
            insights_used=["INS_REV_GROWTH"],
            data_gaps=[]
        )
        res = self.validator.validate_block(block)
        self.assertTrue(res["valid"], msg=f"Errors: {res.get('errors')}")

    def test_ungrounded_number_fails(self):
        block = NarrativeBlock(
            section="FINANCIAL",
            target_binding=NarrativeTargetBinding.PNL_ANALYSIS,
            title="Phân tích Kết quả Kinh doanh",
            text="Doanh thu thuần năm 2025 đạt 9999999 triệu VND với biên lãi gộp 88,8%.",
            facts_used=["FIN_REV_2025"],
            insights_used=[],
            data_gaps=[]
        )
        res = self.validator.validate_block(block)
        self.assertFalse(res["valid"])
        self.assertTrue(any("Ungrounded numeric claim" in err for err in res["errors"]))

    def test_missing_fact_id_referential_integrity(self):
        block = NarrativeBlock(
            section="FINANCIAL",
            target_binding=NarrativeTargetBinding.PNL_ANALYSIS,
            title="Phân tích Kết quả Kinh doanh",
            text="Doanh thu thuần đạt 7819000 triệu VND.",
            facts_used=["NON_EXISTENT_FACT_XYZ"],
            insights_used=[],
            data_gaps=[]
        )
        res = self.validator.validate_block(block)
        self.assertFalse(res["valid"])
        self.assertTrue(any("Referential integrity error" in err for err in res["errors"]))

    def test_source_claim_mandatory_attribution(self):
        # BIZ_MARKET_SHARE_CLAIM has authority SOURCE_CLAIM
        # Without attribution phrase "Theo hồ sơ doanh nghiệp cung cấp" -> must fail
        claim_fact = self.manifest.get_fact("BIZ_MARKET_SHARE_CLAIM")
        self.assertIsNotNone(claim_fact)

        block = NarrativeBlock(
            section="BUSINESS",
            target_binding=NarrativeTargetBinding.MARKET_SUMMARY,
            title="Thị phần",
            text="Doanh nghiệp chiếm 15% thị phần phân phối trên toàn quốc.",
            facts_used=["BIZ_MARKET_SHARE_CLAIM"],
            insights_used=[],
            data_gaps=[]
        )
        res = self.validator.validate_block(block)
        self.assertFalse(res["valid"])
        self.assertTrue(any("Missing mandatory source attribution" in err for err in res["errors"]))

    def test_source_claim_with_proper_attribution_passes(self):
        block = NarrativeBlock(
            section="BUSINESS",
            target_binding=NarrativeTargetBinding.MARKET_SUMMARY,
            title="Thị phần",
            text="Theo hồ sơ doanh nghiệp cung cấp, doanh nghiệp ước tính chiếm 15% thị phần phân phối.",
            facts_used=["BIZ_MARKET_SHARE_CLAIM"],
            insights_used=[],
            data_gaps=[]
        )
        res = self.validator.validate_block(block)
        self.assertTrue(res["valid"], msg=f"Errors: {res.get('errors')}")

    def test_cic_incomplete_caveat_enforcement(self):
        case_with_incomplete_cic = dict(self.sample_case_data)
        case_with_incomplete_cic["section_e"] = {
            "is_incomplete": True,
            "incomplete_reason": "Có khoản nợ USD chưa quy đổi",
            "relations": []
        }
        incomplete_manifest = FactPackager.package_from_case_data(case_with_incomplete_cic, case_id="PSD_INCOMPLETE")
        validator = DeterministicNarrativeValidator(incomplete_manifest, [])

        # CIC block without caveat must fail
        block_no_caveat = NarrativeBlock(
            section="CIC",
            target_binding=NarrativeTargetBinding.CIC_SUMMARY,
            title="CIC Toàn hệ thống",
            text="Khách hàng có lịch sử trả nợ tốt tại tất cả các ngân hàng.",
            facts_used=["CIC_HISTORY_STATUS"],
            insights_used=[],
            data_gaps=[]
        )
        res1 = validator.validate_block(block_no_caveat)
        self.assertFalse(res1["valid"])
        self.assertTrue(any("CIC external debt is INCOMPLETE" in err for err in res1["errors"]))

        # CIC block with caveat must pass
        block_with_caveat = NarrativeBlock(
            section="CIC",
            target_binding=NarrativeTargetBinding.CIC_SUMMARY,
            title="CIC Toàn hệ thống",
            text="Lưu ý: Dư nợ TCTD khác chưa thể xác định đầy đủ bằng VND do có khoản nợ ngoại tệ chưa quy đổi. Khách hàng có lịch sử trả nợ tốt.",
            facts_used=["CIC_HISTORY_STATUS"],
            insights_used=[],
            data_gaps=[]
        )
        res2 = validator.validate_block(block_with_caveat)
        self.assertTrue(res2["valid"], msg=f"Errors: {res2.get('errors')}")


if __name__ == "__main__":
    unittest.main()

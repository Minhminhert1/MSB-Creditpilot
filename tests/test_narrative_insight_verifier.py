# -*- coding: utf-8 -*-
"""Unit tests for PythonInsightVerifier in msb_eb_copilot.src.narrative."""

import unittest
from decimal import Decimal

from msb_eb_copilot.src.narrative.models import (
    FactItem, FactAuthority, FactNature, FactCompleteness,
    FactManifest, InsightCandidate, SupportedInsightType,
    TrendDirection, VerificationStatus, VerifiedInsight
)
from msb_eb_copilot.src.narrative.fact_packager import FactPackager
from msb_eb_copilot.src.narrative.insight_verifier import PythonInsightVerifier, STABLE_THRESHOLD_PCT


class TestNarrativeInsightVerifier(unittest.TestCase):
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
        self.verifier = PythonInsightVerifier(self.manifest)

    def test_verify_growth_insight_exact_match(self):
        # 2024 -> 2025 revenue growth: (7819000 - 5702000) / 5702000 = +37.13%
        candidate = InsightCandidate(
            insight_id="INS_REV_GROWTH",
            insight_type=SupportedInsightType.GROWTH.value,
            metric="Doanh thu thuần",
            related_fact_ids=["FIN_REV_2024", "FIN_REV_2025"],
            from_period="2024",
            to_period="2025",
            proposed_value=37.13,
            proposed_unit="PERCENT",
            trend=TrendDirection.INCREASE,
            observation="Doanh thu thuần năm 2025 đạt mức tăng trưởng tích cực so với 2024.",
            materiality_reason="Thể hiện mở rộng quy mô kinh doanh."
        )
        res = self.verifier.verify_candidate(candidate)
        self.assertEqual(res.status, VerificationStatus.VERIFIED)
        self.assertAlmostEqual(float(res.verified_value), 37.13, places=2)

    def test_verify_growth_insight_corrected(self):
        # Model proposed 40.0% instead of 37.13% (minor arithmetic error -> CORRECTED_AND_VERIFIED)
        candidate = InsightCandidate(
            insight_id="INS_REV_GROWTH_MINOR_DIFF",
            insight_type=SupportedInsightType.GROWTH.value,
            metric="Doanh thu thuần",
            related_fact_ids=["FIN_REV_2024", "FIN_REV_2025"],
            from_period="2024",
            to_period="2025",
            proposed_value=40.0,  # Within 20% relative difference
            proposed_unit="PERCENT",
            trend=TrendDirection.INCREASE,
            observation="Doanh thu thuần năm 2025 tăng trưởng xấp xỉ 40%.",
            materiality_reason="Tăng trưởng doanh thu hỗ trợ năng lực trả nợ."
        )
        res = self.verifier.verify_candidate(candidate)
        self.assertEqual(res.status, VerificationStatus.CORRECTED_AND_VERIFIED)
        self.assertAlmostEqual(float(res.verified_value), 37.13, places=2)
        self.assertTrue(len(res.warnings) > 0)

    def test_verify_growth_insight_large_mismatch_rejected(self):
        # Model proposed 55.0% instead of 37.13% (large mismatch > 20% -> REJECTED_QUANTITATIVE_MISMATCH)
        candidate = InsightCandidate(
            insight_id="INS_REV_GROWTH_LARGE_MISMATCH",
            insight_type=SupportedInsightType.GROWTH.value,
            metric="Doanh thu thuần",
            related_fact_ids=["FIN_REV_2024", "FIN_REV_2025"],
            from_period="2024",
            to_period="2025",
            proposed_value=55.0,  # Beyond 20% tolerance
            proposed_unit="PERCENT",
            trend=TrendDirection.INCREASE,
            observation="Doanh thu thuần năm 2025 tăng trưởng vượt bậc 55%.",
            materiality_reason="Tăng trưởng quy mô."
        )
        res = self.verifier.verify_candidate(candidate)
        self.assertEqual(res.status, VerificationStatus.REJECTED_QUANTITATIVE_MISMATCH)

    def test_stable_threshold_guardrail(self):
        # Delta is 37.13% (> 2.0%), so calling it STABLE must be REJECTED
        candidate = InsightCandidate(
            insight_id="INS_STABLE_FAIL",
            insight_type=SupportedInsightType.GROWTH.value,
            metric="Doanh thu thuần",
            related_fact_ids=["FIN_REV_2024", "FIN_REV_2025"],
            from_period="2024",
            to_period="2025",
            proposed_value=0.0,
            proposed_unit="PERCENT",
            trend=TrendDirection.STABLE,
            observation="Doanh thu thuần không biến động.",
            materiality_reason="Đánh giá tính ổn định dòng tiền."
        )
        res = self.verifier.verify_candidate(candidate)
        self.assertEqual(res.status, VerificationStatus.REJECTED_INVALID_CONCEPT)

    def test_causal_word_guardrail_rejection(self):
        # Causal claim contains "nhờ mở rộng" without business fact IDs in related_fact_ids
        candidate = InsightCandidate(
            insight_id="INS_CAUSAL_FAIL",
            insight_type=SupportedInsightType.GROWTH.value,
            metric="Doanh thu thuần",
            related_fact_ids=["FIN_REV_2024", "FIN_REV_2025"],
            from_period="2024",
            to_period="2025",
            proposed_value=37.13,
            proposed_unit="PERCENT",
            trend=TrendDirection.INCREASE,
            observation="Doanh thu thuần tăng trưởng 37,13% nhờ mở rộng hệ thống bán buôn.",
            materiality_reason="Tăng trưởng quy mô phân phối."
        )
        res = self.verifier.verify_candidate(candidate)
        self.assertEqual(res.status, VerificationStatus.REJECTED_UNSUPPORTED_CAUSAL)

    def test_missing_fact_id_rejected(self):
        candidate = InsightCandidate(
            insight_id="INS_INVALID_FACT",
            insight_type=SupportedInsightType.GROWTH.value,
            metric="Chỉ tiêu không tồn tại",
            related_fact_ids=["NON_EXISTENT_FACT_123"],
            from_period="2024",
            to_period="2025",
            proposed_value=10.0,
            proposed_unit="PERCENT",
            trend=TrendDirection.INCREASE,
            observation="Chỉ tiêu tăng trưởng.",
            materiality_reason="Đánh giá tăng trưởng."
        )
        res = self.verifier.verify_candidate(candidate)
        self.assertEqual(res.status, VerificationStatus.REJECTED_MISSING_FACTS)


if __name__ == "__main__":
    unittest.main()

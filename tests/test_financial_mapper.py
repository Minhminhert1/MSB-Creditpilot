# -*- coding: utf-8 -*-
"""Unit tests for Phase 3A: Deterministic Financial Document Mapper and Ratio Calculator."""

import copy
import unittest

from msb_eb_copilot.src.extraction.financial_extraction import (
    FinancialDocumentExtraction,
    FinancialEvidenceField,
    FinancialPeriodExtraction,
    FinancialUnitInfo,
)
from msb_eb_copilot.src.mapping.financial_mapper import (
    FinancialDocumentMapper,
    compute_canonical_ratios,
)
from msb_eb_copilot.src.mapping.models import (
    CanonicalMappingResult,
    MappingConflict,
    MappingProvenance,
    MappingSchemaError,
    MappingSourceMetadata,
)


class TestFinancialDocumentMapper(unittest.TestCase):
    """Test FinancialDocumentMapper guarantees."""

    def setUp(self):
        self.source_meta = MappingSourceMetadata(
            source_document="bctc_test.pdf",
            ingestion_mode="digital",
            extractor="FinancialDocumentExtractor",
        )
        self.doc_unit = FinancialUnitInfo(unit_raw="VND", evidence="Đơn vị tính: VND", page=1)

    def test_non_mutation_guarantee(self):
        original_case = {
            "customer": {"name": "PSD"},
            "section_d": {
                "years": ["2024"],
                "net_revenue": [5000000.0],
            }
        }
        case_copy = copy.deepcopy(original_case)

        extraction = FinancialDocumentExtraction(
            document_unit=self.doc_unit,
            periods=[
                FinancialPeriodExtraction(
                    period="2025",
                    net_revenue=FinancialEvidenceField(
                        value_raw="6.000.000.000.000",
                        evidence="Doanh thu thuần | 6.000.000.000.000",
                        page=1,
                    )
                )
            ]
        )

        res = FinancialDocumentMapper.map(original_case, extraction, self.source_meta)
        self.assertEqual(original_case, case_copy, "Mapper must NEVER mutate original input case_data!")
        self.assertIn("2025", res.case_data["section_d"]["years"])

    def test_multi_period_timeline_alignment(self):
        # Case has 2023, 2024. Document provides 2024, 2025.
        case_data = {
            "section_d": {
                "years": ["2023", "2024"],
                "net_revenue": [4000000.0, 5000000.0],
            }
        }
        extraction = FinancialDocumentExtraction(
            document_unit=self.doc_unit,
            periods=[
                FinancialPeriodExtraction(
                    period="2024",
                    net_revenue=FinancialEvidenceField(
                        value_raw="5.000.000.000.000",
                        evidence="DT 2024: 5.000.000.000.000",
                        page=1,
                    )
                ),
                FinancialPeriodExtraction(
                    period="2025",
                    net_revenue=FinancialEvidenceField(
                        value_raw="7.000.000.000.000",
                        evidence="DT 2025: 7.000.000.000.000",
                        page=1,
                    )
                )
            ]
        )

        res = FinancialDocumentMapper.map(case_data, extraction, self.source_meta)
        years = res.case_data["section_d"]["years"]
        revs = res.case_data["section_d"]["net_revenue"]

        self.assertEqual(years, ["2023", "2024", "2025"])
        self.assertEqual(revs[0], 4000000.0)  # 2023 preserved
        self.assertEqual(revs[1], 5000000.0)  # 2024 matched
        self.assertEqual(revs[2], 7000000.0)  # 2025 added (7,000,000 triệu VND)

    def test_conflict_detection_does_not_overwrite(self):
        # Case has 5,000,000 triệu VND for 2024. Document reports 6,000,000 triệu VND.
        case_data = {
            "section_d": {
                "years": ["2024"],
                "net_revenue": [5000000.0],
            }
        }
        extraction = FinancialDocumentExtraction(
            document_unit=self.doc_unit,
            periods=[
                FinancialPeriodExtraction(
                    period="2024",
                    net_revenue=FinancialEvidenceField(
                        value_raw="6.000.000.000.000",
                        evidence="DT 2024: 6.000.000.000.000",
                        page=1,
                    )
                )
            ]
        )

        res = FinancialDocumentMapper.map(case_data, extraction, self.source_meta)
        self.assertEqual(len(res.conflicts), 1)
        conflict = res.conflicts[0]
        self.assertEqual(conflict.canonical_path, "section_d.net_revenue[2024]")
        self.assertEqual(conflict.existing_value, 5000000.0)
        self.assertEqual(conflict.extracted_value, 6000000.0)
        # Value in case_data remains 5,000,000 (NOT overwritten)
        self.assertEqual(res.case_data["section_d"]["net_revenue"][0], 5000000.0)

    def test_provenance_contains_unit_and_evidence(self):
        case_data = {"section_d": {}}
        extraction = FinancialDocumentExtraction(
            document_unit=FinancialUnitInfo(unit_raw="VND", evidence="Đơn vị: VND", page=1),
            periods=[
                FinancialPeriodExtraction(
                    period="2025",
                    cash=FinancialEvidenceField(
                        value_raw="8.500.000.000",
                        semantic_label="Tiền và các khoản tương đương tiền",
                        accounting_code="110",
                        evidence="Tiền và tương đương tiền: 8.500.000.000",
                        page=2,
                    )
                )
            ]
        )

        res = FinancialDocumentMapper.map(case_data, extraction, self.source_meta)
        prov_list = res.provenance["section_d.cash[2025]"]
        self.assertEqual(len(prov_list), 1)
        p = prov_list[0]
        self.assertEqual(p.mapped_value, 8500.0)
        self.assertEqual(p.resolved_unit, "VND")
        self.assertEqual(p.accounting_code, "110")
        self.assertEqual(p.page, 2)


class TestCanonicalRatioCalculation(unittest.TestCase):
    """Test Python deterministic financial ratio calculations."""

    def test_ratio_calculations(self):
        section_d = {
            "years": ["2024", "2025"],
            "net_revenue": [1000000.0, 1200000.0],
            "gross_profit": [200000.0, 300000.0],
            "net_profit_after_tax": [50000.0, 84000.0],
            "current_assets": [600000.0, 800000.0],
            "cash": [100000.0, 150000.0],
            "inventories": [200000.0, 250000.0],
            "total_assets": [900000.0, 1200000.0],
            "short_term_debt": [400000.0, 500000.0],
            "equity": [500000.0, 700000.0],
        }

        ratios = compute_canonical_ratios(section_d)

        # Current Ratio = CA / ST_Debt -> 600k / 400k = 1.5; 800k / 500k = 1.6
        self.assertEqual(ratios["current_ratio"], [1.5, 1.6])

        # Quick Ratio = (CA - Inv) / ST_Debt -> (600 - 200)/400 = 1.0; (800 - 250)/500 = 1.1
        self.assertEqual(ratios["quick_ratio"], [1.0, 1.1])

        # Cash Ratio = Cash / ST_Debt -> 100/400 = 0.25; 150/500 = 0.3
        self.assertEqual(ratios["cash_ratio"], [0.25, 0.3])

        # Debt to Equity = ST_Debt / Equity -> 400/500 = 0.8; 500/700 = 0.71
        self.assertEqual(ratios["debt_to_equity"], [0.8, 0.71])

        # ROS = NP / Rev * 100 -> 50k / 1000k = 5.0%; 84k / 1200k = 7.0%
        self.assertEqual(ratios["ros"], [5.0, 7.0])

        # ROE = NP / Eq * 100 -> 50k / 500k = 10.0%; 84k / 700k = 12.0%
        self.assertEqual(ratios["roe"], [10.0, 12.0])

        # Gross Margin = GP / Rev * 100 -> 200/1000 = 20.0%; 300/1200 = 25.0%
        self.assertEqual(ratios["gross_profit_margin_pct"], [20.0, 25.0])

        # Revenue Growth YoY -> None for year 0; (1200 - 1000)/1000 * 100 = 20.0%
        self.assertEqual(ratios["revenue_growth"], [None, 20.0])

    def test_division_by_zero_safety(self):
        section_d = {
            "years": ["2025"],
            "net_revenue": [0.0],
            "short_term_debt": [0.0],
            "equity": [0.0],
        }
        ratios = compute_canonical_ratios(section_d)
        self.assertIsNone(ratios["current_ratio"][0])
        self.assertIsNone(ratios["ros"][0])
        self.assertIsNone(ratios["roe"][0])

    def test_ratio_calculations_with_liabilities(self):
        """Authoritative MSB formulas using current_liabilities and total_liabilities."""
        section_d = {
            "years": ["2024", "2025"],
            "net_revenue": [100000.0, 120000.0],
            "cogs": [82000.0, 96000.0],
            "gross_profit": [18000.0, 24000.0],
            "net_profit_after_tax": [7120.0, 10240.0],
            "current_assets": [52000.0, 65000.0],
            "cash": [6200.0, 8500.0],
            "inventories": [22500.0, 28000.0],
            "total_assets": [75000.0, 90000.0],
            "total_liabilities": [38000.0, 45000.0],
            "current_liabilities": [30000.0, 35000.0],
            "short_term_debt": [16000.0, 20000.0],
            "equity": [37000.0, 45000.0],
        }

        ratios = compute_canonical_ratios(section_d)

        # Current Ratio = Current Assets / Current Liabilities
        # 2024: 52000 / 30000 = 1.73 | 2025: 65000 / 35000 = 1.86
        self.assertEqual(ratios["current_ratio"], [1.73, 1.86])

        # Quick Ratio = (Current Assets - Inventories) / Current Liabilities
        # 2024: (52000 - 22500) / 30000 = 0.98 | 2025: (65000 - 28000) / 35000 = 1.06
        self.assertEqual(ratios["quick_ratio"], [0.98, 1.06])

        # Cash Ratio = Cash / Current Liabilities
        # 2024: 6200 / 30000 = 0.21 | 2025: 8500 / 35000 = 0.24
        self.assertEqual(ratios["cash_ratio"], [0.21, 0.24])

        # Debt to Equity = Total Liabilities / Equity
        # 2024: 38000 / 37000 = 1.03 | 2025: 45000 / 45000 = 1.0
        self.assertEqual(ratios["debt_to_equity"], [1.03, 1.0])

        # ROS = NP / Rev * 100
        # 2024: 7120 / 100000 * 100 = 7.12% | 2025: 10240 / 120000 * 100 = 8.5333%
        self.assertEqual(ratios["ros"], [7.12, 8.5333])

        # ROE = NP / Equity * 100
        # 2024: 7120 / 37000 * 100 = 19.2432% | 2025: 10240 / 45000 * 100 = 22.7556%
        self.assertEqual(ratios["roe"], [19.2432, 22.7556])

        # Gross Profit Margin = Gross Profit / Revenue * 100
        # 2024: 18000 / 100000 * 100 = 18.0% | 2025: 24000 / 120000 * 100 = 20.0%
        self.assertEqual(ratios["gross_profit_margin_pct"], [18.0, 20.0])

        # Revenue Growth YoY
        # 2024: None | 2025: (120000 - 100000) / 100000 * 100 = 20.0%
        self.assertEqual(ratios["revenue_growth"], [None, 20.0])


if __name__ == "__main__":
    unittest.main()

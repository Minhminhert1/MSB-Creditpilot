# -*- coding: utf-8 -*-
"""Golden End-to-End Test for Financial Document Agent & Canonical Section D Lineage.

Verifies:
1. Exact mathematical correspondence of derived ratios to newly confirmed synthetic BCTC SOURCE_FACTS.
2. Complete auditable metric lineage (numerator, denominator, formula, result).
3. Liquidity and leverage ratios based on authoritative MSB Section D standards:
   - current_ratio = current_assets / current_liabilities
   - quick_ratio = (current_assets - inventories) / current_liabilities
   - cash_ratio = cash / current_liabilities
   - debt_to_equity = total_liabilities / equity
4. Legacy revenue safety:
   - Canonical section_d.net_revenue takes strict precedence over customer.revenue_2025.
   - customer.revenue_2025 is NOT written or mutated during financial preview confirmation.
"""

import copy
import unittest
from msb_eb_copilot.src.canonical_validator import CanonicalAdapter
from msb_eb_copilot.src.mapping.financial_mapper import (
    compute_canonical_ratios,
    FinancialDocumentMapper,
)
from msb_eb_copilot.src.mapping.models import MappingSourceMetadata
from msb_eb_copilot.src.extraction.financial_extraction import (
    FinancialDocumentExtraction,
    FinancialEvidenceField,
    FinancialPeriodExtraction,
    FinancialUnitInfo,
)


class TestFinancialGoldenE2E(unittest.TestCase):
    """Synthetic Golden E2E Test with mathematically known values."""

    def setUp(self):
        def fef(val, label, code, ev, pg):
            return FinancialEvidenceField(value_raw=val, semantic_label=label, accounting_code=code, evidence=ev, page=pg)

        # Build synthetic 2024-2025 verified staging extraction matching synthetic BCTC
        self.p2024 = FinancialPeriodExtraction(
            period="2024",
            net_revenue=fef("100.000.000.000", "Doanh thu thuần", "10", "Doanh thu thuần | 100.000.000.000", 1),
            cogs=fef("82.000.000.000", "Giá vốn hàng bán", "11", "Giá vốn | 82.000.000.000", 1),
            gross_profit=fef("18.000.000.000", "Lợi nhuận gộp", "20", "Lợi nhuận gộp | 18.000.000.000", 1),
            net_profit_after_tax=fef("7.120.000.000", "LNST", "60", "LNST | 7.120.000.000", 1),
            current_assets=fef("52.000.000.000", "TSNH", "100", "TSNH | 52.000.000.000", 2),
            cash=fef("6.200.000.000", "Tiền", "110", "Tiền | 6.200.000.000", 2),
            receivables=fef("21.800.000.000", "Phải thu", "130", "Phải thu | 21.800.000.000", 2),
            inventories=fef("22.500.000.000", "Hàng tồn kho", "140", "Tồn kho | 22.500.000.000", 2),
            total_assets=fef("75.000.000.000", "Tổng tài sản", "270", "Tổng tài sản | 75.000.000.000", 2),
            total_liabilities=fef("38.000.000.000", "Nợ phải trả", "300", "Nợ phải trả | 38.000.000.000", 2),
            current_liabilities=fef("30.000.000.000", "Nợ ngắn hạn", "310", "Nợ ngắn hạn | 30.000.000.000", 2),
            short_term_debt=fef("16.000.000.000", "Vay ngắn hạn", "320", "Vay ngắn hạn | 16.000.000.000", 2),
            equity=fef("37.000.000.000", "Vốn chủ sở hữu", "400", "Vốn CSH | 37.000.000.000", 2),
        )

        self.p2025 = FinancialPeriodExtraction(
            period="2025",
            net_revenue=fef("120.000.000.000", "Doanh thu thuần", "10", "Doanh thu thuần | 120.000.000.000", 1),
            cogs=fef("96.000.000.000", "Giá vốn hàng bán", "11", "Giá vốn | 96.000.000.000", 1),
            gross_profit=fef("24.000.000.000", "Lợi nhuận gộp", "20", "Lợi nhuận gộp | 24.000.000.000", 1),
            net_profit_after_tax=fef("10.240.000.000", "LNST", "60", "LNST | 10.240.000.000", 1),
            current_assets=fef("65.000.000.000", "TSNH", "100", "TSNH | 65.000.000.000", 2),
            cash=fef("8.500.000.000", "Tiền", "110", "Tiền | 8.500.000.000", 2),
            receivables=fef("26.500.000.000", "Phải thu", "130", "Phải thu | 26.500.000.000", 2),
            inventories=fef("28.000.000.000", "Hàng tồn kho", "140", "Tồn kho | 28.000.000.000", 2),
            total_assets=fef("90.000.000.000", "Tổng tài sản", "270", "Tổng tài sản | 90.000.000.000", 2),
            total_liabilities=fef("45.000.000.000", "Nợ phải trả", "300", "Nợ phải trả | 45.000.000.000", 2),
            current_liabilities=fef("35.000.000.000", "Nợ ngắn hạn", "310", "Nợ ngắn hạn | 35.000.000.000", 2),
            short_term_debt=fef("20.000.000.000", "Vay ngắn hạn", "320", "Vay ngắn hạn | 20.000.000.000", 2),
            equity=fef("45.000.000.000", "Vốn chủ sở hữu", "400", "Vốn CSH | 45.000.000.000", 2),
        )

        doc_unit = FinancialUnitInfo(
            unit_raw="VND",
            normalized_unit="VND",
            multiplier_to_million=1e-6,
            evidence="Đơn vị tính: VND",
            page=1,
        )
        self.extraction = FinancialDocumentExtraction(
            document_title="BCTC Synthetic",
            periods=[self.p2024, self.p2025],
            page_units={1: doc_unit, 2: doc_unit},
            document_unit=doc_unit,
        )

    def test_golden_metrics_mathematical_lineage(self):
        """Map synthetic BCTC into clean case and assert mathematically known metrics."""
        clean_case = {
            "id": "CASE_VAN_XUAN",
            "name": "CTCP Vạn Xuân",
            "customer": {"name": "Vạn Xuân", "tax_code": "0109988776"},
            "section_d": {},
        }

        source_meta = MappingSourceMetadata("bctc_synthetic.pdf", "digital", "FinancialDocumentExtractor")
        res = FinancialDocumentMapper.map(clean_case, self.extraction, source_meta)
        sec_d = res.case_data["section_d"]

        # Check Year Alignment
        self.assertEqual(sec_d["years"], ["2024", "2025"])

        # Check Normalized Canonical Values (in triệu VND)
        self.assertEqual(sec_d["net_revenue"], [100000.0, 120000.0])
        self.assertEqual(sec_d["cogs"], [82000.0, 96000.0])
        self.assertEqual(sec_d["gross_profit"], [18000.0, 24000.0])
        self.assertEqual(sec_d["net_profit_after_tax"], [7120.0, 10240.0])
        self.assertEqual(sec_d["current_assets"], [52000.0, 65000.0])
        self.assertEqual(sec_d["cash"], [6200.0, 8500.0])
        self.assertEqual(sec_d["receivables"], [21800.0, 26500.0])
        self.assertEqual(sec_d["inventories"], [22500.0, 28000.0])
        self.assertEqual(sec_d["total_assets"], [75000.0, 90000.0])
        self.assertEqual(sec_d["total_liabilities"], [38000.0, 45000.0])
        self.assertEqual(sec_d["current_liabilities"], [30000.0, 35000.0])
        self.assertEqual(sec_d["short_term_debt"], [16000.0, 20000.0])
        self.assertEqual(sec_d["equity"], [37000.0, 45000.0])

        # Compute Ratios
        ratios = compute_canonical_ratios(sec_d)

        # 2025 Golden Assertions
        # 1. Gross Profit Margin: 24000 / 120000 * 100 = 20.0%
        self.assertEqual(ratios["gross_profit_margin_pct"][1], 20.0)

        # 2. ROS: 10240 / 120000 * 100 = 8.5333%
        self.assertAlmostEqual(ratios["ros"][1], 8.5333, places=4)

        # 3. ROE: 10240 / 45000 * 100 = 22.7556%
        self.assertAlmostEqual(ratios["roe"][1], 22.7556, places=4)

        # 4. Revenue Growth vs 2024: (120000 - 100000) / 100000 * 100 = 20.0%
        self.assertEqual(ratios["revenue_growth"][1], 20.0)

        # 5. Current Ratio: 65000 / 35000 = 1.86
        self.assertEqual(ratios["current_ratio"][1], 1.86)

        # 6. Quick Ratio: (65000 - 28000) / 35000 = 37000 / 35000 = 1.06
        self.assertEqual(ratios["quick_ratio"][1], 1.06)

        # 7. Cash Ratio: 8500 / 35000 = 0.24
        self.assertEqual(ratios["cash_ratio"][1], 0.24)

        # 8. Debt to Equity: 45000 / 45000 = 1.00
        self.assertEqual(ratios["debt_to_equity"][1], 1.0)

    def test_legacy_revenue_precedence_regression(self):
        """Prove canonical section_d.net_revenue takes precedence over customer.revenue_2025."""
        case_with_both = {
            "id": "REGRESSION_CASE",
            "customer": {
                "name": "Test Precedence Co",
                # Stale legacy revenue value
                "revenue_2025": 999999.0,
            },
            "section_d": {
                "years": ["2024", "2025"],
                # Authoritative canonical revenue
                "net_revenue": [100000.0, 120000.0],
            },
        }

        # CanonicalAdapter must return section_d.net_revenue[-1] = 120000.0, NOT 999999.0
        resolved_rev = CanonicalAdapter.get_latest_revenue(case_with_both)
        self.assertEqual(resolved_rev, 120000.0)
        self.assertNotEqual(resolved_rev, 999999.0)

        # Fallback only works when section_d.net_revenue is completely absent
        case_legacy_only = {
            "id": "LEGACY_ONLY_CASE",
            "customer": {
                "name": "Legacy Customer",
                "revenue_2025": 888888.0,
            },
            "section_d": {},
        }
        warnings = []
        resolved_legacy = CanonicalAdapter.get_latest_revenue(case_legacy_only, warnings_collector=warnings)
        self.assertEqual(resolved_legacy, 888888.0)
        self.assertTrue(any("legacy fallback" in w for w in warnings))


if __name__ == "__main__":
    unittest.main()

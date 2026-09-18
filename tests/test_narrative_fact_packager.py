# -*- coding: utf-8 -*-
"""Unit tests for FactPackager in msb_eb_copilot.src.narrative."""

import unittest
from decimal import Decimal
from msb_eb_copilot.src.narrative.models import (
    FactItem, FactAuthority, FactNature, FactCompleteness,
    FactManifest
)
from msb_eb_copilot.src.narrative.fact_packager import FactPackager


class TestNarrativeFactPackager(unittest.TestCase):
    def setUp(self):
        self.packager = FactPackager()
        self.sample_case_data = {
            "id": "TEST_CASE",
            "name": "CÔNG TY CỔ PHẦN THỬ NGHIỆM",
            "customer": {
                "name": "CÔNG TY CỔ PHẦN THỬ NGHIỆM",
                "short_name": "TEST_CORP",
                "tax_code": "0123456789",
                "established_year": 2010,
                "address": "Hà Nội, Việt Nam",
                "charter_capital": 50000.0,
                "rating_grade": "A+",
                "rating_score": 85.0,
            },
            "rm_metadata": {
                "unit_name": "ĐVKD HÀ NỘI",
                "rm_name": "Nguyễn Văn A",
                "rm_phone": "0987654321",
                "manager_name": "Trần Văn B",
            },
            "section_b": {
                "total_limit": 100000.0,
                "loan_limit": 60000.0,
                "guarantee_limit": 40000.0,
                "loan_purpose": "Bổ sung vốn lưu động",
                "collateral_type": "Bất động sản",
                "cashflow_commitment_pct": 80.0,
                "cashflow_direct_pct": 50.0,
            },
            "section_c": {
                "business_model": "THUONG_MAI",
                "main_products": "Vật tư xây dựng",
                "market_share_position": "Top 3 khu vực phía Bắc",
                "target_customers": "Các nhà thầu xây dựng",
                "warehouses": [
                    {"name": "Kho 1", "location": "Hà Nội", "area_sqm": 5000}
                ]
            },
            "section_d": {
                "years": ["2023", "2024", "2025"],
                "net_revenue": [500000.0, 600000.0, 750000.0],
                "cogs": [450000.0, 530000.0, 660000.0],
                "gross_profit": [50000.0, 70000.0, 90000.0],
                "financial_expenses": [10000.0, 12000.0, 15000.0],
                "interest_expenses": [8000.0, 10000.0, 12000.0],
                "operating_expenses": [25000.0, 30000.0, 38000.0],
                "net_profit": [12000.0, 22000.0, 30000.0],
                "current_assets": [200000.0, 250000.0, 320000.0],
                "cash_and_equivalents": [30000.0, 40000.0, 60000.0],
                "receivables": [90000.0, 110000.0, 140000.0],
                "inventories": [70000.0, 90000.0, 110000.0],
                "total_assets": [300000.0, 380000.0, 480000.0],
                "liabilities": [200000.0, 260000.0, 330000.0],
                "short_term_debt": [80000.0, 100000.0, 130000.0],
                "equity": [100000.0, 120000.0, 150000.0],
                "ocf": [15000.0, 20000.0, 28000.0],
            },
            "section_e": {
                "cic_date": "31/12/2025",
                "msb_outstanding": 45000.0,
                "history_status": "Nhóm 1",
                "relations": [
                    {
                        "bank_name": "Ngân hàng TMCP Hàng Hải Việt Nam (MSB)",
                        "short_term_limit_million_vnd": 50000.0,
                        "short_term_debt_vnd_million": 45000.0,
                        "debt_group": "NHOM_1_DU_TIEU_CHUAN"
                    },
                    {
                        "bank_name": "Ngân hàng TMCP Ngoại thương Việt Nam (VCB)",
                        "short_term_limit_million_vnd": 60000.0,
                        "short_term_debt_vnd_million": 40000.0,
                        "debt_group": "NHOM_1_DU_TIEU_CHUAN"
                    }
                ]
            }
        }

    def test_package_from_case_data_creates_valid_manifest(self):
        manifest = self.packager.package_from_case_data(self.sample_case_data, case_id="TEST_CASE")
        self.assertIsInstance(manifest, FactManifest)
        self.assertEqual(manifest.case_id, "TEST_CASE")
        self.assertTrue(len(manifest.get_all_facts()) > 20)
        self.assertTrue(len(manifest.manifest_hash) == 64)

    def test_deterministic_hash_stability(self):
        m1 = self.packager.package_from_case_data(self.sample_case_data, case_id="TEST_CASE")
        m2 = self.packager.package_from_case_data(self.sample_case_data, case_id="TEST_CASE")
        self.assertEqual(m1.manifest_hash, m2.manifest_hash)

    def test_hash_changes_when_data_changes(self):
        m1 = self.packager.package_from_case_data(self.sample_case_data, case_id="TEST_CASE")
        modified_data = dict(self.sample_case_data)
        modified_data["section_d"] = dict(self.sample_case_data["section_d"])
        modified_data["section_d"]["net_revenue"] = [500000.0, 600000.0, 800000.0]
        m2 = self.packager.package_from_case_data(modified_data, case_id="TEST_CASE")
        self.assertNotEqual(m1.manifest_hash, m2.manifest_hash)

    def test_display_representations_generation(self):
        manifest = self.packager.package_from_case_data(self.sample_case_data, case_id="TEST_CASE")
        rev_fact = manifest.get_fact("FIN_REV_2025")
        self.assertIsNotNone(rev_fact)
        self.assertIn("750000", rev_fact.display_representations)
        self.assertIn("750.000", rev_fact.display_representations)
        self.assertTrue(any("750" in r for r in rev_fact.display_representations))

    def test_ratios_derived_by_canonical_calculator(self):
        manifest = self.packager.package_from_case_data(self.sample_case_data, case_id="TEST_CASE")
        cr_fact = manifest.get_fact("RATIO_CURRENT_RATIO_2025")
        self.assertIsNotNone(cr_fact)
        self.assertEqual(cr_fact.fact_nature, FactNature.DERIVED_METRIC)
        self.assertAlmostEqual(float(cr_fact.value), 320000.0 / 130000.0, places=2)

    def test_incomplete_cic_generates_data_gap(self):
        case_with_incomplete_cic = dict(self.sample_case_data)
        case_with_incomplete_cic["section_e"] = {
            "is_incomplete": True,
            "incomplete_reason": "Thiếu dữ liệu quy đổi USD tại Shinhan Bank",
            "relations": []
        }
        manifest = self.packager.package_from_case_data(case_with_incomplete_cic, case_id="TEST_CASE")
        cic_gaps = [g for g in manifest.data_gaps if "CIC" in g.fact_id or "cic" in g.canonical_path]
        self.assertTrue(len(cic_gaps) > 0)


if __name__ == "__main__":
    unittest.main()

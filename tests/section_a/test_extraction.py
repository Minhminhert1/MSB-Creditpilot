"""Tests for Section A fact extraction and normalization (Phase 5)."""

from decimal import Decimal
import unittest

from msb_eb_copilot.src.section_a import CandidateStatus
from msb_eb_copilot.src.section_a.extractors import (
    CompanyCharterExtractor,
    EnterpriseRegistrationExtractor,
    FinancialWorkbookMB09Extractor,
)
from msb_eb_copilot.src.section_a.normalizers import (
    normalize_date,
    normalize_identifier,
    normalize_monetary_to_million_vnd,
)


class SectionAExtractionAndNormalizationTests(unittest.TestCase):
    """Test suite for Section A normalizers and semantic extractors."""

    def test_normalize_identifier(self):
        # Leading zero preserved, dots/spaces/hyphens removed
        self.assertEqual(normalize_identifier(" 0305097236 "), "0305097236")
        self.assertEqual(normalize_identifier("030.509.7236-001"), "0305097236001")
        self.assertEqual(normalize_identifier(" 0100 013 557 "), "0100013557")

        with self.assertRaises(ValueError):
            normalize_identifier("   ")
        with self.assertRaises(TypeError):
            normalize_identifier(305097236)  # type: ignore

    def test_normalize_date(self):
        self.assertEqual(normalize_date("ngày 15 tháng 10 năm 2024"), "2024-10-15")
        self.assertEqual(normalize_date("ngày 5 tháng 4 năm 2007"), "2007-04-05")
        self.assertEqual(normalize_date("15/10/2024"), "2024-10-15")
        self.assertEqual(normalize_date("2024-10-15"), "2024-10-15")
        self.assertEqual(normalize_date("2024"), "2024")

    def test_normalize_monetary_to_million_vnd(self):
        # VND to million VND
        self.assertEqual(
            normalize_monetary_to_million_vnd("900.000.000.000 đồng", source_unit="VND"),
            Decimal("900000"),
        )
        self.assertEqual(
            normalize_monetary_to_million_vnd(900000000000, source_unit="VND"),
            Decimal("900000"),
        )
        # Triệu đồng directly
        self.assertEqual(
            normalize_monetary_to_million_vnd("6.162.331,83414", source_unit="triệu đồng"),
            Decimal("6162331.83414"),
        )
        # Tỷ đồng to million VND
        self.assertEqual(
            normalize_monetary_to_million_vnd("1.500 tỷ", source_unit="tỷ"),
            Decimal("1500000"),
        )

    def test_gpkd_extraction_extracts_legal_profile(self):
        gpkd_text = (
            "SỞ KẾ HOẠCH VÀ ĐẦU TƯ TỈNH BÀ RỊA - VŨNG TÀU\n"
            "PHÒNG ĐĂNG KÝ KINH DOANH\n"
            "GIẤY CHỨNG NHẬN ĐĂNG KÝ DOANH NGHIỆP\n"
            "Mã số doanh nghiệp: 0305097236\n"
            "Đăng ký lần đầu: ngày 25 tháng 07 năm 2007\n"
            "Đăng ký thay đổi lần thứ 8: ngày 30 tháng 10 năm 2025\n"
            "Tên công ty viết bằng tiếng Việt: CÔNG TY TNHH MTV THÉP MIỀN NAM - VNSTEEL\n"
            "Tên công ty viết tắt: THEPMIENNAM\n"
            "Địa chỉ trụ sở chính: Khu công nghiệp Mỹ Xuân A, Phường Mỹ Xuân, Thị xã Phú Mỹ, Tỉnh Bà Rịa - Vũng Tàu, Việt Nam\n"
            "Điện thoại: 0254 3894 123\n"
            "Vốn điều lệ: 900.000.000.000 đồng\n"
            "Người đại diện theo pháp luật của công ty:\n"
            "Họ và tên: NGUYỄN NGUYÊN NGỌC   Giới tính: Nam\n"
            "Chức danh: Tổng Giám đốc\n"
            "Ngành, nghề kinh doanh chính:\n"
            "Sản xuất sắt, thép, gang. Mã ngành: 2410 - Sản xuất gang, sắt, thép\n"
        )
        extractor = EnterpriseRegistrationExtractor()
        candidates = extractor.extract(
            document_id="doc-gpkd-001",
            text_content=gpkd_text,
            original_filename="gpkd.pdf",
        )
        keys_found = {c.canonical_key for c in candidates}

        self.assertIn("company.legal_name", keys_found)
        self.assertIn("company.short_name", keys_found)
        self.assertIn("company.registration_no", keys_found)
        self.assertIn("company.registered_address", keys_found)
        self.assertIn("company.legal_representative.name", keys_found)
        self.assertIn("company.legal_representative.title", keys_found)
        self.assertIn("capital.registered_capital", keys_found)
        self.assertIn("business.primary_industry.code_level_5", keys_found)
        self.assertIn("business.primary_industry.name", keys_found)

        # Check values
        name_cand = [c for c in candidates if c.canonical_key == "company.legal_name"][0]
        self.assertEqual(name_cand.candidate_value, "CÔNG TY TNHH MTV THÉP MIỀN NAM - VNSTEEL")

        reg_cand = [c for c in candidates if c.canonical_key == "company.registration_no"][0]
        self.assertEqual(reg_cand.candidate_value, "0305097236")

        # Two dates extracted with explicit labels
        dates = [c for c in candidates if c.canonical_key == "company.registration_issue_date"]
        self.assertEqual(len(dates), 2)
        date_labels = {d.evidence_label for d in dates}
        self.assertIn("first registration date", date_labels)
        self.assertIn("amendment #8 date", date_labels)

        # Strict rule: operation_start_date_or_year MUST NOT be inferred!
        self.assertNotIn("company.operation_start_date_or_year", keys_found)

    def test_charter_extraction(self):
        charter_text = (
            "ĐIỀU LỆ TỔ CHỨC VÀ HOẠT ĐỘNG CỦA CÔNG TY CỔ PHẦN KINH DOANH KHÍ MIỀN NAM\n"
            "Công ty là công ty con của: Tổng công ty Khí Việt Nam - CTCP (PV GAS)\n"
            "Vốn điều lệ của công ty là: 500.000.000.000 đồng\n"
        )
        extractor = CompanyCharterExtractor()
        candidates = extractor.extract(
            document_id="doc-charter-01",
            text_content=charter_text,
            original_filename="dieu_le.pdf",
        )
        group_cands = [c for c in candidates if c.canonical_key == "company.group_name"]
        self.assertEqual(len(group_cands), 1)
        self.assertEqual(group_cands[0].candidate_value, "Tổng công ty Khí Việt Nam - CTCP (PV GAS)")

        cap_cands = [c for c in candidates if c.canonical_key == "capital.registered_capital"]
        self.assertEqual(len(cap_cands), 1)
        self.assertEqual(cap_cands[0].candidate_value, Decimal("500000"))
        self.assertEqual(cap_cands[0].unit, "triệu đồng")

    def test_mb09_revenue_conflict_preservation(self):
        """Rule: When both HN and RL revenue figures are found, mark as CONFLICTING."""
        sheets_data = {
            "HN_2025": [
                {"label": "Doanh thu thuần về bán hàng và cung cấp dịch vụ", "amount": "6162331.83414", "unit": "triệu đồng", "year": "2025"},
                {"label": "Vốn góp của chủ sở hữu", "amount": "500000", "unit": "triệu đồng", "as_of": "2025-12-31"},
            ],
            "RL_2025": [
                {"label": "Doanh thu thuần về bán hàng và cung cấp dịch vụ", "amount": "5518843.929542", "unit": "triệu đồng", "year": "2025"},
                {"label": "Vốn góp của chủ sở hữu", "amount": "500000", "unit": "triệu đồng", "as_of": "2025-12-31"},
            ],
        }
        extractor = FinancialWorkbookMB09Extractor()
        candidates = extractor.extract_from_sheets_data(
            document_id="doc-mb09-01",
            sheets_data=sheets_data,
            original_filename="MB09.xlsx",
        )
        rev_cands = [c for c in candidates if c.canonical_key == "financial.latest_net_revenue"]
        self.assertEqual(len(rev_cands), 2)
        # Both must be marked CONFLICTING
        for c in rev_cands:
            self.assertEqual(c.status, CandidateStatus.CONFLICTING)

        cap_cands = [c for c in candidates if c.canonical_key == "capital.paid_in_capital"]
        self.assertTrue(len(cap_cands) >= 1)
        self.assertEqual(cap_cands[0].candidate_value, Decimal("500000"))


if __name__ == "__main__":
    unittest.main()

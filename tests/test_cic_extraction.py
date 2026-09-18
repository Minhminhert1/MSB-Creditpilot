# -*- coding: utf-8 -*-
"""Unit tests for Phase 4: CIC Extraction Models, Normalizer, Grounding Auditor, and Identity Reconciler."""

import unittest
from pydantic import ValidationError

from msb_eb_copilot.src.extraction.cic_extraction import (
    CICEvidenceField,
    CICFacilityItem,
    CICInstitutionItem,
    CICDocumentExtraction,
    CICGroundingAuditor,
    CICNormalizer,
    CICIdentityReconciler,
)


class TestCICExtractionModels(unittest.TestCase):
    """Test strict Pydantic schemas forbidding extra fields."""

    def test_strict_field_extra_forbidden(self):
        with self.assertRaises(ValidationError):
            CICEvidenceField(
                value_raw="15.000",
                page=1,
                evidence="Hạn mức: 15.000",
                extra_hallucinated_field="forbidden"
            )

    def test_strict_facility_item_extra_forbidden(self):
        with self.assertRaises(ValidationError):
            CICFacilityItem(
                bank_name=CICEvidenceField(value_raw="VCB", page=1, evidence="VCB"),
                extra_param="not_allowed"
            )

    def test_strict_institution_item_extra_forbidden(self):
        with self.assertRaises(ValidationError):
            CICInstitutionItem(
                bank_name=CICEvidenceField(value_raw="MSB", page=1, evidence="MSB"),
                hallucinated_key=123
            )

    def test_valid_cic_document_extraction(self):
        doc = CICDocumentExtraction(
            customer_name=CICEvidenceField(value_raw="CTY CP THĂNG LONG", page=1, evidence="Tên: CTY CP THĂNG LONG"),
            tax_code=CICEvidenceField(value_raw="0109876543", page=1, evidence="MST: 0109876543"),
            cic_report_date=CICEvidenceField(value_raw="28/02/2026", page=1, evidence="Ngày tra cứu: 28/02/2026"),
            customer_highest_debt_group=CICEvidenceField(value_raw="Nhóm 1", page=1, evidence="Nhóm nợ cao nhất: Nhóm 1"),
            is_overdue_12m=CICEvidenceField(value_raw="Không có nợ quá hạn", page=1, evidence="Trong 12 tháng gần nhất không có nợ quá hạn"),
            derivative_transactions_info=CICEvidenceField(value_raw=None, page=None, evidence=None),
            institutions=[
                CICInstitutionItem(
                    bank_name=CICEvidenceField(value_raw="MSB", page=1, evidence="Ngân hàng TMCP Hàng Hải Việt Nam"),
                    short_term_debt_vnd_raw=CICEvidenceField(value_raw="5.200", page=1, evidence="Dư nợ ngắn hạn VND: 5.200"),
                    debt_group=CICEvidenceField(value_raw="Nhóm 1", page=1, evidence="Nhóm 1"),
                )
            ]
        )
        self.assertEqual(doc.tax_code.value_raw, "0109876543")
        self.assertEqual(len(doc.institutions), 1)
        self.assertIsNone(doc.derivative_transactions_info.value_raw)


class TestCICGroundingAuditor(unittest.TestCase):
    """Test verbatim grounding and page bounds verification."""

    def setUp(self):
        self.tagged_text = (
            "[PAGE 1]\n"
            "TRUNG TÂM THÔNG TIN TÍN DỤNG QUỐC GIA VIỆT NAM (CIC)\n"
            "Tên khách hàng: CÔNG TY CỔ PHẦN CÔNG NGHỆ THĂNG LONG\n"
            "Mã số thuế: 0109876543\n"
            "Ngày tra cứu: 28/02/2026\n"
            "Trong 12 tháng gần nhất không có nợ quá hạn.\n"
            "[PAGE 2]\n"
            "Ngân hàng TMCP Hàng Hải Việt Nam (MSB)\n"
            "Dư nợ ngắn hạn VND: 5.200 triệu\n"
            "Tổng dư nợ: 7.200 triệu đồng\n"
        )
        self.pages_text, self.max_page = CICGroundingAuditor.extract_pages(self.tagged_text)

    def test_extract_pages(self):
        self.assertEqual(self.max_page, 2)
        self.assertIn("thăng long", self.pages_text[1].lower())
        self.assertIn("hàng hải", self.pages_text[2].lower())

    def test_audit_field_verified(self):
        field = CICEvidenceField(
            value_raw="0109876543",
            page=1,
            evidence="Mã số thuế: 0109876543"
        )
        res = CICGroundingAuditor.audit_field(field, "customer.tax_code", self.pages_text, self.max_page)
        self.assertEqual(res.status, "VERIFIED")

    def test_audit_field_page_out_of_bounds(self):
        field = CICEvidenceField(
            value_raw="0109876543",
            page=99,
            evidence="Mã số thuế: 0109876543"
        )
        res = CICGroundingAuditor.audit_field(field, "customer.tax_code", self.pages_text, self.max_page)
        self.assertEqual(res.status, "REJECTED")
        self.assertIn("out of bounds", res.message)

    def test_audit_field_evidence_empty(self):
        field = CICEvidenceField(
            value_raw="0109876543",
            page=1,
            evidence=""
        )
        res = CICGroundingAuditor.audit_field(field, "customer.tax_code", self.pages_text, self.max_page)
        self.assertEqual(res.status, "REJECTED")

    def test_audit_field_evidence_mismatch(self):
        field = CICEvidenceField(
            value_raw="9999999999",
            page=1,
            evidence="Mã số thuế bịa đặt: 9999999999"
        )
        res = CICGroundingAuditor.audit_field(field, "customer.tax_code", self.pages_text, self.max_page)
        self.assertEqual(res.status, "REJECTED")


class TestCICNormalizer(unittest.TestCase):
    """Test monetary parsing, debt group parsing, and tri-state overdue normalization."""

    def test_parse_monetary(self):
        val, err = CICNormalizer.parse_monetary("15.000", unit_hint="triệu")
        self.assertIsNone(err)
        self.assertEqual(val, 15000.0)

        val, err = CICNormalizer.parse_monetary("8.500,50", unit_hint="triệu")
        self.assertIsNone(err)
        self.assertEqual(val, 8500.5)

        val, err = CICNormalizer.parse_monetary("0")
        self.assertIsNone(err)
        self.assertEqual(val, 0.0)

        val, err = CICNormalizer.parse_monetary("-")
        self.assertIsNone(err)
        self.assertIsNone(val)

        val, err = CICNormalizer.parse_monetary(None)
        self.assertIsNone(err)
        self.assertIsNone(val)

    def test_parse_debt_group(self):
        self.assertEqual(CICNormalizer.parse_debt_group("Nhóm 1"), 1)
        self.assertEqual(CICNormalizer.parse_debt_group("1"), 1)
        self.assertEqual(CICNormalizer.parse_debt_group("Nhóm 2 (Cần chú ý)"), 2)
        self.assertEqual(CICNormalizer.parse_debt_group("Nhóm 3"), 3)
        self.assertEqual(CICNormalizer.parse_debt_group("Nhóm 4"), 4)
        self.assertEqual(CICNormalizer.parse_debt_group("Nhóm 5"), 5)
        self.assertIsNone(CICNormalizer.parse_debt_group("Nhóm 6"))
        self.assertIsNone(CICNormalizer.parse_debt_group(None))

    def test_parse_tri_state_overdue(self):
        # Explicit clean -> False
        self.assertFalse(CICNormalizer.parse_tri_state_overdue("Trong 12 tháng gần nhất không có nợ quá hạn"))
        self.assertFalse(CICNormalizer.parse_tri_state_overdue("Không phát sinh nợ quá hạn"))
        self.assertFalse(CICNormalizer.parse_tri_state_overdue("Không có nợ cần chú ý"))

        # Explicit overdue -> True
        self.assertTrue(CICNormalizer.parse_tri_state_overdue("Có nợ quá hạn 10 ngày"))
        self.assertTrue(CICNormalizer.parse_tri_state_overdue("Phát sinh nợ quá hạn"))
        self.assertTrue(CICNormalizer.parse_tri_state_overdue("Chậm thanh toán"))

        # Absent / uncertain -> None
        self.assertIsNone(CICNormalizer.parse_tri_state_overdue(None))
        self.assertIsNone(CICNormalizer.parse_tri_state_overdue(""))
        self.assertIsNone(CICNormalizer.parse_tri_state_overdue("Không có thông tin tra cứu"))


class TestCICIdentityReconciler(unittest.TestCase):
    """Test identity checking without mutating customer.*."""

    def test_identity_match(self):
        cust = {"tax_code": "0109876543", "name": "CÔNG TY CỔ PHẦN CÔNG NGHỆ THĂNG LONG"}
        status, msg = CICIdentityReconciler.reconcile("0109876543", "CÔNG TY CỔ PHẦN CÔNG NGHỆ THĂNG LONG", cust)
        self.assertEqual(status, "MATCH")
        self.assertIn("trùng khớp", msg)
        self.assertEqual(cust["tax_code"], "0109876543")

    def test_identity_name_warning(self):
        cust = {"tax_code": "0109876543", "name": "CTY CP CN THĂNG LONG"}
        status, msg = CICIdentityReconciler.reconcile("0109876543", "CÔNG TY HOÀN TOÀN KHÁC", cust)
        self.assertEqual(status, "WARNING")
        self.assertIn("khác biệt", msg)

    def test_identity_tax_mismatch(self):
        cust = {"tax_code": "0109876543", "name": "CTY CP THĂNG LONG"}
        status, msg = CICIdentityReconciler.reconcile("0301234567", "CTY CP DẦU KHÍ", cust)
        self.assertEqual(status, "MISMATCH")
        self.assertIn("KHÔNG TRÙNG KHỚP", msg)

    def test_identity_missing_cic_tax_code(self):
        cust = {"tax_code": "0109876543", "name": "CTY CP THĂNG LONG"}
        status, msg = CICIdentityReconciler.reconcile(None, "CTY CP THĂNG LONG", cust)
        self.assertEqual(status, "WARNING")


if __name__ == "__main__":
    unittest.main()

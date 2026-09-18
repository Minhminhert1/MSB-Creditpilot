# -*- coding: utf-8 -*-
"""Unit tests for Phase 3A: Financial Extraction, Parsers, Unit Resolver, and Grounding Auditor."""

import unittest
from decimal import Decimal
from unittest.mock import patch, MagicMock

from msb_eb_copilot.src.extraction.financial_extraction import (
    AccountingSemanticInterpreter,
    FinancialDocumentExtraction,
    FinancialDocumentExtractor,
    FinancialEvidenceField,
    FinancialGroundingAuditor,
    FinancialPeriodExtraction,
    FinancialUnitInfo,
    FinancialUnitResolver,
    LexicalFinancialNumberParser,
)


class TestLexicalFinancialNumberParser(unittest.TestCase):
    """Test Stage A lexical number decomposition."""

    def test_standard_vietnamese_dot_separator(self):
        tok, err = LexicalFinancialNumberParser.parse_token("120.000.000")
        self.assertIsNone(err)
        self.assertEqual(tok.cleaned_digits, "120000000")
        self.assertFalse(tok.is_negative)
        self.assertFalse(tok.is_zero)
        self.assertFalse(tok.is_dash)

    def test_vietnamese_comma_decimal(self):
        tok, err = LexicalFinancialNumberParser.parse_token("120.000.000,50")
        self.assertIsNone(err)
        self.assertEqual(tok.cleaned_digits, "120000000.50")
        self.assertFalse(tok.is_negative)

    def test_parentheses_negative(self):
        tok, err = LexicalFinancialNumberParser.parse_token("(12.500.000)")
        self.assertIsNone(err)
        self.assertEqual(tok.cleaned_digits, "12500000")
        self.assertTrue(tok.is_negative)
        self.assertTrue(tok.is_parentheses)

    def test_leading_minus_negative(self):
        tok, err = LexicalFinancialNumberParser.parse_token("-5.000.000")
        self.assertIsNone(err)
        self.assertEqual(tok.cleaned_digits, "5000000")
        self.assertTrue(tok.is_negative)

    def test_accounting_dash(self):
        for dash in ("-", "–", "—", "- -"):
            tok, err = LexicalFinancialNumberParser.parse_token(dash)
            self.assertIsNone(err)
            self.assertTrue(tok.is_dash)
            self.assertFalse(tok.is_negative)

    def test_zero_representations(self):
        tok, err = LexicalFinancialNumberParser.parse_token("0")
        self.assertIsNone(err)
        self.assertTrue(tok.is_zero)

        tok2, err2 = LexicalFinancialNumberParser.parse_token("0.0")
        self.assertIsNone(err2)
        self.assertTrue(tok2.is_zero)

    def test_empty_input(self):
        tok, err = LexicalFinancialNumberParser.parse_token("")
        self.assertIsNone(err)
        self.assertTrue(tok.is_empty)

        tok_none, err_none = LexicalFinancialNumberParser.parse_token(None)
        self.assertIsNone(err_none)
        self.assertTrue(tok_none.is_empty)

    def test_invalid_tokens(self):
        tok, err = LexicalFinancialNumberParser.parse_token("abc")
        self.assertIsNone(tok)
        self.assertIn("No numeric digits", err)


class TestAccountingSemanticInterpreter(unittest.TestCase):
    """Test Stage B semantic interpretation."""

    def test_dash_interpreted_as_none(self):
        # Strict rule: dash means missing / not reported, do not fabricate fact
        tok, _ = LexicalFinancialNumberParser.parse_token("-")
        val, err = AccountingSemanticInterpreter.interpret(tok)
        self.assertIsNone(val)
        self.assertIsNone(err)

    def test_zero_interpreted_as_decimal_zero(self):
        tok, _ = LexicalFinancialNumberParser.parse_token("0")
        val, err = AccountingSemanticInterpreter.interpret(tok)
        self.assertEqual(val, Decimal("0"))

    def test_positive_and_negative_decimals(self):
        tok_pos, _ = LexicalFinancialNumberParser.parse_token("120.000.000")
        val_pos, err = AccountingSemanticInterpreter.interpret(tok_pos)
        self.assertEqual(val_pos, Decimal("120000000"))

        tok_neg, _ = LexicalFinancialNumberParser.parse_token("(15.000.000)")
        val_neg, err = AccountingSemanticInterpreter.interpret(tok_neg)
        self.assertEqual(val_neg, Decimal("-15000000"))


class TestFinancialUnitResolver(unittest.TestCase):
    """Test per-fact unit resolution and conversion to triệu VND."""

    def test_field_level_unit_vnd(self):
        amount = Decimal("120000000000")  # 120 billion VND
        norm_val, res_unit, unit_ev, err = FinancialUnitResolver.resolve_and_normalize(
            amount=amount,
            field_unit="VND",
            page_unit=None,
            doc_unit=None,
        )
        self.assertIsNone(err)
        self.assertEqual(norm_val, Decimal("120000.00"))  # 120,000 triệu VND
        self.assertEqual(res_unit, "VND")
        self.assertIn("Field unit", unit_ev)

    def test_page_level_unit_nghin_dong(self):
        amount = Decimal("50000000")  # 50,000,000 nghìn đồng
        page_u = FinancialUnitInfo(unit_raw="nghìn đồng", evidence="Đơn vị tính: nghìn đồng", page=2)
        norm_val, res_unit, unit_ev, err = FinancialUnitResolver.resolve_and_normalize(
            amount=amount,
            field_unit=None,
            page_unit=page_u,
            doc_unit=None,
        )
        self.assertIsNone(err)
        self.assertEqual(norm_val, Decimal("50000.00"))  # 50,000 triệu VND
        self.assertEqual(res_unit, "nghìn đồng")

    def test_document_level_unit_trieu_dong(self):
        amount = Decimal("45000")  # 45,000 triệu đồng
        doc_u = FinancialUnitInfo(unit_raw="triệu đồng", evidence="Đơn vị tính: triệu đồng", page=1)
        norm_val, res_unit, unit_ev, err = FinancialUnitResolver.resolve_and_normalize(
            amount=amount,
            field_unit=None,
            page_unit=None,
            doc_unit=doc_u,
        )
        self.assertIsNone(err)
        self.assertEqual(norm_val, Decimal("45000.00"))  # unchanged

    def test_ty_dong_unit(self):
        amount = Decimal("250")  # 250 tỷ
        norm_val, res_unit, unit_ev, err = FinancialUnitResolver.resolve_and_normalize(
            amount=amount,
            field_unit="tỷ đồng",
            page_unit=None,
            doc_unit=None,
        )
        self.assertIsNone(err)
        self.assertEqual(norm_val, Decimal("250000.00"))  # 250,000 triệu VND

    def test_missing_unit_hierarchy(self):
        amount = Decimal("1000")
        norm_val, res_unit, unit_ev, err = FinancialUnitResolver.resolve_and_normalize(
            amount=amount,
            field_unit=None,
            page_unit=None,
            doc_unit=None,
        )
        self.assertIsNone(norm_val)
        self.assertIn("No grounded currency unit", err)


class TestFinancialGroundingAuditor(unittest.TestCase):
    """Test evidence and grounding auditor."""

    def setUp(self):
        self.tagged_text = """[PAGE 1]
BÁO CÁO KẾT QUẢ HOẠT ĐỘNG KINH DOANH
Đơn vị tính: VND
Doanh thu thuần về bán hàng và cung cấp dịch vụ | 10 | 120.000.000.000
Giá vốn hàng bán | 11 | 96.000.000.000
Lợi nhuận gộp về bán hàng và cung cấp dịch vụ | 20 | 24.000.000.000
[PAGE 2]
BẢNG CÂN ĐỐI KẾ TOÁN
Đơn vị tính: VND
A. TÀI SẢN NGẮN HẠN | 100 | 65.000.000.000
Tiền và các khoản tương đương tiền | 110 | 8.500.000.000
"""

    def test_perfect_grounding_audit(self):
        field_data = FinancialEvidenceField(
            value_raw="120.000.000.000",
            semantic_label="Doanh thu thuần về bán hàng và cung cấp dịch vụ",
            accounting_code="10",
            evidence="Doanh thu thuần về bán hàng và cung cấp dịch vụ | 10 | 120.000.000.000",
            page=1,
        )
        errs = FinancialGroundingAuditor.audit_field("net_revenue", field_data, self.tagged_text, 2)
        self.assertEqual(errs, [])

    def test_missing_page_number(self):
        field_data = FinancialEvidenceField(
            value_raw="120.000.000.000",
            evidence="Doanh thu thuần | 120.000.000.000",
            page=None,
        )
        errs = FinancialGroundingAuditor.audit_field("net_revenue", field_data, self.tagged_text, 2)
        self.assertTrue(any("Missing declared page" in e for e in errs))

    def test_page_out_of_bounds(self):
        field_data = FinancialEvidenceField(
            value_raw="120.000.000.000",
            evidence="Doanh thu thuần | 120.000.000.000",
            page=99,
        )
        errs = FinancialGroundingAuditor.audit_field("net_revenue", field_data, self.tagged_text, 2)
        self.assertTrue(any("exceeds physical pages" in e for e in errs))

    def test_evidence_not_on_declared_page(self):
        # Evidence is on page 1, but declared page is 2
        field_data = FinancialEvidenceField(
            value_raw="120.000.000.000",
            evidence="Doanh thu thuần về bán hàng và cung cấp dịch vụ | 10 | 120.000.000.000",
            page=2,
        )
        errs = FinancialGroundingAuditor.audit_field("net_revenue", field_data, self.tagged_text, 2)
        self.assertTrue(any("Evidence not found on declared Page 2" in e for e in errs))

    def test_raw_value_not_inside_evidence(self):
        field_data = FinancialEvidenceField(
            value_raw="999.999.999",
            evidence="Doanh thu thuần về bán hàng | 10 | 120.000.000.000",
            page=1,
        )
        errs = FinancialGroundingAuditor.audit_field("net_revenue", field_data, self.tagged_text, 2)
        self.assertTrue(any("Raw numeric value" in e for e in errs))

    def test_accounting_code_conflict(self):
        # Mã 11 is COGS, but bound to net_revenue
        field_data = FinancialEvidenceField(
            value_raw="96.000.000.000",
            semantic_label="Giá vốn hàng bán",
            accounting_code="11",
            evidence="Giá vốn hàng bán | 11 | 96.000.000.000",
            page=1,
        )
        errs = FinancialGroundingAuditor.audit_field("net_revenue", field_data, self.tagged_text, 2)
        self.assertTrue(any("conflicts with expected code" in e for e in errs))


class TestFinancialDocumentExtractor(unittest.TestCase):
    """Test extractor JSON orchestration."""

    @patch("msb_eb_copilot.src.extraction.financial_extraction.AIAssistantClient.chat")
    def test_extractor_parses_json_payload(self, mock_chat):
        mock_chat.return_value = """{
            "document_title": "BCTC 2025",
            "document_unit": {"unit_raw": "VND", "evidence": "Đơn vị tính: VND", "page": 1},
            "page_units": {"1": {"unit_raw": "VND", "evidence": "Đơn vị tính: VND", "page": 1}},
            "periods": [
                {
                    "period": "2025",
                    "net_revenue": {"value_raw": "120.000.000.000", "semantic_label": "Doanh thu thuần", "accounting_code": "10", "evidence": "Doanh thu thuần 120.000.000.000", "page": 1}
                }
            ]
        }"""
        extractor = FinancialDocumentExtractor()
        res = extractor.extract("[PAGE 1] Some text", page_count=1)
        self.assertIsInstance(res, FinancialDocumentExtraction)
        self.assertEqual(len(res.periods), 1)
        self.assertEqual(res.periods[0].period, "2025")
        self.assertEqual(res.periods[0].net_revenue.value_raw, "120.000.000.000")

    @patch("msb_eb_copilot.src.extraction.financial_extraction.AIAssistantClient.chat")
    def test_extractor_handles_markdown_fenced_json(self, mock_chat):
        mock_chat.return_value = "```json\n{\"periods\": [{\"period\": \"2024\"}]}\n```"
        extractor = FinancialDocumentExtractor()
        res = extractor.extract("[PAGE 1]", page_count=1)
        self.assertEqual(len(res.periods), 1)
        self.assertEqual(res.periods[0].period, "2024")


if __name__ == "__main__":
    unittest.main()

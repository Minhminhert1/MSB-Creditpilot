# -*- coding: utf-8 -*-
"""Unit tests for Phase 3A: Financial Extraction, Parsers, Unit Resolver, and Grounding Auditor."""

import unittest
from decimal import Decimal
from unittest.mock import patch, MagicMock

import pydantic

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


class TestFinancialUnitInfoNormalization(unittest.TestCase):
    """Tests for the null-handling normalization of page_units/document_unit,
    fixing the confirmed production failure where the LLM emits page_units
    entries with null fields (e.g. {"unit_raw": null, "evidence": null, "page": 21})
    that used to crash Pydantic validation of FinancialDocumentExtraction.

    Policy: a unit record is either fully present (unit_raw/evidence non-blank
    strings + page non-blank) or fully absent -- never half-populated. Empty
    records are dropped/normalized to None; partial records raise loudly.
    """

    # -- A/B: page_units all-null / effectively-empty entries are dropped ----

    def test_a_page_units_entry_all_null_is_removed(self):
        ext = FinancialDocumentExtraction.model_validate({
            "page_units": {"21": {"unit_raw": None, "evidence": None, "page": None}}
        })
        self.assertEqual(ext.page_units, {})

    def test_b_page_units_entry_null_text_but_valid_page_is_removed(self):
        """B. unit_raw=None + evidence=None + a VALID page number: this is exactly
        the confirmed production shape. `page` alone carries no unit provenance,
        so this is treated as semantically empty (no evidence at all) and dropped,
        not treated as 'partial' -- this is precisely the case that must be fixed."""
        ext = FinancialDocumentExtraction.model_validate({
            "page_units": {"21": {"unit_raw": None, "evidence": None, "page": 21}}
        })
        self.assertEqual(ext.page_units, {})

    def test_page_units_entry_literally_null_is_removed(self):
        """A page_units value of JSON null (not even an object) is also absence."""
        ext = FinancialDocumentExtraction.model_validate({"page_units": {"22": None}})
        self.assertEqual(ext.page_units, {})

    # -- C/D: partially populated page_units entries raise loudly ------------

    def test_c_page_units_entry_unit_raw_present_evidence_none_raises(self):
        with self.assertRaises(pydantic.ValidationError):
            FinancialDocumentExtraction.model_validate({
                "page_units": {"22": {"unit_raw": "VND", "evidence": None, "page": 22}}
            })

    def test_d_page_units_entry_evidence_present_unit_raw_none_raises(self):
        with self.assertRaises(pydantic.ValidationError):
            FinancialDocumentExtraction.model_validate({
                "page_units": {"23": {"unit_raw": None, "evidence": "Đơn vị tính: VND", "page": 23}}
            })

    def test_page_units_entry_text_present_but_page_missing_raises(self):
        """Fully-present requires page too -- unit_raw+evidence alone is still partial."""
        with self.assertRaises(pydantic.ValidationError):
            FinancialDocumentExtraction.model_validate({
                "page_units": {"24": {"unit_raw": "VND", "evidence": "Đơn vị tính: VND", "page": None}}
            })

    def test_page_units_entry_whitespace_only_strings_treated_as_blank(self):
        """H8: whitespace-only strings count as empty for this normalization."""
        ext = FinancialDocumentExtraction.model_validate({
            "page_units": {"25": {"unit_raw": "   ", "evidence": "  \n\t ", "page": 25}}
        })
        self.assertEqual(ext.page_units, {})

        with self.assertRaises(pydantic.ValidationError):
            FinancialDocumentExtraction.model_validate({
                "page_units": {"26": {"unit_raw": "VND", "evidence": "   ", "page": 26}}
            })

    # -- E: fully valid page unit is preserved unchanged ----------------------

    def test_e_valid_full_page_unit_is_preserved(self):
        ext = FinancialDocumentExtraction.model_validate({
            "page_units": {"1": {"unit_raw": "VND", "evidence": "Đơn vị tính: VND", "page": 1}}
        })
        self.assertEqual(len(ext.page_units), 1)
        self.assertEqual(ext.page_units[1].unit_raw, "VND")
        self.assertEqual(ext.page_units[1].evidence, "Đơn vị tính: VND")
        self.assertEqual(ext.page_units[1].page, 1)

    def test_multiple_page_units_only_empty_ones_dropped(self):
        """Mix of valid, empty, and (would-be) partial entries: only the empty one
        is silently dropped; the valid one survives unaffected; nothing is
        fabricated from the other pages."""
        ext = FinancialDocumentExtraction.model_validate({
            "page_units": {
                "1": {"unit_raw": "VND", "evidence": "Đơn vị tính: VND", "page": 1},
                "2": {"unit_raw": None, "evidence": None, "page": 2},
                "3": {"unit_raw": "triệu đồng", "evidence": "Đơn vị tính: triệu đồng", "page": 3},
            }
        })
        self.assertEqual(set(ext.page_units.keys()), {1, 3})
        self.assertEqual(ext.page_units[1].unit_raw, "VND")
        self.assertEqual(ext.page_units[3].unit_raw, "triệu đồng")

    # -- F: document_unit all-null normalizes to None -------------------------

    def test_f_document_unit_all_null_normalizes_to_none(self):
        ext = FinancialDocumentExtraction.model_validate({
            "document_unit": {"unit_raw": None, "evidence": None, "page": None}
        })
        self.assertIsNone(ext.document_unit)

    def test_document_unit_literal_null_stays_none(self):
        ext = FinancialDocumentExtraction.model_validate({"document_unit": None})
        self.assertIsNone(ext.document_unit)

    def test_document_unit_absent_key_stays_none(self):
        ext = FinancialDocumentExtraction.model_validate({"document_title": "x"})
        self.assertIsNone(ext.document_unit)

    # -- G: partially populated document_unit raises loudly -------------------

    def test_g_partial_document_unit_raises(self):
        with self.assertRaises(pydantic.ValidationError):
            FinancialDocumentExtraction.model_validate({
                "document_unit": {"unit_raw": "VND", "evidence": None, "page": 1}
            })

    def test_partial_document_unit_evidence_present_unit_raw_missing_raises(self):
        with self.assertRaises(pydantic.ValidationError):
            FinancialDocumentExtraction.model_validate({
                "document_unit": {"unit_raw": None, "evidence": "Đơn vị tính: VND", "page": 1}
            })

    # -- H: valid document_unit is preserved -----------------------------------

    def test_h_valid_document_unit_is_preserved(self):
        ext = FinancialDocumentExtraction.model_validate({
            "document_unit": {"unit_raw": "VND", "evidence": "Đơn vị tính: VND", "page": 1}
        })
        self.assertIsNotNone(ext.document_unit)
        self.assertEqual(ext.document_unit.unit_raw, "VND")
        self.assertEqual(ext.document_unit.evidence, "Đơn vị tính: VND")
        self.assertEqual(ext.document_unit.page, 1)

    # -- I: existing unit resolution/fallback logic is untouched --------------

    def test_i_field_level_page_level_document_level_fallback_still_works(self):
        """I. FinancialUnitResolver's field -> page -> document fallback chain
        (unchanged production logic) still works correctly with page/document
        units that survive this new normalization step."""
        ext = FinancialDocumentExtraction.model_validate({
            "document_unit": {"unit_raw": "triệu đồng", "evidence": "Đơn vị tính: triệu đồng", "page": 1},
            "page_units": {"2": {"unit_raw": "nghìn đồng", "evidence": "Đơn vị tính: nghìn đồng", "page": 2}},
        })
        # Page-level unit takes precedence over document-level when both exist.
        norm_val, res_unit, _ev, err = FinancialUnitResolver.resolve_and_normalize(
            amount=Decimal("50000000"),
            field_unit=None,
            page_unit=ext.page_units.get(2),
            doc_unit=ext.document_unit,
        )
        self.assertIsNone(err)
        self.assertEqual(res_unit, "nghìn đồng")
        self.assertEqual(norm_val, Decimal("50000.00"))

        # Falls back to document-level unit when no page-level unit exists.
        norm_val2, res_unit2, _ev2, err2 = FinancialUnitResolver.resolve_and_normalize(
            amount=Decimal("45000"),
            field_unit=None,
            page_unit=ext.page_units.get(99),  # no unit for page 99
            doc_unit=ext.document_unit,
        )
        self.assertIsNone(err2)
        self.assertEqual(res_unit2, "triệu đồng")

    # -- J: no fabrication of unit/evidence/page -------------------------------

    def test_j_normalization_never_fabricates_values(self):
        """J. Dropped/empty entries must vanish entirely -- never replaced with a
        placeholder, never backfilled from a sibling page or the document unit."""
        ext = FinancialDocumentExtraction.model_validate({
            "document_unit": {"unit_raw": "VND", "evidence": "Đơn vị tính: VND", "page": 1},
            "page_units": {
                "5": {"unit_raw": None, "evidence": None, "page": 5},
                "6": {"unit_raw": "VND", "evidence": "Đơn vị tính: VND", "page": 6},
            },
        })
        self.assertNotIn(5, ext.page_units)  # never fabricated from document_unit or page 6
        self.assertEqual(set(ext.page_units.keys()), {6})

    def test_j_direct_construction_with_validated_model_instances_untouched(self):
        """J / merge path safety: FinancialUnitInfo instances built programmatically
        (e.g. by merge_financial_extractions) are already fully validated and must
        pass through the model_validator unchanged, not be re-classified as dicts."""
        unit = FinancialUnitInfo(unit_raw="VND", evidence="Đơn vị tính: VND", page=1)
        ext = FinancialDocumentExtraction(page_units={1: unit}, document_unit=unit)
        self.assertIs(ext.page_units[1], unit)
        self.assertIs(ext.document_unit, unit)

    def test_end_to_end_extractor_drops_empty_unit_without_crashing(self):
        """End-to-end regression test for the exact confirmed production failure:
        GreenNode returns page_units entries with null unit_raw/evidence for some
        pages -- extraction must succeed (not raise), with those entries dropped."""
        with patch("msb_eb_copilot.src.extraction.financial_extraction.AIAssistantClient.chat") as mock_chat:
            mock_chat.return_value = """{
                "document_title": "BCTC 2025",
                "page_units": {
                    "21": {"unit_raw": null, "evidence": null, "page": 21},
                    "22": {"unit_raw": "VND", "evidence": null, "page": 22},
                    "1": {"unit_raw": "VND", "evidence": "Đơn vị tính: VND", "page": 1}
                },
                "periods": []
            }"""
            extractor = FinancialDocumentExtractor()
            with self.assertRaises(Exception):
                # page 22 is partially populated -> must fail loudly, not silently accept it.
                extractor.extract("[PAGE 1]", page_count=1)

        with patch("msb_eb_copilot.src.extraction.financial_extraction.AIAssistantClient.chat") as mock_chat:
            mock_chat.return_value = """{
                "document_title": "BCTC 2025",
                "page_units": {
                    "21": {"unit_raw": null, "evidence": null, "page": 21},
                    "1": {"unit_raw": "VND", "evidence": "Đơn vị tính: VND", "page": 1}
                },
                "periods": []
            }"""
            extractor2 = FinancialDocumentExtractor()
            res = extractor2.extract("[PAGE 1]", page_count=1)
            self.assertEqual(set(res.page_units.keys()), {1})


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

# -*- coding: utf-8 -*-
"""Tests for page-level degraded OCR handling on the BUSINESS document preview
flow (process_business_pdf_preview / confirm_business_preview).

Confirmed production motivation: a single page whose OCR content came back
empty after all retries (e.g. "Trang 4 co noi dung OCR hoan toan rong.") used
to kill the entire Business document extraction, even though every other page
was perfectly readable. Financial preview already tolerates a small,
configurable number of such pages (FINANCIAL_OCR_MAX_FAILED_PAGES); this test
suite verifies Business now reuses the exact same OCR-layer mechanism
(BUSINESS_OCR_MAX_FAILED_PAGES) rather than duplicating it, while never
tolerating any other exception class (auth/4xx/5xx/schema failures).
"""

import copy
import os
import unittest
from unittest.mock import patch

import web_copilot_app as w
from msb_eb_copilot.src.extraction.business_extraction import (
    BusinessDocumentExtraction,
    BusinessEvidenceField,
    BUSINESS_EXTRACTION_SYSTEM_PROMPT,
    BusinessGroundingAuditor,
    DEFAULT_BUSINESS_OCR_MAX_FAILED_PAGES,
    get_business_ocr_max_failed_pages,
)
from msb_eb_copilot.src.ingestion.pdf_ocr import (
    OCRNoTextError,
    OCRServiceError,
    OCRFailedPageInfo,
    OCR_FAILED_PAGE_REASON_EMPTY_AFTER_RETRIES,
    OCR_UNREADABLE_PAGE_MARKER,
)
from msb_eb_copilot.src.ingestion.router import DocumentIngestionResult
from web_copilot_app import (
    CASES_DB,
    BUSINESS_PREVIEW_STORE,
    process_business_pdf_preview,
)


def _tagged_text_with_failed_pages(page_count: int, failed_page_nums: list) -> str:
    blocks = []
    for i in range(1, page_count + 1):
        if i in failed_page_nums:
            blocks.append(f"[PAGE {i}]\n{OCR_UNREADABLE_PAGE_MARKER}")
        else:
            blocks.append(
                f"[PAGE {i}]\nCÔNG TY CỔ PHẦN PHÂN PHỐI DEMO\nMST: 0100000000\n"
                f"Thành lập năm 2007 từ Chi nhánh Viễn thông Dầu khí. Trang {i}."
            )
    return "\n\n".join(blocks)


def _fake_ingestion_result(page_count: int, failed_page_nums=None) -> DocumentIngestionResult:
    failed_page_nums = failed_page_nums or []
    return DocumentIngestionResult(
        mode="ocr",
        provider="qwen_vision",
        page_count=page_count,
        tagged_text=_tagged_text_with_failed_pages(page_count, failed_page_nums),
        fallback_reason="PDFBlankPageError",
        failed_pages=[
            OCRFailedPageInfo(
                page=p,
                reason=OCR_FAILED_PAGE_REASON_EMPTY_AFTER_RETRIES,
                detail=f"Trang {p} có nội dung OCR hoàn toàn rỗng.",
            )
            for p in failed_page_nums
        ],
    )


MINIMAL_EXTRACTION = BusinessDocumentExtraction(
    company_name=BusinessEvidenceField(
        value_raw="CÔNG TY CỔ PHẦN PHÂN PHỐI DEMO",
        page=1,
        evidence="CÔNG TY CỔ PHẦN PHÂN PHỐI DEMO",
    ),
    tax_code=BusinessEvidenceField(
        value_raw="0100000000",
        page=1,
        evidence="MST: 0100000000",
    ),
    history_narrative=BusinessEvidenceField(
        value_raw="Thành lập năm 2007 từ Chi nhánh Viễn thông Dầu khí.",
        page=1,
        evidence="Thành lập năm 2007 từ Chi nhánh Viễn thông Dầu khí.",
    ),
)


class BusinessOCRDegradedHandlingTests(unittest.TestCase):
    def setUp(self):
        self.orig_cases_db = copy.deepcopy(CASES_DB)
        BUSINESS_PREVIEW_STORE.clear()

    def tearDown(self):
        CASES_DB.clear()
        CASES_DB.update(self.orig_cases_db)
        BUSINESS_PREVIEW_STORE.clear()

    # ------------------------------------------------------------------
    # A. All pages readable -> normal success, empty ocr_warnings
    # ------------------------------------------------------------------
    @patch("web_copilot_app.DocumentIngestionRouter.ingest_document")
    @patch("web_copilot_app.BusinessDocumentExtractor.extract")
    def test_a_all_pages_readable_normal_success(self, mock_extract, mock_ingest):
        mock_ingest.return_value = _fake_ingestion_result(page_count=3, failed_page_nums=[])
        mock_extract.return_value = MINIMAL_EXTRACTION

        res, code = process_business_pdf_preview(b"%PDF-1.4 dummy", "biz.pdf", case_id="PSD")

        self.assertEqual(code, 200)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["ocr_warnings"], {"failed_pages": [], "failed_page_count": 0})

        # Confirms the OCR layer is wired with the reusable max_failed_pages
        # threshold rather than being silently omitted.
        _, kwargs = mock_ingest.call_args
        self.assertEqual(kwargs.get("max_failed_pages"), get_business_ocr_max_failed_pages())

    # ------------------------------------------------------------------
    # B. One exhausted empty OCR page -> success with warning
    # ------------------------------------------------------------------
    @patch("web_copilot_app.DocumentIngestionRouter.ingest_document")
    @patch("web_copilot_app.BusinessDocumentExtractor.extract")
    def test_b_one_failed_page_succeeds_with_warning(self, mock_extract, mock_ingest):
        mock_ingest.return_value = _fake_ingestion_result(page_count=5, failed_page_nums=[4])
        mock_extract.return_value = MINIMAL_EXTRACTION

        res, code = process_business_pdf_preview(b"%PDF-1.4 dummy", "biz.pdf", case_id="PSD")

        self.assertEqual(code, 200)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["ocr_warnings"], {"failed_pages": [4], "failed_page_count": 1})

    # ------------------------------------------------------------------
    # C. Two exhausted empty pages -> success with warning
    # ------------------------------------------------------------------
    @patch("web_copilot_app.DocumentIngestionRouter.ingest_document")
    @patch("web_copilot_app.BusinessDocumentExtractor.extract")
    def test_c_two_failed_pages_succeeds_with_warning(self, mock_extract, mock_ingest):
        mock_ingest.return_value = _fake_ingestion_result(page_count=6, failed_page_nums=[2, 5])
        mock_extract.return_value = MINIMAL_EXTRACTION

        res, code = process_business_pdf_preview(b"%PDF-1.4 dummy", "biz.pdf", case_id="PSD")

        self.assertEqual(code, 200)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["ocr_warnings"], {"failed_pages": [2, 5], "failed_page_count": 2})

    # ------------------------------------------------------------------
    # D. Exceeding BUSINESS_OCR_MAX_FAILED_PAGES fails clearly (no silent
    #    fallback) -- the OCR layer itself is the one raising OCRNoTextError
    #    once its own tolerated-page budget is exhausted; this test verifies
    #    process_business_pdf_preview does NOT swallow that failure.
    # ------------------------------------------------------------------
    @patch("web_copilot_app.DocumentIngestionRouter.ingest_document")
    @patch("web_copilot_app.BusinessDocumentExtractor.extract")
    def test_d_exceeds_threshold_fails_clearly(self, mock_extract, mock_ingest):
        mock_ingest.side_effect = OCRNoTextError(
            "Vượt quá ngưỡng dung thứ trang lỗi (tối đa 2 trang): trang 3, 4, 7."
        )

        res, code = process_business_pdf_preview(b"%PDF-1.4 dummy", "biz.pdf", case_id="PSD")

        self.assertEqual(code, 500)
        self.assertEqual(res["status"], "error")
        self.assertEqual(res["error_type"], "OCRNoTextError")
        mock_extract.assert_not_called()

    # ------------------------------------------------------------------
    # E. Marker preserves page sequence -- physical page count and ordering
    #    survive even when an interior page is unreadable.
    # ------------------------------------------------------------------
    @patch("web_copilot_app.DocumentIngestionRouter.ingest_document")
    @patch("web_copilot_app.BusinessDocumentExtractor.extract")
    def test_e_marker_preserves_page_numbering(self, mock_extract, mock_ingest):
        ingestion_result = _fake_ingestion_result(page_count=5, failed_page_nums=[4])
        mock_ingest.return_value = ingestion_result
        mock_extract.return_value = MINIMAL_EXTRACTION

        res, code = process_business_pdf_preview(b"%PDF-1.4 dummy", "biz.pdf", case_id="PSD")
        self.assertEqual(code, 200)
        self.assertEqual(res["routing"]["page_count"], 5)

        pages_text, max_p = BusinessGroundingAuditor.extract_pages(ingestion_result.tagged_text)
        self.assertEqual(max_p, 5)
        self.assertEqual(set(pages_text.keys()), {1, 2, 3, 4, 5})
        self.assertEqual(pages_text[4], OCR_UNREADABLE_PAGE_MARKER)
        self.assertIn("Trang 5", pages_text[5])

    # ------------------------------------------------------------------
    # F. An unreadable page can never become evidence -- a fabricated fact
    #    citing the marker-only page must be rejected by the grounding audit.
    # ------------------------------------------------------------------
    def test_f_unreadable_page_cannot_become_evidence(self):
        pages_text = {
            1: "CÔNG TY CỔ PHẦN PHÂN PHỐI DEMO",
            4: OCR_UNREADABLE_PAGE_MARKER,
        }
        fabricated_field = BusinessEvidenceField(
            value_raw="Chiếm 40% thị phần",
            evidence="Chiếm 40% thị phần phân phối toàn quốc",
            page=4,
        )
        audit_res = BusinessGroundingAuditor.audit_field(
            fabricated_field, "section_c.market_share_estimate", pages_text, 5
        )
        self.assertNotEqual(audit_res.status, "VERIFIED")

    # ------------------------------------------------------------------
    # G. Non-empty-page OCR/network/schema failures remain fatal regardless
    #    of the max_failed_pages tolerance being enabled.
    # ------------------------------------------------------------------
    @patch("web_copilot_app.DocumentIngestionRouter.ingest_document")
    @patch("web_copilot_app.BusinessDocumentExtractor.extract")
    def test_g_non_ocr_no_text_errors_still_fatal(self, mock_extract, mock_ingest):
        mock_ingest.side_effect = OCRServiceError("GreenNode OCR service returned HTTP 503.")

        res, code = process_business_pdf_preview(b"%PDF-1.4 dummy", "biz.pdf", case_id="PSD")

        self.assertEqual(code, 500)
        self.assertEqual(res["error_type"], "OCRServiceError")
        mock_extract.assert_not_called()

    # ------------------------------------------------------------------
    # H. Customer/business extraction from fully readable pages is unchanged.
    # ------------------------------------------------------------------
    @patch("web_copilot_app.DocumentIngestionRouter.ingest_document")
    @patch("web_copilot_app.BusinessDocumentExtractor.extract")
    def test_h_extraction_from_readable_pages_unchanged(self, mock_extract, mock_ingest):
        mock_ingest.return_value = _fake_ingestion_result(page_count=1, failed_page_nums=[])
        mock_extract.return_value = MINIMAL_EXTRACTION

        res, code = process_business_pdf_preview(b"%PDF-1.4 dummy", "biz.pdf", case_id="PSD")

        self.assertEqual(code, 200)
        self.assertEqual(res["identity_reconciliation"]["extracted_company_name"], "CÔNG TY CỔ PHẦN PHÂN PHỐI DEMO")
        self.assertEqual(res["identity_reconciliation"]["extracted_tax_code"], "0100000000")
        history_rows = [r for r in res["review_table"] if r["canonical_path"] == "section_c.history_narrative"]
        self.assertEqual(len(history_rows), 1)

    # ------------------------------------------------------------------
    # I. No fabricated values/evidence make it into the review table for a
    #    fact that (falsely) cites the unreadable page.
    # ------------------------------------------------------------------
    @patch("web_copilot_app.DocumentIngestionRouter.ingest_document")
    @patch("web_copilot_app.BusinessDocumentExtractor.extract")
    def test_i_no_fabricated_values_surface_in_review_table(self, mock_extract, mock_ingest):
        mock_ingest.return_value = _fake_ingestion_result(page_count=4, failed_page_nums=[4])
        fabricated_extraction = MINIMAL_EXTRACTION.model_copy(update={
            "market_share_claim": BusinessEvidenceField(
                value_raw="Chiếm 40% thị phần",
                evidence="Chiếm 40% thị phần phân phối toàn quốc",
                page=4,
            )
        })
        mock_extract.return_value = fabricated_extraction

        res, code = process_business_pdf_preview(b"%PDF-1.4 dummy", "biz.pdf", case_id="PSD")
        self.assertEqual(code, 200)

        market_rows = [r for r in res["review_table"] if r["canonical_path"] == "section_c.market_share_estimate"]
        self.assertEqual(len(market_rows), 1)
        self.assertNotEqual(market_rows[0]["grounding_status"], "VERIFIED")


class BusinessOCRMaxFailedPagesConfigTests(unittest.TestCase):
    """Mirrors test_g_financial_ocr_max_failed_pages_configuration exactly,
    for the new business-side config getter."""

    def test_business_ocr_max_failed_pages_configuration(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(get_business_ocr_max_failed_pages(), DEFAULT_BUSINESS_OCR_MAX_FAILED_PAGES)
            self.assertEqual(get_business_ocr_max_failed_pages(), 2)
        with patch.dict(os.environ, {"BUSINESS_OCR_MAX_FAILED_PAGES": "abc"}):
            self.assertEqual(get_business_ocr_max_failed_pages(), 2)
        with patch.dict(os.environ, {"BUSINESS_OCR_MAX_FAILED_PAGES": "-1"}):
            self.assertEqual(get_business_ocr_max_failed_pages(), 2)
        with patch.dict(os.environ, {"BUSINESS_OCR_MAX_FAILED_PAGES": "1"}):
            self.assertEqual(get_business_ocr_max_failed_pages(), 1)
        with patch.dict(os.environ, {"BUSINESS_OCR_MAX_FAILED_PAGES": "0"}):
            self.assertEqual(get_business_ocr_max_failed_pages(), 0)
        with patch.dict(os.environ, {"BUSINESS_OCR_MAX_FAILED_PAGES": "5"}):
            self.assertEqual(get_business_ocr_max_failed_pages(), 5)

        self.assertEqual(get_business_ocr_max_failed_pages(configured=1), 1)
        self.assertEqual(get_business_ocr_max_failed_pages(configured=0), 0)

    def test_prompt_instructs_marker_is_not_evidence(self):
        self.assertIn(OCR_UNREADABLE_PAGE_MARKER, BUSINESS_EXTRACTION_SYSTEM_PROMPT)
        self.assertIn("HOÀN TOÀN KHÔNG chứa bằng chứng", BUSINESS_EXTRACTION_SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()

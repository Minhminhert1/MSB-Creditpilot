# -*- coding: utf-8 -*-
"""Unit tests for Phase 3A: Financial Preview, Trust Boundary, and Confirmation APIs."""

import base64
import copy
import json
import unittest
from unittest.mock import MagicMock, patch

import web_copilot_app
from msb_eb_copilot.src.extraction.financial_extraction import (
    FinancialDocumentExtraction,
    FinancialEvidenceField,
    FinancialPeriodExtraction,
    FinancialUnitInfo,
)
from msb_eb_copilot.src.ingestion.router import DocumentIngestionResult
from web_copilot_app import (
    CASES_DB,
    FINANCIAL_PREVIEW_STORE,
    FinancialPreviewRecord,
    process_financial_pdf_preview,
    validate_and_confirm_financial_preview,
)


class TestFinancialPreviewAndConfirm(unittest.TestCase):
    """Test server-authoritative preview store and confirmation trust boundaries."""

    def setUp(self):
        # Save snapshot of CASES_DB
        self.orig_cases_db = copy.deepcopy(CASES_DB)
        FINANCIAL_PREVIEW_STORE.clear()

        # Dummy valid BCTC extraction
        self.mock_extraction = FinancialDocumentExtraction(
            document_title="Báo cáo tài chính năm 2025",
            document_unit=FinancialUnitInfo(unit_raw="VND", evidence="Đơn vị tính: VND", page=1),
            periods=[
                FinancialPeriodExtraction(
                    period="2024",
                    net_revenue=FinancialEvidenceField(
                        value_raw="5.702.529.000.000",
                        semantic_label="Doanh thu thuần về bán hàng",
                        accounting_code="10",
                        evidence="Doanh thu thuần | 10 | 5.702.529.000.000",
                        page=1,
                    ),
                    gross_profit=FinancialEvidenceField(
                        value_raw="320.928.000.000",
                        semantic_label="Lợi nhuận gộp",
                        accounting_code="20",
                        evidence="Lợi nhuận gộp | 20 | 320.928.000.000",
                        page=1,
                    ),
                    net_profit_after_tax=FinancialEvidenceField(
                        value_raw="89.729.000.000",
                        semantic_label="Lợi nhuận sau thuế",
                        accounting_code="60",
                        evidence="Lợi nhuận sau thuế | 60 | 89.729.000.000",
                        page=1,
                    ),
                    current_assets=FinancialEvidenceField(
                        value_raw="2.723.355.000.000",
                        semantic_label="Tài sản ngắn hạn",
                        accounting_code="100",
                        evidence="Tài sản ngắn hạn | 100 | 2.723.355.000.000",
                        page=2,
                    ),
                    cash=FinancialEvidenceField(
                        value_raw="103.169.000.000",
                        semantic_label="Tiền và các khoản tương đương tiền",
                        accounting_code="110",
                        evidence="Tiền và tương đương tiền | 110 | 103.169.000.000",
                        page=2,
                    ),
                    inventories=FinancialEvidenceField(
                        value_raw="525.688.000.000",
                        semantic_label="Hàng tồn kho",
                        accounting_code="140",
                        evidence="Hàng tồn kho | 140 | 525.688.000.000",
                        page=2,
                    ),
                    total_assets=FinancialEvidenceField(
                        value_raw="2.810.436.000.000",
                        semantic_label="Tổng cộng tài sản",
                        accounting_code="270",
                        evidence="Tổng tài sản | 270 | 2.810.436.000.000",
                        page=2,
                    ),
                    short_term_debt=FinancialEvidenceField(
                        value_raw="1.537.823.000.000",
                        semantic_label="Vay ngắn hạn",
                        accounting_code="320",
                        evidence="Vay ngắn hạn | 320 | 1.537.823.000.000",
                        page=2,
                    ),
                    equity=FinancialEvidenceField(
                        value_raw="597.826.000.000",
                        semantic_label="Vốn chủ sở hữu",
                        accounting_code="400",
                        evidence="Vốn chủ sở hữu | 400 | 597.826.000.000",
                        page=2,
                    ),
                ),
                FinancialPeriodExtraction(
                    period="2025",
                    net_revenue=FinancialEvidenceField(
                        value_raw="7.819.398.000.000",
                        semantic_label="Doanh thu thuần về bán hàng",
                        accounting_code="10",
                        evidence="Doanh thu thuần | 10 | 7.819.398.000.000",
                        page=1,
                    ),
                    gross_profit=FinancialEvidenceField(
                        value_raw="406.809.000.000",
                        semantic_label="Lợi nhuận gộp",
                        accounting_code="20",
                        evidence="Lợi nhuận gộp | 20 | 406.809.000.000",
                        page=1,
                    ),
                    net_profit_after_tax=FinancialEvidenceField(
                        value_raw="134.201.000.000",
                        semantic_label="Lợi nhuận sau thuế",
                        accounting_code="60",
                        evidence="Lợi nhuận sau thuế | 60 | 134.201.000.000",
                        page=1,
                    ),
                    current_assets=FinancialEvidenceField(
                        value_raw="4.600.702.000.000",
                        semantic_label="Tài sản ngắn hạn",
                        accounting_code="100",
                        evidence="Tài sản ngắn hạn | 100 | 4.600.702.000.000",
                        page=2,
                    ),
                    cash=FinancialEvidenceField(
                        value_raw="227.658.000.000",
                        semantic_label="Tiền và các khoản tương đương tiền",
                        accounting_code="110",
                        evidence="Tiền và tương đương tiền | 110 | 227.658.000.000",
                        page=2,
                    ),
                    inventories=FinancialEvidenceField(
                        value_raw="965.402.000.000",
                        semantic_label="Hàng tồn kho",
                        accounting_code="140",
                        evidence="Hàng tồn kho | 140 | 965.402.000.000",
                        page=2,
                    ),
                    total_assets=FinancialEvidenceField(
                        value_raw="4.683.423.000.000",
                        semantic_label="Tổng cộng tài sản",
                        accounting_code="270",
                        evidence="Tổng tài sản | 270 | 4.683.423.000.000",
                        page=2,
                    ),
                    short_term_debt=FinancialEvidenceField(
                        value_raw="2.572.040.000.000",
                        semantic_label="Vay ngắn hạn",
                        accounting_code="320",
                        evidence="Vay ngắn hạn | 320 | 2.572.040.000.000",
                        page=2,
                    ),
                    equity=FinancialEvidenceField(
                        value_raw="729.343.000.000",
                        semantic_label="Vốn chủ sở hữu",
                        accounting_code="400",
                        evidence="Vốn chủ sở hữu | 400 | 729.343.000.000",
                        page=2,
                    ),
                )
            ]
        )

    def tearDown(self):
        web_copilot_app.CASES_DB.clear()
        web_copilot_app.CASES_DB.update(copy.deepcopy(self.orig_cases_db))

    @patch("web_copilot_app.FinancialDocumentExtractor.extract")
    @patch("web_copilot_app.DocumentIngestionRouter.ingest_document")
    def test_preview_generation_review_table_and_ratios(self, mock_ingest, mock_extract):
        mock_ingest.return_value = DocumentIngestionResult(
            mode="digital",
            provider="pypdf",
            page_count=2,
            tagged_text="[PAGE 1] Doanh thu thuần 5.702.529.000.000 [PAGE 2] Tài sản ngắn hạn",
        )
        mock_extract.return_value = self.mock_extraction

        raw_bytes = b"%PDF-1.4 dummy content"
        res, status = process_financial_pdf_preview(raw_bytes, "bctc_2025.pdf", case_id="PSD")

        self.assertEqual(status, 200)
        self.assertEqual(res["status"], "success")
        self.assertIn("preview_id", res)
        self.assertEqual(res["periods"], ["2024", "2025"])

        # Check review table format: (YEAR | FINANCIAL ITEM | EXTRACTED VALUE | UNIT | PAGE | STATUS)
        table = res["review_table"]
        self.assertTrue(len(table) > 0)
        sample_row = next(r for r in table if r["canonical_field"] == "net_revenue" and r["year"] == "2025")
        self.assertEqual(sample_row["extracted_value"], 7819398.0)
        self.assertEqual(sample_row["unit"], "VND")
        self.assertEqual(sample_row["page"], 1)
        self.assertIn(sample_row["status"], ("EXTRACTED", "CONFLICT"))

        # Check calculated ratios
        ratios = res["calculated_ratios"]
        self.assertIn("current_ratio", ratios)
        self.assertIn("ros", ratios)
        self.assertIn("roe", ratios)

        # Ensure preview was saved to server-side store
        p_id = res["preview_id"]
        self.assertIn(p_id, FINANCIAL_PREVIEW_STORE)
        self.assertFalse(FINANCIAL_PREVIEW_STORE[p_id].consumed)

    def test_confirmation_missing_preview_id(self):
        res, status = validate_and_confirm_financial_preview(preview_id=None, case_id="PSD")
        self.assertEqual(status, 400)
        self.assertEqual(res["error_type"], "InvalidInputError")

    def test_confirmation_unknown_preview_id(self):
        res, status = validate_and_confirm_financial_preview(preview_id="non-existent-uuid", case_id="PSD")
        self.assertEqual(status, 404)
        self.assertEqual(res["error_type"], "PreviewNotFoundError")

    @patch("web_copilot_app.FinancialDocumentExtractor.extract")
    @patch("web_copilot_app.DocumentIngestionRouter.ingest_document")
    def test_confirmation_conflict_handling_and_resolution(self, mock_ingest, mock_extract):
        mock_ingest.return_value = DocumentIngestionResult(
            mode="digital",
            provider="pypdf",
            page_count=2,
            tagged_text="[PAGE 1] test [PAGE 2] test",
        )

        # Alter 2025 revenue to conflict with PSD canonical 7,819,398
        conflicting_extraction = copy.deepcopy(self.mock_extraction)
        conflicting_extraction.periods[1].net_revenue.value_raw = "8.500.000.000.000"  # 8,500,000 triệu VND
        mock_extract.return_value = conflicting_extraction

        preview_res, status = process_financial_pdf_preview(b"%PDF-1.4", "bctc.pdf", case_id="PSD")
        p_id = preview_res["preview_id"]

        # Confirm without resolution -> 409 Conflict
        conf_res, conf_status = validate_and_confirm_financial_preview(preview_id=p_id, case_id="PSD", resolutions=None)
        self.assertEqual(conf_status, 409)
        self.assertEqual(conf_res["status"], "conflict")
        self.assertTrue(len(conf_res["conflicts"]) > 0)
        # Verify preview is NOT consumed yet
        self.assertFalse(FINANCIAL_PREVIEW_STORE[p_id].consumed)

        # Confirm with explicit resolution: 'use_extracted'
        resolutions = {"section_d.net_revenue[2025]": "use_extracted"}
        res2, status2 = validate_and_confirm_financial_preview(preview_id=p_id, case_id="PSD", resolutions=resolutions)
        self.assertEqual(status2, 200)
        self.assertEqual(res2["status"], "success")

        # Verify preview is now consumed
        self.assertTrue(FINANCIAL_PREVIEW_STORE[p_id].consumed)

        # Verify CASES_DB["PSD"]["section_d"] was updated with extracted value
        psd_d = web_copilot_app.CASES_DB["PSD"]["section_d"]
        idx_2025 = psd_d["years"].index("2025")
        self.assertEqual(psd_d["net_revenue"][idx_2025], 8500000.0)

        # HARD CONTRACT: customer.revenue_2025 NOT written (preserves original value)
        self.assertEqual(web_copilot_app.CASES_DB["PSD"]["customer"]["revenue_2025"], self.orig_cases_db["PSD"]["customer"]["revenue_2025"])
        self.assertNotEqual(web_copilot_app.CASES_DB["PSD"]["customer"]["revenue_2025"], 8500000.0)

        # Attempt to confirm again -> 409 PreviewAlreadyConsumedError
        res3, status3 = validate_and_confirm_financial_preview(preview_id=p_id, case_id="PSD")
        self.assertEqual(status3, 409)
        self.assertEqual(res3["error_type"], "PreviewAlreadyConsumedError")


class TestFinancialHTTPHandlerEndpoints(unittest.TestCase):
    """Test HTTP POST handler directly for /api/preview_financial_pdf and /api/confirm_financial_preview."""

    def setUp(self):
        self.orig_cases_db = copy.deepcopy(CASES_DB)
        FINANCIAL_PREVIEW_STORE.clear()

    def tearDown(self):
        web_copilot_app.CASES_DB = self.orig_cases_db

    def _invoke_post(self, path: str, body: dict) -> tuple[int, dict]:
        import io
        body_bytes = json.dumps(body).encode("utf-8")
        handler = web_copilot_app.CopilotHTTPHandler.__new__(web_copilot_app.CopilotHTTPHandler)
        handler.path = path
        handler.headers = {"Content-Length": str(len(body_bytes))}
        handler.rfile = io.BytesIO(body_bytes)
        out_buf = io.BytesIO()
        handler.wfile = out_buf

        status_container = {"status": 200}

        def fake_send_json(data, status_code=200):
            status_container["status"] = status_code
            status_container["data"] = data

        handler._send_json = fake_send_json
        handler.do_POST()
        return status_container["status"], status_container.get("data", {})

    def test_preview_rejection_of_client_file_path(self):
        status, data = self._invoke_post("/api/preview_financial_pdf", {
            "filename": "bctc.pdf",
            "content_base64": base64.b64encode(b"%PDF-1.4").decode("utf-8"),
            "file_path": "C:\\malicious\\path.pdf",
        })
        self.assertEqual(status, 400)
        self.assertEqual(data["error_type"], "InvalidInputError")

    def test_preview_rejection_of_non_pdf(self):
        status, data = self._invoke_post("/api/preview_financial_pdf", {
            "filename": "bctc.docx",
            "content_base64": base64.b64encode(b"docx content").decode("utf-8"),
        })
        self.assertEqual(status, 400)
        self.assertEqual(data["error_type"], "InvalidFormatError")

    def test_confirm_rejection_of_forbidden_keys(self):
        for forbidden in ("fields", "case_data", "canonical_path", "file_path", "section_d", "ratios"):
            status, data = self._invoke_post("/api/confirm_financial_preview", {
                "preview_id": "test-id",
                forbidden: {"some": "data"},
            })
            self.assertEqual(status, 400, f"Failed to reject forbidden key: {forbidden}")
            self.assertEqual(data["error_type"], "InvalidInputError")


if __name__ == "__main__":
    unittest.main()


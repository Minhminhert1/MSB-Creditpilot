# -*- coding: utf-8 -*-
"""Unit tests for Phase 5: Business Preview, Trust Boundary, Replay Protection, and Confirmation APIs."""

import copy
import io
import json
import unittest
from unittest.mock import MagicMock, patch

import web_copilot_app
from msb_eb_copilot.src.extraction.business_extraction import (
    BusinessDocumentExtraction,
    BusinessEvidenceField,
    ShareholderItem,
    ManagementItem,
    ProductItem,
    SupplierItem,
    CustomerItem,
)
from msb_eb_copilot.src.ingestion.router import DocumentIngestionResult
from web_copilot_app import (
    CASES_DB,
    BUSINESS_PREVIEW_STORE,
    BusinessPreviewRecord,
    process_business_pdf_preview,
    confirm_business_preview,
    CopilotHTTPHandler,
)


class TestBusinessPreviewAndConfirm(unittest.TestCase):
    """Test server-authoritative preview store and confirmation trust boundaries."""

    def setUp(self):
        self.orig_cases_db = copy.deepcopy(CASES_DB)
        BUSINESS_PREVIEW_STORE.clear()

        # Mock valid extraction
        self.mock_extraction = BusinessDocumentExtraction(
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
            operating_model_description=BusinessEvidenceField(
                value_raw="Doanh nghiệp hoạt động theo mô hình phân phối thương mại thiết bị ICT.",
                page=1,
                evidence="mô hình phân phối thương mại",
            ),
            shareholders=[
                ShareholderItem(
                    shareholder_name=BusinessEvidenceField(
                        value_raw="DEMO_GROUP",
                        page=1,
                        evidence="DEMO_GROUP sở hữu 76.93%",
                    ),
                    id_tax_code=BusinessEvidenceField(
                        value_raw="0100779779",
                        page=1,
                        evidence="0100779779",
                    ),
                    ownership_percentage_raw=BusinessEvidenceField(
                        value_raw="76.93%",
                        page=1,
                        evidence="sở hữu 76.93%",
                    ),
                    contributed_capital_raw=BusinessEvidenceField(
                        value_raw="398712.0",
                        page=1,
                        evidence="398712.0",
                    ),
                    page=1,
                )
            ],
            management=[
                ManagementItem(
                    full_name=BusinessEvidenceField(
                        value_raw="Đại diện Demo",
                        page=1,
                        evidence="Đại diện Demo - Chủ tịch HĐQT",
                    ),
                    position=BusinessEvidenceField(
                        value_raw="Chủ tịch HĐQT",
                        page=1,
                        evidence="Chủ tịch HĐQT",
                    ),
                    explicit_experience_years_raw=BusinessEvidenceField(
                        value_raw="15",
                        page=1,
                        evidence="15 năm kinh nghiệm",
                    ),
                    profile_summary=BusinessEvidenceField(
                        value_raw="Chủ tịch HĐQT",
                        page=1,
                        evidence="Chủ tịch HĐQT",
                    ),
                    page=1,
                )
            ],
        )

    def tearDown(self):
        CASES_DB.clear()
        CASES_DB.update(self.orig_cases_db)
        BUSINESS_PREVIEW_STORE.clear()

    @patch("web_copilot_app.DocumentIngestionRouter.ingest_document")
    @patch("web_copilot_app.BusinessDocumentExtractor.extract")
    def test_process_business_pdf_preview_success(self, mock_extract, mock_ingest):
        mock_ingest.return_value = DocumentIngestionResult(
            mode="digital",
            tagged_text="[PAGE 1]\nCÔNG TY CỔ PHẦN PHÂN PHỐI DEMO\nMST: 0100000000\nThành lập năm 2007 từ Chi nhánh Viễn thông Dầu khí.\nmô hình phân phối thương mại\nDEMO_GROUP sở hữu 76.93% 0100779779 398712.0\nĐại diện Demo - Chủ tịch HĐQT 15 năm kinh nghiệm",
            page_count=1,
            provider="pypdf",
            model="pypdf",
        )
        mock_extract.return_value = self.mock_extraction

        res, code = process_business_pdf_preview(b"%PDF-1.4 dummy", "biz_test.pdf", case_id="PSD")
        self.assertEqual(code, 200)
        self.assertEqual(res["status"], "success")
        self.assertIn("preview_id", res)
        self.assertEqual(res["identity_reconciliation"]["status"], "MATCH")
        self.assertIn(res["preview_id"], BUSINESS_PREVIEW_STORE)

    @patch("web_copilot_app.DocumentIngestionRouter.ingest_document")
    @patch("web_copilot_app.BusinessDocumentExtractor.extract")
    def test_confirm_business_preview_single_use_token(self, mock_extract, mock_ingest):
        mock_ingest.return_value = DocumentIngestionResult(
            mode="digital",
            tagged_text="[PAGE 1]\nCÔNG TY CỔ PHẦN PHÂN PHỐI DEMO\nMST: 0100000000\nThành lập năm 2007 từ Chi nhánh Viễn thông Dầu khí.\nmô hình phân phối thương mại\nDEMO_GROUP sở hữu 76.93% 0100779779 398712.0\nĐại diện Demo - Chủ tịch HĐQT 15 năm kinh nghiệm",
            page_count=1,
            provider="pypdf",
            model="pypdf",
        )
        mock_extract.return_value = self.mock_extraction

        res_prev, _ = process_business_pdf_preview(b"%PDF-1.4 dummy", "biz_test.pdf", case_id="PSD")
        pid = res_prev["preview_id"]

        # 1. First confirmation succeeds
        res1, code1 = confirm_business_preview(pid, case_id="PSD")
        self.assertEqual(code1, 200)
        self.assertEqual(res1["status"], "success")

        # 2. Second confirmation fails with 409 (Replay Protection)
        res2, code2 = confirm_business_preview(pid, case_id="PSD")
        self.assertEqual(code2, 409)
        self.assertEqual(res2["error_type"], "PreviewAlreadyConsumedError")

    def test_confirm_business_preview_not_found(self):
        res, code = confirm_business_preview("non-existent-uuid", case_id="PSD")
        self.assertEqual(code, 404)
        self.assertEqual(res["error_type"], "PreviewNotFoundError")

    def test_confirm_business_preview_identity_mismatch_blocks_without_ack(self):
        """If identity reconciliation returned MISMATCH, confirmation must be blocked unless acknowledged."""
        record = BusinessPreviewRecord(
            preview_id="mismatch-pid",
            case_id="PSD",
            extraction=self.mock_extraction,
            source_filename="test.pdf",
            routing={"mode": "digital"},
            mapping_result=MagicMock(case_data={"section_c": {}}, conflicts=(), warnings=(), updated_fields=()),
            review_table=[],
            identity_status="MISMATCH",
            identity_message="Mã số thuế không trùng khớp!",
            suggested_business_model=None,
            consumed=False,
        )
        BUSINESS_PREVIEW_STORE["mismatch-pid"] = record

        # 1. Blocked without ack
        res1, code1 = confirm_business_preview("mismatch-pid", case_id="PSD", identity_acknowledged=False)
        self.assertEqual(code1, 400)
        self.assertEqual(res1["error_type"], "IdentityMismatchError")

        # 2. Allowed with explicit RM ack
        res2, code2 = confirm_business_preview("mismatch-pid", case_id="PSD", identity_acknowledged=True)
        self.assertEqual(code2, 200)
        self.assertEqual(res2["status"], "success")

    def _make_handler(self, method: str, path: str, body: dict = None):
        request_bytes = json.dumps(body).encode("utf-8") if body is not None else b""
        handler = CopilotHTTPHandler.__new__(CopilotHTTPHandler)
        handler.command = method
        handler.path = path
        handler.rfile = io.BytesIO(request_bytes)
        handler.headers = {"Content-Length": str(len(request_bytes))}
        handler.wfile = io.BytesIO()
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        return handler

    def test_http_endpoint_rejects_client_supplied_facts(self):
        """Verify that confirm endpoint strictly rejects client-supplied Section C facts."""
        payload = {
            "preview_id": "test-pid",
            "section_c": {"shareholders": [{"name": "Fake Shareholder"}]},
        }
        handler = self._make_handler("POST", "/api/confirm_business_preview", payload)
        handler.do_POST()

        handler.send_response.assert_called_with(400)
        resp_data = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertEqual(resp_data["status"], "error")
        self.assertIn("section_c", resp_data["message"])

# -*- coding: utf-8 -*-
"""Unit tests for Phase 4: CIC Preview, Trust Boundary, and Confirmation APIs."""

import copy
import io
import json
import unittest
from unittest.mock import MagicMock, patch

import web_copilot_app
from msb_eb_copilot.src.extraction.cic_extraction import (
    CICDocumentExtraction,
    CICEvidenceField,
    CICInstitutionItem,
    CICFacilityItem,
)
from msb_eb_copilot.src.ingestion.router import DocumentIngestionResult
from web_copilot_app import (
    CASES_DB,
    CIC_PREVIEW_STORE,
    CICPreviewRecord,
    process_cic_pdf_preview,
    confirm_cic_preview,
    CopilotHTTPHandler,
)


class TestCICPreviewAndConfirm(unittest.TestCase):
    """Test server-authoritative preview store and confirmation trust boundaries."""

    def setUp(self):
        self.orig_cases_db = copy.deepcopy(CASES_DB)
        CIC_PREVIEW_STORE.clear()

        # Mock valid extraction
        self.mock_extraction = CICDocumentExtraction(
            customer_name=CICEvidenceField(value_raw="CÔNG TY CỔ PHẦN PHÂN PHỐI DEMO", page=1, evidence="CÔNG TY CỔ PHẦN PHÂN PHỐI DEMO"),
            tax_code=CICEvidenceField(value_raw="0109876543", page=1, evidence="MST: 0109876543"),
            cic_report_date=CICEvidenceField(value_raw="28/02/2026", page=1, evidence="Ngày: 28/02/2026"),
            customer_highest_debt_group=CICEvidenceField(value_raw="Nhóm 1", page=1, evidence="Nhóm nợ: Nhóm 1"),
            history_status=CICEvidenceField(value_raw="Lịch sử tốt", page=1, evidence="Lịch sử tốt không nợ xấu"),
            is_overdue_12m=CICEvidenceField(value_raw="Không có nợ quá hạn", page=1, evidence="Trong 12 tháng gần nhất không có nợ quá hạn"),
            derivative_transactions_info=CICEvidenceField(value_raw=None, page=None, evidence=None),
            institutions=[
                CICInstitutionItem(
                    bank_name=CICEvidenceField(value_raw="Ngân hàng TMCP Ngoại thương Việt Nam (Vietcombank)", page=1, evidence="Vietcombank"),
                    short_term_limit_raw=CICEvidenceField(value_raw="15.000", page=1, evidence="HMTD 15.000"),
                    short_term_debt_vnd_raw=CICEvidenceField(value_raw="8.500", page=1, evidence="VND 8.500"),
                    short_term_debt_usd_vnd_equiv_raw=CICEvidenceField(value_raw="1.500", page=1, evidence="USD 1.500"),
                    debt_group=CICEvidenceField(value_raw="Nhóm 1", page=1, evidence="Nhóm 1"),
                ),
                CICInstitutionItem(
                    bank_name=CICEvidenceField(value_raw="Ngân hàng TMCP Hàng Hải Việt Nam (MSB)", page=1, evidence="MSB"),
                    short_term_limit_raw=CICEvidenceField(value_raw="10.000", page=1, evidence="HMTD 10.000"),
                    short_term_debt_vnd_raw=CICEvidenceField(value_raw="5.200", page=1, evidence="VND 5.200"),
                    medium_long_term_debt_raw=CICEvidenceField(value_raw="2.000", page=1, evidence="TDH 2.000"),
                    debt_group=CICEvidenceField(value_raw="Nhóm 1", page=1, evidence="Nhóm 1"),
                ),
            ]
        )

    def tearDown(self):
        CASES_DB.clear()
        CASES_DB.update(self.orig_cases_db)
        CIC_PREVIEW_STORE.clear()

    @patch("web_copilot_app.DocumentIngestionRouter.ingest_document")
    @patch("web_copilot_app.CICDocumentExtractor.extract")
    def test_process_cic_pdf_preview_success(self, mock_extract, mock_ingest):
        mock_ingest.return_value = DocumentIngestionResult(
            mode="digital",
            tagged_text="[PAGE 1]\nCÔNG TY CỔ PHẦN PHÂN PHỐI DEMO\nMST: 0109876543\nNgày: 28/02/2026\nTrong 12 tháng gần nhất không có nợ quá hạn\nVietcombank HMTD 15.000 VND 8.500 USD 1.500 Nhóm 1\nMSB HMTD 10.000 VND 5.200 TDH 2.000 Nhóm 1\nLịch sử tốt không nợ xấu",
            page_count=1,
            provider="pypdf",
            model="pypdf",
        )
        mock_extract.return_value = self.mock_extraction

        res, code = process_cic_pdf_preview(b"%PDF-1.4 dummy", "cic_test.pdf", case_id="PSD")
        self.assertEqual(code, 200)
        self.assertEqual(res["status"], "success")
        self.assertIn("preview_id", res)
        self.assertEqual(res["filename"], "cic_test.pdf")
        self.assertEqual(len(res["review_table"]), 5)  # 3 doc facts + 2 institutions (derivative is None)

        # Check preview registered in store
        pid = res["preview_id"]
        self.assertIn(pid, CIC_PREVIEW_STORE)
        record = CIC_PREVIEW_STORE[pid]
        self.assertFalse(record.consumed)
        self.assertEqual(record.case_id, "PSD")

    @patch("web_copilot_app.DocumentIngestionRouter.ingest_document")
    @patch("web_copilot_app.CICDocumentExtractor.extract")
    def test_confirm_cic_preview_single_use_token(self, mock_extract, mock_ingest):
        mock_ingest.return_value = DocumentIngestionResult(
            mode="digital",
            tagged_text="[PAGE 1]\nMST: 0109876543\nNgày: 28/02/2026",
            page_count=1,
            provider="pypdf",
            model="pypdf",
        )
        mock_extract.return_value = self.mock_extraction

        res_prev, _ = process_cic_pdf_preview(b"%PDF-1.4 dummy", "cic_test.pdf", case_id="PSD")
        pid = res_prev["preview_id"]

        # First confirm -> Success 200
        res1, code1 = confirm_cic_preview(pid, case_id="PSD")
        self.assertEqual(code1, 200)
        self.assertEqual(res1["status"], "success")

        # Second confirm with same preview_id -> 409 Conflict
        res2, code2 = confirm_cic_preview(pid, case_id="PSD")
        self.assertEqual(code2, 409)
        self.assertEqual(res2["error_type"], "PreviewAlreadyConsumedError")

    def test_confirm_cic_preview_not_found(self):
        res, code = confirm_cic_preview("non-existent-uuid", case_id="psd")
        self.assertEqual(code, 404)
        self.assertEqual(res["error_type"], "PreviewNotFoundError")

    def test_confirm_cic_preview_case_not_found(self):
        # Create dummy record
        record = CICPreviewRecord(
            preview_id="dummy-pid",
            case_id="unknown_case",
            extraction=self.mock_extraction,
            source_filename="test.pdf",
            routing={},
            mapping_result=MagicMock(),
            review_table=[],
            identity_status="MATCH",
            identity_message="Match",
            consumed=False,
        )
        CIC_PREVIEW_STORE["dummy-pid"] = record

        res, code = confirm_cic_preview("dummy-pid", case_id="unknown_case")
        self.assertEqual(code, 404)
        self.assertEqual(res["error_type"], "CaseNotFoundError")


class TestCICHTTPHandlerSecurity(unittest.TestCase):
    """Test HTTP endpoint validation and rejection of client-supplied values/facts."""

    def _make_handler(self, method: str, path: str, body: dict):
        body_bytes = json.dumps(body).encode("utf-8")
        handler = CopilotHTTPHandler.__new__(CopilotHTTPHandler)
        handler.command = method
        handler.path = path
        handler.headers = {
            "Content-Length": str(len(body_bytes)),
            "Content-Type": "application/json",
        }
        handler.rfile = io.BytesIO(body_bytes)
        handler.wfile = io.BytesIO()

        # Captured responses
        handler._sent_status = None
        handler._sent_data = None

        def mock_send_json(data, status_code=200):
            handler._sent_status = status_code
            handler._sent_data = data

        handler._send_json = mock_send_json
        return handler

    def test_confirm_rejects_forbidden_keys(self):
        """Security: reject client trying to forge canonical values or facts."""
        forbidden_attempts = [
            {"preview_id": "test", "section_e": {"total_debt_million": 999999}},
            {"preview_id": "test", "relations": [{"bank_name": "MSB"}]},
            {"preview_id": "test", "total_debt_million": 50000},
            {"preview_id": "test", "fields": {"status": "ok"}},
            {"preview_id": "test", "canonical_path": "section_e.cic_date"},
        ]
        for payload in forbidden_attempts:
            handler = self._make_handler("POST", "/api/confirm_cic_preview", payload)
            handler.do_POST()
            self.assertEqual(handler._sent_status, 400)
            self.assertEqual(handler._sent_data["error_type"], "InvalidInputError")
            self.assertIn("không được phép", handler._sent_data["message"])

    def test_preview_rejects_physical_file_path(self):
        """Security: reject local file path injection."""
        handler = self._make_handler(
            "POST",
            "/api/preview_cic_pdf",
            {"file_path": "C:\\Windows\\system32\\cmd.exe", "filename": "test.pdf"}
        )
        handler.do_POST()
        self.assertEqual(handler._sent_status, 400)
        self.assertEqual(handler._sent_data["error_type"], "InvalidInputError")

    def test_preview_rejects_non_pdf(self):
        handler = self._make_handler(
            "POST",
            "/api/preview_cic_pdf",
            {"filename": "document.docx", "content_base64": "AAAA"}
        )
        handler.do_POST()
        self.assertEqual(handler._sent_status, 400)
        self.assertEqual(handler._sent_data["error_type"], "InvalidFormatError")


if __name__ == "__main__":
    unittest.main()

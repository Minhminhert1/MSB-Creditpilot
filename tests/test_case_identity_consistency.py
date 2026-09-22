# -*- coding: utf-8 -*-
"""Tests for case_id consistency across the document preview/confirm flow.

=================================================================
BUG 3: preview case_id mismatch ("Ban xem truoc nay thuoc ho so
'GAS_SOUTH_JSC', khong khop voi ho so yeu cau 'GAS_SOUTH'.")
=================================================================
Repository-wide search found NO "GAS_SOUTH_JSC" string anywhere in the
codebase or demo data -- CASES_DB["GAS_SOUTH"]["id"] == "GAS_SOUTH" (canonical
key and internal id already agree; see test_demo_case_ids_match_their_dict_keys
below). "GAS_SOUTH_JSC" is not a hardcoded alias, so this is not a demo-data
key/id disagreement (section 9 of the bug report) -- it's a runtime value that
could only ever reach this system as an ad hoc case_id (e.g. a company
short_name a user typed into "+ Tao Ho So Khach Hang Moi", which builds its new
case_id via `short_name.upper().replace(" ", "_")`, matching "GAS SOUTH JSC" ->
"GAS_SOUTH_JSC" character-for-character).

The concrete, demonstrated defect this file targets is upstream of that: all
four preview-creation functions (process_legal_pdf_preview,
process_financial_pdf_preview, process_business_pdf_preview,
process_cic_pdf_preview) allowed a preview to be STAGED under a case_id that
does not exist in CASES_DB at all:
  - financial: `CASES_DB.get(target_cid, {})` silently proceeded with an
    empty case skeleton, while still recording preview.case_id = target_cid
    (the unknown id) -- the mismatch then only surfaces later, confusingly, at
    confirm time.
  - business/CIC: `if target_cid not in CASES_DB: target_cid = ACTIVE_CASE_ID`
    silently substituted whatever case happened to be currently active,
    without telling the caller -- so a preview requested for one case_id could
    silently end up owned by a completely different one.
  - legal: no check at all (relied entirely on confirm-time validation).

Fix: a single shared `_resolve_and_validate_preview_case_id()` now runs first
in all four preview functions (and before the async financial job is even
queued) -- an explicitly-provided, unknown case_id fails immediately and
clearly (CaseNotFoundError, 404). Confirm-time cross-case ownership validation
(preview.case_id == requested case_id) is untouched and still strictly
enforced -- this fix makes unknown ids fail earlier and more clearly, it does
NOT relax that check.
"""

import copy
import threading
import unittest
from unittest.mock import patch

import web_copilot_app as w
from msb_eb_copilot.src.extraction.business_extraction import (
    BusinessDocumentExtraction,
    BusinessEvidenceField,
)
from msb_eb_copilot.src.extraction.financial_extraction import (
    FinancialDocumentExtraction,
    FinancialPeriodExtraction,
)
from msb_eb_copilot.src.extraction.legal_extraction import LegalDocumentExtraction, EvidenceField as LegalEvidenceField
from msb_eb_copilot.src.extraction.cic_extraction import CICDocumentExtraction
from msb_eb_copilot.src.ingestion.router import DocumentIngestionResult
from web_copilot_app import (
    CASES_DB,
    ACTIVE_CASE_ID,
    LEGAL_PREVIEW_STORE,
    FINANCIAL_PREVIEW_STORE,
    BUSINESS_PREVIEW_STORE,
    CIC_PREVIEW_STORE,
    process_legal_pdf_preview,
    process_financial_pdf_preview,
    process_business_pdf_preview,
    process_cic_pdf_preview,
    validate_and_confirm_financial_preview,
    CopilotHTTPHandler,
)

UNKNOWN_ALIAS_CASE_ID = "GAS_SOUTH_JSC"  # never a real CASES_DB key
REAL_CASE_ID = "GAS_SOUTH"
OTHER_REAL_CASE_ID = "PSD"


def _fake_ingestion_result(page_count: int = 1) -> DocumentIngestionResult:
    tagged = "\n\n".join(f"[PAGE {i}]\nNội dung trang {i}" for i in range(1, page_count + 1))
    return DocumentIngestionResult(
        mode="digital", provider="pypdf", page_count=page_count, tagged_text=tagged,
    )


MINIMAL_FINANCIAL_EXTRACTION = FinancialDocumentExtraction(
    document_title="Báo cáo tài chính",
    periods=[FinancialPeriodExtraction(period="2025")],
)
def _empty_legal_field() -> LegalEvidenceField:
    return LegalEvidenceField(value=None, evidence=None, page=None)


MINIMAL_LEGAL_EXTRACTION = LegalDocumentExtraction(
    company_name=_empty_legal_field(),
    short_name=_empty_legal_field(),
    tax_code=_empty_legal_field(),
    address=_empty_legal_field(),
    charter_capital_raw=_empty_legal_field(),
    legal_rep_name=_empty_legal_field(),
    legal_rep_title=_empty_legal_field(),
)
MINIMAL_CIC_EXTRACTION = CICDocumentExtraction()


class CaseIdentityConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.orig_cases_db = copy.deepcopy(CASES_DB)
        LEGAL_PREVIEW_STORE.clear()
        FINANCIAL_PREVIEW_STORE.clear()
        BUSINESS_PREVIEW_STORE.clear()
        CIC_PREVIEW_STORE.clear()

    def tearDown(self):
        w.CASES_DB.clear()
        w.CASES_DB.update(copy.deepcopy(self.orig_cases_db))
        LEGAL_PREVIEW_STORE.clear()
        FINANCIAL_PREVIEW_STORE.clear()
        BUSINESS_PREVIEW_STORE.clear()
        CIC_PREVIEW_STORE.clear()

    # ------------------------------------------------------------------
    # A/B. Financial preview created with case_id=GAS_SOUTH stays GAS_SOUTH
    # ------------------------------------------------------------------
    @patch("web_copilot_app.DocumentIngestionRouter.ingest_document")
    @patch("web_copilot_app.FinancialDocumentExtractor.extract")
    def test_ab_financial_preview_created_under_gas_south_stays_gas_south(self, mock_extract, mock_ingest):
        mock_ingest.return_value = _fake_ingestion_result()
        mock_extract.return_value = MINIMAL_FINANCIAL_EXTRACTION

        res, status = process_financial_pdf_preview(b"%PDF-1.4", "bctc.pdf", case_id=REAL_CASE_ID)

        self.assertEqual(status, 200)
        self.assertEqual(res["status"], "success")
        pid = res["preview_id"]
        self.assertEqual(FINANCIAL_PREVIEW_STORE[pid].case_id, REAL_CASE_ID)

    # ------------------------------------------------------------------
    # C. Extracted company name/short name cannot mutate case_id
    # ------------------------------------------------------------------
    @patch("web_copilot_app.DocumentIngestionRouter.ingest_document")
    @patch("web_copilot_app.BusinessDocumentExtractor.extract")
    def test_c_extracted_identity_cannot_mutate_case_id(self, mock_extract, mock_ingest):
        mock_ingest.return_value = _fake_ingestion_result()
        # Deliberately fabricate an extracted identity that matches NEITHER
        # GAS_SOUTH nor any other real case -- if extraction identity ever
        # leaked into case_id resolution, this would either crash (unknown
        # case) or silently retarget the preview to some other case.
        mock_extract.return_value = BusinessDocumentExtraction(
            company_name=BusinessEvidenceField(
                value_raw="CÔNG TY HOÀN TOÀN KHÁC KHÔNG LIÊN QUAN",
                page=1,
                evidence="CÔNG TY HOÀN TOÀN KHÁC KHÔNG LIÊN QUAN",
            ),
            tax_code=BusinessEvidenceField(value_raw="9999999999", page=1, evidence="MST: 9999999999"),
        )

        res, status = process_business_pdf_preview(b"%PDF-1.4", "biz.pdf", case_id=REAL_CASE_ID)

        self.assertEqual(status, 200)
        pid = res["preview_id"]
        self.assertEqual(BUSINESS_PREVIEW_STORE[pid].case_id, REAL_CASE_ID)
        self.assertEqual(res["case_id"], REAL_CASE_ID)

    # ------------------------------------------------------------------
    # D/E/J. Confirm: same case succeeds, different real case is rejected
    # (cross-case security protection remains fully enforced)
    # ------------------------------------------------------------------
    @patch("web_copilot_app.DocumentIngestionRouter.ingest_document")
    @patch("web_copilot_app.FinancialDocumentExtractor.extract")
    def test_dej_confirm_same_case_succeeds_other_real_case_rejected(self, mock_extract, mock_ingest):
        mock_ingest.return_value = _fake_ingestion_result()
        mock_extract.return_value = MINIMAL_FINANCIAL_EXTRACTION

        preview_res, _ = process_financial_pdf_preview(b"%PDF-1.4", "bctc.pdf", case_id=REAL_CASE_ID)
        pid = preview_res["preview_id"]

        # D: confirming with the SAME case_id it was created under succeeds.
        res_ok, status_ok = validate_and_confirm_financial_preview(preview_id=pid, case_id=REAL_CASE_ID)
        self.assertEqual(status_ok, 200)
        self.assertEqual(res_ok["status"], "success")

        # E/J: a second preview, confirmed against a DIFFERENT real case,
        # must still be rejected -- the ownership check is not weakened.
        preview_res2, _ = process_financial_pdf_preview(b"%PDF-1.4", "bctc2.pdf", case_id=REAL_CASE_ID)
        pid2 = preview_res2["preview_id"]
        res_bad, status_bad = validate_and_confirm_financial_preview(preview_id=pid2, case_id=OTHER_REAL_CASE_ID)
        self.assertEqual(status_bad, 400)
        self.assertEqual(res_bad["error_type"], "CaseMismatchError")
        self.assertIn(REAL_CASE_ID, res_bad["message"])
        self.assertIn(OTHER_REAL_CASE_ID, res_bad["message"])

    # ------------------------------------------------------------------
    # F. An unknown alias-like case_id can never become a preview ownership
    # id -- it must fail immediately at creation, not silently succeed under
    # ACTIVE_CASE_ID or an empty case skeleton.
    # ------------------------------------------------------------------
    def test_f_unknown_alias_case_id_rejected_for_all_four_doc_types(self):
        cases = [
            ("legal", process_legal_pdf_preview),
            ("financial", process_financial_pdf_preview),
            ("business", process_business_pdf_preview),
            ("cic", process_cic_pdf_preview),
        ]
        for doc_type, fn in cases:
            with self.subTest(doc_type=doc_type):
                res, status = fn(b"%PDF-1.4", "doc.pdf", case_id=UNKNOWN_ALIAS_CASE_ID)
                self.assertEqual(status, 404, f"{doc_type} did not reject unknown case_id")
                self.assertEqual(res["status"], "error")
                self.assertEqual(res["error_type"], "CaseNotFoundError")
                self.assertIn(UNKNOWN_ALIAS_CASE_ID, res["message"])

        # No preview may have been staged under the unknown id in any store.
        self.assertFalse(any(r.case_id == UNKNOWN_ALIAS_CASE_ID for r in LEGAL_PREVIEW_STORE.values()))
        self.assertFalse(any(r.case_id == UNKNOWN_ALIAS_CASE_ID for r in FINANCIAL_PREVIEW_STORE.values()))
        self.assertFalse(any(r.case_id == UNKNOWN_ALIAS_CASE_ID for r in BUSINESS_PREVIEW_STORE.values()))
        self.assertFalse(any(r.case_id == UNKNOWN_ALIAS_CASE_ID for r in CIC_PREVIEW_STORE.values()))

    # ------------------------------------------------------------------
    # G. The async financial job preserves the exact validated case_id
    # end-to-end and never recomputes it from extraction.
    # ------------------------------------------------------------------
    def test_g_async_financial_job_preserves_original_case_id(self):
        job_id = w.FINANCIAL_JOB_MANAGER.create_job(case_id=REAL_CASE_ID)
        with patch.object(w.DocumentIngestionRouter, "ingest_document", return_value=_fake_ingestion_result()), \
             patch.object(w.FinancialDocumentExtractor, "extract", return_value=MINIMAL_FINANCIAL_EXTRACTION):
            t = threading.Thread(
                target=w._run_financial_preview_job,
                args=(job_id, b"%PDF-1.4", "bctc.pdf", REAL_CASE_ID),
            )
            t.start()
            t.join(timeout=5)

        snap = w.FINANCIAL_JOB_MANAGER.get_job_snapshot(job_id)
        self.assertEqual(snap["status"], "completed")
        pid = snap["result"]["preview_id"]
        self.assertEqual(FINANCIAL_PREVIEW_STORE[pid].case_id, REAL_CASE_ID)

    def test_g_dispatcher_rejects_unknown_case_id_before_queueing_job(self):
        """The HTTP dispatcher validates case_id BEFORE creating a background
        job -- an unknown case_id never gets an OCR job queued for it at all."""
        import base64
        import io
        import json as json_mod

        jobs_before = len(w.FINANCIAL_JOB_MANAGER._jobs)
        payload = {
            "filename": "bctc.pdf",
            "content_base64": base64.b64encode(b"%PDF-1.4 dummy").decode("utf-8"),
            "case_id": UNKNOWN_ALIAS_CASE_ID,
        }
        body_bytes = json_mod.dumps(payload).encode("utf-8")
        handler = CopilotHTTPHandler.__new__(CopilotHTTPHandler)
        handler.path = "/api/preview_financial_pdf"
        handler.headers = {"Content-Length": str(len(body_bytes))}
        handler.rfile = io.BytesIO(body_bytes)
        handler.wfile = io.BytesIO()
        result = {}

        def fake_send_json(data, status_code=200):
            result["status_code"] = status_code
            result["data"] = data

        handler._send_json = fake_send_json
        handler.do_POST()

        self.assertEqual(result["status_code"], 404)
        self.assertEqual(result["data"]["error_type"], "CaseNotFoundError")
        self.assertEqual(len(w.FINANCIAL_JOB_MANAGER._jobs), jobs_before, "No job should have been queued")

    # ------------------------------------------------------------------
    # H. Legal / Business / CIC ownership behavior: valid real case_id
    # succeeds and is preserved verbatim in each store.
    # ------------------------------------------------------------------
    @patch("web_copilot_app.DocumentIngestionRouter.ingest_document")
    @patch("web_copilot_app.LegalDocumentExtractor.extract")
    def test_h_legal_ownership_preserved(self, mock_extract, mock_ingest):
        mock_ingest.return_value = _fake_ingestion_result()
        mock_extract.return_value = MINIMAL_LEGAL_EXTRACTION
        res, status = process_legal_pdf_preview(b"%PDF-1.4", "legal.pdf", case_id=REAL_CASE_ID)
        self.assertEqual(status, 200)
        self.assertEqual(LEGAL_PREVIEW_STORE[res["preview_id"]].case_id, REAL_CASE_ID)

    @patch("web_copilot_app.DocumentIngestionRouter.ingest_document")
    @patch("web_copilot_app.CICDocumentExtractor.extract")
    def test_h_cic_ownership_preserved(self, mock_extract, mock_ingest):
        mock_ingest.return_value = _fake_ingestion_result()
        mock_extract.return_value = MINIMAL_CIC_EXTRACTION
        res, status = process_cic_pdf_preview(b"%PDF-1.4", "cic.pdf", case_id=REAL_CASE_ID)
        self.assertEqual(status, 200)
        self.assertEqual(CIC_PREVIEW_STORE[res["preview_id"]].case_id, REAL_CASE_ID)

    @patch("web_copilot_app.DocumentIngestionRouter.ingest_document")
    @patch("web_copilot_app.BusinessDocumentExtractor.extract")
    def test_h_business_ownership_preserved(self, mock_extract, mock_ingest):
        mock_ingest.return_value = _fake_ingestion_result()
        mock_extract.return_value = BusinessDocumentExtraction()
        res, status = process_business_pdf_preview(b"%PDF-1.4", "biz.pdf", case_id=REAL_CASE_ID)
        self.assertEqual(status, 200)
        self.assertEqual(BUSINESS_PREVIEW_STORE[res["preview_id"]].case_id, REAL_CASE_ID)

    # ------------------------------------------------------------------
    # I. Switching the active case cannot confirm a stale preview created
    # under a previously-selected case.
    # ------------------------------------------------------------------
    @patch("web_copilot_app.DocumentIngestionRouter.ingest_document")
    @patch("web_copilot_app.FinancialDocumentExtractor.extract")
    def test_i_switching_case_cannot_confirm_stale_preview(self, mock_extract, mock_ingest):
        mock_ingest.return_value = _fake_ingestion_result()
        mock_extract.return_value = MINIMAL_FINANCIAL_EXTRACTION

        # RM was working on GAS_SOUTH and created a preview there.
        preview_res, _ = process_financial_pdf_preview(b"%PDF-1.4", "bctc.pdf", case_id=REAL_CASE_ID)
        pid = preview_res["preview_id"]

        # RM then switches the case selector to PSD without re-uploading, and
        # tries to confirm the SAME (now stale) preview_id under PSD.
        res, status = validate_and_confirm_financial_preview(preview_id=pid, case_id=OTHER_REAL_CASE_ID)
        self.assertEqual(status, 400)
        self.assertEqual(res["error_type"], "CaseMismatchError")
        self.assertFalse(FINANCIAL_PREVIEW_STORE[pid].consumed)
        # PSD's own data must remain completely untouched by the rejected attempt.
        self.assertEqual(CASES_DB[OTHER_REAL_CASE_ID], self.orig_cases_db[OTHER_REAL_CASE_ID])


class DemoCaseIdConsistencyTests(unittest.TestCase):
    """Section 9: demo/preloaded data must never disagree between the
    CASES_DB dict key and the case's own canonical `id` field."""

    def test_demo_case_ids_match_their_dict_keys(self):
        for key, case_data in CASES_DB.items():
            self.assertEqual(
                case_data.get("id"), key,
                f"CASES_DB key '{key}' disagrees with its own case['id']={case_data.get('id')!r}",
            )

    def test_gas_south_is_the_sole_canonical_id_no_jsc_alias_present(self):
        self.assertIn("GAS_SOUTH", CASES_DB)
        self.assertNotIn("GAS_SOUTH_JSC", CASES_DB)
        self.assertEqual(CASES_DB["GAS_SOUTH"]["id"], "GAS_SOUTH")


if __name__ == "__main__":
    unittest.main()

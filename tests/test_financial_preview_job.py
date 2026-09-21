# -*- coding: utf-8 -*-
"""Tests for the async background-job refactor of the financial PDF OCR preview
flow (POST /api/preview_financial_pdf -> 202 + job_id, GET
/api/financial_preview_job/<job_id> -> progress/result polling).

Confirmed production motivation: a 46-page scanned BCTC against a 5 RPM Vision
quota takes far longer than the browser/gateway request lifetime, so OCR must
run on a background thread instead of blocking the HTTP request.
"""

import base64
import copy
import io
import json
import os
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import web_copilot_app as w
from msb_eb_copilot.src.extraction.financial_extraction import (
    FinancialDocumentExtraction,
    FinancialPeriodExtraction,
)
from msb_eb_copilot.src.ingestion.pdf_ocr import OCRServiceError
from msb_eb_copilot.src.ingestion.router import DocumentIngestionResult

FAKE_SECRET = "sk-LIVE-super-secret-should-never-leak-abc123"

MINIMAL_EXTRACTION = FinancialDocumentExtraction(
    document_title="Báo cáo tài chính năm 2025",
    periods=[FinancialPeriodExtraction(period="2025")],
)


def _fake_ingestion_result(page_count: int = 1) -> DocumentIngestionResult:
    tagged = "\n\n".join(f"[PAGE {i}]\nNội dung trang {i}" for i in range(1, page_count + 1))
    return DocumentIngestionResult(
        mode="ocr",
        provider="qwen_vision",
        page_count=page_count,
        tagged_text=tagged,
        fallback_reason="PDFBlankPageError",
    )


def _wait_until(predicate, timeout: float = 5.0, interval: float = 0.02) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


class _HTTPHandlerTestMixin:
    """Constructs a real CopilotHTTPHandler with I/O methods swapped for
    in-memory doubles, so do_POST()/do_GET() can be exercised directly without
    an actual TCP socket -- same pattern already used elsewhere in this suite."""

    def _invoke_post(self, path: str, body: dict):
        body_bytes = json.dumps(body).encode("utf-8")
        handler = w.CopilotHTTPHandler.__new__(w.CopilotHTTPHandler)
        handler.path = path
        handler.headers = {"Content-Length": str(len(body_bytes))}
        handler.rfile = io.BytesIO(body_bytes)
        handler.wfile = io.BytesIO()

        result = {"status": 200, "data": {}}
        handler.send_response = lambda code: result.__setitem__("status", code)
        handler.send_header = lambda k, v: None
        handler.end_headers = lambda: None

        def fake_send_json(data, status_code=200):
            result["status"] = status_code
            result["data"] = data
        handler._send_json = fake_send_json

        handler.do_POST()
        return result["status"], result["data"]

    def _invoke_get(self, path: str):
        handler = w.CopilotHTTPHandler.__new__(w.CopilotHTTPHandler)
        handler.path = path
        handler.wfile = io.BytesIO()

        result = {"status": 200, "data": {}}
        handler.send_response = lambda code: result.__setitem__("status", code)
        handler.send_header = lambda k, v: None
        handler.end_headers = lambda: None

        def fake_send_json(data, status_code=200):
            result["status"] = status_code
            result["data"] = data
        handler._send_json = fake_send_json

        handler.do_GET()
        return result["status"], result["data"]


class TestFinancialPreviewJobFlow(_HTTPHandlerTestMixin, unittest.TestCase):
    def setUp(self):
        self.orig_cases_db = copy.deepcopy(w.CASES_DB)
        w.FINANCIAL_PREVIEW_STORE.clear()
        w.FINANCIAL_JOB_MANAGER._jobs.clear()

    def tearDown(self):
        w.CASES_DB.clear()
        w.CASES_DB.update(copy.deepcopy(self.orig_cases_db))
        w.FINANCIAL_JOB_MANAGER._jobs.clear()

    # -- A: POST returns 202 quickly with job_id -----------------------------
    def test_post_returns_202_quickly_with_job_id_while_ocr_still_running(self):
        release_event = threading.Event()

        def blocking_ingest(pdf_path, progress_callback=None, **kwargs):
            release_event.wait(timeout=5)
            return _fake_ingestion_result()

        with patch.object(w.DocumentIngestionRouter, "ingest_document", side_effect=blocking_ingest), \
             patch.object(w.FinancialDocumentExtractor, "extract", return_value=MINIMAL_EXTRACTION):

            start = time.monotonic()
            status, data = self._invoke_post("/api/preview_financial_pdf", {
                "filename": "bctc.pdf",
                "content_base64": base64.b64encode(b"%PDF-1.4 dummy").decode("utf-8"),
                "case_id": "PSD",
            })
            elapsed = time.monotonic() - start

            self.assertEqual(status, 202)
            self.assertEqual(data["status"], "accepted")
            self.assertIn("job_id", data)
            # Must return well before the (still-blocked) OCR call ever finishes.
            self.assertLess(elapsed, 1.0)

            release_event.set()
            job_id = data["job_id"]
            ok = _wait_until(lambda: w.FINANCIAL_JOB_MANAGER.get_job_snapshot(job_id)["status"] == "completed")
        self.assertTrue(ok, "background job never reached 'completed'")

    # -- B: queued -> processing -> completed --------------------------------
    def test_job_transitions_queued_processing_completed(self):
        job_id = w.FINANCIAL_JOB_MANAGER.create_job(case_id="PSD")
        self.assertEqual(w.FINANCIAL_JOB_MANAGER.get_job_snapshot(job_id)["status"], "queued")

        observed = {}

        def fake_ingest(pdf_path, progress_callback=None, **kwargs):
            observed["mid_flight_status"] = w.FINANCIAL_JOB_MANAGER.get_job_snapshot(job_id)["status"]
            if progress_callback:
                progress_callback(1, 1, 1)
            return _fake_ingestion_result()

        with patch.object(w.DocumentIngestionRouter, "ingest_document", side_effect=fake_ingest), \
             patch.object(w.FinancialDocumentExtractor, "extract", return_value=MINIMAL_EXTRACTION):
            w._run_financial_preview_job(job_id, b"%PDF-1.4 dummy", "bctc.pdf", "PSD")

        self.assertEqual(observed["mid_flight_status"], "processing")
        final = w.FINANCIAL_JOB_MANAGER.get_job_snapshot(job_id)
        self.assertEqual(final["status"], "completed")
        self.assertEqual(final["progress_percent"], 100.0)
        self.assertEqual(final["result"]["status"], "success")

    # -- C: polling returns progress ------------------------------------------
    def test_polling_returns_current_page_total_pages_and_percent_mid_flight(self):
        job_id = w.FINANCIAL_JOB_MANAGER.create_job(case_id="PSD")
        captured = {}

        def fake_ingest(pdf_path, progress_callback=None, **kwargs):
            progress_callback(18, 18, 46)
            captured["snapshot"] = w.FINANCIAL_JOB_MANAGER.get_job_snapshot(job_id)
            return _fake_ingestion_result()

        with patch.object(w.DocumentIngestionRouter, "ingest_document", side_effect=fake_ingest), \
             patch.object(w.FinancialDocumentExtractor, "extract", return_value=MINIMAL_EXTRACTION):
            w._run_financial_preview_job(job_id, b"%PDF-1.4 dummy", "bctc.pdf", "PSD")

        snap = captured["snapshot"]
        self.assertEqual(snap["status"], "processing")
        self.assertEqual(snap["current_page"], 18)
        self.assertEqual(snap["total_pages"], 46)
        self.assertAlmostEqual(snap["progress_percent"], round(18 / 46 * 100, 1))
        self.assertIn("trang 18 / 46", snap["message"])

        # And the same fields are reachable through the real GET polling route.
        status_code, body = self._invoke_get(f"/api/financial_preview_job/{job_id}")
        self.assertEqual(status_code, 200)
        self.assertEqual(body["status"], "completed")  # job already finished by the time we polled
        self.assertEqual(body["job_id"], job_id)

    # -- D: completed job matches synchronous schema --------------------------
    def test_completed_job_result_matches_synchronous_endpoint_schema(self):
        job_id = w.FINANCIAL_JOB_MANAGER.create_job(case_id="PSD")
        raw_bytes = b"%PDF-1.4 dummy content"

        with patch.object(w.DocumentIngestionRouter, "ingest_document", return_value=_fake_ingestion_result()), \
             patch.object(w.FinancialDocumentExtractor, "extract", return_value=MINIMAL_EXTRACTION):
            w._run_financial_preview_job(job_id, raw_bytes, "bctc.pdf", "PSD")
            sync_result, sync_status = w.process_financial_pdf_preview(raw_bytes, "bctc.pdf", case_id="PSD")

        self.assertEqual(sync_status, 200)
        job_result = w.FINANCIAL_JOB_MANAGER.get_job_snapshot(job_id)["result"]

        self.assertEqual(set(job_result.keys()), set(sync_result.keys()))
        for key in ("status", "filename", "routing", "review_table", "periods", "calculated_ratios"):
            self.assertEqual(job_result[key], sync_result[key], f"mismatch on key={key}")

    # -- E: OCR failure -> failed job with safe error -------------------------
    def test_ocr_failure_produces_failed_job_with_safe_unchanged_error_message(self):
        job_id = w.FINANCIAL_JOB_MANAGER.create_job(case_id="PSD")

        def blow_up(pdf_path, progress_callback=None, **kwargs):
            try:
                raise RuntimeError(f"connection reset, key={FAKE_SECRET}, path={pdf_path}")
            except RuntimeError as root:
                raise OCRServiceError("Lỗi dịch vụ OCR khi xử lý trang 5: boom") from root

        with patch.object(w.DocumentIngestionRouter, "ingest_document", side_effect=blow_up):
            w._run_financial_preview_job(job_id, b"%PDF-1.4 dummy", "bctc.pdf", "PSD")

        snap = w.FINANCIAL_JOB_MANAGER.get_job_snapshot(job_id)
        self.assertEqual(snap["status"], "failed")
        self.assertEqual(snap["error"]["error_type"], "OCRServiceError")
        # Exact unchanged Vietnamese user-facing message (same as the old sync path).
        self.assertEqual(snap["error"]["message"], "Dịch vụ OCR hình ảnh gặp sự cố kết nối.")
        self.assertIsNone(snap["result"])

    # -- F: client disconnect does not stop background processing ------------
    def test_client_disconnect_does_not_stop_background_processing(self):
        release_event = threading.Event()

        def fake_ingest(pdf_path, progress_callback=None, **kwargs):
            release_event.wait(timeout=5)
            return _fake_ingestion_result()

        with patch.object(w.DocumentIngestionRouter, "ingest_document", side_effect=fake_ingest), \
             patch.object(w.FinancialDocumentExtractor, "extract", return_value=MINIMAL_EXTRACTION):
            status, data = self._invoke_post("/api/preview_financial_pdf", {
                "filename": "bctc.pdf",
                "content_base64": base64.b64encode(b"%PDF-1.4 dummy").decode("utf-8"),
                "case_id": "PSD",
            })
            job_id = data["job_id"]
            # Simulate the browser/gateway dropping the connection: nothing about
            # the background thread references the handler/request objects, so
            # dropping them here has zero effect on job execution.
            del status, data

            release_event.set()
            ok = _wait_until(lambda: w.FINANCIAL_JOB_MANAGER.get_job_snapshot(job_id)["status"] == "completed")
        self.assertTrue(ok)

    # -- G: concurrent jobs are isolated ---------------------------------------
    def test_concurrent_jobs_are_isolated(self):
        job_id_1 = w.FINANCIAL_JOB_MANAGER.create_job(case_id="PSD")
        job_id_2 = w.FINANCIAL_JOB_MANAGER.create_job(case_id="GAS_SOUTH")

        def dispatch_ingest(pdf_path, progress_callback=None, **kwargs):
            with open(pdf_path, "rb") as f:
                content = f.read()
            if b"JOB_ONE_MARKER" in content:
                if progress_callback:
                    progress_callback(1, 1, 1)
                return _fake_ingestion_result()
            try:
                raise RuntimeError("root cause for job two")
            except RuntimeError as root:
                raise OCRServiceError("Lỗi dịch vụ OCR khi xử lý trang 1: boom") from root

        with patch.object(w.DocumentIngestionRouter, "ingest_document", side_effect=dispatch_ingest), \
             patch.object(w.FinancialDocumentExtractor, "extract", return_value=MINIMAL_EXTRACTION):
            t1 = threading.Thread(
                target=w._run_financial_preview_job,
                args=(job_id_1, b"%PDF-1.4 JOB_ONE_MARKER", "a.pdf", "PSD"),
            )
            t2 = threading.Thread(
                target=w._run_financial_preview_job,
                args=(job_id_2, b"%PDF-1.4 JOB_TWO_MARKER", "b.pdf", "GAS_SOUTH"),
            )
            t1.start()
            t2.start()
            t1.join(timeout=5)
            t2.join(timeout=5)

        snap1 = w.FINANCIAL_JOB_MANAGER.get_job_snapshot(job_id_1)
        snap2 = w.FINANCIAL_JOB_MANAGER.get_job_snapshot(job_id_2)

        self.assertEqual(snap1["status"], "completed")
        self.assertIsNotNone(snap1["result"])
        self.assertIsNone(snap1["error"])

        self.assertEqual(snap2["status"], "failed")
        self.assertIsNone(snap2["result"])
        self.assertIsNotNone(snap2["error"])

    # -- H: expired jobs are cleaned up -----------------------------------------
    def test_expired_completed_job_is_purged_lazily(self):
        fake_now = {"t": 0.0}
        manager = w.FinancialJobManager(retention_seconds=60.0, clock=lambda: fake_now["t"])

        job_id = manager.create_job(case_id="PSD")
        manager.mark_completed(job_id, {"status": "success"})
        self.assertIsNotNone(manager.get_job_snapshot(job_id))

        fake_now["t"] = 61.0  # just past the retention window
        self.assertIsNone(manager.get_job_snapshot(job_id))

    def test_in_progress_job_is_never_purged_regardless_of_age(self):
        fake_now = {"t": 0.0}
        manager = w.FinancialJobManager(retention_seconds=60.0, clock=lambda: fake_now["t"])

        job_id = manager.create_job(case_id="PSD")
        manager.mark_processing(job_id)
        fake_now["t"] = 10_000.0
        self.assertIsNotNone(manager.get_job_snapshot(job_id))

    def test_new_job_creation_triggers_purge_of_other_expired_jobs(self):
        fake_now = {"t": 0.0}
        manager = w.FinancialJobManager(retention_seconds=60.0, clock=lambda: fake_now["t"])

        old_job_id = manager.create_job(case_id="PSD")
        manager.mark_completed(old_job_id, {"status": "success"})

        fake_now["t"] = 61.0
        new_job_id = manager.create_job(case_id="PSD")

        self.assertNotIn(old_job_id, manager._jobs)
        self.assertIn(new_job_id, manager._jobs)

    # -- I: secrets/temp paths are never returned ------------------------------
    def test_job_snapshot_never_contains_secrets_or_temp_paths(self):
        job_id = w.FINANCIAL_JOB_MANAGER.create_job(case_id="PSD")

        def leaking_ingest(pdf_path, progress_callback=None, **kwargs):
            self.assertTrue(os.path.exists(pdf_path))  # sanity: this IS a real temp path
            try:
                raise RuntimeError(f"key={FAKE_SECRET} path={pdf_path}")
            except RuntimeError as root:
                raise OCRServiceError(f"Lỗi dịch vụ OCR khi xử lý trang 1: {pdf_path}") from root

        with patch.object(w.DocumentIngestionRouter, "ingest_document", side_effect=leaking_ingest):
            w._run_financial_preview_job(job_id, b"%PDF-1.4 dummy", "bctc.pdf", "PSD")

        snap = w.FINANCIAL_JOB_MANAGER.get_job_snapshot(job_id)
        dumped = json.dumps(snap, default=str)
        self.assertNotIn(FAKE_SECRET, dumped)
        self.assertNotIn("fin_preview_", dumped)  # tempfile.NamedTemporaryFile prefix
        self.assertNotIn(tempfile.gettempdir(), dumped)
        # Contract: only ever these fields, nothing extra sneaks in.
        self.assertEqual(
            set(snap.keys()),
            {"job_id", "status", "current_page", "total_pages", "progress_percent", "message", "result", "error"},
        )

    def test_unknown_job_id_returns_404_without_leaking_internals(self):
        status_code, body = self._invoke_get("/api/financial_preview_job/does-not-exist-uuid")
        self.assertEqual(status_code, 404)
        self.assertEqual(body["error_type"], "JobNotFoundError")


if __name__ == "__main__":
    unittest.main()

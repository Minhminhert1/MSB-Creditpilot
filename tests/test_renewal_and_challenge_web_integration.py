# -*- coding: utf-8 -*-
"""Integration tests for the "Tái cấp" and "AI Challenge" sidebar workspaces at
the web_copilot_app.py HTTP layer: sidebar markup, real end-to-end HTTP routes,
per-case state isolation (no global stale state), and the light MB07-generation
provenance-context integration point (FACT vs RM_EXPLANATION separation).
"""

import base64
import copy
import io
import json
import unittest
from unittest.mock import patch

import docx

import web_copilot_app as w


def _make_old_mb07_docx(rows):
    document = docx.Document()
    table = document.add_table(rows=0, cols=2)
    for label, value in rows:
        row = table.add_row()
        row.cells[0].text = label
        row.cells[1].text = value
    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


class _HTTPHandlerTestMixin:
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


class TestSidebarContainsNewWorkspaces(unittest.TestCase):
    def test_sidebar_contains_tai_cap_entry(self):
        html = w.HTML_PAGE
        self.assertIn("switchTab('tab-renewal')", html)
        self.assertIn('id="nav-tab-renewal"', html)
        self.assertIn(">Tái cấp<", html)

    def test_sidebar_contains_ai_challenge_entry(self):
        html = w.HTML_PAGE
        self.assertIn("switchTab('tab-ai-challenge')", html)
        self.assertIn('id="nav-tab-ai-challenge"', html)
        self.assertIn(">AI Challenge<", html)

    def test_workspace_sections_exist_as_real_sections_not_a_modal(self):
        """These must be proper application workspaces (real <section> tabs
        toggled by switchTab), not temporary buttons bolted onto another page."""
        html = w.HTML_PAGE
        self.assertIn('<section id="tab-renewal"', html)
        self.assertIn('<section id="tab-ai-challenge"', html)

    def test_switch_tab_master_list_includes_both_new_tabs(self):
        html = w.HTML_PAGE
        self.assertIn("'tab-renewal'", html)
        self.assertIn("'tab-ai-challenge'", html)

    def test_l_frontend_renders_inline_enrichment_and_analyzer_warnings(self):
        """L. Inline (non-blocking) warning panel logic exists in the frontend
        for both enrichment_status PARTIAL/FAILED and non-empty analyzer_warnings
        -- and must not use alert() for these warnings."""
        html = w.HTML_PAGE
        self.assertIn('id="challenge-warnings-container"', html)
        self.assertIn("function renderChallengeWarnings", html)
        self.assertIn("enrichment_status", html)
        self.assertIn("analyzer_warnings", html)
        self.assertIn(
            "AI Challenge đã được tạo bằng bộ quy tắc kiểm soát. Bước tinh chỉnh ngôn ngữ AI không hoàn tất.",
            html,
        )
        self.assertIn("Một số chỉ tiêu không thể tính toán tự động. Vui lòng kiểm tra dữ liệu đầu vào.", html)

    def test_l_challenge_warnings_rendering_does_not_use_alert(self):
        html = w.HTML_PAGE
        start = html.index("function renderChallengeWarnings")
        end = html.index("\n    }", start)
        render_fn_body = html[start:end]
        self.assertNotIn("alert(", render_fn_body)


class TestRenewalAndChallengeHTTPFlow(_HTTPHandlerTestMixin, unittest.TestCase):
    def setUp(self):
        self.orig_cases_db = copy.deepcopy(w.CASES_DB)
        w.RENEWAL_STORE.clear_case("PSD")
        w.RENEWAL_STORE.clear_case("GAS_SOUTH")
        w.AI_CHALLENGE_STORE.clear_case("PSD")
        w.AI_CHALLENGE_STORE.clear_case("GAS_SOUTH")

    def tearDown(self):
        w.CASES_DB.clear()
        w.CASES_DB.update(copy.deepcopy(self.orig_cases_db))
        w.RENEWAL_STORE.clear_case("PSD")
        w.RENEWAL_STORE.clear_case("GAS_SOUTH")
        w.AI_CHALLENGE_STORE.clear_case("PSD")
        w.AI_CHALLENGE_STORE.clear_case("GAS_SOUTH")

    def test_renewal_state_before_any_upload(self):
        status, data = self._invoke_get("/api/renewal/state?case_id=PSD")
        self.assertEqual(status, 200)
        self.assertFalse(data["has_old_mb07"])
        self.assertFalse(data["has_change_analysis"])

    def test_upload_old_mb07_rejects_non_docx(self):
        status, data = self._invoke_post("/api/renewal/upload_old_mb07", {
            "filename": "old.pdf",
            "content_base64": base64.b64encode(b"not a docx").decode("utf-8"),
            "case_id": "PSD",
        })
        self.assertEqual(status, 400)
        self.assertEqual(data["error_type"], "InvalidFormatError")

    def test_upload_old_mb07_rejects_client_file_path(self):
        status, data = self._invoke_post("/api/renewal/upload_old_mb07", {
            "filename": "old.docx",
            "content_base64": "",
            "file_path": "/etc/passwd",
        })
        self.assertEqual(status, 400)
        self.assertEqual(data["error_type"], "InvalidInputError")

    def test_full_renewal_flow_upload_analyze_resolve(self):
        docx_bytes = _make_old_mb07_docx([
            ("Doanh thu thuần", "7.200 tỷ VND"),
            ("Khách hàng lớn nhất", "ABC Corporation"),
        ])
        status, data = self._invoke_post("/api/renewal/upload_old_mb07", {
            "filename": "MB07_kytruoc.docx",
            "content_base64": base64.b64encode(docx_bytes).decode("utf-8"),
            "case_id": "PSD",
        })
        self.assertEqual(status, 200)
        self.assertEqual(data["parsed_field_count"], 2)

        status, data = self._invoke_post("/api/renewal/analyze_changes", {"case_id": "PSD"})
        self.assertEqual(status, 200)
        self.assertGreater(data["summary"]["CHANGED"], 0)

        revenue_item = next(i for i in data["change_set"]["items"] if i["canonical_path"] == "financial.net_revenue_latest")
        self.assertEqual(revenue_item["status"], "CHANGED")

        status, data = self._invoke_post("/api/renewal/resolve_change", {
            "case_id": "PSD",
            "canonical_path": "financial.net_revenue_latest",
            "resolution": "ACCEPT_NEW",
        })
        self.assertEqual(status, 200)
        self.assertEqual(data["item"]["rm_resolution"], "ACCEPT_NEW")

    def test_analyze_changes_without_old_mb07_fails_loudly(self):
        status, data = self._invoke_post("/api/renewal/analyze_changes", {"case_id": "PSD"})
        self.assertEqual(status, 400)
        self.assertEqual(data["error_type"], "OldMB07MissingError")

    def test_case_switching_isolates_renewal_and_challenge_state(self):
        """Switching cases must show only data belonging to that case -- no
        global stale state leaking between PSD and GAS_SOUTH."""
        docx_bytes = _make_old_mb07_docx([("Doanh thu thuần", "1.000 tỷ VND")])
        self._invoke_post("/api/renewal/upload_old_mb07", {
            "filename": "psd_old.docx",
            "content_base64": base64.b64encode(docx_bytes).decode("utf-8"),
            "case_id": "PSD",
        })

        with patch("msb_eb_copilot.src.ai_client.AIAssistantClient.chat", side_effect=RuntimeError("offline")):
            self._invoke_post("/api/ai_challenge/run", {"case_id": "PSD"})

        status, psd_state = self._invoke_get("/api/renewal/state?case_id=PSD")
        self.assertTrue(psd_state["has_old_mb07"])

        status, gas_state = self._invoke_get("/api/renewal/state?case_id=GAS_SOUTH")
        self.assertFalse(gas_state["has_old_mb07"])  # PSD's upload never leaks to GAS_SOUTH

        status, psd_challenge = self._invoke_get("/api/ai_challenge/state?case_id=PSD")
        self.assertEqual(psd_challenge["run_status"], "COMPLETED")

        status, gas_challenge = self._invoke_get("/api/ai_challenge/state?case_id=GAS_SOUTH")
        self.assertEqual(gas_challenge["run_status"], "NOT_RUN")  # never run for GAS_SOUTH

    def test_run_ai_challenge_and_respond_end_to_end(self):
        with patch("msb_eb_copilot.src.ai_client.AIAssistantClient.chat", side_effect=RuntimeError("offline")):
            status, data = self._invoke_post("/api/ai_challenge/run", {"case_id": "PSD"})
        self.assertEqual(status, 200)
        self.assertGreater(len(data["items"]), 0)

        challenge_id = data["items"][0]["id"]
        status, resp_data = self._invoke_post("/api/ai_challenge/respond", {
            "case_id": "PSD",
            "challenge_id": challenge_id,
            "rm_status": "ANSWERED",
            "rm_response": "RM đã giải trình lý do biến động.",
        })
        self.assertEqual(status, 200)
        self.assertEqual(resp_data["item"]["rm_status"], "ANSWERED")

        # Persisted -- reading state again shows the same answered status.
        status, state = self._invoke_get("/api/ai_challenge/state?case_id=PSD")
        item = next(i for i in state["items"] if i["id"] == challenge_id)
        self.assertEqual(item["rm_status"], "ANSWERED")
        self.assertEqual(item["rm_response"], "RM đã giải trình lý do biến động.")

    def test_respond_rejects_invalid_status_transition_to_open(self):
        with patch("msb_eb_copilot.src.ai_client.AIAssistantClient.chat", side_effect=RuntimeError("offline")):
            _, data = self._invoke_post("/api/ai_challenge/run", {"case_id": "PSD"})
        challenge_id = data["items"][0]["id"]
        status, resp = self._invoke_post("/api/ai_challenge/respond", {
            "case_id": "PSD", "challenge_id": challenge_id, "rm_status": "OPEN",
        })
        self.assertEqual(status, 400)

    def test_demo_reset_clears_only_that_cases_renewal_and_challenge_state(self):
        docx_bytes = _make_old_mb07_docx([("Doanh thu thuần", "1.000 tỷ VND")])
        self._invoke_post("/api/renewal/upload_old_mb07", {
            "filename": "psd_old.docx",
            "content_base64": base64.b64encode(docx_bytes).decode("utf-8"),
            "case_id": "PSD",
        })
        self._invoke_post("/api/renewal/upload_old_mb07", {
            "filename": "gas_old.docx",
            "content_base64": base64.b64encode(docx_bytes).decode("utf-8"),
            "case_id": "GAS_SOUTH",
        })

        self._invoke_post("/api/demo_reset", {"case_id": "PSD"})

        _, psd_state = self._invoke_get("/api/renewal/state?case_id=PSD")
        self.assertFalse(psd_state["has_old_mb07"])  # cleared by reset

        _, gas_state = self._invoke_get("/api/renewal/state?case_id=GAS_SOUTH")
        self.assertTrue(gas_state["has_old_mb07"])  # untouched by PSD's reset

    def test_k_enrichment_warning_metadata_reaches_http_response_on_failure(self):
        """K. Zero Silent Fallback metadata must reach the HTTP response, not
        just the internal ChallengeSet object."""
        with patch("msb_eb_copilot.src.ai_client.AIAssistantClient.chat", side_effect=RuntimeError("simulated outage")):
            status, data = self._invoke_post("/api/ai_challenge/run", {"case_id": "PSD"})
        self.assertEqual(status, 200)
        self.assertEqual(data["enrichment_status"], "FAILED")
        self.assertEqual(
            data["enrichment_warning"],
            "AI Challenge đã được tạo bằng bộ quy tắc kiểm soát. Bước tinh chỉnh ngôn ngữ AI không hoàn tất.",
        )
        self.assertIn("analyzer_warnings", data)
        # Deterministic content is still fully present and usable despite FAILED enrichment.
        self.assertGreater(len(data["items"]), 0)

        # The polling GET route surfaces the exact same metadata afterwards.
        status, state = self._invoke_get("/api/ai_challenge/state?case_id=PSD")
        self.assertEqual(state["enrichment_status"], "FAILED")
        self.assertEqual(state["enrichment_warning"], data["enrichment_warning"])

    def test_k_analyzer_warnings_metadata_reaches_http_response(self):
        with patch("msb_eb_copilot.src.ai_challenge.analyzers.compute_canonical_ratios", side_effect=RuntimeError("boom")), \
             patch("msb_eb_copilot.src.ai_client.AIAssistantClient.chat", side_effect=RuntimeError("offline")):
            status, data = self._invoke_post("/api/ai_challenge/run", {"case_id": "PSD"})
        self.assertEqual(status, 200)
        self.assertTrue(any(
            w["component"] == "financial.current_ratio" and w["code"] == "DETERMINISTIC_CALCULATION_FAILED"
            for w in data["analyzer_warnings"]
        ))
        # Other (unrelated) challenges still made it through.
        self.assertGreater(len(data["items"]), 0)

    def test_k_success_path_has_no_warnings(self):
        def _echo_client(**kwargs):
            up = kwargs["user_prompt"]
            fields = {}
            for line in up.splitlines():
                for key in ("OBSERVATION", "RISK_HYPOTHESIS", "QUESTION"):
                    if line.strip().upper().startswith(key + ":"):
                        fields[key] = line.split(":", 1)[1].strip()
            return (
                f"OBSERVATION: {fields.get('OBSERVATION', '')}\n"
                f"RISK_HYPOTHESIS: {fields.get('RISK_HYPOTHESIS', '')}\n"
                f"QUESTION: {fields.get('QUESTION', '')}"
            )

        with patch("msb_eb_copilot.src.ai_client.AIAssistantClient.chat", side_effect=_echo_client):
            status, data = self._invoke_post("/api/ai_challenge/run", {"case_id": "PSD"})
        self.assertEqual(status, 200)
        self.assertEqual(data["enrichment_status"], "SUCCESS")
        self.assertIsNone(data["enrichment_warning"])
        self.assertEqual(data["analyzer_warnings"], [])

    def test_m_no_secrets_or_provider_internals_in_http_response(self):
        """M. The safe warning metadata must never leak stack traces, provider
        internals, API keys, raw prompts, or request payloads."""
        fake_secret = "sk-LIVE-super-secret-should-never-leak-zzz"
        with patch.dict("os.environ", {"LLM_API_KEY": fake_secret}):
            with patch("msb_eb_copilot.src.ai_client.AIAssistantClient.chat",
                       side_effect=RuntimeError(f"connection reset, key={fake_secret}")):
                status, data = self._invoke_post("/api/ai_challenge/run", {"case_id": "PSD"})
        dumped = json.dumps(data, ensure_ascii=False)
        self.assertNotIn(fake_secret, dumped)
        self.assertNotIn("Traceback", dumped)
        self.assertNotIn("RuntimeError", dumped)
        self.assertNotIn("connection reset", dumped)


class TestMB07GenerationProvenanceIntegration(unittest.TestCase):
    """N: FACT vs RM_EXPLANATION provenance separation for the (read-only,
    non-invasive) MB07 generation context integration point."""

    def setUp(self):
        w.RENEWAL_STORE.clear_case("PSD")
        w.AI_CHALLENGE_STORE.clear_case("PSD")

    def tearDown(self):
        w.RENEWAL_STORE.clear_case("PSD")
        w.AI_CHALLENGE_STORE.clear_case("PSD")

    def test_empty_state_returns_empty_context(self):
        ctx = w.get_mb07_generation_provenance_context("PSD")
        self.assertEqual(ctx["confirmed_renewal_changes"], [])
        self.assertEqual(ctx["rm_explanations"], [])

    def test_challenge_output_can_feed_mb07_generation_context(self):
        with patch("msb_eb_copilot.src.ai_client.AIAssistantClient.chat", side_effect=RuntimeError("offline")):
            challenge_set = w.AIChallengeEngine.generate("PSD", w.CASES_DB["PSD"])
        challenge_set.items[0].mark_answered("RM giải trình: biến động theo mùa vụ kinh doanh.")
        w.AI_CHALLENGE_STORE.set_challenge_set("PSD", challenge_set)

        ctx = w.get_mb07_generation_provenance_context("PSD")
        self.assertEqual(len(ctx["rm_explanations"]), 1)
        self.assertEqual(ctx["rm_explanations"][0]["rm_explanation"], "RM giải trình: biến động theo mùa vụ kinh doanh.")

    def test_confirmed_renewal_changes_are_distinct_from_rm_explanations(self):
        from msb_eb_copilot.src.renewal.change_detection import build_change_set, extract_new_canonical_snapshot
        from msb_eb_copilot.src.renewal.models import RMResolution

        change_set = build_change_set("PSD", old_baseline={}, new_snapshot=extract_new_canonical_snapshot(w.CASES_DB["PSD"]))
        change_set.items[0].rm_resolution = RMResolution.ACCEPT_NEW
        w.RENEWAL_STORE.set_change_set("PSD", change_set)

        ctx = w.get_mb07_generation_provenance_context("PSD")
        self.assertEqual(len(ctx["confirmed_renewal_changes"]), 1)
        self.assertEqual(ctx["confirmed_renewal_changes"][0]["resolution"], "ACCEPT_NEW")
        self.assertEqual(ctx["rm_explanations"], [])  # no challenge answered in this test


class TestExistingDocumentQAStillRunsAfterGeneration(unittest.TestCase):
    """O: Post-generation role remains Document QA -- AI Challenge must never be
    invoked as part of (or instead of) that post-generation check."""

    def test_execute_generation_pipeline_still_calls_document_qa_gate(self):
        with patch("web_copilot_app.run_document_qa_gate", return_value={"overall_status": "PASS"}) as mock_qa, \
             patch("web_copilot_app.CreditProposalAssembler") as mock_assembler_cls, \
             patch("web_copilot_app.DocumentFormatter") as mock_formatter, \
             patch("web_copilot_app.AIChallengeEngine") as mock_challenge_engine:
            mock_assembler = mock_assembler_cls.return_value
            mock_assembler.assemble.return_value = "output/fake_output.docx"
            mock_formatter.polish.return_value = "output/fake_output.docx"

            w.execute_generation_pipeline("PSD")

            mock_qa.assert_called_once()
            # AI Challenge is a PRE-generation gate, never invoked by the
            # generation pipeline itself.
            mock_challenge_engine.generate.assert_not_called()


if __name__ == "__main__":
    unittest.main()

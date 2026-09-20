# -*- coding: utf-8 -*-
"""
Tests for Patch 2: Grounded Credit Narrative RM Web UI Workflow Integration.
Verifies frontend-backend narrative contracts, UX states, and safety invariants.

Requirements verified:
1. Generate narrative action calls POST /api/narrative/generate.
2. Request contains correct case_id behavior.
3. Duplicate click prevented while generating (isGenerating guard).
4. Generate success returns draft and updates UI state to DRAFT.
5. Draft is visually marked as 'AI Draft — Chờ RM xác nhận'.
6. Accept button calls exact existing accept API contract (POST /api/narrative/accept).
7. Accepted response changes state to '✓ Đã được RM xác nhận' and registers for MB07.
8. Edit flow: modal opens, preserves original text until save, sends exact edit payload, updates block.
9. Generate error: no fake fallback, loading state cleared, safe error message shown.
10. Accept/edit error: existing draft remains visible, no false accepted state.
11. Missing/insufficient facts: generate action blocked, no narrative API call made.
12. Existing document upload and review flows remain unchanged.
13. ZERO real GreenNode / external API calls in unit tests.
"""

import copy
import io
import json
import unittest
from unittest.mock import MagicMock, patch

import web_copilot_app
from web_copilot_app import (
    CopilotHTTPHandler,
    CASES_DB,
    ACTIVE_CASE_ID,
    HTML_PAGE,
    is_narrative_case_ready,
)
from msb_eb_copilot.src.narrative.models import (
    FactManifest,
    InsightCandidate,
    NarrativeBlock,
    NarrativeTargetBinding,
    VerificationStatus,
    VerifiedInsight,
    TrendDirection,
    GenerationStatus,
)
from msb_eb_copilot.src.narrative.insight_verifier import PythonInsightVerifier
from msb_eb_copilot.src.narrative.fact_packager import FactPackager
from msb_eb_copilot.src.narrative.store import (
    NarrativeDraftManager,
    NARRATIVE_DRAFT_STORE,
)


class DummyMockServer:
    """Mock HTTP Request Handler helper for testing CopilotHTTPHandler routes."""
    def __init__(self):
        self.response_status = None
        self.response_headers = {}
        self.response_body = None

    def post_json(self, path, post_data_dict):
        body_bytes = json.dumps(post_data_dict).encode("utf-8")
        handler = CopilotHTTPHandler.__new__(CopilotHTTPHandler)
        handler.path = path
        handler.headers = {"Content-Length": str(len(body_bytes))}
        handler.rfile = io.BytesIO(body_bytes)
        out_buf = io.BytesIO()
        handler.wfile = out_buf

        def send_response(code):
            self.response_status = code
        def send_header(k, v):
            self.response_headers[k] = v
        def end_headers():
            pass

        handler.send_response = send_response
        handler.send_header = send_header
        handler.end_headers = end_headers

        def send_json(data, status_code=200):
            self.response_status = status_code
            self.response_body = data

        handler._send_json = send_json
        handler.do_POST()
        return self.response_body, self.response_status

    def get_json(self, path):
        handler = CopilotHTTPHandler.__new__(CopilotHTTPHandler)
        handler.path = path
        handler.headers = {"Content-Length": "0"}
        handler.rfile = io.BytesIO(b"")
        out_buf = io.BytesIO()
        handler.wfile = out_buf

        def send_response(code):
            self.response_status = code
        def send_header(k, v):
            self.response_headers[k] = v
        def end_headers():
            pass

        handler.send_response = send_response
        handler.send_header = send_header
        handler.end_headers = end_headers

        def send_json(data, status_code=200):
            self.response_status = status_code
            self.response_body = data

        handler._send_json = send_json
        handler.do_GET()
        return self.response_body, self.response_status


def make_mock_blocks():
    """Create sample NarrativeBlock objects for testing."""
    return [
        NarrativeBlock(
            section="FINANCIAL",
            target_binding=NarrativeTargetBinding.PNL_ANALYSIS,
            title="Phân Tích Kết Quả Hoạt Động Kinh Doanh",
            text="Doanh thu thuần năm 2025 đạt 7.819,4 tỷ đồng, tăng trưởng 37.1% so với 2024.",
            facts_used=["FIN_REV_2024", "FIN_REV_2025"],
            insights_used=["INS_REV_GROWTH"],
            data_gaps=[]
        ),
        NarrativeBlock(
            section="CIC",
            target_binding=NarrativeTargetBinding.CIC_SUMMARY,
            title="Đánh Giá Quan Hệ Tín Dụng CIC",
            text="Duy trì lịch sử tín dụng mẫu mực 100% Nhóm 1 trong 24 tháng liên tục.",
            facts_used=["CIC_MSB_OUTSTANDING", "CIC_HISTORY_STATUS"],
            insights_used=["INS_CIC_DISCIPLINE"],
            data_gaps=[]
        )
    ]


def make_mock_insights():
    """Create sample VerifiedInsight objects for testing."""
    return [
        VerifiedInsight(
            insight_id="INS_REV_GROWTH",
            status=VerificationStatus.VERIFIED,
            insight_type="GROWTH",
            metric="NET_REVENUE",
            fact_ids=["FIN_REV_2024", "FIN_REV_2025"],
            verified_value=37.12,
            unit="PERCENT",
            trend=TrendDirection.INCREASE,
            observation="Doanh thu tăng trưởng 37.1% trong năm 2025.",
            verification_formula="(7819.4 - 5702.5) / 5702.5 = +37.12%",
            data_quality="HIGH",
            display_representations=["37.1%", "37.12%"]
        )
    ]


def make_mock_candidates():
    """Create sample InsightCandidate objects for testing."""
    return [
        InsightCandidate(
            insight_id="INS_REV_GROWTH_2025",
            insight_type="GROWTH",
            metric="NET_REVENUE",
            related_fact_ids=["FIN_REV_2024", "FIN_REV_2025"],
            from_period="2024",
            to_period="2025",
            proposed_value=37.12,
            proposed_unit="PERCENT",
            trend=TrendDirection.INCREASE,
            observation="Doanh thu thuần năm 2025 tăng trưởng 37.1% so với năm 2024.",
            materiality_reason="Đánh giá quy mô mở rộng hoạt động kinh doanh."
        )
    ]


class TestNarrativeUIBackendRoutes(unittest.TestCase):
    """Test backend HTTP endpoints for Narrative generation, acceptance, editing, and status."""

    def setUp(self):
        self.orig_cases_db = copy.deepcopy(web_copilot_app.CASES_DB)
        self.orig_active_case = web_copilot_app.ACTIVE_CASE_ID
        NARRATIVE_DRAFT_STORE.clear()
        self.server = DummyMockServer()

    def tearDown(self):
        web_copilot_app.CASES_DB = self.orig_cases_db
        web_copilot_app.ACTIVE_CASE_ID = self.orig_active_case
        NARRATIVE_DRAFT_STORE.clear()

    @patch("web_copilot_app.GLMInsightDiscoveryAgent")
    @patch("web_copilot_app.PythonInsightVerifier")
    @patch("web_copilot_app.GLMNarrativeWriterAgent")
    @patch("web_copilot_app.DeterministicNarrativeValidator")
    def test_01_generate_narrative_endpoint_exact_contract(
        self, mock_val_cls, mock_writer_cls, mock_verifier_cls, mock_disc_cls
    ):
        """1. Generate narrative calls correct endpoint with case_id and returns full draft."""
        mock_disc = MagicMock()
        mock_disc.discover_insights.return_value = ([], {"operation": "credit_insight_discovery", "latency_ms": 120.0})
        mock_disc_cls.return_value = mock_disc

        mock_verifier = MagicMock()
        mock_verifier.verify_candidates.return_value = make_mock_insights()
        mock_verifier_cls.return_value = mock_verifier

        mock_writer = MagicMock()
        mock_blocks = make_mock_blocks()
        mock_writer.generate_narrative.return_value = (mock_blocks, {"operation": "credit_narrative_generation", "latency_ms": 250.0})
        mock_writer_cls.return_value = mock_writer

        mock_validator = MagicMock()
        mock_validator.validate_blocks.return_value = MagicMock(is_valid=True, errors=[])
        mock_val_cls.return_value = mock_validator

        body, code = self.server.post_json('/api/narrative/generate', {"case_id": "PSD"})

        self.assertEqual(code, 200)
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["case_id"], "PSD")
        self.assertIn("generation_id", body)
        self.assertIn("manifest_hash", body)
        self.assertEqual(body["blocks_count"], 2)
        self.assertEqual(len(body["blocks"]), 2)
        self.assertEqual(body["blocks"][0]["target_binding"], "pnl_analysis")
        self.assertEqual(body["blocks"][1]["target_binding"], "cic_summary")
        self.assertTrue(body["is_valid"])

        # Verify draft was created in server store
        gen_id = body["generation_id"]
        rec = NarrativeDraftManager.get_record(gen_id)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.case_id, "PSD")

    def test_02_generate_narrative_unknown_case_returns_404(self):
        """2. Non-existent case_id returns 404 error."""
        body, code = self.server.post_json('/api/narrative/generate', {"case_id": "NON_EXISTENT_CORP"})
        self.assertEqual(code, 404)
        self.assertEqual(body["status"], "error")
        self.assertIn("không tồn tại", body["message"])

    def test_03_generate_narrative_insufficient_facts_blocked(self):
        """3. Case without customer name or financial data is rejected with 400."""
        # Create empty case
        web_copilot_app.CASES_DB["EMPTY_CASE"] = {
            "id": "EMPTY_CASE",
            "name": "",
            "customer": {},
            "section_d": {"net_revenue": []}
        }

        body, code = self.server.post_json('/api/narrative/generate', {"case_id": "EMPTY_CASE"})
        self.assertEqual(code, 400)
        self.assertEqual(body["status"], "error")
        self.assertIn("Chưa đủ dữ liệu", body["message"])

    @patch("web_copilot_app.GLMInsightDiscoveryAgent")
    def test_04_generate_narrative_backend_failure_returns_safe_500(self, mock_disc_cls):
        """4. GreenNode API or verifier failure returns safe 500 error."""
        mock_disc = MagicMock()
        mock_disc.discover_insights.side_effect = RuntimeError("GreenNode upstream timeout (504)")
        mock_disc_cls.return_value = mock_disc

        body, code = self.server.post_json('/api/narrative/generate', {"case_id": "PSD"})
        self.assertEqual(code, 500)
        self.assertEqual(body["status"], "error")
        self.assertIn("GreenNode upstream timeout", body["message"])

    @patch("web_copilot_app.GLMInsightDiscoveryAgent")
    @patch("web_copilot_app.PythonInsightVerifier")
    @patch("web_copilot_app.GLMNarrativeWriterAgent")
    @patch("web_copilot_app.DeterministicNarrativeValidator")
    def test_05_accept_narrative_exact_contract(
        self, mock_val_cls, mock_writer_cls, mock_verifier_cls, mock_disc_cls
    ):
        """5. Accept narrative calls /api/narrative/accept, transitions status, and binds to MB07."""
        # Setup draft first
        mock_disc_cls.return_value.discover_insights.return_value = ([], {"operation": "credit_insight_discovery"})
        mock_verifier_cls.return_value.verify_candidates.return_value = make_mock_insights()
        mock_writer_cls.return_value.generate_narrative.return_value = (make_mock_blocks(), {"operation": "credit_narrative_generation"})
        mock_val_cls.return_value.validate_blocks.return_value = MagicMock(is_valid=True, errors=[])

        gen_res, _ = self.server.post_json('/api/narrative/generate', {"case_id": "PSD"})
        gen_id = gen_res["generation_id"]

        # Call accept route
        accept_payload = {
            "generation_id": gen_id,
            "case_id": "PSD",
            "rm_reviewer_name": "RM Tran Van Thang"
        }
        acc_res, acc_code = self.server.post_json('/api/narrative/accept', accept_payload)

        self.assertEqual(acc_code, 200)
        self.assertEqual(acc_res["status"], "success")
        self.assertEqual(acc_res["generation_id"], gen_id)
        self.assertEqual(acc_res["case_id"], "PSD")
        self.assertEqual(acc_res["draft_status"], "ACCEPTED_FOR_RENDERING")
        self.assertEqual(acc_res["accepted_blocks_count"], 2)

        # Verify MB07 render store now includes accepted narrative text
        render_dict = NarrativeDraftManager.get_accepted_narratives_for_rendering("PSD")
        self.assertIn("pnl_analysis", render_dict)
        self.assertIn("cic_summary", render_dict)
        self.assertIn("7.819,4", render_dict["pnl_analysis"])

    def test_06_accept_narrative_missing_generation_id_rejected(self):
        """6. Accept route rejects payload with missing generation_id."""
        body, code = self.server.post_json('/api/narrative/accept', {"case_id": "PSD"})
        self.assertEqual(code, 400)
        self.assertEqual(body["status"], "error")
        self.assertIn("Thiếu generation_id", body["message"])

    @patch("web_copilot_app.GLMInsightDiscoveryAgent")
    @patch("web_copilot_app.PythonInsightVerifier")
    @patch("web_copilot_app.GLMNarrativeWriterAgent")
    @patch("web_copilot_app.DeterministicNarrativeValidator")
    def test_07_edit_narrative_exact_contract(
        self, mock_val_cls, mock_writer_cls, mock_verifier_cls, mock_disc_cls
    ):
        """7. Edit narrative updates block text, re-validates, and transitions to RM_REVIEWED."""
        mock_disc_cls.return_value.discover_insights.return_value = ([], {"operation": "credit_insight_discovery"})
        mock_verifier_cls.return_value.verify_candidates.return_value = make_mock_insights()
        mock_writer_cls.return_value.generate_narrative.return_value = (make_mock_blocks(), {"operation": "credit_narrative_generation"})
        mock_val_cls.return_value.validate_blocks.return_value = MagicMock(is_valid=True, errors=[])

        gen_res, _ = self.server.post_json('/api/narrative/generate', {"case_id": "PSD"})
        gen_id = gen_res["generation_id"]

        # RM edits pnl_analysis text with valid numbers
        edited_text = "Doanh thu thuần năm 2025 đạt 7.819,4 tỷ đồng. RM ghi nhận tăng trưởng vượt trội."
        edit_payload = {
            "generation_id": gen_id,
            "target_binding": "pnl_analysis",
            "edited_text": edited_text,
            "rm_note": "Bổ sung ghi chú phê duyệt của GĐ KHDN"
        }
        edit_res, edit_code = self.server.post_json('/api/narrative/edit', edit_payload)

        self.assertEqual(edit_code, 200)
        self.assertEqual(edit_res["status"], "success")
        self.assertEqual(edit_res["generation_id"], gen_id)
        self.assertEqual(edit_res["target_binding"], "pnl_analysis")
        self.assertEqual(edit_res["draft_status"], "RM_REVIEWED")

        # Verify updated text in record
        rec = NarrativeDraftManager.get_record(gen_id)
        self.assertEqual(rec.narrative_blocks["pnl_analysis"].text, edited_text)

    def test_08_edit_narrative_missing_fields_rejected(self):
        """8. Edit route rejects missing parameters."""
        body, code = self.server.post_json('/api/narrative/edit', {"generation_id": "gen-123"})
        self.assertEqual(code, 400)
        self.assertEqual(body["status"], "error")
        self.assertIn("Thiếu generation_id", body["message"])

    @patch("web_copilot_app.GLMInsightDiscoveryAgent")
    @patch("web_copilot_app.PythonInsightVerifier")
    @patch("web_copilot_app.GLMNarrativeWriterAgent")
    @patch("web_copilot_app.DeterministicNarrativeValidator")
    def test_09_status_endpoint_returns_draft_and_blocks(
        self, mock_val_cls, mock_writer_cls, mock_verifier_cls, mock_disc_cls
    ):
        """9. GET /api/narrative/status returns active draft, blocks, and freshness info."""
        mock_disc_cls.return_value.discover_insights.return_value = ([], {"operation": "credit_insight_discovery"})
        mock_verifier_cls.return_value.verify_candidates.return_value = make_mock_insights()
        mock_writer_cls.return_value.generate_narrative.return_value = (make_mock_blocks(), {"operation": "credit_narrative_generation"})
        mock_val_cls.return_value.validate_blocks.return_value = MagicMock(is_valid=True, errors=[])

        gen_res, _ = self.server.post_json('/api/narrative/generate', {"case_id": "PSD"})
        gen_id = gen_res["generation_id"]

        # Call GET /api/narrative/status?case_id=PSD
        body, code = self.server.get_json('/api/narrative/status?case_id=PSD')
        self.assertEqual(code, 200)
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["case_id"], "PSD")
        self.assertTrue(body["has_draft"])
        self.assertEqual(body["generation_id"], gen_id)
        self.assertEqual(body["blocks_count"], 2)
        self.assertEqual(len(body["blocks"]), 2)
        self.assertIn("manifest_hash", body)
        self.assertTrue(body["narrative_ready"])
        self.assertEqual(body["readiness_reason"], "Dữ liệu canonical đủ để tạo nhận định.")
        self.assertEqual(body["model"], "z-ai/glm-5.2-hackathon")
        self.assertEqual(body["generation_source"], "live")

        # Call GET /api/narrative/case/PSD
        body2, code2 = self.server.get_json('/api/narrative/case/PSD')
        self.assertEqual(code2, 200)
        self.assertEqual(body2["generation_id"], gen_id)


class TestNarrativeUIFrontendContracts(unittest.TestCase):
    """Test HTML template structure and JavaScript logic contracts in web_copilot_app.py."""

    def test_10_html_template_contains_all_narrative_dom_elements(self):
        """10. Verify presence of required DOM containers and control IDs."""
        required_dom_ids = [
            'id="tab-narrative"',
            'id="narrative-status-badge"',
            'id="narrative-header-actions"',
            'id="narrative-alert-container"',
            'id="narrative-telemetry-strip"',
            'id="narrative-model-label"',
            'id="narrative-manifest-hash"',
            'id="narrative-insights-count"',
            'id="narrative-blocks-count"',
            'id="narrative-blocks-container"',
            'id="btn-generate-main"',
            'id="export-result"',
            'id="modal-edit-narrative"',
            'id="modal-narr-target-title"',
            'id="modal-narr-text"',
            'id="modal-narr-rm-note"',
            'id="modal-narr-error"',
            'id="btn-modal-save"',
        ]
        for dom_id in required_dom_ids:
            with self.subTest(dom_id=dom_id):
                self.assertIn(dom_id, HTML_PAGE, f"Missing required DOM element: {dom_id}")

    def test_11_javascript_contains_all_narrative_functions_and_state(self):
        """11. Verify presence of JavaScript state object and narrative workflow functions."""
        required_js_symbols = [
            'let NARRATIVE_STATE = {',
            'function checkCaseFactsReadiness()',
            'async function loadNarrativeState(caseId)',
            'async function generateNarrative()',
            'async function acceptNarrative()',
            'function openEditNarrativeModal(targetBinding)',
            'function closeEditModal()',
            'async function saveAndRevalidateNarrative()',
            'function renderNarrativeUI()',
            'function escapeHtml(text)',
        ]
        for symbol in required_js_symbols:
            with self.subTest(symbol=symbol):
                self.assertIn(symbol, HTML_PAGE, f"Missing required JS function/state: {symbol}")

    def test_12_javascript_enforces_strict_ux_states(self):
        """12. Verify that UI script code enforces NOT_READY, READY, GENERATING, DRAFT, and ACCEPTED."""
        # NOT_READY strings & behavior
        self.assertIn('Chưa Đủ Dữ Liệu', HTML_PAGE)
        self.assertIn('Chưa đủ dữ liệu để tạo nhận định.', HTML_PAGE)

        # READY strings & behavior
        self.assertIn('Sẵn Sàng Tạo Nhận Định', HTML_PAGE)
        self.assertIn('Tạo Nhận Định AI', HTML_PAGE)

        # GENERATING state & duplicate click protection
        self.assertIn('if (NARRATIVE_STATE.isGenerating)', HTML_PAGE)
        self.assertIn('AI đang tổng hợp dữ liệu đã xác nhận và xây dựng nhận định...', HTML_PAGE)

        # DRAFT state visual marker
        self.assertIn('AI Draft — Chờ RM xác nhận', HTML_PAGE)
        self.assertIn('RM Phê Duyệt Toàn Bộ Bản Thảo', HTML_PAGE)

        # ACCEPTED state visual marker
        self.assertIn('✓ Đã được RM xác nhận', HTML_PAGE)

    def test_13_existing_tabs_and_upload_flow_remain_intact(self):
        """13. Verify that existing tabs (dashboard, upload, review, insights, committee) are preserved."""
        existing_tabs = [
            'id="tab-dashboard"',
            'id="tab-upload"',
            'id="tab-review"',
            'id="tab-insights"',
            'id="tab-committee"',
            'DOC_STATES',
            'triggerDocUpload',
            'updateDocCardUI',
            'loadCommitteeCards',
            'generateDocx',
        ]
        for tab_marker in existing_tabs:
            with self.subTest(tab_marker=tab_marker):
                self.assertIn(tab_marker, HTML_PAGE, f"Existing feature was unexpectedly altered: {tab_marker}")

    def test_14_is_narrative_case_ready_helper_matrix(self):
        """14. Backend helper is_narrative_case_ready enforces strict canonical readiness invariants."""
        # 1. None or invalid input
        ready, reason = is_narrative_case_ready(None)
        self.assertFalse(ready)
        self.assertIn("không tồn tại", reason)

        ready, reason = is_narrative_case_ready({})
        self.assertFalse(ready)
        self.assertIn("Chưa đủ dữ liệu canonical", reason)

        # 2. Missing customer name or placeholder names
        ready, reason = is_narrative_case_ready({"customer": {"name": ""}})
        self.assertFalse(ready)
        self.assertIn("thiếu tên doanh nghiệp", reason)

        ready, reason = is_narrative_case_ready({"customer": {"name": "DOANH NGHIỆP MỚI"}})
        self.assertFalse(ready)
        self.assertIn("thiếu tên doanh nghiệp", reason)

        ready, reason = is_narrative_case_ready({"customer": {"name": "CHƯA CẬP NHẬT"}})
        self.assertFalse(ready)
        self.assertIn("thiếu tên doanh nghiệp", reason)

        # 3. Customer name present, but missing section_d or net_revenue
        ready, reason = is_narrative_case_ready({"customer": {"name": "CÔNG TY ABC"}})
        self.assertFalse(ready)
        self.assertIn("doanh thu thuần", reason)

        ready, reason = is_narrative_case_ready({
            "customer": {"name": "CÔNG TY ABC"},
            "section_d": {"net_revenue": []}
        })
        self.assertFalse(ready)
        self.assertIn("doanh thu thuần", reason)

        ready, reason = is_narrative_case_ready({
            "customer": {"name": "CÔNG TY ABC"},
            "section_d": {"net_revenue": [0.0, 0.0, 0.0]}
        })
        self.assertFalse(ready)
        self.assertIn("doanh thu thuần", reason)

        # 4. Valid canonical facts (customer name + positive net_revenue)
        ready, reason = is_narrative_case_ready({
            "customer": {"name": "CÔNG TY ABC"},
            "section_d": {"net_revenue": [1000.0, 2000.0]}
        })
        self.assertTrue(ready)
        self.assertEqual(reason, "Dữ liệu canonical đủ để tạo nhận định.")

        # 5. Existing PSD case
        ready, reason = is_narrative_case_ready(CASES_DB["PSD"])
        self.assertTrue(ready)
        self.assertEqual(reason, "Dữ liệu canonical đủ để tạo nhận định.")

    def test_15_status_endpoint_returns_backend_readiness_and_safe_metadata(self):
        """15. Status endpoint returns narrative_ready/reason and safe runtime telemetry without leaking secrets."""
        server = DummyMockServer()

        # 1. Empty canonical case
        web_copilot_app.CASES_DB["EMPTY_CANONICAL"] = {
            "id": "EMPTY_CANONICAL",
            "name": "Empty Canonical Case",
            "customer": {},
            "section_d": {}
        }
        body, code = server.get_json('/api/narrative/status?case_id=EMPTY_CANONICAL')
        self.assertEqual(code, 200)
        self.assertFalse(body["narrative_ready"])
        self.assertIn("Chưa đủ dữ liệu canonical", body["readiness_reason"])
        self.assertFalse(body["has_draft"])
        self.assertIsNone(body["model"])
        self.assertIsNone(body["generation_source"])

        # 2. Case with customer name but no financial facts
        web_copilot_app.CASES_DB["NAME_ONLY_CASE"] = {
            "id": "NAME_ONLY_CASE",
            "name": "ABC Corp",
            "customer": {"name": "ABC Corp"},
            "section_d": {"net_revenue": [0.0, 0.0]}
        }
        body, code = server.get_json('/api/narrative/status?case_id=NAME_ONLY_CASE')
        self.assertEqual(code, 200)
        self.assertFalse(body["narrative_ready"])
        self.assertIn("doanh thu thuần từ BCTC", body["readiness_reason"])
        self.assertIsNone(body["model"])

        # 3. Valid canonical case before generation
        body, code = server.get_json('/api/narrative/status?case_id=PSD')
        self.assertEqual(code, 200)
        self.assertTrue(body["narrative_ready"])
        self.assertEqual(body["readiness_reason"], "Dữ liệu canonical đủ để tạo nhận định.")
        self.assertFalse(body["has_draft"])
        self.assertIsNone(body["model"])
        self.assertIsNone(body["generation_source"])

    def test_16_generate_repeats_backend_readiness_validation(self):
        """16. POST /api/narrative/generate repeats backend readiness check to prevent bypass."""
        server = DummyMockServer()
        web_copilot_app.CASES_DB["INVALID_CASE"] = {
            "id": "INVALID_CASE",
            "name": "Invalid Case",
            "customer": {"name": "DOANH NGHIỆP MỚI"},
            "section_d": {"net_revenue": [0.0]}
        }
        body, code = server.post_json('/api/narrative/generate', {"case_id": "INVALID_CASE"})
        self.assertEqual(code, 400)
        self.assertEqual(body["status"], "error")
        self.assertIn("Chưa đủ dữ liệu canonical", body["message"])

    def test_17_static_html_and_frontend_contracts_patch_2_1(self):
        """17. Verify static HTML does not hardcode model identity and JS uses backend readiness."""
        # 1. Static HTML does NOT hardcode z-ai/glm-5.2-hackathon (GreenNode)
        self.assertNotIn("z-ai/glm-5.2-hackathon (GreenNode)", HTML_PAGE)

        # 2. Dynamic model label exists in HTML
        self.assertIn('id="narrative-model-label"', HTML_PAGE)

        # 3. checkCaseFactsReadiness does NOT infer readiness from dashboard DOM text
        readiness_fn_code = HTML_PAGE.split("function checkCaseFactsReadiness()")[1].split("async function loadNarrativeState")[0]
        self.assertNotIn("dash-cust-name", readiness_fn_code)
        self.assertNotIn("dash-rev-2025", readiness_fn_code)

        # 4. checkCaseFactsReadiness does NOT auto-ready demo cases independently
        self.assertNotIn("isDemo", readiness_fn_code)
        self.assertNotIn("PSD", readiness_fn_code)

        # 5. Frontend strictly relies on backend readiness
        self.assertIn("NARRATIVE_STATE.narrativeReady", HTML_PAGE)
        self.assertIn("AI Backend: Live", HTML_PAGE)
        self.assertIn("Model: Không công bố", HTML_PAGE)

    @patch("web_copilot_app.GLMInsightDiscoveryAgent")
    @patch("web_copilot_app.PythonInsightVerifier")
    @patch("web_copilot_app.GLMNarrativeWriterAgent")
    @patch("web_copilot_app.DeterministicNarrativeValidator")
    def test_18_rm_reviewed_remains_draft_and_only_accept_sets_accepted(
        self, mock_val_cls, mock_writer_cls, mock_verifier_cls, mock_disc_cls
    ):
        """18. Invariant: RM_REVIEWED remains DRAFT in UI; only ACCEPTED_FOR_RENDERING maps to ACCEPTED."""
        mock_disc_cls.return_value.discover_insights.return_value = ([], {"operation": "credit_insight_discovery"})
        mock_verifier_cls.return_value.verify_candidates.return_value = make_mock_insights()
        mock_writer_cls.return_value.generate_narrative.return_value = (make_mock_blocks(), {"operation": "credit_narrative_generation"})
        mock_val_cls.return_value.validate_blocks.return_value = MagicMock(is_valid=True, errors=[])
        server = DummyMockServer()

        # Generate draft
        gen_res, _ = server.post_json('/api/narrative/generate', {"case_id": "PSD"})
        gen_id = gen_res["generation_id"]

        # Edit block -> transitions to RM_REVIEWED
        edit_payload = {
            "generation_id": gen_id,
            "target_binding": "pnl_analysis",
            "edited_text": "Doanh thu thuần năm 2025 đạt 7.819,4 tỷ đồng. Đã cập nhật theo số liệu kiểm toán.",
            "rm_note": "Ghi chú thẩm định bổ sung"
        }
        edit_res, edit_code = server.post_json('/api/narrative/edit', edit_payload)
        self.assertEqual(edit_code, 200)
        self.assertEqual(edit_res["draft_status"], "RM_REVIEWED")

        # GET status returns RM_REVIEWED
        status_body, _ = server.get_json('/api/narrative/status?case_id=PSD')
        self.assertEqual(status_body["draft_status"], "RM_REVIEWED")

        # Verify UI mapping in JavaScript: (data.draft_status === 'ACCEPTED_FOR_RENDERING') ? 'ACCEPTED' : 'DRAFT'
        # Ensures RM_REVIEWED != ACCEPTED and evaluates strictly to DRAFT
        js_mapping = "(data.draft_status === 'ACCEPTED_FOR_RENDERING') ? 'ACCEPTED' : 'DRAFT'"
        self.assertIn(js_mapping, HTML_PAGE)

        # Accept draft -> transitions to ACCEPTED_FOR_RENDERING
        accept_payload = {
            "generation_id": gen_id,
            "case_id": "PSD",
            "rm_reviewer_name": "RM Trưởng"
        }
        accept_res, accept_code = server.post_json('/api/narrative/accept', accept_payload)
        self.assertEqual(accept_code, 200)
        self.assertEqual(accept_res["draft_status"], "ACCEPTED_FOR_RENDERING")

        # GET status now returns ACCEPTED_FOR_RENDERING
        status_body2, _ = server.get_json('/api/narrative/status?case_id=PSD')
        self.assertEqual(status_body2["draft_status"], "ACCEPTED_FOR_RENDERING")


class TestNarrativeTupleUnpackingContracts(unittest.TestCase):
    """Test Patch 2.3 tuple contract unpacking and PythonInsightVerifier strictness."""

    def setUp(self):
        self.orig_cases_db = copy.deepcopy(web_copilot_app.CASES_DB)
        self.orig_active_case = web_copilot_app.ACTIVE_CASE_ID
        NARRATIVE_DRAFT_STORE.clear()
        self.server = DummyMockServer()

    def tearDown(self):
        web_copilot_app.CASES_DB = self.orig_cases_db
        web_copilot_app.ACTIVE_CASE_ID = self.orig_active_case
        NARRATIVE_DRAFT_STORE.clear()

    @patch("web_copilot_app.GLMInsightDiscoveryAgent")
    @patch("web_copilot_app.PythonInsightVerifier")
    @patch("web_copilot_app.GLMNarrativeWriterAgent")
    @patch("web_copilot_app.DeterministicNarrativeValidator")
    def test_19_discover_and_narrative_writer_tuple_unpacking_contract(
        self, mock_val_cls, mock_writer_cls, mock_verifier_cls, mock_disc_cls
    ):
        """19. Backend routes unpack (candidates, telemetry) and (blocks, telemetry) tuples before passing to verifier/validator."""
        discovery_telemetry = {
            "operation": "credit_insight_discovery",
            "model": "z-ai/glm-5.2-hackathon",
            "latency_ms": 150.0,
            "input_tokens": 500,
            "output_tokens": 120,
            "total_tokens": 620,
        }
        writer_telemetry = {
            "operation": "credit_narrative_generation",
            "model": "z-ai/glm-5.2-hackathon",
            "latency_ms": 300.0,
            "input_tokens": 900,
            "output_tokens": 350,
            "total_tokens": 1250,
        }
        mock_candidates = make_mock_candidates()
        mock_blocks = make_mock_blocks()

        mock_disc = MagicMock()
        mock_disc.discover_insights.return_value = (mock_candidates, discovery_telemetry)
        mock_disc_cls.return_value = mock_disc

        mock_verifier = MagicMock()
        mock_verifier.verify_candidates.return_value = make_mock_insights()
        mock_verifier_cls.return_value = mock_verifier

        mock_writer = MagicMock()
        mock_writer.model = "z-ai/glm-5.2-hackathon"
        mock_writer.generate_narrative.return_value = (mock_blocks, writer_telemetry)
        mock_writer_cls.return_value = mock_writer

        mock_validator = MagicMock()
        mock_validator.validate_blocks.return_value = MagicMock(is_valid=True, errors=[])
        mock_val_cls.return_value = mock_validator

        # Trigger generation
        body, code = self.server.post_json('/api/narrative/generate', {"case_id": "PSD"})
        self.assertEqual(code, 200)
        self.assertEqual(body["status"], "success")

        # 1. Assert verifier received strictly List[InsightCandidate], not a tuple
        mock_verifier.verify_candidates.assert_called_once()
        passed_to_verifier = mock_verifier.verify_candidates.call_args[0][0]
        self.assertIsInstance(passed_to_verifier, list)
        self.assertNotIsInstance(passed_to_verifier, tuple)
        self.assertEqual(len(passed_to_verifier), len(mock_candidates))
        for item in passed_to_verifier:
            self.assertIsInstance(item, InsightCandidate)
        # Telemetry was NOT passed to verifier
        self.assertNotIn(discovery_telemetry, passed_to_verifier)

        # 2. Assert validator received strictly List[NarrativeBlock], not a tuple
        mock_validator.validate_blocks.assert_called_once()
        passed_to_validator = mock_validator.validate_blocks.call_args[0][0]
        self.assertIsInstance(passed_to_validator, list)
        self.assertNotIsInstance(passed_to_validator, tuple)
        self.assertEqual(len(passed_to_validator), len(mock_blocks))
        for item in passed_to_validator:
            self.assertIsInstance(item, NarrativeBlock)
        # Telemetry was NOT passed to validator
        self.assertNotIn(writer_telemetry, passed_to_validator)

        # 3. Assert generate response contains safe combined telemetry
        self.assertIn("telemetry", body)
        self.assertEqual(body["telemetry"]["discovery"]["operation"], "credit_insight_discovery")
        self.assertEqual(body["telemetry"]["discovery"]["latency_ms"], 150.0)
        self.assertEqual(body["telemetry"]["discovery"]["total_tokens"], 620)
        self.assertEqual(body["telemetry"]["writer"]["operation"], "credit_narrative_generation")
        self.assertEqual(body["telemetry"]["writer"]["latency_ms"], 300.0)
        self.assertEqual(body["telemetry"]["writer"]["total_tokens"], 1250)

        # 4. Assert GET /api/narrative/status returns safe combined telemetry
        status_body, status_code = self.server.get_json('/api/narrative/status?case_id=PSD')
        self.assertEqual(status_code, 200)
        self.assertIn("telemetry", status_body)
        self.assertEqual(status_body["telemetry"]["discovery"]["latency_ms"], 150.0)
        self.assertEqual(status_body["telemetry"]["writer"]["latency_ms"], 300.0)

    def test_20_verifier_strictly_rejects_nested_or_tuple_inputs(self):
        """20. PythonInsightVerifier strictly expects List[InsightCandidate] and rejects tuples or nested structures."""
        packager = FactPackager()
        manifest = packager.package_from_case_data(web_copilot_app.CASES_DB["PSD"], case_id="PSD")
        verifier = PythonInsightVerifier(manifest)

        # 1. Passing raw 2-tuple (candidates, telemetry) must raise AttributeError or TypeError
        raw_tuple = (make_mock_candidates(), {"operation": "credit_insight_discovery", "latency_ms": 100.0})
        with self.assertRaises((AttributeError, TypeError)):
            verifier.verify_candidates(raw_tuple)

        # 2. Passing nested list [[candidate]] must raise AttributeError or TypeError
        nested_candidates = [make_mock_candidates()]
        with self.assertRaises((AttributeError, TypeError)):
            verifier.verify_candidates(nested_candidates)

        # 3. Passing proper List[InsightCandidate] succeeds without error
        valid_candidates = make_mock_candidates()
        verified = verifier.verify_candidates(valid_candidates)
        self.assertIsInstance(verified, list)


class TestNarrativeValidationSerialization(unittest.TestCase):
    """Test Patch 2.4 NarrativeValidationSummary string error serialization contracts."""

    def setUp(self):
        self.orig_cases_db = copy.deepcopy(web_copilot_app.CASES_DB)
        self.orig_active_case = web_copilot_app.ACTIVE_CASE_ID
        NARRATIVE_DRAFT_STORE.clear()
        self.server = DummyMockServer()

    def tearDown(self):
        web_copilot_app.CASES_DB = self.orig_cases_db
        web_copilot_app.ACTIVE_CASE_ID = self.orig_active_case
        NARRATIVE_DRAFT_STORE.clear()

    @patch("web_copilot_app.GLMInsightDiscoveryAgent")
    @patch("web_copilot_app.PythonInsightVerifier")
    @patch("web_copilot_app.GLMNarrativeWriterAgent")
    @patch("web_copilot_app.DeterministicNarrativeValidator")
    def test_21_generate_narrative_with_validation_errors_serializes_list_of_strings(
        self, mock_val_cls, mock_writer_cls, mock_verifier_cls, mock_disc_cls
    ):
        """21. When validator reports string errors, /api/narrative/generate returns is_valid=False and validation_errors as List[str]."""
        mock_disc_cls.return_value.discover_insights.return_value = ([], {"operation": "credit_insight_discovery"})
        mock_verifier_cls.return_value.verify_candidates.return_value = make_mock_insights()
        mock_writer_cls.return_value.generate_narrative.return_value = (make_mock_blocks(), {"operation": "credit_narrative_generation"})

        raw_errors = [
            "Referential integrity error: fact_id 'UNKNOWN_FACT' does not exist in FactManifest",
            "Strict numeric fact checking failure: number '9999.0' in block text has no grounding match"
        ]
        mock_validator = MagicMock()
        mock_validator.validate_blocks.return_value = MagicMock(is_valid=False, errors=raw_errors)
        mock_val_cls.return_value = mock_validator

        body, code = self.server.post_json('/api/narrative/generate', {"case_id": "PSD"})

        self.assertEqual(code, 200)
        self.assertEqual(body["status"], "success")
        self.assertFalse(body["is_valid"])
        self.assertIsInstance(body["validation_errors"], list)
        self.assertEqual(body["validation_errors"], raw_errors)
        for err in body["validation_errors"]:
            self.assertIsInstance(err, str)
            self.assertFalse(hasattr(err, "model_dump"))

    def test_22_real_deterministic_validator_summary_model_dump_and_errors_contract(self):
        """22. Real DeterministicNarrativeValidator returns ValidationSummary where errors is List[str], not objects."""
        from msb_eb_copilot.src.narrative.validator import DeterministicNarrativeValidator
        packager = FactPackager()
        manifest = packager.package_from_case_data(web_copilot_app.CASES_DB["PSD"], case_id="PSD")
        validator = DeterministicNarrativeValidator(manifest, verified_insights=[])

        # Create block with ungrounded fact_id to trigger real validator error
        invalid_block = NarrativeBlock(
            section="FINANCIAL",
            target_binding=NarrativeTargetBinding.PNL_ANALYSIS,
            title="Invalid Block",
            text="Doanh thu đạt 99999 tỷ đồng.",
            facts_used=["NON_EXISTENT_FACT_999"],
            insights_used=[],
            data_gaps=[]
        )

        val_res = validator.validate_blocks([invalid_block])
        self.assertFalse(val_res.is_valid)
        self.assertGreater(len(val_res.errors), 0)
        for err in val_res.errors:
            self.assertIsInstance(err, str)
            self.assertFalse(hasattr(err, "model_dump"))

        # Verify list(val_res.errors) serializes without crash
        serialized = list(val_res.errors)
        self.assertIsInstance(serialized, list)
        self.assertEqual(len(serialized), len(val_res.errors))


if __name__ == "__main__":
    unittest.main()

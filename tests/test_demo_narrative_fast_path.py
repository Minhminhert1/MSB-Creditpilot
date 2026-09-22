# -*- coding: utf-8 -*-
"""Tests for the demo Narrative fast path (hackathon-only precomputed snapshots).

Scope: /api/narrative/generate (and /api/narrative/status, /edit, /accept)
must transparently reuse a precomputed narrative for a preloaded demo case
(PSD, GAS_SOUTH, PHYTOPHARMA) ONLY when:
  1. case_data["_is_preloaded_demo"] is True (explicit flag, never inferred), AND
  2. the CURRENT FactManifest hash (recomputed fresh from live canonical
     case_data on every request) matches the snapshot's source_manifest_hash.

Any other case, or a demo case whose facts changed, must run the existing
live pipeline completely unchanged (GLMInsightDiscoveryAgent ->
PythonInsightVerifier -> GLMNarrativeWriterAgent -> DeterministicNarrativeValidator).

No real GreenNode/GLM calls are made anywhere in this file -- the live-path
tests mock the same agent classes web_copilot_app.py imports, exactly like
tests/test_narrative_ui_flow.py already does.
"""

import copy
import io
import json
import unittest
from unittest.mock import MagicMock, patch

import web_copilot_app
from web_copilot_app import CopilotHTTPHandler, CASES_DB
from msb_eb_copilot.src.demo_narrative_cache import (
    DemoNarrativeSnapshot,
    get_valid_demo_snapshot,
    is_preloaded_demo_case,
)
from msb_eb_copilot.src.narrative.fact_packager import FactPackager
from msb_eb_copilot.src.narrative.models import (
    NarrativeBlock,
    NarrativeTargetBinding,
    VerifiedInsight,
    VerificationStatus,
    TrendDirection,
)
from msb_eb_copilot.src.narrative.store import NarrativeDraftManager, NARRATIVE_DRAFT_STORE
from msb_eb_copilot.src.ai_client import AIAssistantClient


class DummyMockServer:
    """Mirrors the harness already used in tests/test_narrative_ui_flow.py."""

    def __init__(self):
        self.response_status = None
        self.response_body = None

    def post_json(self, path, post_data_dict):
        body_bytes = json.dumps(post_data_dict).encode("utf-8")
        handler = CopilotHTTPHandler.__new__(CopilotHTTPHandler)
        handler.path = path
        handler.headers = {"Content-Length": str(len(body_bytes))}
        handler.rfile = io.BytesIO(body_bytes)
        handler.wfile = io.BytesIO()
        handler.send_response = lambda code: None
        handler.send_header = lambda k, v: None
        handler.end_headers = lambda: None

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
        handler.wfile = io.BytesIO()
        handler.send_response = lambda code: None
        handler.send_header = lambda k, v: None
        handler.end_headers = lambda: None

        def send_json(data, status_code=200):
            self.response_status = status_code
            self.response_body = data

        handler._send_json = send_json
        handler.do_GET()
        return self.response_body, self.response_status


def _make_block(fact_id: str, text: str, binding=NarrativeTargetBinding.BUSINESS_OVERVIEW) -> NarrativeBlock:
    return NarrativeBlock(
        section="BUSINESS",
        target_binding=binding,
        title="Tổng quan doanh nghiệp",
        text=text,
        facts_used=[fact_id],
        insights_used=[],
        data_gaps=[],
    )


def _snapshot_for(case_id: str, fact_id: str, text: str) -> DemoNarrativeSnapshot:
    """Builds a DemoNarrativeSnapshot whose source_manifest_hash matches the
    CURRENT (real) canonical case_data for case_id, using only a genuine
    fact_id that FactPackager actually produced for that case -- never a
    fabricated fact."""
    manifest = FactPackager.package_from_case_data(CASES_DB[case_id], case_id=case_id)
    assert manifest.get_fact(fact_id) is not None, f"test setup error: {fact_id} not a real fact for {case_id}"
    return DemoNarrativeSnapshot(
        case_id=case_id,
        source_manifest_hash=manifest.manifest_hash,
        model_id="z-ai/glm-5.2-hackathon",
        narrative_blocks=[_make_block(fact_id, text)],
        verified_insights=[],
    )


class DemoNarrativeFastPathTests(unittest.TestCase):
    def setUp(self):
        self.orig_cases_db = copy.deepcopy(web_copilot_app.CASES_DB)
        self.orig_active_case = web_copilot_app.ACTIVE_CASE_ID
        NARRATIVE_DRAFT_STORE.clear()
        self.server = DummyMockServer()

    def tearDown(self):
        web_copilot_app.CASES_DB = self.orig_cases_db
        web_copilot_app.ACTIVE_CASE_ID = self.orig_active_case
        NARRATIVE_DRAFT_STORE.clear()

    def _patched_snapshots(self, snapshots_by_case):
        return patch.dict(
            "msb_eb_copilot.src.demo_narrative_cache.DEMO_NARRATIVE_SNAPSHOTS",
            snapshots_by_case,
            clear=True,
        )

    # ------------------------------------------------------------------
    # A. Preloaded demo + matching manifest hash -> DEMO_PRECOMPUTED
    # ------------------------------------------------------------------
    def test_a_matching_snapshot_uses_demo_precomputed(self):
        snap = _snapshot_for("PSD", "LEGAL_NAME", "Doanh nghiệp có tên đầy đủ là CÔNG TY CỔ PHẦN PHÂN PHỐI DEMO.")
        with self._patched_snapshots({"PSD": snap}):
            body, status = self.server.post_json("/api/narrative/generate", {"case_id": "PSD"})

        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["execution_mode"], "DEMO_PRECOMPUTED")
        self.assertEqual(body["generation_source"], "demo_precomputed")
        self.assertEqual(body["manifest_hash"], snap.source_manifest_hash)
        self.assertTrue(body["is_valid"])
        self.assertEqual(body["validation_errors"], [])

    # ------------------------------------------------------------------
    # B. Demo response never invokes the GLM client
    # ------------------------------------------------------------------
    def test_b_demo_path_never_calls_glm_client(self):
        snap = _snapshot_for("PSD", "LEGAL_NAME", "Doanh nghiệp có tên đầy đủ là CÔNG TY CỔ PHẦN PHÂN PHỐI DEMO.")
        with self._patched_snapshots({"PSD": snap}), \
             patch.object(AIAssistantClient, "chat", side_effect=AssertionError("GLM must never be called on the demo fast path")) as mock_chat:
            body, status = self.server.post_json("/api/narrative/generate", {"case_id": "PSD"})

        self.assertEqual(status, 200)
        self.assertEqual(body["execution_mode"], "DEMO_PRECOMPUTED")
        mock_chat.assert_not_called()

    # ------------------------------------------------------------------
    # C. Demo response conforms to the existing Narrative API contract
    # ------------------------------------------------------------------
    def test_c_demo_response_matches_live_response_contract(self):
        snap = _snapshot_for("PSD", "LEGAL_NAME", "Doanh nghiệp có tên đầy đủ là CÔNG TY CỔ PHẦN PHÂN PHỐI DEMO.")
        with self._patched_snapshots({"PSD": snap}):
            body, status = self.server.post_json("/api/narrative/generate", {"case_id": "PSD"})
        self.assertEqual(status, 200)

        expected_keys = {
            "status", "case_id", "generation_id", "manifest_hash", "model",
            "generation_source", "execution_mode", "telemetry",
            "verified_insights_count", "blocks_count", "is_valid",
            "validation_errors", "blocks", "verified_insights",
        }
        self.assertEqual(expected_keys, set(body.keys()))
        self.assertIsInstance(body["blocks"], list)
        self.assertIsInstance(body["verified_insights"], list)
        self.assertIn("target_binding", body["blocks"][0])
        self.assertIn("facts_used", body["blocks"][0])

    # ------------------------------------------------------------------
    # D. Demo canonical fact changed -> snapshot rejected -> LIVE_AI path
    # ------------------------------------------------------------------
    @patch("web_copilot_app.GLMInsightDiscoveryAgent")
    @patch("web_copilot_app.PythonInsightVerifier")
    @patch("web_copilot_app.GLMNarrativeWriterAgent")
    @patch("web_copilot_app.DeterministicNarrativeValidator")
    def test_d_stale_snapshot_falls_back_to_live(self, mock_val_cls, mock_writer_cls, mock_verifier_cls, mock_disc_cls):
        snap = _snapshot_for("PSD", "LEGAL_NAME", "Doanh nghiệp có tên đầy đủ là CÔNG TY CỔ PHẦN PHÂN PHỐI DEMO.")

        # Mutate a canonical fact AFTER the snapshot was built -- this changes
        # the live manifest hash, so the (now stale) snapshot must be rejected.
        web_copilot_app.CASES_DB["PSD"]["section_d"]["net_revenue"][-1] = 999999999.0

        mock_disc_cls.return_value.discover_insights.return_value = ([], {})
        mock_verifier_cls.return_value.verify_candidates.return_value = []
        mock_writer_cls.return_value.generate_narrative.return_value = ([], {})
        mock_writer_cls.return_value.model = "z-ai/glm-5.2-hackathon"
        mock_val_cls.return_value.validate_blocks.return_value = MagicMock(is_valid=True, errors=[])

        with self._patched_snapshots({"PSD": snap}):
            body, status = self.server.post_json("/api/narrative/generate", {"case_id": "PSD"})

        self.assertEqual(status, 200)
        self.assertEqual(body["execution_mode"], "LIVE_AI")
        self.assertEqual(body["generation_source"], "live")
        self.assertNotEqual(body["manifest_hash"], snap.source_manifest_hash)
        mock_disc_cls.return_value.discover_insights.assert_called_once()
        mock_writer_cls.return_value.generate_narrative.assert_called_once()

    # ------------------------------------------------------------------
    # E. A real (non-demo) case always uses LIVE_AI
    # ------------------------------------------------------------------
    @patch("web_copilot_app.GLMInsightDiscoveryAgent")
    @patch("web_copilot_app.PythonInsightVerifier")
    @patch("web_copilot_app.GLMNarrativeWriterAgent")
    @patch("web_copilot_app.DeterministicNarrativeValidator")
    def test_e_real_case_always_uses_live(self, mock_val_cls, mock_writer_cls, mock_verifier_cls, mock_disc_cls):
        real_case_id = "REAL_TEST_CASE"
        web_copilot_app.CASES_DB[real_case_id] = copy.deepcopy(CASES_DB["PSD"])
        web_copilot_app.CASES_DB[real_case_id]["id"] = real_case_id
        web_copilot_app.CASES_DB[real_case_id].pop("_is_preloaded_demo", None)
        self.assertFalse(is_preloaded_demo_case(web_copilot_app.CASES_DB[real_case_id]))

        mock_disc_cls.return_value.discover_insights.return_value = ([], {})
        mock_verifier_cls.return_value.verify_candidates.return_value = []
        mock_writer_cls.return_value.generate_narrative.return_value = ([], {})
        mock_writer_cls.return_value.model = "z-ai/glm-5.2-hackathon"
        mock_val_cls.return_value.validate_blocks.return_value = MagicMock(is_valid=True, errors=[])

        body, status = self.server.post_json("/api/narrative/generate", {"case_id": real_case_id})

        self.assertEqual(status, 200)
        self.assertEqual(body["execution_mode"], "LIVE_AI")
        mock_disc_cls.return_value.discover_insights.assert_called_once()

    # ------------------------------------------------------------------
    # F. Each demo case uses only its OWN snapshot
    # ------------------------------------------------------------------
    def test_f_psd_and_gas_south_each_use_their_own_snapshot(self):
        psd_snap = _snapshot_for("PSD", "LEGAL_NAME", "Doanh nghiệp có tên đầy đủ là CÔNG TY CỔ PHẦN PHÂN PHỐI DEMO.")
        gas_snap = _snapshot_for("GAS_SOUTH", "LEGAL_NAME", "Doanh nghiệp có tên đầy đủ là CÔNG TY CỔ PHẦN KINH DOANH KHÍ MIỀN NAM.")

        with self._patched_snapshots({"PSD": psd_snap, "GAS_SOUTH": gas_snap}):
            psd_body, psd_status = self.server.post_json("/api/narrative/generate", {"case_id": "PSD"})
            gas_body, gas_status = self.server.post_json("/api/narrative/generate", {"case_id": "GAS_SOUTH"})

        self.assertEqual(psd_status, 200)
        self.assertEqual(gas_status, 200)
        self.assertEqual(psd_body["execution_mode"], "DEMO_PRECOMPUTED")
        self.assertEqual(gas_body["execution_mode"], "DEMO_PRECOMPUTED")
        self.assertIn("PHÂN PHỐI DEMO", psd_body["blocks"][0]["text"])
        self.assertIn("KHÍ MIỀN NAM", gas_body["blocks"][0]["text"])
        self.assertNotIn("KHÍ MIỀN NAM", psd_body["blocks"][0]["text"])

    # ------------------------------------------------------------------
    # G. A snapshot from one case can never be used by another case
    # ------------------------------------------------------------------
    def test_g_mismatched_snapshot_case_id_is_never_used(self):
        real_psd_manifest = FactPackager.package_from_case_data(CASES_DB["PSD"], case_id="PSD")
        # Deliberately malformed: stored under key "GAS_SOUTH" but its own
        # case_id field says "PSD" -- must never be usable for either case.
        mismatched = DemoNarrativeSnapshot(
            case_id="PSD",
            source_manifest_hash=real_psd_manifest.manifest_hash,
            model_id="z-ai/glm-5.2-hackathon",
            narrative_blocks=[_make_block("LEGAL_NAME", "Doanh nghiệp có tên đầy đủ là CÔNG TY CỔ PHẦN PHÂN PHỐI DEMO.")],
            verified_insights=[],
        )
        with self._patched_snapshots({"GAS_SOUTH": mismatched}):
            gas_manifest = FactPackager.package_from_case_data(CASES_DB["GAS_SOUTH"], case_id="GAS_SOUTH")
            result = get_valid_demo_snapshot("GAS_SOUTH", CASES_DB["GAS_SOUTH"], gas_manifest.manifest_hash)
            self.assertIsNone(result)

    # ------------------------------------------------------------------
    # H. Cross-case security remains intact: fast-path records still carry
    # the correct case_id ownership.
    # ------------------------------------------------------------------
    def test_h_demo_precomputed_record_has_correct_case_id_ownership(self):
        snap = _snapshot_for("PSD", "LEGAL_NAME", "Doanh nghiệp có tên đầy đủ là CÔNG TY CỔ PHẦN PHÂN PHỐI DEMO.")
        with self._patched_snapshots({"PSD": snap}):
            body, _ = self.server.post_json("/api/narrative/generate", {"case_id": "PSD"})

        rec = NarrativeDraftManager.get_record(body["generation_id"])
        self.assertIsNotNone(rec)
        self.assertEqual(rec.case_id, "PSD")

    # ------------------------------------------------------------------
    # I. Generated MB07 rendering path works from a precomputed narrative
    # ------------------------------------------------------------------
    def test_i_accepted_demo_narrative_is_available_for_mb07_rendering(self):
        snap = _snapshot_for("PSD", "LEGAL_NAME", "Doanh nghiệp có tên đầy đủ là CÔNG TY CỔ PHẦN PHÂN PHỐI DEMO.")
        with self._patched_snapshots({"PSD": snap}):
            gen_body, _ = self.server.post_json("/api/narrative/generate", {"case_id": "PSD"})
            accept_body, accept_status = self.server.post_json(
                "/api/narrative/accept", {"generation_id": gen_body["generation_id"], "case_id": "PSD"}
            )

        self.assertEqual(accept_status, 200)
        self.assertEqual(accept_body["status"], "success")

        rendered = NarrativeDraftManager.get_accepted_narratives_for_rendering("PSD")
        self.assertIn("business_overview", rendered)
        self.assertIn("CÔNG TY CỔ PHẦN PHÂN PHỐI DEMO", rendered["business_overview"])

    # ------------------------------------------------------------------
    # J. Narrative editing / acceptance still works on a demo-precomputed draft
    # ------------------------------------------------------------------
    def test_j_editing_a_demo_precomputed_draft_still_works(self):
        snap = _snapshot_for("PSD", "LEGAL_NAME", "Doanh nghiệp có tên đầy đủ là CÔNG TY CỔ PHẦN PHÂN PHỐI DEMO.")
        with self._patched_snapshots({"PSD": snap}):
            gen_body, _ = self.server.post_json("/api/narrative/generate", {"case_id": "PSD"})

            edited_text = "Doanh nghiệp có tên đầy đủ là CÔNG TY CỔ PHẦN PHÂN PHỐI DEMO, hoạt động trong lĩnh vực phân phối."
            edit_body, edit_status = self.server.post_json("/api/narrative/edit", {
                "generation_id": gen_body["generation_id"],
                "target_binding": "business_overview",
                "edited_text": edited_text,
            })

        self.assertEqual(edit_status, 200)
        self.assertEqual(edit_body["status"], "success")
        rec = NarrativeDraftManager.get_record(gen_body["generation_id"])
        self.assertEqual(rec.narrative_blocks["business_overview"].text, edited_text)

    # ------------------------------------------------------------------
    # K. FactManifest SHA verification (stale-manifest protection) still works
    # ------------------------------------------------------------------
    def test_k_stale_manifest_protection_still_applies_after_demo_generation(self):
        snap = _snapshot_for("PSD", "LEGAL_NAME", "Doanh nghiệp có tên đầy đủ là CÔNG TY CỔ PHẦN PHÂN PHỐI DEMO.")
        with self._patched_snapshots({"PSD": snap}):
            gen_body, _ = self.server.post_json("/api/narrative/generate", {"case_id": "PSD"})

        # Canonical facts change AFTER the demo-precomputed draft was created.
        web_copilot_app.CASES_DB["PSD"]["section_d"]["net_revenue"][-1] = 111111111.0

        accept_body, accept_status = self.server.post_json(
            "/api/narrative/accept", {"generation_id": gen_body["generation_id"], "case_id": "PSD"}
        )
        self.assertEqual(accept_status, 400)
        self.assertEqual(accept_body["status"], "error")

    # ------------------------------------------------------------------
    # L. No fabricated facts: snapshot narrative can only reference real
    # canonical fact_ids, and the response never claims anything the manifest
    # doesn't actually contain.
    # ------------------------------------------------------------------
    def test_l_snapshot_referencing_unknown_fact_id_fails_validation(self):
        manifest = FactPackager.package_from_case_data(CASES_DB["PSD"], case_id="PSD")
        fabricated = DemoNarrativeSnapshot(
            case_id="PSD",
            source_manifest_hash=manifest.manifest_hash,
            model_id="z-ai/glm-5.2-hackathon",
            narrative_blocks=[_make_block("FICTIONAL_FACT_DOES_NOT_EXIST", "Doanh thu tăng vọt 999% nhờ phép màu.")],
            verified_insights=[],
        )
        with self._patched_snapshots({"PSD": fabricated}):
            body, status = self.server.post_json("/api/narrative/generate", {"case_id": "PSD"})

        self.assertEqual(status, 200)
        self.assertEqual(body["execution_mode"], "DEMO_PRECOMPUTED")
        self.assertFalse(body["is_valid"])
        self.assertTrue(any("does not exist in FactManifest" in e for e in body["validation_errors"]))


class DemoNarrativeConfigTests(unittest.TestCase):
    """Section 9 (from Bug 3) style config/data-integrity checks specific to
    this feature."""

    def test_all_preloaded_demo_cases_are_explicitly_flagged(self):
        for case_id in ("PSD", "GAS_SOUTH", "PHYTOPHARMA"):
            self.assertTrue(is_preloaded_demo_case(CASES_DB[case_id]), f"{case_id} missing _is_preloaded_demo flag")

    def test_new_case_created_via_api_is_never_flagged_as_demo(self):
        fresh_case = {"id": "SOME_NEW_CASE", "name": "x", "customer": {}}
        self.assertFalse(is_preloaded_demo_case(fresh_case))

    def test_is_preloaded_demo_case_rejects_falsy_and_missing_flag(self):
        self.assertFalse(is_preloaded_demo_case(None))
        self.assertFalse(is_preloaded_demo_case({}))
        self.assertFalse(is_preloaded_demo_case({"_is_preloaded_demo": False}))
        self.assertFalse(is_preloaded_demo_case({"_is_preloaded_demo": "true"}))  # must be the literal bool True


class DemoNarrativePerformanceTests(unittest.TestCase):
    """Section 13: snapshot retrieval performs only local deterministic
    operations and never invokes external AI. Avoids fragile wall-clock
    assertions; instead asserts the AI client call count directly."""

    def setUp(self):
        NARRATIVE_DRAFT_STORE.clear()

    def tearDown(self):
        NARRATIVE_DRAFT_STORE.clear()

    def test_repeated_demo_requests_never_call_ai_client(self):
        manifest = FactPackager.package_from_case_data(CASES_DB["PSD"], case_id="PSD")
        snap = DemoNarrativeSnapshot(
            case_id="PSD",
            source_manifest_hash=manifest.manifest_hash,
            model_id="z-ai/glm-5.2-hackathon",
            narrative_blocks=[_make_block("LEGAL_NAME", "Doanh nghiệp có tên đầy đủ là CÔNG TY CỔ PHẦN PHÂN PHỐI DEMO.")],
            verified_insights=[],
        )
        server = DummyMockServer()
        with patch.dict(
            "msb_eb_copilot.src.demo_narrative_cache.DEMO_NARRATIVE_SNAPSHOTS",
            {"PSD": snap},
            clear=True,
        ), patch.object(AIAssistantClient, "chat", side_effect=AssertionError("must not call AI")) as mock_chat:
            for _ in range(10):
                body, status = server.post_json("/api/narrative/generate", {"case_id": "PSD"})
                self.assertEqual(status, 200)
                self.assertEqual(body["execution_mode"], "DEMO_PRECOMPUTED")

        mock_chat.assert_not_called()


if __name__ == "__main__":
    unittest.main()

# -*- coding: utf-8 -*-
"""Tests for the Phase 1 GreenNode-powered Document QA Agent (document_qa_agent.py).

Covers:
1. Deterministic PASS on an authoritative-compatible DOCX.
2. Missing image/logo relationship -> FAIL.
3. Changed section geometry -> FAIL.
4. Corrupted DOCX package -> FAIL.
5. GreenNode visual QA mocked PASS (full orchestrator, no network calls).
6. GreenNode visual QA mocked FAIL (full orchestrator, no network calls).
7. Malformed GreenNode JSON -> fail closed (unit-level, mocked OpenAI client).
8. GreenNode API exception -> fail closed (unit-level, mocked OpenAI client).
9. No real network/API calls anywhere in this file.

AI is a REVIEWER ONLY: none of these tests assert or allow any DOCX mutation by the
vision agent.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import unittest
import zipfile
from unittest.mock import MagicMock, patch

import docx
from docx.shared import Pt

from msb_eb_copilot.src.document_qa_agent import (
    DocumentQAAgent,
    DocumentQAFailedError,
    DocxPageRenderer,
    GreenNodeVisionQAError,
    GreenNodeVisualQAAgent,
    STATUS_FAIL,
    STATUS_PASS,
    STATUS_VISUAL_QA_UNAVAILABLE,
    run_deterministic_checks,
    run_document_qa_gate,
)


def _authoritative_template_path() -> str:
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(
        base_dir, "MB07 Tờ trình đề xuất cấp tín dụng (ĐVKD) - thực hiện rà soát - tái cấp.docx"
    )
    assert os.path.exists(path), f"MB07 authoritative template not found at {path}"
    return path


def _strip_image_relationship(src_path: str, dst_path: str) -> None:
    """Writes a copy of src_path with all 'image' relationships stripped from
    word/_rels/document.xml.rels, simulating a lost logo relationship."""
    with zipfile.ZipFile(src_path, "r") as zin:
        rels_xml = zin.read("word/_rels/document.xml.rels").decode("utf-8")

    stripped_rels_xml = re.sub(r"<Relationship[^>]*Type=\"[^\"]*/image\"[^>]*/>", "", rels_xml)
    assert stripped_rels_xml != rels_xml, "Test setup failed: no image relationship found to strip."

    with zipfile.ZipFile(src_path, "r") as zin, zipfile.ZipFile(dst_path, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/_rels/document.xml.rels":
                data = stripped_rels_xml.encode("utf-8")
            zout.writestr(item, data)


class _FakeRenderer(DocxPageRenderer):
    """Test double: never invokes LibreOffice; produces one tiny placeholder PNG per call."""

    @classmethod
    def is_available(cls) -> bool:
        return True

    @classmethod
    def render_to_page_images(cls, docx_path, out_dir, dpi=150, max_pages=None, timeout=120.0):
        os.makedirs(out_dir, exist_ok=True)
        img_path = os.path.join(out_dir, "page_1.png")
        with open(img_path, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n\x00\x00\x00\x00")
        return [img_path]


class _UnavailableRenderer(DocxPageRenderer):
    @classmethod
    def is_available(cls) -> bool:
        return False


class _FakeVisionAgent:
    """Test double standing in for GreenNodeVisualQAAgent: no network calls."""

    model = "fake/qwen3.6-flash-stub"

    def __init__(self, page_result=None, raise_error=None):
        self._page_result = page_result
        self._raise_error = raise_error

    def compare_page(self, template_b64_png, generated_b64_png, page_num):
        if self._raise_error is not None:
            raise self._raise_error
        return self._page_result


class TestDeterministicDocumentQA(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template_path = _authoritative_template_path()

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_01_deterministic_pass_on_authoritative_compatible_docx(self):
        candidate = os.path.join(self.temp_dir, "compatible.docx")
        shutil.copyfile(self.template_path, candidate)

        checks, issues, all_passed = run_deterministic_checks(candidate, template_path=self.template_path)

        self.assertTrue(all_passed, msg=f"Expected all deterministic checks to pass, issues={issues}")
        self.assertEqual(checks["docx_opens"], STATUS_PASS)
        self.assertEqual(checks["package_integrity"], STATUS_PASS)
        self.assertEqual(checks["section_count_preserved"], STATUS_PASS)
        self.assertEqual(checks["header_footer_relationships_present"], STATUS_PASS)
        self.assertEqual(checks["image_logo_relationships_preserved"], STATUS_PASS)
        self.assertEqual(checks["table_count_structurally_compatible"], STATUS_PASS)
        self.assertEqual(checks["section_orientation_margins_preserved"], STATUS_PASS)
        self.assertEqual(issues, [])

    def test_02_missing_image_logo_relationship_fails(self):
        candidate = os.path.join(self.temp_dir, "no_logo.docx")
        _strip_image_relationship(self.template_path, candidate)

        checks, issues, all_passed = run_deterministic_checks(candidate, template_path=self.template_path)

        self.assertFalse(all_passed)
        self.assertEqual(checks["image_logo_relationships_preserved"], STATUS_FAIL)
        self.assertTrue(any("image" in i.lower() or "logo" in i.lower() for i in issues))

    def test_03_changed_section_geometry_fails(self):
        candidate = os.path.join(self.temp_dir, "bad_geometry.docx")
        shutil.copyfile(self.template_path, candidate)

        doc = docx.Document(candidate)
        section = doc.sections[0]
        section.top_margin = Pt((section.top_margin.pt if section.top_margin else 72) + 200)
        doc.save(candidate)

        checks, issues, all_passed = run_deterministic_checks(candidate, template_path=self.template_path)

        self.assertFalse(all_passed)
        self.assertEqual(checks["section_orientation_margins_preserved"], STATUS_FAIL)

    def test_04_corrupted_docx_fails(self):
        candidate = os.path.join(self.temp_dir, "corrupted.docx")
        with open(candidate, "wb") as f:
            f.write(b"THIS IS NOT A VALID ZIP OR DOCX PACKAGE" * 20)

        checks, issues, all_passed = run_deterministic_checks(candidate, template_path=self.template_path)

        self.assertFalse(all_passed)
        self.assertEqual(checks["docx_opens"], STATUS_FAIL)
        self.assertEqual(checks["package_integrity"], STATUS_FAIL)
        self.assertEqual(checks["no_corruption_detected"], STATUS_FAIL)


class TestDocumentQAOrchestrator(unittest.TestCase):
    """Full DocumentQAAgent.run_qa() pipeline tests with injected renderer/vision-agent
    test doubles. No LibreOffice invocation, no network calls."""

    @classmethod
    def setUpClass(cls):
        cls.template_path = _authoritative_template_path()

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.compatible_docx = os.path.join(self.temp_dir, "compatible.docx")
        shutil.copyfile(self.template_path, self.compatible_docx)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _passing_page_result(self):
        return {
            "logo": "PASS",
            "header_footer": "PASS",
            "font_consistency": "PASS",
            "table_layout": "PASS",
            "spacing_alignment": "PASS",
            "overall_visual_fidelity": "PASS",
            "issues": [],
        }

    def _failing_page_result(self):
        return {
            "logo": "PASS",
            "header_footer": "FAIL",
            "font_consistency": "PASS",
            "table_layout": "FAIL",
            "spacing_alignment": "PASS",
            "overall_visual_fidelity": "FAIL",
            "issues": ["Footer missing on generated page", "Table 2 columns misaligned"],
        }

    def test_05_visual_qa_mocked_pass_yields_overall_pass(self):
        agent = DocumentQAAgent(
            template_path=self.template_path,
            renderer=_FakeRenderer,
            vision_agent_factory=lambda: _FakeVisionAgent(page_result=self._passing_page_result()),
        )
        result = agent.run_qa(self.compatible_docx)

        self.assertEqual(result["status"], STATUS_PASS)
        self.assertEqual(result["visual_checks"]["overall_visual_fidelity"], STATUS_PASS)
        self.assertEqual(result["model"], "fake/qwen3.6-flash-stub")
        self.assertIn("qa_timestamp", result)

    def test_06_visual_qa_mocked_fail_blocks_export(self):
        agent = DocumentQAAgent(
            template_path=self.template_path,
            renderer=_FakeRenderer,
            vision_agent_factory=lambda: _FakeVisionAgent(page_result=self._failing_page_result()),
        )
        result = agent.run_qa(self.compatible_docx)

        self.assertEqual(result["status"], STATUS_FAIL)
        self.assertEqual(result["visual_checks"]["overall_visual_fidelity"], STATUS_FAIL)
        self.assertEqual(result["visual_checks"]["header_footer"], STATUS_FAIL)
        self.assertTrue(any("Footer missing" in i for i in result["issues"]))

        with self.assertRaises(DocumentQAFailedError):
            with patch("msb_eb_copilot.src.document_qa_agent.DocumentQAAgent", return_value=agent):
                run_document_qa_gate(self.compatible_docx, template_path=self.template_path)

    def test_07_visual_qa_greennode_exception_fails_closed(self):
        agent = DocumentQAAgent(
            template_path=self.template_path,
            renderer=_FakeRenderer,
            vision_agent_factory=lambda: _FakeVisionAgent(
                raise_error=GreenNodeVisionQAError("simulated GreenNode API failure")
            ),
        )
        result = agent.run_qa(self.compatible_docx)

        self.assertEqual(result["status"], STATUS_FAIL)
        self.assertTrue(any("fail-closed" in i.lower() for i in result["issues"]))

    def test_08_visual_qa_unavailable_does_not_silently_pass(self):
        agent = DocumentQAAgent(
            template_path=self.template_path,
            renderer=_UnavailableRenderer,
            vision_agent_factory=lambda: _FakeVisionAgent(page_result=self._passing_page_result()),
        )
        result = agent.run_qa(self.compatible_docx)

        self.assertEqual(result["status"], STATUS_VISUAL_QA_UNAVAILABLE)
        self.assertNotEqual(result["status"], STATUS_PASS)
        for v in result["visual_checks"].values():
            self.assertNotEqual(v, STATUS_PASS)

        # run_document_qa_gate must NOT raise on VISUAL_QA_UNAVAILABLE (deterministic checks
        # already passed); it returns the result so the caller can decide/export-with-warning.
        gated = DocumentQAAgent(template_path=self.template_path, renderer=_UnavailableRenderer)
        gated_result = gated.run_qa(self.compatible_docx)
        self.assertEqual(gated_result["status"], STATUS_VISUAL_QA_UNAVAILABLE)

    def test_09_deterministic_fail_short_circuits_before_any_vision_call(self):
        broken_docx = os.path.join(self.temp_dir, "broken.docx")
        with open(broken_docx, "wb") as f:
            f.write(b"not a docx")

        vision_agent = MagicMock()
        agent = DocumentQAAgent(
            template_path=self.template_path,
            renderer=_FakeRenderer,
            vision_agent_factory=lambda: vision_agent,
        )
        result = agent.run_qa(broken_docx)

        self.assertEqual(result["status"], STATUS_FAIL)
        vision_agent.compare_page.assert_not_called()

        with self.assertRaises(DocumentQAFailedError):
            run_document_qa_gate(broken_docx, template_path=self.template_path)


class TestGreenNodeVisualQAAgentUnit(unittest.TestCase):
    """Direct unit tests of the GreenNode vision reviewer call, with the OpenAI SDK mocked.
    No real network/API calls are made anywhere in this test class."""

    def test_10_missing_api_key_fails_closed(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(GreenNodeVisionQAError):
                GreenNodeVisualQAAgent(api_key=None)

    @patch("openai.resources.chat.completions.Completions.create")
    def test_11_malformed_json_fails_closed(self, mock_create):
        mock_resp = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "This is not JSON at all, sorry."
        mock_resp.choices = [mock_choice]
        mock_create.return_value = mock_resp

        agent = GreenNodeVisualQAAgent(api_key="mock_key")
        with self.assertRaises(GreenNodeVisionQAError):
            agent.compare_page("dGVtcGxhdGU=", "Z2VuZXJhdGVk", page_num=1)

    @patch("openai.resources.chat.completions.Completions.create")
    def test_12_missing_required_key_in_json_fails_closed(self, mock_create):
        mock_resp = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = '{"logo": "PASS"}'  # missing required keys
        mock_resp.choices = [mock_choice]
        mock_create.return_value = mock_resp

        agent = GreenNodeVisualQAAgent(api_key="mock_key")
        with self.assertRaises(GreenNodeVisionQAError):
            agent.compare_page("dGVtcGxhdGU=", "Z2VuZXJhdGVk", page_num=1)

    @patch("openai.resources.chat.completions.Completions.create")
    def test_13_api_exception_fails_closed(self, mock_create):
        import openai
        mock_create.side_effect = openai.APIConnectionError(request=MagicMock())

        agent = GreenNodeVisualQAAgent(api_key="mock_key")
        with self.assertRaises(GreenNodeVisionQAError):
            agent.compare_page("dGVtcGxhdGU=", "Z2VuZXJhdGVk", page_num=1)

    @patch("openai.resources.chat.completions.Completions.create")
    def test_14_valid_strict_json_pass_parses_correctly(self, mock_create):
        mock_resp = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = (
            '{"logo": "PASS", "header_footer": "PASS", "font_consistency": "PASS", '
            '"table_layout": "PASS", "spacing_alignment": "PASS", '
            '"overall_visual_fidelity": "PASS", "issues": []}'
        )
        mock_resp.choices = [mock_choice]
        mock_create.return_value = mock_resp

        agent = GreenNodeVisualQAAgent(api_key="mock_key")
        result = agent.compare_page("dGVtcGxhdGU=", "Z2VuZXJhdGVk", page_num=1)

        self.assertEqual(result["overall_visual_fidelity"], "PASS")
        self.assertEqual(result["issues"], [])

        # Confirm the vision prompt sent to GreenNode carries the required contract terms.
        called_messages = mock_create.call_args[1]["messages"]
        system_prompt = called_messages[0]["content"]
        self.assertIn("authoritative", system_prompt.lower())
        self.assertIn("strict json", system_prompt.lower())
        self.assertIn("do not", system_prompt.lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)

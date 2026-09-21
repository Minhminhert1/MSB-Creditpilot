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

import json
import os
import re
import shutil
import tempfile
import unittest
import zipfile
from unittest.mock import MagicMock, patch

import docx
import openai
from docx.shared import Pt

from msb_eb_copilot.src.document_qa_agent import (
    DocumentQAAgent,
    DocumentQAFailedError,
    DocxPageRenderer,
    GreenNodeVisionQAError,
    GreenNodeVisualQAAgent,
    MAX_VISUAL_QA_ATTEMPTS,
    STATUS_FAIL,
    STATUS_PASS,
    STATUS_PASS_WITH_WARNING,
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

    def _font_only_failing_page_result(self):
        """Deterministic-equivalent PASS on every visual category except a genuine
        font_consistency finding — the exact production scenario this policy targets
        (e.g. a name rendering sans-serif or parenthetical text rendering roman
        instead of italic due to cross-platform LibreOffice/Linux font substitution)."""
        return {
            "logo": "PASS",
            "header_footer": "PASS",
            "font_consistency": "FAIL",
            "table_layout": "PASS",
            "spacing_alignment": "PASS",
            "overall_visual_fidelity": "FAIL",
            "issues": [
                "\"GAS SOUTH JSC (PGS)\" renders in a sans-serif font instead of the "
                "template's Times New Roman.",
                "Parenthetical text renders upright instead of italic.",
            ],
        }

    def test_06b_font_consistency_only_fail_does_not_block_export(self):
        """Deterministic PASS + the ONLY visual failure being font_consistency must
        downgrade to PASS_WITH_WARNING and allow export (run_document_qa_gate must
        NOT raise), while still surfacing the font finding as a warning."""
        agent = DocumentQAAgent(
            template_path=self.template_path,
            renderer=_FakeRenderer,
            vision_agent_factory=lambda: _FakeVisionAgent(page_result=self._font_only_failing_page_result()),
        )
        result = agent.run_qa(self.compatible_docx)

        self.assertEqual(result["status"], STATUS_PASS_WITH_WARNING)
        self.assertEqual(result["visual_checks"]["font_consistency"], STATUS_FAIL)
        self.assertEqual(result["visual_checks"]["overall_visual_fidelity"], STATUS_PASS_WITH_WARNING)
        # Deterministic checks must all still be PASS and unaffected by this policy.
        self.assertTrue(all(v == STATUS_PASS for v in result["deterministic_checks"].values()))

        # Font findings must remain visible (never silently discarded).
        self.assertTrue(any("sans-serif" in i for i in result["issues"]))
        self.assertTrue(any("italic" in i for i in result["issues"]))
        self.assertTrue(any("font_consistency" in i and "non-blocking" in i for i in result["issues"]))

        # Export must be allowed: run_document_qa_gate must NOT raise for this status.
        with patch("msb_eb_copilot.src.document_qa_agent.DocumentQAAgent", return_value=agent):
            gated_result = run_document_qa_gate(self.compatible_docx, template_path=self.template_path)
        self.assertEqual(gated_result["status"], STATUS_PASS_WITH_WARNING)

    def test_06c_font_consistency_plus_blocking_category_still_blocks(self):
        """font_consistency being non-blocking must not accidentally mask a genuine
        blocking failure reported alongside it on the same page."""
        page_result = self._font_only_failing_page_result()
        page_result["table_layout"] = "FAIL"
        page_result["issues"].append("Table 2 columns misaligned.")

        agent = DocumentQAAgent(
            template_path=self.template_path,
            renderer=_FakeRenderer,
            vision_agent_factory=lambda: _FakeVisionAgent(page_result=page_result),
        )
        result = agent.run_qa(self.compatible_docx)

        self.assertEqual(result["status"], STATUS_FAIL)
        self.assertEqual(result["visual_checks"]["table_layout"], STATUS_FAIL)
        self.assertEqual(result["visual_checks"]["font_consistency"], STATUS_FAIL)

        with self.assertRaises(DocumentQAFailedError):
            with patch("msb_eb_copilot.src.document_qa_agent.DocumentQAAgent", return_value=agent):
                run_document_qa_gate(self.compatible_docx, template_path=self.template_path)

    def test_06d_deterministic_fail_blocks_export_even_if_visual_would_pass(self):
        """Deterministic QA remains the hard gate: a deterministic FAIL must block
        export regardless of what visual QA would have reported."""
        broken_docx = os.path.join(self.temp_dir, "broken_for_policy_test.docx")
        with open(broken_docx, "wb") as f:
            f.write(b"not a valid docx package")

        agent = DocumentQAAgent(
            template_path=self.template_path,
            renderer=_FakeRenderer,
            vision_agent_factory=lambda: _FakeVisionAgent(page_result=self._passing_page_result()),
        )
        result = agent.run_qa(broken_docx)

        self.assertEqual(result["status"], STATUS_FAIL)
        self.assertFalse(all(v == STATUS_PASS for v in result["deterministic_checks"].values()))

        with self.assertRaises(DocumentQAFailedError):
            with patch("msb_eb_copilot.src.document_qa_agent.DocumentQAAgent", return_value=agent):
                run_document_qa_gate(broken_docx, template_path=self.template_path)

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


def _build_single_finding_page_json(fail_category: str, description: str) -> str:
    """Builds a raw GreenNode-style JSON response where exactly one category is claimed
    FAIL, backed by exactly one finding attached to that category."""
    payload = {
        "logo": "PASS",
        "header_footer": "PASS",
        "font_consistency": "PASS",
        "table_layout": "PASS",
        "spacing_alignment": "PASS",
    }
    payload[fail_category] = "FAIL"
    payload["overall_visual_fidelity"] = "FAIL"
    payload["findings"] = [{"category": fail_category, "description": description}]
    return json.dumps(payload, ensure_ascii=False)


def _compare_with_mocked_content(raw_content: str) -> dict:
    with patch("openai.resources.chat.completions.Completions.create") as mock_create:
        mock_resp = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = raw_content
        mock_resp.choices = [mock_choice]
        mock_create.return_value = mock_resp

        agent = GreenNodeVisualQAAgent(api_key="mock_key")
        return agent.compare_page("dGVtcGxhdGU=", "Z2VuZXJhdGVk", page_num=1)


class TestVisualQAFalsePositiveFilter(unittest.TestCase):
    """Regression tests for the observed false-positive bug: the GreenNode vision reviewer
    was treating CONTENT and PAGINATION differences as formatting defects. These tests lock
    in that such findings are ignored (never cause FAIL), while genuine visual defects still
    correctly FAIL. No real network/API calls are made — the OpenAI client is mocked."""

    IGNORED_CASES = [
        ("missing_rows", "table_layout",
         "Table 15 in the generated document is missing 2 rows that are present in the template."),
        ("missing_template_guidance", "spacing_alignment",
         "The template's guidance text explaining how to fill this field is missing here."),
        ("missing_dotted_placeholder", "spacing_alignment",
         "The dotted placeholder lines from the template have disappeared in this field."),
        ("footnote_number_difference", "header_footer",
         "The footnote number differs from the template (footnote 3 here vs footnote 2 in the template)."),
        ("section_moved_to_another_page", "header_footer",
         "Section C now appears on a different page than in the template."),
        ("red_instructional_text_now_black", "font_consistency",
         "The template's red instructional text has become normal black content here."),
    ]

    STILL_FAILING_CASES = [
        ("sans_serif_block_in_times_new_roman_doc", "font_consistency",
         "A block of text renders in a sans-serif font while the rest of the document uses Times New Roman."),
        ("text_concatenation_tai_cap", "spacing_alignment",
         "Two labels run together with no separating space: \"Chọn kết quảTái cấp và\"."),
        ("text_concatenation_toi_da", "spacing_alignment",
         "Two labels run together with no separating space: \"Chọn kết quảTối đa 700 tỷ đồng\"."),
        ("broken_table_geometry", "table_layout",
         "Table borders are broken and cell geometry is malformed and collapsed."),
        ("missing_visible_logo", "logo",
         "The MSB logo is completely missing from the header area where it should render."),
        ("overlapping_clipped_text", "spacing_alignment",
         "Text is visibly clipped and overlapping at the bottom of the page."),
    ]

    def test_ignored_content_and_pagination_findings_do_not_fail(self):
        for name, category, description in self.IGNORED_CASES:
            with self.subTest(case=name):
                raw = _build_single_finding_page_json(category, description)
                result = _compare_with_mocked_content(raw)

                self.assertEqual(
                    result[category], STATUS_PASS,
                    msg=f"'{name}' should be downgraded to PASS (content/pagination-only finding), got {result}",
                )
                self.assertEqual(result["overall_visual_fidelity"], STATUS_PASS, msg=f"'{name}': {result}")
                self.assertEqual(result["issues"], [], msg=f"'{name}' should leave no surfaced issue: {result}")

    def test_genuine_visual_defects_still_fail(self):
        for name, category, description in self.STILL_FAILING_CASES:
            with self.subTest(case=name):
                raw = _build_single_finding_page_json(category, description)
                result = _compare_with_mocked_content(raw)

                self.assertEqual(
                    result[category], STATUS_FAIL,
                    msg=f"'{name}' is a genuine visual defect and must still FAIL, got {result}",
                )
                self.assertEqual(result["overall_visual_fidelity"], STATUS_FAIL, msg=f"'{name}': {result}")
                self.assertIn(description, result["issues"], msg=f"'{name}': {result}")

    def test_fail_with_no_backing_finding_is_downgraded(self):
        """A category claimed FAIL with an empty findings list has no evidence at all and
        must be downgraded, closing the loophole where a model fails a category without
        attaching any finding to justify it."""
        payload = {
            "logo": "PASS", "header_footer": "PASS", "font_consistency": "PASS",
            "table_layout": "FAIL", "spacing_alignment": "PASS",
            "overall_visual_fidelity": "FAIL", "findings": [],
        }
        result = _compare_with_mocked_content(json.dumps(payload))

        self.assertEqual(result["table_layout"], STATUS_PASS)
        self.assertEqual(result["overall_visual_fidelity"], STATUS_PASS)
        self.assertEqual(result["issues"], [])

    def test_mixed_page_only_genuine_defect_survives(self):
        """A page with both a content-completeness finding AND a genuine defect on two
        different categories must fail only for the genuine one."""
        payload = {
            "logo": "FAIL", "header_footer": "PASS", "font_consistency": "PASS",
            "table_layout": "FAIL", "spacing_alignment": "PASS",
            "overall_visual_fidelity": "FAIL",
            "findings": [
                {"category": "logo", "description": "The MSB logo is completely missing from the header."},
                {"category": "table_layout", "description": "Table 15 is missing 2 rows versus the template."},
            ],
        }
        result = _compare_with_mocked_content(json.dumps(payload))

        self.assertEqual(result["logo"], STATUS_FAIL)
        self.assertEqual(result["table_layout"], STATUS_PASS)
        self.assertEqual(result["overall_visual_fidelity"], STATUS_FAIL)
        self.assertEqual(result["issues"], ["The MSB logo is completely missing from the header."])


_VALID_PASS_JSON = (
    '{"logo": "PASS", "header_footer": "PASS", "font_consistency": "PASS", '
    '"table_layout": "PASS", "spacing_alignment": "PASS", '
    '"overall_visual_fidelity": "PASS", "findings": []}'
)


def _mock_success_response(content: str = _VALID_PASS_JSON):
    resp = MagicMock()
    choice = MagicMock()
    choice.message.content = content
    resp.choices = [choice]
    return resp


def _mock_status_error(exc_cls, status_code: int, retry_after=None):
    headers = {"Retry-After": str(retry_after)} if retry_after is not None else {}
    response = MagicMock(status_code=status_code, headers=headers)
    return exc_cls(f"simulated error {status_code}", response=response, body=None)


class TestGreenNodeRetryPolicy(unittest.TestCase):
    """Regression tests for bounded retry on retryable GreenNode API errors (HTTP 429, 500,
    502, 503, 504). time.sleep is mocked so these tests run instantly and make no real
    network/API calls."""

    def setUp(self):
        self._sleep_patcher = patch("msb_eb_copilot.src.document_qa_agent.time.sleep")
        self.mock_sleep = self._sleep_patcher.start()
        self.addCleanup(self._sleep_patcher.stop)

    @patch("openai.resources.chat.completions.Completions.create")
    def test_429_then_success_yields_pass(self, mock_create):
        err_429 = _mock_status_error(openai.RateLimitError, 429)
        mock_create.side_effect = [err_429, _mock_success_response()]

        agent = GreenNodeVisualQAAgent(api_key="mock_key")
        result = agent.compare_page("dGVtcGxhdGU=", "Z2VuZXJhdGVk", page_num=1)

        self.assertEqual(result["overall_visual_fidelity"], STATUS_PASS)
        self.assertEqual(mock_create.call_count, 2)
        self.assertEqual(self.mock_sleep.call_count, 1)

    @patch("openai.resources.chat.completions.Completions.create")
    def test_multiple_429_then_success_yields_pass(self, mock_create):
        err_429 = _mock_status_error(openai.RateLimitError, 429)
        mock_create.side_effect = [err_429, err_429, _mock_success_response()]

        agent = GreenNodeVisualQAAgent(api_key="mock_key")
        result = agent.compare_page("dGVtcGxhdGU=", "Z2VuZXJhdGVk", page_num=1)

        self.assertEqual(result["overall_visual_fidelity"], STATUS_PASS)
        self.assertEqual(mock_create.call_count, 3)
        self.assertEqual(self.mock_sleep.call_count, 2)

    @patch("openai.resources.chat.completions.Completions.create")
    def test_429_exhausted_fails_closed_with_explicit_message(self, mock_create):
        err_429 = _mock_status_error(openai.RateLimitError, 429)
        mock_create.side_effect = [err_429, err_429, err_429, err_429, err_429]

        agent = GreenNodeVisualQAAgent(api_key="mock_key")
        with self.assertRaises(GreenNodeVisionQAError) as ctx:
            agent.compare_page("dGVtcGxhdGU=", "Z2VuZXJhdGVk", page_num=3)

        self.assertIn("GreenNode visual QA rate limit/retry exhausted", str(ctx.exception))
        self.assertEqual(mock_create.call_count, MAX_VISUAL_QA_ATTEMPTS)
        self.assertEqual(self.mock_sleep.call_count, MAX_VISUAL_QA_ATTEMPTS - 1)

    @patch("openai.resources.chat.completions.Completions.create")
    def test_500_retry_then_success_yields_pass(self, mock_create):
        err_500 = _mock_status_error(openai.InternalServerError, 500)
        mock_create.side_effect = [err_500, _mock_success_response()]

        agent = GreenNodeVisualQAAgent(api_key="mock_key")
        result = agent.compare_page("dGVtcGxhdGU=", "Z2VuZXJhdGVk", page_num=1)

        self.assertEqual(result["overall_visual_fidelity"], STATUS_PASS)
        self.assertEqual(mock_create.call_count, 2)
        self.assertEqual(self.mock_sleep.call_count, 1)

    @patch("openai.resources.chat.completions.Completions.create")
    def test_502_503_504_are_also_retried(self, mock_create):
        for status_code in (502, 503, 504):
            with self.subTest(status_code=status_code):
                mock_create.reset_mock()
                self.mock_sleep.reset_mock()
                err = _mock_status_error(openai.InternalServerError, status_code)
                mock_create.side_effect = [err, _mock_success_response()]

                agent = GreenNodeVisualQAAgent(api_key="mock_key")
                result = agent.compare_page("dGVtcGxhdGU=", "Z2VuZXJhdGVk", page_num=1)

                self.assertEqual(result["overall_visual_fidelity"], STATUS_PASS)
                self.assertEqual(mock_create.call_count, 2)

    @patch("openai.resources.chat.completions.Completions.create")
    def test_retry_after_header_is_respected(self, mock_create):
        err_429 = _mock_status_error(openai.RateLimitError, 429, retry_after=7)
        mock_create.side_effect = [err_429, _mock_success_response()]

        agent = GreenNodeVisualQAAgent(api_key="mock_key")
        agent.compare_page("dGVtcGxhdGU=", "Z2VuZXJhdGVk", page_num=1)

        self.mock_sleep.assert_called_once_with(7.0)

    @patch("openai.resources.chat.completions.Completions.create")
    def test_malformed_json_is_not_retried(self, mock_create):
        mock_create.return_value = _mock_success_response("this is not JSON at all")

        agent = GreenNodeVisualQAAgent(api_key="mock_key")
        with self.assertRaises(GreenNodeVisionQAError):
            agent.compare_page("dGVtcGxhdGU=", "Z2VuZXJhdGVk", page_num=1)

        self.assertEqual(mock_create.call_count, 1)
        self.mock_sleep.assert_not_called()

    @patch("openai.resources.chat.completions.Completions.create")
    def test_non_retryable_400_is_not_retried(self, mock_create):
        err_400 = _mock_status_error(openai.BadRequestError, 400)
        mock_create.side_effect = [err_400, _mock_success_response()]

        agent = GreenNodeVisualQAAgent(api_key="mock_key")
        with self.assertRaises(GreenNodeVisionQAError) as ctx:
            agent.compare_page("dGVtcGxhdGU=", "Z2VuZXJhdGVk", page_num=1)

        self.assertNotIn("retry exhausted", str(ctx.exception).lower())
        self.assertEqual(mock_create.call_count, 1)
        self.mock_sleep.assert_not_called()


class _TwoPageFakeRenderer(DocxPageRenderer):
    """Test double producing 2 pages, used to verify the inter-page pacing delay."""

    @classmethod
    def is_available(cls) -> bool:
        return True

    @classmethod
    def render_to_page_images(cls, docx_path, out_dir, dpi=150, max_pages=None, timeout=120.0):
        os.makedirs(out_dir, exist_ok=True)
        paths = []
        for i in (1, 2):
            img_path = os.path.join(out_dir, f"page_{i}.png")
            with open(img_path, "wb") as f:
                f.write(b"\x89PNG\r\n\x1a\n\x00\x00\x00\x00")
            paths.append(img_path)
        return paths


class _FakeVisionAgentAlwaysPass:
    model = "fake/qwen3.6-flash-stub"

    def compare_page(self, template_b64_png, generated_b64_png, page_num):
        return {
            "logo": "PASS", "header_footer": "PASS", "font_consistency": "PASS",
            "table_layout": "PASS", "spacing_alignment": "PASS",
            "overall_visual_fidelity": "PASS", "issues": [],
        }


class TestPageDelayPacing(unittest.TestCase):
    """Verifies the configurable inter-page delay (DOCUMENT_QA_PAGE_DELAY_SECONDS) is applied
    between successful page calls, independent of retry backoff."""

    @classmethod
    def setUpClass(cls):
        cls.template_path = _authoritative_template_path()

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.compatible_docx = os.path.join(self.temp_dir, "compatible.docx")
        shutil.copyfile(self.template_path, self.compatible_docx)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_delay_applied_between_pages_but_not_after_last_page(self):
        with patch("msb_eb_copilot.src.document_qa_agent.time.sleep") as mock_sleep:
            agent = DocumentQAAgent(
                template_path=self.template_path,
                renderer=_TwoPageFakeRenderer,
                vision_agent_factory=_FakeVisionAgentAlwaysPass,
                page_delay_seconds=3.5,
            )
            result = agent.run_qa(self.compatible_docx)

            self.assertEqual(result["status"], STATUS_PASS)
            mock_sleep.assert_called_once_with(3.5)

    def test_zero_delay_skips_sleep(self):
        with patch("msb_eb_copilot.src.document_qa_agent.time.sleep") as mock_sleep:
            agent = DocumentQAAgent(
                template_path=self.template_path,
                renderer=_TwoPageFakeRenderer,
                vision_agent_factory=_FakeVisionAgentAlwaysPass,
                page_delay_seconds=0,
            )
            agent.run_qa(self.compatible_docx)
            mock_sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)

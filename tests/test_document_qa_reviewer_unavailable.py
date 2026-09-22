# -*- coding: utf-8 -*-
"""URGENT HACKATHON FIX regression tests: GreenNode Visual QA reviewer
unavailability (empty response, timeout, malformed response, or exhausted
transient 429/5xx retry) must downgrade to a non-blocking PASS_WITH_WARNING
after bounded retry -- NEVER a blocking FAIL -- provided deterministic checks
passed. A genuine deterministic FAIL, or a genuine well-formed BLOCKING visual
defect, must still FAIL and block export exactly as before.

Numbered tests below correspond 1:1 to the fix's required regression list.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import openai

from msb_eb_copilot.src.document_qa_agent import (
    DocumentQAAgent,
    DocumentQAFailedError,
    DocxPageRenderer,
    GreenNodeVisualQAAgent,
    MAX_VISUAL_QA_ATTEMPTS,
    VISUAL_QA_CONTENT_MAX_ATTEMPTS,
    STATUS_FAIL,
    STATUS_PASS,
    STATUS_PASS_WITH_WARNING,
    run_document_qa_gate,
)


def _authoritative_template_path() -> str:
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(
        base_dir, "MB07 Tờ trình đề xuất cấp tín dụng (ĐVKD) - thực hiện rà soát - tái cấp.docx"
    )
    assert os.path.exists(path), f"MB07 authoritative template not found at {path}"
    return path


class _FakeRenderer(DocxPageRenderer):
    """One-page renderer test double: never invokes LibreOffice."""

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


_VALID_PASS_JSON = (
    '{"logo": "PASS", "header_footer": "PASS", "font_consistency": "PASS", '
    '"table_layout": "PASS", "spacing_alignment": "PASS", '
    '"overall_visual_fidelity": "PASS", "findings": []}'
)


def _mock_response(content: str = _VALID_PASS_JSON):
    resp = MagicMock()
    choice = MagicMock()
    choice.message.content = content
    resp.choices = [choice]
    return resp


def _mock_status_error(exc_cls, status_code: int):
    response = MagicMock(status_code=status_code, headers={})
    return exc_cls(f"simulated error {status_code}", response=response, body=None)


class DocumentQAReviewerUnavailableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template_path = _authoritative_template_path()

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.compatible_docx = os.path.join(self.temp_dir, "compatible.docx")
        shutil.copyfile(self.template_path, self.compatible_docx)
        self._sleep_patcher = patch("msb_eb_copilot.src.document_qa_agent.time.sleep")
        self.mock_sleep = self._sleep_patcher.start()
        self.addCleanup(self._sleep_patcher.stop)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _run(self, docx_path, side_effect_or_return):
        """Runs the full DocumentQAAgent pipeline with a fake renderer and the
        REAL GreenNodeVisualQAAgent, with only the OpenAI network call mocked."""
        with patch("openai.resources.chat.completions.Completions.create") as mock_create:
            if isinstance(side_effect_or_return, list):
                mock_create.side_effect = side_effect_or_return
            else:
                mock_create.return_value = side_effect_or_return
            agent = DocumentQAAgent(
                template_path=self.template_path,
                renderer=_FakeRenderer,
                vision_agent_factory=lambda: GreenNodeVisualQAAgent(api_key="mock_key"),
            )
            result = agent.run_qa(docx_path)
        return result, mock_create

    # ------------------------------------------------------------------
    # 1. deterministic PASS + visual PASS -> PASS
    # ------------------------------------------------------------------
    def test_1_deterministic_and_visual_pass(self):
        result, mock_create = self._run(self.compatible_docx, _mock_response())
        self.assertEqual(result["status"], STATUS_PASS)
        self.assertEqual(result["visual_qa_status"], "AVAILABLE")
        self.assertTrue(all(v == STATUS_PASS for v in result["deterministic_checks"].values()))
        self.assertEqual(mock_create.call_count, 1)

    # ------------------------------------------------------------------
    # 2. deterministic PASS + font-only visual issue -> PASS_WITH_WARNING
    # ------------------------------------------------------------------
    def test_2_font_only_issue_pass_with_warning(self):
        content = (
            '{"logo": "PASS", "header_footer": "PASS", "font_consistency": "FAIL", '
            '"table_layout": "PASS", "spacing_alignment": "PASS", '
            '"overall_visual_fidelity": "FAIL", '
            '"findings": [{"category": "font_consistency", "description": '
            '"A block of text renders sans-serif inside an otherwise Times New Roman document."}]}'
        )
        result, _ = self._run(self.compatible_docx, _mock_response(content))
        self.assertEqual(result["status"], STATUS_PASS_WITH_WARNING)
        # The reviewer DID answer for every page -- this is a genuine font-only
        # finding, not a reviewer-unavailable case.
        self.assertEqual(result["visual_qa_status"], "AVAILABLE")
        self.assertEqual(result["visual_checks"]["font_consistency"], STATUS_FAIL)

    # ------------------------------------------------------------------
    # 3. visual empty response -> retry -> exhausted -> PASS_WITH_WARNING
    # ------------------------------------------------------------------
    def test_3_empty_response_retried_then_pass_with_warning(self):
        empty = _mock_response("")
        result, mock_create = self._run(self.compatible_docx, [empty] * VISUAL_QA_CONTENT_MAX_ATTEMPTS)

        self.assertEqual(result["status"], STATUS_PASS_WITH_WARNING)
        self.assertEqual(result["visual_qa_status"], "UNAVAILABLE")
        self.assertEqual(mock_create.call_count, VISUAL_QA_CONTENT_MAX_ATTEMPTS)
        self.assertTrue(any("AI reviewer unavailable" in i for i in result["issues"]))
        self.assertTrue(any("AI Visual QA tạm thời không phản hồi đầy đủ" in i for i in result["issues"]))
        # Structural checks are untouched by this policy.
        self.assertTrue(all(v == STATUS_PASS for v in result["deterministic_checks"].values()))

    # ------------------------------------------------------------------
    # 4. visual timeout -> PASS_WITH_WARNING
    # ------------------------------------------------------------------
    def test_4_timeout_retried_then_pass_with_warning(self):
        timeout_exc = openai.APITimeoutError(request=MagicMock())
        side_effects = [timeout_exc] * (MAX_VISUAL_QA_ATTEMPTS * VISUAL_QA_CONTENT_MAX_ATTEMPTS)
        result, mock_create = self._run(self.compatible_docx, side_effects)

        self.assertEqual(result["status"], STATUS_PASS_WITH_WARNING)
        self.assertEqual(result["visual_qa_status"], "UNAVAILABLE")
        self.assertEqual(mock_create.call_count, MAX_VISUAL_QA_ATTEMPTS * VISUAL_QA_CONTENT_MAX_ATTEMPTS)

    # ------------------------------------------------------------------
    # 5. transient 5xx exhausted -> PASS_WITH_WARNING
    # ------------------------------------------------------------------
    def test_5_transient_5xx_exhausted_then_pass_with_warning(self):
        err_500 = _mock_status_error(openai.InternalServerError, 500)
        side_effects = [err_500] * (MAX_VISUAL_QA_ATTEMPTS * VISUAL_QA_CONTENT_MAX_ATTEMPTS)
        result, mock_create = self._run(self.compatible_docx, side_effects)

        self.assertEqual(result["status"], STATUS_PASS_WITH_WARNING)
        self.assertEqual(result["visual_qa_status"], "UNAVAILABLE")
        self.assertEqual(mock_create.call_count, MAX_VISUAL_QA_ATTEMPTS * VISUAL_QA_CONTENT_MAX_ATTEMPTS)

    # ------------------------------------------------------------------
    # 6. deterministic PASS + valid visual BLOCKING issue -> FAIL
    # ------------------------------------------------------------------
    def test_6_genuine_blocking_visual_defect_still_fails(self):
        content = (
            '{"logo": "FAIL", "header_footer": "PASS", "font_consistency": "PASS", '
            '"table_layout": "PASS", "spacing_alignment": "PASS", '
            '"overall_visual_fidelity": "FAIL", '
            '"findings": [{"category": "logo", "description": '
            '"The MSB logo is completely missing from the header area where it should render."}]}'
        )
        result, _ = self._run(self.compatible_docx, _mock_response(content))
        self.assertEqual(result["status"], STATUS_FAIL)
        self.assertEqual(result["visual_checks"]["logo"], STATUS_FAIL)
        self.assertEqual(result["visual_qa_status"], "AVAILABLE")

        with self.assertRaises(DocumentQAFailedError):
            with patch("openai.resources.chat.completions.Completions.create") as mock_create:
                mock_create.return_value = _mock_response(content)
                with patch(
                    "msb_eb_copilot.src.document_qa_agent.DocumentQAAgent",
                    return_value=DocumentQAAgent(
                        template_path=self.template_path,
                        renderer=_FakeRenderer,
                        vision_agent_factory=lambda: GreenNodeVisualQAAgent(api_key="mock_key"),
                    ),
                ):
                    run_document_qa_gate(self.compatible_docx, template_path=self.template_path)

    # ------------------------------------------------------------------
    # 7. deterministic FAIL + visual unavailable -> FAIL (deterministic wins,
    # visual QA is never even attempted).
    # ------------------------------------------------------------------
    def test_7_deterministic_fail_short_circuits_before_visual_qa(self):
        broken_docx = os.path.join(self.temp_dir, "broken.docx")
        with open(broken_docx, "wb") as f:
            f.write(b"not a valid docx package")

        result, mock_create = self._run(broken_docx, _mock_response(""))
        self.assertEqual(result["status"], STATUS_FAIL)
        self.assertIsNone(result["visual_qa_status"])  # visual QA never attempted at all
        mock_create.assert_not_called()

    # ------------------------------------------------------------------
    # 8. export allowed for PASS_WITH_WARNING
    # ------------------------------------------------------------------
    def test_8_export_allowed_for_pass_with_warning(self):
        empty = _mock_response("")
        with patch("openai.resources.chat.completions.Completions.create") as mock_create:
            mock_create.return_value = empty
            agent = DocumentQAAgent(
                template_path=self.template_path,
                renderer=_FakeRenderer,
                vision_agent_factory=lambda: GreenNodeVisualQAAgent(api_key="mock_key"),
            )
            with patch("msb_eb_copilot.src.document_qa_agent.DocumentQAAgent", return_value=agent):
                gated_result = run_document_qa_gate(self.compatible_docx, template_path=self.template_path)

        self.assertEqual(gated_result["status"], STATUS_PASS_WITH_WARNING)

    # ------------------------------------------------------------------
    # 9. export blocked for a real FAIL
    # ------------------------------------------------------------------
    def test_9_export_blocked_for_genuine_fail(self):
        content = (
            '{"logo": "FAIL", "header_footer": "PASS", "font_consistency": "PASS", '
            '"table_layout": "PASS", "spacing_alignment": "PASS", '
            '"overall_visual_fidelity": "FAIL", '
            '"findings": [{"category": "logo", "description": "The MSB logo is completely missing."}]}'
        )
        with patch("openai.resources.chat.completions.Completions.create") as mock_create:
            mock_create.return_value = _mock_response(content)
            agent = DocumentQAAgent(
                template_path=self.template_path,
                renderer=_FakeRenderer,
                vision_agent_factory=lambda: GreenNodeVisualQAAgent(api_key="mock_key"),
            )
            with patch("msb_eb_copilot.src.document_qa_agent.DocumentQAAgent", return_value=agent):
                with self.assertRaises(DocumentQAFailedError):
                    run_document_qa_gate(self.compatible_docx, template_path=self.template_path)

    # ------------------------------------------------------------------
    # 10. warning is observable; no silent fallback (never treated as a
    # clean PASS, and the specific reviewer-unavailable reason is visible).
    # ------------------------------------------------------------------
    def test_10_warning_is_observable_not_silent(self):
        empty = _mock_response("")
        result, _ = self._run(self.compatible_docx, [empty] * VISUAL_QA_CONTENT_MAX_ATTEMPTS)

        self.assertNotEqual(result["status"], STATUS_PASS)
        self.assertEqual(result["status"], STATUS_PASS_WITH_WARNING)
        self.assertGreater(len(result["issues"]), 0)
        self.assertEqual(result["visual_qa_status"], "UNAVAILABLE")
        # The empty-DOCX-vs-empty-AI-response distinction must be explicit in the
        # issue text, never phrased as if the rendered page itself were blank.
        self.assertTrue(any("empty content" in i or "reviewer unavailable" in i.lower() for i in result["issues"]))


if __name__ == "__main__":
    unittest.main()

"""Tests for MB07 template verification and immutable working copy manager (Phase 10)."""

import os
import tempfile
import unittest

from msb_eb_copilot.src.template_verification import (
    AUTHORITATIVE_MB07_SHA256,
    MB07TemplateVerifier,
    TemplateVerificationError,
)


class MB07TemplateVerifierTests(unittest.TestCase):
    """Test suite for Phase 10 template verification."""

    def setUp(self) -> None:
        self.verifier = MB07TemplateVerifier()
        # Find root authoritative template file
        self.repo_root = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..")
        )
        self.authoritative_template_path = os.path.join(
            self.repo_root,
            "MB07 Tờ trình đề xuất cấp tín dụng (ĐVKD) - thực hiện rà soát - tái cấp.docx",
        )
        self.legacy_template_path = os.path.join(
            self.repo_root,
            "MB07 Tờ trình đề xuất cấp tín dụng (ĐVKD) - Tho.docx",
        )
        self.template_path = self.authoritative_template_path

    def test_new_authoritative_mb07_template_passes_verification(self):
        self.assertTrue(os.path.exists(self.authoritative_template_path))
        result = self.verifier.verify(self.authoritative_template_path)
        self.assertEqual(result.sha256, AUTHORITATIVE_MB07_SHA256)
        self.assertTrue(result.is_authoritative)
        self.assertIsNone(result.notes)
        self.assertEqual(len(result.missing_markers), 0)
        self.assertIn("Tick chọn", result.markers_verified)
        self.assertIn("46321", result.markers_verified)

    def test_legacy_mb07_template_passes_verification(self):
        self.assertTrue(os.path.exists(self.legacy_template_path))
        result = self.verifier.verify(self.legacy_template_path)
        self.assertTrue(result.is_authoritative)
        self.assertIsNone(result.notes)
        self.assertEqual(len(result.missing_markers), 0)
        self.assertIn("Tick chọn", result.markers_verified)

    def test_mismatched_template_fails_verification(self):
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
            tmp.write(b"corrupted fake docx content")
            fake_path = tmp.name

        try:
            result = self.verifier.verify(fake_path)
            self.assertFalse(result.is_authoritative)
            self.assertIsNotNone(result.notes)
            self.assertIn("SHA-256 mismatch", result.notes)
        finally:
            os.remove(fake_path)

    def test_create_working_copy_creates_isolated_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            dest_copy = os.path.join(tmpdir, "working_mb07.docx")
            out = self.verifier.create_working_copy(self.template_path, dest_copy)
            self.assertTrue(os.path.exists(dest_copy))
            self.assertEqual(out, dest_copy)
            self.assertEqual(self.verifier.compute_sha256(dest_copy), AUTHORITATIVE_MB07_SHA256)

    def test_create_working_copy_rejects_corrupted_template(self):
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
            tmp.write(b"not a valid template")
            fake_path = tmp.name

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                dest = os.path.join(tmpdir, "out.docx")
                with self.assertRaises(TemplateVerificationError):
                    self.verifier.create_working_copy(fake_path, dest)
        finally:
            os.remove(fake_path)


if __name__ == "__main__":
    unittest.main()

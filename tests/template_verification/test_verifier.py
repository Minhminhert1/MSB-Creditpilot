"""Tests for MB07 template verification and immutable working copy manager (Phase 10)."""

import os
import shutil
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
            "MB07 Tờ trình đề xuất cấp tín dụng (ĐVKD) - bản tham khảo.docx",
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
        """A corrupted/non-DOCX file is a hard FAIL (never downgraded) -- distinct
        from a genuine SHA-256-only mismatch on an otherwise valid, marker-complete
        DOCX, which demo mode tolerates (see test_sha_mismatch_only_is_downgraded_*
        below)."""
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
            tmp.write(b"corrupted fake docx content")
            fake_path = tmp.name

        try:
            result = self.verifier.verify(fake_path)
            self.assertFalse(result.is_authoritative)
            self.assertEqual(result.status, "FAIL")
            self.assertIsNotNone(result.notes)
            self.assertIn("Cannot open template as a valid DOCX/OPC package", result.notes)
        finally:
            os.remove(fake_path)

    def test_sha_mismatch_only_is_downgraded_to_pass_with_warning(self):
        """URGENT DEMO HOTFIX: a valid, marker-complete DOCX whose exact SHA-256
        does not match an approved hash must be downgraded to PASS_WITH_WARNING
        (is_authoritative=True, export/working-copy creation proceeds), not a
        hard FAIL -- 'Demo mode: allow scrubbed template hash drift.'"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tweaked_path = os.path.join(tmpdir, "tweaked.docx")
            shutil.copyfile(self.authoritative_template_path, tweaked_path)
            # Append a trailing byte: still a valid ZIP/DOCX (extra bytes after
            # the central directory are harmless), content/markers unchanged,
            # but the file's own SHA-256 no longer matches any approved hash.
            with open(tweaked_path, "ab") as f:
                f.write(b"\x00")

            result = self.verifier.verify(tweaked_path)
            self.assertNotEqual(result.sha256, AUTHORITATIVE_MB07_SHA256)
            self.assertTrue(result.is_authoritative)
            self.assertEqual(result.status, "PASS_WITH_WARNING")
            self.assertIsNotNone(result.notes)
            self.assertIn("SHA-256 mismatch", result.notes)
            self.assertIn("demo mode", result.notes.lower())
            self.assertEqual(len(result.missing_markers), 0)
            self.assertIn("Tick chọn", result.markers_verified)

            # And it must not block working-copy creation.
            dest = os.path.join(tmpdir, "working_copy.docx")
            out = self.verifier.create_working_copy(tweaked_path, dest)
            self.assertTrue(os.path.exists(out))

    def test_stale_expected_sha256_mismatch_is_downgraded_not_blocking(self):
        """Reproduces the exact reported production error verbatim: a verifier
        constructed with a STALE/non-default expected_sha256 (e.g. an old
        AUTHORITATIVE_MB07_SHA256 value from before a legitimate template
        content update) checked against the CURRENT, genuinely-authoritative
        template file on disk. This exercises the `else` branch of verify()'s
        is_match computation (expected_sha256 != AUTHORITATIVE_MB07_SHA256),
        which is untouched by test_sha_mismatch_only_is_downgraded_* above
        (that test uses the default verifier and a tweaked-copy file, hitting
        the `if` branch instead). Must downgrade to PASS_WITH_WARNING, log a
        warning, and NOT block create_working_copy -- never a hard FAIL."""
        stale_expected_hash = "4355d918479f173a879089f554abe6e19dfe0e3c1c990fb1c26f12b0c6fb68bd"
        self.assertNotEqual(stale_expected_hash, AUTHORITATIVE_MB07_SHA256)
        verifier = MB07TemplateVerifier(expected_sha256=stale_expected_hash)

        with self.assertLogs("msb_eb_copilot.src.template_verification.verifier", level="WARNING") as log_ctx:
            result = verifier.verify(self.authoritative_template_path)

        self.assertEqual(result.sha256, AUTHORITATIVE_MB07_SHA256)
        self.assertTrue(result.is_authoritative)
        self.assertEqual(result.status, "PASS_WITH_WARNING")
        self.assertIsNotNone(result.notes)
        self.assertIn(stale_expected_hash, result.notes)
        self.assertIn(AUTHORITATIVE_MB07_SHA256, result.notes)
        self.assertTrue(any("SHA-256 mismatch" in msg for msg in log_ctx.output))

        # Must NOT raise / must NOT block export.
        with tempfile.TemporaryDirectory() as tmpdir:
            dest = os.path.join(tmpdir, "working_copy.docx")
            out = verifier.create_working_copy(self.authoritative_template_path, dest)
            self.assertTrue(os.path.exists(out))
            self.assertEqual(verifier.compute_sha256(out), AUTHORITATIVE_MB07_SHA256)

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

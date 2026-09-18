"""Authoritative MB07 template verifier and immutable working copy manager (Phase 10)."""

from dataclasses import dataclass
import hashlib
import os
import shutil

AUTHORITATIVE_MB07_SHA256 = "4355d918479f173a879089f554abe6e19dfe0e3c1c990fb1c26f12b0c6fb68bd"
LEGACY_MB07_SHA256 = "ca60127f5a8a97a6b345cca3bb110cbfb8cb4a438d589131fe5b929e8be8f68b"

APPROVED_MB07_SHA256S: set[str] = {
    AUTHORITATIVE_MB07_SHA256,
    LEGACY_MB07_SHA256,
}

EXPECTED_MARKERS: tuple[str, ...] = (
    "Tick chọn",
    "46321",
    "Bán buôn thịt và các sản phẩm từ thịt",
    "Lúa, điều, gạo",
)


class TemplateVerificationError(Exception):
    """Raised when an authoritative template does not match the approved signature or checksum."""


@dataclass(frozen=True)
class TemplateVerificationResult:
    """Outcome of verifying a Word MB07 template file."""

    template_path: str
    sha256: str
    is_authoritative: bool
    markers_verified: tuple[str, ...] = ()
    missing_markers: tuple[str, ...] = ()
    notes: str | None = None


class MB07TemplateVerifier:
    """Verifies that a Word template matches the approved authoritative MSB MB07 template."""

    def __init__(
        self,
        expected_sha256: str = AUTHORITATIVE_MB07_SHA256,
        expected_markers: tuple[str, ...] = EXPECTED_MARKERS,
    ) -> None:
        self.expected_sha256 = expected_sha256.lower() if expected_sha256 else None
        self.expected_markers = expected_markers

    def compute_sha256(self, file_path: str) -> str:
        """Compute the SHA-256 checksum of any file."""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Template file not found at '{file_path}'.")
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(65536), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest().lower()

    def verify(self, template_path: str) -> TemplateVerificationResult:
        """Verify that the template matches the approved SHA-256 and content markers."""
        actual_sha256 = self.compute_sha256(template_path)
        if self.expected_sha256 == AUTHORITATIVE_MB07_SHA256:
            is_match = actual_sha256 in APPROVED_MB07_SHA256S
        else:
            is_match = actual_sha256 == self.expected_sha256

        # Check markers inside DOCX plain text
        verified_markers: list[str] = []
        missing_markers: list[str] = []

        import re
        import zipfile
        try:
            with zipfile.ZipFile(template_path, "r") as z:
                # Read document.xml and header/footer xml
                xml_content = ""
                for name in z.namelist():
                    if name.startswith("word/") and name.endswith(".xml"):
                        xml_content += z.read(name).decode("utf-8", errors="ignore")

                # Strip XML tags to get continuous text across runs
                plain_text = re.sub(r"<[^>]+>", "", xml_content)

                for marker in self.expected_markers:
                    if marker in plain_text:
                        verified_markers.append(marker)
                    else:
                        missing_markers.append(marker)
        except Exception:
            missing_markers = list(self.expected_markers)

        notes = None
        if not is_match:
            notes = f"SHA-256 mismatch: expected '{self.expected_sha256}', got '{actual_sha256}'."
        elif missing_markers:
            notes = f"Authoritative template is missing expected markers: {missing_markers}."

        return TemplateVerificationResult(
            template_path=template_path,
            sha256=actual_sha256,
            is_authoritative=is_match and len(missing_markers) == 0,
            markers_verified=tuple(verified_markers),
            missing_markers=tuple(missing_markers),
            notes=notes,
        )

    def create_working_copy(self, template_path: str, working_copy_path: str) -> str:
        """Verify the authoritative template and copy it to a working location.

        The source template must remain completely immutable.
        """
        result = self.verify(template_path)
        if not result.is_authoritative:
            raise TemplateVerificationError(
                f"Cannot create working copy from non-authoritative template: {result.notes}"
            )

        os.makedirs(os.path.dirname(os.path.abspath(working_copy_path)), exist_ok=True)
        shutil.copy2(template_path, working_copy_path)
        return working_copy_path

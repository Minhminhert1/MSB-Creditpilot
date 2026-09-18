"""Domain models for case document intake."""

from dataclasses import dataclass, field
from datetime import datetime
import re
from typing import Any

from .enums import ProcessingStatus, RegistrationOutcome

_SHA256_REGEX = re.compile(r"^[0-9a-fA-F]{64}$")


def _validate_sha256(checksum: str) -> str:
    """Validate and normalize a SHA-256 checksum string."""
    if not isinstance(checksum, str):
        raise TypeError("Checksum must be a string.")
    normalized = checksum.strip().lower()
    if not _SHA256_REGEX.match(normalized):
        raise ValueError(
            f"Invalid SHA-256 checksum: '{checksum}'. Must be a 64-character hexadecimal string."
        )
    return normalized


@dataclass(frozen=True)
class CaseDocument:
    """A single document registered within a credit proposal case.

    Attributes:
        document_id: Unique identifier for this document record (UUID string).
        case_id: The credit proposal case this document belongs to.
        original_filename: The original filename as provided by the RM / uploader.
            This is a metadata hint only and should not be used as an extraction rule.
        checksum_sha256: 64-character lowercase hexadecimal SHA-256 checksum of content.
        storage_reference: URI or path reference pointing to the document storage location.
        registered_at: Timestamp (UTC) when the document was registered.
        mime_type_hint: Optional MIME type hint (e.g., 'application/pdf').
        processing_status: Lifecycle processing status of the document.
        metadata: Additional metadata dictionary (e.g., file size, source channel).
    """

    document_id: str
    case_id: str
    original_filename: str
    checksum_sha256: str
    storage_reference: str
    registered_at: datetime
    mime_type_hint: str | None = None
    processing_status: ProcessingStatus = ProcessingStatus.REGISTERED
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.document_id, str) or not self.document_id.strip():
            raise ValueError("document_id must be a non-empty string.")
        if not isinstance(self.case_id, str) or not self.case_id.strip():
            raise ValueError("case_id must be a non-empty string.")
        if not isinstance(self.original_filename, str) or not self.original_filename.strip():
            raise ValueError("original_filename must be a non-empty string.")
        if not isinstance(self.storage_reference, str) or not self.storage_reference.strip():
            raise ValueError("storage_reference must be a non-empty string.")
        if not isinstance(self.registered_at, datetime):
            raise TypeError("registered_at must be a datetime instance.")
        if not isinstance(self.processing_status, ProcessingStatus):
            raise TypeError(
                f"processing_status must be a ProcessingStatus enum, got {type(self.processing_status)}."
            )

        # Validate and normalize checksum
        normalized_checksum = _validate_sha256(self.checksum_sha256)
        if normalized_checksum != self.checksum_sha256:
            object.__setattr__(self, "checksum_sha256", normalized_checksum)

        if not isinstance(self.metadata, dict):
            raise TypeError("metadata must be a dictionary.")

    def to_dict(self) -> dict[str, Any]:
        """Deterministic dictionary representation for serialization."""
        return {
            "document_id": self.document_id,
            "case_id": self.case_id,
            "original_filename": self.original_filename,
            "checksum_sha256": self.checksum_sha256,
            "storage_reference": self.storage_reference,
            "registered_at": self.registered_at.isoformat(),
            "mime_type_hint": self.mime_type_hint,
            "processing_status": self.processing_status.value,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CaseDocument":
        """Reconstruct a CaseDocument from a dictionary payload."""
        registered_at_raw = data["registered_at"]
        if isinstance(registered_at_raw, str):
            registered_at = datetime.fromisoformat(registered_at_raw)
        elif isinstance(registered_at_raw, datetime):
            registered_at = registered_at_raw
        else:
            raise TypeError("registered_at must be an ISO format string or datetime.")

        return cls(
            document_id=data["document_id"],
            case_id=data["case_id"],
            original_filename=data["original_filename"],
            checksum_sha256=data["checksum_sha256"],
            storage_reference=data["storage_reference"],
            registered_at=registered_at,
            mime_type_hint=data.get("mime_type_hint"),
            processing_status=ProcessingStatus(
                data.get("processing_status", ProcessingStatus.REGISTERED.value)
            ),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass(frozen=True)
class DocumentRegistrationResult:
    """Outcome of attempting to register a document in a case registry.

    Attributes:
        document: The registered or existing CaseDocument.
        outcome: NEW_DOCUMENT if newly registered, DUPLICATE_CONTENT if duplicate detected.
        message: Optional explanatory message.
    """

    document: CaseDocument
    outcome: RegistrationOutcome
    message: str | None = None

    @property
    def is_duplicate(self) -> bool:
        """True if the registration resolved to an existing duplicate document."""
        return self.outcome == RegistrationOutcome.DUPLICATE_CONTENT

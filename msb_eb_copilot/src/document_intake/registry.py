"""In-memory document registry supporting case-scoped intake and duplicate prevention."""

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from .enums import ProcessingStatus, RegistrationOutcome
from .models import CaseDocument, DocumentRegistrationResult, _validate_sha256


class InMemoryDocumentRegistry:
    """In-memory registry managing case documents and enforcing intake rules.

    Key Rules:
        1. Duplicate detection is strictly scoped to (case_id, checksum_sha256).
        2. Same case + same checksum: duplicate content detected. No new document record
           is created; returns the existing document with DUPLICATE_CONTENT outcome.
        3. Same case + same filename + different checksum: NOT duplicate. Creates new document.
        4. Different cases + same checksum: NOT duplicate. Independent case documents;
           no cross-case leakage or record sharing.
    """

    def __init__(self) -> None:
        # Map: document_id -> CaseDocument
        self._documents_by_id: dict[str, CaseDocument] = {}
        # Map: (case_id, checksum_sha256) -> document_id
        self._case_checksum_index: dict[tuple[str, str], str] = {}
        # Map: case_id -> list of document_id
        self._case_documents_index: dict[str, list[str]] = {}

    def register_document(
        self,
        case_id: str,
        original_filename: str,
        checksum_sha256: str,
        storage_reference: str,
        mime_type_hint: str | None = None,
        document_id: str | None = None,
        registered_at: datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> DocumentRegistrationResult:
        """Register a document for a case, checking for content duplicates.

        Args:
            case_id: The target case identifier.
            original_filename: The original name of the file.
            checksum_sha256: 64-character SHA-256 checksum string.
            storage_reference: Reference / path to stored content.
            mime_type_hint: Optional MIME type hint.
            document_id: Optional custom document ID (generated if not provided).
            registered_at: Optional registration timestamp (defaults to current UTC).
            metadata: Optional dictionary of extra metadata.

        Returns:
            DocumentRegistrationResult with either NEW_DOCUMENT or DUPLICATE_CONTENT.
        """
        if not isinstance(case_id, str) or not case_id.strip():
            raise ValueError("case_id must be a non-empty string.")

        normalized_checksum = _validate_sha256(checksum_sha256)
        scoped_key = (case_id.strip(), normalized_checksum)

        # Check for existing document with same checksum in the same case
        existing_doc_id = self._case_checksum_index.get(scoped_key)
        if existing_doc_id is not None:
            existing_doc = self._documents_by_id[existing_doc_id]
            return DocumentRegistrationResult(
                document=existing_doc,
                outcome=RegistrationOutcome.DUPLICATE_CONTENT,
                message=(
                    f"Duplicate content detected for case '{case_id}' with checksum "
                    f"'{normalized_checksum}'. Existing document ID: '{existing_doc_id}'."
                ),
            )

        # Generate new document
        doc_id = document_id.strip() if document_id else str(uuid4())
        if doc_id in self._documents_by_id:
            raise ValueError(f"Document with ID '{doc_id}' is already registered.")

        reg_time = registered_at if registered_at is not None else datetime.now(timezone.utc)
        meta = dict(metadata) if metadata is not None else {}

        doc = CaseDocument(
            document_id=doc_id,
            case_id=case_id.strip(),
            original_filename=original_filename,
            checksum_sha256=normalized_checksum,
            storage_reference=storage_reference,
            registered_at=reg_time,
            mime_type_hint=mime_type_hint,
            processing_status=ProcessingStatus.REGISTERED,
            metadata=meta,
        )

        self._documents_by_id[doc_id] = doc
        self._case_checksum_index[scoped_key] = doc_id
        self._case_documents_index.setdefault(case_id.strip(), []).append(doc_id)

        return DocumentRegistrationResult(
            document=doc,
            outcome=RegistrationOutcome.NEW_DOCUMENT,
            message=None,
        )

    def get_document(self, document_id: str) -> CaseDocument | None:
        """Retrieve a registered document by its ID."""
        return self._documents_by_id.get(document_id)

    def list_documents_for_case(self, case_id: str) -> list[CaseDocument]:
        """Return all documents registered for the specified case in order of registration."""
        doc_ids = self._case_documents_index.get(case_id.strip(), [])
        return [self._documents_by_id[doc_id] for doc_id in doc_ids]

    def find_by_checksum(self, case_id: str, checksum_sha256: str) -> CaseDocument | None:
        """Find a document in a specific case by its SHA-256 checksum."""
        normalized = _validate_sha256(checksum_sha256)
        doc_id = self._case_checksum_index.get((case_id.strip(), normalized))
        return self._documents_by_id.get(doc_id) if doc_id else None

    def update_status(self, document_id: str, status: ProcessingStatus) -> CaseDocument:
        """Update the processing status of a registered document."""
        doc = self._documents_by_id.get(document_id)
        if doc is None:
            raise KeyError(f"Document with ID '{document_id}' not found.")
        if not isinstance(status, ProcessingStatus):
            raise TypeError(f"status must be a ProcessingStatus enum, got {type(status)}.")

        updated = CaseDocument(
            document_id=doc.document_id,
            case_id=doc.case_id,
            original_filename=doc.original_filename,
            checksum_sha256=doc.checksum_sha256,
            storage_reference=doc.storage_reference,
            registered_at=doc.registered_at,
            mime_type_hint=doc.mime_type_hint,
            processing_status=status,
            metadata=doc.metadata,
        )
        self._documents_by_id[document_id] = updated
        return updated

    def __len__(self) -> int:
        return len(self._documents_by_id)

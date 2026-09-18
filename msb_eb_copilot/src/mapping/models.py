# -*- coding: utf-8 -*-
"""Domain models and exceptions for deterministic legal document mapping."""

from dataclasses import dataclass, field
from typing import Any, Literal


class MappingError(Exception):
    """Base exception for mapping errors."""
    pass


class MappingSchemaError(MappingError):
    """Raised when existing case_data has an invalid or malformed schema structure."""
    pass


@dataclass(frozen=True)
class MappingSourceMetadata:
    """Stable metadata identifying the source document and ingestion mode."""
    source_document: str
    ingestion_mode: Literal["digital", "ocr"]
    extractor: str = "LegalDocumentExtractor"


@dataclass(frozen=True)
class MappingProvenance:
    """Immutable provenance record for a single observed fact in a source document."""
    canonical_path: str
    source_value: str
    mapped_value: Any
    evidence: str
    page: int
    source_document: str
    ingestion_mode: Literal["digital", "ocr"]
    extractor: str = "LegalDocumentExtractor"
    resolved_unit: str | None = None
    unit_evidence: str | None = None
    accounting_code: str | None = None
    semantic_label: str | None = None

    @property
    def identity_key(self) -> tuple[str, str, int, str]:
        """Stable deduplication identity: (canonical_path, source_document, page, source_value)."""
        return (self.canonical_path, self.source_document, self.page, self.source_value)


@dataclass(frozen=True)
class MappingConflict:
    """Surfaced when an existing canonical value contradicts a newly extracted valid observation."""
    canonical_path: str
    existing_value: Any
    extracted_value: Any
    evidence: str
    page: int
    source_document: str
    resolution_status: str = "UNRESOLVED"
    resolved_by: str | None = None

    @property
    def identity_key(self) -> tuple[str, Any, Any, str, int]:
        """Stable deduplication identity: (canonical_path, existing_value, extracted_value, source_document, page)."""
        return (
            self.canonical_path,
            self.existing_value,
            self.extracted_value,
            self.source_document,
            self.page,
        )


@dataclass(frozen=True)
class MappingWarning:
    """Surfaced when an extracted value cannot be deterministically normalized or converted."""
    canonical_path: str
    source_value: str
    reason: str
    evidence: str
    page: int
    source_document: str

    @property
    def extracted_value(self) -> str:
        """Alias for source_value for API serialization consistency."""
        return self.source_value

    @property
    def identity_key(self) -> tuple[str, str, str, int]:
        """Stable deduplication identity: (canonical_path, source_value, source_document, page)."""
        return (self.canonical_path, self.source_value, self.source_document, self.page)


@dataclass(frozen=True)
class CanonicalMappingResult:
    """Complete output of mapping document extractions to canonical case data."""
    case_data: dict[str, Any]
    provenance: dict[str, tuple[MappingProvenance, ...]]
    conflicts: tuple[MappingConflict, ...] = ()
    warnings: tuple[MappingWarning, ...] = ()
    updated_fields: tuple[str, ...] = ()

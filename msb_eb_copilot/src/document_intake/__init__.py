"""Generic document intake and registration interface for MSB Credit Proposal Copilot.

This package handles document ingestion, metadata registration, and deduplication
across cases. It is intentionally independent of proposal sections so that Sections
A, B, C, D, and E can share the same intake models and registry.
"""

from .enums import ProcessingStatus, RegistrationOutcome
from .models import CaseDocument, DocumentRegistrationResult
from .registry import InMemoryDocumentRegistry

__all__ = [
    "CaseDocument",
    "DocumentRegistrationResult",
    "InMemoryDocumentRegistry",
    "ProcessingStatus",
    "RegistrationOutcome",
]

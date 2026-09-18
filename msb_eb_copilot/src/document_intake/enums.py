"""Enums for the Document Intake foundation."""

from enum import Enum


class ProcessingStatus(str, Enum):
    """Current processing lifecycle status for a registered document."""

    REGISTERED = "REGISTERED"
    PENDING = "PENDING"
    PROCESSED = "PROCESSED"
    FAILED = "FAILED"


class RegistrationOutcome(str, Enum):
    """Result category of attempting to register a document in a case."""

    NEW_DOCUMENT = "NEW_DOCUMENT"
    DUPLICATE_CONTENT = "DUPLICATE_CONTENT"

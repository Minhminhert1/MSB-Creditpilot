"""Domain models for document classification results."""

from dataclasses import dataclass, field
from typing import Any

from .enums import DocumentClass, Modality


@dataclass(frozen=True)
class DocumentClassificationResult:
    """The result of classifying a case document semantically.

    Attributes:
        document_id: Identifier of the document being classified.
        document_class: Classified semantic type.
        modality: Modality route (e.g. TEXT_PDF, SCANNED_IMAGE_PDF for OCR, etc.).
        confidence: Confidence score in [0.0, 1.0].
        detected_markers: Tuple of semantic textual markers or signatures detected.
        needs_rm_confirmation: True if confidence is below threshold or classification is ambiguous.
        notes: Optional explanation or error notes.
    """

    document_id: str
    document_class: DocumentClass
    modality: Modality
    confidence: float
    detected_markers: tuple[str, ...] = ()
    needs_rm_confirmation: bool = False
    notes: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.document_id, str) or not self.document_id.strip():
            raise ValueError("document_id must be a non-empty string.")
        if not isinstance(self.document_class, DocumentClass):
            raise TypeError(f"document_class must be a DocumentClass enum, got {type(self.document_class)}.")
        if not isinstance(self.modality, Modality):
            raise TypeError(f"modality must be a Modality enum, got {type(self.modality)}.")
        if not isinstance(self.confidence, (int, float)) or isinstance(self.confidence, bool):
            raise TypeError("confidence must be a float.")
        if not (0.0 <= float(self.confidence) <= 1.0):
            raise ValueError(f"confidence must be in [0.0, 1.0], got {self.confidence}.")
        if not isinstance(self.detected_markers, tuple):
            object.__setattr__(self, "detected_markers", tuple(self.detected_markers))

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "document_class": self.document_class.value,
            "modality": self.modality.value,
            "confidence": float(self.confidence),
            "detected_markers": list(self.detected_markers),
            "needs_rm_confirmation": self.needs_rm_confirmation,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DocumentClassificationResult":
        return cls(
            document_id=data["document_id"],
            document_class=DocumentClass(data["document_class"]),
            modality=Modality(data["modality"]),
            confidence=float(data["confidence"]),
            detected_markers=tuple(data.get("detected_markers", ())),
            needs_rm_confirmation=bool(data.get("needs_rm_confirmation", False)),
            notes=data.get("notes"),
        )

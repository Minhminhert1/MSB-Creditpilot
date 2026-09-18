"""Evidence and provenance models for Section A candidate facts."""

from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from .enums import CandidateStatus, SourceCategory


ScalarValue = str | int | Decimal | bool
FactValuePayload = ScalarValue | tuple[str, ...]


def _validate_payload(value: Any) -> None:
    if isinstance(value, bool):
        return
    if isinstance(value, (str, int, Decimal)):
        return
    if isinstance(value, tuple) and all(isinstance(item, str) for item in value):
        return
    raise TypeError(f"Unsupported fact value payload type: {type(value).__name__}")


def _serialize_value(value: Any) -> Any:
    if value is None:
        return None
    _validate_payload(value)
    if isinstance(value, Decimal):
        return {"kind": "decimal", "value": str(value)}
    if isinstance(value, tuple):
        return {"kind": "tuple", "value": list(value)}
    if isinstance(value, bool):
        return {"kind": "bool", "value": value}
    if isinstance(value, int):
        return {"kind": "int", "value": value}
    if isinstance(value, str):
        return {"kind": "str", "value": value}
    raise TypeError(f"Unsupported fact value payload type: {type(value).__name__}")


@dataclass(frozen=True)
class Provenance:
    """Where a candidate was observed in a specific case.

    Filename, page, sheet, and cell references are provenance only. They must
    not be reused as extraction rules for future customers.
    """

    document_id: str | None = None
    original_filename: str | None = None
    document_type: str | None = None
    page_number: int | None = None
    sheet_name: str | None = None
    cell_range: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvidenceCandidate:
    """One candidate value plus its supporting evidence."""

    canonical_key: str
    candidate_value: FactValuePayload
    source_category: SourceCategory
    normalized_value: FactValuePayload | None = None
    provenance: Provenance = field(default_factory=Provenance)
    snippet: str | None = None
    extraction_method: str | None = None
    confidence: float | None = None
    unit: str | None = None
    period_context: str | None = None
    date_context: str | None = None
    evidence_label: str | None = None
    notes: str | None = None
    status: CandidateStatus = CandidateStatus.CANDIDATE

    def __post_init__(self) -> None:
        _validate_payload(self.candidate_value)
        if self.normalized_value is not None:
            _validate_payload(self.normalized_value)
        if self.confidence is None:
            return
        if isinstance(self.confidence, bool) or not isinstance(self.confidence, (int, float)):
            raise TypeError("confidence must be a numeric score between 0.0 and 1.0 inclusive.")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0 inclusive.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_key": self.canonical_key,
            "candidate_value": _serialize_value(self.candidate_value),
            "normalized_value": _serialize_value(self.normalized_value) if self.normalized_value is not None else None,
            "source_category": self.source_category.value,
            "provenance": self.provenance.to_dict(),
            "snippet": self.snippet,
            "extraction_method": self.extraction_method,
            "confidence": self.confidence,
            "unit": self.unit,
            "period_context": self.period_context,
            "date_context": self.date_context,
            "evidence_label": self.evidence_label,
            "notes": self.notes,
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvidenceCandidate":
        candidate_value = _deserialize_payload(data["candidate_value"])
        normalized = data.get("normalized_value")
        return cls(
            canonical_key=data["canonical_key"],
            candidate_value=candidate_value,
            normalized_value=_deserialize_payload(normalized) if normalized is not None else None,
            source_category=SourceCategory(data["source_category"]),
            provenance=Provenance(**data.get("provenance", {})),
            snippet=data.get("snippet"),
            extraction_method=data.get("extraction_method"),
            confidence=data.get("confidence"),
            unit=data.get("unit"),
            period_context=data.get("period_context"),
            date_context=data.get("date_context"),
            evidence_label=data.get("evidence_label"),
            notes=data.get("notes"),
            status=CandidateStatus(data.get("status", CandidateStatus.CANDIDATE.value)),
        )


def _deserialize_payload(value: Any) -> Any:
    if value is None:
        return None
    if not isinstance(value, dict) or "kind" not in value:
        _validate_payload(value)
        return value
    kind = value["kind"]
    payload = value.get("value")
    if kind == "str":
        if not isinstance(payload, str):
            raise TypeError("Serialized str payload must contain a string value.")
        return payload
    if kind == "int":
        if isinstance(payload, bool) or not isinstance(payload, int):
            raise TypeError("Serialized int payload must contain an integer value.")
        return payload
    if kind == "bool":
        if not isinstance(payload, bool):
            raise TypeError("Serialized bool payload must contain a boolean value.")
        return payload
    if kind == "decimal":
        if not isinstance(payload, str):
            raise TypeError("Serialized decimal payload must contain a string value.")
        try:
            return Decimal(payload)
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("Serialized decimal payload is not a valid Decimal string.") from exc
    if kind == "tuple":
        if not isinstance(payload, list) or not all(isinstance(item, str) for item in payload):
            raise TypeError("Serialized tuple payload must contain a list of strings.")
        return tuple(payload)
    raise TypeError(f"Unsupported serialized payload kind: {kind}")

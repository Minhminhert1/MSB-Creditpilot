# -*- coding: utf-8 -*-
"""Phase 6 Narrative Intelligence Layer.

Module: msb_eb_copilot.src.narrative
"""

from .models import (
    CreditNarrativePackage,
    FactAuthority,
    FactCompleteness,
    FactItem,
    FactManifest,
    FactNature,
    GenerationStatus,
    InsightCandidate,
    InsightVerificationError,
    NarrativeBlock,
    NarrativeGenerationRecord,
    NarrativeTargetBinding,
    NarrativeValidationError,
    StaleNarrativeGenerationError,
    SupportedInsightType,
    TrendDirection,
    VerificationStatus,
    VerifiedInsight,
)
from .fact_packager import FactPackager
from .insight_discovery import GLMInsightDiscoveryAgent
from .insight_verifier import PythonInsightVerifier
from .narrative_agent import GLMNarrativeWriterAgent
from .validator import DeterministicNarrativeValidator
from .store import NARRATIVE_DRAFT_STORE, NarrativeDraftManager

__all__ = [
    "CreditNarrativePackage",
    "FactAuthority",
    "FactCompleteness",
    "FactItem",
    "FactManifest",
    "FactNature",
    "GenerationStatus",
    "InsightCandidate",
    "InsightVerificationError",
    "NarrativeBlock",
    "NarrativeGenerationRecord",
    "NarrativeTargetBinding",
    "NarrativeValidationError",
    "StaleNarrativeGenerationError",
    "SupportedInsightType",
    "TrendDirection",
    "VerificationStatus",
    "VerifiedInsight",
    "FactPackager",
    "GLMInsightDiscoveryAgent",
    "PythonInsightVerifier",
    "GLMNarrativeWriterAgent",
    "DeterministicNarrativeValidator",
    "NARRATIVE_DRAFT_STORE",
    "NarrativeDraftManager",
]

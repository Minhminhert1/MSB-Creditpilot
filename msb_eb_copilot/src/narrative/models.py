# -*- coding: utf-8 -*-
"""Pydantic v2 data models for Phase 6: Grounded Credit Narrative Layer.

Module: msb_eb_copilot.src.narrative.models
Principles:
- Strict typing (extra='forbid')
- Deterministic hashing
- Immutable fact items
- Server-authoritative lifecycle
"""

from __future__ import annotations
from datetime import datetime
from enum import Enum
import hashlib
import json
from typing import Any, Dict, List, Optional, Set
import uuid
from pydantic import BaseModel, ConfigDict, Field


class FactAuthority(str, Enum):
    SOURCE_FACT = "SOURCE_FACT"        # Extracted from authoritative primary document
    SOURCE_CLAIM = "SOURCE_CLAIM"      # Unverified claim stated by enterprise in profile
    RM_INPUT = "RM_INPUT"              # Explicitly entered or judged by RM
    DERIVED_PYTHON = "DERIVED_PYTHON"  # Authoritatively calculated by deterministic Python


class FactNature(str, Enum):
    OBJECTIVE_FACT = "OBJECTIVE_FACT"  # Audited, verifiable data point
    SOURCE_CLAIM = "SOURCE_CLAIM"      # Subjective enterprise representation
    DERIVED_METRIC = "DERIVED_METRIC"  # Ratio, growth rate, or aggregate
    RM_JUDGMENT = "RM_JUDGMENT"        # Professional qualitative credit judgment
    DATA_GAP = "DATA_GAP"              # Known missing, unconfirmed, or incomplete item


class FactCompleteness(str, Enum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    ESTIMATED = "ESTIMATED"


class FactItem(BaseModel):
    """Immutable, typed canonical business fact item."""
    model_config = ConfigDict(extra="forbid", frozen=True)

    fact_id: str = Field(..., description="Unique alphanumeric identifier (e.g. FIN_REV_2024, BIZ_MODEL, CIC_DEBT_GROUP)")
    section: str = Field(..., description="Origin section: LEGAL | BUSINESS | FINANCIAL | CREDIT_REQUEST | DEBT_SERVICE | CIC | DATA_GAPS")
    canonical_path: str = Field(..., description="Dotted path in case_data (e.g. section_d.net_revenue[2024])")
    label: str = Field(..., description="Human-readable Vietnamese label (e.g. Doanh thu thuần năm 2024)")
    value: Any = Field(..., description="Authoritative typed value (float, int, str, bool, list, dict)")
    unit: Optional[str] = Field(None, description="Standardized unit: TRIEU_VND | TY_VND | PERCENT | RATIO | DAYS | MONTHS | YEAR | COUNT | TEXT")
    period: Optional[str] = Field(None, description="Temporal period if applicable (e.g. 2022, 2023, 2024, 2025-01-15)")
    authority: FactAuthority = Field(..., description="Authoritative provenance origin")
    fact_nature: FactNature = Field(..., description="Epistemic classification of fact")
    completeness: FactCompleteness = Field(default=FactCompleteness.COMPLETE, description="Data completeness status")
    source_attribution: Optional[str] = Field(None, description="Required narrative prefix if SOURCE_CLAIM")
    display_representations: List[str] = Field(
        default_factory=list,
        description="Allowed string representations in narrative (e.g. ['120000', '120.000', '120.000 triệu đồng', '120 tỷ đồng'])"
    )

    def to_canonical_dict(self) -> Dict[str, Any]:
        """Convert to deterministic dictionary for manifest hashing."""
        return {
            "fact_id": self.fact_id,
            "section": self.section,
            "canonical_path": self.canonical_path,
            "label": self.label,
            "value": self.value,
            "unit": self.unit,
            "period": self.period,
            "authority": self.authority.value,
            "fact_nature": self.fact_nature.value,
            "completeness": self.completeness.value,
            "source_attribution": self.source_attribution,
            "display_representations": sorted(self.display_representations),
        }


class FactManifest(BaseModel):
    """Immutable collection of all verified canonical facts for a case."""
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    manifest_hash: str = Field(..., description="SHA-256 hash of all canonical fact items in canonical order")
    
    # Categorized Fact Inventories (indexed by fact_id)
    legal_facts: Dict[str, FactItem] = Field(default_factory=dict)
    business_facts: Dict[str, FactItem] = Field(default_factory=dict)
    financial_facts: Dict[str, FactItem] = Field(default_factory=dict)
    credit_request_facts: Dict[str, FactItem] = Field(default_factory=dict)
    debt_service_facts: Dict[str, FactItem] = Field(default_factory=dict)
    cic_facts: Dict[str, FactItem] = Field(default_factory=dict)
    data_gaps: List[FactItem] = Field(default_factory=list)

    def get_fact(self, fact_id: str) -> Optional[FactItem]:
        all_dicts = [
            self.legal_facts, self.business_facts, self.financial_facts,
            self.credit_request_facts, self.debt_service_facts, self.cic_facts
        ]
        for d in all_dicts:
            if fact_id in d:
                return d[fact_id]
        for gap in self.data_gaps:
            if gap.fact_id == fact_id:
                return gap
        return None

    @property
    def facts(self) -> List[FactItem]:
        return self.get_all_facts()

    def get_all_facts(self) -> List[FactItem]:
        all_items = []
        for d in [self.legal_facts, self.business_facts, self.financial_facts,
                  self.credit_request_facts, self.debt_service_facts, self.cic_facts]:
            all_items.extend(d.values())
        all_items.extend(self.data_gaps)
        return sorted(all_items, key=lambda x: x.fact_id)

    def get_entity_allow_list(self) -> Set[str]:
        """Dynamically extract known entity names (company, banks, persons, suppliers, customers)."""
        entities: Set[str] = set()
        for fact in self.get_all_facts():
            val = fact.value
            if isinstance(val, str) and len(val.strip()) > 1:
                if fact.fact_id in ("LEGAL_NAME", "LEGAL_SHORT_NAME", "LEGAL_REP_NAME", "PARENT_GROUP"):
                    entities.add(val.strip())
                elif "BANK" in fact.fact_id or "INSTITUTION" in fact.fact_id:
                    entities.add(val.strip())
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, dict):
                        for k in ("name", "bank_name", "title"):
                            if k in item and isinstance(item[k], str):
                                entities.add(item[k].strip())
        entities.update({"MSB", "Ngân hàng TMCP Hàng Hải Việt Nam", "TCTD", "NHNN", "CIC"})
        return entities


class TrendDirection(str, Enum):
    INCREASE = "INCREASE"
    DECREASE = "DECREASE"
    STABLE = "STABLE"
    VOLATILE = "VOLATILE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class SupportedInsightType(str, Enum):
    GROWTH = "GROWTH"
    DECLINE = "DECLINE"
    ABSOLUTE_DELTA = "ABSOLUTE_DELTA"
    TREND_DIRECTION = "TREND_DIRECTION"
    MARGIN_CHANGE = "MARGIN_CHANGE"
    RATIO_CHANGE = "RATIO_CHANGE"
    WORKING_CAPITAL_CHANGE = "WORKING_CAPITAL_CHANGE"
    LIQUIDITY_OBSERVATION = "LIQUIDITY_OBSERVATION"
    LEVERAGE_OBSERVATION = "LEVERAGE_OBSERVATION"
    PROFITABILITY_OBSERVATION = "PROFITABILITY_OBSERVATION"
    CASH_CONVERSION_OBSERVATION = "CASH_CONVERSION_OBSERVATION"
    CUSTOMER_CONCENTRATION = "CUSTOMER_CONCENTRATION"
    SUPPLIER_CONCENTRATION = "SUPPLIER_CONCENTRATION"
    CROSS_METRIC_RELATIONSHIP = "CROSS_METRIC_RELATIONSHIP"


class InsightCandidate(BaseModel):
    """GLM-5.2 proposed insight candidate."""
    model_config = ConfigDict(extra="forbid")

    insight_id: str = Field(..., description="Unique client/model ID (e.g. INS_REV_GROWTH_2023_2024)")
    insight_type: str = Field(..., description="Must match SupportedInsightType whitelist")
    metric: str = Field(..., description="Target financial or operational metric name")
    related_fact_ids: List[str] = Field(..., min_length=1, description="Fact IDs referenced to support this observation")
    from_period: Optional[str] = Field(None, description="Starting period (e.g. 2023)")
    to_period: Optional[str] = Field(None, description="Ending period (e.g. 2024)")
    proposed_value: Optional[float] = Field(None, description="Numeric result proposed by GLM (growth %, delta, ratio)")
    proposed_unit: Optional[str] = Field(None, description="Proposed unit: PERCENT | TRIEU_VND | RATIO | DAYS")
    trend: TrendDirection = Field(default=TrendDirection.NOT_APPLICABLE)
    observation: str = Field(..., description="Qualitative insight in Vietnamese")
    materiality_reason: str = Field(..., description="Credit justification why this metric or pattern matters")


class VerificationStatus(str, Enum):
    VERIFIED = "VERIFIED"                                # Math matches exactly within tolerance (<= 0.05%)
    CORRECTED_AND_VERIFIED = "CORRECTED_AND_VERIFIED"    # Concept valid, math corrected by Python
    REJECTED_QUANTITATIVE_MISMATCH = "REJECTED_QUANTITATIVE_MISMATCH" # Math contradicted facts
    REJECTED_MISSING_FACTS = "REJECTED_MISSING_FACTS"    # Unknown or missing fact IDs
    REJECTED_INVALID_CONCEPT = "REJECTED_INVALID_CONCEPT"# Direction or relationship contradicted facts
    REJECTED_UNSUPPORTED_CAUSAL = "REJECTED_UNSUPPORTED_CAUSAL" # Unsupported causal claims (do, nhờ, dẫn đến)
    INCOMPLETE = "INCOMPLETE"                            # Underlying facts incomplete
    NOT_APPLICABLE = "NOT_APPLICABLE"


class VerifiedInsight(BaseModel):
    """Python-verified insight ready for trusted narrative consumption."""
    model_config = ConfigDict(extra="forbid")

    insight_id: str
    status: VerificationStatus
    insight_type: str
    metric: str
    fact_ids: List[str]

    # Authoritative Values
    @property
    def verification_status(self) -> VerificationStatus:
        return self.status

    @property
    def difference_pct(self) -> float:
        if self.verified_value is not None and self.model_proposed_value is not None and self.verified_value != 0:
            return round(abs(self.verified_value - self.model_proposed_value) / abs(self.verified_value) * 100.0, 2)
        return 0.0

    verified_value: Optional[float] = Field(None, description="Authoritative Python-calculated number")
    model_proposed_value: Optional[float] = Field(None, description="Original value proposed by GLM")
    unit: Optional[str] = None
    trend: TrendDirection

    # Text and Traceability
    observation: str = Field(..., description="Audited textual observation")
    verification_formula: str = Field(..., description="Deterministic formula used by Python")
    data_quality: str = Field("HIGH", description="HIGH | MEDIUM | LOW | UNVERIFIED")
    warnings: List[str] = Field(default_factory=list)
    display_representations: List[str] = Field(default_factory=list, description="Allowed text formats for narrative")


class NarrativeTargetBinding(str, Enum):
    """Approved neutral target bindings for proposal templates."""
    BUSINESS_OVERVIEW = "business_overview"
    MANAGEMENT_SUMMARY = "management_summary"
    SUPPLY_CHAIN_SUMMARY = "supply_chain_summary"
    MARKET_SUMMARY = "market_summary"
    PNL_ANALYSIS = "pnl_analysis"
    BALANCE_SHEET_ANALYSIS = "balance_sheet_analysis"
    WORKING_CAPITAL_ANALYSIS = "working_capital_analysis"
    LIQUIDITY_ANALYSIS = "liquidity_analysis"
    LEVERAGE_ANALYSIS = "leverage_analysis"
    CIC_SUMMARY = "cic_summary"
    CREDIT_REQUEST_SUMMARY = "credit_request_summary"
    RISK_OBSERVATION_SUMMARY = "risk_observation_summary"


class NarrativeBlock(BaseModel):
    """Individual narrative section generated by GLM-5.2 and validated by Python."""
    model_config = ConfigDict(extra="forbid")

    section: str = Field(..., description="BUSINESS | FINANCIAL | CIC | CREDIT_REQUEST")
    target_binding: NarrativeTargetBinding = Field(..., description="Whitelisted template placeholder target")
    title: str = Field(..., description="Heading for proposal section")
    text: str = Field(..., description="Grounded credit analysis prose in Vietnamese")
    facts_used: List[str] = Field(..., min_length=1, description="List of valid fact_ids from FactManifest")
    insights_used: List[str] = Field(default_factory=list, description="List of verified insight_ids")
    data_gaps: List[str] = Field(default_factory=list, description="Explicit data gaps acknowledged in prose")


class CreditNarrativePackage(BaseModel):
    """Collection of narrative blocks produced for a case."""
    model_config = ConfigDict(extra="forbid")

    case_id: str
    generation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    fact_manifest_hash: str
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    model_id: str = "z-ai/glm-5.2-hackathon"
    narrative_blocks: List[NarrativeBlock] = Field(default_factory=list)


class GenerationStatus(str, Enum):
    GENERATED = "GENERATED"
    INSIGHTS_VERIFIED = "INSIGHTS_VERIFIED"
    NARRATIVE_VALIDATED = "NARRATIVE_VALIDATED"
    RM_REVIEWED = "RM_REVIEWED"
    ACCEPTED_FOR_RENDERING = "ACCEPTED_FOR_RENDERING"
    REJECTED = "REJECTED"


class NarrativeGenerationRecord(BaseModel):
    """External server-side workflow record stored in NARRATIVE_DRAFT_STORE."""
    model_config = ConfigDict(extra="forbid")

    generation_id: str
    case_id: str
    fact_manifest_hash: str
    status: GenerationStatus

    # Audit & Intermediate Artefacts
    fact_manifest: FactManifest
    insight_candidates: List[InsightCandidate] = Field(default_factory=list)
    verified_insights: List[VerifiedInsight] = Field(default_factory=list)
    narrative_blocks: Dict[str, NarrativeBlock] = Field(default_factory=dict)  # keyed by target_binding.value
    validation_results: List[Dict[str, Any]] = Field(default_factory=list)

    # Server & Model Telemetry
    model_id: str = "z-ai/glm-5.2-hackathon"
    telemetry: Dict[str, Any] = Field(default_factory=dict)
    created_at: str

    # RM Review Lifecycle
    rm_edits: Dict[str, str] = Field(default_factory=dict, description="RM edited text keyed by target_binding")
    accepted_bindings: List[str] = Field(default_factory=list, description="Target bindings approved by RM for rendering")

    @property
    def accepted_block_ids(self) -> List[str]:
        return self.accepted_bindings

    @property
    def blocks(self) -> Dict[str, NarrativeBlock]:
        return self.narrative_blocks


# Exceptions
class NarrativeValidationError(Exception):
    """Raised when generated or RM-edited narrative fails deterministic validation."""
    def __init__(self, message: str, code: str = "VALIDATION_FAILED", token: Optional[str] = None, binding: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.token = token
        self.binding = binding


class StaleNarrativeGenerationError(Exception):
    """Raised when canonical case facts have mutated since narrative generation."""
    pass


class InsightVerificationError(Exception):
    """Raised on critical verification calculation fault."""
    pass

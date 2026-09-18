# -*- coding: utf-8 -*-
"""GLM-5.2 Credit Insight Discovery Agent.

Module: msb_eb_copilot.src.narrative.insight_discovery
Principles:
- Reads FactManifest only.
- Discovers multi-period trends, cross-metric patterns, and concentration observations.
- Outputs strict JSON matching List[InsightCandidate].
- Uses GreenNode GLM-5.2 (z-ai/glm-5.2-hackathon).
"""

from __future__ import annotations
import json
import re
from typing import Any, Dict, List, Optional, Tuple

from pydantic import ValidationError

from .models import (
    FactManifest,
    InsightCandidate,
    SupportedInsightType,
    TrendDirection,
)
from ..ai_client import AIAssistantClient


DISCOVERY_SYSTEM_PROMPT = """You are an Expert Large Corporate Credit Risk Analyst.
Your task is to inspect the provided FactManifest containing confirmed business and financial facts of an enterprise, and propose insightful quantitative and qualitative credit observations (InsightCandidate[]).

ABSOLUTE RULES:
1. Propose observations ONLY from the supported insight_type whitelist:
   - GROWTH (YoY or multi-period percentage growth)
   - DECLINE (YoY or multi-period percentage decline)
   - ABSOLUTE_DELTA (numerical difference V_to - V_from)
   - TREND_DIRECTION (multi-year directional pattern: INCREASE, DECREASE, STABLE)
   - MARGIN_CHANGE (change in gross margin or net margin)
   - RATIO_CHANGE (change in leverage or liquidity ratio)
   - WORKING_CAPITAL_CHANGE (change in WCD or CCC days)
   - LIQUIDITY_OBSERVATION (relationship across current, quick, and cash ratios)
   - LEVERAGE_OBSERVATION (capital structure and D/E trend)
   - PROFITABILITY_OBSERVATION (relative growth of profit vs revenue)
   - CASH_CONVERSION_OBSERVATION (dynamics of DIO, DSO, DPO, CCC)
   - CUSTOMER_CONCENTRATION (maximum customer revenue share)
   - SUPPLIER_CONCENTRATION (maximum supplier purchase share)
   - CROSS_METRIC_RELATIONSHIP (comparison of two related metrics, e.g. receivables growth vs revenue growth)
2. Every candidate MUST reference real fact_id values existing in the FactManifest in related_fact_ids.
3. Observations must be strictly factual credit prose in Vietnamese.
4. DO NOT make ungrounded causal claims ("nhờ mở rộng mạng lưới", "do thị trường phục hồi") unless an explicit qualitative fact is referenced in related_fact_ids. State what happened, not unproven external causes.
5. DO NOT invent risk benchmarks or credit approval conclusions.
6. OUTPUT FORMAT: Return ONLY a valid JSON array of objects conforming to InsightCandidate schema.
No markdown prose outside the JSON block.

Schema per item:
{
  "insight_id": "INS_<METRIC>_<YEARS>",
  "insight_type": "GROWTH" | "DECLINE" | "ABSOLUTE_DELTA" | "TREND_DIRECTION" | "MARGIN_CHANGE" | "RATIO_CHANGE" | "WORKING_CAPITAL_CHANGE" | "LIQUIDITY_OBSERVATION" | "LEVERAGE_OBSERVATION" | "PROFITABILITY_OBSERVATION" | "CASH_CONVERSION_OBSERVATION" | "CUSTOMER_CONCENTRATION" | "SUPPLIER_CONCENTRATION" | "CROSS_METRIC_RELATIONSHIP",
  "metric": "NET_REVENUE" | "NET_PROFIT" | "GROSS_PROFIT" | "DSO" | "DIO" | "DPO" | "CCC" | "CURRENT_RATIO" | "DEBT_TO_EQUITY" | "CUSTOMER_SHARE" | "SUPPLIER_SHARE" | "WCD",
  "related_fact_ids": ["FACT_ID_1", "FACT_ID_2"],
  "from_period": "2023",
  "to_period": "2024",
  "proposed_value": 20.0,
  "proposed_unit": "PERCENT" | "TRIEU_VND" | "RATIO" | "DAYS",
  "trend": "INCREASE" | "DECREASE" | "STABLE" | "VOLATILE" | "NOT_APPLICABLE",
  "observation": "Doanh thu thuần năm 2024 tăng trưởng 20% so với năm 2023.",
  "materiality_reason": "Đánh giá quy mô mở rộng hoạt động kinh doanh của doanh nghiệp."
}
"""


class GLMInsightDiscoveryAgent:
    """Agent that leverages GLM-5.2 to discover patterns across canonical facts."""

    def __init__(self, api_key: Optional[str] = None, model: str = "z-ai/glm-5.2-hackathon"):
        self.api_key = api_key
        self.model = model

    def discover_insights(self, manifest: FactManifest) -> Tuple[List[InsightCandidate], Dict[str, Any]]:
        """Call GreenNode GLM-5.2 to propose insight candidates from FactManifest."""
        # Build structured fact manifest payload for model
        payload = {
            "case_id": manifest.case_id,
            "manifest_hash": manifest.manifest_hash,
            "legal_facts": [f.to_canonical_dict() for f in manifest.legal_facts.values()],
            "business_facts": [f.to_canonical_dict() for f in manifest.business_facts.values()],
            "financial_facts": [f.to_canonical_dict() for f in manifest.financial_facts.values()],
            "credit_request_facts": [f.to_canonical_dict() for f in manifest.credit_request_facts.values()],
            "debt_service_facts": [f.to_canonical_dict() for f in manifest.debt_service_facts.values()],
            "cic_facts": [f.to_canonical_dict() for f in manifest.cic_facts.values()],
            "data_gaps": [f.to_canonical_dict() for f in manifest.data_gaps],
        }

        user_prompt = f"FACT_MANIFEST:\n{json.dumps(payload, indent=2, ensure_ascii=False)}\n\nDiscover and return credit insight candidates as a JSON list:"

        response_text = AIAssistantClient.chat(
            system_prompt=DISCOVERY_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.1,
            max_tokens=2048,
            api_key=self.api_key,
            operation="credit_insight_discovery"
        )

        telemetry_records = AIAssistantClient.get_telemetry(limit=1)
        latest = telemetry_records[0] if telemetry_records else {}
        call_telemetry = {
            "operation": latest.get("operation", "credit_insight_discovery"),
            "model": latest.get("model", self.model),
            "input_tokens": latest.get("input_tokens", 0),
            "output_tokens": latest.get("output_tokens", 0),
            "total_tokens": latest.get("total_tokens", 0),
            "latency_ms": latest.get("latency_ms", 0.0),
        }

        # Parse JSON
        candidates = self._parse_candidates_json(response_text)
        return candidates, call_telemetry

    def _parse_candidates_json(self, raw_text: str) -> List[InsightCandidate]:
        """Parse raw response text into validated InsightCandidate models."""
        cleaned = raw_text.strip()
        m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned)
        if m:
            cleaned = m.group(1).strip()

        data = None
        # Attempt 1: Direct JSON parse
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # Attempt 2: Remove trailing commas before } or ]
        if data is None:
            try:
                fixed = re.sub(r",\s*([\]\}])", r"\1", cleaned)
                data = json.loads(fixed)
            except json.JSONDecodeError:
                pass

        # Attempt 3: Extract outer JSON array [...]
        if data is None:
            arr_match = re.search(r"\[\s*\{[\s\S]*\}\s*\]", cleaned)
            if arr_match:
                try:
                    fixed = re.sub(r",\s*([\]\}])", r"\1", arr_match.group(0))
                    data = json.loads(fixed)
                except json.JSONDecodeError:
                    pass

        # Attempt 4: Parse individual JSON objects item-by-item
        if data is None:
            items = []
            for obj_match in re.finditer(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", cleaned):
                try:
                    obj_fixed = re.sub(r",\s*([\]\}])", r"\1", obj_match.group(0))
                    item_dict = json.loads(obj_fixed)
                    items.append(item_dict)
                except Exception:
                    continue
            if items:
                data = items

        if data is None:
            print(f"[DEBUG] GLM-5.2 raw response failed parsing:\n{raw_text[:1500]}")
            raise ValueError("Failed to parse GLM insight discovery response as JSON.")

        if isinstance(data, dict):
            for k in ("insights", "candidates", "insight_candidates", "items"):
                if k in data and isinstance(data[k], list):
                    data = data[k]
                    break

        if not isinstance(data, list):
            raise ValueError(f"Expected JSON list of candidates, got {type(data)}")

        candidates = []
        for idx, item in enumerate(data):
            try:
                candidate = InsightCandidate.model_validate(item)
                candidates.append(candidate)
            except ValidationError as ve:
                continue

        return candidates

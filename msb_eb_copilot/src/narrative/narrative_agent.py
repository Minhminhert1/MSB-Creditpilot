# -*- coding: utf-8 -*-
"""GLM-5.2 Grounded Credit Narrative Writer Agent.

Module: msb_eb_copilot.src.narrative.narrative_agent
Principles:
- Takes FactManifest + VerifiedInsights (VERIFIED / CORRECTED_AND_VERIFIED only) + DATA_GAPS.
- Rejects unverified insight candidates.
- Uses GreenNode GLM-5.2 (z-ai/glm-5.2-hackathon) with operation="credit_narrative_generation".
- Strictly outputs List[NarrativeBlock].
"""

from __future__ import annotations
import json
import re
from typing import Any, Dict, List, Optional, Tuple

from pydantic import ValidationError

from .models import (
    FactAuthority,
    FactManifest,
    NarrativeBlock,
    NarrativeTargetBinding,
    VerificationStatus,
    VerifiedInsight,
)
from ..ai_client import AIAssistantClient

NARRATIVE_SYSTEM_PROMPT = """You are a Senior Corporate Credit Analyst and Credit Proposal Writer for MSB (Vietnam Maritime Commercial Joint Stock Bank).
Your task is to synthesize CONFIRMED CANONICAL FACTS and INDEPENDENTLY VERIFIED INSIGHTS into professional, grounded credit analysis prose for the MB07 Credit Proposal.

ABSOLUTE NON-NEGOTIABLE PRINCIPLES:
1. STRICT GROUNDING:
   - You may ONLY use facts explicitly provided in INPUT_FACTS and insights in VERIFIED_INSIGHTS.
   - Every number, percentage, ratio, date, or entity name you mention MUST exist in INPUT_FACTS or VERIFIED_INSIGHTS.
   - DO NOT invent numbers, thresholds, benchmarks, or interest rates.
   - DO NOT perform new mathematical calculations.
2. SOURCE ATTRIBUTION FOR SOURCE_CLAIM:
   - For any fact labeled with authority='SOURCE_CLAIM' (such as self-reported market share or business claims), you MUST begin the statement with:
     "Theo hồ sơ doanh nghiệp cung cấp, doanh nghiệp cho biết..." or "Theo báo cáo tự kê khai của doanh nghiệp..."
3. CIC EXTERNAL DEBT COMPLETENESS:
   - If DATA_GAPS indicates external debt is incomplete (e.g. unnormalized foreign currency debt), DO NOT state a single authoritative total debt figure for other banks.
   - You MUST explicitly state that external debt is not fully determinable in VND due to the unconverted foreign currency exposure.
4. CAUSAL LANGUAGE RESTRICTIONS:
   - Do NOT use causal words ("nhờ", "do", "dẫn đến", "khiến", "chủ yếu do") unless an explicit supporting business or qualitative fact is cited.
   - State what happened objectively rather than asserting unverified external causes.
5. NEUTRAL ANALYTICAL ROLE:
   - You write analytical commentary and evaluations.
   - DO NOT make autonomous credit approval decisions, credit sanction recommendations, or policy waivers.
6. TARGET BINDINGS:
   Generate narrative blocks for the following neutral bindings:
   - business_overview (Phần C: Quá trình hình thành & mô hình kinh doanh)
   - management_summary (Phần C: Đánh giá ban điều hành & cổ đông)
   - supply_chain_summary (Phần C: Đánh giá mạng lưới nhà cung cấp & khách hàng)
   - pnl_analysis (Phần D: Phân tích doanh thu, chi phí, lợi nhuận)
   - balance_sheet_analysis (Phần D: Phân tích cơ cấu tài sản & nguồn vốn)
   - working_capital_analysis (Phần D: Phân tích chu chuyển vốn lưu động & chu kỳ tiền mặt)
   - cic_summary (Phần E: Đánh giá quan hệ tín dụng & lịch sử CIC)
   - credit_request_summary (Phần B: Tổng hợp nhu cầu cấp tín dụng & cam kết dòng tiền)

OUTPUT FORMAT:
Return ONLY a valid JSON array of objects conforming to NarrativeBlock schema.
No markdown prose outside the JSON block.

Schema per NarrativeBlock:
{
  "section": "BUSINESS" | "FINANCIAL" | "CIC" | "CREDIT_REQUEST",
  "target_binding": "business_overview" | "management_summary" | "supply_chain_summary" | "market_summary" | "pnl_analysis" | "balance_sheet_analysis" | "working_capital_analysis" | "liquidity_analysis" | "leverage_analysis" | "cic_summary" | "credit_request_summary" | "risk_observation_summary",
  "title": "Tiêu đề phân tích",
  "text": "Lời văn phân tích chuyên nghiệp bằng tiếng Việt...",
  "facts_used": ["FACT_ID_1", "FACT_ID_2"],
  "insights_used": ["INSIGHT_ID_1"],
  "data_gaps": ["DATA_GAP_1"]
}
"""


class GLMNarrativeWriterAgent:
    """Agent that leverages GLM-5.2 to generate grounded credit proposal narratives."""

    def __init__(self, api_key: Optional[str] = None, model: str = "z-ai/glm-5.2-hackathon"):
        self.api_key = api_key
        self.model = model

    def generate_narrative(
        self,
        manifest: FactManifest,
        verified_insights: List[VerifiedInsight],
    ) -> Tuple[List[NarrativeBlock], Dict[str, Any]]:
        """Synthesize verified facts and insights into structured NarrativeBlock[]."""
        # Filter ONLY trusted verified insights
        trusted_insights = [
            i for i in verified_insights
            if i.status in (VerificationStatus.VERIFIED, VerificationStatus.CORRECTED_AND_VERIFIED)
        ]

        # Prepare payload
        facts_payload = [f.to_canonical_dict() for f in manifest.get_all_facts()]
        insights_payload = [
            {
                "insight_id": i.insight_id,
                "insight_type": i.insight_type,
                "metric": i.metric,
                "verified_value": i.verified_value,
                "unit": i.unit,
                "trend": i.trend.value,
                "observation": i.observation,
                "formula": i.verification_formula,
                "fact_ids": i.fact_ids,
            }
            for i in trusted_insights
        ]
        gaps_payload = [g.to_canonical_dict() for g in manifest.data_gaps]

        input_data = {
            "case_id": manifest.case_id,
            "INPUT_FACTS": facts_payload,
            "VERIFIED_INSIGHTS": insights_payload,
            "DATA_GAPS": gaps_payload,
        }

        user_prompt = f"INPUT_DATA:\n{json.dumps(input_data, indent=2, ensure_ascii=False)}\n\nWrite grounded credit proposal narrative blocks as a JSON array:"

        response_text = AIAssistantClient.chat(
            system_prompt=NARRATIVE_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.1,
            max_tokens=3072,
            api_key=self.api_key,
            operation="credit_narrative_generation"
        )

        telemetry_records = AIAssistantClient.get_telemetry(limit=1)
        latest = telemetry_records[0] if telemetry_records else {}
        call_telemetry = {
            "operation": latest.get("operation", "credit_narrative_generation"),
            "model": latest.get("model", self.model),
            "input_tokens": latest.get("input_tokens", 0),
            "output_tokens": latest.get("output_tokens", 0),
            "total_tokens": latest.get("total_tokens", 0),
            "latency_ms": latest.get("latency_ms", 0.0),
        }

        blocks = self._parse_blocks_json(response_text)
        return blocks, call_telemetry

    def _parse_blocks_json(self, raw_text: str) -> List[NarrativeBlock]:
        """Parse raw response text into validated NarrativeBlock models."""
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

        # Attempt 2: Remove trailing commas
        if data is None:
            try:
                fixed = re.sub(r",\s*([\]\}])", r"\1", cleaned)
                data = json.loads(fixed)
            except json.JSONDecodeError:
                pass

        # Attempt 3: Extract outer JSON array
        if data is None:
            arr_match = re.search(r"\[\s*\{[\s\S]*\}\s*\]", cleaned)
            if arr_match:
                try:
                    fixed = re.sub(r",\s*([\]\}])", r"\1", arr_match.group(0))
                    data = json.loads(fixed)
                except json.JSONDecodeError:
                    pass

        # Attempt 4: Parse individual objects
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
            print(f"[DEBUG] GLM-5.2 narrative raw response failed parsing:\n{raw_text[:1500]}")
            raise ValueError("Failed to parse GLM narrative generation response as JSON.")

        if isinstance(data, dict):
            for k in ("blocks", "narrative_blocks", "narratives", "items"):
                if k in data and isinstance(data[k], list):
                    data = data[k]
                    break

        if not isinstance(data, list):
            raise ValueError(f"Expected JSON list of narrative blocks, got {type(data)}")

        blocks = []
        for item in data:
            try:
                block = NarrativeBlock.model_validate(item)
                blocks.append(block)
            except ValidationError as ve:
                continue

        return blocks

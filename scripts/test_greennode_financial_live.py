# -*- coding: utf-8 -*-
"""Live GreenNode Financial Extraction & Python Ratio Calculation Smoke Test.

Usage:
    python scripts/test_greennode_financial_live.py

Hard Rules:
- NEVER print API key or secret credentials.
- GreenNode extracts SOURCE_FACT fields only.
- Python calculates 100% of DERIVED ratios.
- Verify grounding audit against physical pages.
"""

import os
import sys
from dotenv import load_dotenv

load_dotenv()

# Ensure proper encoding and module paths
sys.path.insert(0, ".")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from msb_eb_copilot.src.ai_client import AIAssistantClient
from msb_eb_copilot.src.extraction.financial_extraction import (
    FinancialDocumentExtractor,
    FinancialGroundingAuditor,
)
from msb_eb_copilot.src.ingestion.router import DocumentIngestionRouter
from msb_eb_copilot.src.mapping.financial_mapper import (
    FinancialDocumentMapper,
    compute_canonical_ratios,
    FINANCIAL_SOURCE_FACT_FIELDS,
)
from msb_eb_copilot.src.mapping.models import MappingSourceMetadata


def main():
    print("=" * 80)
    print("MSB COPILOT - PHASE 3A LIVE GREENNODE FINANCIAL DOCUMENT AGENT SMOKE TEST")
    print("=" * 80)

    # 1. Check API Key
    api_key = os.getenv("GREENNODE_API_KEY") or os.getenv("AI_PLATFORM_API_KEY")
    if not api_key:
        print("[!] GREENNODE_API_KEY is not set. Please configure it in .env.")
        print("[!] Exiting live smoke test (offline tests are in tests/test_financial_*.py).")
        return 0

    masked_key = f"{api_key[:4]}...{api_key[-4:]}" if len(api_key) > 8 else "***"
    print(f"[+] GreenNode API Key detected: {masked_key} (Endpoint: {AIAssistantClient.DEFAULT_BASE_URL})")

    # 2. Target Test Fixture (Digital BCTC)
    fixture_path = os.path.join("tests", "fixtures", "bctc", "bctc_synthetic_digital.pdf")
    if not os.path.exists(fixture_path):
        print(f"[!] Fixture not found at {fixture_path}.")
        return 1

    print(f"\n[Step 1] Ingesting Document: {fixture_path}")
    ingestion_res = DocumentIngestionRouter.ingest_document(fixture_path)
    print(f"  - Mode: {ingestion_res.mode}")
    print(f"  - Provider: {ingestion_res.provider}")
    print(f"  - Page count: {ingestion_res.page_count}")
    print(f"  - Tagged text length: {len(ingestion_res.tagged_text)} chars")

    print("\n[Step 2] GreenNode Financial Extraction (z-ai/glm-5.2-hackathon)...")
    extractor = FinancialDocumentExtractor()
    try:
        extraction = extractor.extract(ingestion_res.tagged_text, ingestion_res.page_count)
        print("  [✓] GreenNode returned valid structured financial staging data!")
    except Exception as e:
        print(f"  [X] Extraction failed: {e}")
        return 1

    print(f"  - Document title: {extraction.document_title}")
    print(f"  - Document unit fallback: {extraction.document_unit.unit_raw if extraction.document_unit else 'None'}")
    print(f"  - Extracted periods: {[p.period for p in extraction.periods]}")

    print("\n[Step 3] Grounding Audit (Field evidence containment & accounting code corroboration)...")
    total_audited = 0
    total_warnings = 0
    for period in extraction.periods:
        for f_name in FINANCIAL_SOURCE_FACT_FIELDS:
            field_obj = getattr(period, f_name, None)
            if field_obj and field_obj.value_raw:
                total_audited += 1
                errs = FinancialGroundingAuditor.audit_field(
                    canonical_name=f_name,
                    field_data=field_obj,
                    page_tagged_text=ingestion_res.tagged_text,
                    page_count=ingestion_res.page_count,
                )
                if errs:
                    total_warnings += len(errs)
                    for err in errs:
                        print(f"    [WARN] {period.period} {err}")

    print(f"  [✓] Audited {total_audited} raw financial facts across {len(extraction.periods)} periods. Audit issues: {total_warnings}.")

    print("\n[Step 4] Deterministic Mapping into Canonical section_d...")
    initial_case = {
        "customer": {"name": "CÔNG TY CỔ PHẦN PHÂN PHỐI TỔNG HỢP PSD"},
        "section_d": {
            "years": ["2023"],
            "net_revenue": [6755948.0],
        }
    }
    source_meta = MappingSourceMetadata(
        source_document="bctc_synthetic_digital.pdf",
        ingestion_mode=ingestion_res.mode,
        extractor="FinancialDocumentExtractor",
    )
    map_result = FinancialDocumentMapper.map(initial_case, extraction, source_meta)
    mapped_d = map_result.case_data["section_d"]

    print(f"  - Canonical years aligned: {mapped_d['years']}")
    print(f"  - Net Revenue (triệu VND): {mapped_d.get('net_revenue')}")
    print(f"  - Net Profit After Tax (triệu VND): {mapped_d.get('net_profit_after_tax')}")
    print(f"  - Total Assets (triệu VND): {mapped_d.get('total_assets')}")
    print(f"  - Equity (triệu VND): {mapped_d.get('equity')}")
    print(f"  - Conflicts detected: {len(map_result.conflicts)}")
    print(f"  - Provenance records generated: {len(map_result.provenance)}")

    print("\n[Step 5] Deterministic Python Ratio Calculation (Zero AI Ownership)...")
    ratios = compute_canonical_ratios(mapped_d)
    print("  " + "-" * 60)
    print(f"  {'RATIO':<30} | {'2023':<10} | {'2024':<10} | {'2025':<10}")
    print("  " + "-" * 60)
    for ratio_name, vals in ratios.items():
        str_vals = [f"{v:.2f}" if v is not None else "-" for v in vals]
        # Pad if needed
        while len(str_vals) < 3:
            str_vals.insert(0, "-")
        print(f"  {ratio_name:<30} | {str_vals[0]:<10} | {str_vals[1]:<10} | {str_vals[2]:<10}")
    print("  " + "-" * 60)

    print("\n[✓] PHASE 3A LIVE SMOKE TEST COMPLETED SUCCESSFULLY!")
    return 0


if __name__ == "__main__":
    sys.exit(main())

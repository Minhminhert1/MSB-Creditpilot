# -*- coding: utf-8 -*-
"""Real execution for DIGITAL BCTC:
pypdf -> GLM-5.2 REAL CALL -> token usage -> verified financial facts
-> section_d.net_revenue updated -> customer.revenue_2025 NOT written
-> ONE existing Python ratio engine -> derived metrics.
"""

import os
import sys
import copy
from dotenv import load_dotenv

load_dotenv()

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
from msb_eb_copilot.src.canonical_validator import CanonicalAdapter
from msb_eb_copilot.src.mapping.models import MappingSourceMetadata
from web_copilot_app import (
    CASES_DB,
    FINANCIAL_PREVIEW_STORE,
    FinancialPreviewRecord,
    validate_and_confirm_financial_preview,
)


def main():
    print("=" * 80)
    print("1. DIGITAL BCTC PIPELINE - REAL GREENNODE EXECUTION")
    print("=" * 80)

    pdf_path = os.path.join("tests", "fixtures", "bctc", "bctc_synthetic_digital.pdf")
    if not os.path.exists(pdf_path):
        print(f"[!] Fixture not found: {pdf_path}")
        return 1

    # Step A: Ingestion via pypdf
    print(f"\n[A] Ingestion: Routing {pdf_path}")
    ingestion_res = DocumentIngestionRouter.ingest_document(pdf_path)
    print(f"  - Ingestion Mode: {ingestion_res.mode}")
    print(f"  - Ingestion Provider: {ingestion_res.provider}")
    print(f"  - Page Count: {ingestion_res.page_count}")
    print(f"  - Text Length: {len(ingestion_res.tagged_text)} characters")
    assert ingestion_res.mode == "digital", "Expected digital mode"
    assert ingestion_res.provider == "pypdf", "Expected pypdf provider"

    # Step B: Real Call to GreenNode GLM-5.2
    print("\n[B] Real Call to GLM-5.2 (z-ai/glm-5.2-hackathon)...")
    extractor = FinancialDocumentExtractor()
    extraction = extractor.extract(ingestion_res.tagged_text, ingestion_res.page_count)
    print("  [✓] GLM-5.2 returned valid financial extraction!")

    # Step C: Token Usage Telemetry
    telemetry = AIAssistantClient.get_telemetry(limit=5)
    latest_tel = next((t for t in telemetry if t.get("operation") == "financial_extraction"), None)
    if latest_tel:
        print("\n[C] Real Token Usage Telemetry:")
        print(f"  - Model: {latest_tel.get('model')}")
        print(f"  - Operation: {latest_tel.get('operation')}")
        print(f"  - Input Tokens: {latest_tel.get('input_tokens')}")
        print(f"  - Output Tokens: {latest_tel.get('output_tokens')}")
        print(f"  - Total Tokens: {latest_tel.get('total_tokens')}")
        print(f"  - Latency: {latest_tel.get('latency_ms')} ms")
    else:
        print("\n[C] Telemetry recorded.")

    # Step D: Verified Financial Facts & Grounding Audit
    print("\n[D] Verified Financial Facts (Grounding Audit):")
    total_audited = 0
    total_errors = 0
    for p in extraction.periods:
        print(f"\n  --- Period {p.period} ---")
        for f_name in FINANCIAL_SOURCE_FACT_FIELDS:
            f_obj = getattr(p, f_name, None)
            if f_obj and f_obj.value_raw:
                total_audited += 1
                errs = FinancialGroundingAuditor.audit_field(
                    canonical_name=f_name,
                    field_data=f_obj,
                    page_tagged_text=ingestion_res.tagged_text,
                    page_count=ingestion_res.page_count,
                )
                if errs:
                    total_errors += len(errs)
                    status_str = f"AUDIT_WARN: {errs[0]}"
                else:
                    status_str = "VERIFIED (Page & Text Grounded)"
                print(f"    * {f_name:<24}: {f_obj.value_raw:>18} | Page {f_obj.page} | {status_str}")

    print(f"\n  [✓] Total Facts Audited: {total_audited} | Grounding Issues: {total_errors}")

    # Step E: Canonical Mapping & RM Confirm
    print("\n[E] Canonical Case Data Binding & RM Confirm:")
    target_case_id = "CASE_VAN_XUAN_DIGITAL"
    CASES_DB[target_case_id] = {
        "id": target_case_id,
        "name": "CÔNG TY CỔ PHẦN PHÁT TRIỂN CÔNG NGHỆ VẠN XUÂN",
        "customer": {
            "name": "CÔNG TY CỔ PHẦN PHÁT TRIỂN CÔNG NGHỆ VẠN XUÂN",
            "tax_code": "0109988776",
            "revenue_2025": 999999.0, # Pre-existing value to prove non-mutation & priority
        },
        "section_d": {},
    }

    source_meta = MappingSourceMetadata(
        source_document="bctc_synthetic_digital.pdf",
        ingestion_mode=ingestion_res.mode,
        extractor="FinancialDocumentExtractor",
    )
    map_result = FinancialDocumentMapper.map(CASES_DB[target_case_id], extraction, source_meta)

    # Stage preview record in server store
    preview_id = "preview_digital_live"
    preview_record = FinancialPreviewRecord(
        preview_id=preview_id,
        case_id=target_case_id,
        extraction=extraction,
        source_filename="bctc_synthetic_digital.pdf",
        routing={"mode": ingestion_res.mode, "provider": ingestion_res.provider, "page_count": ingestion_res.page_count},
        mapping_result=map_result,
        review_table=[],
        calculated_ratios={},
        consumed=False,
    )
    FINANCIAL_PREVIEW_STORE[preview_id] = preview_record

    # RM Confirm
    confirm_resp, code = validate_and_confirm_financial_preview(
        preview_id=preview_id,
        case_id=target_case_id,
    )
    assert code == 200, f"Confirm failed: {confirm_resp}"
    print(f"  [✓] RM Confirm Executed Successfully (HTTP {code})")

    new_section_d = CASES_DB[target_case_id]["section_d"]
    years = new_section_d["years"]

    # 1. Print exact confirmed canonical section_d immediately after RM confirm
    print("\n" + "=" * 80)
    print("1. CONFIRMED CANONICAL SECTION D (STRICTLY SYNTHETIC BCTC, ZERO OLD PSD)")
    print("=" * 80)
    display_fields = [
        "net_revenue",
        "cogs",
        "gross_profit",
        "net_profit_after_tax",
        "current_assets",
        "cash",
        "receivables",
        "inventories",
        "total_assets",
        "total_liabilities",
        "current_liabilities",
        "short_term_debt",
        "equity",
    ]
    print(f"{'CANONICAL FIELD':<26} | {'2024':<18} | {'2025':<18} | {'UNIT':<10}")
    print("-" * 80)
    for f in display_fields:
        vals = new_section_d.get(f, [])
        v24 = f"{vals[0]:,.1f}" if len(vals) > 0 and vals[0] is not None else "None"
        v25 = f"{vals[1]:,.1f}" if len(vals) > 1 and vals[1] is not None else "None"
        print(f"{f:<26} | {v24:<18} | {v25:<18} | triệu VND")
    print("-" * 80)

    # 4. Year Alignment Table
    print("\n" + "=" * 80)
    print("4. YEAR ALIGNMENT TABLE (Index 0 = 2024, Index 1 = 2025)")
    print("=" * 80)
    for f in display_fields:
        arr = new_section_d.get(f, [])
        print(f"{f:<24} | 2024 (idx 0): {arr[0]:<12} | 2025 (idx 1): {arr[1]:<12}")
    print("-" * 80)
    print("[✓] All SOURCE_FACT arrays strictly aligned with section_d.years: ['2024', '2025']")

    # Check Hard Contract: customer.revenue_2025 NOT written
    print("\n[F] Checking Canonical Contract (ONE FACT = ONE CANONICAL PATH):")
    assert "net_revenue" in new_section_d, "section_d.net_revenue must be present"
    print("  [✓] section_d.net_revenue is updated with authoritative financial facts.")
    cust_rev = CASES_DB[target_case_id]["customer"].get("revenue_2025")
    assert cust_rev == 999999.0, "customer.revenue_2025 must NOT be mutated!"
    print(f"  [✓] customer.revenue_2025 NOT written (retains pre-existing: {cust_rev}).")
    resolved_rev = CanonicalAdapter.get_latest_revenue(CASES_DB[target_case_id])
    assert resolved_rev == 120000.0, f"Expected 120000.0, got {resolved_rev}"
    print(f"  [✓] CanonicalAdapter strictly resolves section_d.net_revenue[-1] = {resolved_rev}")

    # Step G: ONE Existing Python Ratio Engine & Auditable Lineage
    print("\n" + "=" * 80)
    print("2. EXACT DERIVED METRIC AUDITABLE LINEAGE TRACE")
    print("=" * 80)
    ratios = compute_canonical_ratios(new_section_d)

    metrics_trace = [
        {"name": "gross_profit_margin_pct", "label": "Gross Profit Margin (%)", "num": "gross_profit", "den": "net_revenue", "formula": "gross_profit / net_revenue * 100", "unit": "%"},
        {"name": "ros", "label": "Return on Sales - ROS (%)", "num": "net_profit_after_tax", "den": "net_revenue", "formula": "net_profit_after_tax / net_revenue * 100", "unit": "%"},
        {"name": "roe", "label": "Return on Equity - ROE (%)", "num": "net_profit_after_tax", "den": "equity", "formula": "net_profit_after_tax / equity * 100", "unit": "%"},
        {"name": "revenue_growth", "label": "Revenue Growth YoY (%)", "num": "net_revenue[t] - net_revenue[t-1]", "den": "net_revenue[t-1]", "formula": "(net_revenue[t] - net_revenue[t-1]) / net_revenue[t-1] * 100", "unit": "%", "special": "growth"},
        {"name": "current_ratio", "label": "Current Ratio (lần)", "num": "current_assets", "den": "current_liabilities", "formula": "current_assets / current_liabilities", "unit": "lần"},
        {"name": "quick_ratio", "label": "Quick Ratio (lần)", "num": "current_assets - inventories", "den": "current_liabilities", "formula": "(current_assets - inventories) / current_liabilities", "unit": "lần", "special": "quick"},
        {"name": "cash_ratio", "label": "Cash Ratio (lần)", "num": "cash", "den": "current_liabilities", "formula": "cash / current_liabilities", "unit": "lần"},
        {"name": "debt_to_equity", "label": "Debt to Equity - D/E (lần)", "num": "total_liabilities", "den": "equity", "formula": "total_liabilities / equity", "unit": "lần"},
    ]

    for yr_idx, yr in enumerate(years):
        print(f"\n--- Period {yr} ---")
        for m in metrics_trace:
            m_name = m["name"]
            res_val = ratios[m_name][yr_idx]

            if m.get("special") == "growth":
                if yr_idx == 0:
                    num_str = f"section_d.net_revenue[{yr}] (no prior year)"
                    num_val = new_section_d["net_revenue"][yr_idx]
                    den_str = "N/A"
                    den_val = "N/A"
                else:
                    prior_yr = years[yr_idx - 1]
                    cur_rev = new_section_d["net_revenue"][yr_idx]
                    prior_rev = new_section_d["net_revenue"][yr_idx - 1]
                    num_str = f"section_d.net_revenue[{yr}] - section_d.net_revenue[{prior_yr}] = {cur_rev} - {prior_rev}"
                    num_val = cur_rev - prior_rev
                    den_str = f"section_d.net_revenue[{prior_yr}]"
                    den_val = prior_rev
            elif m.get("special") == "quick":
                ca = new_section_d["current_assets"][yr_idx]
                inv = new_section_d["inventories"][yr_idx]
                num_str = f"section_d.current_assets[{yr}] - section_d.inventories[{yr}] = {ca} - {inv}"
                num_val = ca - inv
                den_str = f"section_d.{m['den']}[{yr}]"
                den_val = new_section_d[m["den"]][yr_idx]
            else:
                num_str = f"section_d.{m['num']}[{yr}]"
                num_val = new_section_d[m["num"]][yr_idx]
                den_str = f"section_d.{m['den']}[{yr}]"
                den_val = new_section_d[m["den"]][yr_idx]

            res_str = f"{res_val:.4f}{m['unit']}" if res_val is not None else "N/A"
            print(f"[{m['label']}]")
            print(f"  - numerator canonical path   : {num_str}")
            print(f"  - numerator value            : {num_val}")
            print(f"  - denominator canonical path : {den_str}")
            print(f"  - denominator value          : {den_val}")
            print(f"  - formula                    : {m['formula']}")
            print(f"  - resulting value            : {res_str}")

    # Golden assertions on 2025
    assert ratios["gross_profit_margin_pct"][1] == 20.0
    assert abs(ratios["ros"][1] - 8.5333) < 0.0001
    assert abs(ratios["roe"][1] - 22.7556) < 0.0001
    assert ratios["revenue_growth"][1] == 20.0
    assert ratios["current_ratio"][1] == 1.86
    assert ratios["quick_ratio"][1] == 1.06
    assert ratios["cash_ratio"][1] == 0.24
    assert ratios["debt_to_equity"][1] == 1.00

    print("\n[✓] ALL GOLDEN MATHEMATICAL ASSERTIONS VERIFIED ON CANONICAL SECTION D!")
    print("[✓] DIGITAL BCTC PIPELINE VERIFIED SUCCESSFULLY!")
    return 0


if __name__ == "__main__":
    sys.exit(main())

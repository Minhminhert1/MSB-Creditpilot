# -*- coding: utf-8 -*-
"""Real execution for DIGITAL Business Document:
pypdf -> GLM-5.2 REAL CALL -> token usage -> verified Business facts
-> grounding audit -> identity reconciliation -> RM review & confirm
-> canonical section_c -> MB07 Section C Word document generation.
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
from msb_eb_copilot.src.extraction.business_extraction import (
    BusinessDocumentExtractor,
    BusinessGroundingAuditor,
    BusinessIdentityReconciler,
    BusinessModelClassifier,
    GroundingAuditResult,
)
from msb_eb_copilot.src.ingestion.router import DocumentIngestionRouter
from msb_eb_copilot.src.mapping.business_mapper import BusinessDocumentMapper
from msb_eb_copilot.src.section_c.models import (
    SectionCData,
    CapitalMilestone,
    ShareholderInfo,
    ManagementMember,
    ProductInfo,
    WarehouseInfo,
    EquipmentInfo,
    SupplierInfo,
    CustomerInfo,
)
from msb_eb_copilot.src.section_c.renderer import SectionCRenderer
from msb_eb_copilot.src.section_c.enums import BusinessModelType, BlacklistStatus
from msb_eb_copilot.src.mapping.models import MappingSourceMetadata
from web_copilot_app import (
    CASES_DB,
    BUSINESS_PREVIEW_STORE,
    BusinessPreviewRecord,
    process_business_pdf_preview,
    confirm_business_preview,
)


def main():
    print("=" * 80)
    print("1. DIGITAL BUSINESS PIPELINE - REAL GREENNODE EXECUTION")
    print("=" * 80)

    pdf_path = os.path.join("tests", "fixtures", "business", "synthetic_business_digital.pdf")
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
    extractor = BusinessDocumentExtractor()
    extraction = extractor.extract(ingestion_res.tagged_text, ingestion_res.page_count)
    print("  [✓] GLM-5.2 returned valid Business extraction!")

    # Step C: Token Usage Telemetry
    telemetry = AIAssistantClient.get_telemetry(limit=5)
    latest_tel = next((t for t in telemetry if t.get("operation") == "business_extraction"), None)
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

    # Step D: Comprehensive Grounding Audit on Every Candidate SOURCE_FACT
    print("\n[D] Grounding Audit on Extracted Business Facts:")
    pages_text, max_p = BusinessGroundingAuditor.extract_pages(ingestion_res.tagged_text)
    all_audits = BusinessGroundingAuditor.audit_all_facts(extraction, pages_text, max_p)

    print("\n  " + "=" * 90)
    print(f"  {'Canonical Candidate Path':<42} | {'Extracted Value':<25} | {'Page':<5} | {'Status'}")
    print("  " + "-" * 90)
    status_counts = {"VERIFIED": 0, "WARNING": 0, "REJECTED": 0, "MISSING": 0}
    for cpath, a_res in all_audits.items():
        v_str = str(a_res.extracted_value)[:23] if a_res.extracted_value is not None else "-"
        p_str = str(a_res.page) if a_res.page else "-"
        st = a_res.status
        status_counts[st] = status_counts.get(st, 0) + 1
        print(f"  {cpath:<42} | {v_str:<25} | {p_str:<5} | {st}")
    print("  " + "-" * 90)
    print(f"  TOTAL FACTS AUDITED: {len(all_audits)}")
    print(f"  STATUS BREAKDOWN: {status_counts}")

    # Step E: Identity Reconciliation Check
    print("\n[E] Identity Reconciliation Check (IDENTITY_CHECK_ONLY):")
    case_id = "CASE-LIVE-BIZ-01"
    CASES_DB[case_id] = {
        "customer": {
            "name": "CÔNG TY CỔ PHẦN CÔNG NGHỆ VÀ TRUYỀN THÔNG ĐÔNG NAM Á",
            "tax_code": "0108889999",
        },
        "section_c": {
            "rm_supply_chain_assessment": "Khách hàng duy trì chuỗi cung ứng ổn định với các đối tác viễn thông hàng đầu.",
            "rm_credit_risk_mitigation": "Doanh nghiệp có dòng tiền thanh toán tốt từ các hợp đồng phân phối thiết bị.",
        },
    }

    doc_tax = extraction.tax_code.value_raw if extraction.tax_code else None
    doc_name = extraction.company_name.value_raw if extraction.company_name else None
    id_status, id_msg = BusinessIdentityReconciler.reconcile(doc_tax, doc_name, CASES_DB[case_id]["customer"])
    print(f"  - Extracted Tax Code: {doc_tax}")
    print(f"  - Extracted Company Name: {doc_name}")
    print(f"  - Case Tax Code: {CASES_DB[case_id]['customer']['tax_code']}")
    print(f"  - Case Company Name: {CASES_DB[case_id]['customer']['name']}")
    print(f"  - Reconciliation Verdict: {id_status} ({id_msg})")
    assert id_status in ("MATCH", "WARNING"), f"Unexpected mismatch: {id_msg}"

    # Step F: Business Model Suggestion
    op_desc = extraction.operating_model_description.value_raw if extraction.operating_model_description else ""
    sug_bm = BusinessModelClassifier.suggest_model(op_desc)
    print(f"\n[F] Operating Model Classification:")
    print(f"  - Operating Description: {op_desc[:80]}...")
    print(f"  - Deterministic Suggestion: {sug_bm} (HON_HOP)")
    assert sug_bm == "HON_HOP", f"Expected HON_HOP, got {sug_bm}"

    # Step G: Server-Authoritative Preview
    print("\n[G] Server-Authoritative Preview Generation:")
    with open(pdf_path, "rb") as f:
        raw_bytes = f.read()
    preview_res, preview_code = process_business_pdf_preview(raw_bytes, os.path.basename(pdf_path), case_id=case_id)
    assert preview_code == 200, f"Preview failed: {preview_res}"
    preview_id = preview_res["preview_id"]
    print(f"  - Preview Status: {preview_res.get('status')}")
    print(f"  - Preview ID: {preview_id}")
    print(f"  - Total Review Items: {len(preview_res.get('review_table', []))}")
    print(f"  - Suggested Business Model: {preview_res.get('suggested_business_model')}")

    # Step H: RM Review & Confirmation
    print("\n[H] RM Review & Confirmation:")
    confirm_res, confirm_code = confirm_business_preview(
        preview_id=preview_id,
        case_id=case_id,
        business_model_override="HON_HOP",
        identity_acknowledged=True,
    )
    assert confirm_code == 200, f"Confirm failed: {confirm_res}"
    print(f"  - Confirm Status: {confirm_res.get('status')}")
    print(f"  - Updated Fields Count: {len(confirm_res.get('updated_fields', []))}")

    # Step I: Inspect Canonical Section C in Case
    sec_c = CASES_DB[case_id]["section_c"]
    print("\n[I] Canonical Section C Content in CASES_DB:")
    print(f"  - business_model: {sec_c.get('business_model')}")
    print(f"  - capital_milestones: {len(sec_c.get('capital_milestones', []))} items")
    for m in sec_c.get('capital_milestones', []):
        print(f"      * {m['effective_date']}: {m['charter_capital_million_vnd']:,.0f} tr VND ({m['event_description']})")
    print(f"  - shareholders: {len(sec_c.get('shareholders', []))} items")
    for s in sec_c.get('shareholders', []):
        print(f"      * {s['name']}: {s['pct']}% (Val: {s['val']:,.0f} tr VND, Major: {s['is_major_shareholder']})")
    print(f"  - management: {len(sec_c.get('management', []))} items")
    for mg in sec_c.get('management', []):
        print(f"      * {mg['title']} - {mg['name']} (Exp: {mg['exp']} years)")
    print(f"  - products: {len(sec_c.get('products', []))} items")
    print(f"  - warehouses: {len(sec_c.get('warehouses', []))} items")
    print(f"  - equipments: {len(sec_c.get('equipments', []))} items")
    print(f"  - suppliers: {len(sec_c.get('suppliers', []))} items")
    for sup in sec_c.get('suppliers', []):
        print(f"      * {sup['name']}: {sup['share']}% (CIC Check: {sup['has_cic_check']})")
    print(f"  - customers: {len(sec_c.get('customers', []))} items")
    print(f"  - top_competitors: {sec_c.get('top_competitors', [])}")
    print(f"  - rm_supply_chain_assessment: {sec_c.get('rm_supply_chain_assessment')}")
    print(f"  - rm_credit_risk_mitigation: {sec_c.get('rm_credit_risk_mitigation')}")

    # Step J: Render MB07 Section C Word Document
    print("\n[J] MB07 Section C Word Document Generation:")
    sh_objs = [
        ShareholderInfo(s["stt"], s["name"], s["tax_code"], s["pct"], s["val"], s["is_major_shareholder"])
        for s in sec_c["shareholders"]
    ]
    mgmt_objs = [
        ManagementMember(m["title"], m["name"], m["note"], m["exp"] or 0)
        for m in sec_c["management"]
    ]
    prod_objs = [
        ProductInfo(i+1, p["name"], p["spec"], p["share"])
        for i, p in enumerate(sec_c["products"])
    ]
    wh_objs = [
        WarehouseInfo(w["stt"], w["facility_type"], w["address"], w["area_m2"], w["ownership_type"], w["capacity_description"])
        for w in sec_c["warehouses"]
    ]
    eq_objs = [
        EquipmentInfo(eq["stt"], eq["equipment_name"], eq["origin_and_technology"], eq["designed_capacity"], eq["utilization_rate"])
        for eq in sec_c["equipments"]
    ]
    sup_objs = [
        SupplierInfo(i+1, s["name"], s["goods"], s["share"], s["term"], s["has_cic_check"])
        for i, s in enumerate(sec_c["suppliers"])
    ]
    cust_objs = [
        CustomerInfo(i+1, c["name"], c["goods"], c["share"], c["term"])
        for i, c in enumerate(sec_c["customers"])
    ]
    ms_objs = [
        CapitalMilestone(m["effective_date"], m["charter_capital_million_vnd"], m["event_description"])
        for m in sec_c["capital_milestones"]
    ]

    bm_enum = BusinessModelType[sec_c["business_model"]] if sec_c["business_model"] in BusinessModelType.__members__ else BusinessModelType.HON_HOP
    data_c = SectionCData(
        customer_name=CASES_DB[case_id]["customer"]["name"],
        history_narrative=sec_c["history_narrative"],
        capital_milestones=ms_objs,
        parent_company_or_owner=sec_c["parent_company_or_owner"],
        major_shareholders=sh_objs,
        blacklist_status=BlacklistStatus.KHONG_VI_PHAM,
        management_members=mgmt_objs,
        business_model=bm_enum,
        products=prod_objs,
        warehouses=wh_objs,
        equipments=eq_objs,
        suppliers=sup_objs,
        customers=cust_objs,
        distribution_channels=sec_c["distribution_channels"],
        market_share_estimate=sec_c["market_share_estimate"],
        top_competitors=sec_c["top_competitors"],
        competitive_advantages=sec_c["competitive_advantages"],
        rm_supply_chain_assessment=sec_c.get("rm_supply_chain_assessment", ""),
        rm_credit_risk_mitigation=sec_c.get("rm_credit_risk_mitigation", ""),
    )

    out_docx = os.path.join("output", "LIVE_GREENNODE_SECTION_C_MB07.docx")
    os.makedirs("output", exist_ok=True)
    SectionCRenderer.generate_docx(data_c, out_docx)
    print(f"  [✓] MB07 Section C Word Document successfully generated: {out_docx}")
    print(f"  - File size: {os.path.getsize(out_docx)} bytes")

    print("\n" + "=" * 80)
    print("DIGITAL BUSINESS PIPELINE VERIFIED SUCCESSFULLY WITH REAL GREENNODE!")
    print("=" * 80)
    return 0


if __name__ == "__main__":
    exit(main())

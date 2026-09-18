# -*- coding: utf-8 -*-
"""Real execution for SCANNED Business Document:
PDFium -> Qwen Vision REAL CALL (qwen/qwen3.6-flash OCR)
-> GLM-5.2 REAL CALL (z-ai/glm-5.2-hackathon structured extraction)
-> token usage -> verified Business facts -> grounding audit
-> identity reconciliation -> RM review & confirm
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
    process_business_pdf_preview,
    confirm_business_preview,
)


def main():
    print("=" * 80)
    print("2. SCANNED BUSINESS PIPELINE - REAL GREENNODE OCR + LLM EXECUTION")
    print("=" * 80)

    pdf_path = os.path.join("tests", "fixtures", "business", "synthetic_business_scanned.pdf")
    if not os.path.exists(pdf_path):
        print(f"[!] Fixture not found: {pdf_path}")
        return 1

    # Step A: Ingestion via PDFium + Qwen Vision OCR
    print(f"\n[A] Ingestion: Routing Scanned PDF {pdf_path}")
    print("  - Digital pass detects zero text layer -> raises PDFBlankPageError")
    print("  - Fallback triggers PDFOCRIngestor (PDFium rasterization + Qwen Vision OCR)")
    ingestion_res = DocumentIngestionRouter.ingest_document(pdf_path)
    print(f"  - Ingestion Mode: {ingestion_res.mode}")
    print(f"  - Ingestion Provider: {ingestion_res.provider}")
    print(f"  - Page Count: {ingestion_res.page_count}")
    print(f"  - Fallback Reason: {ingestion_res.fallback_reason}")
    print(f"  - OCR Text Length: {len(ingestion_res.tagged_text)} characters")
    assert ingestion_res.mode in ("ocr", "scanned"), "Expected ocr mode"
    assert ingestion_res.provider == "qwen_vision", "Expected qwen_vision provider"

    # Step B: OCR Telemetry
    telemetry = AIAssistantClient.get_telemetry(limit=5)
    ocr_tel = next((t for t in telemetry if t.get("operation") == "ocr_page"), None)
    if ocr_tel:
        print("\n[B] Real OCR Token Usage Telemetry (qwen/qwen3.6-flash):")
        print(f"  - Model: {ocr_tel.get('model')}")
        print(f"  - Operation: {ocr_tel.get('operation')}")
        print(f"  - Input Tokens: {ocr_tel.get('input_tokens')}")
        print(f"  - Output Tokens: {ocr_tel.get('output_tokens')}")
        print(f"  - Total Tokens: {ocr_tel.get('total_tokens')}")
        print(f"  - Latency: {ocr_tel.get('latency_ms')} ms")

    # Step C: Real Extraction via GLM-5.2
    print("\n[C] Real Call to GLM-5.2 on OCR Text (z-ai/glm-5.2-hackathon)...")
    extractor = BusinessDocumentExtractor()
    extraction = extractor.extract(ingestion_res.tagged_text, ingestion_res.page_count)
    print("  [✓] GLM-5.2 returned valid Business extraction from scanned document!")

    # Step D: Extraction Telemetry
    telemetry = AIAssistantClient.get_telemetry(limit=5)
    ext_tel = next((t for t in telemetry if t.get("operation") == "business_extraction"), None)
    if ext_tel:
        print("\n[D] Real Extraction Token Usage Telemetry (z-ai/glm-5.2-hackathon):")
        print(f"  - Model: {ext_tel.get('model')}")
        print(f"  - Operation: {ext_tel.get('operation')}")
        print(f"  - Input Tokens: {ext_tel.get('input_tokens')}")
        print(f"  - Output Tokens: {ext_tel.get('output_tokens')}")
        print(f"  - Total Tokens: {ext_tel.get('total_tokens')}")
        print(f"  - Latency: {ext_tel.get('latency_ms')} ms")

    # Step E: Grounding Audit on OCR Text
    print("\n[E] Grounding Audit on Scanned Text:")
    pages_text, max_p = BusinessGroundingAuditor.extract_pages(ingestion_res.tagged_text)
    all_audits = BusinessGroundingAuditor.audit_all_facts(extraction, pages_text, max_p)

    status_counts = {"VERIFIED": 0, "WARNING": 0, "REJECTED": 0, "MISSING": 0}
    for cpath, a_res in all_audits.items():
        st = a_res.status
        status_counts[st] = status_counts.get(st, 0) + 1

    print(f"  TOTAL CANDIDATE FACTS: {len(all_audits)}")
    print(f"  STATUS BREAKDOWN: {status_counts}")
    assert status_counts["VERIFIED"] >= 20, f"Expected >= 20 verified facts from OCR, got {status_counts['VERIFIED']}"

    # Step F: Identity Check & Operating Model Suggestion
    case_id = "CASE-LIVE-BIZ-SCAN-01"
    CASES_DB[case_id] = {
        "customer": {
            "name": "CÔNG TY CỔ PHẦN CÔNG NGHỆ VÀ TRUYỀN THÔNG ĐÔNG NAM Á",
            "tax_code": "0108889999",
        },
        "section_c": {},
    }
    doc_tax = extraction.tax_code.value_raw if extraction.tax_code else None
    doc_name = extraction.company_name.value_raw if extraction.company_name else None
    id_status, id_msg = BusinessIdentityReconciler.reconcile(doc_tax, doc_name, CASES_DB[case_id]["customer"])
    print(f"\n[F] Identity Reconciliation: {id_status} ({id_msg})")
    assert id_status in ("MATCH", "WARNING"), f"Unexpected mismatch: {id_msg}"

    op_desc = extraction.operating_model_description.value_raw if extraction.operating_model_description else ""
    sug_bm = BusinessModelClassifier.suggest_model(op_desc)
    print(f"  - Suggested Business Model: {sug_bm}")

    # Step G: Preview and Confirmation
    with open(pdf_path, "rb") as f:
        raw_bytes = f.read()
    preview_res, preview_code = process_business_pdf_preview(raw_bytes, os.path.basename(pdf_path), case_id=case_id)
    assert preview_code == 200, f"Preview failed: {preview_res}"
    preview_id = preview_res["preview_id"]
    confirm_res, confirm_code = confirm_business_preview(
        preview_id=preview_id,
        case_id=case_id,
        business_model_override=sug_bm or "HON_HOP",
        identity_acknowledged=True,
    )
    assert confirm_code == 200, f"Confirm failed: {confirm_res}"
    print(f"\n[G] Preview & Confirmation Result: {confirm_res.get('status')}")

    sec_c = CASES_DB[case_id]["section_c"]
    print(f"  - Canonical Shareholders: {len(sec_c.get('shareholders', []))}")
    print(f"  - Canonical Management: {len(sec_c.get('management', []))}")
    print(f"  - Canonical Products: {len(sec_c.get('products', []))}")
    print(f"  - Canonical Suppliers: {len(sec_c.get('suppliers', []))}")
    print(f"  - Canonical Customers: {len(sec_c.get('customers', []))}")

    print("\n" + "=" * 80)
    print("SCANNED BUSINESS PIPELINE VERIFIED SUCCESSFULLY WITH REAL GREENNODE!")
    print("=" * 80)
    return 0


if __name__ == "__main__":
    exit(main())

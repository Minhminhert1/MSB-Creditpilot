# -*- coding: utf-8 -*-
"""Real execution for SCANNED CIC:
PDFium -> Qwen Vision REAL CALL (qwen/qwen3.6-flash OCR)
-> GLM-5.2 REAL CALL (z-ai/glm-5.2-hackathon structured extraction)
-> token usage -> verified CIC facts -> grounding audit
-> identity reconciliation -> RM review & confirm
-> canonical section_e -> MB07 Table 32 binding.
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
from msb_eb_copilot.src.extraction.cic_extraction import (
    CICDocumentExtractor,
    CICGroundingAuditor,
    CICIdentityReconciler,
    CICNormalizer,
)
from msb_eb_copilot.src.ingestion.router import DocumentIngestionRouter
from msb_eb_copilot.src.mapping.cic_mapper import CICDocumentMapper
from msb_eb_copilot.src.section_e.models import is_msb_institution
from msb_eb_copilot.src.mapping.models import MappingSourceMetadata
from web_copilot_app import (
    CASES_DB,
    CIC_PREVIEW_STORE,
    CICPreviewRecord,
    confirm_cic_preview,
)


def main():
    print("=" * 80)
    print("2. SCANNED CIC PIPELINE - REAL GREENNODE OCR + LLM EXECUTION")
    print("=" * 80)

    pdf_path = os.path.join("tests", "fixtures", "cic", "synthetic_cic_scanned.pdf")
    if not os.path.exists(pdf_path):
        pdf_path = os.path.join("tests", "fixtures", "synthetic_cic_scanned.pdf")
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
    print(f"  - OCR Tagged Text Length: {len(ingestion_res.tagged_text)} characters")
    assert ingestion_res.mode == "ocr", "Expected ocr mode"
    assert ingestion_res.fallback_reason == "PDFBlankPageError", "Expected PDFBlankPageError fallback"

    # Step B: Real Call to GreenNode GLM-5.2
    print("\n[B] Real Call to GLM-5.2 (z-ai/glm-5.2-hackathon)...")
    extractor = CICDocumentExtractor()
    extraction = extractor.extract(ingestion_res.tagged_text, ingestion_res.page_count)
    print("  [✓] GLM-5.2 returned valid CIC extraction from OCR text!")

    # Step C: Token Usage Telemetry
    telemetry = AIAssistantClient.get_telemetry(limit=5)
    ocr_tel = next((t for t in telemetry if t.get("operation") == "ocr_page"), None)
    ext_tel = next((t for t in telemetry if t.get("operation") == "cic_extraction"), None)

    print("\n[C] Real Token Usage Telemetry:")
    if ocr_tel:
        print(f"  [Qwen Vision OCR]")
        print(f"    - Model: {ocr_tel.get('model')}")
        print(f"    - Latency: {ocr_tel.get('latency_ms')} ms")
    if ext_tel:
        print(f"  [GLM-5.2 Structured Extraction]")
        print(f"    - Model: {ext_tel.get('model')}")
        print(f"    - Input Tokens: {ext_tel.get('input_tokens')}")
        print(f"    - Output Tokens: {ext_tel.get('output_tokens')}")
        print(f"    - Total Tokens: {ext_tel.get('total_tokens')}")
        print(f"    - Latency: {ext_tel.get('latency_ms')} ms")

    # Step D: Comprehensive Grounding Audit on Every Candidate SOURCE_FACT
    print("\n[D] Grounding Audit on OCR Extracted Facts:")
    pages_text, max_p = CICGroundingAuditor.extract_pages(ingestion_res.tagged_text)
    all_audits = CICGroundingAuditor.audit_all_facts(extraction, pages_text, max_p)

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
    print("  " + "=" * 90)

    total_non_null = len(all_audits)
    print(f"  [✓] Total Non-Null SOURCE_FACTs Audited : {total_non_null}")
    print(f"      - VERIFIED : {status_counts.get('VERIFIED', 0)}")
    print(f"      - WARNING  : {status_counts.get('WARNING', 0)}")
    print(f"      - REJECTED : {status_counts.get('REJECTED', 0)}")
    print(f"      - MISSING  : {status_counts.get('MISSING', 0)}")

    # Step E: Identity Reconciliation & Canonical Mapping
    print("\n[E] Identity Reconciliation & Canonical Mapping:")
    target_case_id = "CASE_THANG_LONG_SCANNED"
    CASES_DB[target_case_id] = {
        "id": target_case_id,
        "name": "CÔNG TY CỔ PHẦN CÔNG NGHỆ THĂNG LONG",
        "customer": {
            "name": "CÔNG TY CỔ PHẦN CÔNG NGHỆ THĂNG LONG",
            "tax_code": "0109876543",
        },
        "section_e": {},
    }

    id_status, id_msg = CICIdentityReconciler.reconcile(
        extraction.tax_code.value_raw if extraction.tax_code else None,
        extraction.customer_name.value_raw if extraction.customer_name else None,
        CASES_DB[target_case_id]["customer"]
    )
    print(f"  - Identity Status: {id_status} ({id_msg})")

    source_meta = MappingSourceMetadata(
        source_document="synthetic_cic_scanned.pdf",
        ingestion_mode=ingestion_res.mode,
        extractor="CICDocumentExtractor",
    )
    map_result = CICDocumentMapper.map(
        CASES_DB[target_case_id],
        extraction,
        source_meta,
        grounding_audits=all_audits,
    )

    # Step F: Stage Server Preview & Confirm
    print("\n[F] Server-Authoritative Preview & RM Confirm:")
    preview_id = "preview_scanned_cic_live"
    preview_record = CICPreviewRecord(
        preview_id=preview_id,
        case_id=target_case_id,
        extraction=extraction,
        source_filename="synthetic_cic_scanned.pdf",
        routing={"mode": ingestion_res.mode, "provider": ingestion_res.provider, "page_count": ingestion_res.page_count},
        mapping_result=map_result,
        review_table=[],
        identity_status=id_status,
        identity_message=id_msg,
        consumed=False,
    )
    CIC_PREVIEW_STORE[preview_id] = preview_record

    conf_res, conf_code = confirm_cic_preview(preview_id, case_id=target_case_id)
    assert conf_code == 200, f"Confirm failed with {conf_code}: {conf_res}"
    print(f"  [✓] Confirmed successfully! Single-use token consumed.")

    # Step G: Print Confirmed Canonical Facts & Relations
    confirmed_e = CASES_DB[target_case_id]["section_e"]
    print("\n" + "=" * 80)
    print("CONFIRMED CANONICAL SECTION E (FROM REAL GREENNODE SCANNED OCR EXTRACTION)")
    print("=" * 80)
    print(f"  - Ngày tra cứu CIC: {confirmed_e.get('cic_date')}")
    print(f"  - Lịch sử quan hệ tín dụng: {confirmed_e.get('history_status')}")
    print(f"  - Phát sinh nợ quá hạn 12T: {confirmed_e.get('is_overdue_12m')}")
    print(f"  - Giao dịch phái sinh: {confirmed_e.get('derivative_transactions_info')}")
    print(f"  - Dư nợ tại MSB (Triệu VND): {confirmed_e.get('msb_outstanding'):,.1f}")
    print(f"  - Tổng mức cấp TD tại MSB (Triệu VND): {confirmed_e.get('total_credit_exposure_at_msb_million'):,.1f}")
    print(f"  - Tổng dư nợ TCTD khác loại trừ MSB: {confirmed_e.get('total_debt_other_banks_excluding_msb')}")

    print("\n  DANH SÁCH QUAN HỆ TÍN DỤNG TẠI CÁC TCTD:")
    print(f"  {'STT':<4} | {'Tên TCTD':<40} | {'HMTD (trđ)':<10} | {'Dư nợ VND':<10} | {'USD quy đổi':<11} | {'Dư nợ TDH':<10} | {'Tổng dư nợ':<10} | {'Nhóm':<5} | {'MSB?'}")
    print("  " + "-" * 125)
    for r in confirmed_e.get("relations", []):
        stt = r.get("stt", "-")
        b_name = r.get("bank_name", "")[:38]
        lim = f"{r.get('short_term_limit_million_vnd'):,.0f}" if r.get('short_term_limit_million_vnd') is not None else "-"
        vnd = f"{r.get('short_term_debt_vnd_million'):,.0f}" if r.get('short_term_debt_vnd_million') is not None else "-"
        usd = f"{r.get('short_term_debt_usd_million'):,.0f}" if r.get('short_term_debt_usd_million') is not None else "-"
        tdh = f"{r.get('medium_long_term_debt_million'):,.0f}" if r.get('medium_long_term_debt_million') is not None else "-"
        tot = f"{r.get('total_debt_million'):,.0f}" if r.get('total_debt_million') is not None else "Incomplete"
        grp = r.get("debt_group", "-")
        is_m = "YES (MSB)" if is_msb_institution(r.get("bank_name")) else "No"
        print(f"  {stt:<4} | {b_name:<40} | {lim:>10} | {vnd:>10} | {usd:>11} | {tdh:>10} | {tot:>10} | {str(grp):>5} | {is_m}")

    print("=" * 80)
    print(">>> SCANNED CIC PIPELINE: LIVE GREENNODE VERIFICATION COMPLETE <<<")
    return 0


if __name__ == "__main__":
    sys.exit(main())

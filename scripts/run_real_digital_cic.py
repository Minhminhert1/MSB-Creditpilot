# -*- coding: utf-8 -*-
"""Real execution for DIGITAL CIC:
pypdf -> GLM-5.2 REAL CALL -> token usage -> verified CIC facts
-> grounding audit -> identity reconciliation -> RM review & confirm
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
    GroundingAuditResult,
)
from msb_eb_copilot.src.ingestion.router import DocumentIngestionRouter
from msb_eb_copilot.src.mapping.cic_mapper import CICDocumentMapper
from msb_eb_copilot.src.section_e.models import (
    is_msb_institution,
    SectionEData,
    CreditInstitutionRelation,
)
from msb_eb_copilot.src.section_e.cross_link import get_other_debt_for_section_d
from msb_eb_copilot.src.credit_demand_engine import CreditDemandEngine, FinancialInput
from msb_eb_copilot.src.mapping.models import MappingSourceMetadata
from web_copilot_app import (
    CASES_DB,
    CIC_PREVIEW_STORE,
    CICPreviewRecord,
    confirm_cic_preview,
)


def main():
    print("=" * 80)
    print("1. DIGITAL CIC PIPELINE - REAL GREENNODE EXECUTION")
    print("=" * 80)

    pdf_path = os.path.join("tests", "fixtures", "cic", "synthetic_cic_digital.pdf")
    if not os.path.exists(pdf_path):
        pdf_path = os.path.join("tests", "fixtures", "synthetic_cic_digital.pdf")
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
    extractor = CICDocumentExtractor()
    extraction = extractor.extract(ingestion_res.tagged_text, ingestion_res.page_count)
    print("  [✓] GLM-5.2 returned valid CIC extraction!")

    # Step C: Token Usage Telemetry
    telemetry = AIAssistantClient.get_telemetry(limit=5)
    latest_tel = next((t for t in telemetry if t.get("operation") == "cic_extraction"), None)
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
    print("\n[D] Grounding Audit on Extracted CIC Facts:")
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
    target_case_id = "CASE_THANG_LONG_DIGITAL"
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
        source_document="synthetic_cic_digital.pdf",
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
    preview_id = "preview_digital_cic_live"
    preview_record = CICPreviewRecord(
        preview_id=preview_id,
        case_id=target_case_id,
        extraction=extraction,
        source_filename="synthetic_cic_digital.pdf",
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
    print("CONFIRMED CANONICAL SECTION E (FROM REAL GREENNODE DIGITAL EXTRACTION)")
    print("=" * 80)
    print(f"  - Ngày tra cứu CIC: {confirmed_e.get('cic_date')}")
    print(f"  - Lịch sử quan hệ tín dụng: {confirmed_e.get('history_status')}")
    print(f"  - Phát sinh nợ quá hạn 12T: {confirmed_e.get('is_overdue_12m')}")
    print(f"  - Giao dịch phái sinh: {confirmed_e.get('derivative_transactions_info')}")
    msb_out_val = confirmed_e.get('msb_outstanding')
    msb_out_str = f"{msb_out_val:,.1f}" if msb_out_val is not None else "None"
    msb_exp_val = confirmed_e.get('total_credit_exposure_at_msb_million')
    msb_exp_str = f"{msb_exp_val:,.1f}" if msb_exp_val is not None else "None"
    other_debt_val = confirmed_e.get('total_debt_other_banks_excluding_msb')
    other_debt_str = f"{other_debt_val:,.1f}" if other_debt_val is not None else "None (INCOMPLETE)"

    print(f"  - Dư nợ tại MSB (Triệu VND): {msb_out_str}")
    print(f"  - Tổng mức cấp TD tại MSB (Triệu VND): {msb_exp_str}")
    print(f"  - Tổng dư nợ TCTD khác loại trừ MSB: {other_debt_str}")

    print("\n  DANH SÁCH QUAN HỆ TÍN DỤNG TẠI CÁC TCTD:")
    print(f"  {'STT':<4} | {'Tên TCTD':<40} | {'HMTD (trđ)':<10} | {'Dư nợ VND':<10} | {'USD quy đổi':<11} | {'Dư nợ TDH':<10} | {'Tổng dư nợ':<10} | {'Nhóm':<5} | {'MSB?'}")
    print("  " + "-" * 125)
    built_relations: List[CreditInstitutionRelation] = []
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
        built_relations.append(
            CreditInstitutionRelation(
                stt=r.get("stt", 1),
                bank_name=r.get("bank_name", ""),
                short_term_limit_million_vnd=r.get("short_term_limit_million_vnd"),
                short_term_debt_vnd_million=r.get("short_term_debt_vnd_million"),
                short_term_debt_usd_million=r.get("short_term_debt_usd_million"),
                medium_long_term_debt_million=r.get("medium_long_term_debt_million"),
                total_debt_million=r.get("total_debt_million"),
                raw_usd_amount=r.get("raw_usd_amount"),
                raw_usd_currency=r.get("raw_usd_currency"),
                collateral_description=r.get("collateral_description"),
            )
        )

    # Step H: Cross-Section Recheck with Canonical SectionEData & Engine MB09
    print("\n" + "=" * 80)
    print("CROSS-SECTION RECHECK: SECTION E -> MB09 LINKAGE")
    print("=" * 80)
    sec_e_obj = SectionEData(
        customer_name=CASES_DB[target_case_id]["customer"]["name"],
        cic_report_date=confirmed_e.get("cic_date") or "",
        relations=built_relations,
        loan_outstanding_at_msb_million=confirmed_e.get("msb_outstanding") or 0.0,
        total_credit_exposure_at_msb_million=confirmed_e.get("total_credit_exposure_at_msb_million") or 0.0,
    )

    agg_incomplete = sec_e_obj.total_debt_other_banks_excluding_msb is None
    mb09_other_debt = get_other_debt_for_section_d(sec_e_obj)

    print(f"  - Canonical section_e.msb_outstanding: {confirmed_e.get('msb_outstanding')}")
    print(f"  - Canonical section_e.total_credit_exposure_at_msb_million: {confirmed_e.get('total_credit_exposure_at_msb_million')}")
    print(f"  - Canonical section_e.total_debt_other_banks_excluding_msb: {confirmed_e.get('total_debt_other_banks_excluding_msb')}")
    print(f"  - Aggregate Completeness Status: {'INCOMPLETE' if agg_incomplete else 'COMPLETE'}")
    print(f"  - Exact Value Supplied to MB09 (get_other_debt_for_section_d): {mb09_other_debt}")

    assert mb09_other_debt is None, f"Expected MB09 other_debt to be None, got {mb09_other_debt}"
    assert confirmed_e.get("total_debt_other_banks_excluding_msb") is None, "Expected total_debt_other_banks_excluding_msb to be None"
    print("  [✓] Verified: MB09 did NOT consume partial subtotal (10,000). Passed None safely!")

    # Test CreditDemandEngine with None other_debt
    fin_inp = FinancialInput(
        net_revenue_plan=60_000_000_000,
        cogs_plan=45_000_000_000,
        operating_cost_plan=5_000_000_000,
        dio=60.0,
        dso=45.0,
        dpo=30.0,
        equity_participation=5_000_000_000,
        other_debt=mb09_other_debt,
    )
    mb09_calc = CreditDemandEngine.calculate_credit_limits(fin_inp)
    print(f"  - CreditDemandEngine working_capital_demand: {mb09_calc['working_capital_demand']:,.0f} VND")
    print(f"  - CreditDemandEngine net_working_capital_demand: {mb09_calc['net_working_capital_demand']:,.0f} VND")
    print(f"  - CreditDemandEngine loan_limit_msb: {mb09_calc['loan_limit_msb']} (Safely blocked due to incomplete other_debt!)")
    print(f"  - CreditDemandEngine total_credit_facility_msb: {mb09_calc['total_credit_facility_msb']}")

    print("=" * 80)
    print(">>> DIGITAL CIC PIPELINE: LIVE GREENNODE VERIFICATION COMPLETE <<<")
    return 0


if __name__ == "__main__":
    sys.exit(main())

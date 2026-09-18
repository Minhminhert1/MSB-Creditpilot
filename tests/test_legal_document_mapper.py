# -*- coding: utf-8 -*-
"""Comprehensive unit test suite for LegalDocumentMapper and deterministic mapping."""

import copy
import pytest

from msb_eb_copilot.src.extraction.legal_extraction import EvidenceField, LegalDocumentExtraction
from msb_eb_copilot.src.mapping import (
    CanonicalMappingResult,
    LegalDocumentMapper,
    MappingConflict,
    MappingError,
    MappingProvenance,
    MappingSchemaError,
    MappingSourceMetadata,
    MappingWarning,
)


def make_sample_extraction(
    company_name="CÔNG TY CỔ PHẦN THƯƠNG MẠI DỊCH VỤ AN BÌNH",
    short_name="AN BINH CORP",
    tax_code="0101234567",
    address="Số 123 Đường Kim Mã, Phường Giảng Võ, Quận Ba Đình, Hà Nội",
    charter_capital_raw="50.000.000.000 đồng",
    legal_rep_name="Nguyễn Văn An",
    legal_rep_title="Tổng Giám đốc",
    page=1,
) -> LegalDocumentExtraction:
    """Helper to build a valid LegalDocumentExtraction instance."""
    return LegalDocumentExtraction(
        company_name=EvidenceField(
            value=company_name,
            evidence=f"Tên công ty: {company_name}" if company_name else None,
            page=page if company_name else None,
        ),
        short_name=EvidenceField(
            value=short_name,
            evidence=f"Tên viết tắt: {short_name}" if short_name else None,
            page=page if short_name else None,
        ),
        tax_code=EvidenceField(
            value=tax_code,
            evidence=f"Mã số DN: {tax_code}" if tax_code else None,
            page=page if tax_code else None,
        ),
        address=EvidenceField(
            value=address,
            evidence=f"Địa chỉ: {address}" if address else None,
            page=page if address else None,
        ),
        charter_capital_raw=EvidenceField(
            value=charter_capital_raw,
            evidence=f"Vốn điều lệ: {charter_capital_raw}" if charter_capital_raw else None,
            page=page if charter_capital_raw else None,
        ),
        legal_rep_name=EvidenceField(
            value=legal_rep_name,
            evidence=f"Họ và tên: {legal_rep_name}" if legal_rep_name else None,
            page=page if legal_rep_name else None,
        ),
        legal_rep_title=EvidenceField(
            value=legal_rep_title,
            evidence=f"Chức danh: {legal_rep_title}" if legal_rep_title else None,
            page=page if legal_rep_title else None,
        ),
    )


SOURCE_DOC_A = MappingSourceMetadata(
    source_document="giay_phep_kinh_doanh.pdf",
    ingestion_mode="digital",
)

SOURCE_DOC_B = MappingSourceMetadata(
    source_document="dieu_le_cong_ty.pdf",
    ingestion_mode="digital",
)

SOURCE_DOC_C = MappingSourceMetadata(
    source_document="scan_dkkd_thay_doi.pdf",
    ingestion_mode="ocr",
)


# ==============================================================================
# 1. CANONICAL SHAPE & NON-MUTATION TESTS
# ==============================================================================
def test_input_case_data_is_not_mutated():
    original_case_data = {
        "customer": {"name": "ORIGINAL NAME"},
        "section_b": {"loan_limit": 1000},
    }
    before_copy = copy.deepcopy(original_case_data)
    extraction = make_sample_extraction()

    result = LegalDocumentMapper.map(
        existing_case_data=original_case_data,
        extraction=extraction,
        source_meta=SOURCE_DOC_A,
    )

    assert original_case_data == before_copy
    assert result.case_data is not original_case_data
    assert result.case_data["customer"] is not original_case_data["customer"]


def test_malformed_customer_raises_schema_error():
    malformed_cases = [
        {"customer": "invalid_string_not_dict"},
        {"customer": [1, 2, 3]},
        {"customer": 12345},
    ]
    extraction = make_sample_extraction()
    for case_data in malformed_cases:
        with pytest.raises(MappingSchemaError) as exc_info:
            LegalDocumentMapper.map(case_data, extraction, SOURCE_DOC_A)
        assert "must be a dict" in str(exc_info.value)


def test_absent_customer_initialized_cleanly():
    empty_case_data = {}
    extraction = make_sample_extraction()
    result = LegalDocumentMapper.map(empty_case_data, extraction, SOURCE_DOC_A)

    assert "customer" in result.case_data
    assert isinstance(result.case_data["customer"], dict)
    assert result.case_data["customer"]["name"] == "CÔNG TY CỔ PHẦN THƯƠNG MẠI DỊCH VỤ AN BÌNH"


def test_unrelated_business_keys_preserved():
    complex_case_data = {
        "id": "PSD",
        "rm_metadata": {"rm_name": "Nguyen Van RM", "proposal_no": "01.2026"},
        "section_b": {"total_limit": 700000},
        "customer": {"cif": "123456", "segment": "LC"},
    }
    extraction = make_sample_extraction()
    result = LegalDocumentMapper.map(complex_case_data, extraction, SOURCE_DOC_A)

    assert result.case_data["id"] == "PSD"
    assert result.case_data["rm_metadata"] == complex_case_data["rm_metadata"]
    assert result.case_data["section_b"] == complex_case_data["section_b"]
    assert result.case_data["customer"]["cif"] == "123456"
    assert result.case_data["customer"]["segment"] == "LC"


# ==============================================================================
# 2. CANONICAL FIELD MAPPING & RESTRICTION TESTS
# ==============================================================================
def test_all_seven_fields_map_correctly():
    extraction = make_sample_extraction()
    result = LegalDocumentMapper.map({}, extraction, SOURCE_DOC_A)

    cust = result.case_data["customer"]
    assert cust["name"] == "CÔNG TY CỔ PHẦN THƯƠNG MẠI DỊCH VỤ AN BÌNH"
    assert cust["short_name"] == "AN BINH CORP"
    assert cust["tax_code"] == "0101234567"
    assert cust["address"] == "Số 123 Đường Kim Mã, Phường Giảng Võ, Quận Ba Đình, Hà Nội"
    assert cust["charter_capital"] == 50000
    assert cust["legal_rep_name"] == "Nguyễn Văn An"
    assert cust["legal_rep_title"] == "Tổng Giám đốc"

    assert set(result.updated_fields) == {
        "customer.name",
        "customer.short_name",
        "customer.tax_code",
        "customer.address",
        "customer.charter_capital",
        "customer.legal_rep_name",
        "customer.legal_rep_title",
    }
    assert len(result.conflicts) == 0
    assert len(result.warnings) == 0


def test_provenance_kept_outside_case_data_and_no_raw_capital():
    extraction = make_sample_extraction()
    result = LegalDocumentMapper.map({}, extraction, SOURCE_DOC_A)

    # 1. Provenance is in result.provenance, NEVER in case_data
    assert "_provenance" not in result.case_data
    assert "_metadata" not in result.case_data
    assert len(result.provenance) == 7

    # 2. NO charter_capital_raw in customer
    assert "charter_capital_raw" not in result.case_data["customer"]


def test_null_staging_field_skipped_and_never_overwrites():
    existing = {
        "customer": {
            "short_name": "EXISTING SHORT",
            "name": "EXISTING FULL NAME",
        }
    }
    extraction = make_sample_extraction(short_name=None)
    result = LegalDocumentMapper.map(existing, extraction, SOURCE_DOC_A)

    assert result.case_data["customer"]["short_name"] == "EXISTING SHORT"
    assert result.case_data["customer"]["name"] == "EXISTING FULL NAME"
    assert "customer.short_name" not in result.updated_fields
    assert "customer.short_name" not in result.provenance
    assert len(result.conflicts) == 1
    assert result.conflicts[0].canonical_path == "customer.name"


def test_null_staging_never_creates_sentinel_empty_or_na():
    extraction = make_sample_extraction(short_name=None, legal_rep_title=None)
    result = LegalDocumentMapper.map({}, extraction, SOURCE_DOC_A)

    cust = result.case_data["customer"]
    assert "short_name" not in cust
    assert "legal_rep_title" not in cust
    for k, v in cust.items():
        assert v not in ("", "N/A", "null", "None", 0, None)


def test_tax_code_leading_zero_preserved():
    extraction = make_sample_extraction(tax_code="0101234567")
    result = LegalDocumentMapper.map({}, extraction, SOURCE_DOC_A)

    tax_val = result.case_data["customer"]["tax_code"]
    assert tax_val == "0101234567"
    assert isinstance(tax_val, str)
    assert tax_val.startswith("0")


# ==============================================================================
# 3. PROVENANCE, CONFLICT & IDEMPOTENCY TESTS
# ==============================================================================
def test_same_document_twice_one_provenance_record():
    extraction = make_sample_extraction()
    res1 = LegalDocumentMapper.map({}, extraction, SOURCE_DOC_A)

    res2 = LegalDocumentMapper.map(
        existing_case_data=res1.case_data,
        extraction=extraction,
        source_meta=SOURCE_DOC_A,
        existing_provenance=res1.provenance,
        existing_conflicts=res1.conflicts,
        existing_warnings=res1.warnings,
    )

    assert res2.case_data == res1.case_data
    assert len(res2.updated_fields) == 0  # No new fields updated on second run
    assert len(res2.conflicts) == 0
    assert len(res2.warnings) == 0

    # Exactly 1 provenance record per field
    for path, records in res2.provenance.items():
        assert len(records) == 1, f"Expected 1 record for {path}, got {len(records)}"


def test_two_documents_same_fact_two_provenances():
    ext_a = make_sample_extraction()
    res1 = LegalDocumentMapper.map({}, ext_a, SOURCE_DOC_A)

    ext_b = make_sample_extraction(page=3)
    res2 = LegalDocumentMapper.map(
        existing_case_data=res1.case_data,
        extraction=ext_b,
        source_meta=SOURCE_DOC_B,
        existing_provenance=res1.provenance,
        existing_conflicts=res1.conflicts,
        existing_warnings=res1.warnings,
    )

    assert res2.case_data == res1.case_data
    assert len(res2.conflicts) == 0

    tax_prov = res2.provenance["customer.tax_code"]
    assert len(tax_prov) == 2
    sources = {p.source_document for p in tax_prov}
    assert sources == {"giay_phep_kinh_doanh.pdf", "dieu_le_cong_ty.pdf"}


def test_third_conflicting_document_preserves_canonical_and_records_conflict():
    ext_a = make_sample_extraction(tax_code="0101234567")
    res1 = LegalDocumentMapper.map({}, ext_a, SOURCE_DOC_A)

    # Document C has conflicting tax code
    ext_c = make_sample_extraction(tax_code="0100000000", page=2)
    res2 = LegalDocumentMapper.map(
        existing_case_data=res1.case_data,
        extraction=ext_c,
        source_meta=SOURCE_DOC_C,
        existing_provenance=res1.provenance,
        existing_conflicts=res1.conflicts,
        existing_warnings=res1.warnings,
    )

    # 1. Existing canonical tax code remains untouched!
    assert res2.case_data["customer"]["tax_code"] == "0101234567"
    assert "customer.tax_code" not in res2.updated_fields

    # 2. Exactly one conflict emitted
    assert len(res2.conflicts) == 1
    conflict = res2.conflicts[0]
    assert conflict.canonical_path == "customer.tax_code"
    assert conflict.existing_value == "0101234567"
    assert conflict.extracted_value == "0100000000"
    assert conflict.source_document == "scan_dkkd_thay_doi.pdf"
    assert conflict.page == 2

    # 3. Provenance for conflicting observation is preserved
    tax_prov = res2.provenance["customer.tax_code"]
    assert len(tax_prov) == 2
    conflicting_prov = [p for p in tax_prov if p.source_document == "scan_dkkd_thay_doi.pdf"][0]
    assert conflicting_prov.source_value == "0100000000"
    assert conflicting_prov.mapped_value == "0100000000"


def test_repeated_conflict_does_not_duplicate():
    ext_a = make_sample_extraction(tax_code="0101234567")
    res1 = LegalDocumentMapper.map({}, ext_a, SOURCE_DOC_A)

    ext_c = make_sample_extraction(tax_code="0100000000", page=2)
    res2 = LegalDocumentMapper.map(
        existing_case_data=res1.case_data,
        extraction=ext_c,
        source_meta=SOURCE_DOC_C,
        existing_provenance=res1.provenance,
        existing_conflicts=res1.conflicts,
        existing_warnings=res1.warnings,
    )
    assert len(res2.conflicts) == 1

    # Map conflicting Document C a second time
    res3 = LegalDocumentMapper.map(
        existing_case_data=res2.case_data,
        extraction=ext_c,
        source_meta=SOURCE_DOC_C,
        existing_provenance=res2.provenance,
        existing_conflicts=res2.conflicts,
        existing_warnings=res2.warnings,
    )
    assert len(res3.conflicts) == 1
    assert res3.conflicts == res2.conflicts


def test_repeated_warning_does_not_duplicate():
    ext_warn = make_sample_extraction(charter_capital_raw="Năm mươi tỷ đồng")
    res1 = LegalDocumentMapper.map({}, ext_warn, SOURCE_DOC_A)
    assert len(res1.warnings) == 1

    res2 = LegalDocumentMapper.map(
        existing_case_data=res1.case_data,
        extraction=ext_warn,
        source_meta=SOURCE_DOC_A,
        existing_provenance=res1.provenance,
        existing_conflicts=res1.conflicts,
        existing_warnings=res1.warnings,
    )
    assert len(res2.warnings) == 1
    assert res2.warnings == res1.warnings


# ==============================================================================
# 4. MONETARY TOKEN PARSING & CHARTER CAPITAL TESTS
# ==============================================================================
@pytest.mark.parametrize(
    "raw_input,expected_million_vnd",
    [
        ("50.000.000.000 đồng", 50000),
        ("50 tỷ đồng", 50000),
        ("50 triệu đồng", 50),
        ("50,5 tỷ đồng", 50500.0),
        ("50.000 triệu đồng", 50000),
        ("50.500.000.000 VND", 50500),
        ("50.000.000.000 đồng (Bằng chữ: Năm mươi tỷ đồng)", 50000),
        ("50 tỷ VNĐ (Bằng chữ: Năm mươi tỷ đồng)", 50000),
        ("50.000 triệu đồng (Bằng chữ: Năm mươi tỷ đồng)", 50000),
        ("50.000.000.000đ", 50000),
        ("Vốn điều lệ:50 tỷ đồng", 50000),
        ("Vốn điều lệ: 50 tỷ đồng", 50000),
    ],
)
def test_charter_capital_valid_conversions(raw_input, expected_million_vnd):
    extraction = make_sample_extraction(charter_capital_raw=raw_input)
    result = LegalDocumentMapper.map({}, extraction, SOURCE_DOC_A)

    cap_val = result.case_data["customer"]["charter_capital"]
    assert cap_val == pytest.approx(expected_million_vnd)
    assert len(result.warnings) == 0


@pytest.mark.parametrize(
    "invalid_input,expected_reason_snippet",
    [
        ("50", "No explicit recognized currency unit"),
        ("Năm mươi tỷ đồng", "No numeric digits found"),
        ("-50 tỷ đồng", "Negative monetary amount not allowed"),
        ("50-60 tỷ đồng", "Range expression detected"),
        ("about 50 tỷ đồng", "Approximation expression detected"),
        ("khoảng 50 tỷ đồng", "Approximation expression detected"),
    ],
)
def test_charter_capital_invalid_inputs_emit_warning_and_no_write(invalid_input, expected_reason_snippet):
    extraction = make_sample_extraction(charter_capital_raw=invalid_input)
    result = LegalDocumentMapper.map({}, extraction, SOURCE_DOC_A)

    assert "charter_capital" not in result.case_data["customer"]
    assert len(result.warnings) == 1
    warning = result.warnings[0]
    assert warning.canonical_path == "customer.charter_capital"
    assert warning.source_value == invalid_input
    assert expected_reason_snippet in warning.reason

    prov = result.provenance["customer.charter_capital"][0]
    assert prov.source_value == invalid_input
    assert prov.mapped_value is None


def test_charter_capital_different_units_same_value_no_conflict():
    # Step 1: Doc A sets 50000 via VND format
    ext_a = make_sample_extraction(charter_capital_raw="50.000.000.000 đồng")
    res1 = LegalDocumentMapper.map({}, ext_a, SOURCE_DOC_A)
    assert res1.case_data["customer"]["charter_capital"] == 50000

    # Step 2: Doc B presents 50 tỷ đồng (same value in different unit)
    ext_b = make_sample_extraction(charter_capital_raw="50 tỷ đồng", page=2)
    res2 = LegalDocumentMapper.map(
        existing_case_data=res1.case_data,
        extraction=ext_b,
        source_meta=SOURCE_DOC_B,
        existing_provenance=res1.provenance,
        existing_conflicts=res1.conflicts,
        existing_warnings=res1.warnings,
    )

    assert res2.case_data["customer"]["charter_capital"] == 50000
    assert len(res2.conflicts) == 0
    assert len(res2.provenance["customer.charter_capital"]) == 2


def test_charter_capital_different_normalized_value_causes_conflict():
    # Step 1: Doc A sets 50000
    ext_a = make_sample_extraction(charter_capital_raw="50 tỷ đồng")
    res1 = LegalDocumentMapper.map({}, ext_a, SOURCE_DOC_A)
    assert res1.case_data["customer"]["charter_capital"] == 50000

    # Step 2: Doc C presents 60 tỷ đồng (different value)
    ext_c = make_sample_extraction(charter_capital_raw="60 tỷ đồng", page=3)
    res2 = LegalDocumentMapper.map(
        existing_case_data=res1.case_data,
        extraction=ext_c,
        source_meta=SOURCE_DOC_C,
        existing_provenance=res1.provenance,
        existing_conflicts=res1.conflicts,
        existing_warnings=res1.warnings,
    )

    # Existing preserved
    assert res2.case_data["customer"]["charter_capital"] == 50000
    assert len(res2.conflicts) == 1
    conflict = res2.conflicts[0]
    assert conflict.canonical_path == "customer.charter_capital"
    assert conflict.existing_value == 50000
    assert conflict.extracted_value == 60000

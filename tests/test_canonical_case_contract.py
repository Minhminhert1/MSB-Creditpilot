# -*- coding: utf-8 -*-
"""Comprehensive unit tests for the Canonical Case Data Contract (Phase 2).

Verifies:
1. Current demo cases (PSD, Thép Tây Đô) validate.
2. Legal-mapped customer validates into case_data.
3. Partial cases with missing optional or downstream fields are valid (readiness warnings only).
4. Missing required structural containers produce blocking errors.
5. tax_code strictly verified as a string preserving leading zeros.
6. charter_capital unit contract (numeric in triệu VND >= 0, negative rejected).
7. Financial statement period structure (arrays must match years length).
8. Source facts separated from calculated metrics (DERIVED_PYTHON vs SOURCE_FACT).
9. None accepted for unavailable source facts; 0 preserved as genuine fact.
10. Input non-mutation guarantee.
11. Legacy compatibility adapter and warnings.
"""

import copy
import json
import pytest

from msb_eb_copilot.src.canonical_validator import (
    CanonicalAdapter,
    ContractValidationReport,
    FieldOwner,
    validate_case_data_contract,
)
from msb_eb_copilot.src.mapping.legal_mapper import LegalDocumentMapper
from msb_eb_copilot.src.mapping.models import MappingSourceMetadata
from msb_eb_copilot.src.extraction.legal_extraction import (
    EvidenceField,
    LegalDocumentExtraction,
)


@pytest.fixture
def base_canonical_case():
    with open("case_input_template.json", "r", encoding="utf-8") as f:
        return json.load(f)


def test_base_template_case_validates(base_canonical_case):
    """Verify standard template case passes validation."""
    report = validate_case_data_contract(base_canonical_case)
    assert report.is_valid, f"Base template should be valid: {report.blocking_errors}"
    assert len(report.blocking_errors) == 0
    # May have legacy compatibility warning for revenue_2025
    assert any("revenue_2025" in w for w in report.legacy_compatibility_warnings)


def test_all_web_copilot_demo_cases_validate():
    """Verify all real demo cases in web_copilot_app.py validate with 0 blocking errors."""
    from web_copilot_app import CASES_DB
    for case_id, case_data in CASES_DB.items():
        report = validate_case_data_contract(case_data)
        assert report.is_valid, f"Demo case {case_id} failed contract: {report.blocking_errors}"
        assert len(report.blocking_errors) == 0, f"Demo case {case_id} has blocking errors: {report.blocking_errors}"


def test_input_non_mutation_guarantee(base_canonical_case):
    """Ensure validation does not mutate caller's case_data."""
    original = copy.deepcopy(base_canonical_case)
    report = validate_case_data_contract(base_canonical_case)
    assert base_canonical_case == original


def test_missing_required_structural_container():
    """Missing a top-level section container must produce a blocking error."""
    broken_case = {
        "id": "CASE_01",
        "customer": {},
        "rm_metadata": {},
        # section_b missing
        "section_c": {},
        "section_d": {},
        "section_e": {},
    }
    report = validate_case_data_contract(broken_case)
    assert not report.is_valid
    assert any("section_b" in err for err in report.blocking_errors)


def test_container_not_dict_produces_blocking_error():
    """Top-level container must be a dict, not a list or scalar."""
    broken_case = {
        "id": "CASE_01",
        "customer": ["not_a_dict"],
        "rm_metadata": {},
        "section_b": {},
        "section_c": {},
        "section_d": {},
        "section_e": {},
    }
    report = validate_case_data_contract(broken_case)
    assert not report.is_valid
    assert any("customer" in err and "dict" in err for err in report.blocking_errors)


def test_partial_case_is_valid_with_readiness_warnings():
    """Early-stage partial cases with empty sections must be valid (not globally invalid)."""
    partial_case = {
        "id": "CASE_NEW",
        "customer": {
            "name": "CÔNG TY MỚI",
            "tax_code": "0123456789",
            # cif is missing
        },
        "rm_metadata": {},
        "section_b": {},
        "section_c": {},
        "section_d": {},  # financials not populated yet
        "section_e": {},
    }
    report = validate_case_data_contract(partial_case)
    assert report.is_valid, f"Partial case should be valid: {report.blocking_errors}"
    assert len(report.blocking_errors) == 0
    # Must report downstream readiness warnings
    assert any("cif" in w for w in report.readiness_warnings)
    assert any("section_d" in w or "net_revenue" in w for w in report.readiness_warnings)


def test_tax_code_must_be_string_preserving_leading_zero():
    """tax_code cannot be numeric integer; it must be a string."""
    case = {
        "customer": {"tax_code": 101234567},  # integer!
        "rm_metadata": {},
        "section_b": {},
        "section_c": {},
        "section_d": {},
        "section_e": {},
    }
    report = validate_case_data_contract(case)
    assert not report.is_valid
    assert any("tax_code" in err and "string" in err for err in report.blocking_errors)


def test_tax_code_valid_string_with_leading_zero():
    """tax_code as valid string with leading zero is accepted."""
    case = {
        "customer": {"tax_code": "0100000000"},
        "rm_metadata": {},
        "section_b": {},
        "section_c": {},
        "section_d": {},
        "section_e": {},
    }
    report = validate_case_data_contract(case)
    assert report.is_valid


def test_charter_capital_unit_contract_and_non_negative():
    """charter_capital must be numeric in triệu VND and cannot be negative."""
    # Negative capital
    case_neg = {
        "customer": {"charter_capital": -100.0},
        "rm_metadata": {},
        "section_b": {},
        "section_c": {},
        "section_d": {},
        "section_e": {},
    }
    report_neg = validate_case_data_contract(case_neg)
    assert not report_neg.is_valid
    assert any("charter_capital" in err and "negative" in err for err in report_neg.blocking_errors)

    # String capital
    case_str = {
        "customer": {"charter_capital": "500 tỷ"},
        "rm_metadata": {},
        "section_b": {},
        "section_c": {},
        "section_d": {},
        "section_e": {},
    }
    report_str = validate_case_data_contract(case_str)
    assert not report_str.is_valid
    assert any("charter_capital" in err and "numeric" in err for err in report_str.blocking_errors)


def test_zero_preserved_as_valid_fact_not_missing():
    """Genuine zero (e.g. 0 debt) is a valid fact and must not be treated as missing."""
    case = {
        "customer": {"charter_capital": 500000.0},
        "rm_metadata": {},
        "section_b": {"total_limit": 0.0},
        "section_c": {},
        "section_d": {},
        "section_e": {"msb_outstanding": 0.0},
    }
    report = validate_case_data_contract(case)
    assert report.is_valid
    assert len(report.blocking_errors) == 0


def test_none_accepted_for_missing_source_facts():
    """None is the standard representation for missing/unextracted source facts."""
    case = {
        "customer": {
            "name": "TEST",
            "short_name": None,
            "charter_capital": None,
            "rating_grade": None,
        },
        "rm_metadata": {},
        "section_b": {"total_limit": None},
        "section_c": {},
        "section_d": {"years": None},
        "section_e": {"msb_outstanding": None},
    }
    report = validate_case_data_contract(case)
    assert report.is_valid
    assert len(report.blocking_errors) == 0


def test_financial_statement_array_length_mismatch():
    """Financial statement arrays must match the length of years."""
    case = {
        "customer": {},
        "rm_metadata": {},
        "section_b": {},
        "section_c": {},
        "section_d": {
            "years": ["2023", "2024", "2025"],
            "net_revenue": [100.0, 200.0],  # only 2 elements!
        },
        "section_e": {},
    }
    report = validate_case_data_contract(case)
    assert not report.is_valid
    assert any("net_revenue" in err and "length" in err for err in report.blocking_errors)


def test_legal_mapped_customer_validates():
    """Ensure output of LegalDocumentMapper directly passes canonical validation."""
    extraction = LegalDocumentExtraction(
        company_name=EvidenceField(value="CÔNG TY CỔ PHẦN AN BÌNH", evidence="Tên công ty", page=1),
        short_name=EvidenceField(value="AN BINH CORP", evidence="Tên viết tắt", page=1),
        tax_code=EvidenceField(value="0101234567", evidence="Mã số thuế: 0101234567", page=1),
        charter_capital_raw=EvidenceField(value="50 tỷ đồng", evidence="Vốn điều lệ: 50 tỷ đồng", page=1),
        address=EvidenceField(value="Hà Nội", evidence="Địa chỉ", page=1),
        legal_rep_name=EvidenceField(value="Nguyễn Văn A", evidence="Đại diện", page=1),
        legal_rep_title=EvidenceField(value="Giám đốc", evidence="Chức danh", page=1),
    )
    meta = MappingSourceMetadata("DKKD.pdf", "digital_pdf", "LegalDocumentExtractor")
    map_result = LegalDocumentMapper.map({}, extraction, meta)

    full_case = {
        "id": "AN_BINH",
        "name": "CÔNG TY CỔ PHẦN AN BÌNH",
        "customer": map_result.case_data["customer"],
        "rm_metadata": {},
        "section_b": {},
        "section_c": {},
        "section_d": {},
        "section_e": {},
    }
    report = validate_case_data_contract(full_case)
    assert report.is_valid
    assert full_case["customer"]["charter_capital"] == 50000.0  # 50 tỷ = 50,000 triệu VND
    assert full_case["customer"]["tax_code"] == "0101234567"


def test_canonical_adapter_legacy_resolution():
    """CanonicalAdapter resolves revenue authoritatively with fallback."""
    # 1. Authoritative from section_d
    case1 = {
        "customer": {"revenue_2025": 100.0},
        "section_d": {"net_revenue": [80.0, 90.0, 150.0]},
    }
    assert CanonicalAdapter.get_latest_revenue(case1) == 150.0

    # 2. Fallback to customer legacy field when section_d is empty
    case2 = {
        "customer": {"revenue_2025": 120.0},
        "section_d": {},
    }
    assert CanonicalAdapter.get_latest_revenue(case2) == 120.0

    # 3. to_legacy_customer populates revenue_2025 if missing
    case3 = {
        "customer": {"name": "TEST"},
        "section_d": {"net_revenue": [500.0]},
    }
    legacy_cust = CanonicalAdapter.to_legacy_customer(case3)
    assert legacy_cust["revenue_2025"] == 500.0


def test_field_owner_enumeration():
    """Verify all authoritative FieldOwner enum members."""
    assert FieldOwner.SOURCE_FACT.value == "SOURCE_FACT"
    assert FieldOwner.RM_INPUT.value == "RM_INPUT"
    assert FieldOwner.DERIVED_PYTHON.value == "DERIVED_PYTHON"
    assert FieldOwner.AI_NARRATIVE.value == "AI_NARRATIVE"
    assert FieldOwner.SYSTEM_METADATA.value == "SYSTEM_METADATA"


def test_shareholders_capital_distinct_reconciliation():
    """Verify that charter_capital and shareholder equity are distinct facts reconciled via summation."""
    case = {
        "customer": {"charter_capital": 500000.0},
        "section_c": {
            "shareholders": [
                {"name": "Cổ đông 1", "val": 350000.0},
                {"name": "Cổ đông 2", "val": 150000.0},
            ]
        }
    }
    charter, sum_shareholders, is_reconciled = CanonicalAdapter.reconcile_shareholders_capital(case)
    assert charter == 500000.0
    assert sum_shareholders == 500000.0
    assert is_reconciled is True


def test_legacy_revenue_adapter_emits_warning():
    """Verify that resolving revenue from legacy customer.revenue_2025 emits a compatibility warning."""
    case = {
        "customer": {"revenue_2025": 123456.0},
        "section_d": {},
    }
    warnings = []
    val = CanonicalAdapter.get_latest_revenue(case, warnings_collector=warnings)
    assert val == 123456.0
    assert len(warnings) == 1
    assert "legacy fallback" in warnings[0]

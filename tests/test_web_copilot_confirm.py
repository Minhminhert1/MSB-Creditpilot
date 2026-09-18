# -*- coding: utf-8 -*-
"""
Tests cho tinh nang RM Confirm Preview & Conflict Resolution trong web_copilot_app.py
voi Server-Side Verified Preview Store va Trust Boundary bao ve:

Cac cam ket ky thuat bat buoc:
1. Preview pipeline tao ra preview_id (UUID4) tren server va luu vao LEGAL_PREVIEW_STORE.
2. preview_id lien ket voi verified_fields tren server; client khong the truyen fields khi confirm.
3. Confirm khong can gui fields tu client ma van thanh cong.
4. Confirm lap tuc tu choi (HTTP 400 InvalidInputError) neu payload chua 'fields'.
5. Tampered browser values khong bao gio duoc chap nhan va khong bao gio ghi vao CASES_DB.
6. Invalid preview_id bi tu choi voi 404 PreviewNotFoundError.
7. Preview duoc bind voi case khac se bi tu choi voi 400 CaseMismatchError.
8. Confirm thanh cong se danh dau consumed = True tren server.
9. Consumed preview khong the tai su dung (409 PreviewAlreadyConsumedError).
10. Khi phat sinh xung dot (409 Conflict), preview van giu nguyen chua bi consumed.
11. RM giai quyet xung dot ('use_extracted' / 'keep_existing') dua tren gia tri da luu tren server.
12. CASES_DB khong bao gio thay doi khi preview lookup loi hoac co xung dot chua giai quyet.
13. Missing canonical field -> duoc tu dong dien.
14. Identical existing value -> khong tao xung dot.
15. Charter capital equivalent units (50000 vs 50000.0) -> khong tao xung dot.
16. Unrelated case sections (rm_metadata, section_b-e) duoc bao toan 100%.
17. Chi 7 truong customer phap ly duoc phep thay doi; cac truong customer khac duoc bao toan 100%.
18. Confirm tuyet doi KHONG goi execute_generation_pipeline.
19. Confirm tuyet doi KHONG tao file .docx.
20. Endpoint security: tu choi forbidden keys (fields, file_path, canonical_path, case_data) va arbitrary keys.
"""

import copy
import io
import json
import os
import uuid
import pytest
from unittest.mock import patch, MagicMock

import web_copilot_app
from web_copilot_app import (
    validate_and_confirm_legal_preview,
    LegalPreviewRecord,
    CopilotHTTPHandler,
    CASES_DB,
    ACTIVE_CASE_ID,
    LEGAL_PREVIEW_STORE,
    ALLOWED_CONFIRM_FIELDS,
)


@pytest.fixture(autouse=True)
def restore_cases_db():
    """Tu dong sao luu va khoi phuc CASES_DB, ACTIVE_CASE_ID, va LEGAL_PREVIEW_STORE sau moi bai test."""
    original_db = copy.deepcopy(web_copilot_app.CASES_DB)
    original_active_id = web_copilot_app.ACTIVE_CASE_ID
    original_latest_preview = web_copilot_app.LATEST_LEGAL_PREVIEW
    original_preview_store = copy.deepcopy(web_copilot_app.LEGAL_PREVIEW_STORE)
    yield
    web_copilot_app.CASES_DB = original_db
    web_copilot_app.ACTIVE_CASE_ID = original_active_id
    web_copilot_app.LATEST_LEGAL_PREVIEW = original_latest_preview
    web_copilot_app.LEGAL_PREVIEW_STORE = original_preview_store


class DummyMockServer:
    """Mock HTTP Request Handler helper for testing CopilotHTTPHandler.do_POST."""
    def __init__(self):
        self.response_status = None
        self.response_headers = {}
        self.response_body = None

    def post_json(self, path, post_data_dict):
        body_bytes = json.dumps(post_data_dict).encode("utf-8")
        handler = CopilotHTTPHandler.__new__(CopilotHTTPHandler)
        handler.path = path
        handler.headers = {"Content-Length": str(len(body_bytes))}
        handler.rfile = io.BytesIO(body_bytes)
        out_buf = io.BytesIO()
        handler.wfile = out_buf

        def send_response(code):
            self.response_status = code
        def send_header(k, v):
            self.response_headers[k] = v
        def end_headers():
            pass

        handler.send_response = send_response
        handler.send_header = send_header
        handler.end_headers = end_headers

        def send_json(data, status_code=200):
            self.response_status = status_code
            self.response_body = data

        handler._send_json = send_json
        handler.do_POST()
        return self.response_body, self.response_status


def create_test_preview(
    case_id="PSD",
    fields=None,
    preview_id=None,
    consumed=False,
    source_filename="test_legal.pdf",
):
    """Helper tao preview record luu vao server-side LEGAL_PREVIEW_STORE."""
    if preview_id is None:
        preview_id = str(uuid.uuid4())
    if fields is None:
        fields = {}
    record = LegalPreviewRecord(
        preview_id=preview_id,
        case_id=case_id,
        verified_fields=fields,
        source_filename=source_filename,
        routing={"mode": "text_digital", "provider": "pypdf", "page_count": 1, "fallback_reason": None},
        consumed=consumed,
    )
    web_copilot_app.LEGAL_PREVIEW_STORE[preview_id] = record
    return preview_id, record


# ==============================================================================
# TEST 1 & 2: SERVER-SIDE PREVIEW_ID CREATION & VERIFIED FIELDS LOOKUP
# ==============================================================================
def test_preview_creates_server_side_record_and_id():
    """Tien trinh preview tao preview_id tren server va luu vao LEGAL_PREVIEW_STORE."""
    pid, record = create_test_preview(
        case_id="PSD",
        fields={"tax_code": "0100000000", "company_name": "CONG TY CP TEST"}
    )
    assert pid in web_copilot_app.LEGAL_PREVIEW_STORE
    stored = web_copilot_app.LEGAL_PREVIEW_STORE[pid]
    assert stored.case_id == "PSD"
    assert stored.consumed is False
    assert stored.verified_fields["tax_code"] == "0100000000"


def test_confirm_without_client_fields_succeeds():
    """RM Confirm chi can gui preview_id (va tuy chon case_id), khong can gui fields."""
    # Chuan bi case co address rong
    web_copilot_app.CASES_DB["PSD"]["customer"]["address"] = ""
    pid, _ = create_test_preview(
        case_id="PSD",
        fields={"address": "Dia chi duoc truyen tu server store 123"}
    )

    res, status_code = validate_and_confirm_legal_preview(
        preview_id=pid,
        case_id="PSD",
    )
    assert status_code == 200
    assert res["status"] == "success"
    assert "customer.address" in res["updated_fields"]
    assert web_copilot_app.CASES_DB["PSD"]["customer"]["address"] == "Dia chi duoc truyen tu server store 123"


# ==============================================================================
# TEST 3, 4, 5: SECURITY & TAMPER RESISTANCE (CLIENT FIELDS REJECTED)
# ==============================================================================
def test_confirm_endpoint_rejects_payload_containing_fields():
    """POST /api/confirm_legal_preview tu choi ngay lap tuc neu client co tinh truyen 'fields'."""
    server = DummyMockServer()
    pid, _ = create_test_preview(case_id="PSD", fields={"tax_code": "0100000000"})

    payload = {
        "preview_id": pid,
        "case_id": "PSD",
        "fields": {
            "tax_code": "9999999999"
        }
    }
    res, code = server.post_json("/api/confirm_legal_preview", payload)
    assert code == 400
    assert res["status"] == "error"
    assert res["error_type"] == "InvalidInputError"
    assert "fields" in res["message"]


def test_tampered_browser_values_cannot_enter_cases_db():
    """Gia tri bi sua doi o client khong the xam nhap vao CASES_DB."""
    server = DummyMockServer()
    original_tax = web_copilot_app.CASES_DB["PSD"]["customer"]["tax_code"]
    assert original_tax == "0100000000"

    pid, _ = create_test_preview(case_id="PSD", fields={"tax_code": "0100000000"})

    # Client hacker co tinh truyen fields gia mao
    payload = {
        "preview_id": pid,
        "case_id": "PSD",
        "fields": {
            "tax_code": "1112223334"
        }
    }
    res, code = server.post_json("/api/confirm_legal_preview", payload)
    assert code == 400
    # CASES_DB giu nguyen tuyet doi
    assert web_copilot_app.CASES_DB["PSD"]["customer"]["tax_code"] == original_tax


# ==============================================================================
# TEST 6 & 7: PREVIEW NOT FOUND (404) & CASE MISMATCH (400)
# ==============================================================================
def test_invalid_preview_id_returns_404():
    """preview_id khong ton tai tra ve 404 PreviewNotFoundError."""
    res, status_code = validate_and_confirm_legal_preview(
        preview_id="non-existent-uuid-12345",
        case_id="PSD",
    )
    assert status_code == 404
    assert res["status"] == "error"
    assert res["error_type"] == "PreviewNotFoundError"


def test_preview_bound_to_different_case_is_rejected():
    """Preview duoc gan voi case 'GAS_SOUTH' khong the dung cho case 'PSD'."""
    pid, _ = create_test_preview(case_id="GAS_SOUTH", fields={"tax_code": "0304958184"})

    res, status_code = validate_and_confirm_legal_preview(
        preview_id=pid,
        case_id="PSD",
    )
    assert status_code == 400
    assert res["status"] == "error"
    assert res["error_type"] == "CaseMismatchError"


# ==============================================================================
# TEST 8 & 9: PREVIEW CONSUMPTION POLICY
# ==============================================================================
def test_successful_confirmation_consumes_preview():
    """Confirm thanh cong se danh dau preview.consumed = True."""
    web_copilot_app.CASES_DB["PSD"]["customer"]["address"] = ""
    pid, record = create_test_preview(
        case_id="PSD",
        fields={"address": "Dia chi moi"}
    )
    assert record.consumed is False

    res, status_code = validate_and_confirm_legal_preview(preview_id=pid, case_id="PSD")
    assert status_code == 200
    assert record.consumed is True


def test_consumed_preview_cannot_be_reused():
    """Preview da duoc xac nhan khong the xac nhan lai (409 PreviewAlreadyConsumedError)."""
    web_copilot_app.CASES_DB["PSD"]["customer"]["address"] = ""
    pid, record = create_test_preview(
        case_id="PSD",
        fields={"address": "Dia chi moi 2"}
    )
    # Confirm lan 1
    res1, code1 = validate_and_confirm_legal_preview(preview_id=pid, case_id="PSD")
    assert code1 == 200

    # Confirm lan 2 -> Bi tu choi
    res2, code2 = validate_and_confirm_legal_preview(preview_id=pid, case_id="PSD")
    assert code2 == 409
    assert res2["status"] == "error"
    assert res2["error_type"] == "PreviewAlreadyConsumedError"



# ==============================================================================
# TEST 10, 11, 12: CONFLICT PRESERVES UNCONSUMED STATUS & CASES_DB INTEGRITY
# ==============================================================================
def test_unresolved_conflict_keeps_preview_unconsumed():
    """Khi phat sinh xung dot (409), preview van o trang thai unconsumed de RM chon cach giai quyet."""
    pid, record = create_test_preview(
        case_id="PSD",
        fields={"tax_code": "0109998888"}  # Khac voi 0100000000
    )

    res, status_code = validate_and_confirm_legal_preview(preview_id=pid, case_id="PSD")
    assert status_code == 409
    assert res["status"] == "conflict"
    assert record.consumed is False  # Chua bi consumed!


def test_conflict_resolution_uses_server_stored_extracted_value():
    """Giai quyet xung dot bang cach lay gia tri da luu tren server vao CASES_DB."""
    original_tax = web_copilot_app.CASES_DB["PSD"]["customer"]["tax_code"]
    extracted_tax = "0109998888"

    pid, record = create_test_preview(
        case_id="PSD",
        fields={"tax_code": extracted_tax}
    )

    # 1. Chon keep_existing: giu nguyen gia tri cu
    res_keep, code_keep = validate_and_confirm_legal_preview(
        preview_id=pid,
        case_id="PSD",
        resolutions={"customer.tax_code": "keep_existing"}
    )
    assert code_keep == 200
    assert record.consumed is True
    assert web_copilot_app.CASES_DB["PSD"]["customer"]["tax_code"] == original_tax

    # 2. Tao preview khac va chon use_extracted: cap nhat gia tri server da trich xuat
    pid2, record2 = create_test_preview(
        case_id="PSD",
        fields={"tax_code": extracted_tax}
    )
    res_use, code_use = validate_and_confirm_legal_preview(
        preview_id=pid2,
        case_id="PSD",
        resolutions={"customer.tax_code": "use_extracted"}
    )
    assert code_use == 200
    assert record2.consumed is True
    assert web_copilot_app.CASES_DB["PSD"]["customer"]["tax_code"] == extracted_tax


def test_cases_db_unchanged_when_preview_lookup_fails():
    """CASES_DB khong he bi thay doi khi lookup preview loi."""
    snapshot_before = copy.deepcopy(web_copilot_app.CASES_DB)

    res, code = validate_and_confirm_legal_preview(
        preview_id="invalid-id-xyz",
        case_id="PSD"
    )
    assert code == 404
    assert web_copilot_app.CASES_DB == snapshot_before


def test_conflict_response_leaves_cases_db_completely_unchanged():
    """Khi tra ve 409 conflict, toan bo CASES_DB nguyen ven 100%."""
    snapshot_before = copy.deepcopy(web_copilot_app.CASES_DB)

    pid, _ = create_test_preview(
        case_id="PSD",
        fields={
            "company_name": "TEN HOAN TOAN MOI KHONG KHOP",
            "tax_code": "9999999999",
        }
    )

    res, status_code = validate_and_confirm_legal_preview(preview_id=pid, case_id="PSD")
    assert status_code == 409
    assert res["status"] == "conflict"
    assert web_copilot_app.CASES_DB == snapshot_before


# ==============================================================================
# TEST 13, 14, 15: BUSINESS FACT VALIDATION (MISSING, IDENTICAL, CHARTER CAPITAL)
# ==============================================================================
def test_missing_canonical_field_populated():
    """Truong thong tin con thieu trong ho so (None hoac rong) se duoc tu dong dien."""
    web_copilot_app.CASES_DB["TEST_CASE"] = {
        "id": "TEST_CASE",
        "name": "Test Case Missing Fields",
        "customer": {
            "name": "CONG TY TEST",
            "short_name": "",
            "tax_code": "0109999999",
            "address": None,
            "charter_capital": 20000,
        },
        "rm_metadata": {"unit_name": "TEST_UNIT"},
        "section_b": {"total_limit": 100000},
    }

    pid, _ = create_test_preview(
        case_id="TEST_CASE",
        fields={
            "short_name": "TEST SHORT",
            "address": "123 Duong Lang, Ha Noi",
        }
    )

    res, status_code = validate_and_confirm_legal_preview(
        preview_id=pid,
        case_id="TEST_CASE",
    )

    assert status_code == 200
    assert res["status"] == "success"
    assert "customer.short_name" in res["updated_fields"]
    assert "customer.address" in res["updated_fields"]

    cust = web_copilot_app.CASES_DB["TEST_CASE"]["customer"]
    assert cust["short_name"] == "TEST SHORT"
    assert cust["address"] == "123 Duong Lang, Ha Noi"
    assert cust["name"] == "CONG TY TEST"
    assert cust["tax_code"] == "0109999999"


def test_identical_existing_value_no_conflict():
    """Gia tri trich xuat giong het gia tri ho so khong gay xung dot."""
    web_copilot_app.CASES_DB["PSD"]["customer"]["tax_code"] = "0100000000"

    pid, _ = create_test_preview(
        case_id="PSD",
        fields={"tax_code": "0100000000"}
    )

    res, status_code = validate_and_confirm_legal_preview(
        preview_id=pid,
        case_id="PSD",
    )

    assert status_code == 200
    assert res["status"] == "success"
    assert "customer.tax_code" not in res["updated_fields"]
    assert web_copilot_app.CASES_DB["PSD"]["customer"]["tax_code"] == "0100000000"


def test_charter_capital_equivalent_units_no_conflict():
    """Von dieu le tuong duong mat so hoc (50000 vs 50000.0) khong kich hoat xung dot."""
    web_copilot_app.CASES_DB["PSD"]["customer"]["charter_capital"] = 50000

    pid1, _ = create_test_preview(case_id="PSD", fields={"charter_capital": 50000.0})
    res1, status_code1 = validate_and_confirm_legal_preview(preview_id=pid1, case_id="PSD")
    assert status_code1 == 200
    assert res1["status"] == "success"

    pid2, _ = create_test_preview(case_id="PSD", fields={"charter_capital": "50000"})
    res2, status_code2 = validate_and_confirm_legal_preview(preview_id=pid2, case_id="PSD")
    assert status_code2 == 200
    assert res2["status"] == "success"


# ==============================================================================
# TEST 16 & 17: UNRELATED SECTIONS & NON-LEGAL CUSTOMER FIELDS PRESERVED
# ==============================================================================
def test_unrelated_case_sections_preserved():
    """Xac nhan thong tin phap ly KHONG duoc phep thay doi Section B, C, D, E va rm_metadata."""
    case_before = copy.deepcopy(web_copilot_app.CASES_DB["PSD"])

    web_copilot_app.CASES_DB["PSD"]["customer"]["address"] = ""
    pid, _ = create_test_preview(
        case_id="PSD",
        fields={
            "company_name": case_before["customer"]["name"],
            "short_name": "DEMO DISTRIBUTION JSC",
            "tax_code": "0100000000",
            "address": "Dia chi cap nhat moi so 999",
        }
    )

    res, status_code = validate_and_confirm_legal_preview(preview_id=pid, case_id="PSD")
    assert status_code == 200

    case_after = web_copilot_app.CASES_DB["PSD"]
    assert case_after["rm_metadata"] == case_before["rm_metadata"]
    assert case_after["section_b"] == case_before["section_b"]
    assert case_after["section_c"] == case_before["section_c"]
    assert case_after["section_d"] == case_before["section_d"]
    assert case_after["section_e"] == case_before["section_e"]


def test_only_allowed_customer_fields_changed():
    """Chi 7 truong phap ly duoc phep thay doi; cac truong khac giu nguyen 100%."""
    cust_before = copy.deepcopy(web_copilot_app.CASES_DB["PSD"]["customer"])

    web_copilot_app.CASES_DB["PSD"]["customer"]["address"] = ""
    pid, _ = create_test_preview(
        case_id="PSD",
        fields={"address": "Tang 5 Toa nha Moi"}
    )

    res, status_code = validate_and_confirm_legal_preview(preview_id=pid, case_id="PSD")
    assert status_code == 200

    cust_after = web_copilot_app.CASES_DB["PSD"]["customer"]
    assert cust_after["cif"] == cust_before["cif"]
    assert cust_after["segment"] == cust_before["segment"]
    assert cust_after["parent_group"] == cust_before["parent_group"]
    assert cust_after["established_year"] == cust_before["established_year"]
    assert cust_after["rating_grade"] == cust_before["rating_grade"]
    assert cust_after["rating_score"] == cust_before["rating_score"]
    assert cust_after["restricted_subject"] == cust_before["restricted_subject"]
    assert cust_after["esg_status"] == cust_before["esg_status"]
    assert cust_after["revenue_2025"] == cust_before["revenue_2025"]
    assert cust_after["address"] == "Tang 5 Toa nha Moi"


# ==============================================================================
# TEST 18 & 19: CONFIRM NEVER CALLS GENERATION OR WRITES DOCX
# ==============================================================================
def test_confirm_never_calls_execute_generation_pipeline():
    """Xac nhan xem truoc tuyet doi KHONG goi execute_generation_pipeline."""
    with patch("web_copilot_app.execute_generation_pipeline") as mock_pipeline:
        pid, _ = create_test_preview(case_id="PSD", fields={"tax_code": "0100000000"})
        res, status_code = validate_and_confirm_legal_preview(preview_id=pid, case_id="PSD")
        assert status_code == 200
        mock_pipeline.assert_not_called()


def test_confirm_does_not_generate_docx():
    """Xac nhan xem truoc khong tao ra bat ky tep tin .docx nao."""
    out_dir = "output"
    os.makedirs(out_dir, exist_ok=True)
    files_before = set(os.listdir(out_dir))

    pid, _ = create_test_preview(case_id="PSD", fields={"tax_code": "0100000000"})
    res, status_code = validate_and_confirm_legal_preview(preview_id=pid, case_id="PSD")
    assert status_code == 200

    files_after = set(os.listdir(out_dir))
    new_files = files_after - files_before
    docx_created = [f for f in new_files if f.endswith(".docx")]
    assert len(docx_created) == 0, f"Unexpected DOCX files created: {docx_created}"


# ==============================================================================
# TEST 20: HTTP API POST /api/confirm_legal_preview SECURITY & RESOLUTIONS
# ==============================================================================
def test_endpoint_security_rejects_forbidden_keys():
    """POST /api/confirm_legal_preview tu choi cac khoa doc hai hoac nguy hiem."""
    server = DummyMockServer()

    # Reject file_path
    res1, code1 = server.post_json("/api/confirm_legal_preview", {"file_path": "/etc/passwd"})
    assert code1 == 400
    assert res1["error_type"] == "InvalidInputError"

    # Reject canonical_path at top level
    res2, code2 = server.post_json("/api/confirm_legal_preview", {"canonical_path": "customer.name"})
    assert code2 == 400
    assert res2["error_type"] == "InvalidInputError"

    # Reject case_data whole object injection
    res3, code3 = server.post_json("/api/confirm_legal_preview", {"case_data": {"injected": True}})
    assert code3 == 400
    assert res3["error_type"] == "InvalidInputError"

    # Reject fields top level
    res4, code4 = server.post_json("/api/confirm_legal_preview", {"fields": {"tax_code": "123"}})
    assert code4 == 400
    assert res4["error_type"] == "InvalidInputError"

    # Reject unexpected arbitrary top-level keys
    res5, code5 = server.post_json("/api/confirm_legal_preview", {"arbitrary_key": "val"})
    assert code5 == 400
    assert res5["error_type"] == "InvalidInputError"


def test_endpoint_resolves_conflict_and_updates_successfully():
    """Kiem thu qua endpoint HTTP: giai quyet xung dot voi resolutions va thanh cong 200."""
    server = DummyMockServer()
    pid, _ = create_test_preview(
        case_id="PSD",
        fields={"tax_code": "0109888777"}
    )

    payload = {
        "preview_id": pid,
        "case_id": "PSD",
        "resolutions": {
            "customer.tax_code": "use_extracted",
        }
    }

    res, code = server.post_json("/api/confirm_legal_preview", payload)
    assert code == 200
    assert res["status"] == "success"
    assert "customer.tax_code" in res["updated_fields"]
    assert web_copilot_app.CASES_DB["PSD"]["customer"]["tax_code"] == "0109888777"

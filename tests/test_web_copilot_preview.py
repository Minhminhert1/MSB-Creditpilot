# -*- coding: utf-8 -*-
"""
Tests cho tính năng Preview Hồ sơ Pháp lý trong web_copilot_app.py:
- POST /api/preview_legal_pdf
- process_legal_pdf_preview(...)

Bảo đảm 11 cam kết bắt buộc:
1. Provider kỹ thuật số thực tế là "pypdf" (không phải "pdfplumber").
2. API Security: Chỉ nhận {filename, content_base64}, cấm client-supplied file_path.
3. Temp File Lifecycle: Tên ngẫu nhiên phía máy chủ, xóa trong khối finally, không lộ đường dẫn.
4. Input Validation: Định dạng .pdf, base64 hợp lệ, tệp không rỗng, kích thước < 15MB.
5. Exact Pipeline: temp PDF -> Router -> LegalExtractor -> LegalMapper (ZERO AIDocumentExtractor).
6. Precedence: CONFLICT > WARNING > MISSING > EXTRACTED.
7. Fixture test expectations: ABC JSC, MST 0101234567, vốn 50.000 triệu đồng, ĐDPL Nguyễn Văn An.
8. 100% Offline: ZERO network calls, ZERO real GreenNode calls.
9. Confirm button: Frontend state only, không có API save backend.
10. CASES_DB & ACTIVE_CASE_ID snapshot: Hoàn toàn không bị biến đổi.
11. Locked modules không bị sửa đổi.
"""

import base64
import copy
import io
import json
import os
import tempfile
import pytest
from unittest.mock import patch, MagicMock

import web_copilot_app
from web_copilot_app import (
    process_legal_pdf_preview,
    MAX_PREVIEW_UPLOAD_SIZE,
    CopilotHTTPHandler,
    CASES_DB,
    ACTIVE_CASE_ID,
)
from msb_eb_copilot.src.ingestion.router import DocumentIngestionResult
from msb_eb_copilot.src.extraction.legal_extraction import (
    EvidenceField,
    LegalDocumentExtraction,
    ExtractionAuditError,
)
from msb_eb_copilot.src.mapping.models import MappingConflict, MappingWarning


FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "pdf")
LEGAL_REGISTRATION_FIXTURE_PDF = os.path.join(FIXTURES_DIR, "legal_registration_fixture.pdf")
SCANNED_FIXTURE_PDF = os.path.join(FIXTURES_DIR, "scanned_legal_fixture.pdf")
ENCRYPTED_PDF = os.path.join(FIXTURES_DIR, "encrypted.pdf")


@pytest.fixture
def snapshot_case_state():
    """Snapshot CASES_DB and ACTIVE_CASE_ID before each test and verify after."""
    db_before = copy.deepcopy(web_copilot_app.CASES_DB)
    active_before = web_copilot_app.ACTIVE_CASE_ID
    yield
    assert web_copilot_app.CASES_DB == db_before, "VIOLATION: CASES_DB was mutated!"
    assert web_copilot_app.ACTIVE_CASE_ID == active_before, "VIOLATION: ACTIVE_CASE_ID was mutated!"


# ==============================================================================
# 1. DIGITAL LEGAL PDF PREVIEW TEST (OFFLINE MOCKED LLM)
# ==============================================================================
def test_digital_legal_pdf_preview(snapshot_case_state):
    """Kiểm thử trích xuất PDF số legal_registration_fixture.pdf:
    - mode = 'digital'
    - provider = 'pypdf'
    - 7 trường thông tin đúng kỳ vọng đã fix
    """
    assert os.path.exists(LEGAL_REGISTRATION_FIXTURE_PDF)
    with open(LEGAL_REGISTRATION_FIXTURE_PDF, "rb") as f:
        raw_bytes = f.read()

    mock_llm_json = {
        "company_name": {
            "value": "CÔNG TY CỔ PHẦN ABC",
            "evidence": "Tên doanh nghiệp: CÔNG TY CỔ PHẦN ABC",
            "page": 1,
        },
        "short_name": {
            "value": "ABC JSC",
            "evidence": "Tên viết tắt: ABC JSC",
            "page": 1,
        },
        "tax_code": {
            "value": "0101234567",
            "evidence": "Mã số doanh nghiệp: 0101234567",
            "page": 1,
        },
        "address": {
            "value": "Số 123 Phố Huế, Hà Nội",
            "evidence": "Địa chỉ trụ sở chính: Số 123 Phố Huế, Hà Nội",
            "page": 1,
        },
        "charter_capital_raw": {
            "value": "50.000.000.000 đồng",
            "evidence": "Vốn điều lệ: 50.000.000.000 đồng",
            "page": 2,
        },
        "legal_rep_name": {
            "value": "Ông Nguyễn Văn An",
            "evidence": "Họ và tên: Ông Nguyễn Văn An",
            "page": 2,
        },
        "legal_rep_title": {
            "value": "Giám đốc",
            "evidence": "Chức danh: Giám đốc",
            "page": 2,
        },
    }

    with patch("msb_eb_copilot.src.ai_client.AIAssistantClient.chat", return_value=json.dumps(mock_llm_json)):
        res, status_code = process_legal_pdf_preview(raw_bytes, "legal_registration_fixture.pdf")

    assert status_code == 200
    assert res["status"] == "success"
    assert res["filename"] == "legal_registration_fixture.pdf"

    # 1. Routing assertions
    routing = res["routing"]
    assert routing["mode"] == "digital"
    assert routing["provider"] == "pypdf"  # MUST be pypdf, NOT pdfplumber
    assert routing["page_count"] == 2
    assert routing["fallback_reason"] is None

    # 7 Canonical fields assertions
    fields = res["fields"]
    assert set(fields.keys()) == {
        "company_name",
        "short_name",
        "tax_code",
        "address",
        "charter_capital",
        "legal_rep_name",
        "legal_rep_title",
    }

    # Verify company_name
    assert fields["company_name"]["status"] == "EXTRACTED"
    assert fields["company_name"]["value"] == "CÔNG TY CỔ PHẦN ABC"
    assert fields["company_name"]["canonical_path"] == "customer.name"
    assert fields["company_name"]["page"] == 1
    assert "CÔNG TY CỔ PHẦN ABC" in fields["company_name"]["evidence"]

    # Verify short_name
    assert fields["short_name"]["status"] == "EXTRACTED"
    assert fields["short_name"]["value"] == "ABC JSC"
    assert fields["short_name"]["canonical_path"] == "customer.short_name"
    assert fields["short_name"]["page"] == 1

    # Verify tax_code
    assert fields["tax_code"]["status"] == "EXTRACTED"
    assert fields["tax_code"]["value"] == "0101234567"
    assert fields["tax_code"]["canonical_path"] == "customer.tax_code"
    assert fields["tax_code"]["page"] == 1

    # Verify address
    assert fields["address"]["status"] == "EXTRACTED"
    assert fields["address"]["value"] == "Số 123 Phố Huế, Hà Nội"
    assert fields["address"]["canonical_path"] == "customer.address"

    # Verify charter_capital (normalized numeric to million VND: 50,000)
    assert fields["charter_capital"]["status"] == "EXTRACTED"
    assert fields["charter_capital"]["value"] == 50000
    assert fields["charter_capital"]["source_value"] == "50.000.000.000 đồng"
    assert fields["charter_capital"]["canonical_path"] == "customer.charter_capital"
    assert fields["charter_capital"]["page"] == 2

    # Verify legal_rep_name (honorific stripped by extractor: "Nguyễn Văn An")
    assert fields["legal_rep_name"]["status"] == "EXTRACTED"
    assert fields["legal_rep_name"]["value"] == "Nguyễn Văn An"
    assert fields["legal_rep_name"]["source_value"] == "Nguyễn Văn An"
    assert "Ông Nguyễn Văn An" in fields["legal_rep_name"]["evidence"]
    assert fields["legal_rep_name"]["canonical_path"] == "customer.legal_rep_name"
    assert fields["legal_rep_name"]["page"] == 2

    # Verify legal_rep_title
    assert fields["legal_rep_title"]["status"] == "EXTRACTED"
    assert fields["legal_rep_title"]["value"] == "Giám đốc"
    assert fields["legal_rep_title"]["canonical_path"] == "customer.legal_rep_title"
    assert fields["legal_rep_title"]["page"] == 2


# ==============================================================================
# 2. SCANNED OCR LEGAL PDF PREVIEW TEST (OFFLINE MOCKED OCR & LLM)
# ==============================================================================
def test_scanned_legal_pdf_preview(snapshot_case_state):
    """Kiểm thử tài liệu scan với OCR fallback (offline):
    - mode = 'ocr'
    - provider = 'qwen_vision'
    - fallback_reason = 'PDFBlankPageError'
    """
    assert os.path.exists(SCANNED_FIXTURE_PDF)
    with open(SCANNED_FIXTURE_PDF, "rb") as f:
        raw_bytes = f.read()

    mock_ingestion_result = DocumentIngestionResult(
        tagged_text=(
            "[PAGE 1]\n"
            "Tên doanh nghiệp: CÔNG TY CỔ PHẦN SCANNED TEST\n"
            "Tên viết tắt: SCAN JSC\n"
            "Mã số doanh nghiệp: 0398765432\n"
            "Địa chỉ trụ sở chính: 456 Nguyễn Thị Minh Khai, Q3, TP HCM\n\n"
            "[PAGE 2]\n"
            "Vốn điều lệ: 80.000.000.000 đồng\n"
            "Họ và tên: Ông Trần Văn B\n"
            "Chức danh: Tổng Giám đốc\n"
        ),
        mode="ocr",
        page_count=2,
        fallback_reason="PDFBlankPageError",
        provider="qwen_vision",
    )

    mock_llm_json = {
        "company_name": {
            "value": "CÔNG TY CỔ PHẦN SCANNED TEST",
            "evidence": "Tên doanh nghiệp: CÔNG TY CỔ PHẦN SCANNED TEST",
            "page": 1,
        },
        "short_name": {
            "value": "SCAN JSC",
            "evidence": "Tên viết tắt: SCAN JSC",
            "page": 1,
        },
        "tax_code": {
            "value": "0398765432",
            "evidence": "Mã số doanh nghiệp: 0398765432",
            "page": 1,
        },
        "address": {
            "value": "456 Nguyễn Thị Minh Khai, Q3, TP HCM",
            "evidence": "Địa chỉ trụ sở chính: 456 Nguyễn Thị Minh Khai, Q3, TP HCM",
            "page": 1,
        },
        "charter_capital_raw": {
            "value": "80.000.000.000 đồng",
            "evidence": "Vốn điều lệ: 80.000.000.000 đồng",
            "page": 2,
        },
        "legal_rep_name": {
            "value": "Ông Trần Văn B",
            "evidence": "Họ và tên: Ông Trần Văn B",
            "page": 2,
        },
        "legal_rep_title": {
            "value": "Tổng Giám đốc",
            "evidence": "Chức danh: Tổng Giám đốc",
            "page": 2,
        },
    }

    with patch("web_copilot_app.DocumentIngestionRouter.ingest_document", return_value=mock_ingestion_result):
        with patch("msb_eb_copilot.src.ai_client.AIAssistantClient.chat", return_value=json.dumps(mock_llm_json)):
            res, status_code = process_legal_pdf_preview(raw_bytes, "scanned_fixture.pdf")

    assert status_code == 200
    assert res["status"] == "success"
    assert res["routing"]["mode"] == "ocr"
    assert res["routing"]["provider"] == "qwen_vision"
    assert res["routing"]["fallback_reason"] == "PDFBlankPageError"
    assert res["fields"]["charter_capital"]["value"] == 80000
    assert res["fields"]["legal_rep_name"]["value"] == "Trần Văn B"


# ==============================================================================
# 3. LEGACY AIDocumentExtractor NEVER CALLED
# ==============================================================================
def test_legacy_ai_document_extractor_never_called(snapshot_case_state):
    """Khẳng định AIDocumentExtractor không được gọi trong luồng preview pháp lý mới."""
    with open(LEGAL_REGISTRATION_FIXTURE_PDF, "rb") as f:
        raw_bytes = f.read()

    with patch.object(web_copilot_app, "AIDocumentExtractor") as mock_legacy:
        mock_llm_json = {
            "company_name": {"value": "CÔNG TY CỔ PHẦN ABC", "evidence": "Tên doanh nghiệp: CÔNG TY CỔ PHẦN ABC", "page": 1},
            "short_name": {"value": None, "evidence": None, "page": None},
            "tax_code": {"value": "0101234567", "evidence": "Mã số doanh nghiệp: 0101234567", "page": 1},
            "address": {"value": "Số 123 Phố Huế, Hà Nội", "evidence": "Địa chỉ trụ sở chính: Số 123 Phố Huế, Hà Nội", "page": 1},
            "charter_capital_raw": {"value": "50.000.000.000 đồng", "evidence": "Vốn điều lệ: 50.000.000.000 đồng", "page": 2},
            "legal_rep_name": {"value": "Ông Nguyễn Văn An", "evidence": "Họ và tên: Ông Nguyễn Văn An", "page": 2},
            "legal_rep_title": {"value": "Giám đốc", "evidence": "Chức danh: Giám đốc", "page": 2},
        }
        with patch("msb_eb_copilot.src.ai_client.AIAssistantClient.chat", return_value=json.dumps(mock_llm_json)):
            process_legal_pdf_preview(raw_bytes, "legal.pdf")

        mock_legacy.assert_not_called()
        mock_legacy.read_file_content.assert_not_called()
        mock_legacy.extract_from_text.assert_not_called()


# ==============================================================================
# 4. PREVIEW FIELD STATUS PRECEDENCE: CONFLICT > WARNING > MISSING > EXTRACTED
# ==============================================================================
def test_status_precedence_warning_and_missing(snapshot_case_state):
    """Kiểm thử thứ tự ưu tiên trạng thái:
    - short_name = None -> status='MISSING'
    - charter_capital unparseable -> mapper sinh warning -> status='WARNING'
    """
    with open(LEGAL_REGISTRATION_FIXTURE_PDF, "rb") as f:
        raw_bytes = f.read()

    # charter_capital_raw with unrecognized currency unit -> mapper emits MappingWarning
    mock_llm_json = {
        "company_name": {"value": "CÔNG TY CỔ PHẦN ABC", "evidence": "Tên doanh nghiệp: CÔNG TY CỔ PHẦN ABC", "page": 1},
        "short_name": {"value": None, "evidence": None, "page": None},  # MISSING
        "tax_code": {"value": "0101234567", "evidence": "Mã số doanh nghiệp: 0101234567", "page": 1},
        "address": {"value": "Số 123 Phố Huế, Hà Nội", "evidence": "Địa chỉ trụ sở chính: Số 123 Phố Huế, Hà Nội", "page": 1},
        "charter_capital_raw": {
            "value": "50.000",  # WARNING: No explicit recognized currency unit
            "evidence": "Vốn điều lệ: 50.000.000.000 đồng",
            "page": 2,
        },
        "legal_rep_name": {"value": "Ông Nguyễn Văn An", "evidence": "Họ và tên: Ông Nguyễn Văn An", "page": 2},
        "legal_rep_title": {"value": "Giám đốc", "evidence": "Chức danh: Giám đốc", "page": 2},
    }

    with patch("msb_eb_copilot.src.ai_client.AIAssistantClient.chat", return_value=json.dumps(mock_llm_json)):
        res, status_code = process_legal_pdf_preview(raw_bytes, "legal.pdf")

    assert status_code == 200
    fields = res["fields"]

    # short_name is MISSING
    assert fields["short_name"]["status"] == "MISSING"
    assert fields["short_name"]["value"] is None
    assert fields["short_name"]["source_value"] is None

    # charter_capital has WARNING
    assert fields["charter_capital"]["status"] == "WARNING"
    assert fields["charter_capital"]["value"] is None
    assert fields["charter_capital"]["warning_reason"] is not None

    # company_name is EXTRACTED
    assert fields["company_name"]["status"] == "EXTRACTED"
    assert fields["company_name"]["value"] == "CÔNG TY CỔ PHẦN ABC"


# ==============================================================================
# 5. TEMP FILE LIFECYCLE & CLEANUP
# ==============================================================================
def test_temp_file_deleted_in_finally(snapshot_case_state):
    """Đảm bảo temp file luôn được dọn dẹp (xóa) trong khối finally kể cả khi có lỗi."""
    created_temp_files = []
    original_named_temp_file = tempfile.NamedTemporaryFile

    def spy_named_temp_file(*args, **kwargs):
        tmp = original_named_temp_file(*args, **kwargs)
        created_temp_files.append(tmp.name)
        return tmp

    # Test trường hợp thành công
    with patch("tempfile.NamedTemporaryFile", side_effect=spy_named_temp_file):
        with open(LEGAL_REGISTRATION_FIXTURE_PDF, "rb") as f:
            raw_bytes = f.read()
        mock_llm_json = {
            "company_name": {"value": "CÔNG TY CỔ PHẦN ABC", "evidence": "Tên doanh nghiệp: CÔNG TY CỔ PHẦN ABC", "page": 1},
            "short_name": {"value": "ABC JSC", "evidence": "Tên viết tắt: ABC JSC", "page": 1},
            "tax_code": {"value": "0101234567", "evidence": "Mã số doanh nghiệp: 0101234567", "page": 1},
            "address": {"value": "Số 123 Phố Huế, Hà Nội", "evidence": "Địa chỉ trụ sở chính: Số 123 Phố Huế, Hà Nội", "page": 1},
            "charter_capital_raw": {"value": "50.000.000.000 đồng", "evidence": "Vốn điều lệ: 50.000.000.000 đồng", "page": 2},
            "legal_rep_name": {"value": "Ông Nguyễn Văn An", "evidence": "Họ và tên: Ông Nguyễn Văn An", "page": 2},
            "legal_rep_title": {"value": "Giám đốc", "evidence": "Chức danh: Giám đốc", "page": 2},
        }
        with patch("msb_eb_copilot.src.ai_client.AIAssistantClient.chat", return_value=json.dumps(mock_llm_json)):
            process_legal_pdf_preview(raw_bytes, "doc.pdf")

    assert len(created_temp_files) == 1
    assert not os.path.exists(created_temp_files[0]), "Temp file was NOT deleted after preview!"


# ==============================================================================
# 6. SAFE ERROR HANDLING: ENCRYPTED, AUDIT ERROR, MALFORMED
# ==============================================================================
def test_encrypted_pdf_returns_safe_vietnamese_message(snapshot_case_state):
    """Kiểm thử file bị đặt mật khẩu trả về mã lỗi 400 và thông điệp an toàn."""
    assert os.path.exists(ENCRYPTED_PDF)
    with open(ENCRYPTED_PDF, "rb") as f:
        raw_bytes = f.read()

    res, status_code = process_legal_pdf_preview(raw_bytes, "encrypted.pdf")
    assert status_code == 400
    assert res["status"] == "error"
    assert res["error_type"] == "PDFEncryptedError"
    assert "mật khẩu" in res["message"]


def test_audit_error_returns_safe_vietnamese_message(snapshot_case_state):
    """Kiểm thử vi phạm kiểm định chuỗi bằng chứng (ExtractionAuditError) trả về mã 422."""
    with open(LEGAL_REGISTRATION_FIXTURE_PDF, "rb") as f:
        raw_bytes = f.read()

    # Evidence that does NOT exist in document text triggers ExtractionAuditError
    mock_llm_json = {
        "company_name": {
            "value": "CÔNG TY BỊA ĐẶT",
            "evidence": "Tên doanh nghiệp: CÔNG TY BỊA ĐẶT HOÀN TOÀN",
            "page": 1,
        },
        "short_name": {"value": None, "evidence": None, "page": None},
        "tax_code": {"value": None, "evidence": None, "page": None},
        "address": {"value": None, "evidence": None, "page": None},
        "charter_capital_raw": {"value": None, "evidence": None, "page": None},
        "legal_rep_name": {"value": None, "evidence": None, "page": None},
        "legal_rep_title": {"value": None, "evidence": None, "page": None},
    }

    with patch("msb_eb_copilot.src.ai_client.AIAssistantClient.chat", return_value=json.dumps(mock_llm_json)):
        res, status_code = process_legal_pdf_preview(raw_bytes, "legal.pdf")

    assert status_code == 422
    assert res["status"] == "error"
    assert res["error_type"] == "ExtractionAuditError"
    assert "bằng chứng" in res["message"]


# ==============================================================================
# 7. HTTP ENDPOINT POST VALIDATION & SECURITY CONTRACT
# ==============================================================================
class DummyMockServer:
    """Mock HTTP Request Handler helper for testing do_POST directly."""
    def __init__(self):
        self.response_status = None
        self.response_headers = {}
        self.response_body = None

    def make_handler(self, post_data_dict):
        body_bytes = json.dumps(post_data_dict).encode("utf-8")
        handler = CopilotHTTPHandler.__new__(CopilotHTTPHandler)
        handler.path = "/api/preview_legal_pdf"
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

        return handler


def test_endpoint_rejects_client_file_path(snapshot_case_state):
    """Cấm client-supplied file_path: Server sở hữu mọi đường dẫn filesystem."""
    server = DummyMockServer()
    handler = server.make_handler({
        "filename": "test.pdf",
        "content_base64": base64.b64encode(b"%PDF-1.4 dummy").decode("utf-8"),
        "file_path": "/etc/passwd"  # Strictly forbidden!
    })
    handler.do_POST()

    assert server.response_status == 400
    assert server.response_body["error_type"] == "InvalidInputError"


def test_endpoint_rejects_non_pdf_extension(snapshot_case_state):
    """Kiểm tra từ chối các tệp không có đuôi .pdf."""
    server = DummyMockServer()
    handler = server.make_handler({
        "filename": "malicious.exe",
        "content_base64": base64.b64encode(b"dummy").decode("utf-8"),
    })
    handler.do_POST()

    assert server.response_status == 400
    assert server.response_body["error_type"] == "InvalidFormatError"


def test_endpoint_rejects_malformed_base64(snapshot_case_state):
    """Kiểm tra từ chối chuỗi base64 bị hỏng."""
    server = DummyMockServer()
    handler = server.make_handler({
        "filename": "legal.pdf",
        "content_base64": "!!!not_valid_base64@@@",
    })
    handler.do_POST()

    assert server.response_status == 400
    assert server.response_body["error_type"] == "InvalidBase64Error"


def test_endpoint_rejects_empty_file(snapshot_case_state):
    """Kiểm tra từ chối tệp rỗng 0 bytes."""
    server = DummyMockServer()
    handler = server.make_handler({
        "filename": "empty.pdf",
        "content_base64": "",  # Empty
    })
    handler.do_POST()

    assert server.response_status == 400
    assert server.response_body["error_type"] == "InvalidInputError"


def test_endpoint_rejects_file_exceeding_max_size(snapshot_case_state):
    """Kiểm tra từ chối tệp vượt quá kích thước MAX_PREVIEW_UPLOAD_SIZE."""
    server = DummyMockServer()
    huge_bytes = b"0" * (MAX_PREVIEW_UPLOAD_SIZE + 1024)
    handler = server.make_handler({
        "filename": "huge.pdf",
        "content_base64": base64.b64encode(huge_bytes).decode("utf-8"),
    })
    handler.do_POST()

    assert server.response_status == 400
    assert server.response_body["error_type"] == "FileTooLargeError"

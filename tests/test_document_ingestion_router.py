# -*- coding: utf-8 -*-
"""
Tests cho module router.py (DocumentIngestionRouter).
Bảo đảm:
- 100% Deterministic Offline Tests: ZERO network calls, ZERO real GreenNode calls.
- Kiểm thử chính sách Digital-first: Ưu tiên digital text, chỉ OCR fallback khi phát hiện trang ảnh/quét.
- Kiểm thử CORRECTION 1: Chỉ PDFBlankPageError mới kích hoạt OCR fallback; plain PDFNoTextError (0 trang)
  lan truyền lỗi và TUYỆT ĐỐI không gọi OCR.
- Kiểm thử CORRECTION 2: Metadata nguồn gốc (page_count, provider, fallback_reason) lấy trực tiếp
  từ nguồn chân lý (pypdf cho digital, OCRDocumentResult cho OCR).
- Kiểm thử lan truyền trung thực các ngoại lệ: File not found, Encrypted, Corrupted, Timeout, Service error.
- Kiểm thử tích hợp trọn vẹn A & B:
  A. Digital PDF -> Router (mode='digital') -> LegalDocumentExtractor.
  B. Scanned PDF -> Router (mode='ocr') -> LegalDocumentExtractor.
"""

import os
import json
import threading
import pytest
import pypdf
from unittest.mock import patch, MagicMock

from msb_eb_copilot.src.ingestion.router import (
    DocumentIngestionRouter,
    DocumentIngestionResult,
)
from msb_eb_copilot.src.ingestion.pdf_text import (
    PDFTextIngestor,
    PDFBlankPageError,
    PDFNoTextError,
    PDFFileNotFoundError,
    PDFEncryptedError,
    PDFIngestionError,
)
from msb_eb_copilot.src.ingestion.pdf_ocr import (
    PDFOCRIngestor,
    BaseOCREngine,
    OCRPageResult,
    OCRDocumentResult,
    OCRTimeoutError,
    OCRServiceError,
)
from msb_eb_copilot.src.extraction.legal_extraction import (
    LegalDocumentExtractor,
    LegalDocumentExtraction,
)


FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "pdf")
SAMPLE_MULTIPAGE_PDF = os.path.join(FIXTURES_DIR, "sample_multipage.pdf")
LEGAL_REGISTRATION_FIXTURE_PDF = os.path.join(FIXTURES_DIR, "legal_registration_fixture.pdf")
SCANNED_FIXTURE_PDF = os.path.join(FIXTURES_DIR, "scanned_legal_fixture.pdf")
MIXED_BLANK_PDF = os.path.join(FIXTURES_DIR, "mixed_blank.pdf")
ENCRYPTED_PDF = os.path.join(FIXTURES_DIR, "encrypted.pdf")


class DummyCustomOCREngine(BaseOCREngine):
    provider_name = "custom_vendor_engine"

    def __init__(self, responses=None):
        self.responses = responses or {}
        self.call_count = 0
        self._lock = threading.Lock()

    def ocr_page(self, base64_png: str, page_num: int) -> str:
        with self._lock:
            self.call_count += 1
        return self.responses.get(page_num, f"Nội dung OCR giả lập trang {page_num}")


# ==============================================================================
# 1. ROUTING POLICY & ZERO-DOUBLE-PROCESSING TESTS
# ==============================================================================
def test_digital_pdf_routes_to_digital():
    """Tệp PDF kỹ thuật số mẫu: Router chọn mode='digital', provider='pypdf'."""
    assert os.path.exists(SAMPLE_MULTIPAGE_PDF)
    result = DocumentIngestionRouter.ingest_document(SAMPLE_MULTIPAGE_PDF)

    assert isinstance(result, DocumentIngestionResult)
    assert result.mode == "digital"
    assert result.provider == "pypdf"
    assert result.fallback_reason is None

    # page_count bằng chính xác số trang vật lý từ pypdf
    expected_count = len(pypdf.PdfReader(SAMPLE_MULTIPAGE_PDF).pages)
    assert result.page_count == expected_count

    # tagged_text bắt đầu bằng [PAGE 1]
    assert result.tagged_text.startswith("[PAGE 1]\n")
    assert "[PAGE 2]" in result.tagged_text


def test_ocr_never_called_on_digital_success():
    """Khi trích xuất digital thành công: PDFOCRIngestor TUYỆT ĐỐI không bao giờ được gọi."""
    assert os.path.exists(SAMPLE_MULTIPAGE_PDF)
    with patch("msb_eb_copilot.src.ingestion.pdf_ocr.PDFOCRIngestor.extract_document") as mock_ocr:
        result = DocumentIngestionRouter.ingest_document(SAMPLE_MULTIPAGE_PDF)
        assert result.mode == "digital"
        assert mock_ocr.call_count == 0


def test_scanned_pdf_routes_to_ocr():
    """Tệp scanned_legal_fixture.pdf là ảnh: PDFTextIngestor gặp PDFBlankPageError -> Router kích hoạt OCR."""
    assert os.path.exists(SCANNED_FIXTURE_PDF)
    engine = DummyCustomOCREngine(responses={
        1: "Trang 1 quét: CÔNG TY ABC",
        2: "Trang 2 quét: Vốn 85 tỷ"
    })

    result = DocumentIngestionRouter.ingest_document(SCANNED_FIXTURE_PDF, ocr_engine=engine)

    assert isinstance(result, DocumentIngestionResult)
    assert result.mode == "ocr"
    assert result.fallback_reason == "PDFBlankPageError"
    assert result.provider == "custom_vendor_engine"
    assert result.page_count == 2
    assert result.tagged_text.startswith("[PAGE 1]\nTrang 1 quét: CÔNG TY ABC")
    assert "\n\n[PAGE 2]\nTrang 2 quét: Vốn 85 tỷ" in result.tagged_text

    # Engine được gọi đúng 2 lần cho 2 trang vật lý
    assert engine.call_count == 2


def test_mixed_pdf_routes_to_hybrid():
    """Tệp mixed_blank.pdf (trang 1 digital, trang 2 trắng/ảnh):
    Patch 1.5A: Router bóc tách trang 1 bằng pypdf và CHỈ gửi trang 2 qua OCR (hybrid page-level routing).
    """
    assert os.path.exists(MIXED_BLANK_PDF)
    engine = DummyCustomOCREngine(responses={
        1: "Trang 1 hỗn hợp qua OCR",
        2: "Trang 2 hỗn hợp qua OCR"
    })

    result = DocumentIngestionRouter.ingest_document(MIXED_BLANK_PDF, ocr_engine=engine)

    assert result.mode == "hybrid"
    assert result.provider == "pypdf+custom_vendor_engine"
    assert result.fallback_reason == "PDFBlankPageError"
    assert result.page_count == 2
    # Trang 1 lấy trực tiếp văn bản kỹ thuật số (không qua OCR engine)
    assert result.tagged_text.startswith("[PAGE 1]\nCÔNG TY CỔ PHẦN KINH DOANH KHÍ MIỀN NAM")
    # Trang 2 nhận dạng qua OCR engine
    assert "\n\n[PAGE 2]\nTrang 2 hỗn hợp qua OCR" in result.tagged_text
    # Engine CHỈ được gọi đúng 1 lần cho trang 2 (trang 1 hoàn toàn không bị gọi OCR)
    assert engine.call_count == 1


# ==============================================================================
# 2. CORRECTION 1: NARROW OCR FALLBACK TESTS (BlankPageError vs Plain NoTextError)
# ==============================================================================
def test_pdf_blank_page_error_triggers_ocr():
    """PDFBlankPageError (trang không có text khả dụng) kích hoạt OCR chính xác 1 lần."""
    with patch("msb_eb_copilot.src.ingestion.pdf_text.PDFTextIngestor.extract_text_with_page_markers",
               side_effect=PDFBlankPageError("Trang 1 không có text")):
        with patch("msb_eb_copilot.src.ingestion.pdf_ocr.PDFOCRIngestor.extract_document") as mock_ocr:
            mock_ocr.return_value = OCRDocumentResult(
                tagged_text="[PAGE 1]\nVăn bản OCR",
                page_count=1,
                pages=[OCRPageResult(page_num=1, text="Văn bản OCR")],
                provider="mock_qwen"
            )
            result = DocumentIngestionRouter.ingest_document("dummy.pdf")
            assert result.mode == "ocr"
            assert result.fallback_reason == "PDFBlankPageError"
            assert mock_ocr.call_count == 1


def test_plain_pdf_no_text_error_does_not_trigger_ocr():
    """Plain PDFNoTextError (tài liệu 0 trang) là tệp không hợp lệ -> Lan truyền nguyên vẹn, KHÔNG gọi OCR."""
    with patch("msb_eb_copilot.src.ingestion.pdf_text.PDFTextIngestor.extract_text_with_page_markers",
               side_effect=PDFNoTextError("Tệp PDF có 0 trang")):
        with patch("msb_eb_copilot.src.ingestion.pdf_ocr.PDFOCRIngestor.extract_document") as mock_ocr:
            with pytest.raises(PDFNoTextError, match="0 trang"):
                DocumentIngestionRouter.ingest_document("dummy.pdf")
            # Khẳng định OCR call count == 0
            assert mock_ocr.call_count == 0


# ==============================================================================
# 3. EXCEPTION PROPAGATION & NON-FALLBACK TESTS
# ==============================================================================
def test_file_not_found_does_not_trigger_ocr():
    """Tệp không tồn tại: Lan truyền PDFFileNotFoundError, KHÔNG gọi OCR."""
    non_existent = os.path.join(FIXTURES_DIR, "non_existent_file.pdf")
    with patch("msb_eb_copilot.src.ingestion.pdf_ocr.PDFOCRIngestor.extract_document") as mock_ocr:
        with pytest.raises(PDFFileNotFoundError):
            DocumentIngestionRouter.ingest_document(non_existent)
        assert mock_ocr.call_count == 0


def test_encrypted_pdf_does_not_trigger_ocr():
    """Tệp bị khóa mật khẩu: Lan truyền PDFEncryptedError, KHÔNG gọi OCR."""
    assert os.path.exists(ENCRYPTED_PDF)
    with patch("msb_eb_copilot.src.ingestion.pdf_ocr.PDFOCRIngestor.extract_document") as mock_ocr:
        with pytest.raises(PDFEncryptedError):
            DocumentIngestionRouter.ingest_document(ENCRYPTED_PDF)
        assert mock_ocr.call_count == 0


def test_generic_pdf_ingestion_error_does_not_trigger_ocr():
    """Lỗi tệp PDF hỏng cú pháp (PDFIngestionError): Lan truyền lỗi, KHÔNG gọi OCR."""
    with patch("msb_eb_copilot.src.ingestion.pdf_text.PDFTextIngestor.extract_text_with_page_markers",
               side_effect=PDFIngestionError("Tệp PDF bị hỏng")):
        with patch("msb_eb_copilot.src.ingestion.pdf_ocr.PDFOCRIngestor.extract_document") as mock_ocr:
            with pytest.raises(PDFIngestionError, match="bị hỏng"):
                DocumentIngestionRouter.ingest_document("dummy.pdf")
            assert mock_ocr.call_count == 0


def test_ocr_timeout_propagates_faithfully():
    """Khi OCR fallback gặp lỗi timeout: Lan truyền trực tiếp OCRTimeoutError."""
    assert os.path.exists(SCANNED_FIXTURE_PDF)
    with patch("msb_eb_copilot.src.ingestion.pdf_ocr.PDFOCRIngestor.extract_document",
               side_effect=OCRTimeoutError("Timeout sau 60s")):
        with pytest.raises(OCRTimeoutError, match="Timeout sau 60s"):
            DocumentIngestionRouter.ingest_document(SCANNED_FIXTURE_PDF)


def test_ocr_service_error_propagates_faithfully():
    """Khi OCR fallback gặp sự cố máy chủ: Lan truyền trực tiếp OCRServiceError."""
    assert os.path.exists(SCANNED_FIXTURE_PDF)
    with patch("msb_eb_copilot.src.ingestion.pdf_ocr.PDFOCRIngestor.extract_document",
               side_effect=OCRServiceError("Lỗi kết nối 500")):
        with pytest.raises(OCRServiceError, match="Lỗi kết nối 500"):
            DocumentIngestionRouter.ingest_document(SCANNED_FIXTURE_PDF)


# ==============================================================================
# 4. METADATA PURITY & HELPER FUNCTION TESTS
# ==============================================================================
def test_ingest_to_tagged_text_matches_result_tagged_text():
    """Hàm tiện ích ingest_to_tagged_text trả về chính xác chuỗi tagged_text nguyên vẹn không chèn metadata."""
    assert os.path.exists(SAMPLE_MULTIPAGE_PDF)
    res_obj = DocumentIngestionRouter.ingest_document(SAMPLE_MULTIPAGE_PDF)
    clean_text = DocumentIngestionRouter.ingest_to_tagged_text(SAMPLE_MULTIPAGE_PDF)

    assert clean_text == res_obj.tagged_text
    # Không bị chèn các header metadata tùy tiện
    assert clean_text.startswith("[PAGE 1]\n")
    assert "mode=" not in clean_text
    assert "provider=" not in clean_text


# ==============================================================================
# 5. INTEGRATION TESTS A & B (Router -> LegalDocumentExtractor)
# ==============================================================================
def test_integration_a_digital_router_to_legal_extractor():
    """Kiểm thử tích hợp A:
    legal_registration_fixture.pdf -> Router -> mode='digital' -> tagged_text -> LegalDocumentExtractor.
    """
    assert os.path.exists(LEGAL_REGISTRATION_FIXTURE_PDF)

    with patch("msb_eb_copilot.src.ingestion.pdf_ocr.PDFOCRIngestor.extract_document") as mock_ocr:
        result = DocumentIngestionRouter.ingest_document(LEGAL_REGISTRATION_FIXTURE_PDF)

        assert result.mode == "digital"
        assert result.provider == "pypdf"
        assert result.fallback_reason is None
        assert mock_ocr.call_count == 0

        tagged_text = result.tagged_text
        assert tagged_text.startswith("[PAGE 1]\n")

        mock_llm_json = {
            "company_name": {
                "value": "CÔNG TY CỔ PHẦN ABC",
                "evidence": "Tên doanh nghiệp: CÔNG TY CỔ PHẦN ABC",
                "page": 1
            },
            "short_name": {
                "value": "ABC JSC",
                "evidence": "Tên viết tắt: ABC JSC",
                "page": 1
            },
            "tax_code": {
                "value": "0101234567",
                "evidence": "Mã số doanh nghiệp: 0101234567",
                "page": 1
            },
            "address": {
                "value": "Số 123 Phố Huế, Hà Nội",
                "evidence": "Địa chỉ trụ sở chính: Số 123 Phố Huế, Hà Nội",
                "page": 1
            },
            "charter_capital_raw": {
                "value": "50.000.000.000 đồng",
                "evidence": "Vốn điều lệ: 50.000.000.000 đồng",
                "page": 2
            },
            "legal_rep_name": {
                "value": "Ông Nguyễn Văn An",
                "evidence": "Họ và tên: Ông Nguyễn Văn An",
                "page": 2
            },
            "legal_rep_title": {
                "value": "Giám đốc",
                "evidence": "Chức danh: Giám đốc",
                "page": 2
            }
        }

        # Khẳng định nghiêm ngặt trước khi gọi extractor: Mọi evidence đều có mặt trong tagged_text
        for field_name, field_data in mock_llm_json.items():
            evi = field_data["evidence"]
            if evi is not None:
                assert evi in tagged_text, f"Evidence for {field_name} not found in actual tagged_text: '{evi}'"

        with patch("msb_eb_copilot.src.ai_client.AIAssistantClient.chat", return_value=json.dumps(mock_llm_json)):
            extraction = LegalDocumentExtractor.extract(tagged_text)
            assert isinstance(extraction, LegalDocumentExtraction)
            assert extraction.company_name.value == "CÔNG TY CỔ PHẦN ABC"
            assert extraction.tax_code.value == "0101234567"
            assert extraction.legal_rep_name.value == "Nguyễn Văn An"  # Đã chuẩn hóa danh xưng


def test_integration_b_scanned_router_to_legal_extractor():
    """Kiểm thử tích hợp B:
    scanned_legal_fixture.pdf -> Router (gặp PDFBlankPageError) -> PDFOCRIngestor (mode='ocr') -> LegalDocumentExtractor.
    """
    assert os.path.exists(SCANNED_FIXTURE_PDF)

    mock_ocr_pages = {
        1: (
            "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM\n"
            "Độc lập - Tự do - Hạnh phúc\n"
            "GIẤY CHỨNG NHẬN ĐĂNG KÝ DOANH NGHIỆP\n"
            "Tên doanh nghiệp: CÔNG TY CỔ PHẦN CÔNG NGHỆ VÀ THƯƠNG MẠI SAO MAI\n"
            "Tên viết tắt: SAO MAI TECH JSC\n"
            "Mã số doanh nghiệp: 0312456789\n"
            "Địa chỉ trụ sở chính: Lô CN-08, Khu Công nghiệp Tân Bình, Phường Tây Thạnh, Quận Tân Phú, Thành phố Hồ Chí Minh, Việt Nam"
        ),
        2: (
            "THÔNG TIN VỐN VÀ ĐẠI DIỆN PHÁP LUẬT\n"
            "Vốn điều lệ: 85.000.000.000 đồng\n"
            "Họ và tên: Ông Đặng Quốc Hưng\n"
            "Chức danh: Tổng Giám đốc"
        )
    }
    engine = DummyCustomOCREngine(responses=mock_ocr_pages)

    result = DocumentIngestionRouter.ingest_document(SCANNED_FIXTURE_PDF, ocr_engine=engine)

    assert result.mode == "ocr"
    assert result.fallback_reason == "PDFBlankPageError"
    assert result.provider == "custom_vendor_engine"
    assert result.page_count == 2

    tagged_text = result.tagged_text
    assert tagged_text.startswith("[PAGE 1]\n")
    assert "\n\n[PAGE 2]\n" in tagged_text

    mock_llm_json = {
        "company_name": {
            "value": "CÔNG TY CỔ PHẦN CÔNG NGHỆ VÀ THƯƠNG MẠI SAO MAI",
            "evidence": "Tên doanh nghiệp: CÔNG TY CỔ PHẦN CÔNG NGHỆ VÀ THƯƠNG MẠI SAO MAI",
            "page": 1
        },
        "short_name": {
            "value": "SAO MAI TECH JSC",
            "evidence": "Tên viết tắt: SAO MAI TECH JSC",
            "page": 1
        },
        "tax_code": {
            "value": "0312456789",
            "evidence": "Mã số doanh nghiệp: 0312456789",
            "page": 1
        },
        "address": {
            "value": "Lô CN-08, Khu Công nghiệp Tân Bình, Phường Tây Thạnh, Quận Tân Phú, Thành phố Hồ Chí Minh, Việt Nam",
            "evidence": "Địa chỉ trụ sở chính: Lô CN-08, Khu Công nghiệp Tân Bình, Phường Tây Thạnh, Quận Tân Phú, Thành phố Hồ Chí Minh, Việt Nam",
            "page": 1
        },
        "charter_capital_raw": {
            "value": "85.000.000.000 đồng",
            "evidence": "Vốn điều lệ: 85.000.000.000 đồng",
            "page": 2
        },
        "legal_rep_name": {
            "value": "Ông Đặng Quốc Hưng",
            "evidence": "Họ và tên: Ông Đặng Quốc Hưng",
            "page": 2
        },
        "legal_rep_title": {
            "value": "Tổng Giám đốc",
            "evidence": "Chức danh: Tổng Giám đốc",
            "page": 2
        }
    }

    # Khẳng định nghiêm ngặt trước khi gọi extractor: Mọi evidence đều có mặt trong tagged_text
    for field_name, field_data in mock_llm_json.items():
        evi = field_data["evidence"]
        if evi is not None:
            assert evi in tagged_text, f"Evidence for {field_name} not found in actual tagged_text: '{evi}'"

    with patch("msb_eb_copilot.src.ai_client.AIAssistantClient.chat", return_value=json.dumps(mock_llm_json)):
        extraction = LegalDocumentExtractor.extract(tagged_text)
        assert isinstance(extraction, LegalDocumentExtraction)
        assert extraction.company_name.value == "CÔNG TY CỔ PHẦN CÔNG NGHỆ VÀ THƯƠNG MẠI SAO MAI"
        assert extraction.tax_code.value == "0312456789"
        assert extraction.legal_rep_name.value == "Đặng Quốc Hưng"  # Đã chuẩn hóa danh xưng

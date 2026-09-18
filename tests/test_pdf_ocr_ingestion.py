# -*- coding: utf-8 -*-
"""
Tests cho module pdf_ocr.py (Scanned/Image-based PDF Ingestion Layer).
Bảo đảm:
- 100% Deterministic Offline Tests: ZERO network calls, ZERO real GreenNode API calls.
- Kiểm thử đầy đủ các điều kiện biên: File not found, Encrypted, Render error, Service error,
  Timeout, Empty/Whitespace OCR, Non-alphanumeric OCR, Page count mismatch.
- Kiểm định tính chất tệp PDF quét: pypdf extract_text trả về rỗng, nhưng PDFium render ra ảnh hợp lệ.
- Kiểm thử tích hợp trọn vẹn: scanned_legal_fixture.pdf -> PDFPageRenderer -> Qwen OCR ->
  tagged_text -> Locked LegalDocumentExtractor.
"""

import os
import json
import pytest
import pypdf
import pypdfium2 as pdfium
from unittest.mock import patch, MagicMock

from msb_eb_copilot.src.ingestion.pdf_ocr import (
    PDFOCRIngestor,
    BaseOCREngine,
    QwenVisionOCREngine,
    OCRPageResult,
    OCRDocumentResult,
    OCRIngestionError,
    OCRFileNotFoundError,
    OCREncryptedError,
    OCRRenderError,
    OCRServiceError,
    OCRTimeoutError,
    OCRNoTextError,
    OCRPageCountError
)
from msb_eb_copilot.src.extraction.legal_extraction import (
    LegalDocumentExtractor,
    LegalDocumentExtraction
)


FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "pdf")
SCANNED_FIXTURE_PDF = os.path.join(FIXTURES_DIR, "scanned_legal_fixture.pdf")
SAMPLE_SINGLE_PAGE_PDF = os.path.join(FIXTURES_DIR, "sample_single_page.pdf")
ENCRYPTED_PDF = os.path.join(FIXTURES_DIR, "encrypted.pdf")
BLANK_PDF = os.path.join(FIXTURES_DIR, "blank.pdf")


# Dummy engine for unit tests without network calls
class MockOCREngine(BaseOCREngine):
    provider_name = "mock_engine"

    def __init__(self, responses=None):
        self.responses = responses or {}
        self.call_count = 0

    def ocr_page(self, base64_png: str, page_num: int) -> str:
        self.call_count += 1
        if page_num in self.responses:
            val = self.responses[page_num]
            if isinstance(val, Exception):
                raise val
            return val
        return f"Nội dung văn bản nhận dạng được của trang {page_num}"


# ==============================================================================
# 1. SCANNED FIXTURE DUAL-PROPERTY TESTS (pypdf text empty vs PDFium image valid)
# ==============================================================================
def test_scanned_fixture_pypdf_has_zero_extractable_text():
    """Tệp scanned_legal_fixture.pdf là ảnh thuần túy: pypdf extract_text() trả về chuỗi rỗng."""
    assert os.path.exists(SCANNED_FIXTURE_PDF)
    reader = pypdf.PdfReader(SCANNED_FIXTURE_PDF)
    assert len(reader.pages) == 2
    for idx, page in enumerate(reader.pages):
        raw_text = page.extract_text() or ""
        assert raw_text.strip() == "", f"Trang {idx+1} không được chứa text stream có thể trích xuất trực tiếp"


def test_scanned_fixture_pdfium_renders_valid_images():
    """PDFium mở tệp và rasterize thành công cả 2 trang thành đối tượng ảnh PIL hợp lệ."""
    assert os.path.exists(SCANNED_FIXTURE_PDF)
    doc = pdfium.PdfDocument(SCANNED_FIXTURE_PDF)
    assert len(doc) == 2
    for page_idx in range(len(doc)):
        page = doc[page_idx]
        img = page.render(scale=150 / 72.0).to_pil()
        assert img is not None
        assert img.width > 0 and img.height > 0
        page.close()
    doc.close()


# ==============================================================================
# 2. ERROR AND BOUNDARY TESTS
# ==============================================================================
def test_missing_file_raises_not_found():
    non_existent = os.path.join(FIXTURES_DIR, "non_existent_ocr.pdf")
    with pytest.raises(OCRFileNotFoundError, match="không tồn tại"):
        PDFOCRIngestor.extract_text_with_page_markers(non_existent)


def test_directory_path_raises_not_found():
    with pytest.raises(OCRFileNotFoundError, match="không phải là file"):
        PDFOCRIngestor.extract_text_with_page_markers(FIXTURES_DIR)


def test_encrypted_pdf_raises_encrypted_error():
    assert os.path.exists(ENCRYPTED_PDF)
    with pytest.raises(OCREncryptedError, match="bị khóa bằng mật khẩu"):
        PDFOCRIngestor.extract_text_with_page_markers(ENCRYPTED_PDF)


def test_ocr_returning_none_raises_no_text_error():
    engine = MockOCREngine(responses={1: None, 2: "Trang 2"})
    with pytest.raises(OCRNoTextError, match="không nhận được kết quả OCR"):
        PDFOCRIngestor.extract_document(SCANNED_FIXTURE_PDF, engine=engine)


def test_ocr_returning_whitespace_only_raises_no_text_error():
    engine = MockOCREngine(responses={1: "   \n\t  \n  ", 2: "Trang 2"})
    with pytest.raises(OCRNoTextError, match="có nội dung OCR hoàn toàn rỗng"):
        PDFOCRIngestor.extract_document(SCANNED_FIXTURE_PDF, engine=engine)


def test_ocr_returning_non_alphanumeric_raises_no_text_error():
    engine = MockOCREngine(responses={1: "--- === *** !!!", 2: "Trang 2"})
    with pytest.raises(OCRNoTextError, match="không chứa bất kỳ ký tự chữ hoặc số"):
        PDFOCRIngestor.extract_document(SCANNED_FIXTURE_PDF, engine=engine)


def test_page_count_mismatch_between_pypdf_and_pdfium_raises_error():
    """Giả lập sự cố bất đồng số trang giữa pypdf và pypdfium2."""
    engine = MockOCREngine()
    with patch("msb_eb_copilot.src.ingestion.pdf_ocr.PDFOCRIngestor._preflight_pdf", return_value=5):
        with pytest.raises(OCRPageCountError, match="Bất đồng số trang vật lý"):
            PDFOCRIngestor.extract_document(SCANNED_FIXTURE_PDF, engine=engine)


def test_ocr_render_failure_raises_render_error():
    """Giả lập lỗi ném ra từ thư viện PDFium khi mở tệp."""
    engine = MockOCREngine()
    with patch("pypdfium2.PdfDocument", side_effect=Exception("PDFium internal crash")):
        with pytest.raises(OCRRenderError, match="Không thể mở tài liệu bằng PDFium"):
            PDFOCRIngestor.extract_document(SCANNED_FIXTURE_PDF, engine=engine)


def test_qwen_engine_missing_api_key_raises_service_error():
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(OCRServiceError, match="Không tìm thấy AI_PLATFORM_API_KEY"):
            QwenVisionOCREngine(api_key=None)


def test_qwen_engine_timeout_raises_timeout_error():
    from openai import APITimeoutError
    engine = QwenVisionOCREngine(api_key="mock_key")
    with patch.object(engine.client.chat.completions, "create", side_effect=APITimeoutError(request=None)):
        with pytest.raises(OCRTimeoutError, match="vượt quá"):
            engine.ocr_page("dummy_b64", page_num=1)


def test_qwen_engine_api_error_raises_service_error():
    from openai import APIError
    engine = QwenVisionOCREngine(api_key="mock_key")
    with patch.object(engine.client.chat.completions, "create", side_effect=APIError("Internal Server Error", request=None, body=None)):
        with pytest.raises(OCRServiceError, match="Lỗi dịch vụ OCR"):
            engine.ocr_page("dummy_b64", page_num=1)


# ==============================================================================
# 3. PAGE COUNT INVARIANT & FORMAT CONTRACT TESTS
# ==============================================================================
def test_ocr_page_count_invariant_and_formatting():
    """N trang nguồn -> Đúng N khối [PAGE X], N kết quả OCRPageResult."""
    engine = MockOCREngine(responses={
        1: "Văn bản nhận dạng trang 1\nMã số: 0312456789",
        2: "Văn bản nhận dạng trang 2\nVốn điều lệ: 85 tỷ"
    })
    doc_result = PDFOCRIngestor.extract_document(SCANNED_FIXTURE_PDF, engine=engine)

    assert isinstance(doc_result, OCRDocumentResult)
    assert doc_result.page_count == 2
    assert len(doc_result.pages) == 2
    assert doc_result.pages[0].page_num == 1
    assert doc_result.pages[1].page_num == 2

    tagged = doc_result.tagged_text
    assert tagged.startswith("[PAGE 1]\n")
    assert "\n\n[PAGE 2]\n" in tagged
    assert "[PAGE 3]" not in tagged

    # Đảm bảo engine được gọi đúng 2 lần tuần tự
    assert engine.call_count == 2


def test_crlf_normalization_and_whitespace_trimming():
    """Kiểm tra CRLF/CR được chuẩn hóa thành LF và khoảng trắng thừa ngoài biên được cắt bỏ."""
    engine = MockOCREngine(responses={
        1: "\r\n  Dòng 1 trang 1\r\nDòng 2 trang 1\r\n  ",
        2: "\n\n\nDòng 1 trang 2\nDòng 2 trang 2\n\n\n"
    })
    tagged = PDFOCRIngestor.extract_text_with_page_markers(SCANNED_FIXTURE_PDF, engine=engine)

    # Không còn \r trong output
    assert "\r" not in tagged

    # Khối thẻ trang định dạng chuẩn xác
    expected = (
        "[PAGE 1]\nDòng 1 trang 1\nDòng 2 trang 1\n\n"
        "[PAGE 2]\nDòng 1 trang 2\nDòng 2 trang 2"
    )
    assert tagged == expected


# ==============================================================================
# 4. INTEGRATION TEST: SCANNED PDF -> PDFOCRIngestor -> Locked LegalDocumentExtractor
# ==============================================================================
def test_scanned_pdf_ingestion_end_to_end_with_legal_extractor():
    """Kiểm thử tích hợp trọn vẹn:
    1. Đọc tệp PDF quét mẫu scanned_legal_fixture.pdf bằng PDFOCRIngestor
    2. Rasterize bằng PDFium thật
    3. Mock Qwen OCR engine trả về đúng văn bản chứa nhãn và thông tin pháp lý của fixture
    4. Sinh ra chuỗi tagged_text thực tế (KHÔNG qua chỉnh sửa/bổ sung nhân tạo)
    5. Khẳng định MỌI chuỗi evidence trong mock LLM extraction đều có mặt trong tagged_text
    6. Truyền trực tiếp tagged_text vào LegalDocumentExtractor đã khóa
    7. Khẳng định trích xuất thành công, vượt qua toàn bộ audits và chuẩn hóa danh xưng.
    """
    assert os.path.exists(SCANNED_FIXTURE_PDF)

    # Mock văn bản OCR cho từng trang vật lý khớp với nội dung đã vẽ trong scanned_legal_fixture.pdf
    mock_page_texts = {
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
    engine = MockOCREngine(responses=mock_page_texts)

    # Bước 1 & 2: Thực thi PDFOCRIngestor thật trên scanned_legal_fixture.pdf
    tagged_text = PDFOCRIngestor.extract_text_with_page_markers(SCANNED_FIXTURE_PDF, engine=engine)

    # Khẳng định hợp đồng định dạng
    assert tagged_text.startswith("[PAGE 1]\n")
    assert "\n\n[PAGE 2]\n" in tagged_text

    # Mock kết quả LLM extraction của LegalDocumentExtractor
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

    # Bước 3: Khẳng định nghiêm ngặt trước khi gọi extractor:
    # Mọi chuỗi evidence không null đều phải tồn tại nguyên vẹn trong tagged_text thực tế
    for field_name, field_data in mock_llm_json.items():
        evi = field_data["evidence"]
        if evi is not None:
            assert evi in tagged_text, f"Evidence for {field_name} not found in tagged_text: '{evi}'"

    # Bước 4: Chạy trích xuất thực tế: tagged_text từ PDFOCRIngestor được truyền trực tiếp không chỉnh sửa
    with patch("msb_eb_copilot.src.ai_client.AIAssistantClient.chat", return_value=json.dumps(mock_llm_json)):
        result = LegalDocumentExtractor.extract(tagged_text)

        assert isinstance(result, LegalDocumentExtraction)
        assert result.company_name.value == "CÔNG TY CỔ PHẦN CÔNG NGHỆ VÀ THƯƠNG MẠI SAO MAI"
        assert result.short_name.value == "SAO MAI TECH JSC"
        assert result.tax_code.value == "0312456789"
        assert result.address.value == "Lô CN-08, Khu Công nghiệp Tân Bình, Phường Tây Thạnh, Quận Tân Phú, Thành phố Hồ Chí Minh, Việt Nam"
        assert result.charter_capital_raw.value == "85.000.000.000 đồng"

        # Khẳng định chuẩn hóa danh xưng hoạt động chính xác ("Ông Đặng Quốc Hưng" -> "Đặng Quốc Hưng")
        assert result.legal_rep_name.value == "Đặng Quốc Hưng"
        assert result.legal_rep_name.evidence == "Họ và tên: Ông Đặng Quốc Hưng"
        assert result.legal_rep_title.value == "Tổng Giám đốc"

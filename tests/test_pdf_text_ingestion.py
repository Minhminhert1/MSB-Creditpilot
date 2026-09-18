# -*- coding: utf-8 -*-
"""
Tests cho module pdf_text.py (Digital/Text-based PDF Ingestion Layer).
Bảo đảm:
- 100% Deterministic Offline Tests.
- ZERO network calls, ZERO OCR calls, ZERO GreenNode calls.
- Kiểm thử đầy đủ các điều kiện biên: File not found, Encrypted, Empty/Blank, Non-alphanumeric.
- Kiểm thử hợp đồng bảo toàn văn bản đối chiếu trực tiếp với baseline của pypdf.
- Kiểm thử tích hợp trọn vẹn: PDF -> PDFTextIngestor -> [PAGE X] text -> Locked LegalDocumentExtractor.
"""

import os
import json
import pytest
import pypdf
from unittest.mock import patch

from msb_eb_copilot.src.ingestion.pdf_text import (
    PDFTextIngestor,
    PDFIngestionError,
    PDFFileNotFoundError,
    PDFEncryptedError,
    PDFNoTextError,
    PDFBlankPageError
)
from msb_eb_copilot.src.extraction.legal_extraction import (
    LegalDocumentExtractor,
    LegalDocumentExtraction
)


FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "pdf")
SAMPLE_SINGLE_PAGE_PDF = os.path.join(FIXTURES_DIR, "sample_single_page.pdf")
SAMPLE_MULTIPAGE_PDF = os.path.join(FIXTURES_DIR, "sample_multipage.pdf")
LEGAL_REGISTRATION_FIXTURE_PDF = os.path.join(FIXTURES_DIR, "legal_registration_fixture.pdf")
BLANK_PDF = os.path.join(FIXTURES_DIR, "blank.pdf")
MIXED_BLANK_PDF = os.path.join(FIXTURES_DIR, "mixed_blank.pdf")
ENCRYPTED_PDF = os.path.join(FIXTURES_DIR, "encrypted.pdf")


# ==============================================================================
# 1. TESTS: ERROR CASES (FILE NOT FOUND, ENCRYPTED, BLANK, NON-ALPHANUMERIC)
# ==============================================================================
def test_missing_file_raises_not_found():
    non_existent = os.path.join(FIXTURES_DIR, "non_existent_file.pdf")
    with pytest.raises(PDFFileNotFoundError, match="không tồn tại"):
        PDFTextIngestor.extract_text_with_page_markers(non_existent)


def test_directory_path_raises_not_found():
    with pytest.raises(PDFFileNotFoundError, match="không tồn tại hoặc không phải là file"):
        PDFTextIngestor.extract_text_with_page_markers(FIXTURES_DIR)


def test_encrypted_pdf_raises_encrypted_error():
    assert os.path.exists(ENCRYPTED_PDF), f"Fixture missing: {ENCRYPTED_PDF}"
    with pytest.raises(PDFEncryptedError, match="đã bị mã hóa hoặc cài đặt mật khẩu"):
        PDFTextIngestor.extract_text_with_page_markers(ENCRYPTED_PDF)


def test_blank_pdf_raises_blank_page_error():
    assert os.path.exists(BLANK_PDF), f"Fixture missing: {BLANK_PDF}"
    with pytest.raises(PDFBlankPageError, match="không chứa văn bản kỹ thuật số hợp lệ"):
        PDFTextIngestor.extract_text_with_page_markers(BLANK_PDF)


def test_mixed_pdf_with_blank_page_fails_safely():
    """Tệp PDF có trang 1 có text nhưng trang 2 bị trống -> Bắt buộc fail toàn bộ pipeline."""
    assert os.path.exists(MIXED_BLANK_PDF), f"Fixture missing: {MIXED_BLANK_PDF}"
    with pytest.raises(PDFBlankPageError, match=r"Trang 2/2"):
        PDFTextIngestor.extract_text_with_page_markers(MIXED_BLANK_PDF)


def test_extract_text_returning_none_fails_safely(monkeypatch):
    """Giả lập page.extract_text() trả về None -> Phải bắt được và ném PDFBlankPageError."""
    assert os.path.exists(SAMPLE_SINGLE_PAGE_PDF)
    monkeypatch.setattr(pypdf.PageObject, "extract_text", lambda self: None)
    with pytest.raises(PDFBlankPageError):
        PDFTextIngestor.extract_text_with_page_markers(SAMPLE_SINGLE_PAGE_PDF)


def test_non_alphanumeric_page_fails(monkeypatch):
    """Trang chỉ chứa ký tự đặc biệt '--- \n •••' (không có chữ hoặc số) phải bị ném PDFBlankPageError."""
    assert os.path.exists(SAMPLE_SINGLE_PAGE_PDF)
    monkeypatch.setattr(pypdf.PageObject, "extract_text", lambda self: "--- \n ••• \n ***")
    with pytest.raises(PDFBlankPageError, match="không chứa văn bản kỹ thuật số hợp lệ"):
        PDFTextIngestor.extract_text_with_page_markers(SAMPLE_SINGLE_PAGE_PDF)


def test_zero_page_pdf_raises_no_text_error(monkeypatch):
    """PDF có 0 trang -> Phải ném PDFNoTextError."""
    assert os.path.exists(SAMPLE_SINGLE_PAGE_PDF)
    monkeypatch.setattr(pypdf.PdfReader, "pages", [])
    with pytest.raises(PDFNoTextError, match="không chứa bất kỳ trang nào"):
        PDFTextIngestor.extract_text_with_page_markers(SAMPLE_SINGLE_PAGE_PDF)


# ==============================================================================
# 2. TESTS: SUCCESSFUL EXTRACTION & PRESERVATION CONTRACT
# ==============================================================================
def test_single_page_digital_pdf_ingestion():
    assert os.path.exists(SAMPLE_SINGLE_PAGE_PDF)
    result = PDFTextIngestor.extract_text_with_page_markers(SAMPLE_SINGLE_PAGE_PDF)

    # 1. Hợp đồng thẻ trang: Bắt đầu trực tiếp bằng [PAGE 1], không có khoảng trắng phía trước
    assert result.startswith("[PAGE 1]\n")
    assert "[PAGE 2]" not in result

    # 2. Hợp đồng bảo toàn văn bản so với baseline trực tiếp của pypdf
    reader = pypdf.PdfReader(SAMPLE_SINGLE_PAGE_PDF)
    raw_p0 = reader.pages[0].extract_text() or ""
    expected_p0 = raw_p0.replace("\r\n", "\n").replace("\r", "\n").strip()

    extracted_content = result[len("[PAGE 1]\n"):]
    assert extracted_content == expected_p0


def test_multipage_digital_pdf_ingestion():
    assert os.path.exists(SAMPLE_MULTIPAGE_PDF)
    result = PDFTextIngestor.extract_text_with_page_markers(SAMPLE_MULTIPAGE_PDF)

    # 1. Hợp đồng thẻ trang: Chứa đúng [PAGE 1] và [PAGE 2] theo thứ tự 1-based
    assert result.startswith("[PAGE 1]\n")
    assert "\n\n[PAGE 2]\n" in result
    assert "[PAGE 3]" not in result

    # 2. Bảo toàn chính xác từng trang so với baseline pypdf
    reader = pypdf.PdfReader(SAMPLE_MULTIPAGE_PDF)
    assert len(reader.pages) == 2

    raw_p0 = reader.pages[0].extract_text() or ""
    expected_p0 = raw_p0.replace("\r\n", "\n").replace("\r", "\n").strip()

    raw_p1 = reader.pages[1].extract_text() or ""
    expected_p1 = raw_p1.replace("\r\n", "\n").replace("\r", "\n").strip()

    parts = result.split("\n\n[PAGE 2]\n")
    page_1_content = parts[0][len("[PAGE 1]\n"):]
    page_2_content = parts[1]

    assert page_1_content == expected_p0
    assert page_2_content == expected_p1


def test_vietnamese_and_numeric_preservation():
    """Xác nhận các ký tự tiếng Việt có dấu, số tiền, ngày tháng được giữ nguyên vẹn."""
    result = PDFTextIngestor.extract_text_with_page_markers(SAMPLE_MULTIPAGE_PDF)
    reader = pypdf.PdfReader(SAMPLE_MULTIPAGE_PDF)
    raw_text = (reader.pages[0].extract_text() or "") + (reader.pages[1].extract_text() or "")

    # Mọi từ khóa tiếng Việt và số liệu quan trọng trong PDF gốc đều phải xuất hiện trong output
    assert "CÔNG TY CỔ PHẦN" in result
    assert "MIỀN NAM" in result
    assert "2026" in result


def test_page_count_contract_strictly_preserved():
    """N trang trong PDF đầu vào -> Đúng N thẻ [PAGE X] trong output."""
    reader = pypdf.PdfReader(SAMPLE_MULTIPAGE_PDF)
    n_pages = len(reader.pages)

    result = PDFTextIngestor.extract_text_with_page_markers(SAMPLE_MULTIPAGE_PDF)
    markers = [f"[PAGE {i}]" for i in range(1, n_pages + 1)]
    for m in markers:
        assert m in result
    assert f"[PAGE {n_pages + 1}]" not in result


# ==============================================================================
# 3. INTEGRATION TEST: PDF -> PDFTextIngestor -> Locked LegalDocumentExtractor
# ==============================================================================
def test_pdf_ingestion_end_to_end_with_legal_extractor():
    """Kiểm thử tích hợp trọn vẹn:
    1. Đọc tệp PDF kỹ thuật số mẫu qua PDFTextIngestor: PDF -> pypdf -> [PAGE X] tagged text
    2. Kiểm tra mọi chuỗi evidence trong mock_llm_json đều tồn tại thực sự trong tagged_text
    3. Đưa trực tiếp tagged_text (KHÔNG qua chỉnh sửa/bổ sung nhân tạo) vào LegalDocumentExtractor
    4. Mock duy nhất AIAssistantClient.chat()
    5. Khẳng định dữ liệu trích xuất thành công, vượt qua toàn bộ audits và chuẩn hóa danh xưng.
    """
    assert os.path.exists(LEGAL_REGISTRATION_FIXTURE_PDF)
    tagged_text = PDFTextIngestor.extract_text_with_page_markers(LEGAL_REGISTRATION_FIXTURE_PDF)

    # 1. Hợp đồng định dạng thẻ trang
    assert tagged_text.startswith("[PAGE 1]\n")
    assert "\n\n[PAGE 2]\n" in tagged_text

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

    # 2. Khẳng định rõ ràng trước khi mock: Mọi chuỗi evidence đều phải có mặt trong văn bản tagged_text thực tế
    for field_name, field_data in mock_llm_json.items():
        evi = field_data["evidence"]
        if evi is not None:
            assert evi in tagged_text, f"Evidence for {field_name} not found in actual tagged_text: '{evi}'"

    # 3. Chạy trích xuất thực tế: tagged_text từ PDFTextIngestor được truyền trực tiếp không thay đổi
    with patch("msb_eb_copilot.src.ai_client.AIAssistantClient.chat", return_value=json.dumps(mock_llm_json)):
        result = LegalDocumentExtractor.extract(tagged_text)
        assert isinstance(result, LegalDocumentExtraction)
        assert result.company_name.value == "CÔNG TY CỔ PHẦN ABC"
        assert result.short_name.value == "ABC JSC"
        assert result.tax_code.value == "0101234567"
        assert result.address.value == "Số 123 Phố Huế, Hà Nội"
        assert result.charter_capital_raw.value == "50.000.000.000 đồng"
        # Khẳng định chuẩn hóa danh xưng đã diễn ra chính xác ("Ông Nguyễn Văn An" -> "Nguyễn Văn An")
        assert result.legal_rep_name.value == "Nguyễn Văn An"
        assert result.legal_rep_name.evidence == "Họ và tên: Ông Nguyễn Văn An"
        assert result.legal_rep_title.value == "Giám đốc"

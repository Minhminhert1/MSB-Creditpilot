# -*- coding: utf-8 -*-
"""
Tests cho module legal_extraction.py.
Bảo đảm: 100% Deterministic Unit Tests, KHÔNG gọi mạng ra ngoài (mock AIAssistantClient.chat).
Bao quát tất cả các trường hợp:
1. Strict Page Marker Contract
2. Pydantic Model Invariants & All 7 Top-Level Fields
3. Strict JSON Parsing (cấm fence, cấm prose)
4. Two-Tier Evidence Grounding Audit (Value in Evidence, Evidence in Page)
5. Exact Field Semantic Label Grounding (so khớp đẳng thức, cấm substring matching sai lệch)
6. Deterministic Vietnamese Honorific Normalization (strip_legal_rep_honorific) & Non-Empty Safeguards
7. Schema Fields coverage by Semantic Alias Mapping
"""

import json
import pytest
from unittest.mock import patch

from msb_eb_copilot.src.extraction.legal_extraction import (
    EvidenceField,
    LegalDocumentExtraction,
    LegalDocumentExtractor,
    LEGAL_FIELD_SEMANTIC_ALIASES,
    split_into_page_map,
    audit_extraction,
    extract_semantic_label,
    normalize_semantic_label,
    strip_legal_rep_honorific,
    ExtractionError,
    ExtractionPageMarkerError,
    ExtractionJSONError,
    ExtractionSchemaError,
    ExtractionSemanticError,
    ExtractionNormalizationError,
    ExtractionAuditError
)


# ==============================================================================
# SAMPLE TEST FIXTURES
# ==============================================================================
VALID_2_PAGE_TEXT = """[PAGE 1]
CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM
Độc lập - Tự do - Hạnh phúc
GIẤY CHỨNG NHẬN ĐĂNG KÝ DOANH NGHIỆP
Mã số doanh nghiệp: 0101234567
Tên công ty viết bằng tiếng Việt: CÔNG TY CỔ PHẦN THƯƠNG MẠI DỊCH VỤ AN BÌNH
Tên công ty viết tắt: AN BINH CORP
Địa chỉ trụ sở chính: Số 123 Đường Kim Mã, Phường Giảng Võ, Quận Ba Đình, Hà Nội

[PAGE 2]
Vốn điều lệ: 50.000.000.000 đồng (Năm mươi tỷ đồng)
Người đại diện theo pháp luật của công ty:
Họ và tên: Ông Nguyễn Văn An
Chức danh: Tổng Giám đốc
"""

VALID_FULL_JSON_DICT = {
    "company_name": {
        "value": "CÔNG TY CỔ PHẦN THƯƠNG MẠI DỊCH VỤ AN BÌNH",
        "evidence": "Tên công ty viết bằng tiếng Việt: CÔNG TY CỔ PHẦN THƯƠNG MẠI DỊCH VỤ AN BÌNH",
        "page": 1
    },
    "short_name": {
        "value": "AN BINH CORP",
        "evidence": "Tên công ty viết tắt: AN BINH CORP",
        "page": 1
    },
    "tax_code": {
        "value": "0101234567",
        "evidence": "Mã số doanh nghiệp: 0101234567",
        "page": 1
    },
    "address": {
        "value": "Số 123 Đường Kim Mã, Phường Giảng Võ, Quận Ba Đình, Hà Nội",
        "evidence": "Địa chỉ trụ sở chính: Số 123 Đường Kim Mã, Phường Giảng Võ, Quận Ba Đình, Hà Nội",
        "page": 1
    },
    "charter_capital_raw": {
        "value": "50.000.000.000 đồng",
        "evidence": "Vốn điều lệ: 50.000.000.000 đồng (Năm mươi tỷ đồng)",
        "page": 2
    },
    "legal_rep_name": {
        "value": "Nguyễn Văn An",
        "evidence": "Họ và tên: Ông Nguyễn Văn An",
        "page": 2
    },
    "legal_rep_title": {
        "value": "Tổng Giám đốc",
        "evidence": "Chức danh: Tổng Giám đốc",
        "page": 2
    }
}


# ==============================================================================
# 1. TESTS: STRICT PAGE MARKER CONTRACT (split_into_page_map)
# ==============================================================================
def test_no_page_markers_fails():
    text = "Văn bản không hề có thẻ trang nào."
    with pytest.raises(ExtractionPageMarkerError, match="không chứa bất kỳ thẻ trang"):
        split_into_page_map(text)


def test_non_whitespace_preamble_fails():
    text = "Nội dung lời mở đầu trái phép\n[PAGE 1]\nNội dung trang 1"
    with pytest.raises(ExtractionPageMarkerError, match="chứa nội dung không phải khoảng trắng trước thẻ trang"):
        split_into_page_map(text)


def test_whitespace_preamble_passes():
    text = "\n\n   \t   [PAGE 1]\nNội dung trang 1"
    page_map = split_into_page_map(text)
    assert 1 in page_map
    assert "Nội dung trang 1" in page_map[1]


def test_duplicate_page_markers_fails():
    text = "[PAGE 1]\nNội dung 1\n[PAGE 1]\nNội dung trùng"
    with pytest.raises(ExtractionPageMarkerError, match="Phát hiện trùng lặp thẻ trang"):
        split_into_page_map(text)


def test_zero_or_negative_page_fails():
    with pytest.raises(ExtractionPageMarkerError, match="phải > 0"):
        split_into_page_map("[PAGE 0]\nNội dung")

    with pytest.raises(ExtractionPageMarkerError, match="phải > 0"):
        split_into_page_map("[PAGE -2]\nNội dung")


def test_valid_multipage_split():
    page_map = split_into_page_map(VALID_2_PAGE_TEXT)
    assert set(page_map.keys()) == {1, 2}
    assert "0101234567" in page_map[1]
    assert "Tổng Giám đốc" in page_map[2]


# ==============================================================================
# 2. TESTS: PYDANTIC MODEL INVARIANTS & TOP-LEVEL REQUIREMENTS
# ==============================================================================
def test_valid_evidence_field_all_present():
    field = EvidenceField(value="ABC", evidence="Tên doanh nghiệp: ABC", page=1)
    assert field.value == "ABC"
    assert field.evidence == "Tên doanh nghiệp: ABC"
    assert field.page == 1


def test_valid_evidence_field_all_none():
    field = EvidenceField(value=None, evidence=None, page=None)
    assert field.value is None
    assert field.evidence is None
    assert field.page is None


@pytest.mark.parametrize("partial_data", [
    {"value": "ABC", "evidence": None, "page": 1},
    {"value": "ABC", "evidence": "Tên ABC", "page": None},
    {"value": None, "evidence": "Tên ABC", "page": 1},
    {"value": None, "evidence": None, "page": 1},
    {"value": "ABC", "evidence": None, "page": None},
])
def test_partially_populated_field_fails(partial_data):
    with pytest.raises(Exception):
        EvidenceField.model_validate(partial_data)


def test_omitted_top_level_field_fails():
    data = dict(VALID_FULL_JSON_DICT)
    del data["tax_code"]  # Bỏ hẳn trường tax_code
    with pytest.raises(ExtractionSchemaError):
        with patch("msb_eb_copilot.src.ai_client.AIAssistantClient.chat", return_value=json.dumps(data)):
            LegalDocumentExtractor.extract(VALID_2_PAGE_TEXT)


def test_extra_unexpected_fields_fails():
    data = dict(VALID_FULL_JSON_DICT)
    data["extra_field"] = {"value": "X", "evidence": "X", "page": 1}
    with pytest.raises(ExtractionSchemaError):
        with patch("msb_eb_copilot.src.ai_client.AIAssistantClient.chat", return_value=json.dumps(data)):
            LegalDocumentExtractor.extract(VALID_2_PAGE_TEXT)


def test_extra_key_inside_evidence_field_fails():
    data = json.loads(json.dumps(VALID_FULL_JSON_DICT))
    data["company_name"]["confidence"] = 0.99
    with pytest.raises(ExtractionSchemaError):
        with patch("msb_eb_copilot.src.ai_client.AIAssistantClient.chat", return_value=json.dumps(data)):
            LegalDocumentExtractor.extract(VALID_2_PAGE_TEXT)


# ==============================================================================
# 3. TESTS: STRICT JSON PARSING (CẤM MARKDOWN FENCES, CẤM PROSE)
# ==============================================================================
def test_markdown_fenced_json_fails():
    fenced_response = f"```json\n{json.dumps(VALID_FULL_JSON_DICT)}\n```"
    with pytest.raises(ExtractionJSONError, match="không phải là JSON thuần túy"):
        with patch("msb_eb_copilot.src.ai_client.AIAssistantClient.chat", return_value=fenced_response):
            LegalDocumentExtractor.extract(VALID_2_PAGE_TEXT)


def test_prose_around_json_fails():
    prose_response = f"Dưới đây là kết quả trích xuất của tôi:\n{json.dumps(VALID_FULL_JSON_DICT)}"
    with pytest.raises(ExtractionJSONError, match="không phải là JSON thuần túy"):
        with patch("msb_eb_copilot.src.ai_client.AIAssistantClient.chat", return_value=prose_response):
            LegalDocumentExtractor.extract(VALID_2_PAGE_TEXT)


def test_malformed_json_fails():
    malformed = '{"company_name": {"value": "ABC", "evidence": "ABC", "page": 1'
    with pytest.raises(ExtractionJSONError):
        with patch("msb_eb_copilot.src.ai_client.AIAssistantClient.chat", return_value=malformed):
            LegalDocumentExtractor.extract(VALID_2_PAGE_TEXT)


# ==============================================================================
# 4. TESTS: TWO-TIER EVIDENCE GROUNDING AUDIT (VALUE in EVIDENCE in PAGE)
# ==============================================================================
def test_value_not_contained_in_evidence_fails():
    data = json.loads(json.dumps(VALID_FULL_JSON_DICT))
    data["tax_code"]["value"] = "9999999999"
    data["tax_code"]["evidence"] = "Mã số doanh nghiệp: 0101234567"
    data["tax_code"]["page"] = 1

    with pytest.raises(ExtractionAuditError, match="vi phạm Tầng 1: Giá trị"):
        with patch("msb_eb_copilot.src.ai_client.AIAssistantClient.chat", return_value=json.dumps(data)):
            LegalDocumentExtractor.extract(VALID_2_PAGE_TEXT)


def test_evidence_on_wrong_page_fails():
    data = json.loads(json.dumps(VALID_FULL_JSON_DICT))
    data["tax_code"]["page"] = 2

    with pytest.raises(ExtractionAuditError, match="không xuất hiện trên trang 2"):
        with patch("msb_eb_copilot.src.ai_client.AIAssistantClient.chat", return_value=json.dumps(data)):
            LegalDocumentExtractor.extract(VALID_2_PAGE_TEXT)


def test_nonexistent_page_declared_fails():
    data = json.loads(json.dumps(VALID_FULL_JSON_DICT))
    data["tax_code"]["page"] = 99

    with pytest.raises(ExtractionAuditError, match="không tồn tại trong tài liệu nguồn"):
        with patch("msb_eb_copilot.src.ai_client.AIAssistantClient.chat", return_value=json.dumps(data)):
            LegalDocumentExtractor.extract(VALID_2_PAGE_TEXT)


def test_whitespace_normalization_in_audit():
    data = json.loads(json.dumps(VALID_FULL_JSON_DICT))
    data["company_name"]["evidence"] = "Tên công ty viết   bằng tiếng Việt: \n  CÔNG TY CỔ PHẦN THƯƠNG MẠI DỊCH VỤ AN BÌNH"
    data["company_name"]["value"] = "CÔNG TY   CỔ PHẦN THƯƠNG MẠI DỊCH VỤ AN BÌNH"

    with patch("msb_eb_copilot.src.ai_client.AIAssistantClient.chat", return_value=json.dumps(data)):
        res = LegalDocumentExtractor.extract(VALID_2_PAGE_TEXT)
        assert res.company_name.value == "CÔNG TY   CỔ PHẦN THƯƠNG MẠI DỊCH VỤ AN BÌNH"


# ==============================================================================
# 5. TESTS: EXACT FIELD SEMANTIC LABEL GROUNDING
# ==============================================================================
def test_company_name_using_short_name_evidence_fails():
    data = json.loads(json.dumps(VALID_FULL_JSON_DICT))
    data["company_name"]["value"] = "AN BINH CORP"
    data["company_name"]["evidence"] = "Tên công ty viết tắt: AN BINH CORP"
    data["company_name"]["page"] = 1

    with pytest.raises(ExtractionSemanticError, match="vi phạm Semantic Grounding"):
        with patch("msb_eb_copilot.src.ai_client.AIAssistantClient.chat", return_value=json.dumps(data)):
            LegalDocumentExtractor.extract(VALID_2_PAGE_TEXT)


def test_short_name_using_short_name_evidence_passes():
    data = json.loads(json.dumps(VALID_FULL_JSON_DICT))
    with patch("msb_eb_copilot.src.ai_client.AIAssistantClient.chat", return_value=json.dumps(data)):
        res = LegalDocumentExtractor.extract(VALID_2_PAGE_TEXT)
        assert res.short_name.value == "AN BINH CORP"


def test_tax_code_using_charter_capital_evidence_fails():
    data = json.loads(json.dumps(VALID_FULL_JSON_DICT))
    data["tax_code"]["value"] = "50.000.000.000 đồng"
    data["tax_code"]["evidence"] = "Vốn điều lệ: 50.000.000.000 đồng (Năm mươi tỷ đồng)"
    data["tax_code"]["page"] = 2

    with pytest.raises(ExtractionSemanticError, match="vi phạm Semantic Grounding"):
        with patch("msb_eb_copilot.src.ai_client.AIAssistantClient.chat", return_value=json.dumps(data)):
            LegalDocumentExtractor.extract(VALID_2_PAGE_TEXT)


def test_charter_capital_using_tax_code_evidence_fails():
    data = json.loads(json.dumps(VALID_FULL_JSON_DICT))
    data["charter_capital_raw"]["value"] = "0101234567"
    data["charter_capital_raw"]["evidence"] = "Mã số doanh nghiệp: 0101234567"
    data["charter_capital_raw"]["page"] = 1

    with pytest.raises(ExtractionSemanticError, match="vi phạm Semantic Grounding"):
        with patch("msb_eb_copilot.src.ai_client.AIAssistantClient.chat", return_value=json.dumps(data)):
            LegalDocumentExtractor.extract(VALID_2_PAGE_TEXT)


def test_address_evidence_without_semantic_label_fails():
    text = """[PAGE 1]
Mã số doanh nghiệp: 0101234567
Tên công ty viết bằng tiếng Việt: CÔNG TY CỔ PHẦN THƯƠNG MẠI DỊCH VỤ AN BÌNH
Tên công ty viết tắt: AN BINH CORP
Số 123 Đường Kim Mã, Phường Giảng Võ, Quận Ba Đình, Hà Nội
[PAGE 2]
Vốn điều lệ: 50.000.000.000 đồng (Năm mươi tỷ đồng)
Họ và tên: Ông Nguyễn Văn An
Chức danh: Tổng Giám đốc
"""
    data = json.loads(json.dumps(VALID_FULL_JSON_DICT))
    data["address"]["value"] = "Số 123 Đường Kim Mã, Phường Giảng Võ, Quận Ba Đình, Hà Nội"
    data["address"]["evidence"] = "Số 123 Đường Kim Mã, Phường Giảng Võ, Quận Ba Đình, Hà Nội"
    data["address"]["page"] = 1

    with pytest.raises(ExtractionSemanticError, match="vi phạm Semantic Grounding"):
        with patch("msb_eb_copilot.src.ai_client.AIAssistantClient.chat", return_value=json.dumps(data)):
            LegalDocumentExtractor.extract(text)


def test_multiline_evidence_semantic_label_passes():
    text = """[PAGE 1]
Mã số doanh nghiệp: 0101234567
Tên doanh nghiệp:
CÔNG TY CỔ PHẦN THƯƠNG MẠI DỊCH VỤ AN BÌNH
Tên viết tắt:
AN BINH CORP
Địa chỉ trụ sở chính:
Số 123 Đường Kim Mã, Phường Giảng Võ, Quận Ba Đình, Hà Nội
[PAGE 2]
Vốn điều lệ:
50.000.000.000 đồng
Người đại diện theo pháp luật:
Ông Nguyễn Văn An
Chức danh:
Tổng Giám đốc
"""
    data = {
        "company_name": {
            "value": "CÔNG TY CỔ PHẦN THƯƠNG MẠI DỊCH VỤ AN BÌNH",
            "evidence": "Tên doanh nghiệp:\nCÔNG TY CỔ PHẦN THƯƠNG MẠI DỊCH VỤ AN BÌNH",
            "page": 1
        },
        "short_name": {
            "value": "AN BINH CORP",
            "evidence": "Tên viết tắt:\nAN BINH CORP",
            "page": 1
        },
        "tax_code": {
            "value": "0101234567",
            "evidence": "Mã số doanh nghiệp: 0101234567",
            "page": 1
        },
        "address": {
            "value": "Số 123 Đường Kim Mã, Phường Giảng Võ, Quận Ba Đình, Hà Nội",
            "evidence": "Địa chỉ trụ sở chính:\nSố 123 Đường Kim Mã, Phường Giảng Võ, Quận Ba Đình, Hà Nội",
            "page": 1
        },
        "charter_capital_raw": {
            "value": "50.000.000.000 đồng",
            "evidence": "Vốn điều lệ:\n50.000.000.000 đồng",
            "page": 2
        },
        "legal_rep_name": {
            "value": "Nguyễn Văn An",
            "evidence": "Người đại diện theo pháp luật:\nÔng Nguyễn Văn An",
            "page": 2
        },
        "legal_rep_title": {
            "value": "Tổng Giám đốc",
            "evidence": "Chức danh:\nTổng Giám đốc",
            "page": 2
        }
    }

    with patch("msb_eb_copilot.src.ai_client.AIAssistantClient.chat", return_value=json.dumps(data)):
        res = LegalDocumentExtractor.extract(text)
        assert res.company_name.value == "CÔNG TY CỔ PHẦN THƯƠNG MẠI DỊCH VỤ AN BÌNH"
        assert res.short_name.value == "AN BINH CORP"
        assert res.legal_rep_name.value == "Nguyễn Văn An"


def test_unicode_whitespace_case_variations_pass():
    assert extract_semantic_label("  1.  TÊN DOANH NGHIỆP  : ABC") == "tên doanh nghiệp"
    assert extract_semantic_label("• CHỨC DANH: Giám đốc") == "chức danh"
    assert extract_semantic_label("vốn điều lệ:\n10 tỷ") == "vốn điều lệ"


def test_semantic_alias_mapping_covers_all_schema_fields():
    schema_fields = set(LegalDocumentExtraction.model_fields.keys())
    alias_fields = set(LEGAL_FIELD_SEMANTIC_ALIASES.keys())

    assert schema_fields == alias_fields, f"Lệch các trường: {schema_fields ^ alias_fields}"

    for field, aliases in LEGAL_FIELD_SEMANTIC_ALIASES.items():
        assert isinstance(aliases, tuple)
        assert len(aliases) > 0, f"Trường '{field}' có tập alias rỗng!"
        for a in aliases:
            assert a.strip() != "", f"Trường '{field}' chứa alias rỗng!"


# ==============================================================================
# 6. TESTS: DETERMINISTIC HONORIFIC NORMALIZATION & SAFEGUARDS
# ==============================================================================
@pytest.mark.parametrize("input_name,expected_output", [
    ("ÔNG Nguyễn Văn A", "Nguyễn Văn A"),
    ("ông Nguyễn Văn A", "Nguyễn Văn A"),
    ("Ông Nguyễn Văn A", "Nguyễn Văn A"),
    ("BÀ Trần Thu Hà", "Trần Thu Hà"),
    ("bà Trần Thu Hà", "Trần Thu Hà"),
    ("ANH Lê Văn B", "Lê Văn B"),
    ("anh Lê Văn B", "Lê Văn B"),
    ("CHỊ Nguyễn Thị C", "Nguyễn Thị C"),
    ("chị Nguyễn Thị C", "Nguyễn Thị C"),
    ("Nguyễn Văn D", "Nguyễn Văn D"),
    ("Nguyễn Văn Anh", "Nguyễn Văn Anh"),  # Danh xưng ở cuối không bị xóa
    ("Ông.Nguyễn Văn A", "Ông.Nguyễn Văn A"),  # Sau "Ông" là dấu chấm, không phải khoảng trắng/hết chuỗi
])
def test_strip_legal_rep_honorific_success_cases(input_name, expected_output):
    assert strip_legal_rep_honorific(input_name) == expected_output


@pytest.mark.parametrize("invalid_honorific_name", [
    "Ông",
    "Bà   ",
    "  anh  ",
    "CHỊ",
    "   ",
])
def test_strip_legal_rep_honorific_empty_fails(invalid_honorific_name):
    with pytest.raises(ExtractionNormalizationError):
        strip_legal_rep_honorific(invalid_honorific_name)


def test_pipeline_normalizes_honorific_preserves_evidence_and_passes_audit():
    """Mô hình trả về value='Ông Nguyễn Văn An', pipeline chuẩn hóa thành 'Nguyễn Văn An',
    nhưng evidence vẫn giữ nguyên 'Họ và tên: Ông Nguyễn Văn An' và vượt qua toàn bộ audit.
    """
    data = json.loads(json.dumps(VALID_FULL_JSON_DICT))
    data["legal_rep_name"]["value"] = "Ông Nguyễn Văn An"
    data["legal_rep_name"]["evidence"] = "Họ và tên: Ông Nguyễn Văn An"

    with patch("msb_eb_copilot.src.ai_client.AIAssistantClient.chat", return_value=json.dumps(data)):
        res = LegalDocumentExtractor.extract(VALID_2_PAGE_TEXT)
        # Value được chuẩn hóa
        assert res.legal_rep_name.value == "Nguyễn Văn An"
        # Evidence được bảo tồn nguyên vẹn
        assert res.legal_rep_name.evidence == "Họ và tên: Ông Nguyễn Văn An"
        assert res.legal_rep_name.page == 2


def test_pipeline_honorific_only_raises_normalization_error():
    """Mô hình trả về value='Ông', pipeline phát hiện chuỗi rỗng sau chuẩn hóa và ném ExtractionNormalizationError."""
    data = json.loads(json.dumps(VALID_FULL_JSON_DICT))
    data["legal_rep_name"]["value"] = "Ông"
    data["legal_rep_name"]["evidence"] = "Họ và tên: Ông"

    with pytest.raises(ExtractionNormalizationError):
        with patch("msb_eb_copilot.src.ai_client.AIAssistantClient.chat", return_value=json.dumps(data)):
            LegalDocumentExtractor.extract(VALID_2_PAGE_TEXT)


# ==============================================================================
# 7. TESTS: FULL SUCCESS PIPELINE & HONORIFIC HANDLING
# ==============================================================================
def test_complete_document_extraction_success():
    with patch("msb_eb_copilot.src.ai_client.AIAssistantClient.chat", return_value=json.dumps(VALID_FULL_JSON_DICT)):
        res = LegalDocumentExtractor.extract(VALID_2_PAGE_TEXT)
        assert isinstance(res, LegalDocumentExtraction)
        assert res.company_name.value == "CÔNG TY CỔ PHẦN THƯƠNG MẠI DỊCH VỤ AN BÌNH"
        assert res.company_name.page == 1
        assert res.charter_capital_raw.value == "50.000.000.000 đồng"
        assert res.charter_capital_raw.page == 2
        assert res.legal_rep_name.value == "Nguyễn Văn An"
        assert res.legal_rep_title.value == "Tổng Giám đốc"


def test_honorific_not_title_scenario():
    text = """[PAGE 1]
Tên doanh nghiệp: CÔNG TY ABC
Mã số doanh nghiệp: 0101111111
Địa chỉ trụ sở chính: Hà Nội
Họ và tên: Ông Nguyễn Văn An
"""
    data = {
        "company_name": {"value": "CÔNG TY ABC", "evidence": "Tên doanh nghiệp: CÔNG TY ABC", "page": 1},
        "short_name": {"value": None, "evidence": None, "page": None},
        "tax_code": {"value": "0101111111", "evidence": "Mã số doanh nghiệp: 0101111111", "page": 1},
        "address": {"value": "Hà Nội", "evidence": "Địa chỉ trụ sở chính: Hà Nội", "page": 1},
        "charter_capital_raw": {"value": None, "evidence": None, "page": None},
        "legal_rep_name": {"value": "Ông Nguyễn Văn An", "evidence": "Họ và tên: Ông Nguyễn Văn An", "page": 1},
        "legal_rep_title": {"value": None, "evidence": None, "page": None}
    }

    with patch("msb_eb_copilot.src.ai_client.AIAssistantClient.chat", return_value=json.dumps(data)):
        res = LegalDocumentExtractor.extract(text)
        assert res.legal_rep_name.value == "Nguyễn Văn An"
        assert res.legal_rep_title.value is None
        assert res.short_name.value is None
        assert res.charter_capital_raw.value is None

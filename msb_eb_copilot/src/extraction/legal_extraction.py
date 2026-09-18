# -*- coding: utf-8 -*-
"""
Module: msb_eb_copilot.src.extraction.legal_extraction
Mô tả: Pipeline bóc tách thông tin pháp lý doanh nghiệp từ văn bản thô có thẻ trang [PAGE X]
sử dụng GreenNode MaaS và Pydantic với cơ chế kiểm định tiền định nhiều tầng:
    EXACT FIELD SEMANTIC LABEL -> VALUE ⊆ EVIDENCE ⊆ DECLARED PAGE
kèm cơ chế chuẩn hóa tiền định danh xưng tiếng Việt cho legal_rep_name.
"""

import json
import re
import unicodedata
from typing import Optional, Dict, Tuple, Any, Set
from pydantic import BaseModel, ConfigDict, model_validator, ValidationError

from msb_eb_copilot.src.ai_client import AIAssistantClient


# ==============================================================================
# HIERARCHY NGOẠI LỆ BÓC TÁCH (EXTRACTION EXCEPTION HIERARCHY)
# ==============================================================================
class ExtractionError(Exception):
    """Ngoại lệ cơ sở cho toàn bộ pipeline bóc tách tài liệu."""
    pass


class ExtractionPageMarkerError(ExtractionError):
    """Ngoại lệ khi văn bản nguồn vi phạm quy chuẩn thẻ trang [PAGE X]."""
    pass


class ExtractionJSONError(ExtractionError):
    """Ngoại lệ khi phản hồi từ mô hình không phải là JSON thuần túy (dính markdown fence, lời dẫn)."""
    pass


class ExtractionSchemaError(ExtractionError):
    """Ngoại lệ khi cấu trúc JSON vi phạm Pydantic schema (thiếu trường, thừa trường, invariant lỗi)."""
    pass


class ExtractionNormalizationError(ExtractionError):
    """Ngoại lệ khi quá trình chuẩn hóa tiền định tạo ra giá trị rỗng hoặc không hợp lệ."""
    pass


class ExtractionSemanticError(ExtractionError):
    """Ngoại lệ khi nhãn ngữ nghĩa trích xuất từ evidence không khớp chính xác với tập nhãn hợp lệ."""
    pass


class ExtractionAuditError(ExtractionError):
    """Ngoại lệ khi chuỗi kiểm định (Value -> Evidence -> Page) bị vi phạm."""
    pass


# ==============================================================================
# BẢNG ÁNH XẠ NHÃN NGỮ NGHĨA CHUẨN XÁC (STRICT SEMANTIC ALIAS MAPPING)
# ==============================================================================
LEGAL_FIELD_SEMANTIC_ALIASES: Dict[str, Tuple[str, ...]] = {
    "company_name": (
        "tên doanh nghiệp",
        "tên công ty viết bằng tiếng việt",
    ),
    "short_name": (
        "tên viết tắt",
        "tên công ty viết tắt",
    ),
    "tax_code": (
        "mã số doanh nghiệp",
        "mã số thuế",
    ),
    "address": (
        "địa chỉ trụ sở chính",
        "trụ sở chính",
    ),
    "charter_capital_raw": (
        "vốn điều lệ",
    ),
    "legal_rep_name": (
        "người đại diện theo pháp luật",
        "họ và tên",
    ),
    "legal_rep_title": (
        "chức danh",
        "chức vụ",
    ),
}


# ==============================================================================
# PYDANTIC STAGING MODELS VỚI RÀNG BUỘC NGHIÊM NGẶT
# ==============================================================================
class EvidenceField(BaseModel):
    """Mô hình dữ liệu cho từng trường bóc tách kèm bằng chứng và số trang."""
    model_config = ConfigDict(extra="forbid")

    value: Optional[str]
    evidence: Optional[str]
    page: Optional[int]

    @model_validator(mode="after")
    def check_all_or_none(self) -> "EvidenceField":
        all_none = self.value is None and self.evidence is None and self.page is None
        all_present = self.value is not None and self.evidence is not None and self.page is not None
        if not (all_none or all_present):
            raise ValueError(
                f"EvidenceField bắt buộc phải hoặc ĐẦY ĐỦ cả 3 trường (value, evidence, page) "
                f"hoặc RỖNG hoàn toàn (cả 3 đều null). "
                f"Hiện tại nhận được: value={self.value!r}, evidence={self.evidence!r}, page={self.page!r}"
            )
        return self


class LegalDocumentExtraction(BaseModel):
    """Mô hình bóc tách pháp lý doanh nghiệp. Cả 7 trường cấp cao nhất đều bắt buộc."""
    model_config = ConfigDict(extra="forbid")

    company_name: EvidenceField
    short_name: EvidenceField
    tax_code: EvidenceField
    address: EvidenceField
    charter_capital_raw: EvidenceField
    legal_rep_name: EvidenceField
    legal_rep_title: EvidenceField


# ==============================================================================
# CÁC HÀM TIỀN ĐỊNH: CHUẨN HÓA, XỬ LÝ TRANG VÀ KIỂM ĐỊNH BẰNG CHỨNG
# ==============================================================================
def normalize_ws(text: Optional[str]) -> str:
    """Chuẩn hóa khoảng trắng phục vụ so khớp chuỗi con (không làm biến đổi chuỗi gốc)."""
    if not text:
        return ""
    return " ".join(text.split())


def strip_legal_rep_honorific(name: Optional[str]) -> Optional[str]:
    r"""Loại bỏ tiền tố danh xưng tiếng Việt (Ông/Bà/Anh/Chị) ở đầu tên người đại diện pháp luật:
    - Chuẩn hóa Unicode NFC trước khi xử lý.
    - Phát hiện danh xưng theo regex chính xác: r"^(?:ông|bà|anh|chị)(?:\s+|$)" với re.IGNORECASE.
    - Giữ nguyên chữ hoa/chữ thường của phần tên thực tế phía sau.
    - Gộp khoảng trắng thừa của phần tên còn lại.
    - Nếu kết quả sau chuẩn hóa là rỗng hoặc whitespace-only, ném ExtractionNormalizationError.
    - Tuyệt đối không âm thầm chuyển thành null.
    """
    if name is None:
        return None

    # 1. Chuẩn hóa Unicode NFC và cắt khoảng trắng 2 đầu
    nfc_name = unicodedata.normalize("NFC", name).strip()
    if not nfc_name:
        raise ExtractionNormalizationError("Tên người đại diện (legal_rep_name) là chuỗi rỗng trước chuẩn hóa.")

    # 2. Khớp tiền tố danh xưng chính xác: bắt buộc ở đầu chuỗi và theo sau bởi khoảng trắng hoặc hết chuỗi
    pattern = re.compile(r"^(?:ông|bà|anh|chị)(?:\s+|$)", re.IGNORECASE)
    match = pattern.match(nfc_name)
    if match:
        remainder = nfc_name[match.end():].strip()
        cleaned_remainder = " ".join(remainder.split())
        if not cleaned_remainder:
            raise ExtractionNormalizationError(
                f"Tên người đại diện chỉ chứa danh xưng '{name}', không có tên thực tế sau khi loại bỏ danh xưng."
            )
        return cleaned_remainder

    # 3. Không có tiền tố danh xưng -> gộp khoảng trắng và kiểm tra không rỗng
    cleaned_original = " ".join(nfc_name.split())
    if not cleaned_original:
        raise ExtractionNormalizationError("Tên người đại diện không có nội dung sau khi chuẩn hóa khoảng trắng.")
    return cleaned_original


def normalize_semantic_label(label: Optional[str]) -> str:
    """Hàm chuẩn hóa duy nhất dùng cho CẢ nhãn trích xuất và nhãn cấu hình (aliases):
    1. Chuẩn hóa Unicode sang dạng dựng sẵn (NFC).
    2. Loại bỏ dấu đầu dòng, số thứ tự (ví dụ: '1. ', '2. ', '• ', '- ', '* ').
    3. Cắt bỏ dấu ':' ở đuôi và khoảng trắng 2 đầu.
    4. Chuyển thành chữ thường (lowercase).
    5. Gộp khoảng trắng bên trong (' '.join(s.split())).
    """
    if not label or not isinstance(label, str):
        return ""
    # Unicode NFC
    s = unicodedata.normalize("NFC", label)
    s = s.strip()
    # Loại bỏ số thứ tự / ký tự đầu dòng
    s = re.sub(r"^(\d+\.|\-|\•|\*)\s*", "", s)
    s = s.rstrip(":").strip().lower()
    return " ".join(s.split())


def extract_semantic_label(evidence: str) -> str:
    """Trích xuất nhãn ngữ nghĩa tiền định từ chuỗi evidence:
    - Nếu evidence chứa dấu ':', nhãn là phần văn bản trước dấu ':' đầu tiên.
    - Ngược lại, nếu evidence nhiều dòng, nhãn là dòng đầu tiên không rỗng.
    - Ngược lại (chỉ có 1 dòng không có ':'), trả về chuỗi rỗng.
    Áp dụng normalize_semantic_label lên kết quả thu được.
    """
    if not evidence or not isinstance(evidence, str):
        return ""

    clean_evi = evidence.strip()
    if ":" in clean_evi:
        raw_label = clean_evi.split(":", 1)[0]
    else:
        lines = [line.strip() for line in clean_evi.splitlines() if line.strip()]
        if len(lines) > 1:
            raw_label = lines[0]
        else:
            return ""

    return normalize_semantic_label(raw_label)


def split_into_page_map(source_text: str) -> Dict[int, str]:
    """Phân tách văn bản nguồn thành bản đồ trang {page_num: page_text} theo quy tắc nghiêm ngặt:
    - Chỉ cho phép ký tự khoảng trắng trước thẻ [PAGE X] đầu tiên.
    - Bắt buộc phải có ít nhất một thẻ [PAGE X].
    - Số trang phải là số nguyên > 0.
    - Cấm tuyệt đối số trang trùng lặp (không ghi đè ngầm).
    """
    if not isinstance(source_text, str):
        raise ExtractionPageMarkerError("Văn bản nguồn phải là kiểu chuỗi (string).")

    pattern = re.compile(r"\[PAGE\s+(-?\d+)\]")
    matches = list(pattern.finditer(source_text))

    if not matches:
        raise ExtractionPageMarkerError("Văn bản nguồn không chứa bất kỳ thẻ trang [PAGE X] hợp lệ nào.")

    first_match = matches[0]
    preamble = source_text[:first_match.start()]
    if preamble.strip() != "":
        raise ExtractionPageMarkerError(
            f"Văn bản nguồn chứa nội dung không phải khoảng trắng trước thẻ trang đầu tiên: '{preamble.strip()}'"
        )

    page_map: Dict[int, str] = {}

    for i, match in enumerate(matches):
        page_num_str = match.group(1)
        try:
            page_num = int(page_num_str)
        except ValueError:
            raise ExtractionPageMarkerError(f"Số trang không hợp lệ: '{page_num_str}'")

        if page_num <= 0:
            raise ExtractionPageMarkerError(f"Số trang trong thẻ [PAGE {page_num}] phải > 0.")

        if page_num in page_map:
            raise ExtractionPageMarkerError(f"Phát hiện trùng lặp thẻ trang: [PAGE {page_num}].")

        start_pos = match.end()
        end_pos = matches[i + 1].start() if i + 1 < len(matches) else len(source_text)
        page_content = source_text[start_pos:end_pos]
        page_map[page_num] = page_content

    return page_map


def audit_extraction(extraction: LegalDocumentExtraction, page_map: Dict[int, str]) -> None:
    """Kiểm định chuỗi bằng chứng tiền định hoàn chỉnh:
        EXACT FIELD SEMANTIC LABEL -> VALUE ⊆ EVIDENCE ⊆ DECLARED PAGE
    Áp dụng chuẩn hóa khoảng trắng và NFC chỉ trong so sánh, giữ nguyên chuỗi gốc.
    """
    fields_dict = extraction.model_dump()
    for field_name, field_data in fields_dict.items():
        val = field_data.get("value")
        evi = field_data.get("evidence")
        page = field_data.get("page")

        # Nếu trường null toàn bộ (đã được Pydantic bảo đảm invariant), bỏ qua kiểm định
        if val is None:
            continue

        # ----------------------------------------------------------------------
        # TẦNG 0: EXACT FIELD SEMANTIC LABEL CHECK
        # ----------------------------------------------------------------------
        extracted_label = extract_semantic_label(evi)

        # Lấy danh sách alias cấu hình và chuẩn hóa qua cùng một hàm normalize_semantic_label
        raw_aliases = LEGAL_FIELD_SEMANTIC_ALIASES.get(field_name, ())
        normalized_aliases: Set[str] = {normalize_semantic_label(a) for a in raw_aliases}

        # So khớp ĐẲNG THỨC CHÍNH XÁC (EXACT EQUALITY), tuyệt đối KHÔNG dùng substring matching
        if extracted_label not in normalized_aliases:
            raise ExtractionSemanticError(
                f"Trường '{field_name}' vi phạm Semantic Grounding: Nhãn trích xuất '{extracted_label}' "
                f"từ bằng chứng '{evi}' không khớp chính xác với bất kỳ nhãn hợp lệ nào: {raw_aliases}."
            )

        norm_val = normalize_ws(val).lower()
        norm_evi = normalize_ws(evi).lower()

        # ----------------------------------------------------------------------
        # TẦNG 1: VALUE phải nằm trong EVIDENCE
        # ----------------------------------------------------------------------
        if norm_val not in norm_evi:
            raise ExtractionAuditError(
                f"Trường '{field_name}' vi phạm Tầng 1: Giá trị (value) '{val}' "
                f"không xuất hiện trong Bằng chứng (evidence) '{evi}'."
            )

        # ----------------------------------------------------------------------
        # TẦNG 2: Trang khai báo phải tồn tại trong page_map
        # ----------------------------------------------------------------------
        if page not in page_map:
            raise ExtractionAuditError(
                f"Trường '{field_name}' vi phạm Tầng 2: Trang khai báo '{page}' "
                f"không tồn tại trong tài liệu nguồn (các trang có: {list(page_map.keys())})."
            )

        norm_page_text = normalize_ws(page_map[page]).lower()

        # ----------------------------------------------------------------------
        # TẦNG 2: EVIDENCE phải xuất hiện trên đúng trang khai báo
        # ----------------------------------------------------------------------
        if norm_evi not in norm_page_text:
            raise ExtractionAuditError(
                f"Trường '{field_name}' vi phạm Tầng 2: Bằng chứng (evidence) '{evi}' "
                f"không xuất hiện trên trang {page} của tài liệu nguồn."
            )


# ==============================================================================
# BỘ TRÍCH XUẤT PHÁP LÝ DOANH NGHIỆP (LEGAL DOCUMENT EXTRACTOR)
# ==============================================================================
class LegalDocumentExtractor:
    """Bộ bóc tách thông tin pháp lý doanh nghiệp từ văn bản thô theo chuẩn Staging JSON."""

    SYSTEM_PROMPT = (
        "You are a Strict Information Extraction Assistant for Vietnamese Corporate Legal Documents.\n\n"
        "Your task is to extract exact legal entities from the provided SOURCE text and return a valid JSON object matching the required staging schema.\n\n"
        "REQUIRED STAGING SCHEMA:\n"
        "{\n"
        '  "company_name": {"value": string or null, "evidence": string or null, "page": integer or null},\n'
        '  "short_name": {"value": string or null, "evidence": string or null, "page": integer or null},\n'
        '  "tax_code": {"value": string or null, "evidence": string or null, "page": integer or null},\n'
        '  "address": {"value": string or null, "evidence": string or null, "page": integer or null},\n'
        '  "charter_capital_raw": {"value": string or null, "evidence": string or null, "page": integer or null},\n'
        '  "legal_rep_name": {"value": string or null, "evidence": string or null, "page": integer or null},\n'
        '  "legal_rep_title": {"value": string or null, "evidence": string or null, "page": integer or null}\n'
        "}\n\n"
        "ABSOLUTE RULES:\n"
        "1. All 7 top-level keys are strictly required. Do not omit any key.\n"
        "2. For every field, all three sub-keys ('value', 'evidence', 'page') are strictly required.\n"
        "3. All-or-None Invariant: If a field is present, value, evidence, and page must all be non-null. If missing/not found, value, evidence, and page must all be null.\n"
        "4. Exact Grounding & Field Header Requirement: 'evidence' must be exact text copied from SOURCE and MUST include the original field label/header preceding the value (e.g. 'Tên công ty viết bằng tiếng Việt: CÔNG TY ABC', 'Mã số doanh nghiệp: 0101234567', 'Địa chỉ trụ sở chính: Số 123...'). 'value' must be a substring of 'evidence'. 'page' must be the exact integer from [PAGE X] where evidence appears.\n"
        "5. Tax code must be a string.\n"
        "6. Do not convert units (e.g. keep charter capital text as written).\n"
        "7. Vietnamese Honorifics Rule: 'Ông', 'Bà', 'Anh', 'Chị' are honorifics, NOT job titles. 'legal_rep_title' requires an explicit job title (e.g. 'Tổng Giám đốc', 'Chủ tịch HĐQT', 'Giám đốc'). If only an honorific appears before the name with no explicit title, 'legal_rep_title' must be all null.\n"
        "8. Output RAW JSON ONLY. No markdown code blocks (no ```json or ```), no preamble, no explanations, no postscript. Start directly with '{' and end with '}'.\n"
        "9. No additional fields allowed."
    )

    @classmethod
    def build_user_prompt(cls, text: str) -> str:
        return (
            f"SOURCE TEXT WITH PAGE MARKERS:\n"
            f"{text}\n\n"
            f"Extract all 7 legal fields and return raw JSON strictly following the schema and rules above."
        )

    @classmethod
    def extract(cls, source_text: str, api_key: Optional[str] = None) -> LegalDocumentExtraction:
        """Thực thi toàn bộ pipeline bóc tách tài liệu:
        1. Phân tách và kiểm định thẻ trang nguồn -> page_map
        2. Gọi GreenNode MaaS AI qua AIAssistantClient.chat()
        3. Parse JSON nghiêm ngặt (strict json.loads)
        4. Validate qua Pydantic model (LegalDocumentExtraction)
        5. Chuẩn hóa tiền định danh xưng legal_rep_name.value
        6. Kiểm định nhãn ngữ nghĩa chính xác và chuỗi bằng chứng 2 tầng (audit_extraction)
        7. Trả về thực thể LegalDocumentExtraction đã xác thực.
        """
        # Bước 1: Kiểm tra cấu trúc thẻ trang của nguồn
        page_map = split_into_page_map(source_text)

        # Bước 2: Gọi LLM GreenNode MaaS
        user_prompt = cls.build_user_prompt(source_text)
        raw_response = AIAssistantClient.chat(
            system_prompt=cls.SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.0,
            max_tokens=2048,
            api_key=api_key
        )

        # Bước 3: Strict json.loads (Tuyệt đối không gọt markdown fence hay dọn dẹp lời dẫn)
        try:
            parsed_json = json.loads(raw_response)
        except Exception as e:
            raise ExtractionJSONError(
                f"Phản hồi từ GreenNode không phải là JSON thuần túy hợp lệ: {e}. "
                f"Phản hồi nhận được:\n{raw_response}"
            ) from e

        if not isinstance(parsed_json, dict):
            raise ExtractionSchemaError(
                f"Kết quả JSON phải là đối tượng dictionary, nhận được: {type(parsed_json).__name__}"
            )

        # Bước 4: Validate Pydantic Schema
        try:
            extraction_model = LegalDocumentExtraction.model_validate(parsed_json)
        except ValidationError as e:
            raise ExtractionSchemaError(f"Dữ liệu bóc tách không thỏa mãn Pydantic schema: {e}") from e

        # Bước 5: Chuẩn hóa tiền định danh xưng tiếng Việt cho legal_rep_name.value
        if extraction_model.legal_rep_name.value is not None:
            clean_name = strip_legal_rep_honorific(extraction_model.legal_rep_name.value)
            extraction_model.legal_rep_name.value = clean_name

        # Bước 6: Audit ngữ nghĩa chính xác & 2 tầng (Exact Label -> Value ⊆ Evidence ⊆ Page)
        audit_extraction(extraction_model, page_map)

        return extraction_model

"""Semantic document classifier inspecting text content, headings, and structure."""

import os
from typing import Sequence

from .enums import DocumentClass, Modality
from .models import DocumentClassificationResult


# Normalized marker profiles for deterministic scoring
_CLASS_MARKERS: dict[DocumentClass, tuple[str, ...]] = {
    DocumentClass.ENTERPRISE_REGISTRATION: (
        "giấy chứng nhận đăng ký doanh nghiệp",
        "giấy chứng nhận đăng ký kinh doanh",
        "giấy đăng ký kinh doanh",
        "đăng ký kinh doanh",
        "mã số doanh nghiệp",
        "phòng đăng ký kinh doanh",
        "sở kế hoạch và đầu tư",
        "đăng ký thay đổi lần thứ",
        "đăng ký lần đầu",
        "người đại diện theo pháp luật",
        "vốn điều lệ",
    ),
    DocumentClass.COMPANY_CHARTER: (
        "điều lệ công ty",
        "điều lệ tổ chức và hoạt động",
        "điều lệ của công ty",
        "thông báo điều lệ",
        "điều lệ",
        "quy chế tổ chức và hoạt động",
        "căn cứ luật doanh nghiệp",
    ),
    DocumentClass.AUDITED_FINANCIAL_STATEMENTS: (
        "báo cáo kiểm toán độc lập",
        "ý kiến của kiểm toán viên",
        "kiểm toán viên độc lập",
        "báo cáo tài chính đã được kiểm toán",
        "trách nhiệm của kiểm toán viên",
    ),
    DocumentClass.INTERNAL_FINANCIAL_STATEMENTS: (
        "bảng cân đối kế toán",
        "báo cáo kết quả hoạt động kinh doanh",
        "báo cáo lưu chuyển tiền tệ",
        "thuyết minh báo cáo tài chính",
        "báo cáo tài chính quý",
        "báo cáo tài chính riêng lẻ",
        "báo cáo tài chính hợp nhất",
    ),
    DocumentClass.FINANCIAL_WORKBOOK_MB09: (
        "mb09",
        "bảng tính nhu cầu vốn",
        "nhu cầu vốn lưu động",
        "chu kỳ kinh doanh",
        "vòng quay vốn lưu động",
        "chu kỳ ngân quỹ",
        "hạn mức cấp tín dụng",
    ),
    DocumentClass.FINANCIAL_WORKBOOK_MB06: (
        "mb06",
        "template bctc",
        "phân tích báo cáo tài chính",
        "chỉ tiêu tài chính doanh nghiệp",
    ),
    DocumentClass.SHAREHOLDER_RELATED_PARTIES: (
        "danh sách người có liên quan",
        "danh sách cổ đông",
        "thành viên hội đồng quản trị",
        "người nội bộ và người có liên quan",
        "tỷ lệ sở hữu cổ phần",
    ),
    DocumentClass.ANNUAL_REPORT: (
        "báo cáo thường niên",
        "annual report",
        "thông điệp của chủ tịch",
        "báo cáo của ban giám đốc",
    ),
    DocumentClass.CREDIT_INSTITUTION_REPORT_CIC: (
        "trung tâm thông tin tín dụng",
        "thông tin tín dụng",
        "báo cáo cic",
        "nhóm nợ",
        "dư nợ tại các tctd",
        "lịch sử nợ xấu",
        "ngân hàng nhà nước việt nam",
    ),
    DocumentClass.CREDIT_PROPOSAL_DOCX: (
        "tờ trình đề xuất cấp tín dụng",
        "tờ trình thẩm định",
        "mẫu biểu mb07",
        "đơn vị kinh doanh",
        "đề xuất cấp tín dụng",
    ),
    DocumentClass.GENERAL_BUSINESS_DOCUMENT: (
        "kế hoạch sản xuất kinh doanh",
        "hồ sơ năng lực",
        "nghị quyết đại hội đồng cổ đông",
        "phương án kinh doanh",
    ),
}

_EXT_TO_MODALITY: dict[str, Modality] = {
    ".pdf": Modality.TEXT_PDF,
    ".xlsx": Modality.SPREADSHEET,
    ".xls": Modality.SPREADSHEET,
    ".csv": Modality.SPREADSHEET,
    ".docx": Modality.WORD_DOCUMENT,
    ".doc": Modality.WORD_DOCUMENT,
    ".jpg": Modality.IMAGE,
    ".jpeg": Modality.IMAGE,
    ".png": Modality.IMAGE,
}


def _strip_accents_and_delimiters(text: str) -> str:
    """Normalize text by stripping diacritics, d-stroke, and converting delimiters to spaces."""
    import unicodedata
    normalized = text.lower().replace("\u0111", "d").replace("\u0110", "d")
    nfkd = unicodedata.normalize("NFKD", normalized)
    unaccented = "".join([c for c in nfkd if not unicodedata.combining(c)])
    cleaned = unaccented.replace("_", " ").replace("-", " ").replace(".", " ")
    return " ".join(cleaned.split())


class SemanticDocumentClassifier:
    """Classifies document semantic types and determines processing modality."""

    def __init__(self, min_confidence_threshold: float = 0.70) -> None:
        self.min_confidence_threshold = min_confidence_threshold

    def classify(
        self,
        document_id: str,
        text_content: str = "",
        original_filename: str = "",
        mime_type_hint: str | None = None,
        is_scanned_image_pdf: bool = False,
        sheet_names: Sequence[str] = (),
    ) -> DocumentClassificationResult:
        """Classify a document using extracted text, structural markers, and modality hints."""
        normalized_text = text_content.lower()
        normalized_filename = original_filename.lower()
        normalized_sheets = [s.lower() for s in sheet_names]
        stripped_filename = _strip_accents_and_delimiters(original_filename)

        # 1. Determine modality
        modality = self._detect_modality(
            original_filename=normalized_filename,
            mime_type_hint=mime_type_hint,
            is_scanned=is_scanned_image_pdf,
            text_length=len(normalized_text.strip()),
        )

        # 2. Score semantic classes based on textual content markers (Primary signal)
        best_class = DocumentClass.UNKNOWN
        best_score = 0.0
        best_markers: list[str] = []

        all_search_text = " ".join([normalized_text] + normalized_sheets)
        stripped_search_text = _strip_accents_and_delimiters(all_search_text)

        for doc_class, markers in _CLASS_MARKERS.items():
            matched = []
            for m in markers:
                m_stripped = _strip_accents_and_delimiters(m)
                if m in all_search_text or m_stripped in stripped_search_text:
                    matched.append(m)

            if matched:
                score = min(0.95, 0.40 + (len(matched) * 0.15))

                # Weak hint bonus: filename contains keyword
                if any(m in normalized_filename or _strip_accents_and_delimiters(m) in stripped_filename for m in markers):
                    score = min(1.0, score + 0.10)

                if score > best_score:
                    best_score = score
                    best_class = doc_class
                    best_markers = matched

        # 3. Fallback: If no content markers matched, check weak filename hints
        if best_class == DocumentClass.UNKNOWN and original_filename:
            for doc_class, markers in _CLASS_MARKERS.items():
                matched_fname = []
                for m in markers:
                    m_stripped = _strip_accents_and_delimiters(m)
                    if m in normalized_filename or m_stripped in stripped_filename:
                        matched_fname.append(m)
                if matched_fname:
                    # Weak hint only: confidence capped at 0.50, always requiring RM confirmation
                    best_class = doc_class
                    best_score = 0.50
                    best_markers = matched_fname
                    break

        # 4. Handle Scanned PDFs with no OCR text yet
        if modality == Modality.SCANNED_IMAGE_PDF and best_class == DocumentClass.UNKNOWN:
            needs_confirmation = True
            notes = "Scanned image-only PDF detected. Requires OCR for accurate semantic classification."
            confidence = best_score
        else:
            needs_confirmation = best_score < self.min_confidence_threshold or best_class == DocumentClass.UNKNOWN
            notes = (
                f"Confidence below threshold ({best_score:.2f} < {self.min_confidence_threshold}); RM confirmation advised."
                if needs_confirmation and best_class != DocumentClass.UNKNOWN
                else None
            )

        return DocumentClassificationResult(
            document_id=document_id,
            document_class=best_class,
            modality=modality,
            confidence=best_score,
            detected_markers=tuple(best_markers),
            needs_rm_confirmation=needs_confirmation,
            notes=notes,
        )

    def _detect_modality(
        self,
        original_filename: str,
        mime_type_hint: str | None,
        is_scanned: bool,
        text_length: int,
    ) -> Modality:
        _, ext = os.path.splitext(original_filename)
        ext = ext.lower()

        if ext == ".pdf" or (mime_type_hint and "pdf" in mime_type_hint.lower()):
            if is_scanned or text_length < 30:
                return Modality.SCANNED_IMAGE_PDF
            return Modality.TEXT_PDF

        if ext in _EXT_TO_MODALITY:
            return _EXT_TO_MODALITY[ext]

        if mime_type_hint:
            mime = mime_type_hint.lower()
            if "spreadsheet" in mime or "excel" in mime or "csv" in mime:
                return Modality.SPREADSHEET
            if "word" in mime or "officedocument.wordprocessingml" in mime:
                return Modality.WORD_DOCUMENT
            if "image" in mime:
                return Modality.IMAGE

        return Modality.UNKNOWN

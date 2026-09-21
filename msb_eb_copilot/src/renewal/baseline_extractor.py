# -*- coding: utf-8 -*-
"""Module: renewal.baseline_extractor
Mô tả: Trích xuất TẤT ĐỊNH (KHÔNG qua LLM) các giá trị baseline từ Tờ trình
MB07 kỳ trước (.docx) để làm cơ sở so sánh cho luồng Tái cấp tín dụng.

Nguyên tắc cốt lõi:
- Đây là một trình quét nhãn/giá trị tất định (label -> value), tương tự cách
  document_formatter.py duyệt qua bảng biểu (tables -> rows -> cells ->
  paragraphs -> runs). KHÔNG gọi bất kỳ mô hình AI nào.
- Chỉ trích xuất giá trị khi tìm thấy nhãn khớp tường minh trong danh mục
  RENEWAL_TRACKED_FIELDS. Không suy đoán, không nội suy từ ngữ cảnh xung quanh.
- Nếu một trường không tìm thấy trong tài liệu: bỏ qua (coi như vắng mặt trong
  baseline) -- KHÔNG bịa giá trị mặc định.
"""

from __future__ import annotations

import io
import re
import unicodedata
from typing import Dict, List, Optional, Tuple

import docx

from msb_eb_copilot.src.renewal.field_registry import RENEWAL_TRACKED_FIELDS
from msb_eb_copilot.src.renewal.models import RenewalBaselineField

OLD_MB07_SOURCE_LABEL = "MB07 kỳ trước"


class RenewalBaselineExtractionError(Exception):
    """Lỗi khi không thể mở/đọc tệp MB07 kỳ trước (.docx) để trích xuất baseline."""
    pass


def _normalize_label(text: str) -> str:
    if not text:
        return ""
    norm = unicodedata.normalize("NFC", text).strip()
    norm = norm.rstrip(":.- \t")
    return norm.strip().lower()


def _label_matches(candidate_label: str, variants: List[str]) -> bool:
    norm_candidate = _normalize_label(candidate_label)
    if not norm_candidate:
        return False
    for variant in variants:
        norm_variant = _normalize_label(variant)
        if not norm_variant:
            continue
        if norm_candidate == norm_variant or norm_candidate.startswith(norm_variant):
            return True
    return False


def _collect_label_value_candidates(document: "docx.Document") -> List[Tuple[str, str]]:
    """Thu thập các cặp (nhãn, giá trị) ứng viên theo đúng thứ tự xuất hiện
    trong tài liệu, từ hai nguồn tất định:
    1. Bảng biểu dạng 2+ cột: cột đầu = nhãn, cột cuối cùng còn nội dung = giá trị.
    2. Đoạn văn dạng "Nhãn: Giá trị" (tách theo dấu hai chấm đầu tiên)."""
    candidates: List[Tuple[str, str]] = []

    for table in document.tables:
        for row in table.rows:
            cells = row.cells
            if len(cells) < 2:
                continue
            label_text = cells[0].text.strip()
            if not label_text:
                continue
            value_text = ""
            for cell in reversed(cells[1:]):
                cell_text = cell.text.strip()
                if cell_text:
                    value_text = cell_text
                    break
            if value_text:
                candidates.append((label_text, value_text))

    for para in document.paragraphs:
        text = para.text.strip()
        if not text or ":" not in text:
            continue
        label_part, _, value_part = text.partition(":")
        label_part = label_part.strip()
        value_part = value_part.strip()
        if label_part and value_part:
            candidates.append((label_part, value_part))

    return candidates


def extract_old_mb07_baseline(docx_bytes: bytes) -> Dict[str, RenewalBaselineField]:
    """Trích xuất baseline tất định từ tệp MB07 kỳ trước.

    Trả về: Dict[canonical_path -> RenewalBaselineField]. Chỉ chứa các trường
    THỰC SỰ tìm thấy nhãn khớp trong tài liệu -- các trường không tìm thấy sẽ
    vắng mặt trong dict trả về (không bịa giá trị None/rỗng giả).
    """
    try:
        document = docx.Document(io.BytesIO(docx_bytes))
    except Exception as exc:
        raise RenewalBaselineExtractionError(f"Không thể đọc tệp MB07 kỳ trước (.docx): {exc}") from exc

    candidates = _collect_label_value_candidates(document)

    baseline: Dict[str, RenewalBaselineField] = {}
    for field_def in RENEWAL_TRACKED_FIELDS:
        for label_text, value_text in candidates:
            if _label_matches(label_text, field_def.old_label_variants):
                baseline[field_def.canonical_path] = RenewalBaselineField(
                    canonical_path=field_def.canonical_path,
                    label=field_def.label,
                    value=value_text,
                    source=OLD_MB07_SOURCE_LABEL,
                    page=None,
                    evidence=None,
                )
                break  # first match wins (document order) -- deterministic

    return baseline

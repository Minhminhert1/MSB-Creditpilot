# -*- coding: utf-8 -*-
"""Module: renewal.change_detection
Mô tả: So sánh TẤT ĐỊNH giữa baseline (Tờ trình MB07 kỳ trước) và dữ liệu
canonical hiện tại (CASES_DB) để tạo RenewalChangeSet.

Nguyên tắc: UPDATE WHAT CHANGED. PRESERVE WHAT DIDN'T.
- UNCHANGED: giữ nguyên nội dung tờ trình cũ.
- CHANGED: ứng viên cập nhật -- RM phải xác nhận trước khi áp dụng.
- NEW: ứng viên chèn thêm -- RM phải xác nhận trước khi áp dụng.
- REMOVED: KHÔNG tự động xóa thông tin cũ -- RM bắt buộc phải xem xét.
- CONFLICT: KHÔNG tự động chọn -- RM bắt buộc phải giải quyết.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, Optional, Set

from msb_eb_copilot.src.renewal.field_registry import RENEWAL_TRACKED_FIELDS, RenewalFieldDefinition
from msb_eb_copilot.src.renewal.models import ChangeSetItem, ChangeStatus, RenewalBaselineField, RenewalChangeSet

NEW_CANONICAL_SOURCE_LABEL = "Dữ liệu canonical hiện tại"

# Một biến động số học vượt quá ngưỡng này (tỷ lệ tương đối) được coi là bất
# thường tới mức KHÔNG được tự động phân loại là "CHANGED" (cập nhật bình
# thường) -- phải đánh dấu CONFLICT để RM bắt buộc xem xét & giải quyết.
DEFAULT_CONFLICT_RELATIVE_THRESHOLD = 1.0  # biến động > 100% so với giá trị cũ

_VN_NUMBER_PATTERN = re.compile(
    r"(\d{1,3}(?:\.\d{3})*(?:,\d+)?|\d+(?:,\d+)?)\s*(tỷ|ty|triệu|trieu|nghìn|nghin)?",
    re.IGNORECASE,
)


def _normalize_text(text: Optional[str]) -> str:
    if not text:
        return ""
    return unicodedata.normalize("NFC", text).strip().casefold()


def _parse_vn_number_to_trieu(text: Optional[str]) -> Optional[float]:
    """Phân tích một chuỗi số tiếng Việt (dấu '.' phân tách nghìn, dấu ','
    phân tách thập phân) kèm hậu tố đơn vị tùy chọn (tỷ/triệu/nghìn), quy đổi
    về đơn vị triệu VND. Trả về None nếu không tìm thấy số hợp lệ (KHÔNG suy
    đoán/ước lượng khi không phân tích được)."""
    if not text:
        return None
    norm = unicodedata.normalize("NFC", text)
    match = _VN_NUMBER_PATTERN.search(norm)
    if not match:
        return None
    raw_num, unit = match.group(1), (match.group(2) or "").lower()
    cleaned = raw_num.replace(".", "").replace(",", ".")
    try:
        value = float(cleaned)
    except ValueError:
        return None
    if unit in ("tỷ", "ty"):
        value *= 1000.0
    elif unit in ("nghìn", "nghin"):
        value /= 1000.0
    return value


def format_trieu_as_ty_display(value_trieu: float) -> str:
    """Định dạng một giá trị (đơn vị triệu VND) thành chuỗi hiển thị 'X.XXX tỷ
    VND', nhất quán với quy ước hiển thị hiện có của ứng dụng (vd dash-rev-2025)."""
    ty_value = value_trieu / 1000.0
    grouped = f"{ty_value:,.0f}".replace(",", ".")
    return f"{grouped} tỷ VND"


def _values_equal_or_changed(
    field_def: RenewalFieldDefinition,
    old_value: str,
    new_value: str,
) -> ChangeStatus:
    """Quyết định UNCHANGED/CHANGED/CONFLICT cho một cặp giá trị cùng tồn tại
    ở cả hai phía (không xử lý NEW/REMOVED ở đây)."""
    if field_def.is_numeric:
        old_num = _parse_vn_number_to_trieu(old_value)
        new_num = _parse_vn_number_to_trieu(new_value)
        if old_num is not None and new_num is not None:
            if old_num == 0:
                return ChangeStatus.UNCHANGED if new_num == 0 else ChangeStatus.CHANGED
            relative_diff = abs(new_num - old_num) / abs(old_num)
            if relative_diff <= 0.005:  # dung sai làm tròn hiển thị, không phải sai số thực chất
                return ChangeStatus.UNCHANGED
            if relative_diff > DEFAULT_CONFLICT_RELATIVE_THRESHOLD:
                return ChangeStatus.CONFLICT
            return ChangeStatus.CHANGED
        # Không phân tích được số ở một trong hai phía -- so sánh chuỗi tất định.

    return ChangeStatus.UNCHANGED if _normalize_text(old_value) == _normalize_text(new_value) else ChangeStatus.CHANGED


def extract_new_canonical_snapshot(case_data: Dict[str, Any]) -> Dict[str, RenewalBaselineField]:
    """Xây dựng snapshot canonical HIỆN TẠI (từ CASES_DB[case_id]) cho đúng
    tập khóa canonical_path trong RENEWAL_TRACKED_FIELDS -- KHÔNG bịa đặt giá
    trị cho trường không có dữ liệu (bỏ qua khỏi kết quả)."""
    snapshot: Dict[str, RenewalBaselineField] = {}

    customer = case_data.get("customer") or {}
    section_c = case_data.get("section_c") or {}
    section_d = case_data.get("section_d") or {}
    section_e = case_data.get("section_e") or {}

    def _latest(series_key: str) -> Optional[float]:
        series = section_d.get(series_key)
        if isinstance(series, list) and series:
            return series[-1]
        return None

    raw_values: Dict[str, Any] = {
        "customer.legal_name": customer.get("name"),
        "customer.address": customer.get("address"),
        "financial.net_revenue_latest": _latest("net_revenue"),
        "financial.net_profit_after_tax_latest": _latest("net_profit_after_tax"),
        "financial.total_assets_latest": _latest("total_assets"),
        "financial.equity_latest": _latest("equity"),
        "financial.inventories_latest": _latest("inventories"),
        "financial.receivables_latest": _latest("receivables"),
        "financial.short_term_debt_latest": _latest("short_term_debt"),
        "business.key_customer": (section_c.get("customers") or [{}])[0].get("name") if section_c.get("customers") else None,
        "credit.msb_outstanding": section_e.get("msb_outstanding"),
    }

    for field_def in RENEWAL_TRACKED_FIELDS:
        raw_value = raw_values.get(field_def.canonical_path)
        if raw_value is None or (isinstance(raw_value, str) and not raw_value.strip()):
            continue  # thiếu dữ liệu -- KHÔNG bịa, bỏ qua khỏi snapshot

        if field_def.is_numeric and isinstance(raw_value, (int, float)):
            display_value = format_trieu_as_ty_display(float(raw_value))
        else:
            display_value = str(raw_value)

        snapshot[field_def.canonical_path] = RenewalBaselineField(
            canonical_path=field_def.canonical_path,
            label=field_def.label,
            value=display_value,
            source=NEW_CANONICAL_SOURCE_LABEL,
        )

    return snapshot


def build_change_set(
    case_id: str,
    old_baseline: Dict[str, RenewalBaselineField],
    new_snapshot: Dict[str, RenewalBaselineField],
    conflicting_paths: Optional[Set[str]] = None,
) -> RenewalChangeSet:
    """So sánh tất định old_baseline (MB07 kỳ trước) với new_snapshot (canonical
    hiện tại) và trả về RenewalChangeSet. KHÔNG bịa đặt provenance -- mọi
    old_source/new_evidence/new_page chỉ được lấy nguyên trạng từ dữ liệu đầu vào."""
    conflicting_paths = conflicting_paths or set()
    items = []

    all_paths = {f.canonical_path for f in RENEWAL_TRACKED_FIELDS}
    # Bao gồm cả các canonical_path xuất hiện trong baseline/snapshot nhưng
    # (giả thuyết) không còn trong registry hiện tại -- không bỏ sót dữ liệu.
    all_paths |= set(old_baseline.keys()) | set(new_snapshot.keys())

    for canonical_path in sorted(all_paths):
        field_def = next((f for f in RENEWAL_TRACKED_FIELDS if f.canonical_path == canonical_path), None)
        label = field_def.label if field_def else canonical_path

        old_field = old_baseline.get(canonical_path)
        new_field = new_snapshot.get(canonical_path)

        if old_field is None and new_field is None:
            continue

        if old_field is not None and new_field is None:
            status = ChangeStatus.REMOVED
        elif old_field is None and new_field is not None:
            status = ChangeStatus.NEW
        else:
            if canonical_path in conflicting_paths:
                status = ChangeStatus.CONFLICT
            elif field_def is not None:
                status = _values_equal_or_changed(field_def, old_field.value or "", new_field.value or "")
            else:
                status = ChangeStatus.UNCHANGED if _normalize_text(old_field.value) == _normalize_text(new_field.value) else ChangeStatus.CHANGED

        items.append(ChangeSetItem(
            canonical_path=canonical_path,
            label=label,
            old_value=old_field.value if old_field else None,
            new_value=new_field.value if new_field else None,
            status=status,
            old_source=old_field.source if old_field else None,
            new_source=new_field.source if new_field else None,
            new_evidence=new_field.evidence if new_field else None,
            new_page=new_field.page if new_field else None,
        ))

    return RenewalChangeSet(case_id=case_id, items=items)

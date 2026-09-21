# -*- coding: utf-8 -*-
"""Package renewal: Luồng "Tái cấp tín dụng" (renewal) -- so sánh tất định
giữa Tờ trình MB07 kỳ trước và dữ liệu canonical hiện tại, tạo ChangeSet cho
RM xác nhận trước khi áp dụng vào tờ trình mới thông qua kiến trúc sinh/chỉnh
sửa MB07 hiện có (không để LLM tự do viết lại DOCX)."""

from msb_eb_copilot.src.renewal.models import (
    ChangeSetItem,
    ChangeStatus,
    RMResolution,
    RenewalBaselineField,
    RenewalCaseState,
    RenewalChangeSet,
)
from msb_eb_copilot.src.renewal.field_registry import RENEWAL_TRACKED_FIELDS, RENEWAL_FIELD_BY_PATH
from msb_eb_copilot.src.renewal.baseline_extractor import (
    extract_old_mb07_baseline,
    RenewalBaselineExtractionError,
)
from msb_eb_copilot.src.renewal.change_detection import (
    extract_new_canonical_snapshot,
    build_change_set,
    format_trieu_as_ty_display,
)
from msb_eb_copilot.src.renewal.store import RENEWAL_STORE, RenewalStore, RenewalItemNotFoundError

__all__ = [
    "ChangeSetItem",
    "ChangeStatus",
    "RMResolution",
    "RenewalBaselineField",
    "RenewalCaseState",
    "RenewalChangeSet",
    "RENEWAL_TRACKED_FIELDS",
    "RENEWAL_FIELD_BY_PATH",
    "extract_old_mb07_baseline",
    "RenewalBaselineExtractionError",
    "extract_new_canonical_snapshot",
    "build_change_set",
    "format_trieu_as_ty_display",
    "RENEWAL_STORE",
    "RenewalStore",
    "RenewalItemNotFoundError",
]

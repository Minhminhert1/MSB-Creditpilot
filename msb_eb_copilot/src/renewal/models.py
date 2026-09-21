# -*- coding: utf-8 -*-
"""Module: renewal.models
Mô tả: Mô hình dữ liệu tất định (deterministic) cho luồng "Tái cấp tín dụng"
(renewal). Tuyệt đối KHÔNG để LLM tự do viết lại Tờ trình MB07 kỳ trước:
mọi thay đổi trước tiên phải trở thành các đối tượng ChangeSetItem tất định,
và chỉ những thay đổi đã được RM xác nhận mới được áp dụng sau đó thông qua
kiến trúc sinh/chỉnh sửa MB07 hiện có (CreditProposalAssembler / MB07InPlaceMutator).
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ChangeStatus(str, Enum):
    """Trạng thái so sánh tất định giữa hồ sơ kỳ trước và dữ liệu mới."""
    UNCHANGED = "UNCHANGED"
    CHANGED = "CHANGED"
    NEW = "NEW"
    REMOVED = "REMOVED"
    CONFLICT = "CONFLICT"


class RMResolution(str, Enum):
    """Lựa chọn xử lý của RM cho một mục thay đổi (chỉ áp dụng cho các mục
    KHÔNG phải UNCHANGED). UNCHANGED không cần và không yêu cầu RM thao tác."""
    PENDING = "PENDING"
    ACCEPT_NEW = "ACCEPT_NEW"          # "Chấp nhận" -- dùng giá trị mới
    KEEP_OLD = "KEEP_OLD"              # "Giữ nội dung cũ" -- giữ baseline kỳ trước
    EDITED = "EDITED"                  # "Chỉnh sửa" -- RM cung cấp giá trị thay thế


class RenewalBaselineField(BaseModel):
    """Một giá trị trường thông tin trích xuất tất định (KHÔNG qua LLM) từ Tờ
    trình MB07 kỳ trước, hoặc một giá trị canonical hiện tại lấy từ CASES_DB."""
    canonical_path: str = Field(..., description="Khóa canonical tất định, vd 'financial.net_revenue_latest'")
    label: str = Field(..., description="Nhãn tiếng Việt hiển thị cho RM, vd 'Doanh thu thuần'")
    value: Optional[str] = Field(None, description="Giá trị dạng chuỗi hiển thị (đã chuẩn hóa để so sánh)")
    source: Optional[str] = Field(None, description="Mô tả nguồn gốc an toàn, vd 'MB07 kỳ trước' hoặc 'BCTC 2025'")
    page: Optional[int] = Field(None, description="Số trang bằng chứng nếu có (KHÔNG bịa đặt khi không có)")
    evidence: Optional[str] = Field(None, description="Trích dẫn bằng chứng verbatim nếu có (KHÔNG bịa đặt khi không có)")


class ChangeSetItem(BaseModel):
    """Một mục so sánh tất định giữa baseline (kỳ trước) và canonical hiện tại.

    Bất biến bắt buộc (Zero Silent Fallback):
    - REMOVED: KHÔNG tự động xóa thông tin cũ -- chỉ đánh dấu cần RM xem xét.
    - CONFLICT: KHÔNG tự động chọn -- RM bắt buộc phải giải quyết.
    - CHANGED/NEW: chỉ là ỨNG VIÊN cập nhật/chèn, không tự động ghi vào hồ sơ.
    """
    canonical_path: str
    label: str
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    status: ChangeStatus
    old_source: Optional[str] = None
    new_source: Optional[str] = None
    new_evidence: Optional[str] = None
    new_page: Optional[int] = None
    # RM review state -- populated only after RM interacts with this item.
    rm_resolution: RMResolution = RMResolution.PENDING
    rm_edited_value: Optional[str] = None
    rm_note: Optional[str] = None

    def requires_rm_action(self) -> bool:
        """UNCHANGED items never require RM action; everything else does until resolved."""
        return self.status != ChangeStatus.UNCHANGED


class RenewalChangeSet(BaseModel):
    """Toàn bộ kết quả phân tích thay đổi tất định cho một hồ sơ (case)."""
    case_id: str
    items: List[ChangeSetItem] = Field(default_factory=list)

    @property
    def summary(self) -> Dict[str, int]:
        counts = {status.value: 0 for status in ChangeStatus}
        for item in self.items:
            counts[item.status.value] += 1
        return counts

    @property
    def is_rm_review_complete(self) -> bool:
        return all(
            item.rm_resolution != RMResolution.PENDING
            for item in self.items
            if item.requires_rm_action()
        )


class RenewalCaseState(BaseModel):
    """Trạng thái tái cấp của MỘT case cụ thể -- KHÔNG BAO GIỜ được dùng chung
    giữa các case (mỗi case_id có instance riêng trong RenewalStore)."""
    case_id: str
    old_mb07_filename: Optional[str] = None
    old_mb07_parsed: bool = False
    old_baseline: Dict[str, RenewalBaselineField] = Field(default_factory=dict)
    change_set: Optional[RenewalChangeSet] = None

    @property
    def has_old_mb07(self) -> bool:
        return self.old_mb07_filename is not None

    @property
    def has_change_analysis(self) -> bool:
        return self.change_set is not None

# -*- coding: utf-8 -*-
"""Module: renewal.store
Mô tả: Lưu trữ trạng thái Tái cấp tín dụng TRONG BỘ NHỚ (in-process), CÔ LẬP
THEO TỪNG CASE (case_id). Tuyệt đối không có trạng thái toàn cục dùng chung
giữa các case -- mỗi case_id có một RenewalCaseState riêng biệt.
"""

from __future__ import annotations

import threading
from typing import Dict, List, Optional

from msb_eb_copilot.src.renewal.models import (
    ChangeSetItem,
    ChangeStatus,
    RenewalCaseState,
    RenewalChangeSet,
    RMResolution,
)


class RenewalItemNotFoundError(Exception):
    pass


class RenewalStore:
    """Thread-safe, cô lập theo case_id. Không bao giờ để dữ liệu của case A
    rò rỉ sang case B."""

    def __init__(self) -> None:
        self._states: Dict[str, RenewalCaseState] = {}
        self._lock = threading.Lock()

    def get_or_create(self, case_id: str) -> RenewalCaseState:
        with self._lock:
            if case_id not in self._states:
                self._states[case_id] = RenewalCaseState(case_id=case_id)
            return self._states[case_id]

    def get(self, case_id: str) -> Optional[RenewalCaseState]:
        with self._lock:
            return self._states.get(case_id)

    def set_old_baseline(self, case_id: str, filename: str, baseline: dict) -> RenewalCaseState:
        with self._lock:
            state = self._states.setdefault(case_id, RenewalCaseState(case_id=case_id))
            state.old_mb07_filename = filename
            state.old_baseline = baseline
            state.old_mb07_parsed = True
            state.change_set = None  # phân tích cũ (nếu có) không còn hiệu lực
            return state

    def set_change_set(self, case_id: str, change_set: RenewalChangeSet) -> RenewalCaseState:
        with self._lock:
            state = self._states.setdefault(case_id, RenewalCaseState(case_id=case_id))
            state.change_set = change_set
            return state

    def resolve_change_item(
        self,
        case_id: str,
        canonical_path: str,
        resolution: RMResolution,
        edited_value: Optional[str] = None,
        note: Optional[str] = None,
    ) -> ChangeSetItem:
        with self._lock:
            state = self._states.get(case_id)
            if state is None or state.change_set is None:
                raise RenewalItemNotFoundError(f"Không tìm thấy phân tích thay đổi cho hồ sơ '{case_id}'.")
            for item in state.change_set.items:
                if item.canonical_path == canonical_path:
                    item.rm_resolution = resolution
                    item.rm_edited_value = edited_value
                    item.rm_note = note
                    return item
            raise RenewalItemNotFoundError(f"Không tìm thấy mục thay đổi '{canonical_path}' trong hồ sơ '{case_id}'.")

    def clear_case(self, case_id: str) -> None:
        with self._lock:
            self._states.pop(case_id, None)


RENEWAL_STORE = RenewalStore()

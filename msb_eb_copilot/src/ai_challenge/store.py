# -*- coding: utf-8 -*-
"""Module: ai_challenge.store
Mô tả: Lưu trữ trạng thái AI Challenge TRONG BỘ NHỚ (in-process), CÔ LẬP THEO
TỪNG CASE (case_id). Không bao giờ để trạng thái của case A rò rỉ sang case B.
Không bao giờ xóa âm thầm các challenge đã bị RM đánh dấu "Không áp dụng" --
toàn bộ lịch sử được giữ lại trong audit trail (chỉ thay đổi rm_status/rm_response).
"""

from __future__ import annotations

import threading
from enum import Enum
from typing import Dict, Optional

from pydantic import BaseModel, Field

from msb_eb_copilot.src.ai_challenge.models import ChallengeSet, ChallengeStatus


class ChallengeRunStatus(str, Enum):
    NOT_RUN = "NOT_RUN"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"


class ChallengeCaseState(BaseModel):
    case_id: str
    run_status: ChallengeRunStatus = ChallengeRunStatus.NOT_RUN
    challenge_set: Optional[ChallengeSet] = None


class ChallengeItemNotFoundError(Exception):
    pass


class AIChallengeStore:
    def __init__(self) -> None:
        self._states: Dict[str, ChallengeCaseState] = {}
        self._lock = threading.Lock()

    def get_or_create(self, case_id: str) -> ChallengeCaseState:
        with self._lock:
            if case_id not in self._states:
                self._states[case_id] = ChallengeCaseState(case_id=case_id)
            return self._states[case_id]

    def get(self, case_id: str) -> Optional[ChallengeCaseState]:
        with self._lock:
            return self._states.get(case_id)

    def mark_running(self, case_id: str) -> ChallengeCaseState:
        with self._lock:
            state = self._states.setdefault(case_id, ChallengeCaseState(case_id=case_id))
            state.run_status = ChallengeRunStatus.RUNNING
            return state

    def set_challenge_set(self, case_id: str, challenge_set: ChallengeSet) -> ChallengeCaseState:
        with self._lock:
            state = self._states.setdefault(case_id, ChallengeCaseState(case_id=case_id))
            state.challenge_set = challenge_set
            state.run_status = ChallengeRunStatus.COMPLETED
            return state

    def respond(
        self,
        case_id: str,
        challenge_id: str,
        rm_status: ChallengeStatus,
        rm_response: Optional[str] = None,
    ):
        with self._lock:
            state = self._states.get(case_id)
            if state is None or state.challenge_set is None:
                raise ChallengeItemNotFoundError(f"Chưa có AI Challenge nào được chạy cho hồ sơ '{case_id}'.")
            for item in state.challenge_set.items:
                if item.id == challenge_id:
                    item.rm_status = rm_status
                    if rm_response is not None:
                        item.rm_response = rm_response
                    return item
            raise ChallengeItemNotFoundError(f"Không tìm thấy challenge '{challenge_id}' trong hồ sơ '{case_id}'.")

    def clear_case(self, case_id: str) -> None:
        with self._lock:
            self._states.pop(case_id, None)


AI_CHALLENGE_STORE = AIChallengeStore()

# -*- coding: utf-8 -*-
"""Module: ai_challenge.models
Mô tả: Mô hình dữ liệu cho "AI Credit Challenge" -- một CREDIT REVIEWER /
DEVIL'S ADVOCATE, KHÔNG PHẢI mô hình phê duyệt tín dụng.

AI Challenge TUYỆT ĐỐI KHÔNG được xuất ra:
- Approve / Reject
- Good / Bad customer
- Safe / Unsafe
- Khuyến nghị cấp tín dụng
- Rủi ro bịa đặt (không có căn cứ dữ liệu)

Mỗi ChallengeItem BẮT BUỘC tách biệt rõ 3 phần: OBSERVATION (quan sát có căn
cứ) / RISK_HYPOTHESIS (giả thuyết -- KHÔNG PHẢI kết luận) / QUESTION (câu hỏi
cho RM). severity chỉ dùng để ưu tiên rà soát, KHÔNG PHẢI quyết định phê duyệt.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ChallengeSeverity(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ChallengeStatus(str, Enum):
    OPEN = "OPEN"
    ANSWERED = "ANSWERED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ChallengeCategory(str, Enum):
    FINANCIAL = "FINANCIAL"
    BUSINESS = "BUSINESS"
    CREDIT = "CREDIT"
    DATA_CONSISTENCY = "DATA_CONSISTENCY"
    RENEWAL = "RENEWAL"


class EnrichmentStatus(str, Enum):
    """Trạng thái của bước diễn đạt lại (enrichment) qua GreenNode -- CHỈ là một
    nâng cao trình bày KHÔNG có thẩm quyền (non-authoritative). Nội dung
    challenge tất định (analyzers.py) luôn có thẩm quyền (authoritative) và
    LUÔN khả dụng bất kể trạng thái enrichment này.

    - NOT_REQUESTED: không truyền ai_client (không yêu cầu diễn đạt lại).
    - SUCCESS: mọi rewrite được yêu cầu đều thành công và vượt qua xác minh grounding.
    - PARTIAL: một số rewrite thất bại/bị từ chối, nhưng văn bản tất định vẫn hợp lệ.
    - FAILED: toàn bộ rewrite được yêu cầu đều thất bại/bị từ chối.
    """
    NOT_REQUESTED = "NOT_REQUESTED"
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class AnalyzerWarning(BaseModel):
    """Cảnh báo AN TOÀN (không lộ stack trace/nội bộ) khi một phép tính tất
    định TÙY CHỌN (vd một tỷ số tài chính) không thể thực hiện được. Chỉ tín
    hiệu challenge bị ảnh hưởng bị bỏ qua -- KHÔNG bịa giá trị thay thế, KHÔNG
    làm hỏng các bộ phân tích khác."""
    component: str = Field(..., description="Tên tất định của thành phần bị ảnh hưởng, vd 'financial.current_ratio'")
    code: str = Field(..., description="Mã lỗi an toàn, vd 'DETERMINISTIC_CALCULATION_FAILED'")
    message: Optional[str] = Field(None, description="Thông điệp an toàn tùy chọn (không chứa nội dung kỹ thuật/nội bộ)")


class ChallengeFactRef(BaseModel):
    """Một tham chiếu bằng chứng cho challenge. page/evidence CHỈ được điền
    khi thực sự có (KHÔNG bịa đặt) -- để trống (None) là hành vi đúng và an
    toàn khi hệ thống không có provenance cấp trang cho giá trị này."""
    canonical_path: str
    value: str
    source: str
    page: Optional[int] = None
    evidence: Optional[str] = None


class ChallengeItem(BaseModel):
    id: str
    category: ChallengeCategory
    severity: ChallengeSeverity
    title: str

    observation: str = Field(..., description="Quan sát có căn cứ dữ liệu -- KHÔNG phải kết luận")
    risk_hypothesis: str = Field(..., description="Giả thuyết rủi ro -- PHẢI giữ nguyên là giả thuyết, không phải kết luận")
    question: str = Field(..., description="Câu hỏi dành cho RM để làm rõ")

    facts_used: List[ChallengeFactRef] = Field(default_factory=list)

    # RM_EXPLANATION -- tách biệt hoàn toàn khỏi SOURCE_FACT (facts_used ở trên).
    # KHÔNG BAO GIỜ được chuyển đổi rm_response thành một SOURCE_FACT.
    rm_response: Optional[str] = None
    rm_status: ChallengeStatus = ChallengeStatus.OPEN

    def mark_answered(self, rm_response: str) -> None:
        self.rm_response = rm_response
        self.rm_status = ChallengeStatus.ANSWERED

    def mark_not_applicable(self, rm_response: Optional[str] = None) -> None:
        if rm_response is not None:
            self.rm_response = rm_response
        self.rm_status = ChallengeStatus.NOT_APPLICABLE


class ChallengeSet(BaseModel):
    case_id: str
    items: List[ChallengeItem] = Field(default_factory=list)

    # Zero Silent Fallback metadata (see engine.py):
    # A. Deterministic base challenge generation (items above) -> AUTHORITATIVE,
    #    always available regardless of the fields below.
    # B. Optional GreenNode language enrichment -> NON-AUTHORITATIVE presentation
    #    enhancement. Its failure/rejection must be explicitly observable here --
    #    never silent -- but must never invalidate A.
    enrichment_status: EnrichmentStatus = EnrichmentStatus.NOT_REQUESTED
    enrichment_warning: Optional[str] = Field(
        None, description="Cảnh báo an toàn hiển thị cho RM khi enrichment_status là PARTIAL/FAILED -- không chứa nội dung kỹ thuật/nội bộ."
    )
    analyzer_warnings: List[AnalyzerWarning] = Field(
        default_factory=list,
        description="Cảnh báo an toàn khi một phép tính tất định TÙY CHỌN (vd current_ratio) thất bại -- chỉ tín hiệu bị ảnh hưởng bị bỏ qua, không bịa giá trị.",
    )

    @property
    def summary(self) -> Dict[str, int]:
        by_category: Dict[str, int] = {c.value: 0 for c in ChallengeCategory}
        for item in self.items:
            by_category[item.category.value] += 1
        return {"total": len(self.items), **by_category}

    @property
    def progress(self) -> Dict[str, int]:
        resolved = sum(1 for i in self.items if i.rm_status != ChallengeStatus.OPEN)
        return {"resolved": resolved, "total": len(self.items)}

    def get_rm_explanations(self) -> List[Dict[str, Any]]:
        """RM_EXPLANATION provenance (KHÔNG PHẢI SOURCE_FACT) -- chỉ những
        challenge đã được RM giải trình (ANSWERED) với nội dung rm_response
        thực sự khác rỗng."""
        return [
            {
                "id": item.id,
                "title": item.title,
                "question": item.question,
                "rm_explanation": item.rm_response,
            }
            for item in self.items
            if item.rm_status == ChallengeStatus.ANSWERED and item.rm_response
        ]

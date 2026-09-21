# -*- coding: utf-8 -*-
"""Module: ai_challenge.engine
Mô tả: Điều phối AI Credit Challenge. Kiến trúc "AI đề xuất, Python kiểm soát":

1. Các bộ phân tích TẤT ĐỊNH (analyzers.py) tính toán số liệu và sinh sẵn văn
   bản observation/risk_hypothesis/question bằng template -- LUÔN hoạt động
   được, không phụ thuộc mạng/API key. Đây là nội dung CÓ THẨM QUYỀN
   (authoritative) -- luôn khả dụng bất kể bước 2 dưới đây thành công hay không.
2. (Tùy chọn) Một bước "diễn đạt lại" qua GreenNode CHỈ được phép chỉnh văn
   phong -- KHÔNG được thêm số liệu mới, KHÔNG được kết luận phê duyệt/từ
   chối/an toàn/rủi ro cao. Đây là phần KHÔNG CÓ THẨM QUYỀN (non-authoritative
   presentation enhancement) -- kết quả LUÔN được Python xác minh lại trước
   khi dùng; nếu xác minh thất bại (hoặc lời gọi AI thất bại vì bất kỳ lý do
   nào), hệ thống quay về văn bản tất định gốc -- KHÔNG BAO GIỜ chặn hoặc làm
   hỏng luồng chính.

ZERO SILENT FALLBACK: quay về văn bản tất định là hành vi AN TOÀN và ĐÚNG, nhưng
việc đó KHÔNG ĐƯỢC PHÉP xảy ra một cách im lặng -- mỗi lần enrichment thất bại/
bị từ chối đều được ghi log (an toàn, không lộ stack trace/nội bộ) và phản ánh
qua ChallengeSet.enrichment_status/enrichment_warning để RM/giao diện biết rõ.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from msb_eb_copilot.src.ai_challenge.analyzers import (
    analyze_business,
    analyze_credit,
    analyze_data_consistency,
    analyze_financial,
    analyze_renewal_changes,
)
from msb_eb_copilot.src.ai_challenge.models import (
    AnalyzerWarning,
    ChallengeItem,
    ChallengeSet,
    EnrichmentStatus,
)
from msb_eb_copilot.src.renewal.models import RenewalChangeSet

logger = logging.getLogger(__name__)

# Cảnh báo AN TOÀN hiển thị cho RM khi enrichment_status là PARTIAL/FAILED --
# KHÔNG được chứa stack trace, nội bộ nhà cung cấp, API key, prompt gốc, hay
# request payload. Nội dung challenge tất định vẫn hoàn toàn hợp lệ và khả dụng.
ENRICHMENT_INCOMPLETE_WARNING_VI = (
    "AI Challenge đã được tạo bằng bộ quy tắc kiểm soát. "
    "Bước tinh chỉnh ngôn ngữ AI không hoàn tất."
)

# Cụm từ CẤM TUYỆT ĐỐI trong văn bản challenge -- AI Challenge KHÔNG PHẢI mô
# hình phê duyệt tín dụng (xem models.py docstring).
_FORBIDDEN_DECISION_PHRASES = [
    "phê duyệt", "từ chối cấp", "chấp thuận cấp", "không nên cấp", "nên cấp",
    "khách hàng tốt", "khách hàng xấu", "an toàn tuyệt đối", "hoàn toàn an toàn",
    "không an toàn", "khuyến nghị cấp tín dụng", "approve", "reject",
]


def _extract_numeric_tokens(text: str) -> List[str]:
    return re.findall(r"\d[\d.,]*\d|\d", text or "")


def _contains_forbidden_language(text: str) -> bool:
    lowered = (text or "").lower()
    return any(phrase in lowered for phrase in _FORBIDDEN_DECISION_PHRASES)


def _rewrite_is_grounded(original: str, rewritten: str) -> bool:
    """Xác minh bản diễn đạt lại KHÔNG bịa thêm số liệu và KHÔNG chứa ngôn ngữ
    kết luận phê duyệt bị cấm. Mọi token số trong bản gốc phải còn nguyên
    trong bản viết lại (không được đổi số)."""
    if not rewritten or not rewritten.strip():
        return False
    if _contains_forbidden_language(rewritten):
        return False
    for token in _extract_numeric_tokens(original):
        if token not in rewritten:
            return False
    return True


def _maybe_enrich_item(item: ChallengeItem, ai_client: Optional[Any]) -> Tuple[ChallengeItem, Optional[str]]:
    """Cố gắng diễn đạt lại observation/risk_hypothesis/question qua GreenNode,
    áp dụng ĐỘC LẬP cho từng phần (một phần có thể được cải thiện trong khi
    phần khác giữ nguyên bản tất định nếu phần đó không đạt xác minh).

    Trả về (item, failure_reason). failure_reason là None khi mọi phần đều
    được cải thiện thành công và vượt xác minh grounding; ngược lại là một mã
    AN TOÀN (không lộ nội bộ/stack trace) mô tả (các) lý do rơi về văn bản tất
    định, dùng để tổng hợp enrichment_status ở generate(). Văn bản tất định
    gốc từ analyzers.py LUÔN được giữ lại cho bất kỳ phần nào không đạt."""
    if ai_client is None:
        return item, None

    failure_reasons: List[str] = []

    try:
        from msb_eb_copilot.src.ai_client import AIAssistantClient
        client = ai_client if ai_client is not True else AIAssistantClient

        system_prompt = (
            "Bạn là biên tập viên văn phong cho một hệ thống rà soát tín dụng nội bộ. "
            "Bạn CHỈ được phép diễn đạt lại câu chữ cho tự nhiên hơn. "
            "TUYỆT ĐỐI KHÔNG được thêm, bớt, hoặc thay đổi bất kỳ con số nào. "
            "TUYỆT ĐỐI KHÔNG được đưa ra kết luận phê duyệt/từ chối/an toàn/rủi ro cao. "
            "Giữ nguyên ý nghĩa và mọi số liệu của văn bản gốc."
        )
        user_prompt = (
            f"OBSERVATION: {item.observation}\n"
            f"RISK_HYPOTHESIS: {item.risk_hypothesis}\n"
            f"QUESTION: {item.question}\n"
            "Hãy trả về đúng 3 dòng theo định dạng OBSERVATION:/RISK_HYPOTHESIS:/QUESTION: tương ứng."
        )
        response_text = client.chat(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.2,
            max_tokens=512,
            timeout=10.0,
            max_retries=0,
            operation="ai_challenge_rewrite",
        )
        if not response_text or not response_text.strip():
            logger.warning("AI Challenge enrichment returned an empty response for item_id=%s -- keeping deterministic text.", item.id)
            return item, "EMPTY_RESPONSE"

        rewritten: Dict[str, str] = {}
        for line in response_text.splitlines():
            for key in ("OBSERVATION", "RISK_HYPOTHESIS", "QUESTION"):
                prefix = f"{key}:"
                if line.strip().upper().startswith(prefix):
                    rewritten[key] = line.split(":", 1)[1].strip()

        # OBSERVATION -- applied independently; any rejection keeps the
        # deterministic original for this field only.
        if "OBSERVATION" not in rewritten:
            failure_reasons.append("MISSING_OBSERVATION")
        elif not _rewrite_is_grounded(item.observation, rewritten["OBSERVATION"]):
            failure_reasons.append("GROUNDING_REJECTED_OBSERVATION")
        else:
            item.observation = rewritten["OBSERVATION"]

        # RISK_HYPOTHESIS
        if "RISK_HYPOTHESIS" not in rewritten:
            failure_reasons.append("MISSING_RISK_HYPOTHESIS")
        elif not _rewrite_is_grounded(item.risk_hypothesis, rewritten["RISK_HYPOTHESIS"]):
            failure_reasons.append("GROUNDING_REJECTED_RISK_HYPOTHESIS")
        else:
            item.risk_hypothesis = rewritten["RISK_HYPOTHESIS"]

        # QUESTION -- no numeric-grounding requirement (questions rarely carry
        # the source numbers), but still bound by the forbidden-language check
        # and must not be blank.
        if "QUESTION" not in rewritten:
            failure_reasons.append("MISSING_QUESTION")
        elif not rewritten["QUESTION"].strip():
            failure_reasons.append("EMPTY_QUESTION")
        elif _contains_forbidden_language(rewritten["QUESTION"]):
            failure_reasons.append("FORBIDDEN_LANGUAGE_QUESTION")
        else:
            item.question = rewritten["QUESTION"]

        if failure_reasons:
            logger.warning(
                "AI Challenge enrichment partially rejected for item_id=%s (reasons=%s) -- "
                "deterministic text preserved for the affected field(s).",
                item.id, ",".join(failure_reasons),
            )
        return item, (",".join(failure_reasons) if failure_reasons else None)
    except Exception:
        logger.exception(
            "AI Challenge enrichment call failed for item_id=%s -- falling back to deterministic template text.",
            item.id,
        )
        return item, "ENRICHMENT_CALL_FAILED"


class AIChallengeEngine:
    """Điều phối sinh ChallengeSet cho một case cụ thể."""

    @classmethod
    def generate(
        cls,
        case_id: str,
        case_data: Dict[str, Any],
        renewal_change_set: Optional[RenewalChangeSet] = None,
        ai_client: Optional[Any] = None,
    ) -> ChallengeSet:
        analyzer_warnings: List[AnalyzerWarning] = []
        items: List[ChallengeItem] = []
        items.extend(analyze_financial(case_data, warnings_out=analyzer_warnings))
        items.extend(analyze_business(case_data))
        items.extend(analyze_credit(case_data))
        items.extend(analyze_data_consistency(case_data))
        if renewal_change_set is not None:
            items.extend(analyze_renewal_changes(renewal_change_set))

        enrichment_status = EnrichmentStatus.NOT_REQUESTED
        enrichment_warning: Optional[str] = None

        if ai_client is not None:
            if not items:
                # Nothing to enrich -- vacuously successful, not "not requested"
                # (ai_client WAS supplied), but there is no rewrite to fail.
                enrichment_status = EnrichmentStatus.SUCCESS
            else:
                results = [_maybe_enrich_item(item, ai_client) for item in items]
                items = [item for item, _reason in results]
                failures = [reason for _item, reason in results if reason is not None]

                if not failures:
                    enrichment_status = EnrichmentStatus.SUCCESS
                elif len(failures) == len(results):
                    enrichment_status = EnrichmentStatus.FAILED
                else:
                    enrichment_status = EnrichmentStatus.PARTIAL

                if enrichment_status in (EnrichmentStatus.PARTIAL, EnrichmentStatus.FAILED):
                    enrichment_warning = ENRICHMENT_INCOMPLETE_WARNING_VI
                    # Safe, aggregate-only logging -- never expose raw failure
                    # reasons/provider internals to the HTTP response.
                    logger.warning(
                        "AI Challenge enrichment_status=%s for case_id=%s: %d/%d item(s) "
                        "fell back to (or partially kept) deterministic text.",
                        enrichment_status.value, case_id, len(failures), len(results),
                    )

        return ChallengeSet(
            case_id=case_id,
            items=items,
            enrichment_status=enrichment_status,
            enrichment_warning=enrichment_warning,
            analyzer_warnings=analyzer_warnings,
        )

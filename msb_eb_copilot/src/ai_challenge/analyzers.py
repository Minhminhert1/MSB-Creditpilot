# -*- coding: utf-8 -*-
"""Module: ai_challenge.analyzers
Mô tả: Các bộ phân tích TẤT ĐỊNH (deterministic, KHÔNG qua LLM) sinh ra các
ChallengeItem có căn cứ dữ liệu canonical (CASES_DB) hoặc RenewalChangeSet.

Đây là lớp "Python tính toán / xác minh" trong kiến trúc "AI đề xuất, Python
kiểm soát": mọi con số trong observation/risk_hypothesis dưới đây được TÍNH
TRỰC TIẾP từ dữ liệu canonical -- KHÔNG có con số nào do AI tự sinh ra. Một
lớp LLM tùy chọn (xem engine.py) chỉ được phép diễn đạt lại văn phong, và bị
xác minh lại sau đó để đảm bảo không bịa thêm số liệu/kết luận phê duyệt.

Mỗi hàm analyze_* trả về List[ChallengeItem] cho một hạng mục (category).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from msb_eb_copilot.src.ai_challenge.models import (
    AnalyzerWarning,
    ChallengeCategory,
    ChallengeFactRef,
    ChallengeItem,
    ChallengeSeverity,
)
from msb_eb_copilot.src.mapping.financial_mapper import compute_canonical_ratios
from msb_eb_copilot.src.renewal.models import ChangeStatus, RenewalChangeSet

logger = logging.getLogger(__name__)

_MATERIALITY_THRESHOLD_PCT = 15.0  # % biến động tối thiểu để coi là "đáng chú ý"
_HIGH_SEVERITY_THRESHOLD_PCT = 40.0


def _pct_change(old: Optional[float], new: Optional[float]) -> Optional[float]:
    if old is None or new is None or old == 0:
        return None
    return (new - old) / abs(old) * 100.0


def _severity_from_pct(abs_pct: float) -> ChallengeSeverity:
    if abs_pct >= _HIGH_SEVERITY_THRESHOLD_PCT:
        return ChallengeSeverity.HIGH
    if abs_pct >= _MATERIALITY_THRESHOLD_PCT:
        return ChallengeSeverity.MEDIUM
    return ChallengeSeverity.LOW


def _latest_two(series: Optional[List[float]]):
    if not isinstance(series, list) or len(series) < 2:
        return None, None
    return series[-2], series[-1]


def analyze_financial(
    case_data: Dict[str, Any],
    warnings_out: Optional[List[AnalyzerWarning]] = None,
) -> List[ChallengeItem]:
    """FINANCIAL: xu hướng doanh thu, biên lợi nhuận, tồn kho, phải thu, nợ
    ngắn hạn, thanh khoản (current_ratio) -- mọi biến động YoY bất thường.

    warnings_out: danh sách rỗng do caller truyền vào (tùy chọn), được nối
    thêm (append) một AnalyzerWarning nếu một phép tính tất định TÙY CHỌN (vd
    current_ratio qua compute_canonical_ratios) thất bại -- Zero Silent
    Fallback: lỗi được ghi log an toàn và chỉ TÍN HIỆU đó bị bỏ qua (không bịa
    giá trị thay thế, không làm hỏng các phân tích khác trong hàm này)."""
    section_d = case_data.get("section_d") or {}
    years = section_d.get("years") or []
    latest_year = years[-1] if years else "kỳ gần nhất"
    source_label = f"BCTC {latest_year}"

    items: List[ChallengeItem] = []

    def _fact(canonical_field: str, value: Optional[float]) -> ChallengeFactRef:
        return ChallengeFactRef(
            canonical_path=f"section_d.{canonical_field}[{latest_year}]",
            value=f"{value:,.0f} triệu VND" if value is not None else "N/A",
            source=source_label,
        )

    # 1. Doanh thu tăng nhưng lợi nhuận sau thuế không tăng tương ứng (biên lợi nhuận).
    rev_old, rev_new = _latest_two(section_d.get("net_revenue"))
    np_old, np_new = _latest_two(section_d.get("net_profit_after_tax"))
    rev_pct = _pct_change(rev_old, rev_new)
    np_pct = _pct_change(np_old, np_new)
    if rev_pct is not None and np_pct is not None and rev_pct > 0 and np_pct < rev_pct - _MATERIALITY_THRESHOLD_PCT:
        items.append(ChallengeItem(
            id="fin_margin_decline",
            category=ChallengeCategory.FINANCIAL,
            severity=_severity_from_pct(abs(rev_pct - np_pct)),
            title="Biên lợi nhuận suy giảm",
            observation=f"Doanh thu thuần tăng {rev_pct:.1f}% nhưng lợi nhuận sau thuế "
                        f"{'giảm' if np_pct < 0 else 'chỉ tăng'} {abs(np_pct):.1f}% so với kỳ trước.",
            risk_hypothesis="Mức tăng doanh thu có thể chưa tương ứng với hiệu quả sinh lời -- "
                             "khả năng biên lợi nhuận đang chịu áp lực từ chi phí giá vốn hoặc chi phí vận hành.",
            question="Nguyên nhân chính dẫn tới sự chênh lệch giữa tăng trưởng doanh thu và "
                     "lợi nhuận sau thuế là gì?",
            facts_used=[_fact("net_revenue", rev_new), _fact("net_profit_after_tax", np_new)],
        ))

    # 2. Hàng tồn kho tăng mạnh so với kỳ trước.
    inv_old, inv_new = _latest_two(section_d.get("inventories"))
    inv_pct = _pct_change(inv_old, inv_new)
    if inv_pct is not None and inv_pct > _MATERIALITY_THRESHOLD_PCT:
        items.append(ChallengeItem(
            id="fin_inventory_growth",
            category=ChallengeCategory.FINANCIAL,
            severity=_severity_from_pct(inv_pct),
            title="Hàng tồn kho tăng nhanh",
            observation=f"Hàng tồn kho tăng {inv_pct:.1f}% so với kỳ trước.",
            risk_hypothesis="Mức tăng tồn kho có thể tạo thêm nhu cầu vốn lưu động nếu tốc độ "
                             "tiêu thụ không tăng tương ứng.",
            question="RM vui lòng làm rõ nguyên nhân tồn kho tăng và tỷ lệ hàng chậm luân chuyển (nếu có).",
            facts_used=[_fact("inventories", inv_new)],
        ))

    # 3. Phải thu tăng nhanh hơn doanh thu (dấu hiệu nới lỏng chính sách bán chịu).
    rec_old, rec_new = _latest_two(section_d.get("receivables"))
    rec_pct = _pct_change(rec_old, rec_new)
    if rec_pct is not None and rev_pct is not None and rec_pct > rev_pct + _MATERIALITY_THRESHOLD_PCT:
        items.append(ChallengeItem(
            id="fin_receivables_outpace_revenue",
            category=ChallengeCategory.FINANCIAL,
            severity=_severity_from_pct(rec_pct - rev_pct),
            title="Phải thu tăng nhanh hơn doanh thu",
            observation=f"Phải thu ngắn hạn tăng {rec_pct:.1f}% trong khi doanh thu chỉ tăng {rev_pct:.1f}%.",
            risk_hypothesis="Chênh lệch tốc độ tăng có thể phản ánh việc nới lỏng chính sách "
                             "bán chịu hoặc phát sinh nợ khó thu.",
            question="RM vui lòng làm rõ chính sách công nợ khách hàng và tuổi nợ phải thu hiện tại.",
            facts_used=[_fact("receivables", rec_new), _fact("net_revenue", rev_new)],
        ))

    # 4. Nợ ngắn hạn tăng mạnh (đòn bẩy).
    debt_old, debt_new = _latest_two(section_d.get("short_term_debt"))
    debt_pct = _pct_change(debt_old, debt_new)
    if debt_pct is not None and debt_pct > _MATERIALITY_THRESHOLD_PCT:
        items.append(ChallengeItem(
            id="fin_short_term_debt_growth",
            category=ChallengeCategory.FINANCIAL,
            severity=_severity_from_pct(debt_pct),
            title="Nợ vay ngắn hạn tăng",
            observation=f"Vay và nợ thuê tài chính ngắn hạn tăng {debt_pct:.1f}% so với kỳ trước.",
            risk_hypothesis="Đòn bẩy tài chính ngắn hạn tăng có thể ảnh hưởng khả năng thanh "
                             "khoản nếu dòng tiền kinh doanh không cải thiện tương ứng.",
            question="RM vui lòng làm rõ mục đích sử dụng khoản vay ngắn hạn tăng thêm và "
                     "kế hoạch trả nợ.",
            facts_used=[_fact("short_term_debt", debt_new)],
        ))

    # 5. Khả năng thanh toán hiện hành (current_ratio) suy giảm -- dùng đúng
    # công thức tính toán tất định hiện có (compute_canonical_ratios), KHÔNG
    # tự tính lại theo cách khác. Đây là một TÍN HIỆU TÙY CHỌN: nếu phép tính
    # thất bại, KHÔNG được làm hỏng toàn bộ AI Challenge -- chỉ tín hiệu này bị
    # bỏ qua, và lỗi phải được ghi log + báo cáo an toàn (KHÔNG bịa current_ratio).
    try:
        ratios = compute_canonical_ratios(section_d)
    except Exception:
        logger.exception(
            "compute_canonical_ratios failed for AI Challenge financial analyzer "
            "-- omitting the current_ratio signal only (no fabricated value)."
        )
        ratios = {}
        if warnings_out is not None:
            warnings_out.append(AnalyzerWarning(
                component="financial.current_ratio",
                code="DETERMINISTIC_CALCULATION_FAILED",
            ))
    cr_old, cr_new = _latest_two(ratios.get("current_ratio") if ratios else None)
    if cr_old is not None and cr_new is not None and cr_old > 0 and (cr_old - cr_new) / cr_old > 0.20:
        items.append(ChallengeItem(
            id="fin_current_ratio_decline",
            category=ChallengeCategory.FINANCIAL,
            severity=ChallengeSeverity.HIGH if cr_new < 1.0 else ChallengeSeverity.MEDIUM,
            title="Khả năng thanh toán hiện hành suy giảm",
            observation=f"Hệ số thanh toán hiện hành giảm từ {cr_old:.2f} xuống {cr_new:.2f} so với kỳ trước.",
            risk_hypothesis="Khả năng thanh khoản ngắn hạn có thể đang chịu áp lực.",
            question="RM vui lòng đánh giá nguyên nhân suy giảm khả năng thanh toán hiện hành.",
            facts_used=[ChallengeFactRef(
                canonical_path="section_d.ratios.current_ratio",
                value=f"{cr_new:.2f}",
                source=source_label,
            )],
        ))

    return items


def analyze_business(case_data: Dict[str, Any]) -> List[ChallengeItem]:
    """BUSINESS/OPERATING: tập trung khách hàng, tập trung nhà cung cấp."""
    section_c = case_data.get("section_c") or {}
    source_label = "Hồ sơ doanh nghiệp / Báo cáo thường niên"
    items: List[ChallengeItem] = []

    customers = section_c.get("customers") or []
    if customers:
        top = max(customers, key=lambda c: c.get("share", 0) or 0)
        share = top.get("share")
        if share is not None and share > 30.0:
            items.append(ChallengeItem(
                id="biz_customer_concentration",
                category=ChallengeCategory.BUSINESS,
                severity=ChallengeSeverity.HIGH if share > 50.0 else ChallengeSeverity.MEDIUM,
                title="Tập trung khách hàng đầu ra",
                observation=f"Khách hàng lớn nhất ({top.get('name', 'N/A')}) chiếm {share:.1f}% trong cơ cấu khách hàng.",
                risk_hypothesis="Mức độ tập trung này có thể tạo rủi ro phụ thuộc nếu khách hàng "
                                 "này thay đổi chính sách hợp tác hoặc gặp khó khăn tài chính.",
                question="RM vui lòng làm rõ tính ổn định của mối quan hệ với khách hàng này và "
                         "các điều khoản hợp đồng liên quan (thời hạn, khả năng thay thế).",
                facts_used=[ChallengeFactRef(
                    canonical_path="section_c.customers[0].share",
                    value=f"{share:.1f}%",
                    source=source_label,
                )],
            ))

    suppliers = section_c.get("suppliers") or []
    if suppliers:
        top_s = max(suppliers, key=lambda s: s.get("share", 0) or 0)
        s_share = top_s.get("share")
        if s_share is not None and s_share > 30.0:
            items.append(ChallengeItem(
                id="biz_supplier_concentration",
                category=ChallengeCategory.BUSINESS,
                severity=ChallengeSeverity.HIGH if s_share > 50.0 else ChallengeSeverity.MEDIUM,
                title="Tập trung nhà cung cấp đầu vào",
                observation=f"Nhà cung cấp lớn nhất ({top_s.get('name', 'N/A')}) chiếm {s_share:.1f}% cơ cấu nhập hàng.",
                risk_hypothesis="Phụ thuộc vào một nhà cung cấp chính có thể ảnh hưởng nguồn hàng "
                                 "nếu quan hệ hợp tác gián đoạn.",
                question="RM vui lòng làm rõ cơ chế hợp đồng/bảo vệ giá với nhà cung cấp này và "
                         "khả năng thay thế nếu cần.",
                facts_used=[ChallengeFactRef(
                    canonical_path="section_c.suppliers[0].share",
                    value=f"{s_share:.1f}%",
                    source=source_label,
                )],
            ))

    return items


def analyze_credit(case_data: Dict[str, Any]) -> List[ChallengeItem]:
    """CREDIT/CIC: hiển thị tình trạng CIC dưới dạng QUAN SÁT trung lập --
    KHÔNG được suy diễn Nhóm 1 CIC là an toàn tuyệt đối."""
    section_e = case_data.get("section_e") or {}
    history_status = section_e.get("history_status") or ""
    cic_date = section_e.get("cic_date") or "kỳ gần nhất"
    source_label = f"Báo cáo CIC {cic_date}"
    items: List[ChallengeItem] = []

    if history_status:
        is_group1 = "nhóm 1" in history_status.lower() or "nhom 1" in history_status.lower()
        risk_hypothesis = (
            "Lịch sử tín dụng tốt (Nhóm 1) không đồng nghĩa toàn bộ rủi ro tín dụng đã được "
            "loại trừ -- vẫn cần đối chiếu với các dấu hiệu tài chính/kinh doanh khác."
            if is_group1 else
            "Tình trạng nhóm nợ hiện tại có thể ảnh hưởng khả năng cấp/duy trì hạn mức tín dụng."
        )
        items.append(ChallengeItem(
            id="credit_cic_status_review",
            category=ChallengeCategory.CREDIT,
            severity=ChallengeSeverity.LOW if is_group1 else ChallengeSeverity.HIGH,
            title="Tình trạng lịch sử tín dụng (CIC)",
            observation=f"Báo cáo CIC ghi nhận: \"{history_status}\".",
            risk_hypothesis=risk_hypothesis,
            question="RM vui lòng xác nhận không có khoản vay/nghĩa vụ tín dụng nào khác chưa "
                     "được phản ánh trong báo cáo CIC nêu trên.",
            facts_used=[ChallengeFactRef(
                canonical_path="section_e.history_status",
                value=history_status,
                source=source_label,
            )],
        ))

    return items


def analyze_data_consistency(case_data: Dict[str, Any]) -> List[ChallengeItem]:
    """DATA_CONSISTENCY: mâu thuẫn số liệu nội bộ / thiếu dữ liệu nguồn."""
    section_d = case_data.get("section_d") or {}
    years = section_d.get("years") or []
    latest_year = years[-1] if years else "kỳ gần nhất"
    source_label = f"BCTC {latest_year}"
    items: List[ChallengeItem] = []

    total_assets = (section_d.get("total_assets") or [None])[-1] if section_d.get("total_assets") else None
    current_assets = (section_d.get("current_assets") or [None])[-1] if section_d.get("current_assets") else None
    if total_assets is not None and current_assets is not None and current_assets > total_assets:
        items.append(ChallengeItem(
            id="data_assets_inconsistent",
            category=ChallengeCategory.DATA_CONSISTENCY,
            severity=ChallengeSeverity.HIGH,
            title="Mâu thuẫn số liệu tài sản",
            observation=f"Tài sản ngắn hạn ({current_assets:,.0f} triệu VND) lớn hơn Tổng cộng "
                        f"tài sản ({total_assets:,.0f} triệu VND) -- về mặt kế toán là bất khả thi.",
            risk_hypothesis="Có thể tồn tại sai lệch trích xuất số liệu hoặc mâu thuẫn giữa các "
                             "tài liệu nguồn.",
            question="RM vui lòng đối chiếu lại số liệu Bảng cân đối kế toán gốc để xác nhận tính chính xác.",
            facts_used=[
                ChallengeFactRef(canonical_path="section_d.total_assets", value=f"{total_assets:,.0f} triệu VND", source=source_label),
                ChallengeFactRef(canonical_path="section_d.current_assets", value=f"{current_assets:,.0f} triệu VND", source=source_label),
            ],
        ))

    required_fields = ["net_revenue", "net_profit_after_tax", "total_assets", "equity"]
    missing = [f for f in required_fields if not section_d.get(f)]
    if missing:
        items.append(ChallengeItem(
            id="data_missing_financial_fields",
            category=ChallengeCategory.DATA_CONSISTENCY,
            severity=ChallengeSeverity.MEDIUM,
            title="Thiếu dữ liệu tài chính nguồn",
            observation=f"Các chỉ tiêu tài chính sau chưa có dữ liệu trong hồ sơ: {', '.join(missing)}.",
            risk_hypothesis="Hồ sơ có thể chưa đầy đủ tài liệu nguồn hoặc trích xuất chưa hoàn tất.",
            question="RM vui lòng bổ sung/xác nhận các chỉ tiêu tài chính còn thiếu nêu trên.",
            facts_used=[],
        ))

    return items


_RENEWAL_CATEGORY_BY_PREFIX = {
    "financial.": ChallengeCategory.FINANCIAL,
    "business.": ChallengeCategory.BUSINESS,
    "credit.": ChallengeCategory.CREDIT,
    "customer.": ChallengeCategory.DATA_CONSISTENCY,
}


def analyze_renewal_changes(change_set: RenewalChangeSet) -> List[ChallengeItem]:
    """RENEWAL-SPECIFIC: ưu tiên các thay đổi trọng yếu (CHANGED/CONFLICT/
    REMOVED) phát hiện được từ so sánh MB07 kỳ trước với dữ liệu mới."""
    items: List[ChallengeItem] = []

    for change_item in change_set.items:
        if change_item.status == ChangeStatus.UNCHANGED:
            continue

        category = ChallengeCategory.RENEWAL
        for prefix, cat in _RENEWAL_CATEGORY_BY_PREFIX.items():
            if change_item.canonical_path.startswith(prefix):
                category = ChallengeCategory.RENEWAL  # vẫn gắn nhãn RENEWAL để phân biệt nguồn gốc
                break

        facts_used = []
        if change_item.new_value is not None:
            facts_used.append(ChallengeFactRef(
                canonical_path=change_item.canonical_path,
                value=change_item.new_value,
                source=change_item.new_source or "Dữ liệu canonical hiện tại",
                page=change_item.new_page,
                evidence=change_item.new_evidence,
            ))

        if change_item.status == ChangeStatus.CONFLICT:
            items.append(ChallengeItem(
                id=f"renewal_conflict_{change_item.canonical_path}",
                category=category,
                severity=ChallengeSeverity.HIGH,
                title=f"Xung đột dữ liệu tái cấp: {change_item.label}",
                observation=f"'{change_item.label}' thay đổi bất thường: kỳ trước '{change_item.old_value}', "
                            f"hiện tại '{change_item.new_value}' -- chênh lệch vượt ngưỡng thông thường.",
                risk_hypothesis="Biến động lớn bất thường có thể phản ánh thay đổi thực chất trong hoạt "
                                 "động kinh doanh hoặc sai lệch dữ liệu -- cần RM xác minh trước khi áp dụng.",
                question=f"RM vui lòng xác nhận giá trị chính xác của '{change_item.label}' và lý do biến động.",
                facts_used=facts_used,
            ))
        elif change_item.status == ChangeStatus.CHANGED:
            items.append(ChallengeItem(
                id=f"renewal_changed_{change_item.canonical_path}",
                category=category,
                severity=ChallengeSeverity.MEDIUM,
                title=f"Thay đổi so với kỳ trước: {change_item.label}",
                observation=f"'{change_item.label}' thay đổi từ '{change_item.old_value}' (kỳ trước) "
                            f"sang '{change_item.new_value}' (hiện tại).",
                risk_hypothesis="Thay đổi này cần được RM xác nhận là phù hợp với thực tế hoạt động "
                                 "trước khi cập nhật vào tờ trình mới.",
                question=f"RM vui lòng xác nhận nguyên nhân thay đổi của '{change_item.label}'.",
                facts_used=facts_used,
            ))
        elif change_item.status == ChangeStatus.REMOVED:
            items.append(ChallengeItem(
                id=f"renewal_removed_{change_item.canonical_path}",
                category=ChallengeCategory.DATA_CONSISTENCY,
                severity=ChallengeSeverity.MEDIUM,
                title=f"Thông tin không còn trong hồ sơ mới: {change_item.label}",
                observation=f"'{change_item.label}' có trong hồ sơ kỳ trước ('{change_item.old_value}') "
                            f"nhưng không xuất hiện trong dữ liệu mới.",
                risk_hypothesis="Có thể do tài liệu mới chưa đề cập lại, hoặc thông tin thực sự không "
                                 "còn hiệu lực -- KHÔNG được tự động xóa khỏi hồ sơ.",
                question=f"RM vui lòng xác nhận '{change_item.label}' còn hiệu lực hay cần cập nhật lại.",
                facts_used=[],
            ))

    return items

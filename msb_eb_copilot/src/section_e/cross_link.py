"""Module: cross_link.py
Mô tả: Bộ liên kết chéo dữ liệu chuẩn (Cross-Section Data Linking) giữa Phần E với Phần A và Phần D.
Nguyên tắc: ONE BUSINESS FACT = ONE CANONICAL INPUT = MANY OUTPUT BINDINGS
"""

from decimal import Decimal
from typing import Any, Optional
from .models import SectionEData


def link_section_e_to_session_a(section_e_data: SectionEData, session_a: Any):
    """Tự động đẩy dữ liệu Dư nợ MSB từ Phần E sang Phiên làm việc Phần A (SectionAReviewSession)."""
    # 1. Dư nợ cho vay tại MSB (Quy đổi sang Decimal để đảm bảo độ chính xác tài chính)
    loan_msb = Decimal(str(round(section_e_data.loan_outstanding_at_msb_million, 2)))
    session_a.link_cross_section_fact(
        canonical_key="credit_relation.loan_outstanding_at_msb",
        value=loan_msb,
        unit="triệu đồng"
    )

    # 2. Tổng dư tín dụng tại MSB
    total_msb = Decimal(str(round(section_e_data.total_credit_exposure_at_msb_million, 2)))
    session_a.link_cross_section_fact(
        canonical_key="credit_relation.total_credit_exposure_at_msb",
        value=total_msb,
        unit="triệu đồng"
    )


def get_other_debt_for_section_d(section_e_data: SectionEData) -> Optional[float]:
    """Lấy tổng nợ vay tại các TCTD khác (quy đổi VND) để cung cấp cho Engine tính Nhu cầu VLĐ MB09 của Phần D.
    
    Nếu tổng nợ TCTD khác chưa hoàn chỉnh (ví dụ có nợ ngoại tệ chưa quy đổi VND),
    bắt buộc trả về None để cảnh báo dữ liệu chưa hoàn tất, tuyệt đối không trả về số liệu cộng dồn cục bộ.
    """
    other_debt_million = section_e_data.total_debt_other_banks_excluding_msb
    if other_debt_million is None:
        return None
    return float(other_debt_million * 1_000_000.0)

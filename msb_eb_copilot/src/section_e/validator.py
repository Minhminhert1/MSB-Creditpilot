"""Module: validator.py
Mô tả: Bộ thẩm định nợ xấu và uy tín quan hệ tín dụng theo quy chuẩn CIC & QĐ.RR.074.
"""

from dataclasses import dataclass, field
from typing import List

from .enums import DebtGroup
from .models import SectionEData


@dataclass
class SectionEValidationResult:
    is_valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    has_bad_debt: bool = False                   # Nợ xấu (Nhóm 3, 4, 5)
    has_special_mention_debt: bool = False       # Nợ cần chú ý (Nhóm 2)


class SectionEValidator:
    """Thẩm định quan hệ tín dụng và lịch sử CIC."""

    @classmethod
    def validate(cls, data: SectionEData) -> SectionEValidationResult:
        errors = []
        warnings = []
        has_bad_debt = False
        has_special_mention_debt = False

        # 1. Rà soát nhóm nợ từng TCTD
        for r in data.relations:
            if r.debt_group in (DebtGroup.NHOM_3_DUOI_TIEU_CHUAN, DebtGroup.NHOM_4_NGHI_NGO, DebtGroup.NHOM_5_CO_KHA_NANG_MAT_VON):
                has_bad_debt = True
                errors.append(
                    f"CẢNH BÁO NỢ XẤU: Khách hàng có nợ Nhóm {r.debt_group.value} tại '{r.bank_name}'. "
                    f"Vi phạm điều kiện tiên quyết cấp tín dụng theo QĐ.RR.074!"
                )
            elif r.debt_group == DebtGroup.NHOM_2_CAN_CHU_Y:
                has_special_mention_debt = True
                warnings.append(
                    f"CẢNH BÁO NỢ CẦN CHÚ Ý: Khách hàng có nợ Nhóm 2 tại '{r.bank_name}'. "
                    f"Yêu cầu RM giải trình nguyên nhân và bằng chứng khắc phục."
                )

        # 2. Kiểm tra lịch sử quá hạn 12 tháng
        if data.is_overdue_12m is True and not data.overdue_explanation.strip():
            errors.append("Khách hàng có phát sinh nợ quá hạn trong 12 tháng qua nhưng chưa có biên bản giải trình của RM.")
        elif data.is_overdue_12m is None:
            warnings.append("Chưa xác định được trạng thái quá hạn 12 tháng từ Báo cáo CIC (cần RM rà soát xác nhận).")

        # 3. Kiểm tra tính hợp lý của số liệu dư nợ
        for r in data.relations:
            if r.total_debt_million is None:
                warnings.append(f"Dư nợ tại '{r.bank_name}' chưa thể tính tổng hoàn chỉnh do có khoản nợ ngoại tệ chưa quy đổi hoặc thiếu số liệu thành phần.")
            else:
                expected_sum = (r.short_term_debt_vnd_million or 0.0) + (r.short_term_debt_usd_million or 0.0) + (r.medium_long_term_debt_million or 0.0)
                if abs(r.total_debt_million - expected_sum) > 1.0:
                    warnings.append(f"Dư nợ tại '{r.bank_name}' có chênh lệch giữa tổng số ({r.total_debt_million:,.1f}) và chi tiết các kỳ hạn ({expected_sum:,.1f}).")

        is_valid = len(errors) == 0
        return SectionEValidationResult(
            is_valid=is_valid,
            errors=errors,
            warnings=warnings,
            has_bad_debt=has_bad_debt,
            has_special_mention_debt=has_special_mention_debt
        )

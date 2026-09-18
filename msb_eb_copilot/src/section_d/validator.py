"""Module: validator.py
Mô tả: Bộ kiểm định tính toàn vẹn và các chỉ số an toàn tài chính cho Phần D.
"""

from dataclasses import dataclass, field
from typing import List

from .models import SectionDData


@dataclass
class SectionDValidationResult:
    is_valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


class SectionDValidator:
    """Bộ kiểm định Báo cáo tài chính & Tỷ lệ an toàn Phần D."""

    @classmethod
    def validate(cls, data: SectionDData) -> SectionDValidationResult:
        errors = []
        warnings = []

        # 1. Kiểm tra tính đồng nhất về số năm giữa các báo cáo
        n_years = len(data.income_statement.years)
        if len(data.balance_sheet.years) != n_years or len(data.cash_flow.years) != n_years or len(data.ratios.years) != n_years:
            errors.append(f"Không đồng nhất số năm giữa P&L ({n_years}), CĐKT ({len(data.balance_sheet.years)}) và Lưu chuyển tiền ({len(data.cash_flow.years)}).")

        # 2. Kiểm tra tính cân đối của Bảng cân đối kế toán (Tổng tài sản = Nợ phải trả + Vốn CSH)
        bs = data.balance_sheet
        for idx, yr in enumerate(bs.years):
            ta = bs.total_assets[idx]
            tl = bs.liabilities[idx]
            eq = bs.owner_equity[idx]
            diff = abs(ta - (tl + eq))
            # Sai số cho phép tối đa 5 triệu đồng do làm tròn số liệu công bố
            if diff > 5.0:
                errors.append(f"Bảng CĐKT năm {yr} không cân đối: Tổng tài sản ({ta:,.1f}) != Tổng nguồn vốn ({tl + eq:,.1f}), chênh lệch {diff:,.1f} triệu đồng.")

        # 3. Kiểm tra ý kiến kiểm toán
        gov = data.governance
        bad_audit_kw = ["từ chối", "ngoại trừ trọng yếu", "không thể thu thập", "nghi ngờ khả năng hoạt động liên tục"]
        if any(kw in gov.audit_opinion.lower() for kw in bad_audit_kw):
            warnings.append(f"Ý KIẾN KIỂM TOÁN CÓ NGOẠI TRỪ/RỦI RO: '{gov.audit_opinion}'. Cần có giải trình chi tiết của RM.")

        # 4. Kiểm tra các chỉ số an toàn tài chính năm gần nhất
        if data.ratios.current_ratio:
            latest_cr = data.ratios.current_ratio[-1]
            if latest_cr < 1.0:
                warnings.append(f"Chỉ số thanh toán hiện hành năm gần nhất ở mức thấp ({latest_cr:.2f} lần < 1.0 lần), tiềm ẩn rủi ro thanh khoản ngắn hạn.")

        if data.ratios.debt_to_equity:
            latest_de = data.ratios.debt_to_equity[-1]
            if latest_de > 5.0:
                warnings.append(f"Đòn bẩy tài chính Nợ/VCSH năm gần nhất rất cao ({latest_de:.2f} lần > 5.0 lần). Cần kiểm soát chặt chẽ nghĩa vụ trả nợ.")

        if data.ratios.dscr_icr:
            latest_icr = data.ratios.dscr_icr[-1]
            if latest_icr < 1.0:
                warnings.append(f"Hệ số chi trả lãi vay DSCR/ICR ({latest_icr:.2f} lần < 1.0 lần) cho thấy lợi nhuận không đủ bù đắp chi phí lãi vay.")

        is_valid = len(errors) == 0
        return SectionDValidationResult(
            is_valid=is_valid,
            errors=errors,
            warnings=warnings
        )

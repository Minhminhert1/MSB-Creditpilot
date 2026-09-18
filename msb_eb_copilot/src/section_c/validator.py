"""Module: validator.py
Mô tả: Bộ kiểm định nghiệp vụ ngân hàng cho Phần C (Theo QĐ.RR.074 và chuẩn MB07 MSB).
"""

from dataclasses import dataclass, field
from typing import List

from .enums import BlacklistStatus, ConcentrationRiskLevel
from .models import SectionCData


@dataclass
class SectionCValidationResult:
    is_valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    concentration_risks: List[ConcentrationRiskLevel] = field(default_factory=list)


class SectionCValidator:
    """Bộ thẩm định tính hợp lệ và cảnh báo rủi ro Phần C."""

    @classmethod
    def validate(cls, data: SectionCData) -> SectionCValidationResult:
        errors = []
        warnings = []
        risks = []

        # 1. Kiểm tra Blacklist & Điều 126 Luật TCTD (Chặn nghiêm ngặt)
        if data.blacklist_status == BlacklistStatus.THUOC_BLACKLIST:
            errors.append("KHÁCH HÀNG HOẶC NGƯỜI LIÊN QUAN THUỘC BLACKLIST/VI PHẠM ĐIỀU 126 LUẬT TCTD: CẤM CẤP TÍN DỤNG.")

        # 2. Kiểm tra tổng tỷ trọng sở hữu cổ đông
        total_ownership = sum(sh.ownership_percentage for sh in data.major_shareholders)
        if total_ownership > 100.05:
            errors.append(f"Tổng tỷ lệ sở hữu của các cổ đông vượt quá 100%: {total_ownership:.2f}%.")

        # 3. Kiểm tra cơ cấu sản phẩm
        total_prod_share = sum(p.revenue_share_percentage for p in data.products)
        if total_prod_share > 100.05:
            errors.append(f"Tổng tỷ trọng doanh thu của các sản phẩm vượt quá 100%: {total_prod_share:.2f}%.")

        # 4. Kiểm định rủi ro tập trung Nhà cung cấp (QĐ.RR.074: >= 40% chi phí mua hàng)
        for s in data.suppliers:
            if s.purchase_share_percentage >= 40.0:
                risks.append(ConcentrationRiskLevel.CANH_BAO_TAP_TRUNG_NCC)
                warnings.append(
                    f"RỦI RO TẬP TRUNG ĐẦU VÀO: Nhà cung cấp '{s.supplier_name}' chiếm {s.purchase_share_percentage:.1f}% "
                    f"(ngưỡng cảnh báo >= 40%). RM phải có giải trình phương án dự phòng nguồn cung."
                )

        # 5. Kiểm định rủi ro tập trung Khách hàng đầu ra (QĐ.RR.074: >= 30% doanh thu)
        for c in data.customers:
            if c.revenue_share_percentage >= 30.0:
                risks.append(ConcentrationRiskLevel.CANH_BAO_TAP_TRUNG_KH)
                warnings.append(
                    f"RỦI RO TẬP TRUNG ĐẦU RA: Khách hàng '{c.customer_name}' chiếm {c.revenue_share_percentage:.1f}% "
                    f"(ngưỡng cảnh báo >= 30%). RM phải yêu cầu biện pháp kiểm soát công nợ / bảo lãnh thanh toán."
                )

        # 6. Kiểm tra bắt buộc phải có nhận xét của RM nếu có rủi ro tập trung
        if risks and not data.rm_supply_chain_assessment.strip():
            warnings.append("Hồ sơ phát sinh rủi ro tập trung chuỗi cung ứng nhưng chưa có nhận xét giải trình của RM.")

        is_valid = len(errors) == 0
        return SectionCValidationResult(
            is_valid=is_valid,
            errors=errors,
            warnings=warnings,
            concentration_risks=list(set(risks))
        )

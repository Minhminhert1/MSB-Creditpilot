"""
Module: prescreen_engine.py
Mô tả: Engine rà soát 6 Điều kiện Tiền sàng lọc (Pre-screening) & Điều kiện KTSBĐ theo QĐ.RR.074 của MSB.
"""

from dataclasses import dataclass
from typing import Dict, List, Any


@dataclass
class EnterpriseProfile:
    customer_name: str
    tax_code: str
    industry: str
    years_in_operation: float
    equity_vnd: float                 # Vốn chủ sở hữu (VND)
    revenue_t_minus_1: float          # Doanh thu năm T-1 (VND)
    net_profit_t_minus_1: float       # Lợi nhuận sau thuế năm T-1 (VND)
    net_profit_t_minus_2: float       # Lợi nhuận sau thuế năm T-2 (VND)
    has_bad_debt_cic_24m: bool        # Có nợ nhóm 2-5 tại CIC trong 24 tháng gần nhất?
    is_restructured_debt: bool        # Có nợ cơ cấu lại thời hạn trả nợ?
    is_special_monitoring: bool       # Nằm trong danh sách giám sát đặc biệt / cấm cấp tín dụng?
    
    # Chỉ số đòn bẩy & thanh khoản
    debt_to_equity: float             # Nợ phải trả / Vốn CSH
    current_ratio: float              # Khả năng thanh toán hiện hành (Tài sản ngắn hạn / Nợ ngắn hạn)
    requested_unsecured_limit: float = 0.0 # Hạn mức Không tài sản bảo đảm (KTSBĐ) đề xuất


class PrescreenEngine:
    """Rà soát quy chuẩn rủi ro tín dụng QĐ.RR.074."""

    @classmethod
    def evaluate_pre_screening(cls, profile: EnterpriseProfile) -> Dict[str, Any]:
        checks = []
        hard_failures = 0
        warnings = 0
        
        # 1. Kiểm tra Lịch sử tín dụng CIC (Hard rule)
        c1_passed = not profile.has_bad_debt_cic_24m and not profile.is_restructured_debt
        checks.append({
            "code": "C1_CIC",
            "name": "Lịch sử tín dụng CIC & Cơ cấu nợ",
            "requirement": "Không có nợ nhóm 2-5 tại MSB & TCTD khác trong 24 tháng; không có nợ cơ cấu",
            "actual": "Nợ chuẩn nhóm 1" if c1_passed else "Có phát sinh nợ nhóm 2-5 hoặc cơ cấu nợ",
            "passed": c1_passed,
            "is_hard_rule": True
        })
        if not c1_passed: hard_failures += 1
        
        # 2. Kiểm tra Danh sách Hạn chế / Giám sát đặc biệt (Hard rule)
        c2_passed = not profile.is_special_monitoring
        checks.append({
            "code": "C2_LIST",
            "name": "Danh mục cấm / Giám sát đặc biệt MSB",
            "requirement": "Không thuộc danh sách từ chối / hạn chế cấp tín dụng của MSB",
            "actual": "Đạt chuẩn" if c2_passed else "Nằm trong danh sách cảnh báo",
            "passed": c2_passed,
            "is_hard_rule": True
        })
        if not c2_passed: hard_failures += 1

        # 3. Thời gian hoạt động (Quy định: >= 3 năm hoặc tối thiểu 2 năm với ngành ưu tiên)
        c3_passed = profile.years_in_operation >= 2.0
        checks.append({
            "code": "C3_AGE",
            "name": "Thời gian hoạt động liên tục",
            "requirement": "Doanh nghiệp hoạt động liên tục tối thiểu >= 2 năm trong ngành",
            "actual": f"{profile.years_in_operation:.1f} năm",
            "passed": c3_passed,
            "is_hard_rule": True
        })
        if not c3_passed: hard_failures += 1

        # 4. Quy mô Doanh thu thuần (Quy định KHDN lớn: Doanh thu năm gần nhất >= 200 tỷ VND)
        revenue_threshold = 200_000_000_000 # 200 tỷ
        c4_passed = profile.revenue_t_minus_1 >= revenue_threshold
        checks.append({
            "code": "C4_REV",
            "name": "Quy mô Doanh thu thuần KHDN Lớn",
            "requirement": "Doanh thu năm gần nhất tối thiểu >= 200 tỷ VND",
            "actual": f"{profile.revenue_t_minus_1 / 1e9:,.1f} tỷ VND",
            "passed": c4_passed,
            "is_hard_rule": False
        })
        if not c4_passed: warnings += 1

        # 5. Kết quả kinh doanh & Vốn CSH (Không lỗ 2 năm liên tiếp, Vốn CSH > 0)
        c5_passed = (profile.net_profit_t_minus_1 > 0 or profile.net_profit_t_minus_2 > 0) and profile.equity_vnd > 0
        checks.append({
            "code": "C5_PROFIT",
            "name": "Kết quả kinh doanh & Vốn CSH",
            "requirement": "Không lỗ lũy kế 2 năm gần nhất; Vốn chủ sở hữu dương (> 0)",
            "actual": f"Vốn CSH: {profile.equity_vnd / 1e9:,.1f} tỷ | LN T-1: {profile.net_profit_t_minus_1 / 1e9:,.1f} tỷ",
            "passed": c5_passed,
            "is_hard_rule": True
        })
        if not c5_passed: hard_failures += 1

        # 6. Đòn bẩy tài chính (Hệ số Nợ / Vốn CSH thông thường <= 3.0x - 4.0x)
        c6_passed = profile.debt_to_equity <= 3.5
        checks.append({
            "code": "C6_LEVERAGE",
            "name": "Hệ số Đòn bẩy (Nợ phải trả / Vốn CSH)",
            "requirement": "Hệ số Nợ/Vốn CSH <= 3.5x (hoặc giải trình nếu đặc thù thương mại)",
            "actual": f"{profile.debt_to_equity:.2f}x",
            "passed": c6_passed,
            "is_hard_rule": False
        })
        if not c6_passed: warnings += 1

        # Đánh giá điều kiện KTSBĐ (Không tài sản bảo đảm) nếu có đề xuất
        ktsbd_eligible = False
        ktsbd_notes = "Không đề xuất KTSBĐ"
        if profile.requested_unsecured_limit > 0:
            if profile.equity_vnd >= 100_000_000_000 and profile.net_profit_t_minus_1 > 0 and profile.current_ratio >= 1.1:
                ktsbd_eligible = True
                ktsbd_notes = "Đủ điều kiện xem xét KTSBĐ (Vốn CSH > 100 tỷ, có lãi, thanh khoản tốt)"
            else:
                ktsbd_eligible = False
                ktsbd_notes = "Chưa thỏa mãn tiêu chí cấp KTSBĐ chuẩn theo QĐ.074, cần phê duyệt ngoại lệ cấp thẩm quyền"

        overall_status = "PASS" if hard_failures == 0 else "FAIL"
        if hard_failures == 0 and warnings > 0:
            overall_status = "PASS_WITH_CONDITIONS"

        return {
            "overall_status": overall_status,
            "hard_failures": hard_failures,
            "warnings": warnings,
            "checks": checks,
            "ktsbd_eligible": ktsbd_eligible,
            "ktsbd_notes": ktsbd_notes
        }

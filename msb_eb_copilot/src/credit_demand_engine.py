"""
Module: credit_demand_engine.py
Mô tả: Engine tính toán Nhu cầu Tín dụng (Vay VLĐ, L/C, Bảo lãnh) theo chuẩn mẫu biểu MB09 của MSB.
"""

from dataclasses import dataclass
from typing import Dict, Any, Optional


@dataclass
class FinancialInput:
    # 1. Kế hoạch kinh doanh
    net_revenue_plan: float         # Doanh thu thuần kế hoạch (VND)
    cogs_plan: float                # Giá vốn hàng bán kế hoạch (VND)
    operating_cost_plan: float      # Chi phí hoạt động kế hoạch (VND)
    
    # 2. Chu kỳ kinh doanh (ngày)
    dio: float                      # Vòng quay tồn kho (ngày)
    dso: float                      # Vòng quay phải thu (ngày)
    dpo: float                      # Vòng quay phải trả người bán (ngày)
    
    # 3. Nguồn vốn tham gia
    equity_participation: float              # Vốn tự có, vốn huy động khác tham gia (VND)
    other_debt: Optional[float] = 0.0        # Vay nợ TCTD khác (VND, None nếu incomplete/chưa đủ điều kiện)
    
    # 4. Giả định L/C và Bảo lãnh
    import_ratio: float = 0.40      # Tỷ lệ nhập khẩu / Tổng giá vốn (40%)
    lc_tenor_days: int = 90         # Kỳ hạn L/C bình quân (90 ngày)
    guarantee_ratio: float = 0.15   # Tỷ lệ doanh thu cần bảo lãnh thực hiện HĐ / bảo lãnh thanh toán (15%)
    guarantee_tenor_days: int = 180 # Kỳ hạn bảo lãnh bình quân (180 ngày)


class CreditDemandEngine:
    """Engine tính toán Nhu cầu Vốn lưu động & Hạn mức Tín dụng theo MB09."""

    @staticmethod
    def calculate_working_capital_cycle(dio: float, dso: float, dpo: float) -> Dict[str, float]:
        """Tính chu kỳ ngân quỹ (Cash Conversion Cycle / Vòng quay VLĐ)."""
        ccc_days = dio + dso - dpo
        # Số vòng quay VLĐ trong năm = 360 / Chu kỳ ngân quỹ
        turns_per_year = max(round(360.0 / max(ccc_days, 1.0), 2), 0.5)
        return {
            "ccc_days": round(ccc_days, 1),
            "turns_per_year": turns_per_year
        }

    @classmethod
    def calculate_credit_limits(cls, inp: FinancialInput) -> Dict[str, Any]:
        """Tính toán tổng thể các hạn mức tín dụng theo MB09."""
        # 1. Tổng chi phí SXKD cần thiết trong năm
        total_operating_expense = inp.cogs_plan + inp.operating_cost_plan
        
        # 2. Chu kỳ kinh doanh & Vòng quay vốn
        cycle = cls.calculate_working_capital_cycle(inp.dio, inp.dso, inp.dpo)
        turns = cycle["turns_per_year"]
        
        # 3. Nhu cầu vốn lưu động bình quân = Tổng chi phí / Vòng quay VLĐ
        working_capital_demand = total_operating_expense / turns
        
        # 4. Nhu cầu Vốn lưu động Ròng (sau khi trừ vốn tự có)
        net_working_capital_demand = max(0.0, working_capital_demand - inp.equity_participation)
        
        # 5. Hạn mức Cho vay Ngắn hạn đề xuất (đã trừ vay TCTD khác nếu tính hạn mức tại MSB)
        loan_limit_total = net_working_capital_demand
        if inp.other_debt is None:
            loan_limit_msb = None
            total_credit_facility_msb = None
        else:
            loan_limit_msb = max(0.0, loan_limit_total - inp.other_debt)
        
        # 6. Hạn mức L/C (Mở Thư tín dụng nhập khẩu / nội địa)
        # Nhu cầu mở L/C trong năm = Giá vốn * Tỷ lệ nhập hàng qua L/C
        lc_annual_volume = inp.cogs_plan * inp.import_ratio
        # Hạn mức L/C = Doanh số L/C năm * (Kỳ hạn L/C bình quân / 360)
        lc_limit = lc_annual_volume * (inp.lc_tenor_days / 360.0)
        
        # 7. Hạn mức Bảo lãnh (Thực hiện HĐ, Tạm ứng, Thanh toán)
        guarantee_annual_volume = inp.net_revenue_plan * inp.guarantee_ratio
        guarantee_limit = guarantee_annual_volume * (inp.guarantee_tenor_days / 360.0)
        
        # 8. Tổng hạn mức Cấp tín dụng đề xuất
        if loan_limit_msb is not None:
            total_credit_facility_msb = loan_limit_msb + lc_limit + guarantee_limit
        else:
            total_credit_facility_msb = None
        
        return {
            "total_operating_expense": total_operating_expense,
            "ccc_days": cycle["ccc_days"],
            "turns_per_year": turns,
            "working_capital_demand": working_capital_demand,
            "net_working_capital_demand": net_working_capital_demand,
            "loan_limit_total": loan_limit_total,
            "loan_limit_msb": loan_limit_msb,
            "lc_annual_volume": lc_annual_volume,
            "lc_limit": lc_limit,
            "guarantee_annual_volume": guarantee_annual_volume,
            "guarantee_limit": guarantee_limit,
            "total_credit_facility_msb": total_credit_facility_msb
        }

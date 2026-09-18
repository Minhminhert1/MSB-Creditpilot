"""
Module: rorwa_engine.py
Mô tả: Engine mô phỏng Lợi nhuận điều chỉnh theo Rủi ro vốn (RORWA & TORWA) theo chuẩn Basel II của MSB.
"""

from dataclasses import dataclass
from typing import Dict, Any


@dataclass
class DealStructure:
    # 1. Hạn mức & Tỷ lệ giải ngân
    loan_limit: float               # Hạn mức Cho vay (VND)
    lc_limit: float                 # Hạn mức L/C (VND)
    guarantee_limit: float          # Hạn mức Bảo lãnh (VND)
    
    loan_drawdown_rate: float = 0.70 # Tỷ lệ sử dụng hạn mức vay (70%)
    lc_drawdown_rate: float = 0.50   # Tỷ lệ sử dụng hạn mức L/C (50%)
    guarantee_drawdown_rate: float = 0.40 # Tỷ lệ sử dụng bảo lãnh (40%)
    
    # 2. Định giá Lãi & Phí (Pricing)
    loan_interest_rate: float = 0.080 # Lãi suất cho vay (%/năm, ví dụ 8.0%)
    ftp_cost_rate: float = 0.055      # Chi phí vốn FTP (%/năm, ví dụ 5.5%) -> NIM = 2.5%
    lc_fee_rate: float = 0.012        # Phí mở L/C (%/năm, ví dụ 1.2%)
    guarantee_fee_rate: float = 0.015 # Phí bảo lãnh (%/năm, ví dụ 1.5%)
    
    # 3. Huy động & Bán chéo (Cross-sell)
    casa_avg_balance: float = 20_000_000_000 # Số dư CASA bình quân (VND, ví dụ 20 tỷ)
    casa_ftp_benefit_rate: float = 0.035     # Lợi nhuận từ nguồn vốn CASA rẻ (%/năm, ví dụ 3.5%)
    fx_other_fee_income: float = 200_000_000  # Thu phí ngoại hối FX, thu phí thanh toán (VND/năm)
    
    # 4. Trọng số rủi ro Basel II (Risk Weights - RW & CCF)
    loan_rw: float = 1.00          # Hệ số rủi ro cho vay DN chuẩn (100%)
    lc_ccf: float = 0.20           # Hệ số chuyển đổi ngoại bảng L/C (20%)
    guarantee_ccf: float = 0.50    # Hệ số chuyển đổi bảo lãnh (50%)
    
    # 5. Chi phí phân bổ nội bộ (Cost of Capital & Opex)
    opex_ratio: float = 0.008      # Tỷ lệ chi phí vận hành phân bổ (0.8% trên dư nợ)
    expected_loss_rate: float = 0.003 # Tỷ lệ trích lập dự phòng tổn thất kỳ vọng EL (0.3%)
    capital_allocation_rate: float = 0.08 # Tỷ lệ an toàn vốn CAR tối thiểu (8.0%)


class RorwaEngine:
    """Engine tính toán TORWA & RORWA chuẩn Basel II của MSB."""

    @classmethod
    def calculate_deal_profitability(cls, deal: DealStructure) -> Dict[str, Any]:
        # A. Dư nợ & Cam kết bình quân
        avg_loan = deal.loan_limit * deal.loan_drawdown_rate
        avg_lc = deal.lc_limit * deal.lc_drawdown_rate
        avg_guarantee = deal.guarantee_limit * deal.guarantee_drawdown_rate
        
        # B. Tính toán RWA (Tài sản có rủi ro quy đổi)
        rwa_loan = avg_loan * deal.loan_rw
        rwa_lc = avg_lc * deal.lc_ccf * deal.loan_rw
        rwa_guarantee = avg_guarantee * deal.guarantee_ccf * deal.loan_rw
        total_rwa = rwa_loan + rwa_lc + rwa_guarantee
        
        # C. Doanh thu thuần (Income)
        # 1. Thu nhập lãi thuần NII từ cho vay
        nii_loan = avg_loan * (deal.loan_interest_rate - deal.ftp_cost_rate)
        # 2. Thu nhập từ nguồn vốn CASA (CASA benefit)
        nii_casa = deal.casa_avg_balance * deal.casa_ftp_benefit_rate
        total_nii = nii_loan + nii_casa
        
        # 3. Thu nhập ngoài lãi (Non-NII: Phí L/C, Phí BL, Phí FX)
        fee_lc = avg_lc * deal.lc_fee_rate
        fee_guarantee = avg_guarantee * deal.guarantee_fee_rate
        total_non_nii = fee_lc + fee_guarantee + deal.fx_other_fee_income
        
        # 4. Tổng thu nhập hoạt động (Total Operating Income - TOI)
        total_income = total_nii + total_non_nii
        
        # D. Chi phí (Expenses & Provisions)
        opex = avg_loan * deal.opex_ratio
        credit_cost_el = avg_loan * deal.expected_loss_rate
        
        # E. Lợi nhuận trước thuế phân bổ (PBT)
        net_deal_profit = total_income - opex - credit_cost_el
        
        # F. Chỉ số Hiệu quả Vốn Rủi ro (TORWA & RORWA)
        # TORWA = Total Operating Income / Total RWA (Chuẩn MSB: >= 1.5%)
        torwa = (total_income / max(total_rwa, 1.0)) * 100.0
        
        # RORWA = Net Profit After Cost / Total RWA (Chuẩn MSB: >= 0.5%)
        rorwa = (net_deal_profit / max(total_rwa, 1.0)) * 100.0
        
        # Trạng thái đạt chuẩn MSB
        torwa_passed = torwa >= 1.50
        rorwa_passed = rorwa >= 0.50
        
        return {
            "avg_loan": avg_loan,
            "avg_lc": avg_lc,
            "avg_guarantee": avg_guarantee,
            "total_rwa": total_rwa,
            "nii_loan": nii_loan,
            "nii_casa": nii_casa,
            "total_nii": total_nii,
            "fee_lc": fee_lc,
            "fee_guarantee": fee_guarantee,
            "total_non_nii": total_non_nii,
            "total_income": total_income,
            "opex": opex,
            "credit_cost_el": credit_cost_el,
            "net_deal_profit": net_deal_profit,
            "torwa": round(torwa, 2),
            "rorwa": round(rorwa, 2),
            "torwa_passed": torwa_passed,
            "rorwa_passed": rorwa_passed
        }

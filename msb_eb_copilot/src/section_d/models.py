"""Mô hình dữ liệu chuẩn (Canonical Models) cho Phần D - Tài chính doanh nghiệp."""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any


@dataclass
class AccountingGovernance:
    """Quản trị kế toán & kiểm toán theo chuẩn MB07."""
    mandatory_audit_by_law: str = "Có (Đối tượng bắt buộc kiểm toán theo luật)"
    audit_firm_name: str = "Công ty TNHH Kiểm toán độc lập"
    audited_years: str = "2022, 2023, 2024"
    audit_opinion: str = "Chấp thuận toàn phần (Ý kiến không có ngoại trừ)"
    accounting_software: str = "Hệ thống ERP / Phần mềm kế toán chuẩn"
    finance_team_structure: str = "Ban Tài chính Kế toán do Kế toán trưởng điều hành"
    internal_financial_regulations: str = "Tuân thủ Chuẩn mực Kế toán Việt Nam (VAS)"


@dataclass
class IncomeStatement3Y:
    """Báo cáo Kết quả hoạt động kinh doanh (P&L) 3 năm."""
    years: List[str]
    net_revenue: List[float]
    cogs: List[float]
    gross_profit: List[float]
    gross_profit_margin_pct: List[float]
    financial_income: List[float]
    financial_expenses: List[float]
    interest_expenses: List[float]
    sga_expenses: List[float]
    net_profit_before_tax: List[float]
    net_profit_after_tax: List[float]


@dataclass
class PnLAnalysis:
    """Nhận xét đánh giá chuyên sâu của RM về P&L."""
    revenue_analysis: str = ""
    cogs_and_production_cost_analysis: str = ""
    gross_margin_analysis: str = ""
    financial_income_and_expenses_analysis: str = ""
    sga_expenses_analysis: str = ""
    net_profit_and_dividends_analysis: str = ""


@dataclass
class BalanceSheet3Y:
    """Bảng Cân đối kế toán (CĐKT) 3 năm."""
    years: List[str]
    current_assets: List[float]
    cash_and_equivalents: List[float]
    short_term_investments: List[float]
    accounts_receivable: List[float]
    inventories: List[float]
    other_current_assets: List[float]
    non_current_assets: List[float]
    fixed_assets: List[float]
    construction_in_progress: List[float]
    total_assets: List[float]
    liabilities: List[float]
    short_term_debt: List[float]
    long_term_debt: List[float]
    owner_equity: List[float]
    charter_capital: List[float]


@dataclass
class CashFlowStatement3Y:
    """Báo cáo Lưu chuyển tiền tệ 3 năm."""
    years: List[str]
    ocf_cash_from_operations: List[float]
    icf_cash_from_investing: List[float]
    fcf_cash_from_financing: List[float]
    net_cash_flow: List[float]
    cash_beginning: List[float]
    cash_ending: List[float]
    cash_flow_analysis: str = ""


@dataclass
class FinancialRatios3Y:
    """Bảng 8 chỉ số tài chính tổng hợp đối chiếu chuẩn an toàn MSB."""
    years: List[str]
    current_ratio: List[float]        # Chuẩn MSB: >= 1.10
    quick_ratio: List[float]          # Chuẩn MSB: >= 0.50
    cash_ratio: List[float]           # Chuẩn MSB: >= 0.20
    debt_to_equity: List[float]       # Chuẩn MSB: <= 3.00 (hoặc <= 4.0 đối với thép)
    total_debt_to_equity: List[float] # Chuẩn MSB: <= 2.00
    dscr_icr: List[float]             # Chuẩn MSB: >= 1.50
    ros: List[float]                  # Chuẩn MSB: > 0%
    roe: List[float]                  # Chuẩn MSB: > 0%


@dataclass
class SectionDData:
    """Dữ liệu tổng hợp toàn diện Phần D."""
    customer_name: str
    governance: AccountingGovernance
    income_statement: IncomeStatement3Y
    pnl_analysis: PnLAnalysis
    balance_sheet: BalanceSheet3Y
    cash_flow: CashFlowStatement3Y
    ratios: FinancialRatios3Y
    summary_bullets: List[str] = field(default_factory=list)

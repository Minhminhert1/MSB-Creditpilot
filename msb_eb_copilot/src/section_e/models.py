import re
import unicodedata
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

from .enums import DebtGroup, CollateralType


def is_msb_institution(bank_name: Optional[str]) -> bool:
    """Deterministic MSB institution alias resolver.
    
    Recognizes known legitimate representations of MSB:
    - Acronym 'MSB' as a standalone word boundary (e.g. 'MSB', 'MSB - CN Cần Thơ')
    - Full Vietnamese name containing 'HANG HAI' (e.g. 'Ngân hàng TMCP Hàng Hải Việt Nam')
    - Former brand name 'MARITIME BANK' or 'MARITIMEBANK'
    
    Rejects false positives such as 'MBBank', 'MB', 'BIDC', etc.
    """
    if not bank_name:
        return False
    # Normalize: strip diacritics via Unicode NFD, remove punctuation, uppercase, collapse spaces
    norm = unicodedata.normalize("NFD", bank_name)
    norm = "".join(c for c in norm if unicodedata.category(c) != "Mn")
    norm = re.sub(r"[^A-Z0-9\s]", " ", norm.upper())
    norm = " ".join(norm.split())

    # 1. Standalone word boundary \bMSB\b
    if re.search(r"\bMSB\b", norm):
        return True
    # 2. Vietnamese corporate name: HANG HAI (Hàng Hải)
    if "HANG HAI" in norm:
        return True
    # 3. Former brand name: MARITIME BANK
    if "MARITIME BANK" in norm or "MARITIMEBANK" in norm:
        return True
    return False


@dataclass
class CreditInstitutionRelation:
    """Chi tiết Quan hệ tín dụng tại 1 Tổ chức tín dụng (1 dòng trong Bảng 07)."""
    stt: int
    bank_name: str                                         # Tên TCTD (Ví dụ: "BIDV", "Vietcombank", "MSB")
    short_term_limit_million_vnd: Optional[float] = None   # Tổng HMTD ngắn hạn (Triệu VND, None = missing/unsupported)
    short_term_debt_vnd_million: Optional[float] = None    # Dư nợ ngắn hạn VND (Triệu VND)
    short_term_debt_usd_million: Optional[float] = None    # Dư nợ ngắn hạn USD quy đổi VND (Triệu VND, None if raw USD without equiv)
    medium_long_term_debt_million: Optional[float] = None  # Dư nợ trung dài hạn (Triệu VND)
    total_debt_million: Optional[float] = None             # Tổng số dư nợ (Triệu VND, None if incomplete)
    collateral_description: Optional[str] = None          # Chi tiết TSBĐ: "BĐS, HĐTG", "Tín chấp"
    debt_group: Optional[DebtGroup] = DebtGroup.NHOM_1_DU_TIEU_CHUAN # Nhóm nợ CIC (1..5, None if unsupported)

    # Raw / Audit fields for multi-currency or unaggregated provenance
    raw_usd_amount: Optional[float] = None                 # Raw USD amount if CIC provides USD without VND equivalent
    raw_usd_currency: Optional[str] = None                 # "USD"
    total_debt_raw_audited: Optional[float] = None         # Printed total debt from CIC for reconciliation audit

    def __post_init__(self):
        # Tự động tính tổng dư nợ nếu chưa gán và các thành phần khả dụng
        if self.total_debt_million is None or self.total_debt_million == 0.0:
            # Nếu có khoản nợ USD chưa quy đổi được, không thể tính tổng hoàn chỉnh
            if self.raw_usd_amount is not None and self.short_term_debt_usd_million is None:
                self.total_debt_million = None
            else:
                c_vnd = self.short_term_debt_vnd_million or 0.0
                c_usd = self.short_term_debt_usd_million or 0.0
                c_tdh = self.medium_long_term_debt_million or 0.0
                if any(v is not None for v in [self.short_term_debt_vnd_million, self.short_term_debt_usd_million, self.medium_long_term_debt_million]):
                    self.total_debt_million = round(c_vnd + c_usd + c_tdh, 2)


@dataclass
class SectionEData:
    """Dữ liệu toàn diện Phần E - Báo cáo CIC & Quan hệ tín dụng."""
    customer_name: str
    cic_report_date: str                                   # Ngày tra cứu CIC (ví dụ: "15/08/2025")
    relations: List[CreditInstitutionRelation] = field(default_factory=list)
    
    # Quan hệ riêng tại MSB (phục vụ liên kết chéo sang Phần A)
    loan_outstanding_at_msb_million: float = 0.0
    total_credit_exposure_at_msb_million: float = 0.0
    
    # Đánh giá của RM / Lịch sử trả nợ (Tri-state: True, False, None)
    is_overdue_12m: Optional[bool] = None                  # Tri-state: True = có quá hạn, False = không quá hạn, None = thiếu bằng chứng
    overdue_explanation: str = ""
    rm_credit_assessment: str = ""                         # Nhận xét giao dịch, uy tín trả nợ
    derivative_transactions_info: Optional[str] = None     # None nếu CIC không đề cập

    @property
    def total_institutions_count(self) -> int:
        return len(self.relations)

    @property
    def total_short_term_limit_all_banks(self) -> float:
        return sum((r.short_term_limit_million_vnd or 0.0) for r in self.relations)

    @property
    def total_debt_all_banks(self) -> Optional[float]:
        # Nếu có bất kỳ TCTD nào chưa thể tính hoàn chỉnh tổng nợ, tổng toàn ngành cũng incomplete
        if any(r.total_debt_million is None for r in self.relations):
            return None
        return sum((r.total_debt_million or 0.0) for r in self.relations)

    @property
    def total_debt_other_banks_excluding_msb(self) -> Optional[float]:
        """Tổng nợ vay tại các TCTD khác loại trừ MSB (để cấp cho Engine MB09).
        
        Nếu bất kỳ TCTD nào khác MSB có tổng dư nợ chưa hoàn chỉnh (total_debt_million is None),
        trả về None để báo hiệu dữ liệu incomplete, tuyệt đối không tính tổng cục bộ.
        """
        other_relations = [r for r in self.relations if not is_msb_institution(r.bank_name)]
        if any(r.total_debt_million is None for r in other_relations):
            return None
        return sum((r.total_debt_million or 0.0) for r in other_relations)

    @property
    def msb_relations(self) -> List[CreditInstitutionRelation]:
        """Danh sách các quan hệ tín dụng thuộc MSB."""
        return [r for r in self.relations if is_msb_institution(r.bank_name)]

    @property
    def highest_debt_group(self) -> DebtGroup:
        valid_groups = [r.debt_group for r in self.relations if r.debt_group is not None]
        if not valid_groups:
            return DebtGroup.NHOM_1_DU_TIEU_CHUAN
        return max(valid_groups)

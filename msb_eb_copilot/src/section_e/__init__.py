"""Package section_e: Quản lý Quan hệ Tín dụng & Báo cáo CIC đa ngân hàng theo chuẩn MB07."""

from .enums import DebtGroup, FacilityTerm, CollateralType
from .models import CreditInstitutionRelation, SectionEData, is_msb_institution
from .validator import SectionEValidator, SectionEValidationResult
from .renderer import SectionERenderer
from .cross_link import link_section_e_to_session_a, get_other_debt_for_section_d

__all__ = [
    "DebtGroup",
    "FacilityTerm",
    "CollateralType",
    "CreditInstitutionRelation",
    "SectionEData",
    "SectionEValidator",
    "SectionEValidationResult",
    "SectionERenderer",
    "link_section_e_to_session_a",
    "get_other_debt_for_section_d",
    "is_msb_institution",
]

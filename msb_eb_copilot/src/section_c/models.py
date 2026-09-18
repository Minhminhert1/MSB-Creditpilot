"""Mô hình dữ liệu chuẩn (Canonical Models) cho Phần C."""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import List, Optional, Dict, Any

from .enums import BusinessModelType, BlacklistStatus, ConcentrationRiskLevel


@dataclass
class CapitalMilestone:
    """Mốc thời gian thay đổi / tăng vốn điều lệ."""
    effective_date: str
    charter_capital_million_vnd: float
    event_description: str


@dataclass
class ShareholderInfo:
    """Thông tin Cổ đông lớn / Thành viên góp vốn."""
    stt: int
    shareholder_name: str
    id_tax_code: str
    ownership_percentage: float  # ví dụ 55.0 (%)
    contributed_capital_million_vnd: float
    is_major_shareholder: bool = True  # Sở hữu >= 5% vốn


@dataclass
class ManagementMember:
    """Thành viên Ban lãnh đạo / Ban điều hành."""
    position: str             # Ví dụ: "Tổng Giám đốc", "Kế toán trưởng", "Chủ tịch HĐTV"
    full_name: str
    profile_summary: str      # Trình độ, thâm niên, kinh nghiệm ngành
    years_at_company: int = 0 # Số năm công tác tại DN


@dataclass
class ProductInfo:
    """Sản phẩm kinh doanh chính."""
    stt: int
    product_name: str
    brand_name: str
    revenue_share_percentage: float  # ví dụ 60.0 (%)


@dataclass
class WarehouseInfo:
    """Cơ sở vật chất: Hệ thống nhà xưởng, kho bãi (Bảng 01 MB07)."""
    stt: int
    facility_type: str        # "Nhà máy", "Kho chứa hàng", "Trụ sở"
    address: str
    area_m2: float
    ownership_type: str       # "Sở hữu", "Thuê trả tiền hàng năm", "Thuê KCN"
    capacity_description: str


@dataclass
class EquipmentInfo:
    """Chi tiết hệ thống Máy móc thiết bị (MMTB) (Bảng 02 MB07)."""
    stt: int
    equipment_name: str
    origin_and_technology: str # "Ý - Danieli", "Nhật Bản", "Việt Nam"
    designed_capacity: str     # "220.000 tấn/năm", "1.000.000 tấn/năm"
    utilization_rate: str      # "95%", "100%"


@dataclass
class SupplierInfo:
    """Thị trường Đầu vào & Top Nhà cung cấp chính (Bảng 04 MB07)."""
    stt: int
    supplier_name: str
    supplied_goods: str
    purchase_share_percentage: float  # ví dụ 25.0 (%)
    payment_terms: str                # "L/C 90 ngày", "TTR trả ngay", "Công nợ 30 ngày"
    has_cic_check: bool = False       # Tra cứu CIC nếu NCC chiếm >= 30%


@dataclass
class CustomerInfo:
    """Thị trường Đầu ra & Top Khách hàng chính (Bảng 06 MB07)."""
    stt: int
    customer_name: str
    product_purchased: str
    revenue_share_percentage: float   # ví dụ 18.0 (%)
    credit_terms: str                 # "Bảo lãnh thanh toán", "Trả trước 30%, còn lại 15 ngày"


@dataclass
class SectionCData:
    """Dữ liệu toàn diện Phần C Tờ trình MB07."""
    customer_name: str
    history_narrative: str
    capital_milestones: List[CapitalMilestone] = field(default_factory=list)
    
    # 2. Chủ sở hữu & Lãnh đạo
    parent_company_or_owner: str = ""
    major_shareholders: List[ShareholderInfo] = field(default_factory=list)
    blacklist_status: BlacklistStatus = BlacklistStatus.KHONG_VI_PHAM
    management_members: List[ManagementMember] = field(default_factory=list)
    organizational_notes: str = ""
    
    # 3. Sản phẩm & Công nghệ
    business_model: BusinessModelType = BusinessModelType.SAN_XUAT
    products: List[ProductInfo] = field(default_factory=list)
    production_technology_summary: str = ""
    warehouses: List[WarehouseInfo] = field(default_factory=list)
    equipments: List[EquipmentInfo] = field(default_factory=list)
    
    # 4. Chuỗi cung ứng Đầu vào & Đầu ra
    raw_materials_overview: str = ""
    suppliers: List[SupplierInfo] = field(default_factory=list)
    distribution_channels: str = ""
    customers: List[CustomerInfo] = field(default_factory=list)
    market_share_estimate: str = ""
    top_competitors: List[str] = field(default_factory=list)
    competitive_advantages: str = ""
    
    # 5. Nhận xét & Đánh giá của RM (Bắt buộc)
    industry_risk_analysis: str = ""
    rm_industry_assessment: str = ""
    rm_supply_chain_assessment: str = ""
    rm_credit_risk_mitigation: str = ""

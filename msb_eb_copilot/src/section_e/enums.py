"""Enums cho Phân hệ E - Quan hệ tín dụng & Báo cáo CIC."""

from enum import Enum


class DebtGroup(int, Enum):
    """Nhóm nợ theo phân loại CIC và Thông tư 11/2021/TT-NHNN."""
    NHOM_1_DU_TIEU_CHUAN = 1       # Nợ đủ tiêu chuẩn (quá hạn dưới 10 ngày)
    NHOM_2_CAN_CHU_Y = 2           # Nợ cần chú ý (quá hạn 10 đến 90 ngày)
    NHOM_3_DUOI_TIEU_CHUAN = 3     # Nợ dưới tiêu chuẩn (quá hạn 91 đến 180 ngày)
    NHOM_4_NGHI_NGO = 4            # Nợ nghi ngờ (quá hạn 181 đến 360 ngày)
    NHOM_5_CO_KHA_NANG_MAT_VON = 5 # Nợ có khả năng mất vốn (quá hạn trên 360 ngày)


class FacilityTerm(str, Enum):
    """Kỳ hạn cấp tín dụng."""
    NGAN_HAN = "NGAN_HAN"
    TRUNG_DAI_HAN = "TRUNG_DAI_HAN"


class CollateralType(str, Enum):
    """Loại tài sản bảo đảm tại các TCTD."""
    BAT_DONG_SAN = "BAT_DONG_SAN"                 # Bất động sản
    HOP_DONG_TIEN_GUI = "HOP_DONG_TIEN_GUI"       # Sổ tiết kiệm / Hợp đồng tiền gửi
    PHUONG_TIEN_VAN_TAI = "PHUONG_TIEN_VAN_TAI"   # Ô tô, xe máy, xà lan, tàu biển
    HANG_HOA_MAY_MOC = "HANG_HOA_MAY_MOC"         # Hàng tồn kho, máy móc thiết bị
    TIN_CHAP = "TIN_CHAP"                         # Không có TSBĐ (Tín chấp)

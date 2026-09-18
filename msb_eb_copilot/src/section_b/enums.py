# -*- coding: utf-8 -*-
"""Enums for Section B: Nội dung đề xuất cấp tín dụng."""

from enum import Enum


class CreditNeedId(str, Enum):
    """Mã định danh 8 nhu cầu cấp tín dụng chuẩn của Mục 2."""
    NEED_2_1 = "2.1_vay_vld_han_muc"
    NEED_2_2 = "2.2_vay_vld_han_muc_tren_12t"
    NEED_2_3 = "2.3_vay_ngan_han_tung_lan"
    NEED_2_4 = "2.4_vay_trung_dai_han"
    NEED_2_5 = "2.5_lc_nho_thu"
    NEED_2_6 = "2.6_bao_lanh"
    NEED_2_7 = "2.7_chiet_khau_bao_thanh_toan"
    NEED_2_8 = "2.8_rui_ro_doi_tac"


class ProposalType(str, Enum):
    """Hình thức đề xuất."""
    CAP_MOI = "Cấp mới"
    TAI_CAP = "Tái cấp"


class IssuanceStructure(str, Enum):
    """Hình thức cấp tín dụng."""
    HAN_MUC = "Hạn mức"
    TUNG_LAN = "Từng lần"


class LoanTermType(str, Enum):
    """Phân loại kỳ hạn vay (Mục 2.4)."""
    TRUNG_HAN = "Trung hạn"
    DAI_HAN = "Dài hạn"


class TenorClassification(str, Enum):
    """Phân loại kỳ hạn cho L/C (2.5) và Bảo lãnh (2.6)."""
    NGAN_HAN = "Ngắn hạn"
    TREN_12T = "Trên 12 tháng"
    TRUNG_HAN = "Trung hạn"
    DAI_HAN = "Dài hạn"


class ProductTypeLC(str, Enum):
    """Loại sản phẩm tài trợ thương mại (Mục 2.5)."""
    LC = "L/C"
    NHO_THU = "Nhờ thu"


class ProductTypeDiscount(str, Enum):
    """Loại sản phẩm chiết khấu / bao thanh toán (Mục 2.7)."""
    CHIET_KHAU = "Chiết khấu BCT"
    BAO_THANH_TOAN = "Bao thanh toán"


class EffectiveDateType(str, Enum):
    """Quy tắc xác định ngày hiệu lực hạn mức."""
    KY_HDTD = "Kể từ ngày ký Hợp đồng tín dụng"
    PHE_DUYET = "Kể từ ngày phê duyệt khoản vay"
    NGAY_CU_THE = "Ngày cụ thể"
    KHAC = "Khác"


class CounterpartySubProduct(str, Enum):
    """Sản phẩm con của Rủi ro tín dụng đối tác (Mục 2.8)."""
    FX_DERIVATIVE = "Sản phẩm phái sinh ngoại hối"
    IR_DERIVATIVE = "Sản phẩm phái sinh lãi suất có thời hạn dưới 1 năm"


class ValidationSeverity(str, Enum):
    """Mức độ cảnh báo validation."""
    WARNING = "WARNING"
    BLOCKING = "BLOCKING"

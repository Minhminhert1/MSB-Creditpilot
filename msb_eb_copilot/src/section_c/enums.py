"""Enums cho Phân hệ C - Hoạt động kinh doanh & Chuỗi cung ứng."""

from enum import Enum


class BusinessModelType(str, Enum):
    """Mô hình hoạt động kinh doanh chính."""
    SAN_XUAT = "SAN_XUAT"            # Sản xuất, chế biến, chế tạo
    THUONG_MAI = "THUONG_MAI"        # Bán buôn, bán lẻ, phân phối
    DICH_VU = "DICH_VU"              # Dịch vụ, logistics, kho vận
    HON_HOP = "HON_HOP"              # Kết hợp sản xuất và phân phối


class BlacklistStatus(str, Enum):
    """Trạng thái kiểm tra Danh sách đen / Đối tượng hạn chế (Điều 126 Luật TCTD)."""
    KHONG_VI_PHAM = "KHONG_VI_PHAM"  # Hợp lệ, không thuộc Blacklist
    THUOC_BLACKLIST = "THUOC_BLACKLIST"  # Vi phạm, thuộc danh sách cấm cấp tín dụng


class ConcentrationRiskLevel(str, Enum):
    """Mức độ rủi ro tập trung chuỗi cung ứng (QĐ.RR.074)."""
    BINH_THUONG = "BINH_THUONG"
    CANH_BAO_TAP_TRUNG_NCC = "CANH_BAO_TAP_TRUNG_NCC"   # 1 NCC chiếm >= 40% chi phí mua hàng
    CANH_BAO_TAP_TRUNG_KH = "CANH_BAO_TAP_TRUNG_KH"     # 1 Khách hàng chiếm >= 30% doanh thu

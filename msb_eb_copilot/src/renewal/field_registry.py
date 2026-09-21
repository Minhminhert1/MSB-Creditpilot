# -*- coding: utf-8 -*-
"""Module: renewal.field_registry
Mô tả: Danh mục TẤT ĐỊNH các trường thông tin được theo dõi xuyên suốt luồng
Tái cấp (renewal). Đây là NGUỒN DUY NHẤT xác định canonical_path <-> nhãn hiển
thị, được dùng cả bởi baseline_extractor (đọc MB07 kỳ trước) lẫn
change_detection (đọc dữ liệu canonical hiện tại từ CASES_DB), đảm bảo hai bên
luôn so sánh cùng một tập khóa.

Đây KHÔNG phải danh sách đầy đủ mọi trường của MB07 -- là tập hợp các chỉ tiêu
trọng yếu nhất cho tái cấp tín dụng (tài chính cốt lõi + một số thông tin định
danh/khách hàng), có thể mở rộng dần mà không ảnh hưởng logic so sánh.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass(frozen=True)
class RenewalFieldDefinition:
    canonical_path: str
    label: str
    # Các biến thể nhãn tiếng Việt có thể xuất hiện trong MB07 kỳ trước
    # (dùng để dò tìm tất định trong bảng/đoạn văn -- KHÔNG suy đoán ngữ nghĩa).
    old_label_variants: List[str] = field(default_factory=list)
    # Đơn vị hiển thị mặc định khi giá trị là số (chỉ để hiển thị, không ảnh hưởng so sánh).
    unit: str = ""
    is_numeric: bool = False


RENEWAL_TRACKED_FIELDS: List[RenewalFieldDefinition] = [
    RenewalFieldDefinition(
        canonical_path="customer.legal_name",
        label="Tên doanh nghiệp",
        old_label_variants=["Tên doanh nghiệp", "Tên Doanh nghiệp", "Tên công ty", "Tên khách hàng"],
    ),
    RenewalFieldDefinition(
        canonical_path="customer.address",
        label="Địa chỉ trụ sở",
        old_label_variants=["Địa chỉ trụ sở", "Địa chỉ trụ sở chính", "Địa chỉ đăng ký kinh doanh", "Địa chỉ"],
    ),
    RenewalFieldDefinition(
        canonical_path="financial.net_revenue_latest",
        label="Doanh thu thuần",
        old_label_variants=["Doanh thu thuần", "Doanh thu thuần về bán hàng và cung cấp dịch vụ"],
        unit="triệu VND",
        is_numeric=True,
    ),
    RenewalFieldDefinition(
        canonical_path="financial.net_profit_after_tax_latest",
        label="Lợi nhuận sau thuế",
        old_label_variants=["Lợi nhuận sau thuế", "Lợi nhuận sau thuế thu nhập doanh nghiệp"],
        unit="triệu VND",
        is_numeric=True,
    ),
    RenewalFieldDefinition(
        canonical_path="financial.total_assets_latest",
        label="Tổng tài sản",
        old_label_variants=["Tổng cộng tài sản", "Tổng tài sản"],
        unit="triệu VND",
        is_numeric=True,
    ),
    RenewalFieldDefinition(
        canonical_path="financial.equity_latest",
        label="Vốn chủ sở hữu",
        old_label_variants=["Vốn chủ sở hữu"],
        unit="triệu VND",
        is_numeric=True,
    ),
    RenewalFieldDefinition(
        canonical_path="financial.inventories_latest",
        label="Hàng tồn kho",
        old_label_variants=["Hàng tồn kho"],
        unit="triệu VND",
        is_numeric=True,
    ),
    RenewalFieldDefinition(
        canonical_path="financial.receivables_latest",
        label="Phải thu ngắn hạn",
        old_label_variants=["Các khoản phải thu ngắn hạn", "Phải thu ngắn hạn"],
        unit="triệu VND",
        is_numeric=True,
    ),
    RenewalFieldDefinition(
        canonical_path="financial.short_term_debt_latest",
        label="Vay và nợ thuê tài chính ngắn hạn",
        old_label_variants=["Vay và nợ thuê tài chính ngắn hạn", "Vay ngắn hạn"],
        unit="triệu VND",
        is_numeric=True,
    ),
    RenewalFieldDefinition(
        canonical_path="business.key_customer",
        label="Khách hàng lớn nhất",
        old_label_variants=["Khách hàng lớn", "Khách hàng lớn nhất", "Khách hàng chính"],
    ),
    RenewalFieldDefinition(
        canonical_path="credit.msb_outstanding",
        label="Dư nợ tại MSB",
        old_label_variants=["Dư nợ tại MSB", "Dư nợ hiện tại tại MSB"],
        unit="triệu VND",
        is_numeric=True,
    ),
]

RENEWAL_FIELD_BY_PATH = {f.canonical_path: f for f in RENEWAL_TRACKED_FIELDS}

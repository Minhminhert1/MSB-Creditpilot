"""
Module: mock_data.py
Mô tả: Tập dữ liệu mẫu chi tiết (BCTC 3 năm, CIC đa ngân hàng, Top 5 Đối tác, TSBĐ, Kế hoạch Bán chéo) của 4 Archetype Doanh nghiệp lớn.
"""

from typing import Dict, Any


SAMPLE_COMPANIES: Dict[str, Dict[str, Any]] = {
    "GAS_SOUTH": {
        "id": "GAS_SOUTH",
        "name": "CÔNG TY CỔ PHẦN KINH DOANH KHÍ MIỀN NAM (GAS SOUTH - PGS)",
        "tax_code": "0304381832",
        "industry": "Kinh doanh, chiết nạp & phân phối khí hóa lỏng LPG, khí thiên nhiên nén CNG",
        "years_in_operation": 18.0,
        "ticker": "PGS",
        "archetype": "Energy & Gas Trading (KTSBĐ)",
        "address": "Lầu 4, Tòa nhà PetroVietnam, số 1-5 Lê Duẩn, P. Bến Nghé, Quận 1, TP.HCM",
        "legal_rep": "Ông Nguyễn Ngọc Luận - Tổng Giám đốc",
        "charter_capital": 500_000_000_000,
        
        # BCTC 3 Năm (2023, 2024, 2025) - Đơn vị: VND
        "financial_3yr": {
            "years": ["2023", "2024", "2025 (Kế hoạch)"],
            "revenue": [5_850_000_000_000, 6_450_000_000_000, 7_200_000_000_000],
            "cogs": [5_420_000_000_000, 5_980_000_000_000, 6_650_000_000_000],
            "gross_profit": [430_000_000_000, 470_000_000_000, 550_000_000_000],
            "operating_expense": [310_000_000_000, 335_000_000_000, 380_000_000_000],
            "net_profit": [115_000_000_000, 128_000_000_000, 155_000_000_000],
            "total_assets": [2_150_000_000_000, 2_380_000_000_000, 2_650_000_000_000],
            "current_assets": [1_450_000_000_000, 1_620_000_000_000, 1_850_000_000_000],
            "cash_and_equiv": [320_000_000_000, 380_000_000_000, 420_000_000_000],
            "receivables": [580_000_000_000, 640_000_000_000, 720_000_000_000],
            "inventory": [350_000_000_000, 390_000_000_000, 450_000_000_000],
            "short_term_debt": [620_000_000_000, 680_000_000_000, 750_000_000_000],
            "total_liabilities": [1_570_000_000_000, 1_768_000_000_000, 1_950_000_000_000],
            "equity": [580_000_000_000, 612_000_000_000, 700_000_000_000],
            "operating_cash_flow": [145_000_000_000, 168_000_000_000, 190_000_000_000]
        },

        # Chỉ tiêu T-1
        "equity_vnd": 612_000_000_000,
        "revenue_t_minus_1": 6_450_000_000_000,
        "net_profit_t_minus_1": 128_000_000_000,
        "net_profit_t_minus_2": 115_000_000_000,
        "cogs_t_minus_1": 5_980_000_000_000,
        "debt_to_equity": 2.88,
        "current_ratio": 1.35,
        "has_bad_debt_cic_24m": False,
        "is_restructured_debt": False,
        "is_special_monitoring": False,

        # Kế hoạch năm tới (MB09)
        "net_revenue_plan": 7_200_000_000_000,
        "cogs_plan": 6_650_000_000_000,
        "operating_cost_plan": 380_000_000_000,
        "dio": 18.0,
        "dso": 32.0,
        "dpo": 25.0,
        "equity_participation": 250_000_000_000,
        "other_debt": 400_000_000_000,
        "import_ratio": 0.55,
        "lc_tenor_days": 90,
        "guarantee_ratio": 0.08,
        "guarantee_tenor_days": 180,
        "loan_interest_rate": 0.075,
        "ftp_cost_rate": 0.052,
        "lc_fee_rate": 0.010,
        "guarantee_fee_rate": 0.012,
        "casa_avg_balance": 35_000_000_000,
        "requested_unsecured_limit": 500_000_000_000,

        # Quan hệ tín dụng tại các TCTD (CIC Chi tiết)
        "bank_relations": [
            {"bank": "Vietcombank - CN TP.HCM", "facility": "Cho vay ngắn hạn & L/C", "limit": 600_000_000_000, "debt": 320_000_000_000, "collateral": "KTSBĐ & Kho bãi", "status": "Nhóm 1"},
            {"bank": "BIDV - CN Sở Giao Dịch 2", "facility": "Cho vay ngắn hạn & Bảo lãnh", "limit": 450_000_000_000, "debt": 210_000_000_000, "collateral": "Máy móc & Quyền đòi nợ", "status": "Nhóm 1"},
            {"bank": "Vietinbank - CN 1 TP.HCM", "facility": "Hạn mức L/C nhập khẩu", "limit": 300_000_000_000, "debt": 150_000_000_000, "collateral": "Hàng hóa hình thành từ vốn vay", "status": "Nhóm 1"},
            {"bank": "MSB (Đề xuất mới)", "facility": "Hạn mức Tín dụng Tổng hợp", "limit": 1_202_000_000_000, "debt": 0, "collateral": "KTSBĐ 500 tỷ + Dòng tiền", "status": "Khách hàng mới"}
        ],

        # Top 5 Nhà cung cấp & Top 5 Khách hàng
        "top_suppliers": [
            {"name": "Tổng Công ty Khí Việt Nam (PV GAS)", "product": "Khí LPG & CNG nguồn nội địa", "turnover": 3_200_000_000_000, "share": "48%", "term": "L/C 30-60 ngày"},
            {"name": "Shell Eastern Trading Ltd", "product": "Nhập khẩu LPG lạnh", "turnover": 1_500_000_000_000, "share": "23%", "term": "L/C UPAS 90 ngày"},
            {"name": "Marubeni Corporation", "product": "Nhập khẩu LPG định kỳ", "turnover": 850_000_000_000, "share": "13%", "term": "L/C Sight"},
            {"name": "Công ty TNHH Hóa dầu Long Sơn", "product": "Nguồn khí công nghiệp", "turnover": 450_000_000_000, "share": "7%", "term": "T/T 15 ngày"},
            {"name": "Các nhà cung cấp vận tải bồn", "product": "Dịch vụ logistics khí", "turnover": 250_000_000_000, "share": "4%", "term": "Gối đầu 30 ngày"}
        ],
        "top_buyers": [
            {"name": "Công ty Cổ phần Prime Group", "product": "Khí CNG đốt lò gạch men", "revenue": 820_000_000_000, "share": "12.7%", "term": "T/T 30 ngày"},
            {"name": "Tập đoàn Hoa Sen (Hoa Sen Group)", "product": "Khí CNG mạ tôn thép", "revenue": 650_000_000_000, "share": "10.1%", "term": "T/T 45 ngày"},
            {"name": "Tập đoàn Viglacera", "product": "Khí CNG nung sứ vệ sinh", "revenue": 520_000_000_000, "share": "8.1%", "term": "Bảo lãnh / T/T 30 ngày"},
            {"name": "Hệ thống Tổng đại lý Bình gas Dân dụng", "product": "Bình Gas LPG 12kg - 45kg", "revenue": 1_850_000_000_000, "share": "28.7%", "term": "Thu tiền ngay / 7 ngày"},
            {"name": "Công ty CP Gạch men Taicera", "product": "Khí công nghiệp", "revenue": 380_000_000_000, "share": "5.9%", "term": "T/T 30 ngày"}
        ],

        # Tài sản bảo đảm
        "collaterals": [
            {"type": "Bất động sản / Kho chứa khí", "desc": "Kho LPG Gò Dầu (Đồng Nai) & Kho Tiền Giang dung tích 6.000 tấn", "val_book": 420_000_000_000, "val_msb": 350_000_000_000, "ltv": "70%", "max_limit": 245_000_000_000},
            {"type": "Phương tiện vận tải chuyên dùng", "desc": "Đội 35 xe bồn chuyên dụng chở CNG/LPG và vỏ bình gas", "val_book": 180_000_000_000, "val_msb": 130_000_000_000, "ltv": "60%", "max_limit": 78_000_000_000},
            {"type": "Hạn mức Tín chấp KTSBĐ", "desc": "Cấp theo QĐ.RR.074 cho KHDN Lớn uy tín đầu ngành năng lượng", "val_book": 0, "val_msb": 0, "ltv": "-", "max_limit": 500_000_000_000}
        ],

        # Kế hoạch Bán chéo tại MSB (Cross-sell)
        "cross_sell_plan": {
            "payroll": "Chuyển toàn bộ quỹ lương 850 CBNV của Gas South qua tài khoản MSB (Doanh số ~25 tỷ/tháng)",
            "casa_target": "Cam kết số dư tiền gửi không kỳ hạn bình quân 35 - 50 tỷ VND thường xuyên",
            "fx_volume": "Doanh số giao dịch ngoại tệ FX xuất nhập khẩu tối thiểu 30 triệu USD/năm tại MSB",
            "pos_qr": "Triển khai thu hộ qua QR Code động tại 120 trạm chiết nạp và tổng đại lý miền Nam",
            "retail_cross": "Cấp hạn mức thẻ tín dụng và vay tiêu dùng ưu đãi cho Ban lãnh đạo & CBNV"
        }
    },

    "DEMO_GROUP": {
        "id": "DEMO_GROUP",
        "name": "TỔNG CÔNG TY CỔ PHẦN DỊCH VỤ TỔNG HỢP DẦU KHÍ (DEMO_GROUP - PET)",
        "tax_code": "0300452060",
        "industry": "Phân phối thiết bị ICT (Apple, Samsung), Dịch vụ hậu cần logistics & đời sống dầu khí",
        "years_in_operation": 28.0,
        "ticker": "PET",
        "archetype": "ICT Distribution & Parent-Subsidiary Credit Lines",
        "address": "Lầu 6, Tòa nhà PetroVietnam, số 1-5 Lê Duẩn, P. Bến Nghé, Quận 1, TP.HCM",
        "legal_rep": "Ông Đại diện Demo - Tổng Giám đốc",
        "charter_capital": 994_000_000_000,
        
        "financial_3yr": {
            "years": ["2023", "2024", "2025 (Kế hoạch)"],
            "revenue": [17_600_000_000_000, 18_200_000_000_000, 20_500_000_000_000],
            "cogs": [16_500_000_000_000, 17_100_000_000_000, 19_200_000_000_000],
            "gross_profit": [1_100_000_000_000, 1_100_000_000_000, 1_300_000_000_000],
            "operating_expense": [780_000_000_000, 820_000_000_000, 950_000_000_000],
            "net_profit": [185_000_000_000, 210_000_000_000, 260_000_000_000],
            "total_assets": [8_500_000_000_000, 9_200_000_000_000, 10_500_000_000_000],
            "current_assets": [6_800_000_000_000, 7_400_000_000_000, 8_600_000_000_000],
            "cash_and_equiv": [1_200_000_000_000, 1_450_000_000_000, 1_800_000_000_000],
            "receivables": [2_900_000_000_000, 3_100_000_000_000, 3_600_000_000_000],
            "inventory": [2_100_000_000_000, 2_350_000_000_000, 2_700_000_000_000],
            "short_term_debt": [3_800_000_000_000, 4_200_000_000_000, 4_800_000_000_000],
            "total_liabilities": [6_250_000_000_000, 6_750_000_000_000, 7_600_000_000_000],
            "equity": [2_250_000_000_000, 2_450_000_000_000, 2_900_000_000_000],
            "operating_cash_flow": [320_000_000_000, 390_000_000_000, 450_000_000_000]
        },

        "equity_vnd": 2_450_000_000_000,
        "revenue_t_minus_1": 18_200_000_000_000,
        "net_profit_t_minus_1": 210_000_000_000,
        "net_profit_t_minus_2": 185_000_000_000,
        "cogs_t_minus_1": 17_100_000_000_000,
        "debt_to_equity": 2.75,
        "current_ratio": 1.22,
        "has_bad_debt_cic_24m": False,
        "is_restructured_debt": False,
        "is_special_monitoring": False,

        "net_revenue_plan": 20_500_000_000_000,
        "cogs_plan": 19_200_000_000_000,
        "operating_cost_plan": 950_000_000_000,
        "dio": 24.0,
        "dso": 45.0,
        "dpo": 35.0,
        "equity_participation": 800_000_000_000,
        "other_debt": 1_200_000_000_000,
        "import_ratio": 0.65,
        "lc_tenor_days": 120,
        "guarantee_ratio": 0.05,
        "guarantee_tenor_days": 180,
        "loan_interest_rate": 0.072,
        "ftp_cost_rate": 0.052,
        "lc_fee_rate": 0.009,
        "guarantee_fee_rate": 0.010,
        "casa_avg_balance": 80_000_000_000,
        "requested_unsecured_limit": 600_000_000_000,

        "bank_relations": [
            {"bank": "Vietcombank - CN Sở Giao Dịch", "facility": "Hạn mức Vay & L/C UPAS", "limit": 1_800_000_000_000, "debt": 950_000_000_000, "collateral": "KTSBĐ & Tiền gửi", "status": "Nhóm 1"},
            {"bank": "BIDV - CN Quang Trung", "facility": "Cho vay ngắn hạn bổ sung VLĐ", "limit": 1_200_000_000_000, "debt": 720_000_000_000, "collateral": "Kho hàng ICT & Quyền đòi nợ", "status": "Nhóm 1"},
            {"bank": "MB Bank - CN TP.HCM", "facility": "Tài trợ nhập khẩu thiết bị Apple", "limit": 1_000_000_000_000, "debt": 580_000_000_000, "collateral": "L/C & Hàng hóa luân chuyển", "status": "Nhóm 1"},
            {"bank": "MSB (Đề xuất cấp mới)", "facility": "Tín dụng Tổng hợp Công ty mẹ - con", "limit": 2_150_000_000_000, "debt": 0, "collateral": "KTSBĐ 600 tỷ + Bảo lãnh Mẹ", "status": "Khách hàng mới"}
        ],

        "top_suppliers": [
            {"name": "Apple South Asia Pte Ltd", "product": "iPhone, iPad, Macbook chính hãng", "turnover": 8_500_000_000_000, "share": "44.2%", "term": "L/C UPAS 90-120 ngày"},
            {"name": "Samsung Electronics Vietnam", "product": "Điện thoại Galaxy & Thiết bị gia dụng", "turnover": 4_200_000_000_000, "share": "21.8%", "term": "L/C Sight / T/T 30 ngày"},
            {"name": "Dell Global B.V", "product": "Máy chủ, Laptop doanh nghiệp", "turnover": 1_800_000_000_000, "share": "9.4%", "term": "L/C 60 ngày"},
            {"name": "HP PPS Asia Pte Ltd", "product": "Máy in & Thiết bị văn phòng", "turnover": 1_100_000_000_000, "share": "5.7%", "term": "T/T 45 ngày"},
            {"name": "Tập đoàn Dầu khí Quốc gia (PVN)", "product": "Hợp đồng dịch vụ suất ăn & hậu cần", "turnover": 950_000_000_000, "share": "4.9%", "term": "T/T định kỳ"}
        ],
        "top_buyers": [
            {"name": "Công ty CP Thế Giới Di Động (MWG)", "product": "Điện thoại Apple & Laptop", "revenue": 5_200_000_000_000, "share": "25.4%", "term": "T/T 30-45 ngày"},
            {"name": "Công ty CP Bán lẻ Kỹ thuật số FPT (FPT Shop)", "product": "Thiết bị ICT & Phụ kiện", "revenue": 3_800_000_000_000, "share": "18.5%", "term": "T/T 30-45 ngày"},
            {"name": "Hệ thống Chuỗi Viettel Store", "product": "Điện thoại di động các loại", "revenue": 2_100_000_000_000, "share": "10.2%", "term": "Bảo lãnh / T/T 30 ngày"},
            {"name": "Hệ thống Đại lý bán lẻ cấp 2 toàn quốc", "product": "Hàng công nghệ phân phối sỉ", "revenue": 4_500_000_000_000, "share": "22.0%", "term": "Thu tiền trước / T/T 7 ngày"},
            {"name": "Các đơn vị thành viên Tập đoàn PVN", "product": "Dịch vụ đời sống, khách sạn, catering", "revenue": 1_600_000_000_000, "share": "7.8%", "term": "Thanh toán theo nghiệm thu"}
        ],

        "collaterals": [
            {"type": "Hàng tồn kho luân chuyển ICT", "desc": "Kho hàng thiết bị điện tử giá trị cao tại Tổng kho Sóng Thần (Bình Dương)", "val_book": 950_000_000_000, "val_msb": 650_000_000_000, "ltv": "50%", "max_limit": 325_000_000_000},
            {"type": "Bảo lãnh của Công ty mẹ (Tập đoàn PVN)", "desc": "Cam kết bảo lãnh vô điều kiện và không hủy ngang của Tập đoàn mẹ", "val_book": 0, "val_msb": 0, "ltv": "-", "max_limit": 1_000_000_000_000},
            {"type": "Hạn mức Tín chấp KTSBĐ", "desc": "Cấp KTSBĐ cho doanh nghiệp đầu ngành phân phối ICT công lập", "val_book": 0, "val_msb": 0, "ltv": "-", "max_limit": 600_000_000_000}
        ],

        "cross_sell_plan": {
            "payroll": "Chuyển trả lương cho 2.500 nhân sự toàn tổng công ty qua MSB (~65 tỷ/tháng)",
            "casa_target": "Cam kết duy trì số dư CASA bình quân 80 - 120 tỷ VND",
            "fx_volume": "Doanh số giao dịch FX tài trợ L/C nhập khẩu tối thiểu 80 triệu USD/năm",
            "pos_qr": "Tích hợp cổng thanh toán trực tuyến MSB Payment Gateway cho các kênh B2B",
            "retail_cross": "Gói bảo hiểm sức khỏe MSB-Prudential và thẻ tín dụng Platinum cho CBNV"
        }
    },

    "THEP_TAY_DO": {
        "id": "THEP_TAY_DO",
        "name": "CÔNG TY CỔ PHẦN THÉP TÂY ĐÔ",
        "tax_code": "1800156789",
        "industry": "Sản xuất, luyện cán thép xây dựng công nghiệp (phôi thép & thép cuộn/cây)",
        "years_in_operation": 25.0,
        "ticker": "TTD",
        "archetype": "Manufacturing & Output Contract Financing (QĐ.039)",
        "address": "KCN Trà Nóc 1, Phường Trà Nóc, Quận Bình Thủy, TP. Cần Thơ",
        "legal_rep": "Ông Huỳnh Trung Quang - Chủ tịch HĐQT",
        "charter_capital": 350_000_000_000,
        
        "financial_3yr": {
            "years": ["2023", "2024", "2025 (Kế hoạch)"],
            "revenue": [2_800_000_000_000, 3_100_000_000_000, 3_600_000_000_000],
            "cogs": [2_650_000_000_000, 2_920_000_000_000, 3_350_000_000_000],
            "gross_profit": [150_000_000_000, 180_000_000_000, 250_000_000_000],
            "operating_expense": [110_000_000_000, 130_000_000_000, 160_000_000_000],
            "net_profit": [38_000_000_000, 42_000_000_000, 75_000_000_000],
            "total_assets": [1_450_000_000_000, 1_620_000_000_000, 1_850_000_000_000],
            "current_assets": [920_000_000_000, 1_050_000_000_000, 1_220_000_000_000],
            "cash_and_equiv": [65_000_000_000, 85_000_000_000, 120_000_000_000],
            "receivables": [420_000_000_000, 480_000_000_000, 550_000_000_000],
            "inventory": [410_000_000_000, 460_000_000_000, 520_000_000_000],
            "short_term_debt": [520_000_000_000, 580_000_000_000, 680_000_000_000],
            "total_liabilities": [1_030_000_000_000, 1_170_000_000_000, 1_330_000_000_000],
            "equity": [420_000_000_000, 450_000_000_000, 520_000_000_000],
            "operating_cash_flow": [65_000_000_000, 78_000_000_000, 95_000_000_000]
        },

        "equity_vnd": 450_000_000_000,
        "revenue_t_minus_1": 3_100_000_000_000,
        "net_profit_t_minus_1": 42_000_000_000,
        "net_profit_t_minus_2": 38_000_000_000,
        "cogs_t_minus_1": 2_920_000_000_000,
        "debt_to_equity": 2.60,
        "current_ratio": 1.18,
        "has_bad_debt_cic_24m": False,
        "is_restructured_debt": False,
        "is_special_monitoring": False,

        "net_revenue_plan": 3_600_000_000_000,
        "cogs_plan": 3_350_000_000_000,
        "operating_cost_plan": 160_000_000_000,
        "dio": 40.0,
        "dso": 38.0,
        "dpo": 28.0,
        "equity_participation": 120_000_000_000,
        "other_debt": 250_000_000_000,
        "import_ratio": 0.30,
        "lc_tenor_days": 90,
        "guarantee_ratio": 0.12,
        "guarantee_tenor_days": 180,
        "loan_interest_rate": 0.082,
        "ftp_cost_rate": 0.055,
        "lc_fee_rate": 0.012,
        "guarantee_fee_rate": 0.015,
        "casa_avg_balance": 15_000_000_000,
        "requested_unsecured_limit": 100_000_000_000,

        "bank_relations": [
            {"bank": "Agribank - CN Cần Thơ", "facility": "Cho vay ngắn hạn & Đầu tư lò luyện", "limit": 400_000_000_000, "debt": 280_000_000_000, "collateral": "Nhà xưởng & Dây chuyền cán", "status": "Nhóm 1"},
            {"bank": "Sacombank - CN Tây Đô", "facility": "Hạn mức L/C nhập phôi thép", "limit": 200_000_000_000, "debt": 110_000_000_000, "collateral": "Hàng hóa tồn kho", "status": "Nhóm 1"},
            {"bank": "MSB (Đề xuất cấp mới)", "facility": "Tài trợ Chuỗi Hợp đồng đầu ra QĐ.039", "limit": 550_000_000_000, "debt": 0, "collateral": "Quyền đòi nợ HĐ + BĐS", "status": "Khách hàng mới"}
        ],

        "top_suppliers": [
            {"name": "Công ty TNHH Gang thép Hưng Nghiệp Formosa Hà Tĩnh", "product": "Phôi thép vuông 150x150", "turnover": 1_200_000_000_000, "share": "35.8%", "term": "L/C Sight"},
            {"name": "Tổng Công ty Thép Việt Nam (VNSTEEL)", "product": "Phôi thép & Thép phế liệu", "turnover": 800_000_000_000, "share": "23.9%", "term": "T/T 30 ngày"},
            {"name": "Công ty Cổ phần Thép Pomina", "product": "Phôi thép luyện kim", "turnover": 450_000_000_000, "share": "13.4%", "term": "L/C 60 ngày"},
            {"name": "Nhà cung cấp điện lực EVN Cần Thơ", "product": "Điện năng lò hồ quang", "turnover": 350_000_000_000, "share": "10.4%", "term": "Thanh toán tháng"},
            {"name": "Các vựa phế liệu kim loại ĐBSCL", "product": "Sắt vụn, thép tái chế", "turnover": 250_000_000_000, "share": "7.5%", "term": "Tiền mặt / T/T"}
        ],
        "top_buyers": [
            {"name": "Tổng Công ty Xây dựng Số 1 (CC1)", "product": "Thép xây dựng dự án cao tốc", "revenue": 580_000_000_000, "share": "16.1%", "term": "Bảo lãnh / T/T 60 ngày"},
            {"name": "Tập đoàn Xây dựng Hòa Bình", "product": "Thép cây mác cao dự án dân dụng", "revenue": 420_000_000_000, "share": "11.7%", "term": "Hợp đồng đầu ra QĐ.039"},
            {"name": "Công ty CP Tập đoàn Đèo Cả", "product": "Thép dầm cầu & hầm giao thông", "revenue": 350_000_000_000, "share": "9.7%", "term": "Tài trợ theo nghiệm thu"},
            {"name": "Hệ thống Đại lý sắt thép Miền Tây", "product": "Thép cuộn xây dựng dân sinh", "revenue": 1_450_000_000_000, "share": "40.3%", "term": "Gối đầu 15-30 ngày"},
            {"name": "Công ty CP Đầu tư Xây dựng Ricons", "product": "Thép kết cấu công trình", "revenue": 280_000_000_000, "share": "7.8%", "term": "T/T 45 ngày"}
        ],

        "collaterals": [
            {"type": "Nhà máy & Đất thuê KCN Trà Nóc", "desc": "Quyền sử dụng đất 45.000 m2 & Nhà xưởng luyện cán thép tại Cần Thơ", "val_book": 320_000_000_000, "val_msb": 260_000_000_000, "ltv": "70%", "max_limit": 182_000_000_000},
            {"type": "Quyền đòi nợ Hợp đồng đầu ra", "desc": "Toàn bộ quyền đòi nợ từ Hợp đồng cung cấp thép cho CC1, Hòa Bình, Đèo Cả", "val_book": 450_000_000_000, "val_msb": 350_000_000_000, "ltv": "80%", "max_limit": 280_000_000_000},
            {"type": "Hạn mức KTSBĐ", "desc": "Cấp hạn mức bổ sung theo QĐ.074", "val_book": 0, "val_msb": 0, "ltv": "-", "max_limit": 100_000_000_000}
        ],

        "cross_sell_plan": {
            "payroll": "Chuyển toàn bộ 450 công nhân luyện cán thép sang nhận lương MSB (~10 tỷ/tháng)",
            "casa_target": "Duy trì số dư CASA bình quân 15 - 25 tỷ VND",
            "fx_volume": "Doanh số FX nhập khẩu phôi thép 15 triệu USD/năm",
            "pos_qr": "Triển khai dịch vụ bảo lãnh điện tử e-Guarantee cho các gói thầu hạ tầng",
            "retail_cross": "Bảo hiểm cháy nổ nhà xưởng và bảo hiểm tai nạn lao động qua đối tác MSB"
        }
    },

    "MAISON_RETAIL": {
        "id": "MAISON_RETAIL",
        "name": "CÔNG TY CỔ PHẦN MAISON RETAIL MANAGEMENT INTERNATIONAL (MRMI)",
        "tax_code": "0311899123",
        "industry": "Bán lẻ chuỗi thời trang hàng hiệu quốc tế (Charles & Keith, Pedro, MLB, Coach, Puma)",
        "years_in_operation": 14.0,
        "ticker": "MAISON",
        "archetype": "Fashion Retail & Aging Inventory Management",
        "address": "Tầng 18, Tòa nhà Vincom Center Đồng Khởi, 72 Lê Thánh Tôn, Bến Nghé, Quận 1, TP.HCM",
        "legal_rep": "Bà Phạm Thị Mai Son - Chủ tịch HĐQT",
        "charter_capital": 420_000_000_000,
        
        "financial_3yr": {
            "years": ["2023", "2024", "2025 (Kế hoạch)"],
            "revenue": [2_450_000_000_000, 2_850_000_000_000, 3_400_000_000_000],
            "cogs": [1_550_000_000_000, 1_850_000_000_000, 2_200_000_000_000],
            "gross_profit": [900_000_000_000, 1_000_000_000_000, 1_200_000_000_000],
            "operating_expense": [810_000_000_000, 895_000_000_000, 1_050_000_000_000],
            "net_profit": [72_000_000_000, 85_000_000_000, 120_000_000_000],
            "total_assets": [1_850_000_000_000, 2_150_000_000_000, 2_550_000_000_000],
            "current_assets": [1_420_000_000_000, 1_680_000_000_000, 1_980_000_000_000],
            "cash_and_equiv": [180_000_000_000, 240_000_000_000, 310_000_000_000],
            "receivables": [210_000_000_000, 260_000_000_000, 300_000_000_000],
            "inventory": [980_000_000_000, 1_120_000_000_000, 1_320_000_000_000],
            "short_term_debt": [750_000_000_000, 880_000_000_000, 1_050_000_000_000],
            "total_liabilities": [1_320_000_000_000, 1_570_000_000_000, 1_850_000_000_000],
            "equity": [530_000_000_000, 580_000_000_000, 700_000_000_000],
            "operating_cash_flow": [95_000_000_000, 125_000_000_000, 160_000_000_000]
        },

        "equity_vnd": 580_000_000_000,
        "revenue_t_minus_1": 2_850_000_000_000,
        "net_profit_t_minus_1": 85_000_000_000,
        "net_profit_t_minus_2": 72_000_000_000,
        "cogs_t_minus_1": 1_850_000_000_000,
        "debt_to_equity": 2.70,
        "current_ratio": 1.40,
        "has_bad_debt_cic_24m": False,
        "is_restructured_debt": False,
        "is_special_monitoring": False,

        "net_revenue_plan": 3_400_000_000_000,
        "cogs_plan": 2_200_000_000_000,
        "operating_cost_plan": 1_050_000_000_000,
        "dio": 65.0,
        "dso": 15.0,
        "dpo": 45.0,
        "equity_participation": 180_000_000_000,
        "other_debt": 200_000_000_000,
        "import_ratio": 0.85,
        "lc_tenor_days": 90,
        "guarantee_ratio": 0.10,
        "guarantee_tenor_days": 360,
        "loan_interest_rate": 0.080,
        "ftp_cost_rate": 0.054,
        "lc_fee_rate": 0.011,
        "guarantee_fee_rate": 0.014,
        "casa_avg_balance": 25_000_000_000,
        "requested_unsecured_limit": 250_000_000_000,

        "bank_relations": [
            {"bank": "HSBC Vietnam", "facility": "Tài trợ chuỗi cung ứng quốc tế & L/C", "limit": 450_000_000_000, "debt": 240_000_000_000, "collateral": "Bảo lãnh Công ty mẹ & Tiền gửi", "status": "Nhóm 1"},
            {"bank": "Techcombank - CN Tân Bình", "facility": "Cho vay ngắn hạn mở rộng Store", "limit": 350_000_000_000, "debt": 190_000_000_000, "collateral": "Bảo lãnh cá nhân Chủ tịch & BĐS", "status": "Nhóm 1"},
            {"bank": "MSB (Đề xuất cấp mới)", "facility": "Hạn mức Tín dụng Bán lẻ & L/C Nhập khẩu", "limit": 680_000_000_000, "debt": 0, "collateral": "KTSBĐ 250 tỷ + Bảo lãnh cá nhân", "status": "Khách hàng mới"}
        ],

        "top_suppliers": [
            {"name": "Charles & Keith International Pte Ltd (Singapore)", "product": "Túi xách, Giày dép thời trang", "turnover": 950_000_000_000, "share": "43.2%", "term": "L/C UPAS 90 ngày"},
            {"name": "F&F Co., Ltd (Hàn Quốc - Chủ sở hữu MLB)", "product": "Trang phục thể thao & Mũ MLB", "turnover": 520_000_000_000, "share": "23.6%", "term": "L/C Sight"},
            {"name": "Tapestry Inc (Chủ sở hữu Thương hiệu Coach)", "product": "Túi xách cao cấp Coach", "turnover": 380_000_000_000, "share": "17.3%", "term": "T/T 60 ngày"},
            {"name": "Puma SE (Đức)", "product": "Giày dép & Thời trang thể thao Puma", "turnover": 220_000_000_000, "share": "10.0%", "term": "L/C 90 ngày"},
            {"name": "Các nhà thầu thi công nội thất cửa hàng", "product": "Setup Concept Store TTTM", "turnover": 130_000_000_000, "share": "5.9%", "term": "Thanh toán theo tiến độ"}
        ],
        "top_buyers": [
            {"name": "Khách hàng cá nhân mua trực tiếp tại chuỗi 140 Cửa hàng", "product": "Bán lẻ thời trang", "revenue": 2_350_000_000_000, "share": "69.1%", "term": "Tiền mặt / Thẻ POS / QR"},
            {"name": "Sàn TMĐT Shopee Mall & Lazada Mall", "product": "Kênh Online E-commerce", "revenue": 480_000_000_000, "share": "14.1%", "term": "Đối soát ví sàn 7-14 ngày"},
            {"name": "Kênh Online MaisonOnline.vn", "product": "Website chính hãng", "revenue": 320_000_000_000, "share": "9.4%", "term": "Cổng thanh toán trực tuyến"},
            {"name": "Khách hàng Doanh nghiệp mua Voucher quà tặng", "product": "Gift voucher & Đồng phục", "revenue": 180_000_000_000, "share": "5.3%", "term": "Chuyển khoản 100%"},
            {"name": "Kênh TikTok Shop Official", "product": "Live-stream bán hàng", "revenue": 70_000_000_000, "share": "2.1%", "term": "Đối soát 7 ngày"}
        ],

        "collaterals": [
            {"type": "Hàng tồn kho thời trang tại hệ thống Kho & Store", "desc": "Hàng hiệu chính hãng (tuổi tồn kho < 180 ngày) tại 140 điểm bán", "val_book": 850_000_000_000, "val_msb": 450_000_000_000, "ltv": "40%", "max_limit": 180_000_000_000},
            {"type": "Bảo lãnh cá nhân của Chủ tịch HĐQT & BĐS", "desc": "Bảo lãnh vô điều kiện của Bà Phạm Thị Mai Son & 02 BĐS tại Quận 2", "val_book": 150_000_000_000, "val_msb": 120_000_000_000, "ltv": "70%", "max_limit": 84_000_000_000},
            {"type": "Hạn mức KTSBĐ", "desc": "Cấp theo hạn mức uy tín chuỗi bán lẻ dẫn đầu", "val_book": 0, "val_msb": 0, "ltv": "-", "max_limit": 250_000_000_000}
        ],

        "cross_sell_plan": {
            "payroll": "Chuyển toàn bộ 1.800 nhân sự khối Store & Văn phòng sang nhận lương MSB (~30 tỷ/tháng)",
            "casa_target": "Duy trì số dư CASA dòng tiền bán lẻ hàng ngày 25 - 40 tỷ VND",
            "fx_volume": "Doanh số FX thanh toán L/C quốc tế tối thiểu 45 triệu USD/năm",
            "pos_qr": "Lắp đặt 300 máy POS & Soundbox QR MSB tại toàn bộ hệ thống 140 Store",
            "retail_cross": "Chương trình đồng thương hiệu thẻ tín dụng MSB x Maison (Hoàn tiền 10% khi mua sắm)"
        }
    }
}

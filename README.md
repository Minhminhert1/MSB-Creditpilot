# MSB CreditPilot 360 - AI Credit Proposal Copilot

Hệ thống trợ lý ảo thông minh (AI Copilot) hỗ trợ Giám đốc Quản lý Quan hệ Khách hàng (RM) tự động hóa quy trình lập **Tờ trình Đề xuất Cấp Tín dụng MB07** chuẩn ngân hàng MSB từ tài liệu doanh nghiệp.

---

## 🚀 Tính năng nổi bật

1. **Bóc tách tài liệu thông minh (AI Document Extraction)**:
   - Hỗ trợ PDF scan/ảnh (qua GreenNode Qwen Vision OCR) và PDF số (qua GreenNode GLM-5.2).
   - Tự động trích xuất giấy ĐKDN, BCTC 3 năm, Báo cáo quan hệ tín dụng CIC, thông tin ban lãnh đạo, phương án kinh doanh.
2. **Cơ chế RM Review & Canonical Facts**:
   - Mọi thông tin được chuẩn hóa theo nguyên tắc **1 Business Fact = 1 Canonical Input = Nhiều vị trí điền**.
   - RM có thể trực tiếp rà soát, chỉnh sửa hoặc bổ sung các trường thông tin cần đánh giá.
3. **Tính toán tài chính & Định chế chuẩn mực (Deterministic Engine)**:
   - Tự động tính toán PnL, cân đối vốn lưu động, hạn mức tín dụng đề xuất, thẩm quyền phê duyệt, ma trận bảo đảm theo đúng quy định ngân hàng.
4. **Bảo toàn 100% Phôi mẫu MB07 (Template Fidelity Contract)**:
   - Áp dụng cơ chế **In-Place Mutation**: Giữ nguyên toàn bộ 6 Sections, 65 Tables, 694 Paragraphs, Header/Footer, Logo Banner MSB, định dạng font Times New Roman, ô merged.

---

## 💻 Hướng dẫn Cài đặt & Chạy trên máy cá nhân

### 1. Yêu cầu môi trường
- **Python**: 3.10 trở lên (khuyến nghị Python 3.11 hoặc 3.12 / 3.14).
- **Hệ điều hành**: Windows / macOS / Linux.

### 2. Cài đặt thư viện phụ thuộc
Mở Terminal / PowerShell tại thư mục dự án và chạy:
```powershell
pip install -r requirements.txt
```

### 3. Cấu hình biến môi trường (GreenNode MaaS AI)
Sao chép tệp `.env.example` thành `.env`:
```powershell
cp .env.example .env
```
Mở `.env` và điền GreenNode API Key của bạn:
```env
APP_MODE=hackathon
AI_PROVIDER=greennode
GREENNODE_BASE_URL=https://maas-llm-aiplatform-hcm.api.vngcloud.vn/v1
GREENNODE_API_KEY=your_actual_greennode_api_key_here
GREENNODE_TEXT_MODEL=z-ai/glm-5.2-hackathon
GREENNODE_VISION_MODEL=qwen/qwen3.6-flash
ALLOW_AI_FALLBACK=false
ALLOW_HEURISTIC_EXTRACTION=false
```

---

## 🎯 Khởi chạy ứng dụng

### Cách 1: Chạy trực tiếp qua giao diện Web Copilot (Khuyến nghị)
Nhấp đúp chuột vào file:
👉 **`Chay_Tool_Copilot.bat`**

Hoặc chạy lệnh trong terminal:
```powershell
python web_copilot_app.py
```
Sau đó mở trình duyệt truy cập: **`http://localhost:8550`**

### Cách 2: Sinh nhanh Tờ trình MB07 thử nghiệm (CLI Synthetic Test)
```powershell
python scripts/generate_test_proposal.py
```
File Tờ trình sinh ra sẽ nằm tại: `output/DEMO_MB07_TO_TRINH_TIN_DUNG.docx` (đầy đủ Logo Banner MSB và 6 phần A-E).

---

## 🧪 Chạy bộ kiểm thử tự động (Test Suite)

Hệ thống đi kèm 497+ unit tests và script kiểm tra an toàn:

1. **Chạy toàn bộ 497+ tests**:
```powershell
python -m pytest tests/ -q
```

2. **Kiểm tra đối soát độ nguyên vẹn phôi MB07 (Template Fidelity)**:
```powershell
python scripts/compare_mb07_template.py "MB07 Tờ trình đề xuất cấp tín dụng (ĐVKD) - thực hiện rà soát - tái cấp.docx" "output/DEMO_MB07_TO_TRINH_TIN_DUNG.docx"
```

3. **Quét an toàn bí mật & dữ liệu nhạy cảm (Zero Secret Hits)**:
```powershell
python scripts/scan_secrets.py
```

4. **Smoke test kết nối GreenNode MaaS AI**:
```powershell
python scripts/smoke_test_greennode.py
```

---

## 📂 Cơ cấu thư mục dự án

```text
MSB-CreditPilot-360/
├── web_copilot_app.py            # Server ứng dụng Web Copilot giao diện RM
├── Chay_Tool_Copilot.bat         # File click chạy ngay trên Windows
├── requirements.txt              # Danh sách thư viện Python cần thiết
├── .env.example                  # Mẫu cấu hình API Key
├── case_input_template.json      # Schema dữ liệu hồ sơ chuẩn hoá
├── MB07... - tái cấp.docx        # Phôi Word MB07 chuẩn MSB
├── msb_eb_copilot/               # Lõi hệ thống (Engine, Adapters, Mutator, Agents)
│   ├── src/                      # Bóc tách, mapping, tính toán tài chính, safe mutation
│   ├── agents/                   # Section Agents A, B, C, D, E
│   └── template_rendering/       # OOXML safe mutation, structure guard
├── scripts/                      # Công cụ sinh test, so sánh phôi, quét secret
├── tests/                        # 497+ Unit tests kiểm thử toàn diện
└── output/                       # Thư mục chứa các Tờ trình MB07 sinh ra
```
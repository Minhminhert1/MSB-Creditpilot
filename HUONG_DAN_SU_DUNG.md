# HƯỚNG DẪN VẬN HÀNH & BÀN GIAO - MSB AI CREDIT PROPOSAL COPILOT
## BẢN THI ĐẤU HACKATHON 2026 (PHASE 1: UNIFIED ARCHITECTURE)

---

### 🏛️ 1. ĐIỂM KHỞI CHẠY DUY NHẤT (OFFICIAL COMPETITION ENTRY POINT)

Toàn bộ giải pháp vận hành tập trung qua một ứng dụng Web duy nhất:

```powershell
python web_copilot_app.py
```
*(Hoặc nhấp đúp file **`Chay_Tool_Copilot.bat`** để tự động khởi động server và mở giao diện tại `http://localhost:8550`).*

---

### ⚙️ 2. CẤU HÌNH ĐỘNG CƠ AI DUY NHẤT: GREENNODE MAAS

Hệ thống đã loại bỏ hoàn toàn các nhà cung cấp phụ (Gemini, Claude, OpenAI direct inference) và tắt hoàn toàn cơ chế tự bịa đặt dữ liệu (Heuristic Engine). Toàn bộ luồng suy luận AI sử dụng dịch vụ GreenNode MaaS (OpenAI-compatible):

* **Text / Reasoning Model**: `z-ai/glm-5.2-hackathon` (Phân tích ngữ nghĩa, trích xuất pháp lý, sinh văn phong thẩm định).
* **Vision / OCR Model**: `qwen/qwen3.6-flash` (OCR tài liệu scan/ảnh rasterized qua PDFium).
* **Base URL**: `https://maas-llm-aiplatform-hcm.api.vngcloud.vn/v1`

#### Thiết lập biến môi trường (File `.env` hoặc hệ thống):
Sao chép từ `.env.example`:
```env
APP_MODE=hackathon
AI_PROVIDER=greennode
GREENNODE_BASE_URL=https://maas-llm-aiplatform-hcm.api.vngcloud.vn/v1
GREENNODE_API_KEY=your_greennode_api_key_here
GREENNODE_TEXT_MODEL=z-ai/glm-5.2-hackathon
GREENNODE_VISION_MODEL=qwen/qwen3.6-flash
ALLOW_AI_FALLBACK=false
ALLOW_HEURISTIC_EXTRACTION=false
```

---

### 🛡️ 3. QUY TẮC CỐT LÕI (CORE PRINCIPLES)

```
GreenNode:   UNDERSTAND + EXTRACT + WRITE
Python:      VALIDATE + CALCULATE + APPLY RULES + RENDER
```

1. **NO EVIDENCE -> NO FACT**:
   - Nếu tài liệu không có bằng chứng: Để trống / `None` / `MISSING` / `DATA_GAP`.
   - Tuyệt đối không sinh dữ liệu giả định (fake revenue, fake suppliers, fake CIC).
2. **NO SILENT FALLBACK**:
   - Nếu GreenNode lỗi hoặc thiếu Key: Bắn ngoại lệ phân loại rõ ràng (`GreenNodeAuthError`, `GreenNodeRateLimitError`, `GreenNodeTimeoutError`), không âm thầm chuyển sang mock.
3. **PRESERVED VERIFIED LEGAL PIPELINE**:
   - Digital PDF $\to$ `pypdf` $\to$ Tagged Text $\to$ GreenNode `LegalDocumentExtractor` $\to$ Pydantic $\to$ Semantic Audit $\to$ `LegalDocumentMapper` $\to$ Server-Authoritative Preview $\to$ RM Review $\to$ Conflict Resolution $\to$ Canonical Case.
   - Scanned PDF $\to$ PDFium (150 DPI) $\to$ GreenNode Qwen Vision $\to$ Tagged Text.

---

### 🧪 4. KIỂM ĐỊNH & VẬN HÀNH HỆ THỐNG

#### A. Kiểm thử Offline toàn diện (173/173 Unit Tests):
```powershell
python -m pytest tests/test_legal_document_mapper.py tests/test_document_ingestion_router.py tests/test_pdf_ocr_ingestion.py tests/test_pdf_text_ingestion.py tests/test_legal_extraction.py tests/test_ai_client_greennode.py tests/test_web_copilot_preview.py tests/test_web_copilot_confirm.py tests/test_full_proposal_psd.py tests/test_full_proposal_thep_tay_do.py -v
```

#### B. Smoke Test kết nối thật tới GreenNode MaaS:
```powershell
python scripts/smoke_test_greennode.py
```
*(Đo lường độ trễ, kiểm tra model `z-ai/glm-5.2-hackathon`, thống kê token và cam kết không để lộ API Key).*

#### C. Quét an toàn mã nguồn & Bí mật (Secret Hygiene):
```powershell
python scripts/scan_secrets.py
```

#### D. Truy vấn Telemetry:
Truy cập `GET http://localhost:8550/api/telemetry` để lấy lịch sử gọi GreenNode (latency, model, token count, success status).

---

### 📁 5. CƠ CẤU THƯ MỤC CHUẨN HÓA

```
Tờ trình Tool/
├── web_copilot_app.py               # Official Competition App (Port 8550)
├── Chay_Tool_Copilot.bat            # 1-Click Launcher
├── case_input_template.json         # Canonical Schema
├── .env.example                     # Mẫu cấu hình biến môi trường
├── .gitignore                       # Chặn rò rỉ secret, key, output, cache
├── requirements.txt                 # Dependencies tinh gọn (OpenAI SDK transport)
├── HUONG_DAN_SU_DUNG.md             # Tài liệu này
├── scripts/                         # Công cụ kiểm thử & đo lường
│   ├── smoke_test_greennode.py      # Live GreenNode smoke test
│   └── scan_secrets.py              # Kiểm tra secret hygiene
├── msb_eb_copilot/                  # Core deterministic engines & GreenNode adapters
│   ├── src/                         # Extraction, Mapping, Ingestion, Engines
│   ├── agents/                      # Section Agents (A, B, C, D)
│   └── templates/                   # Mẫu Word gốc
├── tests/                           # Bộ kiểm thử tự động 173 test cases
└── legacy/                          # Các bản thử nghiệm cũ (Streamlit, prototype scripts, heuristic extractor)
```
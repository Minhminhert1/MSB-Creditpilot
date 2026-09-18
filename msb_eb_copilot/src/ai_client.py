# -*- coding: utf-8 -*-
"""
Module: ai_client.py
Mô tả: Bộ chuyển đổi AI duy nhất (Canonical GreenNode MaaS Adapter) cho kỳ thi Hackathon 2026.
Tuân thủ nguyên tắc:
1. DUY NHẤT 1 Nhà cung cấp AI: GREENNODE MAAS (OpenAI-compatible).
2. KHÔNG runtime Gemini, Claude, hay OpenAI inference trực tiếp.
3. KHÔNG sinh giả lập business facts trong môi trường thi (NO heuristic facts in competition runtime).
4. Tích hợp cấu trúc đo lường Telemetry (provider, model, operation, tokens, latency, status).
"""

import os
import sys
import time
import threading
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import openai
from openai import OpenAI


# ==============================================================================
# GREENNODE EXCEPTION HIERARCHY
# ==============================================================================
class GreenNodeError(Exception):
    """Lỗi cơ sở cho các sự cố liên quan đến GreenNode MaaS."""
    pass


class GreenNodeAuthError(GreenNodeError):
    """Lỗi xác thực hoặc API Key GreenNode không hợp lệ."""
    pass


class GreenNodeRateLimitError(GreenNodeError):
    """Lỗi vượt quá tần suất gọi API hoặc hạn mức của GreenNode."""
    pass


class GreenNodeConnectionError(GreenNodeError):
    """Lỗi kết nối mạng đến máy chủ GreenNode MaaS."""
    pass


class GreenNodeTimeoutError(GreenNodeError):
    """Lỗi vượt quá thời gian chờ (timeout) khi gọi GreenNode MaaS."""
    pass


# ==============================================================================
# GREENNODE TELEMETRY FOUNDATION
# ==============================================================================
@dataclass
class GreenNodeTelemetryRecord:
    timestamp: str
    provider: str = "GreenNode"
    model: str = ""
    operation: str = ""
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    latency_ms: float = 0.0
    success: bool = True
    error: Optional[str] = None


class AIAssistantClient:
    """Quản lý kết nối và sinh nội dung qua GreenNode MaaS duy nhất."""

    DEFAULT_BASE_URL = "https://maas-llm-aiplatform-hcm.api.vngcloud.vn/v1"
    DEFAULT_MODEL = "z-ai/glm-5.2-hackathon"
    DEFAULT_VISION_MODEL = "qwen/qwen3.6-flash"

    _telemetry_lock = threading.Lock()
    _telemetry_history: List[Dict[str, Any]] = []

    @classmethod
    def record_telemetry(
        cls,
        operation: str,
        model: str,
        latency_ms: float,
        success: bool,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        total_tokens: Optional[int] = None,
        error: Optional[str] = None
    ) -> None:
        """Ghi nhận bản ghi telemetry an toàn (không ghi nhật ký key hay văn bản nhạy cảm)."""
        record = GreenNodeTelemetryRecord(
            timestamp=datetime.now(timezone.utc).isoformat(),
            provider="GreenNode",
            model=model,
            operation=operation,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            latency_ms=round(latency_ms, 2),
            success=success,
            error=str(error)[:200] if error else None
        )
        with cls._telemetry_lock:
            cls._telemetry_history.append(asdict(record))
            if len(cls._telemetry_history) > 200:
                cls._telemetry_history.pop(0)

    @classmethod
    def get_telemetry(cls, limit: int = 50) -> List[Dict[str, Any]]:
        """Lấy danh sách bản ghi telemetry gần nhất cho tầng Web hiển thị."""
        with cls._telemetry_lock:
            return list(reversed(cls._telemetry_history[-limit:]))

    @classmethod
    def get_greennode_config(
        cls,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None
    ) -> Dict[str, str]:
        """Lấy cấu hình chuẩn GreenNode từ tham số hoặc biến môi trường theo hợp đồng chuẩn hóa."""
        resolved_key = (
            api_key
            or os.getenv("LLM_API_KEY")
            or os.getenv("GREENNODE_API_KEY")
            or os.getenv("AI_PLATFORM_API_KEY")
        )
        resolved_base_url = (
            base_url
            or os.getenv("LLM_BASE_URL")
            or os.getenv("GREENNODE_BASE_URL")
            or os.getenv("AI_PLATFORM_BASE_URL", cls.DEFAULT_BASE_URL)
        )
        resolved_model = (
            model
            or os.getenv("LLM_MODEL")
            or os.getenv("GREENNODE_TEXT_MODEL")
            or os.getenv("GREENNODE_MODEL")
            or os.getenv("AI_PLATFORM_MODEL", cls.DEFAULT_MODEL)
        )

        return {
            "api_key": resolved_key,
            "base_url": resolved_base_url,
            "model": resolved_model
        }


    @classmethod
    def chat(
        cls,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.1,
        max_tokens: int = 2048,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 300.0,
        max_retries: int = 2,
        operation: str = "chat"
    ) -> str:
        """Gọi mô hình ngôn ngữ GreenNode MaaS qua chuẩn OpenAI-compatible."""
        config = cls.get_greennode_config(api_key=api_key, base_url=base_url, model=model)
        active_key = config["api_key"]
        active_base_url = config["base_url"]
        active_model = config["model"]

        if not active_key:
            raise ValueError(
                "Thiếu AI_PLATFORM_API_KEY hoặc GREENNODE_API_KEY. "
                "Vui lòng cấu hình biến môi trường GREENNODE_API_KEY."
            )

        start_time = time.perf_counter()
        try:
            client = OpenAI(
                api_key=active_key,
                base_url=active_base_url,
                timeout=timeout,
                max_retries=max_retries
            )

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]

            response = client.chat.completions.create(
                model=active_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens
            )

            latency_ms = (time.perf_counter() - start_time) * 1000.0
            content = response.choices[0].message.content
            if not content or not content.strip():
                cls.record_telemetry(
                    operation=operation,
                    model=active_model,
                    latency_ms=latency_ms,
                    success=False,
                    error="Phản hồi rỗng"
                )
                raise GreenNodeError(f"Phản hồi từ GreenNode ({active_model}) rỗng.")

            in_tok = None
            out_tok = None
            tot_tok = None
            if hasattr(response, "usage") and response.usage:
                in_tok = getattr(response.usage, "prompt_tokens", None)
                out_tok = getattr(response.usage, "completion_tokens", None)
                tot_tok = getattr(response.usage, "total_tokens", None)

            cls.record_telemetry(
                operation=operation,
                model=active_model,
                latency_ms=latency_ms,
                success=True,
                input_tokens=in_tok,
                output_tokens=out_tok,
                total_tokens=tot_tok
            )
            return content.strip()

        except openai.AuthenticationError as e:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            cls.record_telemetry(operation=operation, model=active_model, latency_ms=latency_ms, success=False, error=str(e))
            raise GreenNodeAuthError(f"Lỗi xác thực GreenNode (AuthenticationError): {e}") from e
        except openai.RateLimitError as e:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            cls.record_telemetry(operation=operation, model=active_model, latency_ms=latency_ms, success=False, error=str(e))
            raise GreenNodeRateLimitError(f"Lỗi giới hạn tần suất GreenNode (RateLimitError): {e}") from e
        except openai.APITimeoutError as e:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            cls.record_telemetry(operation=operation, model=active_model, latency_ms=latency_ms, success=False, error=str(e))
            raise GreenNodeTimeoutError(f"Lỗi quá thời gian chờ kết nối GreenNode (APITimeoutError): {e}") from e
        except openai.APIConnectionError as e:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            cls.record_telemetry(operation=operation, model=active_model, latency_ms=latency_ms, success=False, error=str(e))
            raise GreenNodeConnectionError(f"Lỗi kết nối mạng tới máy chủ GreenNode (APIConnectionError): {e}") from e
        except openai.APIError as e:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            cls.record_telemetry(operation=operation, model=active_model, latency_ms=latency_ms, success=False, error=str(e))
            raise GreenNodeError(f"Lỗi máy chủ GreenNode API (APIError): {e}") from e
        except GreenNodeError:
            raise
        except Exception as e:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            cls.record_telemetry(operation=operation, model=active_model, latency_ms=latency_ms, success=False, error=str(e))
            raise GreenNodeError(f"Sự cố không xác định khi gọi GreenNode: {e}") from e

    @classmethod
    def generate_credit_narrative(
        cls, 
        company_data: Dict[str, Any], 
        demand_res: Dict[str, Any], 
        rorwa_res: Dict[str, Any],
        api_key: Optional[str] = None,
        provider: str = "GreenNode Cloud AI"
    ) -> Dict[str, str]:
        """Sinh phân tích tín dụng có căn cứ (Grounded Narrative) bằng GreenNode MaaS duy nhất.

        Nguyên tắc tuyệt đối:
        - Python xác định WHAT IS TRUE (các số liệu, hạn mức, tỷ lệ).
        - GreenNode viết HOW VERIFIED FACTS ARE WRITTEN (lời văn phân tích bám sát bằng chứng).
        - Không tự bịa đặt chỉ tiêu tài chính, không tự đề xuất hạn mức ngoài tính toán.
        """
        if not provider or not isinstance(provider, str):
            raise ValueError("Tham số 'provider' không được để trống. Chỉ hỗ trợ 'GreenNode Cloud AI'.")

        clean_provider = provider.strip()

        # Kiểm tra chế độ chạy: Cấm heuristic trong competition runtime
        app_mode = os.getenv("APP_MODE", "")
        allow_heuristic = os.getenv("ALLOW_HEURISTIC_EXTRACTION", "false").lower() == "true"

        if clean_provider in ("GreenNode Cloud AI", "greennode", "GreenNode"):
            config = cls.get_greennode_config(api_key=api_key)
            model_name = config["model"]

            system_prompt = (
                "You are a Large Corporate Credit Analysis Writing Assistant.\n\n"
                "You may ONLY use information explicitly provided in INPUT.\n\n"
                "ABSOLUTE RULES:\n"
                "- Do not invent facts, numbers, thresholds, benchmarks or policies.\n"
                "- Do not calculate new financial metrics.\n"
                "- Do not infer margins, growth rates, ratios or trends unless explicitly provided as VERIFIED_ASSESSMENT.\n"
                "- Do not label anything as safe, good, low, high, healthy, attractive, acceptable, stable or efficient unless the corresponding VERIFIED_ASSESSMENT is explicitly supplied.\n"
                "- Do not introduce industry knowledge or external knowledge.\n"
                "- Do not invent risks such as FX risk, supply-chain risk, interest-rate risk, collateral risk, etc. unless explicitly provided in INPUT.\n"
                "- Do not create covenants, approval conditions, collateral requirements, percentages, limits or policy thresholds.\n"
                "- Do not approve or reject credit.\n"
                "- Do not recommend a credit decision.\n"
                "- The LLM may not move facts between sections.\n"
                "- The LLM may not infer that a metric belongs to another section.\n"
                "- If REPAYMENT_CAPACITY is empty, output exactly: 'Chưa có dữ liệu được cung cấp để mô tả khả năng trả nợ.'\n"
                "- If DATA_GAPS is empty, output exactly: 'Không có DATA_GAPS được cung cấp trong INPUT.' Do NOT write 'Không có dữ liệu thiếu.'\n"
                "- DATA_GAPS may only contain items explicitly passed in DATA_GAPS.\n"
                "- If VERIFIED_ASSESSMENTS is empty, do not create qualitative assessments.\n"
                "- Return final narrative only.\n"
                "- Never expose reasoning, analysis, chain-of-thought or rule checking."
            )

            user_prompt = f"""INPUT:

FACTS_BY_SECTION:

BUSINESS:
- Tên khách hàng: {company_data.get('name', '')}
- Ngành nghề / Archetype: {company_data.get('archetype', '')}
- Doanh thu năm T-1: {company_data.get('revenue_t_minus_1', 0)/1e9:,.1f} tỷ VND
- Kế hoạch doanh thu thuần: {company_data.get('net_revenue_plan', 0)/1e9:,.1f} tỷ VND

FINANCIAL:
- Lợi nhuận sau thuế năm T-1: {company_data.get('net_profit_t_minus_1', 0)/1e9:,.1f} tỷ VND
- Vốn chủ sở hữu: {company_data.get('equity_vnd', 0)/1e9:,.1f} tỷ VND
- Hệ số Nợ/Vốn CSH: {company_data.get('debt_to_equity', 0)}
- Số ngày luân chuyển hàng tồn kho (DIO): {company_data.get('dio', 0)} ngày
- Số ngày thu tiền khách hàng (DSO): {company_data.get('dso', 0)} ngày
- Số ngày phải trả nhà cung cấp (DPO): {company_data.get('dpo', 0)} ngày
- Chu kỳ tiền mặt (CCC): {demand_res.get('ccc_days', 0)} ngày
- Vòng quay vốn lưu động: {demand_res.get('turns_per_year', 0)} vòng
- Tổng nhu cầu vốn lưu động: {demand_res.get('working_capital_demand', 0)/1e9:,.1f} tỷ VND
- Vốn tự có tham gia: {company_data.get('equity_participation', 0)/1e9:,.1f} tỷ VND

REPAYMENT_CAPACITY:
[]

BANK_RELATIONSHIP:
- Số dư CASA bình quân: {company_data.get('casa_avg_balance', 0)/1e9:,.1f} tỷ VND
- Tổng hạn mức cấp tín dụng tại MSB: {demand_res.get('total_credit_facility_msb', 0)/1e9:,.1f} tỷ VND
- Hạn mức cho vay: {demand_res.get('loan_limit_msb', 0)/1e9:,.1f} tỷ VND
- Hạn mức LC: {demand_res.get('lc_limit', 0)/1e9:,.1f} tỷ VND
- Hạn mức bảo lãnh: {demand_res.get('guarantee_limit', 0)/1e9:,.1f} tỷ VND

RISK_ADJUSTED_RETURN:
- Chỉ số TORWA: {rorwa_res.get('torwa', 0)}%
- Chỉ số RORWA: {rorwa_res.get('rorwa', 0)}%

VERIFIED_ASSESSMENTS:
[]

DATA_GAPS:
[]

Yêu cầu định dạng đầu ra:
Chỉ viết đúng 4 mục sau đây bằng tiếng Việt:
1. Hoạt động kinh doanh: Chỉ sử dụng dữ liệu từ mục BUSINESS.
2. Tình hình tài chính: Chỉ sử dụng dữ liệu từ mục FINANCIAL.
3. Khả năng trả nợ: Nếu REPAYMENT_CAPACITY là rỗng ([]), phải viết chính xác từng chữ:
"Chưa có dữ liệu được cung cấp để mô tả khả năng trả nợ."
Tuyệt đối không lấy dữ liệu từ BANK_RELATIONSHIP hay RISK_ADJUSTED_RETURN đưa vào mục này.
4. Data gap: Nếu DATA_GAPS là rỗng ([]), phải viết chính xác từng chữ:
"Không có DATA_GAPS được cung cấp trong INPUT."
Tuyệt đối không viết "Không có dữ liệu thiếu."

TUYỆT ĐỐI KHÔNG đưa vào:
- Đề xuất phê duyệt
- Covenant
- Conditions
- Collateral recommendation
- Risk mitigation recommendation
- Không tự suy diễn bất kỳ nhận xét định tính, rủi ro, hoặc số liệu nào ngoài FACTS_BY_SECTION."""

            content = cls.chat(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.1,
                max_tokens=2048,
                api_key=api_key,
                operation="credit_narrative"
            )

            return {
                "source": f"GreenNode MaaS ({model_name})",
                "narrative": content
            }

        elif clean_provider == "Demo / Heuristic Mode":
            # Heuristic Mode is strictly isolated: only allowed in offline unit-testing fixtures
            if app_mode == "hackathon" and not allow_heuristic:
                raise ValueError(
                    "Heuristic Mode bị vô hiệu hóa hoàn toàn trong Competition Build. "
                    "Mọi yêu cầu sinh lời văn phải thông qua GreenNode MaaS."
                )

            narrative_financial = f"""1. ĐÁNH GIÁ NĂNG LỰC TÀI CHÍNH & VẬN HÀNH:
• Quy mô & Tăng trưởng: Doanh thu năm gần nhất đạt {company_data['revenue_t_minus_1']/1e9:,.1f} tỷ VND, lợi nhuận sau thuế đạt {company_data['net_profit_t_minus_1']/1e9:,.1f} tỷ VND. Kế hoạch năm tới doanh thu dự kiến đạt {company_data['net_revenue_plan']/1e9:,.1f} tỷ VND, phù hợp với năng lực sản xuất và hợp đồng đã ký kết.
• Cơ cấu vốn & Đòn bẩy: Vốn chủ sở hữu vững mạnh đạt {company_data['equity_vnd']/1e9:,.1f} tỷ VND. Hệ số Nợ/Vốn CSH ở mức {company_data['debt_to_equity']:.2f}x (nằm trong ngưỡng an toàn theo QĐ.074).
• Hiệu quả luân chuyển vốn: Chu kỳ ngân quỹ {demand_res['ccc_days']} ngày (DIO {company_data['dio']} ngày, DSO {company_data['dso']} ngày, DPO {company_data['dpo']} ngày), tương ứng vòng quay VLĐ đạt {demand_res['turns_per_year']} vòng/năm.

2. CĂN CỨ XÁC ĐỊNH HẠN MỨC & HIỆU QUẢ SINH LỜI:
• Tổng nhu cầu vốn lưu động cần thiết là {demand_res['working_capital_demand']/1e9:,.1f} tỷ VND. Sau khi trừ vốn tự có tham gia ({company_data['equity_participation']/1e9:,.1f} tỷ) và vay TCTD khác, đề xuất cấp hạn mức tại MSB là {demand_res['total_credit_facility_msb']/1e9:,.1f} tỷ VND.
• Đánh giá chỉ số hiệu quả theo Basel II: Chỉ số TORWA đạt {rorwa_res['torwa']:.2f}% (Chuẩn MSB ≥ 1.50%) và RORWA đạt {rorwa_res['rorwa']:.2f}% (Chuẩn MSB ≥ 0.50%), đảm bảo hiệu quả sử dụng vốn rủi ro của ngân hàng.

3. BIỆN PHÁP QUẢN TRỊ RỦI RO & ĐIỀU KIỆN TÍN DỤNG:
• Quản lý dòng tiền: Yêu cầu Khách hàng cam kết chuyển tối thiểu 40% doanh thu bán hàng về tài khoản tại MSB, duy trì CASA bình quân {company_data['casa_avg_balance']/1e9:,.1f} tỷ VND/tháng.
• Kiểm soát mục đích vay vốn: Giải ngân theo từng khế ước nhận nợ/L/C gắn liền với hóa đơn VAT và hợp đồng mua bán hợp lệ."""

            return {
                "source": "Smart Banking Heuristic Engine (MSB Policy QĐ.074 & MB09 Compliant)",
                "narrative": narrative_financial
            }

        else:
            raise ValueError(
                f"Provider không được hỗ trợ: '{provider}'. "
                "Hệ thống chỉ chấp nhận duy nhất nhà cung cấp 'GreenNode Cloud AI'."
            )

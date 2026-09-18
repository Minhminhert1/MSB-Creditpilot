#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script: scripts/smoke_test_greennode.py
Mô tả: Kiểm tra kết nối THẬT tới máy chủ GreenNode MaaS (OpenAI-compatible endpoint)
      sử dụng mô hình z-ai/glm-5.2-hackathon.

Yêu cầu an toàn:
- Tuyệt đối KHÔNG in API Key ra màn hình hoặc log.
- Đo lường độ trễ (latency) và thống kê token tiêu thụ nếu có.
- Trả về mã thoát 0 khi thành công, 1 khi thất bại.
"""

import os
import sys
import time

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import openai
from openai import OpenAI

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def run_smoke_test(timeout_sec: float = 30.0) -> bool:
    # 1. Đọc cấu hình từ biến môi trường
    api_key = (
        os.getenv("LLM_API_KEY")
        or os.getenv("GREENNODE_API_KEY")
        or os.getenv("AI_PLATFORM_API_KEY")
    )
    base_url = (
        os.getenv("LLM_BASE_URL")
        or os.getenv("GREENNODE_BASE_URL")
        or os.getenv("AI_PLATFORM_BASE_URL")
        or "https://maas-llm-aiplatform-hcm.api.vngcloud.vn/v1"
    )
    model = (
        os.getenv("LLM_MODEL")
        or os.getenv("GREENNODE_TEXT_MODEL")
        or os.getenv("GREENNODE_MODEL")
        or os.getenv("AI_PLATFORM_MODEL")
        or "z-ai/glm-5.2-hackathon"
    )

    print("=" * 60)
    print("   GREENNODE MAAS LIVE SMOKE TEST (PHASE 1)")
    print("=" * 60)
    print(f"Provider    : GreenNode MaaS (OpenAI-compatible)")
    print(f"Base URL    : {base_url}")
    print(f"Model       : {model}")
    print(f"API Key     : {'[PRESENT - LENGTH ' + str(len(api_key)) + ']' if api_key else '[MISSING]'}")
    print("-" * 60)

    if not api_key:
        print("[!] KẾT QUẢ: FAILURE")
        print("[!] Lý do: Thiếu biến môi trường GREENNODE_API_KEY (hoặc AI_PLATFORM_API_KEY).")
        print("[!] Hướng dẫn: Đặt GREENNODE_API_KEY trong môi trường hoặc file .env.")
        return False

    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=timeout_sec,
        max_retries=1
    )

    start_time = time.perf_counter()
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "You are a test assistant. Answer with exactly one word."
                },
                {
                    "role": "user",
                    "content": "Ping"
                }
            ],
            temperature=0.0,
            max_tokens=30
        )
        latency_ms = (time.perf_counter() - start_time) * 1000.0

        content = response.choices[0].message.content or ""
        content_clean = content.strip().replace("\n", " ")

        print(f"[+] Phản hồi: {content_clean[:60]}")
        print(f"[+] Độ trễ  : {latency_ms:.1f} ms")

        if hasattr(response, "usage") and response.usage:
            usage = response.usage
            prompt_tokens = getattr(usage, "prompt_tokens", "N/A")
            comp_tokens = getattr(usage, "completion_tokens", "N/A")
            total_tokens = getattr(usage, "total_tokens", "N/A")
            print(f"[+] Token   : Input={prompt_tokens}, Output={comp_tokens}, Total={total_tokens}")

        print("-" * 60)
        print("[✓] KẾT QUẢ : SUCCESS - GreenNode MaaS hoạt động hoàn hảo!")
        return True

    except openai.AuthenticationError as e:
        latency_ms = (time.perf_counter() - start_time) * 1000.0
        print(f"[!] Độ trễ  : {latency_ms:.1f} ms")
        print(f"[!] KẾT QUẢ : FAILURE - Lỗi xác thực API Key (401 AuthenticationError)")
        print(f"[!] Chi tiết: {e}")
        return False
    except openai.APITimeoutError as e:
        latency_ms = (time.perf_counter() - start_time) * 1000.0
        print(f"[!] Độ trễ  : {latency_ms:.1f} ms")
        print(f"[!] KẾT QUẢ : FAILURE - Quá thời gian chờ (Timeout sau {timeout_sec}s)")
        print(f"[!] Chi tiết: {e}")
        return False
    except openai.APIConnectionError as e:
        latency_ms = (time.perf_counter() - start_time) * 1000.0
        print(f"[!] Độ trễ  : {latency_ms:.1f} ms")
        print(f"[!] KẾT QUẢ : FAILURE - Lỗi kết nối mạng tới {base_url}")
        print(f"[!] Chi tiết: {e}")
        return False
    except Exception as e:
        latency_ms = (time.perf_counter() - start_time) * 1000.0
        print(f"[!] Độ trễ  : {latency_ms:.1f} ms")
        print(f"[!] KẾT QUẢ : FAILURE - Lỗi ({type(e).__name__})")
        print(f"[!] Chi tiết: {e}")
        return False


if __name__ == "__main__":
    success = run_smoke_test()
    sys.exit(0 if success else 1)

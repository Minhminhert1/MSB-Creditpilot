#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bộ kiểm thử đơn vị cho ai_client.py:
1. Xác minh Demo / Heuristic Mode trả về đúng dữ liệu.
2. Xác minh provider rỗng/không hợp lệ ném ValueError.
3. Xác minh GreenNode Cloud AI ném ValueError khi thiếu API Key (không silent fallback).
4. Xác minh GreenNode Cloud AI ném đúng Typed Exceptions khi API lỗi.
5. Xác minh GreenNode Cloud AI ném GreenNodeError khi content rỗng.
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# Đảm bảo mã hóa console
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from msb_eb_copilot.src.ai_client import (
    AIAssistantClient,
    GreenNodeError,
    GreenNodeAuthError,
    GreenNodeRateLimitError,
    GreenNodeConnectionError,
    GreenNodeTimeoutError
)
import openai


class TestAIClientGreenNodeIntegration(unittest.TestCase):

    def setUp(self):
        self.company_data = {
            "name": "CTCP DỊCH VỤ PHÂN PHỐI TỔNG HỢP DẦU KHÍ",
            "archetype": "Phân phối CNTT",
            "revenue_t_minus_1": 7819398000000,
            "net_profit_t_minus_1": 125000000000,
            "equity_vnd": 518279000000,
            "debt_to_equity": 2.1,
            "net_revenue_plan": 8500000000000,
            "dio": 35,
            "dso": 45,
            "dpo": 40,
            "casa_avg_balance": 50000000000,
            "equity_participation": 150000000000
        }
        self.demand_res = {
            "total_credit_facility_msb": 700000000000,
            "loan_limit_msb": 250000000000,
            "lc_limit": 50000000000,
            "guarantee_limit": 30000000000,
            "turns_per_year": 9.2,
            "ccc_days": 40,
            "working_capital_demand": 950000000000
        }
        self.rorwa_res = {
            "torwa": 2.15,
            "rorwa": 0.85
        }

    def test_01_explicit_heuristic_mode(self):
        """1. Demo / Heuristic Mode trả về đúng source và nội dung Heuristic chuẩn MSB (khi được bật cho test fixture)."""
        with patch.dict(os.environ, {"ALLOW_HEURISTIC_EXTRACTION": "true"}):
            res = AIAssistantClient.generate_credit_narrative(
                company_data=self.company_data,
                demand_res=self.demand_res,
                rorwa_res=self.rorwa_res,
                provider="Demo / Heuristic Mode"
            )
            self.assertIn("Smart Banking Heuristic Engine", res["source"])
            self.assertIn("ĐÁNH GIÁ NĂNG LỰC TÀI CHÍNH & VẬN HÀNH", res["narrative"])
            self.assertIn("CĂN CỨ XÁC ĐỊNH HẠN MỨC", res["narrative"])

    def test_02_invalid_or_empty_provider_raises_value_error(self):
        """2. Provider rỗng, lạ hoặc không hỗ trợ phải bắn ValueError, KHÔNG fallback."""
        with self.assertRaises(ValueError):
            AIAssistantClient.generate_credit_narrative(
                company_data=self.company_data,
                demand_res=self.demand_res,
                rorwa_res=self.rorwa_res,
                provider=""
            )

        with self.assertRaises(ValueError):
            AIAssistantClient.generate_credit_narrative(
                company_data=self.company_data,
                demand_res=self.demand_res,
                rorwa_res=self.rorwa_res,
                provider="UnknownProvider"
            )

    def test_03_greennode_missing_api_key_raises_value_error(self):
        """3. GreenNode Cloud AI thiếu key phải bắn ValueError, KHÔNG trả về Heuristic."""
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError) as ctx:
                AIAssistantClient.generate_credit_narrative(
                    company_data=self.company_data,
                    demand_res=self.demand_res,
                    rorwa_res=self.rorwa_res,
                    api_key=None,
                    provider="GreenNode Cloud AI"
                )
            self.assertIn("Thiếu AI_PLATFORM_API_KEY", str(ctx.exception))

    @patch("openai.resources.chat.completions.Completions.create")
    def test_04_greennode_success(self, mock_create):
        """4. GreenNode trả về kết quả hợp lệ với role='system' và role='user'."""
        mock_resp = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "Đánh giá tín dụng chi tiết từ GreenNode LLM."
        mock_resp.choices = [mock_choice]
        mock_create.return_value = mock_resp

        res = AIAssistantClient.generate_credit_narrative(
            company_data=self.company_data,
            demand_res=self.demand_res,
            rorwa_res=self.rorwa_res,
            api_key="mock_valid_key",
            provider="GreenNode Cloud AI"
        )

        self.assertIn("GreenNode MaaS", res["source"])
        self.assertEqual(res["narrative"], "Đánh giá tín dụng chi tiết từ GreenNode LLM.")
        
        # Kiểm tra messages được gửi đi
        called_messages = mock_create.call_args[1]["messages"]
        self.assertEqual(called_messages[0]["role"], "system")
        self.assertEqual(called_messages[1]["role"], "user")

    @patch("openai.resources.chat.completions.Completions.create")
    def test_05_greennode_empty_response_raises_greennode_error(self, mock_create):
        """5. Phản hồi rỗng phải bắn GreenNodeError."""
        mock_resp = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "   "
        mock_resp.choices = [mock_choice]
        mock_create.return_value = mock_resp

        with self.assertRaises(GreenNodeError) as ctx:
            AIAssistantClient.chat(
                system_prompt="sys",
                user_prompt="usr",
                api_key="mock_key"
            )
        self.assertIn("rỗng", str(ctx.exception))

    @patch("openai.resources.chat.completions.Completions.create")
    def test_06_greennode_auth_error_mapping(self, mock_create):
        """6. OpenAI AuthenticationError -> GreenNodeAuthError."""
        mock_create.side_effect = openai.AuthenticationError("Invalid API Key", response=MagicMock(status_code=401), body=None)

        with self.assertRaises(GreenNodeAuthError):
            AIAssistantClient.chat(
                system_prompt="sys",
                user_prompt="usr",
                api_key="invalid_key"
            )

    @patch("openai.resources.chat.completions.Completions.create")
    def test_07_greennode_rate_limit_mapping(self, mock_create):
        """7. OpenAI RateLimitError -> GreenNodeRateLimitError."""
        mock_create.side_effect = openai.RateLimitError("Rate limit reached", response=MagicMock(status_code=429), body=None)

        with self.assertRaises(GreenNodeRateLimitError):
            AIAssistantClient.chat(
                system_prompt="sys",
                user_prompt="usr",
                api_key="test_key"
            )

    @patch("openai.resources.chat.completions.Completions.create")
    def test_08_greennode_connection_and_timeout_mapping(self, mock_create):
        """8. Timeout & Connection Error mapping."""
        mock_create.side_effect = openai.APITimeoutError(request=MagicMock())
        with self.assertRaises(GreenNodeTimeoutError):
            AIAssistantClient.chat(
                system_prompt="sys",
                user_prompt="usr",
                api_key="test_key"
            )

        mock_create.side_effect = openai.APIConnectionError(request=MagicMock())
        with self.assertRaises(GreenNodeConnectionError):
            AIAssistantClient.chat(
                system_prompt="sys",
                user_prompt="usr",
                api_key="test_key"
            )

    def test_09_heuristic_blocked_in_hackathon_mode(self):
        """9. Heuristic Mode bị chặn hoàn toàn khi APP_MODE=hackathon."""
        with patch.dict(os.environ, {"APP_MODE": "hackathon", "ALLOW_HEURISTIC_EXTRACTION": "false"}):
            with self.assertRaises(ValueError) as ctx:
                AIAssistantClient.generate_credit_narrative(
                    company_data=self.company_data,
                    demand_res=self.demand_res,
                    rorwa_res=self.rorwa_res,
                    provider="Demo / Heuristic Mode"
                )
            self.assertIn("bị vô hiệu hóa", str(ctx.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)

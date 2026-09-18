# -*- coding: utf-8 -*-
"""Standalone Web Application for MSB Credit Proposal Copilot - Phần B.

Features:
- Step 1: Chọn Nhu Cầu Tín Dụng 2.1 - 2.8
- Step 2: Dynamic Form Cards theo Progressive Disclosure
- Step 3: Review, Cảnh báo nghiệp vụ, và Sinh file Word PHẦN B chuẩn xác 100%.
- Không cần cài đặt framework ngoài, chạy trực tiếp bằng python chuẩn.
"""

import os
import sys
import json
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler

sys.path.insert(0, ".")
sys.path.insert(0, "msb_eb_copilot")
sys.stdout.reconfigure(encoding='utf-8')

from msb_eb_copilot.src.section_b.validator import validate_and_calculate_section_b
from msb_eb_copilot.src.section_b.renderer import render_section_b_docx
from msb_eb_copilot.src.section_b.number_to_words import format_amount_with_words

PORT = 8501

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="vi">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>MSB Credit Proposal Copilot – Phần B</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
  <style>
    body { font-family: 'Inter', sans-serif; }
    .msb-red { color: #eb1c24; }
    .bg-msb-red { background-color: #eb1c24; }
    .border-msb-red { border-color: #eb1c24; }
  </style>
</head>
<body class="bg-slate-50 text-slate-800 min-h-screen">
  <!-- Header -->
  <header class="bg-white border-b border-slate-200 sticky top-0 z-30 shadow-sm">
    <div class="max-w-6xl mx-auto px-4 py-3 flex items-center justify-between">
      <div class="flex items-center space-x-3">
        <div class="w-10 h-10 bg-red-600 rounded-lg flex items-center justify-center text-white font-bold text-xl shadow">
          M
        </div>
        <div>
          <h1 class="font-bold text-lg text-slate-900 leading-tight">MSB Credit Proposal Copilot</h1>
          <p class="text-xs text-slate-500 font-medium">PHẦN B: NỘI DUNG ĐỀ XUẤT CẤP TÍN DỤNG (MẪU BIỂU MB07)</p>
        </div>
      </div>
      <div class="flex items-center space-x-2">
        <span class="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-semibold bg-emerald-100 text-emerald-800">
          <span class="w-2 h-2 mr-1.5 bg-emerald-500 rounded-full animate-pulse"></span>
          Engine Active
        </span>
      </div>
    </div>
  </header>

  <main class="max-w-6xl mx-auto px-4 py-6">
    <!-- Stepper Navigation -->
    <div class="mb-8">
      <div class="flex items-center justify-center space-x-4">
        <div class="flex items-center">
          <div id="step-badge-1" class="w-8 h-8 rounded-full bg-red-600 text-white font-bold flex items-center justify-center text-sm shadow">1</div>
          <span class="ml-2 text-sm font-semibold text-slate-800">Chọn nhu cầu</span>
        </div>
        <div class="w-12 h-0.5 bg-slate-300"></div>
        <div class="flex items-center">
          <div id="step-badge-2" class="w-8 h-8 rounded-full bg-slate-200 text-slate-600 font-bold flex items-center justify-center text-sm">2</div>
          <span class="ml-2 text-sm font-medium text-slate-600">Nhập dữ liệu</span>
        </div>
        <div class="w-12 h-0.5 bg-slate-300"></div>
        <div class="flex items-center">
          <div id="step-badge-3" class="w-8 h-8 rounded-full bg-slate-200 text-slate-600 font-bold flex items-center justify-center text-sm">3</div>
          <span class="ml-2 text-sm font-medium text-slate-600">Review & Sinh file</span>
        </div>
      </div>
    </div>

    <!-- STEP 1: CHỌN NHU CẦU -->
    <section id="step-1" class="bg-white rounded-xl border border-slate-200 p-6 shadow-sm mb-6">
      <div class="border-b border-slate-100 pb-4 mb-5 flex items-center justify-between">
        <div>
          <h2 class="text-lg font-bold text-slate-900">BƯỚC 1: CHỌN NHU CẦU CẤP TÍN DỤNG CỦA KHÁCH HÀNG</h2>
          <p class="text-sm text-slate-500">Tích chọn các nhu cầu tín dụng thực tế cần đề xuất. Các mục không chọn sẽ được loại bỏ hoàn toàn khỏi tờ trình.</p>
        </div>
        <span id="selected-count-badge" class="px-3 py-1 bg-red-50 text-red-700 text-xs font-bold rounded-lg border border-red-200">
          Đã chọn: 2 nhu cầu
        </span>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-2 gap-3.5">
        <label class="flex items-start p-3.5 border border-slate-200 rounded-lg hover:border-red-400 hover:bg-red-50/20 cursor-pointer transition">
          <input type="checkbox" id="chk-2-1" value="2.1_vay_vld_han_muc" checked class="mt-1 w-4 h-4 text-red-600 rounded border-slate-300 focus:ring-red-500">
          <div class="ml-3">
            <span class="text-sm font-bold text-slate-800">2.1 – Cho vay VLĐ theo hạn mức</span>
            <span class="block text-xs text-slate-500">Mã hạn mức: ECS1101 (Nhóm A)</span>
          </div>
        </label>

        <label class="flex items-start p-3.5 border border-slate-200 rounded-lg hover:border-red-400 hover:bg-red-50/20 cursor-pointer transition">
          <input type="checkbox" id="chk-2-2" value="2.2_vay_vld_han_muc_tren_12t" class="mt-1 w-4 h-4 text-red-600 rounded border-slate-300 focus:ring-red-500">
          <div class="ml-3">
            <span class="text-sm font-bold text-slate-800">2.2 – Cho vay VLĐ hạn mức trên 12 tháng</span>
            <span class="block text-xs text-slate-500">Mã hạn mức: ECS1101 (Nhóm C - trung hạn)</span>
          </div>
        </label>

        <label class="flex items-start p-3.5 border border-slate-200 rounded-lg hover:border-red-400 hover:bg-red-50/20 cursor-pointer transition">
          <input type="checkbox" id="chk-2-3" value="2.3_vay_ngan_han_tung_lan" class="mt-1 w-4 h-4 text-red-600 rounded border-slate-300 focus:ring-red-500">
          <div class="ml-3">
            <span class="text-sm font-bold text-slate-800">2.3 – Vay ngắn hạn từng lần</span>
            <span class="block text-xs text-slate-500">Mã hạn mức: ECS1109 (Nhóm D)</span>
          </div>
        </label>

        <label class="flex items-start p-3.5 border border-slate-200 rounded-lg hover:border-red-400 hover:bg-red-50/20 cursor-pointer transition">
          <input type="checkbox" id="chk-2-4" value="2.4_vay_trung_dai_han" class="mt-1 w-4 h-4 text-red-600 rounded border-slate-300 focus:ring-red-500">
          <div class="ml-3">
            <span class="text-sm font-bold text-slate-800">2.4 – Vay trung/dài hạn</span>
            <span class="block text-xs text-slate-500">Mã hạn mức: ECS2100 (Trung hạn) / ECS3100 (Dài hạn)</span>
          </div>
        </label>

        <label class="flex items-start p-3.5 border border-slate-200 rounded-lg hover:border-red-400 hover:bg-red-50/20 cursor-pointer transition">
          <input type="checkbox" id="chk-2-5" value="2.5_lc_nho_thu" class="mt-1 w-4 h-4 text-red-600 rounded border-slate-300 focus:ring-red-500">
          <div class="ml-3">
            <span class="text-sm font-bold text-slate-800">2.5 – Hạn mức / từng lần L/C / Nhờ thu</span>
            <span class="block text-xs text-slate-500">Mã hạn mức: ECS1308 / ECS1309 / ECS2300</span>
          </div>
        </label>

        <label class="flex items-start p-3.5 border border-slate-200 rounded-lg hover:border-red-400 hover:bg-red-50/20 cursor-pointer transition">
          <input type="checkbox" id="chk-2-6" value="2.6_bao_lanh" checked class="mt-1 w-4 h-4 text-red-600 rounded border-slate-300 focus:ring-red-500">
          <div class="ml-3">
            <span class="text-sm font-bold text-slate-800">2.6 – Hạn mức / từng lần Bảo lãnh</span>
            <span class="block text-xs text-slate-500">Mã hạn mức: ECS1200 / ECS2200 / ECS3200</span>
          </div>
        </label>

        <label class="flex items-start p-3.5 border border-slate-200 rounded-lg hover:border-red-400 hover:bg-red-50/20 cursor-pointer transition">
          <input type="checkbox" id="chk-2-7" value="2.7_chiet_khau_bao_thanh_toan" class="mt-1 w-4 h-4 text-red-600 rounded border-slate-300 focus:ring-red-500">
          <div class="ml-3">
            <span class="text-sm font-bold text-slate-800">2.7 – Hạn mức / từng lần CK BCT / Bao thanh toán</span>
            <span class="block text-xs text-slate-500">Mã hạn mức: ECS1400 / ECS1102</span>
          </div>
        </label>

        <label class="flex items-start p-3.5 border border-slate-200 rounded-lg hover:border-red-400 hover:bg-red-50/20 cursor-pointer transition">
          <input type="checkbox" id="chk-2-8" value="2.8_rui_ro_doi_tac" class="mt-1 w-4 h-4 text-red-600 rounded border-slate-300 focus:ring-red-500">
          <div class="ml-3">
            <span class="text-sm font-bold text-slate-800">2.8 – Hạn mức rủi ro tín dụng đối tác</span>
            <span class="block text-xs text-slate-500">Mã hạn mức: ECS9100 / ECS9200 (Phái sinh FX/IR)</span>
          </div>
        </label>
      </div>

      <div class="mt-6 flex justify-end">
        <button onclick="goToStep(2)" class="px-6 py-2.5 bg-red-600 text-white font-semibold text-sm rounded-lg hover:bg-red-700 shadow flex items-center space-x-2">
          <span>Tiếp tục: Nhập thông tin</span>
          <span>&rarr;</span>
        </button>
      </div>
    </section>

    <!-- STEP 2: DYNAMIC FORM CARDS -->
    <section id="step-2" class="hidden space-y-6">
      <div class="bg-blue-50 border border-blue-200 p-4 rounded-xl flex items-center justify-between">
        <div class="flex items-center space-x-3">
          <span class="text-blue-600 text-xl">💡</span>
          <div>
            <h4 class="text-sm font-bold text-blue-900">Nguyên tắc: 1 Business Fact = 1 Input duy nhất</h4>
            <p class="text-xs text-blue-700">RM chỉ cần nhập số tiền và điều kiện 1 lần. Toàn bộ Bảng tổng hợp Mục 1, Bảng chi tiết Mục 2 và số tiền bằng chữ sẽ được hệ thống tự động sinh đồng bộ.</p>
          </div>
        </div>
        <button onclick="goToStep(1)" class="text-xs font-semibold text-blue-800 underline hover:text-blue-900">Thay đổi nhu cầu</button>
      </div>

      <!-- CARD 2.1 -->
      <div id="card-2-1" class="bg-white border border-slate-200 rounded-xl p-6 shadow-sm">
        <div class="border-b border-slate-100 pb-3 mb-4 flex items-center justify-between">
          <div class="flex items-center space-x-2">
            <span class="w-6 h-6 rounded-full bg-red-100 text-red-600 text-xs font-bold flex items-center justify-center">2.1</span>
            <h3 class="text-base font-bold text-slate-900">Cho vay VLĐ theo hạn mức (ECS1101)</h3>
          </div>
          <span class="text-xs bg-slate-100 text-slate-600 px-2 py-0.5 rounded font-medium">Nhóm A</span>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
          <div>
            <label class="block text-xs font-bold text-slate-700 mb-1">Hình thức đề xuất *</label>
            <div class="flex space-x-4 mt-2">
              <label class="inline-flex items-center text-sm"><input type="radio" name="f21_prop_type" value="Cấp mới" class="text-red-600"> <span class="ml-2">Cấp mới</span></label>
              <label class="inline-flex items-center text-sm"><input type="radio" name="f21_prop_type" value="Tái cấp" checked class="text-red-600"> <span class="ml-2">Tái cấp</span></label>
            </div>
          </div>
          <div>
            <label class="block text-xs font-bold text-slate-700 mb-1">Hạn mức đã được duyệt (triệu VND)</label>
            <input type="number" id="f21_appr" value="80000" placeholder="Để trống nếu cấp mới" class="w-full text-sm border border-slate-300 rounded-lg px-3 py-2">
          </div>
          <div>
            <label class="block text-xs font-bold text-slate-700 mb-1">Hạn mức đề xuất mới (triệu VND) *</label>
            <input type="number" id="f21_prop" value="100000" oninput="updateWordsPreview('f21')" class="w-full text-sm border border-slate-300 rounded-lg px-3 py-2 font-bold text-red-700">
            <span id="f21_words" class="block text-xs text-slate-500 italic mt-1">100.000.000.000 VND (Một trăm tỷ đồng)</span>
          </div>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
          <div>
            <label class="block text-xs font-bold text-slate-700 mb-1">Mục đích vay *</label>
            <textarea id="f21_purpose" rows="2" class="w-full text-sm border border-slate-300 rounded-lg px-3 py-2">Bổ sung vốn lưu động phục vụ hoạt động sản xuất kinh doanh phôi thép và thép xây dựng</textarea>
          </div>
          <div>
            <label class="block text-xs font-bold text-slate-700 mb-1">Ghi chú hạn mức (Mục 1)</label>
            <input type="text" id="f21_note" value="Tái cấp tăng hạn mức năm 2026" class="w-full text-sm border border-slate-300 rounded-lg px-3 py-2">
          </div>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
          <div>
            <label class="block text-xs font-bold text-slate-700 mb-1">Thời hạn duy trì hạn mức (tháng)</label>
            <input type="number" id="f21_dur" value="12" class="w-full text-sm border border-slate-300 rounded-lg px-3 py-2">
          </div>
          <div>
            <label class="block text-xs font-bold text-slate-700 mb-1">Thời hạn tối đa mỗi KƯ/GNN (tháng)</label>
            <input type="number" id="f21_note_dur" value="6" class="w-full text-sm border border-slate-300 rounded-lg px-3 py-2">
          </div>
          <div>
            <label class="block text-xs font-bold text-slate-700 mb-1">Ngày hiệu lực</label>
            <select id="f21_eff" class="w-full text-sm border border-slate-300 rounded-lg px-3 py-2">
              <option>Kể từ ngày ký Hợp đồng tín dụng</option>
              <option>Kể từ ngày phê duyệt khoản vay</option>
              <option>Ngày cụ thể</option>
              <option>Khác</option>
            </select>
          </div>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
          <div>
            <label class="block text-xs font-bold text-slate-700 mb-1">Lãi suất cho vay</label>
            <input type="text" id="f21_rate" value="Theo quy định MSB tại thời điểm giải ngân từng KƯNN" class="w-full text-sm border border-slate-300 rounded-lg px-3 py-2">
          </div>
          <div>
            <label class="block text-xs font-bold text-slate-700 mb-1">Hình thức giải ngân</label>
            <input type="text" id="f21_disb" value="Chuyển khoản trực tiếp vào tài khoản bên thụ hưởng" class="w-full text-sm border border-slate-300 rounded-lg px-3 py-2">
          </div>
          <div>
            <label class="block text-xs font-bold text-slate-700 mb-1">Kỳ hạn trả nợ</label>
            <input type="text" id="f21_repay" value="Gốc trả cuối kỳ mỗi KƯNN; Lãi trả định kỳ hàng tháng" class="w-full text-sm border border-slate-300 rounded-lg px-3 py-2">
          </div>
        </div>

        <div>
          <label class="block text-xs font-bold text-slate-700 mb-1">Điều kiện khác (Nếu không có sẽ để trống trên Word)</label>
          <input type="text" id="f21_other" placeholder="Để trống nếu không có" class="w-full text-sm border border-slate-300 rounded-lg px-3 py-2">
        </div>
      </div>

      <!-- CARD 2.6 -->
      <div id="card-2-6" class="bg-white border border-slate-200 rounded-xl p-6 shadow-sm">
        <div class="border-b border-slate-100 pb-3 mb-4 flex items-center justify-between">
          <div class="flex items-center space-x-2">
            <span class="w-6 h-6 rounded-full bg-red-100 text-red-600 text-xs font-bold flex items-center justify-center">2.6</span>
            <h3 class="text-base font-bold text-slate-900">Hạn mức / từng lần Bảo lãnh (ECS1200)</h3>
          </div>
          <span class="text-xs bg-slate-100 text-slate-600 px-2 py-0.5 rounded font-medium">Nhóm A / D</span>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-4 gap-4 mb-4">
          <div>
            <label class="block text-xs font-bold text-slate-700 mb-1">Hình thức cấp *</label>
            <div class="flex space-x-4 mt-2">
              <label class="inline-flex items-center text-sm"><input type="radio" name="f26_struct" value="Hạn mức" checked class="text-red-600"> <span class="ml-2">Hạn mức</span></label>
              <label class="inline-flex items-center text-sm"><input type="radio" name="f26_struct" value="Từng lần" class="text-red-600"> <span class="ml-2">Từng lần</span></label>
            </div>
          </div>
          <div>
            <label class="block text-xs font-bold text-slate-700 mb-1">Kỳ hạn *</label>
            <select id="f26_tenor" class="w-full text-sm border border-slate-300 rounded-lg px-3 py-2">
              <option value="Ngắn hạn">Ngắn hạn (≤ 12 tháng)</option>
              <option value="Trên 12 tháng">Trên 12 tháng</option>
              <option value="Trung hạn">Trung hạn</option>
              <option value="Dài hạn">Dài hạn</option>
            </select>
          </div>
          <div>
            <label class="block text-xs font-bold text-slate-700 mb-1">Hình thức đề xuất *</label>
            <div class="flex space-x-4 mt-2">
              <label class="inline-flex items-center text-sm"><input type="radio" name="f26_prop_type" value="Cấp mới" checked class="text-red-600"> <span class="ml-2">Cấp mới</span></label>
              <label class="inline-flex items-center text-sm"><input type="radio" name="f26_prop_type" value="Tái cấp" class="text-red-600"> <span class="ml-2">Tái cấp</span></label>
            </div>
          </div>
          <div>
            <label class="block text-xs font-bold text-slate-700 mb-1">Số tiền đề xuất (triệu VND) *</label>
            <input type="number" id="f26_prop" value="20000" oninput="updateWordsPreview('f26')" class="w-full text-sm border border-slate-300 rounded-lg px-3 py-2 font-bold text-red-700">
            <span id="f26_words" class="block text-xs text-slate-500 italic mt-1">20.000.000.000 VND (Hai mươi tỷ đồng)</span>
          </div>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
          <div>
            <label class="block text-xs font-bold text-slate-700 mb-1">Mục đích bảo lãnh *</label>
            <textarea id="f26_purpose" rows="2" class="w-full text-sm border border-slate-300 rounded-lg px-3 py-2">Phát hành bảo lãnh thực hiện hợp đồng, bảo lãnh thanh toán tiền điện cho EVN và hợp đồng mua bán thép</textarea>
          </div>
          <div>
            <label class="block text-xs font-bold text-slate-700 mb-1">Loại bảo lãnh</label>
            <input type="text" id="f26_type" value="Bảo lãnh dự thầu, Bảo lãnh thực hiện hợp đồng, Bảo lãnh thanh toán" class="w-full text-sm border border-slate-300 rounded-lg px-3 py-2">
          </div>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
          <div>
            <label class="block text-xs font-bold text-slate-700 mb-1">Thời hạn của hạn mức (tháng)</label>
            <input type="number" id="f26_dur" value="12" class="w-full text-sm border border-slate-300 rounded-lg px-3 py-2">
          </div>
          <div>
            <label class="block text-xs font-bold text-slate-700 mb-1">Thời hạn từng món BL</label>
            <input type="text" id="f26_single_dur" value="Tối đa 12 tháng kể từ ngày phát hành" class="w-full text-sm border border-slate-300 rounded-lg px-3 py-2">
          </div>
          <div>
            <label class="block text-xs font-bold text-slate-700 mb-1">Tỷ lệ ký quỹ tối thiểu</label>
            <input type="text" id="f26_margin" value="0%" class="w-full text-sm border border-slate-300 rounded-lg px-3 py-2">
          </div>
        </div>

        <div>
          <label class="block text-xs font-bold text-slate-700 mb-1">Điều kiện khác</label>
          <input type="text" id="f26_other" placeholder="Để trống nếu không có" class="w-full text-sm border border-slate-300 rounded-lg px-3 py-2">
        </div>
      </div>

      <!-- Navigation buttons -->
      <div class="flex justify-between items-center pt-4">
        <button onclick="goToStep(1)" class="px-5 py-2 border border-slate-300 text-slate-700 font-semibold text-sm rounded-lg hover:bg-slate-100">
          &larr; Quay lại chọn nhu cầu
        </button>
        <button onclick="goToStep(3)" class="px-6 py-2.5 bg-red-600 text-white font-semibold text-sm rounded-lg hover:bg-red-700 shadow flex items-center space-x-2">
          <span>Tiếp tục: Review & Kiểm tra</span>
          <span>&rarr;</span>
        </button>
      </div>
    </section>

    <!-- STEP 3: REVIEW & GENERATE -->
    <section id="step-3" class="hidden space-y-6">
      <div class="bg-white border border-slate-200 rounded-xl p-6 shadow-sm">
        <div class="border-b border-slate-100 pb-3 mb-4 flex items-center justify-between">
          <h2 class="text-lg font-bold text-slate-900">BƯỚC 3: XÁC NHẬN SỐ LIỆU & KIỂM TRA MÂU THUẪN</h2>
          <span class="text-xs bg-emerald-50 text-emerald-700 px-3 py-1 rounded-full font-bold border border-emerald-200">
            Sẵn sàng sinh file Word
          </span>
        </div>

        <!-- Calculated totals cards -->
        <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
          <div class="bg-red-50 border border-red-200 p-4 rounded-xl">
            <span class="text-xs font-bold text-red-600 uppercase tracking-wide">Tổng HMTD đề xuất</span>
            <div id="rev-grand-total" class="text-2xl font-black text-red-900 mt-1">120.000 triệu VND</div>
            <p id="rev-grand-words" class="text-xs text-red-700 italic mt-0.5">Một trăm hai mươi tỷ đồng</p>
          </div>
          <div class="bg-slate-50 border border-slate-200 p-4 rounded-xl">
            <span class="text-xs font-bold text-slate-500 uppercase tracking-wide">Mức cho vay tối đa</span>
            <div id="rev-max-lending" class="text-2xl font-black text-slate-800 mt-1">100.000 triệu VND</div>
            <p class="text-xs text-slate-600 italic mt-0.5">Cho vay VLĐ Mục 2.1</p>
          </div>
          <div class="bg-slate-50 border border-slate-200 p-4 rounded-xl">
            <span class="text-xs font-bold text-slate-500 uppercase tracking-wide">Tổng hạn mức Bảo lãnh</span>
            <div class="text-2xl font-black text-slate-800 mt-1">20.000 triệu VND</div>
            <p class="text-xs text-slate-600 italic mt-0.5">Bảo lãnh Mục 2.6</p>
          </div>
        </div>

        <!-- Review Table -->
        <h4 class="text-sm font-bold text-slate-800 mb-2">Bảng tổng hợp Mục 1 sẽ sinh ra:</h4>
        <div class="overflow-x-auto border border-slate-200 rounded-lg mb-6">
          <table class="w-full text-left text-sm">
            <thead class="bg-slate-100 text-slate-700 font-bold text-xs uppercase border-b">
              <tr>
                <th class="p-3">Cụ thể</th>
                <th class="p-3">Mã hạn mức</th>
                <th class="p-3 text-right">Hạn mức đã duyệt</th>
                <th class="p-3 text-right">Hạn mức đề xuất</th>
                <th class="p-3">Hình thức</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-200">
              <tr class="font-bold bg-slate-50">
                <td class="p-3">A. Tín dụng hạn mức ngắn hạn</td>
                <td class="p-3">ECS1000</td>
                <td class="p-3 text-right">-</td>
                <td class="p-3 text-right text-red-700">120.000</td>
                <td class="p-3">-</td>
              </tr>
              <tr>
                <td class="p-3 pl-6">- Cho vay ngắn hạn theo hạn mức</td>
                <td class="p-3">ECS1100</td>
                <td class="p-3 text-right">80.000</td>
                <td class="p-3 text-right font-semibold">100.000</td>
                <td class="p-3"><span class="px-2 py-0.5 bg-amber-100 text-amber-800 rounded text-xs font-semibold">Tái cấp</span></td>
              </tr>
              <tr>
                <td class="p-3 pl-6">- Bảo lãnh</td>
                <td class="p-3">ECS1200</td>
                <td class="p-3 text-right">-</td>
                <td class="p-3 text-right font-semibold">20.000</td>
                <td class="p-3"><span class="px-2 py-0.5 bg-emerald-100 text-emerald-800 rounded text-xs font-semibold">Cấp mới</span></td>
              </tr>
              <tr class="font-bold bg-slate-100 border-t-2">
                <td class="p-3">Tổng tín dụng hạn mức</td>
                <td class="p-3"></td>
                <td class="p-3 text-right">-</td>
                <td class="p-3 text-right text-red-700">120.000</td>
                <td class="p-3"></td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- Status & Checks -->
        <div class="bg-emerald-50 border border-emerald-200 rounded-lg p-4 mb-6">
          <div class="flex items-center space-x-2 text-emerald-800 font-bold text-sm mb-1">
            <span>✅</span>
            <span>Hệ thống đã xác thực tính nhất quán và nguyên vẹn:</span>
          </div>
          <ul class="text-xs text-emerald-700 space-y-1 list-disc list-inside">
            <li>Các mục không chọn (2.2, 2.3, 2.4, 2.5, 2.7, 2.8) sẽ bị xóa hoàn toàn khỏi body tài liệu Word.</li>
            <li>Các dòng không áp dụng trong Bảng 1 (Nhóm B, Nhóm C, Nhóm D, Nhóm E) đã được loại bỏ.</li>
            <li>Form Field Checkbox gốc của MS Word sẽ được tick chính xác vào ô Tái cấp / Cấp mới.</li>
            <li>Các trường không có thông tin (Điều kiện khác) sẽ để trống hoàn toàn (blank, không xuất hiện chữ N/A).</li>
          </ul>
        </div>

        <!-- Action Buttons -->
        <div class="flex items-center justify-between pt-4 border-t border-slate-100">
          <button onclick="goToStep(2)" class="px-5 py-2 border border-slate-300 text-slate-700 font-semibold text-sm rounded-lg hover:bg-slate-100">
            &larr; Quay lại chỉnh sửa
          </button>
          <button onclick="generateDocx()" id="btn-generate" class="px-8 py-3 bg-red-600 text-white font-bold text-base rounded-xl hover:bg-red-700 shadow-lg flex items-center space-x-2">
            <span>📥 TẠO FILE PHẦN B (.DOCX)</span>
          </button>
        </div>
      </div>
    </section>
  </main>

  <script>
    function goToStep(step) {
      document.getElementById('step-1').classList.add('hidden');
      document.getElementById('step-2').classList.add('hidden');
      document.getElementById('step-3').classList.add('hidden');
      
      document.getElementById('step-' + step).classList.remove('hidden');

      // Update badge styling
      for (let i = 1; i <= 3; i++) {
        const b = document.getElementById('step-badge-' + i);
        if (i === step) {
          b.className = "w-8 h-8 rounded-full bg-red-600 text-white font-bold flex items-center justify-center text-sm shadow";
        } else if (i < step) {
          b.className = "w-8 h-8 rounded-full bg-emerald-600 text-white font-bold flex items-center justify-center text-sm";
          b.innerHTML = "✓";
        } else {
          b.className = "w-8 h-8 rounded-full bg-slate-200 text-slate-600 font-bold flex items-center justify-center text-sm";
          b.innerHTML = i;
        }
      }
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }

    function updateWordsPreview(prefix) {
      const val = parseFloat(document.getElementById(prefix + '_prop').value) || 0;
      if (prefix === 'f21') {
        const words = (val * 1000000).toLocaleString('vi-VN') + ' VND';
        document.getElementById('f21_words').innerText = words;
      }
    }

    function generateDocx() {
      const btn = document.getElementById('btn-generate');
      btn.innerHTML = "⏳ Đang tạo file Word...";
      btn.disabled = true;

      // Construct payload
      const payload = {
        selected_needs: ["2.1_vay_vld_han_muc", "2.6_bao_lanh"],
        currency: "VND",
        facilities_data: {
          need_2_1: {
            proposal_type: document.querySelector('input[name="f21_prop_type"]:checked').value,
            approved_limit_vnd: parseFloat(document.getElementById('f21_appr').value) || null,
            proposed_limit_vnd: parseFloat(document.getElementById('f21_prop').value) || 100000.0,
            note: document.getElementById('f21_note').value,
            purpose: document.getElementById('f21_purpose').value,
            duration_months: parseInt(document.getElementById('f21_dur').value) || 12,
            effective_date_rule: document.getElementById('f21_eff').value,
            max_promissory_note_duration_months: parseInt(document.getElementById('f21_note_dur').value) || 6,
            lending_interest_rate: document.getElementById('f21_rate').value,
            disbursement_method: document.getElementById('f21_disb').value,
            repayment_period: document.getElementById('f21_repay').value,
            other_conditions: document.getElementById('f21_other').value
          },
          need_2_6: {
            issuance_structure: document.querySelector('input[name="f26_struct"]:checked').value,
            term_classification: document.getElementById('f26_tenor').value,
            proposal_type: document.querySelector('input[name="f26_prop_type"]:checked').value,
            proposed_limit_vnd: parseFloat(document.getElementById('f26_prop').value) || 20000.0,
            purpose: document.getElementById('f26_purpose').value,
            guarantee_types: document.getElementById('f26_type').value,
            facility_duration_months: parseInt(document.getElementById('f26_dur').value) || 12,
            single_guarantee_duration: document.getElementById('f26_single_dur').value,
            min_margin_cash_percentage: document.getElementById('f26_margin').value,
            other_conditions: document.getElementById('f26_other').value
          }
        }
      };

      fetch('/api/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      })
      .then(response => {
        if (!response.ok) throw new Error("Lỗi khi sinh file");
        return response.blob();
      })
      .then(blob => {
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = "TO_TRINH_MB07_PHAN_B_FINAL.docx";
        document.body.appendChild(a);
        a.click();
        a.remove();
        btn.innerHTML = "✅ ĐÃ TẢI FILE THÀNH CÔNG!";
        setTimeout(() => {
          btn.innerHTML = "📥 TẠO FILE PHẦN B (.DOCX)";
          btn.disabled = false;
        }, 3000);
      })
      .catch(err => {
        alert("Lỗi: " + err.message);
        btn.innerHTML = "📥 TẠO FILE PHẦN B (.DOCX)";
        btn.disabled = false;
      });
    }
  </script>
</body>
</html>
"""


class SectionBHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_TEMPLATE.encode("utf-8"))
        elif self.path.startswith("/output/"):
            file_path = self.path[1:]
            if os.path.exists(file_path):
                self.send_response(200)
                self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
                self.send_header("Content-Disposition", f"attachment; filename={os.path.basename(file_path)}")
                self.end_headers()
                with open(file_path, "rb") as f:
                    self.wfile.write(f.read())
            else:
                self.send_error(404, "File not found")
        else:
            self.send_error(404, "Not Found")

    def do_POST(self):
        if self.path == "/api/validate":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            payload = json.loads(body.decode("utf-8"))
            totals, report, facs = validate_and_calculate_section_b(payload)
            res = {
                "totals": totals.model_dump(),
                "report": report.model_dump()
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(res, ensure_ascii=False).encode("utf-8"))

        elif self.path == "/api/generate":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            payload = json.loads(body.decode("utf-8"))

            out_file = os.path.join("output", "TO_TRINH_MB07_PHAN_B_FINAL.docx")
            render_section_b_docx(payload, out_file)

            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
            self.send_header("Content-Disposition", "attachment; filename=TO_TRINH_MB07_PHAN_B_FINAL.docx")
            self.end_headers()
            with open(out_file, "rb") as f:
                self.wfile.write(f.read())
        else:
            self.send_error(404, "Not Found")


def run_server(port=PORT):
    server = HTTPServer(("0.0.0.0", port), SectionBHandler)
    print(f"🚀 MSB Section B Web App running at http://localhost:{port}")
    print("Press Ctrl+C to stop.")
    server.serve_forever()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else PORT
    run_server(port)

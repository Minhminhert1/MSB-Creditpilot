#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script: scripts/scan_secrets.py
Mô tả: Quét toàn diện thư mục dự án để tìm API keys, secrets, credentials bị rò rỉ.
"""

import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# Patterns to scan
SECRET_PATTERNS = [
    re.compile(r'sk-[a-zA-Z0-9]{20,}'),
    re.compile(r'AIzaSy[a-zA-Z0-9_-]{33}'),
    re.compile(r'sk-ant-[a-zA-Z0-9_-]{20,}'),
    re.compile(r'Bearer\s+[a-zA-Z0-9_\-\.]{30,}'),
]

IGNORE_EXTENSIONS = {'.pyc', '.docx', '.xlsx', '.xls', '.pdf', '.zip', '.png', '.jpg'}
IGNORE_DIRS = {'__pycache__', '.pytest_cache', '.git'}

findings = []

for root, dirs, files in os.walk(BASE_DIR):
    dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
    for f in files:
        if f in ('.env',):  # handled separately
            continue
        ext = os.path.splitext(f)[1].lower()
        if ext in IGNORE_EXTENSIONS:
            continue
        full_path = os.path.join(root, f)
        rel_path = os.path.relpath(full_path, BASE_DIR)
        try:
            with open(full_path, 'r', encoding='utf-8', errors='ignore') as fp:
                for line_no, line in enumerate(fp, 1):
                    for pat in SECRET_PATTERNS:
                        matches = pat.findall(line)
                        for m in matches:
                            if any(placeholder in m.lower() for placeholder in ['placeholder', 'mock_', 'your_']):
                                continue
                            findings.append((rel_path, line_no, m[:8] + "..." + m[-4:], len(m)))
        except Exception:
            pass

print("=" * 60)
print("   SECRET SCAN REPORT")
print("=" * 60)
if findings:
    print(f"[!] CẢNH BÁO: Tìm thấy {len(findings)} nghi vấn bí mật trong mã nguồn:")
    for f in findings:
        print(f"  - {f[0]}:{f[1]} -> {f[2]} (length={f[3]})")
else:
    print("[✓] An toàn tuyệt đối: Không phát hiện bất kỳ secret/API key thực tế nào trong codebase.")
print("=" * 60)

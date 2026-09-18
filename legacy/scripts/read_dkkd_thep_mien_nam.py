# -*- coding: utf-8 -*-
import pypdf
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

folder = r"c:\Users\minhnh33\Documents\Hackathon\New folder"
dkkd_path = os.path.join(folder, "2025-0725 Giay DKKD 8.pdf")
reader = pypdf.PdfReader(dkkd_path)
print("=== DKKD FULL TEXT ===")
for p in reader.pages:
    print(p.extract_text())

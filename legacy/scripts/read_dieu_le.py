# -*- coding: utf-8 -*-
import pypdf
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

folder = r"c:\Users\minhnh33\Documents\Hackathon\New folder"
dl_path = os.path.join(folder, "125-Dieu le Cong ty.pdf")
reader = pypdf.PdfReader(dl_path)
print(f"Dieu Le Total Pages: {len(reader.pages)}")
for i in range(min(10, len(reader.pages))):
    print(f"--- PAGE {i+1} ---")
    print(reader.pages[i].extract_text())

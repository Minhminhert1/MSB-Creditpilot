# -*- coding: utf-8 -*-
import pypdf, os, sys
if hasattr(sys.stdout, "reconfigure"): sys.stdout.reconfigure(encoding="utf-8")

folder = r"c:\Users\minhnh33\Documents\Hackathon\New folder"
dl_path = os.path.join(folder, "125-Dieu le Cong ty.pdf")
reader = pypdf.PdfReader(dl_path)
print("=== DIEU LE PAGES 1 TO 4 ===")
for i in range(4):
    print(f"--- PAGE {i+1} ---")
    print(reader.pages[i].extract_text())

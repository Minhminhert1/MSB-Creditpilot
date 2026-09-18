# -*- coding: utf-8 -*-
import pypdf
import openpyxl
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

folder = r"c:\Users\minhnh33\Documents\Hackathon\New folder"

print("=== 1. EXTRACTING DKKD ===")
dkkd_path = os.path.join(folder, "2025-0725 Giay DKKD 8.pdf")
try:
    reader = pypdf.PdfReader(dkkd_path)
    print(f"DKKD Total Pages: {len(reader.pages)}")
    for i, p in enumerate(reader.pages):
        print(f"--- PAGE {i+1} ---")
        print(p.extract_text()[:1500])
except Exception as e:
    print(f"Error reading DKKD: {e}")

print("\n=== 2. EXTRACTING DIEU LE ===")
dl_path = os.path.join(folder, "125-Dieu le Cong ty.pdf")
try:
    reader_dl = pypdf.PdfReader(dl_path)
    print(f"Dieu Le Total Pages: {len(reader_dl.pages)}")
    for i in range(min(5, len(reader_dl.pages))):
        print(f"--- PAGE {i+1} ---")
        print(reader_dl.pages[i].extract_text()[:1000])
except Exception as e:
    print(f"Error reading Dieu Le: {e}")

print("\n=== 3. EXTRACTING EXCEL BCTC ===")
excel_path = os.path.join(folder, "MB09.QT.RR.044 Template BCTC 2025.updated T2.2206 - Copy.xlsx")
try:
    wb = openpyxl.load_workbook(excel_path, data_only=True)
    print("Sheets in Excel:", wb.sheetnames)
    # Tìm sheet "Tờ trình" hoặc sheet BCTC
    for sname in wb.sheetnames:
        if "tờ trình" in sname.lower() or "to trinh" in sname.lower() or "05" in sname or "01" in sname:
            ws = wb[sname]
            print(f"\n--- SHEET: {sname} (Sample 20 rows) ---")
            for r in list(ws.iter_rows(values_only=True))[:25]:
                if any(r):
                    print([str(c)[:30] for c in r if c is not None][:6])
except Exception as e:
    print(f"Error reading Excel: {e}")

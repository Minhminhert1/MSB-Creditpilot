# -*- coding: utf-8 -*-
import openpyxl, os, sys
if hasattr(sys.stdout, "reconfigure"): sys.stdout.reconfigure(encoding="utf-8")

folder = r"c:\Users\minhnh33\Documents\Hackathon\New folder"
excel_path = os.path.join(folder, "MB09.QT.RR.044 Template BCTC 2025.updated T2.2206 - Copy.xlsx")
wb = openpyxl.load_workbook(excel_path, data_only=True)
ws = wb["02.Du lieu tai chinh"]

print("=== BALANCE SHEET EQUITY ROWS IN 02.Du lieu tai chinh ===")
for r in ws.iter_rows(values_only=True):
    txt = str(r[1]) if len(r) > 1 else ""
    if any(k in txt.lower() for k in ["vốn đầu tư", "vốn chủ sở hữu", "doanh thu thuần", "lợi nhuận sau thuế"]):
        print([c for c in r if c is not None][:6])

# -*- coding: utf-8 -*-
import docx, os, sys
if hasattr(sys.stdout, "reconfigure"): sys.stdout.reconfigure(encoding="utf-8")

parent_dir = r"c:\Users\minhnh33\Documents\Hackathon"
doc = docx.Document(os.path.join(parent_dir, "MB07 Tờ trình đề xuất cấp tín dụng (ĐVKD) - Tho.docx"))
t1 = doc.tables[1]
for i, r in enumerate(t1.rows):
    print(f"Row {i:02d} (len={len(r.cells)}): {[c.text.replace(chr(10), ' ').strip()[:25] for c in r.cells]}")

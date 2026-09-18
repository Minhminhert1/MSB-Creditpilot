import pypdf
import os

folder = r"c:\Users\minhnh33\Documents\Hackathon\New folder"
reader = pypdf.PdfReader(os.path.join(folder, "2025-0725 Giay DKKD 8.pdf"))
img = reader.pages[0].images[0]
out_img = r"c:\Users\minhnh33\Documents\Hackathon\msb_eb_copilot\extracted_dkkd_image.jpg"
with open(out_img, "wb") as f:
    f.write(img.data)
print(f"Extracted image to: {out_img}")

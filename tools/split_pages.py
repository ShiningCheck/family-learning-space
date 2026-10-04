# -*- coding: utf-8 -*-
"""将教材 PDF 拆成逐页 JPG 图片"""
import os
import sys
import json
import pymupdf

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from data_paths import textbooks_dir  # noqa: E402

ROOT = str(textbooks_dir())   # 教材库在仓库之外的 data-root
PDF_DIR = os.path.join(ROOT, "pdf")
PAGES_DIR = os.path.join(ROOT, "pages")

summary = {}
for fn in sorted(os.listdir(PDF_DIR)):
    if not fn.endswith(".pdf"):
        continue
    subject = fn[:-4]
    pdf_path = os.path.join(PDF_DIR, fn)
    out_dir = os.path.join(PAGES_DIR, subject)
    os.makedirs(out_dir, exist_ok=True)

    doc = pymupdf.open(pdf_path)
    n = doc.page_count
    print(f"=== {subject}: {n} pages ===")

    # 目标宽度约 1100px：按第一页尺寸计算缩放
    p0 = doc[0]
    zoom = 1100.0 / p0.rect.width
    mat = pymupdf.Matrix(zoom, zoom)

    for i in range(n):
        out_img = os.path.join(out_dir, f"p{i+1:03d}.jpg")
        if os.path.exists(out_img) and os.path.getsize(out_img) > 5000:
            continue
        pix = doc[i].get_pixmap(matrix=mat, alpha=False)
        pix.save(out_img, jpg_quality=82)
    doc.close()

    files = sorted(os.listdir(out_dir))
    total_mb = sum(os.path.getsize(os.path.join(out_dir, f)) for f in files) / 1024 / 1024
    summary[subject] = {"pages": n, "images_mb": round(total_mb, 1)}
    print(f"  -> {len(files)} images, {total_mb:.1f} MB")

print(json.dumps(summary, ensure_ascii=False, indent=1))

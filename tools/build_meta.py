# -*- coding: utf-8 -*-
"""抓取各科 ebook_mapping.txt，提取 front_page 偏移与章节目录"""
import json
import os
import sys
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from data_paths import textbooks_dir  # noqa: E402

TEXTBOOKS = str(textbooks_dir())   # 教材库在仓库之外的 data-root

session = requests.Session()
session.trust_env = False
session.headers.update({"User-Agent": "Mozilla/5.0"})

# contentId 优先取 textbooks/manifest.json（download_books.py 生成）；否则用内置默认
DEFAULT_BOOKS = {
    "语文": "1c73b348-e8b6-47d6-84b0-6dbacbe28268",
    "数学": "c3e06fe4-c6b3-49cb-8727-4f8ff69bbfbc",
    "道德与法治": "bdc00134-465d-454b-a541-dcd0cec4d86e",
    "科学": "5082db8c-82e3-4253-be5a-36a4cc7473a6",
    "美术": "bb6399d6-24cc-42cd-ae44-304dc3215f1b",
}
BOOKS = dict(DEFAULT_BOOKS)
_manifest_path = os.path.join(TEXTBOOKS, "manifest.json")
if os.path.exists(_manifest_path):
    _m = json.load(open(_manifest_path, encoding="utf-8"))
    _picked = {s: v["contentId"] for s, v in _m.items() if v.get("contentId")}
    if _picked:
        BOOKS = _picked

result = {}
for subject, cid in BOOKS.items():
    url = f"https://r1-ndr.ykt.cbern.com.cn/edu_product/esp/assets/{cid}.pkg/ebook_mapping.txt"
    r = session.get(url, timeout=30)
    if r.status_code != 200:
        print(subject, "mapping fail:", r.status_code)
        continue
    m = r.json()
    ebook_id = m.get("ebook_id")
    front = m.get("front_page")
    print(f"{subject}: front_page={front} ebook_id={ebook_id} mappings={len(m.get('mappings', []))}")

    chapters = []
    if ebook_id:
        tr = session.get(f"https://s-file-1.ykt.cbern.com.cn/zxx/ndrv2/national_lesson/trees/{ebook_id}.json", timeout=30)
        if tr.status_code == 200:
            tree = tr.json()
            page_map = {mm["node_id"]: mm.get("page_number") for mm in m.get("mappings", [])}

            def walk(nodes, out):
                for n in nodes:
                    out.append({"title": n.get("title"), "pdf_page": page_map.get(n["id"])})
                    if n.get("child_nodes"):
                        walk(n["child_nodes"], out)
            if isinstance(tree, list):
                walk(tree, chapters)
            elif isinstance(tree, dict) and tree.get("child_nodes"):
                walk(tree["child_nodes"], chapters)

    result[subject] = {"contentId": cid, "front_page": front, "chapters": chapters}

json.dump(result, open(os.path.join(TEXTBOOKS, "book_meta.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("saved book_meta.json")
for subject, d in result.items():
    print(f"\n{subject} 前5章:", [(c["title"], c["pdf_page"]) for c in d["chapters"][:5]])

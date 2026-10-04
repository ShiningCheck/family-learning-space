# -*- coding: utf-8 -*-
"""批量下载一年级上册教材 PDF（国家中小学智慧教育平台官方源）"""
import json
import os
import sys
import time
import requests
from urllib.parse import quote

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from data_paths import textbooks_dir  # noqa: E402

ROOT = str(textbooks_dir())   # 教材库在仓库之外的 data-root
OUT_DIR = os.path.join(ROOT, "pdf")
os.makedirs(OUT_DIR, exist_ok=True)

# contentId 优先取 filter_books.py 的筛选结果（每科第一个匹配）；
# 无结果时回退到内置默认（仓库自带的一套示例教材）。
DEFAULT_BOOKS = {
    "语文": "1c73b348-e8b6-47d6-84b0-6dbacbe28268",
    "数学": "c3e06fe4-c6b3-49cb-8727-4f8ff69bbfbc",
    "道德与法治": "bdc00134-465d-454b-a541-dcd0cec4d86e",
    "科学": "5082db8c-82e3-4253-be5a-36a4cc7473a6",
    "美术": "bb6399d6-24cc-42cd-ae44-304dc3215f1b",
    "音乐": "61b6fb7c-c602-2e07-4412-8cedb9e9ae77",
    "体育与健康": "e3f6f6e0-7784-f55a-5148-caf5f284f575",
}

BOOKS = dict(DEFAULT_BOOKS)
_target_path = os.path.join(HERE, "target_books.json")
if os.path.exists(_target_path):
    _targets = json.load(open(_target_path, encoding="utf-8"))
    _picked = {s: ms[0]["id"] for s, ms in _targets.items() if ms}
    if _picked:
        BOOKS = _picked

session = requests.Session()
session.trust_env = False
session.headers.update({
    "Authorization": "Bearer 0",
    "Origin": "https://basic.smartedu.cn",
    "Referer": "https://basic.smartedu.cn/",
    "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"),
    "X-ND-AUTH": 'MAC id="0",nonce="0",mac="0"',
})

manifest = {}

for subject, cid in BOOKS.items():
    print(f"=== {subject} ===")
    r = session.get(f"https://s-file-1.ykt.cbern.com.cn/zxx/ndrv2/resources/tch_material/details/{cid}.json", timeout=30)
    d = r.json()
    title = d.get("title")

    pdf_url = None
    for item in d.get("ti_items", []):
        if item.get("ti_is_source_file") and (item.get("ti_format") or "pdf") == "pdf":
            pdf_url = item.get("ti_storage")
            if pdf_url:
                pdf_url = pdf_url.replace("cs_path:${ref-path}", "https://r1-ndr-private.ykt.cbern.com.cn")
            else:
                pdf_url = next((u for u in item.get("ti_storages") or [] if u), None)
            break
    if not pdf_url:
        print("  !! 未找到 PDF 地址")
        continue

    out_path = os.path.join(OUT_DIR, f"{subject}.pdf")
    print(f"  title: {title}")
    print(f"  url: {pdf_url}")
    with session.get(pdf_url, stream=True, timeout=60) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("Content-Length", 0))
        done = 0
        with open(out_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=256 * 1024):
                f.write(chunk)
                done += len(chunk)
        print(f"  downloaded: {done/1024/1024:.1f} MB (declared {total/1024/1024:.1f} MB)")

    manifest[subject] = {
        "contentId": cid,
        "title": title,
        "source": "国家中小学智慧教育平台",
        "pdf": f"pdf/{subject}.pdf",
        "size": os.path.getsize(out_path),
    }
    time.sleep(1)

json.dump(manifest, open(os.path.join(ROOT, "manifest.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("\nDONE. manifest saved.")

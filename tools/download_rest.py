# -*- coding: utf-8 -*-
"""重新下载音乐/体育教材：整文件重试 + 多镜像切换"""
import json
import os
import sys
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from data_paths import textbooks_dir  # noqa: E402

ROOT = str(textbooks_dir())   # 教材库在仓库之外的 data-root
OUT_DIR = os.path.join(ROOT, "pdf")
os.makedirs(OUT_DIR, exist_ok=True)

BOOKS = {
    "音乐": "61b6fb7c-c602-2e07-4412-8cedb9e9ae77",
    "体育与健康": "e3f6f6e0-7784-f55a-5148-caf5f284f575",
}

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

manifest_path = os.path.join(ROOT, "manifest.json")
manifest = json.load(open(manifest_path, encoding="utf-8")) if os.path.exists(manifest_path) else {}

for subject, cid in BOOKS.items():
    print(f"=== {subject} ===")
    r = session.get(f"https://s-file-1.ykt.cbern.com.cn/zxx/ndrv2/resources/tch_material/details/{cid}.json", timeout=30)
    print("detail status:", r.status_code)
    if r.status_code != 200:
        print(r.text[:200])
        continue
    d = r.json()
    title = d.get("title")

    urls = []
    declared = 0
    for item in d.get("ti_items", []):
        if item.get("ti_is_source_file") and (item.get("ti_format") or "pdf") == "pdf":
            storage = item.get("ti_storage")
            if storage:
                path_part = storage.replace("cs_path:${ref-path}", "")
                urls = [f"https://{h}{path_part}" for h in
                        ("r1-ndr-private.ykt.cbern.com.cn", "r2-ndr-private.ykt.cbern.com.cn", "r3-ndr-private.ykt.cbern.com.cn")]
            else:
                urls = [u for u in item.get("ti_storages") or [] if u]
            declared = item.get("ti_size", 0)
            break
    print("title:", title, "| declared:", declared)

    out_path = os.path.join(OUT_DIR, f"{subject}.pdf")
    if os.path.exists(out_path):
        os.remove(out_path)

    ok = False
    for url in urls:
        for attempt in range(3):
            try:
                with session.get(url, stream=True, timeout=120) as resp:
                    resp.raise_for_status()
                    done = 0
                    with open(out_path, "wb") as f:
                        for chunk in resp.iter_content(chunk_size=512 * 1024):
                            f.write(chunk)
                            done += len(chunk)
                if declared and os.path.getsize(out_path) < declared:
                    raise IOError(f"size mismatch {os.path.getsize(out_path)} < {declared}")
                print(f"  OK {os.path.getsize(out_path)/1024/1024:.1f} MB via {url.split('/')[2]} attempt{attempt+1}")
                ok = True
                break
            except Exception as e:
                print(f"  fail {url.split('/')[2]} attempt{attempt+1}: {type(e).__name__} ({os.path.getsize(out_path)/1024/1024 if os.path.exists(out_path) else 0:.1f} MB)")
                if os.path.exists(out_path):
                    os.remove(out_path)
        if ok:
            break
    if ok:
        manifest[subject] = {
            "contentId": cid, "title": title, "source": "国家中小学智慧教育平台",
            "pdf": f"pdf/{subject}.pdf", "size": os.path.getsize(out_path),
        }

json.dump(manifest, open(manifest_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("manifest updated:", list(manifest.keys()))

# -*- coding: utf-8 -*-
"""从平台目录中找出指定年级所需教材的 contentId（默认一年级）

用法：python find_books.py [年级关键词，如 一年级]
"""
import json
import os
import sys
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
GRADE = sys.argv[1] if len(sys.argv) > 1 else "一年级"

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

# 1. 标签层级（用于把 tag_id 翻译成名称）
tags = session.get("https://s-file-1.ykt.cbern.com.cn/zxx/ndrs/tags/tch_material_tag.json", timeout=30).json()

tag_names = {}
def walk(hierarchies):
    for h in hierarchies or []:
        for ch in h.get("children", []):
            tag_names[ch["tag_id"]] = ch["tag_name"]
            walk(ch.get("hierarchies"))
walk(tags.get("hierarchies"))

# 2. 教材列表分片 URL
ver = session.get("https://s-file-1.ykt.cbern.com.cn/zxx/ndrs/resources/tch_material/version/data_version.json", timeout=30).json()
urls = ver["urls"].split(",")
print("list shards:", len(urls))

books = []
for u in urls:
    data = session.get(u, timeout=60).json()
    books.extend(data)
print("total books:", len(books))

# 3. 筛选一年级教材
def tag_path_names(book):
    paths = book.get("tag_paths") or []
    if not paths:
        return []
    ids = paths[0].split("/")
    return [tag_names.get(i, i) for i in ids]

grade1 = []
for b in books:
    names = tag_path_names(b)
    if not names:
        continue
    joined = "/".join(names)
    if "一年级" in joined:
        grade1.append({
            "id": b.get("id"),
            "title": b.get("title") or b.get("name"),
            "path": joined,
            "edition": next((t.get("tag_name") for t in (b.get("tag_list") or []) if t.get("tag_dimension_id") == "zxxbb"), None),
        })

print(GRADE, "books:", len(grade1))
json.dump(grade1, open(os.path.join(HERE, "grade1_books.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
for g in sorted(grade1, key=lambda x: x["path"]):
    print(f'{g["id"]} | {g["title"]} | {g["path"]} | {g["edition"]}')

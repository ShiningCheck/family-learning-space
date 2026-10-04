# -*- coding: utf-8 -*-
"""生成教材库索引 index.json：学科 -> 页码映射/目录/图片路径"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from data_paths import textbooks_dir  # noqa: E402

ROOT = str(textbooks_dir())   # 教材库在仓库之外的 data-root（见 project_rules.md 第 8 节）
meta = json.load(open(os.path.join(ROOT, "book_meta.json"), encoding="utf-8"))
manifest = json.load(open(os.path.join(ROOT, "manifest.json"), encoding="utf-8"))

INFO = {
    "语文": {"publisher": "人民教育出版社（统编）", "offset": 5},
    "数学": {"publisher": "人民教育出版社", "offset": 5},
    "道德与法治": {"publisher": "人民教育出版社（统编）", "offset": 5},
    "科学": {"publisher": "教育科学出版社", "offset": 6},
    "美术": {"publisher": "人民美术出版社（主编：黄宗贤，2024版）", "offset": 6},
}

index = {
    # child 字段保持为空：孩子姓名属于个人数据，只存于 .trae/skills/*/data/config.json
    "child": "",
    "grade": "一年级",
    "semester": "2026-2027学年度第一学期",
    "source": "国家中小学智慧教育平台（官方）",
    "page_rule": "印刷页码 = PDF页序号 - offset；页图位于 pages/{学科}/p{PDF页序号:03d}.jpg",
    "books": {},
    "pending": {
        "英语": "外研版（一年级起点）：国家平台无小学英语电子课本，需外研社官方渠道或家长拍照补录",
        "音乐": "人音版（赵季平主编2024版）：平台 CDN 对象当前返回 400，服务端临时异常，稍后重试 download_rest.py",
        "体育与健康": "平台详情接口 403，暂不可得",
        "书法": "人美版书法：国家平台未收录",
    },
}

for subject, m in meta.items():
    if subject not in INFO:
        continue
    pages_dir = os.path.join(ROOT, "pages", subject)
    n_pages = len([f for f in os.listdir(pages_dir) if f.endswith(".jpg")])
    offset = INFO[subject]["offset"]
    chapters = []
    for c in m.get("chapters", []):
        pp = c.get("pdf_page")
        chapters.append({
            "title": c["title"],
            "print_page": pp - offset if pp else None,
            "pdf_page": pp,
        })
    index["books"][subject] = {
        "title": manifest.get(subject, {}).get("title", ""),
        "publisher": INFO[subject]["publisher"],
        "contentId": m["contentId"],
        "offset": offset,
        "pdf_pages": n_pages,
        "print_pages": n_pages - offset,
        "pages_dir": f"pages/{subject}",
        "pdf": manifest.get(subject, {}).get("pdf"),
        "chapters": chapters,
    }

# 美术：平台映射接口暂不可用，章节取自目录页（印刷页码）
MS_CHAPTERS = [
    ("第一单元 我是校园小主人", None), ("1 介绍我自己", 2), ("2 我的新朋友", 4), ("3 画一画我们的学校", 7),
    ("第二单元 我与美丽大自然", None), ("1 调皮多变的点", 11), ("2 欢快流畅的线", 14), ("3 涂涂抹抹的快乐", 17), ("4 你拓我印的游戏", 20),
    ("第三单元 我是生活小达人", None), ("1 我给瓶子穿“新衣”", 24), ("2 瓶子大变身", 27), ("3 我用瓶盖来拼摆", 30),
    ("第四单元 我的家乡味", None), ("1 巧手捏花馍", 34), ("2 巧做花点心", 38), ("3 小小美食节", 41),
    ("第五单元 红火中国年", None), ("1 巧剪小团花", 45), ("2 巧手饰新年", 49), ("3 最爱中国红", 52),
]
_ms_dir = os.path.join(ROOT, "pages", "美术")
ms_pages = len([f for f in os.listdir(_ms_dir) if f.endswith(".jpg")]) if os.path.isdir(_ms_dir) else 0
index["books"]["美术"] = {
    "title": "（根据2022年版课程标准修订）义务教育教科书·美术一年级上册",
    "publisher": INFO["美术"]["publisher"],
    "contentId": "bb6399d6-24cc-42cd-ae44-304dc3215f1b",
    "offset": 6,
    "pdf_pages": ms_pages,
    "print_pages": ms_pages - 6,
    "pages_dir": "pages/美术",
    "pdf": manifest.get("美术", {}).get("pdf"),
    "chapters": [{"title": t, "print_page": p, "pdf_page": p + 6 if p else None} for t, p in MS_CHAPTERS],
}

json.dump(index, open(os.path.join(ROOT, "index.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("index.json saved")
for s, b in index["books"].items():
    print(f'{s}: pdf_pages={b["pdf_pages"]} print_pages={b["print_pages"]} chapters={len(b["chapters"])}')

# -*- coding: utf-8 -*-
"""按教材版本筛选目标教材，输出 target_books.json 供 download_books.py 使用

先运行 find_books.py 生成年级教材列表（grade1_books.json），再运行本脚本。
教材版本优先读取 <data-root>/bag/data/config.json 的
textbooks 字段（setup.py 首次引导时写入，可适配任意省份版本）；
无配置时使用内置默认（人教版体系示例）。
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from data_paths import skill_dir  # noqa: E402

CONFIG = str(skill_dir("school-bag-organizer") / "data" / "config.json")

books = json.load(open(os.path.join(HERE, "grade1_books.json"), encoding="utf-8"))

# 默认目标：学科 -> (平台路径中的学科关键词, 出版社关键词列表, 册次)
DEFAULT_TARGETS = {
    "语文": ("语文", ["人教版", "统编"], "上册"),
    "数学": ("数学", ["人教版"], "上册"),
    "英语": ("英语", ["外研版"], "上册"),
    "道德与法治": ("道德与法治", ["人教版", "统编"], "上册"),
    "科学": ("科学", ["教科版"], "上册"),
    "美术": ("美术", ["人美版"], "上册"),
    "音乐": ("音乐", ["人音版"], "上册"),
    "书法": ("书法", ["人美版"], None),
    "体育": ("体育与健康", ["人教版"], None),
}


def load_targets():
    """从用户配置的教材版本生成筛选目标；配置缺失时回退默认。"""
    try:
        cfg = json.load(open(CONFIG, encoding="utf-8"))
        targets = {}
        for subject, ver in (cfg.get("textbooks") or {}).items():
            ver = str(ver)
            if not ver or "校本" in ver:
                continue
            # 形如“人教版（部编版）”“外研版（一年级起点）”：取括号前的出版社名作关键词
            base = ver.split("（")[0].split("(")[0].strip()
            kws = [base] if base else []
            if "部编" in ver:
                kws.append("统编")
            subj_kw = "体育与健康" if subject == "体育" else subject
            targets[subject] = (subj_kw, kws, "上册")
        if targets:
            return targets
    except (OSError, ValueError):
        pass
    return DEFAULT_TARGETS


targets = load_targets()

result = {}
for subject, (subj_kw, editions, volume) in targets.items():
    matches = []
    for b in books:
        path = b["path"]
        title = b["title"] or ""
        # 路径形如: .../电子教材/小学/学科/出版社/年级/册次
        if subj_kw not in path:
            continue
        if editions and not any(e in path for e in editions):
            continue
        if volume and volume not in path:
            continue
        # 排除教师用书、活动手册等
        if any(x in title for x in ("教师", "教参", "活动手册", "学生活动手册")):
            continue
        matches.append(b)
    result[subject] = matches
    print(f"=== {subject} ({len(matches)}) ===")
    for m in matches:
        print(f'  {m["id"]} | {m["title"]} | {"/".join(m["path"].split("/")[3:])}')

json.dump(result, open(os.path.join(HERE, "target_books.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("\nsaved target_books.json（download_books.py 会优先使用它）")

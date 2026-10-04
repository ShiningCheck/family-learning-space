# -*- coding: utf-8 -*-
"""把仓库内的隐私数据迁到仓库外的 data-root（见 project_rules.md 第 8 节）。

**两阶段、默认不删任何东西**：
  阶段一  `--apply`   只**复制**到 data-root，仓库内那份原样保留（服务器还没改造前照样能跑）；
  阶段二  `--cleanup` 服务器改造并验收通过后，才删除仓库内的数据目录（先备份）。

两个阶段都会把要动的源目录先备份到 `<root>/_backup_<时间戳>/` 并写 journal.json，
`--rollback <备份目录>` 可原样还原。

用法：
  python tools/migrate_to_data_root.py --data-root D:\\data            # dry-run 看计划
  python tools/migrate_to_data_root.py --data-root D:\\data --apply    # 阶段一：复制
  python tools/migrate_to_data_root.py --data-root D:\\data --cleanup  # 阶段二：删仓库内那份
  python tools/migrate_to_data_root.py --rollback D:\\data\\_backup_20261002-120000
"""
import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
sys.path.insert(0, str(HERE))

from data_paths import data_dirs, skill_namespace  # noqa: E402

# 根级条目： (仓库内相对路径, data-root 下相对路径或 None, 说明)
# dst 为 None 表示「只删不迁」——可重生成的产物，阶段二才清理。
ROOT_ITEMS = [
    ("personal", "personal", "根级隐私内容（隐私词表；原「个人规划区」已停用并删除）"),
    ("textbooks", "textbooks", "教材 PDF 与页图（体积大、不入库）"),
    ("school/语文-一年级能力清单.md", "learn/capability-lists/语文-一年级能力清单.md",
     "学习看板引用的能力清单"),
    ("school/数学-一年级能力清单.md", "learn/capability-lists/数学-一年级能力清单.md",
     "学习看板引用的能力清单"),
    ("画作档案", "_legacy/画作档案",
     "遗留的早期画作目录（与技能 data/ 第 1 幅重复，保留待人工核对，不合并覆盖）"),
    ("commercialization-plan", "_moved-out/commercialization-plan",
     "作者的商业计划，移出开源仓库"),
    (".trae-html-share-packages/school_checklist_standalone.html.zip",
     "bag/share/school_checklist_standalone.html.zip",
     "含真实课表/通知的分享包 → 书包页数据区"),
    (".trae-html-share-packages/commercialization-plan", None, "可重生成的分享缓存"),
    (".trae-html-share-packages/tts-samples", None, "可重生成的分享缓存"),
    (".trae-html-share-packages/yuwen-family-game", None, "可重生成的分享缓存"),
]


class Item:
    def __init__(self, kind, src, dst, note):
        self.kind = kind
        self.src = src
        self.dst = dst
        self.note = note


def build_plan(root):
    items = []
    skills_root = REPO_ROOT / ".trae" / "skills"
    for skill_path in sorted(skills_root.iterdir()) if skills_root.is_dir() else []:
        if not skill_path.is_dir():
            continue
        skill = skill_path.name
        ns = skill_namespace(skill)
        for name in data_dirs(skill):
            src = skill_path / name
            if src.exists():
                items.append(Item("技能数据", src, root / ns / name,
                                  "%s/%s → %s/" % (skill, name, ns)))
    for rel, dst_rel, note in ROOT_ITEMS:
        src = REPO_ROOT / rel
        if src.exists():
            items.append(Item("根级数据", src, (root / dst_rel) if dst_rel else None, note))
    return items


def human(path):
    try:
        return str(Path(path).relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def count_files(path):
    p = Path(path)
    if p.is_file():
        return 1
    return sum(1 for f in p.rglob("*") if f.is_file())


def print_plan(root, items):
    copies = [i for i in items if i.dst]
    deletes = [i for i in items if not i.dst]
    print("data-root: %s" % root)
    print("仓库根  : %s" % REPO_ROOT)
    print("")
    print("阶段一 --apply 将复制 %d 项（仓库内那份不动）：" % len(copies))
    for it in copies:
        print("  [%s] %s\n        → %s   （%s）" % (it.kind, human(it.src), it.dst, it.note))
    print("")
    print("阶段二 --cleanup 才会删除仓库内这 %d 项（先备份）：" % len(items))
    for it in items:
        tag = "仅删" if not it.dst else "删仓库内副本"
        print("  [%s] %s   （%s）" % (tag, human(it.src), it.note))
    print("")
    print("这是 dry-run，未改动任何文件。")


def _backup(src, backup):
    rel = src.relative_to(REPO_ROOT)
    bak = backup / rel
    bak.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(src, bak, dirs_exist_ok=True)
    else:
        shutil.copy2(src, bak)
    return rel


def _remove(path):
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def _prune_empty_repo_dirs():
    for d in sorted((REPO_ROOT / ".trae" / "skills").glob("*/data"), reverse=True):
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()
    for name in ("school", ".trae-html-share-packages"):
        p = REPO_ROOT / name
        if p.is_dir() and not any(p.iterdir()):
            p.rmdir()


def do_apply(root, items):
    """阶段一：只复制，不动仓库内那份。"""
    copied = 0
    problems = []
    for it in items:
        if not it.dst:
            continue
        if it.dst.exists():
            print("  [跳过] 目标已存在：%s" % it.dst)
            continue
        it.dst.parent.mkdir(parents=True, exist_ok=True)
        if it.src.is_dir():
            shutil.copytree(it.src, it.dst, dirs_exist_ok=True)
        else:
            shutil.copy2(it.src, it.dst)
        n_src, n_dst = count_files(it.src), count_files(it.dst)
        if n_src != n_dst:
            problems.append("%s 文件数不一致（源 %d / 目标 %d）" % (human(it.src), n_src, n_dst))
        copied += 1
        print("  [复制] %s → %s（%d 个文件）" % (human(it.src), it.dst, n_dst))
    print("")
    print("阶段一完成：复制 %d 项，仓库内数据原样保留。" % copied)
    if problems:
        print("以下项需要人工核对：")
        for p in problems:
            print("  [!] %s" % p)
        return 1
    return 0


def do_cleanup(root, items, no_backup=False):
    """阶段二：备份后删除仓库内的数据目录。

    no_backup=True 时跳过备份（用于沙箱/只读环境无法在 data-root 下建备份目录的情况）——
    此时 data-root 里阶段一复制的那份就是唯一副本，删除前请确认它完整。
    """
    if no_backup:
        print("  [提示] --no-backup：不建备份，直接删除仓库内副本。")
        print("         请确认 data-root 里阶段一复制的那份完整（可先跑 setup.py --check 体检）。")
        removed = []
        for it in items:
            rel = it.src.relative_to(REPO_ROOT)
            _remove(it.src)
            removed.append(str(rel).replace("\\", "/"))
            print("  [删除] %s" % rel)
        _prune_empty_repo_dirs()
        print("\n阶段二完成（未备份）。")
        return 0

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = root / ("_backup_%s" % stamp)
    backup.mkdir(parents=True, exist_ok=True)
    journal = {"backup": str(backup), "time": stamp, "removed": []}
    for it in items:
        rel = _backup(it.src, backup)
        _remove(it.src)
        journal["removed"].append({"rel": str(rel).replace("\\", "/")})
        print("  [删除] %s（已备份）" % rel)
    (backup / "journal.json").write_text(
        json.dumps(journal, ensure_ascii=False, indent=2), encoding="utf-8")
    _prune_empty_repo_dirs()
    print("")
    print("阶段二完成。备份与回滚日志：%s" % backup)
    print("回滚：python tools/migrate_to_data_root.py --rollback \"%s\"" % backup)
    return 0


def do_rollback(backup):
    journal_path = Path(backup) / "journal.json"
    if not journal_path.exists():
        print("找不到回滚日志：%s" % journal_path)
        return 1
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    backup_dir = Path(journal["backup"])
    for entry in journal.get("removed", []):
        src = backup_dir / entry["rel"]
        dst = REPO_ROOT / entry["rel"]
        if not src.exists():
            print("  [跳过] 备份里没有 %s" % entry["rel"])
            continue
        if dst.exists():
            print("  [跳过] 仓库内已存在 %s（不覆盖）" % entry["rel"])
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        print("  [还原] %s" % entry["rel"])
    print("回滚完成。")
    return 0


def main():
    ap = argparse.ArgumentParser(description="把仓库内的隐私数据迁到仓库外 data-root")
    ap.add_argument("--data-root", help="仓库外的数据区根目录（绝对路径）")
    ap.add_argument("--apply", action="store_true", help="阶段一：复制到 data-root（默认只 dry-run）")
    ap.add_argument("--cleanup", action="store_true", help="阶段二：删除仓库内的数据副本（先备份）")
    ap.add_argument("--no-backup", action="store_true",
                    help="配合 --cleanup：不建备份直接删（沙箱里无法在 data-root 下建目录时用）")
    ap.add_argument("--rollback", metavar="BACKUP_DIR", help="按备份目录回滚")
    args = ap.parse_args()

    if args.rollback:
        return do_rollback(args.rollback)

    if not args.data_root:
        print("请用 --data-root 指定仓库外的数据区根目录（绝对路径）。")
        return 2
    root = Path(args.data_root).expanduser().resolve()
    try:
        root.relative_to(REPO_ROOT)
    except ValueError:
        pass
    else:
        print("data-root 不能落在仓库内：%s" % root)
        return 2

    items = build_plan(root)
    if not items:
        print("没有需要迁移的数据目录（仓库内已经是干净的）。")
        return 0
    if args.cleanup:
        return do_cleanup(root, items, no_backup=args.no_backup)
    if args.apply:
        return do_apply(root, items)
    print_plan(root, items)
    return 0


if __name__ == "__main__":
    sys.exit(main())
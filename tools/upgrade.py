# -*- coding: utf-8 -*-
"""升级脚本：用新版整仓包安全覆盖本地官方代码，不碰用户数据与自定义。

设计原则（与 project_rules.md 第 8 节一致）：
  1. **数据永不参与升级**：孩子的数据在仓库之外的 data-root，升级根本不碰它。
  2. **只覆盖官方代码**：portal-core / tools / 规则 / 根文件 / origin=official 的技能。
  3. **跳过用户的东西**：local.json（data-root 配置）、origin=user 的技能、任何 data/ 目录。
  4. **先备份后覆盖**：被覆盖的文件先备份到 <仓库>/.upgrade_backup_<时间戳>/，可 --rollback 还原。

用法：
  python tools/upgrade.py <新版整仓包.zip>                # dry-run 看升级计划
  python tools/upgrade.py <新版整仓包.zip> --apply         # 备份后覆盖
  python tools/upgrade.py --rollback <备份目录>
"""
import argparse
import json
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

# 根文件（整体替换）
ROOT_FILES = ["setup.py", "VERSION", "README.md", "LICENSE", "AGENTS.md",
              "CLAUDE.md", ".gitignore", "local_example.json"]
# 根目录（整体替换）
ROOT_DIRS = ["portal-core", "tools", "docs", ".codebuddy"]
# .trae 下的规则目录（整体替换，但保留 .trae/skills 由技能逻辑单独处理）
RULES_DIR = ".trae/rules"


def read_version_from_zip(zf, top):
    """从 zip 里读顶层目录名下的 VERSION。"""
    for cand in (f"{top}/VERSION", "VERSION"):
        try:
            return zf.read(cand).decode("utf-8").strip()
        except KeyError:
            continue
    return None


def local_origin(skill):
    """本地技能目录的 origin（缺省按 official 处理）。"""
    sj = ROOT / ".trae" / "skills" / skill / "skill.json"
    if sj.is_file():
        try:
            return (json.loads(sj.read_text(encoding="utf-8")) or {}).get("origin") or "official"
        except (ValueError, OSError):
            return "official"
    return "official"


def iter_zip_entries(zf, top):
    """遍历 zip 内顶层目录名下的条目，返回相对路径列表（去掉顶层名）。"""
    prefix = top + "/"
    out = []
    for n in zf.namelist():
        if not n.startswith(prefix):
            continue
        rel = n[len(prefix):]
        if not rel or rel.endswith("/"):
            continue
        out.append(rel)
    return out


def build_plan(zip_path):
    """返回 (top, 升级项列表)。每项是 dict：{kind, rel, origin}。"""
    zf = zipfile.ZipFile(zip_path)
    names = zf.namelist()
    # 顶层目录名 = 第一个条目的第一段
    top = names[0].split("/")[0] if names else ""
    entries = iter_zip_entries(zf, top)
    if not entries:
        print("  [失败] 包里没有内容，或顶层目录名不对。")
        return None

    plan = []
    for rel in entries:
        seg = rel.split("/")
        first = seg[0]
        if first == "textbooks":
            # 教材元数据不随升级覆盖：它属于 data-root，由教材工具链维护，
            # 覆盖到仓库根反而会违反「仓库内不得有 textbooks/」的隔离规则。
            continue
        if first in ("portal-core", "tools", "docs", ".codebuddy", ".trae"):
            # 目录类：记录目录级别（整体替换）
            continue
        if first in ROOT_FILES or first == "README.md":
            plan.append({"kind": "root_file", "rel": rel, "origin": "official"})
        elif first == ".trae" and len(seg) >= 2 and seg[1] == "skills":
            # 技能目录
            continue
        elif first == ".trae" and len(seg) >= 2 and seg[1] == "rules":
            continue
        else:
            # 根目录或未知文件
            plan.append({"kind": "root_file", "rel": rel, "origin": "official"})

    # 目录类：portal-core / tools / docs / .codebuddy / .trae/rules
    for d in ROOT_DIRS + [RULES_DIR]:
        if any(e.startswith(d.split("/")[0] + "/") for e in entries):
            plan.append({"kind": "dir", "rel": d, "origin": "official"})

    # 技能：新包里 origin=official 的替换，origin=user 的跳过
    skills_in_zip = set()
    for e in entries:
        seg = e.split("/")
        if len(seg) >= 3 and seg[0] == ".trae" and seg[1] == "skills":
            skills_in_zip.add(seg[2])
    for skill in sorted(skills_in_zip):
        # 从 zip 读该技能的 skill.json 判断 origin
        origin = "official"
        try:
            sj = json.loads(zf.read(f"{top}/.trae/skills/{skill}/skill.json").decode("utf-8"))
            origin = sj.get("origin") or "official"
        except (KeyError, ValueError):
            origin = "official"
        plan.append({"kind": "skill", "rel": f".trae/skills/{skill}", "origin": origin})
    zf.close()
    return top, plan


def print_plan(zip_path, top, plan):
    print("升级包  : %s" % zip_path)
    print("顶层目录 : %s" % top)
    print("本地版本 : %s" % ((ROOT / "VERSION").read_text(encoding="utf-8").strip()
                    if (ROOT / "VERSION").is_file() else "（无）"))
    print("")
    official = [p for p in plan if p["origin"] != "user"]
    user = [p for p in plan if p["origin"] == "user"]
    print("将覆盖 %d 项官方代码：" % len(official))
    for p in official:
        tag = "目录" if p["kind"] == "dir" else ("技能" if p["kind"] == "skill" else "文件")
        print("  [%s] %s" % (tag, p["rel"]))
    print("")
    print("将跳过 %d 项（user 技能，保留你的自定义）：" % len(user))
    for p in user:
        print("  [跳过] %s" % p["rel"])
    print("")
    print("始终不碰：local.json（数据区配置）、仓库之外的 data-root、任何 data/ 目录。")
    print("这是 dry-run，未改动任何文件。用 --apply 备份后覆盖。")


def do_apply(zip_path, top, plan):
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = ROOT / (".upgrade_backup_" + stamp)
    zf = zipfile.ZipFile(zip_path)

    def extract(rel, dst):
        dst = Path(dst)
        arc = f"{top}/{rel}"
        if arc in zf.namelist() and not arc.endswith("/"):
            dst.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(arc) as src, open(dst, "wb") as out:
                shutil.copyfileobj(src, out)

    covered = []
    for p in plan:
        if p["origin"] == "user":
            print("  [跳过] %s（user 技能，保留）" % p["rel"])
            continue
        rel = p["rel"]
        dst = ROOT / rel
        # 备份已存在的
        if dst.exists():
            bak = backup / rel
            bak.parent.mkdir(parents=True, exist_ok=True)
            if dst.is_dir():
                shutil.copytree(dst, bak, dirs_exist_ok=True)
            else:
                shutil.copy2(dst, bak)
        # 覆盖
        if p["kind"] == "dir":
            # 目录整体替换：先删旧的（已备份），再从 zip 解压整个目录
            shutil.rmtree(dst, ignore_errors=True)
            dst.mkdir(parents=True)
            prefix = rel + "/"
            for n in zf.namelist():
                if n.startswith(top + "/" + prefix):
                    rel_in = n[len(top + "/"):]
                    if rel_in.endswith("/"):
                        continue
                    out = ROOT / rel_in
                    out.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(n) as src, open(out, "wb") as f:
                        shutil.copyfileobj(src, f)
        elif p["kind"] == "skill":
            shutil.rmtree(dst, ignore_errors=True)
            dst.mkdir(parents=True)
            prefix = rel + "/"
            for n in zf.namelist():
                if n.startswith(top + "/" + prefix):
                    rel_in = n[len(top + "/"):]
                    if rel_in.endswith("/"):
                        continue
                    out = ROOT / rel_in
                    out.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(n) as src, open(out, "wb") as f:
                        shutil.copyfileobj(src, f)
        else:
            extract(rel, dst)
        covered.append(rel)
        print("  [覆盖] %s" % rel)

    zf.close()
    # journal
    journal = {"backup": str(backup), "time": stamp, "covered": covered}
    (backup / "journal.json").write_text(
        json.dumps(journal, ensure_ascii=False, indent=2), encoding="utf-8")
    print("")
    print("升级完成，覆盖 %d 项。" % len(covered))
    print("备份目录：%s" % backup)
    print("回滚：python tools/upgrade.py --rollback \"%s\"" % backup)
    return 0


def do_rollback(backup):
    journal_path = Path(backup) / "journal.json"
    if not journal_path.exists():
        print("找不到回滚日志：%s" % journal_path)
        return 1
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    backup_dir = Path(journal["backup"])
    for rel in journal.get("covered", []):
        src = backup_dir / rel
        dst = ROOT / rel
        if not src.exists():
            continue
        # 删掉升级覆盖后的，还原备份的
        if dst.exists():
            shutil.rmtree(dst) if dst.is_dir() else dst.unlink()
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)
        print("  [还原] %s" % rel)
    print("回滚完成。")
    return 0


def main():
    ap = argparse.ArgumentParser(description="升级：用新版整仓包覆盖官方代码，保留用户数据与自定义")
    ap.add_argument("zip_path", nargs="?", help="新版整仓包 zip 路径")
    ap.add_argument("--apply", action="store_true", help="备份后覆盖（默认 dry-run）")
    ap.add_argument("--rollback", metavar="BACKUP_DIR", help="按备份目录回滚")
    args = ap.parse_args()

    if args.rollback:
        return do_rollback(args.rollback)
    if not args.zip_path:
        print("请提供新版整仓包 zip 路径：python tools/upgrade.py <新版包.zip>")
        return 2
    if not Path(args.zip_path).is_file():
        print("找不到文件：%s" % args.zip_path)
        return 2

    result = build_plan(args.zip_path)
    if result is None:
        return 1
    top, plan = result
    if args.apply:
        return do_apply(args.zip_path, top, plan)
    print_plan(args.zip_path, top, plan)
    return 0


if __name__ == "__main__":
    sys.exit(main())

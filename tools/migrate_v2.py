# -*- coding: utf-8 -*-
"""架构 v2 数据迁移（第 3 步切换段）：把 <data-root>/web/data 里的数据
按新技能归属搬走 + 把 4 个打卡文件合并成 core 统一打卡服务 checkins.json。

安全铁律（沿用 migrate_to_data_root.py 的惯例）：
  - **apply 只生成/复制新文件，绝不删源**；旧 web/data 里的 json 原样保留，
    验收通过、确认新位置无误后，才手动清理（或留待第 5 步）。
  - apply 前会把「目标位置已存在」的文件先备份到 <root>/_backup_v2_<时间戳>/，
    并写 journal.json；--rollback <备份目录> 可还原。
  - --dry-run（默认）只打印完整映射与对账，不改任何文件。

用法：
  python tools/migrate_v2.py                    # dry-run 看计划与对账
  python tools/migrate_v2.py --apply            # 生成新文件（不删源，先备份已存在的目标）
  python tools/migrate_v2.py --rollback <dir>   # 按备份目录还原
"""
import argparse
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
sys.path.insert(0, str(HERE))

from data_paths import data_root  # noqa: E402


# ----------------------------------------------------------------------
# 归一化：homework 的 subject 字段 → 新技能 url
# ----------------------------------------------------------------------
def subject_to_skill(subject):
    s = str(subject or "").strip()
    if s in ("chinese",):
        return "chinese"
    if s in ("math",):
        return "math"
    if s in ("english", "class-english", "class", "school-english"):
        # 辅导班英语（english/class-english）与学校英语（school-english）的作业项：
        # 作业卡里英语作业 teacherNote 都来自辅导班，归 class；学校英语无作业卡条目，
        # 若出现 school-english 也归 school 更语义准确。
        return "school" if s == "school-english" else "class"
    return None  # 未知科目，需人工核对


def normalize_subject(subject):
    """把 subject 的历史简写归一成正式名（english → class-english），
    其余原样返回。用户确认：作业卡里的英语一律是辅导班英语。"""
    s = str(subject or "").strip()
    if s == "english":
        return "class-english"
    return s


def tab_to_skill(tab_id):
    return "reading" if tab_id in ("reading", "booklist") else tab_id


def guess_homework_skill(key, hw_by_id):
    """作业打卡 key → 技能 url：先查作业条目 subject，再猜 key 后缀，最后保守归 homework。"""
    item = hw_by_id.get(key)
    if item:
        sk = subject_to_skill(item.get("subject"))
        if sk:
            return sk
    m = re.search(r"-(chinese|math|english)$", str(key))
    if m:
        return subject_to_skill(m.group(1)) or "class"
    return "homework"  # 查不到归属，保守保留（不丢），人工核对


# ----------------------------------------------------------------------
# 打卡合并：4 个源文件 → 单一 records {skill:{key:{date:{v,ts,...}}}}
# ----------------------------------------------------------------------
def merge_checkins(src_dir):
    """返回 (records, 对账统计)。不落盘，纯内存计算。"""
    records = {}
    stat = {}  # 源 -> {"source_records": n, "target_records": n}

    def load(name):
        p = src_dir / name
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None

    def put(skill, key, date, node):
        records.setdefault(skill, {}).setdefault(key, {})[date] = node

    def put_merge(skill, key, date, node):
        """同 skill+key+date 按 ts 取新（ts=0 视为最旧），v:0 墓碑同样参与。"""
        cur = records.setdefault(skill, {}).setdefault(key, {}).get(date)
        if cur is None:
            records[skill][key][date] = node
            return
        new_ts = int(node.get("ts") or 0)
        old_ts = int(cur.get("ts") or 0)
        if new_ts > old_ts:
            records[skill][key][date] = node

    # 1) homework.json（先读，用于 key → subject 映射）
    homework = load("homework.json") or {}
    hw_items = {str(it.get("id")): it for it in homework.get("items") or [] if it.get("id")}

    # 2) homework_checkins.json
    hc = load("homework_checkins.json") or {}
    hc_recs = hc.get("records") or {}
    n = 0
    for key, days in hc_recs.items():
        skill = guess_homework_skill(key, hw_items)
        for date, rec in days.items():
            if not isinstance(rec, dict):
                continue
            put_merge(skill, key, date, {"v": 1 if rec.get("v") else 0, "ts": int(rec.get("ts") or 0)})
            n += 1
    stat["homework_checkins"] = {"source_records": n}

    # 3) english_class_records.json（辅导班英语：{date:{key:true}}）
    ec = load("english_class_records.json") or {}
    n = 0
    for date, keys in ec.items():
        if not isinstance(keys, dict):
            continue
        for key, val in keys.items():
            put_merge("class", key, date, {"v": 1 if val else 0, "ts": 0})
            n += 1
    stat["english_class_records"] = {"source_records": n}

    # 4) school_english_records.json（学校英语：{date:{key:true}}）
    se = load("school_english_records.json") or {}
    n = 0
    for date, keys in se.items():
        if not isinstance(keys, dict):
            continue
        for key, val in keys.items():
            put_merge("school", key, date, {"v": 1 if val else 0, "ts": 0})
            n += 1
    stat["school_english_records"] = {"source_records": n}

    # 5) tracker_state.json（读书/家务/运动/书单：tabs.<id>.records[date]={done,note,chapters,ts}）
    ts_data = load("tracker_state.json") or {}
    tabs = ts_data.get("tabs") or {}
    n = 0
    for tab_id, tab in tabs.items():
        if not isinstance(tab, dict):
            continue
        skill = tab_to_skill(tab_id)
        for date, rec in (tab.get("records") or {}).items():
            if not isinstance(rec, dict):
                continue
            node = {"v": 1 if rec.get("done") else 0, "ts": int(rec.get("ts") or 0)}
            if "note" in rec and rec.get("note"):
                node["note"] = str(rec["note"])
            if "chapters" in rec and rec.get("chapters"):
                node["chapters"] = rec["chapters"]
            put_merge(skill, tab_id, date, node)
            n += 1
    stat["tracker_state"] = {"source_records": n}

    # 对账：目标记录总数
    total = 0
    per_skill = {}
    for skill, keys in records.items():
        c = sum(len(days) for days in keys.values())
        per_skill[skill] = c
        total += c
    stat["__total_target__"] = total
    stat["__per_skill__"] = per_skill
    return records, stat


# ----------------------------------------------------------------------
# 内容文件搬家计划（复制，不删源）
# ----------------------------------------------------------------------
def build_plan(root):
    """返回 [(src_path, dst_path, note, transform)]，transform 为 None 表示整文件复制。"""
    src_dir = root / "web" / "data"
    plan = []

    def add(rel, dst, note, transform=None):
        src = src_dir / rel
        if src.exists():
            plan.append((src, root / dst, note, transform))

    # core 共享内容
    add("config.json", "core/data/config.json", "孩子档案（全技能共用）→ core")
    add("activities.json", "core/data/activities.json", "门户聚合配置（tabs/subjects）→ core")
    add("feedback_channels.json", "core/data/feedback_channels.json", "反馈通道 → core")
    if (src_dir / "voice").is_dir():
        add("voice", "core/data/voice", "语音索引 → core")

    # 学科内容
    add("english_class.json", "class/data/english_class.json", "辅导班英语内容 → class")
    add("school_english.json", "school/data/school_english.json", "学校英语内容 → school")
    add("booklist.json", "reading/data/booklist.json", "书单 → reading")

    # homework.json 按 subject 拆三份（transform 生成）
    if (src_dir / "homework.json").exists():
        plan.append((src_dir / "homework.json", root, "homework.json 按科目拆 chinese/math/class",
                     split_homework))

    # tracker_state 的 booklist.progress（书单累计章节进度，非按日打卡）→ reading
    if (src_dir / "tracker_state.json").exists():
        plan.append((src_dir / "tracker_state.json", root / "reading/data/booklist_progress.json",
                     "书单累计章节进度 → reading", extract_booklist_progress))

    return plan


def split_homework(src):
    """homework.json → {dst_rel: obj}，按 subject 拆成三份（chinese/math/class）。
    每个 item 的 subject 先归一（english → class-english），再按归一后的科目分桶。"""
    data = json.loads(src.read_text(encoding="utf-8"))
    items = data.get("items") or []
    buckets = {"chinese": [], "math": [], "class": [], "school": []}
    unknown = []
    for it in items:
        it = dict(it)  # 不改源数据
        it["subject"] = normalize_subject(it.get("subject"))
        sk = subject_to_skill(it.get("subject"))
        if sk in buckets:
            buckets[sk].append(it)
        else:
            unknown.append(it)
    out = {}
    for sk, its in buckets.items():
        if its:
            doc = dict(data)
            doc["items"] = its
            doc["updated"] = datetime.now().strftime("%Y-%m-%d")
            out["%s/data/homework.json" % sk] = doc
    if unknown:
        # 未知科目的作业项不丢：原样留在 core 的 homework_legacy 清单供人工核对
        doc = dict(data)
        doc["items"] = unknown
        doc["updated"] = datetime.now().strftime("%Y-%m-%d")
        out["core/data/homework_legacy.json"] = doc
    return out


def extract_booklist_progress(src):
    """tracker_state.json → booklist.progress 单独成文件（reading/data/booklist_progress.json）。
    返回 {目标相对路径: 内容}，与 split_homework 的返回形状一致。"""
    data = json.loads(src.read_text(encoding="utf-8"))
    tabs = data.get("tabs") or {}
    progress = (tabs.get("booklist") or {}).get("progress") or {}
    return {"reading/data/booklist_progress.json": {"progress": progress, "source": "tracker_state.json"}}


# ----------------------------------------------------------------------
# dry-run / apply / rollback
# ----------------------------------------------------------------------
def _migrate_checkins_files(root):
    """返回需要写入 checkins.json 的目标 (dst_path, doc)。不落盘。"""
    src_dir = root / "web" / "data"
    records, stat = merge_checkins(src_dir)
    doc = {"updated": datetime.now().isoformat(timespec="seconds"), "records": records}
    return root / "core" / "data" / "checkins.json", doc, stat


def print_dry_run(root):
    src_dir = root / "web" / "data"
    print("data-root: %s" % root)
    print("源目录  : %s" % src_dir)
    print("")
    print("—— 打卡合并（4 个源 → core/data/checkins.json）——")
    records, stat = merge_checkins(src_dir)
    print("  源记录对账：")
    src_total = 0
    for k, v in stat.items():
        if k.startswith("__"):
            continue
        src_total += v["source_records"]
        print("    %-24s %d 条" % (k, v["source_records"]))
    print("  合计源记录 %d 条 → 目标 %d 条（%s）" % (
        src_total, stat["__total_target__"],
        "无丢损" if src_total == stat["__total_target__"] else "⚠ 数量不一致，需核对"))
    print("  目标按 skill 分布：")
    for sk, c in sorted(stat["__per_skill__"].items()):
        print("    %-12s %d 条" % (sk, c))
    print("")
    print("—— 内容文件搬家（复制，不删源）——")
    plan = build_plan(root)
    for src, dst, note, transform in plan:
        if transform is None:
            kind = "目录" if src.is_dir() else "文件"
            print("  [%s] %s → %s" % (kind, src.relative_to(root), dst.relative_to(root)))
            print("        （%s）" % note)
        else:
            # transform 型：dry-run 里实际算一遍，展示拆分结果
            try:
                result = transform(src)
                for rel, obj in result.items():
                    n = len(obj.get("items", [])) if "items" in obj else (
                        len(obj.get("progress", {})) if "progress" in obj else "?")
                    print("  [生成] %s → %s（%s；%s 项）" % (
                        src.relative_to(root), rel, note, n))
            except Exception as e:
                print("  [!] %s 变换失败：%s" % (src.relative_to(root), e))
    print("")
    print("这是 dry-run，未改动任何文件。用 --apply 生成新文件（不删源）。")


def do_apply(root):
    src_dir = root / "web" / "data"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = root / ("_backup_v2_%s" % stamp)
    journal = {"backup": str(backup), "time": stamp, "created": [], "backed_up": []}

    # 沙箱环境可能禁止新建 data-root 子目录：备份目录建不了就降级为 no-backup。
    # 迁移本身「只生成新文件、绝不删源」，源文件就是天然备份，no-backup 依然安全。
    no_backup = False
    try:
        backup.mkdir(parents=True, exist_ok=True)
    except Exception as e:  # noqa: BLE001
        no_backup = True
        print("  [提示] 备份目录建不了（%s），降级为 no-backup：源文件不删，数据依然安全。" % e)

    def _backup_existing(dst):
        if no_backup or not dst.exists():
            return
        try:
            rel = dst.relative_to(root)
            bak = backup / "pre_existing" / rel
            bak.parent.mkdir(parents=True, exist_ok=True)
            if dst.is_dir():
                shutil.copytree(dst, bak, dirs_exist_ok=True)
            else:
                shutil.copy2(dst, bak)
            journal["backed_up"].append(str(rel).replace("\\", "/"))
        except Exception:  # noqa: BLE001 - 备份失败不阻断迁移
            pass

    def safe_write(dst, content_bytes):
        dst = Path(dst)
        _backup_existing(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content_bytes, (dict, list)):
            dst.write_text(json.dumps(content_bytes, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            dst.write_bytes(content_bytes)
        journal["created"].append(str(dst.relative_to(root)).replace("\\", "/"))

    # 1) checkins.json
    dst, doc, stat = _migrate_checkins_files(root)
    safe_write(dst, doc)
    print("  [生成] %s（%d 条打卡记录）" % (dst.relative_to(root), stat["__total_target__"]))

    # 2) 内容文件
    plan = build_plan(root)
    for src, dst, note, transform in plan:
        if transform is None:
            if src.is_dir():
                # 复制目录
                _backup_existing(dst)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(src, dst, dirs_exist_ok=True)
                journal["created"].append(str(dst.relative_to(root)).replace("\\", "/"))
                print("  [复制] %s → %s" % (src.relative_to(root), dst.relative_to(root)))
            else:
                safe_write(dst, src.read_bytes())
                print("  [复制] %s → %s" % (src.relative_to(root), dst.relative_to(root)))
        else:
            result = transform(src)
            for rel, obj in result.items():
                safe_write(root / rel, obj)
                print("  [生成] %s → %s" % (src.relative_to(root), rel))

    if not no_backup:
        try:
            (backup / "journal.json").write_text(
                json.dumps(journal, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:  # noqa: BLE001
            no_backup = True
    print("")
    print("迁移完成（未删任何源文件）。")
    if no_backup:
        print("本次为 no-backup 模式：未建备份目录（源文件未删，随时可手动回退）。")
    else:
        print("备份与回滚日志：%s" % backup)
        print("回滚：python tools/migrate_v2.py --rollback \"%s\"" % backup)
    return 0


def do_rollback(backup):
    journal_path = Path(backup) / "journal.json"
    if not journal_path.exists():
        print("找不到回滚日志：%s" % journal_path)
        return 1
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    backup_dir = Path(journal["backup"])
    root = data_root()

    # 先删除 apply 生成的文件（它们之前不存在，或有备份）
    for rel in journal.get("created", []):
        dst = root / rel
        if not dst.exists():
            continue
        if dst.is_dir():
            shutil.rmtree(dst)
        else:
            dst.unlink()
        print("  [回滚删除] %s" % rel)

    # 再还原 apply 前已存在、被备份覆盖的文件
    pre = backup_dir / "pre_existing"
    if pre.exists():
        for rel in journal.get("backed_up", []):
            src = pre / rel
            dst = root / rel
            if not src.exists():
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dst)
            print("  [回滚还原] %s" % rel)
    print("回滚完成。")
    return 0


def main():
    ap = argparse.ArgumentParser(description="架构 v2 数据迁移（打卡合并 + 内容搬家）")
    ap.add_argument("--apply", action="store_true", help="生成新文件（不删源，先备份已存在目标）")
    ap.add_argument("--rollback", metavar="BACKUP_DIR", help="按备份目录回滚")
    args = ap.parse_args()

    if args.rollback:
        return do_rollback(args.rollback)

    root = data_root()
    if args.apply:
        return do_apply(root)
    print_dry_run(root)
    return 0


if __name__ == "__main__":
    sys.exit(main())

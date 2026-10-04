# -*- coding: utf-8 -*-
"""门户接线员：把一页挂到「成长家园」门户上，并可撤销。

为什么需要它：新增一页今天要手改 4 处（`index.html` 的 CORE_TABS / TAB_ORDER、
`preview_server.py` 的兄弟技能挂载 / 可选 REDIRECTS），人手改必然漏、且不好回退。
这个脚本把接线变成确定动作：先备份、写日志、只做增量、随时 `undo`。

用法：
  python tools/portal_wire.py list                       # 看门户现状（已登记的标签页、挂载、重定向）
  python tools/portal_wire.py add-page --id piano --name 钢琴 --emoji 🎹 --src /web/piano.html
  python tools/portal_wire.py add-page --id piano --name 钢琴 --src /piano/web/index.html \
      --mount piano --skill piano-practice                # 页面在兄弟技能里：顺带加静态挂载
  python tools/portal_wire.py remove-page --id piano --unmount
  python tools/portal_wire.py undo                        # 撤销上一次操作
  任何写操作都可加 --dry-run 先看会改什么。

接线点（与 .trae/skills/portal-builder/references/page-contract.md 一致）：
  1. index.html  CORE_TABS    页面型标签（id/name/emoji/color/src）
  2. index.html  TAB_ORDER    菜单固定次序
  3. preview_server.py  REDIRECTS       旧书签兼容（可选）
  4. （静态挂载）**不再手改服务器**：兄弟技能的 URL 前缀由各技能自己的 skill.json 的
     `url` 字段声明，preview_server.py 启动时自动扫描挂载（见 tools/data_paths.py）。
     `--mount` 现在只做**校验**：确认该技能的 skill.json 存在且 url 与前缀一致。
  5. （数据侧）data/activities.json 的 tabs —— 那是用户数据不是代码，本脚本不动它，
     打卡型标签请让 AI 改数据文件。
"""
import argparse
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = ROOT / ".trae" / "skills"
# 门户 shell（CORE_TABS / TAB_ORDER 所在）已迁到 portal-core（架构 v2 第 2 步）
INDEX = ROOT / "portal-core" / "web" / "index.html"
SERVER = SKILLS_DIR / "growth-home" / "web" / "preview_server.py"
BACKUP_DIR = ROOT / ".portal-wire-backup"
JOURNAL = BACKUP_DIR / "journal.json"
IND = "  "


def _skip(msg):
    """幂等跳过：不是错误，退出码 0。"""
    print(msg)
    sys.exit(0)


def _fail(msg):
    """真的做不到：退出码 2，且不写任何文件。"""
    print(msg)
    sys.exit(2)


# ---------- 读写（保留原换行符，绝不整篇重写） ----------
def read_text(p):
    with open(p, encoding="utf-8", newline="") as f:
        return f.read()


def write_text(p, text):
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def backup(paths):
    BACKUP_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    saved = {}
    for p in paths:
        p = Path(p)
        if not p.is_file():
            continue
        dst = BACKUP_DIR / f"{stamp}-{p.name}"
        shutil.copy2(p, dst)
        saved[str(p)] = str(dst)
    return saved


def journal_append(entry):
    BACKUP_DIR.mkdir(exist_ok=True)
    data = []
    if JOURNAL.is_file():
        try:
            data = json.loads(JOURNAL.read_text(encoding="utf-8"))
        except ValueError:
            data = []
    data.append(entry)
    JOURNAL.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------- 解析现状 ----------
def parse_core_tabs(text):
    m = re.search(r"const CORE_TABS = \[(.*?)\n\];", text, re.DOTALL)
    if not m:
        return None, None
    body = m.group(1)
    rows = []
    for line in body.splitlines():
        mm = re.search(r"\{\s*id:\s*'([^']+)'.*?name:\s*'([^']+)'.*?emoji:\s*'([^']*)'.*?"
                       r"color:\s*'(#[0-9A-Fa-f]{3,8})'.*?src:\s*'([^']+)'", line)
        if mm:
            rows.append({"id": mm.group(1), "name": mm.group(2), "emoji": mm.group(3),
                         "color": mm.group(4), "src": mm.group(5)})
    return rows, (m.start(1), m.end(1))


def parse_tab_order(text):
    m = re.search(r"const TAB_ORDER = \[(.*?)\n\];", text, re.DOTALL)
    if not m:
        return None, None
    ids = re.findall(r"'([^']+)'", m.group(1))
    return ids, (m.start(1), m.end(1))


def parse_redirects(text):
    m = re.search(r"REDIRECTS = \{(.*?)\n\}", text, re.DOTALL)
    if not m:
        return []
    return re.findall(r'"([^"]+)":\s*"([^"]+)"', m.group(1))


def declared_namespaces():
    """扫各技能 skill.json：返回 [(前缀, 技能目录名)]，即服务器会自动挂载的命名空间。"""
    out = []
    if not SKILLS_DIR.is_dir():
        return out
    for skill_path in sorted(SKILLS_DIR.iterdir()):
        meta_path = skill_path / "skill.json"
        if not meta_path.is_file():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        ns = str(meta.get("url") or "").strip().strip("/")
        if ns and ns != "web":          # 门户自己走默认目录，不算兄弟挂载
            out.append((ns, skill_path.name))
    return out


def verify_mount(prefix, skill_dir):
    """挂载是否成立：该技能必须带 skill.json 且 url == 前缀（服务器据此自动挂载）。
    返回 (ok, 说明)。不做任何文件写入。"""
    meta_path = SKILLS_DIR / skill_dir / "skill.json"
    if not meta_path.is_file():
        return False, (f"[失败] 技能 {skill_dir} 没有 skill.json —— 服务器无法自动挂载 /{prefix}/。\n"
                       f"       请先补 skill.json（可用 python tools/new_skill.py 的模板），"
                       f"其中 url 写 \"{prefix}\"。")
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except ValueError as exc:
        return False, f"[失败] {meta_path} 解析失败：{exc}"
    url = str(meta.get("url") or "").strip().strip("/")
    if not url:
        return False, f"[失败] {skill_dir}/skill.json 缺少 url 字段（应为 \"{prefix}\"）"
    if url != prefix:
        return False, (f"[失败] skill.json 的 url={url!r} 与 --mount {prefix!r} 不一致；\n"
                       f"       请改成 --mount {url}，或把 skill.json 的 url 改为 {prefix!r}。")
    return True, f"已确认 /{prefix}/ → {skill_dir}（由 skill.json 声明，服务器自动挂载）"


# ---------- 各接线动作 ----------
def add_core_tab(text, tab):
    rows, _ = parse_core_tabs(text)
    if rows is None:
        _fail("[失败] 找不到 CORE_TABS（index.html 结构变了？）")
    if any(r["id"] == tab["id"] for r in rows):
        _skip(f"[跳过] CORE_TABS 里已有 id={tab['id']}")
    eol = "\r\n" if "\r\n" in text else "\n"
    line = (f"{IND}{{ id: '{tab['id']}', name: '{tab['name']}', emoji: '{tab['emoji']}', "
            f"color: '{tab['color']}', src: '{tab['src']}' }},")
    # 把「\r?\n」当成分隔符一起捕获，插进去的行才不会和原来的行尾混用（CRLF 文件里插一行 LF 会留下 \r 残渣）
    m = re.search(r"const CORE_TABS = \[(.*?)(\r?\n)\];", text, re.DOTALL)
    if m.group(2) != eol:
        _fail("[失败] CORE_TABS 行尾与本文件不一致，先人工看一眼")
    return text[:m.start(1)] + m.group(1) + eol + line + text[m.start(2):]


def add_tab_order(text, tab_id, after=None, before=None):
    """只做最小文本编辑（不重建整个数组），保证来回一次后文件与原文逐字节一致。"""
    ids, _ = parse_tab_order(text)
    if ids is None:
        _fail("[失败] 找不到 TAB_ORDER")
    if tab_id in ids:
        _skip(f"[跳过] TAB_ORDER 里已有 {tab_id}")

    def edit(body):
        if after and after in ids:
            i = body.index(f"'{after}'") + len(f"'{after}'")
            return body[:i] + f", '{tab_id}'" + body[i:]
        if before and before in ids:
            i = body.index(f"'{before}'")
            return body[:i] + f"'{tab_id}', " + body[i:]
        j = body.rindex("'") + 1            # 最后一个 token 的收尾引号之后
        return body[:j] + f", '{tab_id}'" + body[j:]

    m = re.search(r"const TAB_ORDER = \[(.*?)\n\];", text, re.DOTALL)
    return text[:m.start(1)] + edit(m.group(1)) + text[m.end(1):]


def add_redirect(text, old_path, target):
    if re.search(r'"%s":' % re.escape(old_path), text):
        _skip(f"[跳过] REDIRECTS 里已有 {old_path}")
    m = re.search(r"(REDIRECTS = \{(.*?))(\n\})", text, re.DOTALL)
    eol = "\r\n" if "\r\n" in text else "\n"
    return text[:m.end(2)] + eol + f'    "{old_path}": "{target}",' + text[m.end(2):]


def remove_core_tab(text, tab_id):
    m = re.search(r"const CORE_TABS = \[(.*?)(\r?\n)\];", text, re.DOTALL)
    # 按行拆分时把行尾符也拆掉（否则最后一行会残留一个 \r，删掉它后面那行就会多出空行）
    lines = re.split(r"\r?\n", m.group(1))
    kept = [l for l in lines if not re.search(r"\{\s*id:\s*'%s'" % re.escape(tab_id), l)]
    if len(kept) == len(lines):
        _skip(f"[跳过] CORE_TABS 里没有 id={tab_id}")
    return text[:m.start(1)] + m.group(2).join(kept) + text[m.start(2):]


def remove_tab_order(text, tab_id):
    ids, _ = parse_tab_order(text)
    if tab_id not in ids:
        _skip(f"[跳过] TAB_ORDER 里没有 {tab_id}")

    def edit(body):
        tok = f"'{tab_id}'"
        i = body.index(tok)
        tail = body[i + len(tok):]
        if tail.startswith(", "):                 # 形如 'a', 'b' → 删掉 "'a', "
            return body[:i] + tail[2:]
        head = body[:i]
        if head.endswith(", "):                   # 形如 'a', 'b' 的末尾 → 删掉 ", 'b'"
            return head[:-2] + body[i + len(tok):]
        return head + body[i + len(tok):]

    m = re.search(r"const TAB_ORDER = \[(.*?)\n\];", text, re.DOTALL)
    return text[:m.start(1)] + edit(m.group(1)) + text[m.end(1):]


def remove_mount(text, prefix):
    """挂载已改由 skill.json 声明，服务器不再有可删的分支——保留本函数只为兼容旧调用。"""
    return text


# ---------- 命令 ----------
def cmd_list(_):
    itext = read_text(INDEX)
    stext = read_text(SERVER)
    rows, _ = parse_core_tabs(itext)
    ids, _ = parse_tab_order(itext)
    print("== 门户现状：portal-core/web/（shell 已迁出 growth-home，架构 v2 第 2 步）")
    print(f"\n-- 页面型标签 CORE_TABS（{len(rows)} 个）")
    for r in rows:
        print(f"   {r['id']:<16} {r['emoji']} {r['name']:<10} {r['src']}")
    print(f"\n-- 菜单次序 TAB_ORDER（{len(ids)} 项）")
    print("   " + " → ".join(ids))
    print("\n-- 兄弟技能命名空间（各技能 skill.json 的 url，服务器自动挂载）")
    for ns, skill in declared_namespaces():
        print(f"   /{ns}/  →  {skill}")
    print(f"\n-- 旧书签重定向 REDIRECTS：{len(parse_redirects(stext))} 条")
    print("\n提示：打卡型标签（读书/家务/运动…）在数据文件 data/activities.json 的 tabs 里，不在上面这张表。")
    return 0


def cmd_add_page(args):
    # 挂载先校验（不写文件）：skill.json 声明了 url，服务器才会挂上
    if args.mount:
        ok, msg = verify_mount(args.mount, args.skill)
        if not ok:
            _fail(msg)

    plan = []
    itext = read_text(INDEX)
    new_i = add_core_tab(itext, {"id": args.id, "name": args.name,
                                 "emoji": args.emoji, "color": args.color, "src": args.src})
    plan.append("index.html: CORE_TABS 增加一条")
    new_i = add_tab_order(new_i, args.id, after=args.after, before=args.before)
    plan.append("index.html: TAB_ORDER 插入 " + args.id)
    new_s = None
    if args.mount:
        plan.append(f"preview_server.py: /{args.mount}/ 已由 {args.skill}/skill.json 声明（无需改文件）")
    if args.redirect:
        new_s = add_redirect(read_text(SERVER), args.redirect, args.src)
        plan.append(f"preview_server.py: REDIRECTS {args.redirect} → {args.src}")

    print("== 将要做的接线 ==")
    for p in plan:
        print("   - " + p)
    if args.dry_run:
        print("\n[dry-run] 未写入任何文件。")
        return 0

    files = backup([INDEX] + ([SERVER] if new_s is not None else []))
    write_text(INDEX, new_i)
    if new_s is not None:
        write_text(SERVER, new_s)
    journal_append({"ts": datetime.now().isoformat(timespec="seconds"), "op": "add-page",
                    "id": args.id, "files": files, "plan": plan,
                    "mount": ({"prefix": args.mount, "skill": args.skill} if args.mount else None)})
    print(f"\n[完成] 已接线。备份 → {BACKUP_DIR}")
    print("   下一步：python tools/smoke_test.py   # 起服务点一遍；python tools/portal_wire.py undo 可回退")
    return 0


def cmd_remove_page(args):
    itext = read_text(INDEX)
    plan = []
    new_i = remove_core_tab(itext, args.id)
    plan.append(f"index.html: 移除 CORE_TABS 的 {args.id}")
    new_i = remove_tab_order(new_i, args.id)
    plan.append(f"index.html: 从 TAB_ORDER 移除 {args.id}")
    if args.unmount:
        plan.append(f"preview_server.py: /{args.unmount}/ 挂载由 skill.json 声明，无需改服务器")
    print("== 将要撤销的接线 ==")
    for p in plan:
        print("   - " + p)
    if args.dry_run:
        print("\n[dry-run] 未写入任何文件。")
        return 0
    files = backup([INDEX])
    write_text(INDEX, new_i)
    journal_append({"ts": datetime.now().isoformat(timespec="seconds"), "op": "remove-page",
                    "id": args.id, "files": files, "plan": plan})
    print(f"\n[完成] 已撤销。备份 → {BACKUP_DIR}")
    return 0


def cmd_undo(_):
    if not JOURNAL.is_file():
        print("[跳过] 没有接线日志，无可撤销。")
        return 0
    data = json.loads(JOURNAL.read_text(encoding="utf-8"))
    if not data:
        print("[跳过] 日志为空。")
        return 0
    entry = data.pop()
    for target, back in entry.get("files", {}).items():
        if Path(back).is_file():
            shutil.copy2(back, target)
            print(f"   [还原] {target}")
    JOURNAL.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[完成] 已撤销：{entry.get('op')} {entry.get('id', '')}")
    return 0


def main():
    ap = argparse.ArgumentParser(description="成长家园门户接线员")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="看门户现状").set_defaults(func=cmd_list)

    p = sub.add_parser("add-page", help="挂一页到门户")
    p.add_argument("--id", required=True, help="标签 id（小写连字符，如 piano）")
    p.add_argument("--name", required=True, help="菜单显示名")
    p.add_argument("--src", required=True, help="页面地址，如 /web/piano.html 或 /piano/web/index.html")
    p.add_argument("--emoji", default="🧩")
    p.add_argument("--color", default="#4DABF7")
    p.add_argument("--after", help="排在某个已有标签之后")
    p.add_argument("--before", help="排在某个已有标签之前")
    p.add_argument("--mount", help="兄弟技能挂载前缀（如 piano）；页面在别的技能里时用")
    p.add_argument("--skill", help="配合 --mount：技能目录名（如 piano-practice）")
    p.add_argument("--redirect", help="旧地址兼容，如 /piano.html")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_add_page)

    p = sub.add_parser("remove-page", help="撤掉一页的接线")
    p.add_argument("--id", required=True)
    p.add_argument("--unmount", help="顺带移除该前缀的静态挂载")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_remove_page)

    sub.add_parser("undo", help="撤销上一次操作").set_defaults(func=cmd_undo)

    args = ap.parse_args()
    if args.cmd == "add-page" and args.mount and not args.skill:
        ap.error("--mount 需要同时给 --skill <技能目录名>")
    if not INDEX.is_file() or not SERVER.is_file():
        print(f"[失败] 找不到门户文件：{INDEX} / {SERVER}")
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

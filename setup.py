# -*- coding: utf-8 -*-
"""一键安装 / 首次使用引导 / 启动网页服务。

用法：
  python setup.py                       # 交互式配置（可反复运行，不覆盖已有数据）
  python setup.py --check               # 只体检：哪些技能缺配置、data/ 是否就绪，不改任何文件
  python setup.py --start               # 配置完直接启动网页服务（等价于 --start-only）
  python setup.py --start-only          # 不配置，直接启动网页服务

做什么：
  0. 生成 local.json，指定仓库之外的**数据区（data-root）**（示例见 local_example.json）
  1. 在 data-root 里初始化各技能的 data/（从匿名模板 data-templates/ 复制，已存在不覆盖）
  2. 首次使用引导：填写孩子信息、各科教材版本 —— 只写进 data-root 下的 config.json
  3. 安装 git pre-commit 隐私守卫钩子（提交时自动检查个人信息）
  4. 提示教材下载/更换版本的方法
  5. 启动成长家园门户（--start / --start-only）

隔离约定：孩子的隐私数据**一律落在仓库之外的 data-root**，仓库里不得存在 data/ 目录。
路径解析统一走 tools/data_paths.py（仓库内唯一的数据路径真源）。
详见 .trae/rules/project_rules.md 第 8 节。
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SKILLS_DIR = os.path.join(ROOT, ".trae", "skills")
PORTAL = os.path.join(SKILLS_DIR, "growth-home", "web", "preview_server.py")
LOCAL_JSON = os.path.join(ROOT, "local.json")

sys.path.insert(0, os.path.join(ROOT, "tools"))
import data_paths  # noqa: E402


def discover_skills():
    """自动发现所有带 data-templates/ 的技能（唯一真源是 skill.json + 目录结构）。

    不要再往这里硬编码技能名——新增技能时忘记同步清单，会导致它的 data/
    永远不被初始化，而 --check 又按全量技能体检，报出"跑 setup.py 就能修"的
    假建议（死循环）。
    """
    if not os.path.isdir(SKILLS_DIR):
        return []
    return sorted(
        name for name in os.listdir(SKILLS_DIR)
        if os.path.isdir(os.path.join(SKILLS_DIR, name, "data-templates"))
    )


def discover_basic_skills(skills):
    """需要写孩子基本信息的技能 = 模板 config.json 里带 childName 的那些。"""
    out = []
    for name in skills:
        tpl = os.path.join(SKILLS_DIR, name, "data-templates", "config.json")
        if os.path.isfile(tpl) and "childName" in (read_json(tpl) or {}):
            out.append(name)
    return out

# 内置默认教材版本（人教版体系示例），引导时可逐科修改
DEFAULT_TEXTBOOKS = {
    "语文": "人教版（部编版）",
    "数学": "人教版",
    "英语": "外研版（一年级起点）",
    "道德与法治": "人教版（部编版）",
    "科学": "教科版",
    "美术": "人美版",
    "音乐": "人音版",
    "体育": "人教版",
}


def ask(prompt, default=""):
    tip = prompt + (f"（回车用默认：{default}）" if default else "") + "："
    try:
        v = input(tip).strip()
    except EOFError:
        v = ""
    return v or default


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")


def read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _is_within(child, parent):
    try:
        return os.path.commonpath([os.path.abspath(child), os.path.abspath(parent)]) \
            == os.path.abspath(parent)
    except ValueError:
        return False


def ensure_local_json():
    """确保仓库根有 local.json，返回 data-root（绝对路径）。没有就引导用户填。"""
    if os.path.exists(LOCAL_JSON):
        cfg = read_json(LOCAL_JSON) or {}
        raw = (cfg.get("data_root") or "").strip()
        if raw and not raw.startswith("<"):
            root = os.path.abspath(os.path.expanduser(raw))
            if _is_within(root, ROOT):
                print("  [!] local.json 里的 data_root 落在仓库内：%s" % root)
                print("      数据必须放在仓库之外，请改掉后重跑。")
                return None
            os.environ[data_paths.ENV_VAR] = root
            return root

    print("\n== 0/5 数据区（data-root）==")
    print("  孩子的隐私数据存放在**仓库之外**的独立目录，仓库才能直接开源。")
    print("  这个目录会与门户的页面结构同构：web/ learn/ bag/ art/ lib/ comp/ textbooks/ personal/")
    base = os.path.basename(ROOT.rstrip("\\/")) or "shan-learn"
    default_root = os.path.join(os.path.dirname(ROOT.rstrip("\\/")), base + "-data")
    while True:
        raw = ask("  数据区绝对路径", default_root)
        root = os.path.abspath(os.path.expanduser(raw))
        if _is_within(root, ROOT):
            print("  [!] 这个路径在仓库内，请换一个仓库之外的目录。")
            continue
        break
    write_json(LOCAL_JSON, {"data_root": root, "port": 8090})
    print("  [已写入] local.json（已加入 .gitignore，不会入库）")
    os.environ[data_paths.ENV_VAR] = root
    return root


def data_dir(skill):
    """技能的数据目录（仓库之外，data-root 下）。"""
    return str(data_paths.skill_dir(skill) / "data")


def copy_tree_missing(src, dst, label, skip_subdirs=()):
    """把 src 中 dst 缺失的文件补过去，已存在的一律不覆盖。

    skip_subdirs：对已有真实数据的目录，跳过这些子目录（避免把模板示例
    混入真实数据，如学习看板的 days/ 示例日）。
    """
    created = []
    for dirpath, dirnames, filenames in os.walk(src):
        rel = os.path.relpath(dirpath, src)
        if skip_subdirs and rel != "." and rel.split(os.sep)[0] in skip_subdirs:
            continue
        dst_dir = os.path.join(dst, rel) if rel != "." else dst
        os.makedirs(dst_dir, exist_ok=True)
        for fn in filenames:
            target = os.path.join(dst_dir, fn)
            if not os.path.exists(target):
                shutil.copy2(os.path.join(dirpath, fn), target)
                created.append(os.path.relpath(target, dst))
    for c in created:
        print(f"  [新增] {label}/{c}")
    return created


def _count_files(path):
    return sum(len(fn) for _, _, fn in os.walk(path))


def init_skill_data():
    print("\n== 1/5 初始化技能数据目录（data/ 由 data-templates/ 生成，落在 data-root）==")
    for name in discover_skills():
        skill = os.path.join(SKILLS_DIR, name)
        tpl = os.path.join(skill, "data-templates")
        if not os.path.isdir(tpl):
            continue
        data = data_dir(name)
        if not os.path.isdir(data):
            shutil.copytree(tpl, data)
            print(f"  [初始化] {data}（来自匿名模板，共 {_count_files(data)} 个文件）")
        else:
            copy_tree_missing(tpl, data, name + "/data", skip_subdirs=("days", "weekly"))
        # 技能声明的其它数据目录（images/audio/output）也一并建好
        for extra in data_paths.data_dirs(name):
            if extra == "data":
                continue
            os.makedirs(str(data_paths.skill_dir(name) / extra), exist_ok=True)
    print(f"  数据区：{data_paths.data_root()}")


# 模板里的占位名：出现这些就说明还没填过自己的信息。
# 注意：模板 config.json 里的示例学校名（"光明小学"）同样是占位值——
# 只过滤 childName 会把已经填好的真实学校名覆盖回示例，务必带上学校。
PLACEHOLDERS = {"", "小明", "孩子", "小朋友", "光明小学", "实验小学", "第一小学"}

BASIC_FIELDS = ("childName", "school", "grade", "className", "semester")


def collect_known_basic():
    """扫描所有技能已配置好的孩子信息，用于给引导当默认值 / 回填。

    早期版本只在 school-bag-organizer 一处判断是否引导过，于是别的技能
    拿到模板占位名后被永久跳过。这里从所有技能汇总，取第一个非占位值。
    """
    known = {}
    for name in discover_basic_skills(discover_skills()):
        cfg = read_json(os.path.join(data_dir(name), "config.json")) or {}
        for field in BASIC_FIELDS:
            val = (cfg.get(field) or "").strip()
            if val and val not in PLACEHOLDERS and field not in known:
                known[field] = val
    return known


def need_guide():
    """只要还有技能停在占位名上，就还需要引导（可反复运行，只补缺口）。"""
    for name in discover_basic_skills(discover_skills()):
        cfg = read_json(os.path.join(data_dir(name), "config.json"))
        if cfg is None or (cfg.get("childName") or "").strip() in PLACEHOLDERS:
            return True
    return False


def guide():
    print("\n== 2/5 首次使用引导（信息只写 data-root，不入库）==")
    known = collect_known_basic()
    if known:
        print("  [沿用已配置信息] " + "、".join(
            "%s=%s" % (k, known[k]) for k in BASIC_FIELDS if k in known))
        print("  [回车保持原值，直接回车走完即可]")
    child = ask("  孩子姓名或昵称", known.get("childName", ""))
    school = ask("  学校名称（可留空）", known.get("school", ""))
    grade = ask("  年级", known.get("grade") or "一年级")
    cls = ask("  班级（如：2班，可留空）", known.get("className", ""))
    semester = ask("  当前学期", known.get("semester") or "2026-2027学年度第一学期")

    print("\n-- 各科教材版本（不同省份版本不同，回车用默认；之后可改数据区里的 "
          "bag/data/config.json）--")
    bag_cfg = read_json(os.path.join(data_dir("school-bag-organizer"), "config.json")) or {}
    old_tb = bag_cfg.get("textbooks") or {}
    textbooks = {}
    for subj, dv in DEFAULT_TEXTBOOKS.items():
        textbooks[subj] = ask("  %s版本" % subj, old_tb.get(subj) or dv)
    # 保留数据区里已有但不在默认清单里的科目（如已配的校本教材）
    for subj, val in old_tb.items():
        textbooks.setdefault(subj, val)

    basic = {"childName": child, "school": school, "grade": grade,
             "className": cls, "semester": semester}
    for name in discover_basic_skills(discover_skills()):
        path = os.path.join(data_dir(name), "config.json")
        cfg = read_json(path) or {}
        cfg.update(basic)
        if name == "school-bag-organizer":
            cfg["textbooks"] = textbooks
            cfg.setdefault("morningCutoff", "09:00")
        write_json(path, cfg)
        print("  [已写入] %s/data/config.json" % data_paths.skill_namespace(name))

    for skill, key, title in (("home-library", "childName", "的家庭图书馆"),
                ("xiaoshan-art-archive", "childName", "的画廊"),
                              ("competition", "childName", "的比赛")):
        path = os.path.join(data_dir(skill), "config.json")
        if not os.path.isfile(path):
            continue
        cfg = read_json(path) or {}
        cfg[key] = child
        if child:
            cfg.setdefault("libraryTitle" if skill == "home-library" else "archiveTitle",
                           child + title)
        write_json(path, cfg)
        print("  [已写入] %s/data/config.json" % data_paths.skill_namespace(skill))
    print("  提醒：请把家里的敏感词（真名、学校、老师名等）逐行写进 "
          "<data-root>/personal/privacy-guard-words.txt，提交与打包时隐私守卫会自动检查。")


def install_hook():
    print("\n== 3/5 安装 git 隐私守卫钩子 ==")
    git_dir = os.path.join(ROOT, ".git")
    if not os.path.isdir(git_dir):
        print("  [跳过] 未找到 .git，先 git init 再重跑 python setup.py")
        return
    src = os.path.join(ROOT, "tools", "git-hooks", "pre-commit")
    hooks_dir = os.path.join(git_dir, "hooks")
    dst = os.path.join(hooks_dir, "pre-commit")
    os.makedirs(hooks_dir, exist_ok=True)
    if os.path.exists(dst):
        print("  [已存在] .git/hooks/pre-commit 未覆盖")
        return
    shutil.copyfile(src, dst)
    try:
        os.chmod(dst, 0o755)
    except OSError:
        pass
    print("  [已安装] pre-commit（每次提交自动检查个人信息）")


def textbooks_hint():
    print("\n== 4/5 教材 ==")
    tb = str(data_paths.textbooks_dir())
    pdf_dir = os.path.join(tb, "pdf")
    have = sorted(f[:-4] for f in os.listdir(pdf_dir) if f.endswith(".pdf")) \
        if os.path.isdir(pdf_dir) else []
    print(f"  教材库：{tb}")
    print(f"  本地已有教材：{'、'.join(have) if have else '（无）'}")
    print("  教材页图按你的版本自行获取（版权原因不随仓库分发）：")
    print("    python tools/find_books.py        # 1. 列出该年级全部可用教材")
    print("    python tools/filter_books.py      # 2. 按你配置的教材版本筛选")
    print("    python tools/download_books.py    # 3. 下载 PDF（需 pip install requests）")
    print("    python tools/split_pages.py       # 4. 切页图（需 pip install pymupdf）")
    print("    python tools/build_meta.py        # 5. 抓取章节目录")
    print("    python tools/build_index.py       # 6. 重建总索引")
    print("  详见 tools/README.md。")


def check_up():
    """体检：不写任何文件，报告每个技能在 data-root 里的数据与 config 状态。"""
    print("== 体检：技能数据就绪情况 ==")
    try:
        root = data_paths.data_root()
    except data_paths.DataRootNotConfigured as exc:
        print(f"  [未配置] {exc}")
        return 1
    print(f"  数据区：{root}")
    problems = 0
    for name in discover_skills():
        skill = os.path.join(SKILLS_DIR, name)
        tpl = os.path.join(skill, "data-templates")
        try:
            data = data_dir(name)
        except data_paths.DataRootNotConfigured as exc:
            print(f"  [错误] {name}：{exc}")
            problems += 1
            continue
        has_data = os.path.isdir(data)
        missing = []
        if has_data:
            t = {os.path.relpath(os.path.join(dp, f), tpl) for dp, _, fn in os.walk(tpl) for f in fn}
            d = {os.path.relpath(os.path.join(dp, f), data) for dp, _, fn in os.walk(data) for f in fn}
            # 这两类缺了是**设计如此**，不算问题：
            #   feedback_channels.json —— data/ 没有就回退读 data-templates/ 的默认版
            #   days/*.json          —— 模板里的示例日，不该混进真实数据
            missing = sorted(m for m in (t - d)
                             if os.path.basename(m) != "feedback_channels.json"
                             and not m.replace("\\", "/").startswith("days/"))
        cfg = read_json(os.path.join(data, "config.json")) if has_data else None
        flag = "OK"
        if not has_data:
            flag, problems = "缺 data/（跑 python setup.py）", problems + 1
        elif missing:
            flag, problems = f"缺 {len(missing)} 个文件：{missing[:3]}…（跑 python setup.py 补齐）", problems + 1
        cfg_note = ""
        if cfg is not None and (cfg.get("childName") or "").strip() in PLACEHOLDERS:
            cfg_note, problems = "，config 里还是模板占位名（跑 python setup.py 引导）", problems + 1
        print(f"  [{flag}] {name}{cfg_note}")
    # 顺手提示仓库里是否还残留 data/（违反隔离约定）
    leftover = data_paths.repo_data_dirs()
    if leftover:
        print("\n  [!] 仓库内仍存在不该有的数据目录（应迁到 data-root）：")
        for p in leftover:
            print(f"      {os.path.relpath(str(p), ROOT)}")
        problems += 1
    print(f"\n体检结论：{'全部就绪' if problems == 0 else f'有 {problems} 项待处理'}")
    return 0 if problems == 0 else 1


def start_portal():
    print("\n== 启动成长家园门户 ==")
    if not os.path.exists(PORTAL):
        print(f"  [失败] 找不到 {PORTAL}")
        return 1
    print("  电脑：http://localhost:8090/")
    print("  手机/平板：与本机连同一 WiFi，打开启动日志里打印的 http://<电脑IP>:8090/")
    print("  按 Ctrl+C 停止。\n")
    return subprocess.call([sys.executable, PORTAL])


def main():
    ap = argparse.ArgumentParser(description="家庭学习空间 · 安装与启动")
    ap.add_argument("--check", action="store_true", help="只体检，不改文件")
    ap.add_argument("--start", action="store_true", help="配置完成后启动网页服务")
    ap.add_argument("--start-only", action="store_true", help="不配置，直接启动网页服务")
    args = ap.parse_args()

    print("== 家庭学习空间 · 安装向导 ==")
    if args.check:
        return check_up()
    if args.start_only:
        root = ensure_local_json()
        if not root:
            return 1
        return start_portal()

    if not ensure_local_json():
        return 1
    init_skill_data()
    if need_guide():
        guide()
    else:
        print("\n== 2/5 首次使用引导 ==")
        print("  [跳过] 孩子信息已配置过（如需重填，编辑数据区里的 config.json，或先删掉它再跑）")
    install_hook()
    textbooks_hint()

    print("\n全部完成！")
    print(f"  数据区：{data_paths.data_root()}")
    print("  启动门户：python setup.py --start-only   （或 python .trae/skills/growth-home/web/preview_server.py）")
    print("  手机同 WiFi 访问启动日志里打印的 http://<电脑IP>:8090/")
    print("\n每个页面右下角有「💌 提建议」按钮，用得不顺手可以直接反馈给作者（零配置）。")
    print("想加自己的功能：python tools/new_skill.py my-thing（一个新需求 = 一个新技能）")
    print("发布前自检：python tools/privacy_guard.py --all && python tools/build_dist.py")

    if args.start:
        return start_portal()
    return 0


if __name__ == "__main__":
    sys.exit(main())

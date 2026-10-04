# -*- coding: utf-8 -*-
"""隐私守卫：检查「将要公开的东西」里有没有个人信息。

用法：
  python tools/privacy_guard.py --staged          # 检查 git 暂存区（pre-commit 钩子自动调用）
  python tools/privacy_guard.py --all             # 全量检查所有会公开的文件（手动 / CI 用）
  python tools/privacy_guard.py --dist dist/xx.zip  # 检查已打好的发布包（zip 或目录，含包内每个文件）
  python tools/privacy_guard.py --all --words <data-root>/personal/privacy-guard-words.txt

检查四类问题：
  1. 禁止路径：个人数据目录（各技能 data/、personal/、画作/封面/录音等）不允许进入公开产物；
     构建产物与本机记忆目录（dist/、.trae-html-share-packages/、.workbuddy/）同理。
  2. 敏感词：来自 <data-root>/personal/privacy-guard-words.txt（每行一词，# 为注释，该文件不入库；
     迁移前的仓库内 personal/ 路径仍作兜底）。
  3. 格式类 PII：手机号、身份证号（内置正则）。
  4. 本机绝对路径：C:\\Users\\<名字>、/Users/<名字>、/home/<名字> —— 会把作者的真实用户名带出去。

--dist 模式还会**逐层解开 zip**，扫描包内每个文本成员（这是历史上唯一漏过的洞：
  .zip 曾被当作二进制整体跳过，导致内嵌孩子真名的分享包被放行）。
"""
import argparse
import io
import json
import os
import re
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

# —— 1) 禁止路径：个人数据 / 不该公开的本机内容 ——
FORBIDDEN_PATH_PATTERNS = [
    re.compile(r"^personal/"),
    re.compile(r"^\.trae/skills/[^/]+/data/"),          # 各技能真实运行数据（含 config、录音、打卡）
    re.compile(r"^\.trae/skills/[^/]+/(images|audio|output)/"),
    re.compile(r"^画作档案/"),
    re.compile(r"^school_checklist_standalone\.html$"),  # 由技能生成的、内嵌个人数据的单文件版
    re.compile(r"^textbooks/pdf/科学\.pdf$"),            # 体积超限的教材（用下载脚本自行获取）
    re.compile(r"^textbooks/pages/科学/"),
]

# —— 构建产物 / 本机痕迹：不该进版本库或发布包（出现即视为风险）——
ARTIFACT_PATH_PATTERNS = [
    re.compile(r"^dist/"),
    re.compile(r"^\.trae-html-share-packages/"),
    re.compile(r"^\.workbuddy/"),
    re.compile(r"^\.trae-html-share-packages$"),
]

# 全量扫描时跳过的目录（个人数据 + 第三方/生成物 + 二进制资源目录）
SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", "vendor", "tchsrc",
    "personal", "data", "images", "audio", "output", "画作档案",
}

# 二进制/媒体文件不做文本扫描（注意：.zip **不在**此列——zip 要解开扫）
SKIP_EXT = {
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".ico", ".icns",
    ".m4a", ".mp3", ".wav", ".mp4", ".mov", ".woff", ".woff2", ".ttf",
    ".exe", ".spec", ".docx", ".xlsx", ".pptx", ".zip.bak",
}

# zip 内只扫这些文本后缀
ZIP_TEXT_EXT = {
    ".md", ".json", ".js", ".mjs", ".cjs", ".ts", ".html", ".htm", ".css",
    ".py", ".txt", ".yaml", ".yml", ".csv", ".xml", ".sh", ".bash",
    ".bat", ".ps1", ".toml", ".cfg", ".ini", ".env", ".gitignore",
}

PII_REGEXES = [
    ("手机号", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
    ("身份证号", re.compile(
        r"(?<!\d)\d{6}(?:18|19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?!\d)")),
    # 本机绝对路径：Windows 的反斜杠可能被 JSON 转义成双写，这里两种都收
    ("本机绝对路径", re.compile(r"""[A-Za-z]:\\{1,2}Users\\{1,2}[^\\/\s"',;<>|]+""")),
    ("本机绝对路径", re.compile(r"""/(?:Users|home)/[^/\s"',;<>|]+""")),
]


def default_words_path():
    """敏感词表的默认位置（按优先级取第一个存在的）：

    1. 数据区 `<data-root>/personal/privacy-guard-words.txt` —— 现在的正式位置（不入库）；
    2. 仓库内 `<repo>/personal/privacy-guard-words.txt` —— 迁移前的旧位置，保留兜底。
    """
    candidates = []
    try:
        import data_paths
        candidates.append(str(data_paths.resolve("personal") / "privacy-guard-words.txt"))
    except Exception:
        pass
    candidates.append(os.path.join(ROOT, "personal", "privacy-guard-words.txt"))
    for c in candidates:
        if os.path.exists(c):
            return c
    return candidates[0]


def load_words(path=None):
    """读取敏感词表。真实词表在数据区 personal/ 内、不入库；缺失时只做格式与本机路径检查。"""
    if path is None:
        path = default_words_path()
    words = []
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#"):
                words.append(line)
    return words, path


def is_forbidden(rel, include_artifacts=True):
    rel = rel.replace("\\", "/")
    patterns = list(FORBIDDEN_PATH_PATTERNS)
    if include_artifacts:
        patterns += ARTIFACT_PATH_PATTERNS
    return any(p.search(rel) for p in patterns)


def scan_text(text, words):
    """对一段文本做敏感词 + PII + 本机路径检查，返回问题列表。"""
    problems = []
    for w in words:
        if w in text:
            problems.append(f"敏感词「{w}」")
    for name, rx in PII_REGEXES:
        m = rx.search(text)
        if m:
            problems.append(f"疑似{name}：{m.group(0)[:40]}")
    return problems


def read_text(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except (UnicodeDecodeError, OSError):
        return None


def check_file(rel, words):
    """检查单个磁盘文件（rel 为相对仓库根或相对发布包根的路径）。"""
    if is_forbidden(rel):
        return ["禁止路径：个人数据 / 本机痕迹不得进入公开产物"]
    if os.path.splitext(rel)[1].lower() in SKIP_EXT:
        return []
    text = read_text(os.path.join(ROOT, rel))
    if text is None:
        return []
    return scan_text(text, words)


def check_zip(zip_path, words, display_prefix, depth=0):
    """逐层解开 zip 扫描成员文本（depth=0 扫一层，depth=1 再解内嵌 zip 一层）。"""
    problems = []
    try:
        with zipfile.ZipFile(zip_path) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                name = info.filename
                shown = f"{display_prefix}!{name}"
                ext = os.path.splitext(name)[1].lower()
                if ext == ".zip" and depth < 1:
                    try:
                        inner = io.BytesIO(zf.read(info))
                        tmp = os.path.join(HERE, "_nested_scan.zip")
                        with open(tmp, "wb") as f:
                            f.write(inner.getvalue())
                        problems += check_zip(tmp, words, shown, depth + 1)
                        os.remove(tmp)
                    except Exception as e:  # noqa: BLE001
                        problems.append(f"{shown}: 内嵌 zip 读取失败（{e}）")
                    continue
                if ext not in ZIP_TEXT_EXT:
                    continue
                try:
                    text = zf.read(info).decode("utf-8")
                except (UnicodeDecodeError, KeyError):
                    continue
                for p in scan_text(text, words):
                    problems.append(f"{shown}: {p}")
    except zipfile.BadZipFile:
        problems.append(f"{display_prefix}: 不是有效 zip")
    return problems


def check_dist(target, words):
    """检查发布产物：zip 文件或目录。返回 (参与检查的条目数, 问题列表)。"""
    problems = []
    count = 0
    if os.path.isfile(target):
        if target.lower().endswith(".zip"):
            problems += check_zip(target, words, os.path.basename(target))
            return 1, problems
        problems.append(f"{target}: 不支持的文件类型（只支持 zip / 目录）")
        return 0, problems

    for dp, dn, fn in os.walk(target):
        for f in fn:
            full = os.path.join(dp, f)
            rel = os.path.relpath(full, target).replace("\\", "/")
            count += 1
            if is_forbidden(rel, include_artifacts=False):
                problems.append(f"{rel}: 禁止路径：发布包内不得含真实个人数据目录")
                continue
            if f.lower().endswith(".zip"):
                problems += check_zip(full, words, rel)
                continue
            if os.path.splitext(f)[1].lower() in SKIP_EXT:
                continue
            text = read_text(full)
            if text is None:
                continue
            for p in scan_text(text, words):
                problems.append(f"{rel}: {p}")
    return count, problems


def staged_files():
    out = subprocess.run(
        ["git", "-c", "core.quotepath=false", "diff", "--cached",
         "--name-only", "--diff-filter=ACMR"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    if out.returncode != 0:
        print("[隐私守卫] git 调用失败：", out.stderr.strip())
        sys.exit(2)
    return [l.strip() for l in out.stdout.splitlines() if l.strip()]


def all_files():
    """列出会进入公开仓库的文件：已跟踪 + 未跟踪但未被 .gitignore 忽略。"""
    try:
        out = subprocess.run(
            ["git", "-c", "core.quotepath=false", "ls-files",
             "--cached", "--others", "--exclude-standard"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
        if out.returncode == 0 and out.stdout.strip():
            return [l.strip() for l in out.stdout.splitlines() if l.strip()]
    except OSError:
        pass
    files = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            files.append(os.path.relpath(os.path.join(dirpath, fn), ROOT))
    return files


def check_architecture():
    """架构断言（project_rules.md 第 8 节，全量检查时执行）：
       1) 仓库内不得存在任何数据目录 —— data-root 必须生效，数据不能长回仓库；
       2) 命名空间声明自洽 —— 有 skill.json 的技能，url 必须存在、唯一、非保留前缀，
          且与 data_paths.skill_namespace() 一致（服务器据此自动挂载）。
    返回问题列表；空列表表示通过。"""
    problems = []
    try:
        import data_paths
    except Exception as exc:  # noqa: BLE001
        return ["无法导入 tools/data_paths.py：%s" % exc]

    # 断言 1：仓库内不得有任何数据目录
    try:
        leftovers = data_paths.repo_data_dirs()
    except Exception as exc:  # noqa: BLE001
        leftovers = []
        problems.append("data_paths.repo_data_dirs() 调用失败：%s" % exc)
    for p in leftovers:
        try:
            rel = os.path.relpath(p, ROOT).replace("\\", "/")
        except ValueError:
            rel = str(p)
        problems.append("仓库内不应存在数据目录：%s/（应迁到 data-root）" % rel)

    # 断言 2：skill.json 的命名空间声明自洽
    #   - 根级共享命名空间（textbooks/personal/...）对谁都保留；
    #   - 既有命名空间（web/learn/bag/...）只属于它在 DEFAULT_NAMESPACES 里对应的那个技能
    #     （门户 growth-home 的 url 就是 "web"，不算违规；别的技能抢占才报错）。
    reserved = set(getattr(data_paths, "SHARED_NAMESPACES", ()))
    ns_owner = dict(getattr(data_paths, "DEFAULT_NAMESPACES", {}))
    skills_root = os.path.join(ROOT, ".trae", "skills")
    seen = {}
    if os.path.isdir(skills_root):
        for name in sorted(os.listdir(skills_root)):
            skill_dir = os.path.join(skills_root, name)
            meta_path = os.path.join(skill_dir, "skill.json")
            if not os.path.isdir(skill_dir) or not os.path.isfile(meta_path):
                continue
            try:
                meta = json.loads(open(meta_path, encoding="utf-8").read())
            except Exception as exc:  # noqa: BLE001
                problems.append("技能 %s 的 skill.json 解析失败：%s" % (name, exc))
                continue
            url = str(meta.get("url") or "").strip().strip("/")
            if not url:
                problems.append("技能 %s 的 skill.json 缺少 url" % name)
                continue
            if url in reserved:
                problems.append("技能 %s 的 url=%r 是保留前缀（共享命名空间），请换一个" % (name, url))
            elif url in ns_owner and ns_owner[url] != name:
                problems.append("技能 %s 的 url=%r 已被技能 %s 占用（见 data_paths.DEFAULT_NAMESPACES），请换一个"
                                % (name, url, ns_owner[url]))
            elif url in seen:
                problems.append("技能 %s 的 url=%r 与技能 %s 重复" % (name, url, seen[url]))
            else:
                seen[url] = name
            try:
                actual = data_paths.skill_namespace(name)
            except Exception:  # noqa: BLE001
                actual = None
            if actual is not None and actual != url:
                problems.append("技能 %s 的 url=%r 与 data_paths.skill_namespace()=%r 不一致"
                                % (name, url, actual))
    return problems


def main():
    ap = argparse.ArgumentParser(description="隐私守卫检查")
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--staged", action="store_true", help="检查 git 暂存区")
    group.add_argument("--all", action="store_true", help="全量检查公开文件")
    group.add_argument("--dist", metavar="PATH", help="检查发布产物（zip 或目录）")
    ap.add_argument("--words", help="自定义敏感词表路径（默认 <data-root>/personal/privacy-guard-words.txt）")
    ap.add_argument("--quiet", action="store_true", help="只输出结论")
    args = ap.parse_args()

    words, words_path = load_words(args.words)
    if not words and not args.quiet:
        print(f"[隐私守卫] 提示：{words_path} 不存在或为空，"
              "本次只做禁止路径、手机号/身份证与本机路径检查。")

    violations = []
    if args.dist:
        count, hits = check_dist(args.dist, words)
        violations = [(h.split(":")[0], h) for h in hits]
        scanned_desc = f"发布产物 {args.dist}（{count} 个文件）"
        if args.dist.lower().endswith(".zip"):
            scanned_desc = f"发布产物 {os.path.basename(args.dist)}（含包内全部文本成员）"
    else:
        files = staged_files() if args.staged else all_files()
        scanned_desc = f"{len(files)} 个文件"
        for rel in files:
            for p in check_file(rel, words):
                violations.append((rel, p))
        if args.all:
            for p in check_architecture():
                violations.append(("架构", p))
            if not args.quiet:
                print("[隐私守卫] 架构断言已执行：仓库内无数据目录 + skill.json 命名空间自洽")

    if violations:
        print(f"[隐私守卫] 拦截：{len(violations)} 处风险（{scanned_desc}）")
        for rel, p in violations:
            print(f"  - {rel}: {p}")
        print("处理建议：")
        print("  1) 个人数据文件请移出暂存区：git restore --staged <文件>")
        print("  2) 公开文件里请删掉真实姓名/学校/手机号/本机路径后重新提交")
        print("  3) 重新打包：python tools/build_dist.py（打包器会自动做这一步检查）")
        sys.exit(1)
    print(f"[隐私守卫] 通过（{scanned_desc}；敏感词 {len(words)} 个）")


if __name__ == "__main__":
    main()

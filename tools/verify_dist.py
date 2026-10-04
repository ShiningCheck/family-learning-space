# -*- coding: utf-8 -*-
"""发布包验收：结构对不对、data/ 是不是匿名模板、frontmatter 合不合规、解包后能不能跑。

与 privacy_guard.py 的分工：
  - privacy_guard.py --dist：查「有没有隐私漏出去」（安全闸门，命中即失败）
  - 本脚本：查「这个包能不能用」（质量验收，出包后跑一次）

用法：
  python tools/verify_dist.py dist/家庭学习空间.zip
  python tools/verify_dist.py dist/school-bag-organizer.zip
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load(zip_path):
    zf = zipfile.ZipFile(zip_path)
    names = [n for n in zf.namelist() if not n.endswith("/")]
    blobs = {n: zf.read(n) for n in names}
    return zf, names, blobs


def main():
    ap = argparse.ArgumentParser(description="发布包验收")
    ap.add_argument("zip_path", help="dist/ 下的发布包 zip")
    args = ap.parse_args()
    zp = Path(args.zip_path)
    if not zp.is_file():
        print(f"[失败] 找不到 {zp}")
        return 2
    zp = zp.resolve()

    zf, names, blobs = load(zp)
    top = sorted({n.split("/")[0] for n in names})
    print(f"== 验收 {zp.name}：{len(names)} 个文件，顶层 {top}")

    fails = []

    # 1) 包内 data/ 必须是匿名模板（不能是真实记录）
    print("\n-- 包内 data/ 抽查")
    for n in sorted(x for x in names if "/data/" in x and x.endswith(".json")):
        try:
            obj = json.loads(blobs[n].decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            fails.append(f"{n} 不是合法 JSON：{e}")
            continue
        s = json.dumps(obj, ensure_ascii=False)
        print(f"   {n.split('/data/')[-1]:<28} {s[:80]}{'…' if len(s) > 80 else ''}")

    # 2) 不该出现的目录/文件（真实录音、照片、分享单文件、内嵌 zip）
    print("\n-- 不该出现的东西")
    bad = [n for n in names if re.search(
        r"/data/(voice/audio|feedback/inbox|homework_media|homework_pdf|class_media|school_media|tts/audio)/", n)]
    bad += [n for n in names if "画作档案" in n]
    bad += [n for n in names if n.endswith((".zip", "_standalone.html"))]
    if bad:
        fails.append(f"包含不该发布的 {len(bad)} 个文件")
        print("   " + "\n   ".join(bad[:20]))
    else:
        print("   无")

    # 3) SKILL.md frontmatter（--- 必须 LF；name 小写连字符；有 agent_created）
    print("\n-- SKILL.md frontmatter")
    for n in sorted(x for x in names if x.endswith("/SKILL.md")):
        raw = blobs[n]
        skill = n.split("/")[-2]
        if b"\r\n" in raw:
            fails.append(f"{skill}/SKILL.md 用了 CRLF（平台校验按 LF 匹配）")
        text = raw.decode("utf-8").replace("\r\n", "\n")
        m = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
        ok = bool(m) and bool(re.search(r"^name:[^\S\n]*[a-z0-9-]+[^\S\n]*$", m.group(1), re.M)) \
            and "agent_created: true" in m.group(1)
        print(f"   [{'OK' if ok else '不合格'}] {skill}")
        if not ok:
            fails.append(f"{skill}/SKILL.md frontmatter 不合规")

    # 4) 解包后：Python 语法 + 安装器体检
    tmp = tempfile.mkdtemp(prefix="dist_verify_")
    with zipfile.ZipFile(zp) as z:
        z.extractall(tmp)
    root = Path(tmp) / top[0] if len(top) == 1 else Path(tmp)

    py = [p for p in root.rglob("*.py")]
    errs = []
    for p in py:
        try:
            compile(p.read_text(encoding="utf-8"), str(p), "exec")
        except SyntaxError as e:
            errs.append(f"{p.relative_to(root)}: {e}")
    print(f"\n-- 解包：Python {len(py)} 个，" + ("语法全部通过" if not errs else f"{len(errs)} 个失败"))
    fails += errs

    setup = root / "setup.py"
    if setup.is_file():
        r = subprocess.run([sys.executable, "setup.py", "--check"], cwd=str(root),
                           capture_output=True, text=True, encoding="utf-8")
        tail = (r.stdout or r.stderr).strip().splitlines()[-3:]
        print("-- setup.py --check：" + " | ".join(tail))
    else:
        print("-- 没带 setup.py（单技能包正常）")

    print(f"\n解包目录：{root}")
    if fails:
        print(f"\n[验收不通过] {len(fails)} 项：")
        for f in fails:
            print("  - " + f)
        return 1
    print("\n[验收通过] 结构、模板匿名性、frontmatter、可运行性都没问题。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
"""数据区（data-root）路径解析：全仓库唯一的数据路径真源。

约定见 .trae/rules/project_rules.md 第 8 节：
  - 孩子的隐私数据一律落在**仓库外**的 data-root 下，仓库内不得存在任何 data/ 目录；
  - data-root 布局与门户 URL 命名空间同构（web/ learn/ bag/ art/ lib/ comp/ textbooks/ personal/）；
  - 无网页的技能落 <root>/skills/<技能名>/。

data-root 由仓库根 local.json 的 data_root 指定（示例见 local_example.json），
环境变量 GH_DATA_ROOT 可临时覆盖。缺配置时**报错而非回退**——一旦静默回退到仓库内，
数据就会重新长回仓库。

用法：
  python tools/data_paths.py              # 打印当前配置与各命名空间路径
  python tools/data_paths.py --self-test  # 自检：仓库内的 root 必须被拒绝

  from data_paths import data_root, namespace_dir, skill_dir, resolve, ensure_within_root
"""
import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent

LOCAL_JSON = REPO_ROOT / "local.json"
LOCAL_EXAMPLE = REPO_ROOT / "local_example.json"
ENV_VAR = "GH_DATA_ROOT"

# 命名空间 → 技能名（与门户 URL 前缀同构）。技能有 skill.json 时以其 url 字段为准。
DEFAULT_NAMESPACES = {
    "web": "growth-home",
    "learn": "learning-growth-board",
    "bag": "school-bag-organizer",
    "art": "xiaoshan-art-archive",
    "lib": "home-library",
    "comp": "competition",
}
# 根级共享命名空间（不属于任何技能）
SHARED_NAMESPACES = ("textbooks", "personal", "share", "skills")
_NS_BY_SKILL = {v: k for k, v in DEFAULT_NAMESPACES.items()}

# 技能内目录约定（skill.json 缺省时使用）
DEFAULT_CODE_DIRS = ("web", "tools", "references", "SKILL.md", "data-templates")
DEFAULT_DATA_DIRS = ("data", "images", "audio", "output")


class DataRootNotConfigured(RuntimeError):
    """data-root 未配置、配置非法，或路径逃出了 data-root。"""


def _is_within(child, parent):
    try:
        Path(child).resolve().relative_to(Path(parent).resolve())
        return True
    except ValueError:
        return False


_root_cache = None


def _read_local_json():
    if not LOCAL_JSON.exists():
        return None
    try:
        return json.loads(LOCAL_JSON.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - 配置坏了要给人看得懂的提示
        raise DataRootNotConfigured("local.json 解析失败：%s" % exc)


def data_root(refresh=False):
    """仓库外的数据区根目录（绝对路径）。未配置或落在仓库内即抛错。"""
    global _root_cache
    if _root_cache is not None and not refresh:
        return _root_cache

    raw = os.environ.get(ENV_VAR, "").strip()
    src = ENV_VAR
    if not raw:
        raw = ((_read_local_json() or {}).get("data_root") or "").strip()
        src = "local.json"
    if not raw or raw.startswith("<"):
        raise DataRootNotConfigured(
            "数据区未配置：请在仓库根运行 `python setup.py` 生成 local.json，"
            "或设置环境变量 %s 指向仓库外的数据目录。" % ENV_VAR
        )

    p = Path(raw).expanduser()
    if not p.is_absolute():
        raise DataRootNotConfigured(
            "data_root 必须是绝对路径，当前为 %r（来自 %s）" % (raw, src)
        )
    p = p.resolve()
    if _is_within(p, REPO_ROOT):
        raise DataRootNotConfigured(
            "data_root 落在仓库内（%s）——数据必须放在仓库外，否则会重新长回仓库。" % p
        )
    _root_cache = p
    return p


def ensure_within_root(path):
    """断言路径落在 data-root 内；逃出即抛错（防止拼错路径写回仓库）。"""
    p = Path(path).resolve()
    if not _is_within(p, data_root()):
        raise DataRootNotConfigured("路径逃出 data-root：%s" % p)
    return p


def resolve(*parts):
    """按 data-root 的相对路径取绝对路径。"""
    return ensure_within_root(data_root().joinpath(*parts))


def namespace_dir(ns):
    """取某个命名空间（URL 前缀）对应的数据目录。"""
    ns = str(ns or "").strip().strip("/")
    if not ns:
        raise ValueError("命名空间不能为空")
    return ensure_within_root(data_root() / ns)


def skill_meta(skill):
    """读技能的 skill.json；不存在返回 None。"""
    path = REPO_ROOT / ".trae" / "skills" / skill / "skill.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise DataRootNotConfigured("%s/skill.json 解析失败：%s" % (skill, exc))


def skill_namespace(skill):
    """技能名 → 数据命名空间；无网页技能返回 skills/<技能名>。"""
    url = ((skill_meta(skill) or {}).get("url") or "").strip().strip("/")
    if url:
        return url
    if skill in _NS_BY_SKILL:
        return _NS_BY_SKILL[skill]
    return "skills/" + skill


def skill_dir(skill):
    """技能的数据目录（data-root 下）。"""
    return namespace_dir(skill_namespace(skill))


def code_dirs(skill):
    meta = skill_meta(skill) or {}
    return tuple(meta.get("code") or DEFAULT_CODE_DIRS)


def textbooks_dir():
    """教材库根目录（data-root 下，含 index.json / pages/ / pdf/）。"""
    return resolve("textbooks")


def data_dirs(skill):
    meta = skill_meta(skill) or {}
    return tuple(meta.get("data") or DEFAULT_DATA_DIRS)


def repo_skill_path(skill):
    """技能在仓库内的目录（代码侧）。"""
    return REPO_ROOT / ".trae" / "skills" / skill


def repo_data_dirs():
    """仓库内所有**不该存在**的数据目录（供 guard / 打包器断言）。"""
    found = []
    skills_root = REPO_ROOT / ".trae" / "skills"
    if skills_root.is_dir():
        for skill_path in sorted(skills_root.iterdir()):
            if not skill_path.is_dir():
                continue
            for name in data_dirs(skill_path.name):
                candidate = skill_path / name
                if candidate.is_dir():
                    found.append(candidate)
    for name in ("personal", "画作档案", "textbooks"):
        candidate = REPO_ROOT / name
        if candidate.is_dir():
            found.append(candidate)
    return found


def describe():
    lines = []
    try:
        root = data_root()
    except DataRootNotConfigured as exc:
        return ["数据区未配置：%s" % exc, "（示例配置见 %s）" % LOCAL_EXAMPLE.name]
    lines.append("data-root: %s" % root)
    lines.append("仓库根  : %s" % REPO_ROOT)
    lines.append("")
    lines.append("命名空间 → 技能 → 数据目录")
    skills_root = REPO_ROOT / ".trae" / "skills"
    skills = sorted(p.name for p in skills_root.iterdir() if p.is_dir()) if skills_root.is_dir() else []
    for skill in skills:
        ns = skill_namespace(skill)
        lines.append("  %-10s %-22s %s" % (ns, skill, root / ns))
    lines.append("")
    lines.append("根级共享：%s" % ", ".join(SHARED_NAMESPACES))
    return lines


def _self_test():
    """自检断言：仓库内的 root 必须被拒、仓库外的 root 必须通过、逃逸路径必须被拒。"""
    failures = []
    saved = os.environ.get(ENV_VAR)

    os.environ[ENV_VAR] = str(REPO_ROOT / "_should_be_rejected")
    try:
        data_root(refresh=True)
        failures.append("仓库内的 data_root 未被拒绝")
    except DataRootNotConfigured:
        pass

    os.environ[ENV_VAR] = str(REPO_ROOT)
    try:
        data_root(refresh=True)
        failures.append("data_root 等于仓库根时未被拒绝")
    except DataRootNotConfigured:
        pass

    import tempfile
    with tempfile.TemporaryDirectory(prefix="gh_data_root_") as tmp:
        os.environ[ENV_VAR] = tmp
        try:
            root = data_root(refresh=True)
            if Path(root) != Path(tmp).resolve():
                failures.append("仓库外的 data_root 解析错误：%s" % root)
            try:
                ensure_within_root(REPO_ROOT / "tools")
                failures.append("逃出 data-root 的路径未被拒绝")
            except DataRootNotConfigured:
                pass
        except DataRootNotConfigured as exc:
            failures.append("仓库外的 data_root 被误拒：%s" % exc)

    if saved is None:
        os.environ.pop(ENV_VAR, None)
    else:
        os.environ[ENV_VAR] = saved
    try:  # 重置缓存，回到真实配置（未配置时静默即可）
        data_root(refresh=True)
    except DataRootNotConfigured:
        pass

    if failures:
        for f in failures:
            print("  [失败] %s" % f)
        return 1
    print("  [OK] data-root 断言全部通过（仓库内被拒、仓库外通过、逃逸被拒）")
    return 0


def main():
    ap = argparse.ArgumentParser(description="数据区（data-root）路径解析")
    ap.add_argument("--self-test", action="store_true", help="自检断言")
    args = ap.parse_args()
    if args.self_test:
        return _self_test()
    for line in describe():
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
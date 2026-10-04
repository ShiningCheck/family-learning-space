# -*- coding: utf-8 -*-
"""portal-core.storage · Store：技能数据的统一读写与合并（架构 v2 第 2 步交付）。

全仓库唯一的「同步合并」实现（见 docs/architecture-v2.md §3/§5 与
.trae/rules/project_rules.md 规则 1）。技能不再自写同步逻辑：

    from portal_core.storage import Store   # 第 4 步换 FastAPI 内核后的用法
    store = Store.for_skill("subject-chinese")
    state = store.read("homework")
    store.write("homework", payload, merge="ts")

本步（第 2 步）只交付模块本身，不接进任何 handler；现有 preview_server.py 里的
合并逻辑（merge_stamped / merge_homework_checkins / handle_class_checkin 等）原样保留，
第 3/4 步再把 handler 迁到 Store 上。

路径解析走 tools/data_paths.py（仓库内唯一真源）：数据一律落在仓库之外的
data-root（<data-root>/<命名空间>/data/），仓库内不得出现任何 data/ 目录。

三种 merge 语义：
  - "ts"        ：记录类数据（打卡、勾选、进度）。同一项 + 同一天（或同一本书同一章）
                  按 ts（毫秒时间戳）取新；「取消打卡」的 v:0 墓碑照常保留并参与取新，
                  取消动作才能同步到别的设备；升级前没有 ts 的旧数据（裸 1/true 或
                  无 ts 的记录）按 ts=0 对待，两边都没时间戳时取并集，宁可多留也不丢记录。
  - "date-dim"  ：按天布尔值的简单记录（如英语页 {日期: {维度: true}}）。
                  同一 date + 同一维度，新值直接覆盖；没提到的日期/维度原样保留。
  - "overwrite" ：整体覆盖（配置、内容文件）。
"""
import json
import os
import re
import sys
import threading
from pathlib import Path

# tools/data_paths.py 是数据路径的唯一真源：data-root 由仓库根 local.json 指定，
# 必须是仓库之外的绝对路径；未配置时抛 DataRootNotConfigured，绝不回退到仓库内。
_REPO_ROOT = Path(__file__).resolve().parents[2]
_TOOLS = str(_REPO_ROOT / "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import data_paths  # noqa: E402

MERGE_MODES = ("ts", "date-dim", "overwrite")

_locks = {}
_locks_guard = threading.Lock()


def _lock_for(path):
    with _locks_guard:
        lock = _locks.get(path)
        if lock is None:
            lock = threading.Lock()
            _locks[path] = lock
        return lock


# ----------------------------------------------------------------------
# merge="ts"：按毫秒时间戳取新 + v:0 墓碑 + 无 ts 旧数据取并集
# ----------------------------------------------------------------------

def _ts_of(node):
    """记录节点的时间戳；非记录或没有 ts 一律按 0（旧数据）对待。"""
    if isinstance(node, dict):
        try:
            return float(node.get("ts") or 0)
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def _is_record(node):
    """带 ts 或 v 的 dict 视为一条「记录」（打卡标记、章节进度等）。"""
    return isinstance(node, dict) and ("ts" in node or "v" in node)


def _norm_scalar(mark):
    """升级前的旧格式（裸 1 / true）规范化成记录；假值视为「没有记录」。

    与 preview_server._norm_day_mark 一致：{ "YYYY-MM-DD": 1 } 当作 {v:1, ts:0}，
    0/空 不算记录（升级前的旧数据里没有"取消"概念，取消一定有 ts）。
    """
    if isinstance(mark, dict):
        return mark
    if mark:
        return {"v": 1, "ts": 0}
    return None


def _list_union(a, b):
    """保序并集（如书单逐章进度 chapters）。"""
    out = list(a)
    for x in b:
        if x not in out:
            out.append(x)
    return out


def _union_records(old, new):
    """ts 相同（含两边都没 ts 的旧数据）时取并集：v 取或、列表并集、缺的键补齐，
    宁可多留也不丢记录。"""
    out = dict(old)
    for k, v in new.items():
        if k == "v":
            out["v"] = 1 if (old.get("v") or v) else 0
        elif k == "ts":
            out["ts"] = old.get("ts", 0) or 0
        elif k not in out:
            out[k] = v
        elif isinstance(out[k], list) and isinstance(v, list):
            out[k] = _list_union(out[k], v)
        elif isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _merge_ts_node(out[k], v)
        # 其余标量冲突保旧：并集语义下不动旧值最不容易丢东西
    return out


def _merge_ts_node(old, new):
    """递归合并：记录节点按 ts 取新（相同取并集）；容器 dict 递归；
    旧格式标量先规范化成 ts=0 的记录再比较。"""
    old = _norm_scalar(old) if not isinstance(old, dict) else old
    new = _norm_scalar(new) if not isinstance(new, dict) else new
    if old is None:
        return new
    if new is None:
        return old
    if _is_record(old) and _is_record(new):
        ots, nts = _ts_of(old), _ts_of(new)
        if nts > ots:
            return dict(new)
        if nts < ots:
            return dict(old)
        return _union_records(old, new)
    if isinstance(old, dict) and isinstance(new, dict):
        out = dict(old)
        for k, v in new.items():
            out[k] = _merge_ts_node(out[k], v) if k in out else v
        return out
    # 两个都是标量（旧格式）：取或，不丢已打的卡
    return new if (new and not old) else old


_DAY_KEY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _normalize_legacy(node):
    """把日期键下的旧格式裸标记规范化：truthy 标量 → {"v":1,"ts":0}，
    假值标量（升级前的旧数据里没有"取消"概念）不算记录，丢弃。
    只认日期形键，不动 "updated" 这类普通标量字段。"""
    if not isinstance(node, dict):
        return node
    out = {}
    for k, v in node.items():
        if _DAY_KEY.match(str(k)) and not isinstance(v, dict):
            if v:
                out[k] = {"v": 1, "ts": 0}
        else:
            out[k] = _normalize_legacy(v)
    return out


def merge_ts(old, new):
    """整份记录合并：old/new 都是 dict（任意深度，记录叶子带 ts）。"""
    old = _normalize_legacy(old) if isinstance(old, dict) else {}
    new = _normalize_legacy(new) if isinstance(new, dict) else {}
    return _merge_ts_node(old, new)


# ----------------------------------------------------------------------
# merge="date-dim"：按 date + 维度直接覆盖
# ----------------------------------------------------------------------

def merge_date_dim(old, new):
    """{日期: {维度: 值}} 两层结构：同一天同一维度新值覆盖旧值，其余原样保留。"""
    out = dict(old) if isinstance(old, dict) else {}
    for date, dims in (new or {}).items():
        if not isinstance(dims, dict):
            out[date] = dims
            continue
        day = out.get(date)
        day = dict(day) if isinstance(day, dict) else {}
        day.update(dims)
        out[date] = day
    return out


# ----------------------------------------------------------------------


class Store:
    """一个技能的数据目录（<data-root>/<命名空间>/data/）的读写口。"""

    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)

    @classmethod
    def for_skill(cls, skill_url):
        """按技能的 url 命名空间解析数据目录（走 tools/data_paths.py，唯一真源）。

        参数是技能在门户里的 url 前缀（skill.json 的 url 字段，如 "web"、"lib"、
        "subject-chinese"）；传入的串刚好是技能目录名时，按它的 skill.json 声明解析。
        """
        ns = str(skill_url or "").strip().strip("/")
        if not ns:
            raise ValueError("skill_url 不能为空")
        if data_paths.skill_meta(ns) is not None:
            ns = data_paths.skill_namespace(ns)
        return cls(data_paths.namespace_dir(ns) / "data")

    def _path(self, name):
        rel = str(name or "").strip().strip("/")
        if not rel or ".." in rel.split("/"):
            raise ValueError("非法的数据名：%r" % (name,))
        if not rel.endswith(".json"):
            rel += ".json"
        path = (self.data_dir / rel).resolve()
        if not str(path).startswith(str(self.data_dir.resolve())):
            raise ValueError("数据名逃出了技能数据目录：%r" % (name,))
        return path

    def read(self, name):
        """读 <data_dir>/<name>.json；不存在或解析失败返回 None。"""
        path = self._path(name)
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def write(self, name, payload, merge="overwrite"):
        """按 merge 语义把 payload 合并进 <name>.json 并原子落盘，返回合并结果。

        merge 取值见模块 docstring："ts" / "date-dim" / "overwrite"。
        """
        if merge not in MERGE_MODES:
            raise ValueError("merge 必须是 %s 之一，当前为 %r" % (MERGE_MODES, merge))
        path = self._path(name)
        with _lock_for(str(path)):
            existing = self.read(name)
            if merge == "overwrite":
                merged = payload
            elif merge == "date-dim":
                merged = merge_date_dim(existing, payload)
            else:
                merged = merge_ts(existing, payload)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = str(path) + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(merged, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
            return merged

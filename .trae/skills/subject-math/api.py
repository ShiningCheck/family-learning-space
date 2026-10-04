# -*- coding: utf-8 -*-
"""subject-math 技能 API（架构 v2 第 3 步）：数学学科页的作业卡路由。

这些 handler 从 growth-home/web/preview_server.py 的路由注册表**移动**而来
（移动，不是复制）：collect_homework_data / handle_homework_post /
handle_homework_upload 及三条 /api/homework 系路由。行为与原来逐字一致，
**数据读写路径一律不变**——仍读写 <data-root>/web/data/homework.json，
数据搬家（按科目拆到 chinese/data/ 与 math/data/）是切换段的事。

按任务书「/api/homework 系拆成 chinese 与 math 两套」，本文件与
subject-chinese/api.py 是同源同行为的两套（各自命名空间）；旧路径三条由
先注册者优先（两者 handler 行为一致，谁挂上都不影响响应）。

路由形状与主注册表相同：(方法, 路径) -> handler(h)，h 是 http.server handler 实例。
模块级代码不许碰数据路径：一切依赖由门户服务器启动时 bind(ctx) 注入。
"""
import json
import os
import uuid
from datetime import datetime

# —— 由 bind(ctx) 注入的共享上下文（preview_server.py 的 _skill_api_context）——
_CTX = {}

GH_DATA = None
SKILL_DATA = None
CORE_DATA = None
HOMEWORK_FILE = None
HOMEWORK_MEDIA = None
ACTIVITIES_FILE = None
CONFIG_FILE = None
HOMEWORK_BODY_LIMIT = 300 * 1024 * 1024  # 单个视频/图片附件上限（与原路由一致）


def bind(ctx):
    """门户服务器加载本模块后回调：注入共享助手与数据路径常量。

    架构 v2 第 3 步：作业内容读本技能 data 目录（math/data/homework.json），
    孩子档案与 activities 读 core，作业附件仍落 web/data/homework_media（媒体未搬迁）。
    """
    global GH_DATA, SKILL_DATA, CORE_DATA, HOMEWORK_FILE, HOMEWORK_MEDIA, ACTIVITIES_FILE, CONFIG_FILE
    _CTX.update(ctx)
    GH_DATA = ctx["GH_DATA"]
    SKILL_DATA = ctx["SKILL_DATA"]
    CORE_DATA = ctx["CORE_DATA"]
    HOMEWORK_FILE = os.path.join(SKILL_DATA, "homework.json")
    HOMEWORK_MEDIA = os.path.join(GH_DATA, "homework_media")
    ACTIVITIES_FILE = os.path.join(CORE_DATA, "activities.json")
    CONFIG_FILE = os.path.join(CORE_DATA, "config.json")


def _load_json(path):
    return _CTX["load_json"](path)


def _write_json(path, obj):
    return _CTX["write_json"](path, obj)


def _safe_token(val, allow):
    return _CTX["safe_token"](val, allow)


def collect_homework_data():
    """作业卡片：孩子姓名 + 作业条目（含科目归属、图片/视频附件、有效期）。

    subjects 来自 activities.json——作业卡按 subject 分发到各学科页
    （语文/数学/辅导班英语/学校英语），这里一并下发，页面就不用再多请求一次。
    """
    cfg = _load_json(CONFIG_FILE) or {}
    data = _load_json(HOMEWORK_FILE) or {}
    acts = _load_json(ACTIVITIES_FILE) or {}
    return {
        "childName": cfg.get("childName", ""),
        "items": data.get("items") or [],
        "subjects": acts.get("subjects") or [],
    }


def handle_homework_post(raw_body):
    """作业增删改：op 取值 add / update / delete，返回更新后的完整 items。"""
    try:
        raw = json.loads(raw_body.decode("utf-8", "replace")) if raw_body else {}
    except Exception:
        return 400, {"ok": False, "error": "bad_json"}
    op = raw.get("op")
    data = _load_json(HOMEWORK_FILE) or {}
    items = list(data.get("items") or [])

    if op == "delete":
        hid = _safe_token(raw.get("id"), "A-Za-z0-9_-")
        items = [it for it in items if str(it.get("id")) != hid]
    elif op in ("add", "update"):
        item = raw.get("item") if isinstance(raw.get("item"), dict) else {}
        if not item:
            return 400, {"ok": False, "error": "缺少作业内容"}
        if op == "add":
            item.setdefault("id", "hw_%s" % uuid.uuid4().hex[:8])
            item.setdefault("createdAt", datetime.now(_CTX["CN_TZ"]).strftime("%Y-%m-%d"))
            items.append(item)
        else:
            hid = str(item.get("id") or raw.get("id") or "")
            replaced = False
            for i, it in enumerate(items):
                if str(it.get("id")) == hid:
                    items[i] = item
                    replaced = True
                    break
            if not replaced:
                item.setdefault("id", hid or ("hw_%s" % uuid.uuid4().hex[:8]))
                items.append(item)
    else:
        return 400, {"ok": False, "error": "unknown_op"}

    data["items"] = items
    data["updated"] = datetime.now(_CTX["CN_TZ"]).strftime("%Y-%m-%d")
    _write_json(HOMEWORK_FILE, data)
    return 200, {"ok": True, "items": items}


def handle_homework_upload(fields):
    """保存作业附件（图片/视频），返回可静态托管的 URL。"""
    f = fields.get("file")
    if not f or not f.get("data"):
        raise ValueError("缺少文件")
    blob = f["data"]
    fn = (f.get("filename") or "file").lower()
    ext = os.path.splitext(fn)[1] or ""
    VIDEO_EXTS = {".mp4", ".webm", ".mov", ".m4v", ".mkv", ".avi", ".mts", ".3gp"}
    IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".heic"}
    if ext in VIDEO_EXTS:
        mtype = "video"
    elif ext in IMAGE_EXTS:
        mtype = "image"
    elif blob[:4] == b"\x89PNG":
        mtype, ext = "image", ".png"
    elif blob[:2] == b"\xff\xd8":
        mtype, ext = "image", ".jpg"
    elif blob[:4] == b"RIFF" and blob[8:12] == b"WEBP":
        mtype, ext = "image", ".webp"
    else:
        mtype, ext = "video", ".mp4"  # 无法识别时按视频处理
    os.makedirs(HOMEWORK_MEDIA, exist_ok=True)
    safe = "hw_%s_%s%s" % (datetime.now(_CTX["CN_TZ"]).strftime("%Y%m%d%H%M%S"), uuid.uuid4().hex[:6], ext)
    with open(os.path.join(HOMEWORK_MEDIA, safe), "wb") as fh:
        fh.write(blob)
    label = os.path.splitext((f.get("filename") or ""))[0][:40] or ("视频" if mtype == "video" else "图片")
    return {"ok": True, "url": "/data/homework_media/" + safe, "type": mtype, "label": label}


# ----------------------------------------------------------------------
# 路由（handler 与原 preview_server.py 注册表里的逐字对应）
# ----------------------------------------------------------------------

def route_get_homework(h):
    return h.send_json(collect_homework_data())


def route_post_homework(h):
    try:
        length = int(h.headers.get("Content-Length") or 0)
    except ValueError:
        length = 0
    if length <= 0 or length > _CTX["MAX_BODY_BYTES"]:
        return h.send_json({"ok": False, "error": "empty_body"}, 400)
    try:
        body = h.rfile.read(length)
    except Exception as e:
        return h.send_json({"ok": False, "error": "read_failed: %s" % e}, 400)
    status, resp = handle_homework_post(body)
    return h.send_json(resp, status)


def route_post_homework_upload(h):
    try:
        length = int(h.headers.get("Content-Length") or 0)
    except ValueError:
        length = 0
    if length <= 0:
        return h.send_json({"ok": False, "error": "空请求"}, 400)
    if length > HOMEWORK_BODY_LIMIT:
        return h.send_json({"ok": False, "error": "文件太大（上限 300MB）"}, 413)
    try:
        body = h.rfile.read(length)
    except Exception as e:
        return h.send_json({"ok": False, "error": "读取失败: %s" % e}, 400)
    fields = _CTX["parse_multipart"](h.headers.get("Content-Type", ""), body)
    if not fields:
        return h.send_json({"ok": False, "error": "无法解析表单"}, 400)
    try:
        result = handle_homework_upload(fields)
    except ValueError as e:
        return h.send_json({"ok": False, "error": str(e)}, 400)
    except Exception as e:
        return h.send_json({"ok": False, "error": "%s: %s" % (type(e).__name__, e)}, 500)
    return h.send_json(result)


def route_get_home(h):
    """学科页聚合口：门户 /api/home 的同名载荷（core 的 collector 经由 ctx 复用）。"""
    return h.send_json(_CTX["collect_home_data"]())


ROUTES = {
    # 新命名空间路径
    ("GET", "/api/math/homework"): route_get_homework,
    ("POST", "/api/math/homework"): route_post_homework,
    ("POST", "/api/math/homework/upload"): route_post_homework_upload,
    ("GET", "/api/math/home"): route_get_home,
    # legacy 兼容，v2.1 删除（subject-chinese 已先注册同键，冲突时现有注册表优先；
    # 两者 handler 同源同行为，响应不受影响）
    ("GET", "/api/homework"): route_get_homework,
    ("POST", "/api/homework"): route_post_homework,
    ("POST", "/api/homework/upload"): route_post_homework_upload,
}

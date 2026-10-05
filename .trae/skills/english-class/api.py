# -*- coding: utf-8 -*-
"""english-class 技能 API（架构 v2 第 3 步）：辅导班英语的内容与跟读路由。

handler 从 growth-home/web/preview_server.py 的路由注册表**移动**而来
（移动，不是复制）：collect_class_data 与 GET /api/class/data。行为与原来
逐字一致，**数据读写路径一律不变**——仍读 <data-root>/web/data/
english_class.json 与 english_class_records.json，数据搬家是切换段的事。

打卡说明：POST /api/class/checkin 属 core 打卡 6 条之一，留在 preview_server.py
不动；本技能新页面的打卡走 core 统一打卡服务 /api/checkins（skill=class）。

跟读评分（本次新增）：
    POST /api/class/speech/eval      录音 -> 落盘 + 本机识别 -> 评分 -> 记录（跨设备同步）
    GET  /api/class/speech/records   取跟读记录（可按 unit 过滤）
音频落本技能 data 目录（<root>/class/data/speech/audio/…，URL /class/data/speech/…），
跟读记录落 <root>/class/data/speech_records.json，按 key 的 ts 取新合并。

模块级代码不许碰数据路径：一切依赖由门户服务器启动时 bind(ctx) 注入。
"""
import importlib.util
import os
import re
import threading
import time
import uuid
from datetime import datetime

# —— 由 bind(ctx) 注入的共享上下文（preview_server.py 的 _skill_api_context）——
_CTX = {}

GH_DATA = None
SKILL_DATA = None
CORE_DATA = None
CLASS_FILE = None
CONFIG_FILE = None
ASR = None
SPEECH_FILE = None

_SPEECH_LOCK = threading.Lock()


def _load_sibling(name):
    """加载同目录下的兄弟模块（技能目录不一定在 sys.path 上，按文件路径加载最稳）。"""
    here = os.path.dirname(os.path.abspath(__file__))
    spec = importlib.util.spec_from_file_location("english_class_" + name, os.path.join(here, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


speech_eval = _load_sibling("speech_eval")


def bind(ctx):
    """门户服务器加载本模块后回调：注入共享助手与数据路径常量。

    架构 v2 第 3 步：单元内容读本技能 data 目录（class/data/english_class.json），
    孩子档案读 core，打卡记录改走 core checkins（checkins_by_skill("class")）。
    """
    global GH_DATA, SKILL_DATA, CORE_DATA, CLASS_FILE, CONFIG_FILE, ASR, SPEECH_FILE
    _CTX.update(ctx)
    GH_DATA = ctx["GH_DATA"]
    SKILL_DATA = ctx["SKILL_DATA"]
    CORE_DATA = ctx["CORE_DATA"]
    CLASS_FILE = os.path.join(SKILL_DATA, "english_class.json")
    CONFIG_FILE = os.path.join(CORE_DATA, "config.json")
    ASR = ctx.get("asr_engine")
    SPEECH_FILE = os.path.join(SKILL_DATA, "speech_records.json")


def collect_class_data():
    """英语辅导班：单元内容(听说读写作业/资料) + 孩子姓名 + 打卡记录（来自 core checkins）。"""
    content = _CTX["load_json"](CLASS_FILE) or {}
    cfg = _CTX["load_json"](CONFIG_FILE) or {}
    try:
        # 跟读及格分（与评分接口同源）：前端据此判断"跟读达标 = 自动打卡"
        pass_score = int((content.get("speechEval") or {}).get("passScore") or 60)
    except (TypeError, ValueError):
        pass_score = 60
    return {
        "childName": cfg.get("childName", ""),
        "goal": content.get("goal", "跟着辅导班，听说读写，每天进步一点点"),
        "weeklyTarget": content.get("weeklyTarget", "每周至少打卡 3 次"),
        "roadmap": content.get("roadmap", []),
        "units": content.get("units", []),
        "passScore": pass_score,
        "records": _CTX["checkins_by_skill"]("class"),
    }


def route_get_class_data(h):
    return h.send_json(collect_class_data())


def route_get_home(h):
    """页面聚合口：门户 /api/home 的同名载荷（core 的 collector 经由 ctx 复用）。"""
    return h.send_json(_CTX["collect_home_data"]())


# ======================================================================
# 跟读评分：录音 -> 识别 -> 打分 -> 记录（跨设备同步）
# ======================================================================

def _field_text(fields, key):
    val = (fields.get(key) or {}).get("data") or b""
    try:
        return val.decode("utf-8", "replace").strip()
    except Exception:
        return ""


def _audio_ext(filename, data):
    """按文件头判断音频格式，拿不准再看后缀（手机录音常见 m4a / mp4 / webm）。"""
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return ".wav"
    if data[:4] == b"OggS":
        return ".ogg"
    if data[:4] == b"\x1aE\xdf\xa3":
        return ".webm"
    if data[4:8] == b"ftyp":
        return ".m4a"
    if data[:3] == b"ID3" or data[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return ".mp3"
    fn = (filename or "").lower()
    for ext in (".m4a", ".mp4", ".aac", ".wav", ".mp3", ".ogg", ".oga", ".webm", ".amr", ".3gp"):
        if fn.endswith(ext):
            return ".m4a" if ext in (".mp4", ".aac") else ext
    return ".webm"


def _speech_doc():
    doc = _CTX["load_json"](SPEECH_FILE) or {}
    if not isinstance(doc, dict):
        doc = {}
    recs = doc.get("records")
    if not isinstance(recs, dict):
        recs = {}
    doc["records"] = recs
    return doc


def _speech_upsert(key, node):
    """把一条跟读记录合并落盘：同一 key 按 ts 取新（两台设备同时改互不覆盖）。"""
    with _SPEECH_LOCK:
        doc = _speech_doc()
        old = doc["records"].get(key)
        if isinstance(old, dict) and int(old.get("ts") or 0) > int(node.get("ts") or 0):
            return old                       # 服务器上这份更新，保留
        doc["records"][key] = node
        doc["updated"] = _CTX["now_iso"]()
        _CTX["write_json"](SPEECH_FILE, doc)
        return node


def route_post_speech_eval(h):
    """跟读评分：录音落盘 -> 本机识别（逐词时间戳）-> 评分 -> 记录。

    表单字段：audio（音频）/ target（目标英文句）/ key（<单元id>:<板块id>:<序号>）
             date / lang（默认 en）
    返回 {"ok": True, "record": {…含 score/accuracy/fluency/completeness/targetWords/url…}}。
    """
    try:
        length = int(h.headers.get("Content-Length") or 0)
    except ValueError:
        length = 0
    if length <= 0:
        return h.send_json({"ok": False, "error": "空请求"}, 400)
    if length > _CTX["MAX_BODY_BYTES"]:
        return h.send_json({"ok": False, "error": "录音太大"}, 413)
    try:
        body = h.rfile.read(length)
    except Exception as e:
        return h.send_json({"ok": False, "error": "读取失败: %s" % e}, 400)
    fields = _CTX["parse_multipart"](h.headers.get("Content-Type", ""), body)
    if not fields:
        return h.send_json({"ok": False, "error": "无法解析表单"}, 400)

    audio_field = fields.get("audio") or {}
    data = audio_field.get("data")
    if not data:
        return h.send_json({"ok": False, "error": "缺少录音"}, 400)
    target = _field_text(fields, "target")[:300]
    key = speech_eval.clean_key(_field_text(fields, "key"))
    if not target or not key:
        return h.send_json({"ok": False, "error": "缺少 target 或 key"}, 400)
    lang = _field_text(fields, "lang") or "en"
    date_val = re.sub(r"[^0-9-]", "", _field_text(fields, "date"))[:10]
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_val or ""):
        date_val = datetime.now(_CTX["CN_TZ"]).strftime("%Y-%m-%d")

    vid = "s-%s-%s" % (datetime.now(_CTX["CN_TZ"]).strftime("%Y%m%d-%H%M%S"), uuid.uuid4().hex[:4])
    ext = _audio_ext(audio_field.get("filename"), data)
    day_dir = os.path.join(SKILL_DATA, "speech", "audio", date_val)
    os.makedirs(day_dir, exist_ok=True)
    path = os.path.join(day_dir, vid + ext)
    with open(path, "wb") as f:
        f.write(data)
    url = "/class/data/speech/audio/%s/%s%s" % (date_val, vid, ext)

    heard, words, seconds = "", [], 0.0
    asr_ok, asr_err = False, ""
    if ASR is None:
        asr_err = "本机未启用语音识别（缺 faster-whisper）"
    else:
        r = ASR.transcribe(path, lang, word_timestamps=True)
        if r.get("ok"):
            heard = r.get("text") or ""
            words = r.get("words") or []
            seconds = float(r.get("seconds") or 0)
            asr_ok = True
        else:
            asr_err = str(r.get("error") or "")[:200]

    cfg = ((_CTX["load_json"](CLASS_FILE) or {}).get("speechEval") or {})
    result = speech_eval.evaluate(target, heard, words, seconds, audio_path=path, cfg=cfg)
    try:
        pass_score = int(cfg.get("passScore") or 60)
    except (TypeError, ValueError):
        pass_score = 60

    ts = int(time.time() * 1000)
    with _SPEECH_LOCK:
        old = _speech_doc()["records"].get(key)
    old = old if isinstance(old, dict) else {}
    node = {
        "ts": ts,
        "date": date_val,
        "last": int(result.get("score") or 0),
        "best": max(int(old.get("best") or 0), int(result.get("score") or 0)),
        "attempts": int(old.get("attempts") or 0) + 1,
        "seconds": round(seconds, 1),
        "text": heard[:300],
        "url": url,
        "accuracy": int(result.get("accuracy") or 0),
        "fluency": int(result.get("fluency") or 0),
        "completeness": int(result.get("completeness") or 0),
        "source": result.get("source") or "local",
        "words": result.get("targetWords") or [],
    }
    saved = _speech_upsert(key, node)

    record = {
        "id": vid,
        "key": key,
        "date": date_val,
        "url": url,
        "text": heard,
        "asr": heard,
        "asrOk": asr_ok,
        "asrError": asr_err,
        "seconds": seconds,
        "target": target,
        "score": int(result.get("score") or 0),
        "accuracy": int(result.get("accuracy") or 0),
        "fluency": int(result.get("fluency") or 0),
        "completeness": int(result.get("completeness") or 0),
        "targetWords": result.get("targetWords") or [],
        "source": result.get("source") or "local",
        "passed": int(result.get("score") or 0) >= pass_score,
        "passScore": pass_score,
        "best": int(saved.get("best") or 0),
        "attempts": int(saved.get("attempts") or 0),
    }
    return h.send_json({"ok": True, "record": record})


def route_get_speech_records(h):
    """取跟读记录。?unit=<单元id> 只看某一课；不带则全部。"""
    doc = _speech_doc()
    unit = _CTX["safe_token"](h.query_value("unit"), "A-Za-z0-9_-")[:32]
    out = {}
    for key, node in doc["records"].items():
        if unit and not key.startswith(unit + ":"):
            continue
        if isinstance(node, dict):
            out[key] = node
    return h.send_json({"ok": True, "updated": doc.get("updated", ""), "records": out})


ROUTES = {
    # 技能 url 是 class：新命名空间路径 /api/class/data 与旧路径相同（同源同键）
    ("GET", "/api/class/data"): route_get_class_data,
    ("GET", "/api/class/home"): route_get_home,
    # 跟读评分
    ("POST", "/api/class/speech/eval"): route_post_speech_eval,
    ("GET", "/api/class/speech/records"): route_get_speech_records,
}
"""成长家园门户 - 本地预览服务器
统一托管：成长家园首页 + 学习看板(learning-growth-board) + 书包清单(school-bag-organizer)。
启动后，手机和电脑在同一WiFi下，手机浏览器访问电脑IP即可。
使用: python preview_server.py

【架构 v2 第 2 步说明】本文件是门户的过渡期内核：静态资产与门户 shell 已迁到
仓库根 portal-core/（vendor 单源 /components/homework-section.js /web/index.html），
由下面的 translate_path 映射与 301 重定向承接；但**本服务器文件本身仍留在
growth-home**——换 FastAPI 内核是架构 v2 第 4 步的事，届时本文件整体退役。
29 条 /api 路由的行为、路径、handler 在第 2 步一律不变。

除静态托管外，本服务器还承担「用户反馈」的本地出口：
  GET  /api/feedback/config  下发匿名安装ID、应用版本、中转服务地址
  POST /api/feedback         接收页面反馈 -> 落盘 -> 转发到公网中转服务(自动建 GitHub Issue + 推飞书)
  GET  /api/feedback/status  查看本机反馈的送达状态（作者排查用）
反馈必须经过本地服务器转发，是因为浏览器直连第三方接口会被 CORS 拦住，
而 Python 端发请求没有这个限制；同时断网时能先落盘、联网后自动补发，一条都不丢。

以及「打卡状态跨设备同步」：读书/家务/运动/书单与作业卡的打卡记录都以服务器上的文件为准，
手机、平板、电脑打开的是同一份，浏览器 localStorage 只作断网时的本地缓存。
作业卡按 subject（科目）分发到语文/数学/辅导班英语/学校英语四个学科页里打卡展示，
原来的独立「作业打卡」页已经取消，完成情况统一在「日报」里汇报。
  GET  /api/tracker?tab=<标签id>         读某标签页打卡状态
  POST /api/tracker                      写打卡状态（合并规则：同一天按时间戳取新）
  GET  /api/homework/checkins            读作业打卡记录（含「握笔练习」这类长期作业）
  POST /api/homework/checkins            写作业打卡记录（合并规则同上，逐项逐日按时间戳取新）

另外本服务器负责「配音自动补齐」：英语内容、辅导班、学校英语、作业、标签页、书单、
书目、画作、学情、课表用具等文件一有改动，后台线程就自动跑一次 voice-dubbing 技能的
增量生成，保证页面朗读的内容都有预生成的音频（服务器启动时也会先补一次）。
  GET  /api/tts/status       配音清单条数 + 最近一次自动补齐的时间与结果

以及「语音记录（录音 + 自动转文字）」：各页面的录音/上传都走这里，音频落盘、本机离线识别成
文字，做到文字和语音一起留档（识别引擎见同目录 asr.py，音频不出电脑）。
  GET  /api/voice?scope=&date=&limit=   取语音记录（scope 支持前缀匹配）
  POST /api/voice                       上传录音（multipart: audio/scope/lang/date/text/meta/asr）
  POST /api/voice/text                  修订某条记录的文字
  POST /api/voice/delete                删掉某条记录（索引与音频文件一起删）
  GET  /api/voice/status                识别引擎状态（模型、是否就绪、已识别条数）
"""
import base64
import glob
import hashlib
import hmac
import http.server
import json
import mimetypes
import os
import platform
import posixpath
import re
import shutil
import socket
import socketserver
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import webbrowser
from datetime import datetime, timedelta, timezone

# 本地语音识别（同目录 asr.py）：把页面录的语音转成文字，音频不出电脑。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import asr as asr_engine
except Exception as _asr_err:          # 缺依赖也不该让整个门户起不来
    asr_engine = None
    print("[asr] 语音识别模块不可用：%s" % _asr_err)

PORT = int(os.environ.get("GH_PORT", 8090))   # 默认 8090；自动化测试用 GH_PORT 换端口，避免打扰正在跑的门户
DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # growth-home skill root（只放代码）
SKILLS_DIR = os.path.dirname(DIR)
LEARN_DIR = os.path.join(SKILLS_DIR, "learning-growth-board")      # 代码目录
BAG_DIR = os.path.join(SKILLS_DIR, "school-bag-organizer")
ART_DIR = os.path.join(SKILLS_DIR, "xiaoshan-art-archive")
LIB_DIR = os.path.join(SKILLS_DIR, "home-library")
COMP_DIR = os.path.join(SKILLS_DIR, "competition")
WORKSPACE_ROOT = os.path.dirname(os.path.dirname(SKILLS_DIR))  # 仓库根目录（只放代码）

# —— portal-core 框架核（架构 v2 第 2 步，见 docs/architecture-v2.md §3）——
# vendor 单源、学科共享组件、门户 shell 都迁到了仓库根 portal-core/；
# 这里只做 URL → 文件的路径映射（translate_path）与旧地址 301 重定向。
PORTAL_CORE = os.path.join(WORKSPACE_ROOT, "portal-core")
PORTAL_CORE_VENDOR = os.path.join(PORTAL_CORE, "vendor")
PORTAL_CORE_COMPONENTS = os.path.join(PORTAL_CORE, "components")
PORTAL_CORE_WEB = os.path.join(PORTAL_CORE, "web")

# —— 数据区（data-root）：孩子的隐私数据一律落在仓库之外 ——
# 路径解析走 tools/data_paths.py（仓库内唯一真源）。未配置就报错退出，绝不回退到仓库内，
# 否则数据会重新长回仓库。配置方式：仓库根 local.json 的 data_root（由 python setup.py 生成）。
sys.path.insert(0, os.path.join(WORKSPACE_ROOT, "tools"))
import data_paths  # noqa: E402

try:
    GH_DATA = str(data_paths.skill_dir("growth-home") / "data")            # <root>/web/data
    CORE_DATA = str(data_paths.namespace_dir("core") / "data")             # <root>/core/data（架构 v2）
    READING_DATA = str(data_paths.skill_dir("reading") / "data")           # <root>/reading/data
    LEARN_DATA = str(data_paths.skill_dir("learning-growth-board") / "data")
    BAG_DATA = str(data_paths.skill_dir("school-bag-organizer") / "data")
    ART_DATA = str(data_paths.skill_dir("xiaoshan-art-archive") / "data")
    ART_IMAGES = str(data_paths.skill_dir("xiaoshan-art-archive") / "images")
    ART_AUDIO = str(data_paths.skill_dir("xiaoshan-art-archive") / "audio")
    LIB_DATA = str(data_paths.skill_dir("home-library") / "data")
    LIB_IMAGES = str(data_paths.skill_dir("home-library") / "images")
    COMP_DATA = str(data_paths.skill_dir("competition") / "data")
    TEXTBOOKS_DIR = str(data_paths.textbooks_dir())
except data_paths.DataRootNotConfigured as _exc:
    raise SystemExit("[数据区未配置] %s\n请先在仓库根运行：python setup.py" % _exc)
PAGE_URL = "/"

# —— portal-core 的 Store（架构 v2 第 2 步交付，第 3 步起给 core 打卡服务用）——
# 目录名带连字符，import 语句写不了，走 importlib；合并语义（ts 取新 / date-dim / overwrite）
# 全仓唯一一份，技能不再自写同步逻辑。
sys.path.insert(0, WORKSPACE_ROOT)
import importlib  # noqa: E402
import importlib.util  # noqa: E402
_portal_storage = importlib.import_module("portal-core.storage")
Store = _portal_storage.Store

# 英语辅导班：按周组织的辅导班资料 + 按知识点板块打卡（key = <单元id>:<板块id>）
CLASS_FILE = os.path.join(GH_DATA, "english_class.json")
CLASS_RECORDS = os.path.join(GH_DATA, "english_class_records.json")

# 学校英语：外研社新交际英语 + 每日听练打卡
SCHOOL_FILE = os.path.join(GH_DATA, "school_english.json")
SCHOOL_RECORDS = os.path.join(GH_DATA, "school_english_records.json")

# 作业卡片：结构化作业（含图片/视频附件、有效期、每日打卡）
HOMEWORK_FILE = os.path.join(GH_DATA, "homework.json")
HOMEWORK_MEDIA = os.path.join(GH_DATA, "homework_media")
HOMEWORK_BODY_LIMIT = 300 * 1024 * 1024  # 单个视频/图片附件上限

# 作业打卡记录（含「握笔练习」这类长期作业卡）：落盘到 data/homework_checkins.json。
# 思路和 tracker_state.json 一致——服务器上这份为准，手机、平板、电脑看到同一份，
# 浏览器 localStorage（键 hw_<孩子名>）只当断网时的本地缓存。
HOMEWORK_CHECKINS = os.path.join(GH_DATA, "homework_checkins.json")
HOMEWORK_KEEP_DAYS = 400               # 每项作业最多保留的打卡天数

# 打卡状态：读书/家务/运动/书单的每日打卡记录 + 书单逐章进度。
# 落盘到 data/tracker_state.json：手机、平板、电脑访问同一台服务器时看到同一份数据，
# 浏览器 localStorage 只作为断网时的本地缓存。
TRACKER_STATE = os.path.join(GH_DATA, "tracker_state.json")
ACTIVITIES_FILE = os.path.join(GH_DATA, "activities.json")
TRACKER_KEEP_DAYS = 400                # 每个标签页最多保留的打卡天数

# 通用语音记录：任何页面录下/上传的语音都归到这里，落盘音频 + 识别出的文字。
# 收录音频（较大的二进制）落 data/voice/audio/<场景>/<日期>/，由静态托管直接播放；
# 文字与索引记在 data/voice/index.json —— 做到「文字和语音都留下」。
VOICE_DIR = os.path.join(GH_DATA, "voice")
VOICE_AUDIO = os.path.join(VOICE_DIR, "audio")
VOICE_INDEX = os.path.join(VOICE_DIR, "index.json")
VOICE_BODY_LIMIT = 30 * 1024 * 1024   # 单条录音上限（手机录 5 分钟也够）
VOICE_TEXT_MAX = 2000                 # 单条识别文本上限，防脏数据

# 家庭图书馆：书目 + 封面照片（读取走静态 JSON，增删改走上表接口）
LIB_BOOKS = os.path.join(LIB_DATA, "books.json")
LIB_SHELVES = os.path.join(LIB_DATA, "shelves.json")
LIB_COVERS = os.path.join(LIB_IMAGES, "covers")
LIB_BODY_LIMIT = 30 * 1024 * 1024  # 单张封面照片上限

# 比赛（competition 技能）：活动通知 + 报的项目 + 备赛打卡，记录落该技能自己的 data/
COMP_CONFIG = os.path.join(COMP_DATA, "config.json")
COMP_NOTICE = os.path.join(COMP_DATA, "notice.json")
COMP_STATE = os.path.join(COMP_DATA, "state.json")
COMP_LOCK = threading.Lock()

# 首页入口 + 兼容旧书签：原书包清单/学习看板的独立地址重定向到门户内新路径
# （架构 v2 第 2 步："/" 现在由 portal-core/web/index.html 直接提供，
#   "/index.html" 与 "/web/index.html" 走下面的 301 重定向到 "/"，不再列在这里。）
REDIRECTS = {
    "/english-class.html": "/web/english-class.html",
    "/school-english.html": "/web/school-english.html",
    "/tracker.html": "/web/tracker.html",
    "/library.html": "/lib/web/library.html",
    "/checklist.html": "/bag/web/checklist.html",
    "/web/checklist.html": "/bag/web/checklist.html",
    "/dashboard.html": "/learn/web/dashboard.html",
    "/web/dashboard.html": "/learn/web/dashboard.html",
    # 语文 / 数学各自一个学科页（同一个页面的不同科目），旧书签也能直接进
    "/chinese.html": "/web/subject.html?subject=chinese",
    "/web/chinese.html": "/web/subject.html?subject=chinese",
    "/math.html": "/web/subject.html?subject=math",
    "/web/math.html": "/web/subject.html?subject=math",
    # 「作业打卡」页已删掉，打卡在各学科页里做；旧书签退回作业管理页
    "/homework-checkin.html": "/web/homework.html",
    "/web/homework-checkin.html": "/web/homework.html",
}

# ---------- 反馈相关路径与常量 ----------
FEEDBACK_DIR = os.path.join(GH_DATA, "feedback")
FEEDBACK_INBOX = os.path.join(FEEDBACK_DIR, "inbox")
# 通道配置：真实值在 data/feedback_channels.json（已被 .gitignore 忽略），
# 发布时随 data-templates/ 一起分发的版本里内置作者的中转服务地址，用户零配置即可送达。
CHANNELS_FILE = os.path.join(GH_DATA, "feedback_channels.json")
_TEMPLATES_DIR = os.path.join(DIR, "data-templates")   # 匿名模板目录（随仓库分发）
CHANNELS_TEMPLATE = os.path.join(_TEMPLATES_DIR, "feedback_channels.json")
VERSION_FILE = os.path.join(WORKSPACE_ROOT, "VERSION")

MAX_BODY_BYTES = 8 * 1024 * 1024      # 单次提交上限（含 base64 截图）
MAX_IMAGES = 3
ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp"}
FORWARD_TIMEOUT = 12                   # 转发超时（秒），超时就转后台重试，不阻塞用户
RETRY_INTERVAL = 300                   # 后台重试间隔（秒）
MAX_RETRY_DAYS = 30                    # 超过 30 天的旧反馈不再重试
MAX_RECORDS = 300                      # 本机最多保留的反馈条数
RATE_WINDOW = 600                      # 限流窗口（秒）
RATE_LIMIT = 6                         # 每个窗口内最多转发次数
CN_TZ = timezone(timedelta(hours=8))   # 统一用 UTC+8 记录时间

_feedback_lock = threading.Lock()
_tracker_lock = threading.Lock()       # 打卡状态读写锁，避免两台设备同时提交时互相覆盖
_homework_lock = threading.Lock()      # 作业打卡状态读写锁（同一份逻辑，作业单独一个文件）
_rate_hits = []                        # 转发时间戳列表，用于限流
_meta_cache = {"at": 0, "data": None}


# ======================================================================
# 路由注册表（架构 v2 第 1 步，见 docs/architecture-v2.md §6）
# ----------------------------------------------------------------------
# do_GET / do_POST 原来的 if-chain 分发抽成路由表 ROUTES：键是 (HTTP 方法, 路径)，
# 值是模块级处理函数。处理函数参数 h 是当前的 Handler 实例，函数体与原来的
# if 分支逐字对应（h.send_json / h.query_value / h.headers / h.rfile /
# h.client_address 都从 h 上取）。查不到时走原有兜底逻辑：
#   GET  先查 REDIRECTS（老书签重定向），再走 _serve_static() 静态文件
#   POST 回 {"ok": False, "error": "not_found"} 404
# 下面的分组注释对应 docs/architecture-v2.md §4 的未来归属，只是第 2/3 步的
# 切分标记；本步不改任何 URL、方法、状态码、响应体与 query 解析行为。
# ======================================================================


# === core: 打卡服务（第3步迁入 portal-core：统一 GET/POST /api/checkins）===

def route_get_tracker(h):
    status, obj = collect_tracker_state(h.query_value("tab"))
    return h.send_json(obj, status)


def route_post_tracker(h):
    """打卡状态提交：页面把本地整份状态发上来，服务端按时间戳合并后回传。"""
    try:
        length = int(h.headers.get("Content-Length") or 0)
    except ValueError:
        length = 0
    if length <= 0:
        return h.send_json({"ok": False, "error": "空请求"}, 400)
    if length > MAX_BODY_BYTES:
        return h.send_json({"ok": False, "error": "请求太大"}, 413)
    try:
        body = h.rfile.read(length)
    except Exception as e:
        return h.send_json({"ok": False, "error": "读取失败: %s" % e}, 400)
    try:
        status, obj = handle_tracker_post(body)
    except Exception as e:
        status, obj = 500, {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}
    return h.send_json(obj, status)


def route_get_homework_checkins(h):
    status, obj = collect_homework_checkins()
    return h.send_json(obj, status)


def route_post_homework_checkins(h):
    """作业打卡提交：页面把本地整份记录发上来，服务端逐项逐日按时间戳合并后回传。"""
    try:
        length = int(h.headers.get("Content-Length") or 0)
    except ValueError:
        length = 0
    if length <= 0:
        return h.send_json({"ok": False, "error": "空请求"}, 400)
    if length > MAX_BODY_BYTES:
        return h.send_json({"ok": False, "error": "请求太大"}, 413)
    try:
        body = h.rfile.read(length)
    except Exception as e:
        return h.send_json({"ok": False, "error": "读取失败: %s" % e}, 400)
    try:
        status, obj = handle_homework_checkins_post(body)
    except Exception as e:
        status, obj = 500, {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}
    return h.send_json(obj, status)


def route_post_class_checkin(h):
    try:
        length = int(h.headers.get("Content-Length") or 0)
    except ValueError:
        length = 0
    if length <= 0 or length > MAX_BODY_BYTES:
        return h.send_json({"ok": False, "error": "empty_body"}, 400)
    try:
        body = h.rfile.read(length)
    except Exception as e:
        return h.send_json({"ok": False, "error": "read_failed: %s" % e}, 400)
    status, resp = handle_class_checkin(body)
    return h.send_json(resp, status)


def route_post_school_checkin(h):
    try:
        length = int(h.headers.get("Content-Length") or 0)
    except ValueError:
        length = 0
    if length <= 0 or length > MAX_BODY_BYTES:
        return h.send_json({"ok": False, "error": "empty_body"}, 400)
    try:
        body = h.rfile.read(length)
    except Exception as e:
        return h.send_json({"ok": False, "error": "read_failed: %s" % e}, 400)
    status, resp = handle_school_checkin(body)
    return h.send_json(resp, status)


# === core: 语音服务（第3步迁入 portal-core，原路径保留）===

def route_get_voice(h):
    return h.send_json({"ok": True, "records": voice_records(
        h.query_value("scope"), h.query_value("date"),
        h.query_value("limit") or 200)})


def route_get_voice_status(h):
    st = asr_engine.status() if asr_engine else {"available": False, "error": "未启用"}
    st["ok"] = True
    st["records"] = len(load_json(VOICE_INDEX) or [])
    return h.send_json(st)


def route_post_voice(h):
    """通用语音记录：录音/上传 -> 落盘 + 自动识别成文字（识别要跑几秒，前端记得转圈）。"""
    try:
        length = int(h.headers.get("Content-Length") or 0)
    except ValueError:
        length = 0
    if length <= 0:
        return h.send_json({"ok": False, "error": "空请求"}, 400)
    if length > VOICE_BODY_LIMIT:
        return h.send_json({"ok": False, "error": "录音太大（上限 30MB）"}, 413)
    try:
        body = h.rfile.read(length)
    except Exception as e:
        return h.send_json({"ok": False, "error": "读取失败: %s" % e}, 400)
    fields = parse_multipart(h.headers.get("Content-Type", ""), body)
    if not fields:
        return h.send_json({"ok": False, "error": "无法解析表单"}, 400)
    try:
        record = handle_voice_upload(fields)
    except ValueError as e:
        return h.send_json({"ok": False, "error": str(e)}, 400)
    except Exception as e:
        return h.send_json({"ok": False, "error": "%s: %s" % (type(e).__name__, e)}, 500)
    return h.send_json({"ok": True, "record": record})


def route_post_voice_text(h):
    """修订某条语音记录的文字（原始识别结果保留在 asr 字段）。"""
    try:
        length = int(h.headers.get("Content-Length") or 0)
    except ValueError:
        length = 0
    if length <= 0:
        return h.send_json({"ok": False, "error": "空请求"}, 400)
    if length > MAX_BODY_BYTES:
        return h.send_json({"ok": False, "error": "请求太大"}, 413)
    try:
        obj = json.loads(h.rfile.read(length).decode("utf-8", "replace") or "{}")
    except Exception as e:
        return h.send_json({"ok": False, "error": "解析失败: %s" % e}, 400)
    try:
        record = voice_update_text(obj.get("id"), obj.get("text"))
    except ValueError as e:
        return h.send_json({"ok": False, "error": str(e)}, 400)
    except Exception as e:
        return h.send_json({"ok": False, "error": "%s: %s" % (type(e).__name__, e)}, 500)
    return h.send_json({"ok": True, "record": record})


def route_post_voice_delete(h):
    """删掉某条语音记录：索引与音频文件一起删（页面上的「🗑」按钮走这里）。"""
    try:
        length = int(h.headers.get("Content-Length") or 0)
    except ValueError:
        length = 0
    if length <= 0:
        return h.send_json({"ok": False, "error": "空请求"}, 400)
    if length > MAX_BODY_BYTES:
        return h.send_json({"ok": False, "error": "请求太大"}, 413)
    try:
        obj = json.loads(h.rfile.read(length).decode("utf-8", "replace") or "{}")
    except Exception as e:
        return h.send_json({"ok": False, "error": "解析失败: %s" % e}, 400)
    try:
        record = voice_delete(obj.get("id"))
    except ValueError as e:
        return h.send_json({"ok": False, "error": str(e)}, 400)
    except Exception as e:
        return h.send_json({"ok": False, "error": "%s: %s" % (type(e).__name__, e)}, 500)
    return h.send_json({"ok": True, "record": record})


# === core: TTS 配音状态（第3步迁入 portal-core，原路径保留）===

def route_get_tts_status(h):
    return h.send_json(tts_status())


# === core: 反馈服务（第3步迁入 portal-core，原路径保留）===

def route_get_feedback_config(h):
    return h.send_json(feedback_config_payload())


def route_get_feedback_status(h):
    recs = list_records()[:50]
    slim = []
    for r in recs:
        d = r.get("delivery") or {}
        p = r.get("payload") or {}
        slim.append({
            "id": r.get("id"),
            "receivedAt": r.get("receivedAt"),
            "type": p.get("type"),
            "page": (p.get("page") or {}).get("title"),
            "state": d.get("state"),
            "attempts": d.get("attempts"),
            "issueUrl": d.get("issueUrl", ""),
            "lastError": d.get("lastError", ""),
        })
    return h.send_json({"count": len(slim), "pending": count_pending(), "records": slim})


def route_get_feedback_retry(h):
    n = retry_pending_once()
    return h.send_json({"ok": True, "resent": n, "pending": count_pending()})


def route_post_feedback(h):
    """反馈提交：落盘 + 尝试即时转发（转发失败不算用户失败，后台会自动补发）。"""
    try:
        length = int(h.headers.get("Content-Length") or 0)
    except ValueError:
        length = 0
    if length <= 0:
        return h.send_json({"ok": False, "error": "empty_body"}, 400)
    if length > MAX_BODY_BYTES:
        return h.send_json({"ok": False, "error": "payload_too_large"}, 413)
    try:
        body = h.rfile.read(length)
    except Exception as e:
        return h.send_json({"ok": False, "error": "read_failed: %s" % e}, 400)
    try:
        status, resp = handle_feedback_post(body, h.client_address[0])
    except Exception as e:
        status, resp = 500, {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}
    return h.send_json(resp, status)


# === core: 门户聚合（第3步迁入 portal-core：/api/home、/api/data → /api/portal/home）===

def route_get_data(h):
    return h.send_json(collect_learn_data())


def route_get_home(h):
    return h.send_json(collect_home_data())


# —— 设置页（架构 v2 第 5 步）：技能开关 + 孩子档案 + 主题 + data-root ——
SETTINGS_FILE = os.path.join(CORE_DATA, "config.json")
SETTINGS_FIELDS = ("childName", "school", "grade", "className", "semester", "theme")


def list_skills():
    """扫描技能目录，返回 [{id, url}]（有 skill.json 且声明 url 的技能）。"""
    out = []
    if os.path.isdir(SKILLS_DIR):
        for name in sorted(os.listdir(SKILLS_DIR)):
            meta_path = os.path.join(SKILLS_DIR, name, "skill.json")
            if not os.path.isfile(meta_path):
                continue
            try:
                with open(meta_path, encoding="utf-8") as f:
                    meta = json.load(f)
            except (ValueError, OSError):
                continue
            url = str(meta.get("url") or "").strip().strip("/")
            if not url:
                continue
            out.append({"id": name, "url": url})
    return out


def collect_settings():
    cfg = load_json(SETTINGS_FILE) or {}
    disabled = set(cfg.get("disabled_skills") or [])
    skills = list_skills()
    for s in skills:
        s["enabled"] = s["url"] not in disabled
    return {
        "ok": True,
        "config": {k: cfg.get(k, "") for k in SETTINGS_FIELDS},
        "dataRoot": str(data_paths.data_root()),
        "skills": skills,
    }


def route_get_settings(h):
    return h.send_json(collect_settings())


def handle_settings_post(raw_body):
    try:
        raw = json.loads(raw_body.decode("utf-8", "replace")) if raw_body else {}
    except Exception:
        return 400, {"ok": False, "error": "bad_json"}
    cfg = load_json(SETTINGS_FILE) or {}
    for k in SETTINGS_FIELDS:
        if k in raw and isinstance(raw.get(k), str):
            cfg[k] = raw[k][:200]
    if "disabled_skills" in raw and isinstance(raw.get("disabled_skills"), list):
        cfg["disabled_skills"] = [str(x)[:64] for x in raw["disabled_skills"]]
    write_json(SETTINGS_FILE, cfg)
    return 200, {"ok": True, "config": cfg}


def route_post_settings(h):
    try:
        length = int(h.headers.get("Content-Length") or 0)
    except ValueError:
        length = 0
    if length <= 0 or length > MAX_BODY_BYTES:
        return h.send_json({"ok": False, "error": "empty_body"}, 400)
    try:
        body = h.rfile.read(length)
    except Exception as e:
        return h.send_json({"ok": False, "error": "read_failed: %s" % e}, 400)
    status, resp = handle_settings_post(body)
    return h.send_json(resp, status)


# === subject-chinese / subject-math: 作业卡（第3步已移动到两个学科技能的 api.py）===
# route_get_homework / route_post_homework / route_post_homework_upload 连同
# collect_homework_data / handle_homework_post / handle_homework_upload 已移动到
# .trae/skills/subject-chinese/api.py 与 .trae/skills/subject-math/api.py（移动，不是复制），
# 由下面的技能 api.py 自动注册机制挂回注册表（新命名空间 + 旧路径兼容）。

# === english-class / subject-school-english（第3步已移动到各自技能的 api.py）===
# route_get_class_data + collect_class_data → .trae/skills/english-class/api.py
# route_get_school_data + collect_school_data → .trae/skills/subject-school-english/api.py

# === home-library: 家庭图书馆（第3步 → /api/lib/...）===

def route_get_library(h):
    return h.send_json(collect_library_data())


def route_post_library(h):
    try:
        length = int(h.headers.get("Content-Length") or 0)
    except ValueError:
        length = 0
    if length <= 0 or length > MAX_BODY_BYTES:
        return h.send_json({"ok": False, "error": "empty_body"}, 400)
    try:
        body = h.rfile.read(length)
    except Exception as e:
        return h.send_json({"ok": False, "error": "read_failed: %s" % e}, 400)
    status, resp = handle_library_post(body)
    return h.send_json(resp, status)


def route_post_library_upload(h):
    try:
        length = int(h.headers.get("Content-Length") or 0)
    except ValueError:
        length = 0
    if length <= 0:
        return h.send_json({"ok": False, "error": "空请求"}, 400)
    if length > LIB_BODY_LIMIT:
        return h.send_json({"ok": False, "error": "照片太大（上限 30MB）"}, 413)
    try:
        body = h.rfile.read(length)
    except Exception as e:
        return h.send_json({"ok": False, "error": "读取失败: %s" % e}, 400)
    fields = parse_multipart(h.headers.get("Content-Type", ""), body)
    if not fields:
        return h.send_json({"ok": False, "error": "无法解析表单"}, 400)
    try:
        result = handle_library_upload(fields)
    except ValueError as e:
        return h.send_json({"ok": False, "error": str(e)}, 400)
    except Exception as e:
        return h.send_json({"ok": False, "error": "%s: %s" % (type(e).__name__, e)}, 500)
    return h.send_json(result)


# === competition: 比赛（第3步 → /api/comp/...）===

def route_get_competition(h):
    return h.send_json(collect_competition())


def route_post_competition(h):
    try:
        length = int(h.headers.get("Content-Length") or 0)
    except ValueError:
        length = 0
    if length <= 0 or length > MAX_BODY_BYTES:
        return h.send_json({"ok": False, "error": "empty_body"}, 400)
    try:
        body = h.rfile.read(length)
    except Exception as e:
        return h.send_json({"ok": False, "error": "read_failed: %s" % e}, 400)
    status, resp = handle_competition_post(body)
    return h.send_json(resp, status)


# === xiaoshan-art-archive: 画作档案（第3步 → /api/art/...）===

def route_post_art_upload(h):
    try:
        length = int(h.headers.get("Content-Length") or 0)
    except ValueError:
        length = 0
    if length <= 0:
        return h.send_json({"ok": False, "error": "空请求"}, 400)
    if length > ART_BODY_LIMIT:
        return h.send_json({"ok": False, "error": "文件太大（上限 30MB）"}, 413)
    try:
        body = h.rfile.read(length)
    except Exception as e:
        return h.send_json({"ok": False, "error": "读取失败: %s" % e}, 400)
    fields = parse_multipart(h.headers.get("Content-Type", ""), body)
    if not fields:
        return h.send_json({"ok": False, "error": "无法解析表单"}, 400)
    try:
        record = handle_art_upload(fields)
    except ValueError as e:
        return h.send_json({"ok": False, "error": str(e)}, 400)
    except Exception as e:
        return h.send_json({"ok": False, "error": "%s: %s" % (type(e).__name__, e)}, 500)
    return h.send_json({"ok": True, "record": record})


# === core: 统一打卡服务（架构 v2 第 3 步新增，纯增量）===
# ----------------------------------------------------------------------
# 单一落盘文件 <data-root>/core/data/checkins.json，记录模型 {skill, key, date, v, ts}：
#   skill = 技能 url（chinese / math / class / school / reading / tracker / homework…）
#   key   = 内容块 id（作业项 id、<单元id>:<板块id>、内容组 id、习惯标签 id……）
#   v     = 1 已打卡 / 0 取消（墓碑保留，取消动作才能同步到别的设备）
#   ts    = 毫秒时间戳，同一 skill+key+date 取新；无 ts 旧记录按 ts=0 并集不丢
# 合并走 portal-core 的 Store（merge="ts" 语义，全仓唯一一份同步逻辑）。
# 目录不存在时读空、写时创建（Store 自带）；现有 6 条旧打卡路由行为不变。
# 磁盘形态：{"updated": iso, "records": {skill: {key: {date: {"v":..,"ts":.., 扩展字段…}}}}}
# 扩展字段（note / chapters / items 等）随记录一起存，GET 时平铺带出。
# ----------------------------------------------------------------------

_checkins_store = None
_checkins_lock = threading.Lock()


def checkins_store():
    """core 命名空间的 Store（<data-root>/core/data/），懒加载。"""
    global _checkins_store
    if _checkins_store is None:
        _checkins_store = Store(data_paths.namespace_dir("core") / "data")
    return _checkins_store


def checkins_doc():
    """读整份打卡文档；不存在或损坏时读成空文档（目录不存在同样读空）。"""
    doc = checkins_store().read("checkins")
    if not isinstance(doc, dict):
        doc = {}
    recs = doc.get("records")
    if not isinstance(recs, dict):
        recs = {}
    doc["records"] = recs
    return doc


def checkins_by_skill(skill):
    """把 core checkins 里某 skill 的记录转成旧的嵌套形状 {date: {key: bool}}。

    供 class / school 等页面的 collect_*_data 复用：页面里的 RECORDS 结构不用改，
    打卡却已经统一走 /api/checkins（架构 v2 第 3 步），历史与新打卡不再断裂。
    """
    out = {}
    keys = (checkins_doc().get("records") or {}).get(skill) or {}
    for key, days in keys.items():
        if not isinstance(days, dict):
            continue
        for date, rec in days.items():
            if not isinstance(rec, dict):
                continue
            out.setdefault(date, {})[key] = bool(rec.get("v"))
    return out


def checkins_flatten(doc, skills=None, date_from="", date_to=""):
    """把嵌套的 records 平铺成 [{skill, key, date, v, ts, ...}]，可按 skill/日期区间过滤。"""
    out = []
    for sk in sorted(doc["records"]):
        if skills and sk not in skills:
            continue
        keys = doc["records"][sk]
        if not isinstance(keys, dict):
            continue
        for key in sorted(keys):
            days = keys[key]
            if not isinstance(days, dict):
                continue
            for day in sorted(days):
                if not re.match(r"^\d{4}-\d{2}-\d{2}$", str(day)):
                    continue
                if date_from and day < date_from:
                    continue
                if date_to and day > date_to:
                    continue
                rec = days[day]
                if not isinstance(rec, dict):
                    continue
                row = {"skill": sk, "key": key, "date": day}
                for k, v in rec.items():
                    if k not in ("v", "ts"):
                        row[k] = v
                row["v"] = 1 if rec.get("v") else 0
                try:
                    row["ts"] = int(rec.get("ts") or 0)
                except (TypeError, ValueError):
                    row["ts"] = 0
                out.append(row)
    return out


def _checkins_skill_filter(raw):
    """?skill= 支持单个或逗号分隔多个；空 = 不过滤。返回 None 或集合。"""
    raw = str(raw or "").strip()
    if not raw:
        return None
    out = set()
    for piece in raw.split(","):
        tok = _safe_token(piece, "A-Za-z0-9_-")[:32]
        if tok:
            out.add(tok)
    return out or None


def route_get_checkins(h):
    doc = checkins_doc()
    date_from = _safe_token(h.query_value("from"), "0-9-")[:10]
    date_to = _safe_token(h.query_value("to"), "0-9-")[:10]
    records = checkins_flatten(doc, _checkins_skill_filter(h.query_value("skill")),
                               date_from, date_to)
    return h.send_json({"ok": True, "updated": doc.get("updated", ""), "records": records})


def _checkin_extra_fields(it):
    """打卡记录允许带的扩展字段（note / chapters / items 等），白名单化后随记录一起存。"""
    extras = {}
    for k, v in it.items():
        if k in ("skill", "key", "date", "v", "ts"):
            continue
        kk = _safe_token(k, "A-Za-z0-9_")[:20]
        if not kk:
            continue
        if isinstance(v, bool) or isinstance(v, (int, float)):
            extras[kk] = v
        elif isinstance(v, str):
            extras[kk] = v[:500]
        elif isinstance(v, (list, dict)):
            try:
                extras[kk] = json.loads(json.dumps(v, ensure_ascii=False))  # 深拷贝 + 只留可 JSON 化的
            except (TypeError, ValueError):
                continue
        if len(extras) >= 8:
            break
    return extras


def _checkins_upsert_items(items):
    """把 [{skill, key, date, v, ts, ...}] 合并进 checkins 并落盘。返回 (status, obj)。

    这是打卡的**唯一落盘入口**：handle_checkins_post 与旧打卡路由（tracker / homework
    checkins / class checkin / school checkin）都走这里，保证所有打卡最终落到同一份
    core checkins（架构 v2 彻底切换后，旧 data 文件删除，不再有第二份打卡数据）。
    """
    partial = {"records": {}}
    posted_skills = set()
    for it in items:
        if not isinstance(it, dict):
            continue
        skill = _safe_token(it.get("skill"), "A-Za-z0-9_-")[:32]
        key = _safe_token(it.get("key"), "A-Za-z0-9_:-")[:64]
        date_val = _safe_token(it.get("date"), "0-9-")[:10]
        if not skill or not key or not re.match(r"^\d{4}-\d{2}-\d{2}$", date_val or ""):
            continue
        try:
            ts = int(it.get("ts") or 0)
        except (TypeError, ValueError):
            ts = 0
        if not ts:
            ts = int(time.time() * 1000)
        node = {"v": 1 if it.get("v") else 0, "ts": ts}
        node.update(_checkin_extra_fields(it))
        partial["records"].setdefault(skill, {}).setdefault(key, {})[date_val] = node
        posted_skills.add(skill)
    if not posted_skills:
        return 400, {"ok": False, "error": "没有一条合法的打卡记录（需要 skill/key/date）"}
    with _checkins_lock:
        existing = checkins_doc()
        merged = _portal_storage.merge_ts(existing, partial)
        merged["updated"] = now_iso()
        checkins_store().write("checkins", merged, merge="overwrite")
    return 200, {
        "ok": True,
        "updated": merged["updated"],
        "records": checkins_flatten(merged, posted_skills),
    }


def handle_checkins_post(raw_body):
    """批量 upsert：body 是 {"records": [{skill, key, date, v, ts, ...}, ...]}，
    或单条 {"skill":.., "key":.., "date":.., "v":.., "ts":..}。
    同一 skill+key+date 按 ts 取新（merge="ts"），v:0 墓碑照常参与取新。"""
    try:
        raw = json.loads(raw_body.decode("utf-8", "replace")) if raw_body else {}
    except Exception:
        return 400, {"ok": False, "error": "bad_json"}
    if not isinstance(raw, dict):
        return 400, {"ok": False, "error": "bad_body"}
    items = raw.get("records")
    if items is None and (raw.get("skill") or raw.get("key")):
        items = [raw]
    if not isinstance(items, list) or not items:
        return 400, {"ok": False, "error": "records 必须是非空数组"}
    return _checkins_upsert_items(items)


def route_post_checkins(h):
    try:
        length = int(h.headers.get("Content-Length") or 0)
    except ValueError:
        length = 0
    if length <= 0:
        return h.send_json({"ok": False, "error": "空请求"}, 400)
    if length > MAX_BODY_BYTES:
        return h.send_json({"ok": False, "error": "请求太大"}, 413)
    try:
        body = h.rfile.read(length)
    except Exception as e:
        return h.send_json({"ok": False, "error": "读取失败: %s" % e}, 400)
    try:
        status, obj = handle_checkins_post(body)
    except Exception as e:
        status, obj = 500, {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}
    return h.send_json(obj, status)


# (HTTP 方法, 路径) -> 处理函数。顺序与上面的分组一致，仅供阅读，匹配只按精确键。
ROUTES = {
    # core: 打卡服务（第3步迁入 portal-core）
    ("GET", "/api/tracker"): route_get_tracker,
    ("POST", "/api/tracker"): route_post_tracker,
    ("GET", "/api/homework/checkins"): route_get_homework_checkins,
    ("POST", "/api/homework/checkins"): route_post_homework_checkins,
    ("POST", "/api/class/checkin"): route_post_class_checkin,
    ("POST", "/api/school/checkin"): route_post_school_checkin,
    # core: 语音服务（第3步迁入 portal-core）
    ("GET", "/api/voice"): route_get_voice,
    ("GET", "/api/voice/status"): route_get_voice_status,
    ("POST", "/api/voice"): route_post_voice,
    ("POST", "/api/voice/text"): route_post_voice_text,
    ("POST", "/api/voice/delete"): route_post_voice_delete,
    # core: TTS 配音状态（第3步迁入 portal-core）
    ("GET", "/api/tts/status"): route_get_tts_status,
    # core: 反馈服务（第3步迁入 portal-core）
    ("GET", "/api/feedback/config"): route_get_feedback_config,
    ("GET", "/api/feedback/status"): route_get_feedback_status,
    ("GET", "/api/feedback/retry"): route_get_feedback_retry,
    ("POST", "/api/feedback"): route_post_feedback,
    # core: 门户聚合（第3步迁入 portal-core）
    ("GET", "/api/data"): route_get_data,
    ("GET", "/api/home"): route_get_home,
    # core: 设置页（架构 v2 第 5 步：技能开关 + 孩子档案 + 主题 + data-root）
    ("GET", "/api/settings"): route_get_settings,
    ("POST", "/api/settings"): route_post_settings,
    # core: 统一打卡服务（架构 v2 第 3 步新增，纯增量）
    ("GET", "/api/checkins"): route_get_checkins,
    ("POST", "/api/checkins"): route_post_checkins,
    # subject-chinese / subject-math / english-class / subject-school-english 的
    # 作业卡与内容路由已移动到各技能 api.py，启动时由 load_skill_apis() 挂回
    # （新命名空间 /api/<url>/... + 旧路径 legacy 兼容）。
    # home-library: 家庭图书馆
    ("GET", "/api/library"): route_get_library,
    ("POST", "/api/library"): route_post_library,
    ("POST", "/api/library/upload"): route_post_library_upload,
    # competition: 比赛
    ("GET", "/api/competition"): route_get_competition,
    ("POST", "/api/competition"): route_post_competition,
    # xiaoshan-art-archive: 画作档案
    ("POST", "/api/art/upload"): route_post_art_upload,
}


def ensure_data_dirs():
    """兜底：把 data-root 里需要的目录建好（正常由 setup.py 初始化，这里防止首次直接启动时报错）。"""
    for d in (GH_DATA, LEARN_DATA, BAG_DATA, ART_DATA, ART_IMAGES, ART_AUDIO,
              LIB_DATA, LIB_IMAGES, COMP_DATA, TEXTBOOKS_DIR,
              VOICE_AUDIO, HOMEWORK_MEDIA, LIB_COVERS, FEEDBACK_DIR, FEEDBACK_INBOX):
        os.makedirs(d, exist_ok=True)


def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def now_iso():
    return datetime.now(CN_TZ).isoformat(timespec="seconds")


def collect_dir(dir_path):
    items = []
    if os.path.isdir(dir_path):
        for name in sorted(os.listdir(dir_path)):
            if name.endswith(".json"):
                item = load_json(os.path.join(dir_path, name))
                if item is not None:
                    items.append(item)
    return items


def collect_learn_data():
    data_dir = os.path.join(LEARN_DATA)
    return {
        "config": load_json(os.path.join(data_dir, "config.json")) or {},
        "days": collect_dir(os.path.join(data_dir, "days")),
        "weekly": collect_dir(os.path.join(data_dir, "weekly")),
    }


def collect_home_data():
    # 架构 v2 第 3 步：config/activities 迁到 core，booklist 迁到 reading
    return {
        "config": load_json(os.path.join(CORE_DATA, "config.json")) or {},
        "activities": load_json(os.path.join(CORE_DATA, "activities.json")) or {},
        "booklist": load_json(os.path.join(READING_DATA, "booklist.json")) or {},
    }


# collect_class_data 已随 GET /api/class/data 移动到 .trae/skills/english-class/api.py
# （移动，不是复制；数据读写路径不变）。本文件保留 handle_class_checkin ——
# POST /api/class/checkin 属 core 打卡 6 条之一，切换段才统一进 /api/checkins。

def handle_class_checkin(raw_body):
    """记录某天某个打卡点的状态。

    打卡点是知识点板块（key = "<单元id>:<板块id>"，如 l2-u2:items 物品词汇），
    老页面传的四维 dim（listen/speak/read/write）也照收，历史记录不受影响。
    """
    try:
        raw = json.loads(raw_body.decode("utf-8", "replace")) if raw_body else {}
    except Exception:
        return 400, {"ok": False, "error": "bad_json"}
    date_val = _safe_token(raw.get("date"), "0-9-")
    if not date_val:
        return 400, {"ok": False, "error": "缺少日期"}
    key = _safe_token(raw.get("key"), "A-Za-z0-9_:-")[:64]
    if not key:
        key = _safe_token(raw.get("dim"), "a-z")[:64]
    if not key:
        return 400, {"ok": False, "error": "缺少打卡项"}
    done = bool(raw.get("done"))
    _checkins_upsert_items([{"skill": "class", "key": key, "date": date_val,
                             "v": 1 if done else 0, "ts": int(time.time() * 1000)}])
    return 200, {"ok": True, "date": date_val, "key": key, "done": done}


# collect_school_data 已随 GET /api/school/data 移动到
# .trae/skills/subject-school-english/api.py（移动，不是复制；数据读写路径不变）。
# 本文件保留 handle_school_checkin —— POST /api/school/checkin 属 core 打卡 6 条之一。

def handle_school_checkin(raw_body):
    """记录某天某个内容组的学校英语打卡状态。

    打卡点＝内容组：key 是 units[].groups[].id（没写 groups 时就是材料 id，如 v1），
    老页面传的三维 task（listen/watch/speak）也照收，历史记录不受影响。
    """
    try:
        raw = json.loads(raw_body.decode("utf-8", "replace")) if raw_body else {}
    except Exception:
        return 400, {"ok": False, "error": "bad_json"}
    date_val = _safe_token(raw.get("date"), "0-9-")
    if not date_val:
        return 400, {"ok": False, "error": "缺少日期"}
    key = _safe_token(raw.get("key"), "A-Za-z0-9_:-")[:64]
    if not key:
        key = _safe_token(raw.get("task"), "a-z")[:64]
    if not key:
        return 400, {"ok": False, "error": "缺少打卡项"}
    done = bool(raw.get("done"))
    _checkins_upsert_items([{"skill": "school", "key": key, "date": date_val,
                             "v": 1 if done else 0, "ts": int(time.time() * 1000)}])
    return 200, {"ok": True, "date": date_val, "key": key, "done": done}


# 作业卡的 collect_homework_data / handle_homework_post / handle_homework_upload
# 已移动到 .trae/skills/subject-chinese/api.py 与 subject-math/api.py（移动，不是复制；
# 数据读写路径不变，仍读写 <data-root>/web/data/homework.json，数据搬家在切换段）。
# 上面的 HOMEWORK_FILE / HOMEWORK_MEDIA 常量保留：TTS_SOURCES 与 ensure_data_dirs 仍在用。


# ======================================================================
# 家庭图书馆：书目 + 封面照片
# ======================================================================

def collect_library_data():
    """家庭图书馆：孩子姓名 + 书架配置 + 书目。"""
    cfg = load_json(os.path.join(CORE_DATA, "config.json")) or {}
    shelves = load_json(LIB_SHELVES) or {}
    data = load_json(LIB_BOOKS) or {}
    return {
        "childName": cfg.get("childName", ""),
        "levelNote": shelves.get("levelNote", ""),
        "shelves": shelves.get("shelves") or [],
        "books": data.get("books") or [],
        "updated": data.get("updated", ""),
    }


def _norm_book(raw):
    """白名单化一本书的字段，避免网页端塞进任意结构。"""
    if not isinstance(raw, dict):
        return None
    title = _sanitize_text(raw.get("title"), 120)
    if not title:
        return None

    loc_raw = raw.get("location") if isinstance(raw.get("location"), dict) else None
    location = None
    if loc_raw and loc_raw.get("shelf"):
        try:
            level = int(loc_raw.get("level") or 1)
        except Exception:
            level = 1
        location = {"shelf": _safe_token(loc_raw.get("shelf"), "A-Za-z0-9_-"), "level": max(1, level)}

    def _list(key, limit, maxlen=30):
        vals = raw.get(key)
        if not isinstance(vals, list):
            return []
        return [_sanitize_text(v, maxlen) for v in vals if _sanitize_text(v, maxlen)][:limit]

    return {
        "id": _safe_token(raw.get("id"), "A-Za-z0-9_-"),
        "title": title,
        "author": _sanitize_text(raw.get("author"), 80),
        "publisher": _sanitize_text(raw.get("publisher"), 80),
        "intro": _sanitize_text(raw.get("intro"), 1200),
        "tags": _list("tags", 12),
        "topics": _list("topics", 12),
        "suitableFor": _sanitize_text(raw.get("suitableFor"), 60),
        "cover": _sanitize_text(raw.get("cover"), 300),
        "sources": _list("sources", 5, 300),
        "location": location,
        "readStatus": _sanitize_text(raw.get("readStatus"), 20) or "unread",
        "addedAt": _sanitize_text(raw.get("addedAt"), 20),
        "source": _sanitize_text(raw.get("source"), 40),
        "infoStatus": _sanitize_text(raw.get("infoStatus"), 20) or "待补充",
    }


def handle_library_post(raw_body):
    """图书馆增删改：op 取值 add / update / delete，返回更新后的完整 books。"""
    try:
        raw = json.loads(raw_body.decode("utf-8", "replace")) if raw_body else {}
    except Exception:
        return 400, {"ok": False, "error": "bad_json"}
    op = raw.get("op")
    data = load_json(LIB_BOOKS) or {}
    books = list(data.get("books") or [])
    saved = None

    if op == "delete":
        bid = _safe_token(raw.get("id"), "A-Za-z0-9_-")
        books = [b for b in books if str(b.get("id")) != bid]
    elif op in ("add", "update"):
        book = _norm_book(raw.get("book"))
        if not book:
            return 400, {"ok": False, "error": "缺少书名"}
        if op == "add" or not book["id"]:
            nums = [int(str(b.get("id"))[1:]) for b in books
                    if re.fullmatch(r"[Bb]\d+", str(b.get("id", "")))]
            book["id"] = "B%03d" % (max(nums, default=0) + 1)
        if not book["addedAt"]:
            book["addedAt"] = datetime.now(CN_TZ).strftime("%Y-%m-%d")
        if not book["source"]:
            book["source"] = "手动录入"
        replaced = False
        for i, b in enumerate(books):
            if str(b.get("id")) == book["id"]:
                books[i] = book
                replaced = True
                break
        if not replaced:
            books.append(book)
        saved = book
    else:
        return 400, {"ok": False, "error": "unknown_op"}

    data["books"] = books
    data["updated"] = datetime.now(CN_TZ).strftime("%Y-%m-%d")
    data.setdefault("note", "location 为 null 表示还没有归架；infoStatus 为「待补充」表示出版社/简介待补充")
    write_json(LIB_BOOKS, data)
    return 200, {"ok": True, "books": books, "book": saved}


def handle_library_upload(fields):
    """保存图书封面照片，返回相对技能根目录的 URL。"""
    img = fields.get("image")
    if not img or not img.get("data"):
        raise ValueError("缺少图片")
    data = img["data"]

    ext = ".jpg"
    if data[:4] == b"\x89PNG":
        ext = ".png"
    elif data[:2] == b"\xff\xd8":
        ext = ".jpg"
    elif data[:6] in (b"GIF87a", b"GIF89a"):
        ext = ".gif"
    elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        ext = ".webp"

    os.makedirs(LIB_COVERS, exist_ok=True)
    name = "cover_%s_%s%s" % (datetime.now(CN_TZ).strftime("%Y%m%d%H%M%S"), uuid.uuid4().hex[:6], ext)
    with open(os.path.join(LIB_COVERS, name), "wb") as f:
        f.write(data)
    return {"ok": True, "url": "images/covers/" + name}


# ======================================================================
# 画作档案：网页端上传（图片 + 说明 + 录音）
# ======================================================================

ART_BODY_LIMIT = 30 * 1024 * 1024  # 画作上传上限（含图片/录音）


def parse_multipart(content_type, body):
    """解析 multipart/form-data，返回 {字段名: {"filename": str|None, "data": bytes}}。"""
    boundary = None
    for piece in (content_type or "").split(";"):
        piece = piece.strip()
        if piece.lower().startswith("boundary="):
            boundary = piece.split("=", 1)[1].strip('"')
    if not boundary:
        return {}
    delim = ("--" + boundary).encode("utf-8")
    result = {}
    for part in body.split(delim):
        part = part.strip(b"\r\n")
        if not part or part == b"--":
            continue
        if b"\r\n\r\n" in part:
            head, data = part.split(b"\r\n\r\n", 1)
        else:
            head, data = part, b""
        data = data.rstrip(b"\r\n")
        name = None
        filename = None
        for line in head.decode("utf-8", "replace").split("\r\n"):
            if line.lower().startswith("content-disposition"):
                for item in line.split(";"):
                    item = item.strip()
                    if item.lower().startswith("name="):
                        name = item.split("=", 1)[1].strip('"')
                    elif item.lower().startswith("filename="):
                        filename = item.split("=", 1)[1].strip('"')
        if name:
            result[name] = {"filename": filename, "data": data}
    return result


def _field_text(fields, key):
    val = (fields.get(key) or {}).get("data") or b""
    try:
        return val.decode("utf-8", "replace").strip()
    except Exception:
        return ""


def next_art_id():
    idx = load_json(os.path.join(ART_DATA, "index.json")) or []
    nums = []
    for r in idx:
        if isinstance(r, dict) and str(r.get("id", "")).isdigit():
            nums.append(int(r["id"]))
    return max(nums, default=0) + 1


def handle_art_upload(fields):
    image = fields.get("image")
    if not image or not image.get("data"):
        raise ValueError("缺少图片")
    data = image["data"]

    ext = ".jpg"
    if data[:4] == b"\x89PNG":
        ext = ".png"
    elif data[:2] == b"\xff\xd8":
        ext = ".jpg"
    elif data[:6] in (b"GIF87a", b"GIF89a"):
        ext = ".gif"
    elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        ext = ".webp"

    description = _field_text(fields, "description")
    title = _field_text(fields, "title")
    date_val = _field_text(fields, "date")

    art_id = next_art_id()
    sid = "%03d" % art_id
    os.makedirs(os.path.join(ART_IMAGES), exist_ok=True)
    os.makedirs(os.path.join(ART_AUDIO), exist_ok=True)

    img_name = "%s_upload%s" % (sid, ext)
    with open(os.path.join(ART_IMAGES, img_name), "wb") as f:
        f.write(data)

    audio_rel = None
    audio_field = fields.get("audio")
    if audio_field and audio_field.get("data"):
        audio_data = audio_field["data"]
        afn = (audio_field.get("filename") or "").lower()
        aext = ".webm"
        if afn.endswith(".wav"):
            aext = ".wav"
        elif afn.endswith(".m4a") or afn.endswith(".mp4") or afn.endswith(".aac"):
            aext = ".m4a"
        elif afn.endswith(".mp3"):
            aext = ".mp3"
        elif afn.endswith(".ogg") or afn.endswith(".oga"):
            aext = ".ogg"
        audio_name = "%s_upload%s" % (sid, aext)
        with open(os.path.join(ART_AUDIO, audio_name), "wb") as f:
            f.write(audio_data)
        audio_rel = "audio/" + audio_name

    # 画作描述现在多半先用「语音记录」组件录好并识别成文字（音频已存在 data/voice/ 下），
    # 此时只把地址挂到画作记录上，不重复存一遍同一段语音。
    voice_id = _field_text(fields, "voiceId")
    if not audio_rel:
        vurl = _field_text(fields, "voiceUrl")
        if vurl.startswith("/data/voice/"):
            audio_rel = vurl

    record = {
        "id": sid,
        "date": date_val or datetime.now(CN_TZ).strftime("%Y-%m-%d"),
        "title": title or ("新画作 " + sid),
        "image": "images/" + img_name,
        "audio": audio_rel,
        "voiceId": voice_id or None,
        "description": description,
        "characters": [],
        "tags": [],
    }

    idx = load_json(os.path.join(ART_DATA, "index.json")) or []
    idx.append(record)
    write_json(os.path.join(ART_DATA, "index.json"), idx)
    return record


# ======================================================================
# 比赛（competition 技能）：把通知里的要求读给页面，记录与打卡落该技能自己的 data/
# ======================================================================

def collect_competition():
    """比赛页要的全部内容：孩子信息 + 活动通知（含老师/邮箱，只从 data/ 读）+ 报名与打卡记录。"""
    cfg = load_json(COMP_CONFIG) or {}
    return {
        "ok": True,
        "childName": cfg.get("childName", ""),
        "grade": cfg.get("grade", ""),
        "className": cfg.get("className", ""),
        "notice": load_json(COMP_NOTICE) or dflt_notice(),
        "state": comp_state(),
    }


def dflt_notice():
    """还没有 data/notice.json 时给页面一个空壳，页面会提示去整理通知（不编内容）。"""
    return {"title": "", "categories": [], "notes": [],
            "_说明": "把学校发的比赛通知按 data-templates/notice.json 的结构整理进 data/notice.json。"}


def comp_state():
    st = load_json(COMP_STATE) or {}
    return {
        "enrollment": st.get("enrollment") or {},
        "enrollmentUpdated": int(st.get("enrollmentUpdated") or 0),
        "records": st.get("records") or {},
        "updated": st.get("updated") or "",
    }


def handle_competition_post(raw_body):
    """写入报名与打卡：同一「项+天」按 ts 取新合并，取消也留一条 v:0（跨设备同步）。"""
    try:
        raw = json.loads(raw_body.decode("utf-8", "replace")) if raw_body else {}
    except Exception:
        return 400, {"ok": False, "error": "bad_json"}
    if not isinstance(raw, dict):
        return 400, {"ok": False, "error": "bad_body"}
    with COMP_LOCK:
        st = comp_state()
        # 1) 报了哪几项（每类最多一项）：比 enrollmentUpdated 时间戳，新的那份为准
        try:
            ts_new = int(raw.get("enrollmentUpdated") or 0)
        except (TypeError, ValueError):
            ts_new = 0
        enroll = raw.get("enrollment")
        if isinstance(enroll, dict) and ts_new >= int(st.get("enrollmentUpdated") or 0):
            clean = {}
            for k, v in enroll.items():
                kk = _safe_token(k, "A-Za-z0-9_-")[:32]
                vv = _safe_token(v, "A-Za-z0-9_-")[:32]
                if kk and vv:
                    clean[kk] = vv
            st["enrollment"] = clean
            st["enrollmentUpdated"] = ts_new
        # 2) 备赛打卡：逐 项+天 按 ts 取新
        recs = raw.get("records")
        if isinstance(recs, dict):
            for key, days in recs.items():
                if not isinstance(days, dict):
                    continue
                kk = _safe_token(key, "A-Za-z0-9_:-")[:64]
                if not kk:
                    continue
                cur = st["records"].setdefault(kk, {})
                for day, rec in days.items():
                    dd = _safe_token(day, "0-9-")
                    if len(dd) != 10 or not isinstance(rec, dict):
                        continue
                    try:
                        datetime.strptime(dd, "%Y-%m-%d")
                    except ValueError:
                        continue          # 只收真实存在的日期
                    try:
                        ts = int(rec.get("ts") or 0)
                    except (TypeError, ValueError):
                        ts = 0
                    if not ts:
                        ts = int(time.time() * 1000)
                    old = cur.get(dd)
                    if old and int(old.get("ts") or 0) > ts:
                        continue          # 服务器上这份更新，保留
                    cur[dd] = {"v": 1 if rec.get("v") else 0, "ts": ts}
                if not cur:
                    st["records"].pop(kk, None)   # 全是脏数据就别留空壳
        st["updated"] = now_iso()
        write_json(COMP_STATE, st)
    return 200, {"ok": True, "state": st}


# ======================================================================
# 通用语音记录：录音 / 上传 -> 落盘 -> 自动识别成文字 -> 文字与语音一起归档
# ======================================================================

def voice_scope_clean(val):
    """场景名（页面用来区分是谁录的，如 tracker-reading / homework-xxx）只留安全字符。"""
    s = re.sub(r"[^A-Za-z0-9_.:-]", "", str(val or ""))
    return s.strip(".:-")[:60]


def _voice_ext(filename, data):
    """按文件头判断音频格式，拿不准再看文件名后缀（手机录音常见 m4a / mp4 / webm）。"""
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


def voice_records(scope="", date_val="", limit=200):
    """按场景/日期取语音记录（新的在前）。scope 支持前缀匹配，如 tracker 命中 tracker-reading。"""
    idx = load_json(VOICE_INDEX) or []
    out = []
    for rec in idx:
        if not isinstance(rec, dict):
            continue
        sc = str(rec.get("scope") or "")
        if scope and not (sc == scope or sc.startswith(scope + ":") or sc.startswith(scope + "-")):
            continue
        if date_val and str(rec.get("date") or "") != date_val:
            continue
        out.append(rec)
    out.sort(key=lambda r: r.get("ts") or 0, reverse=True)
    try:
        limit = max(1, min(1000, int(limit)))
    except Exception:
        limit = 200
    return out[:limit]


def handle_voice_upload(fields):
    """保存一条语音记录：音频落盘 + 自动识别成文字，文字和音频一起进索引。"""
    audio_field = fields.get("audio")
    if not audio_field or not audio_field.get("data"):
        raise ValueError("缺少录音")
    data = audio_field["data"]

    scope = voice_scope_clean(_field_text(fields, "scope")) or "misc"
    date_val = re.sub(r"[^0-9-]", "", _field_text(fields, "date")) or datetime.now(CN_TZ).strftime("%Y-%m-%d")
    lang = _field_text(fields, "lang") or "zh"
    typed = _field_text(fields, "text")[:VOICE_TEXT_MAX]
    asr_mode = (_field_text(fields, "asr") or "").lower()

    meta = {}
    raw_meta = _field_text(fields, "meta")
    if raw_meta:
        try:
            obj = json.loads(raw_meta)
            if isinstance(obj, dict):
                meta = {str(k)[:40]: str(v)[:200] for k, v in list(obj.items())[:20]}
        except Exception:
            meta = {}

    ts = int(time.time() * 1000)
    vid = "v-%s-%s" % (datetime.now(CN_TZ).strftime("%Y%m%d-%H%M%S"), uuid.uuid4().hex[:4])
    ext = _voice_ext(audio_field.get("filename"), data)
    day_dir = os.path.join(VOICE_AUDIO, scope, date_val)
    os.makedirs(day_dir, exist_ok=True)
    path = os.path.join(day_dir, vid + ext)
    with open(path, "wb") as f:
        f.write(data)
    rel = "data/voice/audio/%s/%s/%s%s" % (scope, date_val, vid, ext)

    # 页面已经拿到文字（手写或改过）就不重复跑识别；asr=force/1 可强制识别
    result = {"ok": False, "error": "未识别"}
    need_asr = asr_mode not in ("0", "off", "skip") and (not typed or asr_mode in ("1", "force", "on"))
    if need_asr:
        if asr_engine is None:
            result = {"ok": False, "error": "本机未启用语音识别（缺 faster-whisper）"}
        else:
            result = asr_engine.transcribe(path, lang)

    text = typed or (result.get("text") or "")
    record = {
        "id": vid,
        "scope": scope,
        "date": date_val,
        "ts": ts,
        "createdAt": now_iso(),
        "audio": rel,
        "url": "/" + rel,
        "text": text[:VOICE_TEXT_MAX],
        "asr": (result.get("text") or "")[:VOICE_TEXT_MAX],
        "asrOk": bool(result.get("ok")),
        "asrError": "" if result.get("ok") else str(result.get("error") or "")[:200],
        "lang": result.get("lang") or lang,
        "seconds": result.get("seconds") or 0,
        "model": result.get("model") or "",
        "meta": meta,
    }

    idx = load_json(VOICE_INDEX) or []
    if not isinstance(idx, list):
        idx = []
    idx.append(record)
    write_json(VOICE_INDEX, idx)
    return record


def voice_update_text(vid, text):
    """家长/孩子把识别文字改对：文字改掉，原始识别结果留在 asr 字段里不丢。"""
    vid = str(vid or "").strip()
    if not vid:
        raise ValueError("缺少记录 id")
    idx = load_json(VOICE_INDEX) or []
    for rec in idx:
        if isinstance(rec, dict) and rec.get("id") == vid:
            rec["text"] = str(text or "")[:VOICE_TEXT_MAX]
            rec["updatedAt"] = now_iso()
            write_json(VOICE_INDEX, idx)
            return rec
    raise ValueError("找不到这条语音记录")


def voice_delete(vid):
    """删掉一条语音记录：索引里移除，音频文件一起删（删了就找不回来）。"""
    vid = str(vid or "").strip()
    if not vid:
        raise ValueError("缺少记录 id")
    idx = load_json(VOICE_INDEX) or []
    if not isinstance(idx, list):
        idx = []
    removed = None
    keep = []
    for rec in idx:
        if removed is None and isinstance(rec, dict) and rec.get("id") == vid:
            removed = rec
            continue
        keep.append(rec)
    if removed is None:
        raise ValueError("找不到这条语音记录")
    write_json(VOICE_INDEX, keep)

    # 音频文件：先删记录里记的那份，再按「场景/日期/id」兜底扫一遍同名文件；
    # realpath 限定在 data/voice/audio 之内，索引被改坏也不会误删别处的文件。
    scope = re.sub(r"[^0-9A-Za-z_.:-]", "", str(removed.get("scope") or ""))
    date_val = re.sub(r"[^0-9-]", "", str(removed.get("date") or ""))
    candidates = []
    rel = str(removed.get("audio") or "")
    if rel.startswith("data/voice/audio/"):
        candidates.append(os.path.join(os.path.dirname(GH_DATA), rel))
    if scope and date_val:
        candidates.extend(glob.glob(os.path.join(VOICE_AUDIO, scope, date_val, vid + ".*")))
    base = os.path.realpath(VOICE_AUDIO)
    files_deleted = 0
    for path in candidates:
        real = os.path.realpath(path)
        if not real.startswith(base + os.sep) or not os.path.isfile(real):
            continue
        try:
            os.remove(real)
            files_deleted += 1
        except OSError:
            pass
    # 顺手收掉空的日期/场景目录，别越攒越多空文件夹
    for d in (os.path.join(VOICE_AUDIO, scope, date_val) if scope and date_val else "",
              os.path.join(VOICE_AUDIO, scope) if scope else ""):
        try:
            if d and os.path.isdir(d) and not os.listdir(d):
                os.rmdir(d)
        except OSError:
            pass
    removed = dict(removed)
    removed["audioDeleted"] = files_deleted
    return removed


# ======================================================================
# 英语打卡：录音上传 + 打卡状态
# ======================================================================

def _safe_token(val, allow):
    return re.sub(r"[^" + allow + r"]", "", str(val or ""))


# ======================================================================
# 打卡状态：读书/家务/运动/书单（跨设备同步）
# ======================================================================

def known_tab_ids():
    """activities.json 里配置的标签页 id 集合，用来挡住乱写的 key。"""
    cfg = load_json(os.path.join(CORE_DATA, "activities.json")) or {}
    ids = set()
    for t in (cfg.get("tabs") or []):
        tid = _safe_token((t or {}).get("id"), "A-Za-z0-9_-")
        if tid:
            ids.add(tid)
    return ids


def load_tracker_state():
    state = load_json(TRACKER_STATE)
    if not isinstance(state, dict):
        state = {}
    tabs = state.get("tabs")
    if not isinstance(tabs, dict):
        tabs = {}
    state["tabs"] = tabs
    return state


def _stamp_of(obj):
    try:
        return float((obj or {}).get("ts") or 0)
    except (TypeError, ValueError):
        return 0.0


def merge_stamped(old_map, new_map):
    """按 ts 取新：同一天/同一本书，谁的改动更晚谁的生效，避免两台设备互相覆盖。"""
    out = dict(old_map or {})
    for key, val in (new_map or {}).items():
        if not isinstance(val, dict):
            continue
        old = out.get(key)
        if old is None or _stamp_of(val) >= _stamp_of(old):
            out[key] = val
    return out


def merge_progress(old_map, new_map):
    """书单逐章进度：有时间戳就按时间戳取新；
    两边都没有时间戳（升级到跨设备同步之前的旧数据）时取并集，宁可多留也不丢已读章节。"""
    out = dict(old_map or {})
    for key, val in (new_map or {}).items():
        if not isinstance(val, dict):
            continue
        old = out.get(key)
        if not isinstance(old, dict):
            out[key] = val
            continue
        if _stamp_of(old) == 0 and _stamp_of(val) == 0:
            merged = sorted(set(list(old.get("chapters") or []) + list(val.get("chapters") or [])))
            out[key] = {"chapters": merged, "ts": 0}
        elif _stamp_of(val) >= _stamp_of(old):
            out[key] = val
    return out


def tracker_tab_skill(tab_id):
    """tracker 标签页 id → checkins 的 skill（reading/booklist 都归 reading）。"""
    return "reading" if tab_id in ("reading", "booklist") else tab_id


BOOKLIST_PROGRESS = os.path.join(READING_DATA, "booklist_progress.json")


def load_booklist_progress():
    data = load_json(BOOKLIST_PROGRESS) or {}
    return data.get("progress") or {}


def save_booklist_progress(progress):
    os.makedirs(READING_DATA, exist_ok=True)
    write_json(BOOKLIST_PROGRESS, {"progress": progress, "updated": now_iso()})


def checkins_to_tracker_records(skill, key):
    """checkins 里某 skill+key 的记录 → tracker 的 {date: {done, note, chapters, ts}}。"""
    out = {}
    days = (checkins_doc().get("records") or {}).get(skill, {}).get(key) or {}
    for date, rec in days.items():
        if not isinstance(rec, dict):
            continue
        node = {"done": bool(rec.get("v")), "ts": int(rec.get("ts") or 0)}
        if "note" in rec:
            node["note"] = rec["note"]
        if "chapters" in rec:
            node["chapters"] = rec["chapters"]
        out[date] = node
    return out


def collect_tracker_state(tab_id):
    """读取某个标签页的打卡状态（书单还带逐章进度）。

    架构 v2 彻底切换：records 读 core checkins（skill+key 映射），
    书单 progress 读 reading/data/booklist_progress.json，不再读旧 tracker_state.json。
    """
    tab_id = _safe_token(tab_id, "A-Za-z0-9_-")
    if not tab_id:
        return 400, {"ok": False, "error": "缺少标签页 id"}
    skill = tracker_tab_skill(tab_id)
    return 200, {
        "ok": True,
        "tab": tab_id,
        "updated": checkins_doc().get("updated", ""),
        "records": checkins_to_tracker_records(skill, tab_id),
        "progress": load_booklist_progress() if tab_id == "booklist" else {},
    }


def _trim_days(records, keep=TRACKER_KEEP_DAYS):
    days = sorted(k for k in (records or {}) if re.match(r"^\d{4}-\d{2}-\d{2}$", str(k)))
    for key in days[:-keep]:
        records.pop(key, None)
    return records


def merge_tracker_state(tab_id, incoming):
    """把页面提交的打卡状态合并落盘（records → core checkins，progress → reading/data）。"""
    tab_id = _safe_token(tab_id, "A-Za-z0-9_-")
    if not tab_id:
        return 400, {"ok": False, "error": "缺少标签页 id"}
    if tab_id not in known_tab_ids():
        return 400, {"ok": False, "error": "未知标签页: %s" % tab_id}
    records = (incoming or {}).get("records") or {}
    progress = (incoming or {}).get("progress") or {}
    if not isinstance(records, dict) or not isinstance(progress, dict):
        return 400, {"ok": False, "error": "records/progress 必须是对象"}
    skill = tracker_tab_skill(tab_id)
    items = []
    for date, rec in records.items():
        if not isinstance(rec, dict):
            continue
        node = {"skill": skill, "key": tab_id, "date": date,
                "v": 1 if rec.get("done") else 0, "ts": int(rec.get("ts") or 0)}
        if "note" in rec:
            node["note"] = rec["note"]
        if "chapters" in rec:
            node["chapters"] = rec["chapters"]
        items.append(node)
    if items:
        _checkins_upsert_items(items)
    merged_progress = {}
    if tab_id == "booklist" and progress:
        with _tracker_lock:
            merged_progress = merge_progress(load_booklist_progress(), progress)
            save_booklist_progress(merged_progress)
    return 200, {
        "ok": True,
        "tab": tab_id,
        "updated": now_iso(),
        "records": checkins_to_tracker_records(skill, tab_id),
        "progress": merged_progress,
    }


def handle_tracker_post(raw_body):
    try:
        raw = json.loads(raw_body.decode("utf-8", "replace")) if raw_body else {}
    except Exception:
        return 400, {"ok": False, "error": "bad_json"}
    if not isinstance(raw, dict):
        return 400, {"ok": False, "error": "bad_body"}
    return merge_tracker_state(raw.get("tab"), raw)


# ======================================================================
# 作业打卡状态：跨设备同步
# ----------------------------------------------------------------------
# 作业卡（含「握笔练习」）的打卡记录，数据和读书/家务/运动一样放到服务器上，
# 手机、平板、电脑打开同一份；localStorage 只作断网缓存。
# 记录格式：{ 作业id: { "YYYY-MM-DD": {"v": 0|1, "ts": 毫秒} } }
#   v=1 已打卡、v=0 取消打卡（保留一条"取消"记录，取消动作才能同步到别的设备）；
#   升级前的旧数据形如 { 作业id: { "YYYY-MM-DD": 1 } }，当作 ts=0 处理，两边都没时间戳时取并集。
# ======================================================================

def _norm_day_mark(mark):
    """把某天的打卡标记统一成 {"v": 0|1, "ts": 毫秒}；空值返回 None。"""
    if isinstance(mark, dict):
        ts = 0
        try:
            ts = int(float(mark.get("ts") or 0))
        except (TypeError, ValueError):
            ts = 0
        return {"v": 1 if mark.get("v") else 0, "ts": max(0, ts)}
    if mark:
        return {"v": 1, "ts": 0}       # 升级前的旧格式（1 / true），不知道改动时间
    return None


def merge_homework_checkins(old_map, new_map):
    """逐项逐日按时间戳取新：取消打卡也会同步过去。
    两边都没有时间戳（升级到跨设备同步之前的旧数据）时取并集，宁可多留也不丢已打的卡。"""
    out = {}
    old_map = old_map if isinstance(old_map, dict) else {}
    new_map = new_map if isinstance(new_map, dict) else {}
    for item_id in set(list(old_map.keys()) + list(new_map.keys())):
        old_days = old_map.get(item_id)
        new_days = new_map.get(item_id)
        if not isinstance(old_days, dict):
            old_days = {}          # 只有一边有这项作业（新加的卡 / 老文件里没有）时照常合并
        if not isinstance(new_days, dict):
            new_days = {}
        days = {}
        for day in set(list(old_days.keys()) + list(new_days.keys())):
            ov = _norm_day_mark(old_days.get(day))
            nv = _norm_day_mark(new_days.get(day))
            if ov is None:
                pick = nv
            elif nv is None:
                pick = ov
            elif ov["ts"] == 0 and nv["ts"] == 0:
                pick = {"v": 1 if (ov["v"] or nv["v"]) else 0, "ts": 0}
            elif nv["ts"] > ov["ts"]:
                pick = nv
            elif nv["ts"] < ov["ts"]:
                pick = ov
            else:
                pick = {"v": 1 if (ov["v"] or nv["v"]) else 0, "ts": ov["ts"]}
            if pick is not None:
                days[day] = pick
        if days:
            out[item_id] = _trim_days(days, HOMEWORK_KEEP_DAYS)
    return out


def load_homework_checkins():
    state = load_json(HOMEWORK_CHECKINS)
    if not isinstance(state, dict):
        state = {}
    recs = state.get("records")
    if not isinstance(recs, dict):
        recs = {}
    state["records"] = recs
    return state


def homework_key_skill(key):
    """作业打卡 key → checkins 的 skill。查三个作业文件的 id，再猜 key 后缀。"""
    key = str(key)
    for skill, skill_name in (("chinese", "subject-chinese"), ("math", "subject-math"), ("class", "english-class")):
        path = os.path.join(data_paths.skill_dir(skill_name), "data", "homework.json")
        data = load_json(path) or {}
        for it in (data.get("items") or []):
            if str(it.get("id")) == key:
                return skill
    m = re.search(r"-(chinese|math|english)$", key)
    if m:
        s = m.group(1)
        return "class" if s == "english" else s
    return "chinese"  # 查不到保守归 chinese，不丢数据


def homework_ids():
    """三个作业文件（chinese/math/class）里的作业 id 集合。"""
    ids = set()
    for skill_name in ("subject-chinese", "subject-math", "english-class"):
        path = os.path.join(data_paths.skill_dir(skill_name), "data", "homework.json")
        data = load_json(path) or {}
        for it in (data.get("items") or []):
            if it.get("id"):
                ids.add(str(it["id"]))
    return ids


def checkins_to_homework_records():
    """checkins 里 chinese/math/class 的**作业打卡** → {作业id: {date: {v, ts}}}。

    只返回作业 id（在三个作业文件里能查到），不含英语「板块打卡」（l2-u2:items 等，
    它们虽也落在 class skill，但属于知识点板块，不是作业卡）。
    """
    ids = homework_ids()
    out = {}
    for skill in ("chinese", "math", "class"):
        keys = (checkins_doc().get("records") or {}).get(skill) or {}
        for key, days in keys.items():
            if key not in ids:
                continue
            if not isinstance(days, dict):
                continue
            for date, rec in days.items():
                if not isinstance(rec, dict):
                    continue
                out.setdefault(key, {})[date] = {"v": 1 if rec.get("v") else 0, "ts": int(rec.get("ts") or 0)}
    return out


def collect_homework_checkins():
    """读取整份作业打卡记录（架构 v2 彻底切换：读 core checkins）。"""
    return 200, {"ok": True, "updated": checkins_doc().get("updated", ""),
                 "records": checkins_to_homework_records()}


def merge_homework_checkins_state(incoming):
    """把页面提交的整份打卡记录合并进 core checkins 并回传（两端最终一致）。"""
    records = (incoming or {}).get("records")
    if records is None:
        records = {}
    if not isinstance(records, dict):
        return 400, {"ok": False, "error": "records 必须是对象"}
    items = []
    for key, days in records.items():
        if not isinstance(days, dict):
            continue
        skill = homework_key_skill(key)
        for date, mark in days.items():
            norm = _norm_day_mark(mark)
            if norm is None:
                continue
            items.append({"skill": skill, "key": str(key), "date": date,
                          "v": norm["v"], "ts": norm["ts"]})
    if items:
        _checkins_upsert_items(items)
    return 200, {"ok": True, "updated": checkins_doc().get("updated", ""),
                 "records": checkins_to_homework_records()}


def handle_homework_checkins_post(raw_body):
    try:
        raw = json.loads(raw_body.decode("utf-8", "replace")) if raw_body else {}
    except Exception:
        return 400, {"ok": False, "error": "bad_json"}
    if not isinstance(raw, dict):
        return 400, {"ok": False, "error": "bad_body"}
    return merge_homework_checkins_state(raw)


# ======================================================================
# 反馈：配置、身份、落盘、转发
# ======================================================================

def load_channels():
    """读取通道配置；本地没有就用随项目分发的模板（模板里内置作者的中转地址）。"""
    cfg = load_json(CHANNELS_FILE)
    if cfg is None:
        cfg = load_json(CHANNELS_TEMPLATE)
    if not isinstance(cfg, dict):
        cfg = {}
    cfg.setdefault("relay", {})
    cfg.setdefault("lark", {})
    cfg.setdefault("enabled", True)
    return cfg


def get_install_id():
    """匿名安装ID：区分不同家庭用，随机生成、不含任何个人信息，首次生成后持久化。"""
    os.makedirs(FEEDBACK_DIR, exist_ok=True)
    path = os.path.join(FEEDBACK_DIR, "install.json")
    data = load_json(path)
    if isinstance(data, dict) and data.get("installId"):
        return data["installId"]
    iid = str(uuid.uuid4())
    try:
        write_json(path, {"installId": iid, "createdAt": now_iso()})
    except Exception:
        pass
    return iid


def get_git_commit():
    try:
        head = os.path.join(WORKSPACE_ROOT, ".git", "HEAD")
        if not os.path.isfile(head):
            return ""
        with open(head, "r", encoding="utf-8") as f:
            content = f.read().strip()
        if content.startswith("ref:"):
            ref_path = os.path.join(WORKSPACE_ROOT, ".git", content[4:].strip())
            if os.path.isfile(ref_path):
                with open(ref_path, "r", encoding="utf-8") as f:
                    return f.read().strip()[:12]
            return ""
        return content[:12]
    except Exception:
        return ""


def machine_fingerprint():
    """主机名 + 系统信息的 SHA-256 前 8 位，仅作同一台设备的关联标识，不可反推原文。"""
    try:
        raw = "%s|%s|%s" % (socket.gethostname(), platform.machine(), platform.system())
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8]
    except Exception:
        return ""


def get_app_meta():
    """应用版本与运行环境，缓存 60 秒。"""
    with _feedback_lock:
        if _meta_cache["data"] and time.time() - _meta_cache["at"] < 60:
            return _meta_cache["data"]
    version = ""
    try:
        if os.path.isfile(VERSION_FILE):
            with open(VERSION_FILE, "r", encoding="utf-8") as f:
                version = f.read().strip().splitlines()[0].strip()
    except Exception:
        version = ""
    meta = {
        "appVersion": version,
        "gitCommit": get_git_commit(),
        "python": "%d.%d.%d" % sys.version_info[:3],
        "os": "%s %s" % (platform.system(), platform.release()),
        # 只上报主机名的不可逆指纹前 8 位：能把同一台机器的多条反馈串起来，
        # 又不会把 hostname 原文写进公开 Issue —— Windows 主机名常常含真实姓名
        # （形如「名字-PC」），直接上报等于在公开仓库里泄露用户身份。
        "machineId": machine_fingerprint(),
        "port": PORT,
    }
    with _feedback_lock:
        _meta_cache["data"] = meta
        _meta_cache["at"] = time.time()
    return meta


def feedback_config_payload():
    ch = load_channels()
    relay = ch.get("relay") or {}
    return {
        "enabled": bool(ch.get("enabled", True)),
        "installId": get_install_id(),
        "relayUrl": relay.get("url") or "",
        "relayConfigured": bool(relay.get("url")),
        "serverAvailable": True,
        "pendingCount": count_pending(),
        **{k: v for k, v in get_app_meta().items()},
    }


def _sanitize_text(val, limit):
    if not isinstance(val, str):
        return ""
    return val.strip()[:limit]


def normalize_payload(raw, client_ip):
    """清洗前端提交的内容：类型/严重度白名单、长度截断、图片格式与数量限制。"""
    if not isinstance(raw, dict):
        raise ValueError("反馈格式不对")
    message = _sanitize_text(raw.get("message"), 4000)
    if len(message) < 2:
        raise ValueError("反馈内容太短")

    ftype = raw.get("type")
    if ftype not in ("feature", "usability", "bug", "other"):
        ftype = "other"
    severity = raw.get("severity")
    if severity not in ("low", "medium", "high", "blocker"):
        severity = ""

    page = raw.get("page") if isinstance(raw.get("page"), dict) else {}
    envd = raw.get("env") if isinstance(raw.get("env"), dict) else {}
    client = raw.get("client") if isinstance(raw.get("client"), dict) else {}

    images = []
    for img in (raw.get("images") or [])[:MAX_IMAGES]:
        if not isinstance(img, dict):
            continue
        mime = str(img.get("mime") or "")
        data = re.sub(r"\s+", "", str(img.get("data") or ""))
        if data.startswith("data:"):
            data = data.split(",", 1)[-1]
        if mime not in ALLOWED_MIME or not data or len(data) > 3_500_000:
            continue
        try:
            base64.b64decode(data[:64], validate=True)
        except Exception:
            continue
        images.append({
            "name": _sanitize_text(img.get("name"), 80) or "screenshot.jpg",
            "mime": mime,
            "data": data,
        })

    return {
        "type": ftype,
        "summary": _sanitize_text(raw.get("summary"), 120),
        "message": message,
        "expect": _sanitize_text(raw.get("expect"), 1000),
        "severity": severity,
        "contact": _sanitize_text(raw.get("contact"), 200),
        "page": {
            "path": _sanitize_text(page.get("path"), 300),
            "title": _sanitize_text(page.get("title"), 120),
            "tab": _sanitize_text(page.get("tab"), 60),
            "skill": _sanitize_text(page.get("skill"), 60),
            "url": _sanitize_text(page.get("url"), 400),
            "via": _sanitize_text(page.get("via"), 200),
        },
        "env": {
            "ua": _sanitize_text(envd.get("ua"), 400),
            "platform": _sanitize_text(envd.get("platform"), 80),
            "screen": _sanitize_text(envd.get("screen"), 40),
            "viewport": _sanitize_text(envd.get("viewport"), 40),
            "lang": _sanitize_text(envd.get("lang"), 40),
            "theme": _sanitize_text(envd.get("theme"), 60),
            "online": bool(envd.get("online", True)),
            "touch": bool(envd.get("touch", False)),
        },
        "images": images,
        "client": {
            "appVersion": _sanitize_text(client.get("appVersion"), 40),
            "widgetVersion": _sanitize_text(client.get("widgetVersion"), 40),
            "installId": _sanitize_text(client.get("installId"), 80) or get_install_id(),
            "submittedAt": _sanitize_text(client.get("submittedAt"), 60) or now_iso(),
        },
        "server": dict(get_app_meta(),
                       installId=_sanitize_text(client.get("installId"), 80) or get_install_id(),
                       access=("localhost" if _is_local(client_ip) else "lan")),
    }


def _is_local(ip):
    return ip in ("127.0.0.1", "::1", "localhost") or str(ip).startswith("127.")


def new_feedback_id():
    return "fbk_%s_%s" % (datetime.now(CN_TZ).strftime("%Y%m%d"), uuid.uuid4().hex[:8])


def save_record(record):
    os.makedirs(FEEDBACK_INBOX, exist_ok=True)
    path = os.path.join(FEEDBACK_INBOX, record["id"] + ".json")
    write_json(path, record)
    prune_records()
    return path


def prune_records():
    """只保留最近 MAX_RECORDS 条，避免用户机器上无限堆积。"""
    try:
        files = sorted(
            (os.path.join(FEEDBACK_INBOX, f) for f in os.listdir(FEEDBACK_INBOX) if f.endswith(".json")),
            key=os.path.getmtime,
        )
        for old in files[:-MAX_RECORDS]:
            try:
                os.remove(old)
            except Exception:
                pass
    except Exception:
        pass


def list_records():
    out = []
    if not os.path.isdir(FEEDBACK_INBOX):
        return out
    for name in sorted(os.listdir(FEEDBACK_INBOX)):
        if not name.endswith(".json"):
            continue
        rec = load_json(os.path.join(FEEDBACK_INBOX, name))
        if isinstance(rec, dict):
            out.append(rec)
    out.sort(key=lambda r: r.get("receivedAt") or "", reverse=True)
    return out


def count_pending():
    return sum(1 for r in list_records() if (r.get("delivery") or {}).get("state") == "pending")


def _post_json(url, body, headers=None, timeout=FORWARD_TIMEOUT):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json; charset=utf-8")
    req.add_header("User-Agent", "GrowthHome-Feedback/1.0")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", "replace")
            try:
                return resp.status, json.loads(text) if text else {}
            except Exception:
                return resp.status, {"raw": text[:300]}
    except urllib.error.HTTPError as e:
        text = ""
        try:
            text = e.read().decode("utf-8", "replace")
        except Exception:
            pass
        try:
            return e.code, json.loads(text) if text else {}
        except Exception:
            return e.code, {"raw": text[:300]}


def _rate_limited():
    """简单限流：只限制「转发到公网」的频率，本地落盘不受影响。"""
    now = time.time()
    while _rate_hits and now - _rate_hits[0] > RATE_WINDOW:
        _rate_hits.pop(0)
    if len(_rate_hits) >= RATE_LIMIT:
        return True
    _rate_hits.append(now)
    return False


def _lark_sign(secret):
    """飞书自定义机器人加签：以 "时间戳\\n密钥" 为 key、对空串做 HMAC-SHA256 再 base64。"""
    ts = str(int(time.time()))
    string_to_sign = "%s\n%s" % (ts, secret)
    digest = hmac.new(string_to_sign.encode("utf-8"), b"", hashlib.sha256).digest()
    return ts, base64.b64encode(digest).decode("utf-8")


def push_lark(webhook, secret, text):
    body = {"msg_type": "text", "content": {"text": text}}
    if secret:
        ts, sign = _lark_sign(secret)
        body["timestamp"] = ts
        body["sign"] = sign
    status, resp = _post_json(webhook, body, timeout=8)
    code = resp.get("code", resp.get("StatusCode", 0)) if isinstance(resp, dict) else -1
    return status == 200 and code == 0


def forward_record(record):
    """把一条反馈转发到公网中转服务；返回 (是否成功, 结果字典)。"""
    ch = load_channels()
    if not ch.get("enabled", True):
        return False, {"skipped": "disabled"}
    relay = ch.get("relay") or {}
    url = (relay.get("url") or "").strip()
    lark = ch.get("lark") or {}

    # 没有任何外发通道时直接返回，不消耗限流额度（否则后台每 5 分钟的重试
    # 会把额度吃光，等用户真配好地址时反而被限流）。
    if not url and not lark.get("webhook"):
        return False, {"relayError": "未配置中转服务地址"}

    if _rate_limited():
        return False, {"error": "rate_limited", "retryAfter": RATE_WINDOW}

    delivered, failed, result = [], [], {}

    if url:
        headers = {}
        if relay.get("appKey"):
            headers["X-App-Key"] = str(relay["appKey"])
        try:
            status, resp = _post_json(url, record.get("payload", {}), headers=headers)
            if status == 200 and isinstance(resp, dict) and resp.get("ok"):
                delivered.append("relay")
                result["issueUrl"] = resp.get("issueUrl") or ""
                result["issueNumber"] = resp.get("issueNumber")
                result["relay"] = {k: resp.get(k) for k in ("github", "lark", "delivered", "failed") if k in resp}
                result["relayId"] = resp.get("id")
            else:
                failed.append("relay")
                result["relayError"] = "HTTP %s %s" % (status, json.dumps(resp, ensure_ascii=False)[:200])
        except Exception as e:
            failed.append("relay")
            result["relayError"] = "%s: %s" % (type(e).__name__, str(e)[:160])
    else:
        result["relayError"] = "未配置中转服务地址"

    # 作者本机可选：直连飞书群机器人做即时提醒（分发版模板里不含 webhook，普通用户不会触发）
    if lark.get("webhook"):
        try:
            p = record.get("payload", {})
            text = "【成长家园反馈】%s\n页面：%s %s\n内容：%s\n时间：%s\n匿名ID：%s" % (
                p.get("type", ""), (p.get("page") or {}).get("title", ""),
                (p.get("page") or {}).get("path", ""), (p.get("message") or "")[:200],
                now_iso(), str((p.get("client") or {}).get("installId", ""))[:8],
            )
            if push_lark(lark["webhook"], lark.get("secret"), text):
                delivered.append("lark")
            else:
                failed.append("lark")
        except Exception as e:
            failed.append("lark")
            result["larkError"] = "%s: %s" % (type(e).__name__, str(e)[:160])

    ok = bool(delivered)
    result["delivered"] = delivered
    result["failed"] = failed
    return ok, result


def update_delivery(record, ok, result):
    d = record.setdefault("delivery", {})
    d["attempts"] = int(d.get("attempts", 0)) + 1
    d["lastAttemptAt"] = now_iso()
    d["lastResult"] = result
    if ok:
        d["state"] = "sent"
        d["sentAt"] = now_iso()
        if result.get("issueUrl"):
            d["issueUrl"] = result["issueUrl"]
        d.pop("lastError", None)
    else:
        d["state"] = "pending"
        d["lastError"] = result.get("relayError") or result.get("larkError") or json.dumps(result, ensure_ascii=False)[:200]
        if result.get("retryAfter"):
            d["retryAfter"] = (datetime.now(CN_TZ) + timedelta(seconds=int(result["retryAfter"]))).isoformat(timespec="seconds")
    try:
        save_record(record)
    except Exception:
        pass
    return d


def retry_pending_once():
    """补发所有待发送的反馈（跳过限流冷却中的）。返回补发成功条数。"""
    sent = 0
    cutoff = (datetime.now(CN_TZ) - timedelta(days=MAX_RETRY_DAYS)).isoformat(timespec="seconds")
    for rec in list_records():
        d = rec.get("delivery") or {}
        if d.get("state") != "pending":
            continue
        if (rec.get("receivedAt") or "") < cutoff:
            d.update(state="expired")
            try:
                save_record(rec)
            except Exception:
                pass
            continue
        retry_after = d.get("retryAfter")
        if retry_after and retry_after > now_iso():
            continue
        if int(d.get("attempts", 0)) >= 30:
            continue
        try:
            ok, result = forward_record(rec)
        except Exception as e:
            ok, result = False, {"relayError": "%s: %s" % (type(e).__name__, str(e)[:160])}
        update_delivery(rec, ok, result)
        if ok:
            sent += 1
        time.sleep(0.4)   # 温和一点，别把中转服务的限流额度一次吃光
    return sent


# ===== 配音自动补齐 =====
# 页面上的朗读统一播放 data/tts 下预生成的 mp3（见 voice-dubbing 技能）。
# 只要内容文件有改动（新增单词/句子、书目、画作、学情、作业、课表用具…），
# 这里就自动跑一次增量生成，避免"加了内容忘了补配音"导致手机上没声音。
TTS_GEN = os.path.join(SKILLS_DIR, "voice-dubbing", "tools", "gen_tts.py")
TTS_CHECK_INTERVAL = 20          # 秒：多久检查一次内容文件有没有改动
# 配音源：内容已按技能归位（架构 v2 第 3 步），读各技能 data/ 与 core 的新位置
TTS_SOURCES = [
    os.path.join(data_paths.skill_dir("english-class"), "data", "english_class.json"),
    os.path.join(data_paths.skill_dir("subject-school-english"), "data", "school_english.json"),
    os.path.join(data_paths.skill_dir("subject-chinese"), "data", "homework.json"),
    os.path.join(data_paths.skill_dir("subject-math"), "data", "homework.json"),
    os.path.join(data_paths.skill_dir("english-class"), "data", "homework.json"),
    os.path.join(CORE_DATA, "activities.json"),
    os.path.join(READING_DATA, "booklist.json"),
    os.path.join(LIB_DATA, "books.json"),
    os.path.join(ART_DATA, "index.json"),
    os.path.join(BAG_DATA, "config.json"),
    os.path.join(BAG_DATA, "course_requirements.json"),
    os.path.join(BAG_DATA, "schedule.json"),
]
TTS_DAYS_DIR = os.path.join(LEARN_DATA, "days")
TTS_STATE = {"lastRun": "", "lastResult": "尚未运行", "lastAdded": 0, "running": False}


def tts_sources_mtime():
    """所有会影响配音的内容文件里，最新的修改时间。"""
    latest = 0.0
    paths = list(TTS_SOURCES)
    paths += glob.glob(os.path.join(TTS_DAYS_DIR, "*.json"))
    for p in paths:
        try:
            latest = max(latest, os.path.getmtime(p))
        except OSError:
            pass
    return latest


def run_voice_dubbing(quiet=False):
    """跑一次增量补配音（只补新增/变更的内容）。返回 (ok, 输出)。"""
    if not os.path.exists(TTS_GEN):
        return False, "找不到生成脚本 %s" % TTS_GEN
    if not quiet:
        print("  🔊 检测到内容有变化，正在补配音…")
    try:
        proc = subprocess.run([sys.executable, TTS_GEN], cwd=WORKSPACE_ROOT,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=1800)
        out = (proc.stdout or b"").decode("utf-8", "replace")
    except Exception as e:
        TTS_STATE["lastResult"] = "失败: %s" % e
        print("  ⚠️  补配音失败: %s" % e)
        return False, str(e)
    added = 0
    for line in out.splitlines():
        m = re.search(r"生成完成 (\d+) 条", line)
        if m:
            added = int(m.group(1))
    TTS_STATE["lastRun"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    TTS_STATE["lastAdded"] = added
    if proc.returncode != 0:
        TTS_STATE["lastResult"] = "出错（退出码 %d）" % proc.returncode
        tail = "\n".join(out.strip().splitlines()[-4:])
        print("  ⚠️  补配音出错（退出码 %d）：\n%s" % (proc.returncode, tail))
        return False, out
    TTS_STATE["lastResult"] = ("完成，新增 %d 条" % added) if added else "无新增（都已配音）"
    if added or not quiet:
        print("  ✅ 补配音%s" % (("完成，新增 %d 条" % added) if added else "检查完毕，已是最新"))
    return True, out


def tts_loop():
    """内容一变就自动补配音；启动时先补一次，覆盖"服务器没开着时改过内容"的情况。"""
    last = tts_sources_mtime()
    TTS_STATE["running"] = True
    try:
        run_voice_dubbing(quiet=True)
    finally:
        TTS_STATE["running"] = False
    while True:
        time.sleep(TTS_CHECK_INTERVAL)
        cur = tts_sources_mtime()
        if cur <= last:
            continue
        time.sleep(3)                      # 文件可能还在写，稍等再确认一次
        last = tts_sources_mtime()
        TTS_STATE["running"] = True
        try:
            run_voice_dubbing()
        finally:
            TTS_STATE["running"] = False


def tts_status():
    idx = load_json(os.path.join(GH_DATA, "tts", "index.json")) or {}
    stats = idx.get("stats") or {}
    return {"ok": True, "hasGenerator": os.path.exists(TTS_GEN),
            "generated": idx.get("generated"), "entries": stats.get("entries", 0),
            "en": stats.get("en", 0), "zh": stats.get("zh", 0),
            "checkInterval": TTS_CHECK_INTERVAL, "state": TTS_STATE}


def retry_loop():
    while True:
        time.sleep(RETRY_INTERVAL)
        try:
            n = retry_pending_once()
            if n:
                print("  📮 反馈补发成功 %d 条" % n)
        except Exception:
            pass


def handle_feedback_post(raw_body, client_ip):
    """落盘 + 尝试即时转发。转发失败不算用户失败：本机已存，后台会自动补发。"""
    try:
        raw = json.loads(raw_body.decode("utf-8", "replace")) if raw_body else {}
    except Exception:
        return 400, {"ok": False, "error": "bad_json"}
    try:
        payload = normalize_payload(raw, client_ip)
    except ValueError as e:
        return 400, {"ok": False, "error": str(e)}

    record = {
        "id": new_feedback_id(),
        "receivedAt": now_iso(),
        "payload": payload,
        "delivery": {"state": "pending", "attempts": 0},
    }
    try:
        save_record(record)
    except Exception as e:
        return 500, {"ok": False, "error": "本地保存失败: %s" % e}

    try:
        ok, result = forward_record(record)
    except Exception as e:
        ok, result = False, {"relayError": "%s: %s" % (type(e).__name__, str(e)[:160])}
    d = update_delivery(record, ok, result)

    if ok:
        return 200, {
            "ok": True,
            "id": record["id"],
            "queued": False,
            "issueUrl": d.get("issueUrl", ""),
            "issueNumber": (result or {}).get("issueNumber"),
            "delivered": result.get("delivered", []),
            "failed": result.get("failed", []),
            "message": "已送达",
        }
    return 200, {
        "ok": True,
        "id": record["id"],
        "queued": True,
        "delivered": [],
        "failed": result.get("failed", []),
        "message": "已存到本机，联网后自动补发",
        "reason": (result.get("relayError") or "")[:200],
    }


# ======================================================================
# 技能 api.py 自动注册（架构 v2 第 3 步，见 docs/architecture-v2.md §5）
# ----------------------------------------------------------------------
# 启动时扫 .trae/skills/*/skill.json：带 "api": "api.py" 字段的技能，用 importlib
# 加载该模块，把模块里的 ROUTES dict（形状与本注册表相同：(方法, 路径) -> handler(h)，
# h 是 http.server handler 实例）合并进主注册表。冲突时**现有注册表优先**并打印警告。
# 页面（静态目录）自动挂载逻辑照旧（见下面 _skill_namespace_maps）。
#
# 两遍加载：第一遍只 exec_module（模块级代码不许碰数据路径），第二遍才 bind(ctx)
# 并注册路由——这样技能之间可以通过 ctx["skill_module"](技能名) 互相调用
# （如 daily-report 聚合 subject-chinese 的 collect_homework_data），不受加载顺序影响。
# ======================================================================

SKILL_API_MODULES = {}


def _skill_api_context(skill):
    """给技能 api.py 的共享上下文：通用助手与数据路径常量（处理器写回服务器那份逻辑用）。

    技能 api.py 通过这些助手保持与主服务器完全一致的行为（同样的 JSON 读写、同样的
    multipart 解析、同样的数据目录），而不是各自再抄一份。
    架构 v2 第 3 步：每个技能拿到自己的 SKILL_DATA（<root>/<url>/data），
    core 归属的共享内容走 CORE_DATA；GH_DATA（web/data）保留给 media 等尚未搬迁的路径。
    """
    return {
        "load_json": load_json,
        "write_json": write_json,
        "parse_multipart": parse_multipart,
        "safe_token": _safe_token,
        "now_iso": now_iso,
        "CN_TZ": CN_TZ,
        "GH_DATA": GH_DATA,
        "CORE_DATA": CORE_DATA,
        "SKILL_DATA": str(data_paths.skill_dir(skill) / "data"),
        "MAX_BODY_BYTES": MAX_BODY_BYTES,
        # 本机离线语音识别引擎（可能为 None：没装 faster-whisper）
        "asr_engine": asr_engine,
        # 仍留在主服务器的 collector（core 归属），供技能聚合路由复用
        "collect_home_data": collect_home_data,
        "collect_learn_data": collect_learn_data,
        "collect_tracker_state": collect_tracker_state,
        "collect_homework_checkins": collect_homework_checkins,
        "checkins_by_skill": checkins_by_skill,
        # 跨技能调用：daily-report / homework-assigner 的聚合路由用它拿别的技能的 collector
        "skill_module": lambda name: SKILL_API_MODULES.get(name),
    }


def load_skill_apis():
    """扫技能目录，加载带 "api" 字段的技能的 api.py 并合并其 ROUTES（增量）。"""
    if not os.path.isdir(SKILLS_DIR):
        return
    # —— 第一遍：加载模块（exec_module 阶段失败只警告，不影响主服务器与其它技能）——
    pending = []
    for skill in sorted(os.listdir(SKILLS_DIR)):
        skill_path = os.path.join(SKILLS_DIR, skill)
        meta_path = os.path.join(skill_path, "skill.json")
        if not os.path.isfile(meta_path):
            continue
        try:
            with open(meta_path, encoding="utf-8") as f:
                meta = json.load(f)
        except (ValueError, OSError):
            continue
        api_rel = str(meta.get("api") or "").strip()
        if not api_rel:
            continue
        api_path = os.path.join(skill_path, api_rel)
        if not os.path.isfile(api_path):
            print("[api] 技能 %s 声明了 api=%s 但文件不存在，跳过" % (skill, api_rel))
            continue
        mod_name = "skill_api_" + re.sub(r"\W", "_", skill)
        try:
            spec = importlib.util.spec_from_file_location(mod_name, api_path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        except Exception as e:
            print("[api] 技能 %s 的 %s 加载失败：%s: %s" % (skill, api_rel, type(e).__name__, e))
            continue
        SKILL_API_MODULES[skill] = mod
        pending.append((skill, mod))
    # —— 第二遍：bind(ctx) + 注册路由（冲突时现有注册表优先并打印警告）——
    # 每个技能一个专属 ctx（含各自的 SKILL_DATA），不是共享一份
    for skill, mod in pending:
        ctx = _skill_api_context(skill)
        bind = getattr(mod, "bind", None)
        if callable(bind):
            try:
                bind(ctx)
            except Exception as e:
                print("[api] 技能 %s bind 失败：%s: %s（该技能路由不注册）" % (skill, type(e).__name__, e))
                continue
        routes = getattr(mod, "ROUTES", None)
        if not isinstance(routes, dict):
            print("[api] 技能 %s 的 api.py 没有 ROUTES dict，跳过" % skill)
            continue
        n = 0
        for key, fn in routes.items():
            if not (isinstance(key, tuple) and len(key) == 2) or not callable(fn):
                print("[api] 技能 %s 的路由项形状不对：%r（应为 (方法, 路径): handler），跳过" % (skill, key))
                continue
            if key in ROUTES:
                print("[api] 路由冲突：%s %s（技能 %s）被忽略——注册表已有该路由，现有优先"
                      % (key[0], key[1], skill))
                continue
            ROUTES[key] = fn
            n += 1
        print("[api] 技能 %s：注册 %d 条路由" % (skill, n))


load_skill_apis()


# 命名空间（URL 前缀）→ 代码目录 / 数据目录。同一命名空间下：
#   首段是 data/images/audio/output → 走数据区（仓库之外）；否则走仓库里的代码目录。
# 这张表**由各技能的 skill.json 自动生成**（url = 前缀，见 tools/data_paths.py）：
# 新技能只要带上 skill.json 就自动挂上，不用改本文件（portal_wire 也不再手改服务器）。
# 门户自己（growth-home，url=web）走默认目录 DIR，故单独排除。
LEGACY_NS_CODE_DIRS = {"learn": LEARN_DIR, "bag": BAG_DIR, "art": ART_DIR,
                       "lib": LIB_DIR, "comp": COMP_DIR}
LEGACY_NS_DATA_DIRS = {"learn": os.path.dirname(LEARN_DATA), "bag": os.path.dirname(BAG_DATA),
                       "art": os.path.dirname(ART_DATA), "lib": os.path.dirname(LIB_DATA),
                       "comp": os.path.dirname(COMP_DATA)}
DATA_SEGMENTS = {"data", "images", "audio", "output"}


def _skill_namespace_maps():
    """扫 .trae/skills/*/skill.json：命名空间 → (代码目录, 数据目录)。
    技能声明了 url 就用它；门户自己（url=web）不在此表（走默认目录 DIR）。"""
    code = dict(LEGACY_NS_CODE_DIRS)
    data = dict(LEGACY_NS_DATA_DIRS)
    if not os.path.isdir(SKILLS_DIR):
        return code, data
    for skill in sorted(os.listdir(SKILLS_DIR)):
        skill_path = os.path.join(SKILLS_DIR, skill)
        meta_path = os.path.join(skill_path, "skill.json")
        if not os.path.isfile(meta_path):
            continue
        try:
            with open(meta_path, encoding="utf-8") as f:
                meta = json.load(f)
        except (ValueError, OSError):
            continue
        ns = str(meta.get("url") or "").strip().strip("/")
        if not ns or ns == "web":
            continue
        code[ns] = skill_path
        try:
            data[ns] = str(data_paths.skill_dir(skill))
        except data_paths.DataRootNotConfigured:
            pass
    return code, data


NS_CODE_DIRS, NS_DATA_DIRS = _skill_namespace_maps()


def legacy_static_redirect(route):
    """静态资产与门户 shell 的旧地址 → portal-core 新地址（301，保留一个版本后删除）。

    架构 v2 第 2 步：vendor 收拢为 portal-core/vendor 单源（/vendor/<f>），
    homework-section.js 迁到 portal-core/components/，门户 shell 迁到
    portal-core/web/index.html（由 "/" 直接提供）。旧书签、旧缓存页面里的
    相对地址（如 /learn/web/vendor/voice.js）统一 301 到新位置。
    """
    if route in ("/web/index.html", "/index.html"):
        return "/"
    if route == "/web/homework-section.js":
        return "/components/homework-section.js"
    if route.startswith("/web/vendor/"):
        return "/vendor/" + route[len("/web/vendor/"):]
    for ns in NS_CODE_DIRS:
        prefix = "/%s/web/vendor/" % ns
        if route.startswith(prefix):
            return "/vendor/" + route[len(prefix):]
    return None


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIR, **kwargs)

    def translate_path(self, path):
        path = path.split("?", 1)[0].split("#", 1)[0]
        try:
            path = urllib.parse.unquote(path, errors="surrogatepass")
        except UnicodeDecodeError:
            path = urllib.parse.unquote(path)
        path = posixpath.normpath(path)
        segments = [s for s in path.split("/") if s and s != ".."]
        if not segments:
            # 门户 shell：架构 v2 第 2 步起由 portal-core/web/index.html 提供
            return os.path.join(PORTAL_CORE_WEB, "index.html")
        # portal-core 单源静态资产（/vendor/*、/components/*）
        if segments[0] == "vendor":
            return os.path.join(PORTAL_CORE_VENDOR, *segments[1:])
        if segments[0] == "components":
            return os.path.join(PORTAL_CORE_COMPONENTS, *segments[1:])
        # portal-core/web 下的 shell 页面（设置页等）
        if segments[0] == "settings.html":
            return os.path.join(PORTAL_CORE_WEB, "settings.html")
        # growth-home 的数据：公开 URL 是 /data/…，物理落在 <data-root>/web/data/…
        if segments[0] == "data":
            return os.path.join(os.path.dirname(GH_DATA), *segments)
        ns = segments[0]
        if ns in NS_CODE_DIRS:
            rest = segments[1:]
            if rest and rest[0] in DATA_SEGMENTS:
                return os.path.join(NS_DATA_DIRS[ns], *rest)
            return os.path.join(NS_CODE_DIRS[ns], *rest)
        if ns == "textbooks":
            return os.path.join(TEXTBOOKS_DIR, *segments[1:])
        return super().translate_path(path)

    def send_json(self, obj, status=200):
        payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def query_value(self, key):
        query = urllib.parse.urlparse(self.path).query
        return (urllib.parse.parse_qs(query).get(key) or [""])[0]

    def do_GET(self):
        route = self.path.split("?", 1)[0]
        handler_fn = ROUTES.get(("GET", route))
        if handler_fn is not None:
            return handler_fn(self)
        if route in REDIRECTS:
            # 重定向必须带上原来的查询串：/tracker.html?id=sports、/tracker.html?id=reading
            # 这类老地址（老书签、老二维码）少了 ?id=… 就会落到"没有标签页"的页面上，
            # 打开是空的 / 直接报错，看起来像数据丢了。
            target = REDIRECTS[route]
            query = self.path.split("?", 1)[1] if "?" in self.path else ""
            if query:
                target += ("&" if "?" in target else "?") + query
            self.send_response(302)
            self.send_header("Location", target)
            self.end_headers()
            return
        # 静态资产旧地址 → portal-core 新位置（301 永久重定向，查询串原样带上）
        target = legacy_static_redirect(route)
        if target is not None:
            query = self.path.split("?", 1)[1] if "?" in self.path else ""
            if query:
                target += ("&" if "?" in target else "?") + query
            self.send_response(301)
            self.send_header("Location", target)
            self.end_headers()
            return
        self._serve_static()

    def _serve_static(self):
        """带 Range 支持的静态文件服务。

        视频/音频必须支持 HTTP Range 才能拖动进度条；iOS Safari 若无 Range 甚至无法播放。
        """
        path = self.translate_path(self.path)
        if os.path.isdir(path):
            return super().do_GET()
        if not os.path.isfile(path):
            return super().do_GET()
        try:
            size = os.path.getsize(path)
            ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
            # 页面 / 脚本 / 样式不缓存：这是本地门户，改了页面刷新就得是新版；
            # 手机、平板更不能再拿旧版页面（旧版里的接口/渲染逻辑可能和现在的数据对不上，
            # 表现为"点开某个按钮是空的"这种查不出来的毛病）。音频/视频/图片照旧允许缓存。
            no_store = os.path.splitext(path)[1].lower() in (".html", ".js", ".css")
            range_header = self.headers.get("Range")
            start, end = 0, size - 1
            status = 200
            if range_header:
                m = re.match(r"bytes=(\d*)-(\d*)", range_header)
                if m:
                    s, e = m.group(1), m.group(2)
                    if s == "" and e != "":
                        start = max(0, size - int(e))
                    elif s != "" and e == "":
                        start = int(s)
                    elif s != "" and e != "":
                        start = int(s)
                        end = min(int(e), size - 1)
                    if 0 <= start < size:
                        status = 206
                    else:
                        start = 0
            with open(path, "rb") as f:
                if status == 206:
                    f.seek(start)
                    data = f.read(end - start + 1)
                    self.send_response(206)
                    self.send_header("Content-Type", ctype)
                    self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, size))
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Accept-Ranges", "bytes")
                    if no_store:
                        self.send_header("Cache-Control", "no-store, must-revalidate")
                    self.end_headers()
                    self.wfile.write(data)
                else:
                    self.send_response(200)
                    self.send_header("Content-Type", ctype)
                    self.send_header("Content-Length", str(size))
                    self.send_header("Accept-Ranges", "bytes")
                    if no_store:
                        self.send_header("Cache-Control", "no-store, must-revalidate")
                    self.end_headers()
                    shutil.copyfileobj(f, self.wfile)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            pass
        except Exception as e:
            try:
                self.send_error(500, "serve failed: %s" % e)
            except Exception:
                pass

    def do_POST(self):
        route = self.path.split("?", 1)[0]
        handler_fn = ROUTES.get(("POST", route))
        if handler_fn is None:
            return self.send_json({"ok": False, "error": "not_found"}, 404)
        return handler_fn(self)

    def log_message(self, format, *args):
        print(f"  -> {args[0]}")


class ThreadingServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    """多线程：转发反馈到公网时可能等十几秒，单线程会把静态页面一起卡住。"""
    daemon_threads = True
    allow_reuse_address = True


def port_in_use(port):
    """探测端口是否已被占用。

    Windows 上 SO_REUSEADDR 允许两个进程同时绑同一端口，请求会被随机分给新旧两个
    服务器（表现为「页面能开但新接口 404」），极难排查。所以启动前先明确探测一次。
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.6)
        return s.connect_ex(("127.0.0.1", port)) == 0


def main():
    os.chdir(DIR)
    local_ip = get_local_ip()

    if port_in_use(PORT):
        print("=" * 50)
        print(f"  ⚠️  端口 {PORT} 已被占用，门户没有启动")
        print("=" * 50)
        print("  多半是之前启动的服务器（或兄弟技能的独立服务器）还在后台运行。")
        print("  请先关掉它，再重新启动本门户 —— 门户已包含它们的全部功能。")
        print()
        print(f"  Windows 查看占用进程: netstat -ano | findstr :{PORT}")
        print("  Windows 结束进程:     taskkill /PID <上面查到的PID> /F")
        print("  macOS/Linux:          lsof -ti :%d | xargs kill" % PORT)
        print()
        print("  注意：如果继续强行运行，新旧两个服务器会同时绑在 %d 端口，" % PORT)
        print("        页面能打开但新接口会随机 404，非常难排查。")
        sys.exit(1)

    os.makedirs(FEEDBACK_INBOX, exist_ok=True)
    ensure_data_dirs()
    cfg = feedback_config_payload()

    server = ThreadingServer(("0.0.0.0", PORT), Handler)

    print("=" * 50)
    print("  🏠 成长家园门户 - 预览服务器已启动")
    print("=" * 50)
    print(f"  电脑访问: http://localhost:{PORT}{PAGE_URL}")
    print(f"  手机访问: http://{local_ip}:{PORT}{PAGE_URL}")
    print("  学习看板: /learn/web/dashboard.html")
    print("  书包清单: /bag/web/checklist.html")
    print("  画作画廊: /art/web/art.html")
    print("  家庭图书馆: /lib/web/library.html")
    print("-" * 50)
    if cfg["relayConfigured"]:
        print("  💌 反馈通道: 已配置，用户建议将自动送达作者")
    else:
        print("  💌 反馈通道: 未配置中转地址，反馈只存本机 data/feedback/inbox/")
        print("     配置方法见 feedback-relay/README.md")
    if cfg["pendingCount"]:
        print(f"  📮 待补发反馈: {cfg['pendingCount']} 条，正在后台重试…")
    print("  反馈状态: /api/feedback/status")
    print("=" * 50)
    print("  🔊 配音自动补齐: 已开启（内容文件变化后 %d 秒内自动合成）" % TTS_CHECK_INTERVAL)
    print("     状态: /api/tts/status")
    if asr_engine is not None:
        print("  🗣️ 语音识别: 本机离线识别已开启，页面录音会自动转成文字")
        print("     状态: /api/voice/status")
    else:
        print("  🗣️ 语音识别: 未启用（缺 faster-whisper），录音仍会保存，文字请手动输入")
    print("=" * 50)
    print("  按 Ctrl+C 停止服务器")
    print()

    threading.Thread(target=retry_loop, daemon=True).start()
    threading.Thread(target=tts_loop, daemon=True).start()
    if asr_engine is not None:
        asr_engine.warmup()   # 后台预热模型：第一条录音就不用等模型加载了
    if cfg["pendingCount"]:
        threading.Thread(target=lambda: print("  📮 历史反馈补发完成 %d 条" % retry_pending_once()),
                         daemon=True).start()

    # 自动化测试/无头启动时不要弹浏览器：设 GH_NO_BROWSER=1
    if not os.environ.get("GH_NO_BROWSER"):
        webbrowser.open(f"http://localhost:{PORT}{PAGE_URL}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务器已停止。")
        server.shutdown()


if __name__ == "__main__":
    main()

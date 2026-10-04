# -*- coding: utf-8 -*-
"""english-class 技能 API（架构 v2 第 3 步）：辅导班英语的内容路由。

handler 从 growth-home/web/preview_server.py 的路由注册表**移动**而来
（移动，不是复制）：collect_class_data 与 GET /api/class/data。行为与原来
逐字一致，**数据读写路径一律不变**——仍读 <data-root>/web/data/
english_class.json 与 english_class_records.json，数据搬家是切换段的事。

打卡说明：POST /api/class/checkin 属 core 打卡 6 条之一，留在 preview_server.py
不动；本技能新页面的打卡走 core 统一打卡服务 /api/checkins（skill=class）。

模块级代码不许碰数据路径：一切依赖由门户服务器启动时 bind(ctx) 注入。
"""
import os

# —— 由 bind(ctx) 注入的共享上下文（preview_server.py 的 _skill_api_context）——
_CTX = {}

GH_DATA = None
SKILL_DATA = None
CORE_DATA = None
CLASS_FILE = None
CONFIG_FILE = None


def bind(ctx):
    """门户服务器加载本模块后回调：注入共享助手与数据路径常量。

    架构 v2 第 3 步：单元内容读本技能 data 目录（class/data/english_class.json），
    孩子档案读 core，打卡记录改走 core checkins（checkins_by_skill("class")）。
    """
    global GH_DATA, SKILL_DATA, CORE_DATA, CLASS_FILE, CONFIG_FILE
    _CTX.update(ctx)
    GH_DATA = ctx["GH_DATA"]
    SKILL_DATA = ctx["SKILL_DATA"]
    CORE_DATA = ctx["CORE_DATA"]
    CLASS_FILE = os.path.join(SKILL_DATA, "english_class.json")
    CONFIG_FILE = os.path.join(CORE_DATA, "config.json")


def collect_class_data():
    """英语辅导班：单元内容(听说读写作业/资料) + 孩子姓名 + 打卡记录（来自 core checkins）。"""
    content = _CTX["load_json"](CLASS_FILE) or {}
    cfg = _CTX["load_json"](CONFIG_FILE) or {}
    return {
        "childName": cfg.get("childName", ""),
        "goal": content.get("goal", "跟着辅导班，听说读写，每天进步一点点"),
        "weeklyTarget": content.get("weeklyTarget", "每周至少打卡 3 次"),
        "roadmap": content.get("roadmap", []),
        "units": content.get("units", []),
        "records": _CTX["checkins_by_skill"]("class"),
    }


def route_get_class_data(h):
    return h.send_json(collect_class_data())


def route_get_home(h):
    """页面聚合口：门户 /api/home 的同名载荷（core 的 collector 经由 ctx 复用）。"""
    return h.send_json(_CTX["collect_home_data"]())


ROUTES = {
    # 技能 url 是 class：新命名空间路径 /api/class/data 与旧路径相同（同源同键）
    ("GET", "/api/class/data"): route_get_class_data,
    ("GET", "/api/class/home"): route_get_home,
}

# -*- coding: utf-8 -*-
"""subject-school-english 技能 API（架构 v2 第 3 步）：学校英语的内容路由。

handler 从 growth-home/web/preview_server.py 的路由注册表**移动**而来
（移动，不是复制）：collect_school_data 与 GET /api/school/data。行为与原来
逐字一致，**数据读写路径一律不变**——仍读 <data-root>/web/data/
school_english.json 与 school_english_records.json，数据搬家是切换段的事。

打卡说明：POST /api/school/checkin 属 core 打卡 6 条之一，留在 preview_server.py
不动；本技能新页面的打卡走 core 统一打卡服务 /api/checkins（skill=school）。

模块级代码不许碰数据路径：一切依赖由门户服务器启动时 bind(ctx) 注入。
"""
import os

# —— 由 bind(ctx) 注入的共享上下文（preview_server.py 的 _skill_api_context）——
_CTX = {}

GH_DATA = None
SKILL_DATA = None
CORE_DATA = None
SCHOOL_FILE = None
CONFIG_FILE = None


def bind(ctx):
    """门户服务器加载本模块后回调：注入共享助手与数据路径常量。

    架构 v2 第 3 步：单元内容读本技能 data 目录（school/data/school_english.json），
    孩子档案读 core，打卡记录改走 core checkins（checkins_by_skill("school")）。
    """
    global GH_DATA, SKILL_DATA, CORE_DATA, SCHOOL_FILE, CONFIG_FILE
    _CTX.update(ctx)
    GH_DATA = ctx["GH_DATA"]
    SKILL_DATA = ctx["SKILL_DATA"]
    CORE_DATA = ctx["CORE_DATA"]
    SCHOOL_FILE = os.path.join(SKILL_DATA, "school_english.json")
    CONFIG_FILE = os.path.join(CORE_DATA, "config.json")


def collect_school_data():
    """学校英语：外研社新交际英语单元内容 + 孩子姓名 + 每日听练打卡记录（来自 core checkins）。"""
    content = _CTX["load_json"](SCHOOL_FILE) or {}
    cfg = _CTX["load_json"](CONFIG_FILE) or {}
    return {
        "childName": cfg.get("childName", ""),
        "goal": content.get("goal", "每天听一听、看一看、说一说，磨出语感"),
        "textbook": content.get("textbook", "外研社《新交际英语》"),
        "units": content.get("units", []),
        "records": _CTX["checkins_by_skill"]("school"),
    }


def route_get_school_data(h):
    return h.send_json(collect_school_data())


def route_get_home(h):
    """页面聚合口：门户 /api/home 的同名载荷（core 的 collector 经由 ctx 复用）。"""
    return h.send_json(_CTX["collect_home_data"]())


ROUTES = {
    # 技能 url 是 school：新命名空间路径 /api/school/data 与旧路径相同（同源同键）
    ("GET", "/api/school/data"): route_get_school_data,
    ("GET", "/api/school/home"): route_get_home,
}

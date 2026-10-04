# -*- coding: utf-8 -*-
"""reading 技能 API（架构 v2 第 3 步）：读书页（自由阅读 + 书单）的聚合路由。

原页面只读 /api/home 这个聚合口（core 门户聚合 2 条之一，留在 preview_server.py
不动），所以这里没有可移动的业务 handler，按任务书加新聚合路由
/api/reading/home——与 /api/home 同名载荷（config + activities + booklist），
core 的 collector 经由 ctx 复用。

打卡说明：页面每日打卡（自由阅读/书单那天的读完标记）走 core 统一打卡服务
/api/checkins（skill=reading，key=标签 id）；书单逐章累计进度不是打卡，
仍走 core 的 /api/tracker（切换段再定归属）。

模块级代码不许碰数据路径：一切依赖由门户服务器启动时 bind(ctx) 注入。
"""

# —— 由 bind(ctx) 注入的共享上下文（preview_server.py 的 _skill_api_context）——
_CTX = {}


def bind(ctx):
    """门户服务器加载本模块后回调：注入共享助手。"""
    _CTX.update(ctx)


def route_get_reading_home(h):
    """读书页聚合口：门户 /api/home 的同名载荷（config + activities + booklist）。"""
    return h.send_json(_CTX["collect_home_data"]())


ROUTES = {
    ("GET", "/api/reading/home"): route_get_reading_home,
}

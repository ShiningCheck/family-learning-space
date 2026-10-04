# -*- coding: utf-8 -*-
"""daily-report 技能 API（架构 v2 第 3 步）：日报页的聚合路由。

日报是纯消费者（Q11：只读不写）：把 /api/home、/api/homework、/api/data
三个聚合口合成一个 /api/report/data。三个来源的归属：
  - home（config + activities + booklist）：core 门户聚合，collector 留在
    preview_server.py，经 ctx 复用；
  - homework（作业卡）：已移动到 subject-chinese 技能的 api.py，经
    ctx["skill_module"] 跨技能调用（两遍加载保证不受注册顺序影响）；
  - learn（学习看板 days/weekly）：core 门户聚合，经 ctx 复用。

模块级代码不许碰数据路径：一切依赖由门户服务器启动时 bind(ctx) 注入。
"""

# —— 由 bind(ctx) 注入的共享上下文（preview_server.py 的 _skill_api_context）——
_CTX = {}


def bind(ctx):
    """门户服务器加载本模块后回调：注入共享助手。"""
    _CTX.update(ctx)


def route_get_report_data(h):
    """日报页一次取齐：{home, homework, learn}（与旧页三处 fetch 的载荷一一对应）。"""
    chinese = _CTX["skill_module"]("subject-chinese")
    if chinese is not None:
        homework = chinese.collect_homework_data()
    else:
        homework = {"childName": "", "items": [], "subjects": []}
    return h.send_json({
        "ok": True,
        "home": _CTX["collect_home_data"](),
        "homework": homework,
        "learn": _CTX["collect_learn_data"](),
    })


ROUTES = {
    ("GET", "/api/report/data"): route_get_report_data,
}

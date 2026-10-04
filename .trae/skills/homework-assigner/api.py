# -*- coding: utf-8 -*-
"""homework-assigner 技能 API（架构 v2 第 3 步）：作业管理页的聚合路由。

作业管理页要同时看 chinese + math 两套作业 API（按任务书，/api/homework 系
已拆成两套、同源同行为），加一条 /api/homework/overview 聚合路由：
  - homework：作业卡数据（经 ctx["skill_module"] 调 subject-chinese 的
    collect_homework_data；chinese/math 两套同源，读同一文件）；
  - checkins：旧版作业打卡记录（core 的 collector，切换段前旧页面仍在写）；
  - learn：学习看板 days/weekly（core 的 collector）。

页面本身的打卡读写在增量段就走 core 统一打卡服务 /api/checkins
（skill=chinese/math/class/school/homework 多套合并展示）。

模块级代码不许碰数据路径：一切依赖由门户服务器启动时 bind(ctx) 注入。
"""

# —— 由 bind(ctx) 注入的共享上下文（preview_server.py 的 _skill_api_context）——
_CTX = {}


def bind(ctx):
    """门户服务器加载本模块后回调：注入共享助手。"""
    _CTX.update(ctx)


def route_get_overview(h):
    """作业管理页一次取齐：{homework, checkins, learn}。"""
    chinese = _CTX["skill_module"]("subject-chinese")
    if chinese is not None:
        homework = chinese.collect_homework_data()
    else:
        homework = {"childName": "", "items": [], "subjects": []}
    _status, checkins = _CTX["collect_homework_checkins"]()
    return h.send_json({
        "ok": True,
        "homework": homework,
        "checkins": checkins.get("records", {}),
        "learn": _CTX["collect_learn_data"](),
    })


ROUTES = {
    ("GET", "/api/homework/overview"): route_get_overview,
}

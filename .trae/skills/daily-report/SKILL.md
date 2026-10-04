---
name: daily-report
description: 日报页（架构 v2 第 3 步自 growth-home 拆出）：一天完成情况的汇总报告，纯消费者只读不写，打卡数据读 core 统一打卡服务 /api/checkins。
license: 与仓库根 LICENSE 相同
metadata:
  version: 2.0.0-dev
---

# daily-report · 日报页

架构 v2 第 3 步（拆 growth-home）新建的日报技能，url 命名空间 `report`。
日报是纯消费者（Q11）：只读不写。

## 组成

| 文件 | 作用 |
|---|---|
| `web/index.html` | 日报页（复制自 growth-home/web/report.html，fetch 改新路由） |
| `api.py` | 聚合路由（`/api/report/data` = home + homework + learn 一次取齐） |
| `data-templates/activities.json` | 匿名活动/科目配置模板 |

## API

- `GET /api/report/data`：聚合口（core 的 collector + subject-chinese 的 collect_homework_data）。
- 打卡读取：`GET /api/checkins`（core，skill=chinese/math/class/school/reading/tracker）。

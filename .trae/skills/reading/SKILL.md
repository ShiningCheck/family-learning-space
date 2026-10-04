---
name: reading
description: 读书页（架构 v2 第 3 步自 growth-home 拆出）：自由阅读 + 书单逐章进度，每日打卡走 core 统一打卡服务 /api/checkins（skill=reading）。
license: 与仓库根 LICENSE 相同
metadata:
  version: 2.0.0-dev
---

# reading · 读书页

架构 v2 第 3 步（拆 growth-home）新建的读书页技能，url 命名空间 `reading`。

## 组成

| 文件 | 作用 |
|---|---|
| `web/index.html` | 读书页（复制自 growth-home/web/reading.html，fetch 改新路由） |
| `api.py` | 聚合路由（`/api/reading/home`，与 /api/home 同名载荷） |
| `data-templates/booklist.json` | 匿名书单模板 |

## API

- `GET /api/reading/home`：门户 /api/home 同名载荷（config + activities + booklist）。
- 每日打卡：`GET/POST /api/checkins`（core，skill=reading，key=标签 id 如 reading/booklist；
  当天读了哪些章等细节作为记录扩展字段随打卡一起存）。
- 书单逐章累计进度不是打卡，仍走 core 的 `/api/tracker`（切换段再定归属）。

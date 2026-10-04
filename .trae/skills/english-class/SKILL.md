---
name: english-class
description: 辅导班英语页（架构 v2 第 3 步自 growth-home 拆出）：按周组织的辅导班单元内容，按知识点板块打卡，打卡走 core 统一打卡服务 /api/checkins（skill=class）。
license: 与仓库根 LICENSE 相同
metadata:
  version: 2.0.0-dev
---

# english-class · 辅导班英语页

架构 v2 第 3 步（拆 growth-home）新建的学科页技能，url 命名空间 `class`。

## 组成

| 文件 | 作用 |
|---|---|
| `web/index.html` | 辅导班英语页（复制自 growth-home/web/english-class.html，fetch 改新路由） |
| `api.py` | 内容路由（`/api/class/data`，自 preview_server.py 移动而来） |
| `data-templates/` | english_class.json / english_class_records.json 匿名模板 |

## API

- `GET /api/class/data`：单元内容 + 孩子姓名（技能 url=class，新路径与旧路径相同）。
- `GET /api/class/home`：门户 /api/home 同名载荷（聚合口）。
- 打卡：`GET/POST /api/checkins`（core，skill=class，key=`<单元id>:<板块id>`）；
  旧的 `POST /api/class/checkin` 属 core 打卡 6 条，留在 preview_server.py 不动。

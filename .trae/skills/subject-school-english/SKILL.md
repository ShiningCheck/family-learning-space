---
name: subject-school-english
description: 学校英语页（架构 v2 第 3 步自 growth-home 拆出）：外研社新交际英语单元内容，按内容组打卡，打卡走 core 统一打卡服务 /api/checkins（skill=school）。
license: 与仓库根 LICENSE 相同
metadata:
  version: 2.0.0-dev
---

# subject-school-english · 学校英语页

架构 v2 第 3 步（拆 growth-home）新建的学科页技能，url 命名空间 `school`。

## 组成

| 文件 | 作用 |
|---|---|
| `web/index.html` | 学校英语页（复制自 growth-home/web/school-english.html，fetch 改新路由） |
| `api.py` | 内容路由（`/api/school/data`，自 preview_server.py 移动而来） |
| `data-templates/` | school_english.json / school_english_records.json 匿名模板 |

## API

- `GET /api/school/data`：单元内容 + 孩子姓名（技能 url=school，新路径与旧路径相同）。
- `GET /api/school/home`：门户 /api/home 同名载荷（聚合口）。
- 打卡：`GET/POST /api/checkins`（core，skill=school，key=内容组 id）；
  旧的 `POST /api/school/checkin` 属 core 打卡 6 条，留在 preview_server.py 不动。

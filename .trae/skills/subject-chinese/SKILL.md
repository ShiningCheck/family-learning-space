---
name: subject-chinese
description: 语文学科页（架构 v2 第 3 步自 growth-home 拆出）：当天作业卡 + 打卡大按钮 + 一个打卡日历，打卡走 core 统一打卡服务 /api/checkins（skill=chinese）。
license: 与仓库根 LICENSE 相同
metadata:
  version: 2.0.0-dev
---

# subject-chinese · 语文学科页

架构 v2 第 3 步（拆 growth-home）新建的学科页技能，url 命名空间 `chinese`。

## 组成

| 文件 | 作用 |
|---|---|
| `web/index.html` | 语文学科页（薄配置 + 加载 `portal-core/components/subject-page.js`） |
| `api.py` | 作业卡路由（`/api/chinese/homework` 系 + legacy `/api/homework` 系，v2.1 删 legacy） |
| `data-templates/homework.json` | 匿名作业卡模板 |

## API

- `GET/POST /api/chinese/homework`、`POST /api/chinese/homework/upload`：
  handler 自 preview_server.py 注册表**移动**而来，数据路径不变
  （仍读写 `<data-root>/web/data/homework.json`，数据搬家在切换段）。
- `GET /api/chinese/home`：门户 /api/home 同名载荷（聚合口）。
- 打卡：`GET/POST /api/checkins`（core，skill=chinese，key=作业项 id）。

页面公共逻辑在 `portal-core/components/subject-page.js`（语文/数学共用，不复制两份）。

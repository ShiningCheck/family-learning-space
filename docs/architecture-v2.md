# 架构 v2 · 框架核 + 业务技能（重构方案存档）

> 本文是 2026-10-03 架构拷问（grilling）三轮决策的存档，是 v2 重构的对照基准。
> 改方案先改本文；与 `AGENTS.md` / `.trae/rules/project_rules.md` 的条目同步在重构收尾时完成。

## 0. 背景与问题

v1 的痛点（代码事实）：

- 共享层寄生：`homework-section.js`（1345 行）是全仓库共享组件却住在 growth-home 内部；
  `vendor/` 5 个库 × 5 份副本靠 `sync_vendor.py` 人工对齐。
- 服务器单体：`growth-home/web/preview_server.py` 2115 行、约 29 条路由，硬编码 5 个兄弟技能路径，
  每加一个技能都要手改公共文件——与"新需求=新技能"的规则自相矛盾。
- growth-home 一身四职：门户外壳 + 服务器内核 + 共享库 + 8 个业务页。
- 残留：school-bag-organizer、learning-growth-board 各有自己的 preview_server.py（91/152 行），
  另有 479 行的 feedback_backend.py 重复实现。

## 1. 目标

1. 大规模分发：整仓 bundle + 上架 WorkBuddy 专家库（专家包形态）。
2. 持续加功能：新需求=新技能，新增技能**零改动**公共文件（页面与 API 都自动挂载）。
3. 用户个性化：配置解决 80% + AI 生成 20%；升级不冲掉用户自建技能与数据。

## 2. 已锁定决策（三轮拷问，Q1–Q13）

| # | 决策点 | 结论 |
|---|---|---|
| Q1 | 用户与渠道 | AI 陪跑型家长优先（纯小白第二阶段）；上架 WorkBuddy 专家库 |
| Q2 | 个性化主路径 | 配置 80% + AI 生成 20%；`skill.json` v2 引入 `enabled`/`config` 概念 |
| Q3 | 分发与升级 | 整仓 bundle 为主；升级覆盖官方代码区、跳过 `origin:user` 技能；长期再考虑按需选装 |
| Q4 | 共享层形态 | 仓库根 `portal-core/`（非技能，底座）；vendor 单源由服务器 `/vendor/*` 供给；`sync_vendor.py` 退役 |
| Q5 | API 解耦 | 技能自带 `api.py`，core 启动时扫描自动注册；路由强制 `/api/<技能url>/` 命名空间 |
| Q6 | 专家库上架 | 专家包（`.codebuddy-plugin/plugin.json` + 内嵌技能）单条目上架；市场必填 frontmatter（description_zh/en、version、author）由打包器在 zip 内注入，仓库真源只写可移植字段（规则 9.3 不破） |
| Q7 | growth-home 拆分 | 每页一技能：`subject-chinese`、`subject-math`、`subject-school-english`、`english-class`、`reading`、`daily-report`；**打卡是公共能力进 core**，tracker 技能取消；`growth-home` 名字退役 |
| Q8 | 迁移策略 | 硬切 + `tools/migrate_v2.py`（dry-run/apply/rollback，仿 migrate_to_data_root.py）+ 旧 URL 重定向保留一个版本 |
| Q9 | 服务器技术栈 | FastAPI + uvicorn；`setup.py` 建 venv 装依赖；前端零外部依赖规则不受影响 |
| Q10 | 设置页 v1 | 技能开关 + 孩子档案 + 主题 + data-root 查看/迁移入口；schema 驱动表单后置 v2 |
| Q11 | 打卡数据 | core 单一 `checkins.json`（`{skill, key, date, v, ts}`，ts 取新、v:0 墓碑保留）；合并现有 tracker_state / homework_checkins / english_class_records / school_english_records 四个文件；**daily-report 是纯消费者，只读不写** |
| Q12 | 依赖安装兜底 | 在线 pip 为主（可切镜像）；离线 wheels 包后置到上架前 |
| Q13 | 重构顺序 | 5 步渐进，每步 smoke_test + privacy_guard 双绿才推进，全程门户可用 |

## 3. 目标架构

```
仓库根/
├── portal-core/              # 框架底座（不是技能）
│   ├── server/               # FastAPI + uvicorn：技能扫描、路由自动注册、/vendor/* 单源供给、静态页托管
│   ├── storage/              # Store：merge="ts" | "date-dim" | "overwrite"；同步逻辑全仓唯一一份
│   ├── checkins/             # 打卡公共能力：checkins.json + /api/checkins + 日历/明细前端组件
│   ├── services/             # 语音（/api/voice/*）、TTS（/api/tts/*）、反馈（/api/feedback/*）
│   ├── web/                  # 门户 shell：标签容器 + 今日打卡汇总区 + 设置页
│   ├── vendor/               # voice/tts/themes/feedback/pinyin-pro 唯一真源
│   ├── components/           # homework 作业卡等学科共享组件（原 homework-section.js 拆家）
│   └── VERSION
├── .trae/skills/<技能>/      # 纯业务：web 页面 + 可选 api.py + data-templates + SKILL.md + skill.json
├── tools/                    # 含新增 migrate_v2.py、upgrade.py；sync_vendor.py 退役
└── <仓库外 data-root>/       # 不动；迁移脚本负责数据搬家
```

`skill.json` v2 字段：`url`、`code`、`data`、`enabled`、`origin`（official/user）、
`requires.core`、可选 `config` schema、可选 `"api": "api.py"`。

## 4. 路由切分表（旧 → 新）

| 旧路由 | 新归属 | 新形态 |
|---|---|---|
| /api/tracker、/api/homework/checkins、/api/class/checkin、/api/school/checkin | core 打卡服务 | 统一 `GET/POST /api/checkins`（skill+date 过滤，批量 upsert，ts 合并） |
| /api/voice*（4 条）、/api/tts/status、/api/feedback*（4 条） | core 服务 | 原路径保留，实现迁入 core |
| /api/home、/api/data | core 门户聚合 | /api/portal/home，首页数据由 core 聚合各技能 |
| /api/homework(+upload) | subject-chinese / subject-math | /api/subject-chinese/homework、/api/subject-math/homework；homework.json 按科目拆两份 |
| /api/class/data | english-class | /api/english-class/data（checkin 走 core） |
| /api/school/data | subject-school-english | /api/subject-school-english/data（checkin 走 core） |
| /api/library(+upload) | home-library | /api/lib/... |
| /api/competition | competition | /api/comp/... |
| /api/art/upload | xiaoshan-art-archive | /api/art/... |
| school-bag / learn 的遗留服务器路由 | 各自技能 api.py 回收 | 统一进门户，独立服务器删除 |

旧 URL 由 core 做 301 重定向，保留一个版本后删除。

## 5. 技能 API 契约

```python
# .trae/skills/subject-chinese/api.py
from fastapi import APIRouter
from portal_core.storage import Store

router = APIRouter()
store = Store.for_skill("subject-chinese")   # 自动解析 data-root 命名空间

@router.post("/homework")
def save(payload: dict):
    store.write("homework", payload, merge="ts")
```

- `skill.json` 声明 `"api": "api.py"`；core 启动时扫描、importlib 加载、
  `include_router(router, prefix="/api/<url>")`。
- 合并规则（规则 1：ts 取新 / date+维度覆盖 / v:0 墓碑）内建在 `Store`，技能不再自写同步逻辑。
- 打卡一律走 core：`GET/POST /api/checkins`，key = `<内容块 id>`，记录带 skill 命名空间。

## 6. 重构路线（每步过 smoke_test + privacy_guard --all 双门禁）

- **第 0 步 基线**：页面/路由/数据文件清单快照存档，smoke 全绿基线。
- **第 1 步 路由注册表**：现单体内抽路由表（不改任何行为），2115 行按 §4 切块。
- **第 2 步 抽 portal-core**：vendor 单源 + components + 门户 shell + Store；旧 URL 重定向；sync_vendor 退役。
- **第 3 步 拆技能**：growth-home → 6 技能 + 各自 api.py 接管路由；migrate_v2.py 搬数据（dry-run→apply，可 rollback）。
- **第 4 步 换 FastAPI 内核**：路由契约不动，handler 平移；setup.py 增加 venv + pip 安装。
- **第 5 步 收尾**：设置页 v1 + upgrade.py + build_dist --market（专家包）+ 规则文档（AGENTS.md / project_rules）同步。

## 7. 验收线

1. 全部技能页面可打开（拆分后逐页 smoke）。
2. 两台浏览器打卡互相同步（core checkins 的 ts 合并生效）。
3. `migrate_v2.py` 的 rollback 可还原。
4. `build_dist --bundle` 与 `--market` 双包通过 `verify_dist` 与 `privacy_guard --dist`。
5. 包内翻不出任何隐私数据（规则 7/8 不破）。

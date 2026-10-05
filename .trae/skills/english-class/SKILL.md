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
| `api.py` | 内容路由（`/api/class/data`）+ 跟读评分路由 |
| `speech_eval.py` | 跟读评分引擎（本机离线：逐词对齐 + 准确/流利/完整；云端评测为可插拔可选） |
| `data-templates/` | english_class.json / english_class_records.json / speech_records.json 匿名模板 |

## API

- `GET /api/class/data`：单元内容 + 孩子姓名（技能 url=class，新路径与旧路径相同）。
- `GET /api/class/home`：门户 /api/home 同名载荷（聚合口）。
- 打卡：`GET/POST /api/checkins`（core，skill=class，key=`<单元id>:<板块id>`）；
  旧的 `POST /api/class/checkin` 属 core 打卡 6 条，留在 preview_server.py 不动。
- 跟读评分（本次新增）：
  - `POST /api/class/speech/eval`：录音 → 落盘 → 本机识别（逐词时间戳）→ 评分 → 记录；
    表单字段 `audio` / `target`（目标英文句）/ `key`（`<单元id>:<板块id>:<序号>`）/ `date` / `lang`。
  - `GET /api/class/speech/records`：取跟读记录（`?unit=<单元id>` 过滤某一课）。
  - 记录落 `class/data/speech_records.json`（同 key 按 `ts` 取新合并），音频落
    `class/data/speech/audio/<日期>/`，URL `/class/data/speech/…`，跨设备同步。

## 跟读 / 评分 / 完成情况总结 / 家长 PK

页面在单元内容下方新增两张卡：

- **🎤 跟读练习**：跟读材料＝本课「重点句型」与「课文对话」（`sections[].sentences[]` 与
  `dialogue.lines[]`，语法板块是中文讲解不跟读）。每句 🔊 听一遍 → 🎤 录音上传 →
  显示逐词对错（绿＝对、红＝错、划线＝漏读）与总分 / 准确 / 流利 / 完整四个分数。
- **📊 完成情况总结**：进度 `x/N 句`、平均最高分、累计跟读次数、累计用时，按板块分组显示完成比例，
  再附一张 **👨👩👦 家长 PK 榜**。

**家长跟读 PK（孩子一句、家长一句）**：每句都拆成两栏——
👦 **我读**（孩子）与 👨👩 **家长读**，各自录音、各自看逐词与分数；同一句两人都读过才评胜者，
分高的一侧标 👑（打平标 🤝）。总结卡把两人**加权总分**画成对比条，并给出领先句数与胜负结论。

- **key 规则**：孩子沿用原来的 `<单元id>:<板块id>:<序号>`（老记录不丢）；家长用同 key 加
  `:parent` 后缀（`clean_key` 允许冒号，服务端**无需改动**，同一套 `/api/class/speech/eval` 与合并逻辑）。
- **逐词参考照抄原文写法**（`It's` / `What's` / 大小写），与上面的原句一致；缩写展开只发生在内部比对里，
  孩子读全称（`what is`）不扣分。

评分默认**完全本机离线**（音频不出电脑）。若要在 `english_class.json` 里配 `speechEval`
（`provider` / `endpoint` / `apiKey` / `passScore`），才会优先走用户自己的云端评测服务，
失败自动回退本机。内容不许编：跟读文本一律取自真实单元内容。

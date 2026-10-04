---
name: "homework-assigner"
description: "根据前一天学习内容给孩子布置语文/数学/英语作业，生成 A4 PDF 并上线到语文/数学/辅导班学科页。当用户说「布置作业」「生成作业」「今天的作业」时调用。"
---

# 布置作业

根据**前一天**的学习内容，为孩子起草语文/数学/英语三科家庭作业，生成 A4 PDF（每科一页，方便打印给老人直接使用），并写入门户 `data/homework.json`，由门户的**学科页**（语文 / 数学 / 辅导班）展示与打卡。手动触发，不设定时。

## 目录结构

```
homework-assigner/
├── SKILL.md
├── skill.json                # 架构 v2：url=homework，声明 api.py 自动注册
├── api.py                    # /api/homework/overview 聚合路由（第 3 步新增）
├── web/
│   └── index.html            # 作业管理页（复制自 growth-home/web/homework.html，fetch 改新路由）
├── data-templates/
│   └── homework.json         # 匿名作业卡模板
└── tools/
    ├── gen_homework_pdf.py     # 读内容 JSON，生成 A4 作业 PDF
    ├── ocr_page.ps1            # 从教材页图片 OCR 提取文字（Windows 自带引擎）
    └── example_homework.json   # 作业内容 JSON 模板
```

> 架构 v2 第 3 步起，本技能同时托管「作业管理」页（url 命名空间 `homework`）：
> 页面聚合调用 chinese + math 两套 homework API，打卡读 core 的 /api/checkins。

## 数据依赖（跨技能）

- 前一天学习内容：`../learning-growth-board/data/days/*.json`（取有 `teacherReport.received` 或 `learned` 的最近一天）。
- 英语内容：`../growth-home/data/english_class.json`（`units` 最后一个 = 当前单元）。
- 教材页图片：工作区根 `textbooks/pages/{学科}/p{PDF页序号:03d}.jpg`。
- 作业数据：`../growth-home/data/homework.json`（生成后写入，供门户学科页展示与打卡）。

## 工作流程

1. 读最近一天学习看板归档，拿到前一天学了什么。
2. **语文生字**：用 `tools/ocr_page.ps1` 从教材页图片提取文字（页码换算见 `textbooks/index.json`：印刷页码 = PDF 页序号 − offset，语文/数学 offset=5），取「识字加油站 / 字词句运用」里的生字，配好带声调的拼音。
3. **英语**：取辅导班当前单元的主题句。
4. **数学**：由归档里数学 `learned` 推导成摆说题（一年级用摆说，不印书面算式）。
5. **先在对话里给用户确认内容**（写哪几个字、数学几道、英语哪几句），确认后再生成。
6. 生成 PDF：写内容 JSON（结构见 `tools/example_homework.json`），执行 `python tools/gen_homework_pdf.py <内容.json>`，输出到 `../growth-home/data/homework_pdf/<date>_homework.pdf`。
7. 上线：在 `../growth-home/data/homework.json` 的 `items` 前插入三项（语文/数学/英语各一项，`start=end=当天`），**每项都要带 `subject`**——语文 `chinese`、数学 `math`、英语 `class-english`（门户按它把作业分发到语文页 / 数学页 / 辅导班页；不填就只能出现在「作业管理」页）；每项 `media` 挂 `{ "type":"pdf", "url":"/data/homework_pdf/<date>_homework.pdf", "label":"…" }`。

## 排版约定（与孩子实际使用迭代确定，勿随意改）

- 语文：每字一行，拼音独立在田字格上方、与上一行格子不重叠（row_step=58、拼音字号 9、baseline 在格顶 +15）；第一个格印示范字，其后空田字格自动填满整行（孩子能写几遍写几遍）。
- 数学：摆说题 + 教材页图放大（约 360pt 高）。
- 英语：普通句子排版，**不用四线格**。
- 每页标「预计用时」，底部留「家长签字」；每科 ≤ 20 分钟（语文约 12、数学约 15、英语约 10）。

## 依赖

- `reportlab`（已装）、楷体 `C:\Windows\Fonts\simkai.ttf`、黑体 `simhei.ttf`。
- OCR 用 Windows 自带 OCR 引擎（需中文语言包）。
- 内容 JSON 结构见 `tools/example_homework.json`。

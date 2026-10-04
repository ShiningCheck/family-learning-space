# -*- coding: utf-8 -*-
"""新建一个「合规技能」骨架 —— 以后所有个性化需求都从这里起步。

为什么要有它：项目规则第 8 节要求「代码与隐私隔离」，并且要求
「一个新需求 = 一个新的兄弟技能」。手工新建很容易漏掉 data-templates/、
漏掉同步状态、或把个人数据写进页面，所以用脚手架保证起点是对的。

生成内容：
  .trae/skills/<name>/
  ├── SKILL.md                 # 合规 frontmatter + 隔离约定 + 怎么挂到门户
  ├── skill.json               # 声明 url 前缀 / 代码目录 / 数据目录（供 data_paths.py 解析）
  ├── DATA.md                  # 数据落在哪里（仓库之外的 data-root）
  ├── data-templates/          # 匿名模板（包里 data/ 就由它生成）
  │   ├── config.json
  │   └── state.json
  └── web/
      └── index.html           # 儿童友好页面骨架（含同步状态 + 服务器读写）
                               # 共享组件用 /vendor/ 绝对路径引用（portal-core 单源供给，不再复制副本）

用法：
  python tools/new_skill.py my-new-thing
  python tools/new_skill.py my-new-thing --title "我的新功能" --desc "当用户说……时调用"
"""
import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SKILLS_ROOT = ROOT / ".trae" / "skills"

SKILL_MD = """---
name: {name}
description: "{desc}"
agent_created: true
---

# {title}

## 这个技能做什么

（一句话说清能力，以及**什么时候**该用它 —— description 决定 AI 会不会自动调用。）

## 目录约定（不要改）

```
{name}/
├── SKILL.md            # 本文件
├── skill.json          # 声明：url 前缀 / 代码目录 / 数据目录（供 tools/data_paths.py 解析）
├── DATA.md             # 数据落在哪里（仓库之外的 data-root）
├── data-templates/     # 匿名模板：发布包里的 data/ 由它生成，**这里永远不放真实信息**
└── web/
    └── index.html      # 页面（儿童友好：大按钮、拼音、点一下才出声）
```

共享前端组件（themes/pinyin-pro/tts/voice/feedback）由门户服务器 /vendor/* 单源供给
（portal-core/vendor/，sync_vendor.py 已退役），页面一律用 /vendor/x.js 绝对路径引用，
技能里**不再**放 vendor 副本。

**真实数据不在本目录**：落在仓库之外的 data-root（`<data-root>/{name}/data/`），
路径统一走 `tools/data_paths.py`（`skill_dir("{name}")`），由 `python setup.py` 从
`data-templates/` 生成。仓库里不得存在任何 `data/` 目录。

## 硬性约定（与 .trae/rules/project_rules.md 第 8 节一致，违反就算没做完）

1. **代码/隐私隔离**：真实数据只写 data-root；代码、`SKILL.md`、页面、脚本里**不得出现**
   真实姓名、学校、班级、老师、手机号、本机绝对路径。配置一律从 data-root 的 `config.json` 读，
   缺省值写 `data-templates/config.json`。
2. **记录必须跨设备同步**：记录类数据（打卡、勾选、进度、备注……）写成 `data/state.json`，
   页面通过本地服务器的 `GET/POST /api/{name}` 读写，按 `ts`（毫秒）取新合并；
   `localStorage` 只能当断网缓存，不允许"只写本机就当保存成功"。
3. **页面要有看得见的同步状态**（☁️ 已同步 / ⚠️ 连线中）。
4. **语音双显示**：音频 + 识别文字一起留档，直接用 `/vendor/voice.js`，不要自造录音 UI。
5. **内容不许编**：页面上的文字、简介、图都来自真实输入或工作区真实文件（如 `textbooks/index.json`）。
6. **新需求不要改公共页面**：加一个兄弟技能，或用本技能自己的页面扩展，别去改别人的页面。

## 怎么挂到成长家园门户

接线走脚本、不走手改（见 project_rules.md 第 8.3 条）：

1. `python tools/portal_wire.py add-page …` —— 自动在门户加本技能的只读路由与标签项
   （数据文件指向 data-root 下本技能的 `state.json`；`list` 看现状，`undo` 回退）；
2. 接线后必须 `python tools/smoke_test.py` 冒烟 + `python tools/privacy_guard.py --all` 过关；
3. 页面里用 `/api/{name}` 读写，日期/打卡部分优先复用 `/components/homework-section.js`
   的 `HwSection.mount(...)`，不要自己再写一套日历与打卡列表。
   完整规格见 `.trae/skills/portal-builder/references/page-contract.md`。

## 首次使用引导

首次使用时按顺序问用户：孩子姓名/昵称、以及本技能需要的字段，写进 `data/config.json`
（可从 `data-templates/config.json` 复制）。**不要**把答案写进 SKILL.md 或页面。

## 发布前

```bash
python tools/privacy_guard.py --all     # 确认没有隐私外泄
python tools/build_dist.py --skills {name}
```
"""

CONFIG_TPL = {
    "childName": "小明",
    "_说明": "本技能的真实配置请写到 data/config.json（已被 .gitignore 排除）；本文件只放匿名示例。",
}

STATE_TPL = {
    "records": {},
    "updated": "",
    "_说明": "记录格式：{ \"<项id>\": { \"<日期>\": { \"v\": 1, \"ts\": 1730000000000 } } }；按 ts 取新合并，取消写 v:0。",
}

# 声明式数据布局：url 前缀 = data-root 下的命名空间；code/data 列出各自的目录。
# 服务器与 tools/data_paths.py 都按这份声明解析路径，不要在代码里硬编码。
SKILL_JSON_TPL = {
    "url": "{name}",
    "code": ["web", "SKILL.md", "data-templates"],
    "data": ["data"],
    "standalone": {"mode": "none"},
}

DATA_MD = """# {title} · 数据在哪里

本技能**不含数据目录**。真实运行数据落在仓库之外的 data-root：

    <data-root>/{name}/data/          # 本技能的数据（config、state）

- 路径解析统一走 `tools/data_paths.py`（`skill_dir("{name}")`），不要在代码里拼仓库内路径。
- 匿名模板在 `data-templates/`；`data/` 由 `python setup.py` 从模板生成，永不入库、永不参与分发。
- 页面一律通过门户服务器的 `/api/...` 读写，`localStorage` 只当断网缓存。
- 配置方式见仓库根 `local_example.json`（`data_root` 指向仓库之外的绝对路径）。
"""

PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{title}</title>
<script src="/vendor/themes.js"></script>
<script src="/vendor/pinyin-pro.js"></script>
<script src="/vendor/tts.js"></script>
<script src="/vendor/voice.js"></script>
<script src="/vendor/feedback.js"></script>
<style>
  :root {{ font-size: 18px; }}
  body {{ margin: 0; padding: 16px 16px 96px; font-family: system-ui, "Microsoft YaHei", sans-serif; }}
  h1 {{ font-size: 1.5rem; margin: 8px 0 4px; }}
  .sync {{ font-size: .85rem; opacity: .75; margin-bottom: 12px; }}
  .card {{ border: 2px solid #e6e6e6; border-radius: 14px; padding: 14px; margin: 12px 0; background: #fff; }}
  .day {{ font-size: 1.1rem; font-weight: 700; }}
  button.big {{
    width: 100%; padding: 16px; font-size: 1.15rem; font-weight: 700; border-radius: 14px;
    border: none; background: #4c8bf5; color: #fff; margin-top: 10px;
  }}
  button.big[aria-pressed="true"] {{ background: #2f9e44; }}
  .empty {{ opacity: .6; padding: 24px 0; text-align: center; }}
</style>
</head>
<body>
<h1>{title}</h1>
<div class="sync" id="sync">☁️ 连线中…</div>

<div class="card">
  <div class="day" id="today"></div>
  <div id="list" class="empty">还没有内容</div>
  <button class="big" id="mark" aria-pressed="false">今天完成</button>
</div>

<script>
// —— 服务器读写：唯一的数据出口。localStorage 只做断网兜底缓存。——
const SKILL = {name_json};
const API = '/api/' + SKILL;
let state = {{ records: {{}}, updated: '' }};
let online = false;

function ymd(d = new Date()) {{
  const p = n => String(n).padStart(2, '0');
  return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate());
}}

function setSync(text) {{ document.getElementById('sync').textContent = text; }}

async function pull() {{
  try {{
    const r = await fetch(API, {{ cache: 'no-store' }});
    if (!r.ok) throw new Error(r.status);
    state = await r.json();
    online = true;
    setSync('☁️ 已同步');
    localStorage.setItem('cache:' + SKILL, JSON.stringify(state));
  }} catch (e) {{
    online = false;
    setSync('⚠️ 暂时连不上服务器，先用本机缓存');
    try {{ state = JSON.parse(localStorage.getItem('cache:' + SKILL) || 'null') || state; }} catch (_) {{}}
  }}
  render();
}}

function isDone() {{
  const rec = state.records.today || {{}};
  return rec[ymd()] && rec[ymd()].v === 1;
}}

async function toggle() {{
  const rec = state.records.today || {{}};
  const next = {{ v: isDone() ? 0 : 1, ts: Date.now() }};
  rec[ymd()] = next;
  state.records.today = rec;
  render();
  if (!online) return;
  try {{
    const r = await fetch(API, {{
      method: 'POST', headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify({{ records: {{ today: {{ [ymd()]: next }} }} }}),
    }});
    if (r.ok) {{ state = await r.json(); setSync('☁️ 已同步'); }}
    else throw new Error(r.status);
  }} catch (e) {{ setSync('⚠️ 没存上，稍后重试'); }}
  render();
}}

function render() {{
  document.getElementById('today').textContent = ymd() + '（' + SKILL + '）';
  document.getElementById('list').className = 'empty';
  document.getElementById('list').textContent = isDone() ? '今天已完成 ✅' : '今天还没完成';
  document.getElementById('mark').textContent = isDone() ? '已完成（点一下取消）' : '今天完成';
  document.getElementById('mark').setAttribute('aria-pressed', String(isDone()));
}}

document.getElementById('mark').addEventListener('click', toggle);
document.addEventListener('visibilitychange', () => {{ if (!document.hidden) pull(); }});
setInterval(pull, 15000);
pull();
</script>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser(description="新建合规技能骨架")
    ap.add_argument("name", help="技能名：小写字母+连字符（如 book-review）")
    ap.add_argument("--title", help="页面标题（默认取技能名）")
    ap.add_argument("--desc", help="description（决定 AI 何时调用，建议写清触发场景）")
    args = ap.parse_args()

    name = args.name.strip()
    if not re.match(r"^[a-z0-9-]+$", name) or name.startswith("-") or name.endswith("-") or "--" in name:
        print(f"[失败] 技能名 '{name}' 必须是「小写字母+数字+连字符」，不能以连字符开头/结尾或连续连字符")
        return 2
    dst = SKILLS_ROOT / name
    if dst.exists():
        print(f"[失败] 技能已存在：{dst}")
        return 2

    title = args.title or name
    desc = args.desc or f"{title}：（写清这个技能做什么，以及用户说什么话时该调用它。）"

    (dst / "data-templates").mkdir(parents=True)
    (dst / "web").mkdir(parents=True)

    # newline="\n"：SKILL.md 的 frontmatter 必须用 LF（CRLF 会让平台校验判为格式非法）
    (dst / "SKILL.md").write_text(
        SKILL_MD.format(name=name, title=title, desc=desc), encoding="utf-8", newline="\n")
    skill_json = {k: (name if v == "{name}" else v) for k, v in SKILL_JSON_TPL.items()}
    (dst / "skill.json").write_text(
        json.dumps(skill_json, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    (dst / "DATA.md").write_text(
        DATA_MD.format(name=name, title=title), encoding="utf-8", newline="\n")
    (dst / "data-templates" / "config.json").write_text(
        json.dumps(CONFIG_TPL, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    (dst / "data-templates" / "state.json").write_text(
        json.dumps(STATE_TPL, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    (dst / "web" / "index.html").write_text(
        PAGE.format(name_json=json.dumps(name), title=title), encoding="utf-8", newline="\n")

    print(f"[完成] 已生成 .trae/skills/{name}/")
    print("  SKILL.md                    技能说明（含隔离约定与挂载步骤）")
    print("  skill.json                  声明 url 前缀 / 代码目录 / 数据目录")
    print("  DATA.md                     数据落在哪里（仓库之外）")
    print("  data-templates/config.json  匿名配置模板")
    print("  data-templates/state.json   记录模板（按 ts 合并）")
    print(f"  web/index.html              页面骨架（含同步状态 + /api/{name} 读写，共享组件走 /vendor/ 单源）")
    print("\n接下来：")
    print(f"  1) python tools/portal_wire.py add-page …   # 把本技能页面接进门户（路由 + 标签）")
    print(f"  2) 数据落在 <data-root>/{name}/data/，由 python setup.py 生成，别在仓库里建 data/")
    print(f"  3) 自测：python tools/smoke_test.py && python tools/privacy_guard.py --all")
    print(f"     打包：python tools/build_dist.py --skills {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

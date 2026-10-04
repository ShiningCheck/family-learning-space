# -*- coding: utf-8 -*-
"""一键打包发布：把「技能 + 网页框架」打成可直接分发的包，并保证包里没有个人隐私。

设计原则（与 .trae/rules/project_rules.md 第 8 节一致）：
  1. **白名单取件**：只主动收集该发的东西（SKILL.md / web/ / data-templates/ …），
     真实数据目录 data/ 永远不参与复制 —— 不是"复制后删掉"，而是根本不去读。
  2. **模板重建 data/**：包里的 data/ 由 data-templates/ 生成，新用户拿到就是匿名可跑。
  3. **出包即自检**：调用 privacy_guard 扫包内全部文本成员（含解开 zip），命中即中止并删包。
  4. **frontmatter 归一**：`***` → `---`、name 去引号、补 `agent_created: true`。

用法：
  python tools/build_dist.py                                  # 门户全套（默认技能集合）
  python tools/build_dist.py --skills school-bag-organizer     # 只打一个技能包
  python tools/build_dist.py --bundle                          # 整仓发布包（技能 + 框架 + 安装器）
  python tools/build_dist.py --bundle --name 家庭学习空间
  python tools/build_dist.py --skills growth-home --no-guard   # 跳过自检（不建议）
"""
import argparse
import json
import os
import re
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SKILLS_ROOT = ROOT / ".trae" / "skills"
DIST = ROOT / "dist"

sys.path.insert(0, str(HERE))
import privacy_guard as pg  # noqa: E402
import data_paths  # noqa: E402

# 门户默认要一起发的技能（页面互相跳转，缺一个就有死链）
# 架构 v2：growth-home 是服务器壳 + 门户聚合，学科/读书/日报已拆成独立技能
DEFAULT_SKILLS = [
    "growth-home", "portal-builder", "learning-growth-board", "school-bag-organizer",
    "home-library", "xiaoshan-art-archive", "homework-assigner", "voice-dubbing",
    "competition", "subject-chinese", "subject-math", "english-class",
    "subject-school-english", "reading", "daily-report",
]

# 整仓发布包里要带的仓库级文件（白名单）
BUNDLE_ROOT_FILES = ["setup.py", "VERSION", "README.md", "LICENSE", "AGENTS.md",
                     ".gitignore", "local_example.json"]
# 仓库根目录里要一起发的目录：目前没有（原 school/ 的能力清单已迁到
# <data-root>/learn/capability-lists/，属个人数据、不随包分发）
BUNDLE_ROOT_DIRS = []
# 跨 app 复用入口（见 AGENTS.md 第 9 条与 docs/agent-interop.md）：
# 规则与薄入口必须随包一起发出去，否则接收方用 WorkBuddy/Claude Code 打开时读不到规则。
BUNDLE_EXTRA_FILES = [".codebuddy/CODEBUDDY.md", "CLAUDE.md"]
BUNDLE_EXTRA_DIRS = [".trae/rules", "docs"]
BUNDLE_TOOLS_FILES = ["README.md", "privacy_guard.py", "build_dist.py", "verify_dist.py", "new_skill.py",
                      "portal_wire.py", "smoke_test.py",
                      "data_paths.py", "migrate_to_data_root.py", "migrate_v2.py", "upgrade.py",
                      "find_books.py", "filter_books.py", "download_books.py",
                      "download_rest.py", "split_pages.py", "build_meta.py", "build_index.py"]
BUNDLE_TOOLS_DIRS = ["git-hooks"]
BUNDLE_TEXTBOOK_META = ["index.json", "book_meta.json", "manifest.json"]

# 技能目录内永远不发的东西
SKILL_EXCLUDE_DIR_NAMES = {"data", "__pycache__", "node_modules", ".git", "output", "images", "audio", ".ipynb_checkpoints"}
SKILL_EXCLUDE_EXT = {".pyc", ".pyo", ".log", ".swp"}
SKILL_EXCLUDE_NAME = {".DS_Store", "Thumbs.db", "desktop.ini"}

LOG = []


def log(msg):
    LOG.append(str(msg))
    print(msg)


# —— frontmatter 归一 ——
def normalize_frontmatter(text, fallback_name):
    changed = []
    if text.startswith("***"):
        text = "---" + text[3:]
        changed.append("*** -> ---")
    m = re.match(r"^---\s*\n(.*?)\n-{3,}\s*\n", text, re.DOTALL)
    if not m:
        return None, ["未找到 YAML frontmatter（SKILL.md 必须以 --- 开头）"]
    front = m.group(1)
    rest = text[m.end():]

    # name 去引号（注意：不能用 \s*$，那会把换行一起吃掉，导致 YAML 两行粘在一起）
    new_front, n_sub = re.subn(r'^(name:[^\S\n]*)"([^"]+)"[^\S\n]*$', r"\1\2",
                               front, flags=re.MULTILINE)
    if n_sub:
        front = new_front
        changed.append("name 去引号")
    if not re.search(r"^name:", front, re.MULTILINE):
        front = f"name: {fallback_name}\n" + front
        changed.append("补 name")
    if not re.search(r"^agent_created:", front, re.MULTILINE):
        front = front.rstrip("\n") + "\nagent_created: true"
        changed.append("补 agent_created")
    return f"---\n{front}\n---\n{rest}", changed


def stage_skill(skill, stage_root: Path):
    """把一个技能按白名单复制到 stage_root/<skill>/，data/ 用 data-templates/ 重建。"""
    src = SKILLS_ROOT / skill
    if not src.is_dir():
        log(f"  [跳过] 技能不存在：{skill}")
        return 0
    dst = stage_root / skill
    copied = 0
    for dirpath, dirnames, filenames in os.walk(src):
        dirnames[:] = [d for d in dirnames if d not in SKILL_EXCLUDE_DIR_NAMES]
        for fn in filenames:
            f = Path(dirpath) / fn
            rel = f.relative_to(src)
            target = dst / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, target)
            copied += 1

    # data/ 用模板重建（模板不存在时留空目录 + 说明）
    tpl = src / "data-templates"
    data_dir = dst / "data"
    if tpl.is_dir():
        shutil.copytree(tpl, data_dir, dirs_exist_ok=True)
        n = sum(1 for _ in data_dir.rglob("*") if _.is_file())
        log(f"  [模板] {skill}/data/ 由 data-templates/ 生成（{n} 个文件）")
        copied += n
    else:
        data_dir.mkdir(parents=True, exist_ok=True)
        if (src / "data").is_dir():
            log(f"  [警告] {skill} 有 data/ 但没有 data-templates/ —— 包内 data/ 只能留空")
            log("         → 按项目规则第 8 节，有真实数据的技能必须配 data-templates/（匿名模板）")
        else:
            log(f"  [跳过] {skill} 无持久数据（既没有 data/ 也没有 data-templates/），包里 data/ 留空")

    # SKILL.md frontmatter 归一
    skill_md = dst / "SKILL.md"
    if skill_md.exists():
        text = skill_md.read_text(encoding="utf-8")
        fixed, changed = normalize_frontmatter(text, skill)
        if fixed is None:
            log(f"  [错误] {skill}/SKILL.md {changed[0]}")
            return -1
        if changed:
            # newline="\n"：Windows 上默认会把换行写成 CRLF，而 SKILL.md 的 frontmatter
            # 校验（quick_validate / 平台解析）按 "---\n" 匹配，CRLF 会直接判为格式非法
            skill_md.write_text(fixed, encoding="utf-8", newline="\n")
            log(f"  [frontmatter] {skill}/SKILL.md：" + "、".join(changed))
    else:
        log(f"  [错误] {skill} 缺少 SKILL.md")
        return -1
    log(f"  [打包] {skill}：{copied} 个文件")
    return copied


def stage_skill_package(skills):
    """单/多技能包：stage 里直接放技能目录。"""
    stage = DIST / "_stage"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    for s in skills:
        if stage_skill(s, stage) < 0:
            return None
    return stage


# ----------------------------------------------------------------------
# WorkBuddy 专家包（--market）：.codebuddy-plugin/plugin.json + agents/ + avatars/
# + skills/（内嵌 AI 技能）。格式见 https://open.workbuddy.cn/docs/expert
# ----------------------------------------------------------------------
MARKET_PLUGIN_NAME = "family-learning-space"
MARKET_AGENT_FILE = "family-learning-assistant.md"

MARKET_PLUGIN_JSON = """{
  "name": "family-learning-space",
  "version": "{version}",
  "description": "Builds and customizes a family learning space website for parents with young children: homework check-ins, reading, English, art archive, school-bag checklist, all cross-device synced, extendable with AI-generated skills.",
  "author": { "name": "{author_name}", "email": "{author_email}" },
  "agents": ["./agents/family-learning-assistant.md"],
  "expertType": "agent",
  "agentName": "family-learning-assistant",
  "displayName": { "en": "Family Learning Assistant", "zh": "家庭学习助手" },
  "profession": { "en": "Family Learning Space Builder", "zh": "家庭教育空间搭建专家" },
  "displayDescription": {
    "en": "Builds and customizes a private learning website for your child: homework check-ins, reading, English, art and school-bag checklists in one place, synced across devices, extensible with AI-generated skills.",
    "zh": "帮家长搭建孩子的专属学习网站，作业打卡、读书、英语、画作、书包清单一站管理，跨设备同步"
  },
  "avatar": "avatars/expert.png",
  "categoryId": "15-Education",
  "defaultInitPrompt": { "en": "Help me set up my family learning space", "zh": "帮我初始化家庭学习空间" },
  "plugin": "family-learning-space",
  "tags": [
    { "en": "Family Education", "zh": "家庭教育" },
    { "en": "Learning Check-in", "zh": "学习打卡" },
    { "en": "Website Building", "zh": "网站搭建" }
  ],
  "quickPrompts": [
    { "en": "Help me set up my family learning space", "zh": "帮我初始化家庭学习空间" },
    { "en": "Add a new check-in feature for my child", "zh": "给孩子加一个新的打卡功能" },
    { "en": "Assign today's homework", "zh": "布置今天的作业" }
  ],
  "skills": [{skills}]
}
"""

MARKET_AGENT_MD = """---
name: family-learning-assistant
description: Helps parents set up, configure, use and extend a family learning space website for their children
displayName:
  en: "Family Learning Assistant"
  zh: "家庭学习助手"
profession:
  en: "Family Learning Space Builder"
  zh: "家庭教育空间搭建专家"
---

# 家庭学习助手

你是「家庭学习空间」的搭建助手，帮家长把这个仓库跑起来、用起来、改起来。

## 这个系统是什么

一个给家长陪伴小学孩子用的工具集：本地网站是学习看板（作业打卡、读书、英语、画作、书包清单……），
多设备同 WiFi 访问同一份数据；每个能力是一个「技能」，放在 `.trae/skills/<技能名>/` 下。

## 你帮家长做什么

1. **初始化**：引导家长 `python setup.py`，填孩子信息、选数据区（必须是仓库之外的目录）。
2. **使用**：启动门户 `python .trae/skills/growth-home/web/preview_server.py`，手机/平板同 WiFi 访问。
3. **加功能**：一个个性化需求 = 一个新技能，用 `python tools/new_skill.py <名字>` 生成合规骨架，
   再用 `python tools/portal_wire.py add-page …` 接进门户，最后 `python tools/smoke_test.py` 冒烟。
4. **答疑**：解释打卡为什么跨设备同步、数据存在哪、怎么补打卡、怎么改教材版本。

## 铁律（不可违反）

- 孩子的隐私数据（姓名、学校、课表、打卡、录音、画作）一律落**仓库之外**的 data-root，
  仓库里不得出现任何 `data/` 目录；改动后跑 `python tools/privacy_guard.py --all`。
- 内容来自真实输入，不许编造；教材页图来自教材库，页码映射读 `textbooks/index.json`，不硬编码。
- 记录必须跨设备同步：打卡、进度都落服务器上的 `data/*.json`，`localStorage` 只是断网缓存。
- 语音必须「音频 + 文字」双显示，用 `web/vendor/voice.js`。

## 输出规范

- 用中文回答家长；命令给可直接复制的 PowerShell 语句。
- 改动代码后提醒家长跑冒烟 `python tools/smoke_test.py` 与隐私守卫 `python tools/privacy_guard.py --all`。
"""

MARKET_README = """# 家庭学习空间 · WorkBuddy 专家

这是一个可上架 WorkBuddy 专家市场的「家庭学习空间」专家包：

- `agents/family-learning-assistant.md` —— 专家系统提示词（帮家长搭建/使用/扩展学习网站）
- `skills/` —— 内嵌的全部 AI 技能（作业打卡、读书、英语、画作、书包清单、日报、比赛……）
- `.codebuddy-plugin/plugin.json` —— 专家配置（展示名、描述、标签、快捷提示词、行业分类）

## 上架前必做（否则会被退）

用一条命令重新打包即可，作者信息和头像都会自动填好：

```bash
python tools/build_dist.py --market --author "你的名字" --email "you@example.com" --avatar "C:\\path\\to\\expert.png"
```

- **头像** `avatars/expert.png`：512×512 方形 PNG/JPG，≤500KB，漫画/插画风格（`--avatar` 传入）。
- **作者**：`author.name` / `author.email`（`--author` / `--email` 传入，上架必填）。
- **文案**：`plugin.json` 的 `displayName` / `profession` / `displayDescription`（中文 40-50 字）
  / `tags`（3 个）/ `quickPrompts`（3 个）已按规范写好，想改就编辑 `tools/build_dist.py` 里的常量。

打包后把 zip 在开放平台 **open.workbuddy.cn** 提交即可（技能市场与专家市场同一入口）。

## 注意

这个专家包只含「AI 技能 + 专家提示词」，**不含本地网站框架**（portal-core、服务器、安装器）。
网站框架通过整仓包分发：`python tools/build_dist.py --bundle`。
家长要真正跑起网站，仍需整仓包（或 git 仓库）+ `python setup.py`；专家负责引导和答疑。
"""


def stage_market(skills, version, author_name, author_email, avatar_path):
    """专家包：.codebuddy-plugin/plugin.json + agents/ + avatars/ + skills/（内嵌）。"""
    stage = DIST / "_stage"
    if stage.exists():
        shutil.rmtree(stage)
    # 顶层目录名由 zip_stage 的 top_name 决定（main 里传 MARKET_PLUGIN_NAME），
    # 这里不重复加一层，避免 family-learning-space/family-learning-space 双重嵌套。
    top = stage
    top.mkdir(parents=True)

    # plugin.json
    skills_json = ", ".join('"./skills/%s"' % s for s in skills)
    plugin = (MARKET_PLUGIN_JSON
              .replace("{version}", version)
              .replace("{skills}", skills_json)
              .replace("{author_name}", author_name.replace('"', "'"))
              .replace("{author_email}", author_email.replace('"', "'")))
    pd = top / ".codebuddy-plugin"
    pd.mkdir(parents=True)
    (pd / "plugin.json").write_text(plugin, encoding="utf-8", newline="\n")
    log("  [专家] .codebuddy-plugin/plugin.json（作者：%s <%s>）" % (
        author_name or "（空！上架前必须填）", author_email or "（空！上架前必须填）"))

    # agents/
    ad = top / "agents"
    ad.mkdir(parents=True)
    (ad / MARKET_AGENT_FILE).write_text(MARKET_AGENT_MD, encoding="utf-8", newline="\n")
    log("  [专家] agents/" + MARKET_AGENT_FILE)

    # avatars/：给了 --avatar 就用真图，否则放占位说明（上架会被退）
    av = top / "avatars"
    av.mkdir(parents=True)
    av_src = Path(avatar_path) if avatar_path else None
    if av_src and av_src.is_file():
        ext = av_src.suffix.lower() or ".png"
        target = av / ("expert" + ext)
        shutil.copy2(av_src, target)
        size_kb = target.stat().st_size / 1024
        log("  [专家] avatars/expert%s（%.0f KB）" % (ext, size_kb))
        if size_kb > 500:
            log("  [警告] 头像超过 500KB，上架可能被拒；请压缩到 ≤500KB、512×512。")
        if ext != ".png":
            log("  [提示] 官方推荐 PNG；当前是 %s，必要时换成 PNG。" % ext)
        # plugin.json 里的 avatar 路径固定写 avatars/expert.png，若换了扩展名要同步
        if ext != ".png":
            plugin = plugin.replace('"avatar": "avatars/expert.png"',
                                    '"avatar": "avatars/expert%s"' % ext)
            (pd / "plugin.json").write_text(plugin, encoding="utf-8", newline="\n")
    else:
        (av / "README.md").write_text(
            "# 请替换 expert.png\n\n放入 512×512 方形 PNG/JPG（≤500KB），文件名为 expert.png。\n"
            "或用 `python tools/build_dist.py --market --avatar <图片路径>` 直接打包进去。\n",
            encoding="utf-8", newline="\n")
        log("  [警告] 未提供 --avatar：avatars/ 只有占位说明，**上架会被退**")

    # skills/（内嵌 AI 技能）
    skd = top / "skills"
    skd.mkdir(parents=True)
    for s in skills:
        if stage_skill(s, skd) < 0:
            return None

    (top / "README.md").write_text(MARKET_README, encoding="utf-8", newline="\n")
    log("  [专家] README.md")
    return stage


def write_market_test(zip_path, author):
    """把已打好的专家包解成「WorkBuddy 可直接测试」的目录：本地市场外壳 + 测试说明。

    产出 dist/workbuddy-test/：
      .codebuddy-plugin/marketplace.json   本地市场清单（登记插件为可安装项）
      <插件名>/                            专家包本体（= 将提交的 zip 解包内容，逐字节一致）
      开始测试.md                          测试步骤
    """
    out = DIST / "workbuddy-test"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(out)
    mdir = out / ".codebuddy-plugin"
    mdir.mkdir(parents=True, exist_ok=True)
    market_name = MARKET_PLUGIN_NAME + "-local"
    market = {
        "name": market_name,
        "owner": {"name": author or "local"},
        "plugins": [{
            "name": MARKET_PLUGIN_NAME,
            "source": "./" + MARKET_PLUGIN_NAME,
            "description": "家庭学习空间：帮家长搭建孩子的专属学习网站（本地测试版）",
        }],
    }
    (mdir / "marketplace.json").write_text(
        json.dumps(market, ensure_ascii=False, indent=2), encoding="utf-8")

    readme = """# WorkBuddy 本地测试（家庭学习空间 · 专家包）

这是**专供本地测试**的目录，内容与将提交的专家包**完全一致**，只多了一层「本地市场」外壳。
测试完请删掉本目录，**不要上传**（要提交的是 dist/家庭学习空间-专家包.zip）。

```
workbuddy-test/
├── .codebuddy-plugin/marketplace.json   # 本地市场清单
├── %(plugin)s/                          # 专家包本体（= 将提交的 zip 解包内容）
└── 开始测试.md
```

## 方式一：本地市场安装（推荐，最接近上架体验）

在 WorkBuddy 的对话框里依次输入（下面用本目录的绝对路径）：

```
/plugin marketplace add %(dir)s
/plugin install %(plugin)s@%(market)s
/reload-plugins
```

装好后：
- `/plugin` 的「已安装」里能看到 `%(plugin)s`
- 专家 agent：**家庭学习助手**（在 `/agents` 里）
- 技能以命名空间调用，如 `/%(plugin)s:growth-home`

卸载：`/plugin uninstall %(plugin)s@%(market)s`

## 方式二：直接加载插件目录（免安装，改完即测）

在终端（PowerShell）：

```powershell
codebuddy --plugin-dir "%(plugindir)s"
```

启动后 `/reload-plugins` 可热加载改动。

## 重点验证什么

1. 专家能被召唤、认得职责（引导家长初始化、答疑、加新功能）
2. 15 个技能都被识别（技能数 = 15）
3. 头像、展示名、描述显示正常
4. 试着问「帮我初始化家庭学习空间」，看回答是否贴合（应引导 `python setup.py` 等）

## 测试通过后

把 `dist/家庭学习空间-专家包.zip` 上传到 open.workbuddy.cn。
""" % {
        "plugin": MARKET_PLUGIN_NAME,
        "dir": str(out),
        "plugindir": str(out / MARKET_PLUGIN_NAME),
        "market": market_name,
    }
    (out / "开始测试.md").write_text(readme, encoding="utf-8", newline="\n")
    log("  [测试] %s（本地市场 + 插件目录，可直接在 WorkBuddy 里加载）" % out)
    return out


INTRO = """# 开始使用

这个包里是「家庭学习空间」的完整内容：技能（Skill）+ 网页框架 + 本地服务器 + 安装器。
**代码与数据是物理分开的**：这个包只含代码与匿名模板，你的真实数据会落在包**之外**的一个目录里。

## 一、配置你自己的信息（30 秒）

```bash
python setup.py
```

向导会先问你「数据区（data-root）放在哪」——必须是**仓库/解压目录之外**的绝对路径
（例如 `D:\\\\Shan_Learn-data`）。之后你的孩子信息、打卡、录音、画作、教材页图全部只落在这个目录里。
答案只写进 `local.json`（已加入 .gitignore）与数据区 —— **都不会外传**。

## 二、启动网页服务

```bash
python .trae/skills/growth-home/web/preview_server.py
```

- 电脑：打开 http://localhost:8090/
- 手机/平板：与电脑连同一个 WiFi，打开 http://<电脑IP>:8090/ （启动时会打印地址）

不想开服务也能用：部分页面支持导出单文件离线版（如书包清单 `build_standalone.js`）。

## 三、数据放在哪（重要）

- **代码**（技能、页面、脚本）是公开的、可分享的；解压出来就是这个包。
- **数据**（打卡、录音、画作、课表、教材页图）只在你本机的 **data-root**（仓库之外），
  布局与网页结构同构：`web/ learn/ bag/ art/ lib/ comp/ textbooks/ personal/`（`personal/` 放隐私词表）。
- 数据区路径由 `local.json` 的 `data_root` 指定，统一走 `tools/data_paths.py` 解析；
  **仓库内不存在任何 `data/` 目录**（`privacy_guard.py --all` 会断言这一点）。
- 手机/平板/电脑看到的是同一份数据，因为它存在你电脑上的数据区里，页面通过本地服务器读写。

## 四、想加自己的功能？让 WorkBuddy 新建一个技能

不要直接改公共页面，按项目约定：**一个个性化需求 = 一个新的兄弟技能**。

```bash
python tools/new_skill.py my-new-thing --title 我的新功能
```

它会生成合规骨架（`SKILL.md` + `skill.json` + `DATA.md` + `data-templates/` + `web/`），
其中 `skill.json` 声明该技能的 URL 前缀与数据目录，门户服务器会自动挂载，无需手改服务器。

## 五、发布前自检

```bash
python tools/privacy_guard.py --all      # 隐私 + 架构断言（仓库内不得有 data/）
python tools/build_dist.py               # 打包（打包器自己会再查一遍，命中就中止）
```
"""


def stage_bundle(skills, name):
    """整仓包：stage 根下直接铺开，顶层目录名由 zip_stage 的 top_name 决定。"""
    stage = DIST / "_stage"
    if stage.exists():
        shutil.rmtree(stage)
    top = stage
    top.mkdir(parents=True)

    for f in BUNDLE_ROOT_FILES:
        src = ROOT / f
        if src.is_file():
            shutil.copy2(src, top / f)
            log(f"  [根文件] {f}")
    for d in BUNDLE_ROOT_DIRS:
        src = ROOT / d
        if src.is_dir():
            shutil.copytree(src, top / d, dirs_exist_ok=True)
            log(f"  [根目录] {d}/")
    for f in BUNDLE_EXTRA_FILES:
        src = ROOT / f
        if src.is_file():
            dst = top / f
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            log(f"  [入口] {f}")
    for d in BUNDLE_EXTRA_DIRS:
        src = ROOT / d
        if src.is_dir():
            shutil.copytree(src, top / d, dirs_exist_ok=True)
            log(f"  [入口] {d}/")
    # portal-core 框架核（架构 v2 第 2 步）：vendor 单源 + 共享组件 + 门户 shell + Store，
    # 必须随包一起发出去，否则接收方的门户起不来。
    pc_src = ROOT / "portal-core"
    if not pc_src.is_dir():
        log("  [失败] 缺少 portal-core/ —— 框架核必须随整仓包分发")
        return None
    pc_dst = top / "portal-core"
    shutil.copytree(pc_src, pc_dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    log(f"  [框架核] portal-core/（{sum(1 for f in pc_dst.rglob('*') if f.is_file())} 个文件）")
    tools_dir = top / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    for f in BUNDLE_TOOLS_FILES:
        src = ROOT / "tools" / f
        if src.is_file():
            shutil.copy2(src, tools_dir / f)
    for d in BUNDLE_TOOLS_DIRS:
        src = ROOT / "tools" / d
        if src.is_dir():
            shutil.copytree(src, tools_dir / d, dirs_exist_ok=True)
    log(f"  [工具] tools/（{len(BUNDLE_TOOLS_FILES)} 个脚本 + git-hooks/）")

    # 项目规则也要发出去：接收方的 AI 得按同一套隔离约定继续开发
    rules_src = ROOT / ".trae" / "rules"
    if rules_src.is_dir():
        rules_dst = top / ".trae" / "rules"
        rules_dst.mkdir(parents=True, exist_ok=True)
        for f in sorted(rules_src.glob("*.md")):
            shutil.copy2(f, rules_dst / f.name)
        log(f"  [规则] .trae/rules/（{len(list(rules_src.glob('*.md')))} 个规则文件）")

    # 教材只带映射元数据，不带 PDF / 页图（版权与体积原因）。
    # 教材库现在落在仓库之外的 data-root（tools/data_paths.py 的 textbooks_dir()）。
    try:
        tb_src = data_paths.textbooks_dir()
    except Exception:  # noqa: BLE001
        tb_src = ROOT / "textbooks"
    if tb_src.is_dir():
        tb_dst = top / "textbooks"
        tb_dst.mkdir(parents=True, exist_ok=True)
        for f in BUNDLE_TEXTBOOK_META:
            if (tb_src / f).is_file():
                shutil.copy2(tb_src / f, tb_dst / f)
        log("  [教材] 只带 index.json / book_meta.json（页图请用 tools/ 的下载脚本自行获取）")

    # 技能
    skills_dir = top / ".trae" / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    for s in skills:
        if stage_skill(s, skills_dir) < 0:
            return None

    (top / "开始使用.md").write_text(INTRO, encoding="utf-8", newline="\n")
    log("  [说明] 生成 开始使用.md")
    return stage


def zip_stage(stage: Path, zip_path: Path, top_name=None):
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(stage.rglob("*")):
            if not f.is_file():
                continue
            arc = f.relative_to(stage)
            if top_name:
                arc = Path(top_name) / arc
            zf.write(f, str(arc).replace("\\", "/"))
    return zip_path


def check(zip_path, skip_guard):
    if skip_guard:
        log("\n[自检] 已按 --no-guard 跳过（不建议用于对外分发）")
        return True
    words, words_path = pg.load_words()
    if not words:
        log(f"\n[自检] 注意：敏感词表 {words_path} 不存在或为空，只做路径/手机号/身份证/本机路径检查")
    problems = pg.check_zip(zip_path, words, zip_path.name)
    if problems:
        log(f"\n[自检] 拦截：发布包里发现 {len(problems)} 处风险")
        for p in problems[:40]:
            log("  - " + p)
        if len(problems) > 40:
            log(f"  ...（另有 {len(problems) - 40} 处）")
        zip_path.unlink(missing_ok=True)
        log("  → 已删除该发布包。请清理后重打。")
        return False
    log(f"\n[自检] 通过：包内未发现敏感词 / 手机号 / 身份证 / 本机绝对路径（敏感词 {len(words)} 个）")
    return True


def assert_repo_clean():
    """打包前断言：仓库内不得存在数据目录（数据必须已迁到 data-root）。
    这是「代码与隐私物理隔离」的硬门槛——仓库不干净就不该出包。"""
    try:
        leftovers = data_paths.repo_data_dirs()
    except Exception as exc:  # noqa: BLE001
        log(f"[失败] 无法检查仓库数据目录：{exc}")
        return ["data_paths 检查失败"]
    if not leftovers:
        return []
    log("\n[失败] 仓库内仍存在数据目录，打包中止：")
    for p in leftovers:
        try:
            rel = p.relative_to(ROOT)
        except ValueError:
            rel = p
        log(f"  - {rel}/")
    log("  数据必须落在仓库之外的 data-root：")
    log("    python tools/migrate_to_data_root.py --data-root <仓库外路径> --apply")
    log("  迁移并验收后：python tools/migrate_to_data_root.py --data-root <仓库外路径> --cleanup")
    return [str(p) for p in leftovers]


def main():
    ap = argparse.ArgumentParser(description="把技能与网页框架打成可分发、无隐私的包")
    ap.add_argument("--skills", help="逗号分隔的技能名（默认门户全套）")
    ap.add_argument("--bundle", action="store_true", help="打整仓发布包（技能 + 框架 + 安装器）")
    ap.add_argument("--market", action="store_true", help="打 WorkBuddy 专家包（plugin.json + agents + skills）")
    ap.add_argument("--author", default="", help="专家包作者名（上架必填，写进 plugin.json）")
    ap.add_argument("--email", default="", help="专家包作者邮箱（上架必填，写进 plugin.json）")
    ap.add_argument("--avatar", default="", help="专家头像图片路径（512×512 PNG/JPG，≤500KB）")
    ap.add_argument("--market-test", action="store_true",
                    help="配合 --market：额外产出 dist/workbuddy-test/（本地市场 + 插件目录，供本机测试）")
    ap.add_argument("--name", default="家庭学习空间", help="整仓包的顶层目录名 / zip 名")
    ap.add_argument("--out", help="zip 文件名（不含路径，默认按技能或 --name 命名）")
    ap.add_argument("--no-guard", action="store_true", help="跳过隐私自检（不建议）")
    args = ap.parse_args()

    DIST.mkdir(exist_ok=True)
    skills = [s.strip() for s in args.skills.split(",")] if args.skills else DEFAULT_SKILLS
    log(f"[打包] 根目录：{ROOT}")
    log(f"[打包] 技能：{'、'.join(skills)}（{'专家包' if args.market else ('整仓发布包' if args.bundle else '技能包')}）\n")

    if assert_repo_clean():
        log("\n[失败] 打包中止，未生成发布包。")
        (DIST / "_build_report.txt").write_text("\n".join(LOG), encoding="utf-8")
        return 1

    if args.market:
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip() if (ROOT / "VERSION").is_file() else "2.0.0"
        stage = stage_market(skills, version, args.author, args.email, args.avatar)
        top_name = MARKET_PLUGIN_NAME
        default_zip = "家庭学习空间-专家包.zip"
    elif args.bundle:
        stage = stage_bundle(skills, args.name)
        top_name = None
        if stage:
            top_name = args.name
        default_zip = f"{args.name}.zip"
    else:
        stage = stage_skill_package(skills)
        top_name = None
        default_zip = (f"{skills[0]}.zip" if len(skills) == 1 else "家庭学习空间-技能包.zip")

    if stage is None:
        log("\n[失败] 打包中止，未生成发布包。")
        (DIST / "_build_report.txt").write_text("\n".join(LOG), encoding="utf-8")
        return 1

    zip_name = args.out or default_zip
    zip_path = DIST / zip_name
    zip_stage(stage, zip_path, top_name)
    size_mb = zip_path.stat().st_size / 1024 / 1024
    n_files = sum(1 for f in stage.rglob("*") if f.is_file())
    log(f"\n[产物] {zip_path}（{n_files} 个文件，{size_mb:.1f} MB）")

    ok = check(zip_path, args.no_guard)
    if ok and args.market and args.market_test:
        write_market_test(zip_path, args.author)
    shutil.rmtree(stage, ignore_errors=True)
    log(f"[打包] 时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  结果：{'成功' if ok else '被自检拦截'}")
    (DIST / "_build_report.txt").write_text("\n".join(LOG), encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

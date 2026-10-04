# tools/ 工具脚本说明

工具分四类：**隔离与发布**、**新技能脚手架**、**教材下载管线**、**共享资源同步**。
约定见 `.trae/rules/project_rules.md` 第 8 节（代码与隐私隔离）。

## 隔离与发布（分发前必跑）

| 文件 | 作用 |
|---|---|
| `privacy_guard.py` | 隐私守卫。`--staged` 查暂存区（pre-commit 钩子自动调用）、`--all` 查所有会公开的文件（CI 也跑）、`--dist <zip或目录>` 查已打好的发布包（**会解开 zip 扫包内每个文本成员**）。查四类：禁止路径、敏感词（`<data-root>/personal/privacy-guard-words.txt`）、手机号/身份证、本机绝对路径（`C:\Users\<名字>` 等） |
| `build_dist.py` | 一键打包。`python tools/build_dist.py` 打门户全套技能包；`--bundle` 打整仓包（技能 + 网页框架 + `setup.py` + `tools/` + `.trae/rules/` + `开始使用.md`）；`--skills a,b` 只打指定技能。**白名单取件：`data/` 根本不参与复制**，包内 `data/` 由 `data-templates/` 重建；出包后自动跑守卫自检，命中隐私就删包中止。日志与报告写 `dist/_build_report.txt` |
| `verify_dist.py` | 发布包验收（出包后跑一次）：结构、包内 `data/` 是否全为匿名模板、有没有混进真实录音/照片、`SKILL.md` frontmatter 是否合规（含 CRLF 检查）、解包后 Python 能否编译、`setup.py --check` 是否正常 |
| `git-hooks/pre-commit` | 由 `setup.py` 安装到 `.git/hooks/`，每次 commit 自动运行 `privacy_guard.py --staged` |

敏感词表在 `<data-root>/personal/privacy-guard-words.txt`（数据区里、不入库，每行一词；迁移前的仓库内 `personal/` 路径仍作兜底）；缺失时仍会做路径、手机号/身份证与本机路径检查。

## 新建技能与门户接线（个性化需求都从这里起步）

```bash
python tools/new_skill.py my-new-thing --title 我的新功能 --desc "当用户说……时调用"
python tools/portal_wire.py list                    # 先看门户现状（标签页/次序/挂载/重定向）
python tools/portal_wire.py add-page --id my-thing --name 我的新功能 --emoji 🧩 \
    --src /my-thing/web/index.html --mount my-thing --skill my-new-thing
python tools/portal_wire.py remove-page --id my-thing --unmount   # 撤掉接线
python tools/portal_wire.py undo                    # 撤销上一次操作
python tools/smoke_test.py                          # 起服务逐页点一遍（页面 200 / 接口 JSON）
```

| 文件 | 作用 |
|---|---|
| `new_skill.py` | 生成合规技能骨架：`SKILL.md`（含隔离约定与挂载步骤）、`data-templates/`（config + state）、`web/index.html`（含同步状态与 `/api/<name>` 读写）、`web/vendor/`（从门户技能复制的共享组件）。**一个新需求 = 一个新技能** |
| `portal_wire.py` | 门户接线员：把一页挂进 `index.html` 的 `CORE_TABS` / `TAB_ORDER`，页面在兄弟技能里时顺带加 `preview_server.py` 的静态挂载与重定向。只做增量、写前自动备份到 `.portal-wire-backup/`、可 `undo` |
| `smoke_test.py` | 冒烟测试：起一次门户（`GH_NO_BROWSER=1` 不弹浏览器），把 `CORE_TABS` 里每一页与常用 `/api/...` 点一遍，报告 HTTP 状态；只读，不动数据 |

接线点、组件 API、页面骨架、验收清单的完整规格在
`.trae/skills/portal-builder/references/page-contract.md`，常见需求的做法（打卡页/统计图/相册/换主题）在
同目录 `recipes.md`。

## 跨 app 复用（规则与技能入口）

规则真源是根目录 `AGENTS.md` + `.trae/rules/project_rules.md`，其它工具的入口只放薄壳
（`.codebuddy/CODEBUDDY.md`、`CLAUDE.md` 都只导入，无正文）；技能真源是 `.trae/skills/`，
给别的工具用就建目录联接（见 `docs/agent-interop.md`）。打包时这些入口文件会一起进整仓包
（`BUNDLE_EXTRA_FILES` / `BUNDLE_EXTRA_DIRS`）。约定见 `AGENTS.md` 第 9 条。

## 教材下载管线（适配任意省份/版本）

从国家中小学智慧教育平台（官方免费电子教材）按你配置的教材版本下载、切页、建索引。
版权原因教材不随发布包分发，用户自己跑这条管线获取。

依赖安装：

```
pip install requests pymupdf
```

| 步骤 | 脚本 | 作用 |
|---|---|---|
| 1 | `find_books.py [年级]` | 拉取平台教材目录，列出该年级（默认一年级）全部教材，输出 `grade1_books.json` |
| 2 | `filter_books.py` | 按 `.trae/skills/school-bag-organizer/data/config.json` 里的 `textbooks` 版本字段筛选目标教材，输出 `target_books.json`；无配置时用人教版体系默认值 |
| 3 | `download_books.py` | 下载各科 PDF 到 `textbooks/pdf/`，并写 `textbooks/manifest.json` |
| 3b | `download_rest.py` | 个别科目下载失败时的多镜像重试脚本 |
| 4 | `split_pages.py` | 把 PDF 逐页切成 `textbooks/pages/{学科}/pNNN.jpg`（宽约 1100px） |
| 5 | `build_meta.py` | 抓取平台章节目录与页码偏移，生成 `textbooks/book_meta.json` |
| 6 | `build_index.py` | 汇总生成总索引 `textbooks/index.json`（章节 → 印刷页码/PDF 页码/页图对照） |

说明：

- 更换教材版本：改 `config.json` 的 `textbooks` 字段（或重跑 `python setup.py` 引导），再从第 1 步执行。
- 页码规则：印刷页码 = PDF 页序号 − offset，offset 因书而异，由 `build_meta.py` 自动获取。
- 部分科目平台不提供电子课本（如小学英语外研版、书法），`index.json` 的 `pending` 字段有说明。
- 平台接口偶发 400/403，重试或换镜像（`download_rest.py` 已内置）。
- `grade1_books.json`、`target_books.json` 等为中间产物，已在 `.gitignore` 中，不入库。

## 共享前端资源同步

| 文件 | 作用 |
|---|---|
| `sync_vendor.py` | 以 `.trae/skills/growth-home/web/vendor/` 为真源，把 `pinyin-pro.js`、`themes.js`、`feedback.js`、`tts.js`、`voice.js` 复制到其它技能的 `web/vendor/`。`--check` 只报差异不写入（有差异时退出码 1，可用于发布前自查） |

各技能的页面都要能脱离门户独立运行，所以这些文件各存一份副本。改完任意一个，跑一次
`python tools/sync_vendor.py` 对齐；发布前用 `--check` 确认没有漏同步。

## 第三方项目

`tchsrc/tchMaterial-parser-main/` 与 `tchMaterial-parser.zip` 为第三方开源项目
[tchMaterial-parser](https://github.com/happycola233/tchMaterial-parser)（MIT 许可，Copyright (c) 2026 肥宅水水呀），
是教材解析的 GUI 工具，与本目录的下载管线相互独立，可按需使用。其许可与版权声明保留在其目录内。
（发布包默认**不包含**该第三方项目，避免体积与许可混淆。）

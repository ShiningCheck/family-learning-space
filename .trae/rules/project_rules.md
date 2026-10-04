# 项目规则 · family-learning-space（家庭学习空间）

这套仓库是给家长陪伴一年级孩子用的工具集：每个能力是一个技能，放在 `.trae/skills/<技能名>/` 下
（代码侧 `SKILL.md` + `skill.json` + `data-templates/` + `web/`，真实数据在**仓库之外**的 data-root，见第 8 节）。
门户技能 `growth-home` 用本地服务器（`web/preview_server.py`，端口 8090）把兄弟技能的页面与数据托管到一个入口，
手机/平板/电脑同 WiFi 访问。

**与 AGENTS.md 的分工**：根目录 `AGENTS.md` 是 9 条硬规则（讲"必须做什么"），本文件是展开细节
（讲"怎么做"）；各工具的薄入口（`.codebuddy/CODEBUDDY.md`、`CLAUDE.md`）用 `@` 同时导入这两份，
拿到的内容与 Trae 一致。

下面是**所有技能、所有页面都要遵守**的硬性要求。加新功能、改老页面前先看一遍。

## 1. 记录必须跨设备同步（最重要的硬要求）

用户明确要求过：**打卡记录要跨设备同步**，这是全仓库通行的规矩，不是一个页面的临时做法。

- 凡"记录类"数据（打卡、勾选、进度、语音、备注、家长勾选……）一律**以服务器落盘的那份为准**：
  数据写进 data-root 里该技能的 `data/*.json`（路径走 `tools/data_paths.py` 解析），页面通过本地服务器的
  `GET/POST /api/...` 读写。
- `localStorage` **只能**当断网缓存（或供单文件版兜底），**不允许"只写本机就当保存成功"**。
- 合并规则：同一项 + 同一天（或同一本书同一章）按 `ts`（毫秒时间戳）取新，两台设备同时改互不覆盖；
  "取消打卡"也要留一条 `v: 0` 的记录，取消动作才能同步到别的设备；升级前的旧数据没有 `ts`，取并集不丢记录。
  按天布尔值的简单记录（如英语的听/说/读/写、听/看/说）服务器按 `date + 维度` 直接覆盖，同样落盘。
- 页面打开时、切回前台时、每隔十几秒各拉一次服务器状态；用户勾选后尽快推回（同步中收到改动要排队补推）。
- 页面要有**看得见**的同步状态（如「☁️ 已同步 / ⚠️ 暂时连不上服务器」）。
- 自检一句话：**手机、平板、电脑打开同一页，看到的必须是同一份数据**。做不到就等于没做完。

现有实现可照抄：`portal-core/components/homework-section.js`（作业打卡）、`reading/web/index.html`
（读书/书单）、data-root 里 `<root>/core/data/checkins.json`（统一打卡落盘，架构 v2 第 3 步起）。

## 2. 学科页打卡统一方式（今后所有学科页都这么做）

用户明确要求过：**英语页的打卡也要做成和语文页一样的方式，以后都用这种方式**。
语文、数学、辅导班英语、学校英语四个学科页现在是一套做法，新加学科（科学、音乐……）照这套来：

1. **一个科目一个学科页**，挂在门户标签上；页面上是"当天的作业卡 + 打卡大按钮 + 一个打卡日历"。
2. **打卡数据落服务器、跨设备同步**（见第 1 条），学科页只读服务器那份，本机只是缓存。
3. **打卡日历整页只留一个**：月视图，绿点＝那天有打卡（数字＝打卡几项）、蓝框＝今天，◀ ▶ 换月、
   「今天」跳回本月，上行一句"本月：打卡 X 天"。**卡片里不再各挂一个日历**；
   页面自己已经有日历的（如辅导班页的"哪天看哪一课"日历）就用那一个，不再多放。
4. **点某一天 → 列出那天本科目打卡的全部内容**（这是"打卡方式"的核心，别省）：
   ① 页面自己那套打卡项的状态（语文/数学是作业卡；辅导班是**每个知识点板块**，如物品词汇、重点句型；
   学校英语是**每组内容**，如「资料视频 ①」）
   ② 作业卡的打卡情况 + 各自的课本页图 + 那天录的「说一句」
   ③ 页面自己那套录音（音频 + 文字双显示）④ 那天的学情 / 学习看板任务（有的科目才有）。
5. **打卡点要细到"内容块"，不要笼统的维度按钮**（用户明确要求过，两个英语页都已照此改造）：
   辅导班原来是「听/说/读/写」四个大按钮 → 改成**每一块知识点（`sections[]`）末尾一个打卡标志**
   （key = `<单元id>:<板块id>`，如 `l2-u2:items`）；学校英语原来是「听/看/说」三个分别打卡 →
   改成**一组内容（一个视频/一段材料，`materials[]`/可选 `groups[]`）下边跟着一个打卡**
   （key = 内容组 id，如 `v1`）。老师给的听/说/读/写要求只作为纯文本列出来、不再用来打卡。
   新学科、新单元都照这个粒度来：孩子学完哪一块就在哪一块点一下，页面上显示「x/N 个知识点 / 组内容完成」。
6. **作业卡带了「第X页」就附课本页图**，点一下直接看那一页；没有电子课本的科目（英语）自动不显示，不影响打卡。
7. **历史可以回看、可以补打卡**：切到过去某天时，打卡按钮勾的就是那天，并给出「回到今天」；
   页面上的日期条要写清"正在给哪一天打卡"。

实现方式：这些都走共享模块 `portal-core/components/homework-section.js`（`HwSection.mount`，页面引用 `/components/homework-section.js`），
页面自己那套东西通过 `dayChecks` / `dayVoices` 传进去，日期通过 `date` / `onPickDate` / `setDay` 联动，
不要每个页面各写一套日历和打卡列表。挂载示例见 `growth-home/SKILL.md` 的「作业卡片」一节。

## 3. 语音必须"双显示"：音频 + 文字一起给

有语音输入的地方都要同时给出**能点开听的音频**和**识别出来的文字**，两边一起留档
（`data/voice/` 索引里同一条记录含 `url` + `text` + `asr`）。不许只存音频不显示文字，也不许只录文字不留音频；
识别失败时音频照常存、文字允许家长手写补上。直接用 `/vendor/voice.js`（`portal-core/vendor/` 单源）
（`Voice.attach({ autoFill })` + `Voice.listInto()`），不要自己另写一套录音 UI。

## 4. 内容要来自真实来源，不许编

- 教材页图来自教材库 `<data-root>/textbooks/`（门户把 `/textbooks/*` 映射过去；教材库在仓库之外，
  路径读 `tools/data_paths.py` 的 `textbooks_dir()`）；**页码映射读 `textbooks/index.json`**
  （印刷页码 + `offset` = PDF 页序号），**不许硬编码 offset / 页码 / 页数**。作业文字里写了「第X页」时，
  应把对应课本页图直接附给孩子（可点开阅读）。
- 书的出版社、简介，孩子的学情、画作描述等，都要来自真实输入或照片，不许编造；拿不准就留空或标注待补。

## 5. 儿童友好的界面约定

零外部依赖（所有库放本地 `vendor/`）、大按钮、拼音标注（本地 `pinyin-pro.js`）、**只在用户点击时出声**、
庆祝动画可点掉。朗读统一优先播放 `voice-dubbing` 技能预生成的音频（`data/tts/`），没有对应音频才退回浏览器朗读。

## 6. 数据与隐私

- 真实个人数据（孩子姓名、学校、课表、录音、打卡记录）只放**仓库之外的 data-root**（见第 8 节），
  仓库内不得出现 `data/` 等数据目录；仓库里只保留 `data-templates/` 的匿名示例。
- 对外发布/打包前：数据本来就**不在仓库里**（打包只读 `data-templates/`），但仍要确认
  `feedback_channels.json` 模板里的飞书 webhook 为空（那是作者本机专用），并跑
  `python tools/privacy_guard.py --all`（含架构断言）与 `python tools/verify_dist.py dist/xxx.zip`。

## 7. 改完要做的收尾动作

- 改了共享组件（`portal-core/vendor/` 下的 `feedback.js` / `voice.js` / `tts.js` / `themes.js` / `pinyin-pro.js`，
  或 `portal-core/components/`）：已收拢为**单源**（架构 v2 第 2 步），改一份即可，无需同步副本。
- 改了规则（`AGENTS.md` 或本文件）或技能入口：**两处对应条目同步**，再跑一次
  `python tools/build_dist.py --bundle` 确认入口文件（`AGENTS.md`、`.codebuddy/`、`CLAUDE.md`、
  `.trae/rules/`、`docs/`）确实进了包（见第 9 节）。
- 新增或改动了会被朗读的内容（单词句子、作业项、书名简介、章节名……）：跑一次 `voice-dubbing` 补配音。
- 本地自测：`python .trae/skills/growth-home/web/preview_server.py`，浏览器打开 `http://localhost:8090/`
  逐页点一遍（打卡、切日期、换设备模拟用「换个浏览器/无痕」）。
- 各技能自己的细节规矩写在各自的 `SKILL.md` 里，特别是 `growth-home/SKILL.md` 的「通用约定」一节。

## 8. 代码与隐私隔离（分发与扩展的硬性约定）

用户明确要求过：**技能和网页框架要能一起完整发放给别人用**，所以「代码」与「隐私」必须物理隔离，
并且**以后所有开发都按这套来**。

### 8.1 孩子隐私数据必须分离（新增，优先级最高）

**孩子的隐私数据 = 真实姓名/昵称、学校、班级、老师、课表、作息、学情报告、亲子对话、
录音与识别文本、画作与照片、打卡记录、图书与家庭信息，以及任何能指向具体未成年人的组合信息。**
这些数据必须与框架、代码、网页**物理分离** —— 不是"放在一个被 `.gitignore` 忽略的目录里"就算完，
而是**根本不放在仓库里**。

- **落点唯一**：只允许出现在**仓库之外的 data-root**（`<data-root>/web|learn|bag|art|lib|comp|textbooks|personal/`，
  布局与门户 URL 命名空间同构；无网页的技能落 `<data-root>/skills/<技能名>/`；`personal/` 现只放隐私词表）。
  **仓库内不得存在任何 `data/`、`images/`、`audio/`、`output/`、`personal/`、`画作档案/`、`textbooks/` 目录。**
  data-root 由仓库根 `local.json` 的 `data_root` 指定（示例见 `local_example.json`，由 `python setup.py` 生成），
  必须是**仓库之外的绝对路径**；路径解析统一走 `tools/data_paths.py`（仓库内唯一真源，落在仓库内即报错）。
- **永远不参与分发**：打包只消费 `data-templates/`，任何流程都不读 `data/`（白名单取件）；
  `build_dist.py` 出包前会**断言仓库内无数据目录**，`privacy_guard.py --all` 同样会断言。
- **三层防护**：物理层（数据根本不在仓库里、不参与分发）＋ 检查层（`privacy_guard.py` 的暂存区/全量/发布包
  三种模式 + **架构断言**（仓库内无数据目录 + `skill.json` 命名空间自洽）+ pre-commit 钩子 + CI + `verify_dist.py`）
  ＋ 运行层（页面一律走 `/api/...` 读写，不许直读本机文件路径）。
- **迁移与回滚**：`python tools/migrate_to_data_root.py --data-root <仓库外路径>` 先 dry-run 看计划，
  `--apply` 只复制（仓库内那份保留，服务器改造前照样能跑），验收通过后再 `--cleanup` 删仓库内副本（先备份，
  `--rollback <备份目录>` 可还原）。
- **未成年人特别条款**：**绝不外发**（反馈通道 `relay.url` 留空时只落本机，这是默认值）；
  不进日志、截图、示例数据、导出包、提交记录、CI 产物；对外分享截图前确认没有学校全名与其他孩子姓名。
- **可删除**：删掉 data-root 里某个技能的那一层就等于回到出厂状态，不残留、不依赖别的技能的隐私数据。

其余三条铁律：

1. **个人数据只有一个落点**：**仓库之外的 data-root**（`<data-root>/web|learn|bag|art|lib|comp|textbooks|personal/`）。
   仓库内**不允许**出现 `data/`、`images/`、`audio/`、`output/`、`personal/`、`画作档案/`、`textbooks/`
   任何一项（`data_paths.repo_data_dirs()` 会列出违规目录）。
2. **公开侧（会发给别人的一切）只放匿名与可配置**：`SKILL.md`、`skill.json`、`DATA.md`、`web/`、脚本、
   `data-templates/`。里面**不得出现**真实姓名/昵称、学校、班级、老师、手机号、身份证号、
   本机绝对路径（`C:\Users\<名字>`）、真实录音照片、自家打卡记录。要用的值一律从 data-root 的 `config.json` 读，
   缺省值写进 `data-templates/config.json`。
3. **新需求 = 新技能，不改公共页面**：任何个性化需求（新学科页、新打卡项、新功能）都新开一个
   `.trae/skills/<新技能>/`，用 `python tools/new_skill.py <名字>` 生成合规骨架（自带 `skill.json` 声明
   `url`/`code`/`data`，门户服务器启动时**自动挂载**，不再手改 `preview_server.py`）；技能自己的 `/api/...`
   路由仍加在门户 `preview_server.py` 里。禁止把私有逻辑塞进别人的页面。
   接线走脚本、不走手改：`python tools/portal_wire.py add-page …`（可 `undo`），
   接线后必须 `python tools/smoke_test.py` 冒烟 + `python tools/privacy_guard.py --all` 过关。
   完整规格（接线点、组件 API、页面骨架、验收清单）见 `.trae/skills/portal-builder/references/page-contract.md`。

**工具链（靠工具保证，不靠人记得住）**：

| 动作 | 命令 |
|---|---|
| 数据区路径解析（唯一真源） | `python tools/data_paths.py`（`--self-test` 自检：仓库内的 root 必须被拒） |
| 把数据迁到仓库外 | `python tools/migrate_to_data_root.py --data-root <路径>`（`--apply` 复制 / `--cleanup` 删仓库内副本 / `--rollback`） |
| 新建合规技能骨架 | `python tools/new_skill.py my-thing --title 我的新功能`（生成 SKILL.md + skill.json + DATA.md + data-templates/） |
| 把新页面接进门户 | `python tools/portal_wire.py add-page …`（`list` 看现状，`undo` 回退；挂载由 skill.json 自动声明） |
| 接线后冒烟验收 | `python tools/smoke_test.py`（起服务逐页点一遍，只读不动数据） |
| 检查会不会泄露 | `python tools/privacy_guard.py --all`（含架构断言；pre-commit 钩子与 CI 自动跑） |
| 打出可分发的包 | `python tools/build_dist.py`（技能包）/ `--bundle`（技能 + 网页框架整仓包；出包前断言仓库内无数据目录） |
| 验收打好的包 | `python tools/verify_dist.py dist/xxx.zip`（结构、模板匿名性、frontmatter、解包可运行性） |
| 检查已打好的包 | `python tools/privacy_guard.py --dist dist/xxx.zip`（会解开 zip 扫包内每个文本成员） |
| 新用户配置与启动 | `python setup.py` → `python setup.py --start`（`--check` 只体检不改文件；向导会先问 data-root 放哪） |

**打包铁律**：`data/` 永远**不参与复制**（不是"复制后再删"），包内 `data/` 一律由 `data-templates/`
重建；打包器出包后自动自检，命中隐私就删包中止。直接手工 zip 一个技能目录是不允许的。

**自检一句话**：把这个包发给一个陌生家长，他 `python setup.py` 填完自己的信息就能起服务用起来，
而包里翻不出一丁点我家的信息 —— 做不到就等于没做完。

## 9. 跨 app 复用：规则与技能都只写一份

用户明确要求过：**以后 repo 的变更都要符合跨 app 复用的要求**（Trae、WorkBuddy、Claude Code、Cursor…
谁打开这个仓库，都能读到同一套规则、用到同一套技能）。行业现状与各工具读取位置见
`docs/agent-interop.md`（含调研来源）。本节的规矩：

**9.1 规则：一份正文 + 薄入口**

- **真源只有两处**：根目录 `AGENTS.md`（9 条硬规则，讲"必须做什么"）与本文件（讲"怎么做"）。
  **改一处必须同步另一处的对应条目**，不允许出现两份互相矛盾的规则正文。
- **其它工具入口只放薄壳**：能导入就导入（WorkBuddy 的 `.codebuddy/CODEBUDDY.md` 与 Claude Code 的
  `CLAUDE.md` 都用 `@` 导入 `AGENTS.md` 和本文件两份），不能导入的工具就写指向。
  **绝不把规则正文复制进入口文件**。
- 新增工具入口（如 `.cursor/rules/`、`.github/copilot-instructions.md`）时：
  **先按这个模式加薄壳，再在 `docs/agent-interop.md` 的表格里登记一行**。
- Trae 侧的 `.trae/rules/*.md` 保持被自动注入，内容与 `AGENTS.md` 的条目对应，不要写成第三套说法。

**9.2 技能：一个真源 + 联接，不维护第二份**

- 技能真源是 `.trae/skills/<技能名>/`。**任何情况下不手工维护第二份技能内容**。
- 要给别的工具用，用**目录联接**（Windows `New-Item -ItemType Junction -Path .agents\skills -Target .trae\skills`；
  macOS/Linux `ln -s ../.trae/skills .agents/skills`）。`.agents/skills/` 是中立标准位置（Cursor、Codex 都读），
  `.codebuddy/skills/` 给 WorkBuddy。
- **联接不进 git、也不进发布包**（Windows 软链要权限，git 保存联接会出岔子）：分发靠包里的
  `.trae/skills/` + 入口文件里的说明，接收方按需在本机建联接。

**9.3 技能 frontmatter 只写可移植字段**

`name` / `description` / `license` / `compatibility` / `metadata` / `allowed-tools`。
工具私有字段（Cursor 的 `paths`、`disable-model-invocation`、`icon`、`color` 等）**不要写进通用技能**，
需要时在对应工具的说明里单独给，避免"在 A 能用、到 B 报格式错"。

**9.4 收尾**

改完入口或规则：`python tools/privacy_guard.py --all` → `python tools/build_dist.py --bundle` → 确认包里能翻到
`AGENTS.md`、`.codebuddy/CODEBUDDY.md`、`CLAUDE.md`、`.trae/rules/project_rules.md`、`docs/agent-interop.md`。
新增技能后，顺手确认入口说明里的路径仍成立（技能目录没改名、没有被搬走）。

**9.5 仍不统一的地方（别当成已解决）**

Claude Code 不原生读 `AGENTS.md`（只用 `CLAUDE.md`，所以必须留薄入口）；各工具 frontmatter 扩展字段不一致
（所以只写可移植字段）；Trae、WorkBuddy 是否兼容 `.agents/skills/` 中立目录**没有官方声明**，
所以跨工具时用联接而不是赌它自动认。


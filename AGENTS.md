# AGENTS.md · 给在本仓库里干活的 AI 助手

## 这个仓库是什么（先看这个）

「家庭学习空间」：给家长陪伴小学孩子用的工具集——1）个性化的门户网站是学习看板，包括 `growth-home` + 各学科/习惯打卡技能，
多设备同 WiFi 访问同一份数据 2) 用AI Skills理解学习内容后并随时更新网站看板。3）这是yi'g面向大众的解决方案。做任何方案时的取舍顺序：

1. 孩子隐私与数据隔离不可妥协（见第 7、8 条）
2. 儿童友好（大按钮、拼音、点击才出声）优先于功能密度
3. 记录必须跨设备同步，`localStorage` 只是断网缓存

项目完整介绍、快速开始与目录导览见 [`README.md`](README.md)。

技能放在 `.trae/skills/<技能名>/`，门户的**框架核**是仓库根 `portal-core/`（vendor 单源、共享组件、
门户 shell、Store 同步库、设置页），服务器是 `.trae/skills/growth-home/web/preview_server.py`（端口 8090）
把兄弟技能的页面托管到一个入口。学科/读书/日报已从 growth-home 拆成独立技能
（subject-chinese、subject-math、english-class、subject-school-english、reading、daily-report）。

**动手前先读** [`.trae/rules/project_rules.md`](.trae/rules/project_rules.md)（完整项目规则）；
各技能的细节写在各自的 `SKILL.md`，门户的通用约定见 `.trae/skills/growth-home/SKILL.md` 的「通用约定」一节。

**给别的 AI 工具用**：规则正文只写在 `AGENTS.md`（本文件）与 `.trae/rules/project_rules.md` 两处；
`.codebuddy/CODEBUDDY.md`、`CLAUDE.md` 是**薄入口**（只导入、无正文）。各工具读哪个位置、
技能目录怎么对齐见 [`docs/agent-interop.md`](docs/agent-interop.md)。

## 必须遵守的几条（违反就算没做完）

1. **记录必须跨设备同步**：所有打卡、勾选、进度、语音、备注都要落服务器上的 `data/*.json`，
   页面通过本地服务器的 `GET/POST /api/...` 读写，按 `ts` 时间戳合并（按天的布尔打卡按 `date+维度` 覆盖）；
   `localStorage` 只能当断网缓存。自检：手机、平板、电脑打开同一页，看到的必须是同一份数据。
2. **学科页打卡都用同一套方式**（语文/数学/辅导班英语/学校英语已统一，新学科照抄）：
   打卡落服务器 + 作业卡大按钮 + **整页只留一个打卡日历** + **点某天列出那天该科打卡的全部内容**
   （自己的打卡项、作业卡与课本页图、当天录音、学情/看板任务）+ 历史可回看可补打卡。
   **打卡点要细到内容块**：英语辅导班已把「听/说/读/写」四个笼统按钮换成每块知识点末尾一个打卡标志
   （key = `<单元id>:<板块id>`），学校英语已把「听/看/说」换成**一组内容（一个视频/一段材料）下边一个打卡**
   （key = 内容组 id，如 `v1`），别再加笼统的维度按钮。
   实现走共享模块 `portal-core/components/homework-section.js`（`HwSection.mount`，用 `dayChecks`/`dayVoices`/`onPickDate`/`setDay`
   接页面自己的东西，页面引用 `/components/homework-section.js`），**不要每个页面各写一套日历和打卡列表**。
3. **语音必须"双显示"**：能点开听的音频 + 识别出的文字，两边一起留档；用 `/vendor/voice.js`（`portal-core/vendor/` 单源），不要自造录音 UI。
4. **内容不许编**：教材页图/页码来自教材库 `<data-root>/textbooks/`（映射读 `textbooks/index.json`，不硬编码 offset）；出版社、简介、学情都取自真实输入。
5. **儿童友好**：零外部依赖、大按钮、拼音标注、点击才出声。
6. **收尾**：共享库已收拢为 `portal-core/vendor/`（voice/tts/themes/feedback/pinyin-pro）与 `portal-core/components/` 单源，改一份即可、无需同步副本；新增可朗读内容就跑 `voice-dubbing` 补配音；本地起门户点一遍自测（`python tools/smoke_test.py`）。
7. **孩子的隐私数据必须分离（最高优先级）**：真实姓名/学校/班级/老师/课表/学情/亲子对话/录音/照片/画作/
   打卡记录等一律只落**仓库之外的 data-root**（`<data-root>/web|learn|bag|art|lib|comp|textbooks|personal/`），
   仓库内**不得存在任何 `data/` 目录**（`privacy_guard.py --all` 与 `build_dist.py` 都会断言这一点）；
   代码、页面、脚本、`SKILL.md`、`data-templates/`、`tools/` 里不得出现真实信息；数据**永远不参与分发**
   （打包只读 `data-templates/`，`data/` 根本不复制）；路径一律走 `tools/data_paths.py` 解析，页面一律走
   `/api/...` 读写，不许直读本机文件路径；对外分享前跑守卫与验收。
8. **代码与隐私隔离 + 新需求＝新技能**：data-root 由仓库根 `local.json` 的 `data_root` 指定（示例见
   `local_example.json`，由 `python setup.py` 生成），必须是仓库之外的绝对路径；公开侧不得出现真名/学校/
   手机号/本机绝对路径，配置一律从 data-root 的 `config.json` 读。打包只能走 `python tools/build_dist.py`
   （包内 `data/` 由 `data-templates/` 重建，出包自动自检，命中隐私即删包）；个性化需求用
   `python tools/new_skill.py <名字>` 新开一个技能（自带 `skill.json` 声明 url/代码/数据目录，门户自动挂载），
   不去改别人的页面。完整约定见 `.trae/rules/project_rules.md` 第 8 节。
9. **跨 app 复用：规则与技能都只写一份**：规则真源是根目录 `AGENTS.md`（本文件这些条目），
   展开细节在 `.trae/rules/project_rules.md` —— **改一处必须同步另一处的对应条目**，不允许出现两份互相矛盾的正文。
   其它工具的入口只放薄壳，**绝不复制规则正文**（WorkBuddy 入口 `.codebuddy/CODEBUDDY.md` 与
   Claude Code 入口 `CLAUDE.md` 都用 `@` 导入 `AGENTS.md` 和 `.trae/rules/project_rules.md` 两份，
   只导入、无正文）。技能真源是 `.trae/skills/`；要给别的工具用就建**目录联接**
   （`.agents/skills/`、`.codebuddy/skills/` → `.trae/skills/`，联接不进 git），不手工维护第二份内容。
   新增技能的 frontmatter 只写可移植字段（`name` / `description` / `license` / `compatibility` / `metadata` /
   `allowed-tools`），工具私有字段（Cursor 的 `paths` / `icon` / `color` 等）不要写进通用技能。
   静态目录仍按"新需求＝新技能"走，这条只管**入口与格式**。改完跑
   `python tools/privacy_guard.py --all`，再用 `python tools/build_dist.py --bundle` 打一次包 ——
   入口文件（`AGENTS.md`、`.codebuddy/`、`CLAUDE.md`、`.trae/rules/`、`docs/`）必须随包一起发出去。
   完整调研、各工具读取位置与做法对比见 [`docs/agent-interop.md`](docs/agent-interop.md)。

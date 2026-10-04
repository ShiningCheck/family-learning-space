---
name: "growth-home"
description: "孩子的成长家园门户首页：用大标签页统一入口聚合学习看板、家长任务、书包清单、语文/数学/学校英语/辅导班英语学科页（各带作业打卡）、读书/家务/运动每日打卡、日报、家庭图书馆、作业管理。当用户说'成长家园''首页''门户''读书打卡''家务打卡''运动打卡''语文作业''数学作业''图书馆''家长任务''家长页''加一个标签页''固定标签页顺序'时调用。"
---

# 成长家园门户

为 6 岁儿童设计的家庭门户：一个首页、一排大标签页——**学习**（学习成长看板）、**日报**（当天所有打卡 + 各科作业完成情况）、**语文 / 数学 / 辅导班英语 / 学校英语**（学科页：当天的作业在这里打卡，家长也能随手加作业）、**书包**（书包整理清单）、**画作**（画作档案）、**读书**（读书打卡：自由阅读 + 书单，按月日历回看）、**家务 / 运动**（每日打卡）、**图书馆**（家庭实体书架）、**家长任务**（来自 `learning-growth-board` 的家长中心）、**作业管理**（跨学科作业总览）。绘本玩具屋风格：大按钮、拼音标注、语音反馈、庆祝动画，零外部依赖。

本技能是**聚合层**：不复制数据，通过本地服务器把兄弟技能 `learning-growth-board`（学习看板）与 `school-bag-organizer`（书包清单）的页面统一托管在一个入口下。

## 标签页顺序（固定，不要随意改）

首页菜单的次序由 `web/index.html` 里的 `TAB_ORDER` 统一定死，`CORE_TABS` 与 `activities.json` 里的打卡标签（读书/家务/运动）都会按它排序后再渲染。当前次序：

**学习 → 日报 → 语文 → 数学 → 辅导班英语 → 学校英语 → 书包 → 画作 → 读书 → 家务 → 运动 → 图书馆 → 家长任务 → 作业管理**

- `TAB_ORDER` 里没列到的标签 id 会自动排到最后，次序沿用配置里的先后，所以新加标签页不会打乱已有次序（想插在固定位置就把 id 写进 `TAB_ORDER`）。
- 标签页显示名与 id 的对应：`parent`＝家长任务、`homework-admin`＝作业管理、`english-class`＝辅导班英语。改显示名只动 `CORE_TABS` 的 `name`，**不要改 `id`**（`gh_last_tab`、location.hash、旧书签都靠 id）。
- `activities.json` 的 `subjects[].name`（辅导班英语 / 学校英语）用于日报分科标题与庆祝语配音，与标签页名保持一致。
- 标签名本身不参与朗读配音，改显示名不需要重跑 `voice-dubbing`。

## 目录结构

以技能根目录为基准（即本 `SKILL.md` 所在目录）。**代码侧**（公开、可分发）：

```
growth-home/
├── SKILL.md
├── skill.json                  # 声明 url=web / 代码目录 / 数据目录（门户服务器据此自动挂载）
├── DATA.md                     # 数据落在哪里（仓库之外的 data-root）
├── data-templates/             # 发布用匿名示例数据（含 feedback_channels.json 默认值、voice/index.json 空索引）
└── web/
    ├── index.html              # 门户首页（标签页 + iframe 集成）
    ├── subject.html            # 学科页（语文/数学共用，?subject=chinese|math 驱动）
    ├── homework-section.js     # 作业区块模块：作业打卡 + 添加/编辑作业 + 课本页图 + 整页一个打卡日历，学科页共用（growth-home 专属，不参与 vendor 同步）
    ├── homework.html           # 作业管理（家长用：跨学科总览、添加/编辑/删除）
    ├── tracker.html            # 通用每日打卡页（由 ?id= 参数驱动；读书/书单会跳到 reading.html）
    ├── reading.html            # 读书打卡：自由阅读 + 书单两个模式 + 月日历 + 当天内容
    ├── english-class.html      # 辅导班英语（含本科作业区块）
    ├── school-english.html     # 学校英语（内容组打卡：一组内容一个打卡 + 本科作业区块）
    ├── report.html             # 每日日报（含各科作业完成情况）
    ├── preview_server.py       # 门户服务器（端口 8090）+ 反馈收集转发 + 语音识别存档
    ├── asr.py                  # 本地语音识别引擎（faster-whisper，离线、音频不出电脑）
    └── vendor/
        ├── pinyin-pro.js       # 本地拼音库
        ├── themes.js           # 主题引擎
        ├── voice.js            # 通用语音记录组件（录音/上传/自动识别/存档，五个技能各存一份）
        └── feedback.js         # 反馈组件（五个技能各存一份，改动后 5 份一起对齐）
```

**数据侧**（**仓库之外**，本技能目录里没有 `data/`）：`<data-root>/web/data/`，含
`config.json`（孩子姓名等基本信息）、`activities.json`（打卡标签页配置 + 学科清单 subjects）、
`tracker_state.json`（打卡状态：每日记录 + 书单逐章进度，跨设备同步的落盘文件）、
`homework.json`（作业卡）、`homework_checkins.json`（作业打卡记录）、
`feedback_channels.json`（反馈通道真实配置）、`voice/`（通用语音记录：index.json + audio/<场景>/<日期>/*.m4a）、
`feedback/`（install.json 本机匿名安装ID + inbox/*.json 反馈存档）。
路径一律走 `tools/data_paths.py` 的 `skill_dir("growth-home")` 解析，细节见同目录 `DATA.md`。

**同级依赖**：`../learning-growth-board/` 与 `../school-bag-organizer/` 必须存在（门户通过路径映射托管它们的 `web/` 页面与 `data/` 数据）；`../xiaoshan-art-archive/` 提供「画作」标签页（`/art/web/art.html`），`../home-library/` 提供「图书馆」标签页（`/lib/web/library.html`），缺失时首页对应标签会加载失败，其余功能不受影响。

## 服务器与路径映射

`web/preview_server.py` 启动在 **8090** 端口，统一入口：

| 路径 | 内容 |
|---|---|
| `/index.html` | 门户首页（默认页） |
| `/web/subject.html?subject=chinese` | **语文页**（`math` 同理＝**数学页**）：当天的语文/数学作业打卡 + 添加作业 |
| `/chinese.html` `/math.html` | 302 到上面两个学科页（旧书签也能直接进） |
| `/web/reading.html?id=reading` | **读书打卡**（自由阅读 + 书单两个模式；`&mode=booklist` 直接进书单模式） |
| `/tracker.html?id=reading` | 302/前端跳转到读书打卡页（`booklist` 同理，旧书签不用改） |
| `/tracker.html?id=chores` | 家务打卡（`sports` 同理） |
| `/learn/*` | 映射到 `learning-growth-board/` 技能根目录 |
| `/bag/*` | 映射到 `school-bag-organizer/` 技能根目录 |
| `/art/*` | 映射到 `xiaoshan-art-archive/` 技能根目录（画作画廊） |
| `/lib/*` | 映射到 `home-library/` 技能根目录（家庭图书馆：书架分层 + 找书） |
| `/textbooks/*` | 映射到工作区根目录 `textbooks/`（国家平台教材扫描：看板「今天学了」和学科页作业卡的「课本第X页」都读它，页码映射见 `textbooks/index.json`） |
| `/api/home` | 返回 `{ config, activities }` |
| `/api/tracker?tab=<标签id>` | 读某个标签页的打卡状态 `{ records, progress }`（书单逐章进度在 `progress` 里） |
| `POST /api/tracker` | 提交 `{ tab, records, progress }`，按时间戳合并落盘到 `data/tracker_state.json` 并回传合并结果（跨设备同步） |
| `/api/homework` | 返回作业卡 `{ childName, items, subjects }`（`items[].subject` 决定它出现在哪个学科页） |
| `POST /api/homework` | 作业增删改 `{ op: add\|update\|delete, item\|id }` |
| `/api/homework/checkins` | 读作业打卡记录 `{ records }`（作业卡，含「握笔练习」这类长期作业；各学科页共用这一份） |
| `POST /api/homework/checkins` | 提交 `{ records }`，逐项逐日按时间戳合并落盘到 `data/homework_checkins.json` 并回传（跨设备同步） |
| `/api/data` | 返回学习看板数据 `{ config, days, weekly }`（学习看板页面依赖此接口） |
| `/api/class/data` | 返回英语辅导班数据 `{ childName, goal, weeklyTarget, units, records }` |
| `POST /api/class/checkin` | 辅导班**知识点打卡** `{ date, key: "<单元id>:<板块id>"（如 l2-u2:items）, done }`；老的 `{ date, dim, done }` 四维写法仍兼容 |
| `/api/school/data` | 返回学校英语数据 `{ childName, goal, textbook, units, records }` |
| `POST /api/school/checkin` | 学校英语**内容组打卡** `{ date, key: 内容组id（如 v1）, done }`；老的 `{ date, task, done }` 三维写法仍兼容 |
| `/api/library` | 返回图书馆数据 `{ childName, levelNote, shelves, books }`（页面读取主要走 `/lib/data/*.json`） |
| `POST /api/library` | 图书馆增删改 `{ op: add\|update\|delete, book\|id }` |
| `POST /api/library/upload` | 上传图书封面照片（multipart 字段 `image`），返回相对技能根目录的路径 |
| `POST /api/voice` | 通用语音记录：上传录音（multipart 字段 `audio`，另带 `scope`/`lang`/`date`/`text`/`meta`/`asr`），落盘并**自动识别成文字**，回传整条记录 |
| `/api/voice?scope=&date=&limit=` | 取语音记录（`scope` 支持前缀匹配，如 `tracker` 命中 `tracker-read-reading`） |
| `POST /api/voice/text` | 修订某条语音记录的文字（原始识别结果保留在 `asr` 字段） |
| `POST /api/voice/delete` | 删掉某条语音记录（`{ id }`；索引与音频文件一起删，空的日期/场景目录顺手收掉） |
| `/api/voice/status` | 语音识别引擎状态（模型名、是否就绪、已识别条数、本机已下载模型） |
| `/api/feedback/config` | 下发匿名安装ID、应用版本、中转服务地址（反馈组件启动时读取） |
| `POST /api/feedback` | 接收页面反馈：先落盘存档，再转发到公网中转服务 |
| `/api/feedback/status` | 本机反馈的送达状态列表（作者排查用） |
| `/api/feedback/retry` | 立刻补发所有待发送的反馈 |
| `/checklist.html` 等旧地址 | 302 重定向到门户内新路径，兼容旧书签 |

手机与电脑同 WiFi，手机浏览器访问 `http://<电脑IP>:8090/`。

## 通用约定（跨技能，务必遵守）

这是门户里所有页面共用的项目级规矩，加新功能、改老页面时都要照办。
**要新增/修改页面、把页面接进菜单的，先看 `portal-builder` 技能**：
具体接线点、组件 API、页面骨架、验收清单都在
`.trae/skills/portal-builder/references/page-contract.md`（本节只讲"为什么"，那份讲"怎么做"），
接线用 `python tools/portal_wire.py`，验收用 `python tools/smoke_test.py`。

- **语音输入必须「双显示」：音频 + 文字一起给。** 凡是有语音输入的地方（打卡一句话记录、读课文录音、画作描述、图书馆提问、英语「说」任务……），都要同时给出**能点开听的音频**和**识别出来的文字**——孩子说的话既能听、也能读，还要能进日报与档案。两边一起留档（`data/voice/` 索引里同一条记录含 `url` + `text` + `asr`，打卡页另在 `records[日期].voice = { id, url, text, ts }` 里挂一份），**不许只存音频不显示文字，也不许只存文字不留音频**；识别没成功时音频照常存、文字允许家长手写补上。
  - 组件层已经做好：`Voice.attach({ autoFill })` 录完自动把识别文字写进输入框，`Voice.listInto()` 渲染的历史列表每条都是「▶️ 播 + 文字 + ✏️ 改 + 🗑 删」。新页面直接用这套，不要自己再写一套录音 UI。
  - 页面上要**看得见**这两样：一段语音就配一个「▶️ 听」+ 一行文字（`.voice-show` / `.v-item` 这种成对结构），别把文字藏进弹层或只显示时长。

- **记录必须跨设备同步：打卡/记录一律以服务器上的那份为准。** 这也是本仓库的通用需求（写在仓库根目录 `AGENTS.md` 与 `.trae/rules/project_rules.md` 里）。新做任何"记录类"功能（打卡、勾选、进度、语音、备注……）时，**不能只写 localStorage 就当完事**：数据要落服务器上的 `data/*.json`，页面用 `GET/POST /api/...` 读写，合并规则按时间戳取新（同一项同一天两边都改也不互相覆盖），localStorage 只作断网缓存。判断标准很简单：**手机、平板、电脑打开同一页，看到的必须是同一份数据**（语文页的作业打卡就是这样，见「作业卡片」一节）。

- **学科页打卡统一方式：四个学科页一套做法，新学科照这个来。** 语文 / 数学 / 辅导班英语 / 学校英语现在是同一个模式——打卡落服务器、作业卡大按钮、**整页只留一个打卡日历**、**点某天列出那天该科打卡的全部内容**（页面自己的打卡项、作业卡与课本页图、当天录音、学情与看板任务）、历史可回看可补打卡。实现统一走共享模块 `web/homework-section.js`（页面自己的东西用 `dayChecks` / `dayVoices` / `onPickDate` / `setDay` 接进去），**别每个页面各写一套日历和打卡列表**。完整条目见 `.trae/rules/project_rules.md` 第 2 节，挂载细节见下面「作业卡片」一节。

## 工作流程

### 1. 启动门户

```
python <技能根目录>/web/preview_server.py
```

启动前先检查 8090 端口：若被兄弟技能的独立服务器占用，先停掉（门户已包含它们的全部功能）。

### 2. 修改打卡项目

家务/运动默认都是**自由输入**模式（`type: "single"`）：一个大按钮 + 一句话记录，孩子说做了什么、家长代写即可。想改提问语或输入框提示，编辑 `data/activities.json` 对应标签页的 `question` / `placeholder` 字段，刷新页面即生效。读书的提问语同理（它由合并页 `reading.html` 的自由阅读模式使用）。

若用户明确要求清单式打卡（如"家务列一个清单"），把该标签页改为 `"type": "list"` 并配 `items` 数组（每项含 `id`/`name`/`emoji`）。

### 3. 新增标签页

在 `activities.json` 的 `tabs` 中追加一项：

```json
{ "id": "piano", "name": "钢琴", "emoji": "🎹", "color": "#845EF7", "type": "single", "goal": "每天练琴15分钟", "question": "今天练了什么曲子？" }
```

- `type: "single"`：一个大打卡按钮 + 一句话记录（适合"每天做一件事"型）
- `type: "list"`：多个子项目逐个勾选（适合清单型），需配 `items`
- `color` 建议从调色盘选：`#FF922B` 橙 / `#51CF66` 绿 / `#4DABF7` 蓝 / `#F06595` 粉 / `#20C997` 青 / `#845EF7` 紫 / `#FFD43B` 黄

首页会自动读取配置渲染新标签页，无需改代码。**但菜单里的位置由 `web/index.html` 的 `TAB_ORDER` 决定**：想让新标签页插在某个固定位置，就把它的 `id` 加到 `TAB_ORDER` 对应位置上；不加的话它会排到菜单最后。改完顺带跑一次 `voice-dubbing` 补上新标签名的配音。

### 4. 打卡数据与跨设备同步

打卡状态**以服务器上的文件为准**（读书/家务/运动/书单在 `data/tracker_state.json`，作业卡在 `data/homework_checkins.json`）：手机、平板、电脑连的是同一台电脑上的门户服务，看到的就该是同一份数据。浏览器 localStorage（每日记录 `gh_<标签id>_<孩子名>`、书单进度 `ghp_<标签id>_<孩子名>`、作业打卡 `hw_<孩子名>`）只当断网时的本地缓存。

- 读写接口：`GET /api/tracker?tab=<标签id>` 读、`POST /api/tracker` 写（body `{ tab, records, progress }`）；作业打卡是 `GET/POST /api/homework/checkins`。
- 合并规则：同一天 / 同一本书比较 `ts`（毫秒时间戳）取新的，两台设备同时改也互不覆盖；升级前的旧数据没有 `ts`，取并集，不丢已读章节、不丢已打的卡。
- 页面打开时、切回前台时、以及每 12 秒各拉一次服务器状态；勾选后 0.3 秒内自动推回服务器（若此刻正好在同步，会记下来等这轮结束补推，不丢改动）。卡片上有一行小字显示「已同步 / 暂时连不上服务器」。
- 页面独立打开（不走门户服务器，例如双击单文件版）时自动退回纯本机存储，不会报错。

**「📜 查看打卡记录」（通用打卡页 `tracker.html`：读书/家务/运动）的规矩**：

- **按「有记录」列出，不只按「打过卡」列**：某天点了大按钮 → 「✓ 已打卡」；某天只写了一句 / 只录了一段音（没点大按钮）→ 也照样列出来，标「📝 有记录」并显示那句话或录音识别出的文字。中间那条 `dayDone()`（连续天数、圆点）仍旧只认大按钮的 `done`，两套口径别混。
- **空状态分三种，不许一上来就说「还没有打卡记录」**：服务器还没回话 → 「⏳ 正在读取服务器上的打卡记录…」；连不上服务器 → 「⚠️ 暂时连不上服务器…联网后会自动补上」；确认真没有 → 才说「还没有打卡记录，今天开始第一次吧！」。
- **点开记录本会顺手 `syncNow()` 跟服务器对一次**：新手机、清过浏览器缓存也能立刻读到真实记录；`refreshAll()` 里那块只读面板不参与"正在输入就别重画"的保护，必须每次都重画（否则同步到新数据也刷不出来，看起来一直是空的）。
- 录音的 ▶️ 万一播不出来（音频文件被清过、换过电脑），要显示「（这段录音的音频文件不在了，文字还留着）」，不能让点击既没声音又没反应。
- **删录音要连记录里那条引用一起清**：打卡记录里的 `records[日期].voice` 是挂在当天记录上的一份引用，光删 `data/voice/` 里的那条（🗑 删除走的是 `POST /api/voice/delete`）会留下"空引用"，这一天还会在记录本里显示「📝 有记录」，像是没删干净。所以 `Voice.attach` / `Voice.listInto` 都要接 `onDeleted`（通用打卡页是 `clearVoiceRef()`，读书页同理两条记录都扫），把该天的 `voice` 删掉、`ts` 取新后再推回服务器 —— **只留一个只剩 `ts` 的空壳，不要删这一天的键**（服务器按时间戳合并、取并集，键没了会被服务器那份带回来）。
- 版式：**打卡模块（大按钮 + 一句话记录 + 录音）在上面，「📜 查看打卡记录」按钮在它下面**，记录本展开在最后 —— 先打卡、往下才翻记录。

### 读书打卡（`web/reading.html`：自由阅读 + 书单）

「读书」与「书单」原来是两个标签页，现在**合并成一个页面**（一个门户标签「读书」→ `/web/reading.html?id=reading`），页面里用两个大按钮切换两种读法：

- **自由阅读**：原来的读书页（`type: "single"`）——大打卡按钮 + 一句话记录 + 录音转文字，还有连续天数与最近 7 天的圆点。
- **书单**：原来的书单页（`type: "progress"`）——一本书一张卡、逐章勾选，章节列表来自 `data/booklist.json` 的 `chapters`。

合并的只是**页面**：两条记录仍是各自独立的两份数据（`tracker_state.json` 里的 `reading` / `booklist` 两个标签），旧数据不用迁移（localStorage 沿用 `gh_reading_*`、`ghp_reading_*`、`gh_booklist_*`、`ghp_booklist_*` 这些老键）。

- **打卡记录按月日历显示**：日历在页面下半部分，蓝点＝那天自由阅读打过卡，橙点＋数字＝那天书单读完几章，今天有蓝框；◀ ▶ 换月、「今天」跳回本月，上方一行「本月：自由阅读 X 天 · 书单 Y 章」。
- **点某一天 → 显示当天读了什么**：日历下面立刻列出这天 ① 自由阅读的打卡状态、一句话记录、录音（▶️ 听 + 识别出的文字，双显示）② 书单读到的**具体章节名**（如「小巴掌童话·雨天的歌」），以及这天录的音（音频 + 文字）。哪天有记录，日历格上就有圆点，鼠标悬停还有一行小字提示。
- **书单章节要记到天**：勾一章时除了改 `progress`，还会在该天记录里补一条 `records["YYYY-MM-DD"].chapters = [{ book, idx }]`，日历点开那天才看得到读了哪几章；取消勾选会把这条一起撤掉。旧数据（只有 `done`、没有 `chapters`）显示「这天读过书单（当时还没记具体章节）」。
- **勾一章就念这一章的名字**：点某一章会念出**章节名**（如「雨天的歌」）再接一句「读完啦！」，不再笼统地只说"读完一章"；整本读完时改念庆祝语「这本书读完啦，你是小书虫！」。这条对**以后新增的书单同样有效**——往 `data/booklist.json` 加书加章节，`voice-dubbing` 技能会把这些章节名自动补成音频（门户服务器每 20 秒检查一次内容改动，`booklist.json` 在监控列表里），通用打卡页 `tracker.html` 的 `progress` 类型也走同一套逻辑。实现见两页里的 `speakChapter()`（先念章节名、再念"读完啦！"，用 `TTS.speakSeq`）。
- 勾完一章**不会自动收起**：只更新被点的那一行（勾选状态、书头上的「已读 x / y 章」、顶部的累计章数），不整页重画，因此不会跳回顶部；展开状态记在 localStorage（键 `ghb_open_<标签id>_<孩子名>`），点书头才折叠。
- 旧地址 `/tracker.html?id=reading`、`/tracker.html?id=booklist` 会自动跳到这个页面（`&mode=booklist` 直接进书单模式），老书签不用改。切到哪个模式会记在本机（键 `ghread_mode_<孩子名>`），下次打开还是那个模式。
- 每日日报（`report.html`）里仍是「读书」「书单」两行，分别代表自由阅读和书单章节；书单那行现在会写明当天读到的章节名。
- 配置在哪：模式的名字/提示语在 `activities.json` 读书标签的 `modes` 里；书单书目在 `activities.json` 的 `booklist` 标签（`hidden: true`，只在数据里留着、不单独出现在菜单）；章节列表在 `data/booklist.json`。

### 作业卡片（各学科页 + `web/homework.html`）

作业是**按科目分发到学科页**的：每张作业卡带一个 `subject`，语文页只显示语文作业、数学页只显示数学作业、辅导班页/学校英语页各显示自己那一科。**原来的独立「作业打卡」页已经删掉**，打卡就在学科页里做；完成情况汇总进「日报」。

- **学科页**（孩子用，家长也能顺手加）：`/web/subject.html?subject=chinese`（语文）、`?subject=math`（数学）、`/web/english-class.html`（辅导班英语）、`/web/school-english.html`（学校英语）。每页里的「作业区块」由共享模块 `web/homework-section.js` 渲染，包含：当天有效期内（`start ≤ 今天 ≤ end`）的作业卡（图片/视频/PDF、大按钮打卡、连续天数、最近 7 天圆点、每张卡一句语音记录）；已结束/未开始的折叠在底部只读展示；「＋ 添加XX作业」弹层（名称/说明/有效期今天·一周·一个月/上传图片视频）；卡片右上角 ✏️ 编辑、🗑️ 删除。
- **写了「第X页」的作业，卡片上直接附课本那一页的图片**（点一下看那一页，再点放大读）——孩子不用家长翻书找。规则：从作业的 `name`/`desc`/`teacherNote` 里解析页码（支持「第20、21、22、23页」「第20～23页」「第15页」，只认「页」字前的数字，所以「第27页做一做第1题」不会把题号当页码），再把**印刷页码 + `offset`** 换成页图路径 `/textbooks/pages/<学科>/p<PDF页码:03d>.jpg`；`offset`、`pages_dir`、总页数都从 `/textbooks/index.json` 读（语文/数学都是 5），**不许硬编码页码**。解析不出页码、或那科还没有电子课本（英语）就整块不显示，不影响打卡。
- **打卡日历整页只有一个**，卡片里不再各挂一个「📜 查看打卡日历」：日历是月视图，绿色圆点＝那天有打卡（数字＝打卡几项）、蓝框＝今天，◀ ▶ 换月、「今天」跳回本月，上行一行小字写「本月：打卡 X 天」。**点某一天，紧跟着列出那天该科打卡的全部内容**。数据全部来自服务器那份记录，所以换台设备点同一天看到的一样。
- **「点某天看当天打卡全部内容」的面板是四个学科页共用的**（面板里能出现哪几段，看页面挂了哪些开关）：
  ① 页面自己那套打卡项（辅导班＝每个知识点板块，如物品词汇、重点句型；学校英语＝每组内容，如「资料视频 ①」；语文/数学没有这一段，直接列作业卡）
  ② 作业卡打卡状态 + 各自的课本页图 + 那天录的「说一句」（音频 + 文字双显示）
  ③ 页面自己那套录音（如学校英语「说」的跟读，也是音频 + 文字）
  ④ 那天该科课学了什么（学习看板 `learned` + 课本页图，只有语文/数学挂）⑤ 那天学习看板里的任务与完成情况（同上）。
  页面自己已经有日历的（辅导班页顶部那条「哪天看哪一课」）就用那一个，模块这边 `pageCalendar: false` + `panelMount: '#dayCard'`，把这段面板放到它日历下面那张卡里，日历还是一个。

- **语文页 / 数学页**还会额外显示 ①「今天语/数课学了什么」（取自学习看板 `days[].learned` 里对应科目的内容 + 教材页图片）②「学习看板里还没加入的语文/数学任务」（点「＋加入」即生成当天作业卡，科目按看板习惯项的 id/名称自动判定，如 `2026-09-23-yuwen-read` → 语文）。
- **作业管理**（`web/homework.html`，家长用）：跨学科的总览页，添加/编辑/删除任意科目的作业卡（加作业时要**选科目**，否则学科页里看不到），并把学习看板近期 `habits`/`homework` 列为「今日学习作业」一键加入。
- **辅导班 / 学校英语页**的作业区块跟着页面选中的日期走：点日历回看某一天，作业卡、页面自己的打卡项（辅导班＝每个知识点板块、学校英语＝每组内容）都切到那天，能给历史日期补打卡；页面上的日期条会写明「正在给哪天打卡」，不是今天时给一个「回到今天」。学校英语页原来只认"今天"的听/看/说打卡已改成按 `SEL_DATE` 走的内容组打卡（`/api/school/checkin` 传 `date` + `key`）。

共享模块的用法（新学科页照这个挂即可，四个学科页现在就是这么挂的）：

```js
HwSection.mount({
  mount: '#hwCard',          // 容器
  subject: 'chinese',        // 科目 id（chinese / math / class-english / school-english）
  subjectName: '语文',        // 中文名（取学习看板「今天学了」时按它匹配）
  emoji: '📖', color: '#E8590C',
  date: function () { return HwSection.todayStr(); },  // 打卡日期，可跟随页面选中的那天
  allowAdd: true,            // 显示「＋ 添加作业」与编辑/删除
  importFromBoard: true,     // 显示「学习看板里还没加入的…任务」＋「这天学习看板任务」两段（语文/数学用）
  showLearned: true,         // 显示「今天学了」，以及「某天打卡内容」里的学情段（语文/数学用）
  pageCalendar: true,        // 整页一个打卡日历；页面自己已有日历的传 false（日历只留一个）
  dayDetail: true,           // 「点某天看当天打卡内容」面板（默认跟着 pageCalendar 一起开）
  panelMount: '#dayCard',    // 可选：把上面两个面板放进页面自己的卡片里（默认排在作业卡下面）
  dayChecks: function (iso) { return []; },        // 可选：页面自己那套打卡项 [{name, detail, done}]
  dayVoices: function (iso) { return []; },        // 可选：页面自己那套录音 [{scope, label}]
  onPickDate: function (iso) { /* 页面跟着切日期 */ },  // 可选：用户在模块日历里点了某一天
  meta: { page: '语文', subject: 'chinese' }           // 语音记录附带的页面信息
});
HwSection.refresh();          // 页面整体重画（切日期后作业卡也要跟着换时用）
HwSection.refreshDay();       // 只重画「日历 + 某天打卡内容」两个面板（页面自己的打卡项变了时用）
HwSection.setDay('2026-09-23');  // 页面自己切了日期：让日历/某天内容跟着走
```

数据与接口：

- 科目清单：`data/activities.json` 的顶层 `subjects` 数组（`id`/`name`/`emoji`/`color`/`page`），门面标签页、学科页、日报都读它；增删科目改这里一处即可。
- 数据：`data/homework.json`（`items` 数组，每项含 `id`/`name`/`emoji`/`color`/`subject`/`desc`/`teacherNote`/`repeat`/`start`/`end`/`media`）。`media` 每项为 `{ id, type: "image"|"video"|"pdf", url, label }`，`url` 为空时管理页渲染成「待添加」占位。**没写 `subject` 的老作业卡只在「作业管理」页出现**，不会落到任何学科页。
- 附件：上传到 `data/homework_media/`，通过 `POST /api/homework/upload`（multipart `file` 字段），返回 `/data/homework_media/xxx` 供静态托管。
- 增删改：`GET /api/homework` 返回 `{ childName, items, subjects }`；`POST /api/homework` 传 `{ op: "add"|"update"|"delete", item|id }`。
- 打卡：**和读书/家务/运动一样落在服务器上**（跨设备同步），数据在 `data/homework_checkins.json`，读写 `GET/POST /api/homework/checkins`。记录格式 `{ 作业id: { "YYYY-MM-DD": { v: 0|1, ts: 毫秒 } } }`——`v=0` 是「取消打卡」，这条记录留着才能把取消动作同步到别的设备；合并规则是「同一项同一天按时间戳取新」，两边都没时间戳（升级前的旧数据）时取并集，不丢已经打过的卡。学科页打开时先跟服务器对一次（**本机之前打的卡会自动补传上去**），之后每 12 秒一轮，勾选后 0.3 秒内推回，区块标题下一行小字显示「已同步 / 暂时连不上服务器」。localStorage 键 `hw_<孩子名>` 只是断网缓存，各学科页与管理页共享同一份。
- **家长页**（门户「家长任务」标签 → `/learn/web/parent.html`，来自 `learning-growth-board`）的「需要监督孩子完成的作业」读的就是**同一份作业卡与打卡记录**（`/api/homework`、`/api/homework/checkins`，外加 `/api/voice?scope=homework` 取孩子打卡时录的那句话）：孩子在学科页打完卡，家长页 12 秒内跟着变；家长页**只读**，不写回记录，家长事项（`days[].parentTasks`）才由家长自己勾。
- 换设备/换页面看到的是同一份：同一个作业 id 的打卡记录不区分是在哪个学科页勾的；学科页底部的**打卡日历**与「点某天看到的打卡内容」也是从这份记录（外加那天同一批作业的语音记录、学习看板里那天的内容）算出来的，所以换台设备点同一天，看到的完全一样。
- 旧数据无需手动迁移：升级前本机存的 `{ itemId: { "YYYY-MM-DD": 1 } }` 会被当作「没有时间戳」读进来，第一次打开学科页就自动并到服务器上。
- 语音记录沿用旧场景名 `homework-<作业id>`，所以以前在「作业打卡」页录的音，现在在学科页里照样能听到、能改文字、能删。

### 布置作业（独立技能 `homework-assigner`）

「布置作业」（读前一天学习内容 → OCR 提生字 → 起草三科作业 → 生成 PDF → 写入本技能 `data/homework.json`）已独立成 `homework-assigner` 技能，触发词「布置作业」。它写入的每项作业会带上 `subject`（语文→`chinese`、数学→`math`、英语→`class-english`），因此会直接落到对应的学科页里；本技能只负责作业的**打卡展示**（`media` 类型 `pdf` 在学科页里渲染成下载按钮）。

### 每日日报（`web/report.html`）

首页「日报」标签页把当天（可选任意日期）所有打卡内容汇总成一张日报，区分「已完成 / 未完成」两类，并给出完成百分比环图与鼓励语，支持网页查看与打印（`@media print` 已隐藏工具栏与反馈按钮）。

- **作业完成情况**：日报顶部有独立的「📝 作业完成情况」卡片，按科目分别汇报（语文 / 数学 / 辅导班英语 / 学校英语），每科一行进度条 +「已完成 x/y」+「还没完成：…」逐项点名；`items[].subject` 为空的老作业卡归到「其它作业」。
- 数据聚合：读书/家务/运动/书单（`gh_<id>_<孩子名>`）、作业卡（`/api/homework/checkins`，取不到退回本机 `hw_<孩子名>`）、学习看板习惯项（`/api/data` 的 `days[].habits/homework`），全部按所选日期取当天状态。学科页与作业几项都优先取服务器上的那份（`/api/tracker`、`/api/homework/checkins`，换台设备勾的也算数），取不到再退回本机 localStorage。
- 已做成作业卡的学习看板任务在「学习任务」一节里**不再重复列**（同一件事不数两遍）。
- 顶部可选展示「今天学了」（来自学习看板 `learned`），帮助孩子回顾当天收获。

### 英语辅导班（`web/english-class.html`）

「辅导班」标签页按周组织课外英语辅导班的资料与作业，让孩子**按知识点打卡**：每一块知识点（物品词汇、重点句型、语法小知识……）的最后都有一个打卡标志，学完一块点一下（按用户要求，原来那四个笼统的「听 / 说 / 读 / 写」大按钮已经去掉，改成只列要求、不打卡）。

- 内容：`data/english_class.json`（`units` 数组，每个 unit 含 `sections` 五个板块——人物/数字/颜色/年龄/故事指令、`dialogue` 课文、`song` 歌曲、`homework` 听说读写说明、`dictation` 默写表、`materials` 音频/视频/PDF 资料）。
- **每个 unit 必须带 `start` / `end`（`YYYY-MM-DD`）**，表示这次更新覆盖的日期区间（辅导班约一周更新一次，填下发日 ~ 下发日+6 天）。页面靠它决定「某天该看哪一课」。
- 时间维度行为：默认显示**今天**所属单元的作业；过往内容收进页面顶部的**日历**（有内容的日期标橙色底、已打卡的日期标 ✓），点任意一天即回看那一次更新的完整作业，也可给历史日期补打卡。今天不在任何区间内时，自动回退到此前最近的一次更新。
- **打卡点＝知识点板块**：`sections[].id` 与单元 id 拼成 key（`<单元id>:<板块id>`，如 `l2-u2:items`）；每个板块卡最后有一行 `✋ 学完了，打卡` / `✅ 已打卡`，点一下写服务器、按钮就地变绿（板块卡也淡淡变绿），不整块重画；页面顶部显示「今日 x/N 个知识点完成」，全打卡时给庆祝动画，卡片列表底部出现一行「🎉 这个单元的知识点都打卡啦」。打卡记录：`data/english_class_records.json`（按日期 + 打卡点布尔），`GET /api/class/data` 读、`POST /api/class/checkin` 写（`{ date, key, done }`）。
- 「📋 这次的要求（听/说/读/写）」卡片只列 `unit.homework` 里老师给的四条要求（纯文本，没有按钮），说明打卡在知识点卡上做。
- 改造前老的 `listen` / `speak` / `read` / `write` 四维记录**只作兼容读**：日历圆点、连续天数、7 天圆点照旧认它们，页面不会再往这四个维度写新打卡。
- 资料文件：放在 `data/class_media/<单元id>/`（音频 mp3、视频 mp4、PDF），`materials[].url` 用 `/data/class_media/...` 绝对路径。
- **加新视频后先查编码**：微信导出的视频常是 H.265/HEVC，Chrome/Edge/Firefox 一律放不了（只有 Safari 能播）。转成 H.264 再放进目录：
  `ffmpeg -i in.mp4 -c:v libx264 -preset fast -crf 23 -pix_fmt yuv420p -c:a copy -movflags +faststart out.mp4`
  服务器已支持 HTTP Range 请求（视频可拖进度条、iOS 能播），这部分无需额外配置。
- 资料类型按 `type` + 扩展名自动识别（video / audio / image / 其余走链接），所以 `.docx` 默写表不会误当音频；`url` 为空则渲染成「待添加」占位。
- **加新的一周**：在 `units` 数组追加一个新对象（换 `id`/`title`，填好新的 `start`/`end`），把新资料放进对应 `data/class_media/<单元id>/` 目录即可——旧单元不要删，它们会自动折叠进日历供回看。
- 页面顶部的 `{name}` 占位符会用 `config.json` 的 `childName` 替换（自我介绍句子里用到）；孩子若改用英文名，替换 `childName` 即可。
- **本科作业区块 + 「某天打卡内容」面板**：页面里还有一块「今天的辅导班英语作业」（共享模块 `homework-section.js`，`subject: 'class-english'`），只显示归属辅导班的作业卡，可打卡、加作业、编辑删除；打卡日期跟着日历选中的那天走（能补历史打卡），打卡记录与其它学科页同为一份。
  按学科页统一方式，本页在**自己那条日历下面**加了一张「某天打卡内容」卡（`panelMount: '#dayCard'`、`dayDetail: true`、`pageCalendar: false`，所以整页仍然只有一个日历）：点某一天，列出那天 ① 各个知识点板块的状态（由 `dayChecks` 提供，附带那天该看哪一课）② 作业卡打卡情况 + 那天录的「说一句」③（若那天有）学情与看板任务。切日期时页面上有日期条写明是哪天，不是今天时给「回到今天」。

### 学校英语（`web/school-english.html`）

「学校英语」标签页承载**校内**英语（外研社《新交际英语》），与「辅导班」（课外 Kid's Box）是两条独立轨道：按学校下发的单元资料（歌曲/课文录音/视频），让孩子每天跟着看完、练一练，磨出语感。**打卡方式和辅导班一样：一组内容（＝一个视频/一段材料）下边跟着一个打卡标志**（原来「听 / 看 / 说」三个分别打卡的按钮已按用户要求删掉）。

- 内容：`data/school_english.json`（`textbook` 教材名 + `units` 数组，每个 unit 含 `teacherNote` 老师寄语、`tasks` 听/看/说三项（只作说明文字）、`materials` 视频资料，可选 `groups` 内容组、可选 `start`/`end` 日期区间）。
- **打卡点＝内容组**：`units[].groups[].id`（没写 `groups` 就**一条材料一组**，`id` 直接用材料 id，如 `v1`）。想把几条材料合成一组、或给组起个好懂的名字，就在该 unit 加 `groups: [{ id, emoji, title, desc, materials: ['v1','v2'] }]`；没被任何组引用的材料会自动补成自己一组，不会漏。学校再发新视频，只要往 `materials` 里加一条，页面就自动多出一组带打卡的内容，不用改代码。
- 打卡记录：`data/school_english_records.json`（按日期 + 内容组布尔），接口 `GET /api/school/data` 读取、`POST /api/school/checkin` 写入（`{ date, key: 内容组id, done }`）。改造前老的 `listen`/`watch`/`speak` 三维记录**只作兼容读**：日历圆点、连续天数、7 天圆点照旧认它们，页面不再往这三个维度写新打卡。
- 资料文件：放在 `data/school_media/<单元id>/`，`materials[].url` 用 `/data/school_media/...` 绝对路径。
- **录音可删**：「说」跟读区的历史录音每条都有 `▶️ 播放 / ✏️ 改文字 / 🗑 删除`，录错了、念得不好的直接删掉（音频与文字一起删，走 `POST /api/voice/delete`），场景名 `school-english-speak-<单元id>`。「说」不再是打卡点——录音本身就是"说过"的痕迹，会出现在「某天打卡内容」面板里。
- **加新的一周**：学校发新单元资料时，在 `units` 数组追加新对象（写了 `start`/`end` 的话，页面按日期区间自动切单元），把视频放进对应 `data/school_media/<单元id>/`，刷新即生效。
- 时间维度：内容组的勾选打卡**按 `SEL_DATE`（页面选中的那天）走**，默认今天；在下面的日历里点某一天就切到那天，能给历史日期补打卡。不是今天时，内容组卡上方会出现日期条「🕘 X月X日 的打卡」＋「回到今天」，点它回到今天（同时把日历/某天内容也带回今天）。页面顶部显示「今日 x/N 组内容完成」，全部打完给庆祝动画。
- **本科作业区块 + 「某天打卡内容」面板**：页面里还有一块「今天的学校英语作业」（共享模块 `homework-section.js`，`subject: 'school-english'`），只显示归属学校英语的作业卡，可打卡、加作业、编辑删除；整页的打卡日历也在这一块里（本页没有别的日历）。点日历某一天，紧跟着列出那天 ① 各内容组的状态（`dayChecks`）② 作业卡打卡情况 + 那天录的「说一句」③ 那天录的「说」跟读（`dayVoices`，场景 `school-english-speak-*`，音频 + 文字双显示）。学校还没布置英语书面作业时作业卡会是空状态 + 「＋ 添加学校英语作业」，不影响上面的内容组打卡。
- 「说」的录音记在**当前选中的那天**（`Voice.attach({ date })`），所以回看某天时补录的也和那天对得上。

### 词汇配图（`data/vocab_images/`）— 硬性约定

**所有英语词汇都必须带配图**，帮孩子建立「词 ↔ 物」的直接关联，而不是靠中文翻译来记。

- 每条词汇在 `items[]` / `dictation.words[]` 里带 `img`（本地图片路径）或 `emoji`（兜底）二选一；页面渲染成 56×56 的配图块（`itemVisual()`）。
- 图库统一放 `data/vocab_images/<词>.svg`，**跨单元复用同一张图**（如 table 在多个单元出现时共用一张）。
- 配图方式按词性分：
  - **实物名词、动作词** → 专门画的 SVG 简笔插画（100×100 viewBox、描边 `#4A3B2A` 宽 4、明亮填充，与页面绘本风一致）
  - **颜色** → 纯色块
  - **数字** → 阿拉伯数字 + 对应个数的圆点（顺便建立数量概念）
  - **人物、抽象语法词**（this/that/my/your 等）→ emoji 兜底即可
- **新增词汇时同步补图**：先放 `data/vocab_images/<词>.svg`（或 .png），再在 JSON 写 `"img": "/data/vocab_images/<词>.svg"`；确实找不到合适图形才退回 `"emoji": "…"`。**不要留没有配图的词汇。**
- 现有图库 29 张：table / chair / book / pen / pencil / bag / eraser / school / close-door / sit-down / stand-up / open-book / red / green / purple / orange / pink / blue / yellow / one–ten。

### 朗读与配音（`web/vendor/tts.js` + `data/tts/`）

页面上的 🔊 朗读不再只依赖手机的系统语音引擎：能配到音频的内容直接播 mp3，配不到的才退回浏览器朗读，两条路都失败时页面底部会给出提示（不再"点了没反应"）。

- 音频清单：`data/tts/index.json`（按语言分 `en` / `zh`，key 就是文本本身）；音频文件在 `data/tts/audio/<hash>.mp3`。
- 生成工具已独立成 **`voice-dubbing` 技能**：`python .trae/skills/voice-dubbing/tools/gen_tts.py`（`--dry-run` 只预检、`--force` 全量重生成），产出会自动对齐清单、清理多余文件；`node .trae/skills/voice-dubbing/tools/verify_tts.js` 自检有没有漏配（有漏配退出码为 1）。
- **已接入的页面**（10 个）：**学科页 `subject.html`（语文/数学）**、辅导班 `english-class.html`、学校英语 `school-english.html`、通用打卡页 `tracker.html`、**读书打卡 `reading.html`**、作业管理 `homework.html`、学习看板 `dashboard.html`、书包清单 `checklist.html`、家庭图书馆 `library.html`、画作档案 `art.html`。学科页里的作业区块由 `web/homework-section.js` 渲染，庆祝语（「X 打卡成功」「X作业全部完成」）的文本已由 `voice-dubbing` 从 `homework.json` / `activities.json` 的 `subjects` 推出来配音。
- **播放优先级：全站统一"音频优先"**。所有页面、所有会被读出来的内容都播电脑端用 edge-tts 合成好的 mp3；只有清单里确实没有这条音频时才退回浏览器朗读，作为最后兜底。原先学习看板、书包清单的"手机音色选择"已取消（统一用配音音频后没有意义）。
- **自动补齐已开启**：门户服务器（`web/preview_server.py`）启动时补一次，之后每 20 秒检查内容文件改动，一变就自动跑增量生成，所以"加了内容忘了补配音"也不会漏；状态看 `GET /api/tts/status`。手动命令（预检/强制全量）见 `voice-dubbing` 技能。
- **新增内容后调用 `voice-dubbing` 技能补配音**：加英语单词句子（`english_class.json` / `school_english.json`）、加作业项、改标签页、**往书单加书加章节（`booklist.json`，章节名要念给孩子听）**、改课表用具，以及兄弟技能新增书目/画作/学情后，都要跑一次；脚本会从这些数据里推出"书名＋简介""标题＋孩子口述""某某打卡成功""章节名"等句子。`{name}` 占位符按 `config.json` 的 `childName` 生成。
- 页面调用方式：`TTS.speak(text, 'en'|'zh', {waitEnd})`，连续朗读用 `TTS.speakSeq([...], 'zh')`；字符串是否命中音频由清单决定，页面不用关心。音频都在点击处理里直接播放（用户手势之内），页面打开时不会主动出声。
- 模块副本：`learning-growth-board` / `school-bag-organizer` / `home-library` / `xiaoshan-art-archive` 四个技能的 `web/vendor/tts.js` 是同一份拷贝，**改完 `growth-home` 那份要记得同步复制过去**。各技能独立启动自己的预览服务器时拿不到门户的 `/data/tts` 清单，会自动退回浏览器朗读，不影响使用。
- `school-bag-organizer/web/build_standalone.js` 生成单文件版时会移除 tts.js 引用（单文件拿不到配音清单）。
- 换音色或语速：改 `voice-dubbing/tools/gen_tts.py` 顶部的 `VOICE_EN` / `VOICE_ZH` 与 `rate_for()`，再 `--force` 重生成。

### 语音记录（录音 + 自动识别成文字）

全站统一的语音入口：手机上点 🎤 直接录，或用手机自带「录音机」录好后点 📁 上传录音选文件；语音传到门户服务器落盘，**服务器自动把语音识别成文字**，文字和语音一起存档——孩子说的话既能听、也能读，还能进日报与档案。

- 组件：`web/vendor/voice.js`（五个技能的 `web/vendor/` 各存一份，**改完要 5 份一起对齐**）。`Voice.attach({ mount, scope, lang, autoFill, meta, onSaved, onDeleted })` 生成「🎤 录音 / 📁 上传录音 / 🗑 删除」一整套 UI，录完自动上传识别并把文字写进 `autoFill`；`Voice.listInto(el, { scope })` 渲染「▶️ 可播放 + ✏️ 可改文字 + 🗑 可删除」的历史列表。
- **删除录音**：录错了、不想要了都能删。`attach` 那一行的「🗑 删除」在还没存上时只清本地预览，已经存好的那条会连服务器上的一起删掉；历史列表每条右侧也有「🗑」，点一下确认即删。走 `POST /api/voice/delete`（`{ id }`），删的是 `data/voice/index.json` 里那条 + 对应的音频文件（删了就找不回来，所以按钮先弹一次确认）。`Voice.remove(id)` 可单独调用。
- 识别引擎：`web/asr.py`（faster-whisper，CPU int8 推理，**完全离线、音频不出电脑**）。服务器启动时后台预热模型；默认 `small`（中文准确度明显好于 base），本机只下了 `base`/`tiny` 时自动退回。环境变量 `SHAN_ASR_MODEL` 指定模型、`SHAN_ASR_BEAM` 调解码宽度（默认 1，实测质量与 5 相当、约快三成）。
- 存档位置：`data/voice/index.json` 索引 + `data/voice/audio/<场景>/<日期>/<id>.<ext>`。手机录音机多半给 m4a，浏览器录音给 webm/mp4，按文件头判断后缀，直接静态托管播放。
- 场景名（`scope`）约定：`art-describe`（画作描述）、`tracker-read-<标签id>`（打卡页读课文录音）、`tracker-note-<标签id>`（打卡页一句话记录）、`homework-<作业id>`、`library-ask`、`library-intro`、`school-english-speak-<单元id>`。读书打卡沿用 `tracker-read-reading` / `tracker-note-reading`，所以合并页面之前录的音照样能听到。
- 已接入的页面：画作 `art.html`（录完描述自动变文字，语音地址挂到画作记录上）、打卡页 `tracker.html` 与读书打卡 `reading.html`（一句话记录 + 读课文录音都是服务器存档 + 自动识别，不再只存本机 IndexedDB；合并页点开某一天还能看到那天所有录音的「音频 + 文字」）、**各学科页的每张作业卡「说一句」**（语文/数学 `subject.html`、辅导班 `english-class.html`、学校英语 `school-english.html`，走共享模块 `homework-section.js`，场景名仍是 `homework-<作业id>`）、家庭图书馆 `library.html`（语音提问自动找书、语音补简介）、学校英语 `school-english.html`（「说」任务录音）。
- **双显示是硬要求**：任何一处语音输入都要「能听 + 能读」（见上面「通用约定」），新页面照抄 `Voice.attach({ autoFill })` + 成对的「▶️ 听 / 文字」结构即可。
- **手机端注意**：Android/iOS 浏览器在 `http://<电脑IP>:8090`（非 https）下拿不到麦克风权限，页面会提示改用「📁 上传录音」——这正是这套设计的默认用法：用手机系统录音机录好，再选文件上传。
- 性能与降级：识别耗时大致与录音时长相当（约 28 秒录音、模型预热后 15~20 秒出文字），页面会显示「正在识别成文字… N 秒」；识别失败或没装 faster-whisper 时**音频照常存档**，只是提示手写文字（状态见 `/api/voice/status`）。
- 依赖：`pip install faster-whisper`（本机已装，模型缓存在 `~/.cache/huggingface/hub`）。换模型或换机器后第一次识别会先加载模型，稍慢。

### 家庭图书馆（`web` 页面由 home-library 技能提供）

「图书馆」标签页把家里的实体书架搬到网上：书架按「书架 → 层」陈列书封，点开一本书看简介、改归架位置；孩子有问题时用「帮我找书」按主题从自家藏书里挑书，并给出「哪个书架、第几层」。

- 数据在 `home-library/data/`：`shelves.json`（书架与层数，层号从最下层往上数，最下层是第 1 层）、`books.json`（书目）、`config.json`（`childName`/`libraryTitle`）。封面照片在 `home-library/images/covers/`。
- 页面读取走 `/lib/data/*.json` 静态文件，写入走 `POST /api/library`（`add`/`update`/`delete`）与 `POST /api/library/upload`（封面照片，上限 30MB）。
- 拍照入库、按问题推荐书的完整流程见 `home-library/SKILL.md`（不编造出版社与简介；位置不明就放「还没归架」）。
- 与「书单」标签页的区别：书单是每日阅读打卡清单，图书馆是家里**实体书**的馆藏档案；书单里的书可以在图书馆中补全出版社/简介并归架。

### 用户反馈通道

每个页面右下角都有一个「💌 提建议」悬浮按钮，用户写的改进建议会自动变成作者 GitHub 仓库里的一条 Issue，并推送到作者的飞书。**项目分发出去后，别的家庭在自己电脑上运行时，反馈照样能送达**——这是这套机制的设计目标。

数据链路（三条，按可用性自动降级，一条都不丢）：

```
页面反馈组件 vendor/feedback.js
  → POST /api/feedback（本地 preview_server.py）
      ① 落盘 data/feedback/inbox/<id>.json（本机永久存档）
      ② 转发到公网中转服务 feedback-relay/worker.js（Cloudflare Worker）
            → 自动建 GitHub Issue（截图先传到仓库 feedback-assets/）
            → 推送飞书卡片
      ③ 转发失败 → 标记 pending，后台每 5 分钟自动补发
  → 本地服务器都不可用时（如直接双击打开单文件版）
      浏览器直连中转服务；再失败则存 localStorage 队列，下次打开面板自动补发
```

**为什么必须经过本地服务器转发**：浏览器直连第三方接口会被 CORS 拦住，Python 端发请求没有这个限制；顺带还能落盘排队、断网补发。

**iframe 约定**：门户首页用 iframe 装载子页面，如果每个页面都渲染按钮就会重叠。所以组件规定「只有顶层窗口渲染按钮」，子页面只通过 `postMessage` 上报自己的路径、标题、所属技能；首页收到后，反馈里的「页面」自动指向用户正在看的那个子页面，同时保留「经由门户首页」线索。子页面被单独打开时（自己就是顶层），照常渲染按钮。

**通道配置**：`data/feedback_channels.json`（真实值，不入库）→ 读不到时回退 `data-templates/feedback_channels.json`（随项目分发的默认值，作者的中转地址就写在这里）。

```json
{ "enabled": true, "relay": { "url": "https://xxx.workers.dev/feedback", "appKey": "" }, "lark": { "webhook": "", "secret": "" } }
```

`lark` 一段是**作者本机专用**的直连飞书通道，方便自测；分发版必须留空，否则等于把 webhook 公开给所有人。普通用户的飞书通知由 Worker 端用密钥推送，不经过用户本机。

**隐私**：只收集页面路径、设备与浏览器、屏幕尺寸、皮肤名、随机匿名安装ID、主机名指纹（SHA-256 前 8 位，不含主机名原文）。不收集姓名、学校、班级；面板里有明确告知，也可展开「看看会一起发送哪些信息」核对。

**改了 `vendor/feedback.js` 之后**，务必执行 `python tools/sync_vendor.py` 把四个技能的副本对齐（`--check` 只检查不写入）。

## 数据结构

### activities.json
```json
{
  "tabs": [
    {
      "id": "reading",
      "name": "读书",
      "emoji": "📖",
      "color": "#4DABF7",
      "type": "single",
      "goal": "每天读书15分钟",
      "question": "今天读了什么书？",
      "placeholder": "写下今天读的书…",
      "src": "/web/reading.html?id=reading",
      "booklistTab": "booklist",
      "modes": {
        "reading": { "name": "自由阅读", "emoji": "📖", "hint": "想读什么就读什么" },
        "booklist": { "name": "书单", "emoji": "📚", "hint": "老师给的书，一章一章读" }
      }
    },
    {
      "id": "chores",
      "name": "家务",
      "emoji": "🧹",
      "color": "#F06595",
      "type": "single",
      "goal": "每天做1-2件家务",
      "question": "今天做了什么家务？",
      "placeholder": "写下今天做的家务…"
    },
    {
      "id": "booklist",
      "name": "书单",
      "emoji": "📚",
      "type": "progress",
      "hidden": true,
      "items": [ { "id": "yw-xiaobazhang", "name": "小巴掌童话", "emoji": "📖" } ]
    }
  ]
}
```

字段说明（除 `id`/`name`/`emoji`/`color`/`type` 外都可省略）：

| 字段 | 作用 |
|---|---|
| `type` | `single` 大按钮打卡 / `list` 多项目勾选 / `progress` 逐章书单 |
| `src` | 该标签页指向自己的页面（如合并页）；不填就用通用打卡页 `tracker.html?id=<id>` |
| `hidden: true` | 不单独出现在门户菜单里（该标签已并入别的页面，如 `booklist` 并入 `reading`），数据与配置照旧生效 |
| `booklistTab` | 读书标签用：书单数据在哪个标签下（默认 `booklist`） |
| `modes` | 读书标签用：两个模式的名字/图标/一句提示 |

### subjects（`activities.json` 顶层）

学科清单，门面标签页、学科页、日报、作业归科都读它：

```json
"subjects": [
  { "id": "chinese",        "name": "语文",       "emoji": "📖", "color": "#E8590C", "page": "/web/subject.html?subject=chinese" },
  { "id": "math",           "name": "数学",       "emoji": "🧮", "color": "#1C7ED6", "page": "/web/subject.html?subject=math" },
  { "id": "class-english",  "name": "辅导班英语", "emoji": "🏫", "color": "#F76707", "page": "/web/english-class.html" },
  { "id": "school-english", "name": "学校英语",   "emoji": "🎧", "color": "#12B886", "page": "/web/school-english.html" }
]
```

- 作业卡的 `subject` 就是这里的 `id`；加一个新科目（比如「科学」）＝复制一项改 `id`/`name`，再让对应页面挂一次 `HwSection.mount({ subject: '新id' })`。
- `page` 只在「语文/数学」学科页底部的「其它学科」快捷入口里用到；`name` 会用于日报分科标题与庆祝语（`voice-dubbing` 会据此补「XX作业全部完成，你真棒！」的配音）。

## 打包发布

**代码与隐私的隔离靠工具保证，不靠人记得住**（约定见 `.trae/rules/project_rules.md` 第 8 节）。
不要再手工「复制一份再删掉 data/」——统一走仓库根目录的打包器：

```bash
python tools/build_dist.py                    # 门户全套（默认把 7 个兄弟技能一起打）
python tools/build_dist.py --bundle           # 整仓发布包：技能 + 网页框架 + setup.py + tools/ + 规则
python tools/build_dist.py --skills growth-home
```

打包器做的事：白名单取件（**`data/` 根本不参与复制**，不是复制后删）→ 用各技能的 `data-templates/`
重建包内 `data/` → 归一 `SKILL.md` frontmatter（`---`、name 去引号、补 `agent_created`）→
包内带上 `.trae/rules/` 与 `开始使用.md` → 出包后自动解开 zip 扫敏感词/手机号/身份证/本机绝对路径，
**命中就删包中止**。整仓包只带教材的 `index.json` / `book_meta.json`，不带 PDF 与页图（版权与体积）。

发布前仍要人过一遍的两件事：

1. **反馈通道**：`data-templates/feedback_channels.json` 的 `relay.url` 填你部署好的 Worker 地址
   （不填则用户反馈只落他本机）；`lark.webhook` / `lark.secret` **必须留空**——写进模板等于把你的群公开。
2. **vendor 五份对齐 + 补配音**：`python tools/sync_vendor.py`（`--check` 只查不写）、
   跑了 `voice-dubbing` 之后再更新 `VERSION`。

分发方式与用户侧流程（配置自己的信息 → 启动网页服务 → 用新技能加个性化需求）见包内 `开始使用.md`；
要上架 WorkBuddy 开放平台则在此基础上提交审核（技能包根目录必须有 `SKILL.md`）。

## 注意事项

- 页面风格遵循已验证的工程约定：零外部依赖、本地拼音库、朗读统一走 `voice-dubbing` 预生成的音频、只在用户点击时出声。
- 首页顶栏（「成长家园」标题 + 标签菜单）是一整条 `.topbar`，始终驻留在最上方：内容往下滑时自动压成一条细带，把屏幕让给内容；滑回顶部自动展开，也可以点标题手动收起/展开（选择记在本机 `gh_header_compact`）。收起判定用 60px 收起 / 20px 展开两个阈值，避免来回抖。主页高度用 `height:100%` + `-webkit-fill-available`，再用 `@supports (height:100dvh)` 增强，老浏览器不会把 iframe 内容区压扁。
- 首页 iframe 集成不改动兄弟技能的页面；它们各自的 `preview_server.py` 仍可独立运行（8091 / 8090），但同一时间只应启动门户，避免端口混淆。
- 门户服务器是**多线程**的（`ThreadingServer`）：转发反馈到公网可能等十几秒，单线程会把静态页面一起卡住。改成单线程会导致「提交反馈时整个门户打不开」。
- 启动时会自动探测 8090 是否被占用并直接退出报错。这是刻意的：Windows 上 `SO_REUSEADDR` 允许两个进程同时绑同一端口，请求被随机分给新旧两个服务器，表现为「页面能开但新接口 404」，极难排查。
- 反馈组件的悬浮按钮与弹层用 `z-index: 90000`，高于各页面已有的庆祝动画（1000）与弹层（999），不会被盖住；各页面自己的右下角悬浮主按钮（画作页「＋ 记一幅画」、图书馆「＋ 加一本书」）`bottom` 设成 `74px` 让开它，否则两者叠在右下角会把主按钮压住点不到（手机上前者正是最常用的入口）。
- 隐私：对外分享截图时避免暴露学校全名与其他孩子姓名。反馈面板已内置同样的提醒，并会明确告知自动附带哪些信息。


---

name: school-bag-organizer
description: "管理课表与课程用具要求，处理班级通知截图，生成每日书包整理清单。当用户发送班级通知截图、询问'明天带什么''书包整理''课程提醒'或需要根据课表准备物品时调用。"
agent_created: true
---

# 书包整理助手

根据课表和每门课的用具要求，结合班级群通知，提醒第二天的书包整理清单。生成适合 6 岁儿童使用的交互式 HTML checklist（大复选框、拼音标注、语音朗读）。

## 目录结构

代码全部在技能文件夹内，便于打包发布；**真实数据在仓库之外**。以技能根目录为基准（即本 `SKILL.md` 所在目录）：

**代码侧**（公开、可分发）：

```
school-bag-organizer/
├── SKILL.md                     # 本文件
├── skill.json                   # 声明 url=bag / 代码目录 / 数据目录 / standalone.mode=localstorage
├── DATA.md                      # 数据落在哪里（仓库之外的 data-root）
├── data-templates/              # 发布用的通用示例数据（不含任何个人信息）
│   ├── config.json
│   ├── schedule.json
│   ├── course_requirements.json
│   ├── notifications.json
│   ├── holidays.json
│   └── feedback_channels.json   # 反馈通道配置（默认 relay.url 留空 = 不外发）
└── web/                         # 交互式清单网页与本地预览服务器
    ├── checklist.html           # 主页面（双模式：动态fetch / 内嵌数据）
    ├── preview_server.py        # 局域网预览服务器（含 /api/feedback 反馈出口）
    ├── feedback_backend.py      # 反馈本地后端（落盘 + 转发 + 补发 + 限流）
    ├── build_standalone.js      # 生成 Cloud 模式自包含单文件（产物落 data-root，绝不写回仓库）
    └── vendor/
        ├── pinyin-pro.js        # 本地拼音库（无需联网）
        ├── themes.js            # 主题配置
        └── feedback.js          # 页内「提建议」反馈组件（见「用户反馈通道」）
```

**数据侧**（**仓库之外**，本技能目录里没有 `data/`）：`<data-root>/bag/data/`
（`config.json` 孩子姓名/学校/年级/班级/教材版本/morningCutoff、`schedule.json` 永久课表、
`course_requirements.json` 每门课用具要求、`notifications.json` 历史通知、
`holidays.json` 法定节假日（通用数据）、`feedback/` 反馈本地收件箱）。
路径一律走 `tools/data_paths.py` 的 `skill_dir("school-bag-organizer")` 解析，细节见同目录 `DATA.md`。

**单文件版（standalone）**：`standalone.mode = "localstorage"`——课表/用具要求来自 data-root 的 `data/`，
每天的收拾书包勾选只存 `localStorage`（不必落服务器）；生成的自包含单文件写入 `<data-root>/bag/share/`，
**绝不写回仓库**（含真实信息的单文件不入库、不随包分发）。

## 首次使用引导（重要）

每次被调用时，先检查 `data/` 下的数据是否完整可用。**判断标准**：

- `config.json` 中 `childName` 仍为模板值（如"小明"）或为空
- `schedule.json` 中课表为空、仍是模板示例、或与用户描述不符
- `course_requirements.json` 中大部分课程没有用具要求

若数据缺失或仍是模板，**不要直接生成清单**，而是先引导用户逐项提供信息。按以下顺序询问（一次问 1-2 项，避免信息轰炸）：

1. **孩子基本信息**：姓名、学校、年级、班级（写入 `config.json`）
2. **课表**：请用户拍照上传课表截图，或直接文字输入周一~周五每天的课程（写入 `schedule.json`）
3. **各科用具要求**：请用户提供老师发的用具准备通知（截图或文字），逐科记录（写入 `course_requirements.json`）
4. **教材版本**（可选）：所在地区/年级的教材版本，用于标注课本名称

引导话术示例：
> "你好！我是书包整理助手。要生成准确的清单，我需要先了解几个信息：
> ① 孩子的姓名、学校、年级、班级？
> ② 有没有课表？可以拍照发给我，或直接告诉我每天上什么课。
> ③ 老师有没有发过各科需要准备的用具清单？有的话发截图给我。"

**注意**：
- 用户可能一次只提供部分信息，已提供的立即写入文件，未提供的继续追问，不要重复问已答过的内容。
- 信息收齐前，如果用户坚持要清单，可以用已有数据生成，并明确标注哪些课程"暂无用具要求记录"。
- 用户后续随时可以补充或修改，每次变更后更新对应 JSON 文件。

## 工作流程

### 1. 用户发送截图时

当用户发送班级群通知截图时：

1. **仔细阅读截图内容**，提取所有关键信息：发送者、标题、正文、截止时间、需准备的物品或操作、附件信息。
2. **判断通知类型**并分类处理：

   **永久记录**（需要更新数据文件）：
   - 课表变更 → 更新 `data/schedule.json`
   - 课程用具要求更新/新增 → 更新 `data/course_requirements.json`
   - 长期有效的规章制度 → 记录到 `data/notifications.json`，标记 `type: "permanent"`
   - **改完课表或用具要求后补一次配音**：调用 `voice-dubbing` 技能（`python .trae/skills/voice-dubbing/tools/gen_tts.py`），让新增的课程名与用具名称都有朗读音频，否则手机上点 🔊 可能没声音

   **一次性通知**（执行完即可）：
   - 填表、交回执、签字等 → 记录到 `data/notifications.json`，标记 `type: "one_time"`
   - 特定活动通知 → 记录到 `data/notifications.json`，标记 `type: "one_time"` 并注明日期
   - 若通知要求明天携带某物，务必在该条目中加入 `items_to_bring` 字段
   - **必须填写 `deadline` 字段**（需要上交/完成的日期，格式 `YYYY-MM-DD`）。若通知未写明日期，根据上下文推断（如"明天带回"→ 明天日期），推断不出时向用户确认
   - **顺延机制**：deadline 之后通知不会自动消失。页面会逐日检查该通知的物品是否在当天清单中被勾选——没勾选说明没带去学校，通知自动顺延到第二天（卡片上显示橙色"已顺延 N 天"徽章），直到用户在浏览器中真正勾选了所有物品（= 已带去学校），通知才从后续清单中消失
   - **按截止日出现**：只有目标日期（今天／下一个上学日／自选日期）**到达或超过**该通知的 `deadline` 时，该通知才会出现在清单里，所以两周后的任务不会提前刷屏；交表类通知会在"今晚整理、明天上交"的前一晚自然出现。
   - 一次通知若涉及两个不同日期（如"9月17日前交知情同意书"+"9月28日接种带证件"），应拆成两条 `one_time` 记录，各写各的 `deadline` 与 `items_to_bring`，让它们分别在临近各自日期时出现
   - 只有当用户明确告知"已经交了/不需要了"时，才把 `status` 改为 `"done"`

3. **处理完成后**，向用户总结：提取了哪些通知、哪些记为永久数据、哪些是一次性任务及截止时间、是否需要立即更新书包清单。

### 2. 用户询问"明天带什么"时

1. 确定目标日期（见下方"显示时间规则"）：可能是"今天"（早上检查模式）或"下一个上学日"（晚上准备模式）；休息日不生成清单。
2. 读取 `data/config.json`、`data/schedule.json`、`data/course_requirements.json`、`data/notifications.json`、`data/holidays.json`。
3. 匹配目标日期的课程与各课用具要求，叠加相关的一次性通知物品。
4. 生成交互式 HTML checklist（见下方"两种交付模式"）。
5. 页面要求：适合 6 岁儿童——大复选框、拼音标注（本地 pinyin-pro 库）、语音朗读（内容统一播放 `voice-dubbing` 技能预生成的 edge-tts 音频，不再依赖手机自带语音）、勾选进度环、全部完成庆祝动画。勾选状态用 localStorage 按"日期+孩子名"存储。
6. 若某门课没有记录用具要求，在页面中标注"暂无特殊用具要求"。

### 2.5 显示时间规则（重要）

页面核心原则：**清单 = 为"下一个上学日"准备书包**。按以下规则决定显示内容，`checklist.html` 已内置该逻辑：

| 当前时间 | 显示内容 |
|----------|----------|
| 上学日 0:00 ~ morningCutoff（默认 09:00） | 标题"今天的书包检查"，显示**当天**清单（早上核对书包） |
| 上学日 morningCutoff 之后，且明天也是上学日 | 标题"明天带什么？"，显示**明天**清单（晚上整理） |
| 上学日 morningCutoff 之后，但明天是休息日（如周五晚） | 大卡片"明天休息啦"＋下个上学日提示，**不显示清单** |
| 休息日，且明天是上学日（如周日） | 显示**明天（周一）**清单，供提前整理 |
| 休息日，且明天也是休息日（如周六、节假日中间） | 大卡片"今日休息"＋下个上学日提示，**不显示清单** |

- 关键区别：**休息日不再一律"今日休息"**。只要"明天是上学日"，就正常给出明天的清单（覆盖周日→周一、假期最后一天→返校日等场景）；只有"明天也不是上学日"（周六、长假中间）才显示休息。
- 休息日判定依据 `data/holidays.json`：`holidays`（法定放假日）＋周末（除非在 `workdays` 调休上班日中）＋`breaks`（寒暑假区间，`{from, to, name}`，用户提供学校校历后填写）。
- 上学日早上 9 点前（morningCutoff 可在 `config.json` 调整）打开同一页面即可核对当天书包。
- 调休上班日（如国庆前后的周日补课）按上学日处理；若当地学校不跟随调休，可在 `holidays.json` 的 `workdays`/`holidays` 中按需调整。
- 每年 11 月左右国务院发布下一年放假安排后，应更新 `holidays.json`（用户可发通知截图，或直接采用官方通知内容）。

### 2.6 按日期查看（自选某一天的清单）

页面上有一个「📅 按日期查看」按钮，供家长**指定任意一天**准备书包（比如提前替三天后、假期返校日整理）：

- 点开后是系统日历选择器（可选范围：今天前 30 天 ~ 今天后 180 天），选中某天立即出那天的清单。
- 自选模式下**按"那一天"本身出清单**，不再走"下一个上学日"推断：那天有课就列那天的课程与用具；
  那天是休息日就显示"这天休息"大卡片＋下个上学日提示。
- 目标日期若与自然周几不同（调休补课，见 `schedule.json` 的 `makeupDays`），日期行会标注"· 按X课表"。
- 界面反馈：标题变为"书包整理清单"，日期行尾部显示"· 自选"，按钮点亮并显示所选日期；
  面板里有「回到今天」按钮可恢复自动模式。
- 勾选状态按"日期+孩子名"分别存 `localStorage`（见 `getStorageKey()`），**自选日期的勾选与当天清单互不影响**。
- 自选日期同样套用 2.5 的规则与通知"按截止日出现/顺延"逻辑。

### 3. 两种交付模式（重要）

`web/checklist.html` 支持两种数据来源，根据运行环境选择：

**模式 A — 局域网动态加载（本地电脑 + 手机同 WiFi）**
- 数据通过 `fetch()` 从 `../data/*.json` 动态加载。
- 启动 `web/preview_server.py`，手机浏览器访问 `http://<电脑IP>:8090/web/checklist.html`。
- 优点：修改 `data/*.json` 后刷新页面即生效，无需重新生成。

**模式 B — 单文件内嵌数据（TraeWork Cloud 云端模式 / 无局域网环境）**
- 云端沙箱无法访问用户本地电脑，也无法让手机访问局域网服务器。
- 做法：复制 `web/checklist.html` 为新文件，把其中的 `const EMBEDDED_DATA = null;` 替换为实际数据对象：
  ```js
  const EMBEDDED_DATA = {
    config: { ...config.json 内容... },
    schedule: { ...schedule.json 内容... },
    requirements: { ...course_requirements.json 内容... },
    notifications: [ ...notifications.json 内容... ],
    holidays: { ...holidays.json 内容... }
  };
  ```
- 产出一个**自包含单文件 HTML**，作为云端任务的产物交付。用户在 TraeWork 手机端即可直接预览/下载该文件，无需服务器、无需联网加载数据。
- 注意：内嵌的 `pinyin-pro.js` 通过相对路径 `vendor/pinyin-pro.js` 引用。生成单文件时，应将该 JS 内容直接内联到 HTML 的 `<script>` 标签中，确保完全离线可用。

### 4. 数据管理

用户可以随时要求：
- "查看课表" → 展示完整课表
- "查看某门课的用具" → 展示该课程用具要求
- "更新课表" → 引导用户提供新课表
- "添加课程要求" → 记录新的用具要求
- "查看待办通知" → 列出所有未完成的一次性通知
- "想看某一天要带什么" → 直接用页面上的「📅 按日期查看」选日期（见 2.6），无需改数据

## 数据结构

### config.json
```json
{
  "childName": "孩子的名字",
  "school": "学校名称",
  "grade": "年级",
  "className": "班级",
  "semester": "学期",
  "morningCutoff": "09:00",
  "textbooks": { "语文": "人教版（部编版）", "...": "各科教材版本，参考当地教委目录" }
}
```
- `morningCutoff`：上学日早上检查模式的截止时间，之前打开页面显示当天清单，之后显示下一个上学日清单。

### holidays.json
```json
{
  "year": 2026,
  "source": "国务院办公厅通知文号",
  "holidays": ["2026-01-01"],
  "workdays": ["2026-01-04"],
  "breaks": [{ "from": "2027-01-16", "to": "2027-02-14", "name": "寒假" }]
}
```
- `holidays`：法定放假日（含调休连休的周末）。
- `workdays`：调休补班日（周末变上班/上课日）。
- `breaks`：学校寒暑假等区间，用户提供校历后填写，可为空数组。

### schedule.json
```json
{ "schedule": { "周一": ["课程1", "课程2"], "...": [] } }
```

### course_requirements.json
```json
{ "语文": ["语文课本", "语文练习册"], "体育": ["跳绳", "运动鞋"], "其他": ["记事本1个"] }
```

### notifications.json
```json
[
  {
    "id": "唯一标识",
    "date": "通知日期",
    "title": "通知标题",
    "content": "通知内容摘要",
    "type": "one_time | permanent",
    "deadline": "截止日期（one_time 必填，YYYY-MM-DD；过期未勾选则逐日顺延）",
    "status": "pending | done",
    "course_related": "关联课程（可选）",
    "items_to_bring": ["需携带物品（可选）"]
  }
]
```

## 用户反馈通道（「提建议」组件，透明说明）

`web/vendor/feedback.js` 是本项目自带的页内反馈组件（由 `checklist.html` 引入），
供使用者在页面上点「提建议」把「哪里不好用 / 想要什么功能」反馈给**本项目的部署者**。
它不是第三方追踪脚本，也不采集任何儿童个人信息。

**它收集什么**（全部为用户主动提交或浏览器基本信息）：
- 用户填写的反馈正文、期望效果，以及**可选的**截图（最多 3 张）；
- 页面地址/标题、浏览器 UA、屏幕尺寸、语言、是否联网等调试信息；
- 一个随机生成的**匿名安装 ID**（UUID，仅用于区分不同家庭，不含姓名/学校）。

**数据流向（默认不外发）**：
1. 浏览器 `feedback.js` → 本地 `preview_server.py` 的 `/api/feedback`；
2. 本地服务器落盘到 `data/feedback/inbox/`，再转发到公网中转服务（`feedback-relay/`）；
3. 中转服务自动在部署者自己的仓库建 GitHub Issue（截图存入仓库），并推送到飞书群。

**关键：默认关闭**。`data-templates/feedback_channels.json` 里 `relay.url` 为**空字符串**，
此时反馈**只保存在本机 `data/feedback/inbox/`，绝不外发**。只有当部署者主动部署了
`feedback-relay/`（Cloudflare Worker）并把 Worker 地址填进 `relay.url` 后，反馈才会送达
部署者本人。即：数据只流向「部署者自己的服务器/仓库/飞书」，不流向任何第三方。

**隐私红线**：
- 匿名安装 ID 随机生成、不含个人信息；主机指纹为 SHA-256 不可逆的前 8 位。
- 组件不自动采集姓名、学校、班级等；若用户在正文里自行填写此类信息，属用户主动行为，
  组件与中转服务的 Issue 正文里已提示「反馈中不应包含孩子的真实姓名/学校」。
- 转发走本地服务器中转（浏览器直连会被 CORS 拦截），断网时先落盘、联网自动补发。

部署者启用通道：见仓库根目录 `feedback-relay/README.md`（部署 Worker → 把地址填进
`data/feedback_channels.json` 的 `relay.url`）。普通使用者无需做任何事。

## 打包发布

**不要手工复制 `data/` 再删隐私内容**——那种做法一定会漏。统一用仓库根目录的打包器：

```bash
python tools/build_dist.py --skills school-bag-organizer     # 出 dist/school-bag-organizer.zip
```

打包器按项目规则第 8 节执行：白名单取件（`data/` 根本不参与复制）→ 用 `data-templates/` 重建包内
`data/` → 归一 `SKILL.md` frontmatter（`---`、name 去引号、补 `agent_created`）→ 出包后自动解开 zip
扫敏感词/手机号/身份证/本机路径，命中就删包中止。

发布前自查：`python tools/privacy_guard.py --all`（这一步 CI 与 pre-commit 钩子也会跑）。

新用户拿到包后：`python setup.py` 填孩子信息与课表 → `python setup.py --start` 起网页服务。

## 注意事项

- 用户可能发送多张截图，逐张处理并在最后汇总。
- 永久数据变更时，先确认再写入。
- 一次性通知完成后，询问用户是否标记为"已完成"。若未标记且孩子当天没勾选（没带去学校），页面会自动顺延到第二天继续提醒，直到勾选或用户明确说不需要为止。
- 每天提醒时，除了课程用具，也提醒记事本等通用项。
- 如果通知中有附件（PDF 等），提醒用户查看附件内容。
- 拼音生成优先用本地 `vendor/pinyin-pro.js`，不依赖外部 CDN，保证离线与国内网络可用。

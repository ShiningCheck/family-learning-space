# 页面契约（成长家园门户）

给 AI 看的实现规格：新增/修改一页时，**照这份做**。需求层的硬要求见
`.trae/rules/project_rules.md`（第 1、2、3、8 节），本文件是它的落地写法。

## 一、接线点（新增一页要动的地方）

| # | 文件 | 位置 | 什么时候要改 |
|---|---|---|---|
| 1 | `growth-home/web/index.html` | `CORE_TABS` 数组 | 页面型标签，**必改**（id/name/emoji/color/src） |
| 2 | `growth-home/web/index.html` | `TAB_ORDER` 数组 | 想在菜单里固定位置时改；不改则排最后 |
| 3 | `growth-home/web/preview_server.py` | `translate_path()` 的前缀分支 + 顶部 `*_DIR` 常量 | 页面在**别的技能目录**里时必改（如 `/piano/` → `piano-practice/`） |
| 4 | `growth-home/web/preview_server.py` | `REDIRECTS` | 需要兼容旧书签/旧二维码时改 |
| 5 | `growth-home/data/activities.json` | `tabs` 数组 | 打卡型标签（读书/家务/运动那种）——**这是用户数据**，改前先跟用户确认 |

前四处都由脚本代劳，别手改：

```bash
python tools/portal_wire.py list                      # 先看现状
python tools/portal_wire.py add-page --id piano --name 钢琴 --emoji 🎹 --src /web/piano.html
python tools/portal_wire.py add-page --id piano --name 钢琴 --src /piano/web/index.html --mount piano --skill piano-practice
python tools/portal_wire.py remove-page --id piano --unmount   # 撤掉
python tools/portal_wire.py undo                      # 撤销上一次
```

## 二、页面骨架（门户内页面）

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>页面名</title>
<script src="vendor/themes.js"></script>        <!-- 必须最早：主题/吉祥物/背景 -->
<script src="vendor/pinyin-pro.js"></script>
<script src="vendor/tts.js"></script>
<script src="vendor/voice.js"></script>
<script src="vendor/feedback.js"></script>      <!-- 右下角「💌 提建议」 -->
<style>/* 大按钮、圆角、18px 基准字号、body 底部留 96px 给反馈悬浮按钮 */</style>
</head>
<body>…</body>
</html>
```

硬性要求：

- **零外部依赖**：不许引 CDN，库一律用 `vendor/` 里的本地副本。
- **同步状态可见**：页面上要有一行小字 `☁️ 已同步 / ⚠️ 暂时连不上服务器`。
- **点一下才出声**：不许自动播放。
- **iframe 内不重复渲染反馈按钮**：`feedback.js` 已处理，别自己再加一层。
- 放在别的技能里时，`vendor/` 用相对路径（`vendor/xxx.js`），并保证该技能 `web/vendor/` 有那五个文件
  （`python tools/sync_vendor.py` 对齐）。

## 三、组件 API

| 组件 | 用法 | 说明 |
|---|---|---|
| `themes.js` | 只要在 `<head>` 最早引入 | 主题引擎：CSS 变量 + 背景 + 手绘吉祥物；`localStorage['gh_theme']`，同源页面/iframe 实时同步 |
| `pinyin-pro.js` | `Pinyin.convert('汉字')` | 拼音标注，离线 |
| `tts.js` | `Tts.speak('文字')` | 朗读：优先播 `data/tts/` 预生成的 mp3，没有才退回浏览器朗读 |
| `voice.js` | `Voice.attach({ mount, scope, lang, autoFill, onSaved })`、`Voice.listInto(el, { scope })` | 语音记录：录/传/删 + 自动识别成文字；历史列表每条都是「▶️ 播 + 文字 + ✏️ 改 + 🗑 删」 |
| `homework-section.js` | `HwSection.mount({ subject, date, dayChecks, dayVoices, onPickDate, setDay, ... })` | 作业卡 + 打卡大按钮 + **整页唯一一个打卡日历**；点某天列出那天全部打卡内容 |

## 四、数据与同步（记录类页面必读）

- **落点**：只写各技能的 `data/*.json`。页面**不许**直读本机文件路径，一切走 `/api/...`。
- **读接口（GET）**：`/api/data`（学习看板聚合）、`/api/home`（门户聚合，含各技能 config）、
  `/api/tracker?tab=<id>`、`/api/homework`、`/api/homework/checkins`、`/api/class/data`、
  `/api/school/data`、`/api/library`、`/api/voice`、`/api/tts/status`。
- **写接口（POST）**：`/api/tracker`、`/api/homework`、`/api/homework/checkins`、
  `/api/class/checkin`、`/api/school/checkin`、`/api/library`、`/api/voice`、`/api/art/upload`、
  `/api/homework/upload`、`/api/library/upload`。
- **合并规则**：同一项 + 同一天（同一本书同一章）按 `ts`（毫秒）取新；**取消也要留一条 `v: 0`**，
  否则取消动作同步不到别的设备；按天的布尔打卡（听/说/读/写…）服务端按 `date + 维度` 覆盖。
- **刷新节奏**：打开时、切回前台、每 12～15 秒各拉一次；勾选后尽快推回，同步中收到改动要排队补推。
- **`localStorage` 只能当断网缓存**。判断标准一句话：**手机、平板、电脑打开同一页，看到的是同一份数据**。

**新增一个自己数据文件/接口时**（v1 没有通用记录接口，需要照抄）：

1. 数据文件放本技能 `data/<名字>.json`，同时在 `data-templates/` 放一份空模板（匿名）；
2. 在 `preview_server.py` 里照抄同类 handler 写读/写函数（带 `threading.Lock()` 与 `ts` 合并），
   并在 `do_GET` / `do_POST` 的路由表里注册；
3. 新技能的页面用 `--mount` 挂载后，接口地址建议也用同一前缀（如 `/api/piano/records`）。

## 五、真实内容与版权

- 教材页图来自工作区 `textbooks/`（门户把 `/textbooks/*` 映射过去）；页码映射读 `textbooks/index.json`
  （印刷页码 + `offset` = PDF 页序号），**不许硬编码 offset/页码/页数**。
- 书名、出版社、简介、学情、画作描述等一律来自真实输入，**不许编**；拿不准就留空或标注待补充。

## 六、验收清单（每次接线后逐条过）

```bash
python tools/smoke_test.py            # 起服务：每页 HTTP 200、常用接口返回 JSON
python tools/privacy_guard.py --all   # 页面/脚本里没有真名、学校、手机号、本机绝对路径
```

- [ ] 菜单里能看到新页面，点开不白屏
- [ ] 页面上有同步状态行；换一个浏览器/无痕打开，看到的是同一份数据
- [ ] 打卡类页面：日历只有一个；点某一天能列出那天的全部打卡内容；能补打卡
- [ ] 有语音的地方：音频能播 + 文字能看到（双显示）
- [ ] 有朗读文字的地方：跑过 `voice-dubbing` 补配音
- [ ] 新增/改动 `web/vendor/` 的：跑过 `tools/sync_vendor.py`（`--check` 确认无差异）
- [ ] 新技能：`data-templates/` 有对应空模板，`SKILL.md` frontmatter 合规（`name` 小写连字符、`agent_created: true`）

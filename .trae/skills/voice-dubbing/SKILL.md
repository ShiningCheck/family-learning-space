---
name: "voice-dubbing"
description: "给成长家园门户批量补配音：把新增的单词句子、书名简介、画作描述、打卡提示用 edge-tts 增量合成 mp3 并更新清单（免费、无需密钥），漏配的内容页面会自动退回浏览器朗读。任何内容新增或修改后，或用户说「补配音」「某个页面没声音」时调用。"
---

# 朗读配音（voice-dubbing）

## 这个技能解决什么

成长家园门户里很多内容要"读出来"（英语单词句子、书名简介、画作描述、打卡提示）。但手机浏览器能不能出声，取决于那台手机有没有装系统语音引擎，国产 ROM 常常没有，点 🔊 就毫无反应。

所以页面改成**优先播放电脑端预先合成好的 mp3**：能配到音频就直接播，配不到才退回浏览器朗读，两条都不行会在页面底部弹出原因提示。本技能负责那批 mp3 的生成与维护。

产物位置：`<data-root>/web/data/tts/`（growth-home 命名空间；`index.json` 清单 + `audio/<hash>.mp3`），由门户以 `/data/tts/` 托管给所有页面。

## 什么时候调用

**必须调用的时机**（这些技能里加了新内容之后）：

| 上游技能 | 触发的动作 |
| --- | --- |
| `growth-home` | 加英语单词/句子、加作业项、改标签页或课表用具 |
| `home-library` | 录入新书、补充书名/简介 |
| `xiaoshan-art-archive` | 记一幅画（标题、孩子口述） |
| `learning-growth-board` | 归档学情报告、新增"学到什么" |
| `school-bag-organizer` | 改课程用具要求、课程表 |

**其他时机**：用户说「补配音」「生成朗读音频」「某页点喇叭没声音」；换音色或语速后重生成；同步到新电脑后（音频不入库，需要本机重新生成）。

## 自动补齐：默认已经在跑

门户服务器 `growth-home/web/preview_server.py` 内置了「新增内容就自动补配音」，正常情况下**不需要手动跑命令**：

- **启动时先补一次**：覆盖"服务器没开着的时候改过内容"的情况；
- **之后每 20 秒检查一次**：内容文件（英语内容 / 辅导班 / 学校英语 / 作业 / 标签页 / 书单 / 书目 / 画作 / 学情 `days/*.json` / 课表用具）的修改时间一变，就自动跑一次增量生成，并顺手清掉不再需要的音频；
- **可查询状态**：`GET /api/tts/status` 返回配音条数与最近一次自动补齐的时间、结果（`完成，新增 N 条` / `无新增（都已配音）`）。

边界：这套机制只在**门户开着**且本机装了 `edge-tts`、能联网时生效。服务器没开时改的内容，会在下次启动时补上。

## 怎么用（手动命令）

需要手动跑的场景：换音色/语速后全量重生成、先看缺了什么、或服务器没启动时临时补一次。

```bash
# 1. 先看缺什么（不生成、不改清单）
python .trae/skills/voice-dubbing/tools/gen_tts.py --dry-run

# 2. 补上缺的（只生成新增和变更的，已存在的直接复用）
python .trae/skills/voice-dubbing/tools/gen_tts.py

# 3. 换音色/语速后全量重生成
python .trae/skills/voice-dubbing/tools/gen_tts.py --force
```

依赖：`pip install edge-tts`（首次使用装一次，需要联网）。

**运行后必须做一次自检**，确认没有漏配：

```bash
node .trae/skills/voice-dubbing/tools/verify_tts.js
```

它会按各页面真实取数路径把运行时会朗读的文本全取出来逐条比对，输出每个数据源的漏配数量，并检查 10 个页面的接入（含学科页 `subject.html`）、是否残留"朗读优先"分支、以及"有音频就播音频、没音频才退回朗读"是否按预期工作。**有漏配时退出码为 1**，最后一行会告诉你漏了几处。（学科页的作业区块由 `web/homework-section.js` 渲染，它本身不是页面、不引用 tts.js，靠宿主页面引入；它的庆祝语文本已被下面的数据源覆盖。）

## 覆盖哪些内容

脚本从数据文件里推导出需要配音的文本，不用手工登记：

| 数据文件（架构 v2 后内容按技能归位到 data-root） | 生成的句子 |
| --- | --- |
| `<data-root>/class/data/english_class.json`（english-class） | 辅导班的板块单词、句子、课文对白、歌词、默写词 |
| `<data-root>/core/data/activities.json`（core 命名空间） | 「X 打卡成功，你真棒！」「X 全部完成，你是小能手！」；`subjects` 里每个科目的「X作业全部完成，你真棒！」 |
| `<data-root>/reading/data/booklist.json`（reading） | 书单里**每一章的名字**（勾一章就念这一章叫什么；加新书自动补） |
| `<data-root>/{chinese,math,class}/data/homework.json`（各学科技能） | 「X 打卡成功，你真棒！」（学科页每张作业卡的庆祝语） |
| `<data-root>/web/data/config.json` 等 | 页面里的固定中文提示语（见脚本里的 `FIXED_ZH`） |
| `<data-root>/learn/data/days/*.json` | 每天"学到什么"的朗读内容 |
| `<data-root>/bag/data/course_requirements.json` | 课程名、每样用具；整理完毕的庆祝语 |
| `<data-root>/lib/data/books.json` | 每本书的「书名＋简介」 |
| `<data-root>/art/data/index.json` | 每幅画的「标题＋孩子口述」 |

## 常见处理

- **某句还是没声音**：先 `--dry-run` 看它在不在待补列表里。在 → 生成即可；不在 → 说明脚本没覆盖它的数据来源，按下面「扩展数据源」加一个 `collect_*`。
- **页面朗读不出声（尤其安卓）**：先看是不是走了浏览器朗读兜底（说明这条内容没配音）。`tts.js` 里"清空队列后等约 60ms 再朗读"这段延迟**不能删**——立即 speak 会被安卓 Chrome 丢掉整句。
- **不要加"页面打开时预播放音频解锁"**：曾试过在首次触摸时静音预播一条清单音频来解锁音频元素，结果因为 `audio.src` 读出来是绝对地址、拿它跟相对地址比较永远不相等，提前 return 没暂停，页面一打开就会冒出"10根小棒"这类声音。全站音频优先后播放都在点击处理里同步发生，本来就不需要预播放，`unlock()` 只保留"音量 0 的语音引擎预热"。
- **判断设备/内容状态**：在页面控制台执行 `TTS.info()`——`lastPlayed` 是最近成功播放的音频、`lastError` 记录播放失败原因、`ttsBroken` 表示已判定该设备朗读无声。
- **换音色或语速**：改 `tools/gen_tts.py` 顶部的 `VOICE_EN` / `VOICE_ZH` 和 `rate_for()`，然后 `--force` 重生成。
- **手机仍不出声**：确认该页面引用了 `vendor/tts.js`（自检脚本会检查这 10 个页面），并确认模块副本是最新的（见下）。
- **生成中断**：直接重跑，已生成的会复用；失败条目会在结尾列出并让退出码为 2。
- **自动补齐没生效**：确认门户在运行（`GET /api/tts/status` 能返回内容）、`edge-tts` 已安装且能联网；容器/无网环境下自动补齐会失败，页面会退回浏览器朗读。

## 扩展数据源

在 `tools/gen_tts.py` 的 `Collector` 里加一个方法，并在 `main()` 里调用：

```python
    def collect_xxx(self):
        """说明这段内容出现在哪个页面。"""
        d = load_json(os.path.join(SKILLS_DIR, "某技能", "data", "某文件.json")) or {}
        for it in d.get("items", []):
            self.add(it.get("name"), "zh", "word", "xxx")      # lang: en/zh；kind 影响语速
```

同时在 `tools/verify_tts.js` 的收集段补上同样的取数路径，这样自检才能覆盖到它。

## 维护约定

- **模块副本要同步**：`web/vendor/tts.js` 在 5 个技能里各有一份（growth-home、learning-growth-board、school-bag-organizer、home-library、xiaoshan-art-archive），改完 growth-home 那份要复制过去，否则页面行为不一致。
- **清单按文本索引**：`index.json` 的 key 就是文本本身，前端不做哈希，改文案会自动视为新条目。
- **音频属个人数据**：`.gitignore` 忽略各技能的 `data/`，换电脑需要重新跑一次生成；不要把它挪到会入库的目录。
- **各技能独立启动自己的预览服务器**时拿不到门户的 `/data/tts` 清单，会退回浏览器朗读，属预期行为，不影响门户内的体验。
- **不负责录音回放**：孩子自己的录音走各自的录音存储，与本技能的配音无关。

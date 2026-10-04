# 常见需求的成做法（recipes）

先走决策树，**能复用就不造新页**——造得越多，以后越难维护。

```
用户说"我想有个页面做 XX"
        │
        ├─ 是"每天做一件事、打一个卡"？ ──────────► R1：只加一个数据标签，零代码
        ├─ 是"跟着课本/单元逐项打卡、要回看历史"？ ─► R2：接 HwSection（带日历那种）
        ├─ 是"看趋势/统计"？ ────────────────────► R3：自绘轻量图（零依赖）
        ├─ 是"展示图片/作品"？ ──────────────────► R4：相册式页面
        └─ 是"改外观"？ ─────────────────────────► R5：加一套主题皮肤
```

## R1 每天一件事的打卡（首选：别造新页）

多数"XX 打卡"需求，门户**已经有**通用打卡页 `tracker.html`（读书/家务/运动就是它）。
只要在**用户的数据**里加一个标签页即可，不写一行业务代码：

```json
// growth-home/data/activities.json  → tabs 里追加一项
{ "id": "piano", "name": "钢琴", "emoji": "🎹", "color": "#845EF7",
  "type": "single", "goal": "每天练琴15分钟", "question": "今天练了什么曲子？" }
```

- `type: "single"`：一个大按钮 + 一句话记录；`type: "list"`：清单逐项勾选（需配 `items`）
- 改完跑一次 `voice-dubbing` 补"钢琴"的配音；菜单位置由 `index.html` 的 `TAB_ORDER` 决定
- **这是改用户数据**（`data/activities.json`），改前要跟用户确认

## R2 知识点/作业式打卡（带日历、可回看）

用在"要跟课本单元走、还想翻历史"的场景。核心是**别自己写日历**，接共享模块：

```html
<script src="vendor/themes.js"></script>
<script src="vendor/homework-section.js"></script>
<div id="hw"></div>
<script>
const SUBJECT = 'piano';
let date = new Date(), dayState = {};

async function pull() {
  // 优先用现成接口：作业卡/打卡记录都在门户服务器上
  const r = await fetch('/api/homework/checkins', { cache: 'no-store' });
  dayState = (await r.json()).records || {};
  render();
}
function render() {
  HwSection.mount({
    mount: document.getElementById('hw'),
    subject: SUBJECT,                     // 与 activities.json 里的 id 对应
    date: ymd(date),
    dayChecks: () => dayState,            // 页面自己的打卡项通过回调交给模块
    onPickDate: (d) => { date = d; render(); },
    setDay: (d) => { date = d; render(); },
  });
}
function ymd(d) { const p = n => String(n).padStart(2, '0');
  return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()); }
pull();
document.addEventListener('visibilitychange', () => { if (!document.hidden) pull(); });
setInterval(pull, 12000);
</script>
```

- 打卡细到"知识点/具体一项"（key 形如 `<单元id>:<板块id>`），**不要**做成"听/说/读/写"这种笼统大按钮
- 有语音就配 `Voice.attach({ autoFill })`，音频 + 文字一起显示
- 挂载细节以 `growth-home/SKILL.md` 的「作业卡片」一节为准（那是这套模块的权威说明）

## R3 看趋势 / 统计页

零依赖，自绘就够（**不许引 CDN 图表库**）：

```html
<div class="bars" id="bars"></div>
<script>
async function render() {
  const r = await fetch('/api/tracker?tab=reading', { cache: 'no-store' });
  const d = await r.json();
  const days = last14Days();                       // ['2026-09-15', ...]
  const hits = days.map(day => (d.records?.[day]?.v === 1) ? 1 : 0);
  const max = Math.max(1, ...hits);
  document.getElementById('bars').innerHTML = days.map((day, i) => `
    <div class="bar" title="${day}">
      <span style="height:${Math.round(hits[i] / max * 100)}%"></span>
    </div>`).join('');
}
function last14Days() { const out = [], d = new Date();
  for (let i = 13; i >= 0; i--) { const x = new Date(d); x.setDate(d.getDate() - i);
    const p = n => String(n).padStart(2, '0');
    out.push(x.getFullYear() + '-' + p(x.getMonth() + 1) + '-' + p(x.getDate())); }
  return out; }
render();
</script>
```

要点：数据一律来自 `/api/...`；颜色从 `themes.js` 的 CSS 变量取（换皮肤跟着变）；手机上柱子别太窄。

## R4 展示图片 / 作品（相册式）

- 上传：走 `POST /api/art/upload`（画作）或本技能自己的上传路由，**图片落 `data/` 下的子目录**
- 页面：网格 + 点击放大；每张图有日期和一句话描述（描述走 `voice.js` 时可录音 + 文字）
- 参考现成页：`xiaoshan-art-archive/web/art.html`（画作档案）——它就是这个模式的成熟版本，
  新需求优先扩展它，而不是再写一个相册
- 图片路径只在服务端拼，页面拿相对 URL，不许在页面里出现本机绝对路径

## R5 换外观（加一套主题皮肤）

主题引擎是 `web/vendor/themes.js`（每套皮肤 = CSS 变量 + 背景纹理 + 手绘吉祥物 + 漂浮装饰）。
加皮肤就在它里面的皮肤表里加一项，**不要**在每个页面里各写一份配色。

改完必须：

```bash
python tools/sync_vendor.py --check   # 五个技能的 vendor/ 必须一致
python tools/sync_vendor.py           # 有差异就对齐
```

## 收尾通用动作

```bash
python tools/voice-dubbing ...         # 页面里新增的可朗读文字 → 补配音
python tools/smoke_test.py             # 起服务逐页点一遍
python tools/privacy_guard.py --all    # 确认没有隐私外泄
python tools/portal_wire.py undo       # 不满意就回退接线
```

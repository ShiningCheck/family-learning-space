/* 朗读配音自检：按各页面真实取数路径收集运行时会朗读的文本，核对是否都有配音音频。
 *
 * 用法：node .trae/skills/voice-dubbing/tools/verify_tts.js
 * 输出：每条数据的漏配数量 + 播放优先级是否按预期工作；有漏配时退出码为 1。
 *
 * 原理：页面侧 portal-core/vendor/tts.js 按「文本」查 <data-root>/web/data/tts/index.json，
 * 这里把同一批文本取出来逐条比对，确保生成脚本覆盖了所有页面入口。
 * 内容文件已按架构 v2 归位到各技能自己的 data/（仓库之外的 data-root），
 * 路径解析与 tools/data_paths.py 一致：优先读 skill.json 的 url，缺省退回固定约定表。
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const SKILLS = path.resolve(__dirname, '..', '..');
const REPO = path.resolve(SKILLS, '..', '..');
const ROOT = JSON.parse(fs.readFileSync(path.join(REPO, 'local.json'), 'utf8')).data_root;

const NS_FALLBACK = {
  'growth-home': 'web', 'learning-growth-board': 'learn', 'school-bag-organizer': 'bag',
  'xiaoshan-art-archive': 'art', 'home-library': 'lib', 'competition': 'comp'
};
function namespace(skill) {
  try {
    const m = JSON.parse(fs.readFileSync(path.join(SKILLS, skill, 'skill.json'), 'utf8'));
    if (m.url) return m.url;
  } catch (e) {}
  return NS_FALLBACK[skill] || ('skills/' + skill);
}
function dataDir(skill) { return path.join(ROOT, namespace(skill), 'data'); }
function readJson(p) { return JSON.parse(fs.readFileSync(p, 'utf8')); }

const GH_DATA = dataDir('growth-home');
const CORE_DATA = path.join(ROOT, 'core', 'data');
const INDEX = path.join(GH_DATA, 'tts', 'index.json');

if (!fs.existsSync(INDEX)) {
  console.error('找不到配音清单：' + INDEX + '\n请先运行 gen_tts.py 生成。');
  process.exit(1);
}

/* ---------- 浏览器环境桩（用于加载真实模块） ---------- */
const played = [], fallbackSpoken = [];
const docStub = {
  getElementById: () => null,
  createElement: () => ({ style: {}, appendChild() {}, set textContent(v) { this._t = v; } }),
  addEventListener: () => {},
  body: { appendChild() {} }
};
class AudioStub {
  constructor() { this.preload = ''; this.currentTime = 0; this._src = ''; this._ls = {}; }
  set src(v) { this._src = v; }
  get src() { return this._src; }
  addEventListener(t, f) { (this._ls[t] = this._ls[t] || []).push(f); }
  removeEventListener(t, f) { const a = this._ls[t] || []; const i = a.indexOf(f); if (i >= 0) a.splice(i, 1); }
  play() {
    played.push(this._src);
    const self = this;
    return new Promise(res => setTimeout(() => { (self._ls['ended'] || []).forEach(f => f()); res(); }, 3));
  }
  pause() {}
}
function makeUtterance(text) { return { text, volume: 1, rate: 1, pitch: 1 }; }
const speechStub = {
  mode: 'ok', paused: false,
  getVoices: () => [], cancel() {}, resume() {},
  speak(u) {
    if (this.mode === 'silent') return;              // 模拟手机没有语音引擎
    fallbackSpoken.push(u.text);
    if (u.onstart) u.onstart();
    setTimeout(() => u.onend && u.onend(), 2);
  }
};

global.window = { speechSynthesis: speechStub, SpeechSynthesisUtterance: makeUtterance };
global.document = docStub;
global.Audio = AudioStub;
global.SpeechSynthesisUtterance = makeUtterance;
global.fetch = async (url) => (url === '/data/tts/index.json'
  ? { ok: true, json: async () => readJson(INDEX) }
  : { ok: false, status: 404, json: async () => ({}) });

// tts.js 已收拢到 portal-core/vendor/ 单源（架构 v2 第 2 步，技能里不再有 vendor 副本）
const CORE_VENDOR = path.resolve(REPO, 'portal-core', 'vendor');
vm.runInThisContext(fs.readFileSync(path.join(CORE_VENDOR, 'tts.js'), 'utf8'));

/* ---------- 收集运行时会朗读的文本 ---------- */
const ghData = rel => readJson(path.join(GH_DATA, rel));
const skillData = (skill, rel) => readJson(path.join(dataDir(skill), rel));
const fill = (s, name) => String(s == null ? '' : s).replace(/\{name\}/g, name);
const childName = ghData('config.json').childName;

const enTexts = [], zhTexts = [];
const push = (arr, src, text) => { if (text && String(text).trim()) arr.push([src, String(text)]); };

// 英语：打卡 / 辅导班（内容归 english-class 技能）
skillData('english-class', 'english_class.json').units.forEach(u => {
  (u.sections || []).forEach(s => {
    (s.items || []).forEach(it => push(enTexts, 'class:item', fill(it.en, childName)));
    (s.sentences || []).forEach(x => push(enTexts, 'class:sentence', fill(x.en, childName)));
  });
  ((u.dialogue || {}).lines || []).forEach(l => push(enTexts, 'class:dialogue', l.text));
  ((u.song || {}).lines || []).forEach(l => push(enTexts, 'class:song', l));
  ((u.dictation || {}).words || []).forEach(w => push(enTexts, 'class:dictation', w.en));
});

// 中文固定提示语
['英语打卡成功，你真棒！', '听说读写全打卡，你真棒！', '今天英语听练全打卡，你真棒！',
 '录音保存好啦！', '请允许使用麦克风', '记住啦！', '打卡成功！', '读完一章，真棒！',
 '已取消，没关系！', '加入作业啦！', '作业保存好啦！', '今天的好习惯全部完成，太棒啦！',
  '自由阅读', '书单', '读完啦！', '这本书读完啦，你是小书虫！'
].forEach(t => push(zhTexts, 'fixed', t));

// 打卡页 / 作业页 / 看板（标签配置归 core 命名空间）
readJson(path.join(CORE_DATA, 'activities.json')).tabs.forEach(t => {
  push(zhTexts, 'tracker', t.name + '打卡成功，你真棒！');
  push(zhTexts, 'tracker', t.name + '全部完成，你是小能手！');
});
['subject-chinese', 'subject-math', 'english-class'].forEach(subj =>
  skillData(subj, 'homework.json').items.forEach(it => push(zhTexts, 'homework', it.name + ' 打卡成功，你真棒！')));
// 书单：每一章的名字（勾一章念一章的名字，归 reading 技能）
skillData('reading', 'booklist.json').books.forEach(b => (b.chapters || []).forEach(c => push(zhTexts, 'booklist', c)));
const daysDir = path.join(dataDir('learning-growth-board'), 'days');
if (fs.existsSync(daysDir)) {
  fs.readdirSync(daysDir).filter(f => f.endsWith('.json')).forEach(f => {
    const d = readJson(path.join(daysDir, f));
    (d.learned || []).forEach(l => push(zhTexts, 'dashboard', l.content));
  });
}
// 书包清单
const req = skillData('school-bag-organizer', 'course_requirements.json');
Object.keys(req).forEach(c => { push(zhTexts, 'bag:course', c); (req[c] || []).forEach(i => push(zhTexts, 'bag:item', i)); });
const bagName = skillData('school-bag-organizer', 'config.json').childName;
['今天', '明天'].forEach(d => push(zhTexts, 'bag:done', '太棒了' + bagName + '，书包整理完毕，' + d + '上学开心哦'));
// 图书馆 / 画作
skillData('home-library', 'books.json').books.forEach(b => {
  push(zhTexts, 'library', (b.title || '') + '。' + (b.intro || '这本书还没有简介。'));
  push(zhTexts, 'library', (b.title || '') + '。' + (b.intro || ''));
});
skillData('xiaoshan-art-archive', 'index.json').forEach(p =>
  push(zhTexts, 'art', (p.title || '') + '。' + (p.description || '')));

/* ---------- 检查 ---------- */
const PAGES = [
  ['growth-home', 'web/english-class.html'],
  ['growth-home', 'web/school-english.html'], ['growth-home', 'web/tracker.html'],
  ['growth-home', 'web/reading.html'],
  ['growth-home', 'web/homework.html'], ['growth-home', 'web/subject.html'],
  ['learning-growth-board', 'web/dashboard.html'], ['school-bag-organizer', 'web/checklist.html'],
  ['home-library', 'web/library.html'], ['xiaoshan-art-archive', 'web/art.html']
];

(async () => {
  await window.TTS.ready();
  const info = window.TTS.info();
  console.log('配音清单：' + JSON.stringify(info.stats) + '，生成于 ' + info.generated);

  const missEn = enTexts.filter(x => !window.TTS.has(x[1], 'en'));
  const missZh = zhTexts.filter(x => !window.TTS.has(x[1], 'zh'));
  console.log('英文 ' + enTexts.length + ' 条 → 漏配 ' + missEn.length);
  console.log('中文 ' + zhTexts.length + ' 条 → 漏配 ' + missZh.length);
  [...missEn, ...missZh].slice(0, 20).forEach(m => console.log('   MISS [' + m[0] + '] ' + JSON.stringify(m[1])));

  const notWired = [];
  PAGES.forEach(([sk, page]) => {
    const html = fs.readFileSync(path.join(SKILLS, sk, page), 'utf8');
    if (!/\/vendor\/tts\.js/.test(html)) notWired.push(page + '（未引用模块）');
  });
  // vendor 已单源化：只查 portal-core 这一份
  if (!fs.existsSync(path.join(CORE_VENDOR, 'tts.js'))) notWired.push('portal-core（缺 vendor/tts.js）');
  console.log('页面接入：' + PAGES.length + ' 个页面，问题 ' + notWired.length + ' 处 ' + JSON.stringify(notWired));

  // 统一"音频优先"：任何页面都不该再出现"朗读优先"分支
  const preferTTS = PAGES.filter(([sk, page]) =>
    /prefer:\s*'tts'/.test(fs.readFileSync(path.join(SKILLS, sk, page), 'utf8')));
  console.log('朗读优先分支残留：' + preferTTS.length + ' 处 ' + JSON.stringify(preferTTS.map(p => p[0] + '/' + p[1])));

  played.length = 0; fallbackSpoken.length = 0;
  await window.TTS.speak('打卡成功！', 'zh');
  console.log('有音频时：播放 ' + JSON.stringify(played) + '，朗读兜底 ' + JSON.stringify(fallbackSpoken));

  played.length = 0; fallbackSpoken.length = 0;
  await window.TTS.speak('这条内容肯定没有配音', 'zh');
  console.log('无音频时：朗读兜底 ' + JSON.stringify(fallbackSpoken) + '，播放 ' + JSON.stringify(played));

  const bad = missEn.length + missZh.length + notWired.length + preferTTS.length;
  console.log(bad ? '\n需要补配音或修接入：' + bad + ' 处' : '\n全部通过：没有漏配');
  process.exit(bad ? 1 : 0);
})();
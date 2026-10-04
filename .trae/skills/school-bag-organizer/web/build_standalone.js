const fs = require('fs');
const path = require('path');

// 以脚本自身位置解析路径：web/ -> 技能根目录 -> ... -> 仓库根目录
const skillDir = path.resolve(__dirname, '..');
const repoRoot = path.resolve(__dirname, '..', '..', '..', '..');
const meta = JSON.parse(fs.readFileSync(path.join(skillDir, 'skill.json'), 'utf8'));

// 1) standalone 模式：由 skill.json 的 standalone.mode 决定能不能出单文件版
const mode = (meta.standalone && meta.standalone.mode) || 'none';
if (mode === 'none') {
  console.error(`[停止] ${path.basename(skillDir)} 的 skill.json 声明 standalone.mode = "none"，不生成单文件版。`);
  process.exit(1);
}

// 2) 解析 data-root（数据必须落在仓库之外；见 tools/data_paths.py）
function dataRoot() {
  const env = (process.env.GH_DATA_ROOT || '').trim();
  if (env) return env;
  const localPath = path.join(repoRoot, 'local.json');
  if (fs.existsSync(localPath)) {
    const raw = (JSON.parse(fs.readFileSync(localPath, 'utf8')).data_root || '').trim();
    if (raw) return raw;
  }
  return null;
}

const root = dataRoot();
if (!root) {
  console.error('[停止] 未配置 data-root：请先在仓库根运行 python setup.py（或设环境变量 GH_DATA_ROOT）。');
  process.exit(1);
}

// 3) 数据来源：优先 data-root 里的真实数据，其次仓库内遗留的 data/，最后退回匿名模板
const ns = (meta.url || '').trim().replace(/^\/+|\/+$/g, '') || path.basename(skillDir);
const candidates = [
  path.join(root, ns, 'data'),
  path.join(skillDir, 'data'),
  path.join(skillDir, 'data-templates'),
];
const srcDir = candidates.find((p) => fs.existsSync(p));
if (!srcDir) {
  console.error(`[停止] 找不到数据来源：${candidates.join(' / ')}`);
  process.exit(1);
}
const usingTemplate = srcDir === path.join(skillDir, 'data-templates');

const readJson = (name) => {
  const p = path.join(srcDir, name);
  return fs.existsSync(p) ? JSON.parse(fs.readFileSync(p, 'utf8')) : null;
};

const html = fs.readFileSync(path.join(skillDir, 'web', 'checklist.html'), 'utf8');
// 共享组件已收拢到 portal-core/vendor/ 单源（架构 v2 第 2 步，sync_vendor.py 已退役）
const coreVendor = path.join(repoRoot, 'portal-core', 'vendor');
const pinyinJs = fs.readFileSync(path.join(coreVendor, 'pinyin-pro.js'), 'utf8');
const themesJs = fs.readFileSync(path.join(coreVendor, 'themes.js'), 'utf8');

const data = {
  config: readJson('config.json'),
  schedule: readJson('schedule.json'),
  requirements: readJson('course_requirements.json'),
  notifications: readJson('notifications.json'),
  holidays: readJson('holidays.json')
};

let out = html;

// 1. Inline pinyin-pro.js and themes.js
out = out.replace(
  '<script src="/vendor/pinyin-pro.js"></script>',
  '<script>\n' + pinyinJs + '\n</script>'
);
out = out.replace(
  '<script src="/vendor/themes.js"></script>',
  '<script>\n' + themesJs + '\n</script>'
);

// 2. tts.js 依赖门户服务器提供的 /data/tts 配音清单，单文件版用不上，去掉引用（页面会自动退回浏览器朗读）
out = out.replace(/\s*<script src="\/vendor\/tts\.js"><\/script>/, '');

// 3. Embed data
out = out.replace(
  'const EMBEDDED_DATA = null;',
  'const EMBEDDED_DATA = ' + JSON.stringify(data) + ';'
);

// 4. 产物落 data-root（仓库之外），绝不把含真实信息的单文件写回仓库
const outDir = path.join(root, ns, 'share');
fs.mkdirSync(outDir, { recursive: true });
const outPath = path.join(outDir, 'school_checklist_standalone.html');
fs.writeFileSync(outPath, out, 'utf8');
console.log('OK', (fs.statSync(outPath).size / 1024).toFixed(1) + ' KB');
console.log('数据来源：' + (usingTemplate ? '匿名模板（data-templates/）' : srcDir));
console.log('产物：' + outPath);
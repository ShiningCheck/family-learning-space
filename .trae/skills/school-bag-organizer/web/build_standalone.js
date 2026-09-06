const fs = require('fs');
const path = require('path');

// 以脚本自身位置解析路径：web/ -> 技能根目录 -> ... -> 仓库根目录
const skillDir = path.resolve(__dirname, '..');
const repoRoot = path.resolve(__dirname, '..', '..', '..', '..');
const html = fs.readFileSync(path.join(skillDir, 'web', 'checklist.html'), 'utf8');
const pinyinJs = fs.readFileSync(path.join(skillDir, 'web', 'vendor', 'pinyin-pro.js'), 'utf8');
const themesJs = fs.readFileSync(path.join(skillDir, 'web', 'vendor', 'themes.js'), 'utf8');

const data = {
  config: JSON.parse(fs.readFileSync(path.join(skillDir, 'data', 'config.json'), 'utf8')),
  schedule: JSON.parse(fs.readFileSync(path.join(skillDir, 'data', 'schedule.json'), 'utf8')),
  requirements: JSON.parse(fs.readFileSync(path.join(skillDir, 'data', 'course_requirements.json'), 'utf8')),
  notifications: JSON.parse(fs.readFileSync(path.join(skillDir, 'data', 'notifications.json'), 'utf8')),
  holidays: JSON.parse(fs.readFileSync(path.join(skillDir, 'data', 'holidays.json'), 'utf8'))
};

let out = html;

// 1. Inline pinyin-pro.js and themes.js
out = out.replace(
  '<script src="vendor/pinyin-pro.js"></script>',
  '<script>\n' + pinyinJs + '\n</script>'
);
out = out.replace(
  '<script src="vendor/themes.js"></script>',
  '<script>\n' + themesJs + '\n</script>'
);

// 2. Embed data
out = out.replace(
  'const EMBEDDED_DATA = null;',
  'const EMBEDDED_DATA = ' + JSON.stringify(data) + ';'
);

const outPath = path.join(repoRoot, 'school_checklist_standalone.html');
fs.writeFileSync(outPath, out, 'utf8');
console.log('OK', (fs.statSync(outPath).size / 1024).toFixed(1) + ' KB');

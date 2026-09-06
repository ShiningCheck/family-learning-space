/* 成长家园 - 主题引擎 v2
 * 在 <head> 中尽早引入：自动应用已保存的主题（CSS 变量 + 氛围背景 + 吉祥物场景），
 * 并通过 localStorage 的 storage 事件在同源页面/iframe 间实时同步。
 * 每套皮肤 = 配色变量 + 专属背景纹理 + 手绘 SVG 吉祥物 + 漂浮装饰。
 */
(function () {
  var KEY = 'gh_theme';

  /* ---------- 手绘吉祥物（内联 SVG，无外部依赖） ---------- */

  var MASCOT_ORIGINAL = [
    '<svg viewBox="0 0 200 200" xmlns="http://www.w3.org/2000/svg">',
    '<path d="M22 96 L100 24 L178 96 Z" fill="#FF922B" stroke="#4A3B2A" stroke-width="6" stroke-linejoin="round"/>',
    '<rect x="42" y="96" width="116" height="76" rx="10" fill="#FFF3E0" stroke="#4A3B2A" stroke-width="6"/>',
    '<circle cx="70" cy="122" r="9" fill="#4A3B2A"/><circle cx="130" cy="122" r="9" fill="#4A3B2A"/>',
    '<circle cx="73" cy="119" r="3" fill="#fff"/><circle cx="133" cy="119" r="3" fill="#fff"/>',
    '<path d="M84 142 q16 14 32 0" stroke="#4A3B2A" stroke-width="6" fill="none" stroke-linecap="round"/>',
    '<circle cx="56" cy="136" r="7" fill="#FFB8A0" opacity="0.85"/><circle cx="144" cy="136" r="7" fill="#FFB8A0" opacity="0.85"/>',
    '</svg>'
  ].join('');

  var MASCOT_CAPYBARA = [
    '<svg viewBox="0 0 200 200" xmlns="http://www.w3.org/2000/svg">',
    '<g fill="none" stroke="#FFFFFF" stroke-width="6" stroke-linecap="round" opacity="0.75">',
    '<path d="M34 62 q8 -14 0 -28"/><path d="M54 54 q8 -14 0 -28"/><path d="M166 62 q-8 -14 0 -28"/>',
    '</g>',
    '<ellipse cx="100" cy="136" rx="72" ry="52" fill="#A9744F"/>',
    '<circle cx="55" cy="60" r="13" fill="#8F5B2E"/><circle cx="145" cy="60" r="13" fill="#8F5B2E"/>',
    '<ellipse cx="100" cy="98" rx="58" ry="48" fill="#B98157"/>',
    '<ellipse cx="100" cy="116" rx="30" ry="22" fill="#D9A066"/>',
    '<ellipse cx="92" cy="112" rx="4" ry="6" fill="#5B4636"/><ellipse cx="108" cy="112" rx="4" ry="6" fill="#5B4636"/>',
    '<path d="M62 90 q8 8 16 0" stroke="#5B4636" stroke-width="5" fill="none" stroke-linecap="round"/>',
    '<path d="M122 90 q8 8 16 0" stroke="#5B4636" stroke-width="5" fill="none" stroke-linecap="round"/>',
    '<circle cx="58" cy="104" r="8" fill="#E8A0A0" opacity="0.75"/><circle cx="142" cy="104" r="8" fill="#E8A0A0" opacity="0.75"/>',
    '<circle cx="100" cy="46" r="16" fill="#FF922B"/>',
    '<path d="M100 31 q4 -9 11 -11" stroke="#2F7D46" stroke-width="5" fill="none" stroke-linecap="round"/>',
    '</svg>'
  ].join('');

  var MASCOT_KUROMI = [
    '<svg viewBox="0 0 200 200" xmlns="http://www.w3.org/2000/svg">',
    '<path d="M45 58 L18 30 L58 42 Z" fill="#2B2330"/><path d="M155 58 L182 30 L142 42 Z" fill="#2B2330"/>',
    '<path d="M100 18 C 42 18 26 80 31 122 C 36 166 70 186 100 186 C 130 186 164 166 169 122 C 174 80 158 18 100 18 Z" fill="#2B2330" stroke="#171019" stroke-width="4"/>',
    '<ellipse cx="100" cy="122" rx="52" ry="46" fill="#F3E8FF"/>',
    '<g transform="translate(100 62)">',
    '<circle r="16" fill="#FFFFFF"/><rect x="-8" y="9" width="16" height="8" rx="3" fill="#FFFFFF"/>',
    '<circle cx="-6" cy="-2" r="4" fill="#2B2330"/><circle cx="6" cy="-2" r="4" fill="#2B2330"/>',
    '<path d="M-3 7 L0 2 L3 7 Z" fill="#2B2330"/>',
    '</g>',
    '<circle cx="78" cy="116" r="7" fill="#2B2330"/><circle cx="122" cy="116" r="7" fill="#2B2330"/>',
    '<path d="M85 140 q15 12 30 0" stroke="#2B2330" stroke-width="5" fill="none" stroke-linecap="round"/>',
    '<circle cx="64" cy="131" r="7" fill="#E64980" opacity="0.6"/><circle cx="136" cy="131" r="7" fill="#E64980" opacity="0.6"/>',
    '<g transform="translate(152 44)">',
    '<path d="M0 0 L24 -13 L24 13 Z" fill="#E64980"/><path d="M0 0 L-24 -13 L-24 13 Z" fill="#E64980"/>',
    '<circle r="7" fill="#C2255C"/>',
    '</g>',
    '</svg>'
  ].join('');

  var MASCOT_NEZHA = [
    '<svg viewBox="0 0 200 200" xmlns="http://www.w3.org/2000/svg">',
    '<ellipse cx="100" cy="152" rx="76" ry="28" fill="none" stroke="#E03131" stroke-width="10" opacity="0.8"/>',
    '<circle cx="52" cy="44" r="18" fill="#5C1F0E"/><circle cx="148" cy="44" r="18" fill="#5C1F0E"/>',
    '<circle cx="52" cy="44" r="8" fill="#E03131"/><circle cx="148" cy="44" r="8" fill="#E03131"/>',
    '<circle cx="100" cy="96" r="56" fill="#FFD9B3"/>',
    '<path d="M44 88 Q 58 38 100 38 Q 142 38 156 88 Q 130 64 100 66 Q 70 64 44 88 Z" fill="#5C1F0E"/>',
    '<path d="M100 60 l7 11 -7 11 -7 -11 Z" fill="#E03131"/>',
    '<circle cx="79" cy="100" r="7" fill="#3B2416"/><circle cx="121" cy="100" r="7" fill="#3B2416"/>',
    '<circle cx="81.5" cy="97.5" r="2.5" fill="#fff"/><circle cx="123.5" cy="97.5" r="2.5" fill="#fff"/>',
    '<circle cx="64" cy="114" r="8" fill="#FF9B9B" opacity="0.75"/><circle cx="136" cy="114" r="8" fill="#FF9B9B" opacity="0.75"/>',
    '<path d="M86 122 q14 12 28 0" stroke="#3B2416" stroke-width="5" fill="none" stroke-linecap="round"/>',
    '<circle cx="58" cy="182" r="13" fill="none" stroke="#FFB020" stroke-width="6"/>',
    '<circle cx="142" cy="182" r="13" fill="none" stroke="#FFB020" stroke-width="6"/>',
    '</svg>'
  ].join('');

  var MASCOT_ULTRAMAN = [
    '<svg viewBox="0 0 200 200" xmlns="http://www.w3.org/2000/svg">',
    '<path d="M100 14 C 56 14 40 60 42 106 C 44 152 70 182 100 182 C 130 182 156 152 158 106 C 160 60 144 14 100 14 Z" fill="#DDE4EE" stroke="#24344D" stroke-width="4"/>',
    '<path d="M100 16 L100 58" stroke="#E03131" stroke-width="9" stroke-linecap="round"/>',
    '<path d="M62 72 Q 80 92 78 132" stroke="#E03131" stroke-width="7" fill="none" stroke-linecap="round"/>',
    '<path d="M138 72 Q 120 92 122 132" stroke="#E03131" stroke-width="7" fill="none" stroke-linecap="round"/>',
    '<ellipse cx="72" cy="102" rx="17" ry="26" fill="#FFF3BF" stroke="#24344D" stroke-width="3" transform="rotate(-12 72 102)"/>',
    '<ellipse cx="128" cy="102" rx="17" ry="26" fill="#FFF3BF" stroke="#24344D" stroke-width="3" transform="rotate(12 128 102)"/>',
    '<circle cx="100" cy="156" r="12" fill="#3B5BDB" stroke="#24344D" stroke-width="3"/>',
    '<circle cx="96" cy="152" r="3.5" fill="#9DB8FF"/>',
    '</svg>'
  ].join('');

  var MASCOT_LABUBU = [
    '<svg viewBox="0 0 200 200" xmlns="http://www.w3.org/2000/svg">',
    '<path d="M56 72 L34 10 L88 48 Z" fill="#74B869"/><path d="M144 72 L166 10 L112 48 Z" fill="#74B869"/>',
    '<path d="M58 62 L45 25 L79 49 Z" fill="#EFF4E8"/><path d="M142 62 L155 25 L121 49 Z" fill="#EFF4E8"/>',
    '<ellipse cx="100" cy="118" rx="63" ry="58" fill="#74B869"/>',
    '<circle cx="78" cy="102" r="9" fill="#2F4A33"/><circle cx="122" cy="102" r="9" fill="#2F4A33"/>',
    '<circle cx="81" cy="99" r="3" fill="#fff"/><circle cx="125" cy="99" r="3" fill="#fff"/>',
    '<path d="M62 132 L74 144 L86 132 L98 144 L110 132 L122 144 L138 132" stroke="#2F4A33" stroke-width="6" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
    '<circle cx="56" cy="118" r="7" fill="#3E8E5A" opacity="0.55"/><circle cx="144" cy="118" r="7" fill="#3E8E5A" opacity="0.55"/>',
    '</svg>'
  ].join('');

  var MASCOT_CHIIKAWA = [
    '<svg viewBox="0 0 200 200" xmlns="http://www.w3.org/2000/svg">',
    '<ellipse cx="70" cy="46" rx="14" ry="27" fill="#FFFDF8" stroke="#6B5348" stroke-width="3" transform="rotate(-15 70 46)"/>',
    '<ellipse cx="130" cy="46" rx="14" ry="27" fill="#FFFDF8" stroke="#6B5348" stroke-width="3" transform="rotate(15 130 46)"/>',
    '<ellipse cx="100" cy="122" rx="66" ry="60" fill="#FFFDF8" stroke="#6B5348" stroke-width="3"/>',
    '<circle cx="80" cy="112" r="6" fill="#6B5348"/><circle cx="120" cy="112" r="6" fill="#6B5348"/>',
    '<ellipse cx="61" cy="130" rx="10" ry="7" fill="#FFA8C5" opacity="0.9"/>',
    '<ellipse cx="139" cy="130" rx="10" ry="7" fill="#FFA8C5" opacity="0.9"/>',
    '<path d="M94 130 q6 7 12 0" stroke="#6B5348" stroke-width="4" fill="none" stroke-linecap="round"/>',
    '<circle cx="46" cy="154" r="10" fill="#FFFDF8" stroke="#6B5348" stroke-width="3"/>',
    '<circle cx="154" cy="154" r="10" fill="#FFFDF8" stroke="#6B5348" stroke-width="3"/>',
    '</svg>'
  ].join('');

  /* ---------- 主题定义 ---------- */

  var THEMES = {
    original: {
      name: '成长家园', emoji: '🏠',
      vars: {
        '--paper': '#FFF6E9', '--dot': '#FFE0B8', '--sky': '#D0EBFF',
        '--ink': '#4A3B2A', '--soft': '#8D7357', '--edge': '#4A3B2A',
        '--card': '#FFFFFF', '--line': '#FFE3B3',
        '--acc': '#FF922B', '--acc-deep': '#E8590C',
        '--hero-a': '#FFB84D', '--hero-b': '#FF922B',
        '--bg': '#FFF8F0', '--accent': '#FF6B6B', '--accent2': '#4ECDC4',
        '--text': '#2D3436', '--text-light': '#636E72',
        '--grad-a': '#FF6B6B', '--grad-b': '#FF8E53'
      },
      deco: ['☁️', '🌈', '⭐', '🎈'],
      bg: {
        image: 'radial-gradient(circle at 18% 12%, rgba(116,192,252,0.20), transparent 42%),' +
          'radial-gradient(circle at 82% 20%, rgba(255,212,59,0.16), transparent 38%),' +
          'radial-gradient(circle at 50% 96%, rgba(255,146,43,0.10), transparent 45%),' +
          'radial-gradient(var(--dot) 2.5px, transparent 2.5px)',
        size: 'auto,auto,auto,28px 28px'
      },
      mascot: MASCOT_ORIGINAL
    },
    capybara: {
      name: '卡皮巴拉', emoji: '🦫',
      vars: {
        '--paper': '#F3E7D3', '--dot': '#E0C9A6', '--sky': '#F7E3C8',
        '--ink': '#5B4636', '--soft': '#97806B', '--edge': '#5B4636',
        '--card': '#FFFBF2', '--line': '#E5D3B3',
        '--acc': '#B97A45', '--acc-deep': '#8F5B2E',
        '--hero-a': '#D9A066', '--hero-b': '#B97A45',
        '--bg': '#F3E7D3', '--accent': '#B97A45', '--accent2': '#7FA98F',
        '--text': '#4A3826', '--text-light': '#97806B',
        '--grad-a': '#D9A066', '--grad-b': '#B97A45'
      },
      deco: ['♨️', '🍊', '🦫', '💤'],
      bg: {
        image: 'radial-gradient(circle at 15% 18%, rgba(255,146,43,0.18), transparent 45%),' +
          'radial-gradient(circle at 85% 78%, rgba(127,169,143,0.22), transparent 48%),' +
          'radial-gradient(circle at 70% 10%, rgba(217,160,102,0.20), transparent 36%),' +
          'radial-gradient(var(--dot) 2.5px, transparent 2.5px)',
        size: 'auto,auto,auto,26px 26px'
      },
      mascot: MASCOT_CAPYBARA
    },
    kuromi: {
      name: '库洛米', emoji: '💀',
      vars: {
        '--paper': '#2B2330', '--dot': '#3D3145', '--sky': '#4A3B5E',
        '--ink': '#F3E8FF', '--soft': '#B8A6C9', '--edge': '#171019',
        '--card': '#3A2F45', '--line': '#57496B',
        '--acc': '#E64980', '--acc-deep': '#C2255C',
        '--hero-a': '#9C6BFF', '--hero-b': '#E64980',
        '--bg': '#2B2330', '--accent': '#E64980', '--accent2': '#9C6BFF',
        '--text': '#F3E8FF', '--text-light': '#B8A6C9',
        '--grad-a': '#9C6BFF', '--grad-b': '#E64980'
      },
      deco: ['💜', '🖤', '💀', '🎀'],
      bg: {
        image: 'radial-gradient(circle 2px at 12% 18%, rgba(255,255,255,0.9), transparent 3px),' +
          'radial-gradient(circle 2px at 78% 12%, rgba(255,255,255,0.75), transparent 3px),' +
          'radial-gradient(circle 1.5px at 55% 42%, rgba(255,255,255,0.6), transparent 2.5px),' +
          'radial-gradient(circle 2px at 30% 75%, rgba(255,255,255,0.5), transparent 3px),' +
          'radial-gradient(circle at 85% 88%, rgba(156,107,255,0.28), transparent 46%),' +
          'radial-gradient(circle at 12% 92%, rgba(230,73,128,0.22), transparent 42%)',
        size: '260px 260px,340px 340px,220px 220px,300px 300px,auto,auto'
      },
      mascot: MASCOT_KUROMI
    },
    nezha: {
      name: '哪吒', emoji: '🔥',
      vars: {
        '--paper': '#FFF0E1', '--dot': '#FFD8B0', '--sky': '#FFD8A8',
        '--ink': '#5C1F0E', '--soft': '#A06A4A', '--edge': '#5C1F0E',
        '--card': '#FFFBF5', '--line': '#FFD8B0',
        '--acc': '#E03131', '--acc-deep': '#C92A2A',
        '--hero-a': '#FF6B35', '--hero-b': '#E03131',
        '--bg': '#FFF0E1', '--accent': '#E03131', '--accent2': '#FFB020',
        '--text': '#5C1F0E', '--text-light': '#A06A4A',
        '--grad-a': '#FF6B35', '--grad-b': '#E03131'
      },
      deco: ['🔥', '🌊', '⚡', '☸️'],
      bg: {
        image: 'radial-gradient(circle at 50% -12%, rgba(255,107,53,0.38), transparent 52%),' +
          'radial-gradient(circle at 12% 102%, rgba(255,176,32,0.28), transparent 42%),' +
          'radial-gradient(circle at 88% 102%, rgba(224,49,49,0.24), transparent 42%),' +
          'radial-gradient(var(--dot) 2.5px, transparent 2.5px)',
        size: 'auto,auto,auto,28px 28px'
      },
      mascot: MASCOT_NEZHA
    },
    ultraman: {
      name: '奥特曼', emoji: '🦸',
      vars: {
        '--paper': '#EDF2FA', '--dot': '#D4E0F2', '--sky': '#D6E4F7',
        '--ink': '#24344D', '--soft': '#6B7A90', '--edge': '#24344D',
        '--card': '#FFFFFF', '--line': '#D4E0F2',
        '--acc': '#E03131', '--acc-deep': '#C92A2A',
        '--hero-a': '#74C0FC', '--hero-b': '#3B5BDB',
        '--bg': '#EDF2FA', '--accent': '#E03131', '--accent2': '#1C7ED6',
        '--text': '#24344D', '--text-light': '#6B7A90',
        '--grad-a': '#E03131', '--grad-b': '#1C7ED6'
      },
      deco: ['✨', '🛸', '⚡', '🌟'],
      bg: {
        image: 'radial-gradient(circle at 50% -8%, rgba(116,192,252,0.40), transparent 55%),' +
          'radial-gradient(circle 2px at 20% 28%, rgba(255,255,255,0.95), transparent 3px),' +
          'radial-gradient(circle 2px at 70% 18%, rgba(255,255,255,0.7), transparent 3px),' +
          'radial-gradient(circle 1.5px at 88% 48%, rgba(255,255,255,0.65), transparent 2.5px),' +
          'radial-gradient(circle at 80% 96%, rgba(59,91,219,0.16), transparent 45%),' +
          'radial-gradient(var(--dot) 2px, transparent 2px)',
        size: 'auto,300px 300px,260px 260px,340px 340px,auto,26px 26px'
      },
      mascot: MASCOT_ULTRAMAN
    },
    labubu: {
      name: '拉布布', emoji: '👹',
      vars: {
        '--paper': '#EFF4E8', '--dot': '#D8E4C8', '--sky': '#DDEBD2',
        '--ink': '#2F4A33', '--soft': '#6E8A70', '--edge': '#2F4A33',
        '--card': '#FBFDF7', '--line': '#D8E4C8',
        '--acc': '#3E8E5A', '--acc-deep': '#2F7D46',
        '--hero-a': '#74B869', '--hero-b': '#3E8E5A',
        '--bg': '#EFF4E8', '--accent': '#3E8E5A', '--accent2': '#20B2AA',
        '--text': '#2F4A33', '--text-light': '#6E8A70',
        '--grad-a': '#74B869', '--grad-b': '#3E8E5A'
      },
      deco: ['🌲', '👹', '🍄', '✨'],
      bg: {
        image: 'radial-gradient(circle at 18% 105%, rgba(47,125,70,0.30), transparent 50%),' +
          'radial-gradient(circle at 82% 105%, rgba(116,184,105,0.32), transparent 50%),' +
          'radial-gradient(circle at 50% 6%, rgba(255,212,59,0.14), transparent 40%),' +
          'radial-gradient(var(--dot) 2.5px, transparent 2.5px)',
        size: 'auto,auto,auto,26px 26px'
      },
      mascot: MASCOT_LABUBU
    },
    chiikawa: {
      name: '吉伊卡哇', emoji: '🐣',
      vars: {
        '--paper': '#FFF7F3', '--dot': '#FFE0D6', '--sky': '#FFE3EC',
        '--ink': '#6B5348', '--soft': '#A78B7F', '--edge': '#6B5348',
        '--card': '#FFFFFF', '--line': '#FFE0D6',
        '--acc': '#F06595', '--acc-deep': '#D6336C',
        '--hero-a': '#FFA8C5', '--hero-b': '#F06595',
        '--bg': '#FFF7F3', '--accent': '#F06595', '--accent2': '#74C0FC',
        '--text': '#6B5348', '--text-light': '#A78B7F',
        '--grad-a': '#FFA8C5', '--grad-b': '#F06595'
      },
      deco: ['🌸', '⭐', '🍮', '💕'],
      bg: {
        image: 'radial-gradient(circle at 20% 22%, rgba(255,168,197,0.28), transparent 42%),' +
          'radial-gradient(circle at 82% 18%, rgba(116,192,252,0.22), transparent 40%),' +
          'radial-gradient(circle at 50% 88%, rgba(255,224,214,0.55), transparent 52%),' +
          'radial-gradient(var(--dot) 2px, transparent 2px)',
        size: 'auto,auto,auto,24px 24px'
      },
      mascot: MASCOT_CHIIKAWA
    }
  };

  /* ---------- 场景层（吉祥物 + 漂浮装饰） ---------- */

  var SCENE_CSS = [
    '.gh-scene{position:fixed;inset:0;pointer-events:none;z-index:-1;overflow:hidden}',
    '.gh-mascot{position:absolute;right:3vw;bottom:2.5vh;width:clamp(92px,20vw,150px);',
    'animation:ghBob 3.4s ease-in-out infinite alternate;opacity:.95;',
    'filter:drop-shadow(0 10px 14px rgba(0,0,0,.16))}',
    '.gh-mascot svg{width:100%;height:auto;display:block}',
    '.gh-float{position:absolute;line-height:1;animation:ghFloat 4.6s ease-in-out infinite alternate;opacity:.85}',
    '@keyframes ghBob{from{transform:translateY(0) rotate(-2.5deg)}to{transform:translateY(-14px) rotate(2.5deg)}}',
    '@keyframes ghFloat{from{transform:translateY(0) scale(1)}to{transform:translateY(-18px) scale(1.1)}}'
  ].join('');

  var FLOAT_SPOTS = [
    { l: '5%', t: '13%', s: 27, d: '0s' },
    { l: '87%', t: '9%', s: 23, d: '0.7s' },
    { l: '9%', t: '66%', s: 21, d: '1.4s' },
    { l: '84%', t: '58%', s: 25, d: '0.3s' },
    { l: '46%', t: '5%', s: 19, d: '1.0s' },
    { l: '64%', t: '87%', s: 21, d: '1.8s' }
  ];

  function ensureSceneCss() {
    if (document.getElementById('ghSceneCss')) return;
    var st = document.createElement('style');
    st.id = 'ghSceneCss';
    st.textContent = SCENE_CSS;
    document.head.appendChild(st);
  }

  function decorate(t) {
    if (!document.body) return;
    ensureSceneCss();
    if (t.bg) {
      document.body.style.backgroundImage = t.bg.image;
      document.body.style.backgroundSize = t.bg.size;
    }
    var scene = document.getElementById('ghScene');
    if (!scene) {
      scene = document.createElement('div');
      scene.id = 'ghScene';
      scene.className = 'gh-scene';
      document.body.insertBefore(scene, document.body.firstChild);
    }
    var html = '';
    var deco = t.deco || [];
    for (var i = 0; i < FLOAT_SPOTS.length && deco.length; i++) {
      var p = FLOAT_SPOTS[i];
      html += '<span class="gh-float" style="left:' + p.l + ';top:' + p.t +
        ';font-size:' + p.s + 'px;animation-delay:' + p.d + '">' +
        deco[i % deco.length] + '</span>';
    }
    if (t.mascot) html += '<div class="gh-mascot">' + t.mascot + '</div>';
    scene.innerHTML = html;
  }

  /* ---------- 核心逻辑 ---------- */

  function apply(id) {
    var t = THEMES[id] || THEMES.original;
    var root = document.documentElement;
    for (var k in t.vars) root.style.setProperty(k, t.vars[k]);
    root.setAttribute('data-theme', id);
    if (document.body) {
      decorate(t);
    } else {
      document.addEventListener('DOMContentLoaded', function () { decorate(t); });
    }
    try {
      document.dispatchEvent(new CustomEvent('themechange', { detail: t }));
    } catch (e) {}
  }

  function current() {
    try { return localStorage.getItem(KEY) || 'original'; } catch (e) { return 'original'; }
  }

  function set(id) {
    try { localStorage.setItem(KEY, id); } catch (e) {}
    apply(id);
  }

  window.GrowthThemes = { THEMES: THEMES, KEY: KEY, apply: apply, current: current, set: set };

  apply(current());

  window.addEventListener('storage', function (e) {
    if (e && e.key === KEY) apply(e.newValue || 'original');
  });
})();

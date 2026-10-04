/* 成长家园 - 用户反馈组件 v1.0.0
 *
 * 作用：在每个页面右下角提供一个「提建议」入口，让使用这个项目的家庭能把
 *      页面改进意见直接送到作者手上，并最终自动变成一条 GitHub Issue。
 *
 * 数据链路（三条，按可用性自动降级）：
 *   1) POST /api/feedback        —— 走本地 preview_server.py，由它落盘并转发到公网中转服务（首选）
 *   2) POST DEFAULT_RELAY_URL    —— 本地服务器不可用时（例如直接双击打开单文件版），浏览器直连中转服务
 *   3) localStorage 离线队列     —— 完全断网时先存本机，下次打开面板自动重发，并支持一键复制文本
 *
 * iframe 约定：门户首页用 iframe 装载各子页面，若每个页面都渲染按钮会重叠。
 *   因此「只有顶层窗口渲染按钮」；子页面只通过 postMessage 把自己的上下文报给顶层。
 *   子页面被单独打开时（自己就是顶层），照常渲染按钮。
 *
 * 依赖：零外部依赖。可选配合 vendor/themes.js（读取 CSS 变量与当前皮肤名）。
 * 隐私：只收集页面路径、设备/浏览器、屏幕尺寸、皮肤名与一个随机匿名编号，不含姓名、学校、班级。
 */
(function () {
  'use strict';

  var WIDGET_VERSION = '1.0.0';

  /* 作者部署 feedback-relay/worker.js 后，把输出的 https://xxx.workers.dev/feedback 填到这里。
   * 留空也能工作：正常情况下地址由本地服务器从 data-templates/feedback_channels.json 下发。
   * 这里只是「单文件版脱离服务器运行」时的最后兜底。 */
  var DEFAULT_RELAY_URL = '';

  var MSG_NS = '__ghFb';
  var LS_INSTALL_ID = 'gh_install_id';
  var LS_CONFIG = 'gh_fb_cfg';
  var LS_QUEUE = 'gh_fb_queue';
  var LS_HINT = 'gh_fb_hint_seen';
  var MAX_IMAGES = 3;
  var MAX_IMAGE_EDGE = 1280;
  var MAX_MESSAGE = 2000;

  var TYPES = [
    { id: 'feature', emoji: '✨', name: '想要新功能', desc: '希望多出点什么', color: '#845EF7',
      msgHint: '写下你想要的新功能，比如「希望能看到一周的读书统计图」…',
      expectLabel: '有了它，能帮你做什么？', expectHint: '（可选）说说这个功能解决什么问题…' },
    { id: 'usability', emoji: '😕', name: '用起来不顺', desc: '能找到但别扭', color: '#FF922B',
      msgHint: '写下哪里让你觉得别扭，比如「字太小了，孩子看不清」…',
      expectLabel: '你希望它变成什么样？', expectHint: '（可选）描述理想的样子…' },
    { id: 'bug', emoji: '🐞', name: '出错了', desc: '点了没反应/显示不对', color: '#F06595',
      msgHint: '写下发生了什么，比如「点书包标签一直转圈，出不来清单」…',
      expectLabel: '你是怎么操作的？', expectHint: '（可选）一步步说，方便我复现…' },
    { id: 'other', emoji: '💬', name: '其它想说的', desc: '随便聊聊', color: '#20C997',
      msgHint: '想说什么就写什么…',
      expectLabel: '还想补充点什么？', expectHint: '（可选）' }
  ];

  var SEVERITIES = [
    { id: 'low', name: '不影响用' },
    { id: 'medium', name: '有点烦' },
    { id: 'high', name: '很难用' },
    { id: 'blocker', name: '完全用不了' }
  ];

  /* 路径 -> 人类可读的页面名与所属技能，用于反馈上下文与 Issue 归类 */
  var PAGE_MAP = [
    { re: /\/tracker\.html$/, skill: 'growth-home', tabKey: 'id', name: '每日打卡' },
    { re: /\/learn\/web\/dashboard\.html$|^\/dashboard\.html$/, skill: 'learning-growth-board', name: '学习看板' },
    { re: /\/bag\/web\/checklist\.html$|^\/checklist\.html$/, skill: 'school-bag-organizer', name: '书包清单' },
    { re: /\/art\/web\/art\.html$|^\/art\.html$/, skill: 'xiaoshan-art-archive', name: '画作画廊' },
    { re: /\/web\/index\.html$|^\/$|^\/index\.html$/, skill: 'growth-home', name: '门户首页' }
  ];

  var TRACKER_NAMES = { reading: '读书打卡', chores: '家务打卡', sports: '运动打卡' };

  /* ------------------------------------------------------------------ *
   * 小工具
   * ------------------------------------------------------------------ */

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function uuid() {
    try {
      if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    } catch (e) { /* 继续走下面的降级 */ }
    var buf = new Uint8Array(16);
    try { crypto.getRandomValues(buf); } catch (e) {
      for (var i = 0; i < 16; i++) buf[i] = Math.floor(Math.random() * 256);
    }
    buf[6] = (buf[6] & 0x0f) | 0x40;
    buf[8] = (buf[8] & 0x3f) | 0x80;
    var hex = [];
    for (var j = 0; j < 16; j++) hex.push((buf[j] + 0x100).toString(16).slice(1));
    return hex.slice(0, 4).join('') + '-' + hex.slice(4, 6).join('') + '-' + hex.slice(6, 8).join('') +
      '-' + hex.slice(8, 10).join('') + '-' + hex.slice(10, 16).join('');
  }

  function localInstallId() {
    var id = null;
    try { id = localStorage.getItem(LS_INSTALL_ID); } catch (e) { /* 隐私模式 */ }
    if (!id) {
      id = uuid();
      try { localStorage.setItem(LS_INSTALL_ID, id); } catch (e) { /* 忽略 */ }
    }
    return id;
  }

  function readLS(key, fallback) {
    try {
      var raw = localStorage.getItem(key);
      return raw ? JSON.parse(raw) : fallback;
    } catch (e) { return fallback; }
  }

  function writeLS(key, val) {
    try { localStorage.setItem(key, JSON.stringify(val)); } catch (e) { /* 存储满了就放弃 */ }
  }

  function themeName() {
    try { if (window.GrowthThemes && GrowthThemes.current) return GrowthThemes.current(); } catch (e) { /* 无主题引擎 */ }
    return '';
  }

  function pageInfo() {
    /* 页面可以用 window.GH_FEEDBACK_PAGE = { title: 'xxx', tab: 'yyy' } 显式声明，优先级最高 */
    var declared = window.GH_FEEDBACK_PAGE || {};
    var path = location.pathname;
    var matched = null;
    for (var i = 0; i < PAGE_MAP.length; i++) {
      if (PAGE_MAP[i].re.test(path)) { matched = PAGE_MAP[i]; break; }
    }
    var name = declared.title || (matched ? matched.name : (document.title || path));
    var tab = declared.tab || '';
    if (!tab && matched && matched.tabKey) {
      var q = new URLSearchParams(location.search);
      var tid = q.get('id') || '';
      if (tid) {
        tab = tid;
        if (!declared.title) name = TRACKER_NAMES[tid] || (tid + ' 打卡');
      }
    }
    if (!tab && matched) tab = matched.skill;
    return {
      path: path + location.search,
      title: name,
      tab: tab || 'unknown',
      skill: (matched && matched.skill) || 'growth-home',
      url: location.href
    };
  }

  function envInfo() {
    var nav = navigator;
    var dpr = window.devicePixelRatio || 1;
    return {
      ua: nav.userAgent || '',
      platform: nav.platform || (nav.userAgentData && nav.userAgentData.platform) || '',
      screen: (screen.width || 0) + 'x' + (screen.height || 0) + '@' + dpr,
      viewport: (window.innerWidth || 0) + 'x' + (window.innerHeight || 0),
      lang: nav.language || '',
      theme: themeName(),
      online: !!nav.onLine,
      touch: !!(nav.maxTouchPoints > 0 || 'ontouchstart' in window),
      standalone: !!(window.matchMedia && window.matchMedia('(display-mode: standalone)').matches)
    };
  }

  function fetchJson(url, options, timeoutMs) {
    var ctrl = null;
    if (typeof AbortController === 'function') {
      ctrl = new AbortController();
      setTimeout(function () { ctrl.abort(); }, timeoutMs || 12000);
      options = options || {};
      options.signal = ctrl.signal;
    }
    return fetch(url, options).then(function (res) {
      return res.text().then(function (text) {
        var data = null;
        try { data = text ? JSON.parse(text) : {}; } catch (e) { data = { raw: text.slice(0, 300) }; }
        if (!res.ok) {
          var err = new Error((data && (data.error || data.message)) || ('HTTP ' + res.status));
          err.status = res.status;
          err.data = data;
          throw err;
        }
        return data;
      });
    });
  }

  /* ------------------------------------------------------------------ *
   * 截图压缩：把用户选的图缩到最长边 1280、转 JPEG，避免上传过大
   * ------------------------------------------------------------------ */

  function compressImage(file) {
    return new Promise(function (resolve, reject) {
      if (!/^image\//.test(file.type)) { reject(new Error('不是图片')); return; }
      var url = null;
      var img = new Image();
      var done = false;
      var timer = setTimeout(function () {
        if (!done) { done = true; if (url) URL.revokeObjectURL(url); reject(new Error('图片读取超时')); }
      }, 15000);

      img.onload = function () {
        if (done) return;
        done = true;
        clearTimeout(timer);
        try {
          var w = img.naturalWidth || img.width;
          var h = img.naturalHeight || img.height;
          var scale = Math.min(1, MAX_IMAGE_EDGE / Math.max(w, h));
          var cw = Math.max(1, Math.round(w * scale));
          var ch = Math.max(1, Math.round(h * scale));
          var canvas = document.createElement('canvas');
          canvas.width = cw; canvas.height = ch;
          var ctx = canvas.getContext('2d');
          /* JPEG 不支持透明，先铺白底，否则 PNG 透明区会变黑 */
          ctx.fillStyle = '#FFFFFF';
          ctx.fillRect(0, 0, cw, ch);
          ctx.drawImage(img, 0, 0, cw, ch);

          var quality = 0.82;
          var dataUrl = canvas.toDataURL('image/jpeg', quality);
          /* 还是太大就继续降质量，最多两轮 */
          var tries = 0;
          while (dataUrl.length > 2.2 * 1024 * 1024 && tries < 2) {
            quality -= 0.2;
            dataUrl = canvas.toDataURL('image/jpeg', quality);
            tries++;
          }
          if (url) URL.revokeObjectURL(url);
          resolve({
            name: (file.name || 'screenshot').replace(/\.[^.]+$/, '') + '.jpg',
            mime: 'image/jpeg',
            data: dataUrl.split(',')[1] || '',
            preview: dataUrl,
            bytes: Math.round((dataUrl.length - (dataUrl.indexOf(',') + 1)) * 0.75)
          });
        } catch (e) {
          if (url) URL.revokeObjectURL(url);
          reject(e);
        }
      };
      img.onerror = function () {
        if (done) return;
        done = true;
        clearTimeout(timer);
        if (url) URL.revokeObjectURL(url);
        reject(new Error('图片打不开'));
      };
      try {
        url = URL.createObjectURL(file);
        img.src = url;
      } catch (e) {
        /* 老浏览器兜底：直接用 FileReader */
        var fr = new FileReader();
        fr.onload = function () { img.src = fr.result; };
        fr.onerror = function () { done = true; clearTimeout(timer); reject(new Error('图片读取失败')); };
        fr.readAsDataURL(file);
      }
    });
  }

  /* ------------------------------------------------------------------ *
   * 样式（注入一次，全部带 ghfb- 前缀，不污染宿主页面）
   * ------------------------------------------------------------------ */

  var CSS = [
    '.ghfb-btn{position:fixed;right:14px;bottom:calc(14px + env(safe-area-inset-bottom,0px));z-index:90000;',
    'display:inline-flex;align-items:center;gap:6px;padding:10px 16px 10px 13px;cursor:pointer;',
    'font-family:inherit;font-size:15px;font-weight:900;line-height:1;color:var(--ink,#4A3B2A);',
    'background:var(--card,#FFF6E9);border:3px solid var(--edge,#4A3B2A);border-radius:999px;',
    'box-shadow:0 4px 0 var(--edge,#4A3B2A);transition:transform .12s ease,box-shadow .12s ease;',
    '-webkit-tap-highlight-color:transparent;}',
    '.ghfb-btn:active{transform:translateY(3px);box-shadow:0 1px 0 var(--edge,#4A3B2A);}',
    '.ghfb-btn .ghfb-ico{font-size:19px;animation:ghfbBob 3.2s ease-in-out infinite alternate;}',
    '@keyframes ghfbBob{from{transform:translateY(0) rotate(-6deg)}to{transform:translateY(-3px) rotate(6deg)}}',
    '.ghfb-btn .ghfb-dot{position:absolute;top:-4px;right:-4px;min-width:18px;height:18px;padding:0 4px;',
    'border-radius:9px;background:#F06595;color:#fff;font-size:11px;font-weight:900;line-height:18px;',
    'text-align:center;border:2px solid var(--edge,#4A3B2A);display:none;}',
    '.ghfb-btn.ghfb-pending .ghfb-dot{display:block;}',

    '.ghfb-hint{position:fixed;right:14px;bottom:calc(66px + env(safe-area-inset-bottom,0px));z-index:90000;',
    'max-width:min(72vw,260px);padding:10px 13px;font-family:inherit;font-size:13px;font-weight:700;line-height:1.5;',
    'color:var(--ink,#4A3B2A);background:var(--card,#fff);border:3px solid var(--edge,#4A3B2A);border-radius:16px;',
    'box-shadow:0 4px 0 rgba(74,59,42,.2);animation:ghfbPop .3s cubic-bezier(.34,1.56,.64,1);}',
    '.ghfb-hint b{color:var(--acc-deep,#C9A227);}',
    '.ghfb-hint .ghfb-x{position:absolute;top:-9px;left:-9px;width:22px;height:22px;border-radius:50%;',
    'border:2px solid var(--edge,#4A3B2A);background:var(--card,#fff);font-size:12px;line-height:18px;',
    'text-align:center;cursor:pointer;font-weight:900;}',
    '@keyframes ghfbPop{from{transform:scale(.8) translateY(8px);opacity:0}to{transform:scale(1);opacity:1}}',

    '.ghfb-mask{position:fixed;inset:0;z-index:90001;background:rgba(0,0,0,.42);',
    'display:flex;align-items:flex-end;justify-content:center;padding:0;}',
    '@media(min-width:640px){.ghfb-mask{align-items:center;padding:20px;}}',
    '.ghfb-panel{width:100%;max-width:520px;max-height:92dvh;overflow-y:auto;-webkit-overflow-scrolling:touch;',
    'background:var(--paper,#FFF6E9);border:4px solid var(--edge,#4A3B2A);border-radius:26px 26px 0 0;',
    'box-shadow:0 -6px 0 rgba(0,0,0,.18);padding:14px 16px calc(18px + env(safe-area-inset-bottom,0px));',
    'font-family:inherit;color:var(--ink,#4A3B2A);animation:ghfbUp .28s cubic-bezier(.34,1.56,.64,1);}',
    '@media(min-width:640px){.ghfb-panel{border-radius:26px;box-shadow:0 10px 0 rgba(0,0,0,.22);}}',
    '@keyframes ghfbUp{from{transform:translateY(28px) scale(.97);opacity:0}to{transform:none;opacity:1}}',
    '.ghfb-panel.ghfb-hidden{display:none;}',
    '.ghfb-mask.ghfb-hidden{display:none;}',

    '.ghfb-head{display:flex;align-items:center;gap:8px;margin-bottom:4px;}',
    '.ghfb-head h3{font-size:19px;font-weight:900;letter-spacing:.5px;flex:1;margin:0;}',
    '.ghfb-close{width:32px;height:32px;flex:none;border-radius:50%;border:3px solid var(--edge,#4A3B2A);',
    'background:var(--card,#fff);font-size:15px;font-weight:900;cursor:pointer;line-height:1;color:var(--ink,#4A3B2A);}',
    '.ghfb-lead{font-size:13px;font-weight:700;color:var(--soft,#8D7357);line-height:1.6;margin-bottom:12px;}',

    '.ghfb-sec{margin-bottom:13px;}',
    '.ghfb-lab{display:block;font-size:13px;font-weight:900;margin-bottom:7px;}',
    '.ghfb-lab .ghfb-opt{font-weight:700;color:var(--soft,#8D7357);font-size:12px;}',
    '.ghfb-types{display:grid;grid-template-columns:repeat(2,1fr);gap:8px;}',
    '@media(max-width:359px){.ghfb-types{grid-template-columns:1fr;}}',
    '.ghfb-type{display:flex;align-items:center;gap:8px;padding:9px 10px;cursor:pointer;text-align:left;',
    'font-family:inherit;border:3px solid var(--edge,#4A3B2A);border-radius:16px;background:var(--card,#fff);',
    'box-shadow:0 3px 0 var(--edge,#4A3B2A);transition:transform .12s ease,box-shadow .12s ease,background .2s ease;}',
    '.ghfb-type:active{transform:translateY(2px);box-shadow:0 1px 0 var(--edge,#4A3B2A);}',
    '.ghfb-type .ghfb-te{font-size:22px;flex:none;}',
    '.ghfb-type .ghfb-tn{font-size:14px;font-weight:900;line-height:1.25;color:var(--ink,#4A3B2A);}',
    '.ghfb-type .ghfb-td{font-size:11px;font-weight:700;color:var(--soft,#8D7357);line-height:1.3;}',
    '.ghfb-type.ghfb-on{background:var(--c,#FF922B);}',
    '.ghfb-type.ghfb-on .ghfb-tn,.ghfb-type.ghfb-on .ghfb-td{color:#fff;}',

    '.ghfb-ta,.ghfb-in{width:100%;font-family:inherit;font-size:15px;font-weight:600;color:var(--ink,#4A3B2A);',
    'background:var(--card,#fff);border:3px solid var(--edge,#4A3B2A);border-radius:16px;padding:10px 12px;',
    'outline:none;resize:vertical;}',
    '.ghfb-ta{min-height:96px;line-height:1.6;}',
    '.ghfb-ta:focus,.ghfb-in:focus{box-shadow:0 0 0 3px rgba(255,146,43,.35);}',
    '.ghfb-ta::placeholder,.ghfb-in::placeholder{color:var(--soft,#8D7357);opacity:.65;font-weight:600;}',
    '.ghfb-count{text-align:right;font-size:11px;font-weight:700;color:var(--soft,#8D7357);margin-top:4px;}',

    '.ghfb-chips{display:flex;flex-wrap:wrap;gap:7px;}',
    '.ghfb-chip{padding:7px 12px;font-family:inherit;font-size:13px;font-weight:800;cursor:pointer;',
    'border:3px solid var(--edge,#4A3B2A);border-radius:999px;background:var(--card,#fff);color:var(--ink,#4A3B2A);',
    'box-shadow:0 3px 0 var(--edge,#4A3B2A);}',
    '.ghfb-chip:active{transform:translateY(2px);box-shadow:0 1px 0 var(--edge,#4A3B2A);}',
    '.ghfb-chip.ghfb-on{background:var(--acc,#FF922B);color:#fff;}',

    '.ghfb-shots{display:flex;flex-wrap:wrap;gap:8px;}',
    '.ghfb-shot{position:relative;width:74px;height:74px;border:3px solid var(--edge,#4A3B2A);border-radius:14px;',
    'overflow:hidden;background:var(--card,#fff);}',
    '.ghfb-shot img{width:100%;height:100%;object-fit:cover;display:block;}',
    '.ghfb-shot .ghfb-rm{position:absolute;top:2px;right:2px;width:20px;height:20px;border-radius:50%;',
    'border:2px solid var(--edge,#4A3B2A);background:#fff;font-size:11px;line-height:16px;text-align:center;',
    'cursor:pointer;font-weight:900;}',
    '.ghfb-add{width:74px;height:74px;display:flex;flex-direction:column;align-items:center;justify-content:center;',
    'gap:2px;cursor:pointer;font-family:inherit;font-size:11px;font-weight:800;color:var(--soft,#8D7357);',
    'border:3px dashed var(--edge,#4A3B2A);border-radius:14px;background:transparent;}',
    '.ghfb-add span:first-child{font-size:22px;}',

    '.ghfb-note{font-size:11.5px;font-weight:700;line-height:1.65;color:var(--soft,#8D7357);',
    'background:color-mix(in srgb,var(--card,#fff) 70%,transparent);border:2px dashed var(--edge,#4A3B2A);',
    'border-radius:14px;padding:9px 11px;}',
    '.ghfb-note b{color:var(--ink,#4A3B2A);}',
    '.ghfb-det{margin-top:8px;font-size:12px;}',
    '.ghfb-det summary{cursor:pointer;font-weight:800;color:var(--soft,#8D7357);list-style:none;}',
    '.ghfb-det summary::-webkit-details-marker{display:none;}',
    '.ghfb-det summary::before{content:"▸ ";}',
    '.ghfb-det[open] summary::before{content:"▾ ";}',
    '.ghfb-det pre{margin-top:7px;padding:9px 10px;overflow:auto;max-height:150px;font-size:11px;line-height:1.5;',
    'background:var(--card,#fff);border:2px solid var(--edge,#4A3B2A);border-radius:12px;white-space:pre-wrap;word-break:break-all;}',

    '.ghfb-send{width:100%;padding:14px;font-family:inherit;font-size:17px;font-weight:900;letter-spacing:1px;',
    'color:#fff;background:var(--acc,#FF922B);border:4px solid var(--edge,#4A3B2A);border-radius:18px;',
    'box-shadow:0 6px 0 var(--edge,#4A3B2A);cursor:pointer;transition:transform .12s ease,box-shadow .12s ease;}',
    '.ghfb-send:active{transform:translateY(4px);box-shadow:0 2px 0 var(--edge,#4A3B2A);}',
    '.ghfb-send:disabled{opacity:.6;cursor:not-allowed;}',

    '.ghfb-status{margin-top:10px;padding:10px 12px;border-radius:14px;font-size:13px;font-weight:800;line-height:1.6;',
    'border:3px solid var(--edge,#4A3B2A);background:var(--card,#fff);display:none;}',
    '.ghfb-status.ghfb-show{display:block;animation:ghfbPop .25s ease;}',
    '.ghfb-status.ghfb-ok{background:#D3F9D8;}',
    '.ghfb-status.ghfb-warn{background:#FFF3BF;}',
    '.ghfb-status.ghfb-bad{background:#FFE3E3;}',
    '.ghfb-status a{color:#1971C2;font-weight:900;}',
    '.ghfb-status .ghfb-acts{display:flex;gap:8px;margin-top:8px;flex-wrap:wrap;}',
    '.ghfb-mini{padding:7px 11px;font-family:inherit;font-size:12px;font-weight:800;cursor:pointer;',
    'border:2px solid var(--edge,#4A3B2A);border-radius:999px;background:var(--card,#fff);color:var(--ink,#4A3B2A);}',

    '.ghfb-done{text-align:center;padding:26px 10px 18px;display:none;}',
    '.ghfb-done.ghfb-show{display:block;}',
    '.ghfb-done .ghfb-big{font-size:56px;animation:ghfbBob2 .7s ease-in-out infinite alternate;}',
    '@keyframes ghfbBob2{from{transform:translateY(0) scale(1)}to{transform:translateY(-12px) scale(1.08)}}',
    '.ghfb-done h4{font-size:20px;font-weight:900;margin:10px 0 6px;}',
    '.ghfb-done p{font-size:13.5px;font-weight:700;color:var(--soft,#8D7357);line-height:1.7;}',
    '.ghfb-conf{position:fixed;inset:0;pointer-events:none;z-index:90002;overflow:hidden;}',
    '.ghfb-conf i{position:absolute;top:-24px;font-size:20px;font-style:normal;animation:ghfbFall linear forwards;}',
    '@keyframes ghfbFall{to{transform:translateY(105vh) rotate(540deg);opacity:.2;}}'
  ].join('');

  /* ------------------------------------------------------------------ *
   * 子页面（iframe 内）模式：只上报上下文，不渲染界面
   * ------------------------------------------------------------------ */

  function isFramed() {
    try { return window.self !== window.top; } catch (e) { return true; }
  }

  function runChildMode() {
    var lastSent = '';
    function sendContext() {
      var payload = { __ghFb: MSG_NS, kind: 'context', page: pageInfo(), env: envInfo(), widgetVersion: WIDGET_VERSION };
      var stamp = JSON.stringify(payload.page);
      if (stamp === lastSent) return;
      lastSent = stamp;
      try { window.parent.postMessage(payload, '*'); } catch (e) { /* 跨域或父窗口已关闭 */ }
    }
    window.addEventListener('message', function (e) {
      var d = e.data;
      if (!d || d.__ghFb !== MSG_NS) return;
      if (d.kind === 'ping') { lastSent = ''; sendContext(); }
    });
    /* 初次上报，之后轻量轮询（打卡页切标签、看板切周次时地址或标题会变）。
     * 不用 MutationObserver：书包清单等页面动画很多，监听全树开销太大。 */
    sendContext();
    setTimeout(sendContext, 600);
    setTimeout(sendContext, 2000);
    setInterval(sendContext, 3000);
    document.addEventListener('themechange', function () { lastSent = ''; sendContext(); });
  }

  /* ------------------------------------------------------------------ *
   * 顶层模式：渲染按钮与面板
   * ------------------------------------------------------------------ */

  var state = {
    cfg: null,             /* 本地服务器下发的配置（installId/appVersion/relayUrl…） */
    cfgLoaded: false,
    childPage: null,       /* iframe 子页面上报的上下文 */
    childEnv: null,
    type: 'feature',
    severity: '',
    images: [],
    sending: false,
    flushing: false,
    statusOwner: ''
  };

  function page() {
    /* 首页有子页面上下文时，以「用户实际正在看的那个子页面」为准，同时保留门户信息 */
    var top = pageInfo();
    if (state.childPage && state.childPage.path && state.childPage.path !== top.path) {
      return {
        path: state.childPage.path,
        title: state.childPage.title,
        tab: state.childPage.tab,
        skill: state.childPage.skill,
        url: state.childPage.url,
        via: '门户首页 · ' + top.title
      };
    }
    return { path: top.path, title: top.title, tab: top.tab, skill: top.skill, url: top.url, via: '' };
  }

  function env() {
    var base = envInfo();
    if (state.childEnv) {
      /* 子页面的 UA/屏幕与顶层一致，但皮肤名可能不同步，取子页面的更准 */
      base.theme = state.childEnv.theme || base.theme;
      base.touch = state.childEnv.touch;
    }
    return base;
  }

  function loadConfig() {
    if (state.cfgLoaded) return Promise.resolve(state.cfg);
    return fetchJson('/api/feedback/config', { cache: 'no-store' }, 6000)
      .then(function (data) {
        state.cfg = data || {};
        state.cfgLoaded = true;
        writeLS(LS_CONFIG, { relayUrl: state.cfg.relayUrl || '', appVersion: state.cfg.appVersion || '', ts: Date.now() });
        return state.cfg;
      })
      .catch(function () {
        /* 本地服务器没有这个接口（例如直接打开单文件版）：用缓存 + 内置默认值 */
        var cached = readLS(LS_CONFIG, {});
        state.cfg = {
          installId: localInstallId(),
          appVersion: cached.appVersion || '',
          relayUrl: DEFAULT_RELAY_URL || cached.relayUrl || '',
          serverAvailable: false
        };
        state.cfgLoaded = true;
        return state.cfg;
      });
  }

  function relayUrl() {
    return (state.cfg && state.cfg.relayUrl) || DEFAULT_RELAY_URL || readLS(LS_CONFIG, {}).relayUrl || '';
  }

  function buildPayload() {
    var cfg = state.cfg || {};
    var msgEl = document.getElementById('ghfbMsg');
    var expEl = document.getElementById('ghfbExpect');
    var conEl = document.getElementById('ghfbContact');
    return {
      type: state.type,
      summary: '',
      message: (msgEl && msgEl.value || '').trim().slice(0, MAX_MESSAGE),
      expect: (expEl && expEl.value || '').trim().slice(0, 1000),
      severity: state.severity || '',
      contact: (conEl && conEl.value || '').trim().slice(0, 200),
      page: page(),
      env: env(),
      images: state.images.map(function (im) { return { name: im.name, mime: im.mime, data: im.data }; }),
      client: {
        appVersion: cfg.appVersion || '',
        widgetVersion: WIDGET_VERSION,
        installId: cfg.installId || localInstallId(),
        submittedAt: new Date().toISOString()
      }
    };
  }

  /* 离线队列：断网或通道全挂时先存本机 */
  function enqueue(payload, reason) {
    var q = readLS(LS_QUEUE, []);
    q.push({ payload: payload, reason: String(reason || '').slice(0, 200), queuedAt: new Date().toISOString() });
    if (q.length > 20) q = q.slice(-20);   /* 最多留 20 条，避免 localStorage 撑爆 */
    writeLS(LS_QUEUE, q);
    updatePendingBadge();
  }

  function queueCount() { return readLS(LS_QUEUE, []).length; }

  function updatePendingBadge() {
    var btn = document.getElementById('ghfbBtn');
    var dot = document.getElementById('ghfbDot');
    if (!btn) return;
    var n = queueCount();
    if (n > 0) { btn.classList.add('ghfb-pending'); if (dot) dot.textContent = n > 9 ? '9+' : String(n); }
    else { btn.classList.remove('ghfb-pending'); }
  }

  function flushQueue() {
    var q = readLS(LS_QUEUE, []);
    if (!q.length || state.flushing) return Promise.resolve(0);
    state.flushing = true;
    var sent = 0;
    var chain = Promise.resolve();
    q.forEach(function (item, idx) {
      chain = chain.then(function () {
        return deliver(item.payload, true).then(function (ok) {
          if (ok) { sent++; q[idx] = null; }
        }).catch(function () { /* 单条失败不影响其它 */ });
      });
    });
    return chain.then(function () {
      writeLS(LS_QUEUE, q.filter(Boolean));
      updatePendingBadge();
      state.flushing = false;
      return sent;
    }).catch(function () { state.flushing = false; return sent; });
  }

  /* 真正的发送：优先本地服务器，失败再直连中转服务 */
  function deliver(payload, isRetry) {
    var serverOk = !state.cfg || state.cfg.serverAvailable !== false;
    var attemptServer = serverOk
      ? fetchJson('/api/feedback', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        }, 25000)
      : Promise.reject(new Error('本地服务器不可用'));

    return attemptServer
      .then(function (res) { return normalizeResult(res, 'server'); })
      .catch(function (err1) {
        var url = relayUrl();
        if (!url) throw err1;
        /* 浏览器直连中转服务（Worker 已开启 CORS） */
        return fetchJson(url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        }, 25000).then(function (res) { return normalizeResult(res, 'direct'); })
          .catch(function (err2) { throw err2 || err1; });
      });
  }

  function normalizeResult(res, via) {
    var out = {
      ok: !!(res && res.ok),
      via: via,
      id: (res && res.id) || '',
      issueUrl: (res && res.issueUrl) || '',
      queued: !!(res && res.queued),
      delivered: (res && res.delivered) || [],
      failed: (res && res.failed) || [],
      message: (res && res.message) || ''
    };
    if (!out.ok && !out.queued) {
      var e = new Error(out.message || '发送失败');
      e.result = out;
      throw e;
    }
    return out;
  }

  function plainText(payload) {
    var t = (TYPES.filter(function (x) { return x.id === payload.type; })[0] || {}).name || payload.type;
    var lines = [
      '【成长家园 · 页面反馈】',
      '类型：' + t,
      '页面：' + (payload.page && payload.page.title || '') + ' ' + (payload.page && payload.page.path || ''),
      '内容：' + payload.message
    ];
    if (payload.expect) lines.push('期望：' + payload.expect);
    if (payload.severity) lines.push('严重程度：' + payload.severity);
    if (payload.contact) lines.push('联系方式：' + payload.contact);
    var e = payload.env || {};
    lines.push('环境：' + (e.platform || '') + ' / ' + (e.ua || '').slice(0, 90));
    lines.push('屏幕：' + (e.screen || '') + '  皮肤：' + (e.theme || ''));
    lines.push('匿名ID：' + String((payload.client && payload.client.installId) || '').slice(0, 8));
    lines.push('时间：' + (payload.client && payload.client.submittedAt || ''));
    if (payload.images && payload.images.length) lines.push('（另有 ' + payload.images.length + ' 张截图未能随文本复制）');
    return lines.join('\n');
  }

  function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text).then(function () { return true; }, function () { return legacyCopy(text); });
    }
    return Promise.resolve(legacyCopy(text));
  }

  function legacyCopy(text) {
    try {
      var ta = document.createElement('textarea');
      ta.value = text;
      ta.setAttribute('readonly', '');
      ta.style.cssText = 'position:fixed;left:-9999px;top:0';
      document.body.appendChild(ta);
      ta.select();
      var ok = document.execCommand('copy');
      document.body.removeChild(ta);
      return ok;
    } catch (e) { return false; }
  }

  /* ------------------------------------------------------------------ *
   * 界面构建
   * ------------------------------------------------------------------ */

  function buildDom() {
    var style = document.createElement('style');
    style.id = 'ghfbStyle';
    style.textContent = CSS;
    document.head.appendChild(style);

    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'ghfb-btn';
    btn.id = 'ghfbBtn';
    btn.setAttribute('aria-label', '提交页面改进建议');
    btn.innerHTML = '<span class="ghfb-ico">💌</span><span>提建议</span><span class="ghfb-dot" id="ghfbDot"></span>';
    document.body.appendChild(btn);

    var mask = document.createElement('div');
    mask.className = 'ghfb-mask ghfb-hidden';
    mask.id = 'ghfbMask';
    mask.innerHTML = [
      '<div class="ghfb-panel" role="dialog" aria-modal="true" aria-label="提交反馈">',

      /* --- 表单视图 --- */
      '<div id="ghfbForm">',
      '<div class="ghfb-head"><h3>💌 提个小建议</h3>',
      '<button type="button" class="ghfb-close" id="ghfbClose" aria-label="关闭">✕</button></div>',
      '<p class="ghfb-lead">这个页面是给你们家用的。哪里不好用、想要什么新功能，写下来直接送到作者手里，' +
      '每一条都会被认真看。</p>',

      '<div class="ghfb-sec"><span class="ghfb-lab">这是关于什么的？</span>',
      '<div class="ghfb-types" id="ghfbTypes"></div></div>',

      '<div class="ghfb-sec"><span class="ghfb-lab">具体说说 <span class="ghfb-opt">（必填）</span></span>',
      '<textarea class="ghfb-ta" id="ghfbMsg" maxlength="' + MAX_MESSAGE + '"></textarea>',
      '<div class="ghfb-count" id="ghfbCount">0 / ' + MAX_MESSAGE + '</div></div>',

      '<div class="ghfb-sec"><span class="ghfb-lab" id="ghfbExpectLab">你希望它变成什么样？ <span class="ghfb-opt">（可选）</span></span>',
      '<textarea class="ghfb-ta" id="ghfbExpect" style="min-height:62px"></textarea></div>',

      '<div class="ghfb-sec" id="ghfbSevSec" style="display:none">',
      '<span class="ghfb-lab">影响有多大？ <span class="ghfb-opt">（可选）</span></span>',
      '<div class="ghfb-chips" id="ghfbSev"></div></div>',

      '<div class="ghfb-sec"><span class="ghfb-lab">截图 <span class="ghfb-opt">（可选，最多 ' + MAX_IMAGES + ' 张）</span></span>',
      '<div class="ghfb-shots" id="ghfbShots"></div>',
      '<input type="file" id="ghfbFile" accept="image/*" multiple style="display:none"></div>',

      '<div class="ghfb-sec"><span class="ghfb-lab">想让我回复你？ <span class="ghfb-opt">（可选）</span></span>',
      '<input class="ghfb-in" id="ghfbContact" maxlength="200" placeholder="留个微信号或邮箱，修好了告诉你"></div>',

      '<div class="ghfb-sec"><div class="ghfb-note" id="ghfbNote"></div>',
      '<details class="ghfb-det"><summary>看看会一起发送哪些信息</summary><pre id="ghfbRaw"></pre></details></div>',

      '<button type="button" class="ghfb-send" id="ghfbSend">🚀 发送给作者</button>',
      '<div class="ghfb-status" id="ghfbStatus"></div>',
      '</div>',

      /* --- 成功视图 --- */
      '<div class="ghfb-done" id="ghfbDone">',
      '<div class="ghfb-big">🎉</div>',
      '<h4 id="ghfbDoneTitle">收到啦，谢谢你！</h4>',
      '<p id="ghfbDoneText"></p>',
      '<div class="ghfb-status ghfb-show ghfb-ok" style="margin-top:14px;text-align:left" id="ghfbDoneBox"></div>',
      '<button type="button" class="ghfb-send" id="ghfbDoneClose" style="margin-top:14px">好的</button>',
      '</div>',

      '</div>'
    ].join('');
    document.body.appendChild(mask);
  }

  function renderTypes() {
    var box = document.getElementById('ghfbTypes');
    box.innerHTML = TYPES.map(function (t) {
      return '<button type="button" class="ghfb-type' + (t.id === state.type ? ' ghfb-on' : '') + '" ' +
        'data-t="' + t.id + '" style="--c:' + t.color + '">' +
        '<span class="ghfb-te">' + t.emoji + '</span>' +
        '<span><span class="ghfb-tn">' + esc(t.name) + '</span><br>' +
        '<span class="ghfb-td">' + esc(t.desc) + '</span></span></button>';
    }).join('');
    Array.prototype.forEach.call(box.querySelectorAll('.ghfb-type'), function (el) {
      el.addEventListener('click', function () {
        state.type = el.getAttribute('data-t');
        renderTypes();
        syncTypeTexts();
      });
    });
  }

  function currentType() {
    return TYPES.filter(function (t) { return t.id === state.type; })[0] || TYPES[0];
  }

  function syncTypeTexts() {
    var t = currentType();
    var msg = document.getElementById('ghfbMsg');
    var exp = document.getElementById('ghfbExpect');
    var lab = document.getElementById('ghfbExpectLab');
    if (msg && !msg.value) msg.placeholder = t.msgHint;
    if (exp && !exp.value) exp.placeholder = t.expectHint;
    if (lab) lab.innerHTML = esc(t.expectLabel) + ' <span class="ghfb-opt">（可选）</span>';
    var sevSec = document.getElementById('ghfbSevSec');
    if (sevSec) sevSec.style.display = (state.type === 'bug' || state.type === 'usability') ? '' : 'none';
    if (state.type !== 'bug' && state.type !== 'usability') state.severity = '';
    renderSev();
    updateRaw();
  }

  function renderSev() {
    var box = document.getElementById('ghfbSev');
    if (!box) return;
    box.innerHTML = SEVERITIES.map(function (s) {
      return '<button type="button" class="ghfb-chip' + (s.id === state.severity ? ' ghfb-on' : '') + '" ' +
        'data-s="' + s.id + '">' + esc(s.name) + '</button>';
    }).join('');
    Array.prototype.forEach.call(box.querySelectorAll('.ghfb-chip'), function (el) {
      el.addEventListener('click', function () {
        var v = el.getAttribute('data-s');
        state.severity = (state.severity === v) ? '' : v;
        renderSev();
        updateRaw();
      });
    });
  }

  function renderShots() {
    var box = document.getElementById('ghfbShots');
    if (!box) return;
    var html = state.images.map(function (im, i) {
      return '<div class="ghfb-shot"><img src="' + im.preview + '" alt="截图' + (i + 1) + '">' +
        '<span class="ghfb-rm" data-i="' + i + '" role="button" aria-label="删除截图">✕</span></div>';
    }).join('');
    if (state.images.length < MAX_IMAGES) {
      html += '<button type="button" class="ghfb-add" id="ghfbAdd"><span>📷</span><span>加截图</span></button>';
    }
    box.innerHTML = html;
    Array.prototype.forEach.call(box.querySelectorAll('.ghfb-rm'), function (el) {
      el.addEventListener('click', function () {
        state.images.splice(Number(el.getAttribute('data-i')), 1);
        renderShots();
        updateRaw();
      });
    });
    var add = document.getElementById('ghfbAdd');
    if (add) add.addEventListener('click', function () { document.getElementById('ghfbFile').click(); });
  }

  function updateNote() {
    var p = page();
    var cfg = state.cfg || {};
    var el = document.getElementById('ghfbNote');
    if (!el) return;
    var iid = String(cfg.installId || localInstallId()).slice(0, 8);
    el.innerHTML = [
      '<b>会自动附带这些信息</b>（帮你我快速定位问题）：',
      '页面 <b>' + esc(p.title) + '</b>、设备与浏览器、屏幕尺寸、皮肤 <b>' + esc(env().theme || '默认') + '</b>、',
      '随机匿名编号 <b>' + esc(iid) + '</b>。<br>',
      '<b>不会</b>收集姓名、学校、班级。请别在文字或截图里写学校全名、班级和其他小朋友的名字。'
    ].join('');
  }

  function updateRaw() {
    var pre = document.getElementById('ghfbRaw');
    if (!pre) return;
    var p = buildPayload();
    var slim = {
      类型: p.type,
      内容: p.message || '（还没写）',
      期望: p.expect || '',
      严重程度: p.severity || '',
      联系方式: p.contact || '',
      页面: p.page.title + ' ' + p.page.path,
      设备: p.env.platform + ' · ' + p.env.screen + ' · ' + (p.env.ua || '').slice(0, 60) + '…',
      皮肤: p.env.theme,
      截图: p.images.length + ' 张',
      匿名ID: String(p.client.installId).slice(0, 8) + '…',
      应用版本: p.client.appVersion || '未知'
    };
    pre.textContent = JSON.stringify(slim, null, 2);
  }

  function showStatus(kind, html, actions, owner) {
    var el = document.getElementById('ghfbStatus');
    if (!el) return;
    owner = owner || 'user';
    /* 后台补发的结果不能盖掉用户刚刚看到的提交结果：
     * 打开面板时会顺手补发历史队列，网络慢时补发可能在用户提交之后才回来。 */
    if (owner === 'flush' && state.statusOwner === 'submit') return;
    state.statusOwner = owner;
    el.className = 'ghfb-status ghfb-show ghfb-' + kind;
    el.innerHTML = html + (actions && actions.length
      ? '<div class="ghfb-acts">' + actions.map(function (a, i) {
          return '<button type="button" class="ghfb-mini" data-a="' + i + '">' + esc(a.label) + '</button>';
        }).join('') + '</div>'
      : '');
    if (actions) {
      Array.prototype.forEach.call(el.querySelectorAll('.ghfb-mini'), function (b) {
        b.addEventListener('click', function () { actions[Number(b.getAttribute('data-a'))].onClick(); });
      });
    }
  }

  function hideStatus() {
    var el = document.getElementById('ghfbStatus');
    state.statusOwner = '';
    if (el) { el.className = 'ghfb-status'; el.innerHTML = ''; }
  }

  function confetti() {
    var box = document.createElement('div');
    box.className = 'ghfb-conf';
    var bits = ['🎉', '⭐', '🌈', '💛', '✨', '🎈'];
    var html = '';
    for (var i = 0; i < 22; i++) {
      html += '<i style="left:' + (Math.random() * 100).toFixed(1) + '%;animation-duration:' +
        (1.1 + Math.random() * 1.1).toFixed(2) + 's;animation-delay:' + (Math.random() * 0.35).toFixed(2) +
        's;font-size:' + (14 + Math.random() * 14).toFixed(0) + 'px">' + bits[i % bits.length] + '</i>';
    }
    box.innerHTML = html;
    document.body.appendChild(box);
    setTimeout(function () { if (box.parentNode) box.parentNode.removeChild(box); }, 2600);
  }

  function openPanel() {
    var mask = document.getElementById('ghfbMask');
    var form = document.getElementById('ghfbForm');
    var done = document.getElementById('ghfbDone');
    form.style.display = '';
    done.classList.remove('ghfb-show');
    mask.classList.remove('ghfb-hidden');
    hideStatus();
    updateNote();
    updateRaw();
    updatePendingBadge();
    var hint = document.getElementById('ghfbHint');
    if (hint && hint.parentNode) hint.parentNode.removeChild(hint);
    /* 打开面板时顺手把上次没发出去的补发 */
    if (queueCount() > 0) {
      showStatus('warn', '📮 本机还有 <b>' + queueCount() + '</b> 条上次没发出去的建议，正在重发…', null, 'flush');
      flushQueue().then(function (n) {
        if (n > 0) showStatus('ok', '✅ 补发成功 ' + n + ' 条，谢谢你！', null, 'flush');
        else if (queueCount() > 0) showStatus('warn', '📮 还有 ' + queueCount() + ' 条没发出去，等网络好了会自动重试。', null, 'flush');
        else if (state.statusOwner === 'flush') hideStatus();
      });
    }
    setTimeout(function () {
      var ta = document.getElementById('ghfbMsg');
      if (ta && window.innerWidth >= 640) ta.focus();
    }, 260);
  }

  function closePanel() {
    document.getElementById('ghfbMask').classList.add('ghfb-hidden');
  }

  function showDone(result) {
    var form = document.getElementById('ghfbForm');
    var done = document.getElementById('ghfbDone');
    var box = document.getElementById('ghfbDoneBox');
    var text = document.getElementById('ghfbDoneText');
    form.style.display = 'none';
    done.classList.add('ghfb-show');
    confetti();

    var p = page();
    if (result && result.ok && !result.queued && (result.delivered || []).length) {
      text.textContent = '你的建议已经送到作者手里了，会在「' + p.title + '」上认真改进。';
      var lines = ['✅ <b>已送达</b>'];
      if (result.issueUrl) {
        lines.push('已自动生成跟踪条目：<a href="' + esc(result.issueUrl) + '" target="_blank" rel="noopener">查看进度</a>');
      } else {
        lines.push('作者会尽快处理。');
      }
      if (result.id) lines.push('回执编号：<b>' + esc(String(result.id).slice(0, 24)) + '</b>');
      box.className = 'ghfb-status ghfb-show ghfb-ok';
      box.innerHTML = lines.join('<br>');
    } else if (result && (result.queued || queueCount() > 0)) {
      text.textContent = '现在网络不太通，你的建议已经存在这台设备上了，联网后会自动补发，不会丢。';
      box.className = 'ghfb-status ghfb-show ghfb-warn';
      box.innerHTML = '📮 <b>已存到本机</b>，待发送 ' + queueCount() + ' 条。<br>' +
        '着急的话可以复制下面这段文字，直接发给作者。';
      var acts = document.createElement('div');
      acts.className = 'ghfb-acts';
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'ghfb-mini';
      b.textContent = '📋 复制反馈内容';
      b.addEventListener('click', function () {
        var q = readLS(LS_QUEUE, []);
        var last = q.length ? q[q.length - 1].payload : null;
        copyText(plainText(last || buildPayload())).then(function (ok) {
          b.textContent = ok ? '✅ 已复制' : '复制失败，请手动选择';
        });
      });
      acts.appendChild(b);
      box.appendChild(acts);
    } else {
      text.textContent = '谢谢你愿意告诉我！';
      box.className = 'ghfb-status ghfb-show ghfb-ok';
      box.innerHTML = '✅ 已记录';
    }
  }

  function submit() {
    if (state.sending) return;
    var msg = document.getElementById('ghfbMsg');
    var text = (msg.value || '').trim();
    if (text.length < 2) {
      showStatus('bad', '✏️ 先写两句吧，哪怕只是「字太小了」也很有用。', null, 'submit');
      msg.focus();
      return;
    }
    var payload = buildPayload();
    payload.summary = text.split('\n')[0].slice(0, 60);
    state.sending = true;
    var sendBtn = document.getElementById('ghfbSend');
    sendBtn.disabled = true;
    sendBtn.textContent = '📡 正在发送…';
    showStatus('warn', '📡 正在发送，别关掉页面…', null, 'submit');

    deliver(payload, false)
      .then(function (res) {
        state.sending = false;
        sendBtn.disabled = false;
        sendBtn.textContent = '🚀 发送给作者';
        /* 服务器可能已经落盘但转发失败（queued=true）：不算用户失败，仍显示成功 */
        showDone(res);
        resetForm();
      })
      .catch(function (err) {
        state.sending = false;
        sendBtn.disabled = false;
        sendBtn.textContent = '🚀 发送给作者';
        var status = err && err.status;
        /* 4xx 说明是内容本身不合格（太短、太大），重试多少次都一样：
         * 直接把原因讲清楚，并且不清空输入框、不进补发队列。 */
        if (status === 400 || status === 413 || status === 422) {
          var why = esc((err && err.message) || '内容不符合要求');
          if (status === 413) why += '<br>多半是截图太大了，删掉一张再发试试。';
          showStatus('bad', '😥 没能发出去：' + why + '<br>你写的字还在框里，没有丢。', null, 'submit');
          return;
        }
        enqueue(payload, (err && err.message) || '未知错误');
        showDone({ ok: false, queued: true });
        resetForm();
      });
  }

  function resetForm() {
    document.getElementById('ghfbMsg').value = '';
    document.getElementById('ghfbExpect').value = '';
    document.getElementById('ghfbContact').value = '';
    document.getElementById('ghfbCount').textContent = '0 / ' + MAX_MESSAGE;
    state.images = [];
    state.severity = '';
    renderShots();
    renderSev();
    syncTypeTexts();
  }

  function showHintOnce() {
    var seen = false;
    try { seen = localStorage.getItem(LS_HINT) === '1'; } catch (e) { seen = true; }
    if (seen) return;
    setTimeout(function () {
      if (document.getElementById('ghfbMask') && !document.getElementById('ghfbMask').classList.contains('ghfb-hidden')) return;
      var hint = document.createElement('div');
      hint.className = 'ghfb-hint';
      hint.id = 'ghfbHint';
      hint.innerHTML = '<span class="ghfb-x" role="button" aria-label="知道了">✕</span>' +
        '用得不顺手？<b>点这里告诉作者</b>，她会认真改 💛';
      document.body.appendChild(hint);
      function dismiss() {
        try { localStorage.setItem(LS_HINT, '1'); } catch (e) { /* 忽略 */ }
        if (hint.parentNode) hint.parentNode.removeChild(hint);
      }
      hint.querySelector('.ghfb-x').addEventListener('click', dismiss);
      hint.addEventListener('click', function (e) {
        if (e.target.className !== 'ghfb-x') { dismiss(); openPanel(); }
      });
      setTimeout(dismiss, 12000);
    }, 6000);
  }

  function bind() {
    document.getElementById('ghfbBtn').addEventListener('click', openPanel);
    document.getElementById('ghfbClose').addEventListener('click', closePanel);
    document.getElementById('ghfbDoneClose').addEventListener('click', closePanel);
    document.getElementById('ghfbMask').addEventListener('click', function (e) {
      if (e.target.id === 'ghfbMask') closePanel();
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') closePanel();
    });

    var msg = document.getElementById('ghfbMsg');
    msg.addEventListener('input', function () {
      document.getElementById('ghfbCount').textContent = msg.value.length + ' / ' + MAX_MESSAGE;
      updateRaw();
    });
    ['ghfbExpect', 'ghfbContact'].forEach(function (id) {
      document.getElementById(id).addEventListener('input', updateRaw);
    });

    document.getElementById('ghfbSend').addEventListener('click', submit);

    var file = document.getElementById('ghfbFile');
    file.addEventListener('change', function () {
      var files = Array.prototype.slice.call(file.files || []);
      if (!files.length) return;
      var room = MAX_IMAGES - state.images.length;
      if (room <= 0) { showStatus('warn', '📷 最多 ' + MAX_IMAGES + ' 张截图，先删掉一张再加。', null, 'images'); file.value = ''; return; }
      files = files.slice(0, room);
      showStatus('warn', '🖼️ 正在处理截图…', null, 'images');
      Promise.all(files.map(function (f) {
        return compressImage(f).catch(function (e) { return { error: (e && e.message) || '失败', name: f.name }; });
      })).then(function (results) {
        var bad = [];
        results.forEach(function (r) {
          if (r && r.error) bad.push(r.name || '图片');
          else if (r && r.data) state.images.push(r);
        });
        renderShots();
        updateRaw();
        if (bad.length) showStatus('bad', '😥 这几张没能加上：' + esc(bad.join('、')) + '。换一张试试？', null, 'images');
        else if (state.statusOwner === 'images') hideStatus();
      });
      file.value = '';
    });

    /* 子页面（iframe）上报上下文，或请求顶层代为打开反馈面板 */
    window.addEventListener('message', function (e) {
      var d = e.data;
      if (!d || d.__ghFb !== MSG_NS) return;
      if (d.kind === 'open') { openPanel(); return; }
      if (d.kind !== 'context') return;
      state.childPage = d.page || null;
      state.childEnv = d.env || null;
      updateNote();
      updateRaw();
    });
    var frame = document.getElementById('frame');
    if (frame) {
      frame.addEventListener('load', function () {
        setTimeout(function () {
          try { frame.contentWindow.postMessage({ __ghFb: MSG_NS, kind: 'ping' }, '*'); } catch (e) { /* 跨域忽略 */ }
        }, 120);
      });
    }
    /* 切标签后也主动问一次，确保上下文对得上 */
    window.addEventListener('hashchange', function () {
      state.childPage = null;
      setTimeout(function () {
        var f = document.getElementById('frame');
        if (f) { try { f.contentWindow.postMessage({ __ghFb: MSG_NS, kind: 'ping' }, '*'); } catch (e) { /* 忽略 */ } }
      }, 500);
    });
    document.addEventListener('themechange', function () { updateNote(); updateRaw(); });
  }

  function runTopMode() {
    function boot() {
      if (document.getElementById('ghfbBtn')) return;   /* 防止重复注入 */
      buildDom();
      renderTypes();
      renderSev();
      renderShots();
      syncTypeTexts();
      bind();
      updatePendingBadge();
      loadConfig().then(function () { updateNote(); updateRaw(); });
      showHintOnce();
      /* 页面加载后静默补发历史队列 */
      setTimeout(function () { if (queueCount() > 0) flushQueue(); }, 3500);
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
    else boot();
  }

  /* 对外暴露：页面可主动打开反馈面板，或声明自己的页面名 */
  window.GrowthFeedback = {
    version: WIDGET_VERSION,
    open: function (presetType) {
      if (isFramed()) { try { window.parent.postMessage({ __ghFb: MSG_NS, kind: 'open' }, '*'); } catch (e) { /* 忽略 */ } return; }
      if (presetType) { state.type = presetType; renderTypes(); syncTypeTexts(); }
      openPanel();
    },
    pageContext: pageInfo,
    setConfig: function (cfg) {
      DEFAULT_RELAY_URL = (cfg && cfg.relayUrl) || DEFAULT_RELAY_URL;
      if (cfg) { state.cfg = Object.assign({}, state.cfg || {}, cfg); state.cfgLoaded = true; }
    }
  };

  if (isFramed()) runChildMode();
  else runTopMode();
})();

/* ============================================================
   学科页公共逻辑（语文 / 数学共用一份，不复制两份）——架构 v2 第 3 步

   来源：growth-home/web/subject.html 的页面逻辑原样抽成组件，
   两个学科技能（subject-chinese / subject-math）的 web/index.html 只留
   薄配置 + 加载本组件：

     <script src="/components/homework-section.js"></script>
     <script src="/components/subject-page.js"></script>
     <script>
       SubjectPage.mount({
         subject: 'chinese',
         apiBase: '/api/chinese',       // 技能 API 命名空间（homework 系 + home 聚合口）
         checkinSkill: 'chinese',       // core 统一打卡服务 /api/checkins 的 skill
         fallback: { name: '语文', emoji: '📖', color: '#E8590C' }
       });
     </script>

   与旧版 subject.html 的差异（任务书要求）：
   - fetch /api/home          → <apiBase>/home（技能 api.py 的聚合口，载荷相同）
   - fetch /api/homework 系   → <apiBase>/homework 系（经 HwSection endpoints）
   - 打卡 /api/homework/checkins → /api/checkins（core，skill=checkinSkill）
   页面结构、样式、交互与旧版一致（hero + 作业卡 + 其它学科速链）。
   ============================================================ */
(function () {
  'use strict';

  var CSS = [
    '*{margin:0;padding:0;box-sizing:border-box;-webkit-tap-highlight-color:transparent}',
    'body{font-family:"Yuanti SC","YouYuan","PingFang SC","Microsoft YaHei",sans-serif;background-color:var(--paper,#FFF6E9);background-image:radial-gradient(var(--dot,#FFE0B8) 2.5px,transparent 2.5px);background-size:28px 28px;color:var(--ink,#4A3B2A);padding-bottom:60px;transition:background-color .35s ease,color .35s ease}',
    'ruby{ruby-align:center}',
    'rt{font-size:.5em;color:var(--soft,#B08968);font-weight:normal}',
    '.subj-wrap{max-width:640px;margin:0 auto;padding:0 16px}',
    '.subj-hero{margin:16px 0 18px;background:var(--c,#E8590C);border:4px solid var(--edge,#4A3B2A);border-radius:28px;box-shadow:0 8px 0 var(--edge,#4A3B2A);color:#fff;text-align:center;padding:22px 16px 20px;position:relative;overflow:hidden}',
    '.subj-hero .deco{position:absolute;font-size:24px;opacity:.55}',
    '.subj-hero-emoji{font-size:54px;text-shadow:0 3px 0 rgba(0,0,0,.15)}',
    '.subj-hero h1{font-size:32px;font-weight:900;margin-top:4px;line-height:1.7}',
    '.subj-hero h1 rt{color:rgba(255,255,255,.85)}',
    '.subj-hero .goal{font-size:16px;margin-top:4px;font-weight:700;opacity:.96;line-height:1.8}',
    '.subj-hero .tag{display:inline-block;margin-top:8px;font-size:14px;font-weight:800;background:rgba(255,255,255,.2);border-radius:999px;padding:3px 14px}',
    '.subj-card{background:var(--card,#fff);border:4px solid var(--edge,#4A3B2A);border-radius:24px;box-shadow:0 6px 0 rgba(0,0,0,.18);padding:16px;margin-bottom:16px;transition:background-color .35s ease,border-color .35s ease}',
    '.subj-quick-row{display:flex;gap:10px;flex-wrap:wrap}',
    '.subj-quick-link{flex:1;min-width:132px;display:flex;align-items:center;justify-content:center;gap:6px;font-size:15px;font-weight:900;color:var(--ink,#4A3B2A);text-decoration:none;border:3px solid var(--edge,#4A3B2A);border-radius:16px;padding:11px 8px;background:var(--line,#FFF1DB);box-shadow:0 3px 0 var(--edge,#4A3B2A)}',
    '.subj-quick-link:active{transform:translateY(2px);box-shadow:0 1px 0 var(--edge,#4A3B2A)}',
    '.subj-err{display:none;text-align:center;color:#C92A2A;font-size:17px;line-height:1.9;padding:40px 20px}'
  ];

  // 各科新页面的地址（renderMore 速链用）；没列到的回落到配置里的 s.page
  var PEER_PAGES = {
    chinese: '/chinese/web/index.html',
    math: '/math/web/index.html',
    'class-english': '/class/web/index.html',
    'school-english': '/school/web/index.html'
  };

  var cfg = null;

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function rubyHtml(text) {
    var out = '';
    Array.from(text || '').forEach(function (ch) {
      if (/[\u4e00-\u9fff]/.test(ch)) {
        var py = '';
        try { if (window.pinyinPro) py = pinyinPro.pinyin(ch, { toneType: 'symbol' }); } catch (e) { py = ''; }
        out += py ? '<ruby>' + ch + '<rp>(</rp><rt>' + esc(py) + '</rt><rp>)</rp></ruby>' : ch;
      } else {
        out += esc(ch);
      }
    });
    return out;
  }

  function injectCss() {
    var st = document.createElement('style');
    st.textContent = CSS.join('\n');
    document.head.appendChild(st);
  }

  function buildDom() {
    var wrap = document.createElement('div');
    wrap.className = 'subj-wrap';
    wrap.innerHTML =
      '<div class="subj-err" id="subjErr"></div>' +
      '<div id="subjApp" style="display:none">' +
      '  <header class="subj-hero" id="subjHero">' +
      '    <span class="deco" style="left:12px;top:12px">✨</span>' +
      '    <span class="deco" style="right:14px;bottom:12px">🌟</span>' +
      '    <div class="subj-hero-emoji" id="subjHeroEmoji">📖</div>' +
      '    <h1 id="subjHeroName">语文</h1>' +
      '    <div class="goal" id="subjHeroGoal"></div>' +
      '    <span class="tag" id="subjHeroTag"></span>' +
      '  </header>' +
      '  <div class="subj-card" id="subjHwCard"></div>' +
      '  <div class="subj-card" id="subjMoreCard" style="display:none">' +
      '    <div class="subj-quick-row" id="subjMoreLinks"></div>' +
      '  </div>' +
      '</div>';
    document.body.appendChild(wrap);
  }

  function $(id) { return document.getElementById(id); }

  function renderMore(subjects, curId) {
    var others = (subjects || []).filter(function (s) { return s.id !== curId; });
    if (!others.length) return;
    $('subjMoreCard').style.display = 'block';
    $('subjMoreLinks').innerHTML = others.map(function (s) {
      var href = PEER_PAGES[s.id] || s.page || '#';
      return '<a class="subj-quick-link" href="' + esc(href) + '">' +
        '<span>' + esc(s.emoji || '📚') + '</span><span>' + esc(s.name) + '</span></a>';
    }).join('');
  }

  function init() {
    var err = $('subjErr');
    var apiBase = cfg.apiBase || ('/api/' + cfg.subject);
    fetch(apiBase + '/home', { cache: 'no-store' })
      .then(function (res) { return res.json(); })
      .then(function (data) {
        var childName = (((data || {}).config || {}).childName || '').trim();
        var subjects = ((data || {}).activities || {}).subjects || [];
        var sub = subjects.filter(function (s) { return s.id === cfg.subject; })[0] || cfg.fallback || {};
        var name = sub.name || (cfg.fallback || {}).name || cfg.subject;

        $('subjHero').style.setProperty('--c', sub.color || (cfg.fallback || {}).color || '#E8590C');
        $('subjHeroEmoji').textContent = sub.emoji || (cfg.fallback || {}).emoji || '📖';
        $('subjHeroName').innerHTML = rubyHtml(name) + '作业';
        document.title = (childName ? childName + '的' : '') + name + '作业';
        $('subjHeroGoal').textContent = '今天的' + name + '作业在这里打卡，爸妈也能随时加一项';
        $('subjHeroTag').textContent = childName ? (childName + ' · ' + name) : name;

        HwSection.mount({
          mount: '#subjHwCard',
          subject: cfg.subject,
          subjectName: name,
          emoji: sub.emoji || (cfg.fallback || {}).emoji || '📖',
          color: sub.color || (cfg.fallback || {}).color || '#E8590C',
          date: function () { return HwSection.todayStr(); },
          allowAdd: true,
          importFromBoard: true,
          showLearned: true,
          pageCalendar: true,   // 整页一个「打卡日历 + 点某天看当天全部打卡内容」
          meta: { page: name, subject: cfg.subject },
          // 架构 v2 第 3 步：作业数据走技能命名空间 API，打卡走 core 统一打卡服务
          endpoints: {
            homework: apiBase + '/homework',
            upload: apiBase + '/homework/upload',
            checkins: '/api/checkins',
            board: '/api/data'
          },
          checkinSkill: cfg.checkinSkill || cfg.subject
        });

        renderMore(subjects, cfg.subject);
        $('subjApp').style.display = 'block';
      })
      ['catch'](function () {
        err.style.display = 'block';
        err.textContent = '加载失败：请确认门户服务器已启动（python preview_server.py）。';
      });
  }

  function syncHeroDeco(theme) {
    var ds = document.querySelectorAll('#subjHero .deco');
    if (theme && theme.deco && ds.length) {
      ds.forEach(function (el, i) { el.textContent = theme.deco[i % theme.deco.length]; });
    }
  }

  // 视频点击播放后自动全屏 + 循环播放（孩子看得更清楚，也能反复看）；
  // 已在全屏中不重复请求，失败静默忽略（与旧版 subject.html 相同的全局监听）
  var fullscreenBound = false;
  function bindVideoFullscreen() {
    if (fullscreenBound) return;
    fullscreenBound = true;
    document.addEventListener('play', function (e) {
      var v = e.target;
      if (!v || v.tagName !== 'VIDEO') return;
      v.loop = true;
      if (document.fullscreenElement || document.webkitFullscreenElement) return;
      var req = v.requestFullscreen || v.webkitRequestFullscreen || v.msRequestFullscreen;
      if (req) {
        try { var p = req.call(v); if (p && p.catch) p.catch(function () {}); } catch (err) {}
      } else if (typeof v.webkitEnterFullscreen === 'function') {
        try { v.webkitEnterFullscreen(); } catch (err) {}
      }
    }, true);
  }

  window.SubjectPage = {
    mount: function (options) {
      cfg = options || {};
      if (!cfg.subject) { console.warn('[SubjectPage] 缺少 subject 配置'); return; }
      injectCss();
      buildDom();
      bindVideoFullscreen();
      init();
      if (window.GrowthThemes) {
        syncHeroDeco(GrowthThemes.THEMES[GrowthThemes.current()]);
        document.addEventListener('themechange', function (e) { syncHeroDeco(e.detail); });
      }
    }
  };
})();

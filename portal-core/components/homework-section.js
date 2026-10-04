/* ============================================================
   作业区块（growth-home 专属共享模块）

   把「作业打卡 + 添加/编辑作业」这两件事，从原来的独立页面
   （作业打卡 homework-checkin.html / 作业管理 homework.html）
   搬到各学科页面里：语文、数学、辅导班英语、学校英语各挂一个区块，
   只显示归属该科目的作业。

   位置（架构 v2 第 2 步）：本模块是全仓库学科页共享组件，住在
   portal-core/components/，页面统一用 /components/homework-section.js 引用；
   通用基础库（voice/tts/themes/feedback/pinyin-pro）在 portal-core/vendor/，
   由服务器 /vendor/* 单源供给（sync_vendor.py 已退役，不再有多份副本）。

   用法：
     HwSection.mount({
       mount: '#hwCard',        // 容器（元素或选择器）
       subject: 'chinese',      // 科目 id：chinese / math / class-english / school-english
       subjectName: '语文',      // 科目中文名（取学习看板「今天学了」时按它匹配）
       emoji: '📖',             // 新增作业默认图标
       color: '#E8590C',        // 新增作业默认配色
       date: function () { return todayStr(); },   // 打卡日期（辅导班页跟随日历选中的那天）
       allowAdd: true,          // 显示「＋ 添加作业」与编辑/删除
       importFromBoard: true,   // 显示「今日学习任务」导入清单（从学习看板取）
       showLearned: true,       // 显示「今天学了」
       pageCalendar: true,      // 整页一个打卡日历（页面自己已有日历的传 false，日历只留一个）
       dayDetail: true,         // 「点某天看当天打卡内容」面板（默认跟着 pageCalendar 一起开）
       panelMount: '#dayCard',  // 可选：把上面这两个面板放进页面自己的卡片里（默认在作业卡下面）
       dayChecks: fn(iso),      // 可选：页面自己那套打卡项 [{name, detail, done}]，如英语的听/说/读/写
       dayVoices: fn(iso),      // 可选：页面自己那套录音 [{scope, label}]，按那天双显示出来
       onPickDate: fn(iso),     // 可选：用户在日历里点了某一天（页面可跟着切日期并 refresh()）
       meta: { page: '语文' },   // 语音记录附带的页面信息
       // 架构 v2 第 3 步（可选，不传就是 v1 默认 /api/homework 系）：
       endpoints: { homework: '/api/chinese/homework', upload: '/api/chinese/homework/upload',
                    checkins: '/api/checkins', board: '/api/data' },
       checkinSkill: 'chinese'  // 打卡走 core 统一打卡服务 /api/checkins，记录带该 skill
     });
     HwSection.refresh();       // 页面切日期后重画
     HwSection.setDay('2026-09-23');   // 页面自己切了日期：日历/某天内容跟着走

   打卡记录与「作业管理」页共用同一份（服务器 data/homework_checkins.json 为准，
   本机 localStorage 键 hw_<孩子名> 只作断网缓存），合并规则是逐项逐日按时间戳取新。
   语音记录沿用旧的场景名 homework-<作业id>，所以以前录的音照样能听到。

   四件约定（全站通行的规矩，改这个模块时别破坏）：
   1. 打卡记录一律以服务器为准、跨设备同步（手机、平板、电脑看到的是同一份）。
   2. 作业文字里明确写了「第X页」的，自动把课本那一页的图片附在卡片上，
      孩子点一下就能看（页图来自 textbooks/，页码映射读 /textbooks/index.json）。
   3. 打卡日历整页只留一个，卡片里不再各挂一个「查看打卡日历」；
      页面自己有日历的（辅导班页）就用那一个，模块只出「某天打卡内容」面板。
   4. 点某一天要能列出**那天本科目打卡的所有内容**：页面自己那套打卡项（听/说/读/写…）
      + 作业卡打卡情况（含课本页图、当天录的「说一句」）+ 页面自己那套录音
      + 学情与学习看板任务（语文/数学页）。四个学科页都照这个来，新学科页也一样。
   ============================================================ */
(function () {
  'use strict';

  /* ---------------- 小工具 ---------------- */

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

  function dateStr(d) {
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  }
  function todayStr() { return dateStr(new Date()); }
  function fmtDate(iso) {
    if (!iso) return '';
    var d = new Date(iso + 'T00:00:00');
    return (d.getMonth() + 1) + '月' + d.getDate() + '日';
  }
  function cnDate(iso) {
    if (!iso) return '';
    var d = new Date(iso + 'T00:00:00');
    var wk = ['日', '一', '二', '三', '四', '五', '六'][d.getDay()];
    return (d.getMonth() + 1) + '月' + d.getDate() + '日 周' + wk;
  }
  function daysBetween(a, b) {
    return Math.round((new Date(b + 'T00:00:00') - new Date(a + 'T00:00:00')) / 86400000) + 1;
  }

  // 朗读：优先播放电脑端预生成的配音音频（data/tts/），没有对应音频时降级浏览器朗读
  function speak(text, lang) {
    var lg = lang === 'en' ? 'en' : 'zh';
    if (window.TTS) { TTS.speak(text, lg); return; }
    if (!('speechSynthesis' in window) || !text) return;
    speechSynthesis.cancel();
    setTimeout(function () {
      var u = new SpeechSynthesisUtterance(text);
      u.lang = lg === 'en' ? 'en-US' : 'zh-CN';
      u.rate = 0.9;
      speechSynthesis.speak(u);
    }, 50);
  }

  /* ---------------- 样式（注入一次，全部 hwsec- 前缀，避免和宿主页面撞车） ---------------- */

  var CSS = [
    '.hwsec-sec-head{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin-bottom:8px}',
    '.hwsec-sec-title{font-size:19px;font-weight:900;line-height:1.8}',
    '.hwsec-sec-sub{font-size:13px;font-weight:700;color:var(--soft,#8D7357)}',
    '.hwsec-synctip{margin:0 0 10px;font-size:12px;font-weight:800;color:var(--soft,#8D7357)}',
    '.hwsec-synctip.ok{color:#2B8A3E}',
    '.hwsec-synctip.warn{color:#E8590C}',

    '.hwsec-card{border:4px solid var(--edge,#4A3B2A);border-radius:26px;background:var(--card,#fff);margin-bottom:16px;overflow:hidden;box-shadow:0 7px 0 rgba(0,0,0,.18)}',
    '.hwsec-head{display:flex;align-items:center;gap:12px;padding:13px 15px;background:var(--hc,#845EF7);color:#fff;border-bottom:4px solid var(--edge,#4A3B2A)}',
    '.hwsec-emoji{font-size:34px;flex:none;text-shadow:0 2px 0 rgba(0,0,0,.15)}',
    '.hwsec-title{flex:1;min-width:0}',
    '.hwsec-name{font-size:21px;font-weight:900;line-height:1.7;text-shadow:0 2px 0 rgba(0,0,0,.18)}',
    '.hwsec-name rt{color:rgba(255,255,255,.85)}',
    '.hwsec-valid{font-size:13px;font-weight:800;opacity:.95;line-height:1.5}',
    '.hwsec-badge{flex:none;font-size:13px;font-weight:900;color:#fff;background:rgba(0,0,0,.16);border-radius:999px;padding:6px 12px;white-space:nowrap}',
    '.hwsec-tools{flex:none;display:flex;gap:6px}',
    '.hwsec-tool{border:none;background:rgba(0,0,0,.14);color:#fff;font-size:17px;width:36px;height:36px;border-radius:50%;cursor:pointer}',

    '.hwsec-body{padding:14px 15px}',
    '.hwsec-desc{font-size:15px;line-height:1.8;color:var(--ink,#4A3B2A);margin-bottom:10px}',
    '.hwsec-teacher{font-size:14px;line-height:1.7;color:#B0570F;background:#FFF3D6;border-radius:12px;padding:9px 12px;margin-bottom:12px}',

    '.hwsec-media-grid{display:flex;flex-direction:column;gap:10px;margin-bottom:6px}',
    '.hwsec-media{border:3px solid var(--edge,#4A3B2A);border-radius:16px;overflow:hidden;background:var(--line,#FFF9DB)}',
    '.hwsec-media video{display:block;width:100%;max-height:260px;background:#000}',
    '.hwsec-media img{display:block;width:100%;max-height:260px;object-fit:contain;cursor:zoom-in;background:var(--line,#FFF9DB)}',
    '.hwsec-media .hwsec-media-label{font-size:13px;font-weight:800;color:var(--soft,#8D7357);padding:7px 10px;background:var(--card,#fff)}',
    '.hwsec-media.pdf{display:flex;align-items:center;gap:12px;padding:13px 15px;background:#FFF3D6;text-decoration:none}',
    '.hwsec-media.pdf .hwsec-pdf-ico{font-size:27px;flex:none}',
    '.hwsec-media.pdf .hwsec-pdf-txt{flex:1;font-size:16px;font-weight:900;color:var(--ink,#4A3B2A);line-height:1.6}',
    '.hwsec-media.pdf .hwsec-pdf-sub{font-size:13px;font-weight:700;color:var(--soft,#8D7357)}',
    '.hwsec-media.pdf .hwsec-pdf-dl{flex:none;font-size:14px;font-weight:900;color:#fff;background:#E8590C;border-radius:12px;padding:8px 13px}',

    '.hwsec-progress{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;margin-top:12px}',
    '.hwsec-stat{font-size:17px;font-weight:900;color:var(--acc-deep,#E8590C)}',
    '.hwsec-dots{display:flex;gap:7px}',
    '.hwsec-dot{display:flex;flex-direction:column;align-items:center;gap:3px;font-size:12px;color:var(--soft,#8D7357)}',
    '.hwsec-dot i{width:19px;height:19px;border-radius:50%;display:block;border:2.5px solid var(--edge,#4A3B2A);background:var(--line,#FFF1DB)}',
    '.hwsec-dot.ok i{background:#51CF66}',
    '.hwsec-dot.today{font-weight:900;color:var(--ink,#4A3B2A)}',

    '.hwsec-check-row{margin-top:14px;text-align:center}',
    '.hwsec-check-btn{width:172px;height:82px;border-radius:22px;border:4px solid var(--edge,#4A3B2A);background:var(--hc,#845EF7);color:#fff;font-family:inherit;font-size:21px;font-weight:900;cursor:pointer;box-shadow:0 6px 0 var(--edge,#4A3B2A);transition:transform .12s ease,box-shadow .12s ease,background .2s;text-shadow:0 2px 0 rgba(0,0,0,.15)}',
    '.hwsec-check-btn:active{transform:translateY(4px);box-shadow:0 2px 0 var(--edge,#4A3B2A)}',
    '.hwsec-check-btn.done{background:#69DB7C}',
    // 课本页图片（作业里写了「第X页」时附上，点一下就能看那一页）
    '.hwsec-pages{margin:0 0 10px;background:var(--line,#FFF9DB);border:3px dashed var(--edge,#4A3B2A);border-radius:16px;padding:10px 12px}',
    '.hwsec-pages-title{font-size:15px;font-weight:900;line-height:1.7}',
    '.hwsec-pages-hint{font-size:12px;font-weight:800;color:var(--soft,#8D7357);line-height:1.6;margin-top:2px}',
    '.hwsec-pages-strip{display:flex;gap:10px;overflow-x:auto;padding:8px 2px 2px;-webkit-overflow-scrolling:touch}',
    '.hwsec-page{flex:none;width:96px;padding:0;border:none;background:none;font-family:inherit;cursor:zoom-in;text-align:center}',
    '.hwsec-page img{display:block;width:96px;height:126px;object-fit:contain;border:2.5px solid var(--edge,#4A3B2A);border-radius:10px;background:#fff}',
    '.hwsec-page .hwsec-page-cap{display:block;font-size:12px;font-weight:800;color:var(--soft,#8D7357);margin-top:4px}',

    // 整页一个的打卡日历 + 某天打卡内容
    '.hwsec-panel{margin-top:16px;padding-top:14px;border-top:3px dashed var(--line,#FFE3B3)}',
    '.hwsec-panel.host{margin-top:0;padding-top:0;border-top:none}',
    '.hwsec-cal-head{display:flex;align-items:center;justify-content:space-between;gap:8px}',
    '.hwsec-cal-title{font-size:19px;font-weight:900;line-height:1.7}',
    '.hwsec-cal-nav{flex:none;display:flex;gap:6px}',
    '.hwsec-cal-nav button{font-family:inherit;font-size:15px;font-weight:900;color:var(--ink,#4A3B2A);border:3px solid var(--edge,#4A3B2A);border-radius:12px;background:var(--line,#FFF1DB);padding:6px 11px;cursor:pointer;box-shadow:0 3px 0 var(--edge,#4A3B2A)}',
    '.hwsec-cal-nav button:active{transform:translateY(2px);box-shadow:0 1px 0 var(--edge,#4A3B2A)}',
    '.hwsec-cal-sum{font-size:13px;font-weight:800;color:var(--soft,#8D7357);line-height:1.9;margin-top:4px}',
    '.hwsec-cal-grid{display:grid;grid-template-columns:repeat(7,1fr);gap:4px;margin-top:10px}',
    '.hwsec-cal-wk{text-align:center;font-size:12px;font-weight:800;color:var(--soft,#8D7357);padding:2px 0}',
    '.hwsec-cal-day{font-family:inherit;color:var(--ink,#4A3B2A);cursor:pointer;border:2.5px solid var(--line,#FFE3B3);border-radius:12px;background:var(--card,#FFFDF7);min-height:46px;padding:4px 2px 3px;display:flex;flex-direction:column;align-items:center;gap:2px;transition:transform .12s ease,background .2s}',
    '.hwsec-cal-day:active{transform:scale(.96)}',
    '.hwsec-cal-day.out{background:transparent;border-color:transparent;color:#CFC0A8;cursor:default}',
    '.hwsec-cal-day.has{background:#FFF9DB}',
    '.hwsec-cal-day.today{border-color:#4DABF7;border-width:3px}',
    '.hwsec-cal-day.sel{border-color:var(--edge,#4A3B2A);border-width:3px;background:#FFE8C7}',
    '.hwsec-cal-day .d-num{font-size:15px;font-weight:900;line-height:1.3}',
    '.hwsec-cal-day .d-marks{display:flex;align-items:center;gap:3px;min-height:11px}',
    '.hwsec-cdot{width:9px;height:9px;border-radius:50%;display:inline-block;border:1.5px solid var(--edge,#4A3B2A)}',
    '.hwsec-cdot.ok{background:#51CF66}',
    '.hwsec-dcnt{font-size:10px;font-weight:900;color:#E8590C;line-height:1}',
    '.hwsec-cal-legend{display:flex;gap:14px;align-items:center;flex-wrap:wrap;font-size:12px;font-weight:800;color:var(--soft,#8D7357);margin-top:10px}',

    '.hwsec-day-head{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:10px}',
    '.hwsec-day-title{font-size:18px;font-weight:900;line-height:1.7}',
    '.hwsec-day-tag{flex:none;font-size:12px;font-weight:800;color:#fff;background:#4DABF7;border-radius:999px;padding:4px 10px}',
    '.hwsec-dsec{border-top:2.5px dashed var(--line,#FFF1DB);padding-top:10px;margin-top:10px}',
    '.hwsec-dsec.first{border-top:none;padding-top:0;margin-top:0}',
    '.hwsec-dsec .hwsec-dsec-title{font-size:16px;font-weight:900;line-height:1.7;margin-bottom:8px}',
    '.hwsec-hw-row{border:3px solid var(--edge,#4A3B2A);border-radius:16px;padding:10px 12px;margin-bottom:10px;background:var(--card,#FFFDF7)}',
    '.hwsec-hw-row .r-top{display:flex;align-items:center;gap:8px;flex-wrap:wrap}',
    '.hwsec-hw-row .r-name{flex:1;min-width:120px;font-size:16px;font-weight:800;line-height:1.6}',
    '.hwsec-hw-row .r-ok{flex:none;font-size:13px;font-weight:900;color:#2B8A3E}',
    '.hwsec-hw-row .r-no{flex:none;font-size:13px;font-weight:900;color:var(--soft,#8D7357)}',
    '.hwsec-hw-row .r-detail{font-size:13px;font-weight:700;color:var(--soft,#8D7357);line-height:1.8;margin-top:4px}',
    '.hwsec-dnote{font-size:15px;background:var(--line,#FFF9DB);border-radius:12px;padding:9px 11px;line-height:1.9;margin-bottom:6px;word-break:break-word}',
    '.hwsec-vwrap{margin-top:8px}',
    '.hwsec-none{font-size:14px;font-weight:700;color:var(--soft,#8D7357);line-height:1.9}',

    '.hwsec-voice{margin-top:14px;padding-top:12px;border-top:3px dashed var(--line,#FFE3B3)}',
    '.hwsec-voice-title{font-size:15px;font-weight:900;color:var(--ink,#4A3B2A);margin-bottom:8px}',

    '.hwsec-inactive .hwsec-head{background:var(--soft,#B08968)}',
    '.hwsec-inactive .hwsec-body{opacity:.7}',
    '.hwsec-fold{display:none;width:100%;margin:0 0 14px;font-family:inherit;font-size:16px;font-weight:900;color:var(--ink,#4A3B2A);background:var(--line,#FFF1DB);border:3px solid var(--edge,#4A3B2A);border-radius:14px;padding:11px 14px;cursor:pointer;box-shadow:0 3px 0 var(--edge,#4A3B2A)}',
    '.hwsec-fold:active{transform:translateY(2px);box-shadow:0 1px 0 var(--edge,#4A3B2A)}',
    '.hwsec-empty{text-align:center;color:var(--soft,#8D7357);font-size:15px;padding:14px 0;line-height:1.9}',

    '.hwsec-sub-card{border:3px dashed var(--edge,#4A3B2A);border-radius:18px;padding:12px 14px;background:var(--line,#FFF9DB);margin:0 0 14px}',
    '.hwsec-sub-title{font-size:16px;font-weight:900;line-height:1.7;margin-bottom:8px}',
    '.hwsec-sub-note{font-size:14px;line-height:1.8;color:var(--ink,#4A3B2A)}',
    '.hwsec-sub-imgs{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}',
    '.hwsec-sub-imgs img{width:88px;height:112px;object-fit:cover;border:2.5px solid var(--edge,#4A3B2A);border-radius:10px;cursor:zoom-in;background:#fff}',

    '.hwsec-learn-item{display:flex;align-items:center;gap:10px;border:3px solid var(--edge,#4A3B2A);border-radius:16px;padding:10px 12px;margin-bottom:10px;background:var(--card,#FFFDF7)}',
    '.hwsec-learn-item:last-child{margin-bottom:0}',
    '.hwsec-learn-day{flex:none;font-size:12px;font-weight:800;color:#fff;background:#845EF7;border-radius:999px;padding:4px 9px;white-space:nowrap}',
    '.hwsec-learn-body{flex:1;min-width:0}',
    '.hwsec-learn-name{font-size:16px;font-weight:800;line-height:1.6}',
    '.hwsec-learn-detail{font-size:13px;color:var(--soft,#8D7357);font-weight:700;line-height:1.5}',
    '.hwsec-learn-add{flex:none;font-family:inherit;font-size:14px;font-weight:900;border:3px solid var(--edge,#4A3B2A);border-radius:14px;padding:8px 12px;cursor:pointer;box-shadow:0 3px 0 var(--edge,#4A3B2A);background:#69DB7C;color:#2B8A3E;white-space:nowrap}',
    '.hwsec-learn-add:active{transform:translateY(2px);box-shadow:0 1px 0 var(--edge,#4A3B2A)}',
    '.hwsec-learn-add.added{background:var(--line,#FFF1DB);color:var(--soft,#8D7357)}',

    '.hwsec-add-btn{display:block;width:100%;margin:2px 0 16px;font-family:inherit;font-size:17px;font-weight:900;color:#fff;background:#845EF7;border:4px solid var(--edge,#4A3B2A);border-radius:18px;padding:13px;cursor:pointer;box-shadow:0 5px 0 var(--edge,#4A3B2A)}',
    '.hwsec-add-btn:active{transform:translateY(3px);box-shadow:0 2px 0 var(--edge,#4A3B2A)}',

    '.hwsec-overlay{position:fixed;inset:0;z-index:70;background:rgba(0,0,0,.4);display:flex;align-items:flex-end;justify-content:center;padding:12px}',
    '.hwsec-overlay.hidden{display:none}',
    '.hwsec-sheet{width:min(100%,520px);max-height:92vh;overflow-y:auto;background:var(--card,#fff);border:4px solid var(--edge,#4A3B2A);border-radius:26px;box-shadow:0 10px 0 rgba(0,0,0,.25);padding:18px 18px 22px;animation:hwsecPop .25s cubic-bezier(.34,1.56,.64,1)}',
    '@keyframes hwsecPop{from{transform:translateY(30px);opacity:0}to{transform:translateY(0);opacity:1}}',
    '.hwsec-sheet h3{text-align:center;font-size:20px;margin-bottom:16px}',
    '.hwsec-field{margin-bottom:14px}',
    '.hwsec-field label{display:block;font-size:16px;font-weight:800;margin-bottom:6px;line-height:1.7}',
    '.hwsec-field input[type=text],.hwsec-field input[type=date],.hwsec-field textarea{width:100%;font-size:17px;font-family:inherit;color:var(--ink,#4A3B2A);border:3px solid var(--edge,#4A3B2A);border-radius:14px;padding:11px 13px;background:var(--card,#FFFDF7);box-sizing:border-box}',
    '.hwsec-field textarea{min-height:70px;resize:vertical}',
    '.hwsec-date-row{display:flex;gap:10px;align-items:center}',
    '.hwsec-date-row .hwsec-sep{font-size:16px;font-weight:900;color:var(--soft,#8D7357)}',
    '.hwsec-quick-row{display:flex;gap:8px;margin-top:8px}',
    '.hwsec-quick{flex:1;font-family:inherit;font-size:14px;font-weight:900;color:var(--ink,#4A3B2A);border:3px solid var(--edge,#4A3B2A);border-radius:12px;padding:8px 4px;cursor:pointer;background:var(--line,#FFF1DB)}',
    '.hwsec-quick.on{background:#FFD43B}',
    '.hwsec-file-row{display:flex;align-items:center;gap:10px;flex-wrap:wrap}',
    '.hwsec-file-btn{font-family:inherit;font-size:15px;font-weight:900;border:3px solid var(--edge,#4A3B2A);border-radius:14px;padding:10px 14px;cursor:pointer;background:#4DABF7;color:#fff;box-shadow:0 3px 0 var(--edge,#4A3B2A)}',
    '.hwsec-file-btn:active{transform:translateY(2px);box-shadow:0 1px 0 var(--edge,#4A3B2A)}',
    '.hwsec-uploading{font-size:14px;font-weight:800;color:var(--soft,#8D7357)}',
    '.hwsec-att-list{margin-top:8px;display:flex;flex-direction:column;gap:6px}',
    '.hwsec-att-item{display:flex;align-items:center;gap:8px;font-size:14px;font-weight:700}',
    '.hwsec-att-item .hwsec-att-del{border:none;background:none;font-size:18px;cursor:pointer}',
    '.hwsec-actions{display:flex;gap:10px;margin-top:18px}',
    '.hwsec-btn{flex:1;font-family:inherit;font-size:18px;font-weight:900;border:3.5px solid var(--edge,#4A3B2A);border-radius:16px;padding:13px;cursor:pointer;box-shadow:0 4px 0 var(--edge,#4A3B2A)}',
    '.hwsec-btn:active{transform:translateY(3px);box-shadow:0 1px 0 var(--edge,#4A3B2A)}',
    '.hwsec-btn.primary{background:#845EF7;color:#fff}',
    '.hwsec-btn.ghost{background:var(--line,#FFF1DB);color:var(--ink,#4A3B2A)}',

    '.hwsec-lightbox{position:fixed;inset:0;z-index:95;background:rgba(0,0,0,.85);display:flex;align-items:center;justify-content:center;padding:20px;cursor:zoom-out}',
    '.hwsec-lightbox.hidden{display:none}',
    '.hwsec-lightbox img{max-width:100%;max-height:92vh;border-radius:10px}',

    '.hwsec-celebrate{position:fixed;inset:0;z-index:99;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:16px;background:rgba(255,246,233,.94)}',
    '.hwsec-celebrate.hidden{display:none}',
    '.hwsec-cel-emoji{font-size:92px;animation:hwsecBounce .65s infinite alternate}',
    '.hwsec-cel-msg{font-size:30px;font-weight:900;color:var(--acc-deep,#E8590C);text-align:center;line-height:1.8;padding:0 20px}',
    '@keyframes hwsecBounce{from{transform:translateY(0) scale(1)}to{transform:translateY(-22px) scale(1.1)}}'
  ].join('\n');

  function injectCss() {
    if (document.getElementById('hwsecStyle')) return;
    var st = document.createElement('style');
    st.id = 'hwsecStyle';
    st.textContent = CSS;
    document.head.appendChild(st);
  }

  /* ---------------- 打卡记录：跨设备同步 ---------------- */
  // 记录格式：{ 作业id: { "YYYY-MM-DD": { v: 0|1, ts: 毫秒 } } }
  //   v=1 已打卡、v=0 取消打卡（留着「取消」这条记录，取消动作才能同步到别的设备）
  //   升级到跨设备同步之前的旧格式（{ 日期: 1 }）当作没有时间戳处理。
  var records = {};
  var syncing = false;
  var pendingPush = false;   // 同步过程中收到的改动，等这轮结束再补推
  var pushTimer = null;
  var pullTimer = null;
  var childName = 'child';

  /* ---------------- API 端点（架构 v2 第 3 步：可按技能覆盖，默认与 v1 逐字节一致） ----------------
     旧页面不传 endpoints / checkinSkill，走的就是原来的 /api/homework 系与
     /api/homework/checkins；新技能页（subject-chinese 等）通过 mount 配置改走
     /api/<技能url>/homework 系 + core 统一打卡服务 /api/checkins。 */
  var DEFAULT_ENDPOINTS = {
    homework: '/api/homework',
    upload: '/api/homework/upload',
    checkins: '/api/homework/checkins',
    board: '/api/data'
  };
  var EP = DEFAULT_ENDPOINTS;
  var CHECKIN_SKILL = '';   // 非空时打卡走 /api/checkins（core），记录带 skill 命名空间

  // core 打卡服务的记录是 [{skill, key, date, v, ts}] 列表；模块内部仍用
  // { key: { date: {v, ts} } } 地图，进出时互相转换。
  function listToRecords(list) {
    var out = {};
    (list || []).forEach(function (r) {
      if (!r || !r.key || !r.date) return;
      if (!out[r.key]) out[r.key] = {};
      out[r.key][r.date] = { v: r.v ? 1 : 0, ts: Number(r.ts) || 0 };
    });
    return out;
  }
  function recordsToList(recs) {
    var out = [];
    Object.keys(recs || {}).forEach(function (id) {
      Object.keys(recs[id] || {}).forEach(function (d) {
        var m = recs[id][d];
        if (!m) return;
        out.push({ skill: CHECKIN_SKILL, key: id, date: d, v: m.v ? 1 : 0, ts: Number(m.ts) || 0 });
      });
    });
    return out;
  }
  function checkinsGetUrl() {
    return EP.checkins + (CHECKIN_SKILL ? '?skill=' + encodeURIComponent(CHECKIN_SKILL) : '');
  }

  // core 模式下本机缓存按 skill 分键：语文/数学两页共用一台设备时互不覆盖
  function storeKey() { return 'hw_' + (childName || 'child') + (CHECKIN_SKILL ? '_' + CHECKIN_SKILL : ''); }

  function normMark(m) {
    if (m && typeof m === 'object') return { v: m.v ? 1 : 0, ts: Number(m.ts) || 0 };
    return m ? { v: 1, ts: 0 } : null;
  }
  function normRecords(raw) {
    var out = {};
    Object.keys(raw || {}).forEach(function (id) {
      var days = raw[id];
      if (!days || typeof days !== 'object') return;
      var o = {};
      Object.keys(days).forEach(function (d) { var m = normMark(days[d]); if (m) o[d] = m; });
      if (Object.keys(o).length) out[id] = o;
    });
    return out;
  }
  function loadLocal() {
    try { records = normRecords(JSON.parse(localStorage.getItem(storeKey()) || '{}')); } catch (e) { records = {}; }
  }
  function saveLocal() {
    try { localStorage.setItem(storeKey(), JSON.stringify(records)); } catch (e) { /* 隐私模式等，忽略 */ }
  }
  function isChecked(itemId, date) {
    var m = records[itemId] && records[itemId][date];
    return !!(m && m.v);
  }
  function setChecked(itemId, date, val) {
    if (!records[itemId]) records[itemId] = {};
    records[itemId][date] = { v: val ? 1 : 0, ts: Date.now() };
    saveLocal();
    schedulePush(300);
  }
  function mergeStamped(localMap, remoteMap) {
    var out = {};
    var ids = Object.keys(localMap || {}).concat(Object.keys(remoteMap || {})).filter(function (x, i, a) { return a.indexOf(x) === i; });
    ids.forEach(function (id) {
      var ld = (localMap || {})[id] || {};
      var rd = (remoteMap || {})[id] || {};
      var days = {};
      Object.keys(ld).concat(Object.keys(rd)).filter(function (x, i, a) { return a.indexOf(x) === i; }).forEach(function (d) {
        var lv = normMark(ld[d]), rv = normMark(rd[d]);
        var pick = null;
        if (!lv) pick = rv;
        else if (!rv) pick = lv;
        else if (!lv.ts && !rv.ts) pick = { v: (lv.v || rv.v) ? 1 : 0, ts: 0 };
        else if (rv.ts > lv.ts) pick = rv;
        else if (rv.ts < lv.ts) pick = lv;
        else pick = { v: (lv.v || rv.v) ? 1 : 0, ts: lv.ts };
        if (pick) days[d] = pick;
      });
      if (Object.keys(days).length) out[id] = days;
    });
    return out;
  }
  function sigOf(recs) {
    return JSON.stringify(Object.keys(recs || {}).sort().map(function (id) {
      return [id, Object.keys(recs[id]).sort().map(function (d) {
        return [d, (recs[id][d] || {}).v ? 1 : 0, (recs[id][d] || {}).ts || 0];
      })];
    }));
  }

  var lastSyncState = 'syncing';
  function setSyncTip(state) {
    lastSyncState = state;
    paintSyncTip();
  }
  // 首屏渲染之前 syncNow 就已经跑完，那时提示条还没进 DOM；
  // 所以把最近一次状态记下来，渲染完再补画一遍，别让提示条空着。
  function paintSyncTip() {
    Array.prototype.forEach.call(document.querySelectorAll('.hwsec-synctip'), function (el) {
      if (lastSyncState === 'syncing') { el.className = 'hwsec-synctip'; el.textContent = '⏳ 正在同步…'; }
      else if (lastSyncState === 'ok') { el.className = 'hwsec-synctip ok'; el.textContent = '☁️ 已同步（换台设备打开也是这份数据）'; }
      else { el.className = 'hwsec-synctip warn'; el.textContent = '⚠️ 暂时连不上服务器，先存在本机，联网后自动补上'; }
    });
  }

  function adoptRemote(data, allowRender) {
    if (!data || !data.ok) return false;
    var before = sigOf(records);
    records = mergeStamped(records, normRecords(data.records || {}));
    saveLocal();
    if (before === sigOf(records)) return false;
    if (allowRender) renderAll();
    return true;
  }

  function pushState() {
    if (syncing) { pendingPush = true; return; }
    syncing = true;
    pendingPush = false;
    setSyncTip('syncing');
    fetch(EP.checkins, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: CHECKIN_SKILL ? JSON.stringify({ records: recordsToList(records) })
                          : JSON.stringify({ records: records })
    }).then(function (res) {
      if (!res.ok) throw new Error('http ' + res.status);
      return res.json();
    }).then(function (data) {
      if (CHECKIN_SKILL) data = { ok: data && data.ok, records: listToRecords(data && data.records) };
      adoptRemote(data, false);
      setSyncTip('ok');
    })['catch'](function () {
      setSyncTip('offline');
    })['then'](function () {
      syncing = false;
      if (pendingPush) { pendingPush = false; schedulePush(120); }
    });
  }

  function schedulePush(delay) {
    if (pushTimer) clearTimeout(pushTimer);
    pushTimer = setTimeout(function () { pushTimer = null; pushState(); }, delay || 300);
  }

  function syncNow(allowRender) {
    if (syncing) return Promise.resolve(false);
    syncing = true;
    return fetch(checkinsGetUrl(), { cache: 'no-store' })
      .then(function (res) { if (!res.ok) throw new Error('http ' + res.status); return res.json(); })
      .then(function (data) {
        var remoteMap = CHECKIN_SKILL ? listToRecords((data || {}).records) : ((data || {}).records || {});
        var changed = adoptRemote(CHECKIN_SKILL ? { ok: (data || {}).ok, records: remoteMap } : data, allowRender);
        syncing = false;
        setSyncTip('ok');
        if (sigOf(records) !== sigOf(normRecords(remoteMap))) pushState();
        return changed;
      })['catch'](function () {
        syncing = false;
        setSyncTip('offline');
        return false;
      });
  }

  function startSyncLoop() {
    if (pullTimer) clearInterval(pullTimer);
    pullTimer = setInterval(function () { if (!document.hidden) syncNow(true); }, 12000);
    document.addEventListener('visibilitychange', function () { if (!document.hidden) syncNow(true); });
    window.addEventListener('focus', function () { syncNow(true); });
    window.addEventListener('online', function () { syncNow(true); });
  }

  /* ---------------- 科目识别（从学习看板取任务时用） ---------------- */
  // 学习看板的习惯项 id 一直带科目线索（如 2026-09-23-yuwen-read / -math-fenhe），
  // 能认出来就归到对应科目；认不出来的不强行归类（它仍留在「作业管理」页里）。
  function guessSubjectFromText(s) {
    var t = String(s || '').toLowerCase();
    if (/(^|[-_ ])(yuwen|chinese)([-_ ]|$)|语文/.test(t)) return 'chinese';
    if (/(^|[-_ ])(math|shuxue)([-_ ]|$)|数学/.test(t)) return 'math';
    if (/(^|[-_ ])(english|yingyu)([-_ ]|$)|英语/.test(t)) return 'english';
    return '';
  }

  /* ---------------- 课本页图片：作业里写了「第X页」就附图 ----------------
     页图由工作区 textbooks/ 目录静态托管（门户服务器把 /textbooks/* 映射到那儿），
     文件名用的是「PDF 页序号」，而作业里写的是「印刷页码」，两者差一个 offset，
     offset 从 /textbooks/index.json 读（语文/数学都是 5），所以这里只按印刷页码算，
     不去猜、不硬编码。拿不到 index.json（比如单文件版）时整块不显示，不影响打卡。 */
  var textbooks = null;
  var textbooksTried = false;

  function loadTextbooks() {
    if (textbooksTried) return Promise.resolve(textbooks);
    textbooksTried = true;
    return fetch('/textbooks/index.json', { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { textbooks = (d && d.books) ? d : null; return textbooks; })
      ['catch'](function () { textbooks = null; return null; });
  }

  function currentBook() {
    if (!textbooks) return null;
    var cfg = state.cfg || {};
    return textbooks.books[cfg.subjectName || ''] || textbooks.books[cfg.subject || ''] || null;
  }

  // 从文字里挑出「第20、21、22、23页」「第20～23页」「课本第15页」这类页码。
  // 只认「页」字前面的数字，所以「第27页做一做第1题」只会取到 27，不会把题号当页码。
  function parsePageNums(text) {
    var t = String(text || '');
    var out = [];
    var m;
    function add(v) { if (v > 0 && v < 1000 && out.indexOf(v) < 0) out.push(v); }
    var rangeRe = /第?\s*(\d{1,3})\s*[~～\-—至]\s*(\d{1,3})\s*页/g;
    while ((m = rangeRe.exec(t))) {
      var a = parseInt(m[1], 10), b = parseInt(m[2], 10);
      if (b >= a && b - a <= 30) { for (var i = a; i <= b; i++) add(i); }
      else { add(a); add(b); }
    }
    var listRe = /第?\s*(\d{1,3}(?:\s*[、,，和及]\s*\d{1,3})+)\s*页/g;
    while ((m = listRe.exec(t))) {
      m[1].split(/[、,，和及]/).forEach(function (n) { add(parseInt(n, 10)); });
    }
    var oneRe = /第?\s*(\d{1,3})\s*页/g;
    while ((m = oneRe.exec(t))) add(parseInt(m[1], 10));
    out.sort(function (x, y) { return x - y; });
    return out;
  }

  function pageImages(item) {
    var book = currentBook();
    if (!book || !item) return [];
    var offset = parseInt(book.offset, 10) || 0;
    var dir = book.pages_dir || '';
    var total = parseInt(book.pdf_pages, 10) || 0;
    if (!dir) return [];
    var txt = [item.name, item.desc, item.teacherNote].join(' ');
    return parsePageNums(txt).map(function (p) {
      return { page: p, pdf: p + offset };
    }).filter(function (o) {
      return o.pdf > 0 && (!total || o.pdf <= total);
    }).slice(0, 10).map(function (o) {
      var n = String(o.pdf);
      while (n.length < 3) n = '0' + n;
      return { page: o.page, url: '/textbooks/' + dir + '/p' + n + '.jpg' };
    });
  }

  function pagesHtml(item) {
    var pages = pageImages(item);
    if (!pages.length) return '';
    var nums = pages.map(function (p) { return p.page; }).join('、');
    return '<div class="hwsec-pages">' +
      '<div class="hwsec-pages-title">📖 课本第' + esc(nums) + '页</div>' +
      '<div class="hwsec-pages-hint">点一下图片就能看课本这一页（放大后点一下关掉）</div>' +
      '<div class="hwsec-pages-strip">' + pages.map(function (p) {
        return '<button class="hwsec-page" type="button" data-hwimg="' + esc(p.url) + '">' +
          '<img src="' + esc(p.url) + '" alt="课本第' + p.page + '页" loading="lazy">' +
          '<span class="hwsec-page-cap">第' + p.page + '页</span></button>';
      }).join('') + '</div></div>';
  }

  // 学习看板「这天学了」里带的课本页图（url 已经写全，直接用）
  function imgsStripHtml(urls, title) {
    var list = (urls || []).filter(function (u, i, a) { return u && a.indexOf(u) === i; }).slice(0, 8);
    if (!list.length) return '';
    return '<div class="hwsec-pages-hint" style="margin-top:6px">点图看课本那一页</div>' +
      '<div class="hwsec-pages-strip">' + list.map(function (u) {
        return '<button class="hwsec-page" type="button" data-hwimg="' + esc(u) + '">' +
          '<img src="' + esc(u) + '" alt="' + esc(title || '课本页') + '" loading="lazy"></button>';
      }).join('') + '</div>';
  }

  function collectImgs(items) {
    var out = [];
    (items || []).forEach(function (l) {
      (l.images || []).forEach(function (u) { if (u && out.indexOf(u) < 0) out.push(u); });
    });
    return out;
  }

  function bindPageImgs(el) {
    if (!el) return;
    Array.prototype.forEach.call(el.querySelectorAll('[data-hwimg]'), function (node) {
      node.addEventListener('click', function () { showLightbox(node.getAttribute('data-hwimg')); });
    });
  }

  /* ---------------- 弹层 / 灯箱 / 庆祝动画（全页只造一次） ---------------- */

  function ensureShell() {
    injectCss();
    if (!document.getElementById('hwsecOverlay')) {
      var ov = document.createElement('div');
      ov.className = 'hwsec-overlay hidden';
      ov.id = 'hwsecOverlay';
      ov.innerHTML =
        '<div class="hwsec-sheet">' +
        '<h3 id="hwsecSheetTitle">➕ 添加作业</h3>' +
        '<div class="hwsec-field"><label>作业名称</label>' +
        '<input type="text" id="hwsecFName" maxlength="20" placeholder="例如：写单韵母"></div>' +
        '<div class="hwsec-field"><label>说明（老师的话）</label>' +
        '<textarea id="hwsecFDesc" maxlength="200" placeholder="写一点要求或提醒…"></textarea></div>' +
        '<div class="hwsec-field"><label>有效期（这段时间每天打卡）</label>' +
        '<div class="hwsec-date-row"><input type="date" id="hwsecFStart"><span class="hwsec-sep">到</span>' +
        '<input type="date" id="hwsecFEnd"></div>' +
        '<div class="hwsec-quick-row">' +
        '<button class="hwsec-quick" data-days="0" type="button">今天</button>' +
        '<button class="hwsec-quick" data-days="7" type="button">一周</button>' +
        '<button class="hwsec-quick" data-days="30" type="button">一个月</button>' +
        '</div></div>' +
        '<div class="hwsec-field"><label>图片 / 视频</label>' +
        '<div class="hwsec-file-row"><button class="hwsec-file-btn" id="hwsecFPick" type="button">📎 选择文件</button>' +
        '<span class="hwsec-uploading" id="hwsecFUploading"></span></div>' +
        '<input type="file" id="hwsecFFile" accept="image/*,video/*" multiple style="display:none">' +
        '<div class="hwsec-att-list" id="hwsecFAtts"></div></div>' +
        '<div class="hwsec-actions">' +
        '<button class="hwsec-btn ghost" id="hwsecFCancel" type="button">取消</button>' +
        '<button class="hwsec-btn primary" id="hwsecFSave" type="button">保存作业</button>' +
        '</div></div>';
      document.body.appendChild(ov);
      bindSheet();
    }
    if (!document.getElementById('hwsecLightbox')) {
      var lb = document.createElement('div');
      lb.className = 'hwsec-lightbox hidden';
      lb.id = 'hwsecLightbox';
      lb.innerHTML = '<img id="hwsecLightboxImg" alt="预览">';
      document.body.appendChild(lb);
      lb.addEventListener('click', function () { lb.classList.add('hidden'); });
    }
    if (!document.getElementById('hwsecCelebrate')) {
      var cl = document.createElement('div');
      cl.className = 'hwsec-celebrate hidden';
      cl.id = 'hwsecCelebrate';
      cl.innerHTML = '<div class="hwsec-cel-emoji" id="hwsecCelEmoji">🎉</div><div class="hwsec-cel-msg" id="hwsecCelMsg"></div>';
      document.body.appendChild(cl);
      cl.addEventListener('click', function () { cl.classList.add('hidden'); });
    }
  }

  function showLightbox(url) {
    var img = document.getElementById('hwsecLightboxImg');
    if (!img) return;
    img.src = url;
    document.getElementById('hwsecLightbox').classList.remove('hidden');
  }

  function showCelebration(emoji, msg) {
    var box = document.getElementById('hwsecCelebrate');
    if (!box) return;
    document.getElementById('hwsecCelEmoji').textContent = emoji;
    document.getElementById('hwsecCelMsg').innerHTML = rubyHtml(msg);
    box.classList.remove('hidden');
    speak(msg, 'zh');
    setTimeout(function () { box.classList.add('hidden'); }, 2600);
  }

  /* ---------------- 添加 / 编辑弹层 ---------------- */
  var pendingAtts = [];
  var editingId = null;

  function setQuick(days) {
    Array.prototype.forEach.call(document.querySelectorAll('.hwsec-quick'), function (q) {
      q.classList.toggle('on', parseInt(q.getAttribute('data-days'), 10) === days);
    });
    if (days < 0) return;
    var s = document.getElementById('hwsecFStart').value || todayStr();
    var e = new Date(s + 'T00:00:00');
    e.setDate(e.getDate() + days);
    document.getElementById('hwsecFEnd').value = dateStr(e);
  }

  function renderAtts() {
    var box = document.getElementById('hwsecFAtts');
    if (!box) return;
    if (!pendingAtts.length) { box.innerHTML = ''; return; }
    box.innerHTML = pendingAtts.map(function (a, i) {
      return '<div class="hwsec-att-item"><span>' + (a.type === 'image' ? '🖼️' : '🎬') + ' ' + esc(a.label || '附件') +
        (a.url ? '' : '（待添加）') + '</span>' +
        '<button class="hwsec-att-del" data-att-i="' + i + '" type="button">🗑️</button></div>';
    }).join('');
    Array.prototype.forEach.call(box.querySelectorAll('[data-att-i]'), function (b) {
      b.addEventListener('click', function () {
        pendingAtts.splice(parseInt(b.getAttribute('data-att-i'), 10), 1);
        renderAtts();
      });
    });
  }

  function openSheet(item) {
    var ov = document.getElementById('hwsecOverlay');
    if (!ov) return;
    editingId = item ? item.id : null;
    pendingAtts = item ? (item.media || []).map(function (m) {
      return { id: m.id, type: m.type, url: m.url, label: m.label };
    }) : [];
    document.getElementById('hwsecSheetTitle').textContent = item ? '✏️ 编辑作业' : ('➕ 添加' + (state.cfg.subjectName || '') + '作业');
    document.getElementById('hwsecFName').value = item ? (item.name || '') : '';
    document.getElementById('hwsecFDesc').value = item ? (item.desc || '') : '';
    var t = todayStr();
    document.getElementById('hwsecFStart').value = (item && item.start) || t;
    document.getElementById('hwsecFEnd').value = (item && item.end) || t;
    setQuick(-1);
    renderAtts();
    ov.classList.remove('hidden');
  }
  function closeSheet() {
    var ov = document.getElementById('hwsecOverlay');
    if (ov) ov.classList.add('hidden');
  }

  function apiPost(url, body) {
    return fetch(url, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }).then(function (r) { return r.json(); });
  }

  function uploadFile(file) {
    var tip = document.getElementById('hwsecFUploading');
    if (tip) tip.textContent = '上传中… ' + file.name;
    var fd = new FormData();
    fd.append('file', file);
    return fetch(EP.upload, { method: 'POST', body: fd })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (tip) tip.textContent = '';
        if (!data.ok) { alert('上传失败：' + (data.error || '未知错误')); return null; }
        return { type: data.type, url: data.url, label: data.label };
      })['catch'](function () {
        if (tip) tip.textContent = '';
        alert('上传失败，请确认服务器已启动');
        return null;
      });
  }

  function bindSheet() {
    var ov = document.getElementById('hwsecOverlay');
    document.getElementById('hwsecFCancel').addEventListener('click', closeSheet);
    ov.addEventListener('click', function (e) { if (e.target.id === 'hwsecOverlay') closeSheet(); });
    document.getElementById('hwsecFPick').addEventListener('click', function () {
      document.getElementById('hwsecFFile').click();
    });
    document.getElementById('hwsecFFile').addEventListener('change', function (e) {
      var files = Array.prototype.slice.call(e.target.files || []);
      e.target.value = '';
      var chain = Promise.resolve();
      files.forEach(function (f) {
        chain = chain.then(function () {
          return uploadFile(f).then(function (up) { if (up) pendingAtts.push(up); });
        });
      });
      chain.then(renderAtts);
    });
    Array.prototype.forEach.call(ov.querySelectorAll('.hwsec-quick'), function (q) {
      q.addEventListener('click', function () { setQuick(parseInt(q.getAttribute('data-days'), 10)); });
    });
    document.getElementById('hwsecFSave').addEventListener('click', function () {
      var name = document.getElementById('hwsecFName').value.trim();
      if (!name) { alert('请填写作业名称'); return; }
      var start = document.getElementById('hwsecFStart').value;
      var end = document.getElementById('hwsecFEnd').value;
      if (start && end && end < start) { alert('结束日期不能早于开始日期'); return; }
      var media = pendingAtts.map(function (a, i) {
        return { id: a.id || ('m' + Date.now() + i), type: a.type, url: a.url || '', label: a.label };
      });
      var body = {
        name: name,
        emoji: (state.cfg.emoji || '📝'),
        color: (state.cfg.color || '#845EF7'),
        desc: document.getElementById('hwsecFDesc').value.trim(),
        teacherNote: '', repeat: 'daily', start: start, end: end, media: media,
        subject: state.cfg.subject
      };
      var op = 'add';
      if (editingId) {
        var orig = items.find(function (i) { return i.id === editingId; });
        op = 'update';
        body.id = editingId;
        if (orig) {
          body.teacherNote = orig.teacherNote || '';
          body.emoji = orig.emoji || body.emoji;
          body.color = orig.color || body.color;
          body.createdAt = orig.createdAt;
          body.subject = orig.subject || body.subject;
        }
      }
      apiPost(EP.homework, { op: op, item: body }).then(function () {
        closeSheet();
        speak('作业保存好啦！', 'zh');
        return reload();
      });
    });
  }

  /* ---------------- 数据 ---------------- */

  var items = [];
  var boardDays = null;      // 学习看板 days（懒加载一次）

  function reload() {
    return fetch(EP.homework, { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        items = d.items || [];
        childName = d.childName || childName || 'child';
        // 学习看板的「学了什么/任务」和课本页码映射（/textbooks/index.json）一起并行取
        return Promise.all([reloadBoard(), loadTextbooks()]);
      })
      .then(function () {
        loadLocal();
        return syncNow(false);
      })
      .then(function () { renderAll(); });
  }

  function reloadBoard() {
    if (!state.cfg) return Promise.resolve();
    if (boardDays) return Promise.resolve();
    // 日历里「这天学了什么/有哪些任务」也要用学习看板的数据，所以开着日历就得取
    if (!state.cfg.importFromBoard && !state.cfg.showLearned && !calendarOn()) return Promise.resolve();
    return fetch(EP.board, { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (d) { boardDays = d.days || []; })['catch'](function () { boardDays = []; });
  }

  /* ---------------- 渲染 ---------------- */

  var state = { cfg: null, root: null };

  function curDate() {
    var d = state.cfg && state.cfg.date;
    try { return (typeof d === 'function' ? d() : d) || todayStr(); } catch (e) { return todayStr(); }
  }

  function mine() {
    var sub = state.cfg.subject || '';
    return items.filter(function (it) { return (it.subject || '') === sub && it.id !== undefined; });
  }

  function itemActive(item, d) {
    return (!item.start || item.start <= d) && (!item.end || item.end >= d);
  }
  function checkedInRange(item) {
    var s = item.start || '1970-01-01';
    var e = item.end || '9999-12-31';
    var days = records[item.id] || {};
    return Object.keys(days).filter(function (d) { return d >= s && d <= e && days[d] && days[d].v; });
  }
  function itemTotalDays(item) {
    if (item.start && item.end) return Math.max(1, daysBetween(item.start, item.end));
    return 0;
  }
  function calcStreak(item) {
    var set = {};
    checkedInRange(item).forEach(function (d) { set[d] = 1; });
    var streak = 0;
    var d = new Date();
    if (!set[dateStr(d)]) d.setDate(d.getDate() - 1);
    while (set[dateStr(d)]) { streak++; d.setDate(d.getDate() - 1); }
    return streak;
  }

  function mediaHtml(m) {
    if (!m || !m.url) return '';
    if (m.type === 'image') {
      return '<div class="hwsec-media"><img src="' + esc(m.url) + '" data-hwimg="' + esc(m.url) + '" alt="' + esc(m.label || '图片') + '">' +
        (m.label ? '<div class="hwsec-media-label">🖼️ ' + esc(m.label) + '</div>' : '') + '</div>';
    }
    if (m.type === 'pdf') {
      return '<a class="hwsec-media pdf" href="' + esc(m.url) + '" target="_blank" rel="noopener">' +
        '<span class="hwsec-pdf-ico">📄</span>' +
        '<span class="hwsec-pdf-txt">' + esc(m.label || '作业 PDF') +
        '<div class="hwsec-pdf-sub">点按打开 / 长按保存，打印出来照着做</div></span>' +
        '<span class="hwsec-pdf-dl">下载</span></a>';
    }
    return '<div class="hwsec-media"><video controls loop playsinline preload="metadata" src="' + esc(m.url) + '"></video>' +
      (m.label ? '<div class="hwsec-media-label">🎬 ' + esc(m.label) + '</div>' : '') + '</div>';
  }

  function cardHtml(item, readOnly) {
    var d = curDate();
    var doneOnDate = isChecked(item.id, d);
    var doneCnt = checkedInRange(item).length;
    var total = itemTotalDays(item);
    var streak = calcStreak(item);
    var validTxt = (item.start || item.end)
      ? (fmtDate(item.start) + (item.end && item.end !== item.start ? ' ~ ' + fmtDate(item.end) : ''))
      : '长期有效';
    var media = (item.media || []).map(mediaHtml).join('');
    var isToday = d === todayStr();

    var wkNames = ['日', '一', '二', '三', '四', '五', '六'];
    var dots = '';
    for (var i = 6; i >= 0; i--) {
      var dd = new Date();
      dd.setDate(dd.getDate() - i);
      var key = dateStr(dd);
      var ok = isChecked(item.id, key);
      dots += '<span class="hwsec-dot' + (ok ? ' ok' : '') + (i === 0 ? ' today' : '') + '">' +
        '<i></i>' + (i === 0 ? '今' : wkNames[dd.getDay()]) + '</span>';
    }

    var tools = state.cfg.allowAdd
      ? '<div class="hwsec-tools">' +
        '<button class="hwsec-tool" data-edit="' + esc(item.id) + '" title="编辑">✏️</button>' +
        '<button class="hwsec-tool" data-del="' + esc(item.id) + '" title="删除">🗑️</button>' +
        '</div>'
      : '';

    var body;
    if (readOnly) {
      body = '<div class="hwsec-body">' +
        (item.desc ? '<div class="hwsec-desc">' + esc(item.desc) + '</div>' : '') +
        (item.teacherNote ? '<div class="hwsec-teacher">👩‍🏫 ' + esc(item.teacherNote) + '</div>' : '') +
        pagesHtml(item) +
        (media ? '<div class="hwsec-media-grid">' + media + '</div>' : '') +
        '</div>';
      return '<div class="hwsec-card hwsec-inactive" data-id="' + esc(item.id) + '" style="--hc:#B08968">' +
        '<div class="hwsec-head">' +
        '<span class="hwsec-emoji">' + esc(item.emoji || '📝') + '</span>' +
        '<div class="hwsec-title"><div class="hwsec-name">' + rubyHtml(item.name) + '</div>' +
        '<div class="hwsec-valid">' + (item.start && item.start > todayStr() ? '⏳ 未开始 ' : '⏸️ 已结束 ') +
        esc(validTxt) + '</div></div>' + tools +
        '</div>' + body + '</div>';
    }

    body = '<div class="hwsec-body">' +
      (item.desc ? '<div class="hwsec-desc">' + esc(item.desc) + '</div>' : '') +
      (item.teacherNote ? '<div class="hwsec-teacher">👩‍🏫 ' + esc(item.teacherNote) + '</div>' : '') +
      pagesHtml(item) +
      (media ? '<div class="hwsec-media-grid">' + media + '</div>' : '') +
      '<div class="hwsec-progress">' +
      '<span class="hwsec-stat">' + (streak >= 2 ? '🔥 连续 ' + streak + ' 天' : '🌱 今天开始') +
      (total ? ' · 已打卡 ' + doneCnt + '/' + total + ' 天' : ' · 已打卡 ' + doneCnt + ' 天') + '</span>' +
      '<div class="hwsec-dots">' + dots + '</div>' +
      '</div>' +
      '<div class="hwsec-check-row">' +
      '<button class="hwsec-check-btn' + (doneOnDate ? ' done' : '') + '" data-check="' + esc(item.id) + '">' +
      (doneOnDate ? '✅ ' + (isToday ? '今天' : fmtDate(d)) + '已打卡' : '✍️ 打卡！') + '</button>' +
      '</div>' +
      '<div class="hwsec-voice">' +
      '<div class="hwsec-voice-title">🎤 说一句</div>' +
      '<div id="hwsecVoiceBox-' + esc(item.id) + '"></div>' +
      '<div id="hwsecVoiceList-' + esc(item.id) + '"></div>' +
      '</div>' +
      '</div>';

    return '<div class="hwsec-card" data-id="' + esc(item.id) + '" style="--hc:' + esc(item.color || '#845EF7') + '">' +
      '<div class="hwsec-head">' +
      '<span class="hwsec-emoji">' + esc(item.emoji || '📝') + '</span>' +
      '<div class="hwsec-title">' +
      '<div class="hwsec-name">' + rubyHtml(item.name) + '</div>' +
      '<div class="hwsec-valid">📅 ' + esc(validTxt) + '</div>' +
      '</div>' +
      '<span class="hwsec-badge">' + (doneOnDate ? '✅ 已打卡' : '待打卡') + '</span>' +
      tools +
      '</div>' + body + '</div>';
  }

  // 学习看板里属于这个科目的任务（习惯项 + 作业项）
  function boardCandidates() {
    var sub = state.cfg.subject;
    var out = [];
    var seen = {};
    (boardDays || []).slice().reverse().forEach(function (day) {
      var date = day.date || '';
      var list = [];
      (day.habits || []).forEach(function (h) {
        list.push({ name: h.name, detail: h.detail || '', date: date, hint: (h.id || '') + ' ' + (h.name || '') });
      });
      (day.homework || []).forEach(function (h) {
        var nm = typeof h === 'string' ? h : (h.name || h.content || h.title || '');
        list.push({ name: nm, detail: typeof h === 'object' ? (h.detail || '') : '', date: date, hint: nm });
      });
      list.forEach(function (it) {
        if (!it.name) return;
        if (seen[it.name]) return;
        var g = guessSubjectFromText(it.hint);
        if (g !== sub) return;     // 英语统一挂到两个英语页上，见下面 englishSubject
        seen[it.name] = 1;
        out.push(it);
      });
    });
    return out;
  }

  // 学习看板里「今天学了」——按科目中文名匹配
  function learnedForSubject() {
    var name = state.cfg.subjectName || '';
    var d = curDate();
    var pick = null;
    (boardDays || []).forEach(function (day) {
      if (!day || !day.date) return;
      if (day.date > d) return;
      if (pick && day.date <= pick.date) return;
      var hit = (day.learned || []).filter(function (l) { return (l.subject || '') === name; });
      if (hit.length) pick = { date: day.date, items: hit };
    });
    if (!pick) return null;
    return { new: pick.date === d, date: pick.date, items: pick.items };
  }

  function learnCardHtml(info) {
    if (!info) return '';
    var imgs = [];
    info.items.forEach(function (l) { (l.images || []).forEach(function (u) { if (imgs.indexOf(u) < 0) imgs.push(u); }); });
    return '<div class="hwsec-sub-card">' +
      '<div class="hwsec-sub-title">📚 ' + (info.new ? '今天' : esc(cnDate(info.date))) + (state.cfg.subjectName || '') + '课学了什么</div>' +
      info.items.map(function (l) { return '<div class="hwsec-sub-note">· ' + esc(l.content || '') + '</div>'; }).join('') +
      (imgs.length ? '<div class="hwsec-sub-imgs">' + imgs.slice(0, 4).map(function (u) {
        return '<img src="' + esc(u) + '" data-hwimg="' + esc(u) + '" alt="课本页">';
      }).join('') + '</div>' : '') +
      '</div>';
  }

  /* ---------------- 打卡日历（整页只留一个）+ 点某天看那天的打卡内容 ----------------
     卡片里不再各挂一个日历（一页好几处「查看打卡日历」很乱也没必要），
     改成整页一个：日历在下半部分，绿色小圆点＝那天打过卡（数字＝打卡几项），
     蓝框＝今天；点某一天，紧跟着列出那天这科的全部打卡内容：
     作业打卡情况 + 各自的「说一句」语音（音频＋文字）+ 那天这科课学了什么（含课本页图）
     + 学习看板里那天的任务。数据全来自服务器那份记录，所以换台设备看到的完全一样。 */

  var calY = 0, calM = 0, selDate = '';

  function calendarOn() { return !state.cfg || state.cfg.pageCalendar !== false; }

  function subjectDoneOn(iso) {
    return mine().filter(function (it) { return isChecked(it.id, iso); });
  }

  // 学习看板里这天这科「学了什么」（和卡片上「今天学了」同一套口径）
  function learnedOn(iso) {
    var name = (state.cfg && state.cfg.subjectName) || '';
    var out = [];
    (boardDays || []).forEach(function (day) {
      if (!day || day.date !== iso) return;
      out = (day.learned || []).filter(function (l) { return (l.subject || '') === name; });
    });
    return out;
  }

  // 学习看板里这天这科的任务（习惯项 + 作业项）
  function boardTasksOn(iso) {
    var sub = state.cfg && state.cfg.subject;
    var out = [];
    (boardDays || []).forEach(function (day) {
      if (!day || day.date !== iso) return;
      (day.habits || []).forEach(function (h) {
        if (guessSubjectFromText((h.id || '') + ' ' + (h.name || '')) !== sub) return;
        out.push({ name: h.name || '', detail: h.detail || '', done: !!h.done });
      });
      (day.homework || []).forEach(function (h) {
        var nm = typeof h === 'string' ? h : (h.name || h.content || h.title || '');
        if (!nm || guessSubjectFromText(nm) !== sub) return;
        out.push({
          name: nm,
          detail: (typeof h === 'object' && h.detail) || '',
          done: !!(typeof h === 'object' && h.done)
        });
      });
    });
    return out;
  }

  function renderCal() {
    var box = document.getElementById('hwsecCalBox');
    if (!box) return;
    if (!calY) { var now = new Date(); calY = now.getFullYear(); calM = now.getMonth(); }
    var sname = state.cfg.subjectName || '';
    var today = todayStr();
    var sel = selDate || today;
    var startWk = new Date(calY, calM, 1).getDay();
    var daysInMonth = new Date(calY, calM + 1, 0).getDate();
    var prevMonthDays = new Date(calY, calM, 0).getDate();

    function outCell(num) {
      return '<div class="hwsec-cal-day out"><span class="d-num">' + num + '</span><span class="d-marks"></span></div>';
    }

    var hitDays = 0, hitItems = 0;
    var cells = '';
    for (var i = 0; i < startWk; i++) cells += outCell(prevMonthDays - startWk + 1 + i);
    for (var d = 1; d <= daysInMonth; d++) {
      var iso = dateStr(new Date(calY, calM, d));
      var n = subjectDoneOn(iso).length;
      if (n) { hitDays++; hitItems += n; }
      var cls = ['hwsec-cal-day'];
      if (n) cls.push('has');
      if (iso === today) cls.push('today');
      if (iso === sel) cls.push('sel');
      var tip = (calM + 1) + '月' + d + '日' + (n ? ('：' + sname + '打卡 ' + n + ' 项') : '：还没有打卡');
      cells += '<button type="button" class="' + cls.join(' ') + '" data-day="' + iso + '" title="' + esc(tip) + '">' +
        '<span class="d-num">' + d + '</span><span class="d-marks">' +
        (n ? '<i class="hwsec-cdot ok"></i>' + (n > 1 ? '<span class="hwsec-dcnt">' + n + '</span>' : '') : '') +
        '</span></button>';
    }
    var tail = (7 - ((startWk + daysInMonth) % 7)) % 7;
    for (var t = 1; t <= tail; t++) cells += outCell(t);

    box.innerHTML =
      '<div class="hwsec-cal-head">' +
      '<span class="hwsec-cal-title">📅 ' + calY + '年' + (calM + 1) + '月</span>' +
      '<span class="hwsec-cal-nav">' +
      '<button type="button" data-cal="prev">◀</button>' +
      '<button type="button" data-cal="today">今天</button>' +
      '<button type="button" data-cal="next">▶</button>' +
      '</span></div>' +
      '<div class="hwsec-cal-sum">本月：' + esc(sname) + '打卡 ' + hitDays + ' 天' +
      (hitItems > hitDays ? '（共 ' + hitItems + ' 项）' : '') + '　点某一天，看那天' + esc(sname) + '打卡的所有内容' +
      '</div>' +
      '<div class="hwsec-cal-grid">' +
      ['日', '一', '二', '三', '四', '五', '六'].map(function (w) { return '<span class="hwsec-cal-wk">' + w + '</span>'; }).join('') +
      cells + '</div>' +
      '<div class="hwsec-cal-legend">' +
      '<span><i class="hwsec-cdot ok"></i>这天有打卡（数字＝打卡几项）</span>' +
      '<span>蓝框＝今天</span>' +
      '<span>☁️ 记录在服务器上，换台设备打开也是这份</span>' +
      '</div>';

    Array.prototype.forEach.call(box.querySelectorAll('[data-cal]'), function (btn) {
      btn.addEventListener('click', function () {
        var kind = btn.getAttribute('data-cal');
        if (kind === 'today') {
          var n2 = new Date();
          calY = n2.getFullYear(); calM = n2.getMonth();
          selDate = todayStr();
          notifyPick(selDate);
        } else {
          var dt = new Date(calY, calM + (kind === 'next' ? 1 : -1), 1);
          calY = dt.getFullYear(); calM = dt.getMonth();
        }
        renderCal();
        renderDay();
      });
    });
    Array.prototype.forEach.call(box.querySelectorAll('[data-day]'), function (btn) {
      btn.addEventListener('click', function () {
        selDate = btn.getAttribute('data-day');
        notifyPick(selDate);
        renderCal();
        renderDay();
      });
    });
  }

  // 用户在日历里点了某一天：通知页面（onPickDate），页面要让自己的内容（听/看/说、作业卡……）
  // 也切到那天时，可以在回调里调一次 HwSection.refresh()。
  function notifyPick(iso) {
    var fn = state.cfg && state.cfg.onPickDate;
    if (typeof fn !== 'function') return;
    try { fn(iso); } catch (e) { /* 页面自己的事，失败不影响日历 */ }
  }

  // 「点某天看当天打卡内容」这块面板开关：默认跟着日历一起开
  function dayDetailOn() {
    if (!state.cfg) return false;
    if (typeof state.cfg.dayDetail === 'boolean') return state.cfg.dayDetail;
    return calendarOn();
  }

  // 页面自己那套打卡项（英语页的听/说/读/写、听/看/说……）由页面通过 dayChecks 提供，
  // 模块只负责用同一套样式列出来，这样四个学科页「点某天看当天打卡内容」长得一样。
  function dayChecksOn(iso) {
    var fn = state.cfg && state.cfg.dayChecks;
    if (typeof fn !== 'function') return [];
    try { return fn(iso) || []; } catch (e) { return []; }
  }

  // 页面自己那套录音（如学校英语的「说」跟读）通过 dayVoices 提供，模块按那天取出来双显示。
  // 返回 [{ scope: 'school-english-speak', label: '说 · 跟读录音' }]（scope 支持前缀匹配）。
  function dayVoicesOn(iso) {
    var fn = state.cfg && state.cfg.dayVoices;
    if (typeof fn !== 'function') return [];
    try { return fn(iso) || []; } catch (e) { return []; }
  }

  function renderDay() {
    var box = document.getElementById('hwsecDayBox');
    if (!box) return;
    // 页面自己带日历（pageCalendar:false）时，这天由页面说了算（date() 返回的那天）
    var iso = calendarOn() ? (selDate || todayStr()) : curDate();
    var sname = (state.cfg && state.cfg.subjectName) || '';
    var isToday = iso === todayStr();
    var checks = dayChecksOn(iso);
    var vscopes = dayVoicesOn(iso);
    var list = mine().filter(function (it) { return itemActive(it, iso) || isChecked(it.id, iso); });
    var doneN = list.filter(function (it) { return isChecked(it.id, iso); }).length;
    var secs = [];

    // ① 页面自己那套打卡项（如英语的听/说/读/写）
    if (checks.length) {
      var okN = checks.filter(function (c) { return c && c.done; }).length;
      secs.push('<div class="hwsec-dsec-title">✅ ' + esc(sname) + '打卡（' + okN + '/' + checks.length + ' 项）</div>' +
        checks.map(function (c) {
          return '<div class="hwsec-hw-row"><div class="r-top"><span class="r-name">' + rubyHtml(c.name || '') + '</span>' +
            (c.done ? '<span class="r-ok">✅ 已打卡</span>' : '<span class="r-no">⚪ 还没打卡</span>') + '</div>' +
            (c.detail ? '<div class="r-detail">' + esc(c.detail) + '</div>' : '') + '</div>';
        }).join(''));
    }

    // ② 作业卡打卡情况（含各自的「说一句」：音频 + 文字）
    var hwSec = '<div class="hwsec-dsec-title">📝 作业打卡' +
      (list.length ? '（' + doneN + '/' + list.length + ' 项）' : '') + '</div>';
    if (list.length) {
      hwSec += list.map(function (it) {
        var ok = isChecked(it.id, iso);
        return '<div class="hwsec-hw-row">' +
          '<div class="r-top"><span class="r-name">' + (it.emoji ? esc(it.emoji) + ' ' : '') + rubyHtml(it.name) + '</span>' +
          (ok ? '<span class="r-ok">✅ 已打卡</span>' : '<span class="r-no">⚪ 还没打卡</span>') + '</div>' +
          (it.desc ? '<div class="r-detail">' + esc(it.desc) + '</div>' : '') +
          pagesHtml(it) +
          '<div class="hwsec-vwrap">' +
          '<div class="hwsec-pages-hint">🎤 这天录的「说一句」（点 ▶️ 听，文字就是他说的）</div>' +
          '<div data-voice-item="' + esc(it.id) + '"></div></div>' +
          '</div>';
      }).join('');
    } else {
      hwSec += '<div class="hwsec-none">这天没有要打卡的' + esc(sname) + '作业</div>';
    }
    secs.push(hwSec);

    // ③ 页面自己那套录音（音频 + 文字双显示）
    if (vscopes.length) {
      secs.push('<div class="hwsec-dsec-title">🎙️ 这天录的音</div>' + vscopes.map(function (v, i) {
        return '<div class="hwsec-pages-hint">' + esc(v.label || v.scope || '') + '</div>' +
          '<div data-dayvoice="' + i + '"></div>';
      }).join(''));
    }

    // ④ 那天这科课学了什么（只有语文/数学这类挂了 showLearned 的页面才有）
    if (state.cfg && state.cfg.showLearned) {
      var learned = learnedOn(iso);
      var lSec = '<div class="hwsec-dsec-title">📚 这天' + esc(sname) + '课学了</div>';
      if (learned.length) {
        lSec += learned.map(function (l) { return '<div class="hwsec-dnote">· ' + esc(l.content || '') + '</div>'; }).join('');
        lSec += imgsStripHtml(collectImgs(learned), sname + '课本页');
      } else {
        lSec += '<div class="hwsec-none">这天还没有' + esc(sname) + '课的学情记录</div>';
      }
      secs.push(lSec);
    }

    // ⑤ 学习看板里那天的任务（只有语文/数学这类挂了 importFromBoard 的页面才有）
    if (state.cfg && state.cfg.importFromBoard) {
      var board = boardTasksOn(iso);
      var bSec = '<div class="hwsec-dsec-title">✅ 这天' + esc(sname) + '的学习任务（学习看板）</div>';
      if (board.length) {
        bSec += board.map(function (b) {
          return '<div class="hwsec-hw-row"><div class="r-top"><span class="r-name">' + rubyHtml(b.name) + '</span>' +
            (b.done ? '<span class="r-ok">✅ 已经做了</span>' : '<span class="r-no">⚪ 还没做</span>') + '</div>' +
            (b.detail ? '<div class="r-detail">' + esc(b.detail) + '</div>' : '') + '</div>';
        }).join('');
      } else {
        bSec += '<div class="hwsec-none">这天学习看板里没有' + esc(sname) + '任务</div>';
      }
      secs.push(bSec);
    }

    box.innerHTML = '<div class="hwsec-day-head">' +
      '<span class="hwsec-day-title">' + esc(cnDate(iso)) + ' · ' + esc(sname) + '打卡</span>' +
      (isToday ? '<span class="hwsec-day-tag">就是今天</span>' : '') + '</div>' +
      secs.map(function (s, i) {
        return '<div class="hwsec-dsec' + (i === 0 ? ' first' : '') + '">' + s + '</div>';
      }).join('');

    bindPageImgs(box);
    fillDayVoices(box, list, iso);
    fillDayScopeVoices(box, vscopes, iso);
  }

  function fillDayVoices(box, list, iso) {
    if (!window.Voice || !list.length) return;
    list.forEach(function (it) {
      var el = box.querySelector('[data-voice-item="' + it.id + '"]');
      if (!el) return;
      Voice.list({ scope: 'homework-' + it.id, date: iso, limit: 8 }).then(function (recs) {
        if (!recs || !recs.length) return;
        try {
          Voice.listInto(el, {
            scope: 'homework-' + it.id, date: iso, limit: 8,
            editable: false, deletable: false, empty: '这天没有录音'
          });
        } catch (e) { /* 忽略 */ }
      })['catch'](function () { /* 取不到就不显示，别影响其它内容 */ });
    });
  }

  function fillDayScopeVoices(box, vscopes, iso) {
    if (!window.Voice || !vscopes.length) return;
    vscopes.forEach(function (v, i) {
      var el = box.querySelector('[data-dayvoice="' + i + '"]');
      if (!el || !v.scope) return;
      Voice.list({ scope: v.scope, date: iso, limit: 30 }).then(function (recs) {
        if (!recs || !recs.length) { el.innerHTML = '<div class="hwsec-none">这天没有录音</div>'; return; }
        try {
          Voice.listInto(el, {
            scope: v.scope, date: iso, limit: 30,
            editable: false, deletable: false, empty: '这天没有录音'
          });
        } catch (e) { el.innerHTML = ''; }
      })['catch'](function () { el.innerHTML = ''; });
    });
  }

  // 两个面板的容器 HTML：日历一个、「某天打卡内容」一个（开关各自独立）
  function panelHtml(cls) {
    var h = '';
    if (calendarOn()) h += '<div class="' + cls + '" id="hwsecCalBox"></div>';
    if (dayDetailOn()) h += '<div class="' + cls + '" id="hwsecDayBox"></div>';
    return h;
  }

  function renderAll() {
    var root = state.root;
    if (!root || !state.cfg) return;
    var d = curDate();
    var list = mine();
    var active = list.filter(function (it) { return itemActive(it, d); });
    var inactive = list.filter(function (it) { return !itemActive(it, d); });
    var doneN = active.filter(function (it) { return isChecked(it.id, d); }).length;
    var isToday = d === todayStr();
    var sname = state.cfg.subjectName || '';
    // 页面自己带日历的（如辅导班页）用 panelMount 指定「某天打卡内容」放哪张卡里
    var panelHost = state.cfg.panelMount ? document.querySelector(state.cfg.panelMount) : null;

    var html = '';
    html += '<div class="hwsec-sec-head">' +
      '<span class="hwsec-sec-title">📝 ' + (isToday ? '今天的' : esc(fmtDate(d)) + '的') + esc(sname) + '作业</span>' +
      '<span class="hwsec-sec-sub">' + (active.length ? ('共 ' + active.length + ' 项，已完成 ' + doneN + ' 项') : '') + '</span>' +
      '</div>';
    html += '<div class="hwsec-synctip"></div>';

    html += learnCardHtml(state.cfg.showLearned ? learnedForSubject() : null);

    if (active.length) {
      html += active.map(function (it) { return cardHtml(it, false); }).join('');
    } else {
      html += '<div class="hwsec-empty">' + esc(sname) + '今天没有要打卡的作业 🎈<br>' +
        (state.cfg.allowAdd ? '点下面的「＋ 添加作业」加一项吧。' : '老师布置了就在这里打卡。') + '</div>';
    }

    if (state.cfg.importFromBoard) {
      var cands = boardCandidates();
      var addedNames = {};
      list.forEach(function (i) { addedNames[i.name] = 1; });
      if (cands.length) {
        html += '<div class="hwsec-sub-card"><div class="hwsec-sub-title">📚 学习看板里还没加入的' + esc(sname) + '任务</div>' +
          cands.slice(0, 12).map(function (c) {
            var added = !!addedNames[c.name];
            return '<div class="hwsec-learn-item">' +
              '<span class="hwsec-learn-day">' + (c.date ? c.date.slice(5).replace('-', '/') : '今日') + '</span>' +
              '<div class="hwsec-learn-body"><div class="hwsec-learn-name">' + rubyHtml(c.name) + '</div>' +
              (c.detail ? '<div class="hwsec-learn-detail">' + esc(c.detail) + '</div>' : '') + '</div>' +
              '<button class="hwsec-learn-add' + (added ? ' added' : '') + '" data-learn="' + esc(c.name) + '" data-detail="' + esc(c.detail) + '"' +
              (added ? ' disabled' : '') + '>' + (added ? '已加入' : '＋加入') + '</button>' +
              '</div>';
          }).join('') + '</div>';
      }
    }

    if (state.cfg.allowAdd) {
      html += '<button class="hwsec-add-btn" type="button">＋ 添加' + esc(sname) + '作业</button>';
    }

    html += '<button class="hwsec-fold" type="button">📦 已结束 / 未开始的作业</button>';
    html += '<div class="hwsec-inactive-list" style="display:none"></div>';

    // 整页一个「打卡日历」+「点某天看那天的打卡内容」（面板内容由 renderCal / renderDay 填）；
    // 页面自己带日历的用 panelMount 把这块放到它自己的卡片里
    if (!panelHost) html += panelHtml('hwsec-panel');

    root.innerHTML = html;
    paintSyncTip();
    if (panelHost) panelHost.innerHTML = panelHtml('hwsec-panel host');

    // 已结束 / 未开始
    var fold = root.querySelector('.hwsec-fold');
    var inBox = root.querySelector('.hwsec-inactive-list');
    if (!inactive.length) {
      fold.style.display = 'none';
    } else {
      fold.style.display = 'block';
      fold.textContent = '📦 已结束 / 未开始的作业（' + inactive.length + ' 项）';
      inBox.innerHTML = inactive.map(function (it) { return cardHtml(it, true); }).join('');
    }
    fold.addEventListener('click', function () {
      inBox.style.display = inBox.style.display === 'none' ? 'block' : 'none';
    });

    // 打卡 / 日历 / 图片 / 编辑删除
    Array.prototype.forEach.call(root.querySelectorAll('[data-check]'), function (btn) {
      btn.addEventListener('click', function () {
        var id = btn.getAttribute('data-check');
        var item = items.filter(function (i) { return i.id === id; })[0];
        if (!item) return;
        var cur = isChecked(id, d);
        setChecked(id, d, !cur);
        if (!cur) {
          showCelebration('🎉', item.name + ' 打卡成功，你真棒！');
          var nowDone = mine().filter(function (i) { return itemActive(i, curDate()) && isChecked(i.id, curDate()); }).length;
          var nowTotal = mine().filter(function (i) { return itemActive(i, curDate()); }).length;
          if (nowTotal && nowDone === nowTotal) setTimeout(function () { showCelebration('🏆', sname + '作业全部完成，你真棒！'); }, 2700);
        } else {
          speak('已取消，没关系！', 'zh');
        }
        renderAll();
      });
    });
    bindPageImgs(root);
    Array.prototype.forEach.call(root.querySelectorAll('[data-edit]'), function (btn) {
      btn.addEventListener('click', function () {
        var item = items.filter(function (i) { return i.id === btn.getAttribute('data-edit'); })[0];
        if (item) openSheet(item);
      });
    });
    Array.prototype.forEach.call(root.querySelectorAll('[data-del]'), function (btn) {
      btn.addEventListener('click', function () {
        var id = btn.getAttribute('data-del');
        if (!confirm('确定删除这项作业吗？打卡记录也会一起删除。')) return;
        apiPost(EP.homework, { op: 'delete', id: id }).then(function () { return reload(); });
      });
    });
    Array.prototype.forEach.call(root.querySelectorAll('[data-learn]'), function (btn) {
      btn.addEventListener('click', function () {
        var name = btn.getAttribute('data-learn');
        var detail = btn.getAttribute('data-detail');
        apiPost(EP.homework, {
          op: 'add',
          item: {
            name: name, emoji: state.cfg.emoji || '📝', color: state.cfg.color || '#845EF7',
            desc: detail || '', teacherNote: '', repeat: 'daily',
            start: todayStr(), end: todayStr(), media: [],
            subject: state.cfg.subject
          }
        }).then(function () {
          speak('加入作业啦！', 'zh');
          return reload();
        });
      });
    });
    var addBtn = root.querySelector('.hwsec-add-btn');
    if (addBtn) addBtn.addEventListener('click', function () { openSheet(null); });

    // 语音备注：卡片是整块重建的，每次渲染后重新挂载（旧监听随旧节点一起消失）
    mountVoices(active);

    // 打卡日历 + 某天的打卡内容（只有这两个小面板会重画，别的卡片不动）
    if (calendarOn()) renderCal();
    if (dayDetailOn()) renderDay();
  }

  function mountVoices(active) {
    if (!window.Voice) return;
    active.forEach(function (item) {
      var boxSel = '#hwsecVoiceBox-' + item.id;
      if (!document.querySelector(boxSel)) return;
      try {
        Voice.attach({
          mount: boxSel,
          scope: 'homework-' + item.id,
          lang: 'zh',
          compact: true,
          meta: Object.assign({ item: item.id }, state.cfg.meta || {})
        });
      } catch (e) { /* 单张卡片失败不影响其它卡片 */ }
      try {
        Voice.listInto('#hwsecVoiceList-' + item.id, {
          scope: 'homework-' + item.id,
          limit: 10,
          empty: '还没有语音记录'
        });
      } catch (e) { /* 忽略 */ }
    });
  }

  /* ---------------- 对外接口 ---------------- */

  window.HwSection = {
    mount: function (cfg) {
      ensureShell();
      state.cfg = cfg || {};
      // 架构 v2 第 3 步：端点可按技能覆盖；不传就是 v1 默认（/api/homework 系）
      EP = DEFAULT_ENDPOINTS;
      CHECKIN_SKILL = '';
      if (cfg && cfg.endpoints) {
        EP = {};
        Object.keys(DEFAULT_ENDPOINTS).forEach(function (k) {
          EP[k] = cfg.endpoints[k] || DEFAULT_ENDPOINTS[k];
        });
      }
      if (cfg && cfg.checkinSkill) CHECKIN_SKILL = String(cfg.checkinSkill);
      state.root = typeof cfg.mount === 'string' ? document.querySelector(cfg.mount) : cfg.mount;
      if (!state.root) { console.warn('[HwSection] 找不到挂载点', cfg.mount); return; }
      reload();
      startSyncLoop();
    },
    refresh: function () { renderAll(); },
    // 只重画日历 + 「某天打卡内容」两个面板（页面自己那套打卡项变了，用这个就够）
    refreshDay: function () {
      if (calendarOn()) renderCal();
      if (dayDetailOn()) renderDay();
    },
    // 页面自己切了日期（或点「回到今天」）后调一下：日历/「某天打卡内容」跟着走
    setDay: function (iso) {
      if (!iso) return;
      selDate = iso;
      if (calendarOn()) renderCal();
      if (dayDetailOn()) renderDay();
    },
    // 日期切换后重新拉一次（辅导班页的历史补打卡用）
    reload: reload,
    todayStr: todayStr
  };
})();

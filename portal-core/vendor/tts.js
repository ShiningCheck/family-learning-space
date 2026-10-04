/*! 成长家园 · 朗读模块 tts.js v1
 *
 * 目标：手机上没有系统语音引擎、或浏览器拦住 TTS 时，也能正常听到声音。
 * 策略：
 *   1. 优先播放 data/tts/audio/ 下预生成的 mp3（内容由 voice-dubbing 技能合成）；
 *   2. 清单里没有的文本，自动降级到浏览器 speechSynthesis；
 *   3. 两条路都失败时，用页面底部提示条说明原因，不再静默无反应。
 *
 * 用法：
 *   TTS.speak('three', 'en')           // 读一条
 *   TTS.speakSeq(['one','two'], 'en')  // 依次读（默写表这种）
 *   TTS.stop()                         // 停止
 *   TTS.has('three', 'en')             // 是否有预生成音频
 */
(function () {
  'use strict';
  if (window.TTS) return;

  var BASES = ['/data/tts/', '../data/tts/', 'data/tts/'];

  var manifest = null, base = null, loading = null;
  var token = 0, missCount = 0, missWarned = false, noVoiceWarned = false;
  var ttsBroken = false;           // 判定这台设备朗读不出声后，后续直接播音频，不再每次等
  var lastPlayed = '';             // 最近一次成功开始播放的音频（诊断用）
  var lastError = '';              // 最近一次播放失败原因（诊断用）
  var interrupt = null;            // 正在播放/朗读的终止回调，供 stop() 打断

  var audio = new Audio();
  audio.preload = 'none';
  var currentUrl = '';

  function byId(id) { return document.getElementById(id); }
  function normalize(s) { return String(s == null ? '' : s).replace(/\s+/g, ' ').trim(); }
  function langOf(lang) { return lang === 'zh' ? 'zh' : 'en'; }
  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

  /* ---------------- 提示条 ---------------- */
  var toastTimer = null, lastToast = '', lastToastAt = 0;
  function toast(msg, ms) {
    try {
      var now = Date.now();
      if (!msg || (msg === lastToast && now - lastToastAt < 6000)) return;
      lastToast = msg; lastToastAt = now;
      var el = byId('ttsToast');
      if (!el) {
        el = document.createElement('div');
        el.id = 'ttsToast';
        el.style.cssText = 'position:fixed;left:50%;bottom:26px;transform:translateX(-50%);' +
          'max-width:88vw;padding:11px 16px;border-radius:12px;background:rgba(28,25,22,.9);' +
          'color:#fff;font-size:14px;line-height:1.55;z-index:99999;text-align:center;' +
          'box-shadow:0 6px 20px rgba(0,0,0,.22);transition:opacity .25s;opacity:0;pointer-events:none;';
        document.body.appendChild(el);
      }
      el.textContent = msg;
      el.style.opacity = '1';
      if (toastTimer) clearTimeout(toastTimer);
      toastTimer = setTimeout(function () { el.style.opacity = '0'; }, ms || 4600);
    } catch (e) { /* 提示失败不能影响播放 */ }
  }

  /* ---------------- 配音清单 ---------------- */
  function load() {
    if (loading) return loading;
    var i = 0;
    function tryNext() {
      if (i >= BASES.length) return Promise.resolve(false);
      var b = BASES[i++];
      return fetch(b + 'index.json', { cache: 'no-cache' })
        .then(function (r) { if (!r.ok) throw new Error('http ' + r.status); return r.json(); })
        .then(function (j) {
          if (!j || !j.en) throw new Error('清单格式不对');
          manifest = j; base = b;
          return true;
        })
        .catch(function () { return tryNext(); });
    }
    loading = tryNext();
    return loading;
  }
  load();

  function ready() { return manifest ? Promise.resolve(true) : (loading || load()); }
  function lookup(text, lang) { return (manifest && manifest[lang] && manifest[lang][text]) || null; }

  /* ---------------- 播放预生成音频 ---------------- */
  function stop() {
    token++;
    if (interrupt) { var f = interrupt; interrupt = null; f(false); }
    try { audio.pause(); } catch (e) {}
    try { if ('speechSynthesis' in window) window.speechSynthesis.cancel(); } catch (e) {}
  }

  function playFile(url, myToken) {
    return new Promise(function (resolve) {
      var settled = false;
      function finish(ok) {
        if (settled) return;
        settled = true;
        audio.removeEventListener('ended', onEnd);
        audio.removeEventListener('error', onError);
        if (interrupt === finish) interrupt = null;
        resolve(ok);
      }
      function onEnd() { finish(true); }
      function onError() { lastError = 'audio-error ' + url; finish(false); }
      audio.addEventListener('ended', onEnd);
      audio.addEventListener('error', onError);
      if (currentUrl !== url) { currentUrl = url; audio.src = url; }
      try { audio.currentTime = 0; } catch (e) {}
      interrupt = finish;
      var p = audio.play();
      if (p && p.then) {
        p.then(function () { lastPlayed = url; }).catch(function () { lastError = 'play-blocked ' + url; finish(false); });
      } else {
        lastPlayed = url;
      }
    });
  }

  /* ---------------- 浏览器朗读（兜底） ---------------- */
  var voices = [];
  function refreshVoices() {
    try { voices = window.speechSynthesis.getVoices() || []; } catch (e) { voices = []; }
  }
  if ('speechSynthesis' in window) {
    refreshVoices();
    try { window.speechSynthesis.onvoiceschanged = refreshVoices; } catch (e) {}
  }

  // 第一次触摸时预热语音引擎：安卓 Chrome 的引擎是"用到了才启动"，
  // 冷启动时首次朗读经常没声音。音量设为 0，不会有任何出声。
  // 注意：不要在这里"预播放"任何配音音频——那会在页面刚打开时冒出声音。
  var unlocked = false;
  function unlock() {
    if (unlocked) return;
    unlocked = true;
    if (!('speechSynthesis' in window)) return;
    try {
      var u = new SpeechSynthesisUtterance(' ');
      u.volume = 0; u.rate = 1;
      window.speechSynthesis.speak(u);
      window.speechSynthesis.cancel();
    } catch (e) {}
  }
  document.addEventListener('touchstart', unlock, { once: true, passive: true });
  document.addEventListener('mousedown', unlock, { once: true });

  function ttsSpeak(text, lang, waitEnd, customize, hasAudio) {
    return new Promise(function (resolve) {
      if (!('speechSynthesis' in window)) {
        toast('这个浏览器不支持朗读：请用 Chrome 或 Safari 打开，或到电脑上听');
        resolve(false); return;
      }
      var u = new SpeechSynthesisUtterance(text);
      var list = voices.filter(function (v) {
        return v.lang && v.lang.toLowerCase().indexOf(lang) === 0;
      });
      if (list.length) { u.voice = list[0]; u.lang = list[0].lang; }
      else { u.lang = lang === 'en' ? 'en-US' : 'zh-CN'; }
      u.rate = lang === 'en' ? 0.72 : 0.9;
      // 页面可传 customize 覆盖音色/语速/音调（例如使用家长选好的音色）
      if (customize) { try { customize(u); } catch (e) {} }

      var settled = false, started = false, timer = null, startTimer = null;
      function finish(ok) {
        if (settled) return;
        settled = true;
        if (timer) clearTimeout(timer);
        if (startTimer) clearTimeout(startTimer);
        if (interrupt === finish) interrupt = null;
        resolve(ok);
      }
      u.onstart = function () { started = true; if (!waitEnd) finish(true); };
      u.onend = function () { finish(true); };
      u.onerror = function (ev) {
        var code = (ev && ev.error) || '';
        finish(false);
        if (code === 'not-allowed') toast('浏览器拦住了朗读：先点一下页面，再点喇叭试试');
        else if (!noVoiceWarned) {
          noVoiceWarned = true;
          ttsBroken = true;
          toast(hasAudio ? '这台设备朗读不出声，已改用配音音频' : '这台设备朗读不出声，可以到电脑上听');
        }
      };

      // 清空队列后不要立刻 speak：部分浏览器（尤其安卓 Chrome）会把紧接着的这句丢掉，
      // 所以隔一小段时间再念（与页面原先的写法一致）。
      try { window.speechSynthesis.cancel(); } catch (e) {}
      try { if (window.speechSynthesis.paused) window.speechSynthesis.resume(); } catch (e) {}
      startTimer = setTimeout(function () {
        if (settled) return;
        try { window.speechSynthesis.speak(u); } catch (e) { finish(false); return; }
        // 安卓 Chrome 已知问题：cancel() 之后引擎偶尔卡在暂停态，补一次 resume()
        setTimeout(function () {
          try { if (!settled && window.speechSynthesis.paused) window.speechSynthesis.resume(); } catch (e) {}
        }, 120);
      }, 60);
      timer = setTimeout(function () {
        if (!started && !settled) {
          finish(false);
          ttsBroken = true;               // 这台设备读不出声，后续直接播音频，不再每次等
          if (!noVoiceWarned) {
            noVoiceWarned = true;
            toast(hasAudio ? '这台设备朗读不出声，已改用配音音频' : '这台设备朗读不出声，可以到电脑上听');
          }
        }
      }, 1200);
      interrupt = finish;
    });
  }

  /* ---------------- 单条播放 ----------------
   * opts.prefer = 'mp3'（默认，先播配音音频）| 'tts'（先浏览器朗读，读不出声再用音频兜底）
   * opts.customize = function(utterance) 覆写音色/语速，供带音色选择的页面使用
   */
  function playOne(text, lang, waitEnd, opts) {
    var myToken = token;
    var entry = manifest ? lookup(text, lang) : null;
    var preferTTS = !!(opts && opts.prefer === 'tts');

    function useMp3() {
      if (!entry) return null;
      return playFile(base + 'audio/' + entry.f, myToken);
    }
    function useTTS() {
      return ttsSpeak(text, lang, waitEnd, opts && opts.customize, !!entry);
    }
    function warnMissing() {
      if (manifest) {
        missCount++;
        if (!missWarned && missCount >= 4) {
          missWarned = true;
          toast('有 ' + missCount + ' 条内容还没配音，先用浏览器朗读代替');
        }
      } else if (!missWarned) {
        missWarned = true;
        toast('没找到配音清单，改用浏览器朗读（部分手机读不出声）');
      }
    }

    if (preferTTS && !ttsBroken && 'speechSynthesis' in window) {
      return useTTS().then(function (ok) {
        if (ok || myToken !== token) return ok;
        var p = useMp3();                 // 手机读不出声，用配音音频顶上
        if (p) return p;
        warnMissing();
        return false;
      });
    }
    if (entry) {
      return useMp3().then(function (ok) {
        if (ok || myToken !== token) return ok;
        if (ttsBroken) {
          toast('配音音频没播出来，检查一下手机和电脑是否在同一个 WiFi');
          return false;
        }
        return useTTS();
      });
    }
    warnMissing();
    if (myToken !== token) return Promise.resolve(false);
    return useTTS();
  }

  function speak(text, lang, opts) {
    var t = normalize(text), lg = langOf(lang);
    if (!t) return Promise.resolve(false);
    stop();
    var myToken = token;
    return ready().then(function () {
      if (myToken !== token) return false;
      // opts.waitEnd = true 时等读完/播完再 resolve（用于按钮"朗读中"状态）
      return playOne(t, lg, !!(opts && opts.waitEnd), opts);
    });
  }

  function speakSeq(list, lang, opts) {
    var lg = langOf(lang);
    var arr = (list || []).map(normalize).filter(Boolean);
    if (!arr.length) return Promise.resolve(false);
    stop();
    var myToken = token;
    return ready().then(function () {
      var i = 0;
      function step() {
        if (myToken !== token) return Promise.resolve(false);
        if (i >= arr.length) return Promise.resolve(true);
        var text = arr[i++];
        return playOne(text, lg, true, opts).then(function () {
          if (myToken !== token) return false;
          if (i >= arr.length) return true;
          return sleep(260).then(step);
        });
      }
      return step();
    });
  }

  window.TTS = {
    speak: speak,
    speakSeq: speakSeq,
    stop: stop,
    unlock: unlock,
    prewarm: unlock,
    ready: ready,
    toast: toast,
    has: function (text, lang) { return !!lookup(normalize(text), langOf(lang)); },
    info: function () {
      return { loaded: !!manifest, base: base, generated: manifest && manifest.generated,
               stats: manifest && manifest.stats, ttsBroken: ttsBroken,
               lastPlayed: lastPlayed, lastError: lastError };
    }
  };
})();

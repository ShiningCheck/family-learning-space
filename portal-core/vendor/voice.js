/*!
 * 成长家园 · 通用语音记录组件（voice.js）
 * ---------------------------------------------------------------
 * 把「画作页」那套录音方式推广到全站：手机录一段 / 用手机系统录音机录好再选文件上传，
 * 音频传到门户服务器落盘，服务器**自动识别成文字**，文字和语音一起留档。
 *
 * 用法（页面里）：
 *   <script src="vendor/voice.js"></script>
 *   Voice.attach({ mount: '#recBox', scope: 'tracker-reading', autoFill: '#noteInput' });
 *
 * 接口：
 *   Voice.attach(opts)      生成录音/上传/识别/存档的一套 UI，返回控制器
 *   Voice.list(opts)        取某场景的语音记录（Promise）
 *   Voice.listInto(el, o)   把某场景的语音记录渲染成一个可播放/可改文字/可删除的列表
 *   Voice.updateText(id,t)  改某条记录的文字（原始识别结果不会丢）
 *   Voice.remove(id)        删掉某条记录（索引与音频文件一起删，删了就找不回来）
 *   Voice.serverAvailable() 门户服务器在不在（不在时按钮会给出提示）
 *
 * attach 参数：
 *   mount        必填，容器元素或选择器
 *   scope        必填，场景名（如 tracker-reading / homework-xxx / library-ask）
 *   lang         'zh'（默认）| 'en'，识别语言
 *   date         'YYYY-MM-DD'，默认今天
 *   autoFill     识别出的文字写进哪个输入框/文本域（可省略）
 *   fillMode     'append'（默认，已有内容就换行追加）| 'replace'
 *   meta         附带信息（对象，如 { page: '打卡页' }）
 *   maxSeconds   录音最长秒数，默认 120，到点自动停
 *   compact      true 时按钮更小（适合卡片内嵌）
 *   onText(t,rec)  识别出文字后回调
 *   onSaved(rec)   存档完成后回调（拿到 record.url / record.id / record.text）
 *   onDeleted(id)  删掉刚录这条后回调（列表页用它刷新下方历史列表）
 *
 * 设计约定：零外部依赖；只在用户点击时申请麦克风/播放声音；服务器不可用时明确提示，
 * 不假装成功（宁可让家长知道"录音没存上"）。
 */
(function (global) {
  'use strict';

  var STATUS_TIMEOUT = 30000;   // 服务器可用性探测结果缓存时长
  var _serverOk = null, _serverAt = 0;
  var _probe = null;

  function q(sel) {
    if (!sel) return null;
    return typeof sel === 'string' ? document.querySelector(sel) : sel;
  }

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function todayStr() {
    var d = new Date();
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  }

  function fmtSec(s) {
    s = Math.round(Number(s) || 0);
    return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
  }

  function injectCss() {
    if (document.getElementById('vr-style')) return;
    var css = '' +
      '.vr{display:block;margin:0}' +
      '.vr-row{display:flex;align-items:center;gap:10px;flex-wrap:wrap}' +
      '.vr-btn{border:3px solid var(--edge,#4A3B2A);border-radius:999px;background:var(--line,#FFF1DB);' +
      'color:var(--ink,#4A3B2A);padding:10px 18px;font-size:16px;font-weight:800;cursor:pointer;' +
      'font-family:inherit;line-height:1.2}' +
      '.vr-btn:active{transform:translateY(2px)}' +
      '.vr-btn[disabled]{opacity:.55;cursor:default}' +
      '.vr-btn.vr-recording{background:#FFD8D8}' +
      '.vr-btn.vr-sm{padding:7px 14px;font-size:14px;border-width:2px}' +
      '.vr-del{background:var(--card,#fff);border-width:2px;padding:7px 14px;font-size:13px}' +
      '.vr-status{margin-top:8px;font-size:14px;font-weight:700;color:var(--soft,#8D7357);min-height:20px}' +
      '.vr-status.vr-ok{color:#2F9E44}' +
      '.vr-status.vr-warn{color:#E8590C}' +
      '.vr-status.vr-err{color:#C92A2A}' +
      '.vr-text{margin-top:8px;padding:10px 12px;border-radius:14px;background:var(--paper,#FFF6E9);' +
      'border:2px dashed var(--line,#FFE3B3);font-size:15px;color:var(--ink,#4A3B2A);white-space:pre-wrap;word-break:break-word}' +
      '.vr-audio{margin-top:8px;width:100%;max-width:340px}' +
      '.vr-hide{display:none!important}' +
      '.vr-list{margin-top:10px;display:flex;flex-direction:column;gap:8px}' +
      '.vr-item{display:flex;align-items:flex-start;gap:10px;padding:10px 12px;border-radius:14px;' +
      'background:var(--card,#fff);border:2px solid var(--line,#FFE3B3)}' +
      '.vr-play,.vr-edit,.vr-remove{flex:0 0 auto;border:2px solid var(--edge,#4A3B2A);border-radius:999px;background:var(--line,#FFF1DB);' +
      'cursor:pointer;font-size:15px;padding:4px 10px;font-family:inherit;line-height:1.4}' +
      '.vr-remove{border-color:#E03131;background:#FFE3E3}' +
      '.vr-play[disabled],.vr-edit[disabled],.vr-remove[disabled]{opacity:.5;cursor:default}' +
      '.vr-body{flex:1 1 auto;min-width:0}' +
      '.vr-t{font-size:15px;font-weight:700;color:var(--ink,#4A3B2A);white-space:pre-wrap;word-break:break-word}' +
      '.vr-m{margin-top:4px;font-size:12px;color:var(--soft,#8D7357);font-weight:700}' +
      '.vr-empty{font-size:14px;color:var(--soft,#8D7357);font-weight:700;padding:6px 2px}' +
      '.vr-editbox{width:100%;min-height:64px;border:2px solid var(--line,#FFE3B3);border-radius:12px;padding:8px;' +
      'font-family:inherit;font-size:15px;color:var(--ink,#4A3B2A);background:var(--paper,#FFF6E9);box-sizing:border-box}' +
      '.vr-editactions{margin-top:6px;display:flex;gap:8px}' +
      '.vr-mini{border:2px solid var(--edge,#4A3B2A);border-radius:999px;background:var(--line,#FFF1DB);padding:5px 12px;' +
      'font-size:13px;font-weight:800;cursor:pointer;font-family:inherit;color:var(--ink,#4A3B2A)}';
    var el = document.createElement('style');
    el.id = 'vr-style';
    el.textContent = css;
    document.head.appendChild(el);
  }

  /** 门户服务器是否可用（缓存 30 秒，避免每次点按钮都探一遍） */
  function serverAvailable(force) {
    var now = Date.now();
    if (!force && _serverOk !== null && now - _serverAt < STATUS_TIMEOUT) {
      return Promise.resolve(_serverOk);
    }
    if (_probe) return _probe;
    _probe = fetch('/api/voice/status', { cache: 'no-store' })
      .then(function (r) { _serverOk = r.ok; _serverAt = Date.now(); _probe = null; return _serverOk; })
      .catch(function () { _serverOk = false; _serverAt = Date.now(); _probe = null; return false; });
    return _probe;
  }

  function upload(blob, filename, meta) {
    var fd = new FormData();
    fd.append('audio', blob, filename);
    fd.append('scope', meta.scope);
    fd.append('lang', meta.lang);
    fd.append('date', meta.date);
    if (meta.text) fd.append('text', meta.text);
    if (meta.asr) fd.append('asr', meta.asr);
    if (meta.meta) {
      try { fd.append('meta', JSON.stringify(meta.meta)); } catch (e) { /* 忽略 */ }
    }
    return fetch('/api/voice', { method: 'POST', body: fd }).then(function (r) {
      return r.json().then(function (j) {
        if (!r.ok || !j || !j.ok) throw new Error((j && j.error) || ('HTTP ' + r.status));
        return j.record;
      });
    });
  }

  function extOf(blob, name) {
    var t = (blob && blob.type) || '';
    if (t.indexOf('mp4') >= 0 || t.indexOf('aac') >= 0) return 'm4a';
    if (t.indexOf('webm') >= 0) return 'webm';
    if (t.indexOf('ogg') >= 0) return 'ogg';
    if (t.indexOf('wav') >= 0) return 'wav';
    if (t.indexOf('mpeg') >= 0 || t.indexOf('mp3') >= 0) return 'mp3';
    var m = /\.([a-z0-9]+)$/i.exec(name || '');
    return m ? m[1].toLowerCase() : 'webm';
  }

  function writeText(rec, text, target, mode) {
    if (!target || !text) return;
    if (mode === 'replace') {
      target.value = text;
    } else {
      var cur = (target.value || '').trim();
      target.value = cur ? (cur + '\n' + text) : text;
    }
    try {
      target.dispatchEvent(new Event('input', { bubbles: true }));
      target.dispatchEvent(new Event('change', { bubbles: true }));
    } catch (e) { /* 老浏览器忽略 */ }
  }

  /** 生成一套「🎤 录音 / 📁 上传录音 / 自动识别 / 存档」的 UI */
  function attach(opts) {
    opts = opts || {};
    injectCss();
    var mount = q(opts.mount);
    if (!mount) throw new Error('Voice.attach: 找不到容器 ' + opts.mount);
    var scope = opts.scope || 'misc';
    var lang = opts.lang === 'en' ? 'en' : 'zh';
    var dateStr = opts.date || todayStr();
    var autoFill = q(opts.autoFill);
    var fillMode = opts.fillMode === 'replace' ? 'replace' : 'append';
    var maxSeconds = opts.maxSeconds || 120;
    var small = opts.compact ? ' vr-sm' : '';

    mount.innerHTML =
      '<div class="vr" data-scope="' + esc(scope) + '">' +
      '<div class="vr-row">' +
      '<button class="vr-btn vr-rec' + small + '" type="button">🎤 录音</button>' +
      '<button class="vr-btn vr-up' + small + '" type="button">📁 上传录音</button>' +
      '<button class="vr-btn vr-retry vr-hide' + small + '" type="button">🔁 重试上传</button>' +
      '<button class="vr-btn vr-del vr-hide" type="button">🗑 删除</button>' +
      '</div>' +
      '<div class="vr-status vr-hide"></div>' +
      '<div class="vr-text vr-hide"></div>' +
      '<audio class="vr-audio vr-hide" controls preload="metadata"></audio>' +
      '<input type="file" accept="audio/*" class="vr-hide">' +
      '</div>';

    var root = mount.querySelector('.vr');
    var recBtn = root.querySelector('.vr-rec');
    var upBtn = root.querySelector('.vr-up');
    var retryBtn = root.querySelector('.vr-retry');
    var delBtn = root.querySelector('.vr-del');
    var statusEl = root.querySelector('.vr-status');
    var textEl = root.querySelector('.vr-text');
    var audioEl = root.querySelector('.vr-audio');
    var fileEl = root.querySelector('input[type=file]');

    var st = {
      chunks: [], stream: null, recorder: null, blob: null,
      objUrl: '', timer: null, tick: null, startedAt: 0, sending: false, last: null
    };

    function setStatus(msg, kind) {
      statusEl.className = 'vr-status' + (kind ? ' vr-' + kind : '');
      statusEl.textContent = msg || '';
      statusEl.classList.toggle('vr-hide', !msg);
    }

    function hideAudio() {
      audioEl.classList.add('vr-hide');
      audioEl.removeAttribute('src');
      if (st.objUrl) { URL.revokeObjectURL(st.objUrl); st.objUrl = ''; }
    }

    function stopStream() {
      try { if (st.stream) st.stream.getTracks().forEach(function (t) { t.stop(); }); } catch (e) { /* 忽略 */ }
      st.stream = null;
    }

    function reset(keepStatus) {
      try { if (st.recorder && st.recorder.state === 'recording') st.recorder.stop(); } catch (e) { /* 忽略 */ }
      try { window.clearInterval(st.tick); } catch (e) { /* 忽略 */ }
      stopStream();
      st.recorder = null; st.chunks = []; st.blob = null; st.last = null;
      hideAudio();
      recBtn.textContent = '🎤 录音';
      recBtn.classList.remove('vr-recording');
      delBtn.classList.add('vr-hide');
      retryBtn.classList.add('vr-hide');
      textEl.classList.add('vr-hide');
      textEl.textContent = '';
      fileEl.value = '';
      if (!keepStatus) setStatus('');
    }

    function showPreview(blob) {
      hideAudio();
      st.objUrl = URL.createObjectURL(blob);
      audioEl.src = st.objUrl;
      audioEl.classList.remove('vr-hide');
      delBtn.classList.remove('vr-hide');
    }

    function send(blob, filename) {
      if (st.sending) return;
      st.sending = true;
      recBtn.setAttribute('disabled', 'disabled');
      upBtn.setAttribute('disabled', 'disabled');
      retryBtn.classList.add('vr-hide');
      var waited = 0;
      setStatus('正在识别成文字…（语音越长越慢，先别关页面） 0 秒');
      st.tick = window.setInterval(function () {
        waited += 1;
        setStatus('正在识别成文字…（语音越长越慢，先别关页面） ' + waited + ' 秒');
      }, 1000);

      upload(blob, filename, {
        scope: scope, lang: lang, date: dateStr, meta: opts.meta
      }).then(function (rec) {
        st.last = rec;
        window.clearInterval(st.tick);
        if (rec.text) {
          textEl.textContent = '📝 ' + rec.text;
          textEl.classList.remove('vr-hide');
          writeText(rec, rec.text, autoFill, fillMode);
        } else {
          textEl.classList.add('vr-hide');
        }
        if (rec.asrOk) {
          setStatus(rec.text
            ? '识别完成 ✓ 语音和文字都存好了（文字可以直接改）'
            : '录音存好了，但这段没听出内容，可以自己写下来', rec.text ? 'ok' : 'warn');
        } else {
          setStatus('录音已存好，但识别没成功：' + (rec.asrError || '未知原因') + '（文字可以自己写）', 'warn');
        }
        recBtn.textContent = '🔁 重录';
        if (opts.onText && rec.text) { try { opts.onText(rec.text, rec); } catch (e) { /* 忽略 */ } }
        if (opts.onSaved) { try { opts.onSaved(rec); } catch (e) { /* 忽略 */ } }
      }).catch(function (err) {
        window.clearInterval(st.tick);
        var msg = String((err && err.message) || err);
        if (/Failed to fetch|NetworkError|Load failed/i.test(msg)) {
          setStatus('连不上门户服务器，录音还没存上。请确认电脑上的预览服务器开着（手机与电脑同一 WiFi），再点「🔁 重试上传」。', 'err');
        } else {
          setStatus('保存失败：' + msg + '（可点「🔁 重试上传」）', 'err');
        }
        retryBtn.classList.remove('vr-hide');
      }).then(function () {
        st.sending = false;
        recBtn.removeAttribute('disabled');
        upBtn.removeAttribute('disabled');
      });
    }

    function startRec() {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || typeof window.MediaRecorder === 'undefined') {
        setStatus('这个浏览器录不了音（手机用非 https 地址打开时会受限）。可以按下面的办法：用手机自带「录音机」App 录好，再点「📁 上传录音」选文件。', 'warn');
        return;
      }
      navigator.mediaDevices.getUserMedia({ audio: true }).then(function (stream) {
        st.stream = stream;
        st.chunks = [];
        var mime = 'audio/webm';
        if (window.MediaRecorder.isTypeSupported('audio/mp4')) mime = 'audio/mp4';
        else if (window.MediaRecorder.isTypeSupported('audio/webm')) mime = 'audio/webm';
        var rec;
        try { rec = new MediaRecorder(stream, { mimeType: mime }); }
        catch (e) { rec = new MediaRecorder(stream); }
        st.recorder = rec;
        rec.ondataavailable = function (e) { if (e.data && e.data.size) st.chunks.push(e.data); };
        rec.onstop = function () {
          window.clearInterval(st.tick);
          stopStream();
          recBtn.textContent = '🔁 重录';
          recBtn.classList.remove('vr-recording');
          var blob = new Blob(st.chunks, { type: rec.mimeType || 'audio/webm' });
          if (!blob.size) { setStatus('没录到声音，再试一次吧', 'warn'); return; }
          st.blob = blob;
          showPreview(blob);
          send(blob, 'rec.' + extOf(blob, ''));
        };
        rec.start();
        st.startedAt = Date.now();
        recBtn.textContent = '⏹ 停止';
        recBtn.classList.add('vr-recording');
        setStatus('正在录音…（最长 ' + maxSeconds + ' 秒，到点自动停）');
        st.tick = window.setInterval(function () {
          var s = Math.floor((Date.now() - st.startedAt) / 1000);
          setStatus('正在录音… ' + fmtSec(s) + '（点「⏹ 停止」结束，最长 ' + maxSeconds + ' 秒）');
          if (s >= maxSeconds) { try { rec.stop(); } catch (e) { /* 忽略 */ } }
        }, 500);
      }).catch(function (e) {
        setStatus('用不了麦克风（' + ((e && e.message) || e) + '）。可以在手机上用自带「录音机」录好，再点「📁 上传录音」。', 'warn');
      });
    }

    recBtn.addEventListener('click', function () {
      if (st.recorder && st.recorder.state === 'recording') { st.recorder.stop(); return; }
      startRec();
    });

    upBtn.addEventListener('click', function () { fileEl.click(); });

    fileEl.addEventListener('change', function () {
      var file = fileEl.files && fileEl.files[0];
      if (!file) return;
      if (st.recorder && st.recorder.state === 'recording') { try { st.recorder.stop(); } catch (e) { /* 忽略 */ } }
      st.blob = file;
      showPreview(file);
      recBtn.textContent = '🔁 重录';
      send(file, file.name || ('rec.' + extOf(file, file.name)));
    });

    retryBtn.addEventListener('click', function () {
      if (st.blob) send(st.blob, 'rec.' + extOf(st.blob, ''));
    });

    // 「🗑 删除」：还没存上时只清掉本地预览；已经存好的那条连服务器上的音频和文字一起删掉。
    delBtn.addEventListener('click', function () {
      var rec = st.last;
      if (!rec) { reset(); return; }
      if (!window.confirm('删除这条录音？音频和文字都会删掉，删了就找不回来。')) return;
      delBtn.setAttribute('disabled', 'disabled');
      setStatus('正在删除…');
      remove(rec.id).then(function () {
        reset(true);
        setStatus('这条录音已删除（下方列表也已更新）', 'ok');
        if (opts.onDeleted) { try { opts.onDeleted(rec.id); } catch (e) { /* 忽略 */ } }
      }).catch(function (e) {
        setStatus('没删掉：' + ((e && e.message) || e), 'err');
      }).then(function () { delBtn.removeAttribute('disabled'); });
    });

    serverAvailable(true);
    return {
      el: root,
      reset: reset,
      setStatus: setStatus,
      last: function () { return st.last; }
    };
  }

  /** 取某场景的语音记录 */
  function list(opts) {
    opts = opts || {};
    var qs = [];
    if (opts.scope) qs.push('scope=' + encodeURIComponent(opts.scope));
    if (opts.date) qs.push('date=' + encodeURIComponent(opts.date));
    qs.push('limit=' + (opts.limit || 50));
    return fetch('/api/voice?' + qs.join('&'), { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (j) { return (j && j.records) || []; })
      .catch(function () { return []; });
  }

  /** 改某条记录的文字 */
  function updateText(id, text) {
    return fetch('/api/voice/text', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: id, text: text })
    }).then(function (r) { return r.json(); })
      .then(function (j) {
        if (!j || !j.ok) throw new Error((j && j.error) || '保存失败');
        return j.record;
      });
  }

  /** 删掉某条记录（服务器上索引与音频文件一起删；删了就找不回来） */
  function remove(id) {
    return fetch('/api/voice/delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: id })
    }).then(function (r) { return r.json(); })
      .then(function (j) {
        if (!j || !j.ok) throw new Error((j && j.error) || '删除失败');
        return j;
      });
  }

  /** 把某场景的语音记录渲染成一个列表（可播放、可改文字、可删除） */
  function listInto(mount, opts) {
    opts = opts || {};
    injectCss();
    var host = q(mount);
    if (!host) return Promise.resolve([]);
    var editable = opts.editable !== false;
    var deletable = opts.deletable !== false;
    var player = new Audio();
    var cur = null;

    function render() {
      list(opts).then(function (records) {
        if (!records.length) {
          if (cur) { try { player.pause(); } catch (e) { /* 忽略 */ } cur = null; }
          host.innerHTML = '<div class="vr-empty">' + esc(opts.empty || '还没有语音记录') + '</div>';
          return;
        }
        if (cur && !records.filter(function (r) { return r.id === cur; }).length) {
          try { player.pause(); } catch (e) { /* 忽略 */ }
          cur = null;
        }
        host.innerHTML = '<div class="vr-list">' + records.map(function (r) {
          var t = r.text || r.asr || '（这段没听清）';
          return '<div class="vr-item" data-id="' + esc(r.id) + '">' +
            '<button class="vr-play" type="button" title="播放">▶️</button>' +
            '<div class="vr-body"><div class="vr-t">' + esc(t) + '</div>' +
            '<div class="vr-m">' + esc(r.date || '') + (r.seconds ? ' · ' + fmtSec(r.seconds) : '') +
            (r.asrOk === false ? ' · 识别未成功' : '') + '</div></div>' +
            (editable ? '<button class="vr-edit" type="button" title="改文字">✏️</button>' : '') +
            (deletable ? '<button class="vr-remove" type="button" title="删除这条录音">🗑</button>' : '') +
            '</div>';
        }).join('') + '</div>';

        host.querySelectorAll('.vr-item').forEach(function (item) {
          var id = item.getAttribute('data-id');
          var rec = records.filter(function (r) { return r.id === id; })[0] || {};
          item.querySelector('.vr-play').addEventListener('click', function () {
            if (cur === id) { player.pause(); cur = null; return; }
            player.src = rec.url || '';
            player.play().catch(function () { });
            cur = id;
          });
          var editBtn = item.querySelector('.vr-edit');
          if (editBtn) {
            editBtn.addEventListener('click', function () {
              var body = item.querySelector('.vr-body');
              body.innerHTML = '<textarea class="vr-editbox"></textarea>' +
                '<div class="vr-editactions"><button class="vr-mini vr-save" type="button">保存</button>' +
                '<button class="vr-mini vr-cancel" type="button">取消</button></div>';
              var box = body.querySelector('.vr-editbox');
              box.value = rec.text || rec.asr || '';
              box.focus();
              body.querySelector('.vr-cancel').addEventListener('click', render);
              body.querySelector('.vr-save').addEventListener('click', function () {
                updateText(id, box.value).then(function () { render(); })
                  .catch(function (e) { alert('没保存上：' + e.message); });
              });
            });
          }
          var delBtn = item.querySelector('.vr-remove');
          if (delBtn) {
            delBtn.addEventListener('click', function () {
              if (!window.confirm('删除这条录音？音频和文字都会删掉，删了就找不回来。')) return;
              delBtn.setAttribute('disabled', 'disabled');
              remove(id).then(function () {
                render();
                if (opts.onDeleted) { try { opts.onDeleted(id); } catch (e) { /* 忽略 */ } }
              }).catch(function (e) {
                delBtn.removeAttribute('disabled');
                alert('没删掉：' + ((e && e.message) || e));
              });
            });
          }
        });
      });
    }

    render();
    return Promise.resolve(host);
  }

  global.Voice = {
    attach: attach,
    list: list,
    listInto: listInto,
    updateText: updateText,
    remove: remove,
    serverAvailable: serverAvailable,
    today: todayStr
  };
})(window);

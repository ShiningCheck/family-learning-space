# -*- coding: utf-8 -*-
"""成长家园 · 本地语音识别（ASR）引擎

页面录下 / 手机上传的语音，在这里转成文字，做到「文字和语音都留档」。
全部在本机 CPU 上跑（faster-whisper），音频不出电脑、不需要联网。

对外接口只有四个：
    available()                     引擎是否可用（装了 faster-whisper + 有本地模型）
    warmup()                        后台预热模型（服务器启动时调用，别让第一位用户干等）
    transcribe(path, lang="zh")     把音频文件转成文字
    status()                        当前引擎状态（给 GET /api/voice/status 用）

模型选择顺序：环境变量 SHAN_ASR_MODEL > small > base > tiny，且**优先用本机已下好的**，
避免离线环境下卡在下载上。模型只加载一次，之后每条录音几秒出结果。
"""
import os
import threading
import time

_MODELS = {}                       # 规格 → 已加载模型（不同用途可用不同规格，各自缓存、互不覆盖）
_MODEL_NAME = ""
_WARMED = False                    # 预热只跑一次（要预热两份模型，不能用 _STATE 判断）
_LOAD_LOCK = threading.Lock()      # 只允许一个线程加载模型
_INFER_LOCK = threading.Lock()     # 推理串行：多路录音同时来时不抢 CPU（线程会排队，不会报错）
_STATE = {
    "loading": False,
    "ready": False,
    "error": "",
    "lastMs": 0,
    "count": 0,
    "warmedAt": "",
}

# 中文识别加一句提示语，whisper 才会正常断句加标点（实测差别很大）
PROMPT_ZH = "小朋友在说中文，请用正确的标点符号。"
PROMPT_EN = "A young child speaking English."

_PREFERRED = ["small", "base", "tiny", "medium"]

# 英语跟读专用的快速规格：短句识别足够准，实测比默认规格快约 4 倍
# （6 秒音频：small 约 12 秒 → base 约 3 秒）。想更准可设 SHAN_ASR_MODEL_EN=small。
_FAST_EN = (os.environ.get("SHAN_ASR_MODEL_EN") or "base").strip()


def _beam_size():
    """默认贪心解码（beam=1）：实测中文质量与 beam=5 几乎一致，速度快约三成。"""
    try:
        return max(1, min(5, int(os.environ.get("SHAN_ASR_BEAM") or 1)))
    except Exception:
        return 1


def _cpu_threads():
    """推理线程数：默认用满物理核（上限 8），可设 SHAN_ASR_THREADS 覆盖。"""
    try:
        v = int(os.environ.get("SHAN_ASR_THREADS") or 0)
    except Exception:
        v = 0
    if v > 0:
        return v
    return max(1, min(8, os.cpu_count() or 4))


def available():
    """faster-whisper 是否可用（只查库，不加载模型）。"""
    try:
        import importlib.util
        return importlib.util.find_spec("faster_whisper") is not None
    except Exception:
        return False


def _cache_root():
    root = os.environ.get("HF_HUB_CACHE") or os.environ.get("HUGGINGFACE_HUB_CACHE")
    if root:
        return root
    hf_home = os.environ.get("HF_HOME")
    if hf_home:
        return os.path.join(hf_home, "hub")
    return os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "hub")


def _cached_sizes():
    """本机已下载的 faster-whisper 模型（Systran 官方转档）。"""
    out = []
    root = _cache_root()
    prefix = "models--Systran--faster-whisper-"
    try:
        for name in os.listdir(root):
            if name.startswith(prefix):
                out.append(name[len(prefix):])
    except Exception:
        pass
    return out


def _candidates():
    env = (os.environ.get("SHAN_ASR_MODEL") or "").strip()
    order = ([env] if env else []) + [s for s in _PREFERRED if s != env]
    cached = _cached_sizes()
    if cached:
        picked = [s for s in order if s in cached]
        rest = [s for s in cached if s not in picked]
        return picked + rest
    # 本机一个都没下过：只试最小的两个，避免长时间卡在下载
    return [env or "small", "base"]


def _load(size=None):
    """加载模型（幂等，按规格分别缓存）。size 为空时按默认顺序挑；失败抛异常。

    不同用途用不同规格、各自缓存、互不覆盖：中文语音笔记走默认（质量优先），
    英语跟读走 _FAST_EN（短句够准、快约 4 倍）。size 在本机没下过时自动下载。
    """
    global _MODEL_NAME
    want = [size] if size else _candidates()
    for s in want:
        if s in _MODELS:
            return _MODELS[s]
    with _LOAD_LOCK:
        for s in want:                       # 双重检查：可能已被别的线程加载
            if s in _MODELS:
                return _MODELS[s]
        _STATE["loading"] = True
        _STATE["error"] = ""
        cached = _cached_sizes()
        last_err = None
        for s in want:
            try:
                from faster_whisper import WhisperModel
                model = WhisperModel(
                    s,
                    device="cpu",
                    compute_type="int8",
                    cpu_threads=_cpu_threads(),
                    local_files_only=(s in cached) if cached else False,
                )
                _MODELS[s] = model
                if not _MODEL_NAME:
                    _MODEL_NAME = s
                _STATE["ready"] = True
                _STATE["loading"] = False
                _STATE["warmedAt"] = time.strftime("%Y-%m-%d %H:%M:%S")
                return model
            except Exception as e:  # 换下一个候选模型
                last_err = e
        _STATE["loading"] = False
        _STATE["error"] = "%s: %s" % (type(last_err).__name__, last_err)
        raise RuntimeError("语音识别模型加载失败：%s" % _STATE["error"])


def _model_name(model):
    """反查某份已加载模型对应的规格名（给返回体里的 model 字段用）。"""
    for k, v in _MODELS.items():
        if v is model:
            return k
    return _MODEL_NAME


def warmup():
    """后台预热（服务器启动时调用一次）。失败不影响服务器，只是第一条录音会慢。

    预热两份：默认规格（中文语音笔记）与英语跟读的快速规格，这样第一条跟读
    也不用等模型加载（实测加载一份要二十几秒）。
    """
    global _WARMED
    if not available():
        _STATE["error"] = "未安装 faster-whisper"
        return
    if _WARMED:
        return
    _WARMED = True
    t = threading.Thread(target=_warmup_worker, name="asr-warmup", daemon=True)
    t.start()


def _warmup_worker():
    for size in (None, _FAST_EN):
        label = size or "默认"
        try:
            _load(size)
            print("[asr] 语音识别模型已就绪：%s（本机离线识别）" % label)
        except Exception as e:
            print("[asr] 语音识别模型预热失败（%s）：%s" % (label, e))


def _tidy_zh(text):
    """中文结果里偶尔夹着多余空格；汉字之间不留空格，读起来更像人写的。"""
    out = []
    prev_cjk = False
    for ch in text:
        is_cjk = "\u4e00" <= ch <= "\u9fff"
        if ch == " " and prev_cjk:
            continue
        out.append(ch)
        prev_cjk = is_cjk
    return "".join(out).strip()


def transcribe(path, lang="zh", prompt=None, word_timestamps=False, size=None):
    """把音频转成文字。

    返回 {"ok": True, "text": ..., "lang": ..., "seconds": ..., "model": ..., "elapsedMs": ...,
          "words": [{"word": ..., "start": ..., "end": ..., "prob": ...}, ...]}
    识别不出来（没说话 / 听不清）时 ok=True 且 text 为空字符串，不算失败。
    失败时 {"ok": False, "error": ...}，调用方保留音频、提示手写即可。

    word_timestamps=True 时额外给出逐词时间戳与置信度（跟读评分用：算流利度、逐词对错）；
    默认 False，行为与以前完全一致（words 为空数组）。
    size 指定模型规格（如 "small"）；英文不传时自动用快速规格（跟读短句够准、快约 2.7 倍），
    该规格本机不可用时自动退回默认规格（质量优先），不会因此让识别失败。
    """
    if not available():
        return {"ok": False, "error": "本机未安装 faster-whisper"}
    if not path or not os.path.isfile(path):
        return {"ok": False, "error": "音频文件不存在"}
    if os.path.getsize(path) == 0:
        return {"ok": False, "error": "音频文件为空"}

    language = (lang or "").strip() or None
    if language not in ("zh", "en"):
        language = None
    if prompt is None:
        prompt = PROMPT_ZH if language == "zh" else (PROMPT_EN if language == "en" else PROMPT_ZH)

    # 英文短句（跟读评分）没显式指定规格时，优先用快速规格：实测比默认 small 快约 2.7 倍。
    # 该规格在本机不可用（没下过、离线装不上）时自动退回默认候选，绝不因此让跟读失败。
    if size is None and language == "en":
        size = _FAST_EN
    try:
        model = _load(size)
    except Exception:
        try:
            model = _load(None)
        except Exception as e:
            return {"ok": False, "error": str(e)}

    t0 = time.time()
    words = []
    try:
        with _INFER_LOCK:
            segments, info = model.transcribe(
                path,
                language=language,
                beam_size=_beam_size(),
                vad_filter=True,
                initial_prompt=prompt,
                condition_on_previous_text=False,
                temperature=0.0,
                word_timestamps=bool(word_timestamps),
            )
            parts = []
            for s in segments:
                parts.append(s.text)
                if word_timestamps:
                    for w in (getattr(s, "words", None) or []):
                        words.append({
                            "word": (getattr(w, "word", "") or "").strip(),
                            "start": round(float(getattr(w, "start", 0) or 0), 2),
                            "end": round(float(getattr(w, "end", 0) or 0), 2),
                            "prob": round(float(getattr(w, "probability", 0) or 0), 3),
                        })
            text = "".join(parts).strip()
    except Exception as e:
        _STATE["error"] = "%s: %s" % (type(e).__name__, e)
        return {"ok": False, "error": "识别失败：%s" % e}

    elapsed = int((time.time() - t0) * 1000)
    if (info.language or "").startswith("zh"):
        text = _tidy_zh(text)
    _STATE["lastMs"] = elapsed
    _STATE["count"] = _STATE.get("count", 0) + 1
    return {
        "ok": True,
        "text": text,
        "lang": info.language or language or "",
        "seconds": round(float(info.duration or 0), 1),
        "model": _model_name(model),
        "elapsedMs": elapsed,
        "words": words,
    }


def status():
    return {
        "engine": "faster-whisper" if available() else "",
        "available": available(),
        "model": _MODEL_NAME,
        "ready": bool(_STATE["ready"]),
        "loading": bool(_STATE["loading"]),
        "error": _STATE["error"],
        "count": _STATE["count"],
        "lastMs": _STATE["lastMs"],
        "warmedAt": _STATE["warmedAt"],
        "cachedModels": _cached_sizes(),
    }

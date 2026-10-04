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

_MODEL = None
_MODEL_NAME = ""
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


def _beam_size():
    """默认贪心解码（beam=1）：实测中文质量与 beam=5 几乎一致，速度快约三成。"""
    try:
        return max(1, min(5, int(os.environ.get("SHAN_ASR_BEAM") or 1)))
    except Exception:
        return 1


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


def _load():
    """加载模型（幂等）。返回 model；失败抛异常。"""
    global _MODEL, _MODEL_NAME
    if _MODEL is not None:
        return _MODEL
    with _LOAD_LOCK:
        if _MODEL is not None:
            return _MODEL
        _STATE["loading"] = True
        _STATE["error"] = ""
        last_err = None
        cached = _cached_sizes()
        for size in _candidates():
            try:
                from faster_whisper import WhisperModel
                model = WhisperModel(
                    size,
                    device="cpu",
                    compute_type="int8",
                    local_files_only=(size in cached) if cached else False,
                )
                _MODEL = model
                _MODEL_NAME = size
                _STATE["ready"] = True
                _STATE["loading"] = False
                _STATE["warmedAt"] = time.strftime("%Y-%m-%d %H:%M:%S")
                return _MODEL
            except Exception as e:  # 换下一个候选模型
                last_err = e
        _STATE["loading"] = False
        _STATE["error"] = "%s: %s" % (type(last_err).__name__, last_err)
        raise RuntimeError("语音识别模型加载失败：%s" % _STATE["error"])


def warmup():
    """后台预热（服务器启动时调用一次）。失败不影响服务器，只是第一条录音会慢。"""
    if not available():
        _STATE["error"] = "未安装 faster-whisper"
        return
    if _STATE["ready"] or _STATE["loading"]:
        return
    t = threading.Thread(target=_warmup_worker, name="asr-warmup", daemon=True)
    t.start()


def _warmup_worker():
    try:
        _load()
        print("[asr] 语音识别模型已就绪：%s（本机离线识别）" % _MODEL_NAME)
    except Exception as e:
        print("[asr] 语音识别模型预热失败：%s" % e)


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


def transcribe(path, lang="zh", prompt=None):
    """把音频转成文字。

    返回 {"ok": True, "text": ..., "lang": ..., "seconds": ..., "model": ..., "elapsedMs": ...}
    识别不出来（没说话 / 听不清）时 ok=True 且 text 为空字符串，不算失败。
    失败时 {"ok": False, "error": ...}，调用方保留音频、提示手写即可。
    """
    if not available():
        return {"ok": False, "error": "本机未安装 faster-whisper"}
    if not path or not os.path.isfile(path):
        return {"ok": False, "error": "音频文件不存在"}
    if os.path.getsize(path) == 0:
        return {"ok": False, "error": "音频文件为空"}
    try:
        model = _load()
    except Exception as e:
        return {"ok": False, "error": str(e)}

    language = (lang or "").strip() or None
    if language not in ("zh", "en"):
        language = None
    if prompt is None:
        prompt = PROMPT_ZH if language == "zh" else (PROMPT_EN if language == "en" else PROMPT_ZH)

    t0 = time.time()
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
            )
            text = "".join(s.text for s in segments).strip()
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
        "model": _MODEL_NAME,
        "elapsedMs": elapsed,
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

# -*- coding: utf-8 -*-
"""辅导班英语 · 跟读评分引擎

把「孩子跟读的录音」和「目标句子」比出分数：总分 + 准确度 / 流利度 / 完整度 + 逐词对错。
默认**完全本机离线**：文字与逐词时间戳来自 asr.py（faster-whisper），音频不出电脑。

云端评测是**可插拔的可选项**：在内容文件 english_class.json 的 speechEval 里配置
provider / endpoint / apiKey 后才会走云端；没配置（默认）就一律走本机。
云端只是把「音频 + 目标文字」POST 到用户自己的评测服务，期望返回
{"score":0-100,"accuracy":0-100,"fluency":0-100,"completeness":0-100,"words":[{"word":..,"ok":true}]}；
任何异常都回退本机，绝不让跟读因为云端不可用而卡住。

纯标准库实现，无第三方依赖，方便随技能一起分发。
"""
import base64
import difflib
import json
import re
import urllib.request

# 标点、符号一律丢掉，只留英文单词与撇号（What's → what's）
_PUNCT = re.compile(r"[^a-z0-9']+")
# 内容块 key（<单元id>:<板块id>:<序号>）只允许安全字符
_KEY_OK = re.compile(r"[^A-Za-z0-9_:-]")

# 常见缩写先展开成完整形式再比：孩子跟读时读的是完整音，写法和读法不该互相扣分
_CONTRACTIONS = {
    "what's": "what is", "it's": "it is", "that's": "that is", "this's": "this is",
    "isn't": "is not", "aren't": "are not", "don't": "do not", "doesn't": "does not",
    "can't": "cannot", "let's": "let us", "i'm": "i am", "i've": "i have",
    "you're": "you are", "we're": "we are", "they're": "they are",
    "he's": "he is", "she's": "she is", "there's": "there is",
    "how's": "how is", "where's": "where is", "who's": "who is", "what're": "what are",
}


def clean_key(raw):
    """跟读记录的 key：<单元id>:<板块id>:<序号>，只留安全字符。"""
    return _KEY_OK.sub("", str(raw or ""))[:80]


def normalize(text):
    s = str(text or "").lower()
    for a, b in (("\u2019", "'"), ("\u2018", "'"), ("\u201c", '"'), ("\u201d", '"')):
        s = s.replace(a, b)
    for k, v in _CONTRACTIONS.items():
        s = re.sub(r"\b" + re.escape(k) + r"\b", v, s)
    s = _PUNCT.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def tokenize(text):
    return [w for w in normalize(text).split(" ") if w]


# 逐词展示用：按**原文写法**取词（保留 It's / What's 与大小写），只去掉标点、破折号。
# 页面上的"逐词参考"必须和上面的原句写法完全一致；缩写展开只发生在内部比对里。
_WORD_RE = re.compile(r"[A-Za-z0-9]+(?:['\u2019][A-Za-z]+)?")


def display_tokens(text):
    return _WORD_RE.findall(str(text or ""))


def _norm_with_owner(text):
    """归一化 token 列表 + 每个 token 属于哪个原文词（缩写 1 个原文词 → 2 个 token）。"""
    norm, owner = [], []
    for i, tok in enumerate(display_tokens(text)):
        for p in tokenize(tok):
            norm.append(p)
            owner.append(i)
    return norm, owner


def _merge_marks(n_disp, owner, marks):
    """把归一化 token 的判定回填到原文词：缩写整块读对才算对，只读对一半记读错。"""
    out = []
    for i in range(n_disp):
        ms = [marks[k] for k in range(len(marks)) if owner[k] == i]
        if ms and all(m == "ok" for m in ms):
            out.append("ok")
        elif any(m == "ok" for m in ms) or "wrong" in ms:
            out.append("wrong")
        else:
            out.append("miss")
    return out


def align(target_words, heard_words):
    """把识别出的词对齐到目标词，给出目标每词的判定 ok / wrong / miss，以及多说的词数。

    用 difflib.SequenceMatcher 做最长公共子序列对齐：孩子漏读的算 miss，
    读错的算 wrong，多说的词计入 extra（会拉低准确度）。
    """
    marks = ["miss"] * len(target_words)
    extra = 0
    sm = difflib.SequenceMatcher(a=target_words, b=heard_words, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i1, i2):
                marks[k] = "ok"
        elif tag == "replace":
            span = min(i2 - i1, j2 - j1)
            for k in range(i1, i1 + span):
                marks[k] = "wrong"
            extra += abs((i2 - i1) - (j2 - j1))
        elif tag == "insert":
            extra += j2 - j1
    return marks, extra


def _fluency(target_words, heard_words, words, seconds):
    """流利度 0~1：语速落在儿童跟读的正常区间就满分，越偏越低，长停顿再扣一点。"""
    if not heard_words:
        return 0.0
    dur, pauses = 0.0, 0
    if words and len(words) >= 2:
        starts = [float(w.get("start") or 0) for w in words]
        ends = [float(w.get("end") or 0) for w in words]
        dur = max(ends) - min(starts)
        gaps = [starts[i + 1] - ends[i] for i in range(len(words) - 1)]
        pauses = sum(1 for g in gaps if g > 0.7)
    elif seconds:
        dur = float(seconds)
    if dur <= 0:
        return 0.75
    rate = len(heard_words) / dur          # 词/秒
    if 1.5 <= rate <= 3.0:                 # 儿童英语跟读的正常语速区间
        base = 1.0
    elif rate < 1.5:
        base = max(0.3, rate / 1.5)
    else:
        base = max(0.4, 1.0 - (rate - 3.0) * 0.2)
    base -= min(0.3, pauses * 0.08)
    return max(0.0, min(1.0, base))


def score_local(target, heard, words=None, seconds=0.0):
    """本机评分。target/heard 是英文句子，words 是 asr 的逐词时间戳（可空）。

    返回 {"score","accuracy","fluency","completeness","targetWords":[{"w","mark"}],"extra"}，
    分数都是 0~100 的整数。目标为空时返回 score=0。
    targetWords 按**原文写法**给出（It's / What's / 大小写照抄），页面上的逐词参考
    与上面的原句完全一致；缩写展开只发生在内部比对里（孩子读全称也不扣分）。
    """
    tw, owner = _norm_with_owner(target)          # 内部比对用：缩写展开、转小写
    dsp = display_tokens(target)                  # 对外展示用：照抄原文写法
    hw = tokenize(heard)
    if not tw:
        return {"score": 0, "accuracy": 0, "fluency": 0, "completeness": 0,
                "targetWords": [], "extra": 0}
    marks, extra = align(tw, hw)
    matched = marks.count("ok")
    completeness = matched / len(tw)
    accuracy = matched / max(len(tw), len(hw))          # 多说的词拉低准确度
    fluency = _fluency(tw, hw, words, seconds)
    total = round(100 * (0.5 * accuracy + 0.3 * completeness + 0.2 * fluency))
    disp_marks = _merge_marks(len(dsp), owner, marks)
    return {
        "score": int(total),
        "accuracy": int(round(accuracy * 100)),
        "fluency": int(round(fluency * 100)),
        "completeness": int(round(completeness * 100)),
        "targetWords": [{"w": dsp[i], "mark": disp_marks[i]} for i in range(len(dsp))],
        "extra": extra,
    }


def cloud_configured(cfg):
    cfg = cfg or {}
    return bool(str(cfg.get("provider") or "").strip() and str(cfg.get("endpoint") or "").strip())


def score_cloud(target, audio_path, cfg, timeout=20):
    """云端评测适配层：把音频 + 目标文字 POST 到用户配置的服务。

    没配置、网络失败、返回不合法 → 返回 None，调用方自动回退本机评分。
    """
    if not cloud_configured(cfg):
        return None
    try:
        with open(audio_path, "rb") as f:
            audio_b64 = base64.b64encode(f.read()).decode("ascii")
    except OSError:
        return None
    payload = json.dumps({
        "text": target,
        "audio": audio_b64,
        "format": "base64",
        "sampleRate": 16000,
    }).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    key = str(cfg.get("apiKey") or "").strip()
    if key:
        headers["Authorization"] = "Bearer " + key
    try:
        req = urllib.request.Request(str(cfg.get("endpoint")), data=payload, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            obj = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    try:
        return {
            "score": int(round(float(obj.get("score") or 0))),
            "accuracy": int(round(float(obj.get("accuracy") or 0))),
            "fluency": int(round(float(obj.get("fluency") or 0))),
            "completeness": int(round(float(obj.get("completeness") or 0))),
            "targetWords": obj.get("targetWords") or [],
            "extra": int(obj.get("extra") or 0),
            "source": "cloud",
        }
    except (TypeError, ValueError):
        return None


def evaluate(target, heard, words=None, seconds=0.0, audio_path="", cfg=None):
    """统一入口：配置了云端就优先云端，否则/失败时用本机。返回结果带 source 字段。"""
    result = None
    if audio_path:
        result = score_cloud(target, audio_path, cfg)
    if result is None:
        result = score_local(target, heard, words, seconds)
        result["source"] = "local"
    return result
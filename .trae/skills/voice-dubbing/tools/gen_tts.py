# -*- coding: utf-8 -*-
"""成长家园 · 朗读音频批量生成（edge-tts）

把页面里需要"读出来"的英文单词/句子和中文提示语，用微软神经语音批量合成 mp3，
放到 <data-root>/web/data/tts/audio/ 下，并生成 <data-root>/web/data/tts/index.json 清单。

页面侧 web/vendor/tts.js 直接按「文本」查清单：
  - 命中 → 播放 mp3（手机不依赖系统语音引擎）
  - 未命中 → 自动降级到浏览器 speechSynthesis

用法：
    python .trae/skills/voice-dubbing/tools/gen_tts.py              # 只补新增/变更的
    python .trae/skills/voice-dubbing/tools/gen_tts.py --dry-run    # 只报告待补多少条，不生成
    python .trae/skills/voice-dubbing/tools/gen_tts.py --force      # 全部重新生成

清单结构（key 就是文本本身，前端零哈希、不易错）：
{
  "version": 1, "generated": "...",
  "voices": {"en": "en-US-JennyNeural", "zh": "zh-CN-XiaoxiaoNeural"},
  "en": {"three": {"f": "a1b2c3d4.mp3", "r": "-25%", "v": "en-US-JennyNeural", "src": "..."}},
  "zh": {"打卡成功！": {...}}
}
"""
import argparse
import asyncio
import glob
import json
import os
import re
import sys
import time

# 注意：edge_tts 在真正需要合成时才导入（见 synth_one）。这个库加载较慢，
# 而"检查有没有新增内容"会被服务器每分钟调用多次，不能每次都付这个代价。

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # voice-dubbing 技能目录
SKILLS_DIR = os.path.dirname(SKILL_DIR)
REPO_ROOT = os.path.dirname(os.path.dirname(SKILLS_DIR))
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))
import data_paths  # noqa: E402

try:
    # 成长家园门户以 data-root 的 web/data 作为静态根（页面用 /data/tts/... 取音频），产物固定放这里
    DATA_DIR = str(data_paths.skill_dir("growth-home") / "data")
except data_paths.DataRootNotConfigured as _exc:
    raise SystemExit("[数据区未配置] %s\n请先在仓库根运行：python setup.py" % _exc)
TTS_DIR = os.path.join(DATA_DIR, "tts")
AUDIO_DIR = os.path.join(TTS_DIR, "audio")
INDEX_FILE = os.path.join(TTS_DIR, "index.json")


def skill_data(skill):
    """某技能的数据目录（data-root 下）。"""
    return str(data_paths.skill_dir(skill) / "data")


def core_data():
    """架构 v2 的 core 命名空间数据目录（统一打卡服务，不属任何技能）。"""
    return str(data_paths.namespace_dir("core") / "data")

VOICE_EN = "en-US-JennyNeural"
VOICE_ZH = "zh-CN-XiaoxiaoNeural"
CHILD_NAME_FALLBACK = "小朋友"
MAX_LEN = 300

# 各页面里固定不变的中文提示语（带姓名/日期的句子由数据推出来，见下面的 collect_* 方法）
FIXED_ZH = [
    # 英语打卡 / 辅导班 / 学校英语
    "英语打卡成功，你真棒！",
    "听说读写全打卡，你真棒！",
    "今天英语听练全打卡，你真棒！",
    # 辅导班跟读：达标即自动打卡（页面 autoCheckin 会念这两句）
    "这一块跟读达标，自动打卡成功！",
    "今天的跟读全部达标，你真棒！",
    # 打卡页
    "录音保存好啦！",
    "请允许使用麦克风",
    "记住啦！",
    "打卡成功！",
    "读完一章，真棒！",
    "已取消，没关系！",
    # 读书打卡（自由阅读 + 书单）
    "自由阅读",
    "书单",
    "读完啦！",
    "这本书读完啦，你是小书虫！",
    # 作业页
    "加入作业啦！",
    "作业保存好啦！",
    # 学习看板
    "今天的好习惯全部完成，太棒啦！",
]

CONCURRENCY = 4
RETRY = 3


def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print("  ! 读不了 %s: %s" % (path, e))
        return None


def normalize(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def file_key(lang, text):
    """文件名用的短哈希（FNV-1a 32 位），只在本脚本里用。"""
    h = 0x811C9DC5
    for b in ("%s|%s" % (lang, text)).encode("utf-8"):
        h ^= b
        h = (h * 0x01000193) & 0xFFFFFFFF
    return "%08x" % h


def is_english(text):
    return bool(re.search(r"[A-Za-z]", text)) and not re.search(r"[\u4e00-\u9fff]", text)


def rate_for(lang, text, kind):
    if lang == "zh":
        return "-10%"
    if kind == "song":
        return "-10%"
    return "-25%" if len(text.split()) <= 3 else "-15%"


class Collector:
    """收集需要合成的文本：(lang, text) -> {rate, src}"""

    def __init__(self, child_name):
        self.items = {}
        self.child = child_name

    def add(self, text, lang, kind, src):
        t = normalize(text)
        if not t or len(t) > MAX_LEN:
            return
        if lang is None:
            lang = "zh" if re.search(r"[\u4e00-\u9fff]", t) else "en"
        if lang == "en" and not is_english(t):
            return
        t = t.replace("{name}", self.child)
        rate = rate_for(lang, t, kind)
        prev = self.items.get((lang, t))
        if prev is None:
            self.items[(lang, t)] = {"rate": rate, "src": src}
        else:
            # 同一句出现在多处时，取更慢的语速
            try:
                if int(rate.rstrip("%")) < int(prev["rate"].rstrip("%")):
                    prev["rate"] = rate
            except ValueError:
                pass

    # ---- 各数据源 ----
    def collect_english_class(self):
        # 内容已随架构 v2 归位到 english-class 技能自己的 data/（不再是 web/data 下的旧副本）
        d = load_json(os.path.join(skill_data("english-class"), "english_class.json")) or {}
        for u in d.get("units", []):
            uid = u.get("id")
            for sec in u.get("sections", []):
                for it in sec.get("items", []):
                    self.add(it.get("en"), "en", "word", "english_class:%s.%s" % (uid, sec.get("id")))
                for s in sec.get("sentences", []):
                    self.add(s.get("en"), "en", "sentence", "english_class:%s.%s" % (uid, sec.get("id")))
            for ln in (u.get("dialogue") or {}).get("lines", []):
                self.add(ln.get("text"), "en", "sentence", "english_class:%s.dialogue" % uid)
            for ln in (u.get("song") or {}).get("lines", []):
                self.add(ln, "en", "song", "english_class:%s.song" % uid)
            for w in (u.get("dictation") or {}).get("words", []):
                self.add(w.get("en"), "en", "word", "english_class:%s.dictation" % uid)

    def collect_fixed_zh(self):
        for p in FIXED_ZH:
            self.add(p, "zh", "phrase", "pages")

    def collect_growth_home_dynamic(self):
        """各学科页（语文/数学/辅导班英语/学校英语）里带科目名、作业名的庆祝语。"""
        # 门户菜单/标签配置已归 core 命名空间（架构 v2），不是 web/data 下的旧副本
        acts = load_json(os.path.join(core_data(), "activities.json")) or {}
        for t in acts.get("tabs", []):
            n = (t.get("name") or "").strip()
            if n:
                self.add("%s打卡成功，你真棒！" % n, "zh", "sentence", "activities")
                self.add("%s全部完成，你是小能手！" % n, "zh", "sentence", "activities")
        for s in acts.get("subjects", []):
            n = (s.get("name") or "").strip()
            if n:
                self.add("%s作业全部完成，你真棒！" % n, "zh", "sentence", "subjects")
        # 作业项已按学科拆到各自技能的 data/homework.json
        for subj in ("subject-chinese", "subject-math", "english-class"):
            hw = load_json(os.path.join(skill_data(subj), "homework.json")) or {}
            for it in hw.get("items", []):
                n = (it.get("name") or "").strip()
                if n:
                    self.add("%s 打卡成功，你真棒！" % n, "zh", "sentence", "homework")

    def collect_booklist(self):
        """书单：每一章的名字都要配音——勾一章就念出这一章叫什么（不是笼统的"读完一章"）。

        新书单同样生效：往 booklist.json 加书加章节，服务器就会自动补上这些音频。
        """
        # 书单已归 reading 技能（架构 v2 第 3 步拆出），读它自己的 data/
        d = load_json(os.path.join(skill_data("reading"), "booklist.json")) or {}
        for b in d.get("books", []):
            for ch in (b.get("chapters") or []):
                self.add(ch, "zh", "word", "booklist")

    def collect_learn_board(self):
        """学习看板：朗读每天"学到什么"。"""
        days_dir = os.path.join(skill_data("learning-growth-board"), "days")
        for path in sorted(glob.glob(os.path.join(days_dir, "*.json"))):
            d = load_json(path) or {}
            for l in d.get("learned", []):
                self.add(l.get("content"), "zh", "sentence", "learn:%s" % d.get("date"))

    def collect_school_bag(self):
        """书包清单：课程名、每样用具、整理完毕的庆祝语。"""
        bag = skill_data("school-bag-organizer")
        req = load_json(os.path.join(bag, "course_requirements.json")) or {}
        for course, items in req.items():
            self.add(course, "zh", "word", "bag:course")
            for it in (items or []):
                self.add(it, "zh", "word", "bag:item")
        cfg = load_json(os.path.join(bag, "config.json")) or {}
        name = (cfg.get("childName") or "").strip() or CHILD_NAME_FALLBACK
        for day in ("今天", "明天"):
            self.add("太棒了%s，书包整理完毕，%s上学开心哦" % (name, day), "zh", "sentence", "bag:done")

    def collect_library(self):
        """家庭图书馆：每本书的"书名＋简介"。"""
        b = load_json(os.path.join(skill_data("home-library"), "books.json")) or {}
        for book in b.get("books", []):
            title = (book.get("title") or "").strip()
            if not title:
                continue
            intro = (book.get("intro") or "").strip()
            self.add(title + "。" + (intro or "这本书还没有简介。"), "zh", "sentence", "library")
            self.add(title + "。", "zh", "sentence", "library")

    def collect_art(self):
        """画作档案：每幅画的"标题＋孩子口述"。"""
        idx = load_json(os.path.join(skill_data("xiaoshan-art-archive"), "index.json"))
        if not isinstance(idx, list):
            return
        for p in idx:
            if not isinstance(p, dict):
                continue
            title = (p.get("title") or "").strip()
            if not title:
                continue
            self.add(title + "。" + (p.get("description") or "").strip(), "zh", "sentence", "art")


def scan_audio():
    """一次扫描拿到 audio 目录里的 {文件名: 字节数}。

    逐个 os.path.exists/getsize 在 Windows（尤其带实时防护的目录）上每次要几毫秒，
    340 多个文件就是好几秒，所以统一用 os.scandir：目录项自带 stat 缓存。
    """
    out = {}
    try:
        with os.scandir(AUDIO_DIR) as it:
            for e in it:
                if not e.name.endswith(".mp3"):
                    continue
                try:
                    out[e.name] = e.stat().st_size
                except OSError:
                    out[e.name] = 1
    except OSError:
        pass
    return out


async def synth_one(text, voice, rate, path, sem, stats):
    import edge_tts      # 延迟导入：没有待补内容时就不用加载这个较重的库
    async with sem:
        for attempt in range(1, RETRY + 1):
            try:
                comm = edge_tts.Communicate(text, voice, rate=rate)
                await comm.save(path)
                if os.path.exists(path) and os.path.getsize(path) > 0:
                    stats["ok"] += 1
                    return True
            except Exception as e:
                if attempt == RETRY:
                    stats["fail"].append((text, str(e)))
                else:
                    await asyncio.sleep(1.2 * attempt)
    return False


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="全部重新生成")
    ap.add_argument("--dry-run", action="store_true", help="只报告待补内容，不生成也不动清单")
    args = ap.parse_args()

    os.makedirs(AUDIO_DIR, exist_ok=True)
    cfg = load_json(os.path.join(DATA_DIR, "config.json")) or {}
    child = (cfg.get("childName") or "").strip() or CHILD_NAME_FALLBACK

    col = Collector(child)
    col.collect_english_class()
    col.collect_fixed_zh()
    col.collect_growth_home_dynamic()
    col.collect_booklist()
    col.collect_learn_board()
    col.collect_school_bag()
    col.collect_library()
    col.collect_art()

    old = load_json(INDEX_FILE) or {}
    manifest = {"version": 1, "voices": {"en": VOICE_EN, "zh": VOICE_ZH}, "en": {}, "zh": {}}

    todo = []
    reused = 0
    files = scan_audio()      # 一次目录扫描拿到文件名与大小：逐文件 stat 在 Windows 上极慢
    for (lang, text), meta in sorted(col.items.items()):
        fk = file_key(lang, text)
        fname = "%s.mp3" % fk
        fpath = os.path.join(AUDIO_DIR, fname)
        prev = (old.get(lang) or {}).get(text)
        entry = {"f": fname, "r": meta["rate"], "v": VOICE_EN if lang == "en" else VOICE_ZH,
                 "src": meta["src"]}
        manifest[lang][text] = entry
        if (not args.force) and prev and prev.get("r") == meta["rate"] and prev.get("v") == entry["v"] \
                and files.get(fname, 0) > 0:
            reused += 1
            continue
        todo.append((lang, text, entry["v"], meta["rate"], fpath))

    chars = sum(len(t) for (_l, t) in col.items.keys())
    print("待合成 %d 条（复用 %d 条），共 %d 字符" % (len(todo), reused, chars))

    if args.dry_run:
        for (lang, text, _v, _r, _p) in todo[:20]:
            print("  [%s] %s" % (lang, text))
        if len(todo) > 20:
            print("  ...还有 %d 条" % (len(todo) - 20))
        print("（--dry-run：未生成任何文件）")
        return

    stats = {"ok": 0, "fail": []}
    if todo:
        sem = asyncio.Semaphore(CONCURRENCY)
        t0 = time.time()
        await asyncio.gather(*[synth_one(t, v, r, p, sem, stats) for (_l, t, v, r, p) in todo])
        print("生成完成 %d 条，用时 %.1fs" % (stats["ok"], time.time() - t0))

    # 清掉不再需要的音频文件
    keep = set()
    for lang in ("en", "zh"):
        for t, e in manifest[lang].items():
            keep.add(e["f"])
    files = scan_audio()
    removed = 0
    for fn in list(files):
        if fn not in keep:
            try:
                os.remove(os.path.join(AUDIO_DIR, fn))
                removed += 1
            except OSError:
                pass

    total_bytes = sum(v for k, v in scan_audio().items())
    manifest["generated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    manifest["stats"] = {"entries": len(manifest["en"]) + len(manifest["zh"]),
                         "en": len(manifest["en"]), "zh": len(manifest["zh"]),
                         "bytes": total_bytes, "generator": "edge-tts"}
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1, sort_keys=True)

    print("英文 %d 条 / 中文 %d 条，音频 %.1f MB，清理旧文件 %d 个"
          % (len(manifest["en"]), len(manifest["zh"]), total_bytes / 1048576.0, removed))
    print("清单: %s" % INDEX_FILE)
    if stats["fail"]:
        print("\n失败 %d �
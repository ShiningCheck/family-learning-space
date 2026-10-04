# -*- coding: utf-8 -*-
"""布置作业 —— 生成 A4 家庭作业 PDF（语文/数学/英语，每科一页）。

用法：
    python gen_homework_pdf.py <内容.json>

内容 JSON 结构（见同目录 example_homework.json）：
{
  "date": "2026-09-22", "dateLabel": "9月22日",
  "chinese": { "chars": [{"c":"七","py":"qī"}, ...], "minutes": 12,
               "readLines": ["...","..."], "recite": {"title":"《咏鹅》...", "lines":["...","..."], "blank": 2} },
  "math":    { "items": ["5 可以分成...", ...], "minutes": 15,
               "image": "教材页绝对路径", "imageLabel": "课本第25页「做一做」第1题" },
  "english": { "sentences": ["Hello! ...", ...], "tip": "...", "minutes": 10 }
}

输出默认写到 <data-root>/web/data/homework_pdf/<date>_homework.pdf（供门户学科页引用）。

排版约定（与孩子实际使用迭代确定，勿随意改）：
- 语文：每个生字占一行，拼音独立画在田字格上方、与上一行格子不重叠；第一个格印示范字，
  其后空田字格自动填满整行（孩子能写几遍写几遍）。
- 数学：摆说题（不印书面算式）+ 教材页图放大。
- 英语：普通句子排版，不用四线格。
"""
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SKILLS_DIR = os.path.dirname(os.path.dirname(_HERE))              # .trae/skills
_REPO_ROOT = os.path.dirname(os.path.dirname(_SKILLS_DIR))         # 仓库根
sys.path.insert(0, os.path.join(_REPO_ROOT, "tools"))
import data_paths  # noqa: E402

from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor

FONTS = r"C:\Windows\Fonts"
pdfmetrics.registerFont(TTFont("KaiTi", os.path.join(FONTS, "simkai.ttf")))
pdfmetrics.registerFont(TTFont("HeiTi", os.path.join(FONTS, "simhei.ttf")))

PAGE_W, PAGE_H = 210 * mm, 297 * mm
INK = HexColor("#4A3B2A")
GRID = HexColor("#B08968")
LIGHT = HexColor("#8D7357")

M = 40


def tianzige(c, cx, cy, size, demo=None):
    c.setStrokeColor(GRID)
    c.setLineWidth(1.1)
    c.rect(cx, cy, size, size)
    c.setDash(3, 3)
    c.setLineWidth(0.6)
    c.line(cx, cy + size / 2, cx + size, cy + size / 2)
    c.line(cx + size / 2, cy, cx + size / 2, cy + size)
    c.setDash()
    if demo:
        c.setFont("KaiTi", size * 0.62)
        c.setFillColor(INK)
        c.drawCentredString(cx + size / 2, cy + size * 0.18, demo)


def draw_title(c, y, main, sub):
    c.setFont("HeiTi", 25)
    c.setFillColor(INK)
    c.drawCentredString(PAGE_W / 2, y, main)
    c.setFont("KaiTi", 12)
    c.setFillColor(LIGHT)
    c.drawCentredString(PAGE_W / 2, y - 19, sub)


def draw_footer(c, y, minutes):
    c.setFont("KaiTi", 12)
    c.setFillColor(LIGHT)
    c.drawString(M, y, "预计用时：约 %d 分钟" % minutes)
    c.drawString(PAGE_W - 250, y, "家长签字：____________________")


def hline(c, x, y, w):
    c.setStrokeColor(GRID)
    c.setLineWidth(1)
    c.line(x, y, x + w, y)


def pinyin_four_line(c, x, y_top, w, h, demo=None):
    """四线三格：4 条横线分成上/中/下三格，示范字写在中格。"""
    gap = h / 3.0
    for i in range(4):
        yy = y_top - i * gap
        c.setStrokeColor(GRID)
        c.setLineWidth(0.8)
        c.line(x, yy, x + w, yy)
    if demo:
        c.setFont("KaiTi", gap)
        c.setFillColor(INK)
        c.drawCentredString(x + w / 2, y_top - 2 * gap, demo)


def _draw_chinese_pinyin(c, data, dateLabel):
    draw_title(c, PAGE_H - 60, "语文作业", dateLabel + " · " + data.get("title", "单韵母 + 朗读"))
    c.setFont("KaiTi", 13)
    c.setFillColor(INK)
    c.drawString(M, PAGE_H - 98, data.get("section1", "一、写单韵母（每字写一行：第一格是示范，后面四线三格自己写）"))

    grid_w, grid_h, gap_b, row_step = 100, 48, 10, 56
    top = PAGE_H - 150
    for ch in data.get("pinyin", []):
        x = M
        for k in range(4):
            pinyin_four_line(c, x, top, grid_w, grid_h, demo=ch if k == 0 else None)
            x += grid_w + gap_b
        top -= row_step

    y = top - 4
    c.setFont("HeiTi", 16)
    c.setFillColor(INK)
    c.drawString(M, y, data.get("readTitle", "二、认读四个声调"))
    y -= 24
    c.setFont("KaiTi", 14)
    for line in data.get("readLines", []):
        c.drawString(M, y, line)
        y -= 22
    draw_footer(c, 36, data.get("minutes", 12))


def draw_chinese(c, data, dateLabel):
    if "pinyin" in data:
        _draw_chinese_pinyin(c, data, dateLabel)
        return
    draw_title(c, PAGE_H - 60, "语文作业", dateLabel + " · " + data.get("title", "写生字 + 朗读"))
    c.setFont("KaiTi", 13)
    c.setFillColor(INK)
    c.drawString(M, PAGE_H - 98, data.get("section1", "一、写生字（每字写一行：第一个是示范，后面空田字格自己写）"))

    size, gap, row_step = 32, 8, 58
    left, right = 42, PAGE_W - 42
    grid_top = PAGE_H - 132
    for item in data.get("chars", []):
        ch, py = item.get("c", ""), item.get("py", "")
        c.setFont("KaiTi", 9)
        c.setFillColor(LIGHT)
        c.drawCentredString(left + size / 2, grid_top + 15, py)
        cy = grid_top - size
        tianzige(c, left, cy, size, demo=ch)
        cx = left + size + gap
        while cx + size <= right:
            tianzige(c, cx, cy, size)
            cx += size + gap
        grid_top -= row_step

    y = grid_top - 2
    c.setFont("HeiTi", 16)
    c.setFillColor(INK)
    c.drawString(M, y, data.get("readTitle", "二、朗读并背诵"))
    y -= 24
    c.setFont("KaiTi", 14)
    for line in data.get("readLines", []):
        c.drawString(M, y, line)
        y -= 22

    recite = data.get("recite") or {}
    if recite.get("title"):
        y -= 4
        c.drawString(M, y, recite["title"])
        y -= 22
        for line in recite.get("lines", []):
            c.drawString(M, y, line)
            y -= 22
    if recite.get("blank"):
        y -= 18
        c.setFont("KaiTi", 12)
        c.setFillColor(LIGHT)
        c.drawString(M, y, "默写（背一背，写一写）：")
        y -= 26
        for _ in range(recite["blank"]):
            hline(c, M, y, PAGE_W - 2 * M)
            y -= 28
    draw_footer(c, 36, data.get("minutes", 12))


def draw_math(c, data, dateLabel):
    draw_title(c, PAGE_H - 60, "数学作业", dateLabel + " · 摆一摆，说一说")
    c.setFont("HeiTi", 16)
    c.setFillColor(INK)
    c.drawString(M, PAGE_H - 104, "一、分与合（用豆子、小棒摆一摆，说给家人听）")
    y = PAGE_H - 142
    c.setFont("KaiTi", 15)
    for t in data.get("items", []):
        c.drawString(M + 16, y, "□  " + t)
        y -= 40

    c.setFont("HeiTi", 16)
    c.drawString(M, y - 6, "二、说图意")
    c.setFont("KaiTi", 15)
    c.drawString(M + 16, y - 38, "□  " + data.get("imagePrompt", "说说图上画了什么，怎样用加法来表示？"))

    img = data.get("image")
    if img and not os.path.isabs(img):
        # 规定：作业数据里的图片一律写**相对路径**（不许写本机绝对路径）。
        # 先按 data-root 解析（教材页图等已迁到仓库外），找不到再回退仓库根。
        try:
            candidate = str(data_paths.resolve(*img.replace("\\", "/").split("/")))
        except Exception:
            candidate = ""
        img = candidate if candidate and os.path.isfile(candidate) else os.path.join(_REPO_ROOT, img)
    if img and os.path.isfile(img):
        img_h = 360
        img_w = 260
        img_y = y - 38 - 26 - img_h
        if img_y < 70:
            img_h = y - 38 - 26 - 70
            img_w = img_h * 0.72
        c.drawImage(img, (PAGE_W - img_w) / 2, img_y, img_w, img_h, preserveAspectRatio=True, anchor="c")
        c.setFont("KaiTi", 11)
        c.setFillColor(LIGHT)
        c.drawCentredString(PAGE_W / 2, img_y - 13, data.get("imageLabel", ""))
    draw_footer(c, 36, data.get("minutes", 15))


def draw_english(c, data, dateLabel):
    draw_title(c, PAGE_H - 60, "英语作业", dateLabel + " · " + data.get("title", "自我介绍"))
    c.setFont("KaiTi", 14)
    c.setFillColor(INK)
    c.drawString(M, PAGE_H - 104, data.get("instruction", "读一读，把空填成自己的信息，大声说给家人听："))
    y = PAGE_H - 160
    c.setFont("KaiTi", 20)
    for s in data.get("sentences", []):
        c.drawString(M, y, s)
        y -= 52
    if data.get("tip"):
        c.setFont("KaiTi", 13)
        c.setFillColor(LIGHT)
        c.drawString(M, y + 12, data["tip"])
    draw_footer(c, 36, data.get("minutes", 10))


def build_pdf(content, out_path):
    c = canvas.Canvas(out_path, pagesize=(PAGE_W, PAGE_H))
    c.setTitle(content.get("dateLabel", "") + " 家庭作业")
    dl = content.get("dateLabel", "")
    if content.get("chinese"):
        draw_chinese(c, content["chinese"], dl); c.showPage()
    if content.get("math"):
        draw_math(c, content["math"], dl); c.showPage()
    if content.get("english"):
        draw_english(c, content["english"], dl); c.showPage()
    c.save()
    return out_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python gen_homework_pdf.py <内容.json>")
        sys.exit(1)
    content = json.load(open(sys.argv[1], encoding="utf-8"))
    if content.get("out"):
        out = os.path.abspath(content["out"])
    else:
        # 默认输出到 growth-home 的作业 PDF 目录（供门户静态托管 + 打卡页引用，落在 data-root）
        out = str(data_paths.skill_dir("growth-home") / "data" / "homework_pdf" /
                  ((content.get("date") or "homework") + "_homework.pdf"))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    build_pdf(content, out)
    print("PDF_OK", out, os.path.getsize(out))

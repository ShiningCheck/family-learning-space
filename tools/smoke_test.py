# -*- coding: utf-8 -*-
"""门户冒烟测试：起一次门户服务器，把每个页面和常用接口点一遍，然后关掉。

为什么需要它：接线（加了一页、改了标签）之后，最容易犯的错是"页面路径写错、
服务器挂载漏了、接口 404" —— 这些肉眼看不出来，但打开就是白屏。每次接线后跑一遍，
5 秒内知道有没有踩坑。read-only，不会改动任何数据。

用法：
  python tools/smoke_test.py                  # 起服务 → 逐页检查 → 关掉
  python tools/smoke_test.py --keep-running   # 检查完不关（留着自己点着看）
  python tools/smoke_test.py --port 8091
"""
import argparse
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GH = ROOT / ".trae" / "skills" / "growth-home"
# 门户 shell 已迁到 portal-core（架构 v2 第 2 步）；服务器文件仍留在 growth-home（第 4 步才换内核）
INDEX = ROOT / "portal-core" / "web" / "index.html"
SERVER = GH / "web" / "preview_server.py"

API_GET = [
    "/api/data", "/api/home", "/api/tracker?tab=reading", "/api/homework",
    "/api/homework/checkins", "/api/library", "/api/class/data", "/api/school/data",
    "/api/feedback/config", "/api/tts/status",
]


def pages_from_index():
    text = INDEX.read_text(encoding="utf-8")
    m = re.search(r"const CORE_TABS = \[(.*?)\n\];", text, re.DOTALL)
    if not m:
        return []
    return re.findall(r"src:\s*'([^']+)'", m.group(1))


def port_busy(port):
    with socket.socket() as s:
        s.settimeout(0.6)
        return s.connect_ex(("127.0.0.1", port)) == 0


def get(url, timeout=15):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, b""
    except Exception as e:  # noqa: BLE001
        return 0, str(e).encode()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def get_no_follow(url, timeout=15):
    """不跟随重定向的 GET：返回 (状态码, 响应头 dict)，用来验证 301。"""
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(url, timeout=timeout) as r:
            return r.status, dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {})
    except Exception:  # noqa: BLE001
        return 0, {}


def wait_ready(port, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        code, _ = get(f"http://127.0.0.1:{port}/api/data", timeout=3)
        if code == 200:
            return True
        time.sleep(0.5)
    return False


def main():
    ap = argparse.ArgumentParser(description="门户冒烟测试")
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--keep-running", action="store_true")
    args = ap.parse_args()

    if not SERVER.is_file():
        print(f"[失败] 找不到 {SERVER}")
        return 2

    proc = None
    reused = port_busy(args.port)
    if reused:
        print(f"[注意] {args.port} 端口已有服务在跑，直接复用它做检查（不会动它）。")
    else:
        env = dict(os.environ, GH_NO_BROWSER="1", GH_PORT=str(args.port))
        proc = subprocess.Popen([sys.executable, str(SERVER)], cwd=str(SERVER.parent),
                                env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        print(f"[启动] 门户服务器（pid {proc.pid}，端口 {args.port}）…")
        if not wait_ready(args.port):
            print("[失败] 服务 30 秒内没起来；看终端输出排查（端口被占、依赖缺失等）。")
            if proc.poll() is None:
                proc.terminate()
            return 1

    base = f"http://127.0.0.1:{args.port}"
    fails = []

    print("\n-- 页面（CORE_TABS 里登记的每一页）")
    for src in pages_from_index():
        path = src.split("?")[0]
        code, body = get(base + src if "?" in src else base + path)
        ok = code == 200 and len(body) > 200
        print(f"   [{'OK' if ok else '失败'}] {src}  →  HTTP {code}，{len(body)} 字节")
        if not ok:
            fails.append(f"页面 {src} 返回 {code}（{len(body)} 字节）")

    print("\n-- 接口（只读）")
    for api in API_GET:
        code, body = get(base + api)
        parsed = False
        if code == 200:
            try:
                json.loads(body.decode("utf-8"))
                parsed = True
            except Exception:  # noqa: BLE001
                parsed = False
        ok = code == 200 and parsed
        print(f"   [{'OK' if ok else '失败'}] {api}  →  HTTP {code}{'' if parsed else '（非 JSON）'}")
        if not ok:
            fails.append(f"接口 {api} 返回 {code}")

    print("\n-- portal-core 静态资产（架构 v2 第 2 步）")
    code, body = get(base + "/vendor/voice.js")
    ok = code == 200 and len(body) > 200
    print(f"   [{'OK' if ok else '失败'}] /vendor/voice.js  →  HTTP {code}，{len(body)} 字节")
    if not ok:
        fails.append(f"/vendor/voice.js 返回 {code}")
    code, body = get(base + "/components/homework-section.js")
    ok = code == 200 and len(body) > 200
    print(f"   [{'OK' if ok else '失败'}] /components/homework-section.js  →  HTTP {code}，{len(body)} 字节")
    if not ok:
        fails.append(f"/components/homework-section.js 返回 {code}")
    code, headers = get_no_follow(base + "/web/vendor/voice.js")
    location = headers.get("Location", "")
    ok = code == 301 and location == "/vendor/voice.js"
    print(f"   [{'OK' if ok else '失败'}] /web/vendor/voice.js  →  HTTP {code}，Location: {location or '（无）'}")
    if not ok:
        fails.append(f"/web/vendor/voice.js 应 301 到 /vendor/voice.js，实际 {code} {location}")

    print("\n-- 新技能页面与统一打卡（架构 v2 第 3 步）")
    new_pages = [
        "/chinese/web/index.html", "/math/web/index.html", "/class/web/index.html",
        "/school/web/index.html", "/reading/web/index.html", "/report/web/index.html",
        "/homework/web/index.html",
    ]
    for path in new_pages:
        code, body = get(base + path)
        ok = code == 200 and len(body) > 200
        print(f"   [{'OK' if ok else '失败'}] {path}  →  HTTP {code}，{len(body)} 字节")
        if not ok:
            fails.append(f"新技能页面 {path} 返回 {code}（{len(body)} 字节）")
    new_apis = [
        "/api/checkins", "/api/chinese/homework", "/api/math/homework",
        "/api/reading/home", "/api/report/data",
    ]
    for api in new_apis:
        code, body = get(base + api)
        parsed = False
        if code == 200:
            try:
                json.loads(body.decode("utf-8"))
                parsed = True
            except Exception:  # noqa: BLE001
                parsed = False
        ok = code == 200 and parsed
        print(f"   [{'OK' if ok else '失败'}] {api}  →  HTTP {code}{'' if parsed else '（非 JSON）'}")
        if not ok:
            fails.append(f"新接口 {api} 返回 {code}")

    print("\n-- 其它入口")
    for extra in ["/textbooks/index.json"]:
        code, body = get(base + extra)
        ok = code == 200
        print(f"   [{'OK' if ok else '提示'}] {extra}  →  HTTP {code}"
              + ("" if ok else "（没下载教材时正常）"))

    if proc and not args.keep_running:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
        print(f"\n[关闭] 已停止临时启动的服务（pid {proc.pid}）")
    elif proc:
        print(f"\n[保留] 服务仍在跑：http://localhost:{args.port}/ （Ctrl+C 或关终端停止）")

    if fails:
        print(f"\n[冒烟不通过] {len(fails)} 项：")
        for f in fails:
            print("  - " + f)
        print("排查建议：页面路径写错 / 兄弟技能挂载没加（tools/portal_wire.py add-page --mount）/ 接口路由漏了")
        return 1
    print("\n[冒烟通过] 所有页面与接口都正常。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

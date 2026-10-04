"""书包整理清单 - 本地预览服务器
启动后，手机和电脑在同一WiFi下，手机浏览器访问电脑IP即可预览。
使用: python preview_server.py

除静态托管外，还承担「用户反馈」的本地出口：
  GET  /api/feedback/config   下发匿名安装ID、应用版本、中转服务地址
  POST /api/feedback          接收页面反馈 -> 落盘 -> 转发到公网中转服务(自动建 GitHub Issue + 推飞书)
  GET  /api/feedback/status   查看本机反馈的送达状态（部署者排查用）
  GET  /api/feedback/retry    手动触发一次补发
反馈必须经过本地服务器转发，是因为浏览器直连第三方接口会被 CORS 拦住；
同时断网时能先落盘、联网后自动补发，一条都不丢。
中转服务地址默认留空：未配置时反馈只存本机 data/feedback/inbox/，绝不外发。

注意：本技能的数据（config、课表、通知、反馈）落在**仓库之外的 data-root**（见
.trae/rules/project_rules.md 第 8 节），通过 tools/data_paths.py 解析。未配置会直接报错。
门户（growth-home）已包含本页全部功能，推荐用 `python setup.py --start` 启动门户。
"""
import http.server
import json
import os
import posixpath
import socket
import socketserver
import sys
import threading
import urllib.parse
import webbrowser

from feedback_backend import FeedbackBackend

PORT = 8090
# 以技能根目录（parent of web/）为代码根，使 /web/checklist.html 可达
DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))       # 代码目录
WORKSPACE_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(DIR)))  # 仓库根
PAGE_URL = "/web/checklist.html"

sys.path.insert(0, os.path.join(WORKSPACE_ROOT, "tools"))
import data_paths  # noqa: E402

try:
    BAG_DATA = str(data_paths.skill_dir("school-bag-organizer") / "data")
except data_paths.DataRootNotConfigured as _exc:
    raise SystemExit("[数据区未配置] %s\n请先在仓库根运行：python setup.py" % _exc)

backend = FeedbackBackend(DIR, PORT, "书包整理清单", data_dir=BAG_DATA)


def get_local_ip():
    """获取本机局域网IP"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def port_in_use(port):
    """启动前探测端口，避免新旧两个服务器同时绑同一端口导致接口随机 404。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.6)
        return s.connect_ex(("127.0.0.1", port)) == 0


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIR, **kwargs)

    def translate_path(self, path):
        path = path.split("?", 1)[0].split("#", 1)[0]
        try:
            path = urllib.parse.unquote(path, errors="surrogatepass")
        except UnicodeDecodeError:
            path = urllib.parse.unquote(path)
        path = posixpath.normpath(path)
        segments = [s for s in path.split("/") if s and s != ".."]
        # 数据 URL /data/… 落在仓库之外的 data-root；页面 /web/… 仍走仓库里的代码目录
        if segments[:1] == ["data"]:
            return os.path.join(BAG_DATA, *segments[1:])
        return super().translate_path(path)

    def send_json(self, obj, status=200):
        payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        route = self.path.split("?", 1)[0]
        if route == "/api/feedback/config":
            return self.send_json(backend.config_payload())
        if route == "/api/feedback/status":
            return self.send_json(backend.status_payload())
        if route == "/api/feedback/retry":
            n = backend.retry_pending_once()
            return self.send_json({"ok": True, "resent": n, "pending": backend.count_pending()})
        return super().do_GET()

    def do_POST(self):
        route = self.path.split("?", 1)[0]
        if route != "/api/feedback":
            return self.send_json({"ok": False, "error": "not_found"}, 404)
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0:
            return self.send_json({"ok": False, "error": "empty_body"}, 400)
        if length > MAX_BODY_BYTES:
            return self.send_json({"ok": False, "error": "payload_too_large"}, 413)
        try:
            body = self.rfile.read(length)
        except Exception as e:
            return self.send_json({"ok": False, "error": "read_failed: %s" % e}, 400)
        try:
            status, resp = backend.handle_post(body, self.client_address[0])
        except Exception as e:
            status, resp = 500, {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}
        return self.send_json(resp, status)

    def log_message(self, format, *args):
        print(f"  -> {args[0]}")


class ThreadingServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    """多线程：转发反馈到公网时可能等十几秒，单线程会把静态页面一起卡住。"""
    daemon_threads = True
    allow_reuse_address = True


def main():
    os.chdir(DIR)
    local_ip = get_local_ip()

    if port_in_use(PORT):
        print("=" * 50)
        print(f"  ⚠️  端口 {PORT} 已被占用，服务器没有启动")
        print("=" * 50)
        print("  多半是之前启动的服务器（或成长家园门户）还在后台运行。")
        print(f"  Windows 查看占用进程: netstat -ano | findstr :{PORT}")
        print("  Windows 结束进程:     taskkill /PID <上面查到的PID> /F")
        print()
        sys.exit(1)

    os.makedirs(backend.inbox, exist_ok=True)
    cfg = backend.config_payload()

    server = ThreadingServer(("0.0.0.0", PORT), Handler)

    print("=" * 50)
    print("  🎒 书包整理清单 - 预览服务器已启动")
    print("=" * 50)
    print(f"  电脑访问: http://localhost:{PORT}{PAGE_URL}")
    print(f"  手机访问: http://{local_ip}:{PORT}{PAGE_URL}")
    print("-" * 50)
    if cfg["relayConfigured"]:
        print("  💌 反馈通道: 已配置，用户建议将自动送达部署者")
    else:
        print("  💌 反馈通道: 未配置中转地址，反馈只存本机 data/feedback/inbox/（绝不外发）")
        print("     配置方法见仓库 feedback-relay/README.md")
    print("  反馈状态: /api/feedback/status")
    print("=" * 50)
    print("  按 Ctrl+C 停止服务器")
    print()

    threading.Thread(target=backend.retry_loop, daemon=True).start()

    webbrowser.open(f"http://localhost:{PORT}{PAGE_URL}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务器已停止。")
        server.shutdown()


if __name__ == "__main__":
    main()

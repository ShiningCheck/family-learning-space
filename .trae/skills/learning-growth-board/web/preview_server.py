"""学习成长看板 - 本地预览服务器
启动后，手机和电脑在同一WiFi下，手机浏览器访问电脑IP即可预览。
使用: python preview_server.py

注意：本技能的数据（config、每日学情、周报）落在**仓库之外的 data-root**（见
.trae/rules/project_rules.md 第 8 节），通过 tools/data_paths.py 解析。未配置会直接报错。
门户（growth-home）已包含本页全部功能，推荐用 `python setup.py --start` 启动门户。
"""
import http.server
import json
import os
import socket
import sys
import webbrowser

PORT = 8091
# Serve the skill root (parent of web/) so that /web/dashboard.html and /api/data are reachable
DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))       # 代码目录
WORKSPACE_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(DIR)))  # 仓库根
PAGE_URL = "/web/dashboard.html"

sys.path.insert(0, os.path.join(WORKSPACE_ROOT, "tools"))
import data_paths  # noqa: E402

try:
    LEARN_DATA = str(data_paths.skill_dir("learning-growth-board") / "data")
except data_paths.DataRootNotConfigured as _exc:
    raise SystemExit("[数据区未配置] %s\n请先在仓库根运行：python setup.py" % _exc)


def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def collect_dir(dir_path):
    items = []
    if os.path.isdir(dir_path):
        for name in sorted(os.listdir(dir_path)):
            if name.endswith(".json"):
                item = load_json(os.path.join(dir_path, name))
                if item is not None:
                    items.append(item)
    return items


def collect_data():
    data_dir = LEARN_DATA
    return {
        "config": load_json(os.path.join(data_dir, "config.json")) or {},
        "days": collect_dir(os.path.join(data_dir, "days")),
        "weekly": collect_dir(os.path.join(data_dir, "weekly")),
    }


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIR, **kwargs)

    def do_GET(self):
        if self.path.split("?")[0] == "/api/data":
            payload = json.dumps(collect_data(), ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        super().do_GET()

    def log_message(self, format, *args):
        print(f"  -> {args[0]}")


def main():
    os.chdir(DIR)
    local_ip = get_local_ip()

    server = http.server.HTTPServer(("0.0.0.0", PORT), Handler)

    print("=" * 50)
    print("  🌱 学习成长看板 - 预览服务器已启动")
    print("=" * 50)
    print(f"  电脑访问: http://localhost:{PORT}{PAGE_URL}")
    print(f"  手机访问: http://{local_ip}:{PORT}{PAGE_URL}")
    print("=" * 50)
    print("  按 Ctrl+C 停止服务器")
    print()

    webbrowser.open(f"http://localhost:{PORT}{PAGE_URL}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务器已停止。")
        server.shutdown()


if __name__ == "__main__":
    main()

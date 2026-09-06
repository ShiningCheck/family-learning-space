"""书包整理清单 - 本地预览服务器
启动后，手机和电脑在同一WiFi下，手机浏览器访问电脑IP即可预览。
使用: python preview_server.py
"""
import http.server
import socket
import os
import sys
import webbrowser

PORT = 8090
# Serve the skill root (parent of web/) so that both /web/checklist.html and /data/*.json are reachable
DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGE_URL = f"/web/checklist.html"


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


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIR, **kwargs)

    def log_message(self, format, *args):
        print(f"  -> {args[0]}")


def main():
    os.chdir(DIR)
    local_ip = get_local_ip()

    server = http.server.HTTPServer(("0.0.0.0", PORT), Handler)

    print("=" * 50)
    print("  🎒 书包整理清单 - 预览服务器已启动")
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
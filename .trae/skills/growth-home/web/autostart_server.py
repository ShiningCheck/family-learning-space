"""成长家园门户 - 开机自启动入口
静默启动服务器（不自动打开浏览器），供开机启动项调用。
"""
import http.server
import os
import sys

WEB_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, WEB_DIR)

import preview_server


def main():
    preview_server.ensure_data_dirs()
    server = http.server.HTTPServer(("0.0.0.0", preview_server.PORT), preview_server.Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

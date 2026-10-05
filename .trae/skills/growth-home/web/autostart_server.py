"""成长家园门户 - 开机自启动入口
静默启动服务器（不自动打开浏览器），供开机启动项调用。

这个脚本由 pythonw.exe 拉起来，没有控制台，出错时看不到任何提示——
所以「启动过程」会写一份日志，出问题能查：
    %LOCALAPPDATA%\\growth-home\\autostart.log
"""
import os
import sys
import tempfile
import traceback
from datetime import datetime

WEB_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, WEB_DIR)

LOG_DIR = os.path.join(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir(), "growth-home")
LOG_PATH = os.path.join(LOG_DIR, "autostart.log")


def log(msg):
    """写一行启动日志；日志本身出问题也绝不影响服务器启动。"""
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass


def main():
    log("启动中… pid=%s" % os.getpid())
    import preview_server          # 放在 log 之后，导入失败也能留下痕迹

    preview_server.ensure_data_dirs()

    # 已经有一个门户在跑（多半是开机自启的上一份还在）就直接退出：
    # Windows 上 SO_REUSEADDR 允许两个进程同时绑同一端口，请求被随机分给新旧两个服务器，
    # 表现为「页面能开但新接口 404」，极难排查，所以这里绝不重复启动。
    if preview_server.port_in_use(preview_server.PORT):
        log("端口 %s 已有服务在跑，本次不重复启动" % preview_server.PORT)
        return

    # 预热本机语音识别模型：自启路径不走 preview_server.main()，缺了这步
    # 第一条跟读/录音要干等模型加载（十几二十秒）。后台线程预热，不阻塞启动。
    if getattr(preview_server, "asr_engine", None) is not None:
        preview_server.asr_engine.warmup()
        log("已触发语音识别模型预热")

    # 必须用多线程版本（ThreadingServer）：语音识别一次要十几二十秒、
    # 转发反馈可能等十几秒，单线程会把整个门户的静态页面一起卡住。
    server = preview_server.ThreadingServer(("0.0.0.0", preview_server.PORT), preview_server.Handler)
    log("已监听 %s:%s，服务就绪" % (server.server_address[0], server.server_address[1]))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    log("服务器已停止")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("启动失败：\n" + traceback.format_exc())
        raise

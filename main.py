"""
小树时钟 — 程序入口

运行方式：
    uv run main.py
    或
    python main.py

URL 唤起：
    已注册 URL Scheme 后，可通过浏览器/命令行访问：
        ltclock://open/alarm
        ltclock://open/timer
        ltclock://open/stopwatch
        ltclock://open/world_time
        ltclock://open/plugin
        ltclock://open/automation
        ltclock://open/settings
"""
import sys
import argparse
from pathlib import Path


# ── 插件本地依赖目录（打包后无系统 Python，插件依赖安装至此处）──────── #
# 在任何插件相关模块导入前注入，确保插件能 import 到自己的依赖
if getattr(sys, "frozen", False):
    _BASE = Path(sys.executable).parent
else:
    _BASE = Path(__file__).resolve().parent
_PLUGIN_LIB_DIR = _BASE / "plugins_ext" / "_lib"
_PLUGIN_LIB_DIR.mkdir(parents=True, exist_ok=True)
_plugin_lib_str = str(_PLUGIN_LIB_DIR)
if _plugin_lib_str not in sys.path:
    sys.path.insert(0, _plugin_lib_str)

from PySide6.QtWidgets import QApplication
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtCore    import QTimer

from app.constants import APP_NAME

_SERVER_NAME = f"{APP_NAME}.SingleInstanceServer"
_SOCKET_TIMEOUT_MS = 1_000


def _parse_url_arg() -> str | None:
    """从命令行参数中提取 --url 值"""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--url", default=None)
    args, _ = parser.parse_known_args()
    return args.url


def _try_forward_to_running(url: str) -> bool:
    """
    尝试把 URL 转发给已运行的实例。
    返回 True 表示已转发（调用方应退出），False 表示无在运行实例。
    """
    sock = QLocalSocket()
    sock.connectToServer(_SERVER_NAME)
    if sock.waitForConnected(_SOCKET_TIMEOUT_MS):
        sock.write(url.encode("utf-8"))
        sock.waitForBytesWritten(_SOCKET_TIMEOUT_MS)
        sock.disconnectFromServer()
        return True
    return False


if __name__ == "__main__":
    app = QApplication(sys.argv)

    url_arg = _parse_url_arg()

    # 单实例检查：无论是否携带 URL，若已有实例运行则退出
    # （打包后 sys.executable 即 app.exe，pip subprocess 会意外再次启动 app，
    #  此处作为兜底，防止 pip 子进程引发无限启动循环）
    if _try_forward_to_running(url_arg or ""):
        sys.exit(0)

    # ── 正常启动 ──────────────────────────────────────────────────────── #
    from app.window import MainWindow

    w = MainWindow()

    # ── 单实例服务：监听其他进程转发来的 URL ──────────────────────────── #
    _server = QLocalServer(app)
    # 若上次异常退出可能残留 socket，先清理
    QLocalServer.removeServer(_SERVER_NAME)
    _server.listen(_SERVER_NAME)

    def _on_new_connection():
        conn = _server.nextPendingConnection()
        if conn and conn.waitForReadyRead(500):
            data = conn.readAll().data().decode("utf-8", errors="ignore").strip()
            if data:
                w.handle_url(data)
            conn.disconnectFromServer()

    _server.newConnection.connect(_on_new_connection)

    # ── 如果本次启动就携带了 URL，等窗口就绪后导航 ─────────────────── #
    if url_arg:
        QTimer.singleShot(1200, lambda: w.handle_url(url_arg))

    sys.exit(app.exec())

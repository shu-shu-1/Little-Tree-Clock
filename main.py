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

启动参数：
    --url <URL>          启动后自动导航到指定 URL
    --boot-menu          强制显示启动选项菜单
    --safe-mode          直接以安全模式启动（不加载插件，不触发自动化）
    --hidden             直接以隐藏模式启动（不显示主窗口，仅托盘）
    --extra-args "..."   透传给程序的自定义参数（可在日志中查看）
"""
import sys
import argparse
import json
import subprocess
import time
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

# ── 启动追踪文件路径 ───────────────────────────────────────────────────── #
_TRACKING_PATH    = _BASE / "temp" / "startup_tracking.json"
_CRASH_WINDOW_SEC = 300   # 在此窗口内（5 分钟）统计崩溃次数
_CRASH_THRESHOLD  = 3     # 超过此次数触发安全启动菜单建议


# ─────────────────────────── 命令行解析 ─────────────────────────────────── #

def _parse_args():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--url",        default=None,  help="启动后自动导航到指定 URL")
    parser.add_argument("--boot-menu",  action="store_true", help="强制显示启动选项菜单")
    parser.add_argument("--safe-mode",  action="store_true", help="直接安全模式启动")
    parser.add_argument("--hidden",     action="store_true", help="直接隐藏启动（仅托盘）")
    parser.add_argument("--extra-args", default="",    help="自定义透传参数")
    args, _ = parser.parse_known_args()
    return args


# ─────────────────────────── 单实例转发 ─────────────────────────────────── #

def _try_forward_to_running(payload: str) -> bool:
    """
    尝试连接已运行的实例并发送 payload。
    返回 True 表示另一个实例正在运行（无论是否发送了内容）；
    返回 False 表示无在运行实例。
    """
    sock = QLocalSocket()
    sock.connectToServer(_SERVER_NAME)
    if not sock.waitForConnected(_SOCKET_TIMEOUT_MS):
        return False
    if payload:
        sock.write(payload.encode("utf-8"))
        sock.waitForBytesWritten(_SOCKET_TIMEOUT_MS)
    sock.disconnectFromServer()
    return True


def _handle_duplicate_with_dialog() -> None:
    """已有实例运行且本次启动无 URL 时，显示重复启动提示对话框。
    该函数始终以 sys.exit() 结束。
    """
    from app.views.boot_menu import AlreadyRunningDialog

    want_restart = AlreadyRunningDialog.show_and_wait()
    if want_restart:
        # 发送 __RESTART__ 给正在运行的实例，令其退出
        _try_forward_to_running("__RESTART__")
        # 等待旧实例退出并释放服务器名称
        time.sleep(1.5)
        # 重新启动本程序（使用同样的参数，但不带任何触发重复检测的状态）
        subprocess.Popen([sys.executable] + sys.argv[1:])

    sys.exit(0)


# ─────────────────────────── 崩溃追踪 ───────────────────────────────────── #

def _load_tracking() -> dict:
    try:
        if _TRACKING_PATH.exists():
            return json.loads(_TRACKING_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"crashes": [], "clean": True}


def _save_tracking(data: dict) -> None:
    try:
        _TRACKING_PATH.parent.mkdir(parents=True, exist_ok=True)
        _TRACKING_PATH.write_text(
            json.dumps(data, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass


def _check_and_record_startup() -> tuple[bool, int]:
    """检查崩溃历史并记录本次启动。

    Returns
    -------
    (should_show_menu, crash_count)
        should_show_menu : 是否因崩溃次数达到阈值而建议显示菜单
        crash_count      : 有效窗口内检测到的崩溃次数
    """
    data    = _load_tracking()
    now     = time.time()
    crashes: list = list(data.get("crashes", []))

    # 上次启动未正常退出 → 视为崩溃，将其 started_at 追加到崩溃列表
    if not data.get("clean", True) and data.get("started_at"):
        crashes.append(float(data["started_at"]))

    # 只保留时间窗口内的记录
    crashes = [t for t in crashes if now - t < _CRASH_WINDOW_SEC]

    # 记录本次启动为"未清洁"（等待正常退出后标记为清洁）
    _save_tracking({
        "crashes":    crashes,
        "started_at": now,
        "clean":      False,
    })

    return len(crashes) >= _CRASH_THRESHOLD, len(crashes)


def _mark_clean_exit() -> None:
    """正常退出时调用，将本次启动标记为清洁退出。"""
    data = _load_tracking()
    data["clean"] = True
    _save_tracking(data)


# ─────────────────────────── 主程序入口 ─────────────────────────────────── #

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)   # 关闭主窗口后不退出（托盘模式需要）

    args = _parse_args()

    # ── 单实例检查 ─────────────────────────────────────────────────────── #
    # （打包后 sys.executable 即 app.exe，pip subprocess 会意外再次启动 app，
    #  此处作为兜底，防止 pip 子进程引发无限启动循环）
    _another_running = _try_forward_to_running(args.url or "")
    if _another_running:
        if args.url:
            # URL 已转发给正在运行的实例，直接退出
            sys.exit(0)
        else:
            # 重复启动但无 URL → 显示提示对话框
            _handle_duplicate_with_dialog()
            # _handle_duplicate_with_dialog 始终以 sys.exit() 结束，不会到达此处

    # ── 崩溃追踪 & 启动菜单决策 ─────────────────────────────────────────── #
    crash_triggered, crash_count = _check_and_record_startup()

    safe_mode   = args.safe_mode
    hidden_mode = args.hidden
    extra_args  = args.extra_args.strip()

    # 已通过 CLI 直接指定模式时，不再弹出菜单
    direct_mode = safe_mode or hidden_mode

    need_menu   = False
    menu_reason = ""

    if not direct_mode:
        # 1. --boot-menu 参数强制显示
        if args.boot_menu:
            need_menu = True
        # 2. 设置中「下次启动打开启动菜单」
        if not need_menu:
            try:
                from app.services.settings_service import SettingsService
                _svc = SettingsService.instance()
                if _svc.show_boot_menu_next_start:
                    need_menu = True
                    menu_reason = "您在上次运行时开启了「下次启动打开启动菜单」选项。"
                    _svc.set_show_boot_menu_next_start(False)  # 仅生效一次
            except Exception:
                pass
        # 3. 崩溃检测达到阈值
        if not need_menu and crash_triggered:
            need_menu = True

    # ── 显示启动菜单 ────────────────────────────────────────────────────── #
    if need_menu:
        from app.views.boot_menu import StartupMenuDialog, BootMode
        result = StartupMenuDialog.ask(
            reason=menu_reason,
            crash_count=crash_count if crash_triggered else 0,
            parent=None,
        )
        if result is None:
            # 用户点「退出程序」
            _mark_clean_exit()
            sys.exit(0)

        mode, custom_args = result
        if mode == BootMode.SAFE:
            safe_mode = True
        elif mode == BootMode.HIDDEN:
            hidden_mode = True
        elif mode == BootMode.CUSTOM:
            extra_args = custom_args

        if extra_args:
            try:
                from app.utils.logger import logger as _logger
                _logger.info("自定义启动参数：{}", extra_args)
            except Exception:
                pass

    # ── 正常启动 ──────────────────────────────────────────────────────── #
    from app.window import MainWindow

    w = MainWindow(safe_mode=safe_mode, hidden_mode=hidden_mode, extra_args=extra_args)

    # ── 单实例服务：监听其他进程转发来的 URL ──────────────────────────── #
    _server = QLocalServer(app)
    # 若上次异常退出可能残留 socket，先清理
    QLocalServer.removeServer(_SERVER_NAME)
    _server.listen(_SERVER_NAME)

    def _on_new_connection():
        conn = _server.nextPendingConnection()
        if conn and conn.waitForReadyRead(500):
            data = conn.readAll().data().decode("utf-8", errors="ignore").strip()
            conn.disconnectFromServer()
            if data == "__RESTART__":
                # 另一个实例请求本实例退出（用户点击了「重启」）
                try:
                    from app.utils.logger import logger as _logger
                    _logger.info("收到重启指令，正在退出...")
                except Exception:
                    pass
                w._quit()
            elif data:
                w.handle_url(data)

    _server.newConnection.connect(_on_new_connection)

    # ── 如果本次启动就携带了 URL，等窗口就绪后导航 ─────────────────── #
    if args.url:
        QTimer.singleShot(1200, lambda: w.handle_url(args.url))

    # ── 正常退出时标记清洁 ────────────────────────────────────────────── #
    app.aboutToQuit.connect(_mark_clean_exit)

    sys.exit(app.exec())

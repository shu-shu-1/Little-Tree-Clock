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
        ltclock://fullscreen/<zone_id>

    说明：插件可在运行期注册新的 ``ltclock://open/<view_key>`` 路由。

启动参数：
    --url <URL>          启动后自动导航到指定 URL
    --open-file <PATH>   启动后按类型打开本地文件（插件包/配置包/布局包）
    --boot-menu          强制显示启动选项菜单
    --safe-mode          直接以安全模式启动（不加载插件，不触发自动化）
    --hidden             直接以隐藏模式启动（不显示主窗口，仅托盘）
    --extra-args "..."   透传给程序的自定义参数（可在日志中查看）

兼容：
    直接把文件路径作为首个位置参数传入时，也会按 ``--open-file`` 处理。
"""
import sys
import argparse
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Optional

from app.constants import APP_NAME, TEMP_DIR

from PySide6.QtWidgets import QApplication
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtCore    import QTimer


if getattr(sys, "frozen", False):
    _BASE = Path(sys.executable).parent
else:
    _BASE = Path(__file__).resolve().parent


# ───────────────────── Windows 启动提权检测（最早阶段）──────────────────────── #

def _is_windows() -> bool:
    return os.name == "nt"


def _is_admin_process() -> bool:
    if not _is_windows():
        return False
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _is_permission_error(exc: BaseException) -> bool:
    if isinstance(exc, PermissionError):
        return True
    if isinstance(exc, OSError):
        winerror = getattr(exc, "winerror", None)
        if winerror in {5, 1314}:  # Access denied / privilege not held
            return True
        if getattr(exc, "errno", None) == 13:
            return True
    return False


def _program_dir_requires_admin() -> bool:
    """检测程序目录是否需要管理员权限写入。"""
    if not _is_windows():
        return False

    probe_path = _BASE / f".ltc_uac_probe_{os.getpid()}_{int(time.time() * 1000)}.tmp"
    try:
        with probe_path.open("w", encoding="utf-8") as fp:
            fp.write("probe")
        return False
    except Exception as exc:
        return _is_permission_error(exc)
    finally:
        try:
            if probe_path.exists():
                probe_path.unlink()
        except Exception:
            pass


def _build_elevated_startup_launch() -> tuple[str, str]:
    forwarded_argv = list(sys.argv[1:])
    if "--elevated-startup" not in forwarded_argv:
        forwarded_argv.insert(0, "--elevated-startup")

    if getattr(sys, "frozen", False):
        exe = str(Path(sys.executable).resolve())
        return exe, subprocess.list2cmdline(forwarded_argv)

    exe = str(Path(sys.executable).resolve())
    main_py = str(Path(__file__).resolve())
    return exe, subprocess.list2cmdline([main_py, *forwarded_argv])


def _try_relaunch_as_admin() -> bool:
    if not _is_windows():
        return False
    try:
        import ctypes

        exe, params = _build_elevated_startup_launch()
        ret = int(ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1))
        return ret > 32
    except Exception:
        return False


def _has_startup_flag(flag: str) -> bool:
    return flag in sys.argv[1:]


def _should_auto_elevate_startup_preflight() -> bool:
    if not _is_windows():
        return False
    if _has_startup_flag("--elevated-file-op"):
        return False
    if _has_startup_flag("--elevated-startup"):
        return False
    if _is_admin_process():
        return False
    return _program_dir_requires_admin()


if __name__ == "__main__" and _should_auto_elevate_startup_preflight():
    if _try_relaunch_as_admin():
        sys.exit(0)


def _is_legacy_internal_main_arg(path_text: Optional[str]) -> bool:
    """识别旧版 URL Scheme 在打包态误注入的 _internal/main.py 参数。"""
    text = str(path_text or "").strip().strip('"')
    if not text:
        return False
    try:
        p = Path(text)
    except Exception:
        return False

    if p.name.lower() != "main.py":
        return False
    parts = [part.lower() for part in p.parts]
    return "_internal" in parts


# ── Windows 命名互斥体（最早阶段单实例守护）────────────────────── #
_STARTUP_MUTEX_NAME = "Global\\LittleTreeClock_StartupMutex"
_startup_mutex_handle = None


def _acquire_startup_mutex() -> bool:
    global _startup_mutex_handle
    if os.name != "nt":
        return True
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        _startup_mutex_handle = kernel32.CreateMutexW(None, True, _STARTUP_MUTEX_NAME)
        if not _startup_mutex_handle:
            return True
        return kernel32.GetLastError() != 183
    except Exception:
        return True


def _wait_for_mutex_release(timeout_sec: float = 15.0) -> bool:
    global _startup_mutex_handle
    if os.name != "nt" or not _startup_mutex_handle:
        return True
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        timeout_ms = int(timeout_sec * 1000)
        result = kernel32.WaitForSingleObject(_startup_mutex_handle, timeout_ms)
        return result in (0, 0x80)
    except Exception:
        return False


_is_first_instance = _acquire_startup_mutex()


# ── 插件本地依赖目录（打包后无系统 Python，插件依赖安装至此处）──────── #
# 在任何插件相关模块导入前注入，确保插件能 import 到自己的依赖
_PLUGIN_LIB_DIR = _BASE / "plugins_ext" / "_lib"
try:
    _PLUGIN_LIB_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    from app.utils.fs import mkdir_with_uac
    mkdir_with_uac(_PLUGIN_LIB_DIR, parents=True, exist_ok=True)
_plugin_lib_str = str(_PLUGIN_LIB_DIR)
if _plugin_lib_str not in sys.path:
    sys.path.insert(0, _plugin_lib_str)



_SERVER_NAME = f"{APP_NAME}.SingleInstanceServer"
_SOCKET_TIMEOUT_MS = 1_000
_PAYLOAD_URL_PREFIX = "URL:"
_PAYLOAD_FILE_PREFIX = "FILE:"

# ── 启动追踪文件路径 ───────────────────────────────────────────────────── #
_TRACKING_PATH    = Path(TEMP_DIR) / "startup_tracking.json"
_CRASH_WINDOW_SEC = 300   # 在此窗口内（5 分钟）统计崩溃次数
_CRASH_THRESHOLD  = 3     # 超过此次数触发安全启动菜单建议


# ─────────────────────────── 命令行解析 ─────────────────────────────────── #

def _parse_args():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--url",        default=None,  help="启动后自动导航到指定 URL")
    parser.add_argument("--open-file",  default=None,  help="启动后打开指定本地文件")
    parser.add_argument("--boot-menu",  action="store_true", help="强制显示启动选项菜单")
    parser.add_argument("--safe-mode",  action="store_true", help="直接安全模式启动")
    parser.add_argument("--hidden",     action="store_true", help="直接隐藏启动（仅托盘）")
    parser.add_argument("--extra-args", default="",    help="自定义透传参数")
    parser.add_argument("--restarting", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--elevated-startup", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--elevated-file-op", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--elevated-file-op-result", default=None, help=argparse.SUPPRESS)
    parser.add_argument("open_path", nargs="?", default=None, help=argparse.SUPPRESS)
    args, _ = parser.parse_known_args()

    # 兼容旧版错误 URL Scheme 启动命令："<exe>" "...\\_internal\\main.py" --url "%1"
    # 打包态下若携带 URL 且位置参数是 _internal/main.py，则视为无效参数并忽略。
    if getattr(sys, "frozen", False) and args.url and _is_legacy_internal_main_arg(args.open_path):
        args.open_path = None

    if not args.elevated_file_op and (not args.open_file) and args.open_path:
        args.open_file = args.open_path
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


def _normalize_open_file_path(raw_path: Optional[str]) -> str:
    text = str(raw_path or "").strip().strip('"')
    if not text:
        return ""
    try:
        return str(Path(text).expanduser())
    except Exception:
        return text


def _build_forward_payload(*, url: Optional[str] = None, open_file: Optional[str] = None) -> str:
    normalized_file = _normalize_open_file_path(open_file)
    if normalized_file:
        return f"{_PAYLOAD_FILE_PREFIX}{normalized_file}"
    if url:
        return f"{_PAYLOAD_URL_PREFIX}{url}"
    return ""


def _decode_forward_payload(payload: str) -> tuple[str, str]:
    if payload.startswith(_PAYLOAD_URL_PREFIX):
        return "url", payload[len(_PAYLOAD_URL_PREFIX):]
    if payload.startswith(_PAYLOAD_FILE_PREFIX):
        return "file", payload[len(_PAYLOAD_FILE_PREFIX):]
    if payload.startswith("ltclock://"):
        return "url", payload
    return "file", payload


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


def _wait_previous_instance_exit(timeout_sec: float = 8.0) -> bool:
    """轮询等待旧实例退出并释放单实例服务。"""
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if not _try_forward_to_running(""):
            return True
        time.sleep(0.1)
    return False


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
        from app.utils.fs import write_text_with_uac

        write_text_with_uac(
            _TRACKING_PATH,
            json.dumps(data, ensure_ascii=False),
            encoding="utf-8",
            ensure_parent=True,
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


def _detect_system_dpi_scale() -> float:
    """在 QApplication 创建之前检测系统 DPI 缩放比例（基于 96 DPI 的倍数）。

    Qt 6 默认开启高 DPI 缩放，会自动按系统 DPI 缩放界面；若此时再设置
    ``QT_SCALE_FACTOR``，Qt 会将其作为**叠加倍率**与系统 DPI 相乘。因此
    需要先获得系统缩放，再把用户期望的目标缩放换算成 Qt 实际需要的倍率。

    Returns
    -------
    float
        系统缩放倍率（如 1.0 / 1.25 / 1.5 / 2.0）。检测失败时返回 1.0。
    """
    # Windows：使用 user32.GetDpiForSystem()
    if os.name == "nt":
        try:
            import ctypes

            user32 = ctypes.windll.user32
            # 仅在尚未声明 DPI 感知时尝试声明，失败不影响 GetDpiForSystem 调用
            try:
                user32.SetProcessDPIAware()
            except Exception:
                pass
            dpi = int(user32.GetDpiForSystem())
            if dpi > 0:
                return dpi / 96.0
        except Exception:
            pass

    # macOS：通常 Retina 为 2.0
    if sys.platform == "darwin":
        try:
            # 通过 CoreGraphics 获取 backingScaleFactor（无需先创建 QApplication）
            from ctypes import c_double, cdll

            appkit = cdll.LoadLibrary(
                "/System/Library/Frameworks/AppKit.framework/AppKit"
            )
            # NSBackingScaleFactor 在 Retina 上为 2.0，普通屏为 1.0
            factor = c_double(1.0)
            try:
                appkit.NSBackingScaleFactorForScreen.restype = c_double
                factor = c_double(appkit.NSBackingScaleFactorForScreen())
            except Exception:
                pass
            if factor.value > 0:
                return float(factor.value)
        except Exception:
            pass

    # Linux/其它平台：暂无可靠的预 Qt 检测手段，回退到 1.0
    return 1.0


def _apply_zoom_scale() -> None:
    """在 QApplication 创建前读取缩放设置并应用 QT_SCALE_FACTOR 环境变量。

    语义：百分比代表用户期望的**最终界面缩放**，而非在系统 DPI 之上叠加。
    例如在系统 DPI 为 150% 的 Windows 上选择 "150%"，应得到 150%（而非
    150% × 150% = 225%）的最终缩放；选择 "Auto" 则跟随系统 DPI。
    """
    try:
        settings_path = _BASE / "config" / "settings.json"
        if not settings_path.exists():
            return
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        zoom = str(data.get("zoom_scale", "Auto")).strip()
        scale_map = {
            "100%": 1.0,
            "125%": 1.25,
            "150%": 1.5,
            "175%": 1.75,
            "200%": 2.0,
        }
        if zoom not in scale_map:
            # "Auto" 或未知值：不设置 QT_SCALE_FACTOR，让 Qt 跟随系统 DPI
            return

        target_scale = scale_map[zoom]
        system_scale = _detect_system_dpi_scale()

        if system_scale <= 0:
            # 检测失败时回退到原来的行为（直接使用目标值）
            os.environ["QT_SCALE_FACTOR"] = f"{target_scale:.4f}"
            return

        # Qt 6 会按系统 DPI 自动缩放，QT_SCALE_FACTOR 是叠加倍率；
        # 要让最终缩放达到 target_scale，需要除以系统缩放比例。
        qt_scale = target_scale / system_scale

        # 确保不会得到极端值（如 0 或负数）
        if qt_scale <= 0.1:
            qt_scale = target_scale

        os.environ["QT_SCALE_FACTOR"] = f"{qt_scale:.4f}"
    except Exception:
        pass


# ─────────────────────────── 主程序入口 ─────────────────────────────────── #

if __name__ == "__main__":
    args = _parse_args()

    if args.elevated_file_op:
        from app.utils.fs import run_elevated_file_operation
        sys.exit(
            run_elevated_file_operation(
                args.elevated_file_op,
                args.elevated_file_op_result,
            )
        )

    _apply_zoom_scale()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    # ── 首实例：立即启动 QLocalServer，最大程度缩短重复启动检测窗口 ── #
    state: dict[str, object] = {
        "main_window": None,
        "first_use_window": None,
        "startup_url": None,
        "startup_open_file": None,
    }
    pending_requests: list[tuple[str, str]] = []
    _server: Optional[QLocalServer] = None

    def _on_new_connection():
        if _server is None:
            return
        conn = _server.nextPendingConnection()
        if conn and conn.waitForReadyRead(500):
            data = conn.readAll().data().decode("utf-8", errors="ignore").strip()
            conn.disconnectFromServer()
            if data == "__RESTART__":
                try:
                    from app.utils.logger import logger as _logger
                    _logger.info("收到重启指令，正在退出...")
                except Exception:
                    pass
                main_window = state.get("main_window")
                if main_window is not None:
                    main_window._quit()
                    return
                first_use_window = state.get("first_use_window")
                if first_use_window is not None:
                    first_use_window.close()
                else:
                    QApplication.quit()
            elif data:
                req_type, payload = _decode_forward_payload(data)
                main_window = state.get("main_window")
                if main_window is not None:
                    if req_type == "file":
                        main_window.handle_open_file(payload)
                    else:
                        main_window.handle_url(payload)
                else:
                    pending_requests.append((req_type, payload))

    def _start_local_server():
        global _server
        QLocalServer.removeServer(_SERVER_NAME)
        _server = QLocalServer(app)
        _server.listen(_SERVER_NAME)
        _server.newConnection.connect(_on_new_connection)

    if _is_first_instance:
        _start_local_server()

    from app.services.settings_service import SettingsService
    from app.services.i18n_service import I18nService
    from app.utils.scroll_utils import install_global_smooth_scroll_controller
    _settings = SettingsService.instance()

    _startup_analysis = None
    if _settings.enable_startup_analysis_next_start:
        try:
            from app.services.startup_analysis_service import StartupAnalysisService
            _startup_analysis = StartupAnalysisService.instance()
            _startup_analysis.begin()
            _startup_analysis.begin_phase("init", "初始化运行环境")
            _settings.set_enable_startup_analysis_next_start(False)
        except Exception:
            _startup_analysis = None

    I18nService.instance().set_language(_settings.language)
    install_global_smooth_scroll_controller(app)

    _startup_splash = None
    if _is_first_instance and not args.hidden:
        try:
            from app.views.startup_splash import StartupSplash
            _startup_splash = StartupSplash(show_detail=_settings.show_startup_detail)
            _startup_splash.present()
            state["startup_splash"] = _startup_splash
        except Exception:
            pass

    def _splash_step(step_key: str) -> None:
        _sp = state.get("startup_splash")
        if _sp is not None:
            try:
                _sp.set_step(step_key)
            except Exception:
                pass

    try:
        from app.utils.logger import logger as _logger
        _logger.info("[启动] 初始化完成 · 单实例服务已就绪")
    except Exception:
        pass

    _splash_step("settings")

    if _startup_analysis is not None:
        try:
            _startup_analysis.end_phase("init")
            _startup_analysis.begin_phase("settings", "加载用户配置")
        except Exception:
            pass

    # ── 单实例检查 ─────────────────────────────────────────────────────── #
    startup_open_file = _normalize_open_file_path(args.open_file)
    startup_url = str(args.url or "").strip()
    state["startup_url"] = startup_url
    state["startup_open_file"] = startup_open_file
    _forward_payload = _build_forward_payload(url=startup_url, open_file=startup_open_file)

    try:
        from app.utils.logger import logger as _logger
        _logger.info("[启动] 单实例检查 · payload={}", repr(_forward_payload[:60] if _forward_payload else "(空)"))
    except Exception:
        pass

    if not _is_first_instance:
        if args.restarting:
            _try_forward_to_running("__RESTART__")
            if _wait_for_mutex_release(timeout_sec=15.0):
                _start_local_server()
            else:
                sys.exit(0)
        else:
            _forwarded = False
            _deadline = time.time() + 30.0
            while time.time() < _deadline:
                if _try_forward_to_running(_forward_payload):
                    _forwarded = True
                    break
                time.sleep(0.15)

            if _forwarded:
                if startup_url or startup_open_file:
                    sys.exit(0)
                else:
                    _handle_duplicate_with_dialog()
            else:
                _handle_duplicate_with_dialog()

    # ── 崩溃追踪 & 启动菜单决策 ─────────────────────────────────────────── #
    crash_triggered, crash_count = _check_and_record_startup()

    safe_mode   = args.safe_mode
    hidden_mode = args.hidden
    extra_args  = args.extra_args.strip()

    direct_mode = safe_mode or hidden_mode

    need_menu   = False
    menu_reason = ""

    if not direct_mode:
        if args.boot_menu:
            need_menu = True
        if not need_menu and _settings.show_boot_menu_next_start:
            need_menu = True
            menu_reason = "您在上次运行时开启了「下次启动打开启动菜单」选项。"
            _settings.set_show_boot_menu_next_start(False)
        if not need_menu and crash_triggered:
            need_menu = True

    if need_menu:
        _sp = state.pop("startup_splash", None)
        if _sp:
            _sp.dismiss()
        from app.views.boot_menu import StartupMenuDialog, BootMode
        result = StartupMenuDialog.ask(
            reason=menu_reason,
            crash_count=crash_count if crash_triggered else 0,
            parent=None,
        )
        if result is None:
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

    # ── 启动窗口（首次启动先打开向导）──────────────────────────────────── #
    from app.window import MainWindow
    from app.views.first_use_setup import FirstUseSetupWindow

    _splash_step("services")
    if _startup_analysis is not None:
        try:
            _startup_analysis.end_phase("settings")
            _startup_analysis.begin_phase("services", "初始化基础服务")
        except Exception:
            pass
    try:
        from app.utils.logger import logger as _logger
        _logger.info("[启动] 开始创建主窗口 · safe={} hidden={}", safe_mode, hidden_mode)
    except Exception:
        pass

    def _show_analysis_report(main_window, analysis_service) -> None:
        try:
            from app.services.startup_analysis_service import StartupAnalysisService
            from app.views.startup_analysis_dialog import StartupAnalysisDialog
            analysis_result = analysis_service.analyze_bottleneck()
            analysis_result["phases"] = analysis_service.phases
            system_info = StartupAnalysisService.collect_system_info()
            export_text = analysis_service.generate_export_text()
            dlg = StartupAnalysisDialog(export_text, analysis_result, system_info, parent=main_window)
            dlg.show()
        except Exception:
            try:
                from app.utils.logger import logger as _logger
                _logger.exception("[启动分析] 显示报告失败")
            except Exception:
                pass

    def _create_main_window() -> None:
        if state.get("main_window") is not None:
            return

        main_window = MainWindow(
            safe_mode=safe_mode,
            hidden_mode=hidden_mode,
            extra_args=extra_args,
            splash_step_callback=_splash_step,
            startup_analysis=_startup_analysis,
        )
        state["main_window"] = main_window

        _splash_step("plugins")

        _sp = state.pop("startup_splash", None)
        if _sp:
            _sp.dismiss()

        if _startup_analysis is not None:
            _sa = _startup_analysis
            _analysis_report_shown = [False]

            def _on_analysis_plugins_done():
                if _analysis_report_shown[0]:
                    return
                _analysis_report_shown[0] = True
                try:
                    _sa.end_phase("plugins")
                    _sa.finish()
                except Exception:
                    pass
                QTimer.singleShot(800, lambda: _show_analysis_report(main_window, _sa))

            main_window._plugin_mgr.scanCompleted.connect(_on_analysis_plugins_done)
            QTimer.singleShot(5000, _on_analysis_plugins_done)

        try:
            from app.utils.logger import logger as _logger
            _logger.info("[启动] 主窗口创建完成，启动画面已关闭")
        except Exception:
            pass

        startup_url = state.get("startup_url")
        if isinstance(startup_url, str) and startup_url:
            QTimer.singleShot(1200, lambda u=startup_url: main_window.handle_url(u))
            state["startup_url"] = None

        startup_open_file = state.get("startup_open_file")
        if isinstance(startup_open_file, str) and startup_open_file:
            QTimer.singleShot(1200, lambda p=startup_open_file: main_window.handle_open_file(p))
            state["startup_open_file"] = None

        if pending_requests:
            def _dispatch_pending_requests() -> None:
                while pending_requests:
                    req_type, payload = pending_requests.pop(0)
                    if not payload:
                        continue
                    if req_type == "file":
                        main_window.handle_open_file(payload)
                    else:
                        main_window.handle_url(payload)

            QTimer.singleShot(1200, _dispatch_pending_requests)

    def _show_first_use_window() -> None:
        _sp = state.pop("startup_splash", None)
        if _sp:
            _sp.dismiss()
        first_use_window = FirstUseSetupWindow()
        state["first_use_window"] = first_use_window

        def _on_setup_completed() -> None:
            state["first_use_window"] = None
            _create_main_window()

        def _on_setup_canceled() -> None:
            state["first_use_window"] = None
            _mark_clean_exit()
            QApplication.quit()

        first_use_window.setupCompleted.connect(_on_setup_completed)
        first_use_window.setupCanceled.connect(_on_setup_canceled)
        first_use_window.show()

    if _settings.first_use_completed:
        _create_main_window()
    else:
        _show_first_use_window()

    app.aboutToQuit.connect(_mark_clean_exit)

    sys.exit(app.exec())

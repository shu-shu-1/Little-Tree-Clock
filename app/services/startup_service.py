r"""开机自启动服务（Windows）。

通过注册表 ``HKCU\Software\Microsoft\Windows\CurrentVersion\Run``
写入启动命令，实现当前用户登录后自动启动应用。
"""
from __future__ import annotations

import sys
from pathlib import Path

from app.utils.logger import logger

_WIN = sys.platform == "win32"
if _WIN:
    import winreg


_RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN_VALUE_NAME = "LittleTreeClock"


def _python_exe() -> str:
    return sys.executable


def _main_script() -> str:
    return str(Path(__file__).resolve().parent.parent.parent / "main.py")


def _startup_command(*, hidden: bool = True) -> str:
    """构建写入注册表的启动命令。"""
    exe = _python_exe()
    if getattr(sys, "frozen", False):
        parts = [f'"{exe}"']
    else:
        parts = [f'"{exe}"', f'"{_main_script()}"']

    if hidden:
        parts.append("--hidden")
    return " ".join(parts)


def is_supported() -> bool:
    """当前平台是否支持开机自启动。"""
    return _WIN


def current_command() -> str:
    """返回当前注册的启动命令；未注册时返回空字符串。"""
    if not _WIN:
        return ""

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY_PATH) as key:
            value, _ = winreg.QueryValueEx(key, _RUN_VALUE_NAME)
        return str(value or "").strip()
    except OSError:
        return ""


def is_enabled() -> bool:
    """是否已注册开机自启动。"""
    return bool(current_command())


def enable(*, hidden: bool = True) -> tuple[bool, str]:
    """开启开机自启动。"""
    if not _WIN:
        return False, "开机自启动仅支持 Windows"

    command = _startup_command(hidden=hidden)
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_KEY_PATH) as key:
            winreg.SetValueEx(key, _RUN_VALUE_NAME, 0, winreg.REG_SZ, command)
        logger.info("开机自启动已开启：{}", command)
        return True, "已开启开机自启动（下次登录 Windows 生效）"
    except Exception as exc:  # noqa: BLE001
        msg = f"开启开机自启动失败：{exc}"
        logger.error(msg)
        return False, msg


def disable() -> tuple[bool, str]:
    """关闭开机自启动。"""
    if not _WIN:
        return False, "开机自启动仅支持 Windows"

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            _RUN_KEY_PATH,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            try:
                winreg.DeleteValue(key, _RUN_VALUE_NAME)
            except FileNotFoundError:
                pass
        logger.info("开机自启动已关闭")
        return True, "已关闭开机自启动"
    except FileNotFoundError:
        return True, "已关闭开机自启动"
    except Exception as exc:  # noqa: BLE001
        msg = f"关闭开机自启动失败：{exc}"
        logger.error(msg)
        return False, msg


def set_enabled(enabled: bool, *, hidden: bool = True) -> tuple[bool, str]:
    """按布尔值开启或关闭开机自启动。"""
    if enabled:
        return enable(hidden=hidden)
    return disable()


def set_enabled_with_settings(enabled: bool) -> tuple[bool, str]:
    """按布尔值开启或关闭开机自启动，根据设置决定是否隐藏到托盘。"""
    from app.services.settings_service import SettingsService
    hidden = SettingsService.instance().autostart_hide_to_tray
    return set_enabled(enabled, hidden=hidden)

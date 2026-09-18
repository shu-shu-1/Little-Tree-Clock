"""运行时执行权限拦截：monkey-patch os.system、os.popen、subprocess.Popen。"""

from __future__ import annotations

import inspect
import os
import subprocess
import threading
from typing import Callable

from app.utils.logger import logger

_permission_checker: Callable[[str, str], bool] | None = None
_original: dict[str, any] = {}
_installed: bool = False

# 线程局部变量：记录当前正在执行的插件 ID
_thread_ctx = threading.local()


def set_current_plugin(plugin_id: str | None) -> None:
    _thread_ctx.plugin_id = plugin_id


def get_current_plugin() -> str | None:
    return getattr(_thread_ctx, "plugin_id", None)


def clear_current_plugin() -> None:
    _thread_ctx.plugin_id = None


def set_permission_checker(checker: Callable[[str, str], bool]) -> None:
    """回调签名 (plugin_id, action_name) -> bool，True 表示允许执行。"""
    global _permission_checker
    _permission_checker = checker


def _find_calling_plugin() -> str | None:
    """优先使用线程局部变量，未设置时回退到调用栈模块名分析。"""
    current = get_current_plugin()
    if current:
        return current

    # 插件模块命名格式: _ltc_plugin_{plugin_key}_{10位hex摘要}
    for frame_info in inspect.stack()[2:]:
        module = inspect.getmodule(frame_info.frame)
        if not module:
            continue
        name = getattr(module, "__name__", "")
        if name.startswith("_ltc_plugin_"):
            parts = name.split("_")
            if len(parts) >= 5:
                digest = parts[-1]
                if len(digest) == 10 and all(c in "0123456789abcdef" for c in digest.lower()):
                    return "_".join(parts[3:-1])
    return None


def _guard_func(func, action_name: str):
    def wrapper(*args, **kwargs):
        plugin_id = _find_calling_plugin()
        if plugin_id and _permission_checker:
            allowed = _permission_checker(plugin_id, action_name)
            if not allowed:
                logger.warning(
                    "插件 '{}' 尝试调用 {} 但无 os_exec 权限，已阻止",
                    plugin_id,
                    action_name,
                )
                raise PermissionError(
                    f"插件 '{plugin_id}' 无执行权限，请在 plugin.json 的 permissions 中声明 \"os_exec\""
                )
        return func(*args, **kwargs)

    return wrapper


def _guard_popen_init(original_init):
    def wrapper(self, *args, **kwargs):
        plugin_id = _find_calling_plugin()
        if plugin_id and _permission_checker:
            allowed = _permission_checker(plugin_id, "subprocess.Popen")
            if not allowed:
                logger.warning(
                    "插件 '{}' 尝试调用 subprocess.Popen 但无 os_exec 权限，已阻止",
                    plugin_id,
                )
                raise PermissionError(
                    f"插件 '{plugin_id}' 无执行权限，请在 plugin.json 的 permissions 中声明 \"os_exec\""
                )
        return original_init(self, *args, **kwargs)

    return wrapper


def install() -> None:
    """安装运行时拦截，幂等。"""
    global _installed, _original
    if _installed:
        return

    _original["os.system"] = os.system
    os.system = _guard_func(os.system, "os.system")

    _original["os.popen"] = os.popen
    os.popen = _guard_func(os.popen, "os.popen")

    _original["subprocess.Popen.__init__"] = subprocess.Popen.__init__
    subprocess.Popen.__init__ = _guard_popen_init(subprocess.Popen.__init__)

    _installed = True
    logger.info("os/subprocess 运行时执行权限拦截已安装")


def uninstall() -> None:
    global _installed, _original
    if not _installed or not _original:
        return

    os.system = _original["os.system"]
    os.popen = _original["os.popen"]
    subprocess.Popen.__init__ = _original["subprocess.Popen.__init__"]
    _original.clear()
    _installed = False
    logger.info("os/subprocess 运行时执行权限拦截已卸载")

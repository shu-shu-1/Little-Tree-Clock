"""运行时执行权限拦截

在应用启动时 monkey-patch os.system、subprocess.Popen 等危险函数，
拦截插件对系统命令的执行，检查 os_exec 权限。

用法
----
    from app.plugins.exec_guard import install, set_permission_checker
    install()
    set_permission_checker(lambda pid, action: check_perm(pid, "os_exec"))

拦截范围
--------
- ``os.system`` / ``os.popen``
- ``subprocess.Popen``（覆盖 ``run`` / ``call`` / ``check_call`` / ``check_output``）

实现原理
--------
1. 全局 monkey-patch 目标函数，替换为带权限检查的包装器。
2. 包装器通过 **线程局部变量** 识别当前调用者属于哪个插件
   （由 :class:`~app.plugins.plugin_manager.PluginManager` 在调用插件代码前主动设置）。
3. 若线程局部变量未设置，回退到 **调用栈分析**，查找模块名是否属于
   ``_ltc_plugin_{key}_{digest}`` 命名空间。
4. 若识别出插件身份，调用外部注入的权限检查回调；
   未识别出（主程序代码）则直接放行。
"""
from __future__ import annotations

import inspect
import os
import subprocess
import threading
from typing import Callable, Dict, Optional

from app.utils.logger import logger

# ── 内部状态 ──────────────────────────────────────────
_permission_checker: Optional[Callable[[str, str], bool]] = None
_original: Dict[str, any] = {}
_installed: bool = False

# 线程局部变量：记录当前正在执行的插件 ID
_thread_ctx = threading.local()


# ── 公共 API ──────────────────────────────────────────

def set_current_plugin(plugin_id: Optional[str]) -> None:
    """在调用插件代码前设置当前插件上下文（线程安全）"""
    _thread_ctx.plugin_id = plugin_id


def get_current_plugin() -> Optional[str]:
    """获取当前线程的插件上下文"""
    return getattr(_thread_ctx, "plugin_id", None)


def clear_current_plugin() -> None:
    """清除当前线程的插件上下文"""
    _thread_ctx.plugin_id = None


def set_permission_checker(checker: Callable[[str, str], bool]) -> None:
    """设置权限检查回调。

    回调签名: ``(plugin_id, action_name) -> bool``
    返回 ``True`` 表示允许执行，``False`` 表示拒绝。
    """
    global _permission_checker
    _permission_checker = checker


# ── 调用溯源 ──────────────────────────────────────────

def _find_calling_plugin() -> Optional[str]:
    """尝试识别当前调用者属于哪个插件。

    优先使用线程局部变量（由 PluginManager 在调用插件代码前设置），
    若未设置则回退到调用栈分析。
    """
    # 方法1: 线程局部变量（最可靠）
    current = get_current_plugin()
    if current:
        return current

    # 方法2: 调用栈分析（回退方案）
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
                if (
                    len(digest) == 10
                    and all(c in "0123456789abcdef" for c in digest.lower())
                ):
                    return "_".join(parts[3:-1])
    return None


# ── 包装器 ──────────────────────────────────────────

def _guard_func(func, action_name: str):
    """函数级包装器（用于 os.system / os.popen 等）"""
    def wrapper(*args, **kwargs):
        plugin_id = _find_calling_plugin()
        if plugin_id and _permission_checker:
            allowed = _permission_checker(plugin_id, action_name)
            if not allowed:
                logger.warning(
                    "插件 '{}' 尝试调用 {} 但无 os_exec 权限，已阻止",
                    plugin_id, action_name,
                )
                raise PermissionError(
                    f"插件 '{plugin_id}' 无执行权限，"
                    f"请在 plugin.json 的 permissions 中声明 \"os_exec\""
                )
        return func(*args, **kwargs)
    return wrapper


def _guard_popen_init(original_init):
    """subprocess.Popen.__init__ 包装器"""
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
                    f"插件 '{plugin_id}' 无执行权限，"
                    f"请在 plugin.json 的 permissions 中声明 \"os_exec\""
                )
        return original_init(self, *args, **kwargs)
    return wrapper


# ── 安装 / 卸载 ──────────────────────────────────────────

def install() -> None:
    """安装运行时拦截。幂等：重复调用无效果。"""
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
    """卸载运行时拦截。"""
    global _installed, _original
    if not _installed or not _original:
        return

    os.system = _original["os.system"]
    os.popen = _original["os.popen"]
    subprocess.Popen.__init__ = _original["subprocess.Popen.__init__"]
    _original.clear()
    _installed = False
    logger.info("os/subprocess 运行时执行权限拦截已卸载")

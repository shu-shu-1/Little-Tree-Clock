"""插件系统 — 统一导出"""
from .base_plugin    import BasePlugin, LibraryPlugin, PluginAPI, PluginMeta, PluginPermission, HookType, PluginType
from .plugin_manager import PluginManager, PluginEntry

__all__ = [
    "BasePlugin",
    "LibraryPlugin",
    "PluginAPI",
    "PluginMeta",
    "PluginPermission",
    "HookType",
    "PluginType",
    "PluginManager",
    "PluginEntry",
]

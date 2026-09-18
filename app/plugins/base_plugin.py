"""插件基类与钩子定义"""

from __future__ import annotations

import json
from abc import ABC
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from datetime import datetime

    from PySide6.QtWidgets import QWidget
    from PySide6.QtGui import QIcon

    try:
        # 类型检查环境可能未安装 qfluentwidgets，回退为 Any
        from qfluentwidgets import FluentIcon as FluentIconBase
    except Exception:
        FluentIconBase = Any

from app.utils.logger import logger
from app.utils.fs import mkdir_with_uac, write_text_with_uac
from app.services.i18n_service import I18nService


class PluginPermission(str, Enum):
    """插件可声明请求的系统权限。"""

    NETWORK = "network"
    FS_READ = "fs_read"
    FS_WRITE = "fs_write"
    OS_EXEC = "os_exec"
    OS_ENV = "os_env"
    CLIPBOARD = "clipboard"
    NOTIFICATION = "notification"
    INSTALL_PKG = "install_pkg"


_SERVICE_PERMISSION_MAP: dict[str, PluginPermission] = {
    "notification_service": PluginPermission.NOTIFICATION,
    "ntp_service": PluginPermission.NETWORK,
}


class HookType(Enum):
    """插件可注册的钩子点"""

    ON_LOAD = auto()
    ON_UNLOAD = auto()
    ON_ALARM_BEFORE = auto()
    ON_ALARM_AFTER = auto()
    ON_TIMER_DONE = auto()
    ON_STOPWATCH_LAP = auto()
    ON_FOCUS_START = auto()
    ON_FOCUS_END = auto()
    CUSTOM_TRIGGER = auto()
    CUSTOM_ACTION = auto()
    SIDEBAR_WIDGET = auto()
    SETTINGS_WIDGET = auto()


class PluginType(Enum):
    """插件类型：功能插件 / 依赖插件。"""

    FEATURE = "feature"
    LIBRARY = "library"


@dataclass
class PluginMeta:
    """插件元数据。"""

    id: str
    name: str
    version: str = "1.0.0"
    author: str = ""
    description: str = ""
    homepage: str = ""
    icon: str = ""
    min_host_version: str = ""
    plugin_type: PluginType = PluginType.FEATURE
    requires: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    name_i18n: dict[str, str] = field(default_factory=dict)
    description_i18n: dict[str, str] = field(default_factory=dict)

    @staticmethod
    def _normalize_i18n_map(data: Any) -> dict[str, str]:
        if not isinstance(data, dict):
            return {}
        result: dict[str, str] = {}
        for k, v in data.items():
            if isinstance(v, str) and v.strip():
                lang = I18nService.normalize_language(str(k))
                result[lang] = v
        return result

    @classmethod
    def _split_localized_text(
        cls,
        value: Any,
        *,
        fallback: str = "",
        explicit_i18n: Any = None,
    ) -> tuple[str, dict[str, str]]:
        i18n_map = cls._normalize_i18n_map(explicit_i18n)
        if isinstance(value, str):
            base = value
            if base and "zh-CN" not in i18n_map and "en-US" not in i18n_map:
                i18n_map["zh-CN"] = base
            return base or fallback, i18n_map
        if isinstance(value, dict):
            i18n_map.update(cls._normalize_i18n_map(value))
            base = i18n_map.get("zh-CN") or i18n_map.get("en-US") or next(iter(i18n_map.values()), "")
            return base or fallback, i18n_map
        return fallback, i18n_map

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PluginMeta":
        name, name_i18n = cls._split_localized_text(
            d.get("name", ""),
            explicit_i18n=d.get("name_i18n"),
        )
        description, description_i18n = cls._split_localized_text(
            d.get("description", ""),
            explicit_i18n=d.get("description_i18n"),
        )
        raw_type = d.get("plugin_type", "feature")
        try:
            ptype = PluginType(raw_type)
        except ValueError:
            logger.warning("plugin.json plugin_type 未知值 '{}', 回退到 feature", raw_type)
            ptype = PluginType.FEATURE
        return cls(
            id=d["id"],
            name=name,
            version=d.get("version", "1.0.0"),
            author=d.get("author", ""),
            description=description,
            homepage=d.get("homepage", ""),
            icon=str(d.get("icon", "") or "").strip(),
            min_host_version=d.get("min_host_version", ""),
            plugin_type=ptype,
            requires=d.get("requires", []),
            dependencies=d.get("dependencies", []),
            tags=d.get("tags", []),
            permissions=d.get("permissions", []),
            name_i18n=name_i18n,
            description_i18n=description_i18n,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "author": self.author,
            "description": self.description,
            "homepage": self.homepage,
            "icon": self.icon,
            "min_host_version": self.min_host_version,
            "plugin_type": self.plugin_type.value,
            "requires": self.requires,
            "dependencies": self.dependencies,
            "tags": self.tags,
            "permissions": self.permissions,
            "name_i18n": self.name_i18n,
            "description_i18n": self.description_i18n,
        }

    def get_name(self, language: str | None = None) -> str:
        lang = I18nService.normalize_language(language)
        return self.name_i18n.get(lang) or self.name_i18n.get("zh-CN") or self.name_i18n.get("en-US") or self.name

    def get_description(self, language: str | None = None) -> str:
        lang = I18nService.normalize_language(language)
        return (
            self.description_i18n.get(lang)
            or self.description_i18n.get("zh-CN")
            or self.description_i18n.get("en-US")
            or self.description
        )


class BasePlugin(ABC):
    """所有插件必须继承此类；主入口类名固定为 ``Plugin``，元数据通过 :attr:`meta` 声明。"""

    # 子类必须覆盖（或由 PluginManager 从 plugin.json 注入）
    meta: PluginMeta

    def on_load(self, api: "PluginAPI") -> None:
        """插件加载时调用，用于注册钩子、触发器、动作等。"""

    def on_unload(self) -> None:
        """插件卸载时调用，用于清理资源、取消订阅等。"""

    def create_settings_widget(self) -> "QWidget | None":
        """返回插件专属的设置面板（嵌入宿主设置页）。"""
        return None

    def create_sidebar_widget(self) -> "QWidget | None":
        """返回插件专属的侧边栏面板，返回 ``None`` 表示不添加导航项。

        宿主仅在需要显示面板时调用一次，返回的 widget 会被持久持有。
        """
        return None

    def get_sidebar_icon(self) -> "FluentIconBase | QIcon | str | None":
        """返回侧边栏导航项图标：FluentIcon / QIcon / 图片绝对路径，``None`` 表示使用默认图标。"""
        return None

    def get_sidebar_label(self) -> str:
        """返回侧边栏导航项显示文字，默认使用 ``meta.name``。"""
        return self.meta.name

    def has_settings_widget(self) -> bool:
        """返回插件是否自定义了设置面板工厂。"""
        return type(self).create_settings_widget is not BasePlugin.create_settings_widget

    def has_sidebar_widget(self) -> bool:
        """返回插件是否自定义了侧边栏面板工厂。"""
        return type(self).create_sidebar_widget is not BasePlugin.create_sidebar_widget


class LibraryPlugin(BasePlugin):
    """依赖插件基类：向其他插件暴露公开接口，不直接面向用户。

    管理器加载时会自动把 ``meta.plugin_type`` 补正为 ``PluginType.LIBRARY``。
    """

    def export(self) -> Any:
        """返回供其他插件调用的公开接口对象，默认返回 ``self``。"""
        return self


class PluginAPI:
    """宿主程序提供给插件的能力接口；插件只应通过此接口与宿主交互，不应直接导入宿主内部模块。"""

    def __init__(self, plugin_data_dir: Path | None = None):
        self._hooks: dict[HookType, list[Callable]] = {}
        self._custom_triggers: dict[str, dict] = {}
        self._custom_actions: dict[str, Callable] = {}
        self._config: dict[str, Any] = {}
        self._data_dir: Path | None = plugin_data_dir
        self._plugin_id: str = ""
        self._plugin_name: str = ""
        self._services: dict[str, Any] = {}
        self._toast_callback: Callable | None = None
        self._plugin_resolver: Callable | None = None
        self._fire_trigger_callback: Callable | None = None
        self._permission_requester: Callable[[str, str], bool] | None = None
        self._event_subscriptions: list[tuple] = []  # (EventType, callback)
        self._declared_permissions_known: bool = False
        self._declared_permissions: set[str] = set()
        self._granted_permissions: set[str] = set()
        self._startup_context: dict[str, Any] = {
            "hidden_mode": False,
            "extra_args": "",
        }
        # cli_name -> spec dict
        self._startup_arg_specs: dict[str, dict[str, Any]] = {}
        self._startup_args_dispatched: bool = False
        self._canvas_topbar_factories: list[Callable] = []
        self._canvas_services: dict[str, Any] = {}
        self._home_card_factories: list[dict[str, Any]] = []
        # 每个插件仅允许一个调试页工厂
        self._debug_page_spec: dict[str, Any] | None = None
        self._registered_url_views: set[str] = set()
        self._registered_layout_open_actions: set[str] = set()
        self._registered_file_type_open_actions: set[str] = set()
        self._tray_menu_items: list[dict[str, Any]] = []

        if self._data_dir is not None:
            mkdir_with_uac(self._data_dir, parents=True, exist_ok=True)
            self._load_config()

    def register_hook(self, hook_type: HookType, callback: Callable) -> None:
        """注册钩子回调。同一回调可注册到多个钩子类型。"""
        callbacks = self._hooks.setdefault(hook_type, [])
        if any(cb is callback for cb in callbacks):
            return
        callbacks.append(callback)

    def unregister_hook(self, hook_type: HookType, callback: Callable) -> None:
        """注销指定钩子回调。"""
        if hook_type in self._hooks:
            self._hooks[hook_type] = [c for c in self._hooks[hook_type] if c is not callback]

    def emit_hook(self, hook_type: HookType, *args, **kwargs) -> list[Any]:
        """宿主调用：触发某类钩子，收集所有回调返回值。"""
        results = []
        for cb in self._hooks.get(hook_type, []):
            try:
                results.append(cb(*args, **kwargs))
            except Exception:
                logger.exception("PluginAPI hook {} 回调异常", hook_type)
        return results

    def register_trigger(
        self,
        trigger_id: str,
        handler: Callable | None = None,
        *,
        name: str = "",
        description: str = "",
        name_i18n: dict[str, str] | None = None,
        description_i18n: dict[str, str] | None = None,
    ) -> None:
        """注册自定义自动化触发器。

        ``trigger_id`` 建议使用 ``{plugin_id}.{name}`` 格式；一般用
        :meth:`fire_trigger` 主动触发，无需提供轮询 handler。
        """
        if trigger_id in self._custom_triggers:
            logger.warning("插件触发器 '{}' 被重复注册，已覆盖旧定义", trigger_id)
        self._custom_triggers[trigger_id] = {
            "name": name or trigger_id,
            "description": description,
            "name_i18n": self._normalize_i18n(name_i18n),
            "description_i18n": self._normalize_i18n(description_i18n),
            "handler": handler,
        }

    def unregister_trigger(self, trigger_id: str) -> None:
        """注销已注册的自定义自动化触发器。"""
        self._custom_triggers.pop(trigger_id, None)

    def register_action(self, action_id: str, executor: Callable) -> None:
        """注册自定义自动化动作；``executor`` 接收一个参数字典。"""
        if action_id in self._custom_actions:
            logger.warning("插件动作 '{}' 被重复注册，已覆盖旧定义", action_id)
        self._custom_actions[action_id] = executor

    def unregister_action(self, action_id: str) -> None:
        """注销已注册的自定义自动化动作。"""
        self._custom_actions.pop(action_id, None)

    def get_action_executor(self, action_id: str) -> Callable | None:
        return self._custom_actions.get(action_id)

    def list_custom_triggers(self) -> dict[str, dict]:
        """返回已注册触发器的公开信息字典（trigger_id -> name/description）。"""
        i18n = I18nService.instance()
        return {
            tid: {
                "name": i18n.resolve_text(info.get("name_i18n"), info["name"]),
                "description": i18n.resolve_text(info.get("description_i18n"), info["description"]),
            }
            for tid, info in self._custom_triggers.items()
        }

    @staticmethod
    def _normalize_i18n(value: dict[str, str] | None) -> dict[str, str]:
        if not isinstance(value, dict):
            return {}
        result: dict[str, str] = {}
        for k, v in value.items():
            if isinstance(v, str) and v.strip():
                result[I18nService.normalize_language(k)] = v
        return result

    def list_custom_actions(self) -> dict[str, Callable]:
        return dict(self._custom_actions)

    def fire_trigger(self, trigger_id: str, **context: Any) -> None:
        """主动触发一个已注册的自定义触发器，驱动自动化引擎执行匹配规则。

        额外的关键字参数会作为上下文传给规则动作。
        """
        if self._fire_trigger_callback:
            try:
                self._fire_trigger_callback(trigger_id, **context)
            except Exception:
                logger.exception("fire_trigger({}) 回调异常", trigger_id)
        else:
            logger.debug("fire_trigger({}) 未注入引擎回调，忽略", trigger_id)

    def _set_fire_trigger_callback(self, cb: Callable) -> None:
        """由管理器注入自动化引擎的触发回调。"""
        self._fire_trigger_callback = cb

    def subscribe_event(self, event_type: Any, callback: Callable) -> None:
        """订阅全局事件总线上的事件；插件卸载时会自动取消订阅。"""
        from app.events import EventBus

        EventBus.subscribe(event_type, callback)
        self._event_subscriptions.append((event_type, callback))

    def unsubscribe_event(self, event_type: Any, callback: Callable) -> None:
        """手动取消订阅（一般无需调用，卸载时会自动清理）。"""
        from app.events import EventBus

        EventBus.unsubscribe(event_type, callback)
        try:
            self._event_subscriptions.remove((event_type, callback))
        except ValueError:
            pass

    def _cleanup_event_subscriptions(self) -> None:
        """由管理器在插件卸载时调用，取消所有事件订阅。"""
        from app.events import EventBus

        for event_type, callback in self._event_subscriptions:
            try:
                EventBus.unsubscribe(event_type, callback)
            except Exception:
                pass
        self._event_subscriptions.clear()

    def _clear_runtime_registrations(self) -> None:
        """清空本 API 记录的运行时注册信息。"""
        url_scheme_svc = self._services.get("url_scheme_service")
        if url_scheme_svc is not None and self._registered_url_views:
            unregister = getattr(url_scheme_svc, "unregister_open_view", None)
            if callable(unregister):
                for view_key in list(self._registered_url_views):
                    try:
                        unregister(view_key, plugin_id=self._plugin_id)
                    except Exception:
                        logger.exception("插件 {} 注销 URL 路由 {} 失败", self._plugin_id or "<unknown>", view_key)

        layout_open_svc = self._services.get("layout_file_open_service")
        if layout_open_svc is not None and self._registered_layout_open_actions:
            unregister_action = getattr(layout_open_svc, "unregister_action", None)
            if callable(unregister_action):
                for action_id in list(self._registered_layout_open_actions):
                    try:
                        unregister_action(action_id, plugin_id=self._plugin_id)
                    except Exception:
                        logger.exception("插件 {} 注销布局打开用途 {} 失败", self._plugin_id or "<unknown>", action_id)

        file_type_open_svc = self._services.get("file_type_open_service")
        if file_type_open_svc is not None and self._registered_file_type_open_actions:
            unregister_action = getattr(file_type_open_svc, "unregister_action", None)
            if callable(unregister_action):
                for action_id in list(self._registered_file_type_open_actions):
                    try:
                        unregister_action(action_id, plugin_id=self._plugin_id)
                    except Exception:
                        logger.exception(
                            "插件 {} 注销文件类型打开用途 {} 失败", self._plugin_id or "<unknown>", action_id
                        )

        self._hooks.clear()
        self._custom_triggers.clear()
        self._custom_actions.clear()
        self._granted_permissions.clear()
        self._startup_arg_specs.clear()
        self._startup_args_dispatched = False
        self._canvas_topbar_factories.clear()
        self._canvas_services.clear()
        self._home_card_factories.clear()
        self._debug_page_spec = None
        self._registered_url_views.clear()
        self._registered_layout_open_actions.clear()
        self._registered_file_type_open_actions.clear()
        self._tray_menu_items.clear()

    @staticmethod
    def _normalize_permission_key(permission: str | PluginPermission) -> str:
        return permission.value if isinstance(permission, PluginPermission) else str(permission)

    def has_permission(self, permission: str | PluginPermission) -> bool:
        """返回插件当前是否已获得某项声明权限。"""
        return self._normalize_permission_key(permission) in self._granted_permissions

    def request_permission(
        self,
        permission: str | PluginPermission,
        *,
        reason: str = "",
    ) -> bool:
        """在运行期动态申请一项已声明的系统权限。

        只能申请 ``meta.permissions`` 中已声明的系统权限；``install_pkg``
        仍走启动阶段的依赖安装流程，不支持动态申请。
        """
        key = self._normalize_permission_key(permission)
        if self.has_permission(key):
            return True
        if key == PluginPermission.INSTALL_PKG.value:
            logger.warning("插件 {} 尝试动态申请 install_pkg，当前不支持该流程", self._plugin_id or "<unknown>")
            return False
        if self._declared_permissions_known and key not in self._declared_permissions:
            logger.warning(
                "插件 {} 尝试动态申请未声明权限 {}，请求已拒绝",
                self._plugin_id or "<unknown>",
                key,
            )
            return False
        if self._permission_requester is None:
            logger.warning("插件 {} 未注入权限申请器，无法动态申请 {}", self._plugin_id or "<unknown>", key)
            return False
        try:
            granted = bool(self._permission_requester(key, reason))
        except Exception:
            logger.exception("插件 {} 动态申请权限 {} 时发生异常", self._plugin_id or "<unknown>", key)
            return False
        if granted:
            self._granted_permissions.add(key)
        return granted

    def _set_granted_permissions(self, permissions: list[str]) -> None:
        """由管理器注入当前插件已获准的权限列表。"""
        self._granted_permissions = {self._normalize_permission_key(p) for p in permissions if p}

    def _grant_permission(self, permission: str | PluginPermission) -> None:
        """由管理器在当前会话中授予权限。"""
        self._granted_permissions.add(self._normalize_permission_key(permission))

    def _revoke_permission(self, permission: str | PluginPermission) -> None:
        """由管理器在当前会话中撤销权限。"""
        self._granted_permissions.discard(self._normalize_permission_key(permission))

    def _set_declared_permissions(self, permissions: list[str]) -> None:
        """由管理器注入插件声明过的权限集合。"""
        self._declared_permissions_known = True
        self._declared_permissions = {self._normalize_permission_key(p) for p in permissions if p}

    def _set_identity(self, plugin_id: str, plugin_name: str = "") -> None:
        """由管理器注入插件标识信息。"""
        self._plugin_id = plugin_id
        self._plugin_name = plugin_name

    def _set_permission_requester(self, requester: Callable[[str, str], bool]) -> None:
        """由管理器注入运行期权限申请器。"""
        self._permission_requester = requester

    def list_granted_permissions(self) -> list[str]:
        """返回当前会话已获准的权限列表。"""
        return sorted(self._granted_permissions)

    def get_config(self, key: str, default: Any = None) -> Any:
        """读取插件配置值；``key`` 支持点号路径。"""
        keys = key.split(".")
        node: Any = self._config
        for k in keys:
            if not isinstance(node, dict) or k not in node:
                return default
            node = node[k]
        return node

    def set_config(self, key: str, value: Any) -> None:
        """写入插件配置值并立即持久化到磁盘。"""
        keys = key.split(".")
        node = self._config
        for k in keys[:-1]:
            if k not in node or not isinstance(node[k], dict):
                node[k] = {}
            node = node[k]
        node[keys[-1]] = value
        self._save_config()

    def _config_path(self) -> Path | None:
        if self._data_dir is None:
            return None
        return self._data_dir / "config.json"

    def _load_config(self) -> None:
        path = self._config_path()
        if path and path.exists():
            try:
                self._config = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                logger.exception("插件配置加载失败: {}", path)
                self._config = {}

    def _save_config(self) -> None:
        path = self._config_path()
        if path is None:
            return
        try:
            write_text_with_uac(
                path,
                json.dumps(self._config, ensure_ascii=False, indent=2),
                encoding="utf-8",
                ensure_parent=True,
            )
        except Exception:
            logger.exception("插件配置保存失败: {}", path)

    def get_data_dir(self) -> Path | None:
        """返回插件专属数据目录。"""
        return self._data_dir

    def resolve_data_path(self, *parts: str | Path) -> Path | None:
        """在插件数据目录下拼接路径并确保父目录存在；无数据目录时返回 ``None``。"""
        if self._data_dir is None:
            return None
        path = self._data_dir.joinpath(*(str(p) for p in parts))
        mkdir_with_uac(path.parent, parents=True, exist_ok=True)
        return path

    def get_permission_data_dir(self) -> Path | None:
        """返回插件在权限目录下的专属子目录，用于存放认证绑定信息。"""
        svc = self.get_service("permission_service")
        if svc is None or not self._plugin_id:
            return None
        try:
            return svc.get_plugin_permission_data_dir(self._plugin_id)
        except Exception:
            logger.exception("插件 {} 读取权限数据目录失败", self._plugin_id)
            return None

    def resolve_permission_data_path(self, *parts: str | Path) -> Path | None:
        """在插件权限目录下拼接文件路径并确保父目录存在。"""
        svc = self.get_service("permission_service")
        if svc is None or not self._plugin_id:
            return None
        try:
            return svc.resolve_plugin_permission_data_path(self._plugin_id, *parts)
        except Exception:
            logger.exception("插件 {} 解析权限数据路径失败", self._plugin_id)
            return None

    def show_toast(self, title: str, message: str = "", *, level: str = "info") -> None:
        """弹出 Toast 通知；``level`` 可为 info / success / warning / error。"""
        if self._toast_callback:
            try:
                self._toast_callback(title, message, level=level)
            except Exception:
                logger.exception("插件 show_toast 回调异常")
        else:
            logger.info("[Plugin Toast][{}] {} {}", level, title, message)

    def show_notification(
        self,
        title: str,
        message: str = "",
        *,
        level: str = "info",
        duration_ms: int | None = None,
        image_path: str | None = None,
        progress: tuple[int, int] | None = None,
        progress_text: str = "",
        actions: list[dict[str, str]] | None = None,
    ) -> object | None:
        """弹出可组合富通知，返回通知句柄（可能为 None）。"""
        svc = self.get_service("notification_service")
        if svc is None or not hasattr(svc, "show_notification"):
            self.show_toast(title, message, level=level)
            return None
        try:
            from app.views.toast_notification import ToastAction

            action_list = [
                ToastAction(
                    str(item.get("id", "")),
                    str(item.get("text", "")),
                    str(item.get("kind", "default")),
                )
                for item in (actions or [])
                if item.get("id") and item.get("text")
            ]
            return svc.show_notification(
                title,
                message,
                level=level,
                duration_ms=duration_ms,
                image_path=image_path,
                progress=progress,
                progress_text=progress_text,
                actions=action_list,
            )
        except Exception:
            logger.exception("插件 show_notification 回调异常")
            return None

    def show_custom_notification_card(
        self,
        title: str,
        message: str = "",
        *,
        level: str = "info",
        duration_ms: int | None = None,
        custom_widget_factory: Callable,
    ) -> object | None:
        """显示自定义通知卡片（为插件保留的扩展接口）。"""
        svc = self.get_service("notification_service")
        if svc is None or not hasattr(svc, "show_notification"):
            self.show_toast(title, message, level=level)
            return None
        try:
            return svc.show_notification(
                title,
                message,
                level=level,
                duration_ms=duration_ms,
                custom_widget_factory=custom_widget_factory,
            )
        except Exception:
            logger.exception("插件 show_custom_notification_card 回调异常")
            return None

    def _set_toast_callback(self, cb: Callable) -> None:
        """由宿主注入通知回调。"""
        self._toast_callback = cb

    def get_service(self, name: str) -> Any | None:
        """获取宿主注册的服务对象；无此服务或缺少所需权限时返回 ``None``。"""
        required_perm = _SERVICE_PERMISSION_MAP.get(name)
        if required_perm is not None and not self.has_permission(required_perm):
            logger.warning("插件尝试访问宿主服务 '{}'，但未获得权限 {}", name, required_perm.value)
            return None
        return self._services.get(name)

    def _register_service(self, name: str, service: Any) -> None:
        """由宿主注入服务实例。"""
        self._services[name] = service

    def register_permission_item(
        self,
        item_key: str,
        display_name: str,
        *,
        category: str = "插件",
        description: str = "",
        default_level: Any = "user",
    ) -> bool:
        """注册插件自定义权限项目（独立于插件系统权限声明）。"""
        svc = self.get_service("permission_service")
        if svc is None:
            logger.warning("插件 {} 注册权限项目失败：permission_service 不可用", self._plugin_id or "<unknown>")
            return False
        if not self._plugin_id:
            logger.warning("插件注册权限项目失败：插件身份尚未注入")
            return False

        try:
            from app.services.permission_service import AccessLevel

            svc.register_plugin_permission_item(
                self._plugin_id,
                str(item_key or "").strip(),
                str(display_name or "").strip(),
                category=str(category or "插件").strip() or "插件",
                description=str(description or "").strip(),
                default_level=AccessLevel.from_value(default_level, default=AccessLevel.USER),
            )
            return True
        except Exception:
            logger.exception("插件 {} 注册权限项目异常: {}", self._plugin_id, item_key)
            return False

    def register_permission_auth_method(
        self,
        method_id: str,
        display_name: str,
        verifier: Callable,
        *,
        supported_levels: list[Any] | None = None,
        config_provider: Callable[[Any, str], Any] | None = None,
    ) -> bool:
        """注册插件自定义登录方式。"""
        svc = self.get_service("permission_service")
        if svc is None:
            logger.warning("插件 {} 注册登录方式失败：permission_service 不可用", self._plugin_id or "<unknown>")
            return False
        if not self._plugin_id:
            logger.warning("插件注册登录方式失败：插件身份尚未注入")
            return False

        try:
            from app.services.permission_service import AccessLevel

            levels = None
            if supported_levels is not None:
                levels = {AccessLevel.from_value(level, default=AccessLevel.USER) for level in supported_levels}

            svc.register_plugin_auth_method(
                self._plugin_id,
                str(method_id or "").strip(),
                str(display_name or "").strip(),
                verifier,
                supported_levels=levels,
                config_provider=config_provider,
            )
            return True
        except Exception:
            logger.exception("插件 {} 注册登录方式异常: {}", self._plugin_id, method_id)
            return False

    def ensure_access(
        self,
        feature_key: str,
        *,
        reason: str = "",
        parent: object | None = None,
    ) -> bool:
        """校验独立权限项目是否可访问。"""
        svc = self.get_service("permission_service")
        if svc is None:
            logger.warning("插件 {} 权限校验失败：permission_service 不可用", self._plugin_id or "<unknown>")
            return False
        try:
            return bool(svc.ensure_access(str(feature_key or "").strip(), parent=parent, reason=reason))
        except Exception:
            logger.exception("插件 {} 执行权限校验异常: {}", self._plugin_id or "<unknown>", feature_key)
            return False

    def register_central_event(self, event_key: str, callback: Callable[[dict[str, Any]], None]) -> bool:
        """注册插件的集控事件回调。"""
        svc = self.get_service("central_control_service")
        if svc is None:
            logger.warning("插件 {} 注册集控事件失败：central_control_service 不可用", self._plugin_id or "<unknown>")
            return False
        if not self._plugin_id:
            logger.warning("插件注册集控事件失败：插件身份尚未注入")
            return False

        key = str(event_key or "").strip()
        if not key:
            return False

        try:
            svc.register_event(key, callback, owner=f"plugin:{self._plugin_id}")
            return True
        except Exception:
            logger.exception("插件 {} 注册集控事件异常: {}", self._plugin_id, key)
            return False

    def emit_central_event(self, event_key: str, payload: dict[str, Any] | None = None) -> bool:
        """触发一个集控事件。"""
        svc = self.get_service("central_control_service")
        if svc is None:
            return False
        key = str(event_key or "").strip()
        if not key:
            return False
        try:
            svc.emit_event(key, payload or {})
            return True
        except Exception:
            logger.exception("插件 {} 触发集控事件异常: {}", self._plugin_id or "<unknown>", key)
            return False

    def get_central_plugin_config(self, default: Any = None) -> Any:
        """读取当前插件的集控下发配置。"""
        svc = self.get_service("central_control_service")
        if svc is None or not self._plugin_id:
            return default
        try:
            return svc.get_plugin_config(self._plugin_id, default)
        except Exception:
            logger.exception("插件 {} 读取集控插件配置异常", self._plugin_id)
            return default

    def register_canvas_service(self, name: str, service: Any) -> None:
        """注册供全屏画布组件使用的共享服务，宿主创建组件时会注入 ``services``。"""
        if not name:
            raise ValueError("canvas service name 不能为空")
        existing = self._canvas_services.get(name)
        if existing is not None and existing is not service:
            logger.warning("画布共享服务 '{}' 被重复注册，已覆盖旧对象", name)
        self._canvas_services[name] = service

    def list_canvas_services(self) -> dict[str, Any]:
        """返回当前插件已注册的画布共享服务。"""
        return dict(self._canvas_services)

    def get_plugin(self, plugin_id: str) -> Any | None:
        """获取依赖插件 ``export()`` 的返回值；未加载、未启用或未导出时返回 ``None``。"""
        if self._plugin_resolver is None:
            return None
        try:
            return self._plugin_resolver(plugin_id)
        except Exception:
            logger.exception("get_plugin({}) 调用异常", plugin_id)
            return None

    def _set_plugin_resolver(self, resolver: Callable[[str], Any | None]) -> None:
        """由管理器注入依赖插件解析器。"""
        self._plugin_resolver = resolver

    def get_startup_args(self) -> dict[str, Any]:
        """获取本次启动的上下文快照（``hidden_mode`` / ``extra_args``）。"""
        return dict(self._startup_context)

    def register_startup_arg(
        self,
        name: str,
        handler: Callable,
        *,
        action: str = "store",
        default: Any = None,
        nargs: str | None = None,
        help: str = "",
    ) -> None:
        """注册一个自定义 CLI 启动参数（绑定到 ``--extra-args`` 中的某个标志）。

        全部插件完成 ``on_load`` 后由管理器统一解析；``name`` 中的连字符
        与 argparse 一致映射到 dest（如 ``"my-flag"`` -> ``my_flag``）。
        """
        if name in self._startup_arg_specs:
            logger.warning("插件启动参数 '{}' 被重复注册，已覆盖旧定义", name)
        self._startup_arg_specs[name] = {
            "handler": handler,
            "action": action,
            "default": default,
            "nargs": nargs,
            "help": help,
        }

    def _set_startup_context(self, ctx: dict[str, Any]) -> None:
        """由管理器在实例化时注入启动上下文。"""
        self._startup_context = dict(ctx)

    def _get_startup_arg_specs(self) -> dict[str, dict[str, Any]]:
        """由管理器收集已注册的自定义启动参数规格。"""
        return dict(self._startup_arg_specs)

    def _startup_args_pending(self) -> bool:
        """返回当前插件的启动参数是否尚未派发。"""
        return not self._startup_args_dispatched

    def _mark_startup_args_dispatched(self) -> None:
        """标记当前插件的启动参数已完成派发。"""
        self._startup_args_dispatched = True

    def tr(self, key: str, default: str = "", **kwargs: Any) -> str:
        """获取宿主语言文本，供插件复用宿主 i18n。"""
        return I18nService.instance().t(key, default=default, **kwargs)

    def current_language(self) -> str:
        """返回当前宿主语言代码。"""
        return I18nService.instance().language

    def is_canvas_dark(self, zone_id: str | None = None) -> bool:
        """判断当前全屏时钟画布是否应使用深色模式。"""
        from app.utils.theme_utils import is_widget_dark

        return is_widget_dark(zone_id)

    def canvas_colors(self, zone_id: str | None = None) -> dict[str, str]:
        """返回当前全屏时钟画布的主题配色字典。"""
        from app.utils.theme_utils import widget_colors

        return widget_colors(zone_id)

    def get_canvas_settings(self, zone_id: str) -> dict[str, Any]:
        """获取指定画布的自定义设置。"""
        from app.widgets.layout_store import WidgetLayoutStore

        return WidgetLayoutStore.instance().get_canvas_settings(zone_id)

    def set_canvas_settings(self, zone_id: str, settings: dict[str, Any]) -> None:
        """更新指定画布的自定义设置并持久化，未传入的键保持不变。"""
        from app.widgets.layout_store import WidgetLayoutStore

        store = WidgetLayoutStore.instance()
        cs = store.get_canvas_settings(zone_id)
        cs.update(settings)
        for k in ("bg_color", "bg_image", "grid_color", "bg_overlay_color"):
            if k in cs and not cs[k]:
                del cs[k]
        if cs.get("theme") == "global":
            del cs["theme"]
        store.save_canvas_settings(zone_id, cs)

    def register_widget_type(self, widget_cls) -> None:
        """向全局注册表注册一个画布小组件类型；插件卸载时自动移除。"""
        from app.widgets.registry import WidgetRegistry

        WidgetRegistry.instance().register(widget_cls)

    def unregister_widget_type(self, widget_type: str) -> None:
        """从全局注册表手动移除一个画布小组件类型。"""
        from app.widgets.registry import WidgetRegistry

        WidgetRegistry.instance().unregister(widget_type)

    def register_canvas_topbar_btn_factory(
        self,
        factory: Callable,
    ) -> None:
        """注册画布全屏窗口顶栏按钮工厂；工厂接收 ``zone_id``，返回 widget 或 widget 列表。"""
        if any(existing is factory for existing in self._canvas_topbar_factories):
            return
        self._canvas_topbar_factories.append(factory)

    def register_home_card_factory(
        self,
        factory: Callable,
        *,
        slot: str = "recommend",
        order: int = 100,
    ) -> None:
        """注册首页卡片工厂。"""
        slot_name = str(slot or "recommend").strip().lower()
        if slot_name not in {"top", "recommend", "extra"}:
            raise ValueError("slot 仅支持 'top' / 'recommend' / 'extra'")

        for item in self._home_card_factories:
            if item.get("factory") is factory:
                item["slot"] = slot_name
                item["order"] = int(order)
                return

        self._home_card_factories.append(
            {
                "factory": factory,
                "slot": slot_name,
                "order": int(order),
            }
        )

    def unregister_home_card_factory(self, factory: Callable) -> None:
        """注销首页卡片工厂。"""
        self._home_card_factories = [item for item in self._home_card_factories if item.get("factory") is not factory]

    def register_debug_page_factory(self, label: str, factory: Callable) -> None:
        """注册调试面板中的插件页面工厂（每插件最多一个）。"""
        page_label = str(label or "").strip() or (self._plugin_name or self._plugin_id or "Plugin")
        self._debug_page_spec = {
            "label": page_label,
            "factory": factory,
        }

    def unregister_debug_page_factory(self) -> None:
        """注销调试面板插件页面工厂。"""
        self._debug_page_spec = None

    def get_debug_page_spec(self) -> dict[str, Any] | None:
        """返回当前插件注册的调试页面规格。"""
        if not self._debug_page_spec:
            return None
        return dict(self._debug_page_spec)

    def list_home_card_factories(self) -> list[dict[str, Any]]:
        """返回已注册首页卡片工厂列表。"""
        result: list[dict[str, Any]] = []
        for item in self._home_card_factories:
            factory = item.get("factory")
            if not callable(factory):
                continue
            result.append(
                {
                    "factory": factory,
                    "slot": item.get("slot", "recommend"),
                    "order": int(item.get("order", 100)),
                }
            )
        return result

    def register_tray_menu_item(
        self,
        text: str,
        callback: Callable,
        *,
        icon: Any = None,
        order: int = 100,
        text_i18n: dict[str, str] | None = None,
    ) -> None:
        """注册托盘图标右键菜单项。"""
        for item in self._tray_menu_items:
            if item.get("callback") is callback:
                item["text"] = text
                item["icon"] = icon
                item["order"] = int(order)
                item["text_i18n"] = self._normalize_i18n(text_i18n)
                return

        self._tray_menu_items.append(
            {
                "text": text,
                "callback": callback,
                "icon": icon,
                "order": int(order),
                "text_i18n": self._normalize_i18n(text_i18n),
            }
        )

    def unregister_tray_menu_item(self, callback: Callable) -> None:
        """注销已注册的托盘菜单项（按回调引用匹配）。"""
        self._tray_menu_items = [item for item in self._tray_menu_items if item.get("callback") is not callback]

    def list_tray_menu_items(self) -> list[dict[str, Any]]:
        """返回已注册的托盘菜单项列表。"""
        i18n = I18nService.instance()
        result: list[dict[str, Any]] = []
        for item in self._tray_menu_items:
            callback = item.get("callback")
            if not callable(callback):
                continue
            result.append(
                {
                    "text": i18n.resolve_text(item.get("text_i18n"), item.get("text", "")),
                    "callback": callback,
                    "icon": item.get("icon"),
                    "order": int(item.get("order", 100)),
                }
            )
        return result

    def register_url_scheme_view(self, view_key: str, object_name: str) -> bool:
        """注册 ``ltclock://open/<view_key>`` 路由。"""
        svc = self._services.get("url_scheme_service")
        if svc is None:
            logger.warning("插件 {} 注册 URL 路由失败：url_scheme_service 不可用", self._plugin_id or "<unknown>")
            return False

        register = getattr(svc, "register_open_view", None)
        if not callable(register):
            logger.warning("插件 {} 注册 URL 路由失败：宿主未提供 register_open_view", self._plugin_id or "<unknown>")
            return False

        try:
            ok, _ = register(view_key, object_name, plugin_id=self._plugin_id)
        except Exception:
            logger.exception("插件 {} 注册 URL 路由异常", self._plugin_id or "<unknown>")
            return False

        if ok:
            self._registered_url_views.add(str(view_key or "").strip().lower())
        return bool(ok)

    def unregister_url_scheme_view(self, view_key: str) -> bool:
        """注销通过本插件注册的 URL 路由。"""
        svc = self._services.get("url_scheme_service")
        if svc is None:
            return False

        unregister = getattr(svc, "unregister_open_view", None)
        if not callable(unregister):
            return False

        key = str(view_key or "").strip().lower()
        try:
            ok, _ = unregister(key, plugin_id=self._plugin_id)
        except Exception:
            logger.exception("插件 {} 注销 URL 路由异常", self._plugin_id or "<unknown>")
            return False

        if ok:
            self._registered_url_views.discard(key)
        return bool(ok)

    def register_layout_open_action(
        self,
        action_id: str,
        title: str,
        handler: Callable,
        *,
        description: str = "",
        content: str = "",
        order: int = 100,
        breadcrumb: Any | None = None,
        wizard_pages: Any | None = None,
        title_i18n: dict[str, str] | None = None,
        description_i18n: dict[str, str] | None = None,
    ) -> bool:
        """注册布局文件（.ltlayout）打开时的用途选项。"""
        svc = self._services.get("layout_file_open_service")
        if svc is None:
            logger.warning(
                "插件 {} 注册布局打开用途失败：layout_file_open_service 不可用", self._plugin_id or "<unknown>"
            )
            return False

        register_action = getattr(svc, "register_action", None)
        if not callable(register_action):
            logger.warning("插件 {} 注册布局打开用途失败：宿主未提供 register_action", self._plugin_id or "<unknown>")
            return False

        key = str(action_id or "").strip()
        if not key:
            logger.warning("插件 {} 注册布局打开用途失败：action_id 为空", self._plugin_id or "<unknown>")
            return False

        try:
            ok, _ = register_action(
                action_id=key,
                title=title,
                description=description,
                content=content,
                handler=handler,
                plugin_id=self._plugin_id,
                order=order,
                breadcrumb=breadcrumb,
                wizard_pages=wizard_pages,
                title_i18n=self._normalize_i18n(title_i18n),
                description_i18n=self._normalize_i18n(description_i18n),
            )
        except Exception:
            logger.exception("插件 {} 注册布局打开用途异常", self._plugin_id or "<unknown>")
            return False

        if ok:
            self._registered_layout_open_actions.add(key)
        return bool(ok)

    def unregister_layout_open_action(self, action_id: str) -> bool:
        """注销通过本插件注册的布局文件打开用途。"""
        svc = self._services.get("layout_file_open_service")
        if svc is None:
            return False

        unregister_action = getattr(svc, "unregister_action", None)
        if not callable(unregister_action):
            return False

        key = str(action_id or "").strip()
        if not key:
            return False

        try:
            ok, _ = unregister_action(key, plugin_id=self._plugin_id)
        except Exception:
            logger.exception("插件 {} 注销布局打开用途异常", self._plugin_id or "<unknown>")
            return False

        if ok:
            self._registered_layout_open_actions.discard(key)
        return bool(ok)

    def register_file_type_open_action(
        self,
        action_id: str,
        file_extension: str,
        title: str,
        handler: Callable,
        *,
        description: str = "",
        content: str = "",
        order: int = 100,
        breadcrumb: Any | None = None,
        wizard_pages: Any | None = None,
        title_i18n: dict[str, str] | None = None,
        description_i18n: dict[str, str] | None = None,
    ) -> bool:
        """注册文件类型打开时的用途选项。"""
        svc = self._services.get("file_type_open_service")
        if svc is None:
            logger.warning(
                "插件 {} 注册文件类型打开用途失败：file_type_open_service 不可用", self._plugin_id or "<unknown>"
            )
            return False

        register_action = getattr(svc, "register_action", None)
        if not callable(register_action):
            logger.warning(
                "插件 {} 注册文件类型打开用途失败：宿主未提供 register_action", self._plugin_id or "<unknown>"
            )
            return False

        key = str(action_id or "").strip()
        if not key:
            logger.warning("插件 {} 注册文件类型打开用途失败：action_id 为空", self._plugin_id or "<unknown>")
            return False

        ext = str(file_extension or "").strip().lower()
        if not ext:
            logger.warning("插件 {} 注册文件类型打开用途失败：file_extension 为空", self._plugin_id or "<unknown>")
            return False
        if not ext.startswith("."):
            ext = "." + ext

        try:
            ok, _ = register_action(
                action_id=key,
                file_extension=ext,
                title=title,
                description=description,
                content=content,
                handler=handler,
                plugin_id=self._plugin_id,
                order=order,
                breadcrumb=breadcrumb,
                wizard_pages=wizard_pages,
                title_i18n=self._normalize_i18n(title_i18n),
                description_i18n=self._normalize_i18n(description_i18n),
            )
        except Exception:
            logger.exception("插件 {} 注册文件类型打开用途异常", self._plugin_id or "<unknown>")
            return False

        if ok:
            self._registered_file_type_open_actions.add(key)
        return bool(ok)

    def unregister_file_type_open_action(self, action_id: str) -> bool:
        """注销通过本插件注册的文件类型打开用途。"""
        svc = self._services.get("file_type_open_service")
        if svc is None:
            return False

        unregister_action = getattr(svc, "unregister_action", None)
        if not callable(unregister_action):
            return False

        key = str(action_id or "").strip()
        if not key:
            return False

        try:
            ok, _ = unregister_action(key, plugin_id=self._plugin_id)
        except Exception:
            logger.exception("插件 {} 注销文件类型打开用途异常", self._plugin_id or "<unknown>")
            return False

        if ok:
            self._registered_file_type_open_actions.discard(key)
        return bool(ok)

    def register_recommendation_feature(self, feature_id: str, label: str = "") -> bool:
        """向宿主推荐服务注册一个可打分的自定义特征。"""
        svc = self._services.get("recommendation_service")
        if svc is None:
            return False
        register = getattr(svc, "register_feature", None)
        if not callable(register):
            return False
        try:
            return bool(register(feature_id, label=label))
        except Exception:
            logger.exception("插件 {} 注册推荐特征失败: {}", self._plugin_id or "<unknown>", feature_id)
            return False

    def unregister_recommendation_feature(self, feature_id: str, *, remove_stats: bool = False) -> bool:
        """注销自定义推荐特征。"""
        svc = self._services.get("recommendation_service")
        if svc is None:
            return False
        unregister = getattr(svc, "unregister_feature", None)
        if not callable(unregister):
            return False
        try:
            return bool(unregister(feature_id, remove_stats=remove_stats))
        except Exception:
            logger.exception("插件 {} 注销推荐特征失败: {}", self._plugin_id or "<unknown>", feature_id)
            return False

    def record_recommendation_view(self, feature_id: str) -> None:
        """记录一次推荐特征浏览。"""
        svc = self._services.get("recommendation_service")
        if svc is None:
            return
        fn = getattr(svc, "on_view_shown", None)
        if callable(fn):
            fn(feature_id)

    def record_recommendation_session_start(self, feature_id: str) -> None:
        """记录一次推荐特征会话开始。"""
        svc = self._services.get("recommendation_service")
        if svc is None:
            return
        fn = getattr(svc, "on_session_start", None)
        if callable(fn):
            fn(feature_id)

    def record_recommendation_session_end(self, feature_id: str) -> None:
        """记录一次推荐特征会话结束。"""
        svc = self._services.get("recommendation_service")
        if svc is None:
            return
        fn = getattr(svc, "on_session_end", None)
        if callable(fn):
            fn(feature_id)

    def rank_recommendation_features(
        self,
        feature_ids: list[str],
        *,
        active_features: set[str] | None = None,
        exclude: set[str] | None = None,
        explore: bool = True,
    ) -> list[tuple[str, float]]:
        """按推荐分数对给定特征列表排序。"""
        svc = self._services.get("recommendation_service")
        if svc is None:
            return []
        fn = getattr(svc, "ranked_for", None)
        if not callable(fn):
            return []
        try:
            return list(fn(feature_ids, active_features=active_features, exclude=exclude, explore=explore))
        except Exception:
            logger.exception("插件 {} 推荐排序失败", self._plugin_id or "<unknown>")
            return []

    def apply_canvas_layout(
        self,
        zone_id: str,
        widget_configs: list[dict[str, Any]],
    ) -> None:
        """将一组组件配置应用到指定 zone 的画布并立即刷新显示。

        会覆盖该 zone 的全部现有布局；画布未打开时配置仍会写入磁盘。
        """
        from app.widgets.layout_store import WidgetLayoutStore
        from app.widgets.base_widget import WidgetConfig

        store = WidgetLayoutStore.instance()
        cfg_objs = [WidgetConfig.from_dict(d) for d in widget_configs]
        store.save(zone_id, cfg_objs)
        # 通知所有订阅者（已打开的全屏画布）重新加载布局
        try:
            from app.events import EventBus, EventType

            EventBus.emit(EventType.WIDGET_LAYOUT_CHANGED, zone_id=zone_id)
        except Exception:
            logger.debug("apply_canvas_layout: EventBus 通知失败，布局已写入磁盘")

    def get_canvas_layout(
        self,
        zone_id: str,
    ) -> list[dict[str, Any]]:
        """读取指定 zone 当前画布的布局配置列表。"""
        from app.widgets.layout_store import WidgetLayoutStore

        store = WidgetLayoutStore.instance()
        configs = store.get(zone_id)
        return [c.to_dict() for c in configs]

    def get_corrected_utc(self) -> "datetime":
        """获取经过 NTP 与手动时间偏移校正后的 UTC 时间。"""
        from app.utils.time_utils import _ntp_utc_now

        return _ntp_utc_now()

    def get_corrected_time(self, tz: str = "local") -> "datetime":
        """获取校正后的本地或指定 IANA 时区时间。"""
        from app.utils.time_utils import now_in_zone

        return now_in_zone(tz)

    def get_time_offset_seconds(self) -> int:
        """获取当前手动时间偏移（秒）。"""
        settings_svc = self.get_service("settings_service")
        if settings_svc:
            return settings_svc.time_offset_seconds
        return 0

    def set_time_offset_seconds(self, offset: int) -> None:
        """设置手动时间偏移（秒），范围 -86400 ~ +86400；仅影响插件 API 返回的时间。"""
        settings_svc = self.get_service("settings_service")
        if settings_svc:
            settings_svc.set_time_offset_seconds(max(-86400, min(86400, offset)))

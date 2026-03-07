"""插件基类与钩子定义"""
from __future__ import annotations

import json
from abc import ABC
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget
    from PySide6.QtGui import QIcon
    try:
        # qfluentwidgets 在开发/类型检查时可用；运行时可能不存在，因此放在 TYPE_CHECKING 中
        from qfluentwidgets import FluentIcon as FluentIconBase
    except Exception:
        # 若类型检查器无法解析该包，回退为 Any 以避免静态分析错误
        FluentIconBase = Any  # type: ignore

from app.utils.logger import logger
from app.services.i18n_service import I18nService


class PluginPermission(str, Enum):
    """插件可声明请求的系统权限。"""
    # 网络
    NETWORK      = "network"       # 发起网络请求
    # 文件系统
    FS_READ      = "fs_read"       # 读取任意文件
    FS_WRITE     = "fs_write"      # 写入/删除任意文件
    # 系统接口
    OS_EXEC      = "os_exec"       # 执行外部进程 (os.system / subprocess)
    OS_ENV       = "os_env"        # 读写系统环境变量
    # 剪贴板
    CLIPBOARD    = "clipboard"     # 读写剪贴板
    # 通知
    NOTIFICATION = "notification"  # 发送系统通知
    # Python 包安装
    INSTALL_PKG  = "install_pkg"   # 安装第三方 Python 库


_SERVICE_PERMISSION_MAP: Dict[str, PluginPermission] = {
    "notification_service": PluginPermission.NOTIFICATION,
    "ntp_service": PluginPermission.NETWORK,
}


class HookType(Enum):
    """插件可注册的钩子点"""
    # 生命周期
    ON_LOAD          =   auto()    # 插件加载后
    ON_UNLOAD        =   auto()    # 插件卸载前

    # 闹钟
    ON_ALARM_BEFORE  =   auto()    # 闹钟即将触发（可取消）
    ON_ALARM_AFTER   =   auto()    # 闹钟已触发

    # 计时器
    ON_TIMER_DONE    =   auto()    # 计时器归零
    ON_STOPWATCH_LAP =   auto()    # 秒表记圈

    # 专注
    ON_FOCUS_START   =   auto()    # 专注会话开始
    ON_FOCUS_END     =   auto()    # 专注会话结束

    # 自动化
    CUSTOM_TRIGGER   =   auto()    # 注册自定义触发器
    CUSTOM_ACTION    =   auto()    # 注册自定义动作

    # UI
    SIDEBAR_WIDGET   =   auto()    # 在侧边栏注入额外面板
    SETTINGS_WIDGET  =   auto()    # 在设置页注入插件配置面板


class PluginType(Enum):
    """插件类型。

    FEATURE
        功能插件（面向用户）。提供时钟、通知等实际功能，
        可订阅钩子、注册自动化触发器/动作、扩展 UI。

    LIBRARY
        依赖插件（面向开发者）。封装可复用的能力（HTTP 客户端、
        数据库访问、第三方 SDK 等），通过 :meth:`LibraryPlugin.export`
        向其他插件暴露公开接口。不直接面向普通用户。
    """
    FEATURE = "feature"
    LIBRARY = "library"


@dataclass
class PluginMeta:
    """插件元数据。

    必填字段
    --------
    id : str
        全局唯一标识符，建议用 ``snake_case``，例如 ``my_cool_plugin``。
    name : str
        用户可见的插件名称（支持中文）。

    可选字段
    --------
    version : str
        遵循 `语义化版本 <https://semver.org/lang/zh-CN/>`_ 格式，默认 ``"1.0.0"``。
    author : str
        作者名或联系邮箱。
    description : str
        一句话描述插件功能，显示在插件管理界面。
    homepage : str
        项目主页 / 文档 URL。
    min_host_version : str
        要求的最低宿主版本，格式同 ``version``，例如 ``"0.1.0"``。
        为空字符串代表不限制。
    plugin_type : PluginType
        插件类型，默认 ``PluginType.FEATURE``（功能插件）。
        设为 ``PluginType.LIBRARY`` 声明为依赖插件。
    requires : list[str]
        所依赖的其他插件 ID 列表，例如 ``["http_lib", "db_lib"]``。
        管理器会确保依赖在本插件之前加载；若某依赖缺失则本插件
        加载失败并报错。
    dependencies : list[str]
        PyPI 包依赖列表，例如 ``["requests>=2.31", "pillow"]``。
        等同于 ``requirements.txt``。应用启动时若包缺失，管理器会弹出
        授权确认对话框；用户批准后自动安装到 ``plugins_ext/_lib/``。
        需要在 ``permissions`` 中同时声明 ``"install_pkg"`` 以触发此流程。
    tags : list[str]
        分类标签，例如 ``["notification", "timer"]``。
    """
    id:               str
    name:             str
    version:          str        = "1.0.0"
    author:           str        = ""
    description:      str        = ""
    homepage:         str        = ""
    min_host_version: str        = ""
    plugin_type:      PluginType = PluginType.FEATURE
    requires:         List[str]  = field(default_factory=list)
    dependencies:     List[str]  = field(default_factory=list)
    tags:             List[str]  = field(default_factory=list)
    permissions:      List[str]  = field(default_factory=list)  # PluginPermission 值列表
    name_i18n:        Dict[str, str] = field(default_factory=dict)
    description_i18n: Dict[str, str] = field(default_factory=dict)

    @staticmethod
    def _normalize_i18n_map(data: Any) -> Dict[str, str]:
        if not isinstance(data, dict):
            return {}
        result: Dict[str, str] = {}
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
    ) -> tuple[str, Dict[str, str]]:
        i18n_map = cls._normalize_i18n_map(explicit_i18n)
        if isinstance(value, str):
            base = value
            if base and "zh-CN" not in i18n_map and "en-US" not in i18n_map:
                i18n_map["zh-CN"] = base
            return base or fallback, i18n_map
        if isinstance(value, dict):
            i18n_map.update(cls._normalize_i18n_map(value))
            base = (
                i18n_map.get("zh-CN")
                or i18n_map.get("en-US")
                or next(iter(i18n_map.values()), "")
            )
            return base or fallback, i18n_map
        return fallback, i18n_map

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PluginMeta":
        """从字典（通常来自 plugin.json）构建 PluginMeta。"""
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
            id               = d["id"],
            name             = name,
            version          = d.get("version", "1.0.0"),
            author           = d.get("author", ""),
            description      = description,
            homepage         = d.get("homepage", ""),
            min_host_version = d.get("min_host_version", ""),
            plugin_type      = ptype,
            requires         = d.get("requires", []),
            dependencies     = d.get("dependencies", []),
            tags             = d.get("tags", []),
            permissions      = d.get("permissions", []),
            name_i18n        = name_i18n,
            description_i18n = description_i18n,
        )

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典。"""
        return {
            "id":               self.id,
            "name":             self.name,
            "version":          self.version,
            "author":           self.author,
            "description":      self.description,
            "homepage":         self.homepage,
            "min_host_version": self.min_host_version,
            "plugin_type":      self.plugin_type.value,
            "requires":         self.requires,
            "dependencies":     self.dependencies,
            "tags":             self.tags,
            "permissions":      self.permissions,
            "name_i18n":        self.name_i18n,
            "description_i18n": self.description_i18n,
        }

    def get_name(self, language: str | None = None) -> str:
        lang = I18nService.normalize_language(language)
        return (
            self.name_i18n.get(lang)
            or self.name_i18n.get("zh-CN")
            or self.name_i18n.get("en-US")
            or self.name
        )

    def get_description(self, language: str | None = None) -> str:
        lang = I18nService.normalize_language(language)
        return (
            self.description_i18n.get(lang)
            or self.description_i18n.get("zh-CN")
            or self.description_i18n.get("en-US")
            or self.description
        )


class BasePlugin(ABC):
    """所有插件必须继承此类，并在类体或 ``plugin.json`` 中声明 :attr:`meta`。

    最小示例（不带配置文件）::

        class Plugin(BasePlugin):
            meta = PluginMeta(id="my_plugin", name="我的插件")

            def on_load(self, api: "PluginAPI") -> None:
                api.register_hook(HookType.ON_ALARM_AFTER, self._on_alarm)

            def _on_alarm(self, alarm_id: str) -> None:
                print("闹钟响了!", alarm_id)

    推荐使用 ``plugin.json`` 声明元数据（见开发指南）。

    注意事项
    --------
    - 主入口类名必须为 ``Plugin``，管理器按此名称查找。
    - ``on_load`` / ``on_unload`` 均应捕获内部异常，不应向外抛出。
    - 插件数据请通过 ``api.get_config`` / ``api.set_config`` 持久化，
      不应直接读写宿主 ``config/`` 目录。
    """

    # 子类必须覆盖（或由 PluginManager 从 plugin.json 注入）
    meta: PluginMeta

    # ------------------------------------------------------------------ #
    # 生命周期 — 子类可选重写
    # ------------------------------------------------------------------ #

    def on_load(self, api: "PluginAPI") -> None:
        """插件加载时调用。在此注册钩子、触发器、动作等。"""

    def on_unload(self) -> None:
        """插件卸载时调用。在此清理资源、取消订阅等。"""

    # ------------------------------------------------------------------ #
    # UI 扩展点 — 子类可选重写
    # ------------------------------------------------------------------ #

    def create_settings_widget(self) -> Optional["QWidget"]:
        """返回插件专属的设置面板（嵌入宿主设置页）。"""
        return None

    def create_sidebar_widget(self) -> Optional["QWidget"]:
        """返回插件专属的侧边栏面板。

        返回一个 ``QWidget`` 实例，宿主将把它作为独立导航项添加到左侧边栏。
        返回 ``None`` 表示该插件无需侧边栏面板（不会在导航栏新增条目）。

        .. note::
            - 每次宿主需要显示面板时**只调用一次**，返回的 widget 会被持久持有。
            - 宿主会自动为返回的 widget 设置 ``objectName``（使用插件 ID），
              无需手动调用 ``setObjectName``。
        """
        return None

    def get_sidebar_icon(self) -> "FluentIconBase | QIcon | str | None":
        """返回侧边栏导航项的图标。仅在 :meth:`create_sidebar_widget` 返回非 ``None`` 时生效。

        Returns
        -------
        FluentIconBase
            ``qfluentwidgets.FluentIcon`` 枚举值，如 ``FIF.APPLICATION``。
            完整列表见 https://qfluentwidgets.com/zh/price/icons。
        QIcon
            ``PySide6.QtGui.QIcon`` 实例（可从图片文件构造）。
        str
            图片文件的**绝对路径**字符串（PNG / SVG / ICO 均支持）。
            插件通常通过 ``Path(__file__).parent / 'assets' / 'icon.png'`` 构造。
        None
            使用默认图标（``FIF.APPLICATION``）。
        """
        return None

    def get_sidebar_label(self) -> str:
        """返回侧边栏导航项的显示文字。仅在 :meth:`create_sidebar_widget` 返回非 ``None`` 时生效。

        默认返回 ``meta.name``（插件名称）。
        """
        return self.meta.name

    def has_settings_widget(self) -> bool:
        """返回插件是否自定义了设置面板工厂。"""
        return type(self).create_settings_widget is not BasePlugin.create_settings_widget

    def has_sidebar_widget(self) -> bool:
        """返回插件是否自定义了侧边栏面板工厂。"""
        return type(self).create_sidebar_widget is not BasePlugin.create_sidebar_widget


class LibraryPlugin(BasePlugin):
    """依赖插件基类。

    继承此类代替 :class:`BasePlugin` 以声明本插件为 **依赖插件**
    （``plugin_type = library``）。依赖插件不直接面向用户，而是向其他插件
    提供可复用的公开接口。

    其他插件通过 ``api.get_plugin(plugin_id)`` 获取本插件的导出对象：

    .. code-block:: python

        # 在依赖插件中
        class Plugin(LibraryPlugin):
            meta = PluginMeta(
                id="http_lib", name="HTTP 工具库",
                plugin_type=PluginType.LIBRARY,
            )

            def fetch(self, url: str) -> dict:
                ...

            def export(self):
                return self   # 把自身作为公开接口

        # 在功能插件中
        class Plugin(BasePlugin):
            meta = PluginMeta(
                id="weather_plugin", name="天气插件",
                requires=["http_lib"],
            )

            def on_load(self, api):
                http = api.get_plugin("http_lib")
                if http:
                    data = http.fetch("https://api.example.com/weather")

    注意事项
    --------
    - ``export()`` 返回的对象即为其他插件拿到的接口，可以是 ``self``
      也可以是单独的接口类实例（推荐后者以更好地隔离内部实现）。
    - ``meta.plugin_type`` 必须为 ``PluginType.LIBRARY``；继承本类时
      若忘记设置，管理器会自动补正。
    - 依赖插件同样可以订阅钩子，但 **不应** 直接修改 UI 状态。
    """

    def export(self) -> Any:
        """返回供其他插件调用的公开接口对象。

        默认返回 ``self``；强烈建议子类返回专门的接口对象以隔离内部实现。
        """
        return self


# --------------------------------------------------------------------------- #
# PluginAPI
# --------------------------------------------------------------------------- #

class PluginAPI:
    """宿主程序提供给插件的能力接口。

    插件 **只应** 通过此接口与宿主交互，不应直接导入宿主内部模块。

    可用能力
    --------
    - 钩子注册：:meth:`register_hook` / :meth:`unregister_hook`
        - 自动化扩展：:meth:`register_trigger` / :meth:`unregister_trigger` /
            :meth:`register_action` / :meth:`unregister_action`
    - 持久化配置：:meth:`get_config` / :meth:`set_config`
    - 插件数据目录：:meth:`get_data_dir` / :meth:`resolve_data_path`
    - 用户通知：:meth:`show_toast`
        - 权限查询：:meth:`has_permission` / :meth:`request_permission`
    - 宿主服务：:meth:`get_service`
        - 启动参数：:meth:`get_startup_args` / :meth:`register_startup_arg`
        - i18n 辅助：:meth:`tr` / :meth:`current_language`
        - 画布组件：:meth:`register_widget_type` / :meth:`unregister_widget_type`
        - 顶栏按钮：:meth:`register_canvas_topbar_btn_factory`
    - 画布服务注册：:meth:`register_canvas_service`
        - 画布布局：:meth:`apply_canvas_layout` / :meth:`get_canvas_layout`
    - 依赖插件访问：:meth:`get_plugin`
    - 全局事件订阅：:meth:`subscribe_event` / :meth:`unsubscribe_event`
    """

    def __init__(self, plugin_data_dir: Optional[Path] = None):
        self._hooks: Dict[HookType, List[Callable]]  = {}
        self._custom_triggers: Dict[str, dict]        = {}
        self._custom_actions: Dict[str, Callable]    = {}
        self._config: Dict[str, Any]                 = {}
        self._data_dir: Optional[Path]               = plugin_data_dir
        self._plugin_id: str                         = ""
        self._plugin_name: str                       = ""
        self._services: Dict[str, Any]               = {}
        self._toast_callback: Optional[Callable]     = None
        self._plugin_resolver: Optional[Callable]    = None   # 由管理器注入
        self._fire_trigger_callback: Optional[Callable] = None  # 由管理器注入
        self._permission_requester: Optional[Callable[[str, str], bool]] = None
        self._event_subscriptions: List[tuple]       = []     # (EventType, callback)
        self._declared_permissions_known: bool       = False
        self._declared_permissions: set[str]         = set()
        self._granted_permissions: set[str]          = set()
        # 启动上下文（由管理器注入）
        self._startup_context: Dict[str, Any]        = {
            "hidden_mode": False,
            "extra_args":  "",
        }
        # 插件注册的自定义启动参数规格：cli_name -> spec dict
        self._startup_arg_specs: Dict[str, Dict[str, Any]] = {}
        self._startup_args_dispatched: bool = False
        # 画布顶栏按钮工厂列表：factory(zone_id: str) -> Optional[QWidget]
        self._canvas_topbar_factories: List[Callable] = []
        # 画布共享服务：供 WidgetCanvas 创建插件组件时注入 services 使用
        self._canvas_services: Dict[str, Any] = {}

        if self._data_dir is not None:
            self._data_dir.mkdir(parents=True, exist_ok=True)
            self._load_config()

    # ------------------------------------------------------------------ #
    # 钩子注册
    # ------------------------------------------------------------------ #

    def register_hook(self, hook_type: HookType, callback: Callable) -> None:
        """注册钩子回调。同一回调可注册到多个钩子类型。"""
        callbacks = self._hooks.setdefault(hook_type, [])
        if any(cb is callback for cb in callbacks):
            return
        callbacks.append(callback)

    def unregister_hook(self, hook_type: HookType, callback: Callable) -> None:
        """注销指定钩子回调。"""
        if hook_type in self._hooks:
            self._hooks[hook_type] = [
                c for c in self._hooks[hook_type] if c is not callback
            ]

    def emit_hook(self, hook_type: HookType, *args, **kwargs) -> List[Any]:
        """宿主调用：触发某类钩子，收集所有回调返回值。"""
        results = []
        for cb in self._hooks.get(hook_type, []):
            try:
                results.append(cb(*args, **kwargs))
            except Exception:
                logger.exception("PluginAPI hook {} 回调异常", hook_type)
        return results

    # ------------------------------------------------------------------ #
    # 自定义触发器 / 动作
    # ------------------------------------------------------------------ #

    def register_trigger(
        self,
        trigger_id: str,
        handler: Optional[Callable] = None,
        *,
        name: str = "",
        description: str = "",
        name_i18n: Optional[Dict[str, str]] = None,
        description_i18n: Optional[Dict[str, str]] = None,
    ) -> None:
        """注册自定义自动化触发器。

        Parameters
        ----------
        trigger_id : str
            全局唯一字符串，建议格式 ``{plugin_id}.{name}``，
            例如 ``"weather_plugin.on_rain"``。
        handler : Callable[[], bool], optional
            轮询型处理器（一般不需要；推荐使用 :meth:`fire_trigger` 主动触发）。
        name : str
            触发器的用户可见名称，显示在自动化规则编辑界面，
            例如 ``"超出音量阈值"``。不填写则显示 trigger_id。
        description : str
            触发器的详细说明（可选）。
        """
        if trigger_id in self._custom_triggers:
            logger.warning("插件触发器 '{}' 被重复注册，已覆盖旧定义", trigger_id)
        self._custom_triggers[trigger_id] = {
            "name":        name or trigger_id,
            "description": description,
            "name_i18n": self._normalize_i18n(name_i18n),
            "description_i18n": self._normalize_i18n(description_i18n),
            "handler":     handler,
        }

    def unregister_trigger(self, trigger_id: str) -> None:
        """注销已注册的自定义自动化触发器。"""
        self._custom_triggers.pop(trigger_id, None)

    def register_action(self, action_id: str, executor: Callable) -> None:
        """注册自定义自动化动作。

        Parameters
        ----------
        action_id : str
            全局唯一字符串，建议格式 ``{plugin_id}.{name}``，
            例如 ``"weather_plugin.send_alert"``。
        executor : Callable[[dict], None]
            执行动作的函数，接收一个参数字典。
        """
        if action_id in self._custom_actions:
            logger.warning("插件动作 '{}' 被重复注册，已覆盖旧定义", action_id)
        self._custom_actions[action_id] = executor

    def unregister_action(self, action_id: str) -> None:
        """注销已注册的自定义自动化动作。"""
        self._custom_actions.pop(action_id, None)

    def get_action_executor(self, action_id: str) -> Optional[Callable]:
        return self._custom_actions.get(action_id)

    def list_custom_triggers(self) -> Dict[str, dict]:
        """返回已注册触发器的公开信息字典。

        Returns
        -------
        Dict[str, dict]
            键为 trigger_id，值为包含 ``name`` 和 ``description`` 的字典。
        """
        i18n = I18nService.instance()
        return {
            tid: {
                "name": i18n.resolve_text(info.get("name_i18n"), info["name"]),
                "description": i18n.resolve_text(info.get("description_i18n"), info["description"]),
            }
            for tid, info in self._custom_triggers.items()
        }

    @staticmethod
    def _normalize_i18n(value: Optional[Dict[str, str]]) -> Dict[str, str]:
        if not isinstance(value, dict):
            return {}
        result: Dict[str, str] = {}
        for k, v in value.items():
            if isinstance(v, str) and v.strip():
                result[I18nService.normalize_language(k)] = v
        return result

    def list_custom_actions(self) -> Dict[str, Callable]:
        return dict(self._custom_actions)

    def fire_trigger(self, trigger_id: str, **context: Any) -> None:
        """主动触发一个已注册的自定义触发器，驱动自动化引擎执行匹配的规则。

        Parameters
        ----------
        trigger_id : str
            触发器 ID，应与 :meth:`register_trigger` 注册时一致，
            建议格式 ``{plugin_id}.{event_name}``。
        context : Any
            额外上下文键值对，传递给规则动作，可在动作参数中引用。
        """
        if self._fire_trigger_callback:
            try:
                self._fire_trigger_callback(trigger_id, **context)
            except Exception:
                logger.exception("fire_trigger({}) 回调异常", trigger_id)
        else:
            logger.debug("fire_trigger({}) 未注入引擎回调，忽略", trigger_id)

    def _set_fire_trigger_callback(self, cb: Callable) -> None:
        """由管理器注入自动化引擎的触发回调（内部使用）。"""
        self._fire_trigger_callback = cb

    # ------------------------------------------------------------------ #
    # 全局事件订阅
    # ------------------------------------------------------------------ #

    def subscribe_event(self, event_type: Any, callback: Callable) -> None:
        """订阅全局事件总线上的事件。

        插件卸载时，所有通过此方法注册的订阅将自动取消，无需手动清理。

        Parameters
        ----------
        event_type : EventType
            来自 :mod:`app.events` 的 :class:`~app.events.EventType` 枚举值。
        callback : Callable
            事件回调，以关键字参数接收事件 payload，例如
            ``def _on_timer_done(self, timer_id: str, label: str, **_): ...``

        示例
        ----
        .. code-block:: python

            from app.events import EventBus, EventType

            def on_load(self, api):
                api.subscribe_event(EventType.TIMER_DONE, self._on_timer_done)

            def _on_timer_done(self, timer_id: str, label: str = "", **_):
                api.show_toast("计时完成", label)
        """
        from app.events import EventBus
        EventBus.subscribe(event_type, callback)
        self._event_subscriptions.append((event_type, callback))

    def unsubscribe_event(self, event_type: Any, callback: Callable) -> None:
        """手动取消订阅（一般交由插件卸载时自动清理，无需显式调用）。"""
        from app.events import EventBus
        EventBus.unsubscribe(event_type, callback)
        try:
            self._event_subscriptions.remove((event_type, callback))
        except ValueError:
            pass

    def _cleanup_event_subscriptions(self) -> None:
        """由管理器在插件卸载时调用，自动取消所有事件订阅（内部使用）。"""
        from app.events import EventBus
        for event_type, callback in self._event_subscriptions:
            try:
                EventBus.unsubscribe(event_type, callback)
            except Exception:
                pass
        self._event_subscriptions.clear()

    def _clear_runtime_registrations(self) -> None:
        """清空当前插件 API 中记录的运行时注册信息（内部使用）。"""
        self._hooks.clear()
        self._custom_triggers.clear()
        self._custom_actions.clear()
        self._granted_permissions.clear()
        self._startup_arg_specs.clear()
        self._startup_args_dispatched = False
        self._canvas_topbar_factories.clear()
        self._canvas_services.clear()

    # ------------------------------------------------------------------ #
    # 权限查询
    # ------------------------------------------------------------------ #

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

        该方法适用于延迟请求权限的场景，例如：
        仅在用户真正开启某个功能时再申请通知或网络权限。

        注意：
        - 只能申请插件在 ``meta.permissions`` / ``plugin.json`` 中已声明的系统权限；
        - ``install_pkg`` 仍用于启动阶段依赖安装，不支持通过此方法动态申请；
        - 若权限已在当前会话获准，将直接返回 ``True``。
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

    def _set_granted_permissions(self, permissions: List[str]) -> None:
        """由管理器注入当前插件已获准的权限列表（内部使用）。"""
        self._granted_permissions = {
            self._normalize_permission_key(p)
            for p in permissions
            if p
        }

    def _grant_permission(self, permission: str | PluginPermission) -> None:
        """由管理器在当前会话中授予权限（内部使用）。"""
        self._granted_permissions.add(self._normalize_permission_key(permission))

    def _revoke_permission(self, permission: str | PluginPermission) -> None:
        """由管理器在当前会话中撤销权限（内部使用）。"""
        self._granted_permissions.discard(self._normalize_permission_key(permission))

    def _set_declared_permissions(self, permissions: List[str]) -> None:
        """由管理器注入插件声明过的权限集合（内部使用）。"""
        self._declared_permissions_known = True
        self._declared_permissions = {
            self._normalize_permission_key(p)
            for p in permissions
            if p
        }

    def _set_identity(self, plugin_id: str, plugin_name: str = "") -> None:
        """由管理器注入插件标识信息（内部使用）。"""
        self._plugin_id = plugin_id
        self._plugin_name = plugin_name

    def _set_permission_requester(self, requester: Callable[[str, str], bool]) -> None:
        """由管理器注入运行期权限申请器（内部使用）。"""
        self._permission_requester = requester

    def list_granted_permissions(self) -> List[str]:
        """返回当前会话已获准的权限列表。"""
        return sorted(self._granted_permissions)

    # ------------------------------------------------------------------ #
    # 持久化配置
    # ------------------------------------------------------------------ #

    def get_config(self, key: str, default: Any = None) -> Any:
        """读取插件配置值。

        配置自动保存在 ``plugins_ext/<plugin_id>/config.json``。

        Parameters
        ----------
        key : str
            配置键名（支持点号路径，如 ``"notifications.enabled"``）。
        default : Any
            键不存在时的默认值。
        """
        keys = key.split(".")
        node: Any = self._config
        for k in keys:
            if not isinstance(node, dict) or k not in node:
                return default
            node = node[k]
        return node

    def set_config(self, key: str, value: Any) -> None:
        """写入插件配置值并立即持久化到磁盘。

        Parameters
        ----------
        key : str
            配置键名（支持点号路径，如 ``"notifications.enabled"``）。
        value : Any
            可 JSON 序列化的值。
        """
        keys = key.split(".")
        node = self._config
        for k in keys[:-1]:
            if k not in node or not isinstance(node[k], dict):
                node[k] = {}
            node = node[k]
        node[keys[-1]] = value
        self._save_config()

    def _config_path(self) -> Optional[Path]:
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
            path.write_text(
                json.dumps(self._config, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            logger.exception("插件配置保存失败: {}", path)

    # ------------------------------------------------------------------ #
    # 插件数据目录
    # ------------------------------------------------------------------ #

    def get_data_dir(self) -> Optional[Path]:
        """返回插件专属数据目录。"""
        return self._data_dir

    def resolve_data_path(self, *parts: str | Path) -> Optional[Path]:
        """在插件专属数据目录下拼接文件路径。

        会自动确保父目录存在，适合保存插件自己的 JSON、缓存和静态数据。
        当插件没有专属数据目录时返回 ``None``。
        """
        if self._data_dir is None:
            return None
        path = self._data_dir.joinpath(*(str(p) for p in parts))
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    # ------------------------------------------------------------------ #
    # 用户通知
    # ------------------------------------------------------------------ #

    def show_toast(self, title: str, message: str = "", *, level: str = "info") -> None:
        """弹出 Toast 通知。

        Parameters
        ----------
        title : str
            通知标题（简短）。
        message : str
            详细内容，可为空。
        level : str
            通知级别：``"info"`` | ``"success"`` | ``"warning"`` | ``"error"``。
        """
        if self._toast_callback:
            try:
                self._toast_callback(title, message, level=level)
            except Exception:
                logger.exception("插件 show_toast 回调异常")
        else:
            logger.info("[Plugin Toast][{}] {} {}", level, title, message)

    def _set_toast_callback(self, cb: Callable) -> None:
        """由宿主注入通知回调（内部使用）。"""
        self._toast_callback = cb

    # ------------------------------------------------------------------ #
    # 宿主服务访问
    # ------------------------------------------------------------------ #

    def get_service(self, name: str) -> Optional[Any]:
        """获取宿主注册的服务对象。

        可用服务名称（由宿主注入，可能随版本变化）：

        - ``"alarm_service"``   — :class:`~app.services.alarm_service.AlarmService`
        - ``"timer_service"``   — 计时器/秒表服务（如已暴露）
        - ``"focus_service"``   — :class:`~app.services.focus_service.FocusService`
        - ``"settings_service"``— :class:`~app.services.settings_service.SettingsService`
        - ``"ntp_service"``     — :class:`~app.services.ntp_service.NtpService`

        Parameters
        ----------
        name : str
            服务名称。

        Returns
        -------
        服务对象实例；若不存在或插件未获得访问该服务所需权限，则返回 ``None``。
        """
        required_perm = _SERVICE_PERMISSION_MAP.get(name)
        if required_perm is not None and not self.has_permission(required_perm):
            logger.warning("插件尝试访问宿主服务 '{}'，但未获得权限 {}", name, required_perm.value)
            return None
        return self._services.get(name)

    def _register_service(self, name: str, service: Any) -> None:
        """由宿主注入服务实例（内部使用）。"""
        self._services[name] = service

    # ------------------------------------------------------------------ #
    # 画布共享服务
    # ------------------------------------------------------------------ #

    def register_canvas_service(self, name: str, service: Any) -> None:
        """注册供全屏画布组件使用的共享服务。

        注册后，宿主会在创建 :class:`WidgetCanvas` 时把这些服务合并进
        ``services`` 字典，插件组件可在 ``WidgetBase.__init__`` 的 ``services``
        参数中直接读取。

        Parameters
        ----------
        name : str
            服务名称，例如 ``"exam_service"``。
        service : Any
            任意 Python 对象，通常为 ``QObject``、数据服务或轻量控制器。
        """
        if not name:
            raise ValueError("canvas service name 不能为空")
        existing = self._canvas_services.get(name)
        if existing is not None and existing is not service:
            logger.warning("画布共享服务 '{}' 被重复注册，已覆盖旧对象", name)
        self._canvas_services[name] = service

    def list_canvas_services(self) -> Dict[str, Any]:
        """返回当前插件已注册的画布共享服务。"""
        return dict(self._canvas_services)

    # ------------------------------------------------------------------ #
    # 依赖插件访问
    # ------------------------------------------------------------------ #

    def get_plugin(self, plugin_id: str) -> Optional[Any]:
        """获取已加载的依赖插件（``PluginType.LIBRARY``）的公开接口对象。

        返回值为该依赖插件 :meth:`~LibraryPlugin.export` 方法的返回值。
        若目标插件未加载、未启用或类型不是 ``LIBRARY``，则返回 ``None``。

        Parameters
        ----------
        plugin_id : str
            依赖插件的 ID（与其 ``PluginMeta.id`` 一致）。

        Returns
        -------
        Any | None
            依赖插件导出的接口对象，或 ``None``。

        示例
        ----
        .. code-block:: python

            def on_load(self, api):
                http = api.get_plugin("http_lib")
                if http is None:
                    api.show_toast("初始化失败", "找不到 http_lib 插件", level="error")
                    return
                self._http = http
        """
        if self._plugin_resolver is None:
            return None
        try:
            return self._plugin_resolver(plugin_id)
        except Exception:
            logger.exception("get_plugin({}) 调用异常", plugin_id)
            return None

    def _set_plugin_resolver(self, resolver: Callable[[str], Optional[Any]]) -> None:
        """由管理器注入依赖插件解析器（内部使用）。"""
        self._plugin_resolver = resolver

    # ------------------------------------------------------------------ #
    # 启动参数
    # ------------------------------------------------------------------ #

    def get_startup_args(self) -> Dict[str, Any]:
        """获取本次启动的上下文信息（只读快照）。

        返回字典包含以下字段：

        - ``hidden_mode`` (:class:`bool`) — 是否以隐藏模式启动（主窗口未显示）。
        - ``extra_args`` (:class:`str`) — ``--extra-args`` 传入的原始自定义参数字符串。
          插件可通过 :meth:`register_startup_arg` 注册处理器，获得自动解析后的值。

        注意：安全模式下插件不会被加载，此方法不会返回 ``safe_mode`` 字段。
        若需区分「隐藏启动」行为，请检查 ``hidden_mode``。

        Returns
        -------
        dict
            启动上下文字典，修改返回值不影响宿主状态。

        示例
        ----
        .. code-block:: python

            def on_load(self, api):
                ctx = api.get_startup_args()
                if ctx["hidden_mode"]:
                    # 隐藏启动时延迟初始化 UI 相关资源
                    return
        """
        return dict(self._startup_context)

    def register_startup_arg(
        self,
        name: str,
        handler: Callable,
        *,
        action: str = "store",
        default: Any = None,
        nargs: Optional[str] = None,
        help: str = "",
    ) -> None:
        """注册一个自定义 CLI 启动参数（绑定到 ``--extra-args`` 中的某个标志）。

        全部插件完成 ``on_load`` 后，管理器会统一解析 ``--extra-args``，
        若对应参数存在且值不为默认值，则调用 ``handler``。

        ``name`` 中的连字符会自动映射到 dest（与 argparse 行为一致）：
        例如 ``"my-flag"`` → ``--my-flag`` → dest ``my_flag``。

        Parameters
        ----------
        name : str
            参数名（可含前缀 ``--``，也可不含），例如 ``"verbose"``
            或 ``"--verbose"``。建议使用插件 ID 前缀避免与其他插件冲突，
            如 ``"my_plugin.debug"``。
        handler : Callable
            处理器函数。
            - ``action="store"``：接收解析后的值，签名为 ``handler(value)``。
            - ``action="store_true"`` / ``"store_false"``：无参调用，签名为 ``handler()``。
        action : str
            argparse action 字符串，常用值：

            - ``"store"``（默认）— 存储传入的值。
            - ``"store_true"`` — 标志存在时存储 ``True``。
            - ``"store_false"`` — 标志存在时存储 ``False``。
        default : Any
            参数缺失时的默认值（仅 ``action="store"`` 时有效）。
        nargs : str | None
            argparse nargs，例如 ``"?"``、``"*"``、``"+"``。
        help : str
            参数说明（仅记录，不展示给最终用户）。

        示例
        ----
        .. code-block:: python

            def on_load(self, api):
                # 接收字符串值：uv run main.py --extra-args "--my-plugin.target prod"
                api.register_startup_arg(
                    "my-plugin.target",
                    self._on_target,
                    default="dev",
                    help="部署目标环境",
                )
                # 布尔标志：uv run main.py --extra-args "--my-plugin.verbose"
                api.register_startup_arg(
                    "my-plugin.verbose",
                    self._on_verbose,
                    action="store_true",
                )

            def _on_target(self, value: str):
                self._target = value

            def _on_verbose(self):
                self._verbose = True
        """
        if name in self._startup_arg_specs:
            logger.warning("插件启动参数 '{}' 被重复注册，已覆盖旧定义", name)
        self._startup_arg_specs[name] = {
            "handler": handler,
            "action":  action,
            "default": default,
            "nargs":   nargs,
            "help":    help,
        }

    def _set_startup_context(self, ctx: Dict[str, Any]) -> None:
        """由管理器在实例化时注入启动上下文（内部使用）。"""
        self._startup_context = dict(ctx)

    def _get_startup_arg_specs(self) -> Dict[str, Dict[str, Any]]:
        """由管理器收集已注册的自定义启动参数规格（内部使用）。"""
        return dict(self._startup_arg_specs)

    def _startup_args_pending(self) -> bool:
        """返回当前插件的启动参数是否尚未派发（内部使用）。"""
        return not self._startup_args_dispatched

    def _mark_startup_args_dispatched(self) -> None:
        """标记当前插件的启动参数已完成派发（内部使用）。"""
        self._startup_args_dispatched = True

    def tr(self, key: str, default: str = "", **kwargs: Any) -> str:
        """获取宿主语言文本，供插件复用宿主 i18n。"""
        return I18nService.instance().t(key, default=default, **kwargs)

    def current_language(self) -> str:
        """返回当前宿主语言代码。"""
        return I18nService.instance().language

    # ------------------------------------------------------------------ #
    # 画布小组件类型注册
    # ------------------------------------------------------------------ #

    def register_widget_type(self, widget_cls) -> None:
        """向全局注册表注册一个画布小组件类型。

        插件卸载时，所有通过此方法（或在 ``on_load`` 期间直接调用
        ``WidgetRegistry.instance().register()``）注册的类型将被自动移除。

        Parameters
        ----------
        widget_cls : Type[WidgetBase]
            继承自 :class:`~app.widgets.base_widget.WidgetBase` 的组件类，
            必须已定义 ``WIDGET_TYPE`` 和 ``WIDGET_NAME``。

        示例
        ----
        .. code-block:: python

            from app.widgets.base_widget import WidgetBase, WidgetConfig

            class MyWidget(WidgetBase):
                WIDGET_TYPE = \"my_plugin.my_widget\"
                WIDGET_NAME = \"我的组件\"
                ...

            def on_load(self, api):
                api.register_widget_type(MyWidget)
        """
        from app.widgets.registry import WidgetRegistry
        WidgetRegistry.instance().register(widget_cls)

    def unregister_widget_type(self, widget_type: str) -> None:
        """从全局注册表手动移除一个画布小组件类型。

        通常无需手动调用，插件卸载时管理器会自动清理。

        Parameters
        ----------
        widget_type : str
            组件的 ``WIDGET_TYPE`` 字符串。
        """
        from app.widgets.registry import WidgetRegistry
        WidgetRegistry.instance().unregister(widget_type)

    # ------------------------------------------------------------------ #
    # 画布顶栏按钮注入
    # ------------------------------------------------------------------ #

    def register_canvas_topbar_btn_factory(
        self,
        factory: Callable,
    ) -> None:
        """注册画布全屏窗口顶栏按钮工厂函数。

        每次全屏画布窗口（``FullscreenClockWindow``）打开时，宿主会调用已注册的
        所有工厂函数，并将返回的 ``QWidget`` 或 ``list[QWidget]``（若非 ``None``）插入到顶栏
        "编辑布局"按钮的左侧。

        Parameters
        ----------
        factory : Callable[[str], QWidget | list[QWidget] | tuple[QWidget, ...] | None]
            工厂函数，接收 ``zone_id: str``，返回单个 ``QWidget``、由多个
            widget 组成的列表/元组，或 ``None``。
            每次全屏画布打开时重新调用，返回的 widget 归该窗口所有。

        示例
        ----
        .. code-block:: python

            from PySide6.QtWidgets import QPushButton

            def on_load(self, api):
                api.register_canvas_topbar_btn_factory(self._make_topbar_btn)

            def _make_topbar_btn(self, zone_id: str):
                btn = QPushButton(\"切换科目\")
                btn.clicked.connect(lambda: ...)
                return btn
        """
        if any(existing is factory for existing in self._canvas_topbar_factories):
            return
        self._canvas_topbar_factories.append(factory)

    # ------------------------------------------------------------------ #
    # 画布布局操作
    # ------------------------------------------------------------------ #

    def apply_canvas_layout(
        self,
        zone_id: str,
        widget_configs: List[Dict[str, Any]],
    ) -> None:
        """将一组组件配置应用到指定 zone 的画布并立即刷新显示。

        此方法会覆盖目标 zone 的全部现有布局，适合用于"切换预设"流程。
        若目标 zone 的全屏画布当前未打开，配置仍会写入磁盘；
        下次打开时会自动加载新布局。

        Parameters
        ----------
        zone_id : str
            目标 zone 的 ID（即 ``WorldZone`` 的 ``id``）。
        widget_configs : list[dict]
            组件配置字典列表，格式与 ``WidgetConfig.to_dict()`` 结果一致。
        """
        from app.widgets.layout_store import WidgetLayoutStore
        from app.widgets.base_widget import WidgetConfig
        store = WidgetLayoutStore()
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
    ) -> List[Dict[str, Any]]:
        """读取指定 zone 当前画布的布局配置列表。

        返回的列表可直接传给 :meth:`apply_canvas_layout` 进行保存/还原。

        Parameters
        ----------
        zone_id : str
            目标 zone 的 ID。

        Returns
        -------
        list[dict]
            组件配置字典列表（深拷贝），空列表表示该 zone 没有已保存的布局。
        """
        from app.widgets.layout_store import WidgetLayoutStore
        store = WidgetLayoutStore()
        configs = store.get(zone_id)
        return [c.to_dict() for c in configs]

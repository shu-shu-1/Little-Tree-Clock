"""全局事件广播系统

本模块提供面向全应用（含插件）的轻量事件总线 :class:`EventBus`。

设计原则
--------
- **线程安全**：底层使用 Qt Signal（Auto-Connection），无论事件从哪个线程发出，
  回调均在主线程中被安全调用。
- **松耦合**：发送方无需了解接收方；订阅者只需调用 :meth:`EventBus.subscribe`。
- **自动清理**：插件通过 :meth:`PluginAPI.subscribe_event` 订阅，卸载时自动取消所有订阅。

内置事件类型
------------
见 :class:`EventType`。

快速使用::

    # 插件内
    from app.events import EventBus, EventType

    def on_load(self, api):
        api.subscribe_event(EventType.FULLSCREEN_CLOSED, self._on_fullscreen_closed)

    def _on_fullscreen_closed(self, zone_id: str = "", **_):
        self._monitor.stop()

    # 其他模块中
    EventBus.emit(EventType.FULLSCREEN_CLOSED, zone_id="local")
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import QObject, Signal

from app.utils.logger import logger


# --------------------------------------------------------------------------- #
# 事件类型枚举
# --------------------------------------------------------------------------- #

class EventType(str, Enum):
    """全局事件类型。

    值格式：``{domain}.{name}``，便于按领域分组筛选。
    """

    # ── 应用生命周期 ─────────────────────────────────────────────────── #
    APP_STARTUP  = "app.startup"                # 应用启动（服务就绪后）
    APP_SHUTDOWN = "app.shutdown"               # 应用即将退出
    APP_SHOWN    = "app.shown"                  # 主窗口显示
    APP_HIDDEN   = "app.hidden"                 # 主窗口隐藏到托盘

    # ── 全屏时钟 ─────────────────────────────────────────────────────── #
    FULLSCREEN_OPENED = "fullscreen.opened"     # payload: zone_id: str
    FULLSCREEN_CLOSED = "fullscreen.closed"     # payload: zone_id: str

    # ── 闹钟 ─────────────────────────────────────────────────────────── #
    ALARM_FIRED = "alarm.fired"                 # payload: alarm_id: str

    # ── 计时器 ───────────────────────────────────────────────────────── #
    TIMER_STARTED = "timer.started"             # payload: timer_id, label, total_ms
    TIMER_PAUSED  = "timer.paused"              # payload: timer_id, label
    TIMER_RESET   = "timer.reset"               # payload: timer_id, label
    TIMER_DONE    = "timer.done"                # payload: timer_id, label

    # ── 专注会话 ─────────────────────────────────────────────────────── #
    FOCUS_STARTED       = "focus.started"       # payload: total_cycles: int
    FOCUS_ENDED         = "focus.ended"         # 全部循环完成，无 payload
    FOCUS_PHASE_CHANGED = "focus.phase_changed" # payload: phase: str, cycle_index: int
    FOCUS_DISTRACTED    = "focus.distracted"    # payload: distracted_sec: int

    # ── 插件生命周期 ─────────────────────────────────────────────────── #
    PLUGIN_LOADED   = "plugin.loaded"           # payload: plugin_id: str, name: str
    PLUGIN_UNLOADED = "plugin.unloaded"         # payload: plugin_id: str, name: str

    # ── 自动化 ───────────────────────────────────────────────────────── #
    AUTOMATION_TRIGGERED = "automation.triggered"
    # payload: rule_id: str, rule_name: str, trigger_id: str

    # ── 插件自定义（插件向其他插件广播） ──────────────────────────────── #
    PLUGIN_CUSTOM = "plugin.custom"
    # payload: event_key: str, source_plugin: str, **data


# --------------------------------------------------------------------------- #
# 内部分发器（Qt-backed）
# --------------------------------------------------------------------------- #

class _Dispatcher(QObject):
    """Qt 信号驱动的事件分发器（单例）。

    所有事件均通过 Qt Auto-Connection 派发，无论 ``emit`` 在哪个线程调用
    （例如 sounddevice 音频线程），回调都在主线程中同步执行。
    """

    _bridge = Signal(str, object)   # (event_type.value, payload_dict)

    def __init__(self) -> None:
        super().__init__()
        self._handlers: Dict[str, List[Callable]] = {}
        # Auto-Connection：从非 Qt 线程 emit 时自动走队列派发到主线程
        self._bridge.connect(self._on_bridge)

    # ── 公开 API ─────────────────────────────────────────────────────── #

    def subscribe(self, event_type: EventType, callback: Callable) -> None:
        self._handlers.setdefault(event_type.value, []).append(callback)

    def unsubscribe(self, event_type: EventType, callback: Callable) -> None:
        key = event_type.value
        lst = self._handlers.get(key)
        if lst:
            self._handlers[key] = [c for c in lst if c is not callback]

    def emit_event(self, event_type: EventType, **payload: Any) -> None:
        """发布事件（可从任意线程调用）。"""
        self._bridge.emit(event_type.value, payload)

    # ── 内部 ─────────────────────────────────────────────────────────── #

    def _on_bridge(self, key: str, payload: object) -> None:
        for cb in list(self._handlers.get(key, [])):
            try:
                cb(**(payload or {}))
            except Exception:
                logger.exception("EventBus 回调异常 [{}]", key)


# --------------------------------------------------------------------------- #
# 公开 EventBus（类方法接口，无需实例化）
# --------------------------------------------------------------------------- #

class EventBus:
    """全局事件总线。

    所有方法均为类方法，可在任意位置直接调用:

        EventBus.emit(EventType.TIMER_DONE, timer_id="aaa", label="番茄钟")
        EventBus.subscribe(EventType.TIMER_DONE, my_callback)
        EventBus.unsubscribe(EventType.TIMER_DONE, my_callback)
    """

    _instance: Optional[_Dispatcher] = None

    @classmethod
    def _get(cls) -> _Dispatcher:
        if cls._instance is None:
            cls._instance = _Dispatcher()
        return cls._instance

    @classmethod
    def subscribe(cls, event_type: EventType, callback: Callable) -> None:
        """订阅事件；callback 在主线程中调用，接受 ``**payload`` 关键字参数。"""
        cls._get().subscribe(event_type, callback)

    @classmethod
    def unsubscribe(cls, event_type: EventType, callback: Callable) -> None:
        """取消订阅。"""
        cls._get().unsubscribe(event_type, callback)

    @classmethod
    def emit(cls, event_type: EventType, **payload: Any) -> None:
        """发布事件（可从任意线程调用）。"""
        cls._get().emit_event(event_type, **payload)

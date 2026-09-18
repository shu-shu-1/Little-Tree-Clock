"""全局事件广播系统。"""

from __future__ import annotations

from enum import Enum
from typing import Any, Callable

from PySide6.QtCore import QObject, Signal

from app.utils.logger import logger


class EventType(str, Enum):
    """全局事件类型。

    值格式：``{domain}.{name}``，便于按领域分组筛选。
    """

    APP_STARTUP = "app.startup"  # 应用启动（服务就绪后）
    APP_SHUTDOWN = "app.shutdown"  # 应用即将退出
    APP_SHOWN = "app.shown"  # 主窗口显示
    APP_HIDDEN = "app.hidden"  # 主窗口隐藏到托盘

    FULLSCREEN_OPENED = "fullscreen.opened"  # payload: zone_id: str
    FULLSCREEN_CLOSED = "fullscreen.closed"  # payload: zone_id: str

    ALARM_FIRED = "alarm.fired"  # payload: alarm_id: str

    TIMER_STARTED = "timer.started"  # payload: timer_id, label, total_ms
    TIMER_PAUSED = "timer.paused"  # payload: timer_id, label
    TIMER_RESET = "timer.reset"  # payload: timer_id, label
    TIMER_DONE = "timer.done"  # payload: timer_id, label

    FOCUS_STARTED = "focus.started"  # payload: total_cycles: int
    FOCUS_ENDED = "focus.ended"  # 全部循环完成，无 payload
    FOCUS_PHASE_CHANGED = "focus.phase_changed"  # payload: phase: str, cycle_index: int
    FOCUS_DISTRACTED = "focus.distracted"  # payload: distracted_sec: int

    PLUGIN_LOADED = "plugin.loaded"  # payload: plugin_id: str, name: str
    PLUGIN_UNLOADED = "plugin.unloaded"  # payload: plugin_id: str, name: str

    AUTOMATION_TRIGGERED = "automation.triggered"
    # payload: rule_id: str, rule_name: str, trigger_id: str

    PLUGIN_CUSTOM = "plugin.custom"
    # payload: event_key: str, source_plugin: str, **data

    WIDGET_LAYOUT_CHANGED = "widget.layout_changed"
    # payload: zone_id: str — 某 zone 的画布布局已被插件替换，需重新加载


class _Dispatcher(QObject):
    """Qt 信号驱动的事件分发器（单例）：回调始终在主线程执行。"""

    _bridge = Signal(str, object)  # (event_type.value, payload_dict)

    def __init__(self) -> None:
        super().__init__()
        self._handlers: dict[str, list[Callable]] = {}
        # Auto-Connection：从非 Qt 线程 emit 时自动走队列派发到主线程
        self._bridge.connect(self._on_bridge)

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

    def _on_bridge(self, key: str, payload: object) -> None:
        for cb in list(self._handlers.get(key, [])):
            try:
                cb(**(payload or {}))
            except Exception:
                logger.exception("EventBus 回调异常 [{}]", key)


class EventBus:
    """全局事件总线：所有方法均为类方法，可直接调用。"""

    _instance: _Dispatcher | None = None

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
        cls._get().unsubscribe(event_type, callback)

    @classmethod
    def emit(cls, event_type: EventType, **payload: Any) -> None:
        """发布事件（可从任意线程调用）。"""
        cls._get().emit_event(event_type, **payload)

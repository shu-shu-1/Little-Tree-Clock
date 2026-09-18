"""音量检测插件：注册音量组件与 ``volume_detector.threshold_exceeded`` 触发器，并向其他插件暴露录制 API。"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from app.plugins import BasePlugin, PluginAPI, PluginMeta

if TYPE_CHECKING:
    from .widget import VolumeDetectorAPI, VolumeRecorderManager


class _PluginState:
    api: PluginAPI | None = None
    monitor_instances: list = []  # 注册所有活跃的 AudioMonitor，卸载时停止
    recorder_mgr: VolumeRecorderManager | None = None
    exported_api: VolumeDetectorAPI | None = None
    central_config: dict = {}


_plugin_state = _PluginState()

TRIGGER_ID = "volume_detector.threshold_exceeded"


class Plugin(BasePlugin):
    meta = PluginMeta(
        id="volume_detector",
        name="音量检测",
        version="2.2.0",
        description="基于共享异步音频运行时监测麦克风音量，支持组件显示、告警和会话录制复用同一输入流",
        dependencies=["sounddevice", "numpy"],
        permissions=["notification", "install_pkg"],
    )

    def on_load(self, api: PluginAPI) -> None:
        self._api = api
        _plugin_state.api = api
        self._register_permission_items()
        self._apply_central_config(api.get_central_plugin_config({}))
        api.register_central_event("policy.updated", self._on_policy_updated)

        # 名称用于展示，实际触发由 widget 调用 api.fire_trigger
        api.register_trigger(
            TRIGGER_ID,
            name="音量检测：超出阈值",
            description="当麦克风音量超过设定阈值时触发",
        )

        from .widget import (
            VolumeDetectorWidget,
            VolumeStatusWidget,
            VolumeRecorderManager,
            VolumeDetectorAPI,
            _DEFAULTS,
        )

        data_dir = api.get_data_dir() or (Path(__file__).parent / "_data")
        _plugin_state.recorder_mgr = VolumeRecorderManager(report_dir=Path(data_dir) / "volume_reports")
        _plugin_state.exported_api = VolumeDetectorAPI(
            _plugin_state.recorder_mgr,
            default_threshold=_DEFAULTS["threshold_db"],
        )
        api.register_widget_type(VolumeDetectorWidget)
        api.register_widget_type(VolumeStatusWidget)

        api.show_toast(
            "音量检测",
            "插件已加载，可在「添加组件」菜单中找到「音量检测」",
            level="success",
        )

    def on_unload(self) -> None:
        from .widget import shutdown_shared_audio_runtime

        for monitor in list(_plugin_state.monitor_instances):
            try:
                monitor.stop()
            except Exception:
                pass
        _plugin_state.monitor_instances.clear()
        if _plugin_state.recorder_mgr is not None:
            try:
                _plugin_state.recorder_mgr.stop_all()
            except Exception:
                pass
        try:
            shutdown_shared_audio_runtime()
        except Exception:
            pass
        _plugin_state.recorder_mgr = None
        _plugin_state.exported_api = None
        if hasattr(self, "_api") and self._api:
            try:
                self._api.unregister_widget_type("volume_detector")
                self._api.unregister_widget_type("volume_detector.status")
            except Exception:
                pass
            try:
                self._api.unregister_trigger(TRIGGER_ID)
            except Exception:
                pass
        _plugin_state.api = None

    def export(self):
        """向其他插件暴露录音接口。"""
        return _plugin_state.exported_api

    def _register_permission_items(self) -> None:
        self._api.register_permission_item(
            "plugin.volume_detector.detect_volume",
            "使用音量检测",
            category="音量检测",
            description="调用音量检测接口，录制自习/工作环境音量报告",
        )
        self._api.register_permission_item(
            "plugin.volume_detector.send_alert",
            "发送音量告警通知",
            category="音量检测",
            description="当检测音量超出阈值时发送通知提醒",
        )
        self._api.register_permission_item(
            "plugin.volume_detector.trigger_automation",
            "触发音量自动化",
            category="音量检测",
            description="当音量超阈值时触发自动化规则",
        )

    def _on_policy_updated(self, _payload: dict) -> None:
        if not hasattr(self, "_api") or self._api is None:
            return
        self._apply_central_config(self._api.get_central_plugin_config({}))

    @staticmethod
    def _apply_central_config(config: object) -> None:
        _plugin_state.central_config = dict(config) if isinstance(config, dict) else {}

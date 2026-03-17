"""音量检测插件

功能
----
- 注册 VolumeDetectorWidget 小组件到画布
- 注册自定义触发器 ``volume_detector.threshold_exceeded``，
  可在自动化规则中从下拉列表直接选择，当麦克风音量超过阈值时自动执行规则
- 向其他插件暴露 ``VolumeDetectorAPI``，可通过 ``api.get_plugin("volume_detector")``
    启动/停止音量录制会话并获取报告数据

触发器
------
- ID: ``volume_detector.threshold_exceeded``
- 名称: 音量检测：超出阈值

自动化规则配置方法
------------------
在「自动化」页面新建规则 → 触发方式选择「[插件] 自定义触发器」→
从触发器下拉列表选择「音量检测：超出阈值」，然后配置所需动作即可。
"""
from __future__ import annotations

from pathlib import Path

from app.plugins import BasePlugin, PluginAPI, PluginMeta

# ──────────────────────────────────────────────────────────────────── #
# 模块级 API 引用（供 widget.py 通过 from . import _plugin_state 访问）
# ──────────────────────────────────────────────────────────────────── #

class _PluginState:
    api: PluginAPI | None = None
    monitor_instances: list = []   # 注册所有活跃的 AudioMonitor，卸载时停止
    recorder_mgr: "VolumeRecorderManager | None" = None
    exported_api: "VolumeDetectorAPI | None" = None

_plugin_state = _PluginState()

TRIGGER_ID = "volume_detector.threshold_exceeded"


class Plugin(BasePlugin):
    meta = PluginMeta(
        id          = "volume_detector",
        name        = "音量检测",
        version     = "2.1.0",
        description = "实时监测麦克风音量，超出阈值时变色、发送通知并触发自动化",
        dependencies= ["sounddevice", "numpy"],
        permissions = ["notification", "install_pkg"],
    )

    def on_load(self, api: PluginAPI) -> None:
        self._api = api
        _plugin_state.api = api

        # 注册触发器（声明名称，实际触发由 widget 调用 api.fire_trigger）
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

        api.show_toast("音量检测", "插件已加载，可在「添加组件」菜单中找到「音量检测」", level="success")

    def on_unload(self) -> None:
        # 停止所有正在运行的音频监测实例
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

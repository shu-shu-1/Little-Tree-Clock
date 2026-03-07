"""音量检测插件

功能
----
- 注册 VolumeDetectorWidget 小组件到画布
- 注册自定义触发器 ``volume_detector.threshold_exceeded``，
  可在自动化规则中从下拉列表直接选择，当麦克风音量超过阈值时自动执行规则

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

from app.plugins import BasePlugin, PluginAPI, PluginMeta

# ──────────────────────────────────────────────────────────────────── #
# 模块级 API 引用（供 widget.py 通过 from . import _plugin_state 访问）
# ──────────────────────────────────────────────────────────────────── #

class _PluginState:
    api: PluginAPI | None = None
    monitor_instances: list = []   # 注册所有活跃的 AudioMonitor，卸载时停止

_plugin_state = _PluginState()

TRIGGER_ID = "volume_detector.threshold_exceeded"


class Plugin(BasePlugin):
    meta = PluginMeta(
        id          = "volume_detector",
        name        = "音量检测",
        version     = "1.0.0",
        description = "实时监测麦克风音量，超出阈值时变色、发送通知并触发自动化",
        dependencies= ["sounddevice", "numpy"],
        permissions = ["notification", "install_pkg"],
    )

    def on_load(self, api: PluginAPI) -> None:
        _plugin_state.api = api

        # 注册触发器（声明名称，实际触发由 widget 调用 api.fire_trigger）
        api.register_trigger(
            TRIGGER_ID,
            name="音量检测：超出阈值",
            description="当麦克风音量超过设定阈值时触发",
        )

        from .widget import VolumeDetectorWidget
        api.register_widget_type(VolumeDetectorWidget)

        api.show_toast("音量检测", "插件已加载，可在「添加组件」菜单中找到「音量检测」", level="success")

    def on_unload(self) -> None:
        # 停止所有正在运行的音频监测实例
        for monitor in list(_plugin_state.monitor_instances):
            try:
                monitor.stop()
            except Exception:
                pass
        _plugin_state.monitor_instances.clear()
        _plugin_state.api = None

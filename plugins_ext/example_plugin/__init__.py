"""示例插件（功能插件）：演示如何调用依赖插件。

example_plugin/ 目录含 plugin.json（清单，声明 plugin_type 与 requires）、
本文件（入口类 Plugin），以及可选的 requirements.txt 与 assets/。
主入口类必须名为 ``Plugin`` 并继承 BasePlugin；元数据优先从同目录 plugin.json
加载，无清单时回退类体中的 ``meta``。宿主交互全部通过 ``on_load`` 传入的
``api`` 完成：持久化用 ``api.get_config`` / ``api.set_config``，调用依赖插件用
``api.get_plugin(plugin_id)``。``on_load`` / ``on_unload`` 不应向外抛出异常。
"""

from __future__ import annotations

from app.plugins import BasePlugin, HookType, PluginAPI, PluginMeta

# 仅用于类型标注
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from plugins_ext.example_lib import ExampleLibInterface


class Plugin(BasePlugin):
    meta = PluginMeta(
        id="example_plugin",
        name="示例插件",
        version="1.0.0",
        description="演示插件格式规范",
        requires=["example_lib"],
    )

    def __init__(self):
        self._api: PluginAPI | None = None
        self._lib: ExampleLibInterface | None = None

    # 生命周期

    def on_load(self, api: PluginAPI) -> None:
        self._api = api
        self._lib = api.get_plugin("example_lib")

        greet_count = api.get_config("stats.greet_count", default=0)

        api.register_hook(HookType.ON_ALARM_AFTER, self._on_alarm_fired)
        api.register_hook(HookType.ON_TIMER_DONE, self._on_timer_done)
        api.register_hook(HookType.ON_FOCUS_END, self._on_focus_end)

        api.register_action("example_plugin.greet", self._action_greet)

        api.register_tray_menu_item(
            text="示例插件问候",
            callback=self._tray_greet,
            order=80,
        )

        api.show_toast(
            "示例插件已启动",
            f"本次会话前已问候 {greet_count} 次",
            level="info",
        )

    def on_unload(self) -> None:
        if self._api is not None:
            self._api.unregister_tray_menu_item(self._tray_greet)

    def _tray_greet(self) -> None:
        if self._api is None:
            return
        if self._lib is not None:
            now = self._lib.format_timestamp(self._api.get_corrected_time(), "%H:%M")
            self._api.show_toast("托盘问候", f"现在时间是 {now}，你好！")
        else:
            self._api.show_toast("托盘问候", "你好！")

    # 钩子回调

    def _on_alarm_fired(self, alarm_id: str) -> None:
        if self._api is None:
            return
        if self._lib is not None:
            # 使用校正后的时间（支持 NTP 校正和手动偏移）
            now = self._api.get_corrected_time()
            ts = self._lib.format_timestamp(now, "%H:%M")
            label = self._lib.truncate(alarm_id, 20)
            self._api.show_toast(f"闹钟提醒 [{ts}]", f"闹钟 {label} 已响铃", level="info")
        else:
            self._api.show_toast("闹钟提醒", f"闹钟 {alarm_id} 已响铃")

    def _on_timer_done(self, timer_id: str) -> None:
        # 此处可执行任意逻辑，例如播放自定义音效
        pass

    def _on_focus_end(self, session_minutes: int) -> None:
        if self._api is None:
            return
        total = self._api.get_config("stats.focus_minutes", default=0)
        self._api.set_config("stats.focus_minutes", total + session_minutes)
        if self._lib is not None:
            dur = self._lib.friendly_duration(session_minutes * 60)
            self._api.show_toast("专注完成", f"本次专注了 {dur}", level="success")

    # 自动化动作

    def _action_greet(self, params: dict) -> None:
        if self._api is None:
            return
        msg = params.get("message", "你好！")
        if self._lib is not None:
            msg = self._lib.truncate(msg, 30)
        self._api.show_toast("示例插件问候", msg, level="success")
        count = self._api.get_config("stats.greet_count", default=0)
        self._api.set_config("stats.greet_count", count + 1)

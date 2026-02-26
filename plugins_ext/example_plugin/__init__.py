"""示例插件（功能插件）— 演示如何调用依赖插件

目录结构
--------
example_plugin/
    plugin.json       ← 插件清单（含 plugin_type 和 requires 字段）
    __init__.py       ← 本文件，包含主入口类 Plugin
    requirements.txt  ← 可选，列出 PyPI 依赖
    assets/           ← 可选，图标等静态资源

规范要点
--------
1. 主入口类名必须为 ``Plugin``，继承 :class:`~app.plugins.BasePlugin`。
2. 元数据优先从同目录 ``plugin.json`` 加载；若无清单文件则需在类体中声明 ``meta``。
3. 所有与宿主的交互通过 ``on_load`` 传入的 ``api`` 对象完成。
4. ``on_load`` / ``on_unload`` 不应向外抛出异常。
5. 持久化数据使用 ``api.get_config`` / ``api.set_config``，
   数据自动保存在本插件目录下的 ``config.json``。
6. 调用依赖插件：在 ``plugin.json`` 中声明 ``requires``，
   在 ``on_load`` 中用 ``api.get_plugin(plugin_id)`` 获取其接口。
"""
from __future__ import annotations

from app.plugins import BasePlugin, PluginMeta, HookType
from app.plugins.base_plugin import PluginAPI

# 可选：仅用于类型标注，不强制要求
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from plugins_ext.example_lib import ExampleLibInterface


class Plugin(BasePlugin):
    """示例功能插件主类。

    依赖 ``example_lib`` 提供时间格式化、文本截断等工具能力。
    meta 会被 PluginManager 从同目录 plugin.json 自动覆盖。
    """

    meta = PluginMeta(
        id          = "example_plugin",
        name        = "示例插件",
        version     = "1.0.0",
        description = "演示插件格式规范",
        requires    = ["example_lib"],
    )

    def __init__(self):
        self._api: PluginAPI | None = None
        self._lib: ExampleLibInterface | None = None

    # ------------------------------------------------------------------ #
    # 生命周期
    # ------------------------------------------------------------------ #

    def on_load(self, api: PluginAPI) -> None:
        """插件初始化入口。

        在此完成：
        - 读取配置
        - 注册钩子
        - 注册自定义触发器 / 动作
        """
        self._api = api
        self._lib = api.get_plugin("example_lib")

        # 1. 读取持久化配置（首次使用默认值）
        greet_count = api.get_config("stats.greet_count", default=0)

        # 2. 注册钩子
        api.register_hook(HookType.ON_ALARM_AFTER,  self._on_alarm_fired)
        api.register_hook(HookType.ON_TIMER_DONE,   self._on_timer_done)
        api.register_hook(HookType.ON_FOCUS_END,    self._on_focus_end)

        # 3. 注册自动化动作（可在自动化规则中调用）
        api.register_action("example_plugin.greet", self._action_greet)

        # 4. 入场通知
        api.show_toast(
            "示例插件已启动",
            f"本次会话前已问候 {greet_count} 次",
            level="info",
        )

    def on_unload(self) -> None:
        """插件卸载时清理资源。"""
        # 示例：此处无需特殊清理
        pass

    # ------------------------------------------------------------------ #
    # 钩子回调
    # ------------------------------------------------------------------ #

    def _on_alarm_fired(self, alarm_id: str) -> None:
        """闹钟触发后回调。"""
        if self._api is None:
            return
        if self._lib is not None:
            from datetime import datetime
            ts = self._lib.format_timestamp(datetime.now(), "%H:%M")
            label = self._lib.truncate(alarm_id, 20)
            self._api.show_toast(f"闹钟提醒 [{ts}]", f"闹钟 {label} 已响铃", level="info")
        else:
            self._api.show_toast("闹钟提醒", f"闹钟 {alarm_id} 已响铃")

    def _on_timer_done(self, timer_id: str) -> None:
        """计时器归零回调。"""
        # 此处可执行任意逻辑，例如播放自定义音效
        pass

    def _on_focus_end(self, session_minutes: int) -> None:
        """专注会话结束回调。"""
        if self._api is None:
            return
        total = self._api.get_config("stats.focus_minutes", default=0)
        self._api.set_config("stats.focus_minutes", total + session_minutes)
        if self._lib is not None:
            dur = self._lib.friendly_duration(session_minutes * 60)
            self._api.show_toast("专注完成", f"本次专注了 {dur}", level="success")

    # ------------------------------------------------------------------ #
    # 自动化动作
    # ------------------------------------------------------------------ #

    def _action_greet(self, params: dict) -> None:
        """自动化动作：发送问候通知。"""
        if self._api is None:
            return
        msg = params.get("message", "你好！")
        if self._lib is not None:
            msg = self._lib.truncate(msg, 30)
        self._api.show_toast("示例插件问候", msg, level="success")
        count = self._api.get_config("stats.greet_count", default=0)
        self._api.set_config("stats.greet_count", count + 1)

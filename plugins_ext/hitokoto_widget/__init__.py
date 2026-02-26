"""随机一言插件 — 向画布注册 HitokotoWidget 小组件

安装该插件后，可在"添加组件"菜单中找到"随机一言"。

功能
----
- 一言 API（https://v1.hitokoto.cn/）：可选分类（动画/漫画/游戏等）
- 自定义 HTTP API：支持 JSON 路径解析
- 本地文本文件：每行一条，随机抽取

依赖
----
  pip install requests
"""
from __future__ import annotations

from app.plugins import BasePlugin, PluginMeta
from app.plugins.base_plugin import PluginAPI


class Plugin(BasePlugin):
    meta = PluginMeta(
        id          = "hitokoto_widget",
        name        = "随机一言",
        version     = "1.0.0",
        description = "在桌面显示随机一言，支持一言 API、自定义 API 和本地文本文件",
        dependencies= ["requests"],
    )

    def on_load(self, api: PluginAPI) -> None:
        # 将 HitokotoWidget 注册到全局小组件注册表
        from app.widgets.registry import WidgetRegistry
        from .widget import HitokotoWidget

        WidgetRegistry.instance().register(HitokotoWidget)
        api.show_toast("随机一言", "插件已加载，可在添加组件菜单中找到「随机一言」", level="success")

    def on_unload(self) -> None:
        pass

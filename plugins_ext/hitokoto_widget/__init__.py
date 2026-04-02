"""随机一言插件 — 向画布注册 HitokotoWidget 小组件

安装该插件后，可在"添加组件"菜单中找到"随机一言"。

功能
----
- 一言 API（https://v1.hitokoto.cn/）：可选分类（动画/漫画/游戏等）
- 诏预接口（https://hub.saintic.com/openservice/sentence/）：古诗词名句，支持主题和分类筛选
- 自定义 HTTP API：支持 JSON 路径解析
- 本地文本文件：每行一条，随机抽取

依赖
----
  pip install requests
"""
from __future__ import annotations

from app.plugins import BasePlugin, PluginAPI, PluginMeta, PluginPermission


class Plugin(BasePlugin):
    meta = PluginMeta(
        id          = "hitokoto_widget",
        name        = "随机一言",
        version     = "1.1.0",
        description = "在桌面显示随机一言，支持一言 API、诏预接口、自定义 API 和本地文本文件",
        dependencies= ["requests"],
        permissions = [
            PluginPermission.NETWORK,
            PluginPermission.FS_READ,
            PluginPermission.INSTALL_PKG,
        ],
    )

    def on_load(self, api: PluginAPI) -> None:
        from .widget import HitokotoWidget, set_central_config

        self._api = api
        self._register_permission_items()
        self._apply_central_config(api.get_central_plugin_config({}), set_widget_config=set_central_config)
        api.register_central_event("policy.updated", self._on_policy_updated)

        api.register_widget_type(HitokotoWidget)
        api.show_toast("随机一言", "插件已加载，可在添加组件菜单中找到「随机一言」", level="success")

    def on_unload(self) -> None:
        pass

    def _register_permission_items(self) -> None:
        if not hasattr(self, "_api") or self._api is None:
            return
        self._api.register_permission_item(
            "plugin.hitokoto_widget.fetch_quote",
            "获取随机一言内容",
            category="随机一言",
            description="请求在线接口或读取本地文本来源以刷新展示内容",
        )

    def _on_policy_updated(self, _payload: dict) -> None:
        from .widget import set_central_config

        if not hasattr(self, "_api") or self._api is None:
            return
        self._apply_central_config(
            self._api.get_central_plugin_config({}),
            set_widget_config=set_central_config,
        )

    @staticmethod
    def _apply_central_config(config: object, *, set_widget_config) -> None:
        normalized = dict(config) if isinstance(config, dict) else {}
        try:
            set_widget_config(normalized)
        except Exception:
            pass

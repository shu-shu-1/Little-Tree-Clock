"""随机一言插件：向画布注册 HitokotoWidget 组件，并对外提供数据源注册接口。"""

from __future__ import annotations

from typing import Any

from app.plugins import BasePlugin, PluginAPI, PluginMeta, PluginPermission

# 外部数据源接口版本号（契约变化时递增，供提供方做兼容判断）
# 1.0：register/unregister/list + fetch -> (text, source_info)
# 1.1：fetch 可返回第三项 extras（扩展行），组件为每行新建徽章显示行
DATA_SOURCE_API_VERSION = "1.1"


class HitokotoInterface:
    """「随机一言」对外数据源接口，通过 ``api.get_plugin("hitokoto_widget")`` 获取。

    所有方法线程安全；``fetch`` 回调将在后台线程中被调用。
    """

    DATA_SOURCE_API_VERSION = DATA_SOURCE_API_VERSION

    def register_data_source(
        self,
        source_id: str,
        fetch,
        *,
        name: str = "",
        name_i18n: object = None,
        owner_plugin_id: str = "",
        options: object = None,
    ) -> bool:
        """注册数据源；同提供方可覆盖更新，非法参数或来源 ID 被他人占用返回 False。

        ``fetch(options, props)`` 在后台线程调用，返回二元组 ``(text, source_info)``
        或三元组（接口版本 ≥ 1.1，第三项为扩展行，接受 list/dict 形式）。
        """
        from .sources import register_external_source

        return register_external_source(
            source_id,
            fetch,
            name=name,
            name_i18n=name_i18n,
            owner_plugin_id=owner_plugin_id,
            options=options,
        )

    def unregister_data_source(self, source_id: str, *, owner_plugin_id: object = None) -> bool:
        """注销数据源；传入 owner_plugin_id 时执行归属校验。"""
        from .sources import unregister_external_source

        return unregister_external_source(source_id, owner_plugin_id=owner_plugin_id)

    def list_data_sources(self) -> list[dict[str, Any]]:
        from .sources import all_external_sources

        return [
            {
                "source_id": ext.source_id,
                "name": ext.name,
                "name_i18n": dict(ext.name_i18n),
                "owner_plugin_id": ext.owner_plugin_id,
                "options": [
                    {
                        "key": opt.key,
                        "label": opt.label,
                        "type": opt.type,
                        "default": opt.default,
                        "choices": [list(pair) for pair in opt.choices],
                    }
                    for opt in ext.options
                ],
            }
            for ext in all_external_sources()
        ]


class Plugin(BasePlugin):
    meta = PluginMeta(
        id="hitokoto_widget",
        name="随机一言",
        version="1.4.0",
        description="在桌面显示随机一言，支持一言 API、诏预接口、自定义 API、本地文本文件和插件扩展数据源（可新建扩展行，如教材标注）",
        dependencies=["requests"],
        permissions=[
            PluginPermission.NETWORK,
            PluginPermission.FS_READ,
            PluginPermission.INSTALL_PKG,
        ],
    )

    def __init__(self):
        self._api: PluginAPI | None = None
        self._interface: HitokotoInterface | None = None

    def on_load(self, api: PluginAPI) -> None:
        from .widget import HitokotoWidget, set_central_config

        self._api = api
        self._interface = HitokotoInterface()
        self._register_permission_items()
        self._apply_central_config(api.get_central_plugin_config({}), set_widget_config=set_central_config)
        api.register_central_event("policy.updated", self._on_policy_updated)

        api.register_widget_type(HitokotoWidget)
        api.show_toast("随机一言", "插件已加载，可在添加组件菜单中找到「随机一言」", level="success")

    def on_unload(self) -> None:
        # 本插件卸载时，其注册表（含外部数据源）一并失效
        from .sources import clear_external_sources

        clear_external_sources()

    def export(self) -> HitokotoInterface:
        """对外暴露数据源管理接口，供其他插件通过 ``api.get_plugin`` 获取。"""
        if self._interface is None:
            self._interface = HitokotoInterface()
        return self._interface

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

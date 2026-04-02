"""文档浏览插件。"""
from __future__ import annotations

from app.plugins import BasePlugin, PluginAPI, PluginMeta, PluginPermission


class Plugin(BasePlugin):
    meta = PluginMeta(
        id="document_viewer",
        name="文档浏览",
        version="1.0.0",
        description="在画布中浏览 Word/Markdown/TXT/PDF，支持自动滚动与缩放。",
        dependencies=["mammoth", "python-docx", "pymupdf"],
        permissions=[
            PluginPermission.FS_READ,
            PluginPermission.INSTALL_PKG,
        ],
        tags=["widget", "document", "reader"],
    )

    def on_load(self, api: PluginAPI) -> None:
        from .widget import DocumentViewerWidget, set_central_config

        self._api = api
        self._register_permission_items()
        self._apply_central_config(api.get_central_plugin_config({}), set_widget_config=set_central_config)
        api.register_central_event("policy.updated", self._on_policy_updated)

        api.register_widget_type(DocumentViewerWidget)
        api.show_toast("文档浏览", "插件已加载，可在添加组件菜单中找到「文档浏览」", level="success")

    def on_unload(self) -> None:
        pass

    def _register_permission_items(self) -> None:
        if not hasattr(self, "_api") or self._api is None:
            return
        self._api.register_permission_item(
            "plugin.document_viewer.open_document",
            "打开文档文件",
            category="文档浏览",
            description="读取并渲染 Word/Markdown/TXT/PDF 文档内容",
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

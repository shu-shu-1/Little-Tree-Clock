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
        from .widget import DocumentViewerWidget

        api.register_widget_type(DocumentViewerWidget)
        api.show_toast("文档浏览", "插件已加载，可在添加组件菜单中找到「文档浏览」", level="success")

    def on_unload(self) -> None:
        pass

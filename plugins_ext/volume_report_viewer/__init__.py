"""音量报告可视化插件。"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import QWidget
from qfluentwidgets import FluentIcon as FIF

from app.plugins import BasePlugin, PluginAPI, PluginMeta

from .service import VolumeReportService


class Plugin(BasePlugin):
    meta = PluginMeta(
        id="volume_report_viewer",
        name="音量报告可视化",
        version="1.0.0",
        description="读取音量检测报告并在侧边栏可视化展示，支持导出图片。",
        tags=["audio", "report", "visualization"],
    )

    def on_load(self, api: PluginAPI) -> None:
        self._api = api
        data_dir = api.get_data_dir() or (Path(__file__).parent / "_data")
        self._service = VolumeReportService(data_dir=data_dir, api=api)
        self._register_permission_items()
        self._apply_central_config(api.get_central_plugin_config({}))
        api.register_central_event("policy.updated", self._on_policy_updated)

    def create_sidebar_widget(self) -> Optional[QWidget]:
        from .sidebar import VolumeReportSidebarPanel

        return VolumeReportSidebarPanel(self._service)

    def get_sidebar_icon(self):
        return FIF.MEGAPHONE

    def get_sidebar_label(self) -> str:
        return "音量报告"

    def _register_permission_items(self) -> None:
        if not hasattr(self, "_api") or self._api is None:
            return
        self._api.register_permission_item(
            "plugin.volume_report_viewer.import_report",
            "导入音量报告",
            category="音量报告可视化",
            description="从本地 JSON 导入音量报告到插件目录",
        )
        self._api.register_permission_item(
            "plugin.volume_report_viewer.export_report",
            "导出音量报告图片",
            category="音量报告可视化",
            description="将可视化详情导出为 PNG 图片",
        )
        self._api.register_permission_item(
            "plugin.volume_report_viewer.delete_report",
            "删除音量报告",
            category="音量报告可视化",
            description="删除插件目录中的音量报告文件",
        )

    def _on_policy_updated(self, _payload: dict) -> None:
        if not hasattr(self, "_api") or self._api is None:
            return
        self._apply_central_config(self._api.get_central_plugin_config({}))

    def _apply_central_config(self, config: object) -> None:
        normalized = dict(config) if isinstance(config, dict) else {}
        if hasattr(self, "_service") and self._service is not None:
            self._service.set_central_config(normalized)

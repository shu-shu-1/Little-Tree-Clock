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
        data_dir = api.get_data_dir() or (Path(__file__).parent / "_data")
        self._service = VolumeReportService(data_dir=data_dir)

    def create_sidebar_widget(self) -> Optional[QWidget]:
        from .sidebar import VolumeReportSidebarPanel

        return VolumeReportSidebarPanel(self._service)

    def get_sidebar_icon(self):
        return FIF.MEGAPHONE

    def get_sidebar_label(self) -> str:
        return "音量报告"

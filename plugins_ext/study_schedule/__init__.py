"""自习时间安排插件。"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import QWidget
from qfluentwidgets import FluentIcon as FIF

from app.events import EventType
from app.plugins import BasePlugin, PluginAPI, PluginMeta

from .service import StudyScheduleService
from .widgets import StudyCurrentItemWidget, StudyRemainingTimeWidget, StudyTimePeriodWidget


class Plugin(BasePlugin):
    meta = PluginMeta(
        id="study_schedule",
        name="自习时间安排",
        version="1.0.0",
        description="按事项组和时间段管理自习安排，并可复用共享布局预设。",
        requires=["layout_presets"],
        tags=["education", "study", "schedule"],
    )

    def on_load(self, api: PluginAPI) -> None:
        self._api = api
        preset_service = api.get_plugin("layout_presets")
        if preset_service is None:
            raise RuntimeError("layout_presets 不可用")

        data_dir = api.get_data_dir() or (Path(__file__).parent / "_data")
        world_zone_service = api.get_service("world_zone_service")
        self._svc = StudyScheduleService(
            data_dir=data_dir,
            api=api,
            preset_service=preset_service,
            world_zone_service=world_zone_service,
        )
        api.register_canvas_service("study_service", self._svc)
        for widget_cls in (StudyCurrentItemWidget, StudyTimePeriodWidget, StudyRemainingTimeWidget):
            api.register_widget_type(widget_cls)
        api.subscribe_event(EventType.FULLSCREEN_OPENED, self._on_fullscreen_opened)

    def on_unload(self) -> None:
        if hasattr(self, "_svc") and self._svc:
            self._svc._timer.stop()
        if hasattr(self, "_api") and self._api:
            for widget_type in (
                StudyCurrentItemWidget.WIDGET_TYPE,
                StudyTimePeriodWidget.WIDGET_TYPE,
                StudyRemainingTimeWidget.WIDGET_TYPE,
            ):
                self._api.unregister_widget_type(widget_type)

    def create_sidebar_widget(self) -> Optional[QWidget]:
        from .sidebar import StudyScheduleSidebarPanel
        return StudyScheduleSidebarPanel(self._svc)

    def create_settings_widget(self) -> Optional[QWidget]:
        from .settings_widget import StudyScheduleSettingsWidget
        return StudyScheduleSettingsWidget(self._svc)

    def get_sidebar_icon(self):
        return FIF.HISTORY

    def _on_fullscreen_opened(self, zone_id: str = "", **_) -> None:
        if zone_id:
            self._svc.set_last_zone(zone_id)

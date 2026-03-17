"""自习时间安排插件。"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QPushButton, QWidget
from qfluentwidgets import Action, FluentIcon as FIF, RoundMenu, Theme

from app.events import EventType
from app.plugins import BasePlugin, PluginAPI, PluginMeta

from .service import StudyScheduleService
from .widgets import (
    StudyCurrentItemWidget,
    StudyNextItemWidget,
    StudyRemainingTimeWidget,
    StudyTimePeriodWidget,
    StudyTodayScheduleWidget,
)
from .volume_report import VolumeReportWindow


class Plugin(BasePlugin):
    meta = PluginMeta(
        id="study_schedule",
        name="自习时间安排",
        version="1.4.0",
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
        clock_service = api.get_service("clock_service")
        self._svc = StudyScheduleService(
            data_dir=data_dir,
            api=api,
            preset_service=preset_service,
            world_zone_service=world_zone_service,
            clock_service=clock_service,
        )
        self._report_windows: list[VolumeReportWindow] = []
        volume_api = api.get_plugin("volume_detector")
        if volume_api is not None:
            self._svc.attach_volume_api(volume_api)
        self._svc.volume_report_ready.connect(self._on_volume_report_ready)
        api.register_canvas_service("study_service", self._svc)
        for widget_cls in (
            StudyCurrentItemWidget,
            StudyTimePeriodWidget,
            StudyRemainingTimeWidget,
            StudyTodayScheduleWidget,
            StudyNextItemWidget,
        ):
            api.register_widget_type(widget_cls)
        api.register_canvas_topbar_btn_factory(self._make_topbar_buttons)
        api.subscribe_event(EventType.FULLSCREEN_OPENED, self._on_fullscreen_opened)

    def on_unload(self) -> None:
        if hasattr(self, "_report_windows"):
            for win in list(self._report_windows):
                try:
                    win.close()
                except Exception:
                    pass
            self._report_windows.clear()
        if hasattr(self, "_svc") and self._svc:
            self._svc.shutdown()
        if hasattr(self, "_api") and self._api:
            for widget_type in (
                StudyCurrentItemWidget.WIDGET_TYPE,
                StudyTimePeriodWidget.WIDGET_TYPE,
                StudyRemainingTimeWidget.WIDGET_TYPE,
                StudyTodayScheduleWidget.WIDGET_TYPE,
                StudyNextItemWidget.WIDGET_TYPE,
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

    def _make_topbar_buttons(self, zone_id: str):
        self._svc.set_last_zone(zone_id)
        return [_StudyGroupSwitchButton(self._svc, zone_id)]

    def _on_fullscreen_opened(self, zone_id: str = "", **_) -> None:
        if zone_id:
            self._svc.set_last_zone(zone_id)

    def _on_volume_report_ready(self, report: dict) -> None:
        try:
            auto_close = int(self._svc.get_setting("volume_report_auto_close_sec", 10))
        except Exception:
            auto_close = 10
        window = VolumeReportWindow(report, auto_close_sec=auto_close)
        window.destroyed.connect(lambda *_: self._report_windows.remove(window) if window in self._report_windows else None)
        self._report_windows.append(window)
        try:
            item_name = report.get("item_name") or "音量报告"
            if hasattr(self, "_api"):
                self._api.show_toast("音量报告", f"{item_name} 已生成", level="info")
        except Exception:
            pass


_TOPBAR_STYLE = (
    "QPushButton{"
    "color:rgba(255,255,255,200);"
    "background:rgba(255,255,255,15);"
    "border:1px solid rgba(255,255,255,50);"
    "border-radius:8px;"
    "padding:5px 14px;"
    "font-size:13px;}"
    "QPushButton:hover{"
    "background:rgba(255,255,255,30);"
    "border-color:rgba(255,255,255,80);}"
    "QPushButton:pressed{"
    "background:rgba(255,255,255,18);}"
)


class _TopbarButton(QPushButton):
    def __init__(self, icon, text: str, parent=None):
        super().__init__(parent)
        self.setText(text)
        self.setIcon(icon.icon(Theme.DARK))
        self.setIconSize(QSize(16, 16))
        self.setFixedHeight(36)
        self.setMinimumWidth(108)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(_TOPBAR_STYLE)


class _StudyGroupSwitchButton(_TopbarButton):
    def __init__(self, svc: StudyScheduleService, zone_id: str, parent=None):
        super().__init__(FIF.HISTORY, "切换事项组", parent)
        self._svc = svc
        self._zone_id = zone_id

        svc.current_group_changed.connect(lambda *_: self._refresh_text())
        svc.groups_updated.connect(self._refresh_text)
        self._refresh_text()
        self.clicked.connect(self._show_menu)

    def _refresh_text(self) -> None:
        group = self._svc.get_current_group()
        self.setToolTip(f"当前事项组：{group.name}" if group else "当前未选择事项组")

    def _show_menu(self) -> None:
        menu = RoundMenu(parent=self)
        groups = self._svc.groups()
        if not groups:
            act = Action(FIF.HISTORY, "（暂无事项组）")
            act.setEnabled(False)
            menu.addAction(act)
        else:
            current_id = self._svc.current_group_id
            for group in groups:
                act = Action(FIF.HISTORY, group.name)
                act.setCheckable(True)
                act.setChecked(group.id == current_id)
                act.triggered.connect(lambda _checked=False, gid=group.id: self._switch_group(gid))
                menu.addAction(act)
        menu.addSeparator()
        auto_act = Action(FIF.SYNC, "恢复自动选择")
        auto_act.triggered.connect(self._resume_auto_select)
        menu.addAction(auto_act)
        menu.exec(self.mapToGlobal(self.rect().bottomLeft()))

    def _switch_group(self, group_id: str) -> None:
        self._svc.set_last_zone(self._zone_id)
        self._svc.set_current_group(group_id, apply_preset=True)

    def _resume_auto_select(self) -> None:
        self._svc.set_last_zone(self._zone_id)
        self._svc.set_current_group("", apply_preset=False)
        refresh = getattr(self._svc, "_refresh_runtime_state", None)
        if callable(refresh):
            refresh()

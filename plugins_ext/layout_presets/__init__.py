"""共享布局预设插件。"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QPushButton, QWidget
from qfluentwidgets import Action, FluentIcon as FIF, RoundMenu, Theme

from app.events import EventType
from app.plugins import LibraryPlugin, PluginAPI, PluginMeta, PluginType

from .service import LayoutPresetService


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


class Plugin(LibraryPlugin):
    meta = PluginMeta(
        id="layout_presets",
        name="布局预设",
        version="1.0.0",
        description="提供跨插件共享的全屏画布布局预设，支持保存、切换和复用。",
        plugin_type=PluginType.LIBRARY,
        tags=["education", "layout", "canvas"],
    )

    def on_load(self, api: PluginAPI) -> None:
        self._api = api
        data_dir = api.get_data_dir() or (Path(__file__).parent / "_data")
        world_zone_service = api.get_service("world_zone_service")
        self._svc = LayoutPresetService(data_dir=data_dir, api=api, world_zone_service=world_zone_service)
        api.register_canvas_topbar_btn_factory(self._make_topbar_buttons)
        api.subscribe_event(EventType.FULLSCREEN_OPENED, self._on_fullscreen_opened)

    def export(self) -> LayoutPresetService:
        return self._svc

    def create_sidebar_widget(self) -> Optional[QWidget]:
        from .sidebar import LayoutPresetSidebarPanel
        return LayoutPresetSidebarPanel(self._svc)

    def get_sidebar_icon(self):
        return FIF.LAYOUT

    def get_sidebar_label(self) -> str:
        return "布局预设"

    def _on_fullscreen_opened(self, zone_id: str = "", **_) -> None:
        if zone_id:
            self._svc.set_current_zone(zone_id)

    def _make_topbar_buttons(self, zone_id: str):
        self._svc.set_current_zone(zone_id)
        return [
            _PresetSwitchButton(self._svc, zone_id),
            _SavePresetButton(self._svc, zone_id),
        ]


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


class _PresetSwitchButton(_TopbarButton):
    def __init__(self, svc: LayoutPresetService, zone_id: str, parent=None):
        super().__init__(FIF.LAYOUT, "切换预设", parent)
        self._svc = svc
        self._zone_id = zone_id
        self._svc.presets_updated.connect(self._refresh_text)
        self._svc.active_preset_changed.connect(lambda zid, _pid: self._refresh_text() if zid == self._zone_id else None)
        self._refresh_text()
        self.clicked.connect(self._show_menu)

    def _refresh_text(self) -> None:
        preset = self._svc.get_active_preset(self._zone_id)
        self.setToolTip(f"当前预设：{preset.name}" if preset else "当前未记录共享预设")

    def _show_menu(self) -> None:
        menu = RoundMenu(parent=self)
        presets = self._svc.presets()
        if not presets:
            act = Action(FIF.LAYOUT, "（暂无预设）")
            act.setEnabled(False)
            menu.addAction(act)
        else:
            current_id = self._svc.get_active_preset_id(self._zone_id)
            for preset in presets:
                act = Action(FIF.LAYOUT, preset.name)
                act.setCheckable(True)
                act.setChecked(preset.id == current_id)
                act.triggered.connect(lambda _checked=False, pid=preset.id: self._svc.apply_preset(pid, self._zone_id))
                menu.addAction(act)
        menu.exec(self.mapToGlobal(self.rect().bottomLeft()))


class _SavePresetButton(_TopbarButton):
    def __init__(self, svc: LayoutPresetService, zone_id: str, parent=None):
        super().__init__(FIF.SAVE, "保存预设", parent)
        self._svc = svc
        self._zone_id = zone_id
        self.setToolTip("将当前全屏布局保存为共享预设")
        self.clicked.connect(self._show_menu)

    def _show_menu(self) -> None:
        menu = RoundMenu(parent=self)
        presets = self._svc.presets()
        if presets:
            for preset in presets:
                act = Action(FIF.SAVE, f"覆盖：{preset.name}")
                act.triggered.connect(lambda _checked=False, pid=preset.id: self._overwrite_preset(pid))
                menu.addAction(act)
            menu.addSeparator()
        new_act = Action(FIF.ADD, "新建预设…")
        new_act.triggered.connect(self._new_preset)
        menu.addAction(new_act)
        menu.exec(self.mapToGlobal(self.rect().bottomLeft()))

    def _overwrite_preset(self, preset_id: str) -> None:
        self._svc.update_preset_from_zone(preset_id, self._zone_id)

    def _new_preset(self) -> None:
        from .sidebar import _PresetDialog

        dlg = _PresetDialog(parent=self.window())
        if not dlg.exec():
            return
        preset = dlg.result_preset()
        saved = self._svc.create_preset_from_zone(
            self._zone_id,
            name=preset.name,
            description=preset.description,
        )
        if saved is not None:
            self._svc.apply_preset(saved.id, self._zone_id)

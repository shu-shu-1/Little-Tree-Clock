"""共享布局预设插件。"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QInputDialog, QPushButton, QWidget
from qfluentwidgets import Action, FluentIcon as FIF, InfoBar, InfoBarPosition, RoundMenu, Theme

from app.events import EventType
from app.plugins import LibraryPlugin, PluginAPI, PluginMeta, PluginType
from app.utils.logger import logger

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
        self._register_permission_items()
        data_dir = api.get_data_dir() or (Path(__file__).parent / "_data")
        world_zone_service = api.get_service("world_zone_service")
        self._svc = LayoutPresetService(data_dir=data_dir, api=api, world_zone_service=world_zone_service)
        self._apply_central_config(api.get_central_plugin_config({}))
        api.register_central_event("policy.updated", self._on_policy_updated)
        api.register_canvas_topbar_btn_factory(self._make_topbar_buttons)
        api.register_layout_open_action(
            action_id="layout_presets.import_as_preset",
            title="添加到预设",
            content="将布局文件保存为共享预设",
            handler=self._on_layout_file_open,
            order=20,
            breadcrumb=["插件扩展", "布局预设"],
            wizard_pages=[
                {
                    "type": "text",
                    "title": "预设信息",
                    "title_i18n": {
                        "zh-CN": "预设信息",
                        "en-US": "Preset Info",
                    },
                    "description": "请输入导入后保存的预设名称。",
                    "description_i18n": {
                        "zh-CN": "请输入导入后保存的预设名称。",
                        "en-US": "Enter the preset name to save after importing.",
                    },
                    "field": "preset_name",
                    "label": "预设名称",
                    "label_i18n": {
                        "zh-CN": "预设名称",
                        "en-US": "Preset Name",
                    },
                    "placeholder": "例如：晚自习布局",
                    "placeholder_i18n": {
                        "zh-CN": "例如：晚自习布局",
                        "en-US": "e.g. Evening Self-study Layout",
                    },
                    "required": True,
                    "empty_error_i18n": {
                        "zh-CN": "请先填写预设名称再继续。",
                        "en-US": "Please enter a preset name before continuing.",
                    },
                }
            ],
            title_i18n={"zh-CN": "添加到预设", "en-US": "Add As Preset"},
            description_i18n={
                "zh-CN": "导入布局文件并保存为布局预设",
                "en-US": "Import layout file and save as a preset",
            },
        )
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

    def _register_permission_items(self) -> None:
        self._api.register_permission_item(
            "plugin.layout_presets.manage_presets",
            "管理布局预设",
            category="布局预设",
            description="创建、导入、覆盖、重命名和删除共享布局预设",
        )
        self._api.register_permission_item(
            "plugin.layout_presets.apply_preset",
            "应用布局预设",
            category="布局预设",
            description="将共享布局预设应用到目标全屏画布",
        )

    def _on_policy_updated(self, _payload: dict) -> None:
        if not hasattr(self, "_api") or self._api is None:
            return
        self._apply_central_config(self._api.get_central_plugin_config({}))

    def _apply_central_config(self, config: object) -> None:
        normalized = dict(config) if isinstance(config, dict) else {}
        if hasattr(self, "_svc") and self._svc is not None:
            self._svc.set_central_config(normalized)

    def _on_fullscreen_opened(self, zone_id: str = "", **_) -> None:
        if zone_id:
            self._svc.set_current_zone(zone_id)

    def _make_topbar_buttons(self, zone_id: str):
        self._svc.set_current_zone(zone_id)
        if not self._svc.is_action_allowed("topbar_buttons"):
            return []
        return [
            _PresetSwitchButton(self._svc, zone_id),
            _SavePresetButton(self._svc, zone_id),
        ]

    def _on_layout_file_open(self, file_path: Path, *, parent=None, context: Optional[dict] = None) -> bool:
        if not self._svc.is_action_allowed("import_layout"):
            InfoBar.warning(
                "已被集控禁用",
                "当前策略禁止通过布局文件导入预设。",
                duration=2800,
                parent=parent,
                position=InfoBarPosition.TOP_RIGHT,
            )
            return False
        if not self._svc.ensure_access(
            "plugin.layout_presets.manage_presets",
            reason="从布局文件导入共享预设",
            parent=parent,
        ):
            return False
        try:
            preset = self._svc.build_preset_from_layout_file(
                file_path,
                fallback_zone_id=self._svc.current_zone_id,
            )
        except Exception as exc:
            logger.exception("[布局预设] 通过文件打开导入失败: path={}", file_path)
            InfoBar.error(
                "导入失败",
                str(exc),
                duration=3200,
                parent=parent,
                position=InfoBarPosition.TOP_RIGHT,
            )
            return False

        preset_name = str((context or {}).get("preset_name") or "").strip()
        if not preset_name:
            name, ok = QInputDialog.getText(
                parent,
                "添加到预设",
                "请输入预设名称：",
                text=preset.name,
            )
            if not ok:
                return False
            preset_name = str(name or "").strip()

        if not preset_name:
            InfoBar.warning(
                "名称不能为空",
                "请填写预设名称后再保存。",
                duration=2200,
                parent=parent,
                position=InfoBarPosition.TOP_RIGHT,
            )
            return False

        preset.name = preset_name
        saved = self._svc.save_preset(preset)
        InfoBar.success(
            "已添加到预设",
            f"预设「{saved.name}」已保存",
            duration=2200,
            parent=parent,
            position=InfoBarPosition.TOP_RIGHT,
        )
        return True


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
        current_id = self._svc.get_active_preset_id(self._zone_id)
        if current_id:
            current = self._svc.get_preset(current_id)
            if current is not None:
                overwrite_act = Action(FIF.SAVE, f"覆盖当前预设：{current.name}")
                overwrite_act.triggered.connect(lambda _checked=False, pid=current.id: self._overwrite_preset(pid))
                menu.addAction(overwrite_act)
                menu.addSeparator()

        if not presets:
            act = Action(FIF.LAYOUT, "（暂无预设）")
            act.setEnabled(False)
            menu.addAction(act)
        else:
            for preset in presets:
                act = Action(FIF.LAYOUT, preset.name)
                act.setCheckable(True)
                act.setChecked(preset.id == current_id)
                act.triggered.connect(lambda _checked=False, pid=preset.id: self._apply_preset(pid))
                menu.addAction(act)
        menu.exec(self.mapToGlobal(self.rect().bottomLeft()))

    def _apply_preset(self, preset_id: str) -> None:
        if not self._svc.is_action_allowed("apply_preset"):
            InfoBar.warning(
                "已被集控禁用",
                "当前策略禁止应用布局预设。",
                duration=2200,
                parent=self.window(),
                position=InfoBarPosition.BOTTOM,
            )
            return
        if not self._svc.ensure_access(
            "plugin.layout_presets.apply_preset",
            reason="在全屏画布中切换共享预设",
            parent=self.window(),
        ):
            return
        preset = self._svc.get_preset(preset_id)
        if preset is None:
            InfoBar.warning(
                "切换失败",
                "目标预设不存在或已被删除",
                duration=2200,
                parent=self.window(),
                position=InfoBarPosition.BOTTOM,
            )
            return
        if self._svc.apply_preset(preset_id, self._zone_id):
            InfoBar.success(
                "已应用",
                f"已切换到预设「{preset.name}」",
                duration=1800,
                parent=self.window(),
                position=InfoBarPosition.BOTTOM,
            )
        else:
            InfoBar.error(
                "切换失败",
                "无法应用到当前全屏画布，请检查目标画布是否仍存在",
                duration=2600,
                parent=self.window(),
                position=InfoBarPosition.BOTTOM,
            )

    def _overwrite_preset(self, preset_id: str) -> None:
        if not self._svc.is_action_allowed("overwrite_preset"):
            InfoBar.warning(
                "已被集控禁用",
                "当前策略禁止覆盖预设。",
                duration=2200,
                parent=self.window(),
                position=InfoBarPosition.BOTTOM,
            )
            return
        if not self._svc.ensure_access(
            "plugin.layout_presets.manage_presets",
            reason="用当前全屏布局覆盖共享预设",
            parent=self.window(),
        ):
            return
        preset = self._svc.get_preset(preset_id)
        updated = self._svc.update_preset_from_zone(preset_id, self._zone_id)
        if updated is None:
            InfoBar.error(
                "覆盖失败",
                "无法读取当前画布布局或预设已失效",
                duration=2600,
                parent=self.window(),
                position=InfoBarPosition.BOTTOM,
            )
            return
        InfoBar.success(
            "已覆盖",
            f"预设「{updated.name if updated else (preset.name if preset else '')}」已更新",
            duration=1800,
            parent=self.window(),
            position=InfoBarPosition.BOTTOM,
        )


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
        if not self._svc.is_action_allowed("overwrite_preset"):
            InfoBar.warning(
                "已被集控禁用",
                "当前策略禁止覆盖预设。",
                duration=2200,
                parent=self.window(),
                position=InfoBarPosition.BOTTOM,
            )
            return
        if not self._svc.ensure_access(
            "plugin.layout_presets.manage_presets",
            reason="用当前全屏布局覆盖共享预设",
            parent=self.window(),
        ):
            return
        self._svc.update_preset_from_zone(preset_id, self._zone_id)

    def _new_preset(self) -> None:
        if not self._svc.is_action_allowed("create_preset"):
            InfoBar.warning(
                "已被集控禁用",
                "当前策略禁止创建预设。",
                duration=2200,
                parent=self.window(),
                position=InfoBarPosition.BOTTOM,
            )
            return
        if not self._svc.ensure_access(
            "plugin.layout_presets.manage_presets",
            reason="创建共享布局预设",
            parent=self.window(),
        ):
            return
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

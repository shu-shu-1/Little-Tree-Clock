"""共享布局预设侧边栏。"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    ComboBox,
    FluentIcon as FIF,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    ListWidget,
    MessageBox,
    PushButton,
    SubtitleLabel,
    ToolButton,
)

from .models import LayoutPreset


class _PresetDialog(MessageBox):
    def __init__(self, preset: Optional[LayoutPreset] = None, parent=None):
        title = "编辑预设" if preset else "新建预设"
        super().__init__(title, "", parent)
        self.yesButton.setText("保存")
        self.cancelButton.setText("取消")
        self.contentLabel.hide()

        self._preset = preset or LayoutPreset()

        form = QFormLayout()
        form.setVerticalSpacing(10)
        self._name_edit = LineEdit()
        self._name_edit.setPlaceholderText("预设名称")
        self._name_edit.setText(self._preset.name)
        self._desc_edit = LineEdit()
        self._desc_edit.setPlaceholderText("可选说明")
        self._desc_edit.setText(self._preset.description)
        form.addRow("预设名称:", self._name_edit)
        form.addRow("说明:", self._desc_edit)
        self.textLayout.addLayout(form)

    def accept(self) -> None:
        name = self._name_edit.text().strip()
        if not name:
            InfoBar.warning(
                "提示",
                "预设名称不能为空",
                duration=2000,
                parent=self,
                position=InfoBarPosition.TOP,
            )
            return
        self._preset.name = name
        self._preset.description = self._desc_edit.text().strip()
        super().accept()

    def result_preset(self) -> LayoutPreset:
        return self._preset


class LayoutPresetSidebarPanel(QWidget):
    def __init__(self, svc, parent=None):
        super().__init__(parent)
        self.setObjectName("layoutPresetSidebarPanel")
        self._svc = svc

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QWidget()
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(20, 12, 16, 14)
        header_layout.setSpacing(6)
        header_layout.addWidget(SubtitleLabel("布局预设"))
        self._summary = CaptionLabel("保存、应用并共享全屏画布布局预设")
        self._summary.setWordWrap(True)
        header_layout.addWidget(self._summary)
        root.addWidget(header)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: rgba(128,128,128,60);")
        root.addWidget(sep)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(12, 12, 12, 12)
        body_layout.setSpacing(10)

        zone_row = QHBoxLayout()
        zone_row.addWidget(BodyLabel("目标画布:"))
        self._zone_combo = ComboBox()
        self._zone_combo.setMinimumWidth(180)
        self._zone_combo.currentIndexChanged.connect(self._on_zone_changed)
        zone_row.addWidget(self._zone_combo, 1)
        self._zone_refresh_btn = ToolButton(FIF.SYNC)
        self._zone_refresh_btn.setToolTip("刷新画布列表")
        self._zone_refresh_btn.clicked.connect(self._refresh_zones)
        zone_row.addWidget(self._zone_refresh_btn)
        body_layout.addLayout(zone_row)

        note = CaptionLabel("说明：考试面板和自习时间安排可直接复用这些预设；绑定关系在各自插件中配置。")
        note.setWordWrap(True)
        body_layout.addWidget(note)

        top_row = QHBoxLayout()
        self._save_btn = PushButton(FIF.SAVE, "保存当前布局为预设")
        self._save_btn.clicked.connect(self._on_save_current)
        top_row.addWidget(self._save_btn)
        self._import_btn = PushButton(FIF.DOWNLOAD, "从布局文件导入预设")
        self._import_btn.clicked.connect(self._on_import_layout_file)
        top_row.addWidget(self._import_btn)
        top_row.addStretch()
        body_layout.addLayout(top_row)

        self._list = ListWidget()
        body_layout.addWidget(self._list, 1)

        bottom = QHBoxLayout()
        self._apply_btn = PushButton(FIF.PLAY, "应用")
        self._overwrite_btn = PushButton(FIF.SAVE, "用当前布局覆盖")
        self._rename_btn = PushButton(FIF.EDIT, "重命名")
        self._delete_btn = PushButton(FIF.DELETE, "删除")
        for btn in (self._apply_btn, self._overwrite_btn, self._rename_btn, self._delete_btn):
            bottom.addWidget(btn)
        bottom.addStretch()
        body_layout.addLayout(bottom)

        self._apply_btn.clicked.connect(self._on_apply)
        self._overwrite_btn.clicked.connect(self._on_overwrite)
        self._rename_btn.clicked.connect(self._on_rename)
        self._delete_btn.clicked.connect(self._on_delete)

        root.addWidget(body, 1)

        svc.presets_updated.connect(self._refresh_presets)
        svc.active_preset_changed.connect(lambda *_: self._refresh_presets())
        svc.current_zone_changed.connect(self._sync_zone_from_service)

        self._refresh_zones()
        self._refresh_presets()

    # ------------------------------------------------------------------ #

    def _selected_zone_id(self) -> str:
        zone_id = self._zone_combo.currentData() or ""
        return self._svc.normalize_zone_id(zone_id)

    def _selected_preset_id(self) -> str:
        item = self._list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else ""

    def _refresh_zones(self) -> None:
        previous = self._selected_zone_id() or self._svc.current_zone_id
        zones = self._svc.list_zones()
        self._zone_combo.blockSignals(True)
        self._zone_combo.clear()
        for zone in zones:
            self._zone_combo.addItem(
                str(zone.get("display_name") or zone.get("label") or zone.get("timezone") or zone.get("id") or "未命名画布"),
                userData=str(zone.get("id") or ""),
            )
        if zones:
            target = self._svc.normalize_zone_id(previous)
            index = next(
                (i for i in range(self._zone_combo.count()) if self._zone_combo.itemData(i) == target),
                0,
            )
            self._zone_combo.setCurrentIndex(index)
            self._svc.set_current_zone(self._zone_combo.itemData(index) or "")
        else:
            self._svc.set_current_zone("")
        self._zone_combo.blockSignals(False)
        self._sync_zone_from_service(self._svc.current_zone_id)

    def _sync_zone_from_service(self, zone_id: str) -> None:
        if not zone_id:
            self._summary.setText("当前未选择目标画布，可先在这里选择世界时钟卡片后再保存或应用预设")
            return
        display = self._svc.get_zone_display_name(zone_id)
        self._summary.setText(f"当前目标画布：{display}")
        index = next(
            (i for i in range(self._zone_combo.count()) if self._zone_combo.itemData(i) == zone_id),
            -1,
        )
        if index >= 0 and self._zone_combo.currentIndex() != index:
            self._zone_combo.blockSignals(True)
            self._zone_combo.setCurrentIndex(index)
            self._zone_combo.blockSignals(False)

    def _refresh_presets(self) -> None:
        zone_id = self._selected_zone_id()
        active_id = self._svc.get_active_preset_id(zone_id) if zone_id else ""
        self._list.clear()
        for preset in self._svc.presets():
            source = self._svc.get_zone_display_name(preset.zone_id, fallback="未知画布") if preset.zone_id else "未记录来源"
            line = preset.name
            extras: list[str] = []
            if preset.description:
                extras.append(preset.description)
            extras.append(f"来源：{source}")
            if active_id and preset.id == active_id:
                extras.append("当前")
            item = QListWidgetItem(f"{line}\n{' · '.join(extras)}")
            item.setData(Qt.ItemDataRole.UserRole, preset.id)
            self._list.addItem(item)

    def _select_preset(self, preset_id: str) -> None:
        if not preset_id:
            return
        for index in range(self._list.count()):
            item = self._list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == preset_id:
                self._list.setCurrentItem(item)
                self._list.scrollToItem(item)
                return

    def _on_zone_changed(self, _index: int) -> None:
        self._svc.set_current_zone(self._zone_combo.currentData() or "")
        self._refresh_presets()

    def _on_save_current(self) -> None:
        zone_id = self._selected_zone_id()
        if not zone_id:
            InfoBar.warning("提示", "当前没有可用画布", duration=2200, parent=self.window(), position=InfoBarPosition.BOTTOM)
            return
        dlg = _PresetDialog(parent=self.window())
        if not dlg.exec():
            return
        preset = dlg.result_preset()
        saved = self._svc.create_preset_from_zone(
            zone_id,
            name=preset.name,
            description=preset.description,
        )
        if saved is None:
            InfoBar.error("保存失败", "无法读取当前画布布局", duration=2200, parent=self.window(), position=InfoBarPosition.BOTTOM)
            return
        self._svc.apply_preset(saved.id, zone_id)
        self._select_preset(saved.id)
        InfoBar.success("已保存", f"预设「{saved.name}」已保存", duration=2200, parent=self.window(), position=InfoBarPosition.BOTTOM)

    def _on_import_layout_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "导入布局文件为预设",
            "",
            "小树布局文件 (*.ltlayout);;JSON 文件 (*.json)",
        )
        if not path:
            return
        try:
            preset = self._svc.build_preset_from_layout_file(path, fallback_zone_id=self._selected_zone_id())
        except Exception as exc:
            InfoBar.error("导入失败", str(exc), duration=3000, parent=self.window(), position=InfoBarPosition.BOTTOM)
            return
        dlg = _PresetDialog(preset=preset, parent=self.window())
        if not dlg.exec():
            return
        saved = self._svc.save_preset(dlg.result_preset())
        self._select_preset(saved.id)
        InfoBar.success("已导入", f"预设「{saved.name}」已导入", duration=2200, parent=self.window(), position=InfoBarPosition.BOTTOM)

    def _on_apply(self) -> None:
        preset_id = self._selected_preset_id()
        zone_id = self._selected_zone_id()
        if not preset_id or not zone_id:
            return
        if self._svc.apply_preset(preset_id, zone_id):
            InfoBar.success("已应用", "布局预设已切换", duration=1800, parent=self.window(), position=InfoBarPosition.BOTTOM)

    def _on_overwrite(self) -> None:
        preset_id = self._selected_preset_id()
        zone_id = self._selected_zone_id()
        if not preset_id or not zone_id:
            return
        preset = self._svc.get_preset(preset_id)
        if preset is None:
            return
        box = MessageBox("确认覆盖", f"确定用当前画布布局覆盖预设「{preset.name}」？", self.window())
        box.yesButton.setText("覆盖")
        box.cancelButton.setText("取消")
        if not box.exec():
            return
        if self._svc.update_preset_from_zone(preset_id, zone_id) is not None:
            InfoBar.success("已覆盖", f"预设「{preset.name}」已更新", duration=1800, parent=self.window(), position=InfoBarPosition.BOTTOM)

    def _on_rename(self) -> None:
        preset_id = self._selected_preset_id()
        preset = self._svc.get_preset(preset_id)
        if preset is None:
            return
        dlg = _PresetDialog(preset=preset, parent=self.window())
        if not dlg.exec():
            return
        self._svc.save_preset(dlg.result_preset())

    def _on_delete(self) -> None:
        preset_id = self._selected_preset_id()
        preset = self._svc.get_preset(preset_id)
        if preset is None:
            return
        box = MessageBox("确认删除", f"确定删除预设「{preset.name}」？", self.window())
        box.yesButton.setText("删除")
        box.cancelButton.setText("取消")
        if not box.exec():
            return
        self._svc.delete_preset(preset_id)

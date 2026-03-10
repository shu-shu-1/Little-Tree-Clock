"""自习时间安排侧边栏。"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QTime
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QListWidgetItem,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CheckBox,
    ComboBox,
    FluentIcon as FIF,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    ListWidget,
    MessageBox,
    Pivot,
    PushButton,
    SubtitleLabel,
    TimePicker,
    ToolButton,
)

from .models import StudyGroup, StudyItem, WEEKDAY_LABELS, format_weekdays


def _preset_name(svc, preset_id: str, fallback: str) -> str:
    preset = svc.get_preset(preset_id)
    return preset.name if preset is not None else fallback


class _StudyGroupDialog(MessageBox):
    def __init__(self, svc, group: Optional[StudyGroup] = None, parent=None):
        super().__init__("编辑事项组" if group else "新建事项组", "", parent)
        self.yesButton.setText("保存")
        self.cancelButton.setText("取消")
        self.contentLabel.hide()
        self._svc = svc
        self._group = group or StudyGroup()

        form = QFormLayout()
        form.setVerticalSpacing(10)

        self._name_edit = LineEdit()
        self._name_edit.setPlaceholderText("事项组名称，如「晚自习」")
        self._name_edit.setText(self._group.name)

        self._desc_edit = LineEdit()
        self._desc_edit.setPlaceholderText("可选说明")
        self._desc_edit.setText(self._group.description)

        self._preset_combo = ComboBox()
        self._preset_combo.addItem("（不绑定预设）", userData="")
        for preset in svc.available_presets():
            self._preset_combo.addItem(preset.name, userData=preset.id)
        preset_index = next(
            (i for i in range(self._preset_combo.count()) if self._preset_combo.itemData(i) == self._group.preset_id),
            0,
        )
        self._preset_combo.setCurrentIndex(preset_index)

        weekday_widget = QWidget()
        weekday_layout = QGridLayout(weekday_widget)
        weekday_layout.setContentsMargins(0, 0, 0, 0)
        weekday_layout.setHorizontalSpacing(8)
        weekday_layout.setVerticalSpacing(6)
        self._weekday_boxes: list[CheckBox] = []
        selected = set(self._group.weekdays)
        for index, label in enumerate(WEEKDAY_LABELS):
            checkbox = CheckBox(label)
            checkbox.setChecked(index in selected)
            self._weekday_boxes.append(checkbox)
            weekday_layout.addWidget(checkbox, index // 4, index % 4)

        form.addRow("事项组名称:", self._name_edit)
        form.addRow("说明:", self._desc_edit)
        form.addRow("分组预设:", self._preset_combo)
        form.addRow("自动切换日期:", weekday_widget)
        self.textLayout.addLayout(form)

    def accept(self) -> None:
        name = self._name_edit.text().strip()
        if not name:
            InfoBar.warning("提示", "事项组名称不能为空", duration=2000, parent=self, position=InfoBarPosition.TOP)
            return
        self._group.name = name
        self._group.description = self._desc_edit.text().strip()
        self._group.preset_id = self._preset_combo.currentData() or ""
        self._group.weekdays = [index for index, checkbox in enumerate(self._weekday_boxes) if checkbox.isChecked()]
        super().accept()

    def result_group(self) -> StudyGroup:
        return self._group


class _StudyItemDialog(MessageBox):
    def __init__(self, svc, item: Optional[StudyItem] = None, parent=None):
        super().__init__("编辑事项" if item else "新建事项", "", parent)
        self.yesButton.setText("保存")
        self.cancelButton.setText("取消")
        self.contentLabel.hide()
        self._svc = svc
        self._item = item or StudyItem()

        form = QFormLayout()
        form.setVerticalSpacing(10)

        self._name_edit = LineEdit()
        self._name_edit.setPlaceholderText("事项名称，如「数学刷题」")
        self._name_edit.setText(self._item.name)

        self._desc_edit = LineEdit()
        self._desc_edit.setPlaceholderText("可选说明")
        self._desc_edit.setText(self._item.description)

        self._start_picker = TimePicker(self)
        self._start_picker.setTime(QTime.fromString(self._item.start_time, "HH:mm") if self._item.start_time else QTime(19, 0))
        self._end_picker = TimePicker(self)
        self._end_picker.setTime(QTime.fromString(self._item.end_time, "HH:mm") if self._item.end_time else QTime(20, 0))

        self._preset_combo = ComboBox()
        self._preset_combo.addItem("（继承事项组预设）", userData="")
        for preset in svc.available_presets():
            self._preset_combo.addItem(preset.name, userData=preset.id)
        preset_index = next(
            (i for i in range(self._preset_combo.count()) if self._preset_combo.itemData(i) == self._item.preset_id),
            0,
        )
        self._preset_combo.setCurrentIndex(preset_index)

        self._enabled_cb = CheckBox("启用此事项")
        self._enabled_cb.setChecked(bool(self._item.enabled))

        time_row = QHBoxLayout()
        time_row.setContentsMargins(0, 0, 0, 0)
        time_row.addWidget(self._start_picker)
        time_row.addWidget(BodyLabel("—"))
        time_row.addWidget(self._end_picker)
        time_row.addStretch()

        form.addRow("事项名称:", self._name_edit)
        form.addRow("说明:", self._desc_edit)
        form.addRow("时间段:", time_row)
        form.addRow("事项预设:", self._preset_combo)
        form.addRow("", self._enabled_cb)
        self.textLayout.addLayout(form)

    def accept(self) -> None:
        name = self._name_edit.text().strip()
        if not name:
            InfoBar.warning("提示", "事项名称不能为空", duration=2000, parent=self, position=InfoBarPosition.TOP)
            return
        self._item.name = name
        self._item.description = self._desc_edit.text().strip()
        self._item.start_time = self._start_picker.getTime().toString("HH:mm")
        self._item.end_time = self._end_picker.getTime().toString("HH:mm")
        self._item.preset_id = self._preset_combo.currentData() or ""
        self._item.enabled = self._enabled_cb.isChecked()
        super().accept()

    def result_item(self) -> StudyItem:
        return self._item


class _GroupTab(QWidget):
    def __init__(self, svc, parent=None):
        super().__init__(parent)
        self._svc = svc

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        top = QHBoxLayout()
        self._add_btn = PushButton(FIF.ADD, "新建事项组")
        self._set_current_btn = PushButton(FIF.PLAY, "设为当前组")
        top.addWidget(self._add_btn)
        top.addWidget(self._set_current_btn)
        top.addStretch()
        layout.addLayout(top)

        self._list = ListWidget()
        layout.addWidget(self._list, 1)

        bottom = QHBoxLayout()
        self._edit_btn = PushButton(FIF.EDIT, "编辑")
        self._delete_btn = PushButton(FIF.DELETE, "删除")
        bottom.addWidget(self._edit_btn)
        bottom.addWidget(self._delete_btn)
        bottom.addStretch()
        layout.addLayout(bottom)

        self._add_btn.clicked.connect(self._on_add)
        self._set_current_btn.clicked.connect(self._on_set_current)
        self._edit_btn.clicked.connect(self._on_edit)
        self._delete_btn.clicked.connect(self._on_delete)
        self._list.itemDoubleClicked.connect(self._on_edit)

        svc.groups_updated.connect(self._refresh)
        svc.current_group_changed.connect(lambda *_: self._refresh())
        self._refresh()

    def _selected_group_id(self) -> str:
        item = self._list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else ""

    def _refresh(self) -> None:
        self._list.clear()
        for group in self._svc.groups():
            text = group.name
            if group.id == self._svc.current_group_id:
                text += "  [当前]"
            meta = [f"星期：{format_weekdays(group.weekdays)}"]
            if group.preset_id:
                meta.append(f"预设：{_preset_name(self._svc, group.preset_id, '已删除')}")
            meta.append(f"事项数：{len(group.items)}")
            if group.description:
                meta.append(group.description)
            item = QListWidgetItem(f"{text}\n{' · '.join(meta)}")
            item.setData(Qt.ItemDataRole.UserRole, group.id)
            self._list.addItem(item)

    def _on_add(self) -> None:
        dlg = _StudyGroupDialog(self._svc, parent=self.window())
        if dlg.exec():
            self._svc.save_group(dlg.result_group())

    def _on_set_current(self) -> None:
        group_id = self._selected_group_id()
        if group_id:
            self._svc.set_current_group(group_id, apply_preset=True)

    def _on_edit(self) -> None:
        group_id = self._selected_group_id()
        group = self._svc.get_group(group_id)
        if group is None:
            return
        dlg = _StudyGroupDialog(self._svc, group=group, parent=self.window())
        if dlg.exec():
            self._svc.save_group(dlg.result_group())

    def _on_delete(self) -> None:
        group_id = self._selected_group_id()
        group = self._svc.get_group(group_id)
        if group is None:
            return
        box = MessageBox("确认删除", f"确定删除事项组「{group.name}」及其全部事项？", self.window())
        box.yesButton.setText("删除")
        box.cancelButton.setText("取消")
        if box.exec():
            self._svc.delete_group(group_id)


class _ItemTab(QWidget):
    def __init__(self, svc, parent=None):
        super().__init__(parent)
        self._svc = svc

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        group_row = QHBoxLayout()
        group_row.addWidget(BodyLabel("选择事项组:"))
        self._group_combo = ComboBox()
        self._group_combo.currentIndexChanged.connect(self._refresh_items)
        group_row.addWidget(self._group_combo, 1)
        layout.addLayout(group_row)

        note = CaptionLabel("提示：单个事项绑定的预设会覆盖上层事项组预设；留空则继承事项组配置。")
        note.setWordWrap(True)
        layout.addWidget(note)

        top = QHBoxLayout()
        self._add_btn = PushButton(FIF.ADD, "新建事项")
        self._set_current_btn = PushButton(FIF.PLAY, "设为当前事项")
        top.addWidget(self._add_btn)
        top.addWidget(self._set_current_btn)
        top.addStretch()
        layout.addLayout(top)

        self._list = ListWidget()
        layout.addWidget(self._list, 1)

        bottom = QHBoxLayout()
        self._edit_btn = PushButton(FIF.EDIT, "编辑")
        self._delete_btn = PushButton(FIF.DELETE, "删除")
        bottom.addWidget(self._edit_btn)
        bottom.addWidget(self._delete_btn)
        bottom.addStretch()
        layout.addLayout(bottom)

        self._add_btn.clicked.connect(self._on_add)
        self._set_current_btn.clicked.connect(self._on_set_current)
        self._edit_btn.clicked.connect(self._on_edit)
        self._delete_btn.clicked.connect(self._on_delete)
        self._list.itemDoubleClicked.connect(self._on_edit)

        svc.groups_updated.connect(self._refresh_groups)
        svc.current_group_changed.connect(lambda *_: self._refresh_groups())
        svc.current_item_changed.connect(lambda *_: self._refresh_items())
        self._refresh_groups()

    def _selected_group_id(self) -> str:
        return self._group_combo.currentData() or ""

    def _selected_item_id(self) -> str:
        item = self._list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else ""

    def _refresh_groups(self) -> None:
        previous = self._selected_group_id() or self._svc.current_group_id
        self._group_combo.blockSignals(True)
        self._group_combo.clear()
        self._group_combo.addItem("（选择事项组）", userData="")
        for group in self._svc.groups():
            self._group_combo.addItem(group.name, userData=group.id)
        index = next(
            (i for i in range(self._group_combo.count()) if self._group_combo.itemData(i) == previous),
            0,
        )
        self._group_combo.setCurrentIndex(index)
        self._group_combo.blockSignals(False)
        self._refresh_items()

    def _refresh_items(self) -> None:
        group_id = self._selected_group_id()
        self._list.clear()
        for item in self._svc.items(group_id):
            text = f"{item.start_time} — {item.end_time}  {item.name}"
            if group_id == self._svc.current_group_id and item.id == self._svc.current_item_id:
                text += "  [当前]"
            meta = []
            if item.preset_id:
                meta.append(f"预设：{_preset_name(self._svc, item.preset_id, '已删除')}")
            else:
                meta.append("预设：继承事项组")
            if not item.enabled:
                meta.append("已停用")
            if item.description:
                meta.append(item.description)
            list_item = QListWidgetItem(f"{text}\n{' · '.join(meta)}")
            list_item.setData(Qt.ItemDataRole.UserRole, item.id)
            self._list.addItem(list_item)

    def _on_add(self) -> None:
        group_id = self._selected_group_id()
        if not group_id:
            InfoBar.warning("提示", "请先选择事项组", duration=2000, parent=self.window(), position=InfoBarPosition.BOTTOM)
            return
        dlg = _StudyItemDialog(self._svc, parent=self.window())
        if dlg.exec():
            self._svc.save_item(group_id, dlg.result_item())

    def _on_set_current(self) -> None:
        group_id = self._selected_group_id()
        item_id = self._selected_item_id()
        if not group_id or not item_id:
            return
        if group_id != self._svc.current_group_id:
            self._svc.set_current_group(group_id, apply_preset=False)
        self._svc.set_current_item(item_id, apply_preset=True)

    def _on_edit(self) -> None:
        group_id = self._selected_group_id()
        item_id = self._selected_item_id()
        item = self._svc.get_item(group_id, item_id)
        if item is None:
            return
        dlg = _StudyItemDialog(self._svc, item=item, parent=self.window())
        if dlg.exec():
            self._svc.save_item(group_id, dlg.result_item())

    def _on_delete(self) -> None:
        group_id = self._selected_group_id()
        item_id = self._selected_item_id()
        item = self._svc.get_item(group_id, item_id)
        if item is None:
            return
        box = MessageBox("确认删除", f"确定删除事项「{item.name}」？", self.window())
        box.yesButton.setText("删除")
        box.cancelButton.setText("取消")
        if box.exec():
            self._svc.delete_item(group_id, item_id)


class StudyScheduleSidebarPanel(QWidget):
    def __init__(self, svc, parent=None):
        super().__init__(parent)
        self.setObjectName("studyScheduleSidebarPanel")
        self._svc = svc

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QWidget()
        header.setFixedHeight(72)
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(20, 10, 16, 10)
        header_layout.setSpacing(2)
        header_layout.addWidget(SubtitleLabel("自习时间安排"))
        self._status_label = CaptionLabel("")
        self._status_label.setWordWrap(True)
        header_layout.addWidget(self._status_label)
        root.addWidget(header)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: rgba(128,128,128,60);")
        root.addWidget(sep)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(12, 12, 12, 12)
        body_layout.setSpacing(8)

        zone_row = QHBoxLayout()
        zone_row.addWidget(BodyLabel("目标画布:"))
        self._zone_combo = ComboBox()
        self._zone_combo.currentIndexChanged.connect(self._on_zone_changed)
        zone_row.addWidget(self._zone_combo, 1)
        self._zone_refresh_btn = ToolButton(FIF.SYNC)
        self._zone_refresh_btn.setToolTip("刷新画布列表")
        self._zone_refresh_btn.clicked.connect(self._refresh_zones)
        zone_row.addWidget(self._zone_refresh_btn)
        body_layout.addLayout(zone_row)

        self._zone_tip = CaptionLabel("")
        self._zone_tip.setWordWrap(True)
        body_layout.addWidget(self._zone_tip)

        self._pivot = Pivot()
        body_layout.addWidget(self._pivot)

        self._stack = QStackedWidget()
        body_layout.addWidget(self._stack, 1)

        self._group_tab = _GroupTab(svc)
        self._item_tab = _ItemTab(svc)
        for key, label, widget in (
            ("group", "分组", self._group_tab),
            ("item", "事项", self._item_tab),
        ):
            self._stack.addWidget(widget)
            self._pivot.addItem(routeKey=key, text=label, onClick=lambda _checked=False, w=widget: self._stack.setCurrentWidget(w))

        self._pivot.setCurrentItem("group")
        self._stack.setCurrentWidget(self._group_tab)

        root.addWidget(body, 1)

        svc.groups_updated.connect(self._refresh_status)
        svc.current_group_changed.connect(lambda *_: self._refresh_status())
        svc.current_item_changed.connect(lambda *_: self._refresh_status())
        svc.target_zone_changed.connect(lambda *_: self._refresh_status())

        self._refresh_zones()
        self._refresh_status()

    def _refresh_zones(self) -> None:
        previous = self._svc.target_zone_id()
        self._zone_combo.blockSignals(True)
        self._zone_combo.clear()
        self._zone_combo.addItem("（跟随最近打开的全屏画布）", userData="")
        for zone in self._svc.list_zones():
            self._zone_combo.addItem(
                str(zone.get("display_name") or zone.get("label") or zone.get("timezone") or zone.get("id") or "未命名画布"),
                userData=str(zone.get("id") or ""),
            )
        index = next(
            (i for i in range(self._zone_combo.count()) if self._zone_combo.itemData(i) == previous),
            0,
        )
        self._zone_combo.setCurrentIndex(index)
        self._zone_combo.blockSignals(False)
        self._refresh_status()

    def _on_zone_changed(self, _index: int) -> None:
        self._svc.set_target_zone(self._zone_combo.currentData() or "")
        self._refresh_status()

    def _refresh_status(self) -> None:
        group = self._svc.get_current_group()
        item = self._svc.get_current_item()
        zone_id = self._svc.effective_zone_id()
        zone_name = self._svc.get_zone_display_name(zone_id, fallback="未指定") if zone_id else "未指定"
        if item is not None and group is not None:
            self._status_label.setText(f"当前事项：{group.name} / {item.name}（{item.start_time} — {item.end_time}）")
        elif group is not None:
            self._status_label.setText(f"当前事项组：{group.name}（当前没有进行中的事项）")
        else:
            self._status_label.setText("当前尚未配置或未命中任何事项组")
        if self._svc.target_zone_id():
            self._zone_tip.setText(f"将固定应用到画布：{zone_name}")
        else:
            self._zone_tip.setText(f"当前跟随最近打开的全屏画布：{zone_name}")

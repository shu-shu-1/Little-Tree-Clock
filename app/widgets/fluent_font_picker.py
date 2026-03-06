"""Fluent 风格字体选择组件。"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QListWidgetItem, QWidget, QHBoxLayout, QVBoxLayout
from qfluentwidgets import (
    FluentIcon as FIF,
    BodyLabel,
    CaptionLabel,
    LineEdit,
    ListWidget,
    MessageBoxBase,
    PushButton,
    SubtitleLabel,
    ToolButton,
)


class _FontSelectDialog(MessageBoxBase):
    """字体选择弹窗。"""

    def __init__(self, current_family: str = "", parent=None):
        super().__init__(parent)
        self._all_families = [""] + sorted(QFontDatabase().families())
        self._selected_family = current_family if current_family in self._all_families else ""

        title = SubtitleLabel("选择字体", self)
        hint = CaptionLabel("支持搜索字体名称；第一项为系统默认字体。", self)
        hint.setWordWrap(True)

        self._search_edit = LineEdit(self)
        self._search_edit.setPlaceholderText("搜索字体，例如：微软雅黑 / Segoe UI")

        self._list = ListWidget(self)
        self._list.setMinimumSize(420, 320)

        preview_title = CaptionLabel("预览", self)
        self._preview_label = BodyLabel("小树时钟 Little Tree Clock 0123456789")
        self._preview_label.setWordWrap(True)

        self.viewLayout.insertWidget(0, title)
        self.viewLayout.insertWidget(1, hint)
        self.viewLayout.insertSpacing(2, 4)
        self.viewLayout.insertWidget(3, self._search_edit)
        self.viewLayout.insertWidget(4, self._list)
        self.viewLayout.insertSpacing(5, 6)
        self.viewLayout.insertWidget(6, preview_title)
        self.viewLayout.insertWidget(7, self._preview_label)

        self.yesButton.setText("确定")
        self.cancelButton.setText("取消")
        self.widget.setMinimumWidth(480)

        self._populate_items()
        self._search_edit.textChanged.connect(self._filter_items)
        self._list.itemSelectionChanged.connect(self._sync_from_selection)
        self._list.itemDoubleClicked.connect(lambda *_: self.accept())

        self._filter_items()
        self._sync_preview()

    def _populate_items(self) -> None:
        self._list.clear()
        current_item = None

        for family in self._all_families:
            text = "（跟随系统默认字体）" if not family else family
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, family)
            if family:
                item.setFont(QFont(family, 11))
            self._list.addItem(item)
            if family == self._selected_family:
                current_item = item

        if current_item is None and self._list.count() > 0:
            current_item = self._list.item(0)

        if current_item is not None:
            self._list.setCurrentItem(current_item)

    def _filter_items(self) -> None:
        keyword = self._search_edit.text().strip().lower()
        visible_items: list[QListWidgetItem] = []

        for index in range(self._list.count()):
            item = self._list.item(index)
            family = str(item.data(Qt.ItemDataRole.UserRole) or "")
            haystack = (family or item.text()).lower()
            matched = not keyword or keyword in haystack
            item.setHidden(not matched)
            if matched:
                visible_items.append(item)

        current = self._list.currentItem()
        if current is None or current.isHidden():
            if visible_items:
                self._list.setCurrentItem(visible_items[0])
            else:
                self._list.clearSelection()
                self._selected_family = ""
                self._preview_label.setText("没有匹配的字体")
                self.yesButton.setEnabled(False)
                return

        self.yesButton.setEnabled(True)
        self._sync_from_selection()

    def _sync_from_selection(self) -> None:
        item = self._list.currentItem()
        if item is None:
            self._selected_family = ""
        else:
            self._selected_family = str(item.data(Qt.ItemDataRole.UserRole) or "")
        self._sync_preview()

    def _sync_preview(self) -> None:
        font = self._preview_label.font()
        if self._selected_family:
            font.setFamily(self._selected_family)
        else:
            font = QFont()
        font.setPointSize(14)
        self._preview_label.setFont(font)
        self._preview_label.setText(
            "小树时钟 Little Tree Clock 0123456789\n"
            f"当前字体：{self._selected_family or '系统默认字体'}"
        )

    def selected_family(self) -> str:
        return self._selected_family


class FluentFontPicker(QWidget):
    """由 qfluentwidgets 组件组合而成的字体选择框。"""

    fontChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._family = ""

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._display = LineEdit(self)
        self._display.setReadOnly(True)
        self._display.setPlaceholderText("跟随系统默认字体")
        self._display.setMinimumWidth(220)

        self._pick_btn = PushButton(FIF.FONT, "选择", self)
        self._pick_btn.setMinimumWidth(84)

        self._reset_btn = ToolButton(FIF.CANCEL_MEDIUM, self)
        self._reset_btn.setToolTip("恢复默认字体")

        layout.addWidget(self._display, 1)
        layout.addWidget(self._pick_btn)
        layout.addWidget(self._reset_btn)

        self._pick_btn.clicked.connect(self._choose_font)
        self._reset_btn.clicked.connect(lambda: self.setCurrentFontFamily(""))

        self.setCurrentFontFamily("")

    def currentFontFamily(self) -> str:
        return self._family

    def setCurrentFontFamily(self, family: str) -> None:
        family = str(family or "").strip()
        if self._family == family:
            self._refresh_display()
            return
        self._family = family
        self._refresh_display()
        self.fontChanged.emit(self._family)

    def _refresh_display(self) -> None:
        text = self._family or "系统默认字体"
        self._display.setText(text)
        font = self._display.font()
        if self._family:
            font.setFamily(self._family)
        else:
            font = QFont()
        self._display.setFont(font)
        self._display.setToolTip(self._family or "当前跟随系统默认字体")
        self._reset_btn.setEnabled(bool(self._family))

    def _choose_font(self) -> None:
        dialog = _FontSelectDialog(self._family, self.window() or self)
        if dialog.exec():
            self.setCurrentFontFamily(dialog.selected_family())
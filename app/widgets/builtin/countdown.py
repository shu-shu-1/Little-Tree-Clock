"""倒数日组件"""
from __future__ import annotations

from datetime import date

from PySide6.QtWidgets import (
    QVBoxLayout, QWidget, QLabel, QFormLayout,
)
from PySide6.QtCore import Qt, QDate
from qfluentwidgets import ComboBox, LineEdit, CalendarPicker

from app.widgets.base_widget import WidgetBase, WidgetConfig


class _CountdownEditPanel(QWidget):
    def __init__(self, props: dict, parent=None):
        super().__init__(parent)
        f = QFormLayout(self)

        self._title = LineEdit()
        self._title.setText(props.get("title", "倒数日"))
        f.addRow("标题:", self._title)

        self._date = CalendarPicker()
        target_str = props.get("target_date", "")
        if target_str:
            try:
                d = date.fromisoformat(target_str)
                self._date.setDate(QDate(d.year, d.month, d.day))
            except Exception:
                self._date.setDate(QDate.currentDate())
        else:
            self._date.setDate(QDate.currentDate())
        f.addRow("目标日期:", self._date)

        self._size = ComboBox()
        for label, val in [("小 (1×1)", "small"), ("中 (2×2)", "medium"), ("大 (3×2)", "large")]:
            self._size.addItem(label, userData=val)
        cur = props.get("size", "medium")
        idx = next((i for i in range(self._size.count()) if self._size.itemData(i) == cur), 1)
        self._size.setCurrentIndex(idx)
        f.addRow("组件大小:", self._size)

    def collect_props(self) -> dict:
        qd = self._date.getDate()
        return {
            "title":       self._title.text(),
            "target_date": f"{qd.year()}-{qd.month():02d}-{qd.day():02d}",
            "size":        self._size.currentData(),
        }


_SIZE_MAP = {"small": (1, 1), "medium": (2, 2), "large": (3, 2)}


class CountdownWidget(WidgetBase):
    WIDGET_TYPE = "countdown"
    WIDGET_NAME = "倒数日"
    DELETABLE   = True
    DEFAULT_W   = 2
    DEFAULT_H   = 2

    def __init__(self, config: WidgetConfig, services, parent=None):
        super().__init__(config, services, parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 8, 12, 8)
        root.setSpacing(4)
        root.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._title_lbl = QLabel("")
        self._title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title_lbl.setStyleSheet("color:#aaa; font-size:15px; background:transparent;")

        self._days_lbl = QLabel("")
        self._days_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._days_lbl.setStyleSheet("color:white; font-size:52px; font-weight:200; background:transparent;")

        self._sub_lbl = QLabel("天")
        self._sub_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._sub_lbl.setStyleSheet("color:#666; font-size:14px; background:transparent;")

        root.addStretch()
        root.addWidget(self._title_lbl)
        root.addWidget(self._days_lbl)
        root.addWidget(self._sub_lbl)
        root.addStretch()

        self.refresh()

    def refresh(self) -> None:
        p = self.config.props
        self._title_lbl.setText(p.get("title", "倒数日"))

        target_str = p.get("target_date", "")
        if not target_str:
            self._days_lbl.setText("--")
            self._sub_lbl.setText("请设置目标日期")
            return
        try:
            target = date.fromisoformat(target_str)
            delta  = (target - date.today()).days
            if delta > 0:
                self._days_lbl.setText(f"{delta}")
                self._sub_lbl.setText("天后")
            elif delta == 0:
                self._days_lbl.setText("今天")
                self._sub_lbl.setText("🎉")
            else:
                self._days_lbl.setText(f"{-delta}")
                self._sub_lbl.setText("天前已到")
        except Exception:
            self._days_lbl.setText("?")

    def get_edit_widget(self):
        return _CountdownEditPanel(self.config.props)

    def apply_props(self, props: dict) -> None:
        self.config.props.update(props)
        w, h = _SIZE_MAP.get(props.get("size", "medium"), (2, 2))
        self.config.grid_w = w
        self.config.grid_h = h
        self.refresh()

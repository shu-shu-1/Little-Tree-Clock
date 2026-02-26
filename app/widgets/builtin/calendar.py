"""日历组件"""
from __future__ import annotations

import calendar
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QVBoxLayout, QGridLayout, QWidget, QLabel, QFormLayout,
)
from qfluentwidgets import ComboBox

from app.widgets.base_widget import WidgetBase, WidgetConfig


class _CalendarEditPanel(QWidget):
    def __init__(self, props: dict, parent=None):
        super().__init__(parent)
        f = QFormLayout(self)
        self._size = ComboBox()
        for label, val in [("小 (2×2)", "small"), ("中 (3×3)", "medium"), ("大 (4×4)", "large")]:
            self._size.addItem(label, val)
        cur = props.get("size", "medium")
        idx = next((i for i in range(self._size.count()) if self._size.itemData(i) == cur), 1)
        self._size.setCurrentIndex(idx)
        f.addRow("组件大小:", self._size)

    def collect_props(self) -> dict:
        return {"size": self._size.currentData()}


_SIZE_MAP = {"small": (2, 2), "medium": (3, 3), "large": (4, 4)}
_WEEK_NAMES = ["一", "二", "三", "四", "五", "六", "日"]
_MONTH_NAMES = ["一月","二月","三月","四月","五月","六月",
                "七月","八月","九月","十月","十一月","十二月"]


class CalendarWidget(WidgetBase):
    WIDGET_TYPE = "calendar"
    WIDGET_NAME = "日历"
    DELETABLE   = True
    DEFAULT_W   = 3
    DEFAULT_H   = 3

    def __init__(self, config: WidgetConfig, services, parent=None):
        super().__init__(config, services, parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 4, 8, 4)
        root.setSpacing(4)

        # 月份标题
        self._month_lbl = QLabel("")
        self._month_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._month_lbl.setStyleSheet("color:white; font-size:16px; font-weight:500; background:transparent;")
        root.addWidget(self._month_lbl)

        # 网格
        self._grid_widget = QWidget()
        self._grid_widget.setStyleSheet("background:transparent;")
        self._grid = QGridLayout(self._grid_widget)
        self._grid.setSpacing(2)
        root.addWidget(self._grid_widget, 1)

        self.refresh()

    def refresh(self) -> None:
        now   = datetime.now()
        year  = now.year
        month = now.month
        today = now.day

        self._month_lbl.setText(f"{year}年 {_MONTH_NAMES[month - 1]}")

        # 清空网格
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # 星期头
        for col, name in enumerate(_WEEK_NAMES):
            lbl = QLabel(name)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            color = "#e55" if col >= 5 else "#888"
            lbl.setStyleSheet(f"color:{color}; font-size:11px; background:transparent;")
            self._grid.addWidget(lbl, 0, col)

        # 日期
        first_weekday, n_days = calendar.monthrange(year, month)
        # Python: 0=Monday ... 6=Sunday → 列 = (first_weekday + 6) % 7
        start_col = (first_weekday + 6) % 7 if first_weekday >= 0 else first_weekday
        row = 1
        col = start_col
        for day in range(1, n_days + 1):
            is_today  = (day == today)
            is_weekend = (col >= 5)
            color = "#fff" if is_today else ("#e88" if is_weekend else "#ccc")
            bg    = "rgba(255,255,255,30)" if is_today else "transparent"
            lbl   = QLabel(str(day))
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet(
                f"color:{color}; font-size:12px; background:{bg}; border-radius:3px;"
            )
            self._grid.addWidget(lbl, row, col)
            col += 1
            if col > 6:
                col = 0
                row += 1

    def get_edit_widget(self):
        return _CalendarEditPanel(self.config.props)

    def apply_props(self, props: dict) -> None:
        self.config.props.update(props)
        w, h = _SIZE_MAP.get(props.get("size", "medium"), (3, 3))
        self.config.grid_w = w
        self.config.grid_h = h
        self.refresh()

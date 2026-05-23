"""日历组件"""
from __future__ import annotations

import calendar
from datetime import datetime, date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QVBoxLayout, QGridLayout, QWidget, QLabel, QFormLayout,
)
from qfluentwidgets import CheckBox, SpinBox

from app.widgets.base_widget import WidgetBase, WidgetConfig
from app.widgets.fluent_font_picker import FluentFontPicker
from app.utils.lunar_utils import lunar_short_str


class _CalendarEditPanel(QWidget):
    def __init__(self, props: dict, parent=None):
        super().__init__(parent)
        f = QFormLayout(self)

        self._grid_w = SpinBox()
        self._grid_w.setRange(2, 20)
        self._grid_w.setSuffix(" 格")
        self._grid_w.setValue(props.get("grid_w", 3))
        f.addRow("宽度:", self._grid_w)

        self._grid_h = SpinBox()
        self._grid_h.setRange(2, 20)
        self._grid_h.setSuffix(" 格")
        self._grid_h.setValue(props.get("grid_h", 3))
        f.addRow("高度:", self._grid_h)

        self._font_picker = FluentFontPicker()
        self._font_picker.setCurrentFontFamily(props.get("font_family", ""))
        f.addRow("字体:", self._font_picker)

        self._font_offset = SpinBox()
        self._font_offset.setRange(-10, 20)
        self._font_offset.setSuffix(" px")
        self._font_offset.setValue(props.get("font_size_offset", 0))
        f.addRow("字号偏移:", self._font_offset)

        self._show_lunar = CheckBox()
        self._show_lunar.setChecked(props.get("show_lunar", False))
        f.addRow("显示农历:", self._show_lunar)

    def collect_props(self) -> dict:
        return {
            "show_lunar": self._show_lunar.isChecked(),
            "font_family": self._font_picker.currentFontFamily(),
            "font_size_offset": self._font_offset.value(),
            "grid_w":     self._grid_w.value(),
            "grid_h":     self._grid_h.value(),
        }


_WEEK_NAMES = ["日", "一", "二", "三", "四", "五", "六"]
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
        self._month_lbl.setStyleSheet("color:white; font-weight:500; background:transparent;")
        root.addWidget(self._month_lbl)

        # 网格
        self._grid_widget = QWidget()
        self._grid_widget.setStyleSheet("background:transparent;")
        self._grid = QGridLayout(self._grid_widget)
        self._grid.setSpacing(2)
        root.addWidget(self._grid_widget, 1)

        self.refresh()

    @staticmethod
    def _scaled_px(base_px: int, side: int) -> int:
        return max(base_px // 2, int(base_px * side / 360))

    def refresh(self) -> None:
        now   = datetime.now()
        year  = now.year
        month = now.month
        today = now.day
        show_lunar = self.config.props.get("show_lunar", False)

        side = min(self.width(), self.height())
        if side < 10:
            side = 360
        offset = self.config.props.get("font_size_offset", 0)
        fs_title  = max(6, self._scaled_px(16, side) + offset)
        fs_header = max(6, self._scaled_px(11, side) + offset)
        fs_day    = max(6, self._scaled_px(12, side) + offset)
        fs_lunar  = max(6, self._scaled_px(9, side) + offset)

        self._month_lbl.setText(f"{year}年 {_MONTH_NAMES[month - 1]}")
        self._month_lbl.setStyleSheet(
            f"color:white; font-size:{fs_title}px; font-weight:500; background:transparent;"
        )

        font_family = self.config.props.get("font_family") or ""
        if font_family:
            base_font = self._month_lbl.font()
            base_font.setFamily(font_family)
            self._month_lbl.setFont(base_font)

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
            lbl.setStyleSheet(f"color:{color}; font-size:{fs_header}px; background:transparent;")
            if font_family:
                hdr_font = lbl.font()
                hdr_font.setFamily(font_family)
                lbl.setFont(hdr_font)
            self._grid.addWidget(lbl, 0, col)

        # 日期
        first_weekday, n_days = calendar.monthrange(year, month)
        # Python: 0=Monday ... 6=Sunday; 列按 _WEEK_NAMES 排列: 0=Sunday
        # Monday=0 → Sunday col 1; Sunday=6 → Sunday col 0
        start_col = (first_weekday + 1) % 7
        row = 1
        col = start_col
        for day in range(1, n_days + 1):
            is_today   = (day == today)
            is_weekend = (col >= 5)
            color      = "#fff" if is_today else ("#e88" if is_weekend else "#ccc")
            bg         = "rgba(255,255,255,30)" if is_today else "transparent"

            if show_lunar:
                # 使用容器 widget，上方公历数字 + 下方农历小字
                cell = QWidget()
                cell.setStyleSheet(f"background:{bg}; border-radius:3px;")
                vl = QVBoxLayout(cell)
                vl.setContentsMargins(1, 1, 1, 1)
                vl.setSpacing(0)

                day_lbl = QLabel(str(day))
                day_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                day_lbl.setStyleSheet(f"color:{color}; font-size:{fs_day}px; background:transparent;")
                if font_family:
                    df = day_lbl.font()
                    df.setFamily(font_family)
                    day_lbl.setFont(df)
                vl.addWidget(day_lbl)

                lunar_text = lunar_short_str(date(year, month, day))
                lunar_lbl  = QLabel(lunar_text)
                lunar_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                lc = "#c8a96e" if lunar_text and len(lunar_text) >= 2 and "月" in lunar_text else "#777"
                lunar_lbl.setStyleSheet(f"color:{lc}; font-size:{fs_lunar}px; background:transparent;")
                if font_family:
                    lf = lunar_lbl.font()
                    lf.setFamily(font_family)
                    lunar_lbl.setFont(lf)
                vl.addWidget(lunar_lbl)

                self._grid.addWidget(cell, row, col)
            else:
                lbl = QLabel(str(day))
                lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                lbl.setStyleSheet(
                    f"color:{color}; font-size:{fs_day}px; background:{bg}; border-radius:3px;"
                )
                if font_family:
                    df = lbl.font()
                    df.setFamily(font_family)
                    lbl.setFont(df)
                self._grid.addWidget(lbl, row, col)

            col += 1
            if col > 6:
                col = 0
                row += 1

    def get_edit_widget(self):
        props = dict(self.config.props)
        props["grid_w"] = self.config.grid_w
        props["grid_h"] = self.config.grid_h
        return _CalendarEditPanel(props)

    def apply_props(self, props: dict) -> None:
        self.config.props.update(props)
        self.config.grid_w = max(2, int(props.get("grid_w", self.config.grid_w)))
        self.config.grid_h = max(2, int(props.get("grid_h", self.config.grid_h)))
        self.refresh()

"""时钟组件 —— 不可删除，可编辑显示内容/对齐/字体"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QVBoxLayout, QWidget,
    QLabel, QFormLayout,
)
from qfluentwidgets import CheckBox, ComboBox, SpinBox

from app.widgets.base_widget import WidgetBase, WidgetConfig
from app.utils.time_utils import now_in_zone, format_time, format_date, utc_offset_str
from app.views.world_time_view import _local_offset_diff_str   # 复用


# ─────────────────────────────────────────────────────────────
# 编辑面板
# ─────────────────────────────────────────────────────────────

class _ClockEditPanel(QWidget):
    def __init__(self, props: dict, parent=None):
        super().__init__(parent)
        f = QFormLayout(self)
        f.setVerticalSpacing(10)

        self._show_time = CheckBox()
        self._show_time.setChecked(props.get("show_time", True))
        self._show_date = CheckBox()
        self._show_date.setChecked(props.get("show_date", True))
        self._show_offset = CheckBox()
        self._show_offset.setChecked(props.get("show_offset", True))
        self._show_diff = CheckBox()
        self._show_diff.setChecked(props.get("show_diff", True))

        self._align = ComboBox()
        for label, val in [("居中", "center"), ("左对齐", "left"), ("右对齐", "right")]:
            self._align.addItem(label, val)
        cur = props.get("align", "center")
        idx = next((i for i in range(self._align.count()) if self._align.itemData(i) == cur), 0)
        self._align.setCurrentIndex(idx)

        self._font_size = SpinBox()
        self._font_size.setRange(24, 200)
        self._font_size.setSuffix(" pt")
        self._font_size.setValue(props.get("font_size", 64))

        self._font_weight = ComboBox()
        for label, val in [("细体", 100), ("常规", 400), ("粗体", 700)]:
            self._font_weight.addItem(label, val)
        fw = props.get("font_weight", 100)
        idx2 = next((i for i in range(self._font_weight.count()) if self._font_weight.itemData(i) == fw), 0)
        self._font_weight.setCurrentIndex(idx2)

        f.addRow("显示时间:", self._show_time)
        f.addRow("显示日期:", self._show_date)
        f.addRow("UTC 偏移:", self._show_offset)
        f.addRow("与本地差:", self._show_diff)
        f.addRow("对齐方式:", self._align)
        f.addRow("字体大小:", self._font_size)
        f.addRow("字体粗细:", self._font_weight)

    def collect_props(self) -> dict:
        return {
            "show_time":    self._show_time.isChecked(),
            "show_date":    self._show_date.isChecked(),
            "show_offset":  self._show_offset.isChecked(),
            "show_diff":    self._show_diff.isChecked(),
            "align":        self._align.currentData(),
            "font_size":    self._font_size.value(),
            "font_weight":  self._font_weight.currentData(),
        }


# ─────────────────────────────────────────────────────────────
# ClockWidget
# ─────────────────────────────────────────────────────────────

_ALIGN_MAP = {
    "left":   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
    "center": Qt.AlignmentFlag.AlignCenter,
    "right":  Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
}


class ClockWidget(WidgetBase):
    WIDGET_TYPE = "clock"
    WIDGET_NAME = "时钟"
    DELETABLE   = True
    MIN_W       = 2
    MIN_H       = 2
    DEFAULT_W   = 5
    DEFAULT_H   = 3

    def __init__(self, config: WidgetConfig, services, parent=None):
        super().__init__(config, services, parent)
        self._timezone: str = services.get("timezone", "local")

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(4)

        self._time_lbl = QLabel("--:--:--")
        self._date_lbl = QLabel("")
        self._info_lbl = QLabel("")

        for lbl in (self._time_lbl, self._date_lbl, self._info_lbl):
            lbl.setStyleSheet("color:white; background:transparent;")
            root.addWidget(lbl)

        root.addStretch()
        self.refresh()

    # ------------------------------------------------------------------ #

    def refresh(self) -> None:
        p    = self.config.props
        tz   = self._timezone
        dt   = now_in_zone(tz)
        align_flag = _ALIGN_MAP.get(p.get("align", "center"), Qt.AlignmentFlag.AlignCenter)

        # 时间
        if p.get("show_time", True):
            fs   = p.get("font_size", 64)
            fw   = p.get("font_weight", 100)
            font = QFont()
            font.setPointSize(fs)
            font.setWeight(QFont.Weight(fw))
            self._time_lbl.setFont(font)
            self._time_lbl.setText(format_time(dt))
            self._time_lbl.setAlignment(align_flag)
            self._time_lbl.show()
        else:
            self._time_lbl.hide()

        # 日期
        if p.get("show_date", True):
            self._date_lbl.setText(format_date(dt))
            self._date_lbl.setAlignment(align_flag)
            self._date_lbl.setStyleSheet("color:#aaa; font-size:20px; background:transparent;")
            self._date_lbl.show()
        else:
            self._date_lbl.hide()

        # 信息行
        parts = []
        if p.get("show_offset", True):
            parts.append(utc_offset_str(dt))
        if p.get("show_diff", True):
            diff = _local_offset_diff_str(tz)
            if diff:
                parts.append(diff)
        if parts:
            self._info_lbl.setText("  ".join(parts))
            self._info_lbl.setAlignment(align_flag)
            self._info_lbl.setStyleSheet("color:#666; font-size:16px; background:transparent;")
            self._info_lbl.show()
        else:
            self._info_lbl.hide()

    def get_edit_widget(self):
        return _ClockEditPanel(self.config.props)

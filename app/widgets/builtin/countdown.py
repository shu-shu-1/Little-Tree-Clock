"""倒数日组件"""
from __future__ import annotations

from datetime import date

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QVBoxLayout, QWidget, QLabel, QFormLayout,
)
from PySide6.QtCore import Qt, QDate
from qfluentwidgets import ComboBox, LineEdit, CalendarPicker, SpinBox

from app.services.i18n_service import tr
from app.widgets.base_widget import WidgetBase, WidgetConfig
from app.widgets.fluent_font_picker import FluentFontPicker


class _CountdownEditPanel(QWidget):
    def __init__(self, props: dict, parent=None):
        super().__init__(parent)
        f = QFormLayout(self)

        self._title = LineEdit()
        self._title.setText(props.get("title", tr("widget.countdown")))
        f.addRow(tr("widget.cfg.title"), self._title)

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
        f.addRow(tr("widget.cfg.target_date"), self._date)

        self._size = ComboBox()
        _dims = {"small": "1×1", "medium": "2×2", "large": "3×2"}
        for key, val in [("widget.size.small", "small"), ("widget.size.medium", "medium"), ("widget.size.large", "large")]:
            self._size.addItem(f"{tr(key)} ({_dims[val]})", userData=val)
        cur = props.get("size", "medium")
        idx = next((i for i in range(self._size.count()) if self._size.itemData(i) == cur), 1)
        self._size.setCurrentIndex(idx)
        f.addRow(tr("widget.cfg.size"), self._size)

        self._font_picker = FluentFontPicker()
        self._font_picker.setCurrentFontFamily(props.get("font_family", ""))

        self._font_size = SpinBox()
        self._font_size.setRange(12, 200)
        self._font_size.setSuffix(" pt")
        self._font_size.setValue(props.get("font_size", 52))

        f.addRow(tr("widget.cfg.font"), self._font_picker)
        f.addRow(tr("widget.cfg.font_size"), self._font_size)

    def collect_props(self) -> dict:
        qd = self._date.getDate()
        return {
            "title":       self._title.text(),
            "target_date": f"{qd.year()}-{qd.month():02d}-{qd.day():02d}",
            "size":        self._size.currentData(),
            "font_family": self._font_picker.currentFontFamily(),
            "font_size":   self._font_size.value(),
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

        self._days_lbl = QLabel("")
        self._days_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._sub_lbl = QLabel(tr("widget.countdown.days"))
        self._sub_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        root.addStretch()
        root.addWidget(self._title_lbl)
        root.addWidget(self._days_lbl)
        root.addWidget(self._sub_lbl)
        root.addStretch()

        self.refresh()

    def refresh(self) -> None:
        c = self._wc()
        p = self.config.props
        self._title_lbl.setText(p.get("title", tr("widget.countdown")))

        ff = p.get("font_family") or ""
        fs = p.get("font_size") or 52
        font = QFont()
        if ff:
            font.setFamily(ff)

        days_font = QFont(font)
        days_font.setPointSize(fs)
        days_font.setWeight(QFont.Weight(200))
        self._days_lbl.setFont(days_font)
        self._days_lbl.setStyleSheet(f"color:{c['primary']}; font-size:{fs}px; font-weight:200; background:transparent;")

        title_font = QFont(font)
        title_font.setPointSize(max(10, fs // 3))
        title_font.setWeight(QFont.Weight.Normal)
        self._title_lbl.setFont(title_font)
        self._title_lbl.setStyleSheet(f"color:{c['secondary']}; font-size:15px; background:transparent;")

        sub_font = QFont(font)
        sub_font.setPointSize(max(10, fs // 4))
        sub_font.setWeight(QFont.Weight.Normal)
        self._sub_lbl.setFont(sub_font)
        self._sub_lbl.setStyleSheet(f"color:{c['tertiary']}; font-size:14px; background:transparent;")

        target_str = p.get("target_date", "")
        if not target_str:
            self._days_lbl.setText("--")
            self._sub_lbl.setText(tr("widget.countdown.set_date"))
            return
        try:
            target = date.fromisoformat(target_str)
            delta  = (target - date.today()).days
            if delta > 0:
                self._days_lbl.setText(f"{delta}")
                self._sub_lbl.setText(tr("widget.countdown.days_after"))
            elif delta == 0:
                self._days_lbl.setText(tr("widget.countdown.today"))
                self._sub_lbl.setText("🎉")
            else:
                self._days_lbl.setText(f"{-delta}")
                self._sub_lbl.setText(tr("widget.countdown.days_ago"))
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

"""闹钟列表组件"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QVBoxLayout, QWidget, QLabel, QFormLayout,
)
from qfluentwidgets import ComboBox, SmoothScrollArea

from app.widgets.base_widget import WidgetBase, WidgetConfig
from app.models.alarm_model import AlarmStore


class _AlarmEditPanel(QWidget):
    def __init__(self, props: dict, parent=None):
        super().__init__(parent)
        f = QFormLayout(self)
        self._size = ComboBox()
        for label, val in [("小 (1×2)", "small"), ("中 (2×3)", "medium"), ("大 (3×4)", "large")]:
            self._size.addItem(label, userData=val)
        cur = props.get("size", "medium")
        idx = next((i for i in range(self._size.count()) if self._size.itemData(i) == cur), 1)
        self._size.setCurrentIndex(idx)
        f.addRow("组件大小:", self._size)

    def collect_props(self) -> dict:
        return {"size": self._size.currentData()}


_SIZE_MAP = {"small": (1, 2), "medium": (2, 3), "large": (3, 4)}


class AlarmListWidget(WidgetBase):
    WIDGET_TYPE = "alarm_list"
    WIDGET_NAME = "闹钟列表"
    DELETABLE   = True
    DEFAULT_W   = 2
    DEFAULT_H   = 3

    def __init__(self, config: WidgetConfig, services, parent=None):
        super().__init__(config, services, parent)
        self._store = AlarmStore()

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 4, 8, 4)
        root.setSpacing(0)

        title = QLabel("🔔 闹钟")
        title.setStyleSheet("color:#aaa; font-size:14px; background:transparent;")
        root.addWidget(title)

        sa = SmoothScrollArea()
        sa.setWidgetResizable(True)
        sa.setStyleSheet("background:transparent; border:none;")
        self._inner = QWidget()
        self._inner.setStyleSheet("background:transparent;")
        self._inner_layout = QVBoxLayout(self._inner)
        self._inner_layout.setSpacing(4)
        self._inner_layout.setContentsMargins(0, 4, 0, 0)
        sa.setWidget(self._inner)
        root.addWidget(sa, 1)

        self.refresh()

    def refresh(self) -> None:
        while self._inner_layout.count():
            item = self._inner_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        alarms = self._store.all()
        if not alarms:
            lbl = QLabel("暂无闹钟")
            lbl.setStyleSheet("color:#555; font-size:13px; background:transparent;")
            self._inner_layout.addWidget(lbl)
        else:
            for al in sorted(alarms, key=lambda a: (a.hour, a.minute))[:8]:
                status = "🔔" if al.enabled else "🔕"
                repeat = al.repeat.label() if hasattr(al, "repeat") and al.repeat else ""
                time_str = f"{al.hour:02d}:{al.minute:02d}"
                text   = f"{status} {time_str}  {al.label or ''}  {repeat}"
                lbl = QLabel(text)
                lbl.setStyleSheet("color:white; font-size:14px; background:transparent;")
                self._inner_layout.addWidget(lbl)

        self._inner_layout.addStretch()

    def get_edit_widget(self):
        return _AlarmEditPanel(self.config.props)

    def apply_props(self, props: dict) -> None:
        self.config.props.update(props)
        w, h = _SIZE_MAP.get(props.get("size", "medium"), (2, 3))
        self.config.grid_w = w
        self.config.grid_h = h
        self.refresh()

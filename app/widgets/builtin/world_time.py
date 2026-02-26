"""其他时区时间组件"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QVBoxLayout, QScrollArea, QWidget, QLabel, QFormLayout,
)
from qfluentwidgets import ComboBox

from app.widgets.base_widget import WidgetBase, WidgetConfig
from app.models.world_zone import WorldZoneStore
from app.utils.time_utils import now_in_zone, format_time


class _WorldTimeEditPanel(QWidget):
    def __init__(self, props: dict, parent=None):
        super().__init__(parent)
        f = QFormLayout(self)
        self._size = ComboBox()
        for label, val in [("小 (2×2)", "small"), ("中 (2×3)", "medium"), ("大 (3×4)", "large")]:
            self._size.addItem(label, val)
        cur = props.get("size", "medium")
        idx = next((i for i in range(self._size.count()) if self._size.itemData(i) == cur), 1)
        self._size.setCurrentIndex(idx)
        f.addRow("组件大小:", self._size)

    def collect_props(self) -> dict:
        return {"size": self._size.currentData()}


_SIZE_MAP = {"small": (2, 2), "medium": (2, 3), "large": (3, 4)}


class WorldTimeWidget(WidgetBase):
    WIDGET_TYPE = "world_time"
    WIDGET_NAME = "世界时间"
    DELETABLE   = True
    DEFAULT_W   = 2
    DEFAULT_H   = 3

    def __init__(self, config: WidgetConfig, services, parent=None):
        super().__init__(config, services, parent)
        self._store = WorldZoneStore()

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 4, 8, 4)
        root.setSpacing(0)

        title = QLabel("🌍 世界时间")
        title.setStyleSheet("color:#aaa; font-size:14px; background:transparent;")
        root.addWidget(title)

        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setStyleSheet("background:transparent; border:none;")
        self._inner = QWidget()
        self._inner.setStyleSheet("background:transparent;")
        self._inner_layout = QVBoxLayout(self._inner)
        self._inner_layout.setSpacing(6)
        self._inner_layout.setContentsMargins(0, 4, 0, 0)
        sa.setWidget(self._inner)
        root.addWidget(sa, 1)

        self.refresh()

    def refresh(self) -> None:
        while self._inner_layout.count():
            item = self._inner_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        zones = self._store.all()
        if not zones:
            lbl = QLabel("暂无时区")
            lbl.setStyleSheet("color:#555; font-size:13px; background:transparent;")
            self._inner_layout.addWidget(lbl)
        else:
            for zone in zones[:6]:
                dt = now_in_zone(zone.timezone)
                row = QWidget()
                row.setStyleSheet("background:transparent;")
                rl = QVBoxLayout(row)
                rl.setContentsMargins(0, 0, 0, 0)
                rl.setSpacing(0)
                city = QLabel(zone.label or zone.timezone)
                city.setStyleSheet("color:#888; font-size:12px; background:transparent;")
                time = QLabel(format_time(dt))
                time.setStyleSheet("color:white; font-size:20px; font-weight:300; background:transparent;")
                rl.addWidget(city)
                rl.addWidget(time)
                self._inner_layout.addWidget(row)

        self._inner_layout.addStretch()

    def get_edit_widget(self):
        return _WorldTimeEditPanel(self.config.props)

    def apply_props(self, props: dict) -> None:
        self.config.props.update(props)
        w, h = _SIZE_MAP.get(props.get("size", "medium"), (2, 3))
        self.config.grid_w = w
        self.config.grid_h = h
        self.refresh()

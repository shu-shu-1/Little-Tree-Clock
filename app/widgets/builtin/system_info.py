"""系统信息组件 —— 显示 CPU、内存、磁盘、网络等实时数据"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QVBoxLayout, QWidget, QLabel, QFormLayout, QGridLayout,
)
from qfluentwidgets import CheckBox, ComboBox, SpinBox

from app.widgets.base_widget import WidgetBase, WidgetConfig
from app.utils.theme_utils import widget_colors


class _SystemInfoEditPanel(QWidget):
    def __init__(self, props: dict, config, parent=None):
        super().__init__(parent)
        f = QFormLayout(self)
        f.setVerticalSpacing(10)

        self._show_cpu = CheckBox()
        self._show_cpu.setChecked(props.get("show_cpu", True))

        self._show_memory = CheckBox()
        self._show_memory.setChecked(props.get("show_memory", True))

        self._show_disk = CheckBox()
        self._show_disk.setChecked(props.get("show_disk", True))

        self._show_network = CheckBox()
        self._show_network.setChecked(props.get("show_network", False))

        self._show_uptime = CheckBox()
        self._show_uptime.setChecked(props.get("show_uptime", False))

        self._layout_mode = ComboBox()
        for label, val in [("列表", "list"), ("网格", "grid")]:
            self._layout_mode.addItem(label, userData=val)
        cur = props.get("layout_mode", "list")
        idx = next(
            (i for i in range(self._layout_mode.count())
             if self._layout_mode.itemData(i) == cur), 0
        )
        self._layout_mode.setCurrentIndex(idx)

        self._grid_w = SpinBox()
        self._grid_w.setRange(2, 20)
        self._grid_w.setSuffix(" 格")
        self._grid_w.setValue(config.grid_w)

        self._grid_h = SpinBox()
        self._grid_h.setRange(2, 20)
        self._grid_h.setSuffix(" 格")
        self._grid_h.setValue(config.grid_h)

        f.addRow("CPU 使用率:", self._show_cpu)
        f.addRow("内存使用:", self._show_memory)
        f.addRow("磁盘使用:", self._show_disk)
        f.addRow("网络速率:", self._show_network)
        f.addRow("运行时间:", self._show_uptime)
        f.addRow("布局:", self._layout_mode)
        f.addRow("组件宽度:", self._grid_w)
        f.addRow("组件高度:", self._grid_h)

    def collect_props(self) -> dict:
        return {
            "show_cpu":     self._show_cpu.isChecked(),
            "show_memory":  self._show_memory.isChecked(),
            "show_disk":    self._show_disk.isChecked(),
            "show_network": self._show_network.isChecked(),
            "show_uptime":  self._show_uptime.isChecked(),
            "layout_mode":  self._layout_mode.currentData(),
            "grid_w":       self._grid_w.value(),
            "grid_h":       self._grid_h.value(),
        }


def _fmt_bytes(b: float) -> str:
    if b < 1024:
        return f"{b:.0f} B"
    if b < 1024 * 1024:
        return f"{b / 1024:.1f} KB"
    if b < 1024 * 1024 * 1024:
        return f"{b / (1024 * 1024):.1f} MB"
    return f"{b / (1024 * 1024 * 1024):.1f} GB"


def _fmt_uptime(seconds: float) -> str:
    s = int(seconds)
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    parts = []
    if d > 0:
        parts.append(f"{d}天")
    if h > 0:
        parts.append(f"{h}时")
    if m > 0:
        parts.append(f"{m}分")
    return "".join(parts) or "刚刚"


def _label_style(c: dict) -> str:
    return f"color:{c['secondary']}; font-size:12px; background:transparent;"

def _value_style(c: dict) -> str:
    return f"color:{c['primary']}; font-size:18px; font-weight:600; background:transparent;"

def _unit_style(c: dict) -> str:
    return f"color:{c['tertiary']}; font-size:11px; background:transparent;"


class SystemInfoWidget(WidgetBase):
    WIDGET_TYPE = "system_info"
    WIDGET_NAME = "系统信息"
    DELETABLE = True
    DEFAULT_W = 3
    DEFAULT_H = 3
    MIN_W = 2
    MIN_H = 2
    RUNS_IN_BACKGROUND = False

    def __init__(self, config: WidgetConfig, services, parent=None):
        super().__init__(config, services, parent)

        self._labels: dict[str, tuple[QLabel, QLabel, QLabel]] = {}
        self._last_net_sent = 0.0
        self._last_net_recv = 0.0
        self._net_inited = False

        self._build_ui()
        self._collect_and_update()

    def _build_ui(self):
        p = self.config.props
        mode = p.get("layout_mode", "list")

        if mode == "grid":
            self._layout = QGridLayout(self)
            self._layout.setContentsMargins(10, 8, 10, 8)
            self._layout.setSpacing(6)
        else:
            self._layout = QVBoxLayout(self)
            self._layout.setContentsMargins(12, 8, 12, 8)
            self._layout.setSpacing(8)

        self._rebuild_items()

    def _rebuild_items(self):
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._labels.clear()
        p = self.config.props
        mode = p.get("layout_mode", "list")

        sections = []
        if p.get("show_cpu", True):
            sections.append("cpu")
        if p.get("show_memory", True):
            sections.append("memory")
        if p.get("show_disk", True):
            sections.append("disk")
        if p.get("show_network", False):
            sections.append("network")
        if p.get("show_uptime", False):
            sections.append("uptime")

        if mode == "grid":
            col = 0
            row = 0
            cols = max(2, min(3, self.config.grid_w))
            for key in sections:
                card = self._make_card(key)
                self._layout.addWidget(card, row, col)
                col += 1
                if col >= cols:
                    col = 0
                    row += 1
        else:
            for key in sections:
                card = self._make_card(key)
                self._layout.addWidget(card)
            self._layout.addStretch()

    def _make_card(self, key: str) -> QWidget:
        card = QWidget()
        card.setStyleSheet("background:transparent;")

        titles = {
            "cpu": "CPU",
            "memory": "内存",
            "disk": "磁盘",
            "network": "网络",
            "uptime": "运行时间",
        }

        layout = QVBoxLayout(card)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        c = self._wc()

        title_lbl = QLabel(titles.get(key, key))
        title_lbl.setStyleSheet(_label_style(c))
        layout.addWidget(title_lbl)

        value_lbl = QLabel("--")
        value_lbl.setStyleSheet(_value_style(c))
        layout.addWidget(value_lbl)

        sub_lbl = QLabel("")
        sub_lbl.setStyleSheet(_unit_style(c))
        layout.addWidget(sub_lbl)

        self._labels[key] = (title_lbl, value_lbl, sub_lbl)
        return card

    def _collect_and_update(self):
        try:
            import psutil
        except ImportError:
            return

        p = self.config.props

        if p.get("show_cpu", True) and "cpu" in self._labels:
            _, val, sub = self._labels["cpu"]
            pct = psutil.cpu_percent(interval=0)
            val.setText(f"{pct:.0f}%")
            sub.setText(f"核心: {psutil.cpu_count(logical=True)}")

        if p.get("show_memory", True) and "memory" in self._labels:
            _, val, sub = self._labels["memory"]
            mem = psutil.virtual_memory()
            val.setText(f"{mem.percent:.0f}%")
            sub.setText(
                f"{_fmt_bytes(mem.used)} / {_fmt_bytes(mem.total)}"
            )

        if p.get("show_disk", True) and "disk" in self._labels:
            _, val, sub = self._labels["disk"]
            try:
                disk = psutil.disk_usage("/")
            except Exception:
                try:
                    disk = psutil.disk_usage("C:\\")
                except Exception:
                    disk = None
            if disk:
                val.setText(f"{disk.percent:.0f}%")
                sub.setText(
                    f"{_fmt_bytes(disk.used)} / {_fmt_bytes(disk.total)}"
                )

        if p.get("show_network", False) and "network" in self._labels:
            _, val, sub = self._labels["network"]
            net = psutil.net_io_counters()
            if net:
                cur_sent = net.bytes_sent
                cur_recv = net.bytes_recv
                if self._net_inited:
                    ds = max(0, cur_sent - self._last_net_sent)
                    dr = max(0, cur_recv - self._last_net_recv)
                    val.setText(
                        f"↑{_fmt_bytes(ds)}/s"
                    )
                    sub.setText(
                        f"↓{_fmt_bytes(dr)}/s"
                    )
                else:
                    val.setText("--")
                    sub.setText(
                        f"累计 ↑{_fmt_bytes(cur_sent)} ↓{_fmt_bytes(cur_recv)}"
                    )
                    self._net_inited = True
                self._last_net_sent = cur_sent
                self._last_net_recv = cur_recv

        if p.get("show_uptime", False) and "uptime" in self._labels:
            _, val, sub = self._labels["uptime"]
            try:
                uptime_s = psutil.boot_time()
                import time
                elapsed = time.time() - uptime_s
                val.setText(_fmt_uptime(elapsed))
                sub.setText("")
            except Exception:
                val.setText("--")

    def refresh(self) -> None:
        self._collect_and_update()

    def get_edit_widget(self):
        props = dict(self.config.props)
        props["grid_w"] = self.config.grid_w
        props["grid_h"] = self.config.grid_h
        return _SystemInfoEditPanel(props, self.config)

    def apply_props(self, props: dict) -> None:
        self.config.props.update(props)
        self.config.grid_w = max(2, int(props.get("grid_w", self.DEFAULT_W)))
        self.config.grid_h = max(2, int(props.get("grid_h", self.DEFAULT_H)))
        old_layout = self.layout()
        if old_layout:
            while old_layout.count():
                item = old_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            self._labels.clear()
        self._rebuild_items()
        self.refresh()

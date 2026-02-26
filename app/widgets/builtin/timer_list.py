"""单个计时器组件 —— 进度环 + 时间 + 交互按钮"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QWidget,
    QLabel, QFormLayout,
)
from qfluentwidgets import (
    ProgressRing, TransparentToolButton, FluentIcon as FIF,
    ComboBox, SpinBox,
)

from app.widgets.base_widget import WidgetBase, WidgetConfig
from app.utils.time_utils import format_duration
from app.constants import TIMER_CONFIG


def _load_timer_data() -> list[dict]:
    try:
        data = json.loads(Path(TIMER_CONFIG).read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────
# 编辑面板
# ─────────────────────────────────────────────────────────────

class _TimerEditPanel(QWidget):
    def __init__(self, props: dict, parent=None):
        super().__init__(parent)
        f = QFormLayout(self)
        f.setVerticalSpacing(10)

        # 计时器选择
        self._timer_combo = ComboBox()
        timers = _load_timer_data()
        if timers:
            for t in timers:
                self._timer_combo.addItem(t.get("label", t.get("id", "?")), t.get("id"))
            current_id = props.get("timer_id", "")
            idx = next(
                (i for i in range(self._timer_combo.count())
                 if self._timer_combo.itemData(i) == current_id), 0
            )
            self._timer_combo.setCurrentIndex(idx)
        else:
            self._timer_combo.addItem("（无可用计时器，请先在计时器页创建）", None)
            self._timer_combo.setEnabled(False)
        f.addRow("选择计时器:", self._timer_combo)

        # 横向格数
        self._w_spin = SpinBox()
        self._w_spin.setRange(2, 20)
        self._w_spin.setValue(props.get("grid_w", 2))
        f.addRow("横向格数:", self._w_spin)

        # 纵向格数
        self._h_spin = SpinBox()
        self._h_spin.setRange(2, 20)
        self._h_spin.setValue(props.get("grid_h", 3))
        f.addRow("纵向格数:", self._h_spin)

    def collect_props(self) -> dict:
        return {
            "timer_id": self._timer_combo.currentData(),
            "grid_w":   self._w_spin.value(),
            "grid_h":   self._h_spin.value(),
        }


# ─────────────────────────────────────────────────────────────
# TimerListWidget  （保留原 type 名兼容已存储布局）
# ─────────────────────────────────────────────────────────────

class TimerListWidget(WidgetBase):
    WIDGET_TYPE = "timer_list"
    WIDGET_NAME = "计时器"
    DELETABLE   = True
    DEFAULT_W   = 2
    DEFAULT_H   = 3

    def __init__(self, config: WidgetConfig, services, parent=None):
        super().__init__(config, services, parent)
        self._item = None  # 当前关联的实时 TimerItem

        # ── 外层透明布局 ──────────────────────────────
        outer_lay = QVBoxLayout(self)
        outer_lay.setContentsMargins(0, 0, 0, 0)
        outer_lay.setSpacing(0)

        # ── 卡片（与悬浮小窗相同的深色圆角背景）────────
        self._card = QWidget()
        self._card.setObjectName("timerWidgetCard")
        self._card.setStyleSheet(
            "QWidget#timerWidgetCard{"
            "background:rgb(30,30,30);"
            "border-radius:16px;"
            "}"
        )
        outer_lay.addWidget(self._card, 1)

        root = QVBoxLayout(self._card)
        root.setContentsMargins(12, 10, 12, 12)
        root.setSpacing(6)

        # 标题行（标签名）
        self._label_lbl = QLabel("")
        self._label_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._label_lbl.setStyleSheet(
            "color:rgba(255,255,255,160); font-size:13px; background:transparent;"
        )
        root.addWidget(self._label_lbl)

        # 进度环容器（120px，与悬浮小窗一致）
        RING_SIZE = 120
        self._ring_wrap = QWidget()
        self._ring_wrap.setFixedSize(RING_SIZE, RING_SIZE)
        self._ring_wrap.setStyleSheet("background:transparent;")

        self._ring = ProgressRing(self._ring_wrap)
        self._ring.setFixedSize(RING_SIZE, RING_SIZE)
        self._ring.setRange(0, 1000)
        self._ring.setValue(0)
        self._ring.setTextVisible(False)
        self._ring.setStrokeWidth(8)
        self._ring.move(0, 0)

        self._time_lbl = QLabel("--:--", self._ring_wrap)
        self._time_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._time_lbl.setFixedSize(RING_SIZE, RING_SIZE)
        self._time_lbl.setStyleSheet(
            "color:white; font-size:20px; font-weight:600; background:transparent;"
        )
        self._time_lbl.move(0, 0)
        self._time_lbl.raise_()

        ring_row = QHBoxLayout()
        ring_row.addStretch()
        ring_row.addWidget(self._ring_wrap)
        ring_row.addStretch()
        root.addLayout(ring_row, 1)

        # 状态标签
        self._status_lbl = QLabel("")
        self._status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_lbl.setStyleSheet(
            "color:#888; font-size:12px; background:transparent;"
        )
        root.addWidget(self._status_lbl)

        # ── 交互按钮行（与悬浮小窗相同布局）────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(16)

        self._toggle_btn = TransparentToolButton(FIF.PLAY)
        self._toggle_btn.setFixedSize(32, 32)
        self._toggle_btn.setToolTip("开始 / 暂停")
        self._toggle_btn.setStyleSheet("color:white;")
        self._toggle_btn.clicked.connect(self._on_toggle)

        self._reset_btn = TransparentToolButton(FIF.SYNC)
        self._reset_btn.setFixedSize(32, 32)
        self._reset_btn.setToolTip("重置")
        self._reset_btn.setStyleSheet("color:white;")
        self._reset_btn.clicked.connect(self._on_reset)

        btn_row.addStretch()
        btn_row.addWidget(self._toggle_btn)
        btn_row.addWidget(self._reset_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        # ── 空态提示（直接加入 card 布局，无计时器时显示）──
        self._empty_lbl = QLabel("尚无计时器\n请先在计时器页中创建")
        self._empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_lbl.setWordWrap(True)
        self._empty_lbl.setStyleSheet(
            "color:#555; font-size:13px; background:transparent;"
        )
        root.addWidget(self._empty_lbl)

        # 初始绑定
        self._reconnect_item(config.props.get("timer_id"))

    # ------------------------------------------------------------------ #
    # 私有辅助
    # ------------------------------------------------------------------ #

    def _reconnect_item(self, timer_id: Optional[str]) -> None:
        """断开旧 item 信号，从共享字典中获取新 item"""
        if self._item is not None:
            try:
                self._item.updated.disconnect(self._on_item_updated)
            except Exception:
                pass
            self._item = None

        if not timer_id:
            return

        try:
            from app.views.timer_view import _shared_items
            item = _shared_items.get(timer_id)
        except Exception:
            item = None

        if item is not None:
            self._item = item
            item.updated.connect(self._on_item_updated)

    def _on_item_updated(self) -> None:
        self._sync_from_item()

    def _sync_from_item(self) -> None:
        item = self._item
        if item is None:
            return

        self._ring.setValue(int(item.progress * 1000))
        self._time_lbl.setText(format_duration(item.remaining))
        self._label_lbl.setText(item.label)

        if item.done:
            self._status_lbl.setText("已结束")
            self._status_lbl.setStyleSheet("color:#e55; font-size:12px; background:transparent;")
            self._toggle_btn.setEnabled(False)
            self._toggle_btn.setIcon(FIF.PLAY)
        elif item.running:
            self._status_lbl.setText("▶ 运行中")
            self._status_lbl.setStyleSheet("color:#5c5; font-size:12px; background:transparent;")
            self._toggle_btn.setEnabled(True)
            self._toggle_btn.setIcon(FIF.PAUSE)
        else:
            self._status_lbl.setText("⏸ 已暂停")
            self._status_lbl.setStyleSheet("color:#888; font-size:12px; background:transparent;")
            self._toggle_btn.setEnabled(True)
            self._toggle_btn.setIcon(FIF.PLAY)

    def _sync_from_json(self) -> None:
        """无实时引用时从 JSON 静态显示（只读）"""
        timer_id = self.config.props.get("timer_id")
        timers   = _load_timer_data()

        if not timers:
            self._ring_wrap.hide()
            self._label_lbl.hide()
            self._status_lbl.hide()
            self._toggle_btn.hide()
            self._reset_btn.hide()
            self._empty_lbl.show()
            return

        data = next((t for t in timers if t.get("id") == timer_id), None)
        if data is None:
            data = timers[0]
            self.config.props["timer_id"] = data.get("id", "")

        self._empty_lbl.hide()
        self._ring_wrap.show()
        self._label_lbl.show()
        self._status_lbl.show()
        self._toggle_btn.show()
        self._reset_btn.show()

        total     = data.get("total_ms", 1) or 1
        remaining = data.get("remaining", total)

        self._ring.setValue(max(0, min(1000, int((1 - remaining / total) * 1000))))
        self._time_lbl.setText(format_duration(remaining))
        self._label_lbl.setText(data.get("label", "计时器"))

        # 只读模式
        self._toggle_btn.setEnabled(False)
        self._reset_btn.setEnabled(False)
        if data.get("done", False):
            self._status_lbl.setText("已结束（只读）")
            self._status_lbl.setStyleSheet("color:#e55; font-size:12px; background:transparent;")
        else:
            self._status_lbl.setText("（请打开计时器页 以启用控制）")
            self._status_lbl.setStyleSheet("color:#666; font-size:11px; background:transparent;")

    # ------------------------------------------------------------------ #
    # 按钮回调
    # ------------------------------------------------------------------ #

    def _on_toggle(self) -> None:
        if self._item is None:
            return
        if self._item.running:
            self._item.pause()
        elif not self._item.done:
            self._item.start()

    def _on_reset(self) -> None:
        if self._item is None:
            return
        self._item.reset()
        self._toggle_btn.setEnabled(True)

    # ------------------------------------------------------------------ #
    # WidgetBase 接口
    # ------------------------------------------------------------------ #

    def refresh(self) -> None:
        if self._item is not None:
            self._empty_lbl.hide()
            self._ring_wrap.show()
            self._label_lbl.show()
            self._status_lbl.show()
            self._toggle_btn.show()
            self._reset_btn.show()
            self._toggle_btn.setEnabled(True)
            self._reset_btn.setEnabled(True)
            self._sync_from_item()
        else:
            # 尝试延迟绑定
            timer_id = self.config.props.get("timer_id")
            if timer_id:
                self._reconnect_item(timer_id)
            if self._item is not None:
                self.refresh()
            else:
                self._sync_from_json()

    def get_edit_widget(self):
        props = dict(self.config.props)
        props["grid_w"] = self.config.grid_w
        props["grid_h"] = self.config.grid_h
        return _TimerEditPanel(props)

    def apply_props(self, props: dict) -> None:
        self.config.props.update(props)
        self.config.grid_w = max(2, int(props.get("grid_w", self.DEFAULT_W)))
        self.config.grid_h = max(2, int(props.get("grid_h", self.DEFAULT_H)))
        self._reconnect_item(props.get("timer_id"))
        self.refresh()

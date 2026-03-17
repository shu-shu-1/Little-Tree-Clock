"""单个计时器组件（多样式）

样式 A：进度环 + 时间叠加
样式 B：大字倒计时 + 可选进度条（类时钟组件）
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QTimer as _QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QStackedWidget, QWidget,
    QLabel, QFormLayout,
)
from qfluentwidgets import (
    ProgressRing, ProgressBar, TransparentToolButton, FluentIcon as FIF,
    ComboBox, SpinBox, CheckBox,
)

from app.widgets.base_widget import WidgetBase, WidgetConfig
from app.utils.time_utils import format_duration
from app.constants import TIMER_CONFIG, TIMER_TICK_MS


# ─────────────────────────────────────────────────────────────
# 辅助
# ─────────────────────────────────────────────────────────────

def _load_timer_data() -> list[dict]:
    try:
        data = json.loads(Path(TIMER_CONFIG).read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _get_or_create_item(timer_id: str):
    """
    从 _shared_items 获取 TimerItem；若不存在则从 JSON 构建并注册。
    返回 (item, created_fresh)  ——  created_fresh=True 表示由本函数新建，
    调用方需自行负责 tick。
    """
    if not timer_id:
        return None, False
    try:
        from app.views.timer_view import _shared_items, TimerItem
        if timer_id in _shared_items:
            return _shared_items[timer_id], False
        # 尝试从 JSON 创建
        timers = _load_timer_data()
        data = next((t for t in timers if t.get("id") == timer_id), None)
        if data:
            item = TimerItem.from_dict(data)
            _shared_items[timer_id] = item
            return item, True
    except Exception:
        pass
    return None, False


# ─────────────────────────────────────────────────────────────
# 按钮样式（白色半透明，醒目圆形背景）
# ─────────────────────────────────────────────────────────────

_BTN_STYLE = (
    "TransparentToolButton{"
    "  background:rgba(255,255,255,35);"
    "  border-radius:20px;"
    "  color:white;"
    "}"
    "TransparentToolButton:hover{"
    "  background:rgba(255,255,255,65);"
    "}"
    "TransparentToolButton:pressed{"
    "  background:rgba(255,255,255,18);"
    "}"
    "TransparentToolButton:disabled{"
    "  background:rgba(255,255,255,10);"
    "  color:rgba(255,255,255,70);"
    "}"
)


# ─────────────────────────────────────────────────────────────
# 编辑面板
# ─────────────────────────────────────────────────────────────

class _TimerEditPanel(QWidget):
    def __init__(self, props: dict, parent=None):
        super().__init__(parent)
        f = QFormLayout(self)
        f.setVerticalSpacing(10)

        # ── 计时器选择 ──────────────────────────────────────
        self._timer_combo = ComboBox()
        timers = _load_timer_data()
        if timers:
            for t in timers:
                self._timer_combo.addItem(
                    t.get("label", t.get("id", "?")), userData=t.get("id")
                )
            current_id = props.get("timer_id", "")
            idx = next(
                (i for i in range(self._timer_combo.count())
                 if self._timer_combo.itemData(i) == current_id),
                0,
            )
            self._timer_combo.setCurrentIndex(idx)
        else:
            self._timer_combo.addItem("（无可用计时器，请先在计时器页创建）", None)
            self._timer_combo.setEnabled(False)
        f.addRow("选择计时器:", self._timer_combo)

        # ── 显示样式 ─────────────────────────────────────────
        self._style_combo = ComboBox()
        self._style_combo.addItem("进度环样式", userData="ring")
        self._style_combo.addItem("大字倒计时样式", userData="big")
        cur_style = props.get("style", "ring")
        self._style_combo.setCurrentIndex(0 if cur_style == "ring" else 1)
        self._style_combo.currentIndexChanged.connect(self._on_style_changed)
        f.addRow("显示样式:", self._style_combo)

        # ── 大字样式专属 ─────────────────────────────────────
        self._font_size = SpinBox()
        self._font_size.setRange(24, 200)
        self._font_size.setSuffix(" pt")
        self._font_size.setValue(props.get("font_size", 72))
        f.addRow("倒计时字号:", self._font_size)

        self._show_bar = CheckBox()
        self._show_bar.setChecked(props.get("show_progress_bar", True))
        f.addRow("显示进度条:", self._show_bar)

        # ── 组件尺寸 ─────────────────────────────────────────
        self._w_spin = SpinBox()
        self._w_spin.setRange(2, 20)
        self._w_spin.setValue(props.get("grid_w", 2))
        f.addRow("横向格数:", self._w_spin)

        self._h_spin = SpinBox()
        self._h_spin.setRange(2, 20)
        self._h_spin.setValue(props.get("grid_h", 3))
        f.addRow("纵向格数:", self._h_spin)

        self._on_style_changed()

    def _on_style_changed(self) -> None:
        is_big = self._style_combo.currentData() == "big"
        self._font_size.setEnabled(is_big)
        self._show_bar.setEnabled(is_big)

    def collect_props(self) -> dict:
        return {
            "timer_id":          self._timer_combo.currentData(),
            "style":             self._style_combo.currentData() or "ring",
            "font_size":         self._font_size.value(),
            "show_progress_bar": self._show_bar.isChecked(),
            "grid_w":            self._w_spin.value(),
            "grid_h":            self._h_spin.value(),
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
        self._item       = None    # 当前关联的 TimerItem
        self._owns_item  = False   # True = 本组件从 JSON 自建，需自行 tick
        self._tick_timer = None    # 独立 QTimer（仅 fallback 时使用）
        self._clock_svc  = services.get("clock_service")

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(6)

        # ── 标题行（含前/后切换按钮）────────────────────────
        header_row = QHBoxLayout()
        header_row.setSpacing(4)

        self._prev_btn = TransparentToolButton(FIF.LEFT_ARROW)
        self._prev_btn.setFixedSize(22, 22)
        self._prev_btn.setToolTip("上一个计时器")
        self._prev_btn.setStyleSheet(
            "TransparentToolButton{background:rgba(255,255,255,20);"
            "border-radius:11px;color:white;}"
            "TransparentToolButton:hover{background:rgba(255,255,255,45);}"
        )
        self._prev_btn.clicked.connect(self._switch_prev)

        self._label_lbl = QLabel("")
        self._label_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label_lbl.setStyleSheet(
            "color:rgba(255,255,255,180); font-size:13px; background:transparent;"
        )

        self._next_btn = TransparentToolButton(FIF.RIGHT_ARROW)
        self._next_btn.setFixedSize(22, 22)
        self._next_btn.setToolTip("下一个计时器")
        self._next_btn.setStyleSheet(
            "TransparentToolButton{background:rgba(255,255,255,20);"
            "border-radius:11px;color:white;}"
            "TransparentToolButton:hover{background:rgba(255,255,255,45);}"
        )
        self._next_btn.clicked.connect(self._switch_next)

        header_row.addWidget(self._prev_btn)
        header_row.addWidget(self._label_lbl, 1)
        header_row.addWidget(self._next_btn)
        root.addLayout(header_row)

        # ─────────────────────────────────────────────────────
        # 样式 A：进度环
        # ─────────────────────────────────────────────────────
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

        self._time_ring_lbl = QLabel("--:--", self._ring_wrap)
        self._time_ring_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._time_ring_lbl.setFixedSize(RING_SIZE, RING_SIZE)
        self._time_ring_lbl.setStyleSheet(
            "color:white; font-size:20px; font-weight:600; background:transparent;"
        )
        self._time_ring_lbl.move(0, 0)
        self._time_ring_lbl.raise_()

        ring_row = QHBoxLayout()
        ring_row.addStretch()
        ring_row.addWidget(self._ring_wrap)
        ring_row.addStretch()

        self._ring_container = QWidget()
        self._ring_container.setStyleSheet("background:transparent;")
        rc_lay = QVBoxLayout(self._ring_container)
        rc_lay.setContentsMargins(0, 0, 0, 0)
        rc_lay.addStretch()
        rc_lay.addLayout(ring_row)
        rc_lay.addStretch()

        # ─────────────────────────────────────────────────────
        # 样式 B：大字倒计时
        # ─────────────────────────────────────────────────────
        self._big_time_lbl = QLabel("--:--")
        self._big_time_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._big_time_lbl.setStyleSheet(
            "color:white; font-weight:200; background:transparent;"
        )

        self._big_container = QWidget()
        self._big_container.setStyleSheet("background:transparent;")
        big_lay = QVBoxLayout(self._big_container)
        big_lay.setContentsMargins(0, 0, 0, 0)
        big_lay.setSpacing(0)
        big_lay.addStretch()
        big_lay.addWidget(self._big_time_lbl)
        big_lay.addStretch()

        # ── 内容切换区 ────────────────────────────────────────
        self._stack = QStackedWidget()
        self._stack.setStyleSheet("background:transparent;")
        self._stack.addWidget(self._ring_container)   # index 0 → ring
        self._stack.addWidget(self._big_container)    # index 1 → big
        root.addWidget(self._stack, 1)

        # ── 进度条（大字样式专属，放在 stack 正下方）──────────
        self._progress_bar = ProgressBar()
        self._progress_bar.setRange(0, 1000)
        self._progress_bar.setValue(0)
        self._progress_bar.setFixedHeight(6)
        root.addWidget(self._progress_bar)

        # ── 状态标签 ──────────────────────────────────────────
        self._status_lbl = QLabel("")
        self._status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_lbl.setStyleSheet(
            "color:rgba(255,255,255,100); font-size:12px; background:transparent;"
        )
        root.addWidget(self._status_lbl)

        # ── 按钮行 ────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        self._toggle_btn = TransparentToolButton(FIF.PLAY)
        self._toggle_btn.setFixedSize(40, 40)
        self._toggle_btn.setToolTip("开始 / 暂停")
        self._toggle_btn.setStyleSheet(_BTN_STYLE)
        self._toggle_btn.clicked.connect(self._on_toggle)

        self._reset_btn = TransparentToolButton(FIF.SYNC)
        self._reset_btn.setFixedSize(40, 40)
        self._reset_btn.setToolTip("重置")
        self._reset_btn.setStyleSheet(_BTN_STYLE)
        self._reset_btn.clicked.connect(self._on_reset)

        btn_row.addStretch()
        btn_row.addWidget(self._toggle_btn)
        btn_row.addWidget(self._reset_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        # ── 空态提示 ──────────────────────────────────────────
        self._empty_lbl = QLabel("尚无计时器\n请先在计时器页中创建")
        self._empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_lbl.setWordWrap(True)
        self._empty_lbl.setStyleSheet(
            "color:rgba(255,255,255,80); font-size:13px; background:transparent;"
        )
        root.addWidget(self._empty_lbl)

        # ── 初始绑定 ──────────────────────────────────────────
        self._reconnect_item(config.props.get("timer_id"))

    # ------------------------------------------------------------------ #
    # 显示样式切换
    # ------------------------------------------------------------------ #

    def _apply_style(self) -> None:
        style = self.config.props.get("style", "ring")
        if style == "big":
            self._stack.setCurrentIndex(1)
            fs = int(self.config.props.get("font_size", 72))
            font = QFont()
            font.setPointSize(fs)
            font.setWeight(QFont.Weight(200))
            self._big_time_lbl.setFont(font)
            show_bar = self.config.props.get("show_progress_bar", True)
            self._progress_bar.setVisible(show_bar)
        else:
            self._stack.setCurrentIndex(0)
            self._progress_bar.setVisible(False)

    # ------------------------------------------------------------------ #
    # 切换计时器（前/后按钮）
    # ------------------------------------------------------------------ #

    def _switch_prev(self) -> None:
        self._switch_by_offset(-1)

    def _switch_next(self) -> None:
        self._switch_by_offset(1)

    def _switch_by_offset(self, offset: int) -> None:
        timers = _load_timer_data()
        if not timers:
            return
        cur_id = self.config.props.get("timer_id", "")
        ids = [t.get("id", "") for t in timers]
        try:
            cur_idx = ids.index(cur_id)
        except ValueError:
            cur_idx = 0
        new_id = ids[(cur_idx + offset) % len(ids)]
        self.config.props["timer_id"] = new_id
        self._reconnect_item(new_id)
        self.refresh()
        # 通知画布保存布局
        try:
            p = self.parent()
            while p and not hasattr(p, "_save_layout"):
                p = p.parent() if callable(getattr(p, "parent", None)) else None
            if p:
                p._save_layout()
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # 私有辅助
    # ------------------------------------------------------------------ #

    def _reconnect_item(self, timer_id: Optional[str]) -> None:
        """断开旧 item，绑定新 item；若自有 tick 连接也一并重置。"""
        # 停旧 tick
        if self._tick_timer is not None:
            self._tick_timer.stop()
            self._tick_timer.deleteLater()
            self._tick_timer = None
        if self._owns_item and self._clock_svc is not None:
            try:
                self._clock_svc.tick.disconnect(self._on_own_tick)
            except Exception:
                pass

        if self._item is not None:
            try:
                self._item.updated.disconnect(self._on_item_updated)
            except Exception:
                pass
            self._item = None
        self._owns_item = False

        if not timer_id:
            return

        item, fresh = _get_or_create_item(timer_id)
        if item is None:
            return

        self._item     = item
        self._owns_item = fresh
        item.updated.connect(self._on_item_updated)

        if fresh:
            self._start_own_tick()

    def _start_own_tick(self) -> None:
        """为自行创建的 item 启动本地 tick（避免双重 tick）。"""
        if self._clock_svc is not None:
            try:
                self._clock_svc.tick.connect(self._on_own_tick)
                return
            except Exception:
                pass
        # fallback: 独立 QTimer
        t = _QTimer(self)
        t.setInterval(TIMER_TICK_MS)
        t.timeout.connect(self._on_own_tick)
        t.start()
        self._tick_timer = t

    def _on_own_tick(self, delta_ms: int = 10) -> None:
        if self._item and self._owns_item:
            self._item.tick(delta_ms)

    def _on_item_updated(self) -> None:
        self._sync_from_item()

    def _sync_fields(self, time_str: str, progress: int) -> None:
        self._ring.setValue(progress)
        self._time_ring_lbl.setText(time_str)
        self._big_time_lbl.setText(time_str)
        self._progress_bar.setValue(progress)

    def _sync_from_item(self) -> None:
        item = self._item
        if item is None:
            return

        progress = int(item.progress * 1000)
        time_str = format_duration(item.remaining)
        self._sync_fields(time_str, progress)
        self._label_lbl.setText(item.label)

        if item.done:
            self._status_lbl.setText("已结束")
            self._status_lbl.setStyleSheet(
                "color:#e55; font-size:12px; background:transparent;"
            )
            self._toggle_btn.setEnabled(False)
            self._toggle_btn.setIcon(FIF.PLAY)
        elif item.running:
            self._status_lbl.setText("▶ 运行中")
            self._status_lbl.setStyleSheet(
                "color:#5c5; font-size:12px; background:transparent;"
            )
            self._toggle_btn.setEnabled(True)
            self._toggle_btn.setIcon(FIF.PAUSE)
        else:
            self._status_lbl.setText("⏸ 已暂停")
            self._status_lbl.setStyleSheet(
                "color:rgba(255,255,255,100); font-size:12px; background:transparent;"
            )
            self._toggle_btn.setEnabled(True)
            self._toggle_btn.setIcon(FIF.PLAY)

    def _show_timer_only(self, timers: list[dict]) -> None:
        """无实时引用时从 JSON 只读展示。"""
        timer_id = self.config.props.get("timer_id")
        if not timers:
            self._stack.hide()
            self._progress_bar.hide()
            self._label_lbl.hide()
            self._status_lbl.hide()
            self._toggle_btn.hide()
            self._reset_btn.hide()
            self._prev_btn.hide()
            self._next_btn.hide()
            self._empty_lbl.show()
            return

        data = next((t for t in timers if t.get("id") == timer_id), None)
        if data is None:
            data = timers[0]
            self.config.props["timer_id"] = data.get("id", "")

        self._empty_lbl.hide()
        for w in (self._stack, self._label_lbl, self._status_lbl,
                  self._toggle_btn, self._reset_btn,
                  self._prev_btn, self._next_btn):
            w.show()

        total     = data.get("total_ms", 1) or 1
        remaining = data.get("remaining", total)
        progress  = max(0, min(1000, int((1 - remaining / total) * 1000)))
        self._sync_fields(format_duration(remaining), progress)
        self._label_lbl.setText(data.get("label", "计时器"))
        self._status_lbl.setText("（请打开计时器页 以启用控制）")
        self._status_lbl.setStyleSheet(
            "color:rgba(255,255,255,60); font-size:11px; background:transparent;"
        )
        self._toggle_btn.setEnabled(False)
        self._reset_btn.setEnabled(False)

    # ------------------------------------------------------------------ #
    # 按钮回调
    # ------------------------------------------------------------------ #

    def _on_toggle(self) -> None:
        if self._item is None:
            self._reconnect_item(self.config.props.get("timer_id"))
        if self._item is None:
            return
        if self._item.running:
            self._item.pause()
        elif not self._item.done:
            self._item.start()

    def _on_reset(self) -> None:
        if self._item is None:
            self._reconnect_item(self.config.props.get("timer_id"))
        if self._item is None:
            return
        self._item.reset()
        self._toggle_btn.setEnabled(True)

    # ------------------------------------------------------------------ #
    # WidgetBase 接口
    # ------------------------------------------------------------------ #

    def refresh(self) -> None:
        self._apply_style()
        if self._item is not None:
            self._empty_lbl.hide()
            for w in (self._stack, self._label_lbl, self._status_lbl,
                      self._toggle_btn, self._reset_btn,
                      self._prev_btn, self._next_btn):
                w.show()
            self._toggle_btn.setEnabled(True)
            self._reset_btn.setEnabled(True)
            self._sync_from_item()
        else:
            # 尝试延迟绑定
            timer_id = self.config.props.get("timer_id")
            if timer_id:
                self._reconnect_item(timer_id)
            if self._item is not None:
                self._empty_lbl.hide()
                for w in (self._stack, self._label_lbl, self._status_lbl,
                          self._toggle_btn, self._reset_btn,
                          self._prev_btn, self._next_btn):
                    w.show()
                self._toggle_btn.setEnabled(True)
                self._reset_btn.setEnabled(True)
                self._sync_from_item()
            else:
                self._show_timer_only(_load_timer_data())

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

    def closeEvent(self, event) -> None:  # noqa: N802
        """组件销毁时释放自建的 tick 连接。"""
        if self._tick_timer is not None:
            self._tick_timer.stop()
            self._tick_timer.deleteLater()
            self._tick_timer = None
        if self._owns_item and self._clock_svc is not None:
            try:
                self._clock_svc.tick.disconnect(self._on_own_tick)
            except Exception:
                pass
        super().closeEvent(event)

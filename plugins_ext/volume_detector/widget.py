"""音量检测小组件

实时监测麦克风（或系统默认输入设备）的音量，
超出用户设置的 dB 阈值时：
  - 显示颜色由绿变红
  - 可选：发送系统通知
  - 可选：触发自动化规则（触发器 ID = volume_detector.threshold_exceeded）
"""
from __future__ import annotations

import time
from typing import Any

from PySide6.QtCore import Qt, Signal, QObject, QTimer
from PySide6.QtGui import QPainter, QColor, QLinearGradient, QBrush, QPen
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QWidget,
    QFormLayout, QSizePolicy,
)
from qfluentwidgets import (
    SpinBox, CheckBox, StrongBodyLabel, CaptionLabel, BodyLabel,
)

from app.widgets.base_widget import WidgetBase, WidgetConfig

# ──────────────────────────────────────────────────────────────────── #
# 默认属性
# ──────────────────────────────────────────────────────────────────── #

_DEFAULTS = {
    "threshold_db":        -20,    # 触发阈值（dBFS）
    "notify_enabled":      True,   # 超出阈值时发送通知
    "trigger_enabled":     True,   # 超出阈值时触发自动化
    "retrigger_interval":  5,      # 重新触发最小间隔（秒）
    "show_peak":           True,   # 显示峰值保持
    "always_on":           True,   # 常驻后台（关闭全屏后继续检测）
}

_TRIGGER_ID = "volume_detector.threshold_exceeded"


# ──────────────────────────────────────────────────────────────────── #
# Qt 信号桥（线程安全通信）
# ──────────────────────────────────────────────────────────────────── #

class _AudioSignals(QObject):
    levelChanged = Signal(float)   # 当前 dBFS 值（实时）
    errorOccurred = Signal(str)    # 错误描述


# ──────────────────────────────────────────────────────────────────── #
# 音频监测器（在 sounddevice 回调中运行，非 Qt 线程）
# ──────────────────────────────────────────────────────────────────── #

class _AudioMonitor:
    """管理 sounddevice 输入流，通过信号将音量推送到主线程。"""

    def __init__(self, signals: _AudioSignals):
        self._signals = signals
        self._stream = None
        self._running = False

    def start(self) -> None:
        if self._running:
            return
        try:
            import sounddevice as sd
            import numpy as np

            self._np = np

            def _cb(indata, frames, time, status):  # noqa: N803
                if status:
                    pass  # 忽略溢出等警告
                rms = float(np.sqrt(np.mean(indata ** 2)))
                db = 20.0 * np.log10(max(rms, 1e-10))
                db = max(-80.0, min(0.0, db))
                self._signals.levelChanged.emit(db)

            self._stream = sd.InputStream(
                channels=1,
                samplerate=16000,
                blocksize=1600,   # 每次回调约 100ms 数据
                callback=_cb,
            )
            self._stream.start()
            self._running = True
        except Exception as exc:
            self._signals.errorOccurred.emit(str(exc))

    def stop(self) -> None:
        self._running = False
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None


# ──────────────────────────────────────────────────────────────────── #
# 音量条（自定义绘制）
# ──────────────────────────────────────────────────────────────────── #

class _VolumeBar(QWidget):
    """水平音量条，带阈值刻度线和峰值保持标记。

    dB 范围：-80 → 0
    """

    _DB_MIN = -80.0
    _DB_MAX = 0.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self._level_db: float = -80.0
        self._peak_db:  float = -80.0
        self._threshold_db: float = -20.0
        self._exceeded: bool = False
        self.setMinimumHeight(18)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_level(self, db: float, peak_db: float, exceeded: bool) -> None:
        self._level_db = db
        self._peak_db  = peak_db
        self._exceeded = exceeded
        self.update()

    def set_threshold(self, db: float) -> None:
        self._threshold_db = db
        self.update()

    def _db_to_x(self, db: float) -> int:
        ratio = (db - self._DB_MIN) / (self._DB_MAX - self._DB_MIN)
        return int(ratio * self.width())

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        r = 4   # 圆角

        # ── 背景 ──
        painter.setBrush(QColor(30, 30, 30, 180))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(0, 0, w, h, r, r)

        # ── 填充条 ──
        fill_w = max(0, self._db_to_x(self._level_db))
        if fill_w > 0:
            grad = QLinearGradient(0, 0, w, 0)
            if self._exceeded:
                grad.setColorAt(0.0, QColor("#e74c3c"))
                grad.setColorAt(1.0, QColor("#c0392b"))
            else:
                grad.setColorAt(0.0, QColor("#27ae60"))
                grad.setColorAt(0.6, QColor("#f1c40f"))
                grad.setColorAt(0.85, QColor("#e67e22"))
                grad.setColorAt(1.0, QColor("#e74c3c"))
            painter.setBrush(QBrush(grad))
            painter.drawRoundedRect(0, 0, fill_w, h, r, r)

        # ── 峰值标记 ──
        if self._peak_db > self._DB_MIN:
            peak_x = self._db_to_x(self._peak_db)
            painter.setPen(QPen(QColor(255, 255, 255, 200), 2))
            painter.drawLine(peak_x, 2, peak_x, h - 2)

        # ── 阈值线 ──
        thr_x = self._db_to_x(self._threshold_db)
        painter.setPen(QPen(QColor("#e74c3c"), 2, Qt.PenStyle.DashLine))
        painter.drawLine(thr_x, 0, thr_x, h)

        painter.end()


# ──────────────────────────────────────────────────────────────────── #
# 音量检测编辑面板
# ──────────────────────────────────────────────────────────────────── #

class _EditWidget(QWidget):
    def __init__(self, props: dict, parent=None):
        super().__init__(parent)
        layout = QFormLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(8)

        # 阈值
        self._threshold = SpinBox()
        self._threshold.setRange(-80, 0)
        self._threshold.setSuffix(" dB")
        self._threshold.setValue(props.get("threshold_db", _DEFAULTS["threshold_db"]))
        layout.addRow(BodyLabel("触发阈值："), self._threshold)

        # 重触发间隔
        self._interval = SpinBox()
        self._interval.setRange(1, 3600)
        self._interval.setSuffix(" 秒")
        self._interval.setValue(props.get("retrigger_interval", _DEFAULTS["retrigger_interval"]))
        layout.addRow(BodyLabel("重触发间隔："), self._interval)

        # 复选框
        self._notify = CheckBox("超出阈值时发送通知")
        self._notify.setChecked(props.get("notify_enabled", _DEFAULTS["notify_enabled"]))
        layout.addRow("", self._notify)

        self._trigger = CheckBox("超出阈值时触发自动化")
        self._trigger.setChecked(props.get("trigger_enabled", _DEFAULTS["trigger_enabled"]))
        layout.addRow("", self._trigger)

        self._peak = CheckBox("显示峰值保持")
        self._peak.setChecked(props.get("show_peak", _DEFAULTS["show_peak"]))
        layout.addRow("", self._peak)
        self._always_on = CheckBox("常驻后台（关闭全屏时也继续检测）")
        self._always_on.setChecked(props.get("always_on", _DEFAULTS["always_on"]))
        layout.addRow("", self._always_on)
        # 触发器 ID 提示
        hint = CaptionLabel(f"自动化触发器 ID：{_TRIGGER_ID}")
        hint.setStyleSheet("color: #888;")
        hint.setWordWrap(True)
        layout.addRow("", hint)

    def collect_props(self) -> dict:
        return {
            "threshold_db":       self._threshold.value(),
            "retrigger_interval": self._interval.value(),
            "notify_enabled":     self._notify.isChecked(),
            "trigger_enabled":    self._trigger.isChecked(),
            "show_peak":          self._peak.isChecked(),
            "always_on":          self._always_on.isChecked(),
        }


# ──────────────────────────────────────────────────────────────────── #
# 主小组件
# ──────────────────────────────────────────────────────────────────── #

class VolumeDetectorWidget(WidgetBase):
    WIDGET_TYPE = "volume_detector"
    WIDGET_NAME = "音量检测"
    DELETABLE   = True
    DEFAULT_W   = 3
    DEFAULT_H   = 2
    MIN_W       = 2
    MIN_H       = 2

    def __init__(self, config: WidgetConfig, services: dict[str, Any], parent=None):
        super().__init__(config, services, parent)

        # ── 状态 ──────────────────────────────────────────────────
        self._current_db:   float = -80.0
        self._peak_db:      float = -80.0
        self._exceeded:     bool  = False
        self._last_trigger: float = 0.0   # monotonic time of last trigger
        self._error_msg:    str   = ""

        # ── 峰值衰减定时器 ──────────────────────────────────────── #
        self._peak_decay_timer = QTimer(self)
        self._peak_decay_timer.setInterval(100)
        self._peak_decay_timer.timeout.connect(self._decay_peak)
        self._peak_decay_timer.start()

        # ── 音频信号桥 ──────────────────────────────────────────── #
        self._signals = _AudioSignals()
        self._signals.levelChanged.connect(self._on_level)
        self._signals.errorOccurred.connect(self._on_error)

        # ── 音频监测器 ──────────────────────────────────────────── #
        self._monitor = _AudioMonitor(self._signals)
        self._monitor.start()

        # 注册到插件状态，卸载时可统一停止
        try:
            from . import _plugin_state
            _plugin_state.monitor_instances.append(self._monitor)
        except Exception:
            pass

        # widget 被销毁时自动停止监测（deleteLater 场景）
        self.destroyed.connect(self._on_destroyed)

        # 全屏事件订阅相关状态
        self._active_fullscreen_zones: set = set()
        self._event_subs_registered = False
        # 根据当前属性决定监控模式
        self._apply_monitoring_mode()

        # ── UI ──────────────────────────────────────────────────── #
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(4)

        # 顶行：标题 + dB 值
        top_row = QHBoxLayout()
        title_lbl = StrongBodyLabel("🎤 音量检测")
        title_lbl.setStyleSheet("color: white; font-size: 11px;")
        self._db_lbl = BodyLabel("-80 dB")
        self._db_lbl.setStyleSheet("color: white; font-size: 11px;")
        self._db_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        top_row.addWidget(title_lbl)
        top_row.addStretch()
        top_row.addWidget(self._db_lbl)
        root.addLayout(top_row)

        # 音量条
        self._bar = _VolumeBar()
        root.addWidget(self._bar)

        # 状态标签
        self._status_lbl = CaptionLabel("等待音频输入…")
        self._status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_lbl.setStyleSheet("color: #aaa; font-size: 10px;")
        root.addWidget(self._status_lbl)

        root.addStretch()

        # 初始化阈值线
        self._bar.set_threshold(self._props.get("threshold_db", _DEFAULTS["threshold_db"]))

    # ── 属性辅助 ────────────────────────────────────────────────── #

    @property
    def _props(self) -> dict:
        return self.config.props

    def _get(self, key: str) -> Any:
        return self._props.get(key, _DEFAULTS.get(key))

    # ── 音频回调（在主线程中执行，由 Signal 安全转发） ──────────── #

    def _on_level(self, db: float) -> None:
        threshold = self._get("threshold_db")
        was_exceeded = self._exceeded
        self._exceeded = db > threshold
        self._current_db = db
        if db > self._peak_db:
            self._peak_db = db

        # ── 上升沿触发 ─────────────────────────────────────────── #
        if self._exceeded and not was_exceeded:
            interval = self._get("retrigger_interval")
            now = time.monotonic()
            if now - self._last_trigger >= interval:
                self._last_trigger = now
                self._fire_exceeded(db)

        # ── 更新 UI ────────────────────────────────────────────── #
        self._update_ui()

    def _on_error(self, msg: str) -> None:
        self._error_msg = msg
        self._status_lbl.setText(f"⚠ {msg}")
        self._status_lbl.setStyleSheet("color: #e74c3c; font-size: 10px;")

    # ── 阈值触发逻辑 ───────────────────────────────────────────── #

    def _fire_exceeded(self, db: float) -> None:
        threshold = self._get("threshold_db")

        # 通知
        if self._get("notify_enabled"):
            notif = self.services.get("notification_service")
            if notif:
                notif.show(
                    "音量超出阈值",
                    f"当前音量 {db:.1f} dB，阈值 {threshold} dB",
                )

        # 自动化触发器
        if self._get("trigger_enabled"):
            try:
                from . import _plugin_state
                if _plugin_state.api:
                    _plugin_state.api.fire_trigger(
                        _TRIGGER_ID,
                        volume_db=db,
                        threshold_db=threshold,
                    )
            except Exception:
                pass

    # ── UI 刷新 ──────────────────────────────────────────────────── #

    def _update_ui(self) -> None:
        if self._error_msg:
            return
        db = self._current_db
        threshold = self._get("threshold_db")
        show_peak = self._get("show_peak")

        # 更新音量条
        self._bar.set_level(
            db,
            self._peak_db if show_peak else -80.0,
            self._exceeded,
        )
        self._bar.set_threshold(threshold)

        # dB 标签
        self._db_lbl.setText(f"{db:.1f} dB")
        if self._exceeded:
            self._db_lbl.setStyleSheet("color: #e74c3c; font-size: 11px; font-weight: bold;")
        else:
            self._db_lbl.setStyleSheet("color: white; font-size: 11px;")

        # 状态标签
        if self._exceeded:
            self._status_lbl.setText(f"⚠ 超出阈值（{threshold} dB）")
            self._status_lbl.setStyleSheet("color: #e74c3c; font-size: 10px; font-weight: bold;")
        else:
            self._status_lbl.setText(f"正常  阈值：{threshold} dB")
            self._status_lbl.setStyleSheet("color: #aaa; font-size: 10px;")

    def _decay_peak(self) -> None:
        """每 100ms 让峰值缓慢衰减"""
        if self._peak_db > self._current_db:
            self._peak_db -= 1.5   # 1.5 dB / 100ms 衰减
            if self._peak_db < self._current_db:
                self._peak_db = self._current_db

    def _on_destroyed(self) -> None:
        """widget 被销毁（deleteLater）时停止音频流"""
        self._unsubscribe_fullscreen_events()
        self._monitor.stop()
        self._peak_decay_timer.stop()
        try:
            from . import _plugin_state
            if self._monitor in _plugin_state.monitor_instances:
                _plugin_state.monitor_instances.remove(self._monitor)
        except Exception:
            pass

    # ── 全屏事件订阅 ──────────────────────────────────────────────── #

    def _apply_monitoring_mode(self) -> None:
        """根据 always_on 属性应用监控模式"""
        always_on = self._get("always_on")
        if always_on:
            # 常驻模式：取消全屏事件订阅，确保监测器运行
            self._unsubscribe_fullscreen_events()
            if not self._monitor._running:
                self._monitor.start()
        else:
            # 全屏联动模式：订阅全屏事件
            self._subscribe_fullscreen_events()
            if self._active_fullscreen_zones:
                # 已知有活跃全屏窗口，确保监测器运行
                if not self._monitor._running:
                    self._monitor.start()
            # 若当前无已知活跃全屏，但监测器正在运行（例如刚从常驻模式切换），
            # 保持运行——等待后续 FULLSCREEN_CLOSED 事件自然停止；
            # 若监测器本就未运行，则维持停止状态，由 FULLSCREEN_OPENED 事件启动

    def _subscribe_fullscreen_events(self) -> None:
        if self._event_subs_registered:
            return
        try:
            from app.events import EventBus, EventType
            EventBus.subscribe(EventType.FULLSCREEN_OPENED, self._on_fullscreen_opened)
            EventBus.subscribe(EventType.FULLSCREEN_CLOSED, self._on_fullscreen_closed)
            self._event_subs_registered = True
        except Exception:
            pass

    def _unsubscribe_fullscreen_events(self) -> None:
        if not self._event_subs_registered:
            return
        try:
            from app.events import EventBus, EventType
            EventBus.unsubscribe(EventType.FULLSCREEN_OPENED, self._on_fullscreen_opened)
            EventBus.unsubscribe(EventType.FULLSCREEN_CLOSED, self._on_fullscreen_closed)
            self._event_subs_registered = False
        except Exception:
            pass

    def _on_fullscreen_opened(self, zone_id: str = "", **_) -> None:
        if zone_id:
            self._active_fullscreen_zones.add(zone_id)
        if not self._monitor._running:
            self._monitor.start()

    def _on_fullscreen_closed(self, zone_id: str = "", **_) -> None:
        self._active_fullscreen_zones.discard(zone_id)
        if not self._active_fullscreen_zones:
            self._monitor.stop()

    # ── WidgetBase 接口 ──────────────────────────────────────────── #

    def refresh(self) -> None:
        """由画布定时调用，直接返回（音量更新由 sounddevice 回调驱动）"""
        pass

    def get_edit_widget(self) -> QWidget:
        return _EditWidget(self._props)

    def apply_props(self, props: dict) -> None:
        self.config.props.update(props)
        # 立即将新阈值应用到音量条
        self._bar.set_threshold(props.get("threshold_db", _DEFAULTS["threshold_db"]))
        self._update_ui()        # 应用监控模式
        self._apply_monitoring_mode()
    def showEvent(self, event) -> None:  # noqa: N802
        # 仅在监测条件满足时重启：常驻模式，或联动模式下已有活跃全屏窗口
        if not self._monitor._running:
            if self._get("always_on") or self._active_fullscreen_zones:
                self._monitor.start()
        super().showEvent(event)

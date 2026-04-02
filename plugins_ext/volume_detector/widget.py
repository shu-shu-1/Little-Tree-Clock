"""音量检测小组件。

实时监测麦克风（或系统默认输入设备）的音量，
超出用户设置的 dB 阈值时：
  - 显示颜色由常态色切换为告警色
  - 可选：发送系统通知
  - 可选：触发自动化规则（触发器 ID = volume_detector.threshold_exceeded）
"""
from __future__ import annotations

import importlib
import json
from pathlib import Path
import re
import time
import uuid
from datetime import datetime
from typing import Any, Optional

from PySide6.QtCore import QObject, QTimer, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CheckBox,
    ColorPickerButton,
    ComboBox,
    EditableComboBox,
    FluentIcon as FIF,
    PushButton,
    SpinBox,
    StrongBodyLabel,
    Theme,
    ToolButton,
)

from app.utils.fs import mkdir_with_uac, write_text_with_uac
from app.utils.logger import logger
from app.widgets.base_widget import WidgetBase, WidgetConfig
from app.widgets.fluent_font_picker import FluentFontPicker


_DEFAULTS = {
    "threshold_db": -20,
    "calibration_offset_db": 0,
    "input_device": "",
    "notify_enabled": True,
    "trigger_enabled": True,
    "retrigger_interval": 5,
    "show_peak": True,
    "always_on": True,
    "show_device_name": True,
    "font_family": "",
    "title_font_size": 12,
    "value_font_size": 12,
    "status_font_size": 10,
    "bar_height": 18,
    "normal_color": "#27AE60",
    "warning_color": "#E74C3C",
}

_TRIGGER_ID = "volume_detector.threshold_exceeded"
_TEXT_PRIMARY = "color: rgba(255,255,255,235); background: transparent;"
_TEXT_SECONDARY = "color: rgba(255,255,255,170); background: transparent;"
_TEXT_MUTED = "color: rgba(255,255,255,130); background: transparent;"


def _safe_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _font_size(props: dict, key: str, default: int) -> int:
    return max(8, min(144, _safe_int(props.get(key, default), default)))


def _remember_default_font(label) -> None:
    if getattr(label, "_ltc_default_font", None) is None:
        label._ltc_default_font = QFont(label.font())


def _apply_font(label, props: dict, size_key: str, default_size: int) -> None:
    base_font = getattr(label, "_ltc_default_font", None)
    font = QFont(base_font) if isinstance(base_font, QFont) else QFont(label.font())
    family = str(props.get("font_family", "") or "").strip()
    if family:
        font.setFamilies([family])
    font.setPointSize(_font_size(props, size_key, default_size))
    label.setFont(font)


def _to_qcolor(value: Any, fallback: str) -> QColor:
    color = QColor(str(value or fallback))
    return color if color.isValid() else QColor(fallback)


def _coerce_input_device(value: Any) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_slug(value: Any, fallback: str = "volume_report") -> str:
    text = str(value or "").strip()
    if not text:
        return fallback
    text = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", text, flags=re.UNICODE)
    text = text.strip("_-")
    return text or fallback


def _list_input_devices() -> list[dict[str, Any]]:
    try:
        sd = importlib.import_module("sounddevice")
    except Exception:
        return []

    default_input = None
    try:
        default_device = sd.default.device
        if isinstance(default_device, (list, tuple)) and default_device:
            default_input = default_device[0]
        elif isinstance(default_device, int):
            default_input = default_device
    except Exception:
        default_input = None

    try:
        host_apis = list(sd.query_hostapis())
    except Exception:
        host_apis = []

    result: list[dict[str, Any]] = []
    for index, device in enumerate(sd.query_devices()):
        try:
            if int(device.get("max_input_channels") or 0) < 1:
                continue
        except Exception:
            continue

        name = str(device.get("name") or f"输入设备 {index}")
        hostapi_name = ""
        try:
            hostapi_index = int(device.get("hostapi", -1))
            if 0 <= hostapi_index < len(host_apis):
                hostapi_name = str(host_apis[hostapi_index].get("name") or "")
        except Exception:
            hostapi_name = ""

        label = f"{name} ({hostapi_name})" if hostapi_name else name
        result.append({
            "index": index,
            "name": name,
            "label": label,
            "is_default": index == default_input,
        })
    return result


class _AudioSignals(QObject):
    levelChanged = Signal(float)
    errorOccurred = Signal(str)


class _AudioMonitor:
    """管理 sounddevice 输入流，通过信号将音量推送到主线程。"""

    def __init__(self, signals: _AudioSignals):
        self._signals = signals
        self._stream = None
        self._running = False
        self._device_name = "系统默认麦克风"

    @property
    def device_name(self) -> str:
        return self._device_name or "系统默认麦克风"

    def start(self, device: Optional[int] = None) -> None:
        if self._running:
            return

        candidates = [device]
        if device is not None:
            candidates.append(None)

        last_error: Exception | None = None
        for candidate in candidates:
            try:
                self._start_with_device(candidate)
                return
            except Exception as exc:
                last_error = exc
                self.stop()

        if last_error is not None:
            self._signals.errorOccurred.emit(str(last_error))

    def _start_with_device(self, device: Optional[int]) -> None:
        np = importlib.import_module("numpy")
        sd = importlib.import_module("sounddevice")

        query_kwargs: dict[str, Any] = {"kind": "input"}
        if device is not None:
            query_kwargs["device"] = device
        info = sd.query_devices(**query_kwargs)

        max_input_channels = int(info.get("max_input_channels") or 0)
        if max_input_channels < 1:
            raise RuntimeError("所选麦克风没有可用输入通道")

        samplerate = int(info.get("default_samplerate") or 16000)
        samplerate = max(8000, samplerate)
        blocksize = max(256, samplerate // 10)
        self._device_name = str(info.get("name") or "系统默认麦克风")

        def _cb(indata, frames, time_info, status):  # noqa: N803
            del frames, time_info, status
            rms = float(np.sqrt(np.mean(indata ** 2)))
            db = 20.0 * np.log10(max(rms, 1e-10))
            db = max(-80.0, min(0.0, db))
            self._signals.levelChanged.emit(db)

        self._stream = sd.InputStream(
            device=device,
            channels=1,
            samplerate=samplerate,
            blocksize=blocksize,
            callback=_cb,
        )
        self._stream.start()
        self._running = True

    def restart(self, device: Optional[int] = None) -> None:
        self.stop()
        self.start(device)

    def stop(self) -> None:
        self._running = False
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None


class _VolumeBar(QWidget):
    """水平音量条，带阈值刻度线和峰值保持标记。"""

    _DB_MIN = -80.0
    _DB_MAX = 0.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self._level_db: float = -80.0
        self._peak_db: float = -80.0
        self._threshold_db: float = -20.0
        self._exceeded: bool = False
        self._normal_color = QColor(_DEFAULTS["normal_color"])
        self._warning_color = QColor(_DEFAULTS["warning_color"])
        self.setFixedHeight(_DEFAULTS["bar_height"])
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_level(self, db: float, peak_db: float, exceeded: bool) -> None:
        self._level_db = db
        self._peak_db = peak_db
        self._exceeded = exceeded
        self.update()

    def set_threshold(self, db: float) -> None:
        self._threshold_db = db
        self.update()

    def set_colors(self, normal_color: Any, warning_color: Any) -> None:
        self._normal_color = _to_qcolor(normal_color, _DEFAULTS["normal_color"])
        self._warning_color = _to_qcolor(warning_color, _DEFAULTS["warning_color"])
        self.update()

    def set_bar_height(self, height: int) -> None:
        self.setFixedHeight(max(8, min(40, int(height))))
        self.update()

    def _db_to_x(self, db: float) -> int:
        ratio = (db - self._DB_MIN) / (self._DB_MAX - self._DB_MIN)
        return int(max(0.0, min(1.0, ratio)) * self.width())

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width, height = self.width(), self.height()
        radius = 4

        painter.setBrush(QColor(255, 255, 255, 26))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(0, 0, width, height, radius, radius)

        fill_width = max(0, self._db_to_x(self._level_db))
        if fill_width > 0:
            gradient = QLinearGradient(0, 0, width, 0)
            if self._exceeded:
                gradient.setColorAt(0.0, self._warning_color.lighter(120))
                gradient.setColorAt(1.0, self._warning_color.darker(120))
            else:
                gradient.setColorAt(0.0, self._normal_color.lighter(110))
                gradient.setColorAt(0.72, self._normal_color)
                gradient.setColorAt(1.0, self._warning_color.lighter(105))
            painter.setBrush(QBrush(gradient))
            painter.drawRoundedRect(0, 0, fill_width, height, radius, radius)

        if self._peak_db > self._DB_MIN:
            peak_x = self._db_to_x(self._peak_db)
            painter.setPen(QPen(QColor(255, 255, 255, 210), 2))
            painter.drawLine(peak_x, 2, peak_x, height - 2)

        threshold_x = self._db_to_x(self._threshold_db)
        painter.setPen(QPen(self._warning_color, 2, Qt.PenStyle.DashLine))
        painter.drawLine(threshold_x, 0, threshold_x, height)
        painter.end()


class _EditWidget(QWidget):
    def __init__(self, widget, parent=None):
        super().__init__(parent)
        self._widget = widget
        props = dict(widget.config.props)

        layout = QFormLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(8)

        device_row = QWidget(self)
        device_layout = QHBoxLayout(device_row)
        device_layout.setContentsMargins(0, 0, 0, 0)
        device_layout.setSpacing(6)
        self._device_combo = ComboBox()
        self._device_refresh_btn = ToolButton(FIF.SYNC)
        self._device_refresh_btn.setToolTip("刷新麦克风列表")
        self._device_refresh_btn.clicked.connect(self._reload_devices)
        device_layout.addWidget(self._device_combo, 1)
        device_layout.addWidget(self._device_refresh_btn)
        layout.addRow(BodyLabel("麦克风："), device_row)

        self._runtime_hint = CaptionLabel("")
        self._runtime_hint.setWordWrap(True)
        self._runtime_hint.setStyleSheet(_TEXT_MUTED)
        layout.addRow("", self._runtime_hint)

        self._threshold = SpinBox()
        self._threshold.setRange(-80, 0)
        self._threshold.setSuffix(" dB")
        self._threshold.setValue(_safe_int(props.get("threshold_db", _DEFAULTS["threshold_db"]), _DEFAULTS["threshold_db"]))
        layout.addRow(BodyLabel("触发阈值："), self._threshold)

        self._calibration = SpinBox()
        self._calibration.setRange(-40, 40)
        self._calibration.setSuffix(" dB")
        self._calibration.setValue(_safe_int(props.get("calibration_offset_db", _DEFAULTS["calibration_offset_db"]), _DEFAULTS["calibration_offset_db"]))
        layout.addRow(BodyLabel("校准偏移："), self._calibration)

        calibration_row = QWidget(self)
        calibration_layout = QHBoxLayout(calibration_row)
        calibration_layout.setContentsMargins(0, 0, 0, 0)
        calibration_layout.setSpacing(6)
        self._calibrate_zero_btn = PushButton(FIF.SYNC, "将当前值归零")
        self._calibrate_zero_btn.clicked.connect(self._set_current_as_zero)
        self._reset_calibration_btn = PushButton(FIF.CANCEL_MEDIUM, "重置校准")
        self._reset_calibration_btn.clicked.connect(lambda: self._calibration.setValue(0))
        calibration_layout.addWidget(self._calibrate_zero_btn)
        calibration_layout.addWidget(self._reset_calibration_btn)
        layout.addRow("", calibration_row)

        self._interval = SpinBox()
        self._interval.setRange(1, 3600)
        self._interval.setSuffix(" 秒")
        self._interval.setValue(_safe_int(props.get("retrigger_interval", _DEFAULTS["retrigger_interval"]), _DEFAULTS["retrigger_interval"]))
        layout.addRow(BodyLabel("重触发间隔："), self._interval)

        self._notify = CheckBox("超出阈值时发送通知")
        self._notify.setChecked(bool(props.get("notify_enabled", _DEFAULTS["notify_enabled"])))
        layout.addRow("", self._notify)

        self._trigger = CheckBox("超出阈值时触发自动化")
        self._trigger.setChecked(bool(props.get("trigger_enabled", _DEFAULTS["trigger_enabled"])))
        layout.addRow("", self._trigger)

        self._peak = CheckBox("显示峰值保持")
        self._peak.setChecked(bool(props.get("show_peak", _DEFAULTS["show_peak"])))
        layout.addRow("", self._peak)

        self._always_on = CheckBox("常驻后台（关闭全屏时也继续检测）")
        self._always_on.setChecked(bool(props.get("always_on", _DEFAULTS["always_on"])))
        layout.addRow("", self._always_on)

        self._show_device_name = CheckBox("在组件中显示麦克风名称")
        self._show_device_name.setChecked(bool(props.get("show_device_name", _DEFAULTS["show_device_name"])))
        layout.addRow("", self._show_device_name)

        self._font_picker = FluentFontPicker()
        self._font_picker.setCurrentFontFamily(str(props.get("font_family", _DEFAULTS["font_family"]) or "").strip())
        layout.addRow(BodyLabel("字体："), self._font_picker)

        self._title_font_size = SpinBox()
        self._title_font_size.setRange(8, 144)
        self._title_font_size.setSuffix(" pt")
        self._title_font_size.setValue(_font_size(props, "title_font_size", _DEFAULTS["title_font_size"]))
        layout.addRow(BodyLabel("标题字号："), self._title_font_size)

        self._value_font_size = SpinBox()
        self._value_font_size.setRange(8, 144)
        self._value_font_size.setSuffix(" pt")
        self._value_font_size.setValue(_font_size(props, "value_font_size", _DEFAULTS["value_font_size"]))
        layout.addRow(BodyLabel("数值字号："), self._value_font_size)

        self._status_font_size = SpinBox()
        self._status_font_size.setRange(8, 144)
        self._status_font_size.setSuffix(" pt")
        self._status_font_size.setValue(_font_size(props, "status_font_size", _DEFAULTS["status_font_size"]))
        layout.addRow(BodyLabel("状态字号："), self._status_font_size)

        self._bar_height = SpinBox()
        self._bar_height.setRange(8, 40)
        self._bar_height.setSuffix(" px")
        self._bar_height.setValue(_safe_int(props.get("bar_height", _DEFAULTS["bar_height"]), _DEFAULTS["bar_height"]))
        layout.addRow(BodyLabel("音量条高度："), self._bar_height)

        self._normal_color = ColorPickerButton(_to_qcolor(props.get("normal_color"), _DEFAULTS["normal_color"]), "常态颜色")
        layout.addRow(BodyLabel("常态颜色："), self._normal_color)

        self._warning_color = ColorPickerButton(_to_qcolor(props.get("warning_color"), _DEFAULTS["warning_color"]), "告警颜色")
        layout.addRow(BodyLabel("告警颜色："), self._warning_color)

        hint = CaptionLabel(
            f"自动化触发器 ID：{_TRIGGER_ID}\n"
            "校准偏移会叠加到实时 dB 显示值上；如果麦克风本身偏低，可先观察当前值再手动校准。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(_TEXT_MUTED)
        layout.addRow("", hint)

        self._reload_devices()
        self._runtime_timer = QTimer(self)
        self._runtime_timer.setInterval(250)
        self._runtime_timer.timeout.connect(self._update_runtime_hint)
        self._runtime_timer.start()
        self._update_runtime_hint()

    def _reload_devices(self) -> None:
        current = self._device_combo.currentData()
        if current is None:
            current = self._widget._get("input_device")
        current = _coerce_input_device(current)

        self._device_combo.clear()
        self._device_combo.addItem("系统默认麦克风", userData="")
        for device in _list_input_devices():
            label = device["label"]
            if device.get("is_default"):
                label = f"{label}（默认）"
            self._device_combo.addItem(label, userData=device["index"])

        target_index = 0
        if current is not None:
            target_index = next(
                (i for i in range(self._device_combo.count()) if self._device_combo.itemData(i) == current),
                0,
            )
        self._device_combo.setCurrentIndex(target_index)

    def _set_current_as_zero(self) -> None:
        raw_db = getattr(self._widget, "_raw_db", -80.0)
        self._calibration.setValue(int(round(-raw_db)))

    def _update_runtime_hint(self) -> None:
        raw_db = float(getattr(self._widget, "_raw_db", -80.0))
        current_db = float(getattr(self._widget, "_current_db", -80.0))
        device_name = self._widget.current_device_name()
        error_msg = str(getattr(self._widget, "_error_msg", "") or "")

        lines = [
            f"当前设备：{device_name}",
            f"原始值：{raw_db:.1f} dB · 校准后：{current_db:.1f} dB",
        ]
        if error_msg:
            lines.append(f"当前状态：{error_msg}")
            self._runtime_hint.setStyleSheet("color: #E74C3C; background: transparent;")
        else:
            self._runtime_hint.setStyleSheet(_TEXT_MUTED)
        self._runtime_hint.setText("\n".join(lines))

    def collect_props(self) -> dict:
        device_data = self._device_combo.currentData()
        return {
            "threshold_db": self._threshold.value(),
            "calibration_offset_db": self._calibration.value(),
            "input_device": device_data if device_data not in (None, "") else "",
            "notify_enabled": self._notify.isChecked(),
            "trigger_enabled": self._trigger.isChecked(),
            "retrigger_interval": self._interval.value(),
            "show_peak": self._peak.isChecked(),
            "always_on": self._always_on.isChecked(),
            "show_device_name": self._show_device_name.isChecked(),
            "font_family": self._font_picker.currentFontFamily(),
            "title_font_size": self._title_font_size.value(),
            "value_font_size": self._value_font_size.value(),
            "status_font_size": self._status_font_size.value(),
            "bar_height": self._bar_height.value(),
            "normal_color": self._normal_color.color.name(),
            "warning_color": self._warning_color.color.name(),
        }


class VolumeDetectorWidget(WidgetBase):
    WIDGET_TYPE = "volume_detector"
    WIDGET_NAME = "音量检测"
    DELETABLE = True
    DEFAULT_W = 3
    DEFAULT_H = 2
    MIN_W = 2
    MIN_H = 2

    def __init__(self, config: WidgetConfig, services: dict[str, Any], parent=None):
        super().__init__(config, services, parent)

        self._raw_db: float = -80.0
        self._current_db: float = -80.0
        self._peak_db: float = -80.0
        self._exceeded: bool = False
        self._last_trigger: float = 0.0
        self._error_msg: str = ""

        self._peak_decay_timer = QTimer(self)
        self._peak_decay_timer.setInterval(100)
        self._peak_decay_timer.timeout.connect(self._decay_peak)
        self._peak_decay_timer.start()

        self._signals = _AudioSignals()
        self._signals.levelChanged.connect(self._on_level)
        self._signals.errorOccurred.connect(self._on_error)
        self._monitor = _AudioMonitor(self._signals)

        self._active_fullscreen_zones: set[str] = set()
        self._event_subs_registered = False

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(4)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(6)

        self._icon_lbl = QLabel(self)
        self._icon_lbl.setFixedSize(18, 18)
        self._icon_lbl.setScaledContents(True)

        self._title_lbl = StrongBodyLabel("音量检测")
        self._db_lbl = BodyLabel("-80.0 dB")
        self._db_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self._device_lbl = CaptionLabel("")
        self._device_lbl.setWordWrap(True)

        self._bar = _VolumeBar(self)

        self._status_lbl = CaptionLabel("等待音频输入")
        self._status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_lbl.setWordWrap(True)

        for label in (self._title_lbl, self._db_lbl, self._device_lbl, self._status_lbl):
            _remember_default_font(label)

        top_row.addWidget(self._icon_lbl)
        top_row.addWidget(self._title_lbl)
        top_row.addStretch()
        top_row.addWidget(self._db_lbl)

        root.addLayout(top_row)
        root.addWidget(self._device_lbl)
        root.addWidget(self._bar)
        root.addWidget(self._status_lbl)
        root.addStretch()

        self.destroyed.connect(self._on_destroyed)

        try:
            from . import _plugin_state
            _plugin_state.monitor_instances.append(self._monitor)
        except Exception:
            pass

        self._apply_style()
        self._update_ui()
        self._apply_monitoring_mode()

    @property
    def _props(self) -> dict:
        return self.config.props

    def _get(self, key: str) -> Any:
        return self._props.get(key, _DEFAULTS.get(key))

    def _selected_input_device(self) -> Optional[int]:
        return _coerce_input_device(self._get("input_device"))

    def current_device_name(self) -> str:
        return self._monitor.device_name

    def _start_monitor(self) -> None:
        self._monitor.start(self._selected_input_device())

    def _restart_monitor(self) -> None:
        self._error_msg = ""
        self._monitor.restart(self._selected_input_device())

    def _on_level(self, raw_db: float) -> None:
        self._error_msg = ""
        self._raw_db = raw_db

        calibration = _safe_int(self._get("calibration_offset_db"), _DEFAULTS["calibration_offset_db"])
        db = max(-80.0, min(0.0, raw_db + calibration))
        threshold = _safe_int(self._get("threshold_db"), _DEFAULTS["threshold_db"])

        was_exceeded = self._exceeded
        self._exceeded = db > threshold
        self._current_db = db
        if db > self._peak_db:
            self._peak_db = db

        if self._exceeded and not was_exceeded:
            interval = _safe_int(self._get("retrigger_interval"), _DEFAULTS["retrigger_interval"])
            now = time.monotonic()
            if now - self._last_trigger >= interval:
                self._last_trigger = now
                self._fire_exceeded(db)

        self._update_ui()

    def _on_error(self, msg: str) -> None:
        self._error_msg = str(msg or "未知错误")
        self._update_ui()

    def _fire_exceeded(self, db: float) -> None:
        threshold = _safe_int(self._get("threshold_db"), _DEFAULTS["threshold_db"])
        try:
            from . import _plugin_state
            central_cfg = getattr(_plugin_state, "central_config", {}) or {}
        except Exception:
            _plugin_state = None
            central_cfg = {}

        notify_allowed = bool(self._get("notify_enabled")) and not bool(central_cfg.get("disable_notify", False))
        if notify_allowed:
            if _plugin_state is not None and _plugin_state.api is not None:
                if not _plugin_state.api.ensure_access(
                    "plugin.volume_detector.send_alert",
                    reason="音量检测超阈值时发送提醒通知",
                    parent=self.window(),
                ):
                    notify_allowed = False

        if notify_allowed:
            notif = self.services.get("notification_service")
            if notif is None and _plugin_state is not None:
                try:
                    if _plugin_state.api and _plugin_state.api.request_permission(
                        "notification",
                        reason="音量检测插件需要发送系统通知，以便在超出阈值时提醒用户。",
                    ):
                        notif = self.services.get("notification_service")
                except Exception:
                    notif = None
            if notif:
                notif.show("音量超出阈值", f"当前音量 {db:.1f} dB，阈值 {threshold} dB")

        trigger_allowed = bool(self._get("trigger_enabled")) and not bool(central_cfg.get("disable_trigger", False))
        if trigger_allowed and _plugin_state is not None and _plugin_state.api is not None:
            if not _plugin_state.api.ensure_access(
                "plugin.volume_detector.trigger_automation",
                reason="音量检测超阈值时触发自动化规则",
                parent=self.window(),
            ):
                trigger_allowed = False

        if trigger_allowed and _plugin_state is not None and _plugin_state.api is not None:
            try:
                _plugin_state.api.fire_trigger(_TRIGGER_ID, volume_db=db, threshold_db=threshold)
            except Exception:
                pass

    def _apply_style(self) -> None:
        self._icon_lbl.setPixmap(FIF.MEGAPHONE.icon(Theme.DARK).pixmap(16, 16))
        self._title_lbl.setStyleSheet(_TEXT_PRIMARY)
        self._device_lbl.setStyleSheet(_TEXT_SECONDARY)
        self._status_lbl.setStyleSheet(_TEXT_MUTED)

        _apply_font(self._title_lbl, self._props, "title_font_size", _DEFAULTS["title_font_size"])
        _apply_font(self._db_lbl, self._props, "value_font_size", _DEFAULTS["value_font_size"])
        _apply_font(self._device_lbl, self._props, "status_font_size", _DEFAULTS["status_font_size"])
        _apply_font(self._status_lbl, self._props, "status_font_size", _DEFAULTS["status_font_size"])

        self._bar.set_bar_height(_safe_int(self._get("bar_height"), _DEFAULTS["bar_height"]))
        self._bar.set_colors(self._get("normal_color"), self._get("warning_color"))

    def _update_device_label(self) -> None:
        if bool(self._get("show_device_name")):
            self._device_lbl.setText(f"输入设备：{self.current_device_name()}")
            self._device_lbl.show()
        else:
            self._device_lbl.hide()

    def _update_ui(self) -> None:
        self._apply_style()
        self._update_device_label()

        threshold = _safe_int(self._get("threshold_db"), _DEFAULTS["threshold_db"])
        show_peak = bool(self._get("show_peak"))

        if self._error_msg:
            self._bar.set_level(-80.0, -80.0, False)
            self._bar.set_threshold(threshold)
            self._db_lbl.setText("-- dB")
            self._db_lbl.setStyleSheet(_TEXT_MUTED)
            self._status_lbl.setText(f"检测失败：{self._error_msg}")
            self._status_lbl.setStyleSheet("color: #E74C3C; background: transparent;")
            return

        self._bar.set_level(
            self._current_db,
            self._peak_db if show_peak else -80.0,
            self._exceeded,
        )
        self._bar.set_threshold(threshold)

        self._db_lbl.setText(f"{self._current_db:.1f} dB")
        if self._exceeded:
            self._db_lbl.setStyleSheet("color: #E74C3C; font-weight: 700; background: transparent;")
            self._status_lbl.setText(f"已超出阈值（{threshold} dB）")
            self._status_lbl.setStyleSheet("color: #E74C3C; background: transparent;")
        else:
            self._db_lbl.setStyleSheet(_TEXT_PRIMARY)
            calibration = _safe_int(self._get("calibration_offset_db"), _DEFAULTS["calibration_offset_db"])
            suffix = f" · 校准 {calibration:+d} dB" if calibration else ""
            self._status_lbl.setText(f"当前正常 · 阈值 {threshold} dB{suffix}")
            self._status_lbl.setStyleSheet(_TEXT_MUTED)

    def _decay_peak(self) -> None:
        if self._peak_db > self._current_db:
            self._peak_db -= 1.5
            if self._peak_db < self._current_db:
                self._peak_db = self._current_db
            if not self._error_msg:
                self._update_ui()

    def _on_destroyed(self) -> None:
        self._unsubscribe_fullscreen_events()
        self._stop_monitor_if_idle()
        self._peak_decay_timer.stop()
        try:
            from . import _plugin_state
            if self._monitor in _plugin_state.monitor_instances:
                _plugin_state.monitor_instances.remove(self._monitor)
        except Exception:
            pass

    def _stop_monitor_if_idle(self) -> None:
        if self._monitor._running:
            self._monitor.stop()
            self._raw_db = -80.0
            self._current_db = -80.0
            self._peak_db = -80.0
            self._exceeded = False
            if not self._error_msg:
                self._update_ui()

    def _apply_monitoring_mode(self) -> None:
        always_on = bool(self._get("always_on"))
        if always_on:
            self._unsubscribe_fullscreen_events()
            if not self._monitor._running:
                self._start_monitor()
            return

        self._subscribe_fullscreen_events()
        should_run = bool(self._active_fullscreen_zones) and self.isVisible()
        if should_run:
            if not self._monitor._running:
                self._start_monitor()
        else:
            self._stop_monitor_if_idle()

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
            self._start_monitor()

    def _on_fullscreen_closed(self, zone_id: str = "", **_) -> None:
        self._active_fullscreen_zones.discard(zone_id)
        if not self._active_fullscreen_zones:
            self._stop_monitor_if_idle()

    def refresh(self) -> None:
        """由画布定时调用，音量更新由 sounddevice 回调驱动。"""
        return

    def get_edit_widget(self) -> QWidget:
        return _EditWidget(self)

    def apply_props(self, props: dict) -> None:
        previous_device = self._selected_input_device()
        self.config.props.update(props)
        self._error_msg = ""

        current_device = self._selected_input_device()
        if current_device != previous_device and self._monitor._running:
            self._restart_monitor()

        self._bar.set_threshold(_safe_int(self._get("threshold_db"), _DEFAULTS["threshold_db"]))
        self._update_ui()
        self._apply_monitoring_mode()

    def showEvent(self, event) -> None:  # noqa: N802
        self._apply_monitoring_mode()
        super().showEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802
        super().hideEvent(event)
        if not bool(self._get("always_on")) and not self._active_fullscreen_zones:
            self._stop_monitor_if_idle()


class _VolumeRecordingSession:
    def __init__(
        self,
        *,
        threshold_db: int,
        sample_interval: float,
        dedup_interval: float,
        calibration_db: int = 0,
        metadata: Optional[dict] = None,
    ) -> None:
        self.session_id = uuid.uuid4().hex
        self.started_at = datetime.now()
        self._started_monotonic = time.monotonic()
        self.threshold_db = int(threshold_db)
        self.calibration_db = int(calibration_db)
        self.sample_interval = max(0.05, float(sample_interval))
        self.dedup_interval = max(0.1, float(dedup_interval))
        self.metadata = metadata or {}

        self._sum_db: float = 0.0
        self._sample_count: int = 0
        self.max_db: float = -80.0
        self.exceed_duration: float = 0.0
        self.exceed_count: int = 0
        self._exceed_start: float | None = None
        self._last_exceed_ping: float | None = None
        self._waveform: list[tuple[float, float]] = []
        self._last_record_ts: float = 0.0

    def add_sample(self, raw_db: float) -> None:
        now = time.monotonic()
        db = max(-80.0, min(0.0, raw_db + self.calibration_db))

        if now - self._last_record_ts >= self.sample_interval:
            self._waveform.append((now - self._started_monotonic, db))
            self._last_record_ts = now

        self._sum_db += db
        self._sample_count += 1
        if db > self.max_db:
            self.max_db = db

        if db > self.threshold_db:
            if self._exceed_start is None:
                self._exceed_start = now
                if self._last_exceed_ping is None or now - self._last_exceed_ping >= self.dedup_interval:
                    self.exceed_count += 1
                    self._last_exceed_ping = now
        else:
            if self._exceed_start is not None:
                self.exceed_duration += now - self._exceed_start
                self._exceed_start = None

    def finalize(self, *, device_name: str = "", error: str = "") -> dict:
        now = time.monotonic()
        if self._exceed_start is not None:
            self.exceed_duration += now - self._exceed_start
            self._exceed_start = None

        duration = max(0.0, now - self._started_monotonic)
        avg_db = self._sum_db / self._sample_count if self._sample_count else -80.0

        return {
            "session_id": self.session_id,
            "started_at": self.started_at.isoformat(timespec="seconds"),
            "ended_at": datetime.now().isoformat(timespec="seconds"),
            "duration_sec": duration,
            "threshold_db": self.threshold_db,
            "calibration_db": self.calibration_db,
            "max_db": self.max_db,
            "avg_db": avg_db,
            "exceed_duration_sec": self.exceed_duration,
            "exceed_count": self.exceed_count,
            "sample_interval_sec": self.sample_interval,
            "device_name": device_name,
            "metadata": dict(self.metadata),
            "waveform": [
                {"t": round(t, 3), "db": round(db, 1)}
                for t, db in self._waveform
            ],
            "error": error,
        }


class VolumeSessionHandle:
    def __init__(self, manager: "VolumeRecorderManager", session: _VolumeRecordingSession):
        self._manager = manager
        self.session_id = session.session_id
        self.started_at = session.started_at

    def stop(self) -> Optional[dict]:
        if self._manager is None:
            return None
        report = self._manager.stop_session(self.session_id)
        self._manager = None
        return report


class VolumeRecorderManager(QObject):
    def __init__(self, report_dir: Optional[Path] = None, parent=None):
        super().__init__(parent)
        self._signals = _AudioSignals()
        self._monitor = _AudioMonitor(self._signals)
        self._signals.levelChanged.connect(self._on_level)
        self._signals.errorOccurred.connect(self._on_error)

        self._sessions: dict[str, _VolumeRecordingSession] = {}
        self._device: Optional[int] = None
        self._last_error: str = ""
        self._report_dir = Path(report_dir).resolve() if report_dir is not None else None

    @property
    def device_name(self) -> str:
        return self._monitor.device_name

    def _ensure_running(self) -> None:
        if not self._monitor._running:
            self._monitor.start(self._device)

    def start_session(
        self,
        *,
        threshold_db: int,
        sample_interval: float,
        dedup_interval: float,
        calibration_db: int = 0,
        metadata: Optional[dict] = None,
        device: Optional[int] = None,
    ) -> VolumeSessionHandle:
        if device is not None:
            self._device = device
        self._last_error = ""
        session = _VolumeRecordingSession(
            threshold_db=threshold_db,
            sample_interval=sample_interval,
            dedup_interval=dedup_interval,
            calibration_db=calibration_db,
            metadata=metadata,
        )
        self._sessions[session.session_id] = session
        self._ensure_running()
        return VolumeSessionHandle(self, session)

    def stop_session(self, session_id: str) -> Optional[dict]:
        session = self._sessions.pop(session_id, None)
        if session is None:
            return None
        report = session.finalize(device_name=self._monitor.device_name, error=self._last_error)
        self._persist_report(report)
        if not self._sessions:
            self._monitor.stop()
        return report

    def stop_all(self) -> list[dict]:
        reports: list[dict] = []
        for session_id in list(self._sessions.keys()):
            report = self.stop_session(session_id)
            if report is not None:
                reports.append(report)
        self._last_error = ""
        return reports

    def _on_level(self, raw_db: float) -> None:
        for session in list(self._sessions.values()):
            session.add_sample(raw_db)

    def _on_error(self, msg: str) -> None:
        self._last_error = str(msg or "")

    def _build_report_path(self, report: dict) -> Path:
        if self._report_dir is None:
            raise RuntimeError("report_dir 未设置")

        metadata = report.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}

        slug_source = (
            report.get("item_name")
            or report.get("item_id")
            or metadata.get("item_name")
            or metadata.get("item_id")
            or report.get("session_id")
            or "volume_report"
        )
        slug = _safe_slug(slug_source, fallback="volume_report")
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        candidate = self._report_dir / f"{ts}-{slug}.json"
        if not candidate.exists():
            return candidate

        index = 1
        while True:
            indexed = self._report_dir / f"{ts}-{slug}-{index}.json"
            if not indexed.exists():
                return indexed
            index += 1

    def _persist_report(self, report: dict) -> None:
        if self._report_dir is None:
            return

        try:
            mkdir_with_uac(self._report_dir, parents=True, exist_ok=True)
            report_path = self._build_report_path(report)

            payload = dict(report)
            metadata = payload.get("metadata")
            if not isinstance(metadata, dict):
                metadata = {}
            metadata.setdefault("source", "volume_detector")
            payload["metadata"] = metadata
            payload["saved_path"] = str(report_path)

            write_text_with_uac(
                report_path,
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
                ensure_parent=True,
            )

            report.setdefault("detector_saved_path", str(report_path))
            report.setdefault("saved_path", str(report_path))
        except Exception as exc:
            logger.warning("[音量检测] 保存音量报告失败: {}", exc)


class VolumeDetectorAPI:
    def __init__(self, manager: VolumeRecorderManager, *, default_threshold: int) -> None:
        self._manager = manager
        self._default_threshold = default_threshold

    def start_session(
        self,
        *,
        threshold_db: Optional[int] = None,
        dedup_interval_sec: float = 1.5,
        sample_interval_sec: float = 0.2,
        calibration_db: int = 0,
        metadata: Optional[dict] = None,
        device: Optional[int] = None,
    ) -> VolumeSessionHandle:
        threshold = (
            _safe_int(threshold_db, self._default_threshold)
            if threshold_db is not None
            else self._default_threshold
        )
        return self._manager.start_session(
            threshold_db=threshold,
            sample_interval=max(0.05, float(sample_interval_sec)),
            dedup_interval=max(0.1, float(dedup_interval_sec)),
            calibration_db=calibration_db,
            metadata=metadata,
            device=device,
        )

    def stop_session(self, session_id: str) -> Optional[dict]:
        return self._manager.stop_session(session_id)

    def stop_all(self) -> list[dict]:
        return self._manager.stop_all()

    @property
    def device_name(self) -> str:
        return self._manager.device_name


# ─────────────────────────────────────────────────────────────────────────── #
# 音量状态组件 - 显示检测状态（安静/嘈杂）
# ─────────────────────────────────────────────────────────────────────────── #

_STATUS_DEFAULTS = {
    "threshold_db": -20,
    "calibration_offset_db": 0,
    "input_device": "",
    "always_on": True,
    "notify_enabled": True,
    "retrigger_interval": 5,
    "style": "text",  # text, icon_text, dot
    "quiet_text": "安静",
    "noisy_text": "嘈杂",
    "quiet_color": "#27AE60",
    "noisy_color": "#E74C3C",
    "font_family": "",
    "font_size": 14,
    "show_db": False,
    "db_font_size": 10,
    "alignment": "center",  # left, center, right
}


class _StatusEditWidget(QWidget):
    """音量状态组件的编辑面板。"""

    def __init__(self, widget, parent=None):
        super().__init__(parent)
        self._widget = widget
        props = dict(widget.config.props)

        layout = QFormLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(8)

        # 麦克风选择
        device_row = QWidget(self)
        device_layout = QHBoxLayout(device_row)
        device_layout.setContentsMargins(0, 0, 0, 0)
        device_layout.setSpacing(6)
        self._device_combo = ComboBox()
        self._device_refresh_btn = ToolButton(FIF.SYNC)
        self._device_refresh_btn.setToolTip("刷新麦克风列表")
        self._device_refresh_btn.clicked.connect(self._reload_devices)
        device_layout.addWidget(self._device_combo, 1)
        device_layout.addWidget(self._device_refresh_btn)
        layout.addRow(BodyLabel("麦克风："), device_row)

        # 样式选择
        self._style_combo = ComboBox()
        self._style_combo.addItem("纯文本", userData="text")
        self._style_combo.addItem("图标+文本", userData="icon_text")
        self._style_combo.addItem("圆点指示", userData="dot")
        current_style = str(props.get("style", _STATUS_DEFAULTS["style"]) or "text")
        for i in range(self._style_combo.count()):
            if self._style_combo.itemData(i) == current_style:
                self._style_combo.setCurrentIndex(i)
                break
        layout.addRow(BodyLabel("样式："), self._style_combo)

        # 阈值
        self._threshold = SpinBox()
        self._threshold.setRange(-80, 0)
        self._threshold.setSuffix(" dB")
        self._threshold.setValue(_safe_int(props.get("threshold_db", _STATUS_DEFAULTS["threshold_db"]), _STATUS_DEFAULTS["threshold_db"]))
        layout.addRow(BodyLabel("触发阈值："), self._threshold)

        self._interval = SpinBox()
        self._interval.setRange(1, 3600)
        self._interval.setSuffix(" 秒")
        self._interval.setValue(_safe_int(props.get("retrigger_interval", _STATUS_DEFAULTS["retrigger_interval"]), _STATUS_DEFAULTS["retrigger_interval"]))
        layout.addRow(BodyLabel("提醒间隔："), self._interval)

        self._notify = CheckBox("超出阈值时发送通知")
        self._notify.setChecked(bool(props.get("notify_enabled", _STATUS_DEFAULTS["notify_enabled"])))
        layout.addRow("", self._notify)

        # 校准偏移
        self._calibration = SpinBox()
        self._calibration.setRange(-40, 40)
        self._calibration.setSuffix(" dB")
        self._calibration.setValue(_safe_int(props.get("calibration_offset_db", _STATUS_DEFAULTS["calibration_offset_db"]), _STATUS_DEFAULTS["calibration_offset_db"]))
        layout.addRow(BodyLabel("校准偏移："), self._calibration)

        # 安静文本
        self._quiet_text = EditableComboBox()
        self._quiet_text.addItems(["安静", "正常", "良好", "静音"])
        self._quiet_text.setCurrentText(str(props.get("quiet_text", _STATUS_DEFAULTS["quiet_text"]) or "安静"))
        layout.addRow(BodyLabel("安静文本："), self._quiet_text)

        # 嘈杂文本
        self._noisy_text = EditableComboBox()
        self._noisy_text.addItems(["嘈杂", "警告", "吵闹", "超标"])
        self._noisy_text.setCurrentText(str(props.get("noisy_text", _STATUS_DEFAULTS["noisy_text"]) or "嘈杂"))
        layout.addRow(BodyLabel("嘈杂文本："), self._noisy_text)

        # 安静颜色
        self._quiet_color = ColorPickerButton(
            _to_qcolor(props.get("quiet_color"), _STATUS_DEFAULTS["quiet_color"]),
            "安静颜色"
        )
        layout.addRow(BodyLabel("安静颜色："), self._quiet_color)

        # 嘈杂颜色
        self._noisy_color = ColorPickerButton(
            _to_qcolor(props.get("noisy_color"), _STATUS_DEFAULTS["noisy_color"]),
            "嘈杂颜色"
        )
        layout.addRow(BodyLabel("嘈杂颜色："), self._noisy_color)

        # 字体
        self._font_picker = FluentFontPicker()
        self._font_picker.setCurrentFontFamily(str(props.get("font_family", _STATUS_DEFAULTS["font_family"]) or "").strip())
        layout.addRow(BodyLabel("字体："), self._font_picker)

        # 字号
        self._font_size = SpinBox()
        self._font_size.setRange(8, 72)
        self._font_size.setSuffix(" pt")
        self._font_size.setValue(_safe_int(props.get("font_size", _STATUS_DEFAULTS["font_size"]), _STATUS_DEFAULTS["font_size"]))
        layout.addRow(BodyLabel("字号："), self._font_size)

        # 对齐方式
        self._alignment_combo = ComboBox()
        self._alignment_combo.addItem("居中", userData="center")
        self._alignment_combo.addItem("左对齐", userData="left")
        self._alignment_combo.addItem("右对齐", userData="right")
        current_align = str(props.get("alignment", _STATUS_DEFAULTS["alignment"]) or "center")
        for i in range(self._alignment_combo.count()):
            if self._alignment_combo.itemData(i) == current_align:
                self._alignment_combo.setCurrentIndex(i)
                break
        layout.addRow(BodyLabel("对齐方式："), self._alignment_combo)

        # 显示分贝
        self._show_db = CheckBox("显示分贝值（文本下方）")
        self._show_db.setChecked(bool(props.get("show_db", _STATUS_DEFAULTS["show_db"])))
        layout.addRow("", self._show_db)

        # 分贝字号
        self._db_font_size = SpinBox()
        self._db_font_size.setRange(8, 48)
        self._db_font_size.setSuffix(" pt")
        self._db_font_size.setValue(_safe_int(props.get("db_font_size", _STATUS_DEFAULTS["db_font_size"]), _STATUS_DEFAULTS["db_font_size"]))
        layout.addRow(BodyLabel("分贝字号："), self._db_font_size)

        # 常驻后台
        self._always_on = CheckBox("常驻后台（关闭全屏时也继续检测）")
        self._always_on.setChecked(bool(props.get("always_on", _STATUS_DEFAULTS["always_on"])))
        layout.addRow("", self._always_on)

        hint = CaptionLabel(
            "该组件显示当前音量状态，不影响自习插件的音量报告功能。\n"
            "自习插件可独立使用音量检测接口生成报告。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(_TEXT_MUTED)
        layout.addRow("", hint)

        self._reload_devices()

    def _reload_devices(self) -> None:
        current = self._device_combo.currentData()
        if current is None:
            current = self._widget._get_status("input_device")
        current = _coerce_input_device(current)

        self._device_combo.clear()
        self._device_combo.addItem("系统默认麦克风", userData="")
        for device in _list_input_devices():
            label = device["label"]
            if device.get("is_default"):
                label = f"{label}（默认）"
            self._device_combo.addItem(label, userData=device["index"])

        target_index = 0
        if current is not None:
            target_index = next(
                (i for i in range(self._device_combo.count()) if self._device_combo.itemData(i) == current),
                0,
            )
        self._device_combo.setCurrentIndex(target_index)

    def collect_props(self) -> dict:
        device_data = self._device_combo.currentData()
        return {
            "threshold_db": self._threshold.value(),
            "retrigger_interval": self._interval.value(),
            "notify_enabled": self._notify.isChecked(),
            "calibration_offset_db": self._calibration.value(),
            "input_device": device_data if device_data not in (None, "") else "",
            "style": self._style_combo.currentData() or "text",
            "quiet_text": self._quiet_text.currentText().strip() or "安静",
            "noisy_text": self._noisy_text.currentText().strip() or "嘈杂",
            "quiet_color": self._quiet_color.color.name(),
            "noisy_color": self._noisy_color.color.name(),
            "font_family": self._font_picker.currentFontFamily(),
            "font_size": self._font_size.value(),
            "alignment": self._alignment_combo.currentData() or "center",
            "show_db": self._show_db.isChecked(),
            "db_font_size": self._db_font_size.value(),
            "always_on": self._always_on.isChecked(),
        }


class VolumeStatusWidget(WidgetBase):
    """音量状态组件 - 显示检测状态（安静/嘈杂）。

    该组件独立运行，不与自习插件的音量报告功能冲突。
    自习插件通过 VolumeDetectorAPI 独立进行音量录制。
    """

    WIDGET_TYPE = "volume_detector.status"
    WIDGET_NAME = "音量状态"
    DELETABLE = True
    DEFAULT_W = 2
    DEFAULT_H = 1
    MIN_W = 1
    MIN_H = 1

    def __init__(self, config: WidgetConfig, services: dict[str, Any], parent=None):
        super().__init__(config, services, parent)

        self._raw_db: float = -80.0
        self._current_db: float = -80.0
        self._exceeded: bool = False
        self._last_trigger: float = 0.0
        self._error_msg: str = ""

        self._signals = _AudioSignals()
        self._signals.levelChanged.connect(self._on_level)
        self._signals.errorOccurred.connect(self._on_error)
        self._monitor = _AudioMonitor(self._signals)

        self._active_fullscreen_zones: set[str] = set()
        self._event_subs_registered = False

        # 主布局
        self._root_layout = QVBoxLayout(self)
        self._root_layout.setContentsMargins(8, 6, 8, 6)
        self._root_layout.setSpacing(2)

        # 水平内容布局（用于非居中对齐时的横向排列）
        self._h_layout: Optional[QHBoxLayout] = None

        # 垂直内容布局（用于居中对齐时的纵向排列）
        self._v_content_layout: Optional[QVBoxLayout] = None

        # 圆点指示器（用于 dot 样式）
        self._dot_widget = QWidget(self)
        self._dot_widget.setFixedSize(12, 12)
        self._dot_widget.hide()

        # 图标标签（用于 icon_text 样式）
        self._icon_lbl = QLabel(self)
        self._icon_lbl.setFixedSize(16, 16)
        self._icon_lbl.setScaledContents(True)
        self._icon_lbl.hide()

        # 状态文本
        self._status_lbl = StrongBodyLabel("安静")
        _remember_default_font(self._status_lbl)

        # 分贝值标签
        self._db_lbl = CaptionLabel("-80.0 dB")
        self._db_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _remember_default_font(self._db_lbl)
        self._db_lbl.hide()

        self.destroyed.connect(self._on_destroyed)

        try:
            from . import _plugin_state
            _plugin_state.monitor_instances.append(self._monitor)
        except Exception:
            pass

        self._rebuild_layout()
        self._apply_style()
        self._update_ui()
        self._apply_monitoring_mode()

    def _rebuild_layout(self) -> None:
        """根据对齐方式重建布局。"""
        # 清除现有布局
        while self._root_layout.count():
            item = self._root_layout.takeAt(0)
            sub_layout = item.layout() if item else None
            if sub_layout is not None:
                # 从子布局中移除控件但不删除
                while sub_layout.count():
                    child = sub_layout.takeAt(0)
                    widget = child.widget() if child else None
                    if widget is not None:
                        widget.setParent(self)

        self._h_layout = None
        self._v_content_layout = None

        alignment = str(self._get_status("alignment") or "center")
        style = str(self._get_status("style") or "text")
        show_db = bool(self._get_status("show_db"))

        has_indicator = style in ("dot", "icon_text")

        if alignment == "center":
            # 居中对齐：指示器在上，文本在下
            self._v_content_layout = QVBoxLayout()
            self._v_content_layout.setSpacing(4)
            self._v_content_layout.setContentsMargins(0, 0, 0, 0)

            # 指示器行（居中）
            if has_indicator:
                indicator_row = QHBoxLayout()
                indicator_row.addStretch()
                indicator_row.addWidget(self._dot_widget)
                indicator_row.addWidget(self._icon_lbl)
                indicator_row.addStretch()
                self._v_content_layout.addLayout(indicator_row)
            else:
                self._dot_widget.hide()
                self._icon_lbl.hide()

            # 文本居中
            self._status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._v_content_layout.addWidget(self._status_lbl)

            # 分贝值
            if show_db:
                self._db_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self._v_content_layout.addWidget(self._db_lbl)
                self._db_lbl.show()
            else:
                self._db_lbl.hide()

            self._root_layout.addStretch()
            self._root_layout.addLayout(self._v_content_layout)
            self._root_layout.addStretch()

        elif alignment == "left":
            # 左对齐：指示器在左，文本在右
            self._h_layout = QHBoxLayout()
            self._h_layout.setSpacing(6)
            self._h_layout.setContentsMargins(0, 0, 0, 0)

            # 垂直容器用于文本和分贝
            text_container = QVBoxLayout()
            text_container.setSpacing(2)
            text_container.setContentsMargins(0, 0, 0, 0)

            self._status_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            text_container.addWidget(self._status_lbl)

            if show_db:
                self._db_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                text_container.addWidget(self._db_lbl)
                self._db_lbl.show()
            else:
                self._db_lbl.hide()

            if has_indicator:
                indicator_container = QVBoxLayout()
                indicator_container.setContentsMargins(0, 0, 0, 0)
                indicator_container.addStretch()
                indicator_container.addWidget(self._dot_widget)
                indicator_container.addWidget(self._icon_lbl)
                indicator_container.addStretch()
                self._h_layout.addLayout(indicator_container)
            else:
                self._dot_widget.hide()
                self._icon_lbl.hide()

            self._h_layout.addLayout(text_container)
            self._h_layout.addStretch()

            self._root_layout.addStretch()
            self._root_layout.addLayout(self._h_layout)
            self._root_layout.addStretch()

        else:  # right
            # 右对齐：文本在左，指示器在右
            self._h_layout = QHBoxLayout()
            self._h_layout.setSpacing(6)
            self._h_layout.setContentsMargins(0, 0, 0, 0)

            self._h_layout.addStretch()

            # 垂直容器用于文本和分贝
            text_container = QVBoxLayout()
            text_container.setSpacing(2)
            text_container.setContentsMargins(0, 0, 0, 0)

            self._status_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            text_container.addWidget(self._status_lbl)

            if show_db:
                self._db_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                text_container.addWidget(self._db_lbl)
                self._db_lbl.show()
            else:
                self._db_lbl.hide()

            self._h_layout.addLayout(text_container)

            if has_indicator:
                indicator_container = QVBoxLayout()
                indicator_container.setContentsMargins(0, 0, 0, 0)
                indicator_container.addStretch()
                indicator_container.addWidget(self._dot_widget)
                indicator_container.addWidget(self._icon_lbl)
                indicator_container.addStretch()
                self._h_layout.addLayout(indicator_container)
            else:
                self._dot_widget.hide()
                self._icon_lbl.hide()

            self._root_layout.addStretch()
            self._root_layout.addLayout(self._h_layout)
            self._root_layout.addStretch()

    @property
    def _props(self) -> dict:
        return self.config.props

    def _get_status(self, key: str) -> Any:
        return self._props.get(key, _STATUS_DEFAULTS.get(key))

    def _selected_input_device(self) -> Optional[int]:
        return _coerce_input_device(self._get_status("input_device"))

    def _start_monitor(self) -> None:
        self._monitor.start(self._selected_input_device())

    def _restart_monitor(self) -> None:
        self._error_msg = ""
        self._monitor.restart(self._selected_input_device())

    def _on_level(self, raw_db: float) -> None:
        self._error_msg = ""
        self._raw_db = raw_db

        calibration = _safe_int(self._get_status("calibration_offset_db"), _STATUS_DEFAULTS["calibration_offset_db"])
        db = max(-80.0, min(0.0, raw_db + calibration))
        threshold = _safe_int(self._get_status("threshold_db"), _STATUS_DEFAULTS["threshold_db"])

        was_exceeded = self._exceeded
        self._exceeded = db > threshold
        self._current_db = db

        if self._exceeded and not was_exceeded:
            interval = _safe_int(self._get_status("retrigger_interval"), _STATUS_DEFAULTS["retrigger_interval"])
            now = time.monotonic()
            if now - self._last_trigger >= interval:
                self._last_trigger = now
                self._fire_status_exceeded(db)

        self._update_ui()

    def _on_error(self, msg: str) -> None:
        self._error_msg = str(msg or "未知错误")
        self._update_ui()

    def _fire_status_exceeded(self, db: float) -> None:
        if not self._get_status("notify_enabled"):
            return

        threshold = _safe_int(self._get_status("threshold_db"), _STATUS_DEFAULTS["threshold_db"])
        notif = self.services.get("notification_service")
        if notif is None:
            try:
                from . import _plugin_state
                if _plugin_state.api and _plugin_state.api.request_permission(
                    "notification",
                    reason="音量状态组件需要发送系统通知，以便在超出阈值时提醒用户。",
                ):
                    notif = self.services.get("notification_service")
            except Exception:
                notif = None

        if notif:
            notif.show("音量状态提醒", f"当前音量 {db:.1f} dB，阈值 {threshold} dB")

    def _apply_style(self) -> None:
        style = str(self._get_status("style") or "text")
        quiet_color = _to_qcolor(self._get_status("quiet_color"), _STATUS_DEFAULTS["quiet_color"])
        noisy_color = _to_qcolor(self._get_status("noisy_color"), _STATUS_DEFAULTS["noisy_color"])
        current_color = noisy_color if self._exceeded else quiet_color

        # 应用字体
        _apply_font(self._status_lbl, self._props, "font_size", _STATUS_DEFAULTS["font_size"])
        _apply_font(self._db_lbl, self._props, "db_font_size", _STATUS_DEFAULTS["db_font_size"])

        # 根据样式设置 UI
        if style == "dot":
            self._dot_widget.show()
            self._icon_lbl.hide()
            self._status_lbl.setStyleSheet(f"color: {current_color.name()}; background: transparent;")
        elif style == "icon_text":
            self._dot_widget.hide()
            self._icon_lbl.show()
            icon = FIF.MICROPHONE if self._exceeded else FIF.VOLUME
            self._icon_lbl.setPixmap(icon.icon(Theme.DARK).pixmap(14, 14))
            self._status_lbl.setStyleSheet(f"color: {current_color.name()}; background: transparent;")
        else:  # text
            self._dot_widget.hide()
            self._icon_lbl.hide()
            self._status_lbl.setStyleSheet(f"color: {current_color.name()}; font-weight: bold; background: transparent;")

    def _update_ui(self) -> None:
        self._apply_style()

        quiet_text = str(self._get_status("quiet_text") or "安静")
        noisy_text = str(self._get_status("noisy_text") or "嘈杂")
        style = str(self._get_status("style") or "text")
        show_db = bool(self._get_status("show_db"))

        if self._error_msg:
            self._status_lbl.setText("检测失败")
            self._status_lbl.setStyleSheet("color: #95A5A6; background: transparent;")
            self._db_lbl.setText("-- dB")
            self._db_lbl.setStyleSheet("color: #95A5A6; background: transparent;")
            return

        text = noisy_text if self._exceeded else quiet_text
        self._status_lbl.setText(text)

        # 更新分贝显示
        if show_db:
            self._db_lbl.setText(f"{self._current_db:.1f} dB")
            quiet_color = _to_qcolor(self._get_status("quiet_color"), _STATUS_DEFAULTS["quiet_color"])
            noisy_color = _to_qcolor(self._get_status("noisy_color"), _STATUS_DEFAULTS["noisy_color"])
            current_color = noisy_color if self._exceeded else quiet_color
            # 分贝值颜色稍淡
            self._db_lbl.setStyleSheet(f"color: {current_color.name()}; background: transparent; opacity: 0.8;")

        # 更新圆点颜色
        if style == "dot":
            quiet_color = _to_qcolor(self._get_status("quiet_color"), _STATUS_DEFAULTS["quiet_color"])
            noisy_color = _to_qcolor(self._get_status("noisy_color"), _STATUS_DEFAULTS["noisy_color"])
            current_color = noisy_color if self._exceeded else quiet_color
            self._dot_widget.setStyleSheet(
                f"background: {current_color.name()}; border-radius: 6px;"
            )

    def _on_destroyed(self) -> None:
        self._unsubscribe_fullscreen_events()
        self._stop_monitor_if_idle()
        try:
            from . import _plugin_state
            if self._monitor in _plugin_state.monitor_instances:
                _plugin_state.monitor_instances.remove(self._monitor)
        except Exception:
            pass

    def _stop_monitor_if_idle(self) -> None:
        if self._monitor._running:
            self._monitor.stop()
            self._raw_db = -80.0
            self._current_db = -80.0
            self._exceeded = False
            if not self._error_msg:
                self._update_ui()

    def _apply_monitoring_mode(self) -> None:
        always_on = bool(self._get_status("always_on"))
        if always_on:
            self._unsubscribe_fullscreen_events()
            if not self._monitor._running:
                self._start_monitor()
            return

        self._subscribe_fullscreen_events()
        should_run = bool(self._active_fullscreen_zones) and self.isVisible()
        if should_run:
            if not self._monitor._running:
                self._start_monitor()
        else:
            self._stop_monitor_if_idle()

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
            self._start_monitor()

    def _on_fullscreen_closed(self, zone_id: str = "", **_) -> None:
        self._active_fullscreen_zones.discard(zone_id)
        if not self._active_fullscreen_zones:
            self._stop_monitor_if_idle()

    def refresh(self) -> None:
        """由画布定时调用。"""
        return

    def get_edit_widget(self) -> QWidget:
        return _StatusEditWidget(self)

    def apply_props(self, props: dict) -> None:
        previous_device = self._selected_input_device()
        previous_alignment = self._get_status("alignment")
        previous_style = self._get_status("style")
        previous_show_db = self._get_status("show_db")

        self.config.props.update(props)
        self._error_msg = ""

        current_device = self._selected_input_device()
        current_alignment = self._get_status("alignment")
        current_style = self._get_status("style")
        current_show_db = self._get_status("show_db")

        if current_device != previous_device and self._monitor._running:
            self._restart_monitor()

        # 如果对齐方式、样式或分贝显示改变，需要重建布局
        if (current_alignment != previous_alignment or
            current_style != previous_style or
            current_show_db != previous_show_db):
            self._rebuild_layout()

        self._update_ui()
        self._apply_monitoring_mode()

    def showEvent(self, event) -> None:
        self._apply_monitoring_mode()
        super().showEvent(event)

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        if not bool(self._get_status("always_on")) and not self._active_fullscreen_zones:
            self._stop_monitor_if_idle()

"""专注组件 —— 与专注服务同步的计时器小组件，可在编辑面板选择专注预设"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QVBoxLayout, QWidget, QLabel, QHBoxLayout, QFormLayout,
)
from qfluentwidgets import (
    ProgressRing, ComboBox, FluentIcon as FIF,
    TransparentToolButton, SpinBox,
)

from app.models.focus_model import FocusPreset, FocusStore
from app.services.focus_service import FocusService, FocusPhase
from app.widgets.base_widget import WidgetBase, WidgetConfig
from app.utils.logger import logger


_PHASE_LABELS = {
    FocusPhase.IDLE: "准备开始",
    FocusPhase.FOCUS: "专注中",
    FocusPhase.BREAK: "休息中",
    FocusPhase.DONE: "已完成",
}

_PHASE_COLORS = {
    FocusPhase.IDLE: "#888888",
    FocusPhase.FOCUS: "#0078d4",
    FocusPhase.BREAK: "#107c10",
    FocusPhase.DONE: "#666666",
}


class _FocusEditPanel(QWidget):
    def __init__(self, props: dict, parent=None):
        super().__init__(parent)
        self._store = FocusStore()

        f = QFormLayout(self)
        f.setVerticalSpacing(10)

        self._preset_combo = ComboBox()
        self._preset_combo.setPlaceholderText("选择预设")
        self._preset_combo.setMinimumWidth(160)
        for p in self._store.all():
            self._preset_combo.addItem(p.name, userData=p.id)
        saved_id = props.get("preset_id", "")
        if saved_id:
            for i in range(self._preset_combo.count()):
                if self._preset_combo.itemData(i) == saved_id:
                    self._preset_combo.setCurrentIndex(i)
                    break
        f.addRow("专注预设:", self._preset_combo)

        self._grid_w = SpinBox()
        self._grid_w.setRange(2, 20)
        self._grid_w.setSuffix(" 格")
        self._grid_w.setValue(props.get("grid_w", 2))

        self._grid_h = SpinBox()
        self._grid_h.setRange(2, 20)
        self._grid_h.setSuffix(" 格")
        self._grid_h.setValue(props.get("grid_h", 2))

        f.addRow("组件宽度:", self._grid_w)
        f.addRow("组件高度:", self._grid_h)

    def collect_props(self) -> dict:
        return {
            "preset_id": self._preset_combo.currentData() or "",
            "grid_w": self._grid_w.value(),
            "grid_h": self._grid_h.value(),
        }


class FocusWidget(WidgetBase):
    WIDGET_TYPE = "focus"
    WIDGET_NAME = "专注"
    DELETABLE = True
    DEFAULT_W = 2
    DEFAULT_H = 2
    MIN_W = 2
    MIN_H = 2
    RUNS_IN_BACKGROUND = True

    def __init__(self, config: WidgetConfig, services, parent=None):
        super().__init__(config, services, parent)

        self._store = FocusStore()
        self._active_preset: Optional[FocusPreset] = None
        self._svc: Optional[FocusService] = None
        self._connected = False

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(4)
        root.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._ring = ProgressRing()
        self._ring.setRange(0, 100)
        self._ring.setValue(0)
        self._ring.setFixedSize(100, 100)
        self._ring.setStyleSheet("background:transparent;")
        root.addWidget(self._ring, 0, Qt.AlignmentFlag.AlignCenter)

        self._time_lbl = QLabel("00:00")
        self._time_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._time_lbl.setStyleSheet(
            "color:white; font-size:28px; font-weight:200; background:transparent;"
        )
        root.addWidget(self._time_lbl)

        self._phase_lbl = QLabel("准备开始")
        self._phase_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._phase_lbl.setStyleSheet(
            "color:#888; font-size:13px; background:transparent;"
        )
        root.addWidget(self._phase_lbl)

        self._cycle_lbl = QLabel("")
        self._cycle_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cycle_lbl.setStyleSheet(
            "color:#555; font-size:11px; background:transparent;"
        )
        root.addWidget(self._cycle_lbl)

        self._preset_lbl = QLabel("")
        self._preset_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preset_lbl.setStyleSheet(
            "color:#aaa; font-size:11px; background:transparent;"
        )
        root.addWidget(self._preset_lbl)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        btn_row.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._start_btn = TransparentToolButton(FIF.PLAY)
        self._start_btn.setFixedSize(36, 36)
        self._start_btn.clicked.connect(self._toggle_run)
        btn_row.addWidget(self._start_btn)

        self._reset_btn = TransparentToolButton(FIF.CANCEL)
        self._reset_btn.setFixedSize(36, 36)
        self._reset_btn.clicked.connect(self._stop)
        btn_row.addWidget(self._reset_btn)

        self._skip_btn = TransparentToolButton(FIF.SKIP_FORWARD)
        self._skip_btn.setFixedSize(36, 36)
        self._skip_btn.clicked.connect(self._skip_phase)
        btn_row.addWidget(self._skip_btn)

        root.addLayout(btn_row)

        self._load_preset_from_props()
        self._connect_service()
        self._update_display()

    def _load_preset_from_props(self) -> None:
        pid = self.config.props.get("preset_id", "")
        if pid:
            p = self._store.get(pid)
            if p:
                self._active_preset = p
                self._preset_lbl.setText(p.name)

    def _get_service(self) -> Optional[FocusService]:
        svc = self.services.get("focus_service")
        if svc is not None:
            return svc
        try:
            return FocusService.instance()
        except Exception:
            return None

    def _connect_service(self) -> None:
        if self._connected:
            return
        svc = self._get_service()
        if svc is None:
            return
        self._svc = svc
        svc.tick.connect(self._on_tick)
        svc.phaseChanged.connect(self._on_phase_changed)
        svc.sessionFinished.connect(self._on_session_finished)
        svc.distractedStateChanged.connect(self._on_distracted_state)
        self._connected = True
        self._sync_from_service()

    def _sync_from_service(self) -> None:
        if self._svc is None:
            return
        if self._svc.is_running and self._svc.preset is not None:
            self._active_preset = self._svc.preset
            self._preset_lbl.setText(self._active_preset.name)
        self._update_display()

    def _toggle_run(self) -> None:
        svc = self._svc
        if svc is None:
            return
        if svc.is_running:
            if hasattr(svc, '_timer') and svc._timer.isActive():
                svc.pause()
            else:
                svc.resume()
        else:
            if self._active_preset is None:
                return
            svc.start(self._active_preset)
        self._update_display()

    def _stop(self) -> None:
        if self._svc is not None:
            self._svc.stop()
        self._update_display()

    def _skip_phase(self) -> None:
        if self._svc is None or not self._svc.is_running:
            return
        if self._svc.phase in (FocusPhase.FOCUS, FocusPhase.BREAK):
            self._svc._finish_phase()

    def _on_tick(self, elapsed_ms: int, remaining_ms: int, phase) -> None:
        if self._svc is None or self._active_preset is None:
            return
        total_ms = (
            self._active_preset.focus_minutes * 60_000
            if phase == FocusPhase.FOCUS
            else self._active_preset.break_minutes * 60_000
        )
        progress = 1.0 - (remaining_ms / total_ms) if total_ms > 0 else 1.0
        self._ring.setValue(int(progress * 100))

        secs = max(0, remaining_ms // 1000)
        m, s = divmod(secs, 60)
        self._time_lbl.setText(f"{m:02d}:{s:02d}")

        color = _PHASE_COLORS.get(phase, "#888")
        self._ring.setStyleSheet(
            f"ProgressRing {{ background:transparent; }}"
            f"ProgressRing::chunk {{ background:{color}; }}"
        )

        is_paused = hasattr(self._svc, '_timer') and not self._svc._timer.isActive()
        icon = FIF.PAUSE if self._svc.is_running and not is_paused else FIF.PLAY
        self._start_btn.setIcon(icon)

    def _on_phase_changed(self, phase, cycle_index: int) -> None:
        color = _PHASE_COLORS.get(phase, "#888")
        label = _PHASE_LABELS.get(phase, "")
        self._phase_lbl.setText(label)
        self._phase_lbl.setStyleSheet(
            f"color:{color}; font-size:13px; background:transparent;"
        )
        if self._active_preset:
            total = self._active_preset.cycles if self._active_preset.cycles > 0 else "∞"
            self._cycle_lbl.setText(f"第 {cycle_index + 1}/{total} 轮")
        self._update_display()

    def _on_session_finished(self) -> None:
        self._update_display()

    def _on_distracted_state(self, is_distracted: bool) -> None:
        if is_distracted:
            self._phase_lbl.setStyleSheet(
                "color:#e81123; font-size:13px; background:transparent;"
            )
            self._phase_lbl.setText("⚠ 不专注")
        else:
            self._update_display()

    def _update_display(self) -> None:
        svc = self._svc
        color = "#888"
        if svc is not None:
            phase = svc.phase
            color = _PHASE_COLORS.get(phase, "#888")
            label = _PHASE_LABELS.get(phase, "")

            if phase == FocusPhase.IDLE:
                if self._active_preset:
                    fm = self._active_preset.focus_minutes
                    self._time_lbl.setText(f"{fm:02d}:00")
                else:
                    self._time_lbl.setText("00:00")
                self._ring.setValue(0)
                self._start_btn.setIcon(FIF.PLAY)
                self._start_btn.setEnabled(self._active_preset is not None)
                self._phase_lbl.setText(label)
            elif phase == FocusPhase.DONE:
                self._time_lbl.setText("完成!")
                self._ring.setValue(100)
                self._start_btn.setIcon(FIF.PLAY)
                self._start_btn.setEnabled(True)
            else:
                is_paused = hasattr(svc, '_timer') and not svc._timer.isActive()
                self._start_btn.setIcon(
                    FIF.PAUSE if svc.is_running and not is_paused else FIF.PLAY
                )
                self._start_btn.setEnabled(True)

            self._phase_lbl.setText(label)
            self._phase_lbl.setStyleSheet(
                f"color:{color}; font-size:13px; background:transparent;"
            )

            if svc.cycle_index > 0 and self._active_preset:
                total = self._active_preset.cycles if self._active_preset.cycles > 0 else "∞"
                self._cycle_lbl.setText(f"第 {svc.cycle_index + 1}/{total} 轮")
            elif phase == FocusPhase.IDLE:
                self._cycle_lbl.setText("")
        else:
            self._start_btn.setIcon(FIF.PLAY)
            self._start_btn.setEnabled(self._active_preset is not None)
            self._phase_lbl.setText("准备开始")

        self._ring.setStyleSheet(
            f"ProgressRing {{ background:transparent; }}"
            f"ProgressRing::chunk {{ background:{color}; }}"
        )

    def refresh(self) -> None:
        if not self._connected:
            self._connect_service()
        if self._svc and not self._svc.is_running:
            self._update_display()

    def get_edit_widget(self):
        props = dict(self.config.props)
        props["grid_w"] = self.config.grid_w
        props["grid_h"] = self.config.grid_h
        return _FocusEditPanel(props)

    def apply_props(self, props: dict) -> None:
        self.config.props.update(props)
        self.config.grid_w = max(2, int(props.get("grid_w", self.DEFAULT_W)))
        self.config.grid_h = max(2, int(props.get("grid_h", self.DEFAULT_H)))
        self._load_preset_from_props()
        self.refresh()

    def on_background_detached(self, services=None) -> None:
        super().on_background_detached(services)

    def on_background_attached(self, services) -> None:
        super().on_background_attached(services)
        if not self._connected:
            self._connect_service()


PomodoroWidget = FocusWidget

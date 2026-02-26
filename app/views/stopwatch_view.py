"""秒表视图"""
from __future__ import annotations

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QWidget,
    QListWidget, QListWidgetItem,
)
from qfluentwidgets import (
    FluentIcon as FIF, PushButton,
    TitleLabel, CaptionLabel, BodyLabel,
    TransparentPushButton,
    isDarkTheme, qconfig,
)

from app.services.clock_service import ClockService
from app.services.settings_service import SettingsService
from app.utils.time_utils import format_duration
from app.constants import TIMER_TICK_MS


class StopwatchView(QWidget):
    """秒表视图：开始/暂停/重置 + 记圈"""

    def __init__(self, clock_service: ClockService, parent=None):
        super().__init__(parent)
        self.setObjectName("stopwatchView")
        self.setAutoFillBackground(False)

        self._elapsed_ms   = 0       # 总计时（毫秒）
        self._lap_start_ms = 0       # 当前圈开始时的总计时
        self._running      = False
        self._laps: list[int] = []   # 每圈用时（毫秒）
        self._settings     = SettingsService.instance()

        root = QVBoxLayout(self)
        root.setContentsMargins(40, 24, 40, 16)
        root.setSpacing(12)

        # 页面标题
        root.addWidget(TitleLabel("秒表"))

        # 大时间显示
        self.main_time = TitleLabel(format_duration(0, self._settings.duration_precision))
        self.main_time.setAlignment(Qt.AlignCenter)
        font = self.main_time.font()
        font.setPointSize(48)
        self.main_time.setFont(font)

        # 当前圈时间
        self.lap_time = BodyLabel(f"圈：{format_duration(0, self._settings.duration_precision)}")
        self.lap_time.setAlignment(Qt.AlignCenter)

        # 按钮行
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        self.start_btn = PushButton(FIF.PLAY, "开始")
        self.lap_btn   = PushButton(FIF.HISTORY, "记圈")
        self.reset_btn = TransparentPushButton(FIF.SYNC, "重置")

        self.lap_btn.setEnabled(False)
        self.reset_btn.setEnabled(False)

        self.start_btn.clicked.connect(self._toggle)
        self.lap_btn.clicked.connect(self._on_lap)
        self.reset_btn.clicked.connect(self._on_reset)

        btn_row.addStretch()
        btn_row.addWidget(self.lap_btn)
        btn_row.addWidget(self.start_btn)
        btn_row.addWidget(self.reset_btn)
        btn_row.addStretch()

        # 圈历史列表
        self._lap_list = QListWidget()
        self._lap_list.setMaximumHeight(220)
        self._update_lap_list_style()
        qconfig.themeChanged.connect(self._update_lap_list_style)

        root.addStretch()
        root.addWidget(self.main_time)
        root.addWidget(self.lap_time)
        root.addLayout(btn_row)
        root.addWidget(BodyLabel("圈记录"))
        root.addWidget(self._lap_list)

        clock_service.tick.connect(self._on_tick)
        self._settings.changed.connect(self._on_settings_changed)

    # ------------------------------------------------------------------ #

    def _update_lap_list_style(self) -> None:
        border_color = "#555555" if isDarkTheme() else "#d0d0d0"
        bg_color = "rgba(0,0,0,0)" if isDarkTheme() else "rgba(255,255,255,0)"
        text_color = "#e0e0e0" if isDarkTheme() else "#1a1a1a"
        self._lap_list.setStyleSheet(
            f"QListWidget{{border:1px solid {border_color};"
            f"border-radius:6px;background:transparent;color:{text_color};}}"
        )

    @property
    def _precision(self) -> int:
        return self._settings.stopwatch_precision

    @Slot()
    def _on_settings_changed(self) -> None:
        """设置变更后立即刷新显示"""
        p = self._precision
        self.main_time.setText(format_duration(self._elapsed_ms, p))
        cur_lap = self._elapsed_ms - self._lap_start_ms
        self.lap_time.setText(f"圈：{format_duration(cur_lap, p)}")

    # ------------------------------------------------------------------ #

    @Slot()
    def _toggle(self) -> None:
        self._running = not self._running
        if self._running:
            self.start_btn.setIcon(FIF.PAUSE)
            self.start_btn.setText("暂停")
            self.lap_btn.setEnabled(True)
            self.reset_btn.setEnabled(False)
        else:
            self.start_btn.setIcon(FIF.PLAY)
            self.start_btn.setText("继续")
            self.lap_btn.setEnabled(False)
            self.reset_btn.setEnabled(True)

    @Slot()
    def _on_lap(self) -> None:
        if not self._running:
            return
        lap_ms = self._elapsed_ms - self._lap_start_ms
        idx    = len(self._laps) + 1
        self._laps.append(lap_ms)
        self._lap_start_ms = self._elapsed_ms

        p = self._precision
        item = QListWidgetItem(
            f"  第 {idx:>2} 圈    {format_duration(lap_ms, p)}"
            f"    总计 {format_duration(self._elapsed_ms, p)}"
        )
        self._lap_list.insertItem(0, item)
        self.lap_time.setText(f"圈：{format_duration(0, p)}")

    @Slot()
    def _on_reset(self) -> None:
        self._running      = False
        self._elapsed_ms   = 0
        self._lap_start_ms = 0
        self._laps.clear()
        self._lap_list.clear()
        p = self._precision
        self.main_time.setText(format_duration(0, p))
        self.lap_time.setText(f"圈：{format_duration(0, p)}")
        self.start_btn.setIcon(FIF.PLAY)
        self.start_btn.setText("开始")
        self.lap_btn.setEnabled(False)
        self.reset_btn.setEnabled(False)

    @Slot()
    def _on_tick(self) -> None:
        if not self._running:
            return
        self._elapsed_ms += TIMER_TICK_MS
        p = self._precision
        self.main_time.setText(format_duration(self._elapsed_ms, p))
        cur_lap = self._elapsed_ms - self._lap_start_ms
        self.lap_time.setText(f"圈：{format_duration(cur_lap, p)}")

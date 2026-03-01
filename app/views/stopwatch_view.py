"""秒表视图"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QWidget,
    QListWidget, QListWidgetItem,
    QSizePolicy,
)
from qfluentwidgets import (
    FluentIcon as FIF, PushButton,
    TitleLabel, CaptionLabel, BodyLabel,
    TransparentToolButton,
    isDarkTheme, qconfig,
)

from app.services.clock_service import ClockService
from app.services.settings_service import SettingsService
from app.services.i18n_service import I18nService
from app.utils.time_utils import format_duration
from app.constants import TIMER_TICK_MS


class _LapRowWidget(QWidget):
    """单条计圈记录行，含动态「距现在」标签和删除按钮"""

    delete_requested = Signal(int)   # 发出该圈的 list_index（插入顺序）

    def __init__(
        self,
        list_index: int,
        lap_num: int,
        lap_ms: int,
        total_ms: int,
        precision: int,
        parent=None,
    ):
        super().__init__(parent)
        self._list_index  = list_index
        self._lap_ms      = lap_ms
        self._total_ms    = total_ms
        self._recorded_ms = total_ms   # 记圈时秒表总计时（ms）

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 3, 4, 3)
        layout.setSpacing(8)

        self._num_lbl   = CaptionLabel(f"第 {lap_num} 圈")
        self._num_lbl.setFixedWidth(56)

        self._lap_lbl   = BodyLabel(format_duration(lap_ms, precision))
        self._lap_lbl.setFixedWidth(96)

        self._total_lbl = CaptionLabel(f"总计 {format_duration(total_ms, precision)}")
        self._total_lbl.setFixedWidth(110)

        self._since_lbl = CaptionLabel("+0s")
        self._since_lbl.setFixedWidth(80)
        self._since_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        del_btn = TransparentToolButton(FIF.DELETE, self)
        del_btn.setFixedSize(28, 28)
        del_btn.clicked.connect(lambda: self.delete_requested.emit(self._list_index))

        layout.addWidget(self._num_lbl)
        layout.addWidget(self._lap_lbl)
        layout.addWidget(self._total_lbl)
        layout.addStretch()
        layout.addWidget(self._since_lbl)
        layout.addWidget(del_btn)

    # ------------------------------------------------------------------
    def update_since(self, current_elapsed_ms: int, precision: int) -> None:
        since_ms = current_elapsed_ms - self._recorded_ms
        self._since_lbl.setText(f"+{format_duration(since_ms, precision)}")

    def update_precision(self, precision: int) -> None:
        self._lap_lbl.setText(format_duration(self._lap_ms, precision))
        self._total_lbl.setText(f"总计 {format_duration(self._total_ms, precision)}")

    def update_lap_num(self, lap_num: int) -> None:
        self._num_lbl.setText(f"第 {lap_num} 圈")

    @property
    def list_index(self) -> int:
        return self._list_index

    @list_index.setter
    def list_index(self, v: int) -> None:
        self._list_index = v


# ---------------------------------------------------------------------------

class StopwatchView(QWidget):
    """秒表视图：开始/暂停/重置 + 记圈（可删除，含距Now计时）"""

    def __init__(self, clock_service: ClockService, parent=None):
        super().__init__(parent)
        self.setObjectName("stopwatchView")
        self.setAutoFillBackground(False)

        self._elapsed_ms   = 0
        self._lap_start_ms = 0
        self._running      = False
        # 每条圈记录：(lap_ms, total_ms_at_record)
        self._laps: list[tuple[int, int]] = []
        self._settings     = SettingsService.instance()
        self._i18n         = I18nService.instance()

        root = QVBoxLayout(self)
        root.setContentsMargins(40, 24, 40, 16)
        root.setSpacing(12)

        root.addWidget(TitleLabel(self._i18n.t("stopwatch.title")))

        self.main_time = TitleLabel(format_duration(0, self._settings.duration_precision))
        self.main_time.setAlignment(Qt.AlignCenter)
        font = self.main_time.font()
        font.setPointSize(48)
        self.main_time.setFont(font)

        self.lap_time = BodyLabel(
            f"{self._i18n.t('stopwatch.lap')}：{format_duration(0, self._settings.duration_precision)}"
        )
        self.lap_time.setAlignment(Qt.AlignCenter)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        self.start_btn = PushButton(FIF.PLAY, self._i18n.t("timer.start"))
        self.lap_btn   = PushButton(FIF.HISTORY, self._i18n.t("stopwatch.record_lap"))
        self.reset_btn = PushButton(FIF.SYNC, self._i18n.t("timer.reset"))

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

        self._lap_list = QListWidget()
        self._lap_list.setMaximumHeight(220)
        self._update_lap_list_style()
        qconfig.themeChanged.connect(self._update_lap_list_style)

        root.addStretch()
        root.addWidget(self.main_time)
        root.addWidget(self.lap_time)
        root.addLayout(btn_row)
        root.addWidget(BodyLabel(self._i18n.t("stopwatch.lap_record")))
        root.addWidget(self._lap_list)

        clock_service.tick.connect(self._on_tick)
        self._settings.changed.connect(self._on_settings_changed)

    # ------------------------------------------------------------------
    def _update_lap_list_style(self) -> None:
        border_color = "#555555" if isDarkTheme() else "#d0d0d0"
        text_color   = "#e0e0e0" if isDarkTheme() else "#1a1a1a"
        self._lap_list.setStyleSheet(
            f"QListWidget{{border:1px solid {border_color};"
            f"border-radius:6px;background:transparent;color:{text_color};}}"
        )

    @property
    def _precision(self) -> int:
        return self._settings.stopwatch_precision

    # ------------------------------------------------------------------
    def _iter_row_widgets(self):
        """遍历 QListWidget 中所有 _LapRowWidget"""
        for i in range(self._lap_list.count()):
            item = self._lap_list.item(i)
            w = self._lap_list.itemWidget(item)
            if isinstance(w, _LapRowWidget):
                yield item, w

    # ------------------------------------------------------------------
    @Slot()
    def _on_settings_changed(self) -> None:
        p = self._precision
        self.main_time.setText(format_duration(self._elapsed_ms, p))
        cur_lap = self._elapsed_ms - self._lap_start_ms
        self.lap_time.setText(f"{self._i18n.t('stopwatch.lap')}：{format_duration(cur_lap, p)}")
        for _, w in self._iter_row_widgets():
            w.update_precision(p)

    @Slot()
    def _toggle(self) -> None:
        self._running = not self._running
        if self._running:
            self.start_btn.setIcon(FIF.PAUSE)
            self.start_btn.setText(self._i18n.t("timer.pause"))
            self.lap_btn.setEnabled(True)
            self.reset_btn.setEnabled(False)
        else:
            self.start_btn.setIcon(FIF.PLAY)
            self.start_btn.setText(self._i18n.t("timer.resume"))
            self.lap_btn.setEnabled(False)
            self.reset_btn.setEnabled(True)

    @Slot()
    def _on_lap(self) -> None:
        if not self._running:
            return
        lap_ms = self._elapsed_ms - self._lap_start_ms
        lap_num = self._lap_list.count() + 1
        self._laps.append((lap_ms, self._elapsed_ms))
        self._lap_start_ms = self._elapsed_ms

        p = self._precision
        # list_index = 当前插入位置（顶部 = 0）
        row_widget = _LapRowWidget(
            list_index=0,
            lap_num=lap_num,
            lap_ms=lap_ms,
            total_ms=self._elapsed_ms,
            precision=p,
        )
        row_widget.delete_requested.connect(self._on_delete_lap)

        # 先将已有行的 list_index 全部 +1（因为新行插入在顶部）
        for _, w in self._iter_row_widgets():
            w.list_index += 1

        item = QListWidgetItem()
        item.setSizeHint(row_widget.sizeHint())
        self._lap_list.insertItem(0, item)
        self._lap_list.setItemWidget(item, row_widget)

        self.lap_time.setText(f"{self._i18n.t('stopwatch.lap')}：{format_duration(0, p)}")

    @Slot(int)
    def _on_delete_lap(self, list_index: int) -> None:
        """删除指定 list_index 的圈记录行，并重新编号剩余行"""
        item = self._lap_list.item(list_index)
        if item is None:
            return
        self._lap_list.takeItem(list_index)
        # 修正 list_index 并重新编号：列表最顶（index 0）是最新圈，编号最大
        remaining = list(self._iter_row_widgets())
        total = len(remaining)
        for new_idx, (_, w) in enumerate(remaining):
            w.list_index = new_idx
            w.update_lap_num(total - new_idx)

    @Slot()
    def _on_reset(self) -> None:
        self._running      = False
        self._elapsed_ms   = 0
        self._lap_start_ms = 0
        self._laps.clear()
        self._lap_list.clear()
        p = self._precision
        self.main_time.setText(format_duration(0, p))
        self.lap_time.setText(f"{self._i18n.t('stopwatch.lap')}：{format_duration(0, p)}")
        self.start_btn.setIcon(FIF.PLAY)
        self.start_btn.setText(self._i18n.t("timer.start"))
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
        self.lap_time.setText(f"{self._i18n.t('stopwatch.lap')}：{format_duration(cur_lap, p)}")
        # 更新每行的「距现在」标签
        for _, w in self._iter_row_widgets():
            w.update_since(self._elapsed_ms, p)

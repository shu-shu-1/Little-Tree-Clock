"""
时钟服务
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal, QElapsedTimer

from app.constants import TIMER_TICK_MS
from app.utils.logger import logger


class ClockService(QObject):
    """
    信号
    ----
    tick(delta_ms: int) — 每 TIMER_TICK_MS 发出一次，携带实际经过的毫秒数
    secondTick()        — 每 1000 ms 发出一次（数字时钟 / 世界时间用）
    """

    tick       = Signal(int)  # 携带实际经过的毫秒数
    secondTick = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._counter = 0
        self._elapsed_timer = QElapsedTimer()
        self._elapsed_timer.start()
        self._last_elapsed = 0
        self._last_lag_warning_elapsed = -10_000

        self._timer = QTimer(self)
        self._timer.setInterval(TIMER_TICK_MS)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start()
        logger.debug("ClockService 已启动: interval_ms={}", TIMER_TICK_MS)

    def _on_tick(self) -> None:
        """定时器回调，发出 tick 信号并计算实际经过时间"""
        current = self._elapsed_timer.elapsed()
        delta = current - self._last_elapsed
        self._last_elapsed = current

        if delta >= TIMER_TICK_MS * 5 and (current - self._last_lag_warning_elapsed) >= 10_000:
            self._last_lag_warning_elapsed = current
            logger.warning(
                "ClockService tick 延迟偏高: delta_ms={}, expected_ms={}",
                delta,
                TIMER_TICK_MS,
            )
        
        self._counter += 1
        self.tick.emit(delta)
        
        if self._counter % 100 == 0:
            self.secondTick.emit()

    def elapsed(self) -> int:
        """返回自服务启动以来经过的毫秒数（高精度）"""
        return self._elapsed_timer.elapsed()

    def start(self) -> None:
        if not self._timer.isActive():
            self._elapsed_timer.restart()
            self._last_elapsed = 0
            self._timer.start()
            logger.info("ClockService 定时器已启动")

    def stop(self) -> None:
        if self._timer.isActive():
            self._timer.stop()
            logger.info("ClockService 定时器已停止")

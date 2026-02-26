"""
时钟服务

提供全局唯一的高精度 QTimer（10 ms），
UI 组件只需连接本服务的信号即可，避免每个视图各自创建定时器。
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal

from app.constants import TIMER_TICK_MS


class ClockService(QObject):
    """
    信号
    ----
    tick()       — 每 10 ms 发出一次（秒表 / 计时器用）
    secondTick() — 每 1000 ms 发出一次（数字时钟 / 世界时间用）
    """

    tick       = Signal()
    secondTick = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._counter = 0

        self._timer = QTimer(self)
        self._timer.setInterval(TIMER_TICK_MS)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start()

    def _on_tick(self) -> None:
        self._counter += 1
        self.tick.emit()
        if self._counter % 100 == 0:
            self.secondTick.emit()

    def start(self) -> None:
        if not self._timer.isActive():
            self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

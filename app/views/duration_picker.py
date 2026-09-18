"""自定义时长选择器 DurationPicker。"""

from __future__ import annotations

from PySide6.QtCore import Signal

from qfluentwidgets.components.date_time.picker_base import (
    PickerBase,
    DigitFormatter,
)


class _PadFormatter(DigitFormatter):
    def encode(self, value) -> str:
        return str(int(value)).zfill(2)


class DurationPicker(PickerBase):
    """小时列范围 0~99，分钟/秒列 0~59。"""

    durationChanged = Signal(int)  # 毫秒

    def __init__(self, parent=None, showSeconds: bool = True):
        super().__init__(parent)
        self._showSeconds = showSeconds

        w = 80 if showSeconds else 120
        self.addColumn("时", range(0, 100), w, formatter=_PadFormatter())
        self.addColumn("分", range(0, 60), w, formatter=_PadFormatter())
        self.addColumn("秒", range(0, 60), w, formatter=_PadFormatter())
        self.setColumnVisible(2, showSeconds)

    def totalSeconds(self) -> int:
        try:

            def _v(idx: int) -> int:
                if idx >= len(self.columns):
                    return 0
                raw = self.columns[idx]._value
                return int(raw) if raw is not None else 0

            return max(0, _v(0) * 3600 + _v(1) * 60 + _v(2))
        except Exception:
            return 0

    def totalMs(self) -> int:
        return self.totalSeconds() * 1000

    def setTotalSeconds(self, seconds: int) -> None:
        seconds = max(0, int(seconds))
        h = min(seconds // 3600, 99)
        seconds %= 3600
        m = seconds // 60
        s = seconds % 60
        self.setColumnValue(0, h)
        self.setColumnValue(1, m)
        self.setColumnValue(2, s)

    def setTotalMs(self, ms: int) -> None:
        self.setTotalSeconds(ms // 1000)

    def isSecondVisible(self) -> bool:
        return self._showSeconds

    def setSecondVisible(self, visible: bool) -> None:
        self._showSeconds = visible
        self.setColumnVisible(2, visible)
        w = 80 if visible else 120
        for btn in self.columns:
            btn.setFixedWidth(w)

    def _onConfirmed(self, value: list) -> None:
        super()._onConfirmed(value)
        self.durationChanged.emit(self.totalMs())

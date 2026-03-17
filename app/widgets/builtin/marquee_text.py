"""滚动文字组件 —— 支持上下/左右滚动与滚动速度"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, QRect
from PySide6.QtGui import QColor, QPainter, QPen, QFontMetrics
from PySide6.QtWidgets import QFormLayout, QLabel, QVBoxLayout, QWidget
from qfluentwidgets import ComboBox, ColorPickerButton, PlainTextEdit, SpinBox

from app.widgets.base_widget import WidgetBase, WidgetConfig
from app.widgets.fluent_font_picker import FluentFontPicker


_DIRECTION_ITEMS: list[tuple[str, str]] = [
    ("向左滚动", "left"),
    ("向右滚动", "right"),
    ("向上滚动", "up"),
    ("向下滚动", "down"),
]


class _MarqueeDisplay(QWidget):
    """文字滚动绘制区域。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setStyleSheet("background:transparent;")

        self._text = ""
        self._font_family = ""
        self._font_size = 28
        self._color = "#ffffff"
        self._direction = "left"
        self._speed = 80
        self._offset = 0.0

        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._tick)

    def apply_state(
        self,
        *,
        text: str,
        font_family: str,
        font_size: int,
        color: str,
        direction: str,
        speed: int,
    ) -> None:
        state_changed = (
            text != self._text
            or font_family != self._font_family
            or int(font_size) != self._font_size
            or color != self._color
            or direction != self._direction
        )

        self._text = str(text)
        self._font_family = str(font_family or "")
        self._font_size = max(8, int(font_size))
        self._color = str(color or "#ffffff")
        self._direction = direction if direction in {"left", "right", "up", "down"} else "left"
        self._speed = max(1, int(speed))

        if state_changed:
            self._offset = 0.0

        if self._text.strip() and self._speed > 0:
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()

        self.update()

    def _cycle_length(self) -> float:
        text = self._text.strip()
        if not text:
            return 0.0

        font = self.font()
        if self._font_family:
            font.setFamily(self._font_family)
        font.setPointSize(self._font_size)
        fm = QFontMetrics(font)

        if self._direction in {"left", "right"}:
            text_w = max(1, fm.horizontalAdvance(text))
            gap = max(36, min(260, text_w // 3))
            return float(text_w + gap)

        width = max(1, self.width() - 6)
        text_rect = fm.boundingRect(0, 0, width, 100000, int(Qt.AlignmentFlag.AlignHCenter | Qt.TextFlag.TextWordWrap), text)
        text_h = max(1, text_rect.height())
        gap = max(24, min(180, text_h // 4))
        return float(text_h + gap)

    def _tick(self) -> None:
        if not self._text.strip():
            return

        delta = self._speed * (self._timer.interval() / 1000.0)
        if self._direction in {"left", "up"}:
            self._offset -= delta
        else:
            self._offset += delta

        cycle = self._cycle_length()
        if cycle > 0:
            while self._offset <= -cycle:
                self._offset += cycle
            while self._offset >= cycle:
                self._offset -= cycle

        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        text = self._text.strip()
        if not text:
            painter.setPen(QPen(QColor("#666666")))
            painter.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter), "点击右键 → 编辑\n输入滚动文字")
            return

        font = self.font()
        if self._font_family:
            font.setFamily(self._font_family)
        font.setPointSize(self._font_size)
        painter.setFont(font)
        painter.setPen(QPen(QColor(self._color)))

        fm = QFontMetrics(font)
        rect = self.rect().adjusted(3, 3, -3, -3)

        if self._direction in {"left", "right"}:
            text_w = max(1, fm.horizontalAdvance(text))
            text_h = max(1, fm.height())
            gap = max(36, min(260, text_w // 3))
            cycle = text_w + gap
            baseline = rect.y() + (rect.height() - text_h) // 2 + fm.ascent()

            x = self._offset - cycle
            limit = rect.right() + cycle
            while x <= limit:
                painter.drawText(int(rect.x() + x), int(baseline), text)
                x += cycle
            return

        text_flags = int(Qt.AlignmentFlag.AlignHCenter | Qt.TextFlag.TextWordWrap)
        text_rect = fm.boundingRect(0, 0, max(1, rect.width()), 100000, text_flags, text)
        text_h = max(1, text_rect.height())
        gap = max(24, min(180, text_h // 4))
        cycle = text_h + gap

        y = self._offset - cycle
        limit = rect.bottom() + cycle
        while y <= limit:
            draw_rect = QRect(rect.x(), int(rect.y() + y), rect.width(), text_h)
            painter.drawText(draw_rect, text_flags, text)
            y += cycle


class _MarqueeEditPanel(QWidget):
    """滚动文字编辑面板。"""

    def __init__(self, props: dict, parent=None):
        super().__init__(parent)

        form = QFormLayout(self)
        form.setVerticalSpacing(10)

        self._text_edit = PlainTextEdit()
        self._text_edit.setPlainText(str(props.get("text", "")))
        self._text_edit.setFixedHeight(96)
        form.addRow("文本内容:", self._text_edit)

        self._font_picker = FluentFontPicker()
        self._font_picker.setCurrentFontFamily(str(props.get("font_family", "") or ""))
        form.addRow("字体:", self._font_picker)

        self._font_size = SpinBox()
        self._font_size.setRange(8, 220)
        self._font_size.setSuffix(" pt")
        self._font_size.setValue(int(props.get("font_size", 28) or 28))
        form.addRow("字体大小:", self._font_size)

        self._color_btn = ColorPickerButton(QColor(str(props.get("color", "#ffffff"))), "文字颜色")
        form.addRow("文字颜色:", self._color_btn)

        self._direction_combo = ComboBox()
        for label, value in _DIRECTION_ITEMS:
            self._direction_combo.addItem(label, userData=value)
        direction = str(props.get("direction", "left") or "left")
        direction_idx = next(
            (i for i in range(self._direction_combo.count()) if self._direction_combo.itemData(i) == direction),
            0,
        )
        self._direction_combo.setCurrentIndex(direction_idx)
        form.addRow("滚动方向:", self._direction_combo)

        self._speed_spin = SpinBox()
        self._speed_spin.setRange(1, 2000)
        self._speed_spin.setSuffix(" px/s")
        self._speed_spin.setValue(int(props.get("speed", 80) or 80))
        form.addRow("滚动速度:", self._speed_spin)

        self._w_spin = SpinBox()
        self._w_spin.setRange(1, 20)
        self._w_spin.setValue(int(props.get("grid_w", 4) or 4))
        form.addRow("横向格数:", self._w_spin)

        self._h_spin = SpinBox()
        self._h_spin.setRange(1, 20)
        self._h_spin.setValue(int(props.get("grid_h", 2) or 2))
        form.addRow("纵向格数:", self._h_spin)

        self._hint = QLabel("提示：上下滚动适合多行文字，左右滚动适合短句。")
        self._hint.setStyleSheet("color:#888;background:transparent;")
        self._hint.setWordWrap(True)
        form.addRow("", self._hint)

    def collect_props(self) -> dict:
        return {
            "text": self._text_edit.toPlainText(),
            "font_family": self._font_picker.currentFontFamily(),
            "font_size": self._font_size.value(),
            "color": self._color_btn.color.name(),
            "direction": self._direction_combo.currentData(),
            "speed": self._speed_spin.value(),
            "grid_w": self._w_spin.value(),
            "grid_h": self._h_spin.value(),
        }


class MarqueeTextWidget(WidgetBase):
    """滚动文字组件。"""

    WIDGET_TYPE = "marquee_text"
    WIDGET_NAME = "滚动文字"
    DELETABLE = True
    DEFAULT_W = 4
    DEFAULT_H = 2

    def __init__(self, config: WidgetConfig, services, parent=None):
        super().__init__(config, services, parent)

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 2, 4, 2)
        root.setSpacing(0)

        self._display = _MarqueeDisplay(self)
        root.addWidget(self._display, 1)

        self.refresh()

    def refresh(self) -> None:
        props = self.config.props
        self._display.apply_state(
            text=str(props.get("text", "")),
            font_family=str(props.get("font_family", "") or ""),
            font_size=int(props.get("font_size", 28) or 28),
            color=str(props.get("color", "#ffffff") or "#ffffff"),
            direction=str(props.get("direction", "left") or "left"),
            speed=int(props.get("speed", 80) or 80),
        )

    def get_edit_widget(self):
        props = dict(self.config.props)
        props["grid_w"] = self.config.grid_w
        props["grid_h"] = self.config.grid_h
        return _MarqueeEditPanel(props)

    def apply_props(self, props: dict) -> None:
        self.config.props.update(props)
        self.config.grid_w = max(1, int(props.get("grid_w", self.DEFAULT_W)))
        self.config.grid_h = max(1, int(props.get("grid_h", self.DEFAULT_H)))
        self.refresh()

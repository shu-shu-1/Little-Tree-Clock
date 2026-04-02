"""滚动文字组件 —— 支持上下/左右滚动与滚动速度"""
from __future__ import annotations

from time import monotonic

from PySide6.QtCore import Qt, QTimer, QRect
from PySide6.QtGui import QColor, QPainter, QPen, QFontMetrics, QPixmap
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

    _TEXT_MARGIN = 3

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setStyleSheet("background:transparent;")

        self._text = ""
        self._font_family = ""
        self._font_size = 28
        self._color = "#ffffff"
        self._direction = "left"
        self._speed = 80
        self._offset = 0.0

        self._cache_dirty = True
        self._cache_key: tuple | None = None
        self._content_pixmap = QPixmap()
        self._cycle = 0.0
        self._last_tick_ts = monotonic()

        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(24)
        self._timer.timeout.connect(self._tick)

    def _viewport_rect(self) -> QRect:
        return self.rect().adjusted(
            self._TEXT_MARGIN,
            self._TEXT_MARGIN,
            -self._TEXT_MARGIN,
            -self._TEXT_MARGIN,
        )

    def _mark_layout_dirty(self) -> None:
        self._cache_dirty = True
        self._cache_key = None
        self._content_pixmap = QPixmap()
        self._cycle = 0.0

    def _timer_interval_for_speed(self) -> int:
        # 控制每帧位移约 1.6px，低速降帧减少 CPU，高速保持流畅
        interval = int(round((1.6 * 1000.0) / max(1, self._speed)))
        return max(16, min(48, interval))

    def _sync_animation_timer(self, *, restart_clock: bool = False) -> None:
        should_run = bool(self._text.strip()) and self._speed > 0 and self.isVisible()
        if not should_run:
            if self._timer.isActive():
                self._timer.stop()
            return

        interval = self._timer_interval_for_speed()
        if self._timer.interval() != interval:
            self._timer.setInterval(interval)

        if restart_clock or not self._timer.isActive():
            self._last_tick_ts = monotonic()
        if not self._timer.isActive():
            self._timer.start()

    def _ensure_layout_cache(self) -> None:
        text = self._text.strip()
        if not text:
            self._mark_layout_dirty()
            return

        view = self._viewport_rect()
        if view.width() <= 0 or view.height() <= 0:
            self._mark_layout_dirty()
            return

        cache_key = (
            text,
            self._font_family,
            int(self._font_size),
            self._color,
            self._direction,
            view.width(),
        )
        if not self._cache_dirty and cache_key == self._cache_key:
            return

        font = self.font()
        if self._font_family:
            font.setFamily(self._font_family)
        font.setPointSize(self._font_size)
        fm = QFontMetrics(font)

        if self._direction in {"left", "right"}:
            text_w = max(1, fm.horizontalAdvance(text))
            text_h = max(1, fm.height())
            gap = max(36, min(260, text_w // 3))

            pixmap = QPixmap(text_w, text_h)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
            painter.setFont(font)
            painter.setPen(QPen(QColor(self._color)))
            painter.drawText(0, fm.ascent(), text)
            painter.end()

            self._content_pixmap = pixmap
            self._cycle = float(text_w + gap)
        else:
            text_flags = int(Qt.AlignmentFlag.AlignHCenter | Qt.TextFlag.TextWordWrap)
            text_rect = fm.boundingRect(0, 0, max(1, view.width()), 100000, text_flags, text)
            text_h = max(1, text_rect.height())
            gap = max(24, min(180, text_h // 4))

            pixmap = QPixmap(max(1, view.width()), text_h)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
            painter.setFont(font)
            painter.setPen(QPen(QColor(self._color)))
            painter.drawText(QRect(0, 0, pixmap.width(), pixmap.height()), text_flags, text)
            painter.end()

            self._content_pixmap = pixmap
            self._cycle = float(text_h + gap)

        self._cache_key = cache_key
        self._cache_dirty = False

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
        next_text = str(text)
        next_family = str(font_family or "")
        next_size = max(8, int(font_size))
        next_color = str(color or "#ffffff")
        next_direction = direction if direction in {"left", "right", "up", "down"} else "left"
        next_speed = max(1, int(speed))

        appearance_changed = (
            next_text != self._text
            or next_family != self._font_family
            or next_size != self._font_size
            or next_color != self._color
            or next_direction != self._direction
        )
        speed_changed = next_speed != self._speed

        if not appearance_changed and not speed_changed:
            self._sync_animation_timer()
            return

        self._text = next_text
        self._font_family = next_family
        self._font_size = next_size
        self._color = next_color
        self._direction = next_direction
        self._speed = next_speed

        if appearance_changed:
            self._offset = 0.0
            self._mark_layout_dirty()

        self._sync_animation_timer(restart_clock=appearance_changed or speed_changed)

        if appearance_changed or not self._timer.isActive():
            self.update()

    def _cycle_length(self) -> float:
        self._ensure_layout_cache()
        return self._cycle

    def _tick(self) -> None:
        if not self._text.strip():
            return

        if not self.isVisible():
            self._sync_animation_timer()
            return

        now = monotonic()
        elapsed = now - self._last_tick_ts
        self._last_tick_ts = now
        if elapsed <= 0:
            return

        # 切回窗口后可能累积很长时间，限制单帧位移避免视觉跳变。
        elapsed = min(elapsed, 0.12)

        cycle = self._cycle_length()
        if cycle <= 0:
            return

        delta = self._speed * elapsed
        if self._direction in {"left", "up"}:
            self._offset -= delta
        else:
            self._offset += delta

        if self._offset <= -cycle or self._offset >= cycle:
            self._offset = self._offset % cycle
            if self._direction in {"left", "up"} and self._offset > 0:
                self._offset -= cycle

        self.update(self._viewport_rect())

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        text = self._text.strip()
        if not text:
            painter.setPen(QPen(QColor("#666666")))
            painter.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter), "点击右键 → 编辑\n输入滚动文字")
            return

        self._ensure_layout_cache()
        if self._content_pixmap.isNull() or self._cycle <= 0:
            return

        rect = self._viewport_rect()
        if rect.width() <= 0 or rect.height() <= 0:
            return
        painter.setClipRect(rect)

        if self._direction in {"left", "right"}:
            y = rect.y() + (rect.height() - self._content_pixmap.height()) // 2
            x = self._offset - self._cycle
            limit = rect.right() + self._cycle
            while x <= limit:
                painter.drawPixmap(int(rect.x() + x), int(y), self._content_pixmap)
                x += self._cycle
            return

        x = rect.x() + (rect.width() - self._content_pixmap.width()) // 2
        y = self._offset - self._cycle
        limit = rect.bottom() + self._cycle
        while y <= limit:
            painter.drawPixmap(int(x), int(rect.y() + y), self._content_pixmap)
            y += self._cycle

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._mark_layout_dirty()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._sync_animation_timer(restart_clock=True)

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        if self._timer.isActive():
            self._timer.stop()


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

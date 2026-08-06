"""图形时钟组件 —— 模拟表盘，窗口化后圆形背景"""
from __future__ import annotations

import math
from typing import Any, Optional

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont,
    QRadialGradient, QLinearGradient, QConicalGradient,
)
from PySide6.QtWidgets import QWidget, QVBoxLayout, QFormLayout
from qfluentwidgets import CheckBox, ComboBox, SpinBox

from app.widgets.base_widget import WidgetBase, WidgetConfig
from app.utils.time_utils import now_in_zone
from app.services.i18n_service import tr

_STYLE_OPTIONS = [
    ("widget.clock_style.classic", "classic"),
    ("widget.clock_style.minimal", "minimal"),
    ("widget.clock_style.neon", "neon"),
    ("widget.clock_style.roman", "roman"),
    ("widget.clock_style.sunset", "sunset"),
    ("widget.clock_style.forest", "forest"),
    ("widget.clock_style.ice", "ice"),
]


class _AnalogClockEditPanel(QWidget):
    def __init__(self, props: dict, config, parent=None):
        super().__init__(parent)
        f = QFormLayout(self)
        f.setVerticalSpacing(10)

        self._clock_style = ComboBox()
        for key, val in _STYLE_OPTIONS:
            self._clock_style.addItem(tr(key), userData=val)
        cur_style = props.get("clock_style", "classic")
        idx = next(
            (i for i in range(self._clock_style.count())
             if self._clock_style.itemData(i) == cur_style),
            0,
        )
        self._clock_style.setCurrentIndex(idx)

        self._show_seconds = CheckBox()
        self._show_seconds.setChecked(props.get("show_seconds", True))

        self._show_numbers = CheckBox()
        self._show_numbers.setChecked(props.get("show_numbers", True))

        self._hand_color = ComboBox()
        for key, val in [("widget.hand_color.white", "#ffffff"), ("widget.hand_color.gold", "#c8a96e"), ("widget.hand_color.cyan", "#00e5ff")]:
            self._hand_color.addItem(tr(key), userData=val)
        cur = props.get("hand_color", "#ffffff")
        idx = next(
            (i for i in range(self._hand_color.count()) if self._hand_color.itemData(i) == cur),
            0,
        )
        self._hand_color.setCurrentIndex(idx)

        self._grid_w = SpinBox()
        self._grid_w.setRange(2, 20)
        self._grid_w.setSuffix(tr("widget.cfg.unit_cells"))
        self._grid_w.setValue(config.grid_w)

        self._grid_h = SpinBox()
        self._grid_h.setRange(2, 20)
        self._grid_h.setSuffix(tr("widget.cfg.unit_cells"))
        self._grid_h.setValue(config.grid_h)

        f.addRow(tr("widget.cfg.clock_style"), self._clock_style)
        f.addRow(tr("widget.cfg.show_seconds"), self._show_seconds)
        f.addRow(tr("widget.cfg.show_numbers"), self._show_numbers)
        f.addRow(tr("widget.cfg.hand_color"), self._hand_color)
        f.addRow(tr("widget.cfg.grid_w"), self._grid_w)
        f.addRow(tr("widget.cfg.grid_h"), self._grid_h)

    def collect_props(self) -> dict:
        return {
            "clock_style": self._clock_style.currentData() or "classic",
            "show_seconds": self._show_seconds.isChecked(),
            "show_numbers": self._show_numbers.isChecked(),
            "hand_color": self._hand_color.currentData() or "#ffffff",
            "grid_w": self._grid_w.value(),
            "grid_h": self._grid_h.value(),
        }


class AnalogClockWidget(WidgetBase):
    WIDGET_TYPE = "analog_clock"
    WIDGET_NAME = "图形时钟"
    DELETABLE = True
    MIN_W = 2
    MIN_H = 2
    DEFAULT_W = 3
    DEFAULT_H = 3

    DETACHED_BG_MODE = "solid"
    DETACHED_BG_SHAPE = "ellipse"
    DETACHED_BG_COLOR = "rgba(30,30,30,200)"
    DETACHED_BORDER_COLOR = "rgba(255,255,255,40)"
    DETACHED_BG_RADIUS = 0
    DETACHED_BORDER_WIDTH = 2

    _NUMBERS_ARABIC = ["12", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11"]
    _NUMBERS_ROMAN = ["XII", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI"]

    def _clock_colors(self) -> dict:
        dark = self._is_dark()
        if dark:
            return {
                "tick": QColor(255, 255, 255, 140),
                "tick_minor": QColor(255, 255, 255, 80),
                "number": QColor(255, 255, 255, 200),
                "hand": QColor(255, 255, 255, 255),
                "bg_grad_center": QColor(60, 60, 60, 40),
                "bg_grad_edge": QColor(30, 30, 30, 20),
                "ring_line": QColor(255, 255, 255, 60),
                "ring_line_major": QColor(255, 255, 255, 180),
            }
        return {
            "tick": QColor(0, 0, 0, 120),
            "tick_minor": QColor(0, 0, 0, 60),
            "number": QColor(0, 0, 0, 180),
            "hand": QColor(30, 30, 30, 255),
            "bg_grad_center": QColor(200, 200, 200, 30),
            "bg_grad_edge": QColor(180, 180, 180, 15),
            "ring_line": QColor(0, 0, 0, 50),
            "ring_line_major": QColor(0, 0, 0, 140),
        }

    def _resolve_hand_color(self, p: dict) -> QColor:
        raw = p.get("hand_color", "")
        if raw:
            return QColor(raw)
        cc = self._clock_colors()
        return cc["hand"]

    def __init__(self, config: WidgetConfig, services: dict[str, Any], parent=None):
        super().__init__(config, services)
        self._timezone: str = services.get("timezone", "local")
        self.setMinimumSize(40, 40)

    def refresh(self) -> None:
        self.update()

    # ------------------------------------------------------------------ #
    # Style painters
    # ------------------------------------------------------------------ #

    def _paint_classic(self, painter: QPainter, cx: float, cy: float, r: float,
                       p: dict, h: int, m: int, s: int) -> None:
        hand_color = self._resolve_hand_color(p)
        cc = self._clock_colors()

        painter.setPen(Qt.PenStyle.NoPen)
        grad = QRadialGradient(cx, cy, r)
        grad.setColorAt(0.0, cc["bg_grad_center"])
        grad.setColorAt(1.0, cc["bg_grad_edge"])
        painter.setBrush(QBrush(grad))
        painter.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

        pen = QPen(cc["tick"], 1.5)
        painter.setPen(pen)
        for i in range(60):
            angle = math.radians(i * 6 - 90)
            if i % 5 == 0:
                inner = r * 0.82
                pen.setWidth(2)
            else:
                inner = r * 0.88
                pen.setWidth(1)
            painter.setPen(pen)
            outer = r * 0.92
            painter.drawLine(
                cx + inner * math.cos(angle),
                cy + inner * math.sin(angle),
                cx + outer * math.cos(angle),
                cy + outer * math.sin(angle),
            )

        if p.get("show_numbers", True):
            font = QFont()
            font.setPointSize(max(8, int(r * 0.16)))
            painter.setFont(font)
            painter.setPen(cc["number"])
            for i, num in enumerate(self._NUMBERS_ARABIC):
                angle = math.radians(i * 30 - 90)
                nr = r * 0.72
                tx = cx + nr * math.cos(angle)
                ty = cy + nr * math.sin(angle)
                painter.drawText(
                    QRectF(tx - r * 0.1, ty - r * 0.08, r * 0.2, r * 0.16),
                    Qt.AlignmentFlag.AlignCenter,
                    num,
                )

        self._draw_hands(painter, cx, cy, r, h, m, s, p, hand_color,
                         hour_len=0.5, min_len=0.7, sec_len=0.78,
                         sec_color=QColor(255, 80, 80))

    def _paint_minimal(self, painter: QPainter, cx: float, cy: float, r: float,
                       p: dict, h: int, m: int, s: int) -> None:
        hand_color = self._resolve_hand_color(p)
        cc = self._clock_colors()

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        pen = QPen(cc["ring_line"], 1.5)
        painter.setPen(pen)
        painter.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

        for i in range(12):
            angle = math.radians(i * 30 - 90)
            if i % 3 == 0:
                inner = r * 0.82
                pen.setWidth(2.5)
                pen.setColor(cc["ring_line_major"])
            else:
                inner = r * 0.88
                pen.setWidth(1)
                pen.setColor(cc["tick_minor"])
            painter.setPen(pen)
            outer = r * 0.92
            painter.drawLine(
                cx + inner * math.cos(angle),
                cy + inner * math.sin(angle),
                cx + outer * math.cos(angle),
                cy + outer * math.sin(angle),
            )

        self._draw_hands(painter, cx, cy, r, h, m, s, p, hand_color,
                         hour_len=0.48, min_len=0.68, sec_len=0.76,
                         sec_color=QColor(255, 80, 80))

    def _paint_neon(self, painter: QPainter, cx: float, cy: float, r: float,
                    p: dict, h: int, m: int, s: int) -> None:
        hand_color = self._resolve_hand_color(p)
        dark = self._is_dark()
        neon_cyan = QColor(0, 230, 255, 200)
        neon_pink = QColor(255, 0, 200, 200)
        neon_green = QColor(0, 255, 140, 200)

        painter.setPen(Qt.PenStyle.NoPen)
        grad = QRadialGradient(cx, cy, r)
        if dark:
            grad.setColorAt(0.0, QColor(10, 10, 40, 120))
            grad.setColorAt(0.7, QColor(5, 5, 30, 80))
            grad.setColorAt(1.0, QColor(0, 0, 20, 40))
        else:
            grad.setColorAt(0.0, QColor(200, 230, 255, 60))
            grad.setColorAt(0.7, QColor(180, 220, 250, 40))
            grad.setColorAt(1.0, QColor(160, 210, 240, 20))
        painter.setBrush(QBrush(grad))
        painter.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

        pen = QPen(neon_cyan, 2)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

        for i in range(60):
            angle = math.radians(i * 6 - 90)
            if i % 5 == 0:
                inner = r * 0.80
                pen.setWidth(2.5)
                pen.setColor(neon_cyan)
            else:
                inner = r * 0.88
                pen.setWidth(1)
                pen.setColor(QColor(0, 230, 255, 80))
            painter.setPen(pen)
            outer = r * 0.92
            painter.drawLine(
                cx + inner * math.cos(angle),
                cy + inner * math.sin(angle),
                cx + outer * math.cos(angle),
                cy + outer * math.sin(angle),
            )

        if p.get("show_numbers", True):
            font = QFont()
            font.setPointSize(max(8, int(r * 0.15)))
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(neon_cyan)
            for i, num in enumerate(self._NUMBERS_ARABIC):
                angle = math.radians(i * 30 - 90)
                nr = r * 0.68
                tx = cx + nr * math.cos(angle)
                ty = cy + nr * math.sin(angle)
                painter.drawText(
                    QRectF(tx - r * 0.12, ty - r * 0.08, r * 0.24, r * 0.16),
                    Qt.AlignmentFlag.AlignCenter,
                    num,
                )

        h_angle = math.radians((h + m / 60) * 30 - 90)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawLine(
            cx, cy,
            cx + r * 0.5 * math.cos(h_angle),
            cy + r * 0.5 * math.sin(h_angle),
        )

        m_angle = math.radians((m + s / 60) * 6 - 90)
        pen.setWidth(max(2, r * 0.025))
        painter.setPen(pen)
        painter.drawLine(
            cx, cy,
            cx + r * 0.68 * math.cos(m_angle),
            cy + r * 0.68 * math.sin(m_angle),
        )

        if p.get("show_seconds", True):
            s_angle = math.radians(s * 6 - 90)
            pen.setWidth(max(1.5, r * 0.012))
            pen.setColor(neon_green)
            painter.setPen(pen)
            painter.drawLine(
                cx, cy,
                cx + r * 0.78 * math.cos(s_angle),
                cy + r * 0.78 * math.sin(s_angle),
            )

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(neon_cyan))
        painter.drawEllipse(QRectF(cx - 4, cy - 4, 8, 8))

    def _paint_roman(self, painter: QPainter, cx: float, cy: float, r: float,
                     p: dict, h: int, m: int, s: int) -> None:
        hand_color = self._resolve_hand_color(p)
        gold = QColor(200, 169, 110, 220)

        painter.setPen(Qt.PenStyle.NoPen)
        grad = QRadialGradient(cx, cy, r)
        if self._is_dark():
            grad.setColorAt(0.0, QColor(50, 45, 35, 100))
            grad.setColorAt(0.8, QColor(30, 28, 22, 60))
            grad.setColorAt(1.0, QColor(20, 18, 14, 30))
        else:
            grad.setColorAt(0.0, QColor(255, 245, 220, 60))
            grad.setColorAt(0.8, QColor(255, 240, 210, 40))
            grad.setColorAt(1.0, QColor(255, 235, 200, 20))
        painter.setBrush(QBrush(grad))
        painter.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

        pen_border = QPen(gold, 2)
        painter.setPen(pen_border)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))
        inner_r = r * 0.95
        painter.drawEllipse(QRectF(cx - inner_r, cy - inner_r, inner_r * 2, inner_r * 2))

        pen = QPen(gold, 1.5)
        painter.setPen(pen)
        for i in range(60):
            angle = math.radians(i * 6 - 90)
            if i % 5 == 0:
                inner = r * 0.78
                pen.setWidth(2.5)
                pen.setColor(gold)
            else:
                inner = r * 0.88
                pen.setWidth(0.8)
                pen.setColor(QColor(200, 169, 110, 80))
            painter.setPen(pen)
            outer = r * 0.92
            painter.drawLine(
                cx + inner * math.cos(angle),
                cy + inner * math.sin(angle),
                cx + outer * math.cos(angle),
                cy + outer * math.sin(angle),
            )

        if p.get("show_numbers", True):
            font = QFont("Times New Roman")
            font.setPointSize(max(6, int(r * 0.10)))
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(gold)
            for i, num in enumerate(self._NUMBERS_ROMAN):
                angle = math.radians(i * 30 - 90)
                nr = r * 0.65
                tx = cx + nr * math.cos(angle)
                ty = cy + nr * math.sin(angle)
                painter.drawText(
                    QRectF(tx - r * 0.18, ty - r * 0.08, r * 0.36, r * 0.16),
                    Qt.AlignmentFlag.AlignCenter,
                    num,
                )

        self._draw_hands(painter, cx, cy, r, h, m, s, p, hand_color,
                         hour_len=0.48, min_len=0.65, sec_len=0.76,
                         sec_color=QColor(200, 80, 60))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(gold))
        painter.drawEllipse(QRectF(cx - 4, cy - 4, 8, 8))

    def _paint_sunset(self, painter: QPainter, cx: float, cy: float, r: float,
                      p: dict, h: int, m: int, s: int) -> None:
        hand_color = self._resolve_hand_color(p)
        dark = self._is_dark()

        painter.setPen(Qt.PenStyle.NoPen)
        grad = QConicalGradient(cx, cy, 0)
        if dark:
            grad.setColorAt(0.0, QColor(255, 94, 58, 80))
            grad.setColorAt(0.25, QColor(255, 42, 109, 70))
            grad.setColorAt(0.5, QColor(168, 50, 219, 70))
            grad.setColorAt(0.75, QColor(255, 140, 50, 70))
            grad.setColorAt(1.0, QColor(255, 94, 58, 80))
        else:
            grad.setColorAt(0.0, QColor(255, 94, 58, 40))
            grad.setColorAt(0.25, QColor(255, 42, 109, 35))
            grad.setColorAt(0.5, QColor(168, 50, 219, 35))
            grad.setColorAt(0.75, QColor(255, 140, 50, 35))
            grad.setColorAt(1.0, QColor(255, 94, 58, 40))
        painter.setBrush(QBrush(grad))
        painter.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

        inner_grad = QRadialGradient(cx, cy, r * 0.4)
        if dark:
            inner_grad.setColorAt(0.0, QColor(255, 200, 100, 60))
            inner_grad.setColorAt(1.0, QColor(255, 94, 58, 0))
        else:
            inner_grad.setColorAt(0.0, QColor(255, 200, 100, 30))
            inner_grad.setColorAt(1.0, QColor(255, 94, 58, 0))
        painter.setBrush(QBrush(inner_grad))
        painter.drawEllipse(QRectF(cx - r * 0.4, cy - r * 0.4, r * 0.8, r * 0.8))

        pen = QPen(QColor(255, 200, 150, 180 if dark else 100), 1.5)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

        for i in range(60):
            angle = math.radians(i * 6 - 90)
            if i % 5 == 0:
                inner = r * 0.82
                pen.setWidth(2)
                pen.setColor(QColor(255, 200, 150, 200 if dark else 120))
            else:
                inner = r * 0.88
                pen.setWidth(1)
                pen.setColor(QColor(255, 180, 130, 100 if dark else 60))
            painter.setPen(pen)
            outer = r * 0.92
            painter.drawLine(
                cx + inner * math.cos(angle),
                cy + inner * math.sin(angle),
                cx + outer * math.cos(angle),
                cy + outer * math.sin(angle),
            )

        if p.get("show_numbers", True):
            font = QFont()
            font.setPointSize(max(8, int(r * 0.15)))
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QColor(255, 230, 200, 230 if dark else 180))
            for i, num in enumerate(self._NUMBERS_ARABIC):
                angle = math.radians(i * 30 - 90)
                nr = r * 0.72
                tx = cx + nr * math.cos(angle)
                ty = cy + nr * math.sin(angle)
                painter.drawText(
                    QRectF(tx - r * 0.1, ty - r * 0.08, r * 0.2, r * 0.16),
                    Qt.AlignmentFlag.AlignCenter,
                    num,
                )

        self._draw_hands(painter, cx, cy, r, h, m, s, p, hand_color,
                         hour_len=0.5, min_len=0.7, sec_len=0.78,
                         sec_color=QColor(255, 100, 60))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(255, 200, 100)))
        painter.drawEllipse(QRectF(cx - 4, cy - 4, 8, 8))

    def _paint_forest(self, painter: QPainter, cx: float, cy: float, r: float,
                      p: dict, h: int, m: int, s: int) -> None:
        hand_color = self._resolve_hand_color(p)
        dark = self._is_dark()
        leaf_green = QColor(100, 200, 80, 200)
        dark_green = QColor(20, 60, 20, 160)

        painter.setPen(Qt.PenStyle.NoPen)
        grad = QRadialGradient(cx, cy, r)
        if dark:
            grad.setColorAt(0.0, QColor(30, 80, 30, 100))
            grad.setColorAt(0.6, QColor(20, 60, 20, 80))
            grad.setColorAt(1.0, QColor(10, 40, 10, 50))
        else:
            grad.setColorAt(0.0, QColor(200, 240, 200, 50))
            grad.setColorAt(0.6, QColor(180, 230, 180, 35))
            grad.setColorAt(1.0, QColor(160, 220, 160, 20))
        painter.setBrush(QBrush(grad))
        painter.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

        pen = QPen(leaf_green, 2)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

        for i in range(12):
            angle = math.radians(i * 30 - 90)
            mid_r = r * 0.87
            leaf_r = r * 0.06
            leaf_cx = cx + mid_r * math.cos(angle)
            leaf_cy = cy + mid_r * math.sin(angle)
            painter.save()
            painter.translate(leaf_cx, leaf_cy)
            painter.rotate(i * 30)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(leaf_green))
            painter.drawEllipse(QRectF(-leaf_r, -leaf_r * 0.5, leaf_r * 2, leaf_r))
            painter.restore()

        for i in range(60):
            angle = math.radians(i * 6 - 90)
            if i % 5 != 0:
                pen2 = QPen(QColor(100, 200, 80, 80), 0.8)
                painter.setPen(pen2)
                inner = r * 0.90
                outer = r * 0.93
                painter.drawLine(
                    cx + inner * math.cos(angle),
                    cy + inner * math.sin(angle),
                    cx + outer * math.cos(angle),
                    cy + outer * math.sin(angle),
                )

        if p.get("show_numbers", True):
            font = QFont()
            font.setPointSize(max(8, int(r * 0.15)))
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QColor(180, 240, 160, 230 if dark else 160))
            for i, num in enumerate(self._NUMBERS_ARABIC):
                angle = math.radians(i * 30 - 90)
                nr = r * 0.72
                tx = cx + nr * math.cos(angle)
                ty = cy + nr * math.sin(angle)
                painter.drawText(
                    QRectF(tx - r * 0.1, ty - r * 0.08, r * 0.2, r * 0.16),
                    Qt.AlignmentFlag.AlignCenter,
                    num,
                )

        self._draw_hands(painter, cx, cy, r, h, m, s, p, hand_color,
                         hour_len=0.48, min_len=0.65, sec_len=0.78,
                         sec_color=QColor(100, 220, 80))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(leaf_green))
        painter.drawEllipse(QRectF(cx - 4, cy - 4, 8, 8))

    def _paint_ice(self, painter: QPainter, cx: float, cy: float, r: float,
                   p: dict, h: int, m: int, s: int) -> None:
        hand_color = self._resolve_hand_color(p)
        dark = self._is_dark()
        ice_blue = QColor(130, 200, 255, 200)
        deep_ice = QColor(40, 80, 140, 180)

        painter.setPen(Qt.PenStyle.NoPen)
        grad = QRadialGradient(cx, cy, r)
        if dark:
            grad.setColorAt(0.0, QColor(60, 120, 180, 100))
            grad.setColorAt(0.5, QColor(30, 70, 130, 80))
            grad.setColorAt(1.0, QColor(10, 30, 70, 50))
        else:
            grad.setColorAt(0.0, QColor(200, 230, 255, 50))
            grad.setColorAt(0.5, QColor(180, 220, 250, 35))
            grad.setColorAt(1.0, QColor(160, 210, 240, 20))
        painter.setBrush(QBrush(grad))
        painter.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

        pen = QPen(ice_blue, 2)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

        pen_inner = QPen(QColor(130, 200, 255, 60 if dark else 30), 1)
        painter.setPen(pen_inner)
        painter.drawEllipse(QRectF(cx - r * 0.75, cy - r * 0.75, r * 1.5, r * 1.5))

        for i in range(60):
            angle = math.radians(i * 6 - 90)
            if i % 5 == 0:
                inner = r * 0.82
                pen.setWidth(2.5)
                pen.setColor(ice_blue)
                painter.setPen(pen)
                outer = r * 0.92
                painter.drawLine(
                    cx + inner * math.cos(angle),
                    cy + inner * math.sin(angle),
                    cx + outer * math.cos(angle),
                    cy + outer * math.sin(angle),
                )
                cross_inner = r * 0.92
                cross_outer = r * 0.97
                pen2 = QPen(QColor(130, 200, 255, 100), 1.5)
                painter.setPen(pen2)
                painter.drawLine(
                    cx + cross_inner * math.cos(angle),
                    cy + cross_inner * math.sin(angle),
                    cx + cross_outer * math.cos(angle),
                    cy + cross_outer * math.sin(angle),
                )
            else:
                pen3 = QPen(QColor(130, 200, 255, 60), 0.8)
                painter.setPen(pen3)
                inner = r * 0.90
                outer = r * 0.93
                painter.drawLine(
                    cx + inner * math.cos(angle),
                    cy + inner * math.sin(angle),
                    cx + outer * math.cos(angle),
                    cy + outer * math.sin(angle),
                )

        if p.get("show_numbers", True):
            font = QFont()
            font.setPointSize(max(8, int(r * 0.15)))
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QColor(200, 230, 255, 240 if dark else 180))
            for i, num in enumerate(self._NUMBERS_ARABIC):
                angle = math.radians(i * 30 - 90)
                nr = r * 0.72
                tx = cx + nr * math.cos(angle)
                ty = cy + nr * math.sin(angle)
                painter.drawText(
                    QRectF(tx - r * 0.1, ty - r * 0.08, r * 0.2, r * 0.16),
                    Qt.AlignmentFlag.AlignCenter,
                    num,
                )

        self._draw_hands(painter, cx, cy, r, h, m, s, p, hand_color,
                         hour_len=0.48, min_len=0.68, sec_len=0.78,
                         sec_color=QColor(100, 180, 255))

        painter.setPen(Qt.PenStyle.NoPen)
        grad_dot = QRadialGradient(cx, cy, 5)
        grad_dot.setColorAt(0.0, QColor(255, 255, 255, 255))
        grad_dot.setColorAt(1.0, QColor(130, 200, 255, 200))
        painter.setBrush(QBrush(grad_dot))
        painter.drawEllipse(QRectF(cx - 5, cy - 5, 10, 10))

    # ------------------------------------------------------------------ #
    # Shared hand drawing
    # ------------------------------------------------------------------ #

    def _draw_hands(self, painter: QPainter, cx: float, cy: float, r: float,
                    h: int, m: int, s: int, p: dict, hand_color: QColor,
                    hour_len: float, min_len: float, sec_len: float,
                    sec_color: QColor) -> None:
        h_angle = math.radians((h + m / 60) * 30 - 90)
        pen = QPen(hand_color, max(2, r * 0.04))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawLine(
            cx, cy,
            cx + r * hour_len * math.cos(h_angle),
            cy + r * hour_len * math.sin(h_angle),
        )

        m_angle = math.radians((m + s / 60) * 6 - 90)
        pen.setWidth(max(1.5, r * 0.025))
        painter.setPen(pen)
        painter.drawLine(
            cx, cy,
            cx + r * min_len * math.cos(m_angle),
            cy + r * min_len * math.sin(m_angle),
        )

        if p.get("show_seconds", True):
            s_angle = math.radians(s * 6 - 90)
            pen.setWidth(max(1, r * 0.012))
            pen.setColor(sec_color)
            painter.setPen(pen)
            painter.drawLine(
                cx, cy,
                cx + r * sec_len * math.cos(s_angle),
                cy + r * sec_len * math.sin(s_angle),
            )

    # ------------------------------------------------------------------ #

    def paintEvent(self, event) -> None:
        p = self.config.props
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        side = min(self.width(), self.height())
        cx = self.width() / 2
        cy = self.height() / 2
        r = side / 2 - 4

        if r <= 0:
            return

        dt = now_in_zone(self._timezone)
        h = dt.hour % 12
        m = dt.minute
        s = dt.second

        style = p.get("clock_style", "classic")
        dispatch = {
            "classic": self._paint_classic,
            "minimal": self._paint_minimal,
            "neon": self._paint_neon,
            "roman": self._paint_roman,
            "sunset": self._paint_sunset,
            "forest": self._paint_forest,
            "ice": self._paint_ice,
        }
        painter_fn = dispatch.get(style, self._paint_classic)
        painter_fn(painter, cx, cy, r, p, h, m, s)

        painter.end()

    def get_edit_widget(self) -> Optional[QWidget]:
        return _AnalogClockEditPanel(self.config.props, self.config)

    def apply_props(self, props: dict) -> None:
        self.config.grid_w = props.pop("grid_w", self.config.grid_w)
        self.config.grid_h = props.pop("grid_h", self.config.grid_h)
        self.config.props.update(props)
        self.refresh()

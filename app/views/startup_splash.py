"""应用启动画面。

仅在主程序启动阶段短暂展示，用于给用户即时反馈。设计要点：
- 始终保持深色卡片外观（与系统主题解耦），保证启动瞬间视觉稳定；
- 图标下方带柔和呼吸光晕，进度条改为流动高光，避免呆板；
- 普通模式展示当前步骤状态行，详情模式列出全部步骤与状态标记；
- 动画均由轻量 QTimer 驱动，渲染开销极低。
"""
from __future__ import annotations

import math

from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QPointF,
    QRectF,
    Qt,
    QTimer,
)
from PySide6.QtGui import (
    QColor,
    QLinearGradient,
    QPainter,
    QPaintEvent,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from app.services.i18n_service import tr

# 主题色：与原启动页保持一致的青蓝色调
_ACCENT = QColor("#4cc2ff")
_ACCENT_SOFT = QColor("#7fd4ff")

# 步骤定义：(key, i18n key)。key 被 main.py / window.py 调用，请勿改名。
_STEPS: list[tuple[str, str]] = [
    ("init", "splash.step.init"),
    ("settings", "splash.step.settings"),
    ("services", "splash.step.services"),
    ("views", "splash.step.views"),
    ("window", "splash.step.window"),
    ("plugins", "splash.step.plugins"),
]

_CARD_RADIUS = 16


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


class _GlowIcon(QWidget):
    """带呼吸光晕的应用图标。"""

    def __init__(self, icon_path: str, icon_size: int = 72, parent=None):
        super().__init__(parent)
        self._icon_size = icon_size
        self._phase = 0.0

        pixmap = QPixmap(icon_path)
        if not pixmap.isNull():
            self._pixmap: QPixmap | None = pixmap.scaled(
                icon_size,
                icon_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        else:
            self._pixmap = None

        pad = 26
        self.setFixedSize(icon_size + pad * 2, icon_size + pad * 2)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)

    def start(self) -> None:
        if not self._timer.isActive():
            self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def _tick(self) -> None:
        self._phase = (self._phase + 0.08) % (math.pi * 2)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)

        center_x = self.width() / 2.0
        center_y = self.height() / 2.0

        # 呼吸光晕：半径与透明度随相位正弦变化
        pulse = 0.5 - 0.5 * math.cos(self._phase)  # 0..1
        glow_radius = self._icon_size * 0.92 + pulse * 10.0
        gradient = QRadialGradient(center_x, center_y, glow_radius)
        core = QColor(_ACCENT)
        core.setAlpha(int(34 + pulse * 70))
        gradient.setColorAt(0.0, core)
        edge = QColor(_ACCENT)
        edge.setAlpha(0)
        gradient.setColorAt(1.0, edge)
        painter.setBrush(gradient)
        painter.drawEllipse(QPointF(center_x, center_y), glow_radius, glow_radius)

        # 细高光环，强化“焦点”感
        ring = QColor(_ACCENT_SOFT)
        ring.setAlpha(int(20 + pulse * 26))
        painter.setBrush(ring)
        ring_radius = self._icon_size * 0.62
        painter.drawEllipse(QPointF(center_x, center_y), ring_radius, ring_radius)

        if self._pixmap is not None and not self._pixmap.isNull():
            painter.drawPixmap(
                int(center_x - self._pixmap.width() / 2),
                int(center_y - self._pixmap.height() / 2),
                self._pixmap,
            )


class _ShimmerBar(QWidget):
    """流光进度条：未确定时为流动高光，确定时为填充进度。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._offset = 0.0
        self._total = 0
        self._value = 0
        self._determinate = False
        self.setFixedHeight(4)

        self._timer = QTimer(self)
        self._timer.setInterval(28)
        self._timer.timeout.connect(self._tick)

    def start(self) -> None:
        if not self._timer.isActive():
            self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def set_progress(self, total: int, value: int) -> None:
        self._determinate = total > 0
        self._total = max(1, total)
        self._value = max(0, value)
        self.update()

    def _tick(self) -> None:
        self._offset = (self._offset + 0.045) % 1.0
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)

        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        # 轨道
        track = QColor(255, 255, 255, 22)
        painter.setBrush(track)
        painter.drawRoundedRect(rect, 2.0, 2.0)

        if self._determinate:
            fill_w = rect.width() * (self._value / self._total)
            if fill_w > 1.0:
                grad = QLinearGradient(rect.left(), 0, rect.left() + fill_w, 0)
                grad.setColorAt(0.0, QColor(_ACCENT_SOFT))
                grad.setColorAt(1.0, QColor(_ACCENT))
                painter.setBrush(grad)
                painter.drawRoundedRect(
                    QRectF(rect.left(), rect.top(), fill_w, rect.height()),
                    2.0,
                    2.0,
                )
        else:
            # 流动高光段
            width = rect.width()
            seg = max(40.0, width * 0.42)
            span = width + seg
            x0 = rect.left() - seg + span * self._offset
            grad = QLinearGradient(x0, 0, x0 + seg, 0)
            grad.setColorAt(0.0, QColor(_ACCENT.red(), _ACCENT.green(), _ACCENT.blue(), 0))
            grad.setColorAt(0.5, QColor(_ACCENT.red(), _ACCENT.green(), _ACCENT.blue(), 235))
            grad.setColorAt(1.0, QColor(_ACCENT.red(), _ACCENT.green(), _ACCENT.blue(), 0))
            painter.setBrush(grad)
            # 用轨道区域裁剪，避免高光溢出圆角
            painter.save()
            path_clip = None
            try:
                from PySide6.QtGui import QPainterPath

                path_clip = QPainterPath()
                path_clip.addRoundedRect(rect, 2.0, 2.0)
                painter.setClipPath(path_clip)
            except Exception:
                pass
            painter.drawRect(QRectF(x0, rect.top(), seg, rect.height()))
            painter.restore()


class StartupSplash(QWidget):
    """应用启动画面窗口。"""

    _STEPS = _STEPS

    def __init__(self, show_detail: bool = False):
        super().__init__()
        self._show_detail = show_detail
        self._current_step = -1
        self._step_labels: list[QLabel] = []
        self._entrance_anim: QPropertyAnimation | None = None

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        height = 340 if show_detail else 204
        self.setFixedSize(320, height)

        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            self.move(
                geo.x() + (geo.width() - self.width()) // 2,
                geo.y() + (geo.height() - self.height()) // 2,
            )

        self._build_ui()

    # ── UI 构建 ─────────────────────────────────────────────────────────── #

    def _build_ui(self) -> None:
        from app.constants import APP_NAME, APP_VERSION, ICON_PATH, VERSION_TYPE

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(0)

        self._icon = _GlowIcon(ICON_PATH, icon_size=72, parent=self)
        layout.addWidget(self._icon, alignment=Qt.AlignmentFlag.AlignHCenter)

        layout.addSpacing(6)

        self._name_label = QLabel(APP_NAME, self)
        self._name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._name_label.setStyleSheet(
            "font-size:18px;font-weight:600;color:#ffffff;background:transparent;border:none;"
            "letter-spacing:1px;"
        )
        layout.addWidget(self._name_label)

        self._version_label = QLabel(
            f"v{APP_VERSION} · {VERSION_TYPE}", self
        )
        self._version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._version_label.setStyleSheet(
            "font-size:11px;color:rgba(255,255,255,0.42);background:transparent;border:none;"
            "letter-spacing:0.5px;padding-top:2px;"
        )
        layout.addWidget(self._version_label)

        if self._show_detail:
            layout.addSpacing(14)
            for _key, text in self._STEPS:
                lbl = QLabel(self)
                lbl.setTextFormat(Qt.TextFormat.RichText)
                lbl.setAlignment(
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                )
                lbl.setContentsMargins(10, 1, 0, 1)
                lbl.setStyleSheet(
                    "font-size:12px;background:transparent;border:none;padding:1px 0;"
                )
                layout.addWidget(lbl)
                self._step_labels.append(lbl)
            layout.addSpacing(12)
        else:
            layout.addSpacing(10)
            self._status_label = QLabel(self)
            self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._status_label.setStyleSheet(
                "font-size:12px;color:rgba(255,255,255,0.55);background:transparent;border:none;"
            )
            layout.addWidget(self._status_label)

        layout.addStretch(1)

        self._progress = _ShimmerBar(self)
        layout.addWidget(self._progress)

        # 初始步骤状态
        self._apply_step_visual(-1)

    # ── 状态文案 ─────────────────────────────────────────────────────────── #

    def _step_rich(self, index: int, current: int) -> str:
        text = _escape(tr(self._STEPS[index][1]))
        if index < current:
            return (
                f'<span style="color:{_ACCENT_SOFT.name()}">✓</span>'
                f'&nbsp;&nbsp;<span style="color:rgba(255,255,255,0.42)">{text}</span>'
            )
        if index == current:
            return (
                f'<span style="color:{_ACCENT.name()}">●</span>'
                f'&nbsp;&nbsp;<span style="color:#e8f6ff;font-weight:500">{text}</span>'
            )
        return (
            '<span style="color:rgba(255,255,255,0.22)">○</span>'
            f'&nbsp;&nbsp;<span style="color:rgba(255,255,255,0.26)">{text}</span>'
        )

    def _apply_step_visual(self, current: int) -> None:
        if self._show_detail:
            for i, lbl in enumerate(self._step_labels):
                lbl.setText(self._step_rich(i, max(0, current)))
        else:
            self._status_label.setText(tr("splash.starting"))

    # ── 背景 ─────────────────────────────────────────────────────────────── #

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)

        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        # 深色渐变卡片
        gradient = QLinearGradient(0, 0, 0, self.height())
        gradient.setColorAt(0.0, QColor(48, 50, 60, 252))
        gradient.setColorAt(1.0, QColor(22, 24, 30, 252))
        painter.setBrush(gradient)
        painter.drawRoundedRect(rect, _CARD_RADIUS, _CARD_RADIUS)

        # 细描边
        painter.setBrush(Qt.GlobalColor.transparent)
        painter.setPen(QColor(255, 255, 255, 30))
        painter.drawRoundedRect(rect, _CARD_RADIUS, _CARD_RADIUS)

    # ── 公共接口 ─────────────────────────────────────────────────────────── #

    def set_step(self, step_key: str) -> None:
        idx = next(
            (i for i, (k, _) in enumerate(self._STEPS) if k == step_key), -1
        )
        if idx < 0:
            return
        self._current_step = idx
        self._apply_step_visual(idx)

        total = len(self._STEPS)
        self._progress.set_progress(total, idx + 1)
        QApplication.processEvents()

    def present(self) -> None:
        self._icon.start()
        self._progress.start()
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()

        self._entrance_anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._entrance_anim.setDuration(220)
        self._entrance_anim.setStartValue(0.0)
        self._entrance_anim.setEndValue(1.0)
        self._entrance_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._entrance_anim.start()

        QApplication.processEvents()

    def dismiss(self) -> None:
        self._icon.stop()
        self._progress.stop()
        if self._entrance_anim is not None:
            self._entrance_anim.stop()
        self.close()

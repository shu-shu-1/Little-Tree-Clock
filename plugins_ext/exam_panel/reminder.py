"""考试面板插件 — 提醒叠加层

支持两种模式：
  fullscreen  —  全屏半透明叠加层 + 大字提醒文字，可选闪烁
  voice       —  调用 TTS 朗读提醒（Windows SAPI / pyttsx3）
  both        —  同时执行以上两种
"""
from __future__ import annotations

import threading
from typing import Optional

from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, Property
from PySide6.QtGui import QColor, QPainter, QFont
from PySide6.QtWidgets import QWidget, QApplication, QVBoxLayout, QLabel, QHBoxLayout
from qfluentwidgets import PushButton, FluentIcon as FIF, TitleLabel, SubtitleLabel


# ─────────────────────────────────────────────────────────────────────────── #
# 全屏提醒叠加层
# ─────────────────────────────────────────────────────────────────────────── #

class ExamReminderOverlay(QWidget):
    """
    全屏置顶半透明遮罩，展示考试提醒。

    Parameters
    ----------
    subject_name : str   科目名称
    message      : str   提醒正文
    flash        : bool  是否闪烁
    color        : str   科目颜色（十六进制）
    """

    def __init__(
        self,
        subject_name: str = "",
        message: str = "",
        flash: bool = False,
        color: str = "#2196F3",
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent, Qt.WindowType.WindowStaysOnTopHint |
                         Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

        # 铺满整个主屏幕
        screen = QApplication.primaryScreen()
        if screen:
            self.setGeometry(screen.geometry())

        self._flash = flash
        self._flash_visible = True
        self._color = QColor(color)
        self._backdrop_alpha_normal = 168
        self._backdrop_alpha_dim = 92

        # 布局
        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setAlignment(Qt.AlignmentFlag.AlignCenter)

        inner = QWidget()
        inner.setObjectName("reminderCard")
        inner.setStyleSheet(
            f"#reminderCard {{ background: {color}CC; border-radius: 24px; }}"
        )
        inner.setFixedSize(640, 320)
        vbox.addWidget(inner, 0, Qt.AlignmentFlag.AlignCenter)

        inner_v = QVBoxLayout(inner)
        inner_v.setContentsMargins(48, 32, 48, 32)
        inner_v.setSpacing(16)
        inner_v.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # 科目标签
        subj_lbl = QLabel(subject_name)
        subj_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subj_lbl.setStyleSheet(
            "color: white; font-size: 22px; font-weight: bold; background: transparent;"
        )
        inner_v.addWidget(subj_lbl)

        # 提醒正文
        msg_lbl = QLabel(message or "考试提醒")
        msg_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg_lbl.setWordWrap(True)
        msg_lbl.setStyleSheet(
            "color: white; font-size: 36px; font-weight: bold; background: transparent;"
        )
        inner_v.addWidget(msg_lbl)

        # 关闭按钮
        close_btn = PushButton("知道了")
        close_btn.setFixedWidth(120)
        close_btn.clicked.connect(self.close)
        close_btn.setStyleSheet(
            "PushButton { background: rgba(255,255,255,60); color: white; "
            "border-radius: 8px; font-size: 16px; padding: 8px 0; }"
            "PushButton:hover { background: rgba(255,255,255,100); }"
        )
        inner_v.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignCenter)

        # 闪烁定时器
        self._blink_timer: Optional[QTimer] = None
        if flash:
            self._blink_timer = QTimer(self)
            self._blink_timer.setInterval(600)
            self._blink_timer.timeout.connect(self._blink)
            self._blink_timer.start()

        # 按下鼠标关闭（点击空白处）
        self.mousePressEvent = lambda _e: self.close()  # type: ignore[method-assign]

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)

        # 背景遮罩：先叠加深色，再叠加科目主题色轻微染色。
        alpha = self._backdrop_alpha_normal
        if self._flash and not self._flash_visible:
            alpha = self._backdrop_alpha_dim

        dark = QColor(10, 12, 18, alpha)
        tint = QColor(self._color)
        tint.setAlpha(max(36, alpha // 3))

        painter.fillRect(self.rect(), dark)
        painter.fillRect(self.rect(), tint)
        super().paintEvent(event)

    def _blink(self) -> None:
        self._flash_visible = not self._flash_visible
        self.update()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._blink_timer:
            self._blink_timer.stop()
        super().closeEvent(event)


def show_reminder_overlay(
    subject_name: str,
    message: str,
    flash: bool = False,
    color: str = "#2196F3",
) -> None:
    """在主线程中安全地显示提醒遮罩。"""
    overlay = ExamReminderOverlay(
        subject_name=subject_name,
        message=message,
        flash=flash,
        color=color,
    )
    overlay.show()
    overlay.raise_()
    overlay.activateWindow()


# ─────────────────────────────────────────────────────────────────────────── #
# 语音 TTS
# ─────────────────────────────────────────────────────────────────────────── #

def _speak_text(text: str) -> None:
    """后台线程中调用 TTS 朗读文字。"""
    # 优先使用 Windows SAPI（无额外依赖）
    try:
        import win32com.client  # type: ignore
        sapi = win32com.client.Dispatch("SAPI.SpVoice")
        sapi.Speak(text)
        return
    except ImportError:
        pass

    # 降级到 pyttsx3（可选依赖）
    try:
        import pyttsx3  # type: ignore
        engine = pyttsx3.init()
        engine.say(text)
        engine.runAndWait()
    except Exception:
        pass  # TTS 不可用时静默失败


def speak_reminder(text: str) -> None:
    """在后台线程中朗读提醒，不阻塞主线程。"""
    t = threading.Thread(target=_speak_text, args=(text,), daemon=True)
    t.start()


# ─────────────────────────────────────────────────────────────────────────── #
# 统一入口
# ─────────────────────────────────────────────────────────────────────────── #

def trigger_reminder(
    subject_name: str,
    message: str,
    color: str,
    mode: str,          # "fullscreen" | "voice" | "both"
    flash: bool = False,
) -> None:
    """
    根据 mode 触发对应的提醒。

    Parameters
    ----------
    subject_name  科目名称
    message       提醒文字
    color         科目主题色
    mode          "fullscreen" / "voice" / "both"
    flash         全屏时是否闪烁
    """
    if mode in ("fullscreen", "both"):
        show_reminder_overlay(subject_name, message, flash=flash, color=color)
    if mode in ("voice", "both"):
        speak_reminder(message or f"{subject_name}，考试提醒")

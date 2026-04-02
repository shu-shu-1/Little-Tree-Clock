"""闹钟提醒窗口

组件
----
_BaseAlarmAlert      — N 秒计时 + 铃声循环 + 停止信号（公共基类）
AlarmFullscreenAlert — 全屏提醒（默认）
AlarmPopupAlert      — 弹窗提醒（全屏关闭时）
SnoozeToastItem      — 稍后提醒 Toast 项（ToastItem 子类，集成 ToastManager 队列）
AlarmAlertController — 管理单次闹钟的完整提醒循环
"""
from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer, Signal, QObject
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QApplication, QPushButton, QGraphicsDropShadowEffect,
)
from PySide6.QtGui import QColor, QPainter

from app.models.alarm_model import Alarm
from app.services.i18n_service import I18nService
from app.services import ringtone_service as rs
from app.utils.logger import logger
from app.views.toast_notification import ToastAction, ToastHandle, ToastItem, TOAST_WIDTH, TOAST_RADIUS

if TYPE_CHECKING:
    from app.views.toast_notification import ToastManager


# ─────────────────────────────────────────────────────────────────────────── #
# 公共基类
# ─────────────────────────────────────────────────────────────────────────── #

class _BaseAlarmAlert(QWidget):
    """1 分钟提醒基类：倒计时 + 铃声循环 + 停止/超时信号"""

    stopped   = Signal()   # 用户点了停止
    timed_out = Signal()   # 1 分钟内未操作

    def __init__(self, alarm: Alarm, parent=None):
        super().__init__(parent)
        self._alarm = alarm
        self._i18n = I18nService.instance()
        from app.services.settings_service import SettingsService
        self._remaining_ms = SettingsService.instance().alarm_alert_duration_sec * 1000
        self._user_stopped = False

        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self._on_tick)

    # ── 公开接口 ─────────────────────────────────────────────────────── #

    def start(self) -> None:
        """显示窗口并开始计时 + 铃声"""
        self._show_window()
        self._update_countdown()
        self._tick.start()
        if self._alarm.sound:
            rs.play_sound_loop(self._alarm.sound)
        else:
            rs.play_default_loop()

    # ── 子类实现 ─────────────────────────────────────────────────────── #

    def _show_window(self) -> None:
        raise NotImplementedError

    def _update_countdown(self) -> None:
        raise NotImplementedError

    # ── 内部逻辑 ─────────────────────────────────────────────────────── #

    def _on_tick(self) -> None:
        self._remaining_ms -= 1000
        self._update_countdown()
        if self._remaining_ms <= 0:
            self._tick.stop()
            rs.stop_loop()
            self.close()
            if not self._user_stopped:
                logger.debug("[闹钟] 提醒超时未操作：{}", self._alarm.label)
                self.timed_out.emit()

    def _on_stop(self) -> None:
        if self._user_stopped:
            return
        self._user_stopped = True
        self._tick.stop()
        rs.stop_loop()
        self.close()
        logger.debug("[闹钟] 用户停止提醒：{}", self._alarm.label)
        self.stopped.emit()

    @staticmethod
    def _fmt_countdown(ms: int) -> str:
        secs = max(0, ms // 1000)
        return f"{secs // 60}:{secs % 60:02d}"


# ─────────────────────────────────────────────────────────────────────────── #
# 全屏提醒
# ─────────────────────────────────────────────────────────────────────────── #

class AlarmFullscreenAlert(_BaseAlarmAlert):
    """覆盖整个屏幕的 1 分钟闹钟提醒"""

    def __init__(self, alarm: Alarm, parent=None):
        super().__init__(alarm, parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._countdown_lbl: QLabel | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setContentsMargins(0, 0, 0, 0)

        # 中心内容容器（固定宽度，内容居中）
        inner = QWidget()
        inner.setFixedWidth(380)
        inner.setStyleSheet("background: transparent;")
        il = QVBoxLayout(inner)
        il.setSpacing(16)
        il.setContentsMargins(0, 0, 0, 0)
        il.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon_lbl = QLabel("⏰")
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet(
            "font-size: 64px; color: white; background: transparent;"
        )
        il.addWidget(icon_lbl)

        name_lbl = QLabel(self._alarm.label)
        name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_lbl.setWordWrap(True)
        name_lbl.setStyleSheet(
            "font-size: 26px; font-weight: bold; color: white; background: transparent;"
        )
        il.addWidget(name_lbl)

        time_lbl = QLabel(self._alarm.time_str)
        time_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        time_lbl.setStyleSheet(
            "font-size: 44px; font-weight: bold; color: white;"
            " background: transparent; letter-spacing: 4px;"
        )
        il.addWidget(time_lbl)

        self._countdown_lbl = QLabel(self._fmt_countdown(self._remaining_ms))
        self._countdown_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._countdown_lbl.setStyleSheet(
            "font-size: 13px; color: rgba(255,255,255,160); background: transparent;"
        )
        il.addWidget(self._countdown_lbl)

        il.addSpacing(28)

        stop_btn = QPushButton(self._i18n.t("alarm.alert.stop"))
        stop_btn.setFixedSize(168, 54)
        stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        stop_btn.setStyleSheet(
            "QPushButton {"
            "  background: rgba(255,255,255,220); color: #1a1a1a;"
            "  border-radius: 27px; font-size: 16px; font-weight: 600; border: none;"
            "}"
            "QPushButton:hover { background: white; }"
            "QPushButton:pressed { background: rgba(220,220,220,210); }"
        )
        stop_btn.clicked.connect(self._on_stop)
        il.addWidget(stop_btn, 0, Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(inner, 0, Qt.AlignmentFlag.AlignCenter)

    def _show_window(self) -> None:
        screen = QApplication.primaryScreen()
        if screen:
            self.setGeometry(screen.geometry())
        self.show()
        self.raise_()
        self.activateWindow()

    def _update_countdown(self) -> None:
        if self._countdown_lbl:
            self._countdown_lbl.setText(self._fmt_countdown(self._remaining_ms))

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(10, 12, 22, 215))
        super().paintEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self._on_stop()
        super().keyPressEvent(event)


# ─────────────────────────────────────────────────────────────────────────── #
# 弹窗提醒（全屏关闭时）
# ─────────────────────────────────────────────────────────────────────────── #

class AlarmPopupAlert(_BaseAlarmAlert):
    """居中弹窗式 1 分钟提醒（全屏关闭时使用）"""

    def __init__(self, alarm: Alarm, parent=None):
        super().__init__(alarm, parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._countdown_lbl: QLabel | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        self.setFixedSize(380, 270)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 14)

        card = QWidget(self)
        card.setObjectName("alarmPopupCard")
        card.setStyleSheet(
            "#alarmPopupCard {"
            "  background: rgba(28,30,40,235);"
            "  border-radius: 18px;"
            "  border: 1px solid rgba(255,255,255,18);"
            "}"
        )
        outer.addWidget(card)

        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(30)
        shadow.setColor(QColor(0, 0, 0, 120))
        shadow.setOffset(0, 6)
        card.setGraphicsEffect(shadow)

        cl = QVBoxLayout(card)
        cl.setSpacing(10)
        cl.setContentsMargins(24, 20, 24, 20)
        cl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon_lbl = QLabel("⏰")
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet(
            "font-size: 38px; color: white; background: transparent;"
        )
        cl.addWidget(icon_lbl)

        name_lbl = QLabel(self._alarm.label)
        name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_lbl.setWordWrap(True)
        name_lbl.setStyleSheet(
            "font-size: 18px; font-weight: bold; color: white; background: transparent;"
        )
        cl.addWidget(name_lbl)

        time_lbl = QLabel(self._alarm.time_str)
        time_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        time_lbl.setStyleSheet(
            "font-size: 30px; font-weight: bold; color: white; background: transparent;"
        )
        cl.addWidget(time_lbl)

        self._countdown_lbl = QLabel(self._fmt_countdown(self._remaining_ms))
        self._countdown_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._countdown_lbl.setStyleSheet(
            "font-size: 11px; color: rgba(255,255,255,130); background: transparent;"
        )
        cl.addWidget(self._countdown_lbl)

        stop_btn = QPushButton(self._i18n.t("alarm.alert.stop"))
        stop_btn.setFixedHeight(42)
        stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        stop_btn.setStyleSheet(
            "QPushButton {"
            "  background: rgba(255,255,255,190); color: #1a1a1a;"
            "  border-radius: 21px; font-size: 14px; font-weight: 600; border: none;"
            "}"
            "QPushButton:hover { background: rgba(255,255,255,230); }"
            "QPushButton:pressed { background: rgba(200,200,200,210); }"
        )
        stop_btn.clicked.connect(self._on_stop)
        cl.addWidget(stop_btn)

    def _show_window(self) -> None:
        screen = QApplication.primaryScreen()
        if screen:
            sg = screen.availableGeometry()
            self.move(
                sg.center().x() - self.width() // 2,
                sg.center().y() - self.height() // 2,
            )
        self.show()
        self.raise_()
        self.activateWindow()

    def _update_countdown(self) -> None:
        if self._countdown_lbl:
            self._countdown_lbl.setText(self._fmt_countdown(self._remaining_ms))

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self._on_stop()
        super().keyPressEvent(event)


# ─────────────────────────────────────────────────────────────────────────── #
# 稍后提醒 Toast 项（ToastItem 子类，集成 ToastManager 队列）
# ─────────────────────────────────────────────────────────────────────────── #

class SnoozeToastItem(ToastItem):
    """
    稍后提醒启用中的 ToastItem 子类。

    - 加入 ToastManager 队列，与普通 Toast 共享位置/动画
    - 无右上角关闭按钮，改为底部 PushButton
    - 每秒更新剩余倒计时
    - duration_ms=0 → 常驻（不受全局 Toast 时长影响）
    - user_stopped  → 用户点了取消按钮
    - snooze_timed_out → 倒计时归零，应再次触发提醒
    """

    user_stopped     = Signal()
    snooze_timed_out = Signal()

    def __init__(self, label: str, snooze_ms: int):
        # 必须在 super().__init__() 之前设置，因为 __init__ 内部会调用 _build_ui
        self._i18n                = I18nService.instance()
        self._snooze_label_text   = label
        self._snooze_remaining_ms = snooze_ms
        self._snooze_done         = False
        self._detail_lbl_ref: QLabel | None = None

        # duration_ms=0 → 常驻（ToastItem 不会启动自动关闭定时器）
        super().__init__(self._i18n.t("alarm.snooze.active"), "", duration_ms=0)

        # 稍后提醒倒计时（与 ToastItem 自身定时器相互独立）
        self._snooze_tick = QTimer(self)
        self._snooze_tick.setInterval(1000)
        self._snooze_tick.timeout.connect(self._on_snooze_tick)

    # ── 覆盖 _build_ui：自定义垂直布局 + 无 ✕ 按钮 ─────────────── #

    def _build_ui(self, title: str, message: str) -> None:   # noqa: N802
        self.setFixedWidth(TOAST_WIDTH + self._SHADOW_L + self._SHADOW_R)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            self._SHADOW_L, self._SHADOW_T,
            self._SHADOW_R, self._SHADOW_B,
        )

        self._content = QWidget(self)
        self._content.setObjectName("toastContent")
        outer.addWidget(self._content)

        cl = QVBoxLayout(self._content)
        cl.setContentsMargins(14, 12, 14, 12)
        cl.setSpacing(5)

        title_lbl = QLabel(self._i18n.t("alarm.snooze.active"))
        title_lbl.setStyleSheet(
            "color: #1a1a1a; font-size: 10pt; font-weight: bold;"
        )
        cl.addWidget(title_lbl)

        self._detail_lbl_ref = QLabel()
        self._detail_lbl_ref.setStyleSheet("color: #555555; font-size: 9pt;")
        self._refresh_snooze_detail()
        cl.addWidget(self._detail_lbl_ref)

        cl.addSpacing(4)

        cancel_btn = QPushButton(self._i18n.t("alarm.snooze.cancel"))
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.setFixedHeight(30)
        cancel_btn.setStyleSheet(
            "QPushButton {"
            "  background: #f0f0f0; color: #333333;"
            "  border: 1px solid #d0d0d0; border-radius: 6px;"
            "  font-size: 9pt; padding: 0 12px;"
            "}"
            "QPushButton:hover { background: #e4e4e4; border-color: #b8b8b8; }"
            "QPushButton:pressed { background: #d8d8d8; }"
        )
        cancel_btn.clicked.connect(self._on_snooze_cancel)
        cl.addWidget(cancel_btn)

        self._content.setStyleSheet(
            "#toastContent {"
            "  background: rgba(255,255,255,240);"
            f"  border-radius: {TOAST_RADIUS}px;"
            "  border: 1px solid rgba(0,0,0,12);"
            "}"
        )

    # ── 稍后提醒逻辑 ──────────────────────────────────────────────── #

    def _refresh_snooze_detail(self) -> None:
        if self._detail_lbl_ref is None:
            return
        secs = max(0, self._snooze_remaining_ms // 1000)
        m, s = divmod(secs, 60)
        time_text = f"{m:02d}:{s:02d}"
        self._detail_lbl_ref.setText(
            self._i18n.t("alarm.snooze.detail", label=self._snooze_label_text, time=time_text)
        )

    def start_timer(self) -> None:
        """覆盖父类：启动稍后提醒倒计时（父类的 duration=0 无计时器）"""
        self._snooze_tick.start()

    def _on_snooze_tick(self) -> None:
        self._snooze_remaining_ms -= 1000
        self._refresh_snooze_detail()
        if self._snooze_remaining_ms <= 0:
            self._snooze_tick.stop()
            if not self._snooze_done:
                self._snooze_done = True
                logger.debug("[闹钟] 稍后提醒倒计时结束：{}", self._snooze_label_text)
                self._request_close()       # 从 ToastManager 队列移除
                self.snooze_timed_out.emit()  # 触发再次提醒

    def _on_snooze_cancel(self) -> None:
        if not self._snooze_done:
            self._snooze_done = True
            self._snooze_tick.stop()
            logger.debug("[闹钟] 用户取消稍后提醒：{}", self._snooze_label_text)
            self._request_close()       # 从 ToastManager 队列移除
            self.user_stopped.emit()    # 通知控制器停止循环

    def close_item(self) -> None:
        """外部主动关闭（不发信号），如新一轮提醒开始前清除此 Toast。"""
        if not self._snooze_done:
            self._snooze_done = True
            self._snooze_tick.stop()
            self._request_close()   # 触发 ToastManager 走出队动画


# ─────────────────────────────────────────────────────────────────────────── #
# 提醒控制器
# ─────────────────────────────────────────────────────────────────────────── #

class AlarmAlertController(QObject):
    """
    管理单次闹钟的完整提醒循环：

        提醒（N 秒）
          ├─ 用户停止 → finished（循环结束）
          └─ 超时未停 → SnoozeToastItem 入 ToastManager 队列
                          ├─ 用户取消 → finished（循环结束）
                          └─ 倒计时归零 → 再次触发提醒（循环）
    """

    finished = Signal()   # 用户主动停止 / 无稍后提醒时结束

    def __init__(
        self,
        alarm: Alarm,
        toast_manager: Optional["ToastManager"] = None,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self._alarm        = alarm
        self._toast_mgr    = toast_manager
        self._alert_win: _BaseAlarmAlert | None    = None
        self._snooze_handle: ToastHandle | None = None
        self._snooze_remaining_ms: int = 0
        self._snooze_total_ms: int = 0
        self._snooze_done = False
        self._snooze_tick = QTimer(self)
        self._snooze_tick.setInterval(1000)
        self._snooze_tick.timeout.connect(self._on_snooze_tick)

    def start(self) -> None:
        self._fire_alert()

    # ── 内部 ─────────────────────────────────────────────────────────── #

    def _fire_alert(self) -> None:
        """显示一次提醒窗口（先关闭上一轮稍后提醒 Toast）"""
        self._dismiss_snooze_item()

        if self._alarm.fullscreen:
            win: _BaseAlarmAlert = AlarmFullscreenAlert(self._alarm)
        else:
            win = AlarmPopupAlert(self._alarm)

        self._alert_win = win
        win.stopped.connect(self._on_alert_stopped)
        win.timed_out.connect(self._on_alert_timed_out)
        win.start()
        logger.info("[闹钟] 显示提醒（{}）：{}",
                    "全屏" if self._alarm.fullscreen else "弹窗",
                    self._alarm.label)

    def _on_alert_stopped(self) -> None:
        self._dismiss_snooze_item()
        logger.info("[闹钟] 已停止，不启用稍后提醒：{}", self._alarm.label)
        self.finished.emit()

    def _on_alert_timed_out(self) -> None:
        snooze_min = self._alarm.snooze_min
        if snooze_min <= 0:
            logger.info("[闹钟] 超时，无稍后提醒设置：{}", self._alarm.label)
            self.finished.emit()
            return

        snooze_ms = snooze_min * 60_000
        logger.info("[闹钟] 超时，启动稍后提醒 {} 分钟：{}", snooze_min, self._alarm.label)
        self._start_snooze_notification(snooze_ms)

    def _on_snooze_stopped(self) -> None:
        logger.info("[闹钟] 稍后提醒已取消：{}", self._alarm.label)
        self._dismiss_snooze_item()
        self.finished.emit()

    def _on_snooze_tick(self) -> None:
        if self._snooze_done:
            return
        self._snooze_remaining_ms = max(0, self._snooze_remaining_ms - 1000)
        self._refresh_snooze_notification()
        if self._snooze_remaining_ms <= 0:
            self._snooze_done = True
            self._snooze_tick.stop()
            self._dismiss_snooze_item()
            logger.debug("[闹钟] 稍后提醒倒计时结束：{}", self._alarm.label)
            self._fire_alert()

    def _start_snooze_notification(self, snooze_ms: int) -> None:
        self._dismiss_snooze_item()
        self._snooze_total_ms = max(1000, snooze_ms)
        self._snooze_remaining_ms = self._snooze_total_ms
        self._snooze_done = False

        if self._toast_mgr is None:
            self._snooze_tick.start()
            return

        i18n = I18nService.instance()
        self._snooze_handle = self._toast_mgr.show_notification(
            i18n.t("alarm.snooze.active"),
            i18n.t("alarm.snooze.detail", label=self._alarm.label, time=self._format_snooze_time()),
            duration_ms=0,
            level="warning",
            progress=(0, self._snooze_total_ms // 1000),
            progress_text=i18n.t("alarm.snooze.cancel"),
            actions=[ToastAction("cancel", i18n.t("alarm.snooze.cancel"), kind="danger")],
        )
        self._snooze_handle.action_triggered.connect(self._on_snooze_action)
        self._snooze_tick.start()

    def _on_snooze_action(self, action_id: str) -> None:
        if action_id != "cancel" or self._snooze_done:
            return
        self._snooze_done = True
        self._snooze_tick.stop()
        logger.debug("[闹钟] 用户取消稍后提醒：{}", self._alarm.label)
        self._on_snooze_stopped()

    def _refresh_snooze_notification(self) -> None:
        if self._snooze_handle is None:
            return
        i18n = I18nService.instance()
        elapsed_s = (self._snooze_total_ms - self._snooze_remaining_ms) // 1000
        total_s = max(1, self._snooze_total_ms // 1000)
        self._snooze_handle.update(
            message=i18n.t("alarm.snooze.detail", label=self._alarm.label, time=self._format_snooze_time()),
            progress_value=elapsed_s,
            progress_max=total_s,
            progress_text=i18n.t("alarm.snooze.cancel"),
        )

    def _format_snooze_time(self) -> str:
        secs = max(0, self._snooze_remaining_ms // 1000)
        m, s = divmod(secs, 60)
        return f"{m:02d}:{s:02d}"

    def _dismiss_snooze_item(self) -> None:
        """主动关闭上一轮稍后提醒 Toast（不发用户信号）"""
        self._snooze_tick.stop()
        if self._snooze_handle is not None:
            self._snooze_handle.close()
            self._snooze_handle = None

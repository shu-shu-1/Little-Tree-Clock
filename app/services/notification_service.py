"""通知服务：自定义 Toast > 系统托盘气泡 > 控制台日志。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from PySide6.QtCore import QObject, QThread, QTimer
from PySide6.QtWidgets import QSystemTrayIcon

from app.utils.logger import logger

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget
    from app.views.toast_notification import ToastAction, ToastHandle, ToastManager


class NotificationService(QObject):
    def __init__(self, tray: QSystemTrayIcon | None = None, parent=None):
        super().__init__(parent)
        self._tray = tray
        self._toast_mgr: ToastManager | None = None

    def set_tray(self, tray: QSystemTrayIcon) -> None:
        self._tray = tray

    def set_toast_manager(self, manager: "ToastManager") -> None:
        self._toast_mgr = manager

    def show(
        self,
        title: str,
        message: str,
        icon: QSystemTrayIcon.MessageIcon = QSystemTrayIcon.MessageIcon.Information,
        duration_ms: int = 4000,
        *,
        level: str | None = None,
    ) -> None:
        """level 取值 info | success | warning | error，设置后覆盖由 icon 推断的等级。"""
        # 跨线程保护：Qt GUI 必须在主线程操作
        if QThread.currentThread() != self.thread():
            QTimer.singleShot(0, lambda: self.show(title, message, icon, duration_ms, level=level))
            return

        if self._use_custom() and self._toast_mgr is not None:
            if level is None:
                _icon_to_level = {
                    QSystemTrayIcon.MessageIcon.Information: "info",
                    QSystemTrayIcon.MessageIcon.Warning: "warning",
                    QSystemTrayIcon.MessageIcon.Critical: "error",
                }
                level = _icon_to_level.get(icon, "info")
            self._toast_mgr.show_toast(title, message, level=level)
            return

        if self._tray and self._tray.isVisible():
            self._tray.showMessage(title, message, icon, duration_ms)
        else:
            logger.info("通知 [{}]: {}", title, message)

    def show_notification(
        self,
        title: str,
        message: str = "",
        *,
        level: str = "info",
        duration_ms: int | None = None,
        image_path: str | None = None,
        progress: tuple[int, int] | None = None,
        progress_text: str = "",
        actions: list["ToastAction"] | None = None,
        custom_widget_factory: Callable[["QWidget"], "QWidget"] | None = None,
    ) -> "ToastHandle | None":
        """统一通知入口：支持按钮/进度/图片/自定义卡片并可组合。"""
        # 跨线程保护：异步转发，调用方将拿不到 ToastHandle（比崩溃好）
        if QThread.currentThread() != self.thread():
            QTimer.singleShot(
                0,
                lambda: self.show_notification(
                    title,
                    message,
                    level=level,
                    duration_ms=duration_ms,
                    image_path=image_path,
                    progress=progress,
                    progress_text=progress_text,
                    actions=actions,
                    custom_widget_factory=custom_widget_factory,
                ),
            )
            return None

        if self._use_custom() and self._toast_mgr is not None:
            return self._toast_mgr.show_notification(
                title,
                message,
                duration_ms=duration_ms,
                level=level,
                image_path=image_path,
                progress=progress,
                progress_text=progress_text,
                actions=actions,
                custom_widget_factory=custom_widget_factory,
            )

        # fallback: 系统托盘不支持富内容，退化为普通文本通知
        self.show(title, message)
        return None

    def ask_notification(
        self,
        title: str,
        message: str,
        *,
        actions: list["ToastAction"],
        level: str = "warning",
        image_path: str | None = None,
        duration_ms: int = 0,
    ) -> str:
        """同步等待按钮结果，返回 action_id；fallback 返回空字符串。"""
        # 跨线程保护：同步等待无法在后台线程实现，直接 fallback
        if QThread.currentThread() != self.thread():
            logger.warning("ask_notification 不支持跨线程调用，返回空字符串")
            return ""

        if self._use_custom() and self._toast_mgr is not None:
            return self._toast_mgr.ask_notification(
                title,
                message,
                actions=actions,
                level=level,
                image_path=image_path,
                duration_ms=duration_ms,
            )
        self.show(title, message)
        return ""

    @staticmethod
    def _use_custom() -> bool:
        """始终使用应用内置 Toast 通知系统。"""
        return True

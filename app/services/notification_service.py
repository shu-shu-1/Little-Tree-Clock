"""通知服务

优先使用自定义 Toast 悬浮窗（需在设置中启用），
退回到系统托盘气泡，最终 fallback 到控制台日志。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QSystemTrayIcon

from app.utils.logger import logger

if TYPE_CHECKING:
    from app.views.toast_notification import ToastManager


class NotificationService(QObject):
    """
    封装通知发送。

    优先级：自定义 Toast > 系统托盘气泡 > 控制台日志

    用法：
        service.set_tray(tray)
        service.set_toast_manager(mgr)   # 由 MainWindow 注入
        service.show("标题", "内容")
    """

    def __init__(self, tray: Optional[QSystemTrayIcon] = None, parent=None):
        super().__init__(parent)
        self._tray = tray
        self._toast_mgr: Optional["ToastManager"] = None

    def set_tray(self, tray: QSystemTrayIcon) -> None:
        self._tray = tray

    def set_toast_manager(self, manager: "ToastManager") -> None:
        """注入 ToastManager（由 MainWindow 在初始化完成后调用）"""
        self._toast_mgr = manager

    def show(
        self,
        title: str,
        message: str,
        icon: QSystemTrayIcon.MessageIcon = QSystemTrayIcon.MessageIcon.Information,
        duration_ms: int = 4000,
        *,
        level: Optional[str] = None,
    ) -> None:
        """*level* 取值 ``"info"`` | ``"success"`` | ``"warning"`` | ``"error"``，
        设置后会覆盖 *icon* 推断出的等级。"""
        # ── 自定义 Toast ──
        if self._use_custom() and self._toast_mgr is not None:
            if level is None:
                _icon_to_level = {
                    QSystemTrayIcon.MessageIcon.Information: "info",
                    QSystemTrayIcon.MessageIcon.Warning:     "warning",
                    QSystemTrayIcon.MessageIcon.Critical:    "error",
                }
                level = _icon_to_level.get(icon, "info")
            self._toast_mgr.show_toast(title, message, level=level)
            return

        # ── 系统托盘气泡 ──
        if self._tray and self._tray.isVisible():
            self._tray.showMessage(title, message, icon, duration_ms)
        else:
            logger.info("通知 [{}]: {}", title, message)

    # ── 内部 ──────────────────────────────────────────────── #

    @staticmethod
    def _use_custom() -> bool:
        """惰性读取设置，避免模块加载时的循环导入"""
        try:
            from app.services.settings_service import SettingsService
            return SettingsService.instance().notification_use_custom
        except Exception:
            return False

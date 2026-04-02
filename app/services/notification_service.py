"""通知服务

优先使用自定义 Toast 悬浮窗（需在设置中启用），
退回到系统托盘气泡，最终 fallback 到控制台日志。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Optional

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QSystemTrayIcon

from app.utils.logger import logger

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget
    from app.views.toast_notification import ToastAction, ToastHandle, ToastManager


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

    def show_notification(
        self,
        title: str,
        message: str = "",
        *,
        level: str = "info",
        duration_ms: Optional[int] = None,
        image_path: Optional[str] = None,
        progress: Optional[tuple[int, int]] = None,
        progress_text: str = "",
        actions: Optional[list["ToastAction"]] = None,
        custom_widget_factory: Optional[Callable[["QWidget"], "QWidget"]] = None,
    ) -> Optional["ToastHandle"]:
        """统一通知入口：支持按钮/进度/图片/自定义卡片并可组合。"""
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
        image_path: Optional[str] = None,
        duration_ms: int = 0,
    ) -> str:
        """同步等待按钮结果，返回 action_id；fallback 返回空字符串。"""
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
        """始终使用应用内置 Toast 通知系统（不再依赖设置开关）。
        若 toast_mgr 尚未注入则自动 fallback 到系统托盘气泡。"""
        return True

"""自定义 Toast 通知系统

提供可替代系统通知的悬浮 Toast 窗口，支持：
- 六种出现位置（左上/左下/右上/右下/上中/下中）
- 可配置停留时间（0 = 常驻）
- 单个关闭按钮
- 进入/退出动画：底部位置新通知从下方进入旧通知上移，顶部相反
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import (
    Qt, QTimer, QPoint, QPropertyAnimation,
    QEasingCurve, QParallelAnimationGroup,
    Signal, QObject, QRect, QEventLoop,
)
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel,
    QApplication, QGraphicsDropShadowEffect,
    QPushButton, QSizePolicy,
)
from PySide6.QtGui import (
    QColor, QPainter, QPainterPath, QFont, QPen,
)
from qfluentwidgets import isDarkTheme, qconfig, InfoBarIcon

from app.services.i18n_service import I18nService
from app.utils.logger import logger

# ── 常量 ────────────────────────────────────────────────── #
TOAST_WIDTH    = 340        # 固定宽度（px）
TOAST_MIN_H    = 64         # 最小高度
TOAST_MARGIN   = 16         # 距屏幕边缘距离
TOAST_GAP      = 10         # 相邻 Toast 之间间距
TOAST_ANIM_MS  = 280        # 动画时长（ms）
TOAST_RADIUS   = 12         # 圆角半径

# 位置常量
POS_TOP_LEFT      = "top_left"
POS_TOP_CENTER    = "top_center"
POS_TOP_RIGHT     = "top_right"
POS_BOTTOM_LEFT   = "bottom_left"
POS_BOTTOM_CENTER = "bottom_center"
POS_BOTTOM_RIGHT  = "bottom_right"


def get_position_labels() -> dict[str, str]:
    """获取位置标签的翻译"""
    i18n = I18nService.instance()
    return {
        POS_TOP_LEFT:      i18n.t("toast.pos.top_left"),
        POS_TOP_CENTER:    i18n.t("toast.pos.top_center"),
        POS_TOP_RIGHT:     i18n.t("toast.pos.top_right"),
        POS_BOTTOM_LEFT:   i18n.t("toast.pos.bottom_left"),
        POS_BOTTOM_CENTER: i18n.t("toast.pos.bottom_center"),
        POS_BOTTOM_RIGHT:  i18n.t("toast.pos.bottom_right"),
    }


POSITION_LABELS = get_position_labels()

ALL_POSITIONS = list(POSITION_LABELS.keys())

# ── Toast 等级 → InfoBarIcon 映射 ────────────────────────── #
_LEVEL_ICON: dict[str, InfoBarIcon] = {
    "info":    InfoBarIcon.INFORMATION,
    "success": InfoBarIcon.SUCCESS,
    "warning": InfoBarIcon.WARNING,
    "error":   InfoBarIcon.ERROR,
}


def _is_bottom(position: str) -> bool:
    return position.startswith("bottom")


# ── Toast 单体 ──────────────────────────────────────────── #

class ToastItem(QWidget):
    """单条 Toast 通知窗口"""

    # 用户点击关闭或超时后触发，参数为 self
    request_close = Signal(object)

    def __init__(
        self,
        title: str,
        message: str,
        duration_ms: int = 5000,
        level: str = "info",
        parent: Optional[QWidget] = None,
    ):
        super().__init__(
            parent,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.BypassWindowManagerHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        self._duration_ms = duration_ms
        self._closing = False
        self._level = level
        self._level_icon: Optional[QLabel] = None  # 在 _build_ui 前初始化，供子类覆写使用

        self._build_ui(title, message)
        self._apply_shadow()
        self._apply_theme()
        qconfig.themeChangedFinished.connect(self._apply_theme)

        # 自动关闭定时器
        if duration_ms > 0:
            self._timer = QTimer(self)
            self._timer.setSingleShot(True)
            self._timer.setInterval(duration_ms)
            self._timer.timeout.connect(self._request_close)
        else:
            self._timer = None

    # ── UI ─────────────────────────────────────────────── #

    # 阴影溢出边距（blurRadius=20, offset=(0,4) → 上~18px 下~24px 左右~20px）
    _SHADOW_L = 20
    _SHADOW_T = 18
    _SHADOW_R = 20
    _SHADOW_B = 24

    def _build_ui(self, title: str, message: str) -> None:
        # 窗口宽度 = 内容宽度 + 左右阴影溢出
        self.setFixedWidth(TOAST_WIDTH + self._SHADOW_L + self._SHADOW_R)

        outer = QVBoxLayout(self)
        # 留出阴影溢出空间，使 dirty rect 始终在窗口内
        outer.setContentsMargins(
            self._SHADOW_L, self._SHADOW_T,
            self._SHADOW_R, self._SHADOW_B,
        )

        # 内容容器（用于绘制圆角背景）
        self._content = QWidget(self)
        self._content.setObjectName("toastContent")
        outer.addWidget(self._content)

        h = QHBoxLayout(self._content)
        h.setContentsMargins(14, 10, 10, 10)
        h.setSpacing(10)

        # 文字区
        text_col = QVBoxLayout()
        text_col.setSpacing(3)

        self._title_lbl = QLabel(title)
        self._title_lbl.setWordWrap(True)

        self._msg_lbl = QLabel(message)
        self._msg_lbl.setWordWrap(True)
        self._msg_lbl.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )

        text_col.addWidget(self._title_lbl)
        if message:
            text_col.addWidget(self._msg_lbl)

        # 等级图标（位于文字区左侧，使用 qfluentwidgets InfoBarIcon）
        self._level_icon = QLabel()
        self._level_icon.setFixedSize(20, 20)
        self._level_icon.setAlignment(
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter
        )
        self._level_icon.setStyleSheet("background: transparent;")
        h.addWidget(self._level_icon, 0, Qt.AlignmentFlag.AlignVCenter)
        h.addLayout(text_col, 1)

        # 关闭按钮
        self._close_btn = QPushButton("✕")
        self._close_btn.setFixedSize(22, 22)
        self._close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close_btn.clicked.connect(self._request_close)
        h.addWidget(self._close_btn, 0, Qt.AlignmentFlag.AlignTop)
        # 颜色由 _apply_theme() 统一设置

    def _apply_shadow(self) -> None:
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)   # 与 _SHADOW_* 边距匹配
        shadow.setColor(QColor(0, 0, 0, 55))
        shadow.setOffset(0, 4)
        self._content.setGraphicsEffect(shadow)  # 作用于内容容器而非窗口本身

    def _apply_theme(self) -> None:
        """根据当前深浅色主题刷新 Toast 各元素颜色"""
        dark = isDarkTheme()
        if dark:
            bg         = "rgba(45,45,45,245)"
            border     = "rgba(255,255,255,18)"
            title_c    = "#f0f0f0"
            msg_c      = "#b0b0b0"
            close_c    = "#888888"
            close_h_bg = "rgba(255,255,255,25)"
            close_h_c  = "#dddddd"
        else:
            bg         = "rgba(255,255,255,240)"
            border     = "rgba(0,0,0,12)"
            title_c    = "#1a1a1a"
            msg_c      = "#555555"
            close_c    = "#aaaaaa"
            close_h_bg = "#f0f0f0"
            close_h_c  = "#555555"

        self._content.setStyleSheet(
            "#toastContent {"
            f"  background: {bg};"
            f"  border-radius: {TOAST_RADIUS}px;"
            f"  border: 1px solid {border};"
            "}"
        )
        self._title_lbl.setStyleSheet(
            f"color: {title_c}; font-size: 10pt; font-weight: bold;"
        )
        self._msg_lbl.setStyleSheet(
            f"color: {msg_c}; font-size: 9pt;"
        )
        self._close_btn.setStyleSheet(
            "QPushButton {"
            "  border: none; background: transparent;"
            f"  color: {close_c}; font-size: 13px; font-weight: bold;"
            "  border-radius: 11px;"
            "}"
            f"QPushButton:hover {{ background: {close_h_bg}; color: {close_h_c}; }}"
        )

        # 等级图标（通过 InfoBarIcon 渲染，主题变化时重新生成 pixmap）
        if self._level_icon is not None:
            fluent_icon = _LEVEL_ICON.get(self._level, InfoBarIcon.INFORMATION)
            self._level_icon.setPixmap(fluent_icon.icon().pixmap(18, 18))

    # ── 生命周期 ────────────────────────────────────────── #

    def start_timer(self) -> None:
        """开始自动关闭倒计时（show 后调用）"""
        if self._timer:
            self._timer.start()

    def _request_close(self) -> None:
        if not self._closing:
            self._closing = True
            self.request_close.emit(self)


# ── Toast 管理器 ────────────────────────────────────────── #

class ToastManager(QObject):
    """
    管理所有 ToastItem 的生命周期、堆叠与动画。

    使用：
        mgr = ToastManager()
        mgr.show_toast("标题", "内容")
    """

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._toasts: list[ToastItem] = []
        self._position: str = POS_BOTTOM_RIGHT
        self._duration_ms: int = 5000
        self._anim_group: Optional[QParallelAnimationGroup] = None

    # ── 配置 ────────────────────────────────────────────── #

    def set_position(self, position: str) -> None:
        if position in ALL_POSITIONS:
            self._position = position

    def set_duration(self, duration_ms: int) -> None:
        """duration_ms <= 0 表示常驻"""
        self._duration_ms = max(0, duration_ms)

    # ── 核心 API ─────────────────────────────────────────── #

    def show_toast(
        self,
        title: str,
        message: str,
        duration_ms: Optional[int] = None,
        level: str = "info",
    ) -> None:
        """弹出一条新 Toast

        Args:
            title:       标题文字
            message:     正文文字（可为空）
            duration_ms: 停留时长，None 则使用管理器默认值
            level:       等级，取值 ``"info"`` / ``"success"`` / ``"warning"`` / ``"error"``
        """
        dur = self._duration_ms if duration_ms is None else duration_ms
        toast = ToastItem(title, message, dur, level=level)
        self.add_item(toast)
        logger.debug("Toast 显示：{} | {}", title, message)

    def add_item(self, toast: "ToastItem") -> None:
        """
        将已构建的 ToastItem（或子类）加入队列并显示。

        适用场景：
        - 永久 Toast（duration_ms=0，不受全局时长影响）
        - 自定义 ToastItem 子类（如 SnoozeToastItem）

        调用方无需手动连接 request_close 信号。
        """
        toast.request_close.connect(self._on_toast_close)
        self._toasts.append(toast)

        start_pos = self._off_screen_pos(toast)
        toast.move(start_pos)
        toast.show()
        toast.adjustSize()

        self._animate_all()
        toast.start_timer()
        logger.debug("Toast 入队：{}", type(toast).__name__)

    def _on_toast_close(self, toast: ToastItem) -> None:
        """响应 Toast 关闭请求：动画移出，完成后销毁"""
        if toast not in self._toasts:
            return
        self._toasts.remove(toast)

        # 移出动画
        end_pos = self._off_screen_pos(toast)
        anim = QPropertyAnimation(toast, b"pos", self)
        anim.setDuration(TOAST_ANIM_MS)
        anim.setEasingCurve(QEasingCurve.Type.InCubic)
        anim.setEndValue(end_pos)
        anim.finished.connect(toast.close)
        anim.finished.connect(anim.deleteLater)
        anim.start()

        # 剩余 Toast 重新排列
        QTimer.singleShot(0, self._animate_all)

    def clear(self) -> None:
        """清除所有 Toast"""
        for t in list(self._toasts):
            self._on_toast_close(t)

    # ── 位置计算 ─────────────────────────────────────────── #

    def _screen_rect(self) -> QRect:
        screen = QApplication.primaryScreen()
        return screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)

    def _toast_height(self, toast: ToastItem) -> int:
        """窗口总高（含上下阴影溢出区）"""
        h = toast.sizeHint().height()
        return max(h, TOAST_MIN_H + ToastItem._SHADOW_T + ToastItem._SHADOW_B)

    def _toast_vis_height(self, toast: ToastItem) -> int:
        """内容可见高度（排除阴影溢出），用于堆叠计算"""
        return self._toast_height(toast) - ToastItem._SHADOW_T - ToastItem._SHADOW_B

    @staticmethod
    def _window_width() -> int:
        """窗口固定宽度（内容宽 + 左右阴影溢出）"""
        return TOAST_WIDTH + ToastItem._SHADOW_L + ToastItem._SHADOW_R

    def _target_pos(self, index: int, toast: ToastItem) -> QPoint:
        """
        计算第 index 条 Toast 的目标窗口坐标。
        堆叠步进使用可见内容高度，确保视觉间距始终为 TOAST_GAP。
        """
        rect = self._screen_rect()
        pos = self._position
        is_bot = _is_bottom(pos)

        # 从屏幕边缘到「第 index 条」内容边缘的累积偏移
        vis_offset = TOAST_MARGIN
        for i in range(index):
            vis_offset += self._toast_vis_height(self._toasts[i]) + TOAST_GAP

        ww = self._window_width()          # 窗口宽度（含阴影）
        vh = self._toast_vis_height(toast)  # 当前 Toast 可见高度

        # ── X 坐标（内容与屏幕边缘保持 TOAST_MARGIN）──
        # 公式：x = content_edge - shadow_offset - content_width
        if pos in (POS_TOP_LEFT, POS_BOTTOM_LEFT):
            # 内容左边缘 = rect.left() + TOAST_MARGIN
            x = rect.left() + TOAST_MARGIN - ToastItem._SHADOW_L
        elif pos in (POS_TOP_CENTER, POS_BOTTOM_CENTER):
            x = rect.left() + (rect.width() - ww) // 2
        else:  # right
            # 内容右边缘 = rect.right() - TOAST_MARGIN
            # 窗口左 x = 内容右边缘 - SHADOW_L - TOAST_WIDTH
            x = rect.right() - TOAST_MARGIN - ToastItem._SHADOW_L - TOAST_WIDTH

        # ── Y 坐标（内容对齐屏幕边缘，窗口再向外偏移 SHADOW_T）──
        if is_bot:
            # 内容底边 = rect.bottom() - vis_offset
            content_top = rect.bottom() - vis_offset - vh
            y = content_top - ToastItem._SHADOW_T
        else:
            # 内容顶边 = rect.top() + vis_offset
            content_top = rect.top() + vis_offset
            y = content_top - ToastItem._SHADOW_T

        return QPoint(x, y)

    def _off_screen_pos(self, toast: ToastItem) -> QPoint:
        """Toast 进入/退出动画的屏幕外起终点"""
        rect = self._screen_rect()
        is_bot = _is_bottom(self._position)
        pos = self._position
        ww = self._window_width()
        wh = self._toast_height(toast)

        # X 与目标一致
        if pos in (POS_TOP_LEFT, POS_BOTTOM_LEFT):
            x = rect.left() + TOAST_MARGIN - ToastItem._SHADOW_L
        elif pos in (POS_TOP_CENTER, POS_BOTTOM_CENTER):
            x = rect.left() + (rect.width() - ww) // 2
        else:
            x = rect.right() - TOAST_MARGIN - ToastItem._SHADOW_L - TOAST_WIDTH

        # 底部：从屏幕底部以下进入；顶部：从屏幕顶部以上进入
        if is_bot:
            y = rect.bottom() + TOAST_MARGIN
        else:
            y = rect.top() - wh - TOAST_MARGIN

        return QPoint(x, y)

    def _animate_all(self) -> None:
        """为所有当前 Toast 启动移动到目标位置的动画"""
        if not self._toasts:
            return

        # 安全停止旧动画组（C++ 对象可能已由 DeleteWhenStopped 提前删除）
        if self._anim_group is not None:
            try:
                if self._anim_group.state() == QParallelAnimationGroup.State.Running:
                    self._anim_group.stop()
            except RuntimeError:
                pass  # C++ 对象已删除，忽略
            self._anim_group = None

        group = QParallelAnimationGroup(self)

        for i, toast in enumerate(self._toasts):
            target = self._target_pos(i, toast)
            anim = QPropertyAnimation(toast, b"pos", group)
            anim.setDuration(TOAST_ANIM_MS)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.setStartValue(toast.pos())
            anim.setEndValue(target)
            group.addAnimation(anim)

        self._anim_group = group
        # finished 时清空引用，避免持有已删除的 C++ 对象
        group.finished.connect(self._on_anim_group_finished)
        group.start(QParallelAnimationGroup.DeletionPolicy.DeleteWhenStopped)

    def _on_anim_group_finished(self) -> None:
        self._anim_group = None


# ── 权限请求 Toast ──────────────────────────────────────── #

# 权限键 → (图标, 风险翻译 key)
_PERM_RISK: dict[str, tuple[str, str]] = {
    "network":      ("🌐", "perm.risk.network"),
    "fs_read":      ("📂", "perm.risk.fs_read"),
    "fs_write":     ("✏️",  "perm.risk.fs_write"),
    "os_exec":      ("⚙️",  "perm.risk.os_exec"),
    "os_env":       ("🔑", "perm.risk.os_env"),
    "clipboard":    ("📋", "perm.risk.clipboard"),
    "notification": ("🔔", "perm.risk.notification"),
    "install_pkg":  ("📦", "perm.risk.install_pkg"),
}


class PermissionToastItem(ToastItem):
    """权限请求通知 Toast

    常驻（不自动关闭），含三个操作按钮：始终允许 / 本次允许 / 拒绝。
    通过 ``exec()`` 同步阻塞等待用户响应（内部使用 QEventLoop），
    返回字符串 ``"always"`` / ``"once"`` / ``"deny"``。
    始终置顶，不受启动界面层级影响。
    """

    def __init__(self, title: str, message: str, install_mode: bool = False, parent=None):
        self._perm_result: str = "deny"
        self._loop: Optional[QEventLoop] = None
        self._i18n = I18nService.instance()
        super().__init__(title, message, duration_ms=0, parent=parent)
        # 隐藏 X 按钮，强制用户通过操作按钮做出选择
        self._close_btn.hide()
        # 安装权限使用不同的按钮文字
        if install_mode:
            self._always_btn.setText(self._i18n.t("perm.dialog.install.allow", default="允许"))
            self._once_btn.setText(self._i18n.t("perm.dialog.install.deny_once", default="拒绝"))
            self._deny_btn.setText(self._i18n.t("perm.dialog.install.deny_forever", default="永久拒绝"))

    # ── 重写布局：在文字下方增加按钮行 ────────────────────── #

    def _build_ui(self, title: str, message: str) -> None:
        self.setFixedWidth(TOAST_WIDTH + self._SHADOW_L + self._SHADOW_R)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            self._SHADOW_L, self._SHADOW_T,
            self._SHADOW_R, self._SHADOW_B,
        )

        self._content = QWidget(self)
        self._content.setObjectName("toastContent")
        outer.addWidget(self._content)

        # 内容区：纵向（文字行 + 按钮行）
        v = QVBoxLayout(self._content)
        v.setContentsMargins(14, 10, 10, 10)
        v.setSpacing(6)

        # ── 上行：文字 + 占位按钮（隐藏的 X） ──────────────── #
        h = QHBoxLayout()
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(10)

        text_col = QVBoxLayout()
        text_col.setSpacing(3)

        self._title_lbl = QLabel(title)
        self._title_lbl.setWordWrap(True)

        self._msg_lbl = QLabel(message)
        self._msg_lbl.setWordWrap(True)
        self._msg_lbl.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )

        text_col.addWidget(self._title_lbl)
        if message:
            text_col.addWidget(self._msg_lbl)

        h.addLayout(text_col, 1)

        # 保留隐藏的 close_btn 以兼容父类 _apply_theme
        self._close_btn = QPushButton()
        self._close_btn.hide()
        self._close_btn.clicked.connect(self._request_close)
        h.addWidget(self._close_btn, 0, Qt.AlignmentFlag.AlignTop)

        v.addLayout(h)

        # ── 下行：操作按钮 ──────────────────────────────────── #
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 2, 0, 0)
        btn_row.setSpacing(6)

        self._always_btn = QPushButton(self._i18n.t("perm.dialog.always"))
        self._always_btn.setFixedHeight(26)
        self._always_btn.setMinimumWidth(104)
        self._always_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        self._once_btn = QPushButton(self._i18n.t("perm.dialog.once"))
        self._once_btn.setFixedHeight(26)
        self._once_btn.setMinimumWidth(96)
        self._once_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        self._deny_btn = QPushButton(self._i18n.t("perm.dialog.deny"))
        self._deny_btn.setFixedHeight(26)
        self._deny_btn.setMinimumWidth(76)
        self._deny_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        btn_row.addStretch()
        btn_row.addWidget(self._always_btn)
        btn_row.addWidget(self._once_btn)
        btn_row.addWidget(self._deny_btn)

        v.addLayout(btn_row)

        self._always_btn.clicked.connect(self._on_always)
        self._once_btn.clicked.connect(self._on_once)
        self._deny_btn.clicked.connect(self._on_deny)

    # ── 主题 ────────────────────────────────────────────── #

    def _apply_theme(self) -> None:
        super()._apply_theme()
        dark = isDarkTheme()
        if dark:
            base_bg    = "rgba(255,255,255,15)"
            base_hover = "rgba(255,255,255,30)"
            base_c     = "#e0e0e0"
            base_bdr   = "rgba(255,255,255,30)"
            always_bg  = "rgba(39,174,96,200)"
            always_h   = "rgba(39,174,96,255)"
            deny_bg    = "rgba(231,76,60,180)"
            deny_h     = "rgba(231,76,60,240)"
        else:
            base_bg    = "rgba(0,0,0,8)"
            base_hover = "rgba(0,0,0,18)"
            base_c     = "#333333"
            base_bdr   = "rgba(0,0,0,25)"
            always_bg  = "#27ae60"
            always_h   = "#2ecc71"
            deny_bg    = "#e74c3c"
            deny_h     = "#c0392b"

        btn_style = (
            "QPushButton {"
            f"  background: {base_bg}; color: {base_c};"
            f"  border: 1px solid {base_bdr};"
            "  border-radius: 5px; font-size: 9pt; padding: 2px 10px;"
            "}"
            f"QPushButton:hover {{ background: {base_hover}; }}"
        )
        always_style = (
            "QPushButton {"
            f"  background: {always_bg}; color: white;"
            "  border: none; border-radius: 5px; font-size: 9pt; padding: 2px 10px;"
            "}"
            f"QPushButton:hover {{ background: {always_h}; }}"
        )
        deny_style = (
            "QPushButton {"
            f"  background: {deny_bg}; color: white;"
            "  border: none; border-radius: 5px; font-size: 9pt; padding: 2px 10px;"
            "}"
            f"QPushButton:hover {{ background: {deny_h}; }}"
        )

        self._always_btn.setStyleSheet(always_style)
        self._once_btn.setStyleSheet(btn_style)
        self._deny_btn.setStyleSheet(deny_style)

    # ── 按钮响应 ─────────────────────────────────────────── #

    def _on_always(self) -> None:
        self._perm_result = "always"
        self._request_close()
        self._quit_loop()

    def _on_once(self) -> None:
        self._perm_result = "once"
        self._request_close()
        self._quit_loop()

    def _on_deny(self) -> None:
        self._perm_result = "deny"
        self._request_close()
        self._quit_loop()

    def _quit_loop(self) -> None:
        if self._loop is not None and self._loop.isRunning():
            self._loop.quit()

    # ── 同步阻塞等待 ──────────────────────────────────────── #

    def exec(self) -> str:  # type: ignore[override]
        """同步阻塞，等待用户点击操作按钮。
        返回 ``"always"`` / ``"once"`` / ``"deny"``。
        """
        self._loop = QEventLoop(self)
        self._loop.exec()
        return self._perm_result

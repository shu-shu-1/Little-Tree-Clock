"""登录方式配置窗口：由宿主提供导航框架，页面内容由登录方式提供。"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    BreadcrumbBar,
    FluentIcon as FIF,
    FluentWidget,
    InfoBar,
    InfoBarPosition,
    PrimaryPushButton,
    PushButton,
    TitleLabel,
)

from app.constants import ICON_PATH
from app.services.permission_service import AuthMethodConfigSpec


class PermissionAuthMethodConfigWindow(FluentWidget):
    """登录方式配置向导窗口。"""

    saved = Signal()

    def __init__(self, spec: AuthMethodConfigSpec, parent=None):
        super().__init__(parent)
        self._spec = spec
        self._state: dict[str, Any] = dict(spec.initial_state or {})
        self._syncing_breadcrumb = False
        self._max_unlocked_step = 0
        self._ok = False

        self._stack = QStackedWidget(self)
        self._breadcrumb = BreadcrumbBar(self)
        self._breadcrumb.setSpacing(10)

        self._back_button = PushButton(FIF.LEFT_ARROW, "上一步", self)
        self._next_button = PrimaryPushButton(FIF.RIGHT_ARROW, "下一步", self)
        self._cancel_button = PushButton(FIF.CANCEL, "取消", self)

        self._routes = [f"auth_method_step_{idx}" for idx in range(len(self._spec.pages))]
        self._page_widgets: list[QWidget] = []

        self._build_ui()
        self._bind_signals()
        self._set_step(0)

    @property
    def accepted(self) -> bool:
        return self._ok

    def _build_ui(self) -> None:
        self.resize(860, 620)
        self.setMinimumSize(760, 540)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle(self._spec.window_title or "登录方式配置")
        if ICON_PATH:
            self.setWindowIcon(QIcon(ICON_PATH))

        root = QVBoxLayout(self)
        root.setContentsMargins(26, self.titleBar.height() + 16, 26, 24)
        root.setSpacing(12)

        title = TitleLabel(self._spec.window_title or "登录方式配置", self)
        subtitle = BodyLabel("页面内容由登录方式提供。", self)
        subtitle.setWordWrap(True)

        root.addWidget(title)
        root.addWidget(subtitle)

        if len(self._spec.pages) > 1:
            root.addWidget(self._breadcrumb)
        else:
            self._breadcrumb.hide()

        for page in self._spec.pages:
            widget = page.widget_factory(self._stack, self._state)
            page_widget = widget if isinstance(widget, QWidget) else QWidget(self._stack)
            self._page_widgets.append(page_widget)
            self._stack.addWidget(page_widget)

        root.addWidget(self._stack, 1)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        footer.addStretch()

        self._back_button.setMinimumWidth(108)
        self._next_button.setMinimumWidth(108)
        self._cancel_button.setMinimumWidth(108)

        footer.addWidget(self._cancel_button)
        footer.addWidget(self._back_button)
        footer.addWidget(self._next_button)
        root.addLayout(footer)

    def _bind_signals(self) -> None:
        self._back_button.clicked.connect(self._go_previous)
        self._next_button.clicked.connect(self._go_next)
        self._cancel_button.clicked.connect(self.close)
        self._breadcrumb.currentItemChanged.connect(self._on_breadcrumb_changed)

    def _refresh_breadcrumb(self) -> None:
        if len(self._spec.pages) <= 1:
            return

        current_step = self._stack.currentIndex()
        self._syncing_breadcrumb = True
        self._breadcrumb.blockSignals(True)
        try:
            self._breadcrumb.clear()
            for idx in range(self._max_unlocked_step + 1):
                title = self._spec.pages[idx].title or f"步骤 {idx + 1}"
                self._breadcrumb.addItem(self._routes[idx], title)
            self._breadcrumb.setCurrentItem(self._routes[current_step])
        finally:
            self._breadcrumb.blockSignals(False)
            self._syncing_breadcrumb = False

    def _set_step(self, index: int) -> None:
        last_step = len(self._spec.pages) - 1
        idx = max(0, min(last_step, index))
        self._max_unlocked_step = max(self._max_unlocked_step, idx)
        self._stack.setCurrentIndex(idx)

        self._back_button.setVisible(idx > 0)
        self._next_button.setText("完成" if idx == last_step else "下一步")

        self._refresh_breadcrumb()

    def _show_error(self, message: str) -> None:
        InfoBar.error(
            title="登录方式配置",
            content=message,
            parent=self,
            position=InfoBarPosition.TOP,
            duration=3500,
        )

    def _validate_current_page(self) -> tuple[bool, str]:
        idx = self._stack.currentIndex()
        page_spec = self._spec.pages[idx]
        if page_spec.before_next is None:
            return True, ""

        widget = self._page_widgets[idx]
        result = page_spec.before_next(widget, self._state)
        if isinstance(result, tuple):
            return bool(result[0]), str(result[1] or "")
        return bool(result), ""

    def _finish(self) -> bool:
        if self._spec.on_finish is None:
            self._ok = True
            self.saved.emit()
            return True

        result = self._spec.on_finish(self._state)
        if isinstance(result, tuple):
            ok, msg = bool(result[0]), str(result[1] or "")
        else:
            ok, msg = bool(result), ""

        if not ok:
            self._show_error(msg or "保存失败")
            return False

        self._ok = True
        self.saved.emit()
        return True

    def _go_previous(self) -> None:
        self._set_step(self._stack.currentIndex() - 1)

    def _go_next(self) -> None:
        ok, message = self._validate_current_page()
        if not ok:
            self._show_error(message or "当前步骤校验失败")
            return

        current = self._stack.currentIndex()
        last = len(self._spec.pages) - 1
        if current >= last:
            if self._finish():
                self.close()
            return

        self._set_step(current + 1)

    def _on_breadcrumb_changed(self, route_key: str) -> None:
        if self._syncing_breadcrumb:
            return
        if route_key not in self._routes:
            return
        target = self._routes.index(route_key)
        if target > self._max_unlocked_step:
            return
        self._set_step(target)


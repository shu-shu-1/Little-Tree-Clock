"""延迟创建 QWidget 的轻量容器。"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout
from qfluentwidgets import BodyLabel, CaptionLabel

from app.utils.logger import logger


class LazyFactoryWidget(QWidget):
    """首次显示时再调用工厂创建真实内容的容器。"""

    def __init__(
        self,
        factory: Callable[[], Optional[QWidget]],
        *,
        loading_text: str = "正在加载…",
        empty_text: str = "暂无内容",
        error_text: str = "加载失败",
        debug_name: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self._factory = factory
        self._loading_text = loading_text
        self._empty_text = empty_text
        self._error_text = error_text
        self._debug_name = debug_name or self.__class__.__name__
        self._load_started = False
        self._loaded = False
        self._content_widget: Optional[QWidget] = None

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        self._placeholder = QWidget(self)
        placeholder_layout = QVBoxLayout(self._placeholder)
        placeholder_layout.setContentsMargins(24, 24, 24, 24)
        placeholder_layout.setSpacing(6)
        placeholder_layout.setAlignment(Qt.AlignCenter)

        self._title_label = BodyLabel(loading_text)
        self._title_label.setAlignment(Qt.AlignCenter)
        self._title_label.setWordWrap(True)

        self._detail_label = CaptionLabel("")
        self._detail_label.setAlignment(Qt.AlignCenter)
        self._detail_label.setWordWrap(True)
        self._detail_label.hide()

        placeholder_layout.addWidget(self._title_label)
        placeholder_layout.addWidget(self._detail_label)
        self._layout.addWidget(self._placeholder, 1, Qt.AlignCenter)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._load_started and not self._loaded:
            QTimer.singleShot(0, self.load_now)

    def load_now(self) -> None:
        """立即尝试创建真实内容。"""
        if self._load_started or self._loaded:
            return
        self._load_started = True

        try:
            widget = self._factory()
        except Exception as exc:
            self._loaded = True
            logger.exception("延迟加载组件失败：{}", self._debug_name)
            self._set_status(self._error_text, str(exc))
            return

        self._loaded = True
        if widget is None:
            self._set_status(self._empty_text)
            return

        self._content_widget = widget
        if self.objectName() and not widget.objectName():
            widget.setObjectName(self.objectName())
        widget.setParent(self)
        self._layout.removeWidget(self._placeholder)
        self._placeholder.hide()
        self._layout.addWidget(widget)
        self.updateGeometry()

    def content_widget(self) -> Optional[QWidget]:
        return self._content_widget

    def _set_status(self, title: str, detail: str = "") -> None:
        self._title_label.setText(title)
        if detail:
            self._detail_label.setText(detail)
            self._detail_label.show()
        else:
            self._detail_label.clear()
            self._detail_label.hide()
        self._placeholder.show()

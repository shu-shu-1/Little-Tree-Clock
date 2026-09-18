"""占位符页面（尚未实现的功能页）"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout
from qfluentwidgets import (
    Flyout,
    FlyoutAnimationType,
    InfoBar,
    InfoBarIcon,
    InfoBarPosition,
    PushButton,
    SubtitleLabel,
)

from app.services.i18n_service import pick


class PlaceholderWidget(QFrame):
    """尚未实现的功能模块占位页面"""

    def __init__(self, text: str, parent=None):
        super().__init__(parent=parent)
        self.setObjectName(text.replace(" ", "-"))

        layout = QHBoxLayout(self)
        layout.addWidget(SubtitleLabel(text))

        self._btn = PushButton(text=pick("消息测试", "Message Test"))
        self._btn.clicked.connect(self._show_test_messages)
        layout.addWidget(self._btn)

    def _show_test_messages(self):
        for level, title in (
            ("info", "Info"),
            ("warning", "Warning"),
            ("error", "Error"),
            ("success", "Success"),
        ):
            getattr(InfoBar, level)(
                title=pick(f"{title} 测试", f"{title} Test"),
                content=pick("测试消息", "Test message"),
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=-1,
                parent=self,
            )

        Flyout.create(
            icon=InfoBarIcon.SUCCESS,
            title=pick("测试完毕", "Test Complete"),
            content=pick("所有消息弹窗测试执行完毕！", "All test messages have been shown!"),
            target=self._btn,
            parent=self,
            isClosable=True,
            aniType=FlyoutAnimationType.PULL_UP,
        )

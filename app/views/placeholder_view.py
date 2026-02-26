"""占位符页面（尚未实现的功能页）"""
from qfluentwidgets import SubtitleLabel, PushButton, InfoBar, InfoBarPosition, Flyout, FlyoutAnimationType, InfoBarIcon
from PySide6.QtWidgets import QFrame, QHBoxLayout
from PySide6.QtCore import Qt


class PlaceholderWidget(QFrame):
    """通用占位符页面，用于尚未实现的功能模块"""

    def __init__(self, text: str, parent=None):
        super().__init__(parent=parent)
        self.setObjectName(text.replace(" ", "-"))

        layout = QHBoxLayout(self)
        layout.addWidget(SubtitleLabel(text))

        self._btn = PushButton(text="消息测试")
        self._btn.clicked.connect(self._show_test_messages)
        layout.addWidget(self._btn)

    def _show_test_messages(self):
        for level, title in (
            ("info",    "Info"),
            ("warning", "Warning"),
            ("error",   "Error"),
            ("success", "Success"),
        ):
            getattr(InfoBar, level)(
                title=f"{title} 测试",
                content="测试消息",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=-1,
                parent=self,
            )

        Flyout.create(
            icon=InfoBarIcon.SUCCESS,
            title="测试完毕",
            content="所有消息弹窗测试执行完毕！",
            target=self._btn,
            parent=self,
            isClosable=True,
            aniType=FlyoutAnimationType.PULL_UP,
        )

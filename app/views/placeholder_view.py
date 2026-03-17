"""占位符页面（尚未实现的功能页）"""
from qfluentwidgets import SubtitleLabel, PushButton, InfoBar, InfoBarPosition, Flyout, FlyoutAnimationType, InfoBarIcon
from PySide6.QtWidgets import QFrame, QHBoxLayout
from PySide6.QtCore import Qt
from app.services.i18n_service import I18nService, LANG_EN_US


def _tr(i18n: I18nService, zh: str, en: str) -> str:
    return en if i18n.language == LANG_EN_US else zh


class PlaceholderWidget(QFrame):
    """通用占位符页面，用于尚未实现的功能模块"""

    def __init__(self, text: str, parent=None):
        super().__init__(parent=parent)
        self.setObjectName(text.replace(" ", "-"))
        self._i18n = I18nService.instance()

        layout = QHBoxLayout(self)
        layout.addWidget(SubtitleLabel(text))

        self._btn = PushButton(text=_tr(self._i18n, "消息测试", "Message Test"))
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
                title=_tr(self._i18n, f"{title} 测试", f"{title} Test"),
                content=_tr(self._i18n, "测试消息", "Test message"),
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=-1,
                parent=self,
            )

        Flyout.create(
            icon=InfoBarIcon.SUCCESS,
            title=_tr(self._i18n, "测试完毕", "Test Complete"),
            content=_tr(self._i18n, "所有消息弹窗测试执行完毕！", "All test messages have been shown!"),
            target=self._btn,
            parent=self,
            isClosable=True,
            aniType=FlyoutAnimationType.PULL_UP,
        )

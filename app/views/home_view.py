"""主页视图"""
from PySide6.QtCore import QRect
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import QFrame, QLabel

from app.services.i18n_service import I18nService

_FONT_FAMILY = "霞鹜新晰黑"


class HomeView(QFrame):
    """应用主页"""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("home")
        self.resize(791, 536)
        self._i18n = I18nService.instance()

        # 应用名称大标题
        self.title_label = QLabel(self)
        self.title_label.setObjectName("title_label")
        self.title_label.setGeometry(QRect(50, 90, 301, 91))
        title_font = QFont()
        title_font.setFamilies([_FONT_FAMILY])
        title_font.setPointSize(24)
        self.title_label.setFont(title_font)
        self.title_label.setText(self._i18n.t("home.title"))

        # 版本标签
        self.version_label = QLabel(self)
        self.version_label.setObjectName("version_label")
        self.version_label.setGeometry(QRect(240, 90, 101, 21))
        version_font = QFont()
        version_font.setFamilies([_FONT_FAMILY])
        self.version_label.setFont(version_font)
        self.version_label.setText(self._i18n.t("home.version"))

        # 图标
        self.icon_label = QLabel(self)
        self.icon_label.setObjectName("icon_label")
        self.icon_label.setGeometry(QRect(50, 40, 61, 61))
        self.icon_label.setPixmap(QPixmap(":/icon/icon.png"))
        self.icon_label.setScaledContents(True)

        # 提示文字
        self.hint_label = QLabel(self)
        self.hint_label.setObjectName("hint_label")
        self.hint_label.setGeometry(QRect(50, 180, 201, 41))
        hint_font = QFont()
        hint_font.setFamilies([_FONT_FAMILY])
        hint_font.setPointSize(11)
        self.hint_label.setFont(hint_font)
        self.hint_label.setText(self._i18n.t("home.hint"))

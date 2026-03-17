"""公告弹窗组件。"""
from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    MessageBoxBase,
    PrimaryPushButton,
    PushButton,
    StrongBodyLabel,
    SubtitleLabel,
)

from app.services.i18n_service import I18nService
from app.services.remote_resource_service import Announcement


_ANNOUNCEMENT_STYLE = {
    "info": {
        "icon": "ℹ️",
        "light_bg": "rgba(220, 235, 255, 120)",
        "light_border": "rgba(80, 140, 220, 45)",
        "light_title": "#245ea8",
        "light_text": "#4f6070",
        "dark_bg": "rgba(30, 60, 90, 110)",
        "dark_border": "rgba(80, 140, 220, 50)",
        "dark_title": "#7fb3ff",
        "dark_text": "#c9d6e6",
    },
    "warning": {
        "icon": "⚠️",
        "light_bg": "rgba(255, 244, 214, 130)",
        "light_border": "rgba(216, 165, 32, 55)",
        "light_title": "#9d6200",
        "light_text": "#6e5a34",
        "dark_bg": "rgba(88, 62, 10, 115)",
        "dark_border": "rgba(255, 193, 7, 45)",
        "dark_title": "#ffd86a",
        "dark_text": "#ead9ab",
    },
    "error": {
        "icon": "⛔",
        "light_bg": "rgba(255, 226, 226, 135)",
        "light_border": "rgba(220, 53, 69, 55)",
        "light_title": "#b42318",
        "light_text": "#7a3d3d",
        "dark_bg": "rgba(96, 32, 32, 120)",
        "dark_border": "rgba(244, 67, 54, 50)",
        "dark_title": "#ff8d85",
        "dark_text": "#f0c5c1",
    },
}


def _style_for(level: str) -> dict[str, str]:
    return _ANNOUNCEMENT_STYLE.get(level, _ANNOUNCEMENT_STYLE["info"])


def _level_text(level: str, i18n: I18nService) -> str:
    return i18n.t(f"announcement.level.{level}", default=level.upper())


class AnnouncementPopupDialog(MessageBoxBase):
    """启动时错误级公告弹窗。"""

    def __init__(self, announcement: Announcement, parent=None):
        super().__init__(parent)
        self._announcement = announcement
        self._i18n = I18nService.instance()
        self._mute_requested = False

        self.yesButton.hide()
        self.cancelButton.hide()
        self.widget.setMinimumWidth(500)

        title = SubtitleLabel(
            self._i18n.t(
                "announcement.popup.title",
                default="重要公告",
            ),
            self,
        )
        title.setWordWrap(True)

        headline = StrongBodyLabel(
            f"{_style_for(announcement.level)['icon']} {announcement.display_title(self._i18n.language)}",
            self,
        )
        headline.setWordWrap(True)

        meta = CaptionLabel(
            self._i18n.t(
                "announcement.popup.meta",
                default="等级：{level} · 日期：{date}",
                level=_level_text(announcement.level, self._i18n),
                date=announcement.date or "--",
            ),
            self,
        )
        meta.setWordWrap(True)

        content = BodyLabel(announcement.display_content(self._i18n.language), self)
        content.setWordWrap(True)
        content.setMinimumWidth(440)

        self.viewLayout.insertWidget(0, title)
        self.viewLayout.insertSpacing(1, 4)
        self.viewLayout.insertWidget(2, headline)
        self.viewLayout.insertWidget(3, meta)
        self.viewLayout.insertSpacing(4, 6)
        self.viewLayout.insertWidget(5, content)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch()

        close_btn = PushButton(self._i18n.t("announcement.popup.close", default="关闭"), self)
        mute_btn = PrimaryPushButton(
            self._i18n.t("announcement.popup.mute", default="不再弹出此公告"),
            self,
        )
        close_btn.clicked.connect(self._on_close)
        mute_btn.clicked.connect(self._on_mute)

        btn_row.addWidget(close_btn)
        btn_row.addWidget(mute_btn)
        self.viewLayout.addSpacing(10)
        self.viewLayout.addLayout(btn_row)

    @property
    def mute_requested(self) -> bool:
        return self._mute_requested

    def _on_close(self) -> None:
        self._mute_requested = False
        self.reject()

    def _on_mute(self) -> None:
        self._mute_requested = True
        self.accept()

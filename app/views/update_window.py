"""独立更新窗口。"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QHBoxLayout, QProgressBar, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    FluentIcon as FIF,
    FluentWidget,
    InfoBar,
    InfoBarPosition,
    PrimaryPushButton,
    PushButton,
    TextEdit,
    TitleLabel,
)

from app.constants import APP_NAME, APP_VERSION, ICON_PATH
from app.services.i18n_service import I18nService, LANG_EN_US
from app.services.update_service import UpdateInfo, UpdateService


def _tr(zh: str, en: str) -> str:
    return en if I18nService.instance().language == LANG_EN_US else zh


def _channel_label(channel: str) -> str:
    mapping = {
        "stable": _tr("稳定版（推荐）", "Stable (recommended)"),
        "beta": _tr("测试版", "Beta"),
        "dev": _tr("开发版", "Dev"),
    }
    return mapping.get(str(channel or "").strip().lower(), str(channel or "stable"))


class UpdateWindow(FluentWidget):
    """显示更新说明并负责触发下载安装。"""

    launchInstallerRequested = Signal(str, object)

    def __init__(self, update_service: UpdateService, parent=None):
        super().__init__(parent)
        self._i18n = I18nService.instance()
        self._service = update_service
        self._mode = "status"
        self._current_info: UpdateInfo | None = None

        self._build_ui()
        self._bind_signals()
        self._apply_view()

    def _build_ui(self) -> None:
        self.resize(880, 680)
        self.setMinimumSize(780, 600)
        if ICON_PATH:
            self.setWindowIcon(QIcon(ICON_PATH))
        self.setWindowTitle(APP_NAME)

        root = QVBoxLayout(self)
        root.setContentsMargins(26, self.titleBar.height() + 16, 26, 24)
        root.setSpacing(12)

        self._title_label = TitleLabel("", self)
        self._subtitle_label = BodyLabel("", self)
        self._subtitle_label.setWordWrap(True)
        self._meta_label = CaptionLabel("", self)
        self._hint_label = CaptionLabel("", self)
        self._hint_label.setWordWrap(True)

        root.addWidget(self._title_label)
        root.addWidget(self._subtitle_label)
        root.addWidget(self._meta_label)
        root.addWidget(self._hint_label)

        self._action_card = CardWidget(self)
        action_layout = QHBoxLayout(self._action_card)
        action_layout.setContentsMargins(16, 12, 16, 12)
        action_layout.setSpacing(8)

        self._refresh_btn = PushButton(FIF.SYNC, _tr("重新检查", "Refresh"), self._action_card)
        self._detail_btn = PushButton(FIF.LINK, _tr("查看详情", "View Details"), self._action_card)
        self._close_btn = PushButton(FIF.CANCEL, _tr("关闭", "Close"), self._action_card)
        self._update_btn = PrimaryPushButton(FIF.DOWNLOAD, _tr("立即更新", "Update Now"), self._action_card)

        action_layout.addWidget(self._refresh_btn)
        action_layout.addWidget(self._detail_btn)
        action_layout.addStretch()
        action_layout.addWidget(self._close_btn)
        action_layout.addWidget(self._update_btn)
        root.addWidget(self._action_card)

        self._progress_card = CardWidget(self)
        progress_layout = QVBoxLayout(self._progress_card)
        progress_layout.setContentsMargins(16, 12, 16, 12)
        progress_layout.setSpacing(6)

        self._progress_label = CaptionLabel("", self._progress_card)
        self._progress_bar = QProgressBar(self._progress_card)
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(True)
        progress_layout.addWidget(self._progress_label)
        progress_layout.addWidget(self._progress_bar)
        root.addWidget(self._progress_card)

        self._changelog_card = CardWidget(self)
        changelog_layout = QVBoxLayout(self._changelog_card)
        changelog_layout.setContentsMargins(16, 12, 16, 12)
        changelog_layout.setSpacing(8)
        changelog_layout.addWidget(BodyLabel(_tr("更新内容", "Changelog"), self._changelog_card))

        self._changelog_edit = TextEdit(self._changelog_card)
        self._changelog_edit.setReadOnly(True)
        self._changelog_edit.setMinimumHeight(380)
        changelog_layout.addWidget(self._changelog_edit)
        root.addWidget(self._changelog_card, 1)

    def _bind_signals(self) -> None:
        self._refresh_btn.clicked.connect(self._on_refresh_clicked)
        self._detail_btn.clicked.connect(self._on_detail_clicked)
        self._close_btn.clicked.connect(self.close)
        self._update_btn.clicked.connect(self._on_update_clicked)

        self._service.stateChanged.connect(self._on_service_state_changed)
        self._service.downloadStarted.connect(self._on_download_started)
        self._service.downloadProgress.connect(self._on_download_progress)
        self._service.downloadFinished.connect(self._on_download_finished)
        self._service.downloadFailed.connect(self._on_download_failed)

    def show_available(self, info: UpdateInfo | None = None) -> None:
        self._mode = "available"
        self._current_info = info or self._service.latest_info
        self._apply_view()
        self._show_top_level()

    def show_post_update(self, info: UpdateInfo) -> None:
        self._mode = "post"
        self._current_info = info
        self._apply_view()
        self._show_top_level()

    def show_status(self, info: UpdateInfo | None = None) -> None:
        self._mode = "status"
        self._current_info = info or self._service.latest_info
        self._apply_view()
        self._show_top_level()

    def _show_top_level(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    def _apply_view(self) -> None:
        info = self._current_info
        has_update = self._service.is_update_available(info)
        auto_upgrade_supported = self._service.is_auto_upgrade_supported(info)
        is_post_mode = self._mode == "post" and info is not None

        if is_post_mode:
            self._title_label.setText(_tr("更新完成", "Update Installed"))
            self._subtitle_label.setText(
                _tr(
                    f"当前已更新到 v{info.version}，这是更新后首次启动展示的更新内容。",
                    f"Little Tree Clock has been updated to v{info.version}. This is the first-start changelog cached before update.",
                )
            )
            self._hint_label.setText(
                _tr(
                    "此页面内容来自更新前缓存，不包含安装按钮。",
                    "This page uses changelog content cached before the installer was launched.",
                )
            )
        elif has_update and info is not None:
            self._title_label.setText(_tr("发现新版本", "Update Available"))
            self._subtitle_label.setText(
                _tr(
                    f"当前版本 v{APP_VERSION}，检测到可更新到 v{info.version}。",
                    f"A newer version is available: v{APP_VERSION} -> v{info.version}.",
                )
            )
            if auto_upgrade_supported:
                self._hint_label.setText(
                    _tr(
                        "点击“立即更新”后会下载安装程序，启动安装器并关闭当前程序以完成更新。",
                        "Click 'Update Now' to download the installer, launch it, and close the current app for update.",
                    )
                )
            else:
                self._hint_label.setText(
                    _tr(
                        f"当前版本低于自动升级最低要求 v{info.min_version}，请查看详情后手动升级。",
                        f"Your current version is lower than the minimum auto-upgrade version v{info.min_version}. Please open details and upgrade manually.",
                    )
                )
        else:
            self._title_label.setText(_tr("当前已是最新版本", "Already Up To Date"))
            self._subtitle_label.setText(
                _tr(
                    f"当前版本 v{APP_VERSION} 在所选频道暂无可用更新。",
                    f"No newer version is available for v{APP_VERSION} in the selected channel.",
                )
            )
            self._hint_label.setText(
                _tr(
                    "你仍然可以查看当前缓存的更新说明或重新检查。",
                    "You can still review cached changelog content or refresh the update check.",
                )
            )

        channel_text = _channel_label(info.channel) if info is not None else _channel_label(self._service.current_channel)
        latest_version = info.version if info is not None and info.version else "-"
        release_date = info.release_date if info is not None and info.release_date else "-"
        min_version = info.min_version if info is not None and info.min_version else "-"
        mandatory = _tr("是", "Yes") if info is not None and info.mandatory else _tr("否", "No")
        if is_post_mode and info is not None:
            self._meta_label.setText(
                _tr(
                    f"已安装版本：v{info.version}  ·  更新频道：{channel_text}  ·  发布时间：{release_date}  ·  强制更新：{mandatory}",
                    f"Installed version: v{info.version}  ·  Update channel: {channel_text}  ·  Release date: {release_date}  ·  Mandatory: {mandatory}",
                )
            )
        else:
            self._meta_label.setText(
                _tr(
                    f"频道：{channel_text}  ·  最新版本：{latest_version}  ·  发布日期：{release_date}  ·  最低自动升级版本：{min_version}  ·  强制更新：{mandatory}",
                    f"Channel: {channel_text}  ·  Latest version: {latest_version}  ·  Release date: {release_date}  ·  Min auto-upgrade version: {min_version}  ·  Mandatory: {mandatory}",
                )
            )

        self._refresh_btn.setVisible(not is_post_mode)
        self._update_btn.setVisible(self._mode == "available" and has_update)
        self._update_btn.setEnabled(self._mode == "available" and has_update and auto_upgrade_supported and not self._service.is_downloading)
        self._detail_btn.setEnabled(bool(info and info.resolved_detail_url))

        downloading = self._service.is_downloading and self._mode == "available"
        self._progress_card.setVisible(downloading)
        if not downloading:
            self._progress_label.clear()
            self._progress_bar.setValue(0)

        changelog = info.changelog if info is not None and info.changelog else _tr("暂无更新说明。", "No changelog available.")
        try:
            self._changelog_edit.setMarkdown(changelog)
        except Exception:
            self._changelog_edit.setPlainText(changelog)

    def _on_refresh_clicked(self) -> None:
        started = self._service.check_for_updates()
        if not started:
            InfoBar.info(
                title=_tr("更新检查", "Update Check"),
                content=_tr("更新检查正在进行中。", "Update check is already running."),
                parent=self,
                position=InfoBarPosition.TOP,
                duration=2500,
            )

    def _on_detail_clicked(self) -> None:
        info = self._current_info
        if info is None:
            return
        target = info.resolved_detail_url
        if not target or not QDesktopServices.openUrl(QUrl(target)):
            InfoBar.warning(
                title=_tr("无法打开详情", "Cannot Open Details"),
                content=_tr("无法打开更新详情链接。", "Failed to open the update details link."),
                parent=self,
                position=InfoBarPosition.TOP,
                duration=3000,
            )

    def _on_update_clicked(self) -> None:
        if self._current_info is None:
            return
        started = self._service.download_update(self._current_info)
        if not started:
            InfoBar.warning(
                title=_tr("无法开始更新", "Cannot Start Update"),
                content=_tr("更新下载已在进行中，或当前状态不支持自动升级。", "Download is already running, or auto-upgrade is unavailable."),
                parent=self,
                position=InfoBarPosition.TOP,
                duration=3000,
            )

    def _on_service_state_changed(self) -> None:
        if self._mode == "post":
            return
        if self._current_info is None or self._current_info.channel == self._service.current_channel:
            self._current_info = self._service.latest_info
        self._apply_view()

    def _on_download_started(self, info: object) -> None:
        if not isinstance(info, UpdateInfo):
            return
        if self._current_info is None or info.stable_id != self._current_info.stable_id:
            return
        self._progress_card.show()
        self._progress_label.setText(_tr("准备下载更新安装包…", "Preparing update download..."))
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._apply_view()

    def _on_download_progress(self, received: int, total: int, text: str) -> None:
        if self._mode != "available":
            return
        self._progress_card.show()
        if total > 0:
            self._progress_bar.setRange(0, 100)
            self._progress_bar.setValue(min(100, int(received * 100 / total)))
        else:
            self._progress_bar.setRange(0, 0)
        self._progress_label.setText(text)

    def _on_download_finished(self, _archive_path: str, installer_path: str, info: object) -> None:
        if not isinstance(info, UpdateInfo):
            return
        if self._current_info is None or info.stable_id != self._current_info.stable_id:
            return
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(100)
        self._progress_label.setText(_tr("下载完成，正在启动安装程序…", "Download complete, launching installer..."))
        self.launchInstallerRequested.emit(installer_path, info)

    def _on_download_failed(self, error: str) -> None:
        if self._mode != "available":
            return
        self._progress_card.hide()
        self._apply_view()
        InfoBar.error(
            title=_tr("更新失败", "Update Failed"),
            content=error,
            parent=self,
            position=InfoBarPosition.TOP,
            duration=4000,
        )
"""插件包文件打开窗口。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QStackedWidget, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    BreadcrumbBar,
    CardWidget,
    FluentIcon as FIF,
    FluentWidget,
    PrimaryPushButton,
    PushButton,
    StrongBodyLabel,
    SubtitleLabel,
    TitleLabel,
)

from app.constants import APP_NAME, ICON_PATH


class PluginFileOpenWindow(FluentWidget):
    """用于确认是否导入 .ltcplugin 的多步骤窗口。"""

    importRequested = Signal(str)

    _ROUTE_INFO = "plugin_open_info"
    _ROUTE_CONFIRM = "plugin_open_confirm"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_file_path = ""
        self._package_info: dict[str, Any] = {}
        self._syncing_breadcrumb = False
        self._max_unlocked_step = 0

        self._steps: list[tuple[str, str]] = [
            (self._ROUTE_INFO, "插件信息"),
            (self._ROUTE_CONFIRM, "确认导入"),
        ]
        self._route_to_step = {route: idx for idx, (route, _) in enumerate(self._steps)}

        self._build_ui()
        self._bind_signals()
        self._set_step(0)

    def _build_ui(self) -> None:
        self.resize(760, 560)
        self.setMinimumSize(700, 500)
        if ICON_PATH:
            self.setWindowIcon(QIcon(ICON_PATH))
        self.setWindowTitle(f"{APP_NAME} - 打开插件包")

        root = QVBoxLayout(self)
        root.setContentsMargins(26, self.titleBar.height() + 16, 26, 24)
        root.setSpacing(12)

        self._header_title = TitleLabel("打开插件包", self)
        self._header_subtitle = BodyLabel(
            "已检测到插件安装包，请先查看插件信息，再确认是否导入。",
            self,
        )
        self._header_subtitle.setWordWrap(True)

        self._breadcrumb = BreadcrumbBar(self)
        self._breadcrumb.setSpacing(10)

        self._stack = QStackedWidget(self)
        self._build_info_page()
        self._build_confirm_page()

        root.addWidget(self._header_title)
        root.addWidget(self._header_subtitle)
        root.addWidget(self._breadcrumb)
        root.addWidget(self._stack, 1)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        footer.addStretch()

        self._cancel_btn = PushButton(FIF.CANCEL, "取消", self)
        self._back_btn = PushButton(FIF.LEFT_ARROW, "上一步", self)
        self._next_btn = PrimaryPushButton(FIF.RIGHT_ARROW, "下一步", self)
        self._import_btn = PrimaryPushButton(FIF.DOWN, "导入插件", self)

        footer.addWidget(self._cancel_btn)
        footer.addWidget(self._back_btn)
        footer.addWidget(self._next_btn)
        footer.addWidget(self._import_btn)
        root.addLayout(footer)

    def _build_info_page(self) -> None:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(12)

        info_card = CardWidget(page)
        info_layout = QHBoxLayout(info_card)
        info_layout.setContentsMargins(18, 14, 18, 14)
        info_layout.setSpacing(14)

        self._icon_label = QLabel(info_card)
        self._icon_label.setFixedSize(96, 96)
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        right = QVBoxLayout()
        right.setSpacing(6)

        self._plugin_name = SubtitleLabel("", info_card)
        self._plugin_id = BodyLabel("", info_card)
        self._plugin_version = BodyLabel("", info_card)
        self._plugin_author = BodyLabel("", info_card)
        self._plugin_type = BodyLabel("", info_card)
        self._plugin_desc = BodyLabel("", info_card)
        self._plugin_desc.setWordWrap(True)
        self._plugin_homepage = BodyLabel("", info_card)
        self._plugin_homepage.setWordWrap(True)

        right.addWidget(self._plugin_name)
        right.addWidget(self._plugin_id)
        right.addWidget(self._plugin_version)
        right.addWidget(self._plugin_author)
        right.addWidget(self._plugin_type)
        right.addWidget(self._plugin_desc)
        right.addWidget(self._plugin_homepage)
        right.addStretch()

        info_layout.addWidget(self._icon_label)
        info_layout.addLayout(right, 1)

        file_card = CardWidget(page)
        file_layout = QVBoxLayout(file_card)
        file_layout.setContentsMargins(18, 14, 18, 14)
        file_layout.setSpacing(8)

        self._file_path = StrongBodyLabel("", file_card)
        self._file_path.setWordWrap(True)
        self._icon_hint = BodyLabel("", file_card)
        self._icon_hint.setWordWrap(True)

        file_layout.addWidget(self._file_path)
        file_layout.addWidget(self._icon_hint)

        layout.addWidget(info_card)
        layout.addWidget(file_card)
        layout.addStretch()

        self._stack.addWidget(page)

    def _build_confirm_page(self) -> None:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(12)

        confirm_card = CardWidget(page)
        confirm_layout = QVBoxLayout(confirm_card)
        confirm_layout.setContentsMargins(18, 14, 18, 14)
        confirm_layout.setSpacing(8)

        self._confirm_title = SubtitleLabel("确认导入", confirm_card)
        self._confirm_summary = BodyLabel("", confirm_card)
        self._confirm_summary.setWordWrap(True)
        self._confirm_notice = BodyLabel(
            "导入后将把插件内容复制到 plugins_ext 目录，并尝试加载插件。",
            confirm_card,
        )
        self._confirm_notice.setWordWrap(True)

        confirm_layout.addWidget(self._confirm_title)
        confirm_layout.addWidget(self._confirm_summary)
        confirm_layout.addWidget(self._confirm_notice)

        layout.addWidget(confirm_card)
        layout.addStretch()

        self._stack.addWidget(page)

    def _bind_signals(self) -> None:
        self._cancel_btn.clicked.connect(self.close)
        self._back_btn.clicked.connect(lambda: self._set_step(self._stack.currentIndex() - 1))
        self._next_btn.clicked.connect(lambda: self._set_step(self._stack.currentIndex() + 1))
        self._import_btn.clicked.connect(self._on_import_clicked)
        self._breadcrumb.currentItemChanged.connect(self._on_breadcrumb_changed)

    def _refresh_breadcrumb(self) -> None:
        current_step = self._stack.currentIndex()
        if current_step < 0:
            return

        self._syncing_breadcrumb = True
        self._breadcrumb.blockSignals(True)
        try:
            self._breadcrumb.clear()
            for step in range(self._max_unlocked_step + 1):
                route, text = self._steps[step]
                self._breadcrumb.addItem(route, text)
            self._breadcrumb.setCurrentItem(self._steps[current_step][0])
        finally:
            self._breadcrumb.blockSignals(False)
            self._syncing_breadcrumb = False

    def _on_breadcrumb_changed(self, route_key: str) -> None:
        if self._syncing_breadcrumb:
            return
        step = self._route_to_step.get(route_key)
        if step is None or step > self._max_unlocked_step:
            return
        self._set_step(step)

    def _set_step(self, step: int) -> None:
        last_step = len(self._steps) - 1
        step = max(0, min(last_step, step))
        self._max_unlocked_step = max(self._max_unlocked_step, step)
        self._stack.setCurrentIndex(step)
        self._refresh_breadcrumb()

        self._back_btn.setVisible(step > 0)
        self._next_btn.setVisible(step < last_step)
        self._import_btn.setVisible(step == last_step)

    def _reset_state(self) -> None:
        self._current_file_path = ""
        self._package_info = {}
        self._max_unlocked_step = 0
        self._set_step(0)

    def _render_icon(self) -> None:
        icon_bytes = self._package_info.get("icon_bytes")
        icon_pixmap = QPixmap()

        if isinstance(icon_bytes, (bytes, bytearray)) and icon_bytes:
            icon_pixmap.loadFromData(bytes(icon_bytes))

        if icon_pixmap.isNull() and ICON_PATH:
            fallback = QIcon(ICON_PATH)
            if not fallback.isNull():
                icon_pixmap = fallback.pixmap(96, 96)

        if icon_pixmap.isNull():
            icon_pixmap = QPixmap(96, 96)
            icon_pixmap.fill(Qt.GlobalColor.transparent)

        self._icon_label.setPixmap(
            icon_pixmap.scaled(
                self._icon_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def open_package(self, file_path: Path, package_info: dict[str, Any]) -> None:
        self._reset_state()
        self._current_file_path = str(file_path)
        self._package_info = dict(package_info)

        plugin_name = str(package_info.get("name") or file_path.stem)
        plugin_id = str(package_info.get("id") or "")
        plugin_version = str(package_info.get("version") or "")
        plugin_desc = str(package_info.get("description") or "")
        plugin_author = str(package_info.get("author") or "")
        plugin_type = str(package_info.get("plugin_type") or "feature")
        plugin_homepage = str(package_info.get("homepage") or "")
        icon_name = str(package_info.get("icon_name") or "")

        self._plugin_name.setText(f"插件：{plugin_name}")
        self._plugin_id.setText(f"ID：{plugin_id or '-'}")
        self._plugin_version.setText(f"版本：{plugin_version or '-'}")
        self._plugin_author.setText(f"作者：{plugin_author or '-'}")
        self._plugin_type.setText(f"类型：{plugin_type or '-'}")
        self._plugin_desc.setText(f"说明：{plugin_desc or '-'}")
        self._plugin_homepage.setText(f"主页：{plugin_homepage or '-'}")
        self._file_path.setText(f"文件：{file_path}")
        self._icon_hint.setText(f"图标：{icon_name or '未声明，使用默认图标'}")

        self._confirm_summary.setText(
            f"将导入插件「{plugin_name}」（ID: {plugin_id or '-'}，版本: {plugin_version or '-'}）。"
        )

        self._render_icon()
        self.show()
        self.activateWindow()
        self.raise_()

    def closeEvent(self, event) -> None:
        super().closeEvent(event)
        if event.isAccepted():
            self._reset_state()

    def _on_import_clicked(self) -> None:
        if not self._current_file_path:
            return
        self.importRequested.emit(self._current_file_path)
        self.close()

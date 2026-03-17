"""配置迁移窗口 - 导入/导出配置、插件及其数据。"""
from __future__ import annotations

import json
import io
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Optional

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QSizePolicy,
    QStackedWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import (
    BodyLabel,
    BreadcrumbBar,
    CaptionLabel,
    CardWidget,
    FluentIcon as FIF,
    FluentWidget,
    IconWidget,
    InfoBadge,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    StrongBodyLabel,
    SubtitleLabel,
    TitleLabel,
    TreeWidget,
    ToolButton,
)

from app.constants import APP_NAME, APP_VERSION, CONFIG_DIR, ICON_PATH, PLUGINS_DIR
from app.services.i18n_service import I18nService
from app.utils.fs import write_bytes_with_uac
from app.utils.logger import logger


_CONFIG_FILE_INFO: dict[str, tuple[str, str]] = {
    "alarms.json": ("config.alarms.desc", "闹钟配置"),
    "automation.json": ("config.automation.desc", "自动化规则"),
    "focus.json": ("config.focus.desc", "专注模式配置"),
    "ntp.json": ("config.ntp.desc", "NTP 时间同步设置"),
    "recommendations.json": ("config.recommendations.desc", "推荐内容配置"),
    "settings.json": ("config.settings.desc", "应用设置"),
    "timers.json": ("config.timers.desc", "计时器配置"),
    "widget_layouts.json": ("config.widget_layouts.desc", "小组件布局"),
    "world_time.json": ("config.world_time.desc", "世界时间配置"),
}

_EXPORT_EXTENSION = "ltcconfig"
_PACKAGE_MAGIC = b"LTC_CFG_MIGRATION_V1\n"
_MANIFEST_PATH = "manifest.json"

_ROLE_KIND = int(Qt.ItemDataRole.UserRole)
_ROLE_VALUE = int(Qt.ItemDataRole.UserRole) + 1

_KIND_ROOT_CONFIG = "root_config"
_KIND_ROOT_PLUGINS = "root_plugins"
_KIND_ROOT_PLUGIN_DATA = "root_plugin_data"
_KIND_ROOT_DEPENDENCIES = "root_dependencies"

_KIND_CONFIG_FILE = "config_file"
_KIND_PLUGIN = "plugin"
_KIND_PLUGIN_DATA = "plugin_data"
_KIND_DEPENDENCY_LIB = "dependency_lib"


def _tr(i18n: I18nService, zh: str, en: str) -> str:
    return en if i18n.language == "en-US" else zh


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


def _normalize_simple_name(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    p = PurePosixPath(text)
    if len(p.parts) != 1:
        return ""
    name = p.parts[0]
    if name in {"", ".", ".."}:
        return ""
    if "/" in text or "\\" in text:
        return ""
    return name


def _sanitize_export_filename(name: str) -> str:
    text = name.strip()
    if text.lower().endswith(f".{_EXPORT_EXTENSION}"):
        text = text[: -(len(_EXPORT_EXTENSION) + 1)]
    for ch in '<>:"/\\|?*':
        text = text.replace(ch, "_")
    return text.strip(" .")


@dataclass
class _Selection:
    config_files: set[str]
    plugins: set[str]
    plugin_data: set[str]
    include_lib: bool

    def is_empty(self) -> bool:
        return (
            not self.config_files
            and not self.plugins
            and not self.plugin_data
            and not self.include_lib
        )


class _ActionCard(CardWidget):
    """用于选择导入/导出的横向卡片。"""

    clicked = Signal()

    def __init__(self, icon: FIF, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(10)

        self._icon = IconWidget(icon, self)
        self._icon.setFixedSize(28, 28)
        self._title_label = StrongBodyLabel("", self)

        header.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(self._title_label, 0, Qt.AlignmentFlag.AlignVCenter)
        header.addStretch()

        self._desc_label = BodyLabel("", self)
        self._desc_label.setWordWrap(True)

        layout.addLayout(header)
        layout.addWidget(self._desc_label)

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(130)

    def set_texts(self, title: str, description: str) -> None:
        self._title_label.setText(title)
        self._desc_label.setText(description)

    def set_selected(self, selected: bool) -> None:
        if selected:
            self.setStyleSheet(
                "CardWidget{border:1px solid rgba(0,120,215,0.85);"
                "background-color: rgba(0,120,215,0.06);}"
            )
        else:
            self.setStyleSheet("")

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class _DropAreaCard(CardWidget):
    """支持点击和拖放文件的卡片。"""

    clicked = Signal()
    fileDropped = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._set_drag_state(False)

    def _set_drag_state(self, active: bool) -> None:
        if active:
            self.setStyleSheet(
                "CardWidget{border:1px dashed rgba(0,120,215,0.9);"
                "background-color: rgba(0,120,215,0.08);}"
            )
        else:
            self.setStyleSheet("")

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def dragEnterEvent(self, event) -> None:
        urls = event.mimeData().urls()
        if any(url.isLocalFile() for url in urls):
            event.acceptProposedAction()
            self._set_drag_state(True)
            return
        event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self._set_drag_state(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:
        self._set_drag_state(False)
        for url in event.mimeData().urls():
            if not url.isLocalFile():
                continue
            self.fileDropped.emit(url.toLocalFile())
            event.acceptProposedAction()
            return
        event.ignore()


class ConfigMigrationWindow(FluentWidget):
    """配置迁移窗口。"""

    migrationCompleted = Signal()

    _ROUTE_ACTION = "migration_action"
    _ROUTE_SELECT = "migration_select"
    _ROUTE_CONFIRM = "migration_confirm"

    def __init__(self, parent=None, plugin_manager=None):
        super().__init__(parent)
        self._i18n = I18nService.instance()
        self._plugin_manager = plugin_manager

        self._is_export_mode = True
        self._max_unlocked_step = 0
        self._syncing_breadcrumb = False

        self._export_directory = self._get_desktop_path()
        self._import_file_path: Optional[Path] = None
        self._import_manifest: dict[str, Any] = {}

        self._steps: list[tuple[str, str, str]] = [
            (self._ROUTE_ACTION, "migration.breadcrumb.action", "选择操作"),
            (self._ROUTE_SELECT, "migration.breadcrumb.select", "选择内容"),
            (self._ROUTE_CONFIRM, "migration.breadcrumb.confirm", "确认"),
        ]
        self._route_to_step = {route: idx for idx, (route, _, _) in enumerate(self._steps)}

        self._stack = QStackedWidget(self)
        self._breadcrumb = BreadcrumbBar(self)
        self._breadcrumb.setSpacing(10)

        self._back_button = PushButton(FIF.LEFT_ARROW, "", self)
        self._next_button = PrimaryPushButton(FIF.RIGHT_ARROW, "", self)
        self._cancel_button = PushButton(FIF.CANCEL, "", self)

        self._build_ui()
        self._bind_signals()
        self._set_step(0)
        self._retranslate()

    def closeEvent(self, event) -> None:
        super().closeEvent(event)
        if event.isAccepted():
            self._reset_wizard_state()

    def _reset_wizard_state(self) -> None:
        self._is_export_mode = True
        self._max_unlocked_step = 0

        self._import_file_path = None
        self._import_manifest = {}
        self._import_file_label.clear()
        self._import_file_label.setVisible(False)
        self._import_file_meta_label.clear()
        self._import_file_meta_label.setVisible(False)

        self._export_name_input.clear()
        self._set_step(0)
        self._update_action_card_state()

    def _build_ui(self) -> None:
        self.resize(840, 620)
        self.setMinimumSize(760, 560)
        if ICON_PATH:
            self.setWindowIcon(QIcon(ICON_PATH))

        root = QVBoxLayout(self)
        root.setContentsMargins(26, self.titleBar.height() + 16, 26, 24)
        root.setSpacing(12)

        self._header_title = TitleLabel("", self)
        self._header_subtitle = BodyLabel("", self)
        self._header_subtitle.setWordWrap(True)

        root.addWidget(self._header_title)
        root.addWidget(self._header_subtitle)
        root.addSpacing(4)
        root.addWidget(self._breadcrumb)

        self._build_action_page()
        self._build_select_page()
        self._build_confirm_page()

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

    def _build_action_page(self) -> None:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(16)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._action_title = SubtitleLabel("", page)
        self._action_desc = BodyLabel("", page)
        self._action_desc.setWordWrap(True)

        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(16)

        self._export_card = _ActionCard(FIF.UP, page)
        self._import_card = _ActionCard(FIF.DOWN, page)
        cards_layout.addWidget(self._export_card)
        cards_layout.addWidget(self._import_card)

        layout.addWidget(self._action_title)
        layout.addWidget(self._action_desc)
        layout.addLayout(cards_layout)
        layout.addStretch()

        self._stack.addWidget(page)

    def _build_select_page(self) -> None:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(12)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._select_export_widget = QWidget(page)
        export_layout = QVBoxLayout(self._select_export_widget)
        export_layout.setContentsMargins(0, 0, 0, 0)
        export_layout.setSpacing(8)

        self._select_export_title = SubtitleLabel("", self._select_export_widget)
        self._select_export_desc = BodyLabel("", self._select_export_widget)
        self._select_export_desc.setWordWrap(True)

        select_btn_layout = QHBoxLayout()
        select_btn_layout.setSpacing(8)
        self._select_all_btn = PushButton(FIF.CHECKBOX, "", self._select_export_widget)
        self._deselect_all_btn = PushButton(FIF.CANCEL, "", self._select_export_widget)
        select_btn_layout.addWidget(self._select_all_btn)
        select_btn_layout.addWidget(self._deselect_all_btn)
        select_btn_layout.addStretch()

        self._export_tree = TreeWidget(self._select_export_widget)

        export_layout.addWidget(self._select_export_title)
        export_layout.addWidget(self._select_export_desc)
        export_layout.addLayout(select_btn_layout)
        export_layout.addWidget(self._export_tree)

        self._select_import_widget = QWidget(page)
        import_layout = QVBoxLayout(self._select_import_widget)
        import_layout.setContentsMargins(0, 0, 0, 0)
        import_layout.setSpacing(10)

        self._select_import_title = SubtitleLabel("", self._select_import_widget)
        self._select_import_desc = BodyLabel("", self._select_import_widget)
        self._select_import_desc.setWordWrap(True)

        self._drop_area = _DropAreaCard(self._select_import_widget)
        self._drop_area.setFixedHeight(190)

        drop_layout = QVBoxLayout(self._drop_area)
        drop_layout.setContentsMargins(24, 24, 24, 24)
        drop_layout.setSpacing(8)
        drop_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._drop_icon = IconWidget(FIF.FOLDER, self._drop_area)
        self._drop_icon.setFixedSize(34, 34)
        self._drop_icon.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self._drop_text = StrongBodyLabel("", self._drop_area)
        self._drop_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._drop_text.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self._drop_hint = CaptionLabel("", self._drop_area)
        self._drop_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._drop_hint.setWordWrap(True)
        self._drop_hint.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        drop_layout.addWidget(self._drop_icon, 0, Qt.AlignmentFlag.AlignCenter)
        drop_layout.addWidget(self._drop_text)
        drop_layout.addWidget(self._drop_hint)

        browse_row = QHBoxLayout()
        browse_row.addStretch()
        self._browse_import_btn = PushButton(FIF.FOLDER, "", self._select_import_widget)
        browse_row.addWidget(self._browse_import_btn)
        browse_row.addStretch()

        self._import_file_label = BodyLabel("", self._select_import_widget)
        self._import_file_label.setWordWrap(True)
        self._import_file_label.setVisible(False)

        self._import_file_meta_label = CaptionLabel("", self._select_import_widget)
        self._import_file_meta_label.setWordWrap(True)
        self._import_file_meta_label.setVisible(False)

        import_layout.addWidget(self._select_import_title)
        import_layout.addWidget(self._select_import_desc)
        import_layout.addWidget(self._drop_area)
        import_layout.addLayout(browse_row)
        import_layout.addWidget(self._import_file_label)
        import_layout.addWidget(self._import_file_meta_label)
        import_layout.addStretch()

        layout.addWidget(self._select_export_widget)
        layout.addWidget(self._select_import_widget)

        self._stack.addWidget(page)

    def _build_confirm_page(self) -> None:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(12)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._confirm_export_widget = QWidget(page)
        export_layout = QVBoxLayout(self._confirm_export_widget)
        export_layout.setContentsMargins(0, 0, 0, 0)
        export_layout.setSpacing(12)

        self._confirm_export_title = SubtitleLabel("", self._confirm_export_widget)
        self._confirm_export_desc = BodyLabel("", self._confirm_export_widget)
        self._confirm_export_desc.setWordWrap(True)

        name_row = QHBoxLayout()
        name_row.setSpacing(10)
        self._export_name_label = BodyLabel("", self._confirm_export_widget)
        self._export_name_input = LineEdit(self._confirm_export_widget)
        self._export_name_input.setClearButtonEnabled(True)
        name_row.addWidget(self._export_name_label)
        name_row.addWidget(self._export_name_input, 1)

        path_row = QHBoxLayout()
        path_row.setSpacing(10)
        self._export_path_label = BodyLabel("", self._confirm_export_widget)
        self._export_path_display = BodyLabel("", self._confirm_export_widget)
        self._export_path_display.setWordWrap(True)
        self._export_path_btn = ToolButton(FIF.FOLDER, self._confirm_export_widget)
        path_row.addWidget(self._export_path_label)
        path_row.addWidget(self._export_path_display, 1)
        path_row.addWidget(self._export_path_btn)

        export_layout.addWidget(self._confirm_export_title)
        export_layout.addWidget(self._confirm_export_desc)
        export_layout.addLayout(name_row)
        export_layout.addLayout(path_row)

        self._confirm_import_widget = QWidget(page)
        import_layout = QVBoxLayout(self._confirm_import_widget)
        import_layout.setContentsMargins(0, 0, 0, 0)
        import_layout.setSpacing(12)

        self._confirm_import_title = SubtitleLabel("", self._confirm_import_widget)
        self._confirm_import_desc = BodyLabel("", self._confirm_import_widget)
        self._confirm_import_desc.setWordWrap(True)

        self._import_tree = TreeWidget(self._confirm_import_widget)

        import_layout.addWidget(self._confirm_import_title)
        import_layout.addWidget(self._confirm_import_desc)
        import_layout.addWidget(self._import_tree)

        layout.addWidget(self._confirm_export_widget)
        layout.addWidget(self._confirm_import_widget)
        layout.addStretch()

        self._stack.addWidget(page)

    def _bind_signals(self) -> None:
        self._back_button.clicked.connect(self._go_previous)
        self._next_button.clicked.connect(self._go_next)
        self._cancel_button.clicked.connect(self.close)

        self._export_card.clicked.connect(lambda: self._select_action(True))
        self._import_card.clicked.connect(lambda: self._select_action(False))

        self._select_all_btn.clicked.connect(self._select_all_items)
        self._deselect_all_btn.clicked.connect(self._deselect_all_items)

        self._browse_import_btn.clicked.connect(self._browse_import_file)
        self._drop_area.clicked.connect(self._browse_import_file)
        self._drop_area.fileDropped.connect(self._on_file_dropped)

        self._export_path_btn.clicked.connect(self._browse_export_path)

        self._breadcrumb.currentItemChanged.connect(self._on_breadcrumb_changed)
        self._i18n.languageChanged.connect(lambda _: self._retranslate())

    def _retranslate(self) -> None:
        self.setWindowTitle(f"{APP_NAME} - {self._i18n.t('migration.title', default='配置迁移')}")

        self._header_title.setText(self._i18n.t("migration.title", default="配置迁移"))
        self._header_subtitle.setText(
            self._i18n.t(
                "migration.subtitle",
                default="导出或导入应用配置、插件及其数据。",
            )
        )

        self._action_title.setText(self._i18n.t("migration.action.title", default="选择操作"))
        self._action_desc.setText(
            self._i18n.t(
                "migration.action.desc",
                default="选择要执行的操作：导出当前配置到文件，或从文件导入配置。",
            )
        )

        self._export_card.set_texts(
            self._i18n.t("migration.action.export", default="导出配置"),
            self._i18n.t(
                "migration.action.export.desc",
                default="将当前配置、插件和数据导出为可移植的配置文件。",
            ),
        )
        self._import_card.set_texts(
            self._i18n.t("migration.action.import", default="导入配置"),
            self._i18n.t(
                "migration.action.import.desc",
                default="从配置文件恢复配置、插件和数据。",
            ),
        )

        self._select_export_title.setText(
            self._i18n.t("migration.select.export.title", default="选择导出内容")
        )
        self._select_export_desc.setText(
            self._i18n.t(
                "migration.select.export.desc",
                default="勾选要导出的内容。依赖文件体积较大，通常不建议导出。",
            )
        )
        self._select_all_btn.setText(self._i18n.t("migration.select.all", default="全选"))
        self._deselect_all_btn.setText(self._i18n.t("migration.select.none", default="取消全选"))

        self._select_import_title.setText(
            self._i18n.t("migration.select.import.title", default="选择配置文件")
        )
        self._select_import_desc.setText(
            self._i18n.t(
                "migration.select.import.desc",
                default="拖入配置文件，或点击浏览选择文件。",
            )
        )
        self._drop_text.setText(self._i18n.t("migration.drop.text", default="拖放配置文件到此处"))
        self._drop_hint.setText(
            self._i18n.t("migration.drop.hint", default="支持 .ltcconfig 格式")
        )
        self._browse_import_btn.setText(
            self._i18n.t("migration.browse.import", default="选择配置文件")
        )

        self._confirm_export_title.setText(
            self._i18n.t("migration.confirm.export.title", default="确认导出")
        )
        self._confirm_export_desc.setText(
            self._i18n.t(
                "migration.confirm.export.desc",
                default="设置导出文件名和保存位置。",
            )
        )
        self._confirm_import_title.setText(
            self._i18n.t("migration.confirm.import.title", default="选择导入内容")
        )
        self._confirm_import_desc.setText(
            self._i18n.t(
                "migration.confirm.import.desc",
                default="勾选要从配置文件导入的项目。",
            )
        )

        self._export_name_label.setText(self._i18n.t("migration.export.name", default="文件名："))
        self._export_name_input.setPlaceholderText(
            self._i18n.t("migration.export.name.placeholder", default="例如：my_clock_backup")
        )
        self._export_path_label.setText(self._i18n.t("migration.export.path", default="保存位置："))
        self._export_path_display.setText(str(self._export_directory))

        self._back_button.setText(self._i18n.t("migration.action.back", default="上一步"))
        self._cancel_button.setText(self._i18n.t("common.cancel", default="取消"))

        self._update_action_card_state()
        self._refresh_breadcrumb()
        self._refresh_button_state()

        self._refresh_export_tree()
        if self._import_manifest:
            self._refresh_import_tree()

    def _set_step(self, index: int) -> None:
        last_step = len(self._steps) - 1
        index = max(0, min(last_step, index))
        self._max_unlocked_step = max(self._max_unlocked_step, index)

        self._stack.setCurrentIndex(index)
        self._refresh_breadcrumb()

        self._back_button.setVisible(index > 0)

        if index == 1:
            self._select_export_widget.setVisible(self._is_export_mode)
            self._select_import_widget.setVisible(not self._is_export_mode)
            if self._is_export_mode:
                self._refresh_export_tree()
        elif index == 2:
            self._confirm_export_widget.setVisible(self._is_export_mode)
            self._confirm_import_widget.setVisible(not self._is_export_mode)
            if self._is_export_mode:
                self._export_path_display.setText(str(self._export_directory))
                if not self._export_name_input.text().strip():
                    self._export_name_input.setText(self._build_default_export_name())
            else:
                self._refresh_import_tree()

        self._refresh_button_state()

    def _refresh_button_state(self) -> None:
        current_step = self._stack.currentIndex()
        last_step = len(self._steps) - 1

        if current_step == last_step:
            if self._is_export_mode:
                self._next_button.setText(self._i18n.t("migration.action.export", default="导出"))
            else:
                self._next_button.setText(self._i18n.t("migration.action.import", default="导入"))
        else:
            self._next_button.setText(self._i18n.t("migration.action.next", default="下一步"))

        if current_step == 1 and (not self._is_export_mode) and self._import_file_path is None:
            self._next_button.setEnabled(False)
        else:
            self._next_button.setEnabled(True)

    def _refresh_breadcrumb(self) -> None:
        current_step = self._stack.currentIndex()
        if current_step < 0:
            return

        self._syncing_breadcrumb = True
        self._breadcrumb.blockSignals(True)
        try:
            self._breadcrumb.clear()
            for step in range(self._max_unlocked_step + 1):
                route_key, text_key, default_text = self._steps[step]
                self._breadcrumb.addItem(route_key, self._i18n.t(text_key, default=default_text))
            self._breadcrumb.setCurrentItem(self._steps[current_step][0])
        finally:
            self._breadcrumb.blockSignals(False)
            self._syncing_breadcrumb = False

    def _update_action_card_state(self) -> None:
        self._export_card.set_selected(self._is_export_mode)
        self._import_card.set_selected(not self._is_export_mode)

    @Slot(str)
    def _on_breadcrumb_changed(self, route_key: str) -> None:
        if self._syncing_breadcrumb:
            return
        step = self._route_to_step.get(route_key)
        if step is None or step > self._max_unlocked_step:
            return
        self._set_step(step)

    def _select_action(self, is_export: bool) -> None:
        self._is_export_mode = is_export
        self._update_action_card_state()
        self._set_step(1)

    def open_import_file(self, file_path: Path, *, jump_to_selection: bool = True) -> bool:
        """供外部调用：打开指定配置包并切换到导入流程。"""
        self._reset_wizard_state()
        self._is_export_mode = False
        self._update_action_card_state()
        self._set_step(1)

        self._load_import_file(Path(file_path))
        if self._import_file_path is None:
            return False

        self._max_unlocked_step = max(self._max_unlocked_step, 2)
        if jump_to_selection:
            self._set_step(2)
        else:
            self._refresh_button_state()
        return True

    @Slot()
    def _go_previous(self) -> None:
        self._set_step(self._stack.currentIndex() - 1)

    @Slot()
    def _go_next(self) -> None:
        current_step = self._stack.currentIndex()
        last_step = len(self._steps) - 1

        if current_step == 1 and (not self._is_export_mode) and self._import_file_path is None:
            self._show_error(
                _tr(
                    self._i18n,
                    "请先选择要导入的配置文件。",
                    "Please select a configuration file first.",
                )
            )
            return

        if current_step == last_step:
            ok = self._do_export() if self._is_export_mode else self._do_import()
            if ok:
                self.close()
            return

        self._set_step(current_step + 1)

    def _setup_tree_headers(self, tree: TreeWidget, first_header: str) -> None:
        tree.clear()
        tree.setColumnCount(2)
        tree.setHeaderLabels(
            [
                first_header,
                self._i18n.t("migration.tree.column.note", default="用途 / 说明"),
            ]
        )
        header = tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        tree.setColumnWidth(1, 320)
        tree.setRootIsDecorated(True)

    def _create_root_item(
        self,
        title: str,
        note: str,
        *,
        kind: str,
        checked: Qt.CheckState,
    ) -> QTreeWidgetItem:
        item = QTreeWidgetItem([title, note])
        item.setData(0, _ROLE_KIND, kind)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsAutoTristate)
        item.setCheckState(0, checked)
        return item

    def _create_child_item(
        self,
        title: str,
        note: str,
        *,
        kind: str,
        value: str,
        checked: Qt.CheckState,
    ) -> QTreeWidgetItem:
        item = QTreeWidgetItem([title, note])
        item.setData(0, _ROLE_KIND, kind)
        item.setData(0, _ROLE_VALUE, value)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(0, checked)
        return item

    def _create_not_recommended_widget(self, parent: QWidget, note_text: str) -> QWidget:
        host = QWidget(parent)
        layout = QHBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        badge = InfoBadge.custom(
            self._i18n.t("migration.badge.not_recommended", default="不推荐"),
            "#ad4e00",
            "#fff7e6",
        )
        note_label = CaptionLabel(note_text, host)
        note_label.setWordWrap(True)
        note_label.setMinimumWidth(220)
        note_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        layout.addWidget(badge, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(note_label, 1, Qt.AlignmentFlag.AlignVCenter)
        return host

    def _refresh_export_tree(self) -> None:
        self._setup_tree_headers(
            self._export_tree,
            self._i18n.t("migration.tree.header", default="选择要导出的内容"),
        )

        config_root = self._create_root_item(
            self._i18n.t("migration.tree.config", default="配置文件"),
            self._i18n.t("migration.tree.note.config", default="config 目录（不含 i18n.json）"),
            kind=_KIND_ROOT_CONFIG,
            checked=Qt.CheckState.Checked,
        )
        self._export_tree.addTopLevelItem(config_root)

        config_files = self._collect_config_files()
        for file_name in config_files:
            purpose = self._config_purpose(file_name)
            child = self._create_child_item(
                file_name,
                purpose,
                kind=_KIND_CONFIG_FILE,
                value=file_name,
                checked=Qt.CheckState.Checked,
            )
            child.setToolTip(1, purpose)
            config_root.addChild(child)
        config_root.setExpanded(True)
        if config_root.childCount() == 0:
            config_root.setCheckState(0, Qt.CheckState.Unchecked)
            config_root.setDisabled(True)
            config_root.setText(1, self._i18n.t("migration.tree.empty", default="未检测到可导出内容"))

        plugin_root = self._create_root_item(
            self._i18n.t("migration.tree.plugins", default="插件"),
            self._i18n.t("migration.tree.note.plugins", default="显示为插件名称"),
            kind=_KIND_ROOT_PLUGINS,
            checked=Qt.CheckState.Checked,
        )
        self._export_tree.addTopLevelItem(plugin_root)

        plugin_entries = self._discover_plugins()
        for plugin_id, plugin_name in plugin_entries:
            note = plugin_id if plugin_name != plugin_id else ""
            child = self._create_child_item(
                plugin_name,
                note,
                kind=_KIND_PLUGIN,
                value=plugin_id,
                checked=Qt.CheckState.Checked,
            )
            plugin_root.addChild(child)
        plugin_root.setExpanded(True)
        if plugin_root.childCount() == 0:
            plugin_root.setCheckState(0, Qt.CheckState.Unchecked)
            plugin_root.setDisabled(True)
            plugin_root.setText(1, self._i18n.t("migration.tree.empty", default="未检测到可导出内容"))

        plugin_data_root = self._create_root_item(
            self._i18n.t("migration.tree.plugin_data", default="插件数据"),
            self._i18n.t("migration.tree.note.plugin_data", default="plugins_ext/._data/<plugin_id>"),
            kind=_KIND_ROOT_PLUGIN_DATA,
            checked=Qt.CheckState.Checked,
        )
        self._export_tree.addTopLevelItem(plugin_data_root)

        plugin_name_map = dict(plugin_entries)
        for data_name in self._collect_plugin_data_entries():
            data_title = plugin_name_map.get(data_name, data_name)
            note = data_name if data_title != data_name else ""
            child = self._create_child_item(
                data_title,
                note,
                kind=_KIND_PLUGIN_DATA,
                value=data_name,
                checked=Qt.CheckState.Checked,
            )
            plugin_data_root.addChild(child)
        plugin_data_root.setExpanded(True)
        if plugin_data_root.childCount() == 0:
            plugin_data_root.setCheckState(0, Qt.CheckState.Unchecked)
            plugin_data_root.setDisabled(True)
            plugin_data_root.setText(1, self._i18n.t("migration.tree.empty", default="未检测到可导出内容"))

        deps_note = self._i18n.t(
            "migration.tree.note.dependencies",
            default="第三方库，通常不建议迁移",
        )
        deps_root = self._create_root_item(
            self._i18n.t("migration.tree.dependencies", default="依赖文件"),
            "",
            kind=_KIND_ROOT_DEPENDENCIES,
            checked=Qt.CheckState.Unchecked,
        )
        self._export_tree.addTopLevelItem(deps_root)

        if self._has_lib_files():
            lib_item = self._create_child_item(
                self._i18n.t("migration.tree.lib", default="第三方库 (_lib)"),
                "",
                kind=_KIND_DEPENDENCY_LIB,
                value="_lib",
                checked=Qt.CheckState.Unchecked,
            )
            deps_root.addChild(lib_item)
            deps_root.setExpanded(True)
            self._export_tree.setItemWidget(
                deps_root,
                1,
                self._create_not_recommended_widget(self._export_tree, deps_note),
            )
        else:
            deps_root.setDisabled(True)
            deps_root.setText(1, self._i18n.t("migration.tree.empty", default="未检测到可导出内容"))

    def _refresh_import_tree(self) -> None:
        self._setup_tree_headers(
            self._import_tree,
            self._i18n.t("migration.tree.header_import", default="选择要导入的内容"),
        )

        if not self._import_manifest:
            return

        content = self._import_manifest.get("content", {})

        config_entries = content.get("config_files", [])
        if config_entries:
            config_root = self._create_root_item(
                self._i18n.t("migration.tree.config", default="配置文件"),
                "",
                kind=_KIND_ROOT_CONFIG,
                checked=Qt.CheckState.Checked,
            )
            self._import_tree.addTopLevelItem(config_root)
            for entry in config_entries:
                name = _normalize_simple_name(entry.get("name")) if isinstance(entry, dict) else ""
                if not name:
                    continue
                purpose = (
                    str(entry.get("purpose", "")).strip()
                    if isinstance(entry, dict)
                    else self._config_purpose(name)
                )
                child = self._create_child_item(
                    name,
                    purpose,
                    kind=_KIND_CONFIG_FILE,
                    value=name,
                    checked=Qt.CheckState.Checked,
                )
                child.setToolTip(1, purpose)
                config_root.addChild(child)
            config_root.setExpanded(True)

        plugin_entries = content.get("plugins", [])
        if plugin_entries:
            plugin_root = self._create_root_item(
                self._i18n.t("migration.tree.plugins", default="插件"),
                "",
                kind=_KIND_ROOT_PLUGINS,
                checked=Qt.CheckState.Checked,
            )
            self._import_tree.addTopLevelItem(plugin_root)
            for entry in plugin_entries:
                if not isinstance(entry, dict):
                    continue
                plugin_id = _normalize_simple_name(entry.get("id"))
                if not plugin_id:
                    continue
                plugin_name = str(entry.get("name") or plugin_id).strip() or plugin_id
                note = plugin_id if plugin_name != plugin_id else ""
                child = self._create_child_item(
                    plugin_name,
                    note,
                    kind=_KIND_PLUGIN,
                    value=plugin_id,
                    checked=Qt.CheckState.Checked,
                )
                plugin_root.addChild(child)
            plugin_root.setExpanded(True)

        plugin_data_entries = content.get("plugin_data", [])
        if plugin_data_entries:
            plugin_name_map = dict(self._discover_plugins())
            data_root = self._create_root_item(
                self._i18n.t("migration.tree.plugin_data", default="插件数据"),
                "",
                kind=_KIND_ROOT_PLUGIN_DATA,
                checked=Qt.CheckState.Checked,
            )
            self._import_tree.addTopLevelItem(data_root)
            for entry in plugin_data_entries:
                if isinstance(entry, dict):
                    name = _normalize_simple_name(entry.get("name"))
                    display_name = str(
                        entry.get("plugin_name") or plugin_name_map.get(name, name)
                    ).strip() if name else ""
                else:
                    name = _normalize_simple_name(entry)
                    display_name = plugin_name_map.get(name, name) if name else ""
                if not name:
                    continue
                note = name if display_name and display_name != name else ""
                child = self._create_child_item(
                    display_name or name,
                    note,
                    kind=_KIND_PLUGIN_DATA,
                    value=name,
                    checked=Qt.CheckState.Checked,
                )
                data_root.addChild(child)
            data_root.setExpanded(True)

        include_lib = bool(content.get("dependencies", {}).get("include_lib", False))
        if include_lib:
            deps_note = self._i18n.t(
                "migration.tree.note.dependencies",
                default="第三方库，通常不建议迁移",
            )
            deps_root = self._create_root_item(
                self._i18n.t("migration.tree.dependencies", default="依赖文件"),
                "",
                kind=_KIND_ROOT_DEPENDENCIES,
                checked=Qt.CheckState.Unchecked,
            )
            self._import_tree.addTopLevelItem(deps_root)

            lib_item = self._create_child_item(
                self._i18n.t("migration.tree.lib", default="第三方库 (_lib)"),
                "",
                kind=_KIND_DEPENDENCY_LIB,
                value="_lib",
                checked=Qt.CheckState.Unchecked,
            )
            deps_root.addChild(lib_item)
            deps_root.setExpanded(True)
            self._import_tree.setItemWidget(
                deps_root,
                1,
                self._create_not_recommended_widget(self._import_tree, deps_note),
            )

    def _select_all_items(self) -> None:
        self._set_tree_all_state(self._export_tree, Qt.CheckState.Checked)

    def _deselect_all_items(self) -> None:
        self._set_tree_all_state(self._export_tree, Qt.CheckState.Unchecked)

    def _set_tree_all_state(self, tree: TreeWidget, state: Qt.CheckState) -> None:
        def apply_state(item: QTreeWidgetItem) -> None:
            if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                item.setCheckState(0, state)
            for idx in range(item.childCount()):
                apply_state(item.child(idx))

        for i in range(tree.topLevelItemCount()):
            apply_state(tree.topLevelItem(i))

    def _collect_selection(self, tree: TreeWidget) -> _Selection:
        selection = _Selection(set(), set(), set(), False)

        for i in range(tree.topLevelItemCount()):
            root = tree.topLevelItem(i)
            root_kind = root.data(0, _ROLE_KIND)

            if root_kind == _KIND_ROOT_DEPENDENCIES and root.childCount() == 0:
                if root.checkState(0) == Qt.CheckState.Checked:
                    selection.include_lib = True

            for j in range(root.childCount()):
                child = root.child(j)
                if child.checkState(0) != Qt.CheckState.Checked:
                    continue

                kind = child.data(0, _ROLE_KIND)
                value = _normalize_simple_name(child.data(0, _ROLE_VALUE))
                if not value:
                    continue

                if kind == _KIND_CONFIG_FILE:
                    selection.config_files.add(value)
                elif kind == _KIND_PLUGIN:
                    selection.plugins.add(value)
                elif kind == _KIND_PLUGIN_DATA:
                    selection.plugin_data.add(value)
                elif kind == _KIND_DEPENDENCY_LIB:
                    selection.include_lib = True

        return selection

    def _browse_import_file(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            self._i18n.t("migration.browse.import", default="选择配置文件"),
            str(Path.home()),
            f"{self._i18n.t('migration.file.filter', default='配置文件')} (*.{_EXPORT_EXTENSION})",
        )
        if file_path:
            self._load_import_file(Path(file_path))

    @Slot(str)
    def _on_file_dropped(self, local_file_path: str) -> None:
        file_path = Path(local_file_path)
        if file_path.suffix.lower() != f".{_EXPORT_EXTENSION}":
            self._show_error(
                _tr(
                    self._i18n,
                    "请选择有效的配置文件（.ltcconfig）。",
                    "Please select a valid config file (.ltcconfig).",
                )
            )
            return
        self._load_import_file(file_path)

    def _load_import_file(self, file_path: Path) -> None:
        if not file_path.exists() or not file_path.is_file():
            self._show_error(
                _tr(self._i18n, "文件不存在或不可读取。", "File does not exist or is unreadable.")
            )
            return

        if file_path.suffix.lower() != f".{_EXPORT_EXTENSION}":
            self._show_error(
                _tr(
                    self._i18n,
                    "请选择有效的配置文件（.ltcconfig）。",
                    "Please select a valid config file (.ltcconfig).",
                )
            )
            return

        try:
            with zipfile.ZipFile(file_path, "r") as zf:
                self._import_manifest = self._load_manifest_from_archive(zf)
        except zipfile.BadZipFile:
            self._show_error(
                _tr(self._i18n, "配置文件格式无效。", "Invalid configuration package format.")
            )
            return
        except Exception as exc:
            logger.exception("读取迁移配置文件失败: {}", file_path)
            self._show_error(
                _tr(
                    self._i18n,
                    f"读取配置文件失败：{exc}",
                    f"Failed to load config package: {exc}",
                )
            )
            return

        self._import_file_path = file_path
        self._import_file_label.setText(
            _tr(
                self._i18n,
                f"已选择：{file_path.name}",
                f"Selected: {file_path.name}",
            )
        )

        content = self._import_manifest.get("content", {})
        cfg_count = len(content.get("config_files", []))
        plugin_count = len(content.get("plugins", []))
        data_count = len(content.get("plugin_data", []))
        has_lib = bool(content.get("dependencies", {}).get("include_lib", False))
        package_type = (
            _tr(self._i18n, "自定义格式", "Custom Format")
            if self._is_custom_package(file_path)
            else "ZIP"
        )
        self._import_file_meta_label.setText(
            _tr(
                self._i18n,
                f"{package_type} · 配置 {cfg_count} 项 · 插件 {plugin_count} 项 · 数据 {data_count} 项"
                + (" · 含依赖库" if has_lib else ""),
                f"{package_type} · Config {cfg_count} · Plugins {plugin_count} · Data {data_count}"
                + (" · Includes dependencies" if has_lib else ""),
            )
        )
        self._import_file_label.setVisible(True)
        self._import_file_meta_label.setVisible(True)

        if self._stack.currentIndex() == 2 and not self._is_export_mode:
            self._refresh_import_tree()

        self._refresh_button_state()

    def _load_manifest_from_archive(self, zf: zipfile.ZipFile) -> dict[str, Any]:
        names = [name for name in zf.namelist() if not name.endswith("/")]
        if _MANIFEST_PATH not in zf.namelist():
            raise ValueError("配置文件缺少 manifest.json")
        raw = json.loads(zf.read(_MANIFEST_PATH).decode("utf-8"))
        return self._normalize_manifest(raw, names)

    def _normalize_manifest(self, raw: dict[str, Any], archive_names: list[str]) -> dict[str, Any]:
        schema = str(raw.get("schema") or "ltc-config-migration.v1")
        created_at = str(raw.get("created_at") or raw.get("export_time") or "")
        app_version = str(raw.get("app_version") or "")

        content = raw.get("content")
        if not isinstance(content, dict):
            raise ValueError("配置文件清单缺少 content 字段")

        config_files: list[dict[str, str]] = []
        seen_config: set[str] = set()
        for item in content.get("config_files", []):
            if isinstance(item, str):
                name = _normalize_simple_name(item)
                purpose = self._config_purpose(name) if name else ""
            elif isinstance(item, dict):
                name = _normalize_simple_name(item.get("name"))
                purpose = str(item.get("purpose") or self._config_purpose(name)).strip() if name else ""
            else:
                name = ""
                purpose = ""
            if not name or name in seen_config:
                continue
            seen_config.add(name)
            config_files.append({"name": name, "purpose": purpose})

        plugin_map = dict(self._discover_plugins())
        plugins: list[dict[str, str]] = []
        seen_plugins: set[str] = set()
        for item in content.get("plugins", []):
            if isinstance(item, str):
                pid = _normalize_simple_name(item)
                pname = plugin_map.get(pid, pid) if pid else ""
            elif isinstance(item, dict):
                pid = _normalize_simple_name(item.get("id"))
                pname = str(item.get("name") or plugin_map.get(pid, pid)).strip() if pid else ""
            else:
                pid = ""
                pname = ""
            if not pid or pid in seen_plugins:
                continue
            seen_plugins.add(pid)
            plugins.append({"id": pid, "name": pname or pid})

        plugin_data: list[dict[str, str]] = []
        seen_data: set[str] = set()
        for item in content.get("plugin_data", []):
            if isinstance(item, str):
                name = _normalize_simple_name(item)
                plugin_name = plugin_map.get(name, name) if name else ""
            elif isinstance(item, dict):
                name = _normalize_simple_name(item.get("name"))
                plugin_name = str(item.get("plugin_name") or plugin_map.get(name, name)).strip() if name else ""
            else:
                name = ""
                plugin_name = ""
            if not name or name in seen_data:
                continue
            seen_data.add(name)
            plugin_data.append({"name": name, "plugin_name": plugin_name or name})

        dependencies_value = content.get("dependencies", {})
        include_lib = False
        if isinstance(dependencies_value, dict):
            include_lib = bool(dependencies_value.get("include_lib", False))
        elif isinstance(dependencies_value, bool):
            include_lib = dependencies_value

        return {
            "schema": schema,
            "created_at": created_at,
            "app_version": app_version,
            "content": {
                "config_files": config_files,
                "plugins": plugins,
                "plugin_data": plugin_data,
                "dependencies": {"include_lib": include_lib},
            },
        }

    def _convert_legacy_manifest(self, raw: dict[str, Any], archive_names: list[str]) -> dict[str, Any]:
        raise ValueError("不再支持旧版迁移包，请在新版程序中重新导出 .ltcconfig 文件后导入。")

    def _build_manifest_from_archive(self, archive_names: list[str]) -> dict[str, Any]:
        configs: set[str] = set()
        plugins: set[str] = set()
        plugin_data: set[str] = set()
        has_lib = False

        for name in archive_names:
            parts = PurePosixPath(name).parts
            if not parts:
                continue
            if any(part in {"", ".", ".."} for part in parts):
                continue

            root = parts[0]
            if root == "config" and len(parts) == 2:
                configs.add(parts[1])
            elif root == "plugins" and len(parts) >= 3:
                plugins.add(parts[1])
            elif root == "plugin_data" and len(parts) >= 2:
                plugin_data.add(parts[1])
            elif root == "_lib" and len(parts) >= 2:
                has_lib = True

        plugin_map = dict(self._discover_plugins())

        return {
            "schema": "archive-scan.v0",
            "created_at": "",
            "app_version": "",
            "content": {
                "config_files": [
                    {"name": name, "purpose": self._config_purpose(name)}
                    for name in sorted(configs)
                ],
                "plugins": [
                    {"id": pid, "name": plugin_map.get(pid, pid)}
                    for pid in sorted(plugins)
                ],
                "plugin_data": [
                    {"name": name, "plugin_name": plugin_map.get(name, name)}
                    for name in sorted(plugin_data)
                ],
                "dependencies": {"include_lib": has_lib},
            },
        }

    def _browse_export_path(self) -> None:
        dir_path = QFileDialog.getExistingDirectory(
            self,
            self._i18n.t("migration.browse.export", default="选择保存位置"),
            str(self._export_directory),
        )
        if dir_path:
            self._export_directory = Path(dir_path)
            self._export_path_display.setText(str(self._export_directory))

    def _build_default_export_name(self) -> str:
        return f"ltc_config_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    def _build_export_manifest(self, selection: _Selection) -> dict[str, Any]:
        plugin_name_map = dict(self._discover_plugins())
        return {
            "schema": "ltc-config-migration.v1",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "app_name": APP_NAME,
            "app_version": APP_VERSION,
            "content": {
                "config_files": [
                    {"name": name, "purpose": self._config_purpose(name)}
                    for name in sorted(selection.config_files)
                ],
                "plugins": [
                    {"id": pid, "name": plugin_name_map.get(pid, pid)}
                    for pid in sorted(selection.plugins)
                ],
                "plugin_data": [
                    {"name": name, "plugin_name": plugin_name_map.get(name, name)}
                    for name in sorted(selection.plugin_data)
                ],
                "dependencies": {"include_lib": bool(selection.include_lib)},
            },
        }

    def _do_export(self) -> bool:
        selection = self._collect_selection(self._export_tree)
        if selection.is_empty():
            self._show_error(
                _tr(
                    self._i18n,
                    "请至少选择一项导出内容。",
                    "Please select at least one item to export.",
                )
            )
            return False

        file_name = _sanitize_export_filename(self._export_name_input.text().strip())
        if not file_name:
            file_name = self._build_default_export_name()

        export_path = self._export_directory / f"{file_name}.{_EXPORT_EXTENSION}"

        try:
            buf = io.BytesIO()
            buf.write(_PACKAGE_MAGIC)
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
                manifest = self._build_export_manifest(selection)
                zf.writestr(_MANIFEST_PATH, json.dumps(manifest, ensure_ascii=False, indent=2))
                self._write_export_payload(zf, selection)
            write_bytes_with_uac(export_path, buf.getvalue(), ensure_parent=True)

            self._show_success(
                _tr(
                    self._i18n,
                    f"配置导出成功：{export_path}",
                    f"Configuration exported successfully: {export_path}",
                )
            )
            return True
        except Exception as exc:
            logger.exception("导出配置失败")
            self._show_error(
                _tr(self._i18n, f"导出失败：{exc}", f"Export failed: {exc}")
            )
            return False

    def _write_export_payload(self, zf: zipfile.ZipFile, selection: _Selection) -> None:
        config_dir = Path(CONFIG_DIR)
        plugins_dir = Path(PLUGINS_DIR)

        for config_file in sorted(selection.config_files):
            src = config_dir / config_file
            if src.exists() and src.is_file():
                zf.write(src, f"config/{config_file}")

        for plugin_id in sorted(selection.plugins):
            plugin_path = plugins_dir / plugin_id
            if not plugin_path.exists() or not plugin_path.is_dir():
                continue
            for file_path in plugin_path.rglob("*"):
                if not file_path.is_file():
                    continue
                rel = file_path.relative_to(plugin_path).as_posix()
                zf.write(file_path, f"plugins/{plugin_id}/{rel}")

        data_dir = plugins_dir / "._data"
        for data_name in sorted(selection.plugin_data):
            src = data_dir / data_name
            if not src.exists():
                continue
            if src.is_file():
                zf.write(src, f"plugin_data/{data_name}")
                continue
            for file_path in src.rglob("*"):
                if not file_path.is_file():
                    continue
                rel = file_path.relative_to(src).as_posix()
                zf.write(file_path, f"plugin_data/{data_name}/{rel}")

        if selection.include_lib:
            lib_dir = plugins_dir / "_lib"
            if lib_dir.exists() and lib_dir.is_dir():
                for file_path in lib_dir.rglob("*"):
                    if not file_path.is_file():
                        continue
                    rel = file_path.relative_to(lib_dir).as_posix()
                    zf.write(file_path, f"_lib/{rel}")

    def _do_import(self) -> bool:
        if self._import_file_path is None:
            self._show_error(
                _tr(
                    self._i18n,
                    "请先选择要导入的配置文件。",
                    "Please select a configuration file first.",
                )
            )
            return False

        selection = self._collect_selection(self._import_tree)
        if selection.is_empty():
            self._show_error(
                _tr(
                    self._i18n,
                    "请至少选择一项导入内容。",
                    "Please select at least one item to import.",
                )
            )
            return False

        copied_files = 0
        config_base = Path(CONFIG_DIR).resolve()
        plugins_base = Path(PLUGINS_DIR).resolve()
        plugin_data_base = (plugins_base / "._data").resolve()
        lib_base = (plugins_base / "_lib").resolve()

        try:
            with zipfile.ZipFile(self._import_file_path, "r") as zf:
                for member_name in zf.namelist():
                    if member_name.endswith("/"):
                        continue

                    parts = PurePosixPath(member_name).parts
                    if not parts or any(part in {"", ".", ".."} for part in parts):
                        continue

                    root = parts[0]
                    target_path: Optional[Path] = None

                    if root == "config" and len(parts) == 2:
                        config_file = _normalize_simple_name(parts[1])
                        if config_file in selection.config_files:
                            candidate = (config_base / config_file).resolve()
                            if _is_relative_to(candidate, config_base):
                                target_path = candidate

                    elif root == "plugins" and len(parts) >= 3:
                        plugin_id = _normalize_simple_name(parts[1])
                        if plugin_id in selection.plugins:
                            rel = Path(*parts[1:])
                            candidate = (plugins_base / rel).resolve()
                            if _is_relative_to(candidate, plugins_base):
                                target_path = candidate

                    elif root == "plugin_data" and len(parts) >= 2:
                        data_name = _normalize_simple_name(parts[1])
                        if data_name in selection.plugin_data:
                            rel = Path(*parts[1:])
                            candidate = (plugin_data_base / rel).resolve()
                            if _is_relative_to(candidate, plugin_data_base):
                                target_path = candidate

                    elif root == "_lib" and len(parts) >= 2 and selection.include_lib:
                        rel = Path(*parts[1:])
                        candidate = (lib_base / rel).resolve()
                        if _is_relative_to(candidate, lib_base):
                            target_path = candidate

                    if target_path is None:
                        continue

                    with zf.open(member_name) as src:
                        write_bytes_with_uac(target_path, src.read(), ensure_parent=True)
                    copied_files += 1

            if copied_files == 0:
                self._show_error(
                    _tr(
                        self._i18n,
                        "导入完成，但未匹配到任何可写入文件。",
                        "Import finished, but no matching files were written.",
                    )
                )
                return False

            self._show_success(
                _tr(
                    self._i18n,
                    f"配置导入成功，共写入 {copied_files} 个文件。部分设置可能需要重启后生效。",
                    f"Import completed. {copied_files} files written. Some changes may require restart.",
                )
            )
            self.migrationCompleted.emit()
            return True
        except zipfile.BadZipFile:
            self._show_error(
                _tr(self._i18n, "配置文件格式无效。", "Invalid configuration package format.")
            )
            return False
        except Exception as exc:
            logger.exception("导入配置失败")
            self._show_error(
                _tr(self._i18n, f"导入失败：{exc}", f"Import failed: {exc}")
            )
            return False

    def _collect_config_files(self) -> list[str]:
        config_dir = Path(CONFIG_DIR)
        if not config_dir.exists() or not config_dir.is_dir():
            return []
        files = []
        for path in sorted(config_dir.glob("*.json")):
            if path.name == "i18n.json":
                continue
            files.append(path.name)
        return files

    def _collect_plugin_data_entries(self) -> list[str]:
        data_dir = Path(PLUGINS_DIR) / "._data"
        if not data_dir.exists() or not data_dir.is_dir():
            return []
        names: list[str] = []
        for entry in sorted(data_dir.iterdir(), key=lambda p: p.name.lower()):
            if not entry.is_dir():
                continue
            name = _normalize_simple_name(entry.name)
            if name:
                names.append(name)
        return names

    def _discover_plugins(self) -> list[tuple[str, str]]:
        plugins: dict[str, str] = {}
        lang = self._i18n.language

        if self._plugin_manager is not None:
            if hasattr(self._plugin_manager, "all_known_plugins"):
                try:
                    for meta, *_ in self._plugin_manager.all_known_plugins():
                        if meta is None:
                            continue
                        pid = _normalize_simple_name(getattr(meta, "id", ""))
                        if not pid:
                            continue
                        try:
                            plugins[pid] = str(meta.get_name(lang) or pid)
                        except Exception:
                            plugins[pid] = str(getattr(meta, "name", pid) or pid)
                except Exception:
                    logger.warning("获取 all_known_plugins 失败，回退目录扫描")

            if hasattr(self._plugin_manager, "all_entries"):
                try:
                    for entry in self._plugin_manager.all_entries():
                        meta = getattr(entry, "meta", None)
                        if meta is None:
                            continue
                        pid = _normalize_simple_name(getattr(meta, "id", ""))
                        if not pid:
                            continue
                        try:
                            plugins[pid] = str(meta.get_name(lang) or pid)
                        except Exception:
                            plugins[pid] = str(getattr(meta, "name", pid) or pid)
                except Exception:
                    logger.warning("获取 all_entries 失败，回退目录扫描")

        plugins_dir = Path(PLUGINS_DIR)
        if plugins_dir.exists() and plugins_dir.is_dir():
            for entry in plugins_dir.iterdir():
                if not entry.is_dir():
                    continue
                if entry.name.startswith("_") or entry.name.startswith("."):
                    continue
                pid = _normalize_simple_name(entry.name)
                if pid and pid not in plugins:
                    plugins[pid] = pid

        return sorted(plugins.items(), key=lambda x: x[1].lower())

    def _has_lib_files(self) -> bool:
        lib_dir = Path(PLUGINS_DIR) / "_lib"
        if not lib_dir.exists() or not lib_dir.is_dir():
            return False
        return any(path.is_file() for path in lib_dir.rglob("*"))

    def _config_purpose(self, file_name: str) -> str:
        key, default_desc = _CONFIG_FILE_INFO.get(file_name, ("", file_name))
        if key:
            return self._i18n.t(key, default=default_desc)
        return _tr(self._i18n, "自定义配置", "Custom Config")

    def _is_custom_package(self, file_path: Path) -> bool:
        try:
            with open(file_path, "rb") as fp:
                return fp.read(len(_PACKAGE_MAGIC)) == _PACKAGE_MAGIC
        except OSError:
            return False

    def _show_success(self, message: str) -> None:
        InfoBar.success(
            title=self._i18n.t("common.success", default="成功"),
            content=message,
            parent=self,
            position=InfoBarPosition.TOP,
            duration=4000,
        )

    def _show_error(self, message: str) -> None:
        InfoBar.error(
            title=self._i18n.t("common.error", default="错误"),
            content=message,
            parent=self,
            position=InfoBarPosition.TOP,
            duration=5000,
        )

    @staticmethod
    def _get_desktop_path() -> Path:
        desktop = Path.home() / "Desktop"
        if desktop.exists():
            return desktop
        return Path.home()
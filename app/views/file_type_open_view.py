"""文件类型打开窗口。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, List

from PySide6.QtCore import QParallelAnimationGroup, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QHBoxLayout, QHeaderView, QStackedWidget, QTreeWidgetItem, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    BreadcrumbBar,
    FluentIcon as FIF,
    FluentWidget,
    PrimaryPushButton,
    PushButton,
    SubtitleLabel,
    TitleLabel,
    TreeWidget,
)

from app.constants import APP_NAME, ICON_PATH
from app.services.i18n_service import I18nService
from app.services.settings_service import SettingsService
from app.utils.breadcrumb_animation import animate_stacked_page_slide, stop_animations


_ROLE_ACTION_ID = int(Qt.ItemDataRole.UserRole)


class FileTypeOpenWindow(FluentWidget):
    """用于选择文件打开方式的动态向导窗口。"""

    actionRequested = Signal(str, str, object)

    _ROUTE_METHOD = "file_open_method"

    def __init__(self, parent=None):
        super().__init__(parent)

        self._i18n = I18nService.instance()
        self._settings = SettingsService.instance()
        self._active_animations: list[QParallelAnimationGroup] = []
        self._current_file_path: str = ""
        self._current_extension: str = ""
        self._actions: List[dict[str, Any]] = []
        self._selected_action_id: str = ""

        self._wizard_state: dict[str, Any] = {}
        self._dynamic_page_defs: List[dict[str, Any]] = []
        self._dynamic_page_widgets: List[QWidget] = []

        self._syncing_wizard_breadcrumb = False
        self._max_unlocked_step = 0
        self._steps: list[tuple[str, str]] = [
            (self._ROUTE_METHOD, self._t("filetype.open.breadcrumb.method", "选择打开方式"))
        ]
        self._route_to_step = {self._ROUTE_METHOD: 0}

        self._build_ui()
        self._bind_signals()
        self._set_step(0)
        self._retranslate()

    def _build_ui(self) -> None:
        self.resize(900, 620)
        self.setMinimumSize(820, 560)
        if ICON_PATH:
            self.setWindowIcon(QIcon(ICON_PATH))
        self.setWindowTitle(APP_NAME)

        root = QVBoxLayout(self)
        root.setContentsMargins(26, self.titleBar.height() + 16, 26, 24)
        root.setSpacing(12)

        self._header_title = TitleLabel("", self)
        self._header_subtitle = BodyLabel("", self)
        self._header_subtitle.setWordWrap(True)

        self._file_path = BodyLabel("", self)
        self._file_path.setWordWrap(True)

        self._wizard_breadcrumb = BreadcrumbBar(self)
        self._wizard_breadcrumb.setSpacing(10)

        self._stack = QStackedWidget(self)
        self._build_method_page()

        root.addWidget(self._header_title)
        root.addWidget(self._header_subtitle)
        root.addWidget(self._file_path)
        root.addWidget(self._wizard_breadcrumb)
        root.addWidget(self._stack, 1)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        footer.addStretch()

        self._cancel_btn = PushButton(FIF.CANCEL, "", self)
        self._back_btn = PushButton(FIF.LEFT_ARROW, "", self)
        self._next_btn = PrimaryPushButton(FIF.RIGHT_ARROW, "", self)
        self._execute_btn = PrimaryPushButton(FIF.ACCEPT, "", self)

        footer.addWidget(self._cancel_btn)
        footer.addWidget(self._back_btn)
        footer.addWidget(self._next_btn)
        footer.addWidget(self._execute_btn)
        root.addLayout(footer)

    def _build_method_page(self) -> None:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(10)

        self._method_tip = SubtitleLabel("", page)
        self._method_tree = TreeWidget(page)
        self._method_tree.setColumnCount(3)
        self._method_tree.setHeaderLabels(["", "", ""])
        header = self._method_tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)

        layout.addWidget(self._method_tip)
        layout.addWidget(self._method_tree)
        self._stack.addWidget(page)

    def _bind_signals(self) -> None:
        self._cancel_btn.clicked.connect(self.close)
        self._back_btn.clicked.connect(lambda: self._set_step(self._stack.currentIndex() - 1))
        self._next_btn.clicked.connect(self._go_next)
        self._execute_btn.clicked.connect(self._emit_action)
        self._wizard_breadcrumb.currentItemChanged.connect(self._on_wizard_breadcrumb_changed)

        self._method_tree.itemSelectionChanged.connect(self._on_method_selected)
        self._method_tree.itemDoubleClicked.connect(lambda *_: self._go_next())
        self._i18n.languageChanged.connect(lambda _: self._retranslate())

    def _t(self, key: str, default: str, **kwargs: Any) -> str:
        return self._i18n.t(key, default=default, **kwargs)

    def _resolve_text(self, value: Any, default: str = "") -> str:
        return self._i18n.resolve_text(value, default)

    def _refresh_file_path_label(self) -> None:
        if self._current_file_path:
            self._file_path.setText(
                self._t("filetype.open.file.label", "文件：{path}", path=self._current_file_path)
            )
        else:
            self._file_path.clear()

    def _retranslate(self) -> None:
        self.setWindowTitle(
            f"{APP_NAME} - {self._t('filetype.open.window.title', '打开文件')}"
        )
        self._header_title.setText(self._t("filetype.open.header.title", "打开文件"))
        self._header_subtitle.setText(
            self._t("filetype.open.header.subtitle", "请选择打开方式，再完成对应功能。")
        )
        self._method_tip.setText(self._t("filetype.open.method.tip", "请选择打开方式"))
        self._method_tree.setHeaderLabels(
            [
                self._t("filetype.open.method.column.title", "打开方式"),
                self._t("filetype.open.method.column.content", "内容说明"),
                self._t("filetype.open.method.column.source", "来源"),
            ]
        )

        self._cancel_btn.setText(self._t("common.cancel", "取消"))
        self._back_btn.setText(self._t("common.back", "上一步"))
        self._next_btn.setText(self._t("common.next", "下一步"))
        self._execute_btn.setText(self._t("common.execute", "执行"))

        self._steps = [
            (self._ROUTE_METHOD, self._t("filetype.open.breadcrumb.method", "选择打开方式")),
        ]
        self._rebuild_wizard_breadcrumb()

        # 刷新当前页
        idx = self._stack.currentIndex()
        if idx == 0:
            self._repopulate_method_tree()

    def _rebuild_wizard_breadcrumb(self) -> None:
        self._syncing_wizard_breadcrumb = True
        self._wizard_breadcrumb.clear()
        for step_id, step_label in self._steps:
            item = self._wizard_breadcrumb.newItem()
            item.setText(step_label)
            item.setData(step_id)
        self._syncing_wizard_breadcrumb = False

    def _set_step(self, index: int) -> None:
        if index < 0 or index >= self._stack.count():
            return
        previous_index = self._stack.currentIndex()
        self._stack.setCurrentIndex(index)
        self._update_nav_buttons()
        # 同步 breadcrumb
        self._syncing_wizard_breadcrumb = True
        self._wizard_breadcrumb.setCurrentIndex(index)
        self._syncing_wizard_breadcrumb = False
        animate_stacked_page_slide(
            host=self,
            stack=self._stack,
            target_index=index,
            previous_index=previous_index,
            enabled=self._settings.ui_smooth_scroll_enabled,
            active_animations=self._active_animations,
        )

    def closeEvent(self, event) -> None:
        stop_animations(self._active_animations)
        super().closeEvent(event)

    def _update_nav_buttons(self) -> None:
        idx = self._stack.currentIndex()
        self._back_btn.setEnabled(idx > 0)
        self._next_btn.setEnabled(False)
        self._execute_btn.setVisible(False)

    def _on_wizard_breadcrumb_changed(self, item: Any) -> None:
        if self._syncing_wizard_breadcrumb or item is None:
            return
        step_id = item.data()
        idx = next(
            (i for i, (sid, _) in enumerate(self._steps) if sid == step_id),
            -1,
        )
        if idx >= 0:
            self._set_step(idx)

    def _on_method_selected(self) -> None:
        items = self._method_tree.selectedItems()
        if items:
            self._selected_action_id = items[0].data(0, _ROLE_ACTION_ID) or ""
        else:
            self._selected_action_id = ""
        self._update_nav_buttons()
        if self._selected_action_id:
            self._next_btn.setEnabled(True)

    def _go_next(self) -> None:
        idx = self._stack.currentIndex()
        if idx == 0:
            if not self._selected_action_id:
                return
            # 检查是否有向导页面
            action = next(
                (a for a in self._actions if a.get("action_id") == self._selected_action_id),
                None,
            )
            if action and action.get("wizard_pages"):
                # 有向导页面，切换到下一页
                self._prepare_dynamic_pages(action)
                if self._dynamic_page_widgets:
                    self._set_step(1)
                    return

            # 没有向导页面，直接执行
            self._emit_action()
        else:
            # 动态向导页面，下一步或完成
            self._emit_action()

    def _prepare_dynamic_pages(self, action: dict[str, Any]) -> None:
        # 清理旧页面
        for w in self._dynamic_page_widgets:
            self._stack.removeWidget(w)
            w.deleteLater()
        self._dynamic_page_widgets.clear()
        self._dynamic_page_defs = action.get("wizard_pages") or []

    def _emit_action(self) -> None:
        if not self._selected_action_id:
            return
        self.actionRequested.emit(
            self._current_file_path,
            self._selected_action_id,
            None,
        )
        self.close()

    def open_file(
        self,
        file_path: Path,
        file_extension: str,
        actions: List[dict[str, Any]],
    ) -> None:
        self._current_file_path = str(file_path)
        self._current_extension = file_extension
        self._actions = list(actions)
        self._selected_action_id = ""
        self._wizard_state.clear()

        # 清理旧的动态页面
        for w in self._dynamic_page_widgets:
            self._stack.removeWidget(w)
            w.deleteLater()
        self._dynamic_page_widgets.clear()
        self._dynamic_page_defs.clear()

        # 重置到首页
        while self._stack.count() > 1:
            self._stack.removeWidget(self._stack.widget(1))

        self._set_step(0)
        self._repopulate_method_tree()
        self._refresh_file_path_label()
        self.show()
        self.activateWindow()
        self._method_tree.setFocus()

    def _repopulate_method_tree(self) -> None:
        self._method_tree.clear()
        for action in self._actions:
            item = QTreeWidgetItem()
            item.setText(0, action.get("title", action.get("action_id", "")))
            item.setText(1, action.get("description", ""))
            item.setText(2, " / ".join(action.get("breadcrumb", [])))
            item.setData(0, _ROLE_ACTION_ID, action.get("action_id"))
            self._method_tree.addTopLevelItem(item)

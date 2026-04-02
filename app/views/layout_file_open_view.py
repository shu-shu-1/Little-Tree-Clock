"""布局文件打开窗口。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QParallelAnimationGroup, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QHBoxLayout, QHeaderView, QStackedWidget, QTreeWidgetItem, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    BreadcrumbBar,
    FluentIcon as FIF,
    FluentWidget,
    InfoBar,
    InfoBarPosition,
    LineEdit,
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
_ROLE_OPTION_VALUE = int(Qt.ItemDataRole.UserRole) + 1
_ROLE_OPTION_LABEL = int(Qt.ItemDataRole.UserRole) + 2


def _normalize_breadcrumb_path(
    value: Any,
    fallback: str,
    *,
    resolve: Callable[[Any, str], str] | None = None,
) -> list[str]:
    if isinstance(value, str):
        parts = [value]
    elif isinstance(value, (list, tuple)):
        parts = [str(item) for item in value]
    else:
        parts = []

    result: list[str] = []
    for item in parts:
        if resolve is not None:
            text = resolve(item, "").strip()
        else:
            text = str(item or "").strip()
        if text:
            result.append(text)

    if not result:
        result = [fallback]
    return result


class LayoutFileOpenWindow(FluentWidget):
    """用于选择 .ltlayout 打开用途的动态向导窗口。"""

    actionRequested = Signal(str, str, object)

    _ROUTE_METHOD = "layout_open_method"

    def __init__(self, parent=None):
        super().__init__(parent)

        self._i18n = I18nService.instance()
        self._settings = SettingsService.instance()
        self._active_animations: list[QParallelAnimationGroup] = []
        self._current_file_path = ""
        self._normalized_actions: list[dict[str, Any]] = []
        self._selected_action_id = ""

        self._wizard_state: dict[str, Any] = {}
        self._dynamic_page_defs: list[dict[str, Any]] = []
        self._dynamic_page_widgets: list[QWidget] = []

        self._syncing_wizard_breadcrumb = False
        self._max_unlocked_step = 0
        self._steps: list[tuple[str, str]] = [
            (self._ROUTE_METHOD, self._t("layout.open.breadcrumb.method", "选择打开方式"))
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
        self._method_tree.setColumnCount(4)
        self._method_tree.setHeaderLabels(["", "", "", ""])
        header = self._method_tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)

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

    def _resolve_schema_text(self, schema: dict[str, Any], key: str, default: str = "") -> str:
        base = self._resolve_text(schema.get(key), default)
        return self._resolve_text(schema.get(f"{key}_i18n"), base)

    def _refresh_file_path_label(self) -> None:
        if self._current_file_path:
            self._file_path.setText(
                self._t("layout.open.file.label", "文件：{path}", path=self._current_file_path)
            )
        else:
            self._file_path.clear()

    def _retranslate(self) -> None:
        self.setWindowTitle(
            f"{APP_NAME} - {self._t('layout.open.window.title', '打开布局文件')}"
        )
        self._header_title.setText(self._t("layout.open.header.title", "打开布局文件"))
        self._header_subtitle.setText(
            self._t("layout.open.header.subtitle", "请选择打开方式，再完成对应功能。")
        )
        self._method_tip.setText(self._t("layout.open.method.tip", "请选择打开方式"))
        self._method_tree.setHeaderLabels(
            [
                self._t("layout.open.method.column.title", "打开方式"),
                self._t("layout.open.method.column.path", "路径"),
                self._t("layout.open.method.column.content", "内容说明"),
                self._t("layout.open.method.column.source", "来源"),
            ]
        )

        self._cancel_btn.setText(self._t("common.cancel", "取消"))
        self._back_btn.setText(self._t("migration.action.back", "上一步"))
        self._next_btn.setText(self._t("migration.action.next", "下一步"))
        self._execute_btn.setText(self._t("layout.open.action.execute", "执行"))

        if self._steps and self._steps[0][0] == self._ROUTE_METHOD:
            self._steps[0] = (
                self._ROUTE_METHOD,
                self._t("layout.open.breadcrumb.method", "选择打开方式"),
            )
        self._refresh_file_path_label()
        self._refresh_wizard_breadcrumb()
        self._update_action_buttons()

    def _set_steps(self, steps: list[tuple[str, str]]) -> None:
        self._steps = list(steps) or [
            (self._ROUTE_METHOD, self._t("layout.open.breadcrumb.method", "选择打开方式"))
        ]
        self._route_to_step = {route: idx for idx, (route, _) in enumerate(self._steps)}
        max_step = len(self._steps) - 1
        self._max_unlocked_step = max(0, min(self._max_unlocked_step, max_step))

    def _refresh_wizard_breadcrumb(self) -> None:
        current_step = self._stack.currentIndex()
        if current_step < 0:
            return

        self._syncing_wizard_breadcrumb = True
        self._wizard_breadcrumb.blockSignals(True)
        try:
            self._wizard_breadcrumb.clear()
            for step in range(self._max_unlocked_step + 1):
                route, text = self._steps[step]
                self._wizard_breadcrumb.addItem(route, text)
            self._wizard_breadcrumb.setCurrentItem(self._steps[current_step][0])
        finally:
            self._wizard_breadcrumb.blockSignals(False)
            self._syncing_wizard_breadcrumb = False

    def _on_wizard_breadcrumb_changed(self, route_key: str) -> None:
        if self._syncing_wizard_breadcrumb:
            return
        step = self._route_to_step.get(route_key)
        if step is None or step > self._max_unlocked_step:
            return
        self._set_step(step)

    def _dynamic_page_def_by_step(self, step: int) -> dict[str, Any] | None:
        index = step - 1
        if index < 0 or index >= len(self._dynamic_page_defs):
            return None
        return self._dynamic_page_defs[index]

    def _current_step_ready(self) -> bool:
        step = self._stack.currentIndex()
        if step == 0:
            return bool(self._selected_action_id)

        page_def = self._dynamic_page_def_by_step(step)
        if page_def is None:
            return False

        checker = page_def.get("ready_check")
        if callable(checker):
            try:
                return bool(checker())
            except Exception:
                return False
        return True

    def _show_step_warning(self, message: str) -> None:
        InfoBar.warning(
            self._t("layout.open.step.warning.title", "请先完成当前步骤"),
            message,
            duration=2600,
            position=InfoBarPosition.TOP_RIGHT,
            parent=self,
        )

    def _validate_current_step(self, *, show_feedback: bool = True) -> bool:
        step = self._stack.currentIndex()
        if step <= 0:
            return bool(self._selected_action_id)

        page_def = self._dynamic_page_def_by_step(step)
        if page_def is None:
            return False

        validator = page_def.get("validate")
        if not callable(validator):
            return True

        try:
            ok, message = validator()
        except Exception:
            ok, message = False, self._t(
                "layout.open.step.warning.validation_failed",
                "当前步骤校验失败，请重试。",
            )

        if not ok and show_feedback:
            self._show_step_warning(
                str(
                    message
                    or self._t(
                        "layout.open.step.warning.fill_required",
                        "请先补全当前步骤信息。",
                    )
                )
            )
        return bool(ok)

    def _update_action_buttons(self) -> None:
        step = self._stack.currentIndex()
        last_step = len(self._steps) - 1

        self._back_btn.setVisible(step > 0)
        self._next_btn.setVisible(step == 0 or step < last_step)
        self._execute_btn.setVisible(step == last_step and step > 0)

        if step < last_step:
            self._next_btn.setEnabled(self._current_step_ready())
        else:
            self._execute_btn.setEnabled(
                bool(self._current_file_path and self._selected_action_id and self._current_step_ready())
            )

    def _normalize_actions(self, actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for action in actions:
            action_id = str(action.get("action_id") or "").strip()
            if not action_id:
                continue

            plugin_id = str(action.get("plugin_id") or "").strip()
            source = (
                self._t("layout.open.source.builtin", "内置")
                if plugin_id in {"", "__builtin__"}
                else plugin_id
            )
            breadcrumb_path = _normalize_breadcrumb_path(
                action.get("breadcrumb"),
                source,
                resolve=self._resolve_text,
            )

            base_content = self._resolve_text(
                action.get("content"),
                self._resolve_text(action.get("description"), ""),
            )
            content = self._resolve_text(
                action.get("content_i18n"),
                self._resolve_text(action.get("description_i18n"), base_content),
            ).strip()

            title = self._resolve_text(
                action.get("title_i18n"),
                self._resolve_text(action.get("title"), action_id),
            )

            try:
                order = int(action.get("order") or 100)
            except Exception:
                order = 100

            normalized.append(
                {
                    "action_id": action_id,
                    "title": title,
                    "content": content,
                    "plugin_id": plugin_id,
                    "source": source,
                    "breadcrumb_path": breadcrumb_path,
                    "breadcrumb_text": " / ".join(breadcrumb_path),
                    "wizard_pages": action.get("wizard_pages"),
                    "order": order,
                }
            )

        normalized.sort(
            key=lambda item: (
                int(item.get("order") or 100),
                str(item.get("breadcrumb_text") or "").lower(),
                str(item.get("title") or "").lower(),
                str(item.get("action_id") or ""),
            )
        )
        return normalized

    def _populate_method_page(self) -> None:
        self._method_tree.clear()
        self._selected_action_id = ""

        for action in self._normalized_actions:
            action_id = str(action.get("action_id") or "")
            item = QTreeWidgetItem(
                [
                    str(action.get("title") or action_id),
                    str(action.get("breadcrumb_text") or "-"),
                    str(action.get("content") or ""),
                    str(action.get("source") or ""),
                ]
            )
            item.setData(0, _ROLE_ACTION_ID, action_id)
            self._method_tree.addTopLevelItem(item)

        if self._method_tree.topLevelItemCount() > 0:
            self._method_tree.setCurrentItem(self._method_tree.topLevelItem(0))
        self._on_method_selected()

    def _selected_method_action_id(self) -> str:
        item = self._method_tree.currentItem()
        if item is None:
            return ""
        return str(item.data(0, _ROLE_ACTION_ID) or "")

    def _on_method_selected(self) -> None:
        self._selected_action_id = self._selected_method_action_id()
        self._update_action_buttons()

    def _selected_action(self) -> dict[str, Any] | None:
        for action in self._normalized_actions:
            if str(action.get("action_id") or "") == self._selected_action_id:
                return action
        return None

    def _remove_dynamic_pages(self) -> None:
        for page in self._dynamic_page_widgets:
            self._stack.removeWidget(page)
            page.deleteLater()
        self._dynamic_page_widgets.clear()
        self._dynamic_page_defs.clear()
        self._wizard_state.clear()

    def _resolve_action_pages(self, action: dict[str, Any]) -> list[dict[str, Any]]:
        raw_pages = action.get("wizard_pages")

        if callable(raw_pages):
            try:
                raw_pages = raw_pages(Path(self._current_file_path))
            except Exception:
                raw_pages = []

        if not isinstance(raw_pages, list) or not raw_pages:
            return [
                {
                    "type": "info",
                    "title": self._t("layout.open.step.execute.title", "执行方式"),
                    "content": str(
                        action.get("content")
                        or self._t("layout.open.step.execute.content", "确认后立即执行该操作。")
                    ),
                }
            ]

        pages: list[dict[str, Any]] = []
        for item in raw_pages:
            if isinstance(item, dict):
                pages.append(dict(item))
        return pages

    def _build_info_page(self, schema: dict[str, Any], index: int) -> dict[str, Any]:
        title = self._resolve_schema_text(
            schema,
            "title",
            self._t("layout.open.step.default.title", "步骤 {num}", num=index + 2),
        )
        route = f"layout_open_dynamic_{index}"

        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(10)

        tip = SubtitleLabel(title, page)
        content = self._resolve_schema_text(
            schema,
            "content",
            self._resolve_schema_text(
                schema,
                "description",
                self._t("layout.open.step.execute.content", "确认后将执行所选打开方式。"),
            ),
        )
        body = BodyLabel(content, page)
        body.setWordWrap(True)

        layout.addWidget(tip)
        layout.addWidget(body)
        layout.addStretch()

        return {
            "route": route,
            "title": title,
            "widget": page,
            "ready_check": lambda: True,
            "validate": lambda: (True, ""),
        }

    def _build_text_page(self, schema: dict[str, Any], index: int) -> dict[str, Any]:
        title = self._resolve_schema_text(
            schema,
            "title",
            self._t("layout.open.step.default.title", "步骤 {num}", num=index + 2),
        )
        route = f"layout_open_dynamic_{index}"

        field = str(schema.get("field") or f"text_{index}").strip() or f"text_{index}"
        required = bool(schema.get("required", True))
        empty_error = self._resolve_schema_text(
            schema,
            "empty_error",
            self._t("layout.open.text.empty_error", "请先填写内容再继续。"),
        )

        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(10)

        tip = SubtitleLabel(title, page)
        layout.addWidget(tip)

        desc_text = self._resolve_schema_text(
            schema,
            "description",
            self._resolve_schema_text(schema, "content", ""),
        ).strip()
        if desc_text:
            desc = BodyLabel(desc_text, page)
            desc.setWordWrap(True)
            layout.addWidget(desc)

        label_text = self._resolve_schema_text(
            schema,
            "label",
            self._t("layout.open.text.label", "请输入内容："),
        )
        label = BodyLabel(label_text, page)
        layout.addWidget(label)

        editor = LineEdit(page)
        editor.setPlaceholderText(self._resolve_schema_text(schema, "placeholder", ""))
        default_text = self._resolve_schema_text(schema, "default", "")
        editor.setText(default_text)
        max_length = schema.get("max_length")
        if isinstance(max_length, int) and max_length > 0:
            editor.setMaxLength(max_length)
        layout.addWidget(editor)
        layout.addStretch()

        if default_text.strip() or not required:
            self._wizard_state[field] = default_text.strip()

        def sync_text() -> None:
            value = str(editor.text() or "").strip()
            if value:
                self._wizard_state[field] = value
            else:
                self._wizard_state.pop(field, None)
            self._update_action_buttons()

        editor.textChanged.connect(lambda *_: sync_text())
        sync_text()

        def ready_check() -> bool:
            if not required:
                return True
            return bool(str(self._wizard_state.get(field) or "").strip())

        def validate() -> tuple[bool, str]:
            if not required:
                return True, ""
            if not str(self._wizard_state.get(field) or "").strip():
                return False, empty_error
            return True, ""

        return {
            "route": route,
            "title": title,
            "widget": page,
            "ready_check": ready_check,
            "validate": validate,
        }

    def _build_select_page(self, schema: dict[str, Any], index: int) -> dict[str, Any]:
        title = self._resolve_schema_text(
            schema,
            "title",
            self._t("layout.open.step.default.title", "步骤 {num}", num=index + 2),
        )
        route = f"layout_open_dynamic_{index}"

        field = str(schema.get("field") or f"select_{index}").strip() or f"select_{index}"
        required = bool(schema.get("required", True))
        empty_error = self._resolve_schema_text(
            schema,
            "empty_error",
            self._t("layout.open.select.empty_error", "请先选择一项再继续。"),
        )

        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(10)

        tip = SubtitleLabel(title, page)
        layout.addWidget(tip)

        desc_text = self._resolve_schema_text(
            schema,
            "description",
            self._resolve_schema_text(schema, "content", ""),
        ).strip()
        if desc_text:
            desc = BodyLabel(desc_text, page)
            desc.setWordWrap(True)
            layout.addWidget(desc)

        tree = TreeWidget(page)
        tree.setColumnCount(2)
        tree.setHeaderLabels(
            [
                self._t("layout.open.select.column.option", "选项"),
                self._t("layout.open.select.column.description", "说明"),
            ]
        )
        header = tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(tree)

        options = schema.get("options")
        default_value = schema.get("default")
        has_options = isinstance(options, list) and len(options) > 0

        selected_default_item = None
        if has_options:
            for opt in options:
                if isinstance(opt, dict):
                    value = opt.get("value")
                    label = self._resolve_text(
                        opt.get("label_i18n"),
                        self._resolve_text(opt.get("label"), str(value or "")),
                    )
                    detail = self._resolve_text(
                        opt.get("description_i18n"),
                        self._resolve_text(opt.get("description"), ""),
                    )
                else:
                    value = opt
                    label = str(opt)
                    detail = ""

                item = QTreeWidgetItem([label, detail])
                item.setData(0, _ROLE_OPTION_VALUE, value)
                item.setData(0, _ROLE_OPTION_LABEL, label)
                tree.addTopLevelItem(item)

                if default_value is not None and value == default_value:
                    selected_default_item = item

            if selected_default_item is not None:
                tree.setCurrentItem(selected_default_item)
            elif tree.topLevelItemCount() > 0:
                tree.setCurrentItem(tree.topLevelItem(0))
        else:
            empty_hint = BodyLabel(
                self._resolve_schema_text(
                    schema,
                    "empty_text",
                    self._t("layout.open.select.empty_text", "当前没有可用选项。"),
                ),
                page,
            )
            empty_hint.setWordWrap(True)
            layout.addWidget(empty_hint)

        layout.addStretch()

        def sync_selection() -> None:
            item = tree.currentItem()
            if item is None:
                self._wizard_state.pop(field, None)
                self._wizard_state.pop(f"{field}_label", None)
            else:
                self._wizard_state[field] = item.data(0, _ROLE_OPTION_VALUE)
                self._wizard_state[f"{field}_label"] = str(item.data(0, _ROLE_OPTION_LABEL) or "")
            self._update_action_buttons()

        tree.itemSelectionChanged.connect(sync_selection)
        sync_selection()

        def ready_check() -> bool:
            if not required:
                return True
            return field in self._wizard_state and self._wizard_state.get(field) not in {None, ""}

        def validate() -> tuple[bool, str]:
            if not required:
                return True, ""
            if not ready_check():
                return False, empty_error
            return True, ""

        return {
            "route": route,
            "title": title,
            "widget": page,
            "ready_check": ready_check,
            "validate": validate,
        }

    def _build_dynamic_page_def(self, schema: dict[str, Any], index: int) -> dict[str, Any]:
        page_type = str(schema.get("type") or "info").strip().lower()
        if page_type == "select":
            return self._build_select_page(schema, index)
        if page_type == "text":
            return self._build_text_page(schema, index)
        return self._build_info_page(schema, index)

    def _prepare_selected_action_pages(self) -> bool:
        action = self._selected_action()
        if action is None:
            return False

        self._remove_dynamic_pages()

        page_schemas = self._resolve_action_pages(action)
        for idx, schema in enumerate(page_schemas):
            page_def = self._build_dynamic_page_def(schema, idx)
            widget = page_def.get("widget")
            if not isinstance(widget, QWidget):
                continue
            self._dynamic_page_defs.append(page_def)
            self._dynamic_page_widgets.append(widget)
            self._stack.addWidget(widget)

        if not self._dynamic_page_defs:
            fallback = self._build_info_page(
                {
                    "title": self._t("layout.open.step.execute.title", "执行方式"),
                    "content": self._t(
                        "layout.open.step.execute.content",
                        "确认后将执行所选打开方式。",
                    ),
                },
                0,
            )
            widget = fallback["widget"]
            self._dynamic_page_defs.append(fallback)
            self._dynamic_page_widgets.append(widget)
            self._stack.addWidget(widget)

        steps = [
            (self._ROUTE_METHOD, self._t("layout.open.breadcrumb.method", "选择打开方式"))
        ]
        steps.extend(
            (
                str(item.get("route") or ""),
                str(item.get("title") or self._t("layout.open.step.default.short", "步骤")),
            )
            for item in self._dynamic_page_defs
        )
        self._set_steps(steps)
        self._max_unlocked_step = 1
        return True

    def _go_next(self) -> None:
        step = self._stack.currentIndex()
        last_step = len(self._steps) - 1

        if step == 0:
            if not self._selected_action_id:
                return
            if not self._prepare_selected_action_pages():
                return
            self._set_step(1)
            return

        if step >= last_step:
            return

        if not self._validate_current_step(show_feedback=True):
            return

        self._set_step(step + 1)

    def _set_step(self, step: int) -> None:
        last_step = len(self._steps) - 1
        step = max(0, min(last_step, step))
        previous_step = self._stack.currentIndex()
        self._max_unlocked_step = max(self._max_unlocked_step, step)
        self._stack.setCurrentIndex(step)
        self._refresh_wizard_breadcrumb()
        self._update_action_buttons()
        animate_stacked_page_slide(
            host=self,
            stack=self._stack,
            target_index=step,
            previous_index=previous_step,
            enabled=self._settings.ui_smooth_scroll_enabled,
            active_animations=self._active_animations,
        )

    def _reset_state(self) -> None:
        self._current_file_path = ""
        self._normalized_actions = []
        self._selected_action_id = ""
        self._remove_dynamic_pages()
        self._method_tree.clear()
        self._set_steps(
            [
                (
                    self._ROUTE_METHOD,
                    self._t("layout.open.breadcrumb.method", "选择打开方式"),
                )
            ]
        )
        self._max_unlocked_step = 0
        self._set_step(0)

    def open_layout(self, file_path: Path, actions: list[dict[str, Any]]) -> None:
        self._reset_state()
        self._current_file_path = str(file_path)
        self._refresh_file_path_label()

        self._normalized_actions = self._normalize_actions(actions)
        self._populate_method_page()

        self.show()
        self.activateWindow()
        self.raise_()

    def closeEvent(self, event) -> None:
        stop_animations(self._active_animations)
        super().closeEvent(event)
        if event.isAccepted():
            self._reset_state()

    def _emit_action(self) -> None:
        if not self._current_file_path or not self._selected_action_id:
            return
        if not self._validate_current_step(show_feedback=True):
            return

        self.actionRequested.emit(
            self._current_file_path,
            self._selected_action_id,
            dict(self._wizard_state),
        )
        self.close()

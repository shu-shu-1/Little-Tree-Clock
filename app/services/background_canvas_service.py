"""托管画布关闭后仍在运行的组件实例，并统计各页面的后台组件数量。"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QWidget
from shiboken6 import isValid

from app.utils.logger import logger
from app.widgets.base_widget import WidgetBase, WidgetConfig


class BackgroundCanvasService(QObject):
    changed = Signal()

    _instance: "BackgroundCanvasService | None" = None

    def __init__(self) -> None:
        super().__init__()
        self._pages: dict[str, dict[str, WidgetBase]] = {}
        self._host: QWidget | None = None
        self._quit_connected = False
        self._bind_app_shutdown()

    @classmethod
    def instance(cls) -> "BackgroundCanvasService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _bind_app_shutdown(self) -> None:
        if self._quit_connected:
            return
        app = QApplication.instance()
        if app is None:
            return
        app.aboutToQuit.connect(self.shutdown)
        self._quit_connected = True

    def _ensure_host(self) -> QWidget:
        if self._host is None:
            self._host = QWidget()
            self._host.setObjectName("backgroundCanvasRuntimeHost")
            self._host.hide()
        return self._host

    @staticmethod
    def _is_valid_widget(widget: object) -> bool:
        return isinstance(widget, WidgetBase) and isValid(widget)

    def _collect_valid_page(self, page_id: str) -> dict[str, WidgetBase]:
        page = self._pages.get(page_id, {})
        valid = {widget_id: widget for widget_id, widget in page.items() if self._is_valid_widget(widget)}
        if valid:
            self._pages[page_id] = valid
        else:
            self._pages.pop(page_id, None)
        return valid

    def _detached_window_component_count(self, page_id: str) -> int:
        """统计画布已关闭但仍在分离窗口中运行的组件数。"""
        try:
            # 延迟导入避免 canvas → service 的循环依赖
            from app.widgets.canvas import DetachedWidgetWindow
        except Exception:
            return 0
        try:
            return int(DetachedWidgetWindow.orphaned_entry_count(page_id))
        except Exception:
            return 0

    def _detached_window_page_ids(self) -> set[str]:
        try:
            from app.widgets.canvas import DetachedWidgetWindow
        except Exception:
            return set()
        try:
            return set(DetachedWidgetWindow.orphaned_page_ids())
        except Exception:
            return set()

    def page_component_count(self, page_id: str) -> int:
        pid = str(page_id or "").strip()
        return len(self._collect_valid_page(pid)) + self._detached_window_component_count(pid)

    def background_count(self, page_id: str) -> int:
        return self.page_component_count(page_id)

    def is_page_running(self, page_id: str) -> bool:
        return self.page_component_count(page_id) > 0

    def active_pages(self) -> list[dict[str, int | str]]:
        page_ids = set(self._pages) | self._detached_window_page_ids()
        result: list[dict[str, int | str]] = []
        for page_id in page_ids:
            count = self.page_component_count(page_id)
            if count <= 0:
                continue
            result.append(
                {
                    "page_id": page_id,
                    "component_count": count,
                }
            )
        return result

    def park_widget(
        self,
        page_id: str,
        widget: WidgetBase,
        *,
        services: dict[str, Any] | None = None,
    ) -> bool:
        pid = str(page_id or "").strip()
        if not pid or not self._is_valid_widget(widget):
            return False
        if not widget.runs_in_background():
            return False

        self._bind_app_shutdown()
        host = self._ensure_host()
        page = self._collect_valid_page(pid)
        widget_id = str(widget.config.widget_id or "").strip()
        if not widget_id:
            return False

        previous = page.get(widget_id)
        if previous is not None and previous is not widget:
            self._dispose_widget(previous)

        try:
            widget.on_background_detached(services)
        except Exception:
            logger.exception("后台组件挂起失败: page_id={}, widget_id={}", pid, widget_id)

        widget.setParent(host)
        widget.hide()
        page[widget_id] = widget
        self._pages[pid] = page
        self.changed.emit()
        return True

    def store_widget(
        self,
        page_id: str,
        config: WidgetConfig,
        widget: WidgetBase,
        background_services: dict[str, Any],
    ) -> None:
        del config
        self.park_widget(page_id, widget, services=background_services)

    def restore_widget(
        self,
        page_id: str,
        config_or_widget_id: WidgetConfig | str,
        widget_type: str | None = None,
        *,
        services: dict[str, Any],
        parent: QWidget,
    ) -> WidgetBase | None:
        pid = str(page_id or "").strip()
        if isinstance(config_or_widget_id, WidgetConfig):
            widget_key = str(config_or_widget_id.widget_id or "").strip()
            expected_type = str(config_or_widget_id.widget_type or "")
        else:
            widget_key = str(config_or_widget_id or "").strip()
            expected_type = str(widget_type or "")
        if not pid or not widget_key:
            return None

        page = self._collect_valid_page(pid)
        widget = page.get(widget_key)
        if widget is None:
            return None
        if str(widget.WIDGET_TYPE or "") != expected_type:
            page.pop(widget_key, None)
            if not page:
                self._pages.pop(pid, None)
            self._dispose_widget(widget)
            self.changed.emit()
            return None

        page.pop(widget_key, None)
        if page:
            self._pages[pid] = page
        else:
            self._pages.pop(pid, None)

        widget.setParent(parent)
        try:
            widget.on_background_attached(services)
        except Exception:
            logger.exception("后台组件恢复失败: page_id={}, widget_id={}", pid, widget_key)
        widget.show()
        self.changed.emit()
        return widget

    def discard_widget(self, page_id: str, widget_id: str) -> None:
        pid = str(page_id or "").strip()
        widget_key = str(widget_id or "").strip()
        if not pid or not widget_key:
            return
        page = self._collect_valid_page(pid)
        widget = page.pop(widget_key, None)
        if widget is None:
            return
        if page:
            self._pages[pid] = page
        else:
            self._pages.pop(pid, None)
        self._dispose_widget(widget)
        self.changed.emit()

    def prune_page(self, page_id: str, allowed_widget_ids: set[str]) -> None:
        pid = str(page_id or "").strip()
        if not pid:
            return
        page = self._collect_valid_page(pid)
        if not page:
            return
        allowed = {str(widget_id or "").strip() for widget_id in allowed_widget_ids}
        removed = False
        for widget_id in [widget_id for widget_id in page if widget_id not in allowed]:
            widget = page.pop(widget_id, None)
            self._dispose_widget(widget)
            removed = True
        if page:
            self._pages[pid] = page
        else:
            self._pages.pop(pid, None)
        if removed:
            self.changed.emit()

    def clear_page(self, page_id: str) -> None:
        pid = str(page_id or "").strip()
        page = self._pages.pop(pid, None)
        if not page:
            return
        for widget in page.values():
            self._dispose_widget(widget)
        self.changed.emit()

    def shutdown(self) -> None:
        pages = list(self._pages.values())
        self._pages.clear()
        for page in pages:
            for widget in page.values():
                self._dispose_widget(widget)
        if self._host is not None:
            self._host.hide()
        self.changed.emit()

    @staticmethod
    def _dispose_widget(widget: WidgetBase) -> None:
        if not BackgroundCanvasService._is_valid_widget(widget):
            return
        widget.hide()
        widget.setParent(None)
        widget.deleteLater()

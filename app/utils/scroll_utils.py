"""全局滚动行为控制工具。"""
from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import QEvent, QObject, QTimer, Qt
from PySide6.QtWidgets import QAbstractScrollArea, QApplication, QWidget
from qfluentwidgets import ScrollArea, SmoothMode

from app.services.settings_service import SettingsService
from app.utils.logger import logger


class GlobalSmoothScrollController(QObject):
    """按设置统一控制应用内滚动区域的平滑滚动行为。"""

    _instance: "GlobalSmoothScrollController | None" = None

    def __init__(self, app: QApplication):
        super().__init__(app)
        self._app = app
        self._settings = SettingsService.instance()
        self._enabled = self._settings.ui_smooth_scroll_enabled

        self._app.installEventFilter(self)
        self._settings.changed.connect(self._on_settings_changed)

        # 事件循环就绪后再扫描，避免错过启动期已创建的滚动区域。
        QTimer.singleShot(0, self.apply_to_all)

    @classmethod
    def install(cls, app: QApplication) -> "GlobalSmoothScrollController":
        if cls._instance is None:
            cls._instance = cls(app)
        return cls._instance

    def _on_settings_changed(self) -> None:
        enabled = self._settings.ui_smooth_scroll_enabled
        if enabled == self._enabled:
            return
        self._enabled = enabled
        self.apply_to_all()

    def eventFilter(self, obj, event):
        if isinstance(obj, QAbstractScrollArea) and event.type() in {
            QEvent.Type.Show,
            QEvent.Type.Polish,
        }:
            self._apply_to_scroll_area(obj)
        return super().eventFilter(obj, event)

    def apply_to_all(self) -> None:
        applied = 0
        for area in self._iter_all_scroll_areas():
            if self._apply_to_scroll_area(area):
                applied += 1
        logger.debug(
            "[滚动] 全局平滑滚动={}，已更新 {} 个滚动区域",
            self._enabled,
            applied,
        )

    def apply_to_widget_tree(self, root: QWidget | None) -> None:
        if root is None:
            return
        for area in self._iter_scroll_areas_from_root(root):
            self._apply_to_scroll_area(area)

    def _iter_all_scroll_areas(self) -> Iterable[QAbstractScrollArea]:
        seen: set[int] = set()
        for top in self._app.topLevelWidgets():
            for area in self._iter_scroll_areas_from_root(top):
                key = id(area)
                if key in seen:
                    continue
                seen.add(key)
                yield area

    @staticmethod
    def _iter_scroll_areas_from_root(root: QWidget) -> Iterable[QAbstractScrollArea]:
        if isinstance(root, QAbstractScrollArea):
            yield root
        for area in root.findChildren(QAbstractScrollArea):
            yield area

    def _apply_to_scroll_area(self, area: QAbstractScrollArea) -> bool:
        desired_state = 1 if self._enabled else 0
        if area.property("_ltc_smooth_scroll_state") == desired_state:
            return False

        mode = SmoothMode.LINEAR if self._enabled else SmoothMode.NO_SMOOTH
        applied = False

        # qfluentwidgets.ScrollArea：分别设置横向/纵向。
        if isinstance(area, ScrollArea):
            try:
                area.setSmoothMode(mode, Qt.Orientation.Vertical)
                area.setSmoothMode(mode, Qt.Orientation.Horizontal)
                applied = True
            except Exception:
                pass

        # SingleDirectionScrollArea 或其它兼容 setSmoothMode(mode) 的类型。
        if not applied and hasattr(area, "setSmoothMode"):
            try:
                area.setSmoothMode(mode)
                applied = True
            except TypeError:
                pass
            except Exception:
                pass

        # SmoothScrollArea/ScrollArea 的委托内部处理。
        for delegate_name in ("delegate", "scrollDelagate", "scrollDelegate"):
            delegate = getattr(area, delegate_name, None)
            if delegate is None:
                continue
            if self._apply_delegate(delegate, mode):
                applied = True

        if applied:
            area.setProperty("_ltc_smooth_scroll_state", desired_state)
        return applied

    def _apply_delegate(self, delegate, mode: SmoothMode) -> bool:
        changed = False

        v_smooth = getattr(delegate, "verticalSmoothScroll", None)
        if v_smooth is not None and hasattr(v_smooth, "setSmoothMode"):
            try:
                v_smooth.setSmoothMode(mode)
                changed = True
            except Exception:
                pass

        h_smooth = getattr(delegate, "horizonSmoothScroll", None)
        if h_smooth is not None and hasattr(h_smooth, "setSmoothMode"):
            try:
                h_smooth.setSmoothMode(mode)
                changed = True
            except Exception:
                pass

        # SmoothScrollArea 使用动画滚动，关闭平滑时切回无动画路径。
        if hasattr(delegate, "useAni"):
            try:
                delegate.useAni = bool(self._enabled)
                changed = True
            except Exception:
                pass

        duration = 500 if self._enabled else 0
        for bar_name in ("vScrollBar", "hScrollBar"):
            bar = getattr(delegate, bar_name, None)
            if bar is not None and hasattr(bar, "setScrollAnimation"):
                try:
                    bar.setScrollAnimation(duration)
                    changed = True
                except Exception:
                    pass

        return changed


def install_global_smooth_scroll_controller(app: QApplication) -> GlobalSmoothScrollController:
    return GlobalSmoothScrollController.install(app)


def apply_smooth_scroll_to_widget_tree(root: QWidget | None) -> None:
    controller = GlobalSmoothScrollController._instance
    if controller is not None:
        controller.apply_to_widget_tree(root)

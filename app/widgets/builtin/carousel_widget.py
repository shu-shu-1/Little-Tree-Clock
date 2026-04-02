"""轮播组件 —— 通过 PipsPager 在多个子组件间轮播"""
from __future__ import annotations

import copy
import random
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QFormLayout, QLabel, QStackedWidget, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    ComboBox,
    FluentIcon as FIF,
    MessageBox,
    PipsPager,
    PipsScrollButtonDisplayMode,
    SpinBox,
)

from app.widgets.base_widget import WidgetBase, WidgetConfig
from app.widgets.registry import WidgetRegistry


_MODE_SEQUENTIAL = "sequential"
_MODE_RANDOM = "random"


class _CarouselEditPanel(QWidget):
    def __init__(self, props: dict[str, Any], config: WidgetConfig, parent=None):
        super().__init__(parent)
        form = QFormLayout(self)
        form.setVerticalSpacing(10)

        self._mode_combo = ComboBox()
        self._mode_combo.addItem("顺序", userData=_MODE_SEQUENTIAL)
        self._mode_combo.addItem("随机", userData=_MODE_RANDOM)
        mode = str(props.get("mode", _MODE_SEQUENTIAL) or _MODE_SEQUENTIAL)
        mode_idx = 0 if mode == _MODE_SEQUENTIAL else 1
        self._mode_combo.setCurrentIndex(mode_idx)
        form.addRow("轮播方式:", self._mode_combo)

        self._interval_spin = SpinBox()
        self._interval_spin.setRange(1, 3600)
        self._interval_spin.setSuffix(" 秒")
        self._interval_spin.setValue(int(props.get("interval_sec", 8) or 8))
        form.addRow("轮播间隔:", self._interval_spin)

        self._grid_w_spin = SpinBox()
        self._grid_w_spin.setRange(1, 20)
        self._grid_w_spin.setValue(max(1, int(config.grid_w)))
        form.addRow("组件宽度:", self._grid_w_spin)

        self._grid_h_spin = SpinBox()
        self._grid_h_spin.setRange(1, 20)
        self._grid_h_spin.setValue(max(1, int(config.grid_h)))
        form.addRow("组件高度:", self._grid_h_spin)

    def collect_props(self) -> dict[str, Any]:
        return {
            "mode": self._mode_combo.currentData() or _MODE_SEQUENTIAL,
            "interval_sec": self._interval_spin.value(),
            "grid_w": self._grid_w_spin.value(),
            "grid_h": self._grid_h_spin.value(),
        }


class _ChildEditDialog(MessageBox):
    """轮播子组件编辑对话框。"""

    def __init__(self, widget: WidgetBase, parent=None):
        super().__init__(f"编辑组件 · {widget.WIDGET_NAME}", "", parent)
        self.yesButton.setText("保存")
        self.cancelButton.setText("取消")
        self.contentLabel.hide()

        self._widget = widget
        self._edit = widget.get_edit_widget()

        if self._edit is not None:
            self.textLayout.addWidget(self._edit)
        else:
            self.textLayout.addWidget(BodyLabel("此组件暂无可编辑属性。"))

    def accept(self) -> None:
        if self._edit is not None and hasattr(self._edit, "collect_props"):
            self._widget.apply_props(self._edit.collect_props())
        super().accept()


class CarouselWidget(WidgetBase):
    WIDGET_TYPE = "carousel"
    WIDGET_NAME = "轮播组件"
    DELETABLE = True
    MIN_W = 1
    MIN_H = 1
    DEFAULT_W = 4
    DEFAULT_H = 3

    def __init__(self, config: WidgetConfig, services, parent=None):
        super().__init__(config, services, parent)

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(4)

        self._stack = QStackedWidget(self)
        self._stack.setStyleSheet("background: transparent;")

        self._empty_hint = QLabel("拖拽组件到轮播组件上可加入轮播")
        self._empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_hint.setStyleSheet("color:#666; font-size:12px; background:transparent;")

        self._pager = PipsPager(self)
        self._pager.setFlow(self._pager.Flow.LeftToRight)
        self._pager.setVisibleNumber(8)
        self._pager.setNextButtonDisplayMode(PipsScrollButtonDisplayMode.ALWAYS)
        self._pager.setPreviousButtonDisplayMode(PipsScrollButtonDisplayMode.ALWAYS)
        self._pager.setFixedHeight(22)

        root.addWidget(self._stack, 1)
        root.addWidget(self._empty_hint, 1)
        root.addWidget(self._pager, 0, Qt.AlignmentFlag.AlignHCenter)

        self._children: list[dict[str, Any]] = []
        self._syncing_index = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._advance)

        self._pager.currentIndexChanged.connect(self._on_pager_index_changed)

        self._load_children_from_props()
        self.refresh()

    def is_carousel_widget(self) -> bool:
        return True

    def _clear_children(self) -> None:
        while self._stack.count():
            page = self._stack.widget(0)
            self._stack.removeWidget(page)
            page.setParent(None)
            page.deleteLater()
        self._children.clear()

    def _normalize_mode(self, mode: str) -> str:
        m = str(mode or _MODE_SEQUENTIAL)
        if m not in (_MODE_SEQUENTIAL, _MODE_RANDOM):
            return _MODE_SEQUENTIAL
        return m

    def _normalize_interval_sec(self, value: Any) -> int:
        try:
            return max(1, min(3600, int(value)))
        except (TypeError, ValueError):
            return 8

    def _load_children_from_props(self) -> None:
        self._clear_children()

        raw_children = self.config.props.get("children", [])
        if not isinstance(raw_children, list):
            raw_children = []

        reg = WidgetRegistry.instance()
        target_size: tuple[int, int] | None = None

        for raw in raw_children:
            if not isinstance(raw, dict):
                continue
            cfg = WidgetConfig.from_dict(raw)
            if cfg.widget_type == self.WIDGET_TYPE:
                continue

            cls = reg.get(cfg.widget_type)
            if cls is None:
                continue

            if target_size is None:
                target_size = (max(1, int(cfg.grid_w)), max(1, int(cfg.grid_h)))
            else:
                tw, th = target_size
                if (int(cfg.grid_w), int(cfg.grid_h)) != (tw, th):
                    if not bool(getattr(cls, "RESIZABLE", True)):
                        continue
                    cfg.grid_w = tw
                    cfg.grid_h = th

            child = reg.create(cfg, self.services, self._stack)
            if child is None:
                continue
            self._children.append({"config": cfg, "widget": child})
            self._stack.addWidget(child)

        if target_size is not None:
            self.config.grid_w = target_size[0]
            self.config.grid_h = target_size[1]

        self._sync_props_from_children()
        desired_index = int(self.config.props.get("active_index", 0) or 0)
        self._set_current_index(desired_index, restart_timer=False)
        self._update_ui_state()
        self._restart_timer()

    def _sync_props_from_children(self) -> None:
        self.config.props["mode"] = self._normalize_mode(self.config.props.get("mode", _MODE_SEQUENTIAL))
        self.config.props["interval_sec"] = self._normalize_interval_sec(self.config.props.get("interval_sec", 8))
        self.config.props["children"] = [
            copy.deepcopy(entry["config"].to_dict())
            for entry in self._children
        ]
        if self._children:
            first_cfg: WidgetConfig = self._children[0]["config"]
            self.config.props["item_w"] = int(first_cfg.grid_w)
            self.config.props["item_h"] = int(first_cfg.grid_h)

    def _update_ui_state(self) -> None:
        has_children = bool(self._children)
        self._stack.setVisible(has_children)
        self._empty_hint.setVisible(not has_children)

        page_count = max(1, len(self._children))
        current = int(self.config.props.get("active_index", self._stack.currentIndex()) or 0)

        self._syncing_index = True
        self._pager.setVisible(has_children)
        self._pager.setVisibleNumber(min(8, page_count))
        self._pager.setPageNumber(page_count)
        if has_children:
            idx = max(0, min(current, len(self._children) - 1))
            self._stack.setCurrentIndex(idx)
            self._pager.setCurrentIndex(idx)
            self.config.props["active_index"] = idx
        else:
            self.config.props["active_index"] = 0
        self._syncing_index = False

    def _set_current_index(self, index: int, *, restart_timer: bool = True) -> None:
        if not self._children:
            self.config.props["active_index"] = 0
            return

        idx = max(0, min(int(index), len(self._children) - 1))
        self._syncing_index = True
        self._stack.setCurrentIndex(idx)
        self._pager.setCurrentIndex(idx)
        self._syncing_index = False
        self.config.props["active_index"] = idx
        if restart_timer:
            self._restart_timer()

    def _restart_timer(self) -> None:
        if len(self._children) <= 1:
            self._timer.stop()
            return
        interval_ms = self._normalize_interval_sec(self.config.props.get("interval_sec", 8)) * 1000
        self._timer.start(interval_ms)

    def _advance(self) -> None:
        count = len(self._children)
        if count <= 1:
            return

        current = int(self.config.props.get("active_index", self._stack.currentIndex()) or 0)
        mode = self._normalize_mode(self.config.props.get("mode", _MODE_SEQUENTIAL))
        if mode == _MODE_RANDOM:
            choices = [i for i in range(count) if i != current]
            next_index = random.choice(choices) if choices else current
        else:
            next_index = (current + 1) % count

        self._set_current_index(next_index, restart_timer=False)

    def _on_pager_index_changed(self, index: int) -> None:
        if self._syncing_index:
            return
        self._set_current_index(index, restart_timer=True)

    def get_edit_widget(self):
        return _CarouselEditPanel(self.config.props, self.config)

    def apply_props(self, props: dict) -> None:
        mode = self._normalize_mode(props.get("mode", self.config.props.get("mode", _MODE_SEQUENTIAL)))
        interval_sec = self._normalize_interval_sec(props.get("interval_sec", self.config.props.get("interval_sec", 8)))

        self.config.props["mode"] = mode
        self.config.props["interval_sec"] = interval_sec

        self.config.grid_w = max(1, int(props.get("grid_w", self.config.grid_w)))
        self.config.grid_h = max(1, int(props.get("grid_h", self.config.grid_h)))

        self._sync_props_from_children()
        self._restart_timer()
        self.refresh()

    def _current_child(self) -> WidgetBase | None:
        if not self._children:
            return None
        idx = int(self.config.props.get("active_index", self._stack.currentIndex()) or 0)
        idx = max(0, min(idx, len(self._children) - 1))
        widget = self._children[idx].get("widget")
        return widget if isinstance(widget, WidgetBase) else None

    def _dialog_parent(self):
        host = self.services.get("fullscreen_window") if isinstance(self.services, dict) else None
        if isinstance(host, QWidget):
            try:
                _ = host.windowTitle()
                return host
            except RuntimeError:
                pass
        return self.window()

    def _edit_current_component(self) -> None:
        child = self._current_child()
        if child is None:
            return
        dlg = _ChildEditDialog(child, self._dialog_parent())
        dlg.exec()
        self._sync_props_from_children()
        self.refresh()

    def get_context_menu_actions(self):
        return [
            ("编辑组件", FIF.EDIT, self._edit_current_component),
        ]

    def try_add_widget_config(self, cfg: WidgetConfig) -> tuple[bool, str]:
        if cfg.widget_type == self.WIDGET_TYPE:
            return False, "轮播组件不支持嵌套轮播组件"

        reg = WidgetRegistry.instance()
        cls = reg.get(cfg.widget_type)
        if cls is None:
            return False, "该组件类型不可用"

        if self._children:
            first_cfg: WidgetConfig = self._children[0]["config"]
            target_w, target_h = int(first_cfg.grid_w), int(first_cfg.grid_h)
            if (int(cfg.grid_w), int(cfg.grid_h)) != (target_w, target_h):
                if not bool(getattr(cls, "RESIZABLE", True)):
                    return False, "尺寸不一致，且目标组件不支持自动调整大小"
                cfg.grid_w = target_w
                cfg.grid_h = target_h
        else:
            self.config.grid_w = max(1, int(cfg.grid_w))
            self.config.grid_h = max(1, int(cfg.grid_h))

        child = reg.create(cfg, self.services, self._stack)
        if child is None:
            return False, "无法创建该组件"

        self._children.append({"config": cfg, "widget": child})
        self._stack.addWidget(child)

        self._sync_props_from_children()
        self._update_ui_state()
        self._set_current_index(len(self._children) - 1, restart_timer=True)
        self.refresh()
        return True, ""

    def refresh(self) -> None:
        for entry in self._children:
            widget = entry.get("widget")
            if isinstance(widget, WidgetBase):
                widget.refresh()
        self._update_ui_state()

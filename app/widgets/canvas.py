"""小组件画布 —— 全屏区域内的可编辑网格布局"""
from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import Qt, QPoint, QSize, Slot, QTimer, QEvent, QRectF
from PySide6.QtGui import QPainter, QColor, QPen, QCursor, QPainterPath
from PySide6.QtWidgets import (
    QWidget, QLabel, QDialog, QFileDialog,
    QVBoxLayout, QHBoxLayout, QFrame,
)
from qfluentwidgets import (
    RoundMenu, Action, FluentIcon as FIF, MessageBox,
    PushButton, BodyLabel,
    CardWidget, SmoothScrollArea,
    InfoBar, InfoBarPosition,
)

from app.utils.fs import write_text_with_uac
from app.utils.logger import logger
from app.services.permission_service import PermissionService
from app.widgets.base_widget import WidgetBase, WidgetConfig
from app.widgets.registry import WidgetRegistry
from app.widgets.layout_store import WidgetLayoutStore


# ─────────────────────────────────────────────────────────────────
# 未知组件占位符（插件已卸载/禁用时显示）
# ─────────────────────────────────────────────────────────────────

class _UnknownWidget(WidgetBase):
    """当对应插件未加载时显示的占位小组件。

    - 可删除，用户可以主动移除
    - 显示原始 widget_type 和小提示
    """
    WIDGET_TYPE = "__unknown__"   # 不会注册到全局注册表
    WIDGET_NAME = "未知组件"
    DELETABLE   = True
    MIN_W       = 1
    MIN_H       = 1

    def __init__(self, config: WidgetConfig, services, parent=None):
        super().__init__(config, services, parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        self._lbl = QLabel()
        self._lbl.setWordWrap(True)
        self._lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl.setStyleSheet("color:#666; font-size:12px; background:transparent;")
        layout.addWidget(self._lbl)
        self.refresh()

    def refresh(self) -> None:
        wtype = self.config.widget_type
        self._lbl.setText(
            f"⚠ 未知组件\n({wtype})\n\n所属插件未加载\n\u53f3键可删除"
        )


# ─────────────────────────────────────────────────────────────
# 编辑弹窗
# ─────────────────────────────────────────────────────────────

class _EditDialog(MessageBox):
    """通用属性编辑对话框，内嵌组件自定义的 edit_widget"""

    def __init__(self, widget: WidgetBase, parent=None):
        super().__init__(f"编辑 · {widget.WIDGET_NAME}", "", parent)
        self.yesButton.setText("保存")
        self.cancelButton.setText("取消")
        self.contentLabel.hide()
        self._widget = widget
        self._edit   = widget.get_edit_widget()

        if self._edit:
            self.textLayout.addWidget(self._edit)
        else:
            self.textLayout.addWidget(BodyLabel("此组件暂无可编辑属性。"))

    def accept(self) -> None:
        if self._edit and hasattr(self._edit, "collect_props"):
            self._widget.apply_props(self._edit.collect_props())
        super().accept()


# ─────────────────────────────────────────────────────────────
# 组件类型 → 图标映射
# ─────────────────────────────────────────────────────────────
_TYPE_ICONS: dict[str, FIF] = {
    "clock":      FIF.HISTORY,
    "calendar":   FIF.CALENDAR,
    "countdown":  FIF.STOP_WATCH,
    "countup":    FIF.STOP_WATCH,
    "timer_list": FIF.STOP_WATCH,
    "alarm_list": FIF.RINGER,
    "world_time": FIF.GLOBE,
    "text":       FIF.FONT,
    "marquee_text": FIF.FONT,
    "carousel":   FIF.LAYOUT,
    "image":      FIF.PHOTO,
    "calculator": FIF.APPLICATION,
    "study_schedule.current_item": FIF.HISTORY,
    "study_schedule.time_period": FIF.STOP_WATCH,
    "study_schedule.remaining_time": FIF.STOP_WATCH,
    "study_schedule.today_schedule": FIF.CALENDAR,
    "study_schedule.next_item": FIF.HISTORY,
    "volume_detector": FIF.MEGAPHONE,
}


class _WidgetCard(CardWidget):
    """可点击的组件选择卡片"""

    def __init__(self, type_id: str, name: str, icon: FIF, on_click, parent=None):
        super().__init__(parent)
        self._type_id  = type_id
        self._on_click = on_click
        self.setFixedHeight(56)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        h = QHBoxLayout(self)
        h.setContentsMargins(14, 0, 14, 0)
        h.setSpacing(12)

        icon_lbl = QLabel()
        icon_lbl.setPixmap(icon.icon().pixmap(QSize(20, 20)))
        icon_lbl.setFixedSize(24, 24)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet("background: transparent;")

        name_lbl = BodyLabel(name)

        chevron = QLabel("›")
        chevron.setStyleSheet(
            "color:rgba(128,128,128,160); font-size:18px; background:transparent;"
        )
        chevron.setFixedWidth(16)
        chevron.setAlignment(Qt.AlignmentFlag.AlignCenter)

        h.addWidget(icon_lbl)
        h.addWidget(name_lbl, 1)
        h.addWidget(chevron)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_click(self._type_id)
        super().mouseReleaseEvent(event)


# ─────────────────────────────────────────────────────────────
# "添加组件"弹窗
# ─────────────────────────────────────────────────────────────

class _AddWidgetDialog(MessageBox):
    """从注册表列出所有可用类型，让用户选择"""

    def __init__(self, parent=None):
        super().__init__("添加组件", "", parent)
        self.yesButton.hide()
        self.cancelButton.setText("取消")
        self.contentLabel.hide()
        self.selected_type: str | None = None

        # 可滚动卡片列表
        scroll = SmoothScrollArea()
        scroll.setFixedSize(360, 360)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(0, 4, 0, 4)
        inner_layout.setSpacing(4)
        scroll.setWidget(inner)
        scroll.enableTransparentBackground()
        self.textLayout.addWidget(scroll)

        reg = WidgetRegistry.instance()
        for type_id, name in reg.all_types():
            icon = _TYPE_ICONS.get(type_id, FIF.APPLICATION)
            card = _WidgetCard(type_id, name, icon, self._on_select, inner)
            inner_layout.addWidget(card)
        inner_layout.addStretch()

    def _on_select(self, type_id: str) -> None:
        self.selected_type = type_id
        self.accept()


class _CanvasServiceProxy(dict):
    """为插件组件提供按需解析的服务视图。

    - 仅暴露当前组件所属插件有权访问的宿主服务
    - 仅注入该插件自己注册的画布共享服务
    - 运行期权限变化后，后续 `get()` / 索引访问会自动看到最新结果
    """

    def __init__(self, base_services: dict[str, Any], plugin_manager, widget_type: str):
        super().__init__()
        self._base_services = base_services
        self._plugin_manager = plugin_manager
        self._widget_type = widget_type

    def _snapshot(self) -> dict[str, Any]:
        if self._plugin_manager is not None and hasattr(self._plugin_manager, "build_widget_services"):
            try:
                return self._plugin_manager.build_widget_services(self._widget_type, self._base_services)
            except Exception:
                pass
        return dict(self._base_services)

    def __getitem__(self, key):
        return self._snapshot()[key]

    def get(self, key, default=None):
        return self._snapshot().get(key, default)

    def __contains__(self, key):
        return key in self._snapshot()

    def __iter__(self):
        return iter(self._snapshot())

    def __len__(self):
        return len(self._snapshot())

    def keys(self):
        return self._snapshot().keys()

    def items(self):
        return self._snapshot().items()

    def values(self):
        return self._snapshot().values()

    def copy(self):
        return self._snapshot()


# ─────────────────────────────────────────────────────────────
# WidgetItem —— 单个组件的可拖拽包装器
# ─────────────────────────────────────────────────────────────

class WidgetItem(QWidget):
    """将 WidgetBase 嵌入网格，编辑模式下可拖拽并右键操作"""

    def __init__(
        self,
        widget: WidgetBase,
        canvas: "WidgetCanvas",
    ):
        super().__init__(canvas)
        self._widget = widget
        self._canvas = canvas
        self._dragging = False
        self._drag_offset = QPoint()
        self._drag_items: list[WidgetItem] = []
        self._drag_start_positions: dict[WidgetItem, QPoint] = {}
        self._drag_start_grids: dict[WidgetItem, tuple[int, int]] = {}
        self._drag_active_start = QPoint()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(widget)

        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

        self._update_geometry()

    # ------------------------------------------------------------------ #

    @property
    def config(self) -> WidgetConfig:
        return self._widget.config

    def refresh(self) -> None:
        self._widget.refresh()

    def _update_geometry(self) -> None:
        c = self.config
        cs = self._canvas.cell_size
        self.setGeometry(c.grid_x * cs, c.grid_y * cs,
                         c.grid_w * cs, c.grid_h * cs)

    # ------------------------------------------------------------------ #
    # 右键菜单
    # ------------------------------------------------------------------ #

    def _show_context_menu(self, pos: QPoint) -> None:
        menu = RoundMenu(parent=self)

        # 1. 组件自定义菜单项
        custom_actions = self._widget.get_context_menu_actions()
        for text, icon, callback in custom_actions:
            if icon:
                menu.addAction(Action(icon, text, triggered=callback))
            else:
                menu.addAction(Action(FIF.APPLICATION, text, triggered=callback))

        if custom_actions:
            menu.addSeparator()

        # 2. 编辑
        has_edit = self._widget.get_edit_widget() is not None
        if has_edit:
            edit_text = "编辑轮播组件" if bool(getattr(self._widget, "is_carousel_widget", lambda: False)()) else "编辑"
            menu.addAction(Action(FIF.EDIT, edit_text, triggered=self._open_edit))

        # 3. 分离为置顶窗口
        menu.addAction(Action(FIF.PIN, "分离为窗口", triggered=self._detach_window))

        # 4. 组件组操作
        if self._canvas._is_item_grouped(self):
            menu.addAction(Action(FIF.LAYOUT, "拆分组件组为窗口", triggered=self._request_split_group_to_window))
            menu.addAction(Action(FIF.CANCEL, "解除组件组", triggered=self._request_ungroup))

        # 5. 删除
        if self._widget.DELETABLE:
            menu.addSeparator()
            menu.addAction(Action(FIF.DELETE, "删除", triggered=self._request_delete))

        if not menu.actions():
            return
        menu.exec(self.mapToGlobal(pos))

    def _open_edit(self) -> None:
        if not self._canvas._ensure_access("layout.edit_widget", "编辑组件设置"):
            return
        dlg = _EditDialog(self._widget, self._canvas)
        dlg.exec()
        self._update_geometry()  # 编辑可能改变大小
        self._canvas._save_layout()

    def _request_delete(self) -> None:
        if not self._canvas._ensure_access("layout.delete_widget", "删除组件"):
            return
        self._canvas._remove_item(self)

    def _request_ungroup(self) -> None:
        if not self._canvas._ensure_access("layout.edit_widget", "解除组件组"):
            return
        self._canvas._ungroup_item(self)

    def _request_split_group_to_window(self) -> None:
        if not self._canvas._ensure_access("layout.edit_widget", "拆分组件组"):
            return
        self._canvas._split_group_to_window(self, self.mapToGlobal(QPoint(0, 0)))

    def _detach_window(self) -> None:
        """将组件分离为置顶窗口"""
        if not self._canvas._ensure_access("layout.edit_widget", "分离组件为窗口"):
            return
        self._canvas._detach_item_to_window(self, self.mapToGlobal(QPoint(0, 0)))

    # ------------------------------------------------------------------ #
    # 拖拽（仅编辑模式）
    # ------------------------------------------------------------------ #

    def mousePressEvent(self, event) -> None:
        if self._canvas.edit_mode and event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_offset = event.position().toPoint()
            self._drag_items = self._canvas._group_members(self)
            self._drag_start_positions = {
                item: QPoint(item.x(), item.y())
                for item in self._drag_items
            }
            self._drag_start_grids = {
                item: (item.config.grid_x, item.config.grid_y)
                for item in self._drag_items
            }
            self._drag_active_start = self._drag_start_positions.get(self, QPoint(self.x(), self.y()))

            for item in self._drag_items:
                item.raise_()
            self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._dragging:
            new_pos = self.mapToParent(event.position().toPoint() - self._drag_offset)
            desired_dx = new_pos.x() - self._drag_active_start.x()
            desired_dy = new_pos.y() - self._drag_active_start.y()
            dx, dy = self._canvas._clamp_group_drag_delta(
                self._drag_items,
                self._drag_start_positions,
                desired_dx,
                desired_dy,
            )
            for item in self._drag_items:
                start = self._drag_start_positions.get(item)
                if start is None:
                    continue
                item.move(start.x() + dx, start.y() + dy)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._dragging:
            self._dragging = False
            self.unsetCursor()
            self._snap_to_grid()
            absorbed = self._canvas._try_absorb_overlapping_into_carousel(self)
            if not absorbed:
                self._canvas._merge_overlaps_for_item(self)
            self._canvas._save_layout()
            self._drag_items.clear()
            self._drag_start_positions.clear()
            self._drag_start_grids.clear()
        super().mouseReleaseEvent(event)

    def _snap_to_grid(self) -> None:
        drag_items = self._drag_items if self._drag_items else [self]
        start_grids = self._drag_start_grids
        if not start_grids:
            start_grids = {self: (self.config.grid_x, self.config.grid_y)}
        self._canvas._snap_drag_items_to_grid(drag_items, start_grids, self)

    # ------------------------------------------------------------------ #
    # 绘制编辑模式下的边框高亮
    # ------------------------------------------------------------------ #

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._canvas.edit_mode:
            p = QPainter(self)
            if self._canvas._is_item_grouped(self):
                p.setPen(QPen(QColor(114, 191, 255, 200), 2, Qt.PenStyle.DashLine))
            else:
                p.setPen(QPen(QColor(255, 255, 255, 120), 2))
            p.drawRect(1, 1, self.width() - 2, self.height() - 2)


# ─────────────────────────────────────────────────────────────
# WidgetCanvas —— 主画布
# ─────────────────────────────────────────────────────────────

class WidgetCanvas(QWidget):
    """
    全屏网格画布。

    - edit_mode=False：组件正常展示，不可拖拽
    - edit_mode=True ：显示网格线，组件可拖拽，
                       右上角出现"完成"和"添加"按钮
    """

    def __init__(
        self,
        page_id: str,
        services: dict[str, Any],
        plugin_manager=None,
        parent=None,
        lazy_load: bool = False,
    ):
        super().__init__(parent)
        self.setAutoFillBackground(False)
        self.page_id   = page_id
        self._plugin_manager = plugin_manager
        self._base_services = dict(services)
        self.services  = dict(services)
        permission_svc = self._base_services.get("permission_service")
        self._permission_service = permission_svc if isinstance(permission_svc, PermissionService) else None
        self.edit_mode = False
        self._lazy_load = lazy_load
        self._pending_configs: list[WidgetConfig] = []
        self._batch_timer: QTimer | None = None
        self._save_after_lazy_load = False
        self._lazy_batch_size = 3  # 每批次创建少量组件，避免首屏卡顿
        self._pending_default_clock_init = False

        self._store = WidgetLayoutStore()
        self._items: list[WidgetItem] = []

        self._build_toolbar()
        if self._lazy_load:
            self._load_layout_lazy()
        else:
            self._load_layout()

        # 监听格子大小变更信号，实时重排布局
        from app.services.settings_service import SettingsService
        SettingsService.instance().cell_size_changed.connect(self._on_cell_size_changed)

        # 当插件被卸载时，将其小组件替换为未知占位符
        if plugin_manager is not None:
            plugin_manager.pluginUnloaded.connect(
                lambda _pid: self.refresh_unknown_widgets()
            )

    # ------------------------------------------------------------------ #
    # 工具栏（编辑态）
    # ------------------------------------------------------------------ #

    def _ensure_access(self, feature_key: str, reason: str) -> bool:
        if self._permission_service is None:
            return True
        ok = self._permission_service.ensure_access(
            feature_key,
            parent=self.window(),
            reason=reason,
        )
        if ok:
            return True
        deny_reason = self._permission_service.get_last_denied_reason(feature_key)
        InfoBar.warning(
            "权限不足",
            deny_reason or "无法执行该操作。",
            duration=2500,
            position=InfoBarPosition.BOTTOM,
            parent=self.window(),
        )
        return False

    def _build_toolbar(self) -> None:
        self._toolbar = QFrame(self)
        self._toolbar.setObjectName("canvasToolBar")
        self._toolbar.setStyleSheet(
            "QFrame#canvasToolBar{"
            "background:rgba(10,10,10,200);"
            "border-top:1px solid rgba(255,255,255,20);}"
        )
        tb_layout = QHBoxLayout(self._toolbar)
        tb_layout.setContentsMargins(16, 0, 16, 0)
        tb_layout.setSpacing(8)

        self._add_btn = PushButton(FIF.ADD, "添加组件")
        self._add_btn.clicked.connect(self._on_add_widget)

        self._import_btn = PushButton(FIF.DOWNLOAD, "导入布局")
        self._import_btn.clicked.connect(self._on_import_layout)

        self._export_btn = PushButton(FIF.SHARE, "导出布局")
        self._export_btn.clicked.connect(self._on_export_layout)

        tb_layout.addStretch()
        tb_layout.addWidget(self._import_btn)
        tb_layout.addWidget(self._export_btn)
        tb_layout.addWidget(self._add_btn)
        self._toolbar.hide()

    # ------------------------------------------------------------------ #
    # 编辑模式切换
    # ------------------------------------------------------------------ #

    def enter_edit_mode(self) -> None:
        if not self._ensure_access("layout.edit", "进入布局编辑模式"):
            return
        self.edit_mode = True
        self._toolbar.raise_()
        self._toolbar.show()
        self._toolbar.setGeometry(0, self.height() - 52, self.width(), 52)
        self.update()
        for item in self._items:
            item.update()

    def leave_edit_mode(self) -> None:
        self.edit_mode = False
        self._toolbar.hide()
        self.update()
        for item in self._items:
            item.update()

    # ------------------------------------------------------------------ #
    # 布局加载 / 保存
    # ------------------------------------------------------------------ #

    def _services_for_widget(self, widget_type: str):
        if self._plugin_manager is not None:
            return _CanvasServiceProxy(self._base_services, self._plugin_manager, widget_type)
        return dict(self._base_services)

    def _stop_batch_loader(self) -> None:
        if self._batch_timer is not None:
            self._batch_timer.stop()
        self._pending_configs.clear()
        self._save_after_lazy_load = False

    def _clear_items(self) -> None:
        for it in self._items:
            it.deleteLater()
        self._items.clear()

    def _active_detached_windows(self) -> list["DetachedWidgetWindow"]:
        return [
            win
            for win in list(DetachedWidgetWindow._instances)
            if win.page_id == self.page_id
        ]

    def _close_detached_windows_for_page(self) -> None:
        for win in self._active_detached_windows():
            win.close_for_reload()

    def _create_widget_from_config(self, cfg: WidgetConfig) -> WidgetBase:
        reg = WidgetRegistry.instance()
        widget = reg.create(cfg, self._services_for_widget(cfg.widget_type), self)
        if widget is None:
            widget = _UnknownWidget(cfg, self._services_for_widget(cfg.widget_type), self)
            widget.refresh()
        return widget

    def _create_item_from_config(self, cfg: WidgetConfig) -> None:
        widget = self._create_widget_from_config(cfg)
        item = WidgetItem(widget, self)
        item.show()
        self._items.append(item)

    def _build_detached_window(
        self,
        entries: list[dict[str, Any]],
        *,
        origin_x: int,
        origin_y: int,
    ) -> "DetachedWidgetWindow" | None:
        if not entries:
            return None
        detached = DetachedWidgetWindow(
            entries=entries,
            cell_size=self.cell_size,
            page_id=self.page_id,
            parent=self.window(),
        )
        detached.set_canvas_callbacks(
            merge_callback=self._on_detached_window_merge_requested,
            moved_callback=self._on_detached_window_moved,
            delete_callback=self._on_detached_window_delete_requested,
            split_callback=self._on_detached_window_split_requested,
        )
        cs = max(1, self.cell_size)
        detached.move(int(origin_x) * cs, int(origin_y) * cs)
        detached.show()
        return detached

    def _restore_detached_windows(self) -> None:
        records = self._store.get_detached(self.page_id)
        if not records:
            return

        restored = 0
        for record in records:
            origin_x = int(record.get("origin_x", 0))
            origin_y = int(record.get("origin_y", 0))
            raw_entries = record.get("entries", [])
            if not isinstance(raw_entries, list):
                continue

            entries: list[dict[str, Any]] = []
            for raw_entry in raw_entries:
                if not isinstance(raw_entry, dict):
                    continue
                widget_data = raw_entry.get("widget")
                if not isinstance(widget_data, dict):
                    continue

                cfg = WidgetConfig.from_dict(widget_data)
                widget = self._create_widget_from_config(cfg)
                entries.append(
                    {
                        "config": cfg,
                        "widget": widget,
                        "offset_x": int(raw_entry.get("offset_x", 0)),
                        "offset_y": int(raw_entry.get("offset_y", 0)),
                    }
                )

            if not entries:
                continue

            if self._build_detached_window(entries, origin_x=origin_x, origin_y=origin_y) is not None:
                restored += 1

        if restored:
            logger.info("[画布] 页面 {} 恢复分离窗口 {} 个", self.page_id, restored)

    def _detached_records_for_store(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for win in self._active_detached_windows():
            record = win.to_layout_record()
            if record and isinstance(record.get("entries"), list) and record["entries"]:
                records.append(record)
        return records

    def _grid_dimensions(self) -> tuple[int, int]:
        cs = self.cell_size
        if cs <= 0:
            return 0, 0
        return self.width() // cs, self.height() // cs

    def _default_grid_dimensions(self) -> tuple[int, int]:
        """返回用于默认布局计算的网格尺寸。"""
        return self._grid_dimensions()

    def _build_default_clock_layout(self) -> list[WidgetConfig]:
        """为新页面构建默认布局：单个居中时钟。"""
        reg = WidgetRegistry.instance()
        clock_cls = reg.get("clock")

        min_w = int(getattr(clock_cls, "MIN_W", 2)) if clock_cls else 2
        min_h = int(getattr(clock_cls, "MIN_H", 2)) if clock_cls else 2
        grid_w = int(getattr(clock_cls, "DEFAULT_W", 5)) if clock_cls else 5
        grid_h = int(getattr(clock_cls, "DEFAULT_H", 3)) if clock_cls else 3

        cols, rows = self._default_grid_dimensions()
        if cols < min_w or rows < min_h:
            return []

        grid_w = max(min_w, min(grid_w, cols))
        grid_h = max(min_h, min(grid_h, rows))
        grid_x = max(0, (cols - grid_w) // 2)
        grid_y = max(0, (rows - grid_h) // 2)

        return [
            WidgetConfig(
                widget_type="clock",
                grid_x=grid_x,
                grid_y=grid_y,
                grid_w=grid_w,
                grid_h=grid_h,
                props={
                    "align": "center",
                    "show_time": True,
                    "show_date": True,
                    "show_offset": True,
                    "show_diff": True,
                },
            )
        ]

    def _load_or_create_layout_configs(self) -> list[WidgetConfig]:
        """读取布局；若是新页面则注入默认居中时钟。"""
        self._store.reload()
        self._pending_default_clock_init = False
        configs = self._store.get(self.page_id)
        if configs:
            return configs

        # 已有持久化记录（即使为空）视为用户明确布局，不做默认注入。
        if self._store.has_page(self.page_id):
            logger.debug("[画布] 页面 {} 已存在空布局记录，跳过默认时钟注入", self.page_id)
            return configs

        defaults = self._build_default_clock_layout()
        if not defaults:
            # 尺寸未就绪，延后到 resizeEvent 初始化。
            self._pending_default_clock_init = True
            logger.debug("[画布] 页面 {} 尺寸未就绪，延后初始化默认时钟", self.page_id)
            return []

        self._store.save(self.page_id, defaults)
        cfg = defaults[0]
        logger.info(
            "[画布] 页面 {} 自动初始化默认时钟：x={}, y={}, w={}, h={}",
            self.page_id,
            cfg.grid_x,
            cfg.grid_y,
            cfg.grid_w,
            cfg.grid_h,
        )
        return defaults

    @staticmethod
    def _new_group_id() -> str:
        return str(uuid.uuid4())

    def _group_members(self, item: WidgetItem) -> list[WidgetItem]:
        group_id = str(item.config.group_id or "").strip()
        if not group_id:
            return [item]
        members = [it for it in self._items if str(it.config.group_id or "").strip() == group_id]
        return members or [item]

    def _is_item_grouped(self, item: WidgetItem) -> bool:
        return len(self._group_members(item)) > 1

    def _normalize_group(self, group_id: str) -> None:
        gid = str(group_id or "").strip()
        if not gid:
            return
        members = [it for it in self._items if str(it.config.group_id or "").strip() == gid]
        if len(members) <= 1:
            for it in members:
                it.config.group_id = ""

    def _ungroup_item(self, item: WidgetItem) -> None:
        if not self._ensure_access("layout.edit_widget", "解除组件组"):
            return
        members = self._group_members(item)
        if len(members) <= 1:
            item.config.group_id = ""
            self._save_layout()
            return
        for member in members:
            member.config.group_id = ""
        self._save_layout()

    def _split_group_to_window(self, item: WidgetItem, global_pos: QPoint) -> None:
        if not self._ensure_access("layout.edit_widget", "拆分组件组"):
            return
        members = self._group_members(item)
        if not members:
            return
        if len(members) == 1:
            self._detach_item_to_window(item, global_pos)
            return

        cs = max(1, self.cell_size)
        origin_x = round(global_pos.x() / cs)
        origin_y = round(global_pos.y() / cs)

        min_grid_x = min(member.config.grid_x for member in members)
        min_grid_y = min(member.config.grid_y for member in members)

        entries: list[dict[str, Any]] = []
        for member in members:
            widget = getattr(member, "_widget", None)
            if widget is None:
                continue
            entries.append(
                {
                    "config": widget.config,
                    "widget": widget,
                    "offset_x": int(member.config.grid_x) - int(min_grid_x),
                    "offset_y": int(member.config.grid_y) - int(min_grid_y),
                }
            )

        if not entries:
            return

        for member in members:
            if member in self._items:
                self._items.remove(member)
            member.hide()
            member.setParent(None)
            member.deleteLater()

        self._build_detached_window(
            entries,
            origin_x=origin_x,
            origin_y=origin_y,
        )
        self._save_layout()

    def _try_add_item_to_carousel(self, source_item: WidgetItem, carousel_item: WidgetItem) -> bool:
        target_widget = getattr(carousel_item, "_widget", None)
        source_cfg = copy.deepcopy(source_item.config)
        if target_widget is None or not hasattr(target_widget, "try_add_widget_config"):
            return False

        added, reason = target_widget.try_add_widget_config(source_cfg)
        if not added:
            if reason:
                InfoBar.warning(
                    "无法加入轮播组件",
                    str(reason),
                    duration=2500,
                    position=InfoBarPosition.BOTTOM,
                    parent=self.window(),
                )
            return False

        self._remove_item(source_item, save=False)
        carousel_item._update_geometry()
        carousel_item.update()
        return True

    def _try_absorb_overlapping_into_carousel(self, moving_item: WidgetItem) -> bool:
        if moving_item not in self._items:
            return False
        if self._is_item_grouped(moving_item):
            return False

        moving_widget = getattr(moving_item, "_widget", None)
        moving_is_carousel = bool(
            moving_widget is not None
            and hasattr(moving_widget, "is_carousel_widget")
            and moving_widget.is_carousel_widget()
        )

        src_rect = (
            moving_item.config.grid_x,
            moving_item.config.grid_y,
            moving_item.config.grid_w,
            moving_item.config.grid_h,
        )

        for candidate in self._items:
            if candidate is moving_item:
                continue
            cfg = candidate.config
            candidate_rect = (cfg.grid_x, cfg.grid_y, cfg.grid_w, cfg.grid_h)
            if not self._grid_rects_overlap(src_rect, candidate_rect):
                continue

            candidate_widget = getattr(candidate, "_widget", None)
            candidate_is_carousel = bool(
                candidate_widget is not None
                and hasattr(candidate_widget, "is_carousel_widget")
                and candidate_widget.is_carousel_widget()
            )

            if moving_is_carousel and not candidate_is_carousel:
                if self._try_add_item_to_carousel(candidate, moving_item):
                    return True
            elif candidate_is_carousel and not moving_is_carousel:
                if self._try_add_item_to_carousel(moving_item, candidate):
                    return True

        return False

    def _clamp_group_drag_delta(
        self,
        drag_items: list[WidgetItem],
        start_positions: dict[WidgetItem, QPoint],
        desired_dx: int,
        desired_dy: int,
    ) -> tuple[int, int]:
        if not drag_items:
            return 0, 0

        dx_min = -10**9
        dx_max = 10**9
        dy_min = -10**9
        dy_max = 10**9

        for item in drag_items:
            start = start_positions.get(item)
            if start is None:
                continue
            dx_min = max(dx_min, -start.x())
            dx_max = min(dx_max, self.width() - item.width() - start.x())
            dy_min = max(dy_min, -start.y())
            dy_max = min(dy_max, self.height() - item.height() - start.y())

        dx = max(dx_min, min(desired_dx, dx_max))
        dy = max(dy_min, min(desired_dy, dy_max))
        return int(dx), int(dy)

    def _snap_drag_items_to_grid(
        self,
        drag_items: list[WidgetItem],
        start_grids: dict[WidgetItem, tuple[int, int]],
        anchor: WidgetItem,
    ) -> None:
        if not drag_items:
            return

        cs = self.cell_size
        cols, rows = self._grid_dimensions()
        if cs <= 0 or cols <= 0 or rows <= 0:
            for item in drag_items:
                item._update_geometry()
            return

        anchor_start = start_grids.get(anchor, (anchor.config.grid_x, anchor.config.grid_y))
        desired_anchor_x = round(anchor.x() / cs)
        desired_anchor_y = round(anchor.y() / cs)
        desired_dx = desired_anchor_x - anchor_start[0]
        desired_dy = desired_anchor_y - anchor_start[1]

        dx_min = -10**9
        dx_max = 10**9
        dy_min = -10**9
        dy_max = 10**9
        for item in drag_items:
            start_x, start_y = start_grids.get(item, (item.config.grid_x, item.config.grid_y))
            cfg = item.config
            dx_min = max(dx_min, -start_x)
            dx_max = min(dx_max, cols - cfg.grid_w - start_x)
            dy_min = max(dy_min, -start_y)
            dy_max = min(dy_max, rows - cfg.grid_h - start_y)

        dx = int(max(dx_min, min(desired_dx, dx_max)))
        dy = int(max(dy_min, min(desired_dy, dy_max)))

        for item in drag_items:
            start_x, start_y = start_grids.get(item, (item.config.grid_x, item.config.grid_y))
            item.config.grid_x = start_x + dx
            item.config.grid_y = start_y + dy
            item._update_geometry()

    @staticmethod
    def _grid_rects_overlap(a, b) -> bool:
        ax, ay, aw, ah = a
        bx, by, bw, bh = b
        return not (
            ax + aw <= bx
            or bx + bw <= ax
            or ay + ah <= by
            or by + bh <= ay
        )

    def _merge_overlaps_for_item(self, moving_item: WidgetItem) -> int:
        """若开启重叠合并开关，重叠后将组件自动编组。"""
        from app.services.settings_service import SettingsService

        if not SettingsService.instance().widget_canvas_overlap_group_enabled:
            return 0
        if moving_item not in self._items:
            return 0

        moving_group = self._group_members(moving_item)
        moving_group_set = set(moving_group)

        overlapped_items: set[WidgetItem] = set()
        for src_item in moving_group:
            src = src_item.config
            src_rect = (src.grid_x, src.grid_y, src.grid_w, src.grid_h)
            for item in self._items:
                if item in moving_group_set:
                    continue
                cfg = item.config
                occupied = (cfg.grid_x, cfg.grid_y, cfg.grid_w, cfg.grid_h)
                if self._grid_rects_overlap(src_rect, occupied):
                    overlapped_items.add(item)

        if not overlapped_items:
            return 0

        group_candidates = list(moving_group_set | overlapped_items)
        existing_group_ids = sorted({
            str(item.config.group_id or "").strip()
            for item in group_candidates
            if str(item.config.group_id or "").strip()
        })
        final_group_id = existing_group_ids[0] if existing_group_ids else self._new_group_id()
        for item in group_candidates:
            item.config.group_id = final_group_id

        moving_item.raise_()
        moving_item.update()
        for item in overlapped_items:
            item.update()
        return len(overlapped_items)

    def _can_place_widget(self, grid_x: int, grid_y: int, grid_w: int, grid_h: int) -> bool:
        cols, rows = self._grid_dimensions()
        if grid_w <= 0 or grid_h <= 0 or cols <= 0 or rows <= 0:
            return False
        if grid_x < 0 or grid_y < 0:
            return False
        if grid_x + grid_w > cols or grid_y + grid_h > rows:
            return False

        target = (grid_x, grid_y, grid_w, grid_h)
        for item in self._items:
            cfg = item.config
            occupied = (cfg.grid_x, cfg.grid_y, cfg.grid_w, cfg.grid_h)
            if self._grid_rects_overlap(target, occupied):
                return False
        return True

    def _find_available_slot(self, grid_w: int, grid_h: int) -> tuple[int, int] | None:
        cols, rows = self._grid_dimensions()
        if cols <= 0 or rows <= 0 or grid_w > cols or grid_h > rows:
            return None
        for y in range(max(0, rows - grid_h + 1)):
            for x in range(max(0, cols - grid_w + 1)):
                if self._can_place_widget(x, y, grid_w, grid_h):
                    return x, y
        return None

    def _default_widget_size_for_canvas(self, widget_cls) -> tuple[int, int] | None:
        cols, rows = self._grid_dimensions()
        if cols < widget_cls.MIN_W or rows < widget_cls.MIN_H:
            return None
        grid_w = max(widget_cls.MIN_W, min(widget_cls.DEFAULT_W, cols))
        grid_h = max(widget_cls.MIN_H, min(widget_cls.DEFAULT_H, rows))
        return grid_w, grid_h

    def _resolve_new_widget_placement(self, widget_cls) -> tuple[int, int, int, int] | None:
        from app.services.settings_service import SettingsService

        size = self._default_widget_size_for_canvas(widget_cls)
        if size is None:
            return None
        grid_w, grid_h = size

        settings = SettingsService.instance()
        auto_fill = settings.widget_auto_fill_gap_enabled
        prevent_overflow = settings.widget_prevent_new_overflow_enabled

        if not auto_fill:
            return 0, 0, grid_w, grid_h

        cols, rows = self._grid_dimensions()
        max_w = min(widget_cls.DEFAULT_W, cols)
        max_h = min(widget_cls.DEFAULT_H, rows)
        for try_h in range(max_h, widget_cls.MIN_H - 1, -1):
            for try_w in range(max_w, widget_cls.MIN_W - 1, -1):
                pos = self._find_available_slot(try_w, try_h)
                if pos is not None:
                    return pos[0], pos[1], try_w, try_h

        if prevent_overflow:
            return None
        return 0, 0, grid_w, grid_h

    def _load_layout(self) -> None:
        self._stop_batch_loader()
        self._close_detached_windows_for_page()
        self._clear_items()

        configs = self._load_or_create_layout_configs()

        for cfg in configs:
            self._create_item_from_config(cfg)

        self._restore_detached_windows()

    def _start_lazy_load(self, configs: list[WidgetConfig], save_after: bool = False) -> None:
        self._stop_batch_loader()
        self._close_detached_windows_for_page()
        self._clear_items()
        self._pending_configs = list(configs)
        self._save_after_lazy_load = save_after
        if not self._pending_configs:
            self._restore_detached_windows()
            if save_after:
                self._save_layout()
            return
        if self._batch_timer is None:
            self._batch_timer = QTimer(self)
            self._batch_timer.timeout.connect(self._load_batch_step)
        self._batch_timer.start(0)

    def _load_layout_lazy(self) -> None:
        configs = self._load_or_create_layout_configs()
        self._start_lazy_load(configs, save_after=False)

    def _load_batch_step(self) -> None:
        created = 0
        while self._pending_configs and created < self._lazy_batch_size:
            cfg = self._pending_configs.pop(0)
            self._create_item_from_config(cfg)
            created += 1

        if self._pending_configs:
            return

        if self._batch_timer is not None:
            self._batch_timer.stop()
        self._restore_detached_windows()
        if self._save_after_lazy_load:
            self._save_layout()
            self._save_after_lazy_load = False
        self.refresh_all()

    def _save_layout(self) -> None:
        self._store.save_with_detached(
            self.page_id,
            [it.config for it in self._items],
            self._detached_records_for_store(),
        )

    # ------------------------------------------------------------------ #
    # 添加 / 删除组件
    # ------------------------------------------------------------------ #

    def _on_add_widget(self) -> None:
        if not self._ensure_access("layout.add_widget", "添加组件"):
            return
        dlg = _AddWidgetDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        type_id = dlg.selected_type
        if not type_id:
            return
        reg = WidgetRegistry.instance()
        cls = reg.get(type_id)
        if not cls:
            return
        placement = self._resolve_new_widget_placement(cls)
        if placement is None:
            cols, rows = self._grid_dimensions()
            InfoBar.warning(
                "无法放置组件",
                f"当前完整网格仅 {cols} × {rows}，且已启用阻止溢出，无法放置「{cls.WIDGET_NAME}」。",
                duration=3500,
                position=InfoBarPosition.BOTTOM,
                parent=self.window(),
            )
            return
        grid_x, grid_y, grid_w, grid_h = placement
        cfg = WidgetConfig(
            widget_type=type_id,
            grid_x=grid_x, grid_y=grid_y,
            grid_w=grid_w, grid_h=grid_h,
        )
        widget = reg.create(cfg, self._services_for_widget(cfg.widget_type), self)
        if widget:
            item = WidgetItem(widget, self)
            item.show()
            self._items.append(item)
            self._save_layout()

    def _remove_item(self, item: WidgetItem, *, save: bool = True) -> None:
        if item not in self._items:
            return
        old_group_id = str(item.config.group_id or "").strip()
        widget = getattr(item, "_widget", None)
        self._items.remove(item)
        if widget is not None:
            try:
                widget.deleteLater()
            except Exception:
                pass
        item.deleteLater()
        self._normalize_group(old_group_id)
        if save:
            self._save_layout()

    def _detach_item_to_window(self, item: WidgetItem, global_pos: QPoint) -> None:
        """从画布分离组件并创建分离窗口。"""
        if not self._ensure_access("layout.edit_widget", "分离组件为窗口"):
            return
        if item not in self._items:
            return

        widget = getattr(item, "_widget", None)
        if widget is None:
            return

        old_group_id = str(item.config.group_id or "").strip()
        self._items.remove(item)
        item.hide()
        item.setParent(None)

        cs = max(1, self.cell_size)
        origin_x = round(global_pos.x() / cs)
        origin_y = round(global_pos.y() / cs)

        self._build_detached_window(
            [
                {
                    "config": widget.config,
                    "widget": widget,
                    "offset_x": 0,
                    "offset_y": 0,
                }
            ],
            origin_x=origin_x,
            origin_y=origin_y,
        )

        item.deleteLater()
        self._normalize_group(old_group_id)
        self._save_layout()

    def _clamp_config_to_canvas(self, cfg: WidgetConfig) -> None:
        cols, rows = self._grid_dimensions()
        if cols <= 0 or rows <= 0:
            return

        cfg.grid_w = max(1, min(int(cfg.grid_w), cols))
        cfg.grid_h = max(1, min(int(cfg.grid_h), rows))
        max_x = max(0, cols - cfg.grid_w)
        max_y = max(0, rows - cfg.grid_h)
        cfg.grid_x = max(0, min(int(cfg.grid_x), max_x))
        cfg.grid_y = max(0, min(int(cfg.grid_y), max_y))

    def _on_detached_window_merge_requested(self, detached: "DetachedWidgetWindow") -> None:
        if not self._ensure_access("layout.edit_widget", "合并分离窗口到画布"):
            return
        self._merge_detached_window_to_canvas(detached)

    def _on_detached_window_delete_requested(self, detached: "DetachedWidgetWindow") -> None:
        if not self._ensure_access("layout.delete_widget", "删除分离窗口中的组件"):
            return
        if detached not in self._active_detached_windows():
            return
        detached.close_for_delete()
        self._save_layout()

    def _on_detached_window_moved(self, detached: "DetachedWidgetWindow") -> None:
        if not self._merge_overlaps_for_detached_window(detached):
            self._save_layout()

    def _on_detached_window_split_requested(self, detached: "DetachedWidgetWindow") -> None:
        if not self._ensure_access("layout.edit_widget", "拆分分离窗口组件组"):
            return
        if detached not in self._active_detached_windows():
            return

        moved_entries = detached.take_entries_for_transfer()
        if not moved_entries:
            detached.close_for_reload()
            self._save_layout()
            return

        detached.close_for_reload()

        for entry in moved_entries:
            self._build_detached_window(
                [
                    {
                        "config": entry["config"],
                        "widget": entry["widget"],
                        "offset_x": 0,
                        "offset_y": 0,
                    }
                ],
                origin_x=int(entry["grid_x"]),
                origin_y=int(entry["grid_y"]),
            )

        self._save_layout()

    def _merge_detached_window_to_canvas(self, detached: "DetachedWidgetWindow") -> None:
        if detached not in self._active_detached_windows():
            return

        moved_entries = detached.take_entries_for_transfer()
        if not moved_entries:
            detached.close_for_reload()
            self._save_layout()
            return

        detached.close_for_reload()

        for entry in moved_entries:
            cfg: WidgetConfig = entry["config"]
            cfg.grid_x = int(entry["grid_x"])
            cfg.grid_y = int(entry["grid_y"])
            self._clamp_config_to_canvas(cfg)

            widget: WidgetBase = entry["widget"]
            widget.setParent(self)
            item = WidgetItem(widget, self)
            item.show()
            self._items.append(item)

        self._save_layout()

    def _merge_overlaps_for_detached_window(self, moving_window: "DetachedWidgetWindow") -> bool:
        from app.services.settings_service import SettingsService

        if not SettingsService.instance().widget_detached_overlap_merge_enabled:
            return False
        if moving_window not in self._active_detached_windows():
            return False

        moving_rect = moving_window.grid_bounds()
        overlapped: list[DetachedWidgetWindow] = []
        for win in self._active_detached_windows():
            if win is moving_window:
                continue
            if self._grid_rects_overlap(moving_rect, win.grid_bounds()):
                overlapped.append(win)

        if not overlapped:
            return False

        source_windows = [moving_window] + overlapped
        transfer_entries: list[dict[str, Any]] = []
        for win in source_windows:
            transfer_entries.extend(win.take_entries_for_transfer())

        if not transfer_entries:
            for win in source_windows:
                win.close_for_reload()
            self._save_layout()
            return True

        group_ids = sorted({
            str(entry["config"].group_id or "").strip()
            for entry in transfer_entries
            if str(entry["config"].group_id or "").strip()
        })
        final_group_id = group_ids[0] if group_ids else self._new_group_id()
        for entry in transfer_entries:
            entry["config"].group_id = final_group_id

        origin_x = min(int(entry["grid_x"]) for entry in transfer_entries)
        origin_y = min(int(entry["grid_y"]) for entry in transfer_entries)

        merged_entries: list[dict[str, Any]] = []
        for entry in transfer_entries:
            merged_entries.append(
                {
                    "config": entry["config"],
                    "widget": entry["widget"],
                    "offset_x": int(entry["grid_x"]) - origin_x,
                    "offset_y": int(entry["grid_y"]) - origin_y,
                }
            )

        for win in source_windows:
            win.close_for_reload()

        merged_window = self._build_detached_window(
            merged_entries,
            origin_x=origin_x,
            origin_y=origin_y,
        )
        if merged_window is not None:
            merged_window.raise_()

        self._save_layout()
        return True

    # ------------------------------------------------------------------ #
    # 导入 / 导出布局
    # ------------------------------------------------------------------ #

    def _on_export_layout(self) -> None:
        """将当前页布局导出为独立的 .ltlayout 文件。"""
        if not self._ensure_access("layout.import_export", "导出布局"):
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出布局",
            "",
            "小树布局文件 (*.ltlayout)",
        )
        if not path:
            return
        target_path = Path(path)
        if target_path.suffix.lower() != ".ltlayout":
            target_path = target_path.with_suffix(".ltlayout")

        data = {
            "version": 1,
            "page_id": self.page_id,
            "widgets": [it.config.to_dict() for it in self._items],
        }
        try:
            write_text_with_uac(
                target_path,
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
                ensure_parent=True,
            )
            InfoBar.success(
                "导出成功",
                f"布局已保存至 {target_path.name}",
                duration=3000,
                position=InfoBarPosition.BOTTOM,
                parent=self.window(),
            )
        except Exception as exc:
            InfoBar.error(
                "导出失败",
                str(exc),
                duration=4000,
                position=InfoBarPosition.BOTTOM,
                parent=self.window(),
            )

    def _on_import_layout(self) -> None:
        """从 .ltlayout 文件导入布局，替换当前页所有组件。"""
        if not self._ensure_access("layout.import_export", "导入布局"):
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "导入布局",
            "",
            "小树布局文件 (*.ltlayout)",
        )
        if not path:
            return
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
            widgets_data = raw.get("widgets", []) if isinstance(raw, dict) else raw
            configs = [WidgetConfig.from_dict(d) for d in widgets_data]
        except Exception as exc:
            InfoBar.error(
                "导入失败",
                str(exc),
                duration=4000,
                position=InfoBarPosition.BOTTOM,
                parent=self.window(),
            )
            return
        if self._lazy_load:
            count = len(configs)
            self._start_lazy_load(configs, save_after=True)
            InfoBar.success(
                "导入成功",
                f"正在后台加载 {count} 个组件",
                duration=3000,
                position=InfoBarPosition.BOTTOM,
                parent=self.window(),
            )
        else:
            self._stop_batch_loader()
            self._close_detached_windows_for_page()
            self._clear_items()

            for cfg in configs:
                self._create_item_from_config(cfg)

            self._save_layout()
            InfoBar.success(
                "导入成功",
                f"已加载 {len(self._items)} 个组件",
                duration=3000,
                position=InfoBarPosition.BOTTOM,
                parent=self.window(),
            )

    # ------------------------------------------------------------------ #
    # 刷新所有组件
    # ------------------------------------------------------------------ #

    def reload_layout(self) -> None:
        """从磁盘重新读取布局配置并重建所有组件（供外部调用，如插件切换预设后刷新）。"""
        if self._lazy_load:
            self._load_layout_lazy()
        else:
            self._load_layout()
            self.refresh_all()

    @Slot()
    def refresh_all(self) -> None:
        for item in self._items:
            item.refresh()
        for win in self._active_detached_windows():
            win.refresh()

    def refresh_unknown_widgets(self) -> None:
        """将已从注册表移除的组件类型替换为未知占位符。

        插件被卸载时由 pluginUnloaded 信号触发。
        """
        reg = WidgetRegistry.instance()
        replaced = False
        for i, item in enumerate(self._items):
            wtype = item.config.widget_type
            # 已是占位符或类型仍注册，跳过
            if isinstance(item._widget, _UnknownWidget) or reg.get(wtype) is not None:
                continue
            cfg         = item.config
            placeholder = _UnknownWidget(cfg, self._services_for_widget(cfg.widget_type), self)
            placeholder.refresh()
            new_item    = WidgetItem(placeholder, self)
            new_item.show()
            self._items[i] = new_item
            item.deleteLater()
            replaced = True
        if replaced:
            self._save_layout()

    # ------------------------------------------------------------------ #
    # 绘制网格线（编辑模式）
    # ------------------------------------------------------------------ #

    # ------------------------------------------------------------------ #
    # 格子大小动态属性
    # ------------------------------------------------------------------ #

    @property
    def cell_size(self) -> int:
        """当前格子像素尺寸，动态读取自 SettingsService。"""
        from app.services.settings_service import SettingsService
        return SettingsService.instance().widget_cell_size

    @Slot(int)
    def _on_cell_size_changed(self, _new_size: int) -> None:
        """格子大小变更时重新计算所有组件的几何尺寸并刷新画布。"""
        for item in self._items:
            item._update_geometry()
            item.refresh()
        for win in self._active_detached_windows():
            win.update_cell_size(_new_size)
        self.update()

    # ------------------------------------------------------------------ #
    # 绘制 / 尺寸变化
    # ------------------------------------------------------------------ #

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if not self.edit_mode:
            return
        p = QPainter(self)
        p.setPen(QPen(QColor(255, 255, 255, 25), 1))
        cs = self.cell_size
        w, h = self.width(), self.height()
        x = 0
        while x <= w:
            p.drawLine(x, 0, x, h)
            x += cs
        y = 0
        while y <= h:
            p.drawLine(0, y, w, y)
            y += cs

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._toolbar:
            self._toolbar.setGeometry(0, self.height() - 52, self.width(), 52)

        # 首次进入新画布且尺寸尚未就绪时，在这里补建默认居中时钟。
        if self._pending_default_clock_init and not self._items:
            defaults = self._build_default_clock_layout()
            if defaults:
                self._pending_default_clock_init = False
                if self._lazy_load:
                    self._start_lazy_load(defaults, save_after=True)
                else:
                    for cfg in defaults:
                        self._create_item_from_config(cfg)
                    self._save_layout()
                    self.refresh_all()
                cfg = defaults[0]
                logger.info(
                    "[画布] 页面 {} 在 resize 后补建默认时钟：x={}, y={}, w={}, h={}",
                    self.page_id,
                    cfg.grid_x,
                    cfg.grid_y,
                    cfg.grid_w,
                    cfg.grid_h,
                )


# ─────────────────────────────────────────────────────────────
# DetachedWidgetWindow —— 分离后的置顶窗口
# ─────────────────────────────────────────────────────────────


class _DetachedContainerWidget(QWidget):
    """分离窗口容器：支持整块背景和最小包裹背景两种绘制模式。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._use_minimal_shape = False
        self._fill_alpha = 0
        self._border_alpha = 0
        self._occupied_rects: list[QRectF] = []

    def set_occupied_rects(self, rects: list[QRectF]) -> None:
        self._occupied_rects = list(rects)
        self.update()

    def set_minimal_shape_mode(self, *, enabled: bool, fill_alpha: int, border_alpha: int) -> None:
        self._use_minimal_shape = bool(enabled)
        self._fill_alpha = max(0, min(255, int(fill_alpha)))
        self._border_alpha = max(0, min(255, int(border_alpha)))
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if not self._use_minimal_shape:
            return
        if not self._occupied_rects:
            return
        if self._fill_alpha <= 0 and self._border_alpha <= 0:
            return

        path = QPainterPath()
        for rect in self._occupied_rects:
            path.addRoundedRect(rect, 6, 6)
        if path.isEmpty():
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self._fill_alpha > 0:
            painter.fillPath(path, QColor(0, 0, 0, self._fill_alpha))
        if self._border_alpha > 0:
            painter.setPen(QPen(QColor(255, 255, 255, self._border_alpha), 1))
            painter.drawPath(path)

class DetachedWidgetWindow(QWidget):
    """分离后的组件置顶窗口（可包含多个组件）。"""

    _instances: list["DetachedWidgetWindow"] = []
    _WINDOW_MARGIN = 8

    def __init__(
        self,
        entries: list[dict[str, Any]],
        cell_size: int,
        page_id: str,
        parent=None,
    ):
        super().__init__(parent)
        self._window_id = str(uuid.uuid4())
        self._page_id = str(page_id)
        self._entries: list[dict[str, Any]] = []
        self._cell_size = max(1, int(cell_size))
        self._grid_w = 1
        self._grid_h = 1

        self._dragging = False
        self._drag_offset = QPoint()
        self._host_window = parent.window() if parent is not None else None

        self._merge_callback: Callable[[DetachedWidgetWindow], None] | None = None
        self._moved_callback: Callable[[DetachedWidgetWindow], None] | None = None
        self._delete_callback: Callable[[DetachedWidgetWindow], None] | None = None
        self._split_callback: Callable[[DetachedWidgetWindow], None] | None = None

        self._allow_widget_delete = True
        self._notify_move_on_release = True

        self.setWindowFlags(
            Qt.WindowType.Tool |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        if self._host_window is not None:
            self._host_window.installEventFilter(self)

        from app.services.settings_service import SettingsService
        self._settings = SettingsService.instance()

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)

        self._container = _DetachedContainerWidget()
        self._container.setObjectName("detachedContainer")
        root_layout.addWidget(self._container)

        self._has_custom_bg = False
        self._set_entries(entries)
        self._apply_container_style()

        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

        DetachedWidgetWindow._instances.append(self)
        self._settings.changed.connect(self._apply_container_style)

    @property
    def page_id(self) -> str:
        return self._page_id

    @property
    def window_id(self) -> str:
        return self._window_id

    def set_canvas_callbacks(
        self,
        *,
        merge_callback: Callable[["DetachedWidgetWindow"], None] | None,
        moved_callback: Callable[["DetachedWidgetWindow"], None] | None,
        delete_callback: Callable[["DetachedWidgetWindow"], None] | None,
        split_callback: Callable[["DetachedWidgetWindow"], None] | None,
    ) -> None:
        self._merge_callback = merge_callback
        self._moved_callback = moved_callback
        self._delete_callback = delete_callback
        self._split_callback = split_callback

    def _set_entries(self, entries: list[dict[str, Any]]) -> None:
        normalized: list[dict[str, Any]] = []
        for raw in entries:
            if not isinstance(raw, dict):
                continue
            cfg = raw.get("config")
            widget = raw.get("widget")
            if not isinstance(cfg, WidgetConfig) or not isinstance(widget, QWidget):
                continue
            normalized.append(
                {
                    "config": cfg,
                    "widget": widget,
                    "offset_x": int(raw.get("offset_x", 0)),
                    "offset_y": int(raw.get("offset_y", 0)),
                }
            )

        if not normalized:
            self._entries = []
            return

        min_x = min(int(entry["offset_x"]) for entry in normalized)
        min_y = min(int(entry["offset_y"]) for entry in normalized)
        if min_x != 0 or min_y != 0:
            for entry in normalized:
                entry["offset_x"] = int(entry["offset_x"]) - min_x
                entry["offset_y"] = int(entry["offset_y"]) - min_y

        self._entries = normalized
        self._relayout_entries()

    def _widget_has_custom_bg(self, widget: QWidget) -> bool:
        style = widget.styleSheet() or ""
        return bool(style and "background" in style and "transparent" not in style)

    def _relayout_entries(self) -> None:
        if not self._entries:
            self._grid_w = 1
            self._grid_h = 1
            self.resize(self._WINDOW_MARGIN * 2, self._WINDOW_MARGIN * 2)
            return

        cs = max(1, self._cell_size)
        margin = self._WINDOW_MARGIN

        max_x = 1
        max_y = 1
        all_custom_bg = True
        occupied_rects: list[QRectF] = []
        for entry in self._entries:
            cfg: WidgetConfig = entry["config"]
            ox = int(entry["offset_x"])
            oy = int(entry["offset_y"])
            gw = max(1, int(cfg.grid_w))
            gh = max(1, int(cfg.grid_h))
            max_x = max(max_x, ox + gw)
            max_y = max(max_y, oy + gh)

            widget: QWidget = entry["widget"]
            widget.setParent(self._container)
            widget.setGeometry(
                margin + ox * cs,
                margin + oy * cs,
                gw * cs,
                gh * cs,
            )
            widget.show()
            occupied_rects.append(
                QRectF(
                    margin + ox * cs,
                    margin + oy * cs,
                    gw * cs,
                    gh * cs,
                )
            )
            all_custom_bg = all_custom_bg and self._widget_has_custom_bg(widget)

        self._grid_w = max_x
        self._grid_h = max_y
        self._has_custom_bg = all_custom_bg

        container_w = self._grid_w * cs + margin * 2
        container_h = self._grid_h * cs + margin * 2
        self._container.resize(container_w, container_h)
        self._container.set_occupied_rects(occupied_rects)
        self.resize(container_w, container_h)
        self._apply_container_style()

    def refresh(self) -> None:
        for entry in self._entries:
            widget = entry.get("widget")
            if isinstance(widget, WidgetBase):
                widget.refresh()

    def grid_origin(self) -> tuple[int, int]:
        cs = max(1, self._cell_size)
        return round(self.x() / cs), round(self.y() / cs)

    def grid_bounds(self) -> tuple[int, int, int, int]:
        origin_x, origin_y = self.grid_origin()
        return origin_x, origin_y, self._grid_w, self._grid_h

    def to_layout_record(self) -> dict[str, Any]:
        origin_x, origin_y = self.grid_origin()
        entries_payload: list[dict[str, Any]] = []
        for entry in self._entries:
            cfg: WidgetConfig = entry["config"]
            entries_payload.append(
                {
                    "offset_x": int(entry["offset_x"]),
                    "offset_y": int(entry["offset_y"]),
                    "widget": copy.deepcopy(cfg.to_dict()),
                }
            )
        return {
            "origin_x": origin_x,
            "origin_y": origin_y,
            "entries": entries_payload,
        }

    def take_entries_for_transfer(self) -> list[dict[str, Any]]:
        origin_x, origin_y = self.grid_origin()
        transferred: list[dict[str, Any]] = []
        for entry in self._entries:
            cfg: WidgetConfig = entry["config"]
            widget: QWidget = entry["widget"]
            widget.setParent(None)
            transferred.append(
                {
                    "config": cfg,
                    "widget": widget,
                    "grid_x": origin_x + int(entry["offset_x"]),
                    "grid_y": origin_y + int(entry["offset_y"]),
                }
            )
        self._entries.clear()
        self._allow_widget_delete = False
        return transferred

    def close_for_reload(self) -> None:
        self._notify_move_on_release = False
        self.close()

    def close_for_delete(self) -> None:
        self._notify_move_on_release = False
        self._allow_widget_delete = True
        self.close()

    def update_cell_size(self, new_size: int) -> None:
        origin_x, origin_y = self.grid_origin()
        self._cell_size = max(1, int(new_size))
        self._relayout_entries()
        cs = max(1, self._cell_size)
        self.move(origin_x * cs, origin_y * cs)

    def _apply_container_style(self) -> None:
        if self._has_custom_bg:
            self._container.setStyleSheet("background: transparent; border-radius: 8px;")
            self._container.set_minimal_shape_mode(enabled=False, fill_alpha=0, border_alpha=0)
            return

        opacity = self._settings.detached_widget_background_opacity
        alpha = max(0, min(255, round(opacity * 2.55)))
        border_alpha = max(24, min(120, round(alpha * 0.45))) if alpha > 0 else 0

        self._container.setStyleSheet("QWidget#detachedContainer {background: transparent; border: none;}")
        self._container.set_minimal_shape_mode(
            enabled=True,
            fill_alpha=alpha,
            border_alpha=border_alpha,
        )

    def _ensure_above_host(self) -> None:
        self.raise_()
        self.show()

    def eventFilter(self, watched, event) -> bool:
        if watched is self._host_window and event.type() in {
            QEvent.Type.WindowActivate,
            QEvent.Type.Show,
            QEvent.Type.Resize,
        }:
            QTimer.singleShot(0, self._ensure_above_host)
        return super().eventFilter(watched, event)

    def _show_context_menu(self, pos: QPoint) -> None:
        menu = RoundMenu(parent=self)

        if len(self._entries) == 1:
            widget = self._entries[0].get("widget")
            if isinstance(widget, WidgetBase):
                custom_actions = widget.get_context_menu_actions()
                for text, icon, callback in custom_actions:
                    if icon:
                        menu.addAction(Action(icon, text, triggered=callback))
                    else:
                        menu.addAction(Action(FIF.APPLICATION, text, triggered=callback))
                if custom_actions:
                    menu.addSeparator()

        merge_text = "合并到画布" if len(self._entries) <= 1 else "全部合并到画布"
        menu.addAction(Action(FIF.BACK_TO_WINDOW, merge_text, triggered=self._request_merge))
        if len(self._entries) > 1:
            menu.addAction(Action(FIF.LAYOUT, "拆分组件组", triggered=self._request_split))
        menu.addAction(Action(FIF.CLOSE, "关闭并移除", triggered=self._request_delete))
        menu.exec(self.mapToGlobal(pos))

    def _request_merge(self) -> None:
        if self._merge_callback:
            self._merge_callback(self)
            return
        self.close_for_reload()

    def _request_delete(self) -> None:
        if self._delete_callback:
            self._delete_callback(self)
            return
        self.close_for_delete()

    def _request_split(self) -> None:
        if self._split_callback:
            self._split_callback(self)

    def closeEvent(self, event) -> None:
        if self in DetachedWidgetWindow._instances:
            DetachedWidgetWindow._instances.remove(self)
        if self._host_window is not None:
            try:
                self._host_window.removeEventFilter(self)
            except Exception:
                pass
        try:
            self._settings.changed.disconnect(self._apply_container_style)
        except Exception:
            pass

        if self._allow_widget_delete:
            for entry in self._entries:
                widget = entry.get("widget")
                if isinstance(widget, QWidget):
                    widget.setParent(None)
                    widget.deleteLater()
        self._entries.clear()
        super().closeEvent(event)

    # ------------------------------------------------------------------ #
    # 拖拽移动（支持网格吸附）
    # ------------------------------------------------------------------ #

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_offset = event.position().toPoint()
            self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._dragging:
            new_pos = event.globalPosition().toPoint() - self._drag_offset
            self.move(new_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._dragging:
            self._dragging = False
            self.unsetCursor()
            self._snap_to_grid()
            if self._notify_move_on_release and self._moved_callback:
                self._moved_callback(self)
        super().mouseReleaseEvent(event)

    def _snap_to_grid(self) -> None:
        cs = max(1, self._cell_size)
        x = round(self.x() / cs) * cs
        y = round(self.y() / cs) * cs
        self.move(x, y)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self._ensure_above_host)

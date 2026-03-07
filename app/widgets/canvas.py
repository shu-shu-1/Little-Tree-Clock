"""小组件画布 —— 全屏区域内的可编辑网格布局"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QPoint, QSize, Slot
from PySide6.QtGui import QPainter, QColor, QPen, QCursor
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
    "image":      FIF.PHOTO,
    "calculator": FIF.APPLICATION,
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
        has_edit = self._widget.get_edit_widget() is not None
        if has_edit:
            menu.addAction(Action(FIF.EDIT, "编辑", triggered=self._open_edit))
        if self._widget.DELETABLE:
            if has_edit:
                menu.addSeparator()
            menu.addAction(Action(FIF.DELETE, "删除", triggered=self._request_delete))
        if not menu.actions():
            return
        menu.exec(self.mapToGlobal(pos))

    def _open_edit(self) -> None:
        dlg = _EditDialog(self._widget, self._canvas)
        dlg.exec()
        self._update_geometry()  # 编辑可能改变大小
        self._canvas._save_layout()

    def _request_delete(self) -> None:
        self._canvas._remove_item(self)

    # ------------------------------------------------------------------ #
    # 拖拽（仅编辑模式）
    # ------------------------------------------------------------------ #

    def mousePressEvent(self, event) -> None:
        if self._canvas.edit_mode and event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_offset = event.position().toPoint()
            self.raise_()
            self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._dragging:
            new_pos = self.mapToParent(event.position().toPoint() - self._drag_offset)
            # 实时夹界到画布范围，防止四边溢出
            max_x = max(0, self._canvas.width()  - self.width())
            max_y = max(0, self._canvas.height() - self.height())
            clamped_x = max(0, min(new_pos.x(), max_x))
            clamped_y = max(0, min(new_pos.y(), max_y))
            self.move(clamped_x, clamped_y)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._dragging:
            self._dragging = False
            self.unsetCursor()
            self._snap_to_grid()
            self._canvas._save_layout()
        super().mouseReleaseEvent(event)

    def _snap_to_grid(self) -> None:
        cs = self._canvas.cell_size
        x = round(self.x() / cs)
        y = round(self.y() / cs)
        # 左/上边界
        x = max(0, x)
        y = max(0, y)
        # 右/下边界：限制在画布网格内
        cols = max(1, self._canvas.width()  // cs)
        rows = max(1, self._canvas.height() // cs)
        x = min(x, max(0, cols - self.config.grid_w))
        y = min(y, max(0, rows - self.config.grid_h))
        self.config.grid_x = x
        self.config.grid_y = y
        self._update_geometry()

    # ------------------------------------------------------------------ #
    # 绘制编辑模式下的边框高亮
    # ------------------------------------------------------------------ #

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._canvas.edit_mode:
            p = QPainter(self)
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
    ):
        super().__init__(parent)
        self.setAutoFillBackground(False)
        self.page_id   = page_id
        self._plugin_manager = plugin_manager
        self._base_services = dict(services)
        self.services  = dict(services)
        self.edit_mode = False

        self._store = WidgetLayoutStore()
        self._items: list[WidgetItem] = []

        self._build_toolbar()
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

    def _load_layout(self) -> None:
        for it in self._items:
            it.deleteLater()
        self._items.clear()

        configs = self._store.get(self.page_id)

        reg = WidgetRegistry.instance()
        for cfg in configs:
            widget = reg.create(cfg, self._services_for_widget(cfg.widget_type), self)
            if widget is None:
                # 对应插件未加载，创建占位符让用户可知并可删除
                widget = _UnknownWidget(cfg, self._services_for_widget(cfg.widget_type), self)
                widget.refresh()
            item = WidgetItem(widget, self)
            item.show()
            self._items.append(item)

    def _save_layout(self) -> None:
        self._store.save(self.page_id, [it.config for it in self._items])

    # ------------------------------------------------------------------ #
    # 添加 / 删除组件
    # ------------------------------------------------------------------ #

    def _on_add_widget(self) -> None:
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
        cfg = WidgetConfig(
            widget_type=type_id,
            grid_x=0, grid_y=0,
            grid_w=cls.DEFAULT_W, grid_h=cls.DEFAULT_H,
        )
        widget = reg.create(cfg, self._services_for_widget(cfg.widget_type), self)
        if widget:
            item = WidgetItem(widget, self)
            item.show()
            self._items.append(item)
            self._save_layout()

    def _remove_item(self, item: WidgetItem) -> None:
        self._items.remove(item)
        item.deleteLater()
        self._save_layout()

    # ------------------------------------------------------------------ #
    # 导入 / 导出布局
    # ------------------------------------------------------------------ #

    def _on_export_layout(self) -> None:
        """将当前页布局导出为独立的 .ltlayout 文件。"""
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出布局",
            "",
            "小树布局文件 (*.ltlayout);;JSON 文件 (*.json)",
        )
        if not path:
            return
        data = {
            "version": 1,
            "page_id": self.page_id,
            "widgets": [it.config.to_dict() for it in self._items],
        }
        try:
            Path(path).write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            InfoBar.success(
                "导出成功",
                f"布局已保存至 {Path(path).name}",
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
        path, _ = QFileDialog.getOpenFileName(
            self,
            "导入布局",
            "",
            "小树布局文件 (*.ltlayout);;JSON 文件 (*.json)",
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

        # 清除现有组件并加载导入的组件
        for it in self._items:
            it.deleteLater()
        self._items.clear()

        reg = WidgetRegistry.instance()
        for cfg in configs:
            widget = reg.create(cfg, self._services_for_widget(cfg.widget_type), self)
            if widget is None:
                widget = _UnknownWidget(cfg, self._services_for_widget(cfg.widget_type), self)
                widget.refresh()
            item = WidgetItem(widget, self)
            item.show()
            self._items.append(item)

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
        self._load_layout()
        self.refresh_all()

    @Slot()
    def refresh_all(self) -> None:
        for item in self._items:
            item.refresh()

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

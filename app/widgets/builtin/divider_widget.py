"""分割线组件 —— 在格线边缘显示装饰性分割线，不占用格位，通过小按钮拖拽/操作"""
from __future__ import annotations

from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QPainter, QColor, QPen
from PySide6.QtWidgets import QWidget, QFormLayout, QPushButton
from qfluentwidgets import SpinBox, ColorPickerButton, ComboBox

from app.widgets.base_widget import WidgetBase, WidgetConfig


class _DividerEditPanel(QWidget):
    def __init__(self, props: dict, parent=None):
        super().__init__(parent)
        f = QFormLayout(self)
        f.setVerticalSpacing(10)

        self._orient = ComboBox()
        for label, val in [("\u6c34\u5e73", "horizontal"), ("\u5782\u76f4", "vertical")]:
            self._orient.addItem(label, userData=val)
        cur = props.get("orientation", "horizontal")
        idx = next(
            (i for i in range(self._orient.count())
             if self._orient.itemData(i) == cur), 0,
        )
        self._orient.setCurrentIndex(idx)
        f.addRow("\u65b9\u5411:", self._orient)

        self._length = SpinBox()
        self._length.setRange(1, 20)
        self._length.setValue(props.get("length", 3))
        self._length.setSuffix(" \u683c")
        f.addRow("\u957f\u5ea6:", self._length)

        self._thick = SpinBox()
        self._thick.setRange(1, 20)
        self._thick.setValue(props.get("thickness", 2))
        self._thick.setSuffix(" px")
        f.addRow("\u7c97\u7ec6:", self._thick)

        from app.utils.theme_utils import widget_colors
        default_clr = props.get("color", "") or widget_colors()["border"]
        self._color = ColorPickerButton(
            QColor(default_clr), "\u7ebf\u6761\u989c\u8272",
        )
        f.addRow("\u989c\u8272:", self._color)

    def collect_props(self) -> dict:
        return {
            "orientation": self._orient.currentData(),
            "length": self._length.value(),
            "thickness": self._thick.value(),
            "color": self._color.color.name(),
        }


class _DividerHandle(QPushButton):
    """分割线的拖拽手柄兼右键菜单触发按钮。"""

    _SIZE = 26
    _GAP = 3
    _DRAG_THRESHOLD = 5

    def __init__(self, divider: DividerWidget):
        super().__init__(divider)
        self._divider = divider
        self._dragging = False
        self._has_moved = False
        self._start_global = QPoint()
        self._item_start = QPoint()
        self._side: str = "auto"

        self.setFixedSize(self._SIZE, self._SIZE)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setText("\u22ee")
        self._apply_style()
        self.hide()

    def _apply_style(self):
        dark = self._divider._is_dark()
        if dark:
            bg = "rgba(255,255,255,190)"
            bg_hover = "rgba(255,255,255,245)"
            bg_press = "rgba(200,200,200,245)"
            text_c = "#333"
        else:
            bg = "rgba(0,0,0,150)"
            bg_hover = "rgba(0,0,0,200)"
            bg_press = "rgba(60,60,60,220)"
            text_c = "#eee"
        self.setStyleSheet(
            f"QPushButton{{background:{bg};color:{text_c};"
            f"border:none;border-radius:13px;font-size:16px;font-weight:bold}}"
            f"QPushButton:hover{{background:{bg_hover}}}"
            f"QPushButton:pressed{{background:{bg_press}}}"
        )

    @classmethod
    def _pad(cls) -> int:
        return cls._SIZE + cls._GAP * 2

    def _get_item(self):
        return self._divider.parent()

    def _get_canvas(self):
        item = self._get_item()
        if item is not None:
            canvas = item.parent()
            if canvas is not None and hasattr(canvas, "edit_mode"):
                return canvas
        return None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._has_moved = False
            self._start_global = event.globalPosition().toPoint()
            item = self._get_item()
            if item:
                self._item_start = QPoint(item.x(), item.y())
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging:
            delta = event.globalPosition().toPoint() - self._start_global
            if not self._has_moved and delta.manhattanLength() <= self._DRAG_THRESHOLD:
                return
            self._has_moved = True

            item = self._get_item()
            canvas = self._get_canvas()
            if not item or not canvas:
                return

            new_x = self._item_start.x() + delta.x()
            new_y = self._item_start.y() + delta.y()
            new_x = max(0, min(new_x, canvas.width() - max(item.width(), 1)))
            new_y = max(0, min(new_y, canvas.height() - max(item.height(), 1)))
            item.move(new_x, new_y)

            self._update_side_from_drag(delta.x(), delta.y())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._dragging:
            self._dragging = False
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            if self._has_moved:
                self._snap_to_grid()
            else:
                self._show_context_menu()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _update_side_from_drag(self, dx: int, dy: int):
        orient = self._divider.config.props.get("orientation", "horizontal")
        if orient == "horizontal":
            self._side = "bottom" if dy >= 0 else "top"
        else:
            self._side = "right" if dx >= 0 else "left"
        self._reposition()

    def _resolve_side(self) -> str:
        if self._side != "auto":
            return self._side
        orient = self._divider.config.props.get("orientation", "horizontal")
        return "bottom" if orient == "horizontal" else "right"

    def _reposition(self):
        s = self._SIZE
        gap = self._GAP
        w = self._divider.width()
        h = self._divider.height()
        thick = max(1, self._divider.config.props.get("thickness", 2))
        pad = self._pad()

        side = self._resolve_side()
        cx = (w - s) // 2
        cy = (h - s) // 2

        pos_map = {
            "top":    (cx, pad - s - gap),
            "bottom": (cx, pad + thick + gap),
            "left":   (pad - s - gap, cy),
            "right":  (pad + thick + gap, cy),
        }
        x, y = pos_map.get(side, (cx, pad + thick + gap))
        self.move(x, y)

    def _ensure_on_screen(self):
        canvas = self._get_canvas()
        if not canvas:
            return
        center = self.mapTo(canvas, self.rect().center())
        on_screen = (0 <= center.x() <= canvas.width()
                     and 0 <= center.y() <= canvas.height())
        if not on_screen:
            opposites = {"top": "bottom", "bottom": "top",
                         "left": "right", "right": "left"}
            self._side = opposites.get(self._side, self._side)
            self._reposition()

    def _snap_to_grid(self):
        from app.services.settings_service import SettingsService
        if not SettingsService.instance().widget_grid_snap_enabled:
            item = self._get_item()
            canvas = self._get_canvas()
            if item and canvas:
                cs = max(1, canvas.cell_size)
                self._divider.config.grid_x = round(item.x() / cs)
                self._divider.config.grid_y = round(item.y() / cs)
                canvas._save_layout()
            return
        item = self._get_item()
        canvas = self._get_canvas()
        if not item or not canvas:
            return
        cs = canvas.cell_size
        if cs <= 0:
            return
        self._divider.config.grid_x = round(item.x() / cs)
        self._divider.config.grid_y = round(item.y() / cs)
        item._update_geometry()
        self._ensure_on_screen()
        canvas._save_layout()

    def _show_context_menu(self):
        item = self._get_item()
        if item and hasattr(item, "_show_context_menu"):
            center = self.geometry().center()
            item._show_context_menu(center)

    def show_for_edit(self):
        self.show()
        self._reposition()
        self._ensure_on_screen()

    def hide_for_edit(self):
        self.hide()


class DividerWidget(WidgetBase):
    WIDGET_TYPE = "divider"
    WIDGET_NAME = "\u5206\u5272\u7ebf"
    DELETABLE = True
    MIN_W = 1
    MIN_H = 1
    DEFAULT_W = 3
    DEFAULT_H = 1
    DETACHED_BG_MODE = "transparent"
    FLOATING = True

    def __init__(self, config: WidgetConfig, services, parent=None):
        super().__init__(config, services, parent)
        self._handle = _DividerHandle(self)
        self.refresh()

    def compute_item_geometry(self, cell_size: int) -> tuple[int, int, int, int]:
        cs = cell_size
        p = self.config.props
        orient = p.get("orientation", "horizontal")
        length = max(1, p.get("length", 3))
        thick = max(1, p.get("thickness", 2))
        gx, gy = self.config.grid_x, self.config.grid_y
        pad = _DividerHandle._pad()

        if orient == "horizontal":
            return gx * cs, gy * cs - pad, length * cs, thick + pad * 2
        return gx * cs - pad, gy * cs, thick + pad * 2, length * cs

    def on_edit_mode_changed(self, enabled: bool):
        if enabled:
            self._handle.show_for_edit()
        else:
            self._handle.hide_for_edit()

    def refresh(self) -> None:
        self.config.grid_w = 0
        self.config.grid_h = 0
        self._handle._apply_style()
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        c = self._wc()
        p = self.config.props
        orient = p.get("orientation", "horizontal")
        thick = max(1, p.get("thickness", 2))
        color = QColor(p.get("color", "") or c["border"])
        pad = _DividerHandle._pad()

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(color, thick, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)

        if orient == "horizontal":
            y = pad + thick / 2.0
            painter.drawLine(0, int(y), self.width(), int(y))
        else:
            x = pad + thick / 2.0
            painter.drawLine(int(x), 0, int(x), self.height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._handle.isVisible():
            self._handle._reposition()

    def get_edit_widget(self):
        return _DividerEditPanel(self.config.props)

    def apply_props(self, props: dict) -> None:
        self.config.props.update(props)
        self.refresh()

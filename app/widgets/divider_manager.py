"""分割线管理 —— 画布上的网格线装饰分割线（非组件）"""
from __future__ import annotations

import uuid
from typing import Any, Callable

from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QPainter, QColor, QPen
from PySide6.QtWidgets import QWidget, QPushButton, QFormLayout, QDialog
from qfluentwidgets import (
    SpinBox, ColorPickerButton, ComboBox,
    MessageBox, RoundMenu, Action,
    FluentIcon as FIF,
)


class DividerEditPanel(QWidget):
    """分割线编辑面板"""

    def __init__(self, divider: dict, parent=None):
        super().__init__(parent)
        f = QFormLayout(self)
        f.setVerticalSpacing(10)

        self._orient = ComboBox()
        for label, val in [("水平", "horizontal"), ("垂直", "vertical")]:
            self._orient.addItem(label, userData=val)
        cur = divider.get("orientation", "horizontal")
        idx = next(
            (i for i in range(self._orient.count())
             if self._orient.itemData(i) == cur), 0,
        )
        self._orient.setCurrentIndex(idx)
        f.addRow("方向:", self._orient)

        self._length = SpinBox()
        self._length.setRange(1, 20)
        self._length.setValue(divider.get("length", 3))
        self._length.setSuffix(" 格")
        f.addRow("长度:", self._length)

        self._thick = SpinBox()
        self._thick.setRange(1, 20)
        self._thick.setValue(divider.get("thickness", 2))
        self._thick.setSuffix(" px")
        f.addRow("粗细:", self._thick)

        from app.utils.theme_utils import widget_colors
        stored = divider.get("color", "")
        default_clr = stored if stored and stored != "#ffffff" else widget_colors().get("border", "#cccccc")
        self._color = ColorPickerButton(
            QColor(default_clr), "线条颜色",
        )
        f.addRow("颜色:", self._color)

    def collect_props(self) -> dict:
        return {
            "orientation": self._orient.currentData(),
            "length": self._length.value(),
            "thickness": self._thick.value(),
            "color": self._color.color.name(),
        }


class DividerEditDialog(MessageBox):
    """分割线编辑对话框"""

    def __init__(self, divider: dict, parent=None):
        super().__init__("编辑分割线", "", parent)
        self.yesButton.setText("保存")
        self.cancelButton.setText("取消")
        self.contentLabel.hide()
        self._divider = divider
        self._edit = DividerEditPanel(divider)
        self.textLayout.addWidget(self._edit)

    def accept(self) -> None:
        props = self._edit.collect_props()
        self._divider.update(props)
        super().accept()


class DividerHandle(QPushButton):
    """分割线的编辑手柄按钮。支持拖拽和点击打开菜单。"""

    _SIZE = 26
    _GAP = 3

    def __init__(
        self,
        divider_id: str,
        parent,
        on_drag_start: Callable[[str], None],
        on_drag: Callable[[str, QPoint], None],
        on_drag_end: Callable[[str, QPoint], None],
        on_click: Callable[[str, QPoint], None],
    ):
        super().__init__(parent)
        self._divider_id = divider_id
        self._on_drag_start = on_drag_start
        self._on_drag = on_drag
        self._on_drag_end = on_drag_end
        self._on_click = on_click
        self._dragging = False
        self._start_global = QPoint()

        self.setFixedSize(self._SIZE, self._SIZE)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setText("⋮")

        from app.utils.theme_utils import is_widget_dark
        try:
            dark = is_widget_dark(getattr(parent, "page_id", None))
        except Exception:
            dark = True

        if dark:
            bg, bg_h, bg_p, txt = "rgba(255,255,255,190)", "rgba(255,255,255,245)", "rgba(200,200,200,245)", "#333"
        else:
            bg, bg_h, bg_p, txt = "rgba(0,0,0,150)", "rgba(0,0,0,200)", "rgba(60,60,60,220)", "#eee"

        self.setStyleSheet(
            f"QPushButton{{background:{bg};color:{txt};"
            f"border:none;border-radius:13px;font-size:16px;font-weight:bold}}"
            f"QPushButton:hover{{background:{bg_h}}}"
            f"QPushButton:pressed{{background:{bg_p}}}"
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._start_global = event.globalPosition().toPoint()
            self._on_drag_start(self._divider_id)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        elif event.button() == Qt.MouseButton.RightButton:
            self._on_click(self._divider_id, self.mapToGlobal(event.position().toPoint()))
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging:
            delta = event.globalPosition().toPoint() - self._start_global
            self._on_drag(self._divider_id, delta)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._dragging:
            self._dragging = False
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            delta = event.globalPosition().toPoint() - self._start_global
            if delta.manhattanLength() <= 5:
                self._on_click(self._divider_id, self.mapToGlobal(self.rect().center()))
            else:
                self._on_drag_end(self._divider_id, delta)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class DividerManager:
    """管理画布上的分割线"""

    def __init__(self, canvas: "WidgetCanvas", save_callback: Callable[[], None]):
        self._canvas = canvas
        self._save_callback = save_callback
        self._dividers: list[dict] = []
        self._handles: dict[str, DividerHandle] = {}
        self._drag_state: dict | None = None

    @property
    def cell_size(self) -> int:
        return self._canvas.cell_size

    # ------------------------------------------------------------------ #
    # 数据
    # ------------------------------------------------------------------ #

    def load(self, data: list[dict]) -> None:
        self._dividers = [dict(d) for d in (data or [])]

    def get_data(self) -> list[dict]:
        return [{k: v for k, v in d.items() if k != "_side"} for d in self._dividers]

    def get_divider(self, divider_id: str) -> dict | None:
        for d in self._dividers:
            if d.get("id") == divider_id:
                return d
        return None

    def add_divider(self, x: int = 0, y: int = 0) -> dict:
        divider = {
            "id": str(uuid.uuid4()),
            "x": x,
            "y": y,
            "orientation": "horizontal",
            "length": 3,
            "thickness": 2,
            "color": "",
        }
        self._dividers.append(divider)
        return divider

    def remove_divider(self, divider_id: str) -> None:
        self._dividers = [d for d in self._dividers if d.get("id") != divider_id]
        if divider_id in self._handles:
            self._handles[divider_id].deleteLater()
            del self._handles[divider_id]

    def clamp_to_canvas(self) -> None:
        self._canvas.update()
        self.refresh_handles()

    # ------------------------------------------------------------------ #
    # 绘制
    # ------------------------------------------------------------------ #

    def draw(self, painter: QPainter) -> None:
        cs = self.cell_size
        if cs <= 0:
            return

        from app.utils.theme_utils import widget_colors, is_widget_dark
        zone_id = getattr(self._canvas, "page_id", None)
        wc = widget_colors(zone_id)

        for d in self._dividers:
            x = d["x"] * cs
            y = d["y"] * cs
            length = d.get("length", 3) * cs
            thick = max(1, d.get("thickness", 2))
            color_str = d.get("color", "")
            if not color_str or color_str == "#ffffff":
                color_str = wc.get("border", "#cccccc")
            color = QColor(color_str)
            orient = d.get("orientation", "horizontal")

            pen = QPen(color, thick, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)

            if orient == "horizontal":
                painter.drawLine(int(x), int(y), int(x + length), int(y))
            else:
                painter.drawLine(int(x), int(y), int(x), int(y + length))

    # ------------------------------------------------------------------ #
    # 编辑模式手柄
    # ------------------------------------------------------------------ #

    def enter_edit_mode(self) -> None:
        for d in self._dividers:
            self._create_handle(d)

    def leave_edit_mode(self) -> None:
        for handle in self._handles.values():
            handle.deleteLater()
        self._handles.clear()
        self._drag_state = None

    def refresh_handles(self) -> None:
        for divider_id, handle in list(self._handles.items()):
            divider = self.get_divider(divider_id)
            if divider:
                self._position_handle(handle, divider)
            else:
                handle.deleteLater()
                del self._handles[divider_id]

    def raise_handles(self) -> None:
        for handle in self._handles.values():
            handle.raise_()

    def _create_handle(self, divider: dict) -> None:
        divider_id = divider["id"]
        if divider_id in self._handles:
            return
        handle = DividerHandle(
            divider_id,
            self._canvas,
            self._on_drag_start,
            self._on_drag,
            self._on_drag_end,
            self._on_click,
        )
        self._position_handle(handle, divider)
        handle.show()
        handle.raise_()
        self._handles[divider_id] = handle

    def _position_handle(self, handle: DividerHandle, divider: dict) -> None:
        cs = self.cell_size
        if cs <= 0:
            return
        x = divider["x"] * cs
        y = divider["y"] * cs
        length = divider.get("length", 3) * cs
        thick = max(1, divider.get("thickness", 2))
        orient = divider.get("orientation", "horizontal")
        side = divider.get("_side", "auto")

        s = DividerHandle._SIZE
        gap = DividerHandle._GAP

        if orient == "horizontal":
            cx = x + length // 2 - s // 2
            cx = max(0, min(cx, self._canvas.width() - s))
            if side in ("auto", "bottom"):
                by = y + thick + gap
            else:
                by = y - s - gap
            handle.move(int(cx), int(by))
        else:
            cy = y + length // 2 - s // 2
            cy = max(0, min(cy, self._canvas.height() - s))
            if side in ("auto", "right"):
                bx = x + thick + gap
            else:
                bx = x - s - gap
            handle.move(int(bx), int(cy))

        # 确保按钮在画布内，若不在则翻转方向
        center = handle.mapTo(self._canvas, handle.rect().center())
        if not self._canvas.rect().contains(center):
            opposites = {"top": "bottom", "bottom": "top", "left": "right", "right": "left"}
            new_side = opposites.get(side, side)
            divider["_side"] = new_side
            if orient == "horizontal":
                cx = x + length // 2 - s // 2
                cx = max(0, min(cx, self._canvas.width() - s))
                if new_side == "bottom":
                    by = y + thick + gap
                else:
                    by = y - s - gap
                handle.move(int(cx), int(by))
            else:
                cy = y + length // 2 - s // 2
                cy = max(0, min(cy, self._canvas.height() - s))
                if new_side == "right":
                    bx = x + thick + gap
                else:
                    bx = x - s - gap
                handle.move(int(bx), int(cy))

    def _update_handle_position(self, divider_id: str) -> None:
        handle = self._handles.get(divider_id)
        divider = self.get_divider(divider_id)
        if handle and divider:
            self._position_handle(handle, divider)

    def _update_handle_side(self, divider_id: str, dx: int, dy: int) -> None:
        divider = self.get_divider(divider_id)
        if not divider:
            return
        orient = divider.get("orientation", "horizontal")
        if orient == "horizontal":
            divider["_side"] = "bottom" if dy >= 0 else "top"
        else:
            divider["_side"] = "right" if dx >= 0 else "left"
        self._update_handle_position(divider_id)

    # ------------------------------------------------------------------ #
    # 拖拽回调
    # ------------------------------------------------------------------ #

    def _on_drag_start(self, divider_id: str) -> None:
        divider = self.get_divider(divider_id)
        if divider:
            self._drag_state = {"id": divider_id, "start": dict(divider)}

    def _on_drag(self, divider_id: str, delta: QPoint) -> None:
        if not self._drag_state or self._drag_state["id"] != divider_id:
            return
        divider = self.get_divider(divider_id)
        start = self._drag_state["start"]
        cs = self.cell_size
        if cs > 0 and divider:
            new_x = start["x"] + round(delta.x() / cs)
            new_y = start["y"] + round(delta.y() / cs)
            cols, rows = self._canvas._grid_dimensions()
            divider["x"] = max(0, min(new_x, cols))
            divider["y"] = max(0, min(new_y, rows))
            self._canvas.update()
            self._update_handle_position(divider_id)

    def _on_drag_end(self, divider_id: str, delta: QPoint) -> None:
        self._drag_state = None
        self._update_handle_side(divider_id, delta.x(), delta.y())
        self._save_callback()

    def _on_click(self, divider_id: str, global_pos: QPoint) -> None:
        menu = RoundMenu(parent=self._canvas)
        menu.addAction(Action(FIF.EDIT, "编辑", triggered=lambda: self._edit_divider(divider_id)))
        menu.addAction(Action(FIF.DELETE, "删除", triggered=lambda: self._remove_divider(divider_id)))
        menu.exec(global_pos)

    def _edit_divider(self, divider_id: str) -> None:
        divider = self.get_divider(divider_id)
        if not divider:
            return
        dlg = DividerEditDialog(divider, self._canvas)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._canvas.update()
            self._update_handle_position(divider_id)
            self._save_callback()

    def _remove_divider(self, divider_id: str) -> None:
        self.remove_divider(divider_id)
        self._canvas.update()
        self._save_callback()

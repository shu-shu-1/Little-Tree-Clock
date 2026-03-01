"""文本组件 —— 显示自定义文字，支持字体大小、颜色、对齐和格数"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QVBoxLayout, QWidget,
    QLabel, QFormLayout,
)
from qfluentwidgets import SpinBox, ComboBox, PlainTextEdit, ColorPickerButton

from app.widgets.base_widget import WidgetBase, WidgetConfig


_ALIGN_MAP = {
    "left":   Qt.AlignmentFlag.AlignLeft   | Qt.AlignmentFlag.AlignVCenter,
    "center": Qt.AlignmentFlag.AlignCenter,
    "right":  Qt.AlignmentFlag.AlignRight  | Qt.AlignmentFlag.AlignVCenter,
}


# ─────────────────────────────────────────────────────────────
# 编辑面板
# ─────────────────────────────────────────────────────────────

class _TextEditPanel(QWidget):
    def __init__(self, props: dict, parent=None):
        super().__init__(parent)
        f = QFormLayout(self)
        f.setVerticalSpacing(10)

        # 文本内容
        self._text_edit = PlainTextEdit()
        self._text_edit.setPlainText(props.get("text", ""))
        self._text_edit.setFixedHeight(80)
        f.addRow("文本内容:", self._text_edit)

        # 字体大小
        self._font_spin = SpinBox()
        self._font_spin.setRange(8, 200)
        self._font_spin.setValue(props.get("font_size", 24))
        self._font_spin.setSuffix(" pt")
        f.addRow("字体大小:", self._font_spin)

        # 文字颜色
        self._color_btn = ColorPickerButton(
            QColor(props.get("color", "#ffffff")), "文字颜色"
        )
        f.addRow("文字颜色:", self._color_btn)

        # 对齐方式
        self._align_combo = ComboBox()
        for label, val in [("居中", "center"), ("左对齐", "left"), ("右对齐", "right")]:
            self._align_combo.addItem(label, userData=val)
        cur = props.get("align", "center")
        idx = next((i for i in range(self._align_combo.count())
                    if self._align_combo.itemData(i) == cur), 0)
        self._align_combo.setCurrentIndex(idx)
        f.addRow("对齐方式:", self._align_combo)

        # 横向格数
        self._w_spin = SpinBox()
        self._w_spin.setRange(1, 20)
        self._w_spin.setValue(props.get("grid_w", 3))
        f.addRow("横向格数:", self._w_spin)

        # 纵向格数
        self._h_spin = SpinBox()
        self._h_spin.setRange(1, 20)
        self._h_spin.setValue(props.get("grid_h", 2))
        f.addRow("纵向格数:", self._h_spin)


    def collect_props(self) -> dict:
        return {
            "text":      self._text_edit.toPlainText(),
            "font_size": self._font_spin.value(),
            "color":     self._color_btn.color.name(),
            "align":     self._align_combo.currentData(),
            "grid_w":    self._w_spin.value(),
            "grid_h":    self._h_spin.value(),
        }


# ─────────────────────────────────────────────────────────────
# TextWidget
# ─────────────────────────────────────────────────────────────

class TextWidget(WidgetBase):
    WIDGET_TYPE = "text"
    WIDGET_NAME = "文本"
    DELETABLE   = True
    DEFAULT_W   = 3
    DEFAULT_H   = 2

    def __init__(self, config: WidgetConfig, services, parent=None):
        super().__init__(config, services, parent)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(0)

        self._lbl = QLabel()
        self._lbl.setWordWrap(True)
        self._lbl.setStyleSheet("background:transparent;")
        root.addWidget(self._lbl, 1)

        self.refresh()

    # ------------------------------------------------------------------ #

    def refresh(self) -> None:
        p = self.config.props
        text      = p.get("text", "")
        font_size = p.get("font_size", 24)
        color     = p.get("color", "#ffffff")
        align     = p.get("align", "center")

        if not text:
            self._lbl.setText("点击右键 → 编辑\n输入文本内容")
            self._lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._lbl.setStyleSheet("color:#444; font-size:13px; background:transparent;")
            return

        self._lbl.setText(text)
        self._lbl.setAlignment(_ALIGN_MAP.get(align, Qt.AlignmentFlag.AlignCenter))
        self._lbl.setStyleSheet(
            f"color:{color}; font-size:{font_size}px; background:transparent;"
        )

    def get_edit_widget(self):
        props = dict(self.config.props)
        props["grid_w"] = self.config.grid_w
        props["grid_h"] = self.config.grid_h
        return _TextEditPanel(props)

    def apply_props(self, props: dict) -> None:
        self.config.props.update(props)
        self.config.grid_w = max(1, int(props.get("grid_w", self.DEFAULT_W)))
        self.config.grid_h = max(1, int(props.get("grid_h", self.DEFAULT_H)))
        self.refresh()

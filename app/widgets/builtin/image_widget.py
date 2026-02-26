"""图片组件 —— 显示本地图片，支持自定义格数"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QWidget,
    QLabel, QFormLayout, QFileDialog,
)
from qfluentwidgets import SpinBox, PushButton, CaptionLabel

from app.widgets.base_widget import WidgetBase, WidgetConfig


# ─────────────────────────────────────────────────────────────
# 编辑面板
# ─────────────────────────────────────────────────────────────

class _ImageEditPanel(QWidget):
    def __init__(self, props: dict, parent=None):
        super().__init__(parent)
        f = QFormLayout(self)
        f.setVerticalSpacing(10)

        # 文件路径显示
        self._path_lbl = CaptionLabel(Path(props.get("path", "")).name or "（未选择）")
        self._path_lbl.setWordWrap(True)
        self._full_path: str = props.get("path", "")

        # 选择文件按钮
        pick_btn = PushButton("选择图片…")
        pick_btn.clicked.connect(self._pick_file)

        path_row = QHBoxLayout()
        path_row.setSpacing(6)
        path_row.addWidget(self._path_lbl, 1)
        path_row.addWidget(pick_btn)

        path_wrap = QWidget()
        path_wrap.setLayout(path_row)
        f.addRow("图片文件:", path_wrap)

        # 横向格数
        self._w_spin = SpinBox()
        self._w_spin.setRange(1, 20)
        self._w_spin.setValue(props.get("grid_w", 3))
        f.addRow("横向格数:", self._w_spin)

        # 纵向格数
        self._h_spin = SpinBox()
        self._h_spin.setRange(1, 20)
        self._h_spin.setValue(props.get("grid_h", 3))
        f.addRow("纵向格数:", self._h_spin)

    def _pick_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择图片",
            str(Path(self._full_path).parent) if self._full_path else "",
            "图片文件 (*.png *.jpg *.jpeg *.bmp *.gif *.webp *.svg);;所有文件 (*)",
        )
        if path:
            self._full_path = path
            self._path_lbl.setText(Path(path).name)

    def collect_props(self) -> dict:
        return {
            "path":   self._full_path,
            "grid_w": self._w_spin.value(),
            "grid_h": self._h_spin.value(),
        }


# ─────────────────────────────────────────────────────────────
# ImageWidget
# ─────────────────────────────────────────────────────────────

class ImageWidget(WidgetBase):
    WIDGET_TYPE = "image"
    WIDGET_NAME = "图片"
    DELETABLE   = True
    DEFAULT_W   = 3
    DEFAULT_H   = 3

    def __init__(self, config: WidgetConfig, services, parent=None):
        super().__init__(config, services, parent)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._img_lbl = QLabel()
        self._img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img_lbl.setScaledContents(True)
        self._img_lbl.setStyleSheet("background:transparent;")
        root.addWidget(self._img_lbl, 1)

        # 未选图片时的提示
        self._hint_lbl = QLabel("点击右键 → 编辑\n选择图片文件")
        self._hint_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint_lbl.setWordWrap(True)
        self._hint_lbl.setStyleSheet("color:#444; font-size:13px; background:transparent;")
        root.addWidget(self._hint_lbl)

        self.refresh()

    # ------------------------------------------------------------------ #

    def refresh(self) -> None:
        path = self.config.props.get("path", "")
        if path and Path(path).is_file():
            pix = QPixmap(path)
            if not pix.isNull():
                self._img_lbl.setPixmap(pix)
                self._img_lbl.show()
                self._hint_lbl.hide()
                return
        self._img_lbl.hide()
        self._hint_lbl.show()

    def get_edit_widget(self):
        props = dict(self.config.props)
        props["grid_w"] = self.config.grid_w
        props["grid_h"] = self.config.grid_h
        return _ImageEditPanel(props)

    def apply_props(self, props: dict) -> None:
        self.config.props.update(props)
        self.config.grid_w = max(1, int(props.get("grid_w", self.DEFAULT_W)))
        self.config.grid_h = max(1, int(props.get("grid_h", self.DEFAULT_H)))
        self.refresh()

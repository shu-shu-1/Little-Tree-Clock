"""小计算器组件"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QVBoxLayout, QGridLayout, QWidget, QLabel, QPushButton,
)

from app.widgets.base_widget import WidgetBase, WidgetConfig


_BTN_STYLE_NUM = (
    "QPushButton{color:white;background:rgba(255,255,255,20);"
    "border-radius:6px;font-size:18px;}"
    "QPushButton:hover{background:rgba(255,255,255,40);}"
    "QPushButton:pressed{background:rgba(255,255,255,60);}"
)
_BTN_STYLE_OP = (
    "QPushButton{color:#f90;background:rgba(255,160,0,30);"
    "border-radius:6px;font-size:18px;}"
    "QPushButton:hover{background:rgba(255,160,0,60);}"
)
_BTN_STYLE_EQ = (
    "QPushButton{color:white;background:rgba(100,180,255,120);"
    "border-radius:6px;font-size:18px;font-weight:bold;}"
    "QPushButton:hover{background:rgba(100,180,255,180);}"
)
_BTN_STYLE_CLR = (
    "QPushButton{color:#f55;background:rgba(255,80,80,30);"
    "border-radius:6px;font-size:16px;}"
    "QPushButton:hover{background:rgba(255,80,80,60);}"
)


class CalculatorWidget(WidgetBase):
    WIDGET_TYPE = "calculator"
    WIDGET_NAME = "小计算器"
    DELETABLE   = True
    DEFAULT_W   = 2
    DEFAULT_H   = 4
    MIN_W       = 2
    MIN_H       = 4

    def __init__(self, config: WidgetConfig, services, parent=None):
        super().__init__(config, services, parent)
        self._expr  = ""    # 当前表达式
        self._error = False

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(4)

        # 显示屏
        self._display = QLabel("0")
        self._display.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._display.setStyleSheet(
            "color:white; font-size:28px; font-weight:200;"
            "background:rgba(0,0,0,40); border-radius:6px; padding:4px 8px;"
        )
        self._display.setMinimumHeight(56)
        root.addWidget(self._display)

        # 按键布局
        grid = QGridLayout()
        grid.setSpacing(4)
        root.addLayout(grid, 1)

        buttons = [
            # (text, row, col, colspan, style_key)
            ("C",   0, 0, 1, "clr"), ("±",  0, 1, 1, "op"),
            ("%",   0, 2, 1, "op"),  ("÷",  0, 3, 1, "op"),
            ("7",   1, 0, 1, "num"), ("8",  1, 1, 1, "num"),
            ("9",   1, 2, 1, "num"), ("×",  1, 3, 1, "op"),
            ("4",   2, 0, 1, "num"), ("5",  2, 1, 1, "num"),
            ("6",   2, 2, 1, "num"), ("−",  2, 3, 1, "op"),
            ("1",   3, 0, 1, "num"), ("2",  3, 1, 1, "num"),
            ("3",   3, 2, 1, "num"), ("+",  3, 3, 1, "op"),
            ("0",   4, 0, 2, "num"), (".",  4, 2, 1, "num"),
            ("=",   4, 3, 1, "eq"),
        ]
        _styles = {"num": _BTN_STYLE_NUM, "op": _BTN_STYLE_OP,
                   "eq": _BTN_STYLE_EQ,  "clr": _BTN_STYLE_CLR}

        for text, row, col, span, style_key in buttons:
            btn = QPushButton(text)
            btn.setStyleSheet(_styles[style_key])
            btn.setMinimumHeight(40)
            btn.clicked.connect(lambda checked=False, t=text: self._on_btn(t))
            grid.addWidget(btn, row, col, 1, span)

    # ------------------------------------------------------------------ #

    def refresh(self) -> None:
        pass  # 计算器无需外部刷新

    def _on_btn(self, text: str) -> None:
        if text == "C":
            self._expr  = ""
            self._error = False
            self._display.setText("0")
            return

        if self._error:
            self._expr  = ""
            self._error = False

        if text == "=":
            try:
                expr = (
                    self._expr
                    .replace("×", "*")
                    .replace("÷", "/")
                    .replace("−", "-")
                )
                result = eval(expr, {"__builtins__": {}})   # noqa: S307
                # 去掉多余小数位
                if isinstance(result, float) and result == int(result):
                    result = int(result)
                self._display.setText(str(result))
                self._expr = str(result)
            except Exception:
                self._display.setText("错误")
                self._expr  = ""
                self._error = True
            return

        if text == "±":
            if self._expr.startswith("-"):
                self._expr = self._expr[1:]
            else:
                self._expr = "-" + self._expr
            self._display.setText(self._expr or "0")
            return

        if text == "%":
            try:
                result = eval(self._expr, {"__builtins__": {}}) / 100  # noqa: S307
                self._expr = str(result)
                self._display.setText(self._expr)
            except Exception:
                pass
            return

        self._expr += text
        self._display.setText(self._expr)

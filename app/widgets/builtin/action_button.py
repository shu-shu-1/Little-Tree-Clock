"""按钮组件 —— 可自定义标签和样式，支持绑定自动化规则"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QVBoxLayout, QWidget, QFormLayout,
)
from qfluentwidgets import (
    ComboBox, LineEdit, SpinBox, PushButton, ColorPickerButton,
)

from app.widgets.base_widget import WidgetBase, WidgetConfig
from app.services.i18n_service import tr


class _ButtonEditPanel(QWidget):
    def __init__(self, props: dict, parent=None):
        super().__init__(parent)
        f = QFormLayout(self)
        f.setVerticalSpacing(10)

        self._text = LineEdit()
        self._text.setText(props.get("text", tr("widget.action_button.default_text")))
        f.addRow(tr("widget.cfg.button_text"), self._text)

        self._mode = ComboBox()
        for key, val in [("widget.btnmode.primary", "primary"), ("widget.btnmode.default", "default"), ("widget.btnmode.text", "text")]:
            self._mode.addItem(tr(key), userData=val)
        cur = props.get("mode", "primary")
        idx = next(
            (i for i in range(self._mode.count())
             if self._mode.itemData(i) == cur), 0
        )
        self._mode.setCurrentIndex(idx)
        f.addRow(tr("widget.cfg.style"), self._mode)

        self._color_btn = ColorPickerButton(
            QColor(props.get("bg_color", "#0078d4")), tr("widget.cfg.bg_color_caption")
        )
        f.addRow(tr("widget.cfg.bg_color"), self._color_btn)

        self._font_size = SpinBox()
        self._font_size.setRange(10, 72)
        self._font_size.setValue(props.get("font_size", 18))
        self._font_size.setSuffix(" pt")
        f.addRow(tr("widget.cfg.font_size"), self._font_size)

        self._action = ComboBox()
        self._action.addItem(tr("widget.action_button.no_action"), userData="none")
        self._action.addItem(tr("widget.action_button.run_automation"), userData="automation")
        cur_action = props.get("action_type", "none")
        idx_a = next(
            (i for i in range(self._action.count())
             if self._action.itemData(i) == cur_action), 0
        )
        self._action.setCurrentIndex(idx_a)
        f.addRow(tr("widget.cfg.click_action"), self._action)

        self._rule_combo = ComboBox()
        self._rule_combo.setEnabled(cur_action == "automation")
        self._rule_combo.addItem(tr("widget.action_button.select_rule"), userData="")
        self._load_rules(props.get("rule_id", ""))
        self._action.currentIndexChanged.connect(
            lambda i: self._rule_combo.setEnabled(
                self._action.itemData(i) == "automation"
            )
        )
        f.addRow(tr("widget.cfg.automation_rule"), self._rule_combo)

        self._grid_w = SpinBox()
        self._grid_w.setRange(1, 20)
        self._grid_w.setValue(props.get("grid_w", 2))
        self._grid_w.setSuffix(tr("widget.cfg.unit_cells"))
        f.addRow(tr("widget.cfg.grid_w"), self._grid_w)

        self._grid_h = SpinBox()
        self._grid_h.setRange(1, 20)
        self._grid_h.setValue(props.get("grid_h", 1))
        self._grid_h.setSuffix(tr("widget.cfg.unit_cells"))
        f.addRow(tr("widget.cfg.grid_h"), self._grid_h)

    def _load_rules(self, current_id: str):
        try:
            from app.models.automation_model import AutomationStore
            store = AutomationStore()
            sel_idx = 0
            for i, rule in enumerate(store.all()):
                self._rule_combo.addItem(rule.name, userData=rule.id)
                if rule.id == current_id:
                    sel_idx = i + 1
            self._rule_combo.setCurrentIndex(sel_idx)
        except Exception:
            pass

    def collect_props(self) -> dict:
        return {
            "text":        self._text.text(),
            "mode":        self._mode.currentData(),
            "bg_color":    self._color_btn.color.name(),
            "font_size":   self._font_size.value(),
            "action_type": self._action.currentData(),
            "rule_id":     self._rule_combo.currentData() or "",
            "grid_w":      self._grid_w.value(),
            "grid_h":      self._grid_h.value(),
        }


_BTN_STYLES = {
    "primary": (
        "QPushButton {{ color:white; background:{bg}; border-radius:8px;"
        " font-size:{fs}px; font-weight:600; padding:8px 16px;"
        " background:transparent; }}"
        "QPushButton:hover {{ background:rgba(255,255,255,30); }}"
        "QPushButton:pressed {{ background:rgba(255,255,255,50); }}"
    ),
    "default": (
        "QPushButton {{ color:white; background:rgba(255,255,255,25);"
        " border:1px solid rgba(255,255,255,60); border-radius:8px;"
        " font-size:{fs}px; padding:8px 16px; background:transparent; }}"
        "QPushButton:hover {{ background:rgba(255,255,255,40); }}"
        "QPushButton:pressed {{ background:rgba(255,255,255,60); }}"
    ),
    "text": (
        "QPushButton {{ color:white; background:transparent;"
        " border:none; font-size:{fs}px; padding:8px 16px; }}"
        "QPushButton:hover {{ background:rgba(255,255,255,20);"
        " border-radius:8px; }}"
        "QPushButton:pressed {{ background:rgba(255,255,255,40);"
        " border-radius:8px; }}"
    ),
}


class ActionButtonWidget(WidgetBase):
    WIDGET_TYPE = "action_button"
    WIDGET_NAME = "按钮"
    DELETABLE = True
    DEFAULT_W = 2
    DEFAULT_H = 1
    MIN_W = 1
    MIN_H = 1

    def __init__(self, config: WidgetConfig, services, parent=None):
        super().__init__(config, services, parent)

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 4, 6, 4)
        root.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._btn = PushButton()
        self._btn.setMinimumHeight(40)
        self._btn.clicked.connect(self._on_click)
        root.addWidget(self._btn)

        self.refresh()

    def _on_click(self):
        p = self.config.props
        action = p.get("action_type", "none")

        if action == "automation":
            rule_id = p.get("rule_id", "")
            if not rule_id:
                return
            engine = self.services.get("automation_engine")
            if engine:
                engine.execute_rule_by_id(rule_id)

    def refresh(self) -> None:
        c = self._wc()
        p = self.config.props
        default_text = tr("widget.action_button.default_text")
        text = p.get("text", default_text) or default_text
        mode = p.get("mode", "primary")
        bg_color = p.get("bg_color", "#0078d4")
        fs = p.get("font_size", 18)

        self._btn.setText(text)

        if mode == "primary":
            self._btn.setStyleSheet(
                f"QPushButton {{ color:white; background:{bg_color};"
                f" border-radius:8px; font-size:{fs}px; font-weight:600;"
                f" padding:8px 16px; }}"
                f"QPushButton:hover {{ background:{_lighten(bg_color)}; }}"
                f"QPushButton:pressed {{ background:{_darken(bg_color)}; }}"
            )
        elif mode == "default":
            self._btn.setStyleSheet(
                f"QPushButton {{ color:{c['btn_text']}; background:{c['btn_bg']};"
                f" border:1px solid {c['border']}; border-radius:8px;"
                f" font-size:{fs}px; padding:8px 16px; }}"
                f"QPushButton:hover {{ background:{c['btn_bg_hover']}; }}"
                f"QPushButton:pressed {{ background:{c['btn_bg_press']}; }}"
            )
        else:
            self._btn.setStyleSheet(
                f"QPushButton {{ color:{c['btn_text']}; background:transparent;"
                f" border:none; font-size:{fs}px; padding:8px 16px; }}"
                f"QPushButton:hover {{ background:{c['btn_bg']};"
                f" border-radius:8px; }}"
                f"QPushButton:pressed {{ background:{c['btn_bg_hover']};"
                f" border-radius:8px; }}"
            )

    def get_edit_widget(self):
        props = dict(self.config.props)
        props["grid_w"] = self.config.grid_w
        props["grid_h"] = self.config.grid_h
        return _ButtonEditPanel(props)

    def apply_props(self, props: dict) -> None:
        self.config.props.update(props)
        self.config.grid_w = max(1, int(props.get("grid_w", self.DEFAULT_W)))
        self.config.grid_h = max(1, int(props.get("grid_h", self.DEFAULT_H)))
        self.refresh()


def _lighten(hex_color: str) -> str:
    try:
        c = QColor(hex_color)
        return c.lighter(130).name()
    except Exception:
        return hex_color


def _darken(hex_color: str) -> str:
    try:
        c = QColor(hex_color)
        return c.darker(130).name()
    except Exception:
        return hex_color

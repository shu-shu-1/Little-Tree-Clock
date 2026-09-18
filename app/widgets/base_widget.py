"""小组件基类 & 配置数据模型"""

from __future__ import annotations

import uuid
from abc import abstractmethod
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Callable, TYPE_CHECKING

from PySide6.QtWidgets import QWidget

if TYPE_CHECKING:
    from qfluentwidgets import FluentIcon as FluentIconBase


@dataclass
class WidgetConfig:
    widget_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    widget_type: str = ""
    group_id: str = ""  # 组合分组标识；空字符串表示未分组
    grid_x: int = 0
    grid_y: int = 0
    grid_w: int = 2
    grid_h: int = 2
    layer: int = 0
    pixel_offset_x: float = 0.0
    pixel_offset_y: float = 0.0
    props: dict = field(default_factory=dict)  # 类型特有的属性

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "WidgetConfig":
        valid = {k for k in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in valid})


class WidgetUpdateMode(str, Enum):
    SYNC = "sync"
    ASYNC = "async"


class WidgetBase(QWidget):
    """所有小组件的基类，子类须定义 WIDGET_TYPE 等类属性并实现 refresh()。"""

    WIDGET_TYPE: str = ""
    WIDGET_NAME: str = "未知组件"
    DELETABLE: bool = True
    UPDATE_MODE: WidgetUpdateMode = WidgetUpdateMode.SYNC
    RUNS_IN_BACKGROUND: bool = False
    MIN_W: int = 1
    MIN_H: int = 1
    DEFAULT_W: int = 2
    DEFAULT_H: int = 2

    # 窗口化（分离窗口）时的背景展示方式
    DETACHED_BG_MODE: str = "auto"  # "auto" | "transparent" | "minimal" | "solid"
    DETACHED_BG_SHAPE: str = "rect"  # "rect" | "ellipse"
    DETACHED_BG_COLOR: str | None = None  # 如 "#1e1e1e" 或 "rgba(30,30,30,180)"
    DETACHED_BG_RADIUS: int = 8  # 背景圆角半径（仅 rect 形状）
    DETACHED_BORDER_COLOR: str | None = None  # 边框颜色
    DETACHED_BORDER_WIDTH: int = 1  # 边框宽度（px）

    def __init__(self, config: WidgetConfig, services: dict[str, Any], parent=None):
        super().__init__(parent)
        self.config = config
        self.services = services
        self.setStyleSheet("background: transparent;")

    @abstractmethod
    def refresh(self) -> None:
        """刷新显示内容（每秒由画布调用）"""

    @classmethod
    def uses_async_updates(cls) -> bool:
        return cls.UPDATE_MODE == WidgetUpdateMode.ASYNC

    @classmethod
    def runs_in_background(cls) -> bool:
        return bool(cls.RUNS_IN_BACKGROUND)

    @classmethod
    def keeps_running_in_background(cls) -> bool:
        return cls.runs_in_background()

    def on_background_detached(self, services: dict[str, Any] | None = None) -> None:
        """画布关闭但组件继续后台运行时调用。"""
        if services is not None:
            self.services = services

    def on_background_attached(self, services: dict[str, Any]) -> None:
        """后台组件重新挂回画布时调用。"""
        self.services = services

    def get_edit_widget(self) -> QWidget | None:
        """返回编辑面板 QWidget；None 表示不支持编辑"""
        return None

    def apply_props(self, props: dict) -> None:
        self.config.props.update(props)
        self.refresh()

    # ------------------------------------------------------------------ #
    # 右键菜单扩展
    # ------------------------------------------------------------------ #

    def get_context_menu_actions(self) -> list[tuple[str, "FluentIconBase", Callable]]:
        """返回 (文本, 图标, 回调) 菜单项列表，显示在默认菜单项之前；子类可重写。"""
        return []

    def _wc(self) -> dict[str, str]:
        from app.utils.theme_utils import widget_colors

        return widget_colors(self.services.get("zone_id"))

    def _is_dark(self) -> bool:
        from app.utils.theme_utils import is_widget_dark

        return is_widget_dark(self.services.get("zone_id"))

"""小组件基类 & 配置数据模型"""
from __future__ import annotations

import uuid
from abc import abstractmethod
from dataclasses import dataclass, field, asdict
from typing import Optional, Any, Callable, List, Tuple, TYPE_CHECKING

from PySide6.QtWidgets import QWidget

if TYPE_CHECKING:
    from qfluentwidgets import FluentIcon as FluentIconBase


@dataclass
class WidgetConfig:
    """单个小组件在画布上的位置、尺寸及属性"""
    widget_id:   str  = field(default_factory=lambda: str(uuid.uuid4()))
    widget_type: str  = ""
    group_id:    str  = ""  # 组合分组标识；空字符串表示未分组
    grid_x:      int  = 0
    grid_y:      int  = 0
    grid_w:      int  = 2
    grid_h:      int  = 2
    props:       dict = field(default_factory=dict)  # 类型特有的属性

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "WidgetConfig":
        valid = {k for k in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in valid})


class WidgetBase(QWidget):
    """所有小组件的基类。

    子类须提供:
    - WIDGET_TYPE: str   —— 唯一类型标识
    - WIDGET_NAME: str   —— 显示名称
    - MIN_W / MIN_H      —— 最小格数
    - DEFAULT_W / DEFAULT_H
    - DELETABLE: bool    —— 是否可被用户删除
    - refresh()          —— 刷新内容
    - get_edit_widget()  —— 返回编辑面板（None 表示不可编辑）
    - apply_props()      —— 将编辑面板的修改写入 config.props 并刷新
    """

    WIDGET_TYPE:  str  = ""
    WIDGET_NAME:  str  = "未知组件"
    DELETABLE:    bool = True
    MIN_W:        int  = 1
    MIN_H:        int  = 1
    DEFAULT_W:    int  = 2
    DEFAULT_H:    int  = 2

    def __init__(self, config: WidgetConfig, services: dict[str, Any], parent=None):
        super().__init__(parent)
        self.config   = config
        self.services = services
        self.setStyleSheet("background: transparent;")

    @abstractmethod
    def refresh(self) -> None:
        """刷新显示内容（每秒由画布调用）"""

    def get_edit_widget(self) -> Optional[QWidget]:
        """返回编辑面板 QWidget；None 表示不支持编辑"""
        return None

    def apply_props(self, props: dict) -> None:
        """将编辑面板返回的 props 写入 config 并刷新"""
        self.config.props.update(props)
        self.refresh()

    # ------------------------------------------------------------------ #
    # 右键菜单扩展
    # ------------------------------------------------------------------ #

    def get_context_menu_actions(self) -> List[Tuple[str, "FluentIconBase", Callable]]:
        """返回组件自定义的右键菜单项列表。

        子类可重写此方法以添加自定义菜单项。返回的菜单项会显示在
        默认菜单项（编辑、分离窗口、删除）之前。

        Returns
        -------
        List[Tuple[str, FluentIcon, Callable]]
            菜单项列表，每项为 (文本, 图标, 回调函数) 元组。
            图标可以是 ``qfluentwidgets.FluentIcon`` 枚举值或 ``None``。

        示例
        ----
        .. code-block:: python

            from qfluentwidgets import FluentIcon as FIF

            class MyWidget(WidgetBase):
                def get_context_menu_actions(self):
                    return [
                        ("刷新", FIF.SYNC, self._on_refresh),
                        ("分享", FIF.SHARE, self._on_share),
                    ]

                def _on_refresh(self):
                    self.refresh()

                def _on_share(self):
                    # 分享逻辑
                    pass
        """
        return []

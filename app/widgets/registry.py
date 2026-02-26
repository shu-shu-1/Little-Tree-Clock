"""小组件注册表 —— 全局单例，内置 + 插件均向此处注册"""
from __future__ import annotations

from typing import Type, Any

from app.widgets.base_widget import WidgetBase, WidgetConfig


class WidgetRegistry:
    """全局小组件注册表（单例）。

    用法：
        WidgetRegistry.instance().register(MyWidget)
        cls = WidgetRegistry.instance().get("my_widget")
        widget = cls(config, services)
    """
    _instance: "WidgetRegistry | None" = None

    def __init__(self):
        self._registry: dict[str, Type[WidgetBase]] = {}

    @classmethod
    def instance(cls) -> "WidgetRegistry":
        if cls._instance is None:
            cls._instance = cls()
            cls._instance._register_builtins()
        return cls._instance

    # ------------------------------------------------------------------ #

    def register(self, widget_cls: Type[WidgetBase]) -> None:
        """注册一个小组件类型"""
        assert widget_cls.WIDGET_TYPE, "WIDGET_TYPE 不能为空"
        self._registry[widget_cls.WIDGET_TYPE] = widget_cls

    def unregister(self, widget_type: str) -> None:
        """移除一个小组件类型的注册（插件卸载时调用）"""
        self._registry.pop(widget_type, None)

    def get(self, widget_type: str) -> Type[WidgetBase] | None:
        return self._registry.get(widget_type)

    def all_types(self) -> list[tuple[str, str]]:
        """返回 [(type_id, display_name), ...]，供"添加组件"菜单使用"""
        return [(t, cls.WIDGET_NAME) for t, cls in self._registry.items()]

    def create(
        self,
        config: WidgetConfig,
        services: dict[str, Any],
        parent=None,
    ) -> WidgetBase | None:
        """根据 config.widget_type 创建实例，找不到则返回 None"""
        cls = self._registry.get(config.widget_type)
        if cls is None:
            return None
        inst = cls(config, services, parent)
        inst.refresh()
        return inst

    # ------------------------------------------------------------------ #
    # 内置小组件注册
    # ------------------------------------------------------------------ #

    def _register_builtins(self) -> None:
        from app.widgets.builtin.clock        import ClockWidget
        from app.widgets.builtin.timer_list   import TimerListWidget
        from app.widgets.builtin.alarm_list   import AlarmListWidget
        from app.widgets.builtin.world_time   import WorldTimeWidget
        from app.widgets.builtin.calendar     import CalendarWidget
        from app.widgets.builtin.countdown    import CountdownWidget
        from app.widgets.builtin.countup      import CountupWidget
        from app.widgets.builtin.calculator   import CalculatorWidget
        from app.widgets.builtin.image_widget import ImageWidget
        from app.widgets.builtin.text_widget  import TextWidget

        for cls in [
            ClockWidget,
            TimerListWidget,
            AlarmListWidget,
            WorldTimeWidget,
            CalendarWidget,
            CountdownWidget,
            CountupWidget,
            CalculatorWidget,
            ImageWidget,
            TextWidget,
        ]:
            self.register(cls)

"""通用验证器和工具函数"""
from __future__ import annotations

from typing import Any, Callable, TypeVar, Optional, Union

T = TypeVar("T")


def clamp_int(value: Any, min_val: int, max_val: int, default: int) -> int:
    """将值限制在指定范围内（整数）。

    Args:
        value: 要限制的值
        min_val: 最小值
        max_val: 最大值
        default: 转换失败时的默认值

    Returns:
        限制后的整数值
    """
    try:
        return max(min_val, min(max_val, int(value)))
    except (ValueError, TypeError):
        return default


def clamp_float(value: Any, min_val: float, max_val: float, default: float) -> float:
    """将值限制在指定范围内（浮点数）。

    Args:
        value: 要限制的值
        min_val: 最小值
        max_val: 最大值
        default: 转换失败时的默认值

    Returns:
        限制后的浮点值
    """
    try:
        return max(min_val, min(max_val, float(value)))
    except (ValueError, TypeError):
        return default


def validate_enum(value: Any, enum_class: type, default: T) -> T:
    """验证值是否为枚举类的有效成员。

    Args:
        value: 要验证的值
        enum_class: 枚举类
        default: 无效时的默认值

    Returns:
        枚举值或默认值
    """
    try:
        return enum_class(value)
    except (ValueError, TypeError):
        return default


def safe_get(dictionary: dict, *keys: str, default: Any = None) -> Any:
    """安全地获取嵌套字典中的值。

    Args:
        dictionary: 源字典
        *keys: 嵌套键路径
        default: 键不存在时的默认值

    Returns:
        嵌套值或默认值
    """
    node = dictionary
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return node


def safe_json_loads(text: str, default: Any = None) -> Any:
    """安全地解析 JSON 字符串。

    Args:
        text: JSON 字符串
        default: 解析失败时的默认值

    Returns:
        解析后的对象或默认值
    """
    import json
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        return default


def safe_call(func: Callable, *args, default: Any = None, **kwargs) -> Any:
    """安全地调用函数，捕获所有异常。

    Args:
        func: 要调用的函数
        *args: 位置参数
        default: 调用失败时的默认值
        **kwargs: 关键字参数

    Returns:
        函数返回值或默认值
    """
    try:
        return func(*args, **kwargs)
    except Exception:
        return default


def safe_cast(value: Any, target_type: type[T], default: T) -> T:
    """安全地将值转换为目标类型。

    Args:
        value: 要转换的值
        target_type: 目标类型
        default: 转换失败时的默认值

    Returns:
        转换后的值或默认值
    """
    try:
        return target_type(value)
    except (ValueError, TypeError):
        return default


def validate_path(path: Any, must_exist: bool = False) -> Optional[str]:
    """验证并规范化路径字符串。

    Args:
        path: 路径值
        must_exist: 是否必须存在

    Returns:
        规范化后的路径字符串，无效返回 None
    """
    from pathlib import Path

    try:
        if path is None:
            return None
        p = Path(str(path).strip().strip('"'))
        if must_exist and not p.exists():
            return None
        return str(p)
    except (OSError, ValueError):
        return None


def validate_range(value: Any, valid_values: set | list, default: Any) -> Any:
    """验证值是否在有效集合中。

    Args:
        value: 要验证的值
        valid_values: 有效值集合
        default: 无效时的默认值

    Returns:
        原值或默认值
    """
    if value in valid_values:
        return value
    return default


def lazy_property(func: Callable) -> property:
    """延迟属性装饰器 - 属性只在首次访问时计算。

    使用示例::

        @lazy_property
        def expensive_computation(self):
            return expensive_function()
    """
    attr_name = f"_lazy_{func.__name__}"

    @property
    def wrapper(self):
        if not hasattr(self, attr_name):
            setattr(self, attr_name, func(self))
        return getattr(self, attr_name)

    return wrapper


class Singleton:
    """单例模式基类。

    使用示例::

        class MyService(Singleton):
            pass
    """

    _instance: Optional["Singleton"] = None

    def __new__(cls) -> "Singleton":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """重置单例实例（主要用于测试）。"""
        cls._instance = None


class CallbackList:
    """线程安全的事件回调列表管理器。

    使用示例::

        callbacks = CallbackList()

        def handler():
            print("called")

        callbacks.add(handler)
        callbacks.emit()  # 调用所有回调
        callbacks.remove(handler)
    """

    def __init__(self):
        from threading import RLock
        self._callbacks: list[Callable] = []
        self._lock = RLock()

    def add(self, callback: Callable) -> None:
        """添加回调函数。"""
        with self._lock:
            if callback not in self._callbacks:
                self._callbacks.append(callback)

    def remove(self, callback: Callable) -> None:
        """移除回调函数。"""
        with self._lock:
            self._callbacks = [c for c in self._callbacks if c is not callback]

    def emit(self, *args, **kwargs) -> list:
        """调用所有回调并返回结果列表。"""
        with self._lock:
            callbacks = list(self._callbacks)

        results = []
        for cb in callbacks:
            try:
                results.append(cb(*args, **kwargs))
            except Exception:
                import logging
                logging.exception(f"Callback {cb.__name__} failed")
        return results

    def clear(self) -> None:
        """清空所有回调。"""
        with self._lock:
            self._callbacks.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._callbacks)

    def __bool__(self) -> bool:
        with self._lock:
            return bool(self._callbacks)

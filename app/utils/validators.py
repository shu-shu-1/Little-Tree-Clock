"""通用验证器和工具函数"""

from __future__ import annotations

from typing import Any, Callable, TypeVar

T = TypeVar("T")


def clamp_int(value: Any, min_val: int, max_val: int, default: int) -> int:
    try:
        return max(min_val, min(max_val, int(value)))
    except (ValueError, TypeError):
        return default


def clamp_float(value: Any, min_val: float, max_val: float, default: float) -> float:
    try:
        return max(min_val, min(max_val, float(value)))
    except (ValueError, TypeError):
        return default


def validate_enum(value: Any, enum_class: type, default: T) -> T:
    try:
        return enum_class(value)
    except (ValueError, TypeError):
        return default


def safe_get(dictionary: dict, *keys: str, default: Any = None) -> Any:
    node = dictionary
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return node


def safe_json_loads(text: str, default: Any = None) -> Any:
    import json

    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        return default


def safe_call(func: Callable, *args, default: Any = None, **kwargs) -> Any:
    try:
        return func(*args, **kwargs)
    except Exception:
        return default


def safe_cast(value: Any, target_type: type[T], default: T) -> T:
    try:
        return target_type(value)
    except (ValueError, TypeError):
        return default


def validate_path(path: Any, must_exist: bool = False) -> str | None:
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
    if value in valid_values:
        return value
    return default


def lazy_property(func: Callable) -> property:
    """属性只在首次访问时计算。"""
    attr_name = f"_lazy_{func.__name__}"

    @property
    def wrapper(self):
        if not hasattr(self, attr_name):
            setattr(self, attr_name, func(self))
        return getattr(self, attr_name)

    return wrapper


class Singleton:
    """单例模式基类。"""

    _instance: "Singleton | None" = None

    def __new__(cls) -> "Singleton":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        cls._instance = None


class CallbackList:
    """线程安全的事件回调列表管理器。"""

    def __init__(self):
        from threading import RLock

        self._callbacks: list[Callable] = []
        self._lock = RLock()

    def add(self, callback: Callable) -> None:
        with self._lock:
            if callback not in self._callbacks:
                self._callbacks.append(callback)

    def remove(self, callback: Callable) -> None:
        with self._lock:
            self._callbacks = [c for c in self._callbacks if c is not callback]

    def emit(self, *args, **kwargs) -> list:
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
        with self._lock:
            self._callbacks.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._callbacks)

    def __bool__(self) -> bool:
        with self._lock:
            return bool(self._callbacks)

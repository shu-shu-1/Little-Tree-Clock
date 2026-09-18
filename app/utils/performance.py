"""性能监控和缓存工具"""

from __future__ import annotations

import functools
import time
from collections import OrderedDict
from typing import Any, Callable, Generic, TypeVar
from contextlib import contextmanager

from app.utils.logger import logger

T = TypeVar("T")


class LRUCache(Generic[T]):
    """LRU 缓存实现。"""

    def __init__(self, maxsize: int = 128):
        self._maxsize = maxsize
        self._cache: OrderedDict = OrderedDict()
        self._hits = 0
        self._misses = 0

    def get(self, key: str, default: T | None = None) -> T | None:
        if key in self._cache:
            self._hits += 1
            self._cache.move_to_end(key)
            return self._cache[key]
        self._misses += 1
        return default

    def set(self, key: str, value: T) -> None:
        if key in self._cache:
            self._cache.move_to_end(key)
        self._cache[key] = value

        while len(self._cache) > self._maxsize:
            self._cache.popitem(last=False)

    def delete(self, key: str) -> bool:
        if key in self._cache:
            del self._cache[key]
            return True
        return False

    def clear(self) -> None:
        self._cache.clear()
        self._hits = 0
        self._misses = 0

    @property
    def size(self) -> int:
        return len(self._cache)

    @property
    def hit_rate(self) -> float:
        total = self._hits + self._misses
        return self._hits / total if total > 0 else 0.0

    def __contains__(self, key: str) -> bool:
        return key in self._cache

    def __len__(self) -> int:
        return len(self._cache)

    def __repr__(self) -> str:
        return f"LRUCache(size={self.size}, maxsize={self._maxsize}, hit_rate={self.hit_rate:.2%})"


def lru_cache(maxsize: int = 128, ttl: float | None = None):
    """带 TTL 的 LRU 缓存装饰器。"""

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        cache: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        _hits = 0
        _misses = 0

        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            nonlocal _hits, _misses

            key = f"{func.__name__}:{args}:{sorted(kwargs.items())}"

            current_time = time.time()

            if key in cache:
                value, timestamp = cache[key]
                if ttl is None or (current_time - timestamp) < ttl:
                    _hits += 1
                    cache.move_to_end(key)
                    return value
                else:
                    del cache[key]

            _misses += 1

            try:
                result = func(*args, **kwargs)
            except Exception:
                logger.exception(f"lru_cache 包装的函数 {func.__name__} 执行失败")
                raise

            cache[key] = (result, current_time)
            cache.move_to_end(key)

            while len(cache) > maxsize:
                cache.popitem(last=False)

            return result

        def clear_cache() -> None:
            cache.clear()
            nonlocal _hits, _misses
            _hits = 0
            _misses = 0

        wrapper.cache_info = lambda: {
            "size": len(cache),
            "maxsize": maxsize,
            "hits": _hits,
            "misses": _misses,
            "hit_rate": _hits / (_hits + _misses) if (_hits + _misses) > 0 else 0,
        }
        wrapper.clear_cache = clear_cache

        return wrapper

    return decorator


def timed_cache(maxsize: int = 128):
    """缓存函数结果并统计调用耗时。"""

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        cache: OrderedDict[str, tuple[T, float, float]] = OrderedDict()
        _total_calls = 0
        _total_time = 0.0

        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            nonlocal _total_calls, _total_time

            key = f"{func.__name__}:{args}:{sorted(kwargs.items())}"
            _total_calls += 1

            if key in cache:
                value, _, _ = cache[key]
                cache.move_to_end(key)
                return value

            start = time.perf_counter()
            try:
                result = func(*args, **kwargs)
            finally:
                elapsed = time.perf_counter() - start
                _total_time += elapsed

            cache[key] = (result, elapsed, time.time())
            cache.move_to_end(key)

            while len(cache) > maxsize:
                cache.popitem(last=False)

            return result

        def clear_cache() -> None:
            cache.clear()

        def get_stats() -> dict:
            avg_time = _total_time / _total_calls if _total_calls > 0 else 0
            return {
                "total_calls": _total_calls,
                "total_time": _total_time,
                "avg_time": avg_time,
                "cache_size": len(cache),
            }

        wrapper.cache_info = get_stats
        wrapper.clear_cache = clear_cache

        return wrapper

    return decorator


@contextmanager
def timer(name: str = "", log: bool = True):
    """计时上下文管理器，yield 一个返回已耗时的函数。"""
    start = time.perf_counter()
    try:
        yield lambda: time.perf_counter() - start
    finally:
        elapsed = time.perf_counter() - start
        if log:
            if name:
                logger.debug(f"[计时] {name}: {elapsed * 1000:.2f}ms")
            else:
                logger.debug(f"[计时] 耗时: {elapsed * 1000:.2f}ms")


class PerformanceMonitor:
    """性能监控器 - 跟踪函数调用性能。"""

    def __init__(self):
        self._stats: dict[str, dict] = {}

    def track(self, func: Callable[..., T]) -> Callable[..., T]:
        func_name = func.__qualname__

        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            start = time.perf_counter()
            try:
                return func(*args, **kwargs)
            finally:
                elapsed = time.perf_counter() - start
                self._record(func_name, elapsed)

        return wrapper

    def _record(self, func_name: str, elapsed: float) -> None:
        if func_name not in self._stats:
            self._stats[func_name] = {
                "count": 0,
                "total": 0.0,
                "min": float("inf"),
                "max": 0.0,
            }

        stats = self._stats[func_name]
        stats["count"] += 1
        stats["total"] += elapsed
        stats["min"] = min(stats["min"], elapsed)
        stats["max"] = max(stats["max"], elapsed)

    def get_stats(self, func_name: str | None = None) -> dict:
        if func_name:
            stats = self._stats.get(func_name)
            if stats:
                return {
                    "count": stats["count"],
                    "total": stats["total"],
                    "avg": stats["total"] / stats["count"] if stats["count"] > 0 else 0,
                    "min": stats["min"],
                    "max": stats["max"],
                }
            return {}

        result = {}
        for name, stats in self._stats.items():
            result[name] = {
                "count": stats["count"],
                "total": stats["total"],
                "avg": stats["total"] / stats["count"] if stats["count"] > 0 else 0,
                "min": stats["min"],
                "max": stats["max"],
            }
        return result

    def reset(self) -> None:
        self._stats.clear()

    def report(self, top_n: int = 10) -> str:
        stats = self.get_stats()
        if not stats:
            return "无性能数据"

        sorted_stats = sorted(stats.items(), key=lambda x: x[1]["total"], reverse=True)[:top_n]

        lines = ["性能报告 (Top {}):".format(len(sorted_stats)), "-" * 50]
        for name, s in sorted_stats:
            lines.append(
                f"  {name}:\n"
                f"    调用次数: {s['count']}\n"
                f"    总耗时: {s['total'] * 1000:.2f}ms\n"
                f"    平均耗时: {s['avg'] * 1000:.2f}ms\n"
                f"    最小/最大: {s['min'] * 1000:.2f}ms / {s['max'] * 1000:.2f}ms"
            )

        return "\n".join(lines)


_global_monitor = PerformanceMonitor()


def get_performance_monitor() -> PerformanceMonitor:
    return _global_monitor


def profile(func: Callable[..., T]) -> Callable[..., T]:
    return _global_monitor.track(func)


__all__ = [
    "LRUCache",
    "lru_cache",
    "timed_cache",
    "timer",
    "PerformanceMonitor",
    "get_performance_monitor",
    "profile",
]

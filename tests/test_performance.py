"""app.utils.performance 单元测试"""

from __future__ import annotations

import time

import pytest

from app.utils.performance import (
    LRUCache,
    PerformanceMonitor,
    lru_cache,
    timed_cache,
    timer,
)


class TestLRUCache:
    def test_set_get(self):
        cache: LRUCache[str] = LRUCache(maxsize=3)
        cache.set("a", 1)
        assert cache.get("a") == 1
        assert cache.size == 1

    def test_get_missing_returns_default(self):
        cache: LRUCache[str] = LRUCache()
        assert cache.get("nope") is None
        assert cache.get("nope", default="d") == "d"

    def test_eviction_order(self):
        cache: LRUCache[str] = LRUCache(maxsize=2)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)  # 挤掉最旧的 a
        assert "a" not in cache
        assert cache.get("b") == 2
        assert cache.get("c") == 3

    def test_get_refreshes_recency(self):
        cache: LRUCache[str] = LRUCache(maxsize=2)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.get("a")  # a 变为最近使用
        cache.set("c", 3)  # 应挤掉 b
        assert "b" not in cache
        assert cache.get("a") == 1

    def test_delete(self):
        cache: LRUCache[str] = LRUCache()
        cache.set("a", 1)
        assert cache.delete("a") is True
        assert cache.delete("a") is False

    def test_clear_resets_stats(self):
        cache: LRUCache[str] = LRUCache()
        cache.set("a", 1)
        cache.get("a")
        cache.get("miss")
        cache.clear()
        assert cache.size == 0
        assert cache.hit_rate == 0.0

    def test_hit_rate(self):
        cache: LRUCache[str] = LRUCache()
        cache.set("a", 1)
        cache.get("a")
        cache.get("a")
        cache.get("miss")
        assert cache.hit_rate == pytest.approx(2 / 3)

    def test_len_and_contains(self):
        cache: LRUCache[str] = LRUCache()
        cache.set("a", 1)
        assert len(cache) == 1
        assert "a" in cache


class TestLruCacheDecorator:
    def test_caches_result(self):
        calls = []

        @lru_cache(maxsize=10)
        def add(a, b):
            calls.append((a, b))
            return a + b

        assert add(1, 2) == 3
        assert add(1, 2) == 3
        assert calls == [(1, 2)]

    def test_kwargs_and_args_keyed_separately(self):
        calls = []

        @lru_cache(maxsize=10)
        def f(a, b=0):
            calls.append((a, b))
            return a + b

        f(1, b=2)
        f(1, 2)  # 不同缓存键
        assert len(calls) == 2

    def test_maxsize_eviction(self):
        calls = []

        @lru_cache(maxsize=2)
        def f(x):
            calls.append(x)
            return x

        f(1)
        f(2)
        f(3)  # 挤掉 1
        f(1)  # 未命中，重新计算
        assert calls == [1, 2, 3, 1]

    def test_ttl_expiry(self, monkeypatch):
        now = {"t": 1000.0}
        monkeypatch.setattr(time, "time", lambda: now["t"])
        calls = []

        @lru_cache(maxsize=10, ttl=10)
        def f(x):
            calls.append(x)
            return x

        f(1)
        now["t"] = 1005.0
        f(1)  # 未过期
        now["t"] = 1011.0
        f(1)  # 已过期，重新计算
        assert calls == [1, 1]

    def test_cache_info_and_clear(self):
        @lru_cache(maxsize=4)
        def f(x):
            return x

        f(1)
        f(1)
        info = f.cache_info()
        assert info["size"] == 1
        assert info["hits"] == 1
        assert info["misses"] == 1
        assert info["hit_rate"] == pytest.approx(0.5)

        f.clear_cache()
        assert f.cache_info() == {
            "size": 0,
            "maxsize": 4,
            "hits": 0,
            "misses": 0,
            "hit_rate": 0,
        }

    def test_exception_propagates_and_not_cached(self):
        calls = []

        @lru_cache(maxsize=4)
        def f(x):
            calls.append(x)
            raise ValueError("boom")

        with pytest.raises(ValueError):
            f(1)
        with pytest.raises(ValueError):
            f(1)
        assert calls == [1, 1]


class TestTimedCache:
    def test_caches_result(self):
        calls = []

        @timed_cache(maxsize=10)
        def f(x):
            calls.append(x)
            return x * 2

        assert f(2) == 4
        assert f(2) == 4
        assert calls == [2]

    def test_stats(self):
        @timed_cache(maxsize=10)
        def f(x):
            return x

        f(1)
        f(1)
        stats = f.cache_info()
        assert stats["total_calls"] == 2
        assert stats["cache_size"] == 1


class TestTimer:
    def test_timer_yields_elapsed_callable(self):
        with timer("test", log=False) as elapsed:
            acc = 0
            for i in range(10_000):
                acc += i
        assert callable(elapsed)
        assert elapsed() >= 0

    def test_timer_logs(self):
        # 不抛异常即可（loguru sink 已配置）
        with timer():
            pass


class TestPerformanceMonitor:
    def test_track_records_stats(self):
        monitor = PerformanceMonitor()

        @monitor.track
        def f(x):
            return x + 1

        f(1)
        f(2)
        stats = monitor.get_stats("TestPerformanceMonitor.test_track_records_stats.<locals>.f")
        assert stats["count"] == 2
        assert stats["min"] <= stats["avg"] <= stats["max"]

    def test_get_stats_unknown_function(self):
        monitor = PerformanceMonitor()
        assert monitor.get_stats("nope") == {}

    def test_reset(self):
        monitor = PerformanceMonitor()

        @monitor.track
        def f():
            return None

        f()
        monitor.reset()
        assert monitor.get_stats() == {}

    def test_report(self):
        monitor = PerformanceMonitor()

        @monitor.track
        def f():
            return None

        f()
        report = monitor.report()
        assert "性能报告" in report
        assert "f" in report

    def test_report_empty(self):
        assert "无性能数据" in PerformanceMonitor().report()

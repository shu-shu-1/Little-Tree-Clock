"""全局日志配置 — 基于 loguru"""

import sys
from collections import deque
from pathlib import Path
from threading import RLock
from typing import Callable
from loguru import logger


class _MemoryLog:
    """线程安全的环形缓冲日志仓库。"""

    def __init__(self, maxlen: int = 2000):
        self._buf: deque[dict] = deque(maxlen=maxlen)
        self._lock = RLock()
        self._subscribers: set[Callable[[dict], None]] = set()

    def write(self, message) -> None:
        """loguru sink 回调，message 带有 .record 元数据。"""
        rec = message.record
        item = {
            "level": message.record["level"].name,
            "text": str(message).rstrip(),
            "time": rec["time"].strftime("%H:%M:%S.%f")[:-3],
            "name": rec["name"],
            "line": rec["line"],
            "message": rec["message"],
        }

        with self._lock:
            self._buf.append(item)
            subscribers = tuple(self._subscribers)

        for callback in subscribers:
            try:
                callback(item)
            except Exception:
                # 订阅者异常不能影响日志主流程
                pass

    def get(self, level: str = "") -> list[dict]:
        with self._lock:
            snapshot = list(self._buf)
        if level:
            return [r for r in snapshot if r["level"] == level]
        return snapshot

    def subscribe(self, callback: Callable[[dict], None]) -> None:
        with self._lock:
            self._subscribers.add(callback)

    def unsubscribe(self, callback: Callable[[dict], None]) -> None:
        with self._lock:
            self._subscribers.discard(callback)

    def clear(self) -> None:
        with self._lock:
            self._buf.clear()


memory_log = _MemoryLog()

# 避免重复初始化（热重载场景）
if not hasattr(logger, "_clock_initialized"):
    logger.remove()

    # 控制台 — 彩色，DEBUG 及以上；打包后 sys.stderr 可能为 None
    if sys.stderr is not None:
        logger.add(
            sys.stderr,
            level="DEBUG",
            colorize=True,
            format=(
                "<green>{time:HH:mm:ss}</green> "
                "| <level>{level:<8}</level> "
                "| <cyan>{name}</cyan>:<cyan>{line}</cyan> "
                "— <level>{message}</level>"
            ),
        )

    # 文件 — 每天轮转，保留 7 天，DEBUG 及以上
    from app.constants import LOGS_DIR

    Path(LOGS_DIR).mkdir(parents=True, exist_ok=True)

    logger.add(
        str(Path(LOGS_DIR) / "clock_{time:YYYY-MM-DD}.log"),
        level="DEBUG",
        rotation="00:00",
        retention="7 days",
        encoding="utf-8",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | {name}:{line} — {message}",
    )

    # 内存 sink — 无颜色转义，便于 UI 直接显示
    logger.add(
        memory_log.write,
        level="DEBUG",
        format="{time:HH:mm:ss.SSS} | {level:<8} | {name}:{line} — {message}",
        colorize=False,
    )

    object.__setattr__(logger, "_clock_initialized", True)

__all__ = ["logger", "memory_log"]

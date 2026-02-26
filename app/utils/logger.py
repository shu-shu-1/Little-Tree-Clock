"""全局日志配置 — 基于 loguru

使用方式（任意模块）::

    from app.utils.logger import logger
    logger.info("消息")
    logger.debug("调试")
    logger.warning("警告")
    logger.error("错误")

内存日志（供调试面板实时读取）::

    from app.utils.logger import memory_log
    records = memory_log.get()   # -> list[dict]  每条含 level / text
"""
import sys
from collections import deque
from pathlib import Path
from loguru import logger


# ────────────────────────────────────────────────────────────────────────── #
# 内存 sink —— 保留最近 2000 条，供调试面板实时查看
# ────────────────────────────────────────────────────────────────────────── #

class _MemoryLog:
    """线程安全的环形缓冲日志仓库。"""

    def __init__(self, maxlen: int = 2000):
        self._buf: deque[dict] = deque(maxlen=maxlen)

    def write(self, message) -> None:
        """loguru sink 回调，message 带有 .record 元数据。"""
        self._buf.append({
            "level": message.record["level"].name,
            "text":  str(message).rstrip(),
        })

    def get(self, level: str = "") -> list[dict]:
        """返回所有记录；level 非空时仅返回匹配级别。"""
        if level:
            return [r for r in self._buf if r["level"] == level]
        return list(self._buf)

    def clear(self) -> None:
        self._buf.clear()


memory_log = _MemoryLog()

# 避免重复初始化（热重载场景）
if not hasattr(logger, "_clock_initialized"):
    logger.remove()  # 移除 loguru 默认 stderr sink

    # ------------------------------------------------------------------ #
    # 控制台 — 彩色，DEBUG 及以上（打包后 sys.stderr 可能为 None，跳过）
    # ------------------------------------------------------------------ #
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

    # ------------------------------------------------------------------ #
    # 文件 — 每天轮转，保留 7 天，DEBUG 及以上
    # ------------------------------------------------------------------ #
    _LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs"
    _LOG_DIR.mkdir(parents=True, exist_ok=True)

    logger.add(
        str(_LOG_DIR / "clock_{time:YYYY-MM-DD}.log"),
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

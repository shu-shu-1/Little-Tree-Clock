"""时间工具函数"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.utils.fs import write_text_with_uac
from app.utils.logger import logger
from app.utils.performance import lru_cache

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo


@lru_cache(maxsize=32, ttl=60)
def _get_zone_info(iana_name: str) -> timezone | None:
    try:
        if iana_name == "local":
            return None  # 表示使用本地时区
        return ZoneInfo(iana_name)
    except (KeyError, ValueError):
        return None


def _ntp_utc_now() -> datetime:
    """返回 UTC 当前时间，叠加 NTP 校正与手动时间偏移；延迟导入服务避免循环依赖。"""
    base = datetime.now(timezone.utc)

    try:
        from app.services.ntp_service import NtpService

        svc = NtpService.instance()
        if svc.enabled and svc.last_sync_ts is not None:
            base = svc.now()
    except (ImportError, AttributeError, RuntimeError):
        # 服务未安装或未初始化时忽略
        pass

    # 手动偏移（调试用）
    try:
        from app.services.settings_service import SettingsService

        offset = SettingsService.instance().time_offset_seconds
        if offset != 0:
            base += timedelta(seconds=offset)
    except (ImportError, AttributeError, RuntimeError):
        pass

    return base


def now_in_zone(iana_name: str) -> datetime:
    """返回指定 IANA 时区的当前时间。"""
    utc = _ntp_utc_now()
    if iana_name == "local":
        return utc.astimezone()
    tz = _get_zone_info(iana_name)
    if tz is None:
        return utc.astimezone()  # 回退到本地时区
    return utc.astimezone(tz)


def format_time(dt: datetime, fmt: str = "%H:%M:%S") -> str:
    return dt.strftime(fmt)


def format_date(dt: datetime, fmt: str = "%Y-%m-%d") -> str:
    return dt.strftime(fmt)


def utc_offset_str(dt: datetime) -> str:
    """返回形如 'UTC+8:00' 的偏移字符串"""
    offset = dt.utcoffset()
    if offset is None:
        return "UTC"
    total_seconds = int(offset.total_seconds())
    sign = "+" if total_seconds >= 0 else "-"
    total_seconds = abs(total_seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes = remainder // 60
    if minutes:
        return f"UTC{sign}{hours}:{minutes:02d}"
    return f"UTC{sign}{hours}"


# --------------------------------------------------------------------------- #
# 持续时间格式化
# --------------------------------------------------------------------------- #


def format_duration(ms: int, precision: int = 1) -> str:
    """毫秒 → 时间字符串；precision 0/1/2 对应无小数、十分位、百分位。"""
    secs = ms // 1000
    s = secs % 60
    m = (secs // 60) % 60
    h = secs // 3600

    if precision == 2:
        cs = (ms % 1000) // 10  # 0–99
        if h:
            return f"{h:02d}:{m:02d}:{s:02d}.{cs:02d}"
        return f"{m:02d}:{s:02d}.{cs:02d}"
    elif precision == 1:
        d = (ms % 1000) // 100  # 0–9
        if h:
            return f"{h:02d}:{m:02d}:{s:02d}.{d}"
        return f"{m:02d}:{s:02d}.{d}"
    else:
        if h:
            return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"


def parse_duration_ms(text: str) -> int:
    """解析 'HH:MM:SS' 或 'MM:SS' 文本 → 毫秒"""
    parts = text.strip().split(":")
    try:
        if len(parts) == 3:
            h, m, s = (int(p) for p in parts)
        elif len(parts) == 2:
            h, m, s = 0, int(parts[0]), int(parts[1])
        else:
            h, m, s = 0, 0, int(parts[0])
        return (h * 3600 + m * 60 + s) * 1000
    except ValueError:
        return 0


# load_json 的默认参数哨兵：区分"未显式传入 default"（回退 {}）
# 与"显式传入 default=None"（原样返回，供调用方识别文件不存在）
_UNSET: Any = object()


def load_json(path: str, default: Any = _UNSET) -> Any:
    """安全加载 JSON 文件

    读取失败（文件不存在 / JSON 损坏 / 编码错误）时返回 default；
    未显式传入 default 时回退为空字典 {}。
    需要区分"文件不存在"的场景请显式传 default=None。
    """
    p = Path(path)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
            logger.warning("读取 JSON 失败，已回退默认值: {}, error={}", p, e)
    return {} if default is _UNSET else default


def save_json(path: str, data: Any) -> None:
    p = Path(path)
    try:
        write_text_with_uac(
            p,
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
            ensure_parent=True,
        )
    except OSError as e:
        logger.error("写入 JSON 失败: {}, error={}", p, e)
        raise

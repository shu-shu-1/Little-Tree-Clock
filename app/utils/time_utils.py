"""时间工具函数"""
from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

try:
    from zoneinfo import ZoneInfo, available_timezones  # Python 3.9+
except ImportError:
    from backports.zoneinfo import ZoneInfo, available_timezones  # type: ignore


# --------------------------------------------------------------------------- #
# 时区转换
# --------------------------------------------------------------------------- #

def _ntp_utc_now() -> datetime:
    """
    返回 UTC 当前时间。
    若 NtpService 已启用且已完成同步，则返回经过 NTP 偏移校正的时间；
    否则回退到系统时间。
    使用延迟导入避免循环依赖。
    """
    try:
        from app.services.ntp_service import NtpService
        svc = NtpService.instance()
        if svc.enabled and svc.last_sync_ts is not None:
            return svc.now()
    except Exception:
        pass
    return datetime.now(timezone.utc)


def now_in_zone(iana_name: str) -> datetime:
    """返回指定 IANA 时区的当前时间（自动使用 NTP 校正，若已启用）"""
    utc = _ntp_utc_now()
    if iana_name == "local":
        return utc.astimezone()
    return utc.astimezone(ZoneInfo(iana_name))


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
    """毫秒 → 时间字符串

    precision
    ---------
    0  :  'HH:MM:SS' 或 'MM:SS'（无小数）
    1  :  'HH:MM:SS.d' 或 'MM:SS.d'（十分位，默认）
    2  :  'HH:MM:SS.cs' 或 'MM:SS.cs'（百分位 / 厘秒）
    """
    secs = ms // 1000
    s    = secs % 60
    m    = (secs // 60) % 60
    h    = secs // 3600

    if precision == 2:
        cs = (ms % 1000) // 10   # 0–99
        if h:
            return f"{h:02d}:{m:02d}:{s:02d}.{cs:02d}"
        return f"{m:02d}:{s:02d}.{cs:02d}"
    elif precision == 1:
        d = (ms % 1000) // 100   # 0–9
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


# --------------------------------------------------------------------------- #
# JSON 配置读写
# --------------------------------------------------------------------------- #

def load_json(path: str, default=None):
    p = Path(path)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return default if default is not None else {}


def save_json(path: str, data) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

"""日期时间工具函数"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, Union


def parse_date(date_str: str, fmt: str = "%Y-%m-%d") -> Optional[datetime]:
    """解析日期字符串为 datetime 对象

    Args:
        date_str: 日期字符串
        fmt: 格式字符串

    Returns:
        datetime 对象，解析失败返回 None
    """
    try:
        return datetime.strptime(date_str, fmt)
    except (ValueError, TypeError):
        return None


def parse_datetime(dt_str: str, fmt: str = "%Y-%m-%d %H:%M:%S") -> Optional[datetime]:
    """解析日期时间字符串

    Args:
        dt_str: 日期时间字符串
        fmt: 格式字符串

    Returns:
        datetime 对象，解析失败返回 None
    """
    try:
        return datetime.strptime(dt_str, fmt)
    except (ValueError, TypeError):
        return None


def format_relative_time(dt: datetime, reference: Optional[datetime] = None) -> str:
    """生成相对时间字符串（如"3分钟前"、"2小时后"）

    Args:
        dt: 要格式化的 datetime
        reference: 参考时间，默认当前时间

    Returns:
        相对时间字符串
    """
    if reference is None:
        reference = datetime.now()

    diff = reference - dt

    if diff < timedelta(seconds=0):
        # 未来时间
        diff = -diff
        suffix = "后"
    else:
        suffix = "前"

    if diff < timedelta(minutes=1):
        return "刚刚"
    elif diff < timedelta(hours=1):
        minutes = int(diff.total_seconds() / 60)
        return f"{minutes}分钟{suffix}"
    elif diff < timedelta(days=1):
        hours = int(diff.total_seconds() / 3600)
        return f"{hours}小时{suffix}"
    elif diff < timedelta(days=30):
        days = diff.days
        return f"{days}天{suffix}"
    elif diff < timedelta(days=365):
        months = int(diff.days / 30)
        return f"{months}个月{suffix}"
    else:
        years = int(diff.days / 365)
        return f"{years}年{suffix}"


def parse_duration(text: str) -> Optional[timedelta]:
    """解析自然语言时长描述

    支持格式：
    - "1d", "1day", "2days"
    - "2h", "2hour", "3hours"
    - "30m", "30min", "30minutes"
    - "45s", "45sec", "45seconds"
    - "1d2h30m"

    Args:
        text: 时长描述字符串

    Returns:
        timedelta 对象，解析失败返回 None
    """
    import re

    pattern = r'(\d+)\s*(d(?:ays?)?|h(?:ours?|r)?|m(?:in(?:utes?)?)?|s(?:ec(?:onds?)?)?)'
    matches = re.findall(pattern, text.lower())

    if not matches:
        return None

    total = timedelta()

    for value_str, unit in matches:
        try:
            value = int(value_str)
        except ValueError:
            continue

        if unit.startswith('d'):
            total += timedelta(days=value)
        elif unit.startswith('h'):
            total += timedelta(hours=value)
        elif unit.startswith('m') and not unit.startswith('mi'):
            total += timedelta(minutes=value)
        elif unit.startswith('s'):
            total += timedelta(seconds=value)

    return total if total.total_seconds() > 0 else None


def is_same_day(dt1: datetime, dt2: datetime) -> bool:
    """检查两个 datetime 是否在同一天"""
    return (dt1.year, dt1.month, dt1.day) == (dt2.year, dt2.month, dt2.day)


def is_weekend(dt: datetime) -> bool:
    """检查是否为周末（周六或周日）"""
    return dt.weekday() >= 5


def is_weekday(dt: datetime) -> bool:
    """检查是否为工作日（周一至周五）"""
    return dt.weekday() < 5


def start_of_day(dt: datetime) -> datetime:
    """返回一天的开始（00:00:00）"""
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def end_of_day(dt: datetime) -> datetime:
    """返回一天的结束（23:59:59.999999）"""
    return dt.replace(hour=23, minute=59, second=59, microsecond=999999)


def start_of_week(dt: datetime, week_start: int = 0) -> datetime:
    """返回一周的开始

    Args:
        dt: 参考日期
        week_start: 一周开始日（0=周一, 6=周日）

    Returns:
        一周开始日期
    """
    days_since_start = (dt.weekday() - week_start) % 7
    return start_of_day(dt - timedelta(days=days_since_start))


def start_of_month(dt: datetime) -> datetime:
    """返回一月的开始"""
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def end_of_month(dt: datetime) -> datetime:
    """返回一月的结束"""
    if dt.month == 12:
        next_month = dt.replace(year=dt.year + 1, month=1, day=1)
    else:
        next_month = dt.replace(month=dt.month + 1, day=1)
    return next_month - timedelta(microseconds=1)


def days_in_month(year: int, month: int) -> int:
    """返回指定月份的天数"""
    if month == 12:
        next_month = datetime(year + 1, 1, 1)
    else:
        next_month = datetime(year, month + 1, 1)
    return (next_month - datetime(year, month, 1)).days


def add_business_days(start: datetime, days: int) -> datetime:
    """添加工作日（跳过周末）

    Args:
        start: 起始日期
        days: 要添加的工作日数（正数向后，负数向前）

    Returns:
        计算后的日期
    """
    current = start
    delta = 1 if days > 0 else -1
    remaining = abs(days)

    while remaining > 0:
        current += timedelta(days=delta)
        if is_weekday(current):
            remaining -= 1

    return current


def business_days_between(start: datetime, end: datetime) -> int:
    """计算两个日期之间的工作日数"""
    if start > end:
        start, end = end, start

    count = 0
    current = start_of_day(start)

    while current <= end:
        if is_weekday(current):
            count += 1
        current += timedelta(days=1)

    return count


def age(birth_date: datetime, reference: Optional[datetime] = None) -> int:
    """计算年龄

    Args:
        birth_date: 出生日期
        reference: 参考日期，默认当前日期

    Returns:
        年龄（整数）
    """
    if reference is None:
        reference = datetime.now()

    age = reference.year - birth_date.year

    # 如果今年的生日还没过，年龄减一
    if (reference.month, reference.day) < (birth_date.month, birth_date.day):
        age -= 1

    return age


def quarter(dt: datetime) -> int:
    """返回日期所在的季度（1-4）"""
    return (dt.month - 1) // 3 + 1


def start_of_quarter(dt: datetime) -> datetime:
    """返回季度开始日期"""
    first_month = ((dt.month - 1) // 3) * 3 + 1
    return dt.replace(month=first_month, day=1, hour=0, minute=0, second=0, microsecond=0)


def end_of_quarter(dt: datetime) -> datetime:
    """返回季度结束日期"""
    next_quarter_month = ((dt.month - 1) // 3 + 1) * 3 + 1
    if next_quarter_month > 12:
        next_quarter = datetime(dt.year + 1, next_quarter_month - 12, 1)
    else:
        next_quarter = datetime(dt.year, next_quarter_month, 1)
    return next_quarter - timedelta(microseconds=1)


def is_leap_year(year: int) -> bool:
    """检查是否为闰年"""
    return (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)


def iso_calendar(dt: datetime) -> tuple[int, int, int]:
    """返回 ISO 格式的日历（年、周数、周内第几天）

    Returns:
        (ISO 年份, ISO 周数, 周内第几天(1=周一))
    """
    return dt.isocalendar()


__all__ = [
    "parse_date",
    "parse_datetime",
    "format_relative_time",
    "parse_duration",
    "is_same_day",
    "is_weekend",
    "is_weekday",
    "start_of_day",
    "end_of_day",
    "start_of_week",
    "start_of_month",
    "end_of_month",
    "days_in_month",
    "add_business_days",
    "business_days_between",
    "age",
    "quarter",
    "start_of_quarter",
    "end_of_quarter",
    "is_leap_year",
    "iso_calendar",
]

"""农历（中国传统历法）工具；未安装 lunardate 时相关函数返回空字符串。"""

from __future__ import annotations

import functools
from datetime import date

_HEAVENLY_STEMS = ["甲", "乙", "丙", "丁", "戊", "己", "庚", "辛", "壬", "癸"]
_EARTHLY_BRANCHES = ["子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥"]
_ZODIAC = ["鼠", "牛", "虎", "兔", "龙", "蛇", "马", "羊", "猴", "鸡", "狗", "猪"]
_MONTH_NAMES = ["正月", "二月", "三月", "四月", "五月", "六月", "七月", "八月", "九月", "十月", "冬月", "腊月"]
_DAY_NAMES = [
    "初一",
    "初二",
    "初三",
    "初四",
    "初五",
    "初六",
    "初七",
    "初八",
    "初九",
    "初十",
    "十一",
    "十二",
    "十三",
    "十四",
    "十五",
    "十六",
    "十七",
    "十八",
    "十九",
    "二十",
    "廿一",
    "廿二",
    "廿三",
    "廿四",
    "廿五",
    "廿六",
    "廿七",
    "廿八",
    "廿九",
    "三十",
]

_LunarDate: object | None = None
_lunar_import_tried: bool = False


def _get_lunar_date():
    """返回 lunardate.LunarDate 类型，未安装时返回 None；只尝试导入一次。"""
    global _LunarDate, _lunar_import_tried
    if not _lunar_import_tried:
        _lunar_import_tried = True
        try:
            from lunardate import LunarDate  # noqa: PLC0415

            _LunarDate = LunarDate
        except ImportError:
            _LunarDate = None
    return _LunarDate


@functools.lru_cache(maxsize=366 * 2)
def _lunar_for_date(year: int, month: int, day: int):
    """按公历日期缓存农历转换结果（同一日期一天内不会变化）。"""
    LunarDate = _get_lunar_date()
    if LunarDate is None:
        return None
    try:
        return LunarDate.fromSolarDate(year, month, day)
    except Exception:
        return None


def solar_to_lunar(d: date):
    """公历日期转农历日期对象，失败返回 None。"""
    return _lunar_for_date(d.year, d.month, d.day)


def lunar_day_str(d: date) -> str:
    """返回农历日期字符串，例如 '正月初一'；失败返回空字符串。"""
    ld = solar_to_lunar(d)
    if ld is None:
        return ""
    month_name = ("闰" if ld.isLeapMonth else "") + _MONTH_NAMES[ld.month - 1]
    day_name = _DAY_NAMES[ld.day - 1]
    return f"{month_name}{day_name}"


def lunar_short_str(d: date) -> str:
    """日历格用简短农历：初一显示月名（如 '正月'），其余显示日名。"""
    ld = solar_to_lunar(d)
    if ld is None:
        return ""
    day_name = _DAY_NAMES[ld.day - 1]
    if ld.day == 1:
        month_name = ("闰" if ld.isLeapMonth else "") + _MONTH_NAMES[ld.month - 1]
        return month_name
    return day_name


def ganzhi_year_str(d: date) -> str:
    """返回干支纪年 + 生肖，例如 '甲辰龙年'。"""
    ld = solar_to_lunar(d)
    if ld is None:
        return ""
    year = ld.year
    stem = _HEAVENLY_STEMS[(year - 4) % 10]
    branch = _EARTHLY_BRANCHES[(year - 4) % 12]
    zodiac = _ZODIAC[(year - 4) % 12]
    return f"{stem}{branch}{zodiac}年"

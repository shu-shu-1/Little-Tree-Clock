"""农历（中国传统历法）工具

依赖 lunardate (https://github.com/lidaobing/python-lunardate)
若未安装，所有函数均返回空字符串，不影响运行。
"""
from __future__ import annotations

import functools
from datetime import date

# 天干
_HEAVENLY_STEMS = ["甲", "乙", "丙", "丁", "戊", "己", "庚", "辛", "壬", "癸"]
# 地支
_EARTHLY_BRANCHES = ["子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥"]
# 生肖
_ZODIAC = ["鼠", "牛", "虎", "兔", "龙", "蛇", "马", "羊", "猴", "鸡", "狗", "猪"]
# 月份名
_MONTH_NAMES = [
    "正月", "二月", "三月", "四月", "五月", "六月",
    "七月", "八月", "九月", "十月", "冬月", "腊月"
]
# 日期名
_DAY_NAMES = [
    "初一", "初二", "初三", "初四", "初五", "初六", "初七", "初八", "初九", "初十",
    "十一", "十二", "十三", "十四", "十五", "十六", "十七", "十八", "十九", "二十",
    "廿一", "廿二", "廿三", "廿四", "廿五", "廿六", "廿七", "廿八", "廿九", "三十",
]

# 一次性解析导入结果。None 表示尚未尝试；False 表示不可用。
_LunarDate: object | None = None
_lunar_import_tried: bool = False


def _get_lunar_date():
    """返回 lunardate.LunarDate 类型，未安装时返回 None。

    与原始 ``_try_import`` 的差异：导入只尝试一次，避免每次调用都触发
    ``import`` 开销（时钟组件每秒刷新都会用到）。
    """
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
    """按公历日期缓存农历转换结果（农历每日仅变化一次，缓存命中率高）。"""
    LunarDate = _get_lunar_date()
    if LunarDate is None:
        return None
    try:
        return LunarDate.fromSolarDate(year, month, day)
    except Exception:
        return None


def solar_to_lunar(d: date):
    """将公历日期转换为农历日期对象，失败返回 None。

    返回的 LunarDate 具有属性：
        .year  .month  .day  .isLeapMonth
    """
    return _lunar_for_date(d.year, d.month, d.day)


def lunar_day_str(d: date) -> str:
    """返回农历日期字符串，例如 '正月初一'，失败或初一以外返回日期名，如 '二月十五'。"""
    ld = solar_to_lunar(d)
    if ld is None:
        return ""
    month_name = ("闰" if ld.isLeapMonth else "") + _MONTH_NAMES[ld.month - 1]
    day_name = _DAY_NAMES[ld.day - 1]
    return f"{month_name}{day_name}"


def lunar_short_str(d: date) -> str:
    """返回简短农历日期，仅日部分，用于日历格显示，如 '初一' '十五'。

    若当天是初一，额外前置月名，如 '正月'。
    """
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

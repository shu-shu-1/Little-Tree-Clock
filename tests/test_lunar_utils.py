"""app.utils.lunar_utils 单元测试（参考值已用 lunardate 验证）。"""

from __future__ import annotations

from datetime import date

import pytest

from app.utils.lunar_utils import (
    ganzhi_year_str,
    lunar_day_str,
    lunar_short_str,
    solar_to_lunar,
)


class TestSolarToLunar:
    def test_chinese_new_year_2024(self):
        ld = solar_to_lunar(date(2024, 2, 10))
        assert ld is not None
        assert (ld.year, ld.month, ld.day) == (2024, 1, 1)
        assert not ld.isLeapMonth

    def test_regular_date(self):
        ld = solar_to_lunar(date(2026, 8, 30))
        assert ld is not None
        assert (ld.year, ld.month, ld.day) == (2026, 7, 18)


class TestLunarDayStr:
    def test_new_year_full_name(self):
        assert lunar_day_str(date(2024, 2, 10)) == "正月初一"

    def test_regular_day(self):
        assert lunar_day_str(date(2026, 8, 30)) == "七月十八"


class TestLunarShortStr:
    def test_first_day_shows_month(self):
        assert lunar_short_str(date(2024, 2, 10)) == "正月"

    def test_regular_day_shows_day_only(self):
        assert lunar_short_str(date(2026, 8, 30)) == "十八"


class TestGanzhiYear:
    @pytest.mark.parametrize(
        "solar,expected",
        [
            (date(2024, 6, 1), "甲辰龙年"),
            (date(2025, 6, 1), "乙巳蛇年"),
            (date(2026, 8, 30), "丙午马年"),
        ],
    )
    def test_known_years(self, solar, expected):
        assert ganzhi_year_str(solar) == expected

"""app.utils.datetime_utils 单元测试"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.utils.datetime_utils import (
    add_business_days,
    age,
    business_days_between,
    days_in_month,
    end_of_day,
    end_of_month,
    end_of_quarter,
    format_relative_time,
    is_leap_year,
    is_same_day,
    is_weekday,
    is_weekend,
    iso_calendar,
    parse_date,
    parse_datetime,
    parse_duration,
    quarter,
    start_of_day,
    start_of_month,
    start_of_quarter,
    start_of_week,
)


class TestParse:
    def test_parse_date(self):
        assert parse_date("2026-08-30") == datetime(2026, 8, 30)

    def test_parse_date_custom_fmt(self):
        assert parse_date("30/08/2026", "%d/%m/%Y") == datetime(2026, 8, 30)

    def test_parse_date_invalid(self):
        assert parse_date("not a date") is None
        assert parse_date("2026-13-40") is None

    def test_parse_date_none(self):
        assert parse_date(None) is None

    def test_parse_datetime(self):
        assert parse_datetime("2026-08-30 12:34:56") == datetime(2026, 8, 30, 12, 34, 56)

    def test_parse_datetime_invalid(self):
        assert parse_datetime("oops") is None


class TestFormatRelativeTime:
    REF = datetime(2026, 8, 30, 12, 0, 0)

    def test_just_now(self):
        dt = self.REF - timedelta(seconds=30)
        assert format_relative_time(dt, self.REF) == "刚刚"

    def test_minutes_ago(self):
        dt = self.REF - timedelta(minutes=3)
        assert format_relative_time(dt, self.REF) == "3分钟前"

    def test_hours_ago(self):
        dt = self.REF - timedelta(hours=2)
        assert format_relative_time(dt, self.REF) == "2小时前"

    def test_days_ago(self):
        dt = self.REF - timedelta(days=5)
        assert format_relative_time(dt, self.REF) == "5天前"

    def test_months_ago(self):
        dt = self.REF - timedelta(days=60)
        assert format_relative_time(dt, self.REF) == "2个月前"

    def test_years_ago(self):
        dt = self.REF - timedelta(days=400)
        assert format_relative_time(dt, self.REF) == "1年前"

    def test_future_suffix(self):
        dt = self.REF + timedelta(minutes=10)
        assert format_relative_time(dt, self.REF) == "10分钟后"

    def test_future_hours(self):
        dt = self.REF + timedelta(hours=3)
        assert format_relative_time(dt, self.REF) == "3小时后"


class TestParseDuration:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("30m", timedelta(minutes=30)),
            ("30min", timedelta(minutes=30)),
            ("30minutes", timedelta(minutes=30)),
            ("2h", timedelta(hours=2)),
            ("1d", timedelta(days=1)),
            ("45s", timedelta(seconds=45)),
            ("45sec", timedelta(seconds=45)),
            ("1d2h30m", timedelta(days=1, hours=2, minutes=30)),
            ("2 hours", timedelta(hours=2)),
        ],
    )
    def test_valid(self, text, expected):
        assert parse_duration(text) == expected

    @pytest.mark.parametrize("text", ["", "abc", "0m"])
    def test_invalid(self, text):
        assert parse_duration(text) is None


class TestDayChecks:
    def test_is_same_day(self):
        a = datetime(2026, 8, 30, 8, 0)
        b = datetime(2026, 8, 30, 23, 59)
        c = datetime(2026, 8, 31, 8, 0)
        assert is_same_day(a, b)
        assert not is_same_day(a, c)

    def test_is_weekend(self):
        assert is_weekend(datetime(2026, 8, 29))  # 周六
        assert is_weekend(datetime(2026, 8, 30))  # 周日
        assert not is_weekend(datetime(2026, 8, 28))  # 周五

    def test_is_weekday(self):
        assert is_weekday(datetime(2026, 8, 28))  # 周五
        assert not is_weekday(datetime(2026, 8, 30))  # 周日


class TestBoundaries:
    def test_start_of_day(self):
        dt = datetime(2026, 8, 30, 15, 30, 45)
        assert start_of_day(dt) == datetime(2026, 8, 30)

    def test_end_of_day(self):
        dt = datetime(2026, 8, 30, 8, 0)
        assert end_of_day(dt) == datetime(2026, 8, 30, 23, 59, 59, 999999)

    def test_start_of_week_monday(self):
        # 2026-08-30 是周日
        assert start_of_week(datetime(2026, 8, 30, 10, 0)) == datetime(2026, 8, 24)

    def test_start_of_week_sunday_start(self):
        # week_start=6 表示周日为一周开始
        assert start_of_week(datetime(2026, 8, 30), week_start=6) == datetime(2026, 8, 30)

    def test_start_of_month(self):
        assert start_of_month(datetime(2026, 8, 30, 5, 0)) == datetime(2026, 8, 1)

    def test_end_of_month(self):
        assert end_of_month(datetime(2026, 8, 3)) == datetime(2026, 8, 31, 23, 59, 59, 999999)
        assert end_of_month(datetime(2026, 2, 10)) == datetime(2026, 2, 28, 23, 59, 59, 999999)

    def test_end_of_month_december(self):
        assert end_of_month(datetime(2026, 12, 15)) == datetime(2026, 12, 31, 23, 59, 59, 999999)

    def test_days_in_month(self):
        assert days_in_month(2026, 8) == 31
        assert days_in_month(2026, 2) == 28
        assert days_in_month(2024, 2) == 29
        assert days_in_month(2026, 12) == 31


class TestBusinessDays:
    def test_add_business_days_skips_weekend(self):
        # 2026-08-28 周五 + 1 工作日 = 周一 2026-08-31
        assert add_business_days(datetime(2026, 8, 28), 1) == datetime(2026, 8, 31)

    def test_add_business_days_within_week(self):
        # 周一 +4 工作日 = 周五
        assert add_business_days(datetime(2026, 8, 24), 4) == datetime(2026, 8, 28)

    def test_add_business_days_negative(self):
        # 周一 2026-08-31 - 1 工作日 = 周五 2026-08-28
        assert add_business_days(datetime(2026, 8, 31), -1) == datetime(2026, 8, 28)

    def test_business_days_between_same_week(self):
        start = datetime(2026, 8, 24)  # 周一
        end = datetime(2026, 8, 28)  # 周五
        assert business_days_between(start, end) == 5

    def test_business_days_between_spans_weekend(self):
        start = datetime(2026, 8, 28)  # 周五
        end = datetime(2026, 8, 31)  # 周一
        assert business_days_between(start, end) == 2

    def test_business_days_between_reversed(self):
        start = datetime(2026, 8, 31)
        end = datetime(2026, 8, 28)
        assert business_days_between(start, end) == 2


class TestAge:
    def test_birthday_passed(self):
        assert age(datetime(2010, 5, 1), datetime(2026, 8, 30)) == 16

    def test_birthday_not_yet(self):
        assert age(datetime(2010, 12, 1), datetime(2026, 8, 30)) == 15

    def test_birthday_today(self):
        assert age(datetime(2010, 8, 30), datetime(2026, 8, 30)) == 16


class TestQuarter:
    @pytest.mark.parametrize("month,q", [(1, 1), (3, 1), (4, 2), (6, 2), (7, 3), (9, 3), (10, 4), (12, 4)])
    def test_quarter(self, month, q):
        assert quarter(datetime(2026, month, 15)) == q

    def test_start_of_quarter(self):
        assert start_of_quarter(datetime(2026, 8, 30)) == datetime(2026, 7, 1)

    def test_end_of_quarter(self):
        assert end_of_quarter(datetime(2026, 8, 30)) == datetime(2026, 9, 30, 23, 59, 59, 999999)

    def test_end_of_quarter_q4(self):
        assert end_of_quarter(datetime(2026, 11, 1)) == datetime(2026, 12, 31, 23, 59, 59, 999999)


class TestLeapYear:
    @pytest.mark.parametrize(
        "year,expected",
        [
            (2024, True),
            (2026, False),
            (1900, False),  # 世纪年非闰
            (2000, True),  # 400 的倍数是闰
        ],
    )
    def test_is_leap_year(self, year, expected):
        assert is_leap_year(year) == expected


class TestIsoCalendar:
    def test_iso_calendar(self):
        year, week, weekday = iso_calendar(datetime(2026, 8, 30))
        assert (year, week, weekday) == datetime(2026, 8, 30).isocalendar()

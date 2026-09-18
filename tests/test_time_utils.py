"""app.utils.time_utils 单元测试（涉及 now_in_zone 的用例打桩 _ntp_utc_now，NTP 不直接测试）。"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from app.utils import time_utils


class TestFormatDuration:
    def test_precision1_under_hour(self):
        assert time_utils.format_duration(65_500) == "01:05.5"

    def test_precision1_over_hour(self):
        assert time_utils.format_duration(3_661_500) == "01:01:01.5"

    def test_precision0_under_hour(self):
        assert time_utils.format_duration(65_000, precision=0) == "01:05"

    def test_precision0_over_hour(self):
        assert time_utils.format_duration(3_661_000, precision=0) == "01:01:01"

    def test_precision2(self):
        assert time_utils.format_duration(65_050, precision=2) == "01:05.05"

    def test_precision2_over_hour(self):
        assert time_utils.format_duration(3_661_230, precision=2) == "01:01:01.23"

    def test_zero(self):
        assert time_utils.format_duration(0) == "00:00.0"

    def test_large_hours(self):
        assert time_utils.format_duration(100 * 3_600_000, precision=0) == "100:00:00"


class TestParseDurationMs:
    @pytest.mark.parametrize(
        "text,ms",
        [
            ("01:05", 65_000),
            ("00:30", 30_000),
            ("01:01:01", 3_661_000),
            ("10", 10_000),
            ("0:0:0", 0),
        ],
    )
    def test_valid(self, text, ms):
        assert time_utils.parse_duration_ms(text) == ms

    def test_whitespace_tolerant(self):
        assert time_utils.parse_duration_ms("  01:30 ") == 90_000

    def test_invalid_returns_zero(self):
        assert time_utils.parse_duration_ms("ab:cd") == 0
        assert time_utils.parse_duration_ms("") == 0

    def test_roundtrip_with_format_duration(self):
        # 仅整秒值可无损往返（precision=0 会丢弃毫秒部分）
        for total_ms in (0, 1_000, 61_000, 3_725_000):
            text = time_utils.format_duration(total_ms, precision=0)
            assert time_utils.parse_duration_ms(text) == total_ms


class TestUtcOffsetStr:
    def test_positive_offset(self):
        # 用构造的固定时区验证，避免依赖本地时区
        from datetime import timedelta

        tz = timezone(timedelta(hours=8))
        assert time_utils.utc_offset_str(datetime(2026, 1, 1, tzinfo=tz)) == "UTC+8"

    def test_positive_offset_with_minutes(self):
        from datetime import timedelta

        tz = timezone(timedelta(hours=5, minutes=30))
        assert time_utils.utc_offset_str(datetime(2026, 1, 1, tzinfo=tz)) == "UTC+5:30"

    def test_negative_offset(self):
        from datetime import timedelta

        tz = timezone(timedelta(hours=-6))
        assert time_utils.utc_offset_str(datetime(2026, 1, 1, tzinfo=tz)) == "UTC-6"

    def test_utc_zero(self):
        assert time_utils.utc_offset_str(datetime(2026, 1, 1, tzinfo=timezone.utc)) == "UTC+0"

    def test_naive_datetime(self):
        assert time_utils.utc_offset_str(datetime(2026, 1, 1)) == "UTC"


class TestNowInZone:
    @pytest.fixture(autouse=True)
    def _stub_ntp(self, monkeypatch):
        """屏蔽 NTP/设置服务，返回固定 UTC 时刻"""
        fixed = datetime(2026, 8, 30, 12, 0, 0, tzinfo=timezone.utc)
        monkeypatch.setattr(time_utils, "_ntp_utc_now", lambda: fixed)
        time_utils._get_zone_info.clear_cache()

    def test_utc_zone(self):
        dt = time_utils.now_in_zone("UTC")
        assert dt.utcoffset().total_seconds() == 0
        assert (dt.year, dt.month, dt.day, dt.hour) == (2026, 8, 30, 12)

    def test_shanghai_zone(self):
        dt = time_utils.now_in_zone("Asia/Shanghai")
        assert dt.utcoffset().total_seconds() == 8 * 3600
        assert dt.hour == 20

    def test_invalid_zone_falls_back_to_local(self):
        dt = time_utils.now_in_zone("Not/AZone")
        assert dt.utcoffset() is not None  # astimezone() 后必带偏移

    def test_local_zone(self):
        dt = time_utils.now_in_zone("local")
        assert dt.utcoffset() is not None


class TestLoadSaveJson:
    def test_roundtrip(self, tmp_path):
        path = tmp_path / "data.json"
        data = {"中文": ["a", 1], "nested": {"ok": True}}
        time_utils.save_json(str(path), data)
        assert time_utils.load_json(str(path)) == data

    def test_saves_utf8_without_ascii_escaping(self, tmp_path):
        path = tmp_path / "data.json"
        time_utils.save_json(str(path), {"name": "小树"})
        raw = path.read_text(encoding="utf-8")
        assert "小树" in raw

    def test_creates_parent_dirs(self, tmp_path):
        path = tmp_path / "a" / "b" / "data.json"
        time_utils.save_json(str(path), [1, 2, 3])
        assert path.exists()

    def test_load_missing_returns_default(self, tmp_path):
        path = tmp_path / "missing.json"
        assert time_utils.load_json(str(path), default=[]) == []
        assert time_utils.load_json(str(path)) == {}

    def test_load_corrupt_returns_default(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{not json", encoding="utf-8")
        assert time_utils.load_json(str(path), default={"fallback": True}) == {"fallback": True}

    def test_load_invalid_utf8_returns_default(self, tmp_path):
        # 编码错误应与 JSON 损坏同等对待：回退默认值而非向外抛异常
        path = tmp_path / "bad_encoding.json"
        path.write_bytes(b'\xff\xfe{"a":1}')
        assert time_utils.load_json(str(path), default="d") == "d"
        assert time_utils.load_json(str(path)) == {}

    def test_missing_file_default_none_is_preserved(self, tmp_path):
        """显式传 default=None 时，文件不存在应返回 None（区分"缺失"与"空配置"）"""
        path = tmp_path / "missing.json"
        assert time_utils.load_json(str(path), default=None) is None

    def test_missing_file_without_default_returns_empty_dict(self, tmp_path):
        """未显式传 default 时保持旧行为：回退空字典"""
        path = tmp_path / "missing.json"
        assert time_utils.load_json(str(path)) == {}

    def test_saved_file_is_valid_json(self, tmp_path):
        path = tmp_path / "data.json"
        time_utils.save_json(str(path), {"k": "v"})
        assert json.loads(path.read_text(encoding="utf-8")) == {"k": "v"}

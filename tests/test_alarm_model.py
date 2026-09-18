"""app.models.alarm_model 单元测试（ALARM_CONFIG 由 isolated_config fixture 重定向到临时目录）。"""

from __future__ import annotations

import json

import pytest

from app.models.alarm_model import Alarm, AlarmRepeat, AlarmStore


class TestAlarmDataclass:
    def test_defaults(self):
        a = Alarm()
        assert a.label == "闹钟"
        assert (a.hour, a.minute) == (8, 0)
        assert a.enabled is True
        assert a.repeat == 0
        assert a.snooze_min == 5
        assert a.fullscreen is True
        assert a.id  # uuid 自动生成

    def test_time_str(self):
        assert Alarm(hour=7, minute=5).time_str == "07:05"
        assert Alarm(hour=23, minute=59).time_str == "23:59"

    def test_repeat_flag(self):
        assert Alarm(repeat=0).repeat_flag == AlarmRepeat.NONE
        assert Alarm(repeat=int(AlarmRepeat.WEEKDAYS)).repeat_flag == AlarmRepeat.WEEKDAYS

    def test_roundtrip_dict(self):
        a = Alarm(label="晨读", hour=6, minute=30, repeat=3, sound="x.mp3")
        b = Alarm.from_dict(a.to_dict())
        assert b == a

    def test_from_dict_ignores_unknown_keys(self):
        a = Alarm.from_dict({"hour": 9, "unknown_field": "whatever"})
        assert a.hour == 9
        assert not hasattr(a, "unknown_field")


class TestAlarmRepeatLabel:
    @pytest.mark.parametrize(
        "flag,expected",
        [
            (AlarmRepeat.NONE, "仅一次"),
            (AlarmRepeat.EVERY_DAY, "每天"),
            (AlarmRepeat.WEEKDAYS, "工作日"),
            (AlarmRepeat.WEEKEND, "周末"),
        ],
    )
    def test_special_labels(self, flag, expected):
        assert flag.label() == expected

    def test_single_day(self):
        assert AlarmRepeat.MONDAY.label() == "周一"
        assert AlarmRepeat.SUNDAY.label() == "周日"

    def test_multi_day(self):
        combo = AlarmRepeat.MONDAY | AlarmRepeat.WEDNESDAY | AlarmRepeat.FRIDAY
        assert combo.label() == "周一、周三、周五"

    def test_flag_values_match_qt_convention(self):
        assert int(AlarmRepeat.MONDAY) == 1
        assert int(AlarmRepeat.SUNDAY) == 64
        assert int(AlarmRepeat.EVERY_DAY) == 127


class TestAlarmStore:
    def test_empty_start(self, isolated_config):
        store = AlarmStore()
        assert store.all() == []

    def test_add_and_persist(self, isolated_config):
        store = AlarmStore()
        alarm = Alarm(label="早读", hour=6, minute=40)
        store.add(alarm)

        # 内存与文件均可见
        assert [a.id for a in store.all()] == [alarm.id]
        raw = json.loads((isolated_config / "alarms.json").read_text(encoding="utf-8"))
        assert raw[0]["label"] == "早读"

        # 新实例能读回
        store2 = AlarmStore()
        assert store2.get(alarm.id).time_str == "06:40"

    def test_update(self, isolated_config):
        store = AlarmStore()
        alarm = Alarm()
        store.add(alarm)

        alarm.hour = 12
        store.update(alarm)
        assert AlarmStore().get(alarm.id).hour == 12

    def test_remove(self, isolated_config):
        store = AlarmStore()
        a1, a2 = Alarm(), Alarm()
        store.add(a1)
        store.add(a2)

        store.remove(a1.id)
        remaining = store.all()
        assert [a.id for a in remaining] == [a2.id]
        assert AlarmStore().get(a1.id) is None

    def test_get_missing_returns_none(self, isolated_config):
        assert AlarmStore().get("no-such-id") is None

    def test_set_enabled(self, isolated_config):
        store = AlarmStore()
        alarm = Alarm()
        store.add(alarm)

        store.set_enabled(alarm.id, False)
        assert AlarmStore().get(alarm.id).enabled is False

    def test_set_enabled_missing_noop(self, isolated_config):
        store = AlarmStore()
        store.set_enabled("no-such-id", False)  # 不应抛异常

    def test_load_corrupt_config_falls_back_to_empty(self, isolated_config):
        (isolated_config / "alarms.json").write_text("[[broken", encoding="utf-8")
        assert AlarmStore().all() == []

    def test_load_wrong_type_falls_back_to_empty(self, isolated_config):
        (isolated_config / "alarms.json").write_text('{"not": "a list"}', encoding="utf-8")
        assert AlarmStore().all() == []

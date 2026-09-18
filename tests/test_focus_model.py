"""app.models.focus_model 单元测试"""

from __future__ import annotations

import json
import uuid

from app.models.focus_model import AlertMode, FocusPreset, FocusRule, FocusStore


class TestFocusPreset:
    def test_defaults(self):
        p = FocusPreset()
        assert p.name == "新专注预设"
        assert (p.focus_minutes, p.break_minutes, p.cycles) == (25, 5, 4)
        assert p.rule == FocusRule.MUST_USE_PC
        assert p.alert_mode == AlertMode.NOTIFICATION
        assert p.detect_focus is True
        assert p.id

    def test_roundtrip_dict(self):
        p = FocusPreset(name="晚自习", focus_minutes=45, break_minutes=10, cycles=2)
        d = p.to_dict()
        assert FocusPreset.from_dict(d) == p

    def test_from_dict_missing_id_gets_uuid(self):
        p = FocusPreset.from_dict({"name": "x"})
        assert p.id
        uuid.UUID(p.id)  # 合法 UUID

    def test_from_dict_migrates_legacy_alert_mode(self):
        """旧配置中的 'automation' 应迁移为 'notification'"""
        p = FocusPreset.from_dict({"alert_mode": "automation"})
        assert p.alert_mode == AlertMode.NOTIFICATION

    def test_from_dict_keeps_valid_alert_mode(self):
        p = FocusPreset.from_dict({"alert_mode": "fullscreen"})
        assert p.alert_mode == AlertMode.FULLSCREEN

    def test_from_dict_applies_defaults(self):
        p = FocusPreset.from_dict({})
        assert p.focus_minutes == 25
        assert p.tolerance_sec == 30
        assert p.app_name_filter == ""


class TestFocusStore:
    def test_empty_start(self, isolated_config):
        assert FocusStore().all() == []

    def test_add_and_persist(self, isolated_config):
        store = FocusStore()
        preset = FocusPreset(name="早读专注", focus_minutes=20)
        store.add(preset)

        raw = json.loads((isolated_config / "focus.json").read_text(encoding="utf-8"))
        assert raw[0]["name"] == "早读专注"

        store2 = FocusStore()
        assert store2.get(preset.id).focus_minutes == 20

    def test_get_missing_returns_none(self, isolated_config):
        assert FocusStore().get("nope") is None

    def test_update(self, isolated_config):
        store = FocusStore()
        preset = FocusPreset()
        store.add(preset)

        preset.name = "改名"
        store.update(preset)
        assert FocusStore().get(preset.id).name == "改名"

    def test_update_missing_is_noop(self, isolated_config):
        store = FocusStore()
        store.update(FocusPreset(id="ghost"))  # 不应抛异常

    def test_remove(self, isolated_config):
        store = FocusStore()
        p1, p2 = FocusPreset(), FocusPreset()
        store.add(p1)
        store.add(p2)

        store.remove(p1.id)
        assert [p.id for p in store.all()] == [p2.id]
        assert FocusStore().get(p1.id) is None

    def test_legacy_config_without_id_migrated(self, isolated_config):
        """旧配置缺 id 时，from_dict 补 id 并立即回写"""
        (isolated_config / "focus.json").write_text(
            json.dumps([{"name": "旧数据"}], ensure_ascii=False), encoding="utf-8"
        )
        store = FocusStore()
        assert len(store.all()) == 1

        raw = json.loads((isolated_config / "focus.json").read_text(encoding="utf-8"))
        assert raw[0]["id"]  # id 已回写持久化

    def test_load_corrupt_falls_back_to_empty(self, isolated_config):
        (isolated_config / "focus.json").write_text("nope{", encoding="utf-8")
        assert FocusStore().all() == []

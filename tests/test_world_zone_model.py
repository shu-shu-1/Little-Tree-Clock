"""app.models.world_zone 单元测试"""

from __future__ import annotations

import json

import pytest

from app.models.world_zone import WorldZone, WorldZoneStore


class TestWorldZoneDataclass:
    def test_defaults(self):
        z = WorldZone()
        assert z.timezone == "UTC"
        assert z.show_date is True
        assert z.label == ""
        assert z.id

    def test_roundtrip_dict(self):
        z = WorldZone(label="东京", timezone="Asia/Tokyo", show_date=False)
        assert WorldZone.from_dict(z.to_dict()) == z

    def test_from_dict_ignores_unknown_keys(self):
        z = WorldZone.from_dict({"timezone": "UTC", "extra": 1})
        assert z.timezone == "UTC"
        assert not hasattr(z, "extra")


class TestWorldZoneStore:
    @pytest.fixture
    def store(self, isolated_config):
        """预置空列表配置，使 store 从零张卡片开始（首次运行会生成 5 个预设）"""
        (isolated_config / "world_time.json").write_text("[]", encoding="utf-8")
        return WorldZoneStore()

    def test_first_run_creates_presets(self, isolated_config):
        """配置文件不存在时应写入前 5 个预设时区

        （依赖 load_json 的哨兵语义：显式 default=None 时缺失文件返回 None，
        _load 的首次运行分支据此触发。）
        """
        store = WorldZoneStore()
        zones = store.all()
        assert len(zones) == 5
        assert (isolated_config / "world_time.json").exists()
        assert zones[0].label == "本地时间"

    def test_add_and_persist(self, isolated_config, store):
        zone = WorldZone(label="纽约", timezone="America/New_York")
        store.add(zone)

        raw = json.loads((isolated_config / "world_time.json").read_text(encoding="utf-8"))
        assert any(d["timezone"] == "America/New_York" for d in raw)

        store2 = WorldZoneStore()
        assert zone.label in [z.label for z in store2.all()]

    def test_remove(self, store):
        z1 = WorldZone(label="a", timezone="UTC")
        z2 = WorldZone(label="b", timezone="Asia/Tokyo")
        store.add(z1)
        store.add(z2)

        store.remove(z1.id)
        assert [z.id for z in store.all()] == [z2.id]

    def test_remove_missing_is_noop(self, store):
        z = WorldZone()
        store.add(z)
        store.remove("no-such-id")
        assert len(store.all()) == 1

    def test_update(self, store):
        zone = WorldZone(label="旧名", timezone="UTC")
        store.add(zone)

        zone.label = "新名"
        store.update(zone)
        assert WorldZoneStore().all()[0].label == "新名"

    def test_reorder(self, store):
        za = WorldZone(label="a", timezone="UTC")
        zb = WorldZone(label="b", timezone="Asia/Tokyo")
        zc = WorldZone(label="c", timezone="Asia/Seoul")
        for z in (za, zb, zc):
            store.add(z)

        store.reorder([zc.id, za.id, zb.id])
        assert [z.id for z in store.all()] == [zc.id, za.id, zb.id]

        # 重排结果已持久化
        assert [z.id for z in WorldZoneStore().all()] == [zc.id, za.id, zb.id]

    def test_reorder_ignores_unknown_ids(self, store):
        z = WorldZone()
        store.add(z)
        store.reorder(["ghost-id", z.id])
        assert [x.id for x in store.all()] == [z.id]

    def test_load_corrupt_config_regenerates_presets(self, isolated_config):
        """配置损坏时视为不可读（等同首次运行），自动重新生成预设并覆盖坏文件"""
        (isolated_config / "world_time.json").write_text("{oops", encoding="utf-8")
        store = WorldZoneStore()
        assert len(store.all()) == 5
        assert (isolated_config / "world_time.json").exists()

    def test_load_wrong_type_gives_empty_list(self, isolated_config):
        # 合法 JSON 但不是 list：不覆盖文件，仅本次忽略
        (isolated_config / "world_time.json").write_text('{"a": 1}', encoding="utf-8")
        assert WorldZoneStore().all() == []

    def test_class_cache_respects_file_changes(self, isolated_config):
        """类级缓存命中依赖 mtime 一致；外部修改文件后应重新加载"""
        s1 = WorldZoneStore()
        z = WorldZone(label="外部", timezone="UTC")
        s1.add(z)

        # 模拟另一个进程直接改文件（mtime 变化后缓存失效）
        import time as _time

        _time.sleep(0.01)
        path = isolated_config / "world_time.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data.append({"id": "manual-1", "label": "手工", "timezone": "UTC", "show_date": True})
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        s2 = WorldZoneStore()
        labels = [x.label for x in s2.all()]
        assert "手工" in labels

"""app.models.automation_model 单元测试"""

from __future__ import annotations

import json

from app.models.automation_model import (
    ActionConfig,
    AutomationRule,
    AutomationStore,
    ActionType,
    TriggerConfig,
    TriggerType,
)


class TestTriggerActionConfig:
    def test_trigger_defaults(self):
        t = TriggerConfig()
        assert t.type == TriggerType.NONE
        assert t.params == {}

    def test_action_defaults(self):
        a = ActionConfig()
        assert a.type == ActionType.NOTIFICATION
        assert a.params == {}

    def test_roundtrip(self):
        t = TriggerConfig(type=TriggerType.TIME_OF_DAY, params={"hour": 7})
        assert TriggerConfig.from_dict(t.to_dict()) == t

    def test_from_dict_defaults(self):
        assert TriggerConfig.from_dict({}).type == TriggerType.MANUAL
        assert ActionConfig.from_dict({}).type == ActionType.NOTIFICATION


class TestAutomationRule:
    def test_defaults(self):
        r = AutomationRule()
        assert r.name == "新规则"
        assert r.enabled is True
        assert r.actions == []
        assert r.id

    def test_roundtrip_dict(self):
        r = AutomationRule(
            name="上课提醒",
            trigger=TriggerConfig(type=TriggerType.TIME_OF_DAY, params={"time": "08:00"}),
            actions=[ActionConfig(type=ActionType.NOTIFICATION, params={"msg": "上课"})],
            description="test",
        )
        assert AutomationRule.from_dict(r.to_dict()) == r

    def test_from_dict_missing_id_gets_new(self):
        r = AutomationRule.from_dict({"name": "x"})
        assert r.id

    def test_from_dict_actions_list(self):
        r = AutomationRule.from_dict(
            {
                "actions": [{"type": "log", "params": {}}, {"type": "wait", "params": {"sec": 2}}],
            }
        )
        assert [a.type for a in r.actions] == [ActionType.LOG, ActionType.WAIT]

    def test_enum_string_values(self):
        assert TriggerType.ALARM_FIRED == "alarm_fired"
        assert ActionType.OPEN_URL == "open_url"


class TestAutomationStore:
    def test_empty_start(self, isolated_config):
        assert AutomationStore().all() == []

    def test_add_and_persist(self, isolated_config):
        store = AutomationStore()
        rule = AutomationRule(name="规则A")
        store.add(rule)

        raw = json.loads((isolated_config / "automation.json").read_text(encoding="utf-8"))
        assert raw[0]["name"] == "规则A"
        assert AutomationStore().get(rule.id).name == "规则A"

    def test_get_missing_returns_none(self, isolated_config):
        assert AutomationStore().get("nope") is None

    def test_update(self, isolated_config):
        store = AutomationStore()
        rule = AutomationRule(name="旧")
        store.add(rule)

        rule.name = "新"
        store.update(rule)
        assert AutomationStore().get(rule.id).name == "新"

    def test_remove(self, isolated_config):
        store = AutomationStore()
        r1, r2 = AutomationRule(), AutomationRule()
        store.add(r1)
        store.add(r2)

        store.remove(r1.id)
        assert [r.id for r in store.all()] == [r2.id]
        assert AutomationStore().get(r1.id) is None

    def test_set_enabled(self, isolated_config):
        store = AutomationStore()
        rule = AutomationRule()
        store.add(rule)

        store.set_enabled(rule.id, False)
        assert AutomationStore().get(rule.id).enabled is False

    def test_set_enabled_missing_noop(self, isolated_config):
        AutomationStore().set_enabled("ghost", False)  # 不应抛异常

    def test_load_corrupt_falls_back_to_empty(self, isolated_config):
        (isolated_config / "automation.json").write_text("[[", encoding="utf-8")
        assert AutomationStore().all() == []

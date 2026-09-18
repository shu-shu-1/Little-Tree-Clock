"""独立权限管理服务（PermissionService）单元测试：注册表、key 校验 fail-closed、认证放行策略、密码联动、插件防护与集控 blocker。"""

from __future__ import annotations

from pathlib import Path

import pytest

import app.services.permission_service as ps_module
from app.services.permission_service import (
    AccessLevel,
    PermissionService,
    PluginPermissionFacade,
)


@pytest.fixture
def perm_service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """隔离的 PermissionService：配置与数据目录指向 tmp_path，并重置单例。"""
    from PySide6.QtCore import QCoreApplication

    if QCoreApplication.instance() is None:
        QCoreApplication([])

    monkeypatch.setattr(ps_module, "PERMISSION_CONFIG", str(tmp_path / "config" / "permission.json"))
    monkeypatch.setattr(ps_module, "PERMISSION_DATA_DIR", str(tmp_path / "config" / "permission"))
    PermissionService._instance = None
    svc = PermissionService()
    yield svc
    PermissionService._instance = None


def test_registry_only_contains_enforced_items(perm_service: PermissionService):
    keys = {item.key for item in perm_service.list_items()}
    # 保留项：宿主代码中有 ensure_access 调用点
    for key in (
        "debug.open",
        "settings.modify",
        "ntp.sync",
        "plugin.install",
        "plugin.manage",
        "layout.edit",
        "layout.add_widget",
        "layout.edit_widget",
        "layout.delete_widget",
        "layout.import_export",
        "world_time.manage",
        "clock.alarm.manage",
        "clock.timer.manage",
        "clock.stopwatch",
        "central.manage",
        "permission.manage",
    ):
        assert key in keys

    # 移除项：从未有校验路径，或已由其它功能项覆盖
    for key in (
        "settings.view",
        "plugin.configure",
        "layout.save",
        "widget.group",
        "widget.detach",
        "widget.float",
        "clock.alarm.trigger",
        "calendar.event.manage",
        "notification.send",
        "notification.configure",
        "file.import",
        "file.export",
        "window.fullscreen",
        "window.always_on_top",
        "network.request",
        "auth.login",
        "auth.logout",
    ):
        assert key not in keys


def test_empty_feature_key_denied(perm_service: PermissionService):
    assert perm_service.ensure_access("") is False
    assert perm_service.ensure_access("   ") is False


def test_unknown_feature_key_denied(perm_service: PermissionService):
    assert perm_service.ensure_access("no.such.key") is False
    assert perm_service.ensure_access("clock.alarm.mannage") is False  # 拼写错误不放行
    assert "未知" in perm_service.get_last_denied_reason("no.such.key")


def test_pristine_system_allows_user_level(perm_service: PermissionService):
    """全系统未启用任何登录方式时，USER 级功能无需登录可用（按设计）。"""
    assert perm_service.has_any_auth_configured() is False
    assert perm_service.ensure_access("clock.alarm.manage") is True
    assert perm_service.ensure_access("permission.manage") is True


def test_password_without_enabled_method_still_open(perm_service: PermissionService):
    """只设置密码、未启用任何登录方式：视为未设置登录方式，无需验证。"""
    perm_service.set_password(AccessLevel.USER, "1234")
    assert perm_service.has_password(AccessLevel.USER) is True
    # 只有密码、没有启用的登录方式，不算“已配置认证”
    assert perm_service.has_any_auth_configured() is False
    assert perm_service.ensure_access("clock.alarm.manage") is True
    assert perm_service.ensure_access("central.manage") is True


def test_auth_on_other_level_denies_unprotected_level(perm_service: PermissionService):
    """启用了 USER 级登录方式后，ADMIN 级（未启用登录方式）默认拒绝。"""
    perm_service.set_password(AccessLevel.USER, "1234")
    perm_service.set_enabled_methods_for_level(AccessLevel.USER, ["password"])
    assert perm_service.has_any_auth_configured() is True

    assert perm_service.ensure_access("central.manage") is False  # ADMIN 级
    assert "未启用任何登录方式" in perm_service.get_last_denied_reason("central.manage")
    assert perm_service.ensure_access("permission.manage") is True  # 豁免


def test_enabled_method_allows_with_valid_password(perm_service: PermissionService):
    perm_service.set_password(AccessLevel.USER, "1234")
    perm_service.set_enabled_methods_for_level(AccessLevel.USER, ["password"])

    granted: list[AccessLevel] = []
    perm_service.set_auth_prompt_callback(
        lambda level, methods, name, reason, parent: (
            granted.append(level),
            perm_service.authenticate(level, "password", {"password": "1234"}),
        )[-1]
    )
    assert perm_service.ensure_access("clock.alarm.manage") is True
    assert perm_service.session_level == AccessLevel.USER
    # 会话保持生效，后续不再触发弹窗
    assert perm_service.ensure_access("clock.timer.manage") is True
    assert granted == [AccessLevel.USER]

    perm_service.logout()
    assert perm_service.session_level == AccessLevel.NORMAL


def test_wrong_password_denied(perm_service: PermissionService):
    perm_service.set_password(AccessLevel.USER, "1234")
    perm_service.set_enabled_methods_for_level(AccessLevel.USER, ["password"])
    perm_service.set_auth_prompt_callback(
        lambda level, methods, name, reason, parent: perm_service.authenticate(level, "password", {"password": "0000"})
    )
    assert perm_service.ensure_access("clock.alarm.manage") is False
    assert perm_service.session_level == AccessLevel.NORMAL


def test_no_prompt_callback_denies(perm_service: PermissionService):
    perm_service.set_password(AccessLevel.USER, "1234")
    perm_service.set_enabled_methods_for_level(AccessLevel.USER, ["password"])
    assert perm_service.ensure_access("clock.alarm.manage") is False
    assert "登录窗口" in perm_service.get_last_denied_reason("clock.alarm.manage")


def test_clear_password_disables_password_method(perm_service: PermissionService):
    perm_service.set_password(AccessLevel.USER, "1234")
    perm_service.set_enabled_methods_for_level(AccessLevel.USER, ["password"])
    assert perm_service.get_enabled_methods_for_level(AccessLevel.USER) == ["password"]

    perm_service.clear_password(AccessLevel.USER)
    # 密码清除后登录方式同步移除，避免“启用了密码登录但无密码可验”的软锁死
    assert perm_service.get_enabled_methods_for_level(AccessLevel.USER) == []
    assert perm_service.has_any_auth_configured() is False
    assert perm_service.ensure_access("clock.alarm.manage") is True


def test_verify_password_roundtrip(perm_service: PermissionService):
    assert perm_service.has_password(AccessLevel.ADMIN) is False
    perm_service.set_password(AccessLevel.ADMIN, "s3cret")
    assert perm_service.has_password(AccessLevel.ADMIN) is True
    assert perm_service.verify_password(AccessLevel.ADMIN, "s3cret") is True
    assert perm_service.verify_password(AccessLevel.ADMIN, "wrong") is False


def test_short_password_rejected(perm_service: PermissionService):
    ok, _msg = perm_service.set_password(AccessLevel.USER, "abc")
    assert ok is False
    assert perm_service.has_password(AccessLevel.USER) is False


def test_plugin_item_key_collision_rejected(perm_service: PermissionService):
    # 与内置项冲突
    with pytest.raises(ValueError):
        perm_service.register_plugin_permission_item("plug_a", "debug.open", "钓鱼名")
    # 与其它插件的项冲突
    perm_service.register_plugin_permission_item("plug_a", "plug_a.custom", "自定义项")
    with pytest.raises(ValueError):
        perm_service.register_plugin_permission_item("plug_b", "plug_a.custom", "抢占")
    # 同一插件重复注册（热重载场景）允许覆盖
    perm_service.register_plugin_permission_item("plug_a", "plug_a.custom", "更新名称")
    assert perm_service.get_item_display_name("plug_a.custom") == "更新名称"
    # 卸载后清理
    perm_service.unregister_plugin_entries("plug_a")
    assert perm_service.get_item("plug_a.custom") is None


_MANAGEMENT_APIS = (
    "set_item_level",
    "set_enabled_methods_for_level",
    "set_password",
    "clear_password",
    "authenticate",
    "logout",
    "set_keep_login_session_enabled",
    "register_item",
    "register_auth_method",
    "set_auth_prompt_callback",
    "set_feature_blocker_callback",
    "unregister_plugin_entries",
)


def test_facade_does_not_expose_management_apis(perm_service: PermissionService):
    facade = perm_service.plugin_facade()
    assert isinstance(facade, PluginPermissionFacade)
    for name in _MANAGEMENT_APIS:
        assert not hasattr(facade, name), f"门面不应暴露 {name}"


def test_facade_supports_verify_and_register(perm_service: PermissionService):
    facade = perm_service.plugin_facade()
    assert facade.ensure_access("clock.alarm.manage") is True
    assert facade.get_item_level("plugin.manage") == AccessLevel.ADMIN
    assert facade.get_item_display_name("plugin.manage")
    assert facade.has_password(AccessLevel.USER) is False

    facade.register_plugin_permission_item("plug_x", "plug_x.action", "动作")
    assert perm_service.get_item("plug_x.action") is not None
    assert facade.ensure_access("plug_x.action") is True


def test_facade_is_cached(perm_service: PermissionService):
    assert perm_service.plugin_facade() is perm_service.plugin_facade()


def test_blocker_blocks_feature(perm_service: PermissionService):
    perm_service.set_feature_blocker_callback(lambda key: (key == "clock.alarm.manage"))
    assert perm_service.ensure_access("clock.alarm.manage") is False
    assert "集控" in perm_service.get_last_denied_reason("clock.alarm.manage")
    assert perm_service.ensure_access("clock.timer.manage") is True


def test_blocker_exception_fail_closed(perm_service: PermissionService):
    def _boom(key: str):
        raise RuntimeError("blocker crashed")

    perm_service.set_feature_blocker_callback(_boom)
    assert perm_service.ensure_access("clock.alarm.manage") is False
    assert "受限" in perm_service.get_last_denied_reason("clock.alarm.manage")

"""独立权限管理服务（与插件权限系统解耦）。"""

from __future__ import annotations

import json
import hashlib
import hmac
import os
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QObject, Signal

from app.constants import PERMISSION_CONFIG, PERMISSION_DATA_DIR
from app.utils.fs import mkdir_with_uac, write_text_with_uac
from app.utils.logger import logger
from app.utils.time_utils import load_json, save_json


class AccessLevel(IntEnum):
    NORMAL = 0
    USER = 1
    ADMIN = 2

    @property
    def key(self) -> str:
        return {
            AccessLevel.NORMAL: "normal",
            AccessLevel.USER: "user",
            AccessLevel.ADMIN: "admin",
        }[self]

    @property
    def label(self) -> str:
        return {
            AccessLevel.NORMAL: "普通",
            AccessLevel.USER: "用户",
            AccessLevel.ADMIN: "管理员",
        }[self]

    @classmethod
    def from_value(cls, value: Any, default: "AccessLevel" = None) -> "AccessLevel":
        if default is None:
            default = cls.NORMAL
        if isinstance(value, AccessLevel):
            return value
        if isinstance(value, int):
            return {
                0: cls.NORMAL,
                1: cls.USER,
                2: cls.ADMIN,
            }.get(value, default)
        text = str(value or "").strip().lower()
        return {
            "0": cls.NORMAL,
            "normal": cls.NORMAL,
            "1": cls.USER,
            "user": cls.USER,
            "2": cls.ADMIN,
            "admin": cls.ADMIN,
        }.get(text, default)


@dataclass
class PermissionItem:
    key: str
    name: str
    category: str = "系统"
    description: str = ""
    default_level: AccessLevel = AccessLevel.NORMAL


@dataclass
class AuthMethod:
    method_id: str
    display_name: str
    verifier: Callable[[AccessLevel, dict[str, Any], object | None], bool]
    supported_levels: set[AccessLevel]
    provider: str = "builtin"
    config_provider: Callable[["PermissionService", str], "AuthMethodConfigSpec | None"] | None = None


@dataclass
class AuthMethodConfigPage:
    page_id: str
    title: str
    widget_factory: Callable[[object | None, dict[str, Any]], object]
    before_next: Callable[[object, dict[str, Any]], tuple[bool, str] | bool] | None = None


@dataclass
class AuthMethodConfigSpec:
    window_title: str
    pages: list[AuthMethodConfigPage]
    initial_state: dict[str, Any] | None = None
    on_finish: Callable[[dict[str, Any]], tuple[bool, str] | bool] | None = None


AuthPromptCallback = Callable[[AccessLevel, list[str], str, str, object | None], bool]
FeatureBlockerCallback = Callable[[str], bool | tuple[bool, str]]


class PluginPermissionFacade:
    """暴露给插件与画布组件的安全门面：只提供校验、注册与只读查询，避免插件提权。"""

    def __init__(self, service: "PermissionService"):
        self._service = service

    def ensure_access(
        self,
        feature_key: str,
        *,
        parent: object | None = None,
        reason: str = "",
    ) -> bool:
        return self._service.ensure_access(feature_key, parent=parent, reason=reason)

    def register_plugin_permission_item(
        self,
        plugin_id: str,
        item_key: str,
        display_name: str,
        *,
        category: str = "插件",
        description: str = "",
        default_level: AccessLevel = AccessLevel.USER,
    ) -> None:
        self._service.register_plugin_permission_item(
            plugin_id,
            item_key,
            display_name,
            category=category,
            description=description,
            default_level=default_level,
        )

    def register_plugin_auth_method(
        self,
        plugin_id: str,
        method_id: str,
        display_name: str,
        verifier: Callable[[AccessLevel, dict[str, Any], object | None], bool],
        *,
        supported_levels: set[AccessLevel] | None = None,
        config_provider: Callable[["PermissionService", str], "AuthMethodConfigSpec | None"] | None = None,
    ) -> None:
        self._service.register_plugin_auth_method(
            plugin_id,
            method_id,
            display_name,
            verifier,
            supported_levels=supported_levels,
            config_provider=config_provider,
        )

    def get_plugin_permission_data_dir(self, plugin_id: str) -> Path | None:
        return self._service.get_plugin_permission_data_dir(plugin_id)

    def resolve_plugin_permission_data_path(self, plugin_id: str, *parts: str | Path) -> Path | None:
        return self._service.resolve_plugin_permission_data_path(plugin_id, *parts)

    def has_password(self, level: AccessLevel) -> bool:
        return self._service.has_password(level)

    def get_item_level(self, key: str) -> AccessLevel:
        return self._service.get_item_level(key)

    def get_item_display_name(self, key: str) -> str:
        return self._service.get_item_display_name(key)


class PermissionService(QObject):
    """应用级权限服务，与插件安装/系统权限询问机制独立。

    未启用任何登录方式时用户/管理员等级视为无需验证；一旦有等级启用登录方式，
    未启用登录方式的等级默认拒绝（permission.manage 除外，便于修复配置）。
    """

    changed = Signal()
    registryChanged = Signal()
    sessionChanged = Signal(str)
    accessDenied = Signal(str, str, str)  # feature_key, required_level, reason

    _instance: "PermissionService | None" = None

    @classmethod
    def instance(cls) -> "PermissionService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self, parent=None):
        super().__init__(parent)

        self._items: dict[str, PermissionItem] = {}
        self._plugin_owned_items: dict[str, set[str]] = {}

        self._auth_methods: dict[str, AuthMethod] = {}
        self._plugin_owned_methods: dict[str, set[str]] = {}
        self._plugin_facade: PluginPermissionFacade | None = None

        self._session_level = AccessLevel.NORMAL
        self._auth_prompt_callback: AuthPromptCallback | None = None
        self._feature_blocker_callback: FeatureBlockerCallback | None = None
        self._last_denied_reasons: dict[str, str] = {}

        self._data: dict[str, Any] = load_json(PERMISSION_CONFIG, {})
        if not isinstance(self._data, dict):
            self._data = {}

        self._permission_data_dir = Path(PERMISSION_DATA_DIR)
        self._permission_default_dir = self._permission_data_dir / "default"
        self._permission_plugins_dir = self._permission_data_dir / "plugins"

        self._data.setdefault("item_levels", {})
        self._data.setdefault("level_auth_methods", {"user": [], "admin": []})
        self._data.setdefault("keep_login_session", True)
        self._data.setdefault(
            "password",
            {
                "user": {"salt": "", "hash": ""},
                "admin": {"salt": "", "hash": ""},
            },
        )

        self._ensure_permission_storage_layout()

        self._register_builtin_items()
        self._register_builtin_auth_methods()
        self._save()

    def plugin_facade(self) -> PluginPermissionFacade:
        """返回可安全交给插件/组件使用的只读门面（含注册类操作）。"""
        if self._plugin_facade is None:
            self._plugin_facade = PluginPermissionFacade(self)
        return self._plugin_facade

    def set_auth_prompt_callback(self, callback: AuthPromptCallback | None) -> None:
        self._auth_prompt_callback = callback

    def set_feature_blocker_callback(self, callback: FeatureBlockerCallback | None) -> None:
        self._feature_blocker_callback = callback

    def _ensure_permission_storage_layout(self) -> None:
        mkdir_with_uac(self._permission_default_dir, parents=True, exist_ok=True)
        mkdir_with_uac(self._permission_plugins_dir, parents=True, exist_ok=True)

        default_file = self._permission_default_dir / "default_config.json"
        if default_file.exists():
            return

        template = {
            "version": 1,
            "note": "登录类插件认证数据建议存放在 config/permission/plugins/<plugin_id>/ 下。",
            "plugins_dir": "plugins",
        }
        write_text_with_uac(
            default_file,
            json.dumps(template, ensure_ascii=False, indent=2),
            encoding="utf-8",
            ensure_parent=True,
        )

    def get_permission_data_dir(self) -> Path:
        """返回权限数据根目录（config/permission）。"""
        self._ensure_permission_storage_layout()
        return self._permission_data_dir

    def get_plugin_permission_data_dir(self, plugin_id: str) -> Path | None:
        pid = str(plugin_id or "").strip()
        if not pid:
            return None
        self._ensure_permission_storage_layout()
        path = self._permission_plugins_dir / pid
        mkdir_with_uac(path, parents=True, exist_ok=True)
        return path

    def resolve_plugin_permission_data_path(self, plugin_id: str, *parts: str | Path) -> Path | None:
        """在插件权限目录下拼接路径并确保父目录存在。"""
        base = self.get_plugin_permission_data_dir(plugin_id)
        if base is None:
            return None
        path = base.joinpath(*(str(p) for p in parts))
        mkdir_with_uac(path.parent, parents=True, exist_ok=True)
        return path

    def _register_builtin_items(self) -> None:
        # 仅注册在宿主代码中有 ensure_access 调用点的功能项；
        # 没有校验路径的项一律不注册，避免权限管理界面出现“形同虚设”的开关。
        defaults = [
            PermissionItem("debug.open", "打开调试面板", "系统", "从标题栏打开调试窗口", AccessLevel.USER),
            PermissionItem("settings.modify", "修改应用设置", "系统", "更改设置页任意配置项", AccessLevel.USER),
            PermissionItem("ntp.sync", "同步网络时间", "系统", "通过 NTP 服务器同步系统时间", AccessLevel.USER),
            PermissionItem("plugin.install", "安装插件", "插件", "导入插件、从商店安装插件", AccessLevel.USER),
            PermissionItem("plugin.manage", "管理插件", "插件", "启停、热重载、删除插件", AccessLevel.ADMIN),
            # 布局编辑（保存布局属于布局编辑会话的一部分，随 layout.edit 一并校验）
            PermissionItem("layout.edit", "编辑布局", "全屏时钟", "进入/退出布局编辑模式", AccessLevel.USER),
            PermissionItem("layout.add_widget", "添加组件", "全屏时钟", "在布局中新增组件", AccessLevel.USER),
            PermissionItem("layout.edit_widget", "编辑组件设置", "全屏时钟", "编辑组件配置参数", AccessLevel.USER),
            PermissionItem("layout.delete_widget", "删除组件", "全屏时钟", "从布局删除组件", AccessLevel.USER),
            PermissionItem("layout.import_export", "导入导出布局", "全屏时钟", "导入/导出布局文件", AccessLevel.USER),
            PermissionItem("world_time.manage", "管理世界时钟", "全屏时钟", "添加或删除时区卡片", AccessLevel.USER),
            # 闹钟与计时（分组/分离等画布子操作已由 layout.edit_widget 覆盖）
            PermissionItem("clock.alarm.manage", "管理闹钟", "时钟", "创建、编辑、删除闹钟", AccessLevel.USER),
            PermissionItem("clock.timer.manage", "管理计时器", "时钟", "创建、删除计时器", AccessLevel.USER),
            PermissionItem("clock.stopwatch", "秒表功能", "时钟", "开始使用秒表计时", AccessLevel.USER),
            PermissionItem("central.manage", "管理集控", "集控", "修改集控连接与策略", AccessLevel.ADMIN),
            PermissionItem("permission.manage", "管理权限系统", "权限", "修改权限等级与认证方式", AccessLevel.ADMIN),
        ]
        for item in defaults:
            self.register_item(item)

    def _register_builtin_auth_methods(self) -> None:
        self.register_auth_method(
            method_id="password",
            display_name="密码登录",
            verifier=self._verify_password_method,
            supported_levels={AccessLevel.USER, AccessLevel.ADMIN},
            provider="builtin",
        )

    def register_item(self, item: PermissionItem) -> None:
        key = str(item.key or "").strip()
        if not key:
            raise ValueError("permission item key 不能为空")
        normalized = PermissionItem(
            key=key,
            name=str(item.name or key).strip() or key,
            category=str(item.category or "系统").strip() or "系统",
            description=str(item.description or "").strip(),
            default_level=AccessLevel.from_value(item.default_level),
        )
        self._items[key] = normalized
        self.registryChanged.emit()

    def register_plugin_permission_item(
        self,
        plugin_id: str,
        item_key: str,
        display_name: str,
        *,
        category: str = "插件",
        description: str = "",
        default_level: AccessLevel = AccessLevel.USER,
    ) -> None:
        pid = str(plugin_id or "").strip()
        key = str(item_key or "").strip()
        if not pid or not key:
            raise ValueError("plugin_id / item_key 不能为空")
        # 禁止覆盖内置权限项或其它插件注册的权限项，防止篡改展示信息
        if key in self._items and key not in self._plugin_owned_items.get(pid, set()):
            raise ValueError(f"权限项 key 已被占用: {key}")
        self.register_item(
            PermissionItem(
                key=key,
                name=display_name,
                category=category,
                description=description,
                default_level=default_level,
            )
        )
        self._plugin_owned_items.setdefault(pid, set()).add(key)

    def unregister_plugin_entries(self, plugin_id: str) -> None:
        pid = str(plugin_id or "").strip()
        if not pid:
            return

        item_keys = self._plugin_owned_items.pop(pid, set())
        for key in item_keys:
            self._items.pop(key, None)
            self._data.get("item_levels", {}).pop(key, None)

        method_ids = self._plugin_owned_methods.pop(pid, set())
        for method_id in method_ids:
            self._auth_methods.pop(method_id, None)
            for level_key in ("user", "admin"):
                methods = list(self._data.get("level_auth_methods", {}).get(level_key, []))
                methods = [mid for mid in methods if mid != method_id]
                self._data.setdefault("level_auth_methods", {}).setdefault(level_key, [])
                self._data["level_auth_methods"][level_key] = methods

        self._save()
        self.registryChanged.emit()
        self.changed.emit()

    def list_items(self) -> list[PermissionItem]:
        return sorted(
            self._items.values(),
            key=lambda item: (item.category, item.name, item.key),
        )

    def get_item(self, key: str) -> PermissionItem | None:
        return self._items.get(str(key or "").strip())

    def get_item_level(self, key: str) -> AccessLevel:
        item = self.get_item(key)
        default_level = item.default_level if item else AccessLevel.NORMAL
        raw = self._data.get("item_levels", {}).get(str(key or "").strip(), default_level.key)
        return AccessLevel.from_value(raw, default=default_level)

    def set_item_level(self, key: str, level: AccessLevel) -> None:
        feature_key = str(key or "").strip()
        if not feature_key:
            return
        item = self.get_item(feature_key)
        if item is None:
            return

        normalized = AccessLevel.from_value(level, default=item.default_level)
        current = self.get_item_level(feature_key)
        if current == normalized:
            return

        self._data.setdefault("item_levels", {})[feature_key] = normalized.key
        self._save()
        self.changed.emit()

    def register_auth_method(
        self,
        method_id: str,
        display_name: str,
        verifier: Callable[[AccessLevel, dict[str, Any], object | None], bool],
        *,
        supported_levels: set[AccessLevel] | None = None,
        provider: str = "builtin",
        config_provider: Callable[["PermissionService", str], "AuthMethodConfigSpec | None"] | None = None,
    ) -> None:
        mid = str(method_id or "").strip()
        if not mid:
            raise ValueError("method_id 不能为空")
        levels = supported_levels or {AccessLevel.USER, AccessLevel.ADMIN}
        normalized_levels = {AccessLevel.from_value(v, default=AccessLevel.USER) for v in levels}
        self._auth_methods[mid] = AuthMethod(
            method_id=mid,
            display_name=str(display_name or mid).strip() or mid,
            verifier=verifier,
            supported_levels=normalized_levels,
            provider=str(provider or "builtin").strip() or "builtin",
            config_provider=config_provider,
        )
        self.registryChanged.emit()

    def register_plugin_auth_method(
        self,
        plugin_id: str,
        method_id: str,
        display_name: str,
        verifier: Callable[[AccessLevel, dict[str, Any], object | None], bool],
        *,
        supported_levels: set[AccessLevel] | None = None,
        config_provider: Callable[["PermissionService", str], "AuthMethodConfigSpec | None"] | None = None,
    ) -> None:
        pid = str(plugin_id or "").strip()
        if not pid:
            raise ValueError("plugin_id 不能为空")

        # 登录类插件必须使用权限目录存储认证数据。
        self.get_plugin_permission_data_dir(pid)

        self.register_auth_method(
            method_id=method_id,
            display_name=display_name,
            verifier=verifier,
            supported_levels=supported_levels,
            provider=f"plugin:{pid}",
            config_provider=config_provider,
        )
        self._plugin_owned_methods.setdefault(pid, set()).add(str(method_id or "").strip())

    def get_auth_method_config_spec(self, method_id: str) -> AuthMethodConfigSpec | None:
        method = self.get_auth_method(method_id)
        if method is None or method.config_provider is None:
            return None
        try:
            spec = method.config_provider(self, method.method_id)
            if spec is None or not spec.pages:
                return None
            return spec
        except Exception:
            logger.exception("获取登录方式配置规范失败: {}", method_id)
            return None

    def list_auth_methods_for_level(self, level: AccessLevel) -> list[AuthMethod]:
        target = AccessLevel.from_value(level)
        result: list[AuthMethod] = []
        for method in self._auth_methods.values():
            if target in method.supported_levels:
                result.append(method)
        result.sort(key=lambda item: item.display_name)
        return result

    def get_auth_method(self, method_id: str) -> AuthMethod | None:
        return self._auth_methods.get(str(method_id or "").strip())

    def get_enabled_methods_for_level(self, level: AccessLevel) -> list[str]:
        target = AccessLevel.from_value(level)
        if target == AccessLevel.NORMAL:
            return []
        level_key = target.key
        values = list(self._data.get("level_auth_methods", {}).get(level_key, []))
        result: list[str] = []
        for method_id in values:
            method = self.get_auth_method(method_id)
            if method is None:
                continue
            if target not in method.supported_levels:
                continue
            result.append(method_id)
        return result

    def set_enabled_methods_for_level(self, level: AccessLevel, method_ids: list[str]) -> None:
        target = AccessLevel.from_value(level)
        if target == AccessLevel.NORMAL:
            return
        valid = []
        for method_id in method_ids:
            method = self.get_auth_method(method_id)
            if method is None:
                continue
            if target not in method.supported_levels:
                continue
            valid.append(method_id)
        self._data.setdefault("level_auth_methods", {})[target.key] = valid
        self._save()
        self.changed.emit()

    @staticmethod
    def _hash_password(password: str, salt: str) -> str:
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            str(password or "").encode("utf-8"),
            bytes.fromhex(salt),
            120000,
        )
        return digest.hex()

    def _password_record(self, level: AccessLevel) -> dict[str, str]:
        target = AccessLevel.from_value(level)
        if target == AccessLevel.NORMAL:
            raise ValueError("普通等级不需要密码")
        container = self._data.setdefault("password", {})
        record = container.setdefault(target.key, {"salt": "", "hash": ""})
        if not isinstance(record, dict):
            record = {"salt": "", "hash": ""}
            container[target.key] = record
        record.setdefault("salt", "")
        record.setdefault("hash", "")
        return record

    def has_password(self, level: AccessLevel) -> bool:
        if AccessLevel.from_value(level) == AccessLevel.NORMAL:
            return True
        record = self._password_record(level)
        return bool(record.get("salt") and record.get("hash"))

    def set_password(self, level: AccessLevel, password: str) -> tuple[bool, str]:
        target = AccessLevel.from_value(level)
        if target == AccessLevel.NORMAL:
            return False, "普通等级不需要密码"
        text = str(password or "")
        if len(text) < 1:
            return False, "密码不能为空"
        if len(text) < 4:
            return False, "密码长度至少为 4 个字符"
        salt = os.urandom(16).hex()
        password_hash = self._hash_password(text, salt)
        record = self._password_record(target)
        record["salt"] = salt
        record["hash"] = password_hash
        self._save()
        self.changed.emit()
        return True, ""

    def clear_password(self, level: AccessLevel) -> None:
        target = AccessLevel.from_value(level)
        if target == AccessLevel.NORMAL:
            return
        record = self._password_record(target)
        record["salt"] = ""
        record["hash"] = ""
        # 密码已清除，同步移除该等级启用的密码登录方式，避免出现
        # “启用了密码登录但无密码可验”的软锁死。
        methods = [mid for mid in self.get_enabled_methods_for_level(target) if mid != "password"]
        self._data.setdefault("level_auth_methods", {})[target.key] = methods
        self._save()
        self.changed.emit()

    def verify_password(self, level: AccessLevel, password: str) -> bool:
        target = AccessLevel.from_value(level)
        if target == AccessLevel.NORMAL:
            return True
        record = self._password_record(target)
        salt = str(record.get("salt") or "")
        expected = str(record.get("hash") or "")
        if not salt or not expected:
            return False
        actual = self._hash_password(str(password or ""), salt)
        return hmac.compare_digest(actual, expected)

    def _verify_password_method(
        self,
        level: AccessLevel,
        payload: dict[str, Any],
        _parent: object | None = None,
    ) -> bool:
        return self.verify_password(level, str(payload.get("password") or ""))

    @property
    def session_level(self) -> AccessLevel:
        return self._session_level

    @property
    def keep_login_session_enabled(self) -> bool:
        return bool(self._data.get("keep_login_session", True))

    def set_keep_login_session_enabled(self, value: bool) -> None:
        enabled = bool(value)
        if enabled == self.keep_login_session_enabled:
            return
        self._data["keep_login_session"] = enabled
        self._save()
        self.changed.emit()
        if not enabled:
            self.logout()

    def logout(self) -> None:
        if self._session_level == AccessLevel.NORMAL:
            return
        self._session_level = AccessLevel.NORMAL
        self.sessionChanged.emit(self._session_level.key)

    def authenticate(
        self,
        level: AccessLevel,
        method_id: str,
        payload: dict[str, Any] | None = None,
        parent: object | None = None,
    ) -> bool:
        target = AccessLevel.from_value(level)
        if target == AccessLevel.NORMAL:
            return True

        method = self.get_auth_method(method_id)
        if method is None:
            logger.warning("未知认证方式: {}", method_id)
            return False
        if target not in method.supported_levels:
            logger.warning("认证方式 {} 不支持等级 {}", method_id, target.key)
            return False

        try:
            ok = bool(method.verifier(target, payload or {}, parent))
        except Exception:
            logger.exception("认证方式执行异常: method_id={}", method_id)
            ok = False

        if ok and self.keep_login_session_enabled and self._session_level < target:
            self._session_level = target
            self.sessionChanged.emit(self._session_level.key)
        return ok

    def ensure_access(
        self,
        feature_key: str,
        *,
        parent: object | None = None,
        reason: str = "",
    ) -> bool:
        key = str(feature_key or "").strip()
        if not key:
            logger.warning("ensure_access 收到空 feature_key，已拒绝访问")
            return False
        if key not in self._items:
            logger.warning("ensure_access 收到未注册的 feature_key: {}", key)
            reason_text = "未知的功能权限项"
            self._last_denied_reasons[key] = reason_text
            self.accessDenied.emit(key, AccessLevel.NORMAL.key, reason_text)
            return False

        required = self.get_item_level(key)
        if required == AccessLevel.NORMAL:
            self._last_denied_reasons.pop(key, None)
            return True

        blocked, block_reason = self._is_feature_blocked(key)
        if blocked:
            reason_text = block_reason or "该功能被集控策略限制"
            self._last_denied_reasons[key] = reason_text
            self.accessDenied.emit(key, required.key, reason_text)
            return False

        if self.keep_login_session_enabled and self._session_level >= required:
            self._last_denied_reasons.pop(key, None)
            return True

        methods = self.get_enabled_methods_for_level(required)
        if not methods:
            if key != "permission.manage" and self.has_any_auth_configured():
                # 其它等级启用了登录方式，但该等级未启用任何登录方式：
                # 按失败关闭处理，避免出现“设了验证却全部放行”的失控状态。
                # permission.manage 豁免，保证管理员始终能进来修复配置。
                reason_text = (
                    f"系统已启用登录验证，但{required.label}级未启用任何登录方式，已拒绝访问；"
                    "请到权限管理中为该等级启用登录方式。"
                )
                self._last_denied_reasons[key] = reason_text
                self.accessDenied.emit(key, required.key, reason_text)
                return False
            # 全系统未启用任何登录方式（含“设置了密码但未启用”的情况），
            # 或正在打开权限管理窗口进行修复，视为无需验证。
            self._last_denied_reasons.pop(key, None)
            return True

        if self._auth_prompt_callback is None:
            reason_text = "未配置登录窗口"
            self._last_denied_reasons[key] = reason_text
            self.accessDenied.emit(key, required.key, reason_text)
            return False

        item_name = self.get_item_display_name(key)
        ok = bool(self._auth_prompt_callback(required, methods, item_name, reason, parent))
        if ok:
            if self.keep_login_session_enabled:
                if self._session_level < required:
                    self._session_level = required
                    self.sessionChanged.emit(self._session_level.key)
            self._last_denied_reasons.pop(key, None)
            return True

        reason_text = reason or "用户取消验证"
        self._last_denied_reasons[key] = reason_text
        self.accessDenied.emit(key, required.key, reason_text)
        return False

    def has_any_auth_configured(self) -> bool:
        """是否有任何等级启用了登录方式（只设置密码但未启用不算）。"""
        for level in (AccessLevel.USER, AccessLevel.ADMIN):
            if self.get_enabled_methods_for_level(level):
                return True
        return False

    def get_last_denied_reason(self, feature_key: str) -> str:
        return str(self._last_denied_reasons.get(str(feature_key or "").strip(), ""))

    def _is_feature_blocked(self, key: str) -> tuple[bool, str]:
        if self._feature_blocker_callback is None:
            return False, ""
        try:
            result = self._feature_blocker_callback(key)
            if isinstance(result, tuple):
                blocked = bool(result[0])
                reason = str(result[1] or "") if len(result) > 1 else ""
                return blocked, reason
            return bool(result), ""
        except Exception:
            # blocker 异常时按受限处理（fail-closed），避免拦截机制失效
            logger.exception("feature blocker 回调异常: {}", key)
            return True, "集控策略检查异常，已按受限处理"

    def get_item_display_name(self, key: str) -> str:
        item = self.get_item(key)
        return item.name if item else key

    def _save(self) -> None:
        save_json(PERMISSION_CONFIG, self._data)

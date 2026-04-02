"""独立权限管理服务（与插件权限系统解耦）。"""
from __future__ import annotations

import json
import hashlib
import hmac
import os
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Any, Callable, Optional

from PySide6.QtCore import QObject, Signal

from app.constants import PERMISSION_CONFIG, PERMISSION_DATA_DIR
from app.utils.fs import mkdir_with_uac, write_text_with_uac
from app.utils.logger import logger
from app.utils.time_utils import load_json, save_json


class AccessLevel(IntEnum):
    """功能访问等级。"""

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
    verifier: Callable[[AccessLevel, dict[str, Any], Optional[object]], bool]
    supported_levels: set[AccessLevel]
    provider: str = "builtin"
    config_provider: Optional[Callable[["PermissionService", str], "AuthMethodConfigSpec | None"]] = None


@dataclass
class AuthMethodConfigPage:
    page_id: str
    title: str
    widget_factory: Callable[[Optional[object], dict[str, Any]], object]
    before_next: Optional[Callable[[object, dict[str, Any]], tuple[bool, str] | bool]] = None


@dataclass
class AuthMethodConfigSpec:
    window_title: str
    pages: list[AuthMethodConfigPage]
    initial_state: Optional[dict[str, Any]] = None
    on_finish: Optional[Callable[[dict[str, Any]], tuple[bool, str] | bool]] = None


AuthPromptCallback = Callable[[AccessLevel, list[str], str, str, Optional[object]], bool]
FeatureBlockerCallback = Callable[[str], bool | tuple[bool, str]]


class PermissionService(QObject):
    """应用级权限服务。

    说明
    ----
    - 与插件安装/系统权限询问机制完全独立。
    - 普通等级无需登录。
    - 用户/管理员等级若未配置任何登录方式，则视为无需验证。
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
        self._data.setdefault("password", {
            "user": {"salt": "", "hash": ""},
            "admin": {"salt": "", "hash": ""},
        })

        self._ensure_permission_storage_layout()

        self._register_builtin_items()
        self._register_builtin_auth_methods()
        self._save()

    # ------------------------------------------------------------------ #
    # 回调注入
    # ------------------------------------------------------------------ #

    def set_auth_prompt_callback(self, callback: AuthPromptCallback | None) -> None:
        self._auth_prompt_callback = callback

    def set_feature_blocker_callback(self, callback: FeatureBlockerCallback | None) -> None:
        self._feature_blocker_callback = callback

    # ------------------------------------------------------------------ #
    # 权限数据目录（登录类插件专用存储）
    # ------------------------------------------------------------------ #

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
        """返回插件在权限目录下的专属子目录。"""
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

    # ------------------------------------------------------------------ #
    # 内置注册
    # ------------------------------------------------------------------ #

    def _register_builtin_items(self) -> None:
        defaults = [
            PermissionItem("debug.open", "打开调试面板", "系统", "从标题栏打开调试窗口", AccessLevel.USER),
            PermissionItem("settings.modify", "修改应用设置", "系统", "更改设置页任意配置项", AccessLevel.USER),
            PermissionItem("plugin.install", "安装插件", "插件", "导入插件、从商店安装插件", AccessLevel.USER),
            PermissionItem("plugin.manage", "管理插件", "插件", "启停、热重载、删除插件", AccessLevel.ADMIN),
            PermissionItem("layout.edit", "编辑布局", "全屏时钟", "进入/退出布局编辑模式", AccessLevel.USER),
            PermissionItem("layout.add_widget", "添加组件", "全屏时钟", "在布局中新增组件", AccessLevel.USER),
            PermissionItem("layout.edit_widget", "编辑组件设置", "全屏时钟", "编辑组件配置参数", AccessLevel.USER),
            PermissionItem("layout.delete_widget", "删除组件", "全屏时钟", "从布局删除组件", AccessLevel.USER),
            PermissionItem("layout.import_export", "导入导出布局", "全屏时钟", "导入/导出布局文件", AccessLevel.USER),
            PermissionItem("world_time.manage", "管理世界时钟列表", "全屏时钟", "添加或删除时区卡片", AccessLevel.USER),
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
            config_provider=self._password_auth_config_spec,
        )

    # ------------------------------------------------------------------ #
    # 功能项注册
    # ------------------------------------------------------------------ #

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

    # ------------------------------------------------------------------ #
    # 登录方式注册
    # ------------------------------------------------------------------ #

    def register_auth_method(
        self,
        method_id: str,
        display_name: str,
        verifier: Callable[[AccessLevel, dict[str, Any], Optional[object]], bool],
        *,
        supported_levels: set[AccessLevel] | None = None,
        provider: str = "builtin",
        config_provider: Optional[Callable[["PermissionService", str], "AuthMethodConfigSpec | None"]] = None,
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
        verifier: Callable[[AccessLevel, dict[str, Any], Optional[object]], bool],
        *,
        supported_levels: set[AccessLevel] | None = None,
        config_provider: Optional[Callable[["PermissionService", str], "AuthMethodConfigSpec | None"]] = None,
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

    # ------------------------------------------------------------------ #
    # 内置登录方式配置（密码）
    # ------------------------------------------------------------------ #

    def _password_auth_config_spec(self, _service: "PermissionService", _method_id: str) -> AuthMethodConfigSpec:
        from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout
        from qfluentwidgets import BodyLabel, PasswordLineEdit, PushButton

        service = self

        class _PasswordConfigWidget:
            def __init__(self, parent=None, _state=None):
                from PySide6.QtWidgets import QWidget

                self.widget = QWidget(parent)
                root = QVBoxLayout(self.widget)
                root.setContentsMargins(12, 8, 12, 8)
                root.setSpacing(10)

                root.addWidget(BodyLabel("用户级密码", self.widget))
                self.user_input = PasswordLineEdit(self.widget)
                self.user_input.setPlaceholderText("设置用户级密码（留空不修改）")
                root.addWidget(self.user_input)

                user_row = QHBoxLayout()
                self.user_clear_btn = PushButton("清除用户级密码", self.widget)
                user_row.addWidget(self.user_clear_btn)
                user_row.addStretch(1)
                root.addLayout(user_row)

                root.addWidget(BodyLabel("管理员级密码", self.widget))
                self.admin_input = PasswordLineEdit(self.widget)
                self.admin_input.setPlaceholderText("设置管理员级密码（留空不修改）")
                root.addWidget(self.admin_input)

                admin_row = QHBoxLayout()
                self.admin_clear_btn = PushButton("清除管理员级密码", self.widget)
                admin_row.addWidget(self.admin_clear_btn)
                admin_row.addStretch(1)
                root.addLayout(admin_row)

                self.user_clear_btn.clicked.connect(lambda: service.clear_password(AccessLevel.USER))
                self.admin_clear_btn.clicked.connect(lambda: service.clear_password(AccessLevel.ADMIN))

            def take_state(self) -> dict[str, Any]:
                return {
                    "user_password": self.user_input.text().strip(),
                    "admin_password": self.admin_input.text().strip(),
                }

            def validate_and_save(self) -> tuple[bool, str]:
                state = self.take_state()
                user_pwd = str(state.get("user_password") or "")
                admin_pwd = str(state.get("admin_password") or "")

                if user_pwd:
                    service.set_password(AccessLevel.USER, user_pwd)
                if admin_pwd:
                    service.set_password(AccessLevel.ADMIN, admin_pwd)
                return True, ""

        def _factory(parent: Optional[object], state: dict[str, Any]) -> object:
            editor = _PasswordConfigWidget(parent=parent, _state=state)
            state["_editor"] = editor
            return editor.widget

        def _finish(state: dict[str, Any]) -> tuple[bool, str]:
            editor = state.get("_editor")
            if editor is None or not hasattr(editor, "validate_and_save"):
                return True, ""
            return editor.validate_and_save()

        return AuthMethodConfigSpec(
            window_title="配置登录方式：密码登录",
            pages=[
                AuthMethodConfigPage(
                    page_id="password",
                    title="密码设置",
                    widget_factory=_factory,
                )
            ],
            initial_state={},
            on_finish=_finish,
        )

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

    # ------------------------------------------------------------------ #
    # 密码方法
    # ------------------------------------------------------------------ #

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

    def set_password(self, level: AccessLevel, password: str) -> None:
        target = AccessLevel.from_value(level)
        if target == AccessLevel.NORMAL:
            return
        text = str(password or "")
        if len(text) < 1:
            raise ValueError("密码不能为空")
        salt = os.urandom(16).hex()
        password_hash = self._hash_password(text, salt)
        record = self._password_record(target)
        record["salt"] = salt
        record["hash"] = password_hash
        self._save()
        self.changed.emit()

    def clear_password(self, level: AccessLevel) -> None:
        target = AccessLevel.from_value(level)
        if target == AccessLevel.NORMAL:
            return
        record = self._password_record(target)
        record["salt"] = ""
        record["hash"] = ""
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

    # ------------------------------------------------------------------ #
    # 会话与鉴权
    # ------------------------------------------------------------------ #

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
            return True

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
        # 按需求：若未设置登录方式，则视为可直接使用。
        if not methods:
            self._last_denied_reasons.pop(key, None)
            return True

        if self._auth_prompt_callback is None:
            reason_text = "未配置登录窗口"
            self._last_denied_reasons[key] = reason_text
            self.accessDenied.emit(key, required.key, reason_text)
            return False

        item_name = self.get_item_display_name(key)
        ok = bool(self._auth_prompt_callback(required, methods, item_name, reason, parent))
        if ok and self.keep_login_session_enabled and self._session_level < required:
            self._session_level = required
            self.sessionChanged.emit(self._session_level.key)
            self._last_denied_reasons.pop(key, None)
            return True
        if ok:
            self._last_denied_reasons.pop(key, None)
            return True

        reason_text = reason or "用户取消验证"
        self._last_denied_reasons[key] = reason_text
        self.accessDenied.emit(key, required.key, reason_text)
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
            logger.exception("feature blocker 回调异常: {}", key)
            return False, ""

    def get_item_display_name(self, key: str) -> str:
        item = self.get_item(key)
        return item.name if item else key

    # ------------------------------------------------------------------ #
    # 持久化
    # ------------------------------------------------------------------ #

    def _save(self) -> None:
        save_json(PERMISSION_CONFIG, self._data)

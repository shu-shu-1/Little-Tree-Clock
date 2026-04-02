"""集控服务（客户端侧）。"""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
import os
import socket
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import requests
from PySide6.QtCore import QObject, Signal, QTimer

from app.constants import APP_NAME, APP_VERSION, CENTRAL_CONTROL_CONFIG
from app.utils.logger import logger
from app.utils.time_utils import load_json, save_json


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _norm_list(values: Any) -> list[str]:
    if isinstance(values, str):
        values = [v.strip() for v in values.split(",") if v.strip()]
    if not isinstance(values, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _default_policy() -> dict[str, Any]:
    return {
        "enabled": False,
        "version": 1,
        "updated_at": "",
        "updated_by": "",
        "global_settings": {},
        "blocked_features": [],
        "blocked_permission_items": [],
        "deny_plugin_install": False,
        "managed_plugins": [],
        "fullscreen_clock_list": [],
        "forced_layouts": {},
        "plugin_configs": {},
        "managed_devices": [],
        "central_events": {},
        "note": "",
    }


class CentralControlService(QObject):
    """集控策略与远端服务器交互服务。"""

    changed = Signal()
    policyApplied = Signal()
    devicesUpdated = Signal()
    eventRegistered = Signal(str)
    syncStateChanged = Signal()

    _instance: "CentralControlService | None" = None

    @classmethod
    def instance(cls) -> "CentralControlService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data: dict[str, Any] = load_json(CENTRAL_CONTROL_CONFIG, {})
        if not isinstance(self._data, dict):
            self._data = {}

        self._data.setdefault("enabled", False)
        self._data.setdefault("server_url", "")
        self._data.setdefault("device_id", f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}")
        self._data.setdefault("device_name", APP_NAME)
        self._data.setdefault("poll_interval_sec", 60)
        self._data.setdefault("server_bundle_dir", "")
        self._data.setdefault("server_admin_password", "")
        self._data.setdefault("manage_pwd", {"salt": "", "hash": ""})
        self._data.setdefault("last_policy", _default_policy())
        self._data.setdefault("applied_settings", [])
        self._data.setdefault("cached_devices", [])
        self._data.setdefault("last_sync_at", "")
        self._data.setdefault("last_sync_ok", False)
        self._data.setdefault("last_sync_message", "")
        self._data.setdefault("last_sync_reason", "")
        self._data.setdefault("last_heartbeat_at", "")
        self._data.setdefault("last_policy_pull_at", "")

        self._policy = self._normalize_policy(self._data.get("last_policy", {}))
        self._applied_settings = _norm_list(self._data.get("applied_settings", []))
        self._event_handlers: dict[str, list[tuple[str, Callable[[dict[str, Any]], None]]]] = {}

        self._settings_service = None
        self._plugin_manager = None
        self._world_zone_service = None
        self._plugin_scan_connected = False

        self._http_session = requests.Session()
        self._last_saved_serialized = ""

        self._manage_unlocked = False

        self._syncing = False
        self._sync_timer = QTimer(self)
        self._sync_timer.timeout.connect(self._on_sync_timer)

        self._save()
        self._refresh_sync_timer(force=False)

    # ------------------------------------------------------------------ #
    # 自动同步
    # ------------------------------------------------------------------ #

    def _should_auto_sync(self) -> bool:
        return self.enabled and bool(self.server_url)

    def _refresh_sync_timer(self, *, force: bool) -> None:
        should_run = self._should_auto_sync()
        interval_ms = max(10, self.poll_interval_sec) * 1000

        if not should_run:
            if self._sync_timer.isActive():
                self._sync_timer.stop()
            return

        if self._sync_timer.interval() != interval_ms:
            self._sync_timer.setInterval(interval_ms)

        if not self._sync_timer.isActive():
            self._sync_timer.start()

        if force:
            QTimer.singleShot(1200, lambda: self.sync_once(reason="auto:startup"))

    def _set_sync_status(
        self,
        *,
        ok: bool,
        message: str,
        reason: str,
        heartbeat_ok: bool,
        pull_ok: bool,
    ) -> None:
        now_text = _now_text()
        self._data["last_sync_at"] = now_text
        self._data["last_sync_ok"] = bool(ok)
        self._data["last_sync_message"] = str(message or "")
        self._data["last_sync_reason"] = str(reason or "")
        if heartbeat_ok:
            self._data["last_heartbeat_at"] = now_text
        if pull_ok:
            self._data["last_policy_pull_at"] = now_text
        self._save()
        self.syncStateChanged.emit()
        self.changed.emit()

    def _on_sync_timer(self) -> None:
        self.sync_once(reason="auto:timer")

    def sync_once(self, *, reason: str = "manual") -> tuple[bool, str]:
        if self._syncing:
            return False, "正在同步，请稍后再试"
        if not self.enabled:
            return False, "集控总开关未开启"
        if not self.server_url:
            return False, "未配置集控服务器地址"

        self._syncing = True
        try:
            hb_ok, hb_msg = self.heartbeat()
            pull_ok = False
            pull_msg = ""
            if hb_ok:
                pull_ok, pull_msg = self.pull_policy()
            else:
                pull_msg = "心跳失败，已跳过策略拉取"

            ok = hb_ok and pull_ok
            message = f"{hb_msg}；{pull_msg}" if hb_msg and pull_msg else (hb_msg or pull_msg or "同步完成")
            self._set_sync_status(
                ok=ok,
                message=message,
                reason=reason,
                heartbeat_ok=hb_ok,
                pull_ok=pull_ok,
            )
            return ok, message
        finally:
            self._syncing = False

    # ------------------------------------------------------------------ #
    # 依赖注入
    # ------------------------------------------------------------------ #

    def bind_dependencies(
        self,
        *,
        settings_service=None,
        plugin_manager=None,
        world_zone_service=None,
    ) -> None:
        prev_plugin_manager = self._plugin_manager
        if (
            prev_plugin_manager is not None
            and prev_plugin_manager is not plugin_manager
            and self._plugin_scan_connected
        ):
            try:
                prev_plugin_manager.scanCompleted.disconnect(self._on_plugin_scan_completed)
                self._plugin_scan_connected = False
            except Exception:
                pass

        self._settings_service = settings_service
        self._plugin_manager = plugin_manager
        self._world_zone_service = world_zone_service

        if self._plugin_manager is not None:
            # 仅在确认已连接时断开，避免 Qt 输出 “Failed to disconnect” 运行时警告。
            if self._plugin_scan_connected and prev_plugin_manager is self._plugin_manager:
                try:
                    self._plugin_manager.scanCompleted.disconnect(self._on_plugin_scan_completed)
                    self._plugin_scan_connected = False
                except Exception:
                    pass
            try:
                self._plugin_manager.scanCompleted.connect(self._on_plugin_scan_completed)
                self._plugin_scan_connected = True
            except Exception:
                self._plugin_scan_connected = False
                logger.exception("绑定插件扫描回调失败")

        if self.is_effective():
            self.apply_policy(self._policy)
        self._refresh_sync_timer(force=False)

    # ------------------------------------------------------------------ #
    # 基础属性
    # ------------------------------------------------------------------ #

    @property
    def enabled(self) -> bool:
        return bool(self._data.get("enabled", False))

    def set_enabled(self, value: bool) -> None:
        old = self.enabled
        self._data["enabled"] = bool(value)
        self._save()
        self.changed.emit()
        self.apply_policy(self._policy)
        self._refresh_sync_timer(force=(not old and bool(value)))

    @property
    def server_url(self) -> str:
        return str(self._data.get("server_url", "")).strip()

    def set_server_url(self, value: str) -> None:
        self._data["server_url"] = str(value or "").strip().rstrip("/")
        self._save()
        self.changed.emit()
        self._refresh_sync_timer(force=False)

    @property
    def device_id(self) -> str:
        return str(self._data.get("device_id", "")).strip()

    def set_device_id(self, value: str) -> None:
        text = str(value or "").strip()
        if not text:
            return
        self._data["device_id"] = text
        self._save()
        self.changed.emit()

    @property
    def device_name(self) -> str:
        return str(self._data.get("device_name", APP_NAME)).strip() or APP_NAME

    def set_device_name(self, value: str) -> None:
        text = str(value or "").strip() or APP_NAME
        self._data["device_name"] = text
        self._save()
        self.changed.emit()

    @property
    def poll_interval_sec(self) -> int:
        try:
            return max(10, min(3600, int(self._data.get("poll_interval_sec", 60))))
        except Exception:
            return 60

    def set_poll_interval_sec(self, value: int) -> None:
        self._data["poll_interval_sec"] = max(10, min(3600, int(value)))
        self._save()
        self.changed.emit()
        self._refresh_sync_timer(force=False)

    @property
    def server_bundle_dir(self) -> str:
        return str(self._data.get("server_bundle_dir", "")).strip()

    def set_server_bundle_dir(self, value: str) -> None:
        self._data["server_bundle_dir"] = str(value or "").strip()
        self._save()
        self.changed.emit()

    @property
    def server_admin_password(self) -> str:
        return str(self._data.get("server_admin_password", ""))

    def set_server_admin_password(self, value: str) -> None:
        self._data["server_admin_password"] = str(value or "")
        self._save()

    # ------------------------------------------------------------------ #
    # 集控策略
    # ------------------------------------------------------------------ #

    @property
    def policy(self) -> dict[str, Any]:
        return copy.deepcopy(self._policy)

    def replace_policy(self, policy: dict[str, Any], *, apply_now: bool = True) -> None:
        self._policy = self._normalize_policy(policy)
        self._data["last_policy"] = copy.deepcopy(self._policy)
        self._save()
        self.changed.emit()
        if apply_now:
            self.apply_policy(self._policy)

    def _normalize_policy(self, raw: Any) -> dict[str, Any]:
        policy = _default_policy()
        if isinstance(raw, dict):
            policy.update(raw)

        policy["enabled"] = bool(policy.get("enabled", False))
        try:
            policy["version"] = int(policy.get("version", 1))
        except Exception:
            policy["version"] = 1
        policy["updated_at"] = str(policy.get("updated_at", ""))
        policy["updated_by"] = str(policy.get("updated_by", ""))
        policy["note"] = str(policy.get("note", ""))

        policy["global_settings"] = dict(policy.get("global_settings", {}) or {})
        policy["blocked_features"] = _norm_list(policy.get("blocked_features", []))
        policy["blocked_permission_items"] = _norm_list(policy.get("blocked_permission_items", []))
        policy["deny_plugin_install"] = bool(policy.get("deny_plugin_install", False))
        policy["managed_plugins"] = _norm_list(policy.get("managed_plugins", []))
        policy["fullscreen_clock_list"] = _norm_list(policy.get("fullscreen_clock_list", []))
        policy["managed_devices"] = _norm_list(policy.get("managed_devices", []))

        forced_layouts = policy.get("forced_layouts", {})
        policy["forced_layouts"] = dict(forced_layouts) if isinstance(forced_layouts, dict) else {}

        plugin_configs = policy.get("plugin_configs", {})
        policy["plugin_configs"] = dict(plugin_configs) if isinstance(plugin_configs, dict) else {}

        central_events = policy.get("central_events", {})
        policy["central_events"] = dict(central_events) if isinstance(central_events, dict) else {}
        return policy

    def set_policy_enabled(self, value: bool) -> None:
        policy = self.policy
        policy["enabled"] = bool(value)
        self.replace_policy(policy, apply_now=True)

    def set_policy_field(self, key: str, value: Any, *, apply_now: bool = False) -> None:
        policy = self.policy
        policy[str(key)] = value
        self.replace_policy(policy, apply_now=apply_now)

    def is_effective(self) -> bool:
        return self.enabled and bool(self._policy.get("enabled", False))

    def is_feature_blocked(self, feature_key: str) -> tuple[bool, str]:
        key = str(feature_key or "").strip()
        if not key:
            return False, ""
        if not self.is_effective():
            return False, ""

        blocked_features = set(_norm_list(self._policy.get("blocked_features", [])))
        if key in blocked_features:
            return True, "该功能被集控策略禁用"

        if key == "plugin.install" and bool(self._policy.get("deny_plugin_install", False)):
            return True, "集控策略禁止安装新插件"

        blocked_permission_items = set(_norm_list(self._policy.get("blocked_permission_items", [])))
        if key in blocked_permission_items:
            return True, "该权限项目被集控策略阻止"

        return False, ""

    def is_plugin_allowed(self, plugin_id: str) -> tuple[bool, str]:
        pid = str(plugin_id or "").strip()
        if not pid:
            return True, ""
        if not self.is_effective():
            return True, ""

        managed = set(_norm_list(self._policy.get("managed_plugins", [])))
        if not managed:
            return True, ""
        if pid in managed:
            return True, ""
        return False, "该插件不在集控受管插件列表中"

    def is_fullscreen_zone_allowed(self, zone_id: str) -> tuple[bool, str]:
        zid = str(zone_id or "").strip()
        if not zid:
            return True, ""
        if not self.is_effective():
            return True, ""

        allowed = set(_norm_list(self._policy.get("fullscreen_clock_list", [])))
        if not allowed:
            return True, ""
        if zid in allowed:
            return True, ""
        return False, "该全屏时钟不在集控允许列表中"

    def _apply_managed_plugins(self, raw: Any) -> list[str]:
        mgr = self._plugin_manager
        if mgr is None:
            return []

        managed = set(_norm_list(raw))
        if not managed:
            return []

        disabled_ids: list[str] = []
        try:
            all_plugins = mgr.all_known_plugins()
        except Exception:
            logger.exception("读取插件列表失败，无法应用受管插件策略")
            return []

        for meta, enabled, _error, _dep_warning in all_plugins:
            pid = str(getattr(meta, "id", "") or "").strip()
            if not pid:
                continue

            if pid in managed:
                continue
            if not bool(enabled):
                continue
            try:
                mgr.set_enabled(pid, False)
                disabled_ids.append(pid)
            except Exception:
                logger.exception("应用受管插件策略失败: {}", pid)

        return disabled_ids

    def _on_plugin_scan_completed(self) -> None:
        if not self.is_effective():
            return

        disabled_ids = self._apply_managed_plugins(self._policy.get("managed_plugins", []))
        if not disabled_ids:
            return

        markers = [f"managed_plugin:{pid}" for pid in disabled_ids]
        merged = list(self._applied_settings)
        changed = False
        for marker in markers:
            if marker in merged:
                continue
            merged.append(marker)
            changed = True
        if not changed:
            return

        self._applied_settings = merged
        self._data["applied_settings"] = list(merged)
        self._save()
        self.policyApplied.emit()
        self.changed.emit()

    def apply_policy(self, policy: dict[str, Any] | None = None) -> list[str]:
        source = self._normalize_policy(policy if policy is not None else self._policy)
        self._policy = source
        self._data["last_policy"] = copy.deepcopy(source)

        applied: list[str] = []
        if self.is_effective():
            global_settings = dict(source.get("global_settings", {}) or {})
            for key, value in global_settings.items():
                if self._apply_global_setting(str(key), value):
                    applied.append(str(key))

            disabled_plugins = self._apply_managed_plugins(source.get("managed_plugins", []))
            if disabled_plugins:
                applied.extend([f"managed_plugin:{pid}" for pid in disabled_plugins])

            applied_layouts = self._apply_forced_layouts(source.get("forced_layouts", {}))
            if applied_layouts:
                applied.extend([f"forced_layout:{item}" for item in applied_layouts])

        self._applied_settings = applied
        self._data["applied_settings"] = list(applied)
        self._save()

        # 广播策略已更新，供插件通过 register_central_event 监听并刷新自身配置。
        try:
            self.emit_event(
                "policy.updated",
                {
                    "policy": copy.deepcopy(source),
                    "applied_settings": list(applied),
                    "effective": self.is_effective(),
                },
            )
        except Exception:
            logger.exception("广播集控策略更新事件失败")

        self.policyApplied.emit()
        self.changed.emit()
        return applied

    def _apply_global_setting(self, key: str, value: Any) -> bool:
        svc = self._settings_service
        if svc is None:
            return False

        setter = getattr(svc, f"set_{key}", None)
        if not callable(setter):
            return False
        try:
            setter(value)
            return True
        except Exception:
            logger.exception("应用集控设置失败: key={}", key)
            return False

    def _apply_forced_layouts(self, raw: Any) -> list[str]:
        if not isinstance(raw, dict):
            return []

        applied_zone_ids: list[str] = []
        try:
            from app.widgets.base_widget import WidgetConfig
            from app.widgets.layout_store import WidgetLayoutStore
            from app.events import EventBus, EventType

            store = WidgetLayoutStore()
            for zone_id, widgets in raw.items():
                zid = str(zone_id or "").strip()
                if not zid or not isinstance(widgets, list):
                    continue
                configs = []
                for data in widgets:
                    if not isinstance(data, dict):
                        continue
                    configs.append(WidgetConfig.from_dict(dict(data)))
                if not configs:
                    continue
                store.save(zid, configs)
                EventBus.emit(EventType.WIDGET_LAYOUT_CHANGED, zone_id=zid)
                applied_zone_ids.append(zid)
        except Exception:
            logger.exception("应用集控强制布局失败")
            return []

        return applied_zone_ids

    # ------------------------------------------------------------------ #
    # 插件扩展：集控事件与插件配置
    # ------------------------------------------------------------------ #

    def register_event(
        self,
        event_key: str,
        handler: Callable[[dict[str, Any]], None],
        *,
        owner: str = "local",
    ) -> None:
        key = str(event_key or "").strip()
        if not key:
            return
        entries = self._event_handlers.setdefault(key, [])
        if any(cb is handler for _, cb in entries):
            return
        entries.append((str(owner or "local"), handler))
        self.eventRegistered.emit(key)

    def unregister_owner_events(self, owner: str) -> None:
        target = str(owner or "").strip()
        if not target:
            return
        for key in list(self._event_handlers.keys()):
            entries = self._event_handlers.get(key, [])
            entries = [(o, cb) for o, cb in entries if o != target]
            if entries:
                self._event_handlers[key] = entries
            else:
                self._event_handlers.pop(key, None)

    def emit_event(self, event_key: str, payload: dict[str, Any] | None = None) -> None:
        key = str(event_key or "").strip()
        if not key:
            return
        handlers = list(self._event_handlers.get(key, []))
        data = dict(payload or {})
        for _owner, callback in handlers:
            try:
                callback(data)
            except Exception:
                logger.exception("集控事件回调执行失败: {}", key)

    def get_plugin_config(self, plugin_id: str, default: Any = None) -> Any:
        configs = self._policy.get("plugin_configs", {})
        if not isinstance(configs, dict):
            return default
        return copy.deepcopy(configs.get(str(plugin_id or "").strip(), default))

    # ------------------------------------------------------------------ #
    # 管理口令（用于修改集控设置）
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

    def has_manage_password(self) -> bool:
        record = self._data.get("manage_pwd", {})
        return bool(record.get("salt") and record.get("hash"))

    def set_manage_password(self, password: str) -> None:
        text = str(password or "")
        if not text:
            raise ValueError("管理口令不能为空")
        salt = os.urandom(16).hex()
        record = self._data.setdefault("manage_pwd", {})
        record["salt"] = salt
        record["hash"] = self._hash_password(text, salt)
        self._manage_unlocked = False
        self._save()
        self.changed.emit()

    def clear_manage_password(self) -> None:
        record = self._data.setdefault("manage_pwd", {})
        record["salt"] = ""
        record["hash"] = ""
        self._manage_unlocked = False
        self._save()
        self.changed.emit()

    def unlock_manage_session(self, password: str) -> bool:
        if not self.has_manage_password():
            self._manage_unlocked = True
            return True

        record = self._data.get("manage_pwd", {})
        salt = str(record.get("salt") or "")
        expected = str(record.get("hash") or "")
        if not salt or not expected:
            return False

        actual = self._hash_password(str(password or ""), salt)
        ok = hmac.compare_digest(actual, expected)
        self._manage_unlocked = bool(ok)
        return ok

    def reset_manage_unlock(self) -> None:
        self._manage_unlocked = False

    def is_manage_unlocked(self) -> bool:
        return self._manage_unlocked or (not self.has_manage_password())

    # ------------------------------------------------------------------ #
    # 服务端交互
    # ------------------------------------------------------------------ #

    def _build_url(self, path: str) -> str:
        base = self.server_url.rstrip("/")
        path_value = "/" + str(path or "").lstrip("/")
        return base + path_value

    def _request(
        self,
        method: str,
        path: str,
        *,
        timeout: int = 8,
        headers: dict[str, str] | None = None,
        json_data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ):
        if not self.server_url:
            raise RuntimeError("未配置集控服务器地址")
        url = self._build_url(path)
        return self._http_session.request(
            method=method,
            url=url,
            timeout=timeout,
            headers=headers,
            json=json_data,
            params=params,
        )

    def ping_server(self) -> tuple[bool, str, dict[str, Any]]:
        try:
            resp = self._request("GET", "/api/status", timeout=6)
            data = resp.json() if resp.content else {}
            if resp.status_code != 200:
                return False, f"HTTP {resp.status_code}", data if isinstance(data, dict) else {}
            return True, "连接成功", data if isinstance(data, dict) else {}
        except Exception as exc:
            return False, str(exc), {}

    def heartbeat(self) -> tuple[bool, str]:
        payload = {
            "device_id": self.device_id,
            "device_name": self.device_name,
            "app_version": APP_VERSION,
            "timestamp": _now_text(),
            "capabilities": {
                "supports_forced_layouts": True,
                "supports_plugin_configs": True,
                "supports_permission_items": True,
            },
        }
        try:
            resp = self._request("POST", "/api/device/heartbeat", json_data=payload, timeout=8)
            if resp.status_code != 200:
                return False, f"上报失败: HTTP {resp.status_code}"
            return True, "设备已上报"
        except Exception as exc:
            return False, str(exc)

    def pull_policy(self) -> tuple[bool, str]:
        params = {
            "device_id": self.device_id,
        }
        try:
            resp = self._request("GET", "/api/policy", params=params, timeout=8)
            data = resp.json() if resp.content else {}
            if resp.status_code != 200:
                return False, f"拉取失败: HTTP {resp.status_code}"
            policy = data.get("policy", data) if isinstance(data, dict) else {}
            if not isinstance(policy, dict):
                return False, "拉取失败: 返回数据格式错误"
            self.replace_policy(policy, apply_now=True)
            return True, "策略已更新"
        except Exception as exc:
            return False, str(exc)

    def _login_server(self, admin_password: str) -> tuple[bool, str, str]:
        payload = {
            "password": str(admin_password or ""),
        }
        try:
            resp = self._request("POST", "/api/auth/login", json_data=payload, timeout=8)
            data = resp.json() if resp.content else {}
            if resp.status_code != 200:
                return False, f"登录失败: HTTP {resp.status_code}", ""
            token = str(data.get("token") or "") if isinstance(data, dict) else ""
            if not token:
                return False, "登录失败: 未返回 token", ""
            return True, "登录成功", token
        except Exception as exc:
            return False, str(exc), ""

    def push_policy(
        self,
        admin_password: str,
        *,
        target_device_ids: list[str] | None = None,
    ) -> tuple[bool, str]:
        ok, msg, token = self._login_server(admin_password)
        if not ok:
            return False, msg

        headers = {
            "Authorization": f"Bearer {token}",
        }
        policy_payload = self.policy

        try:
            if target_device_ids:
                payload = {
                    "policy": policy_payload,
                    "device_ids": _norm_list(target_device_ids),
                }
                resp = self._request(
                    "POST",
                    "/api/policy/push",
                    headers=headers,
                    json_data=payload,
                    timeout=10,
                )
            else:
                payload = {
                    "policy": policy_payload,
                }
                resp = self._request(
                    "PUT",
                    "/api/policy",
                    headers=headers,
                    json_data=payload,
                    timeout=10,
                )
            if resp.status_code != 200:
                return False, f"推送失败: HTTP {resp.status_code}"
            return True, "策略已推送"
        except Exception as exc:
            return False, str(exc)

    def fetch_devices(self, admin_password: str) -> tuple[bool, str, list[dict[str, Any]]]:
        ok, msg, token = self._login_server(admin_password)
        if not ok:
            return False, msg, []

        headers = {
            "Authorization": f"Bearer {token}",
        }
        try:
            resp = self._request("GET", "/api/devices", headers=headers, timeout=8)
            data = resp.json() if resp.content else {}
            if resp.status_code != 200:
                return False, f"获取失败: HTTP {resp.status_code}", []
            devices = data.get("devices", []) if isinstance(data, dict) else []
            if not isinstance(devices, list):
                devices = []
            self._data["cached_devices"] = devices
            self._save()
            self.devicesUpdated.emit()
            return True, "设备列表已刷新", devices
        except Exception as exc:
            return False, str(exc), []

    def cached_devices(self) -> list[dict[str, Any]]:
        raw = self._data.get("cached_devices", [])
        return list(raw) if isinstance(raw, list) else []

    # ------------------------------------------------------------------ #
    # 状态快照
    # ------------------------------------------------------------------ #

    def status_snapshot(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "policy_enabled": bool(self._policy.get("enabled", False)),
            "policy_version": int(self._policy.get("version", 1)),
            "server_url": self.server_url,
            "device_id": self.device_id,
            "auto_sync_active": self._should_auto_sync() and self._sync_timer.isActive(),
            "poll_interval_sec": self.poll_interval_sec,
            "syncing": self._syncing,
            "last_sync_at": str(self._data.get("last_sync_at", "")),
            "last_sync_ok": bool(self._data.get("last_sync_ok", False)),
            "last_sync_message": str(self._data.get("last_sync_message", "")),
            "last_sync_reason": str(self._data.get("last_sync_reason", "")),
            "last_heartbeat_at": str(self._data.get("last_heartbeat_at", "")),
            "last_policy_pull_at": str(self._data.get("last_policy_pull_at", "")),
            "applied_settings": list(self._applied_settings),
            "blocked_features": list(_norm_list(self._policy.get("blocked_features", []))),
            "blocked_permission_items": list(_norm_list(self._policy.get("blocked_permission_items", []))),
            "deny_plugin_install": bool(self._policy.get("deny_plugin_install", False)),
            "managed_plugins": list(_norm_list(self._policy.get("managed_plugins", []))),
            "fullscreen_clock_list": list(_norm_list(self._policy.get("fullscreen_clock_list", []))),
            "cached_devices": len(self.cached_devices()),
            "manage_locked": not self.is_manage_unlocked(),
        }

    # ------------------------------------------------------------------ #
    # 独立集控服务器程序生成
    # ------------------------------------------------------------------ #

    def create_server_bundle(self, target_dir: str | Path) -> tuple[bool, str]:
        target = Path(target_dir).expanduser()
        try:
            target.mkdir(parents=True, exist_ok=True)
            (target / "data").mkdir(parents=True, exist_ok=True)

            main_path = target / "main.py"
            readme_path = target / "README.md"
            policy_path = target / "data" / "policy.json"
            server_path = target / "data" / "server.json"
            devices_path = target / "data" / "devices.json"

            main_path.write_text(_server_main_py(), encoding="utf-8")
            readme_path.write_text(_server_readme_md(), encoding="utf-8")
            policy_path.write_text(json.dumps(_default_policy(), ensure_ascii=False, indent=2), encoding="utf-8")

            server_json = {
                "admin_password": "admin123",
                "token_ttl_sec": 28800,
                "bind_host": "127.0.0.1",
                "bind_port": 18900,
            }
            server_path.write_text(json.dumps(server_json, ensure_ascii=False, indent=2), encoding="utf-8")
            if not devices_path.exists():
                devices_path.write_text("[]\n", encoding="utf-8")

            self.set_server_bundle_dir(str(target))
            return True, f"已创建集控服务器程序：{target}"
        except Exception as exc:
            logger.exception("创建集控服务器程序失败")
            return False, str(exc)

    # ------------------------------------------------------------------ #
    # 持久化
    # ------------------------------------------------------------------ #

    def _save(self) -> None:
        serialized = json.dumps(self._data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if serialized == self._last_saved_serialized:
            return
        save_json(CENTRAL_CONTROL_CONFIG, self._data)
        self._last_saved_serialized = serialized


def _server_readme_md() -> str:
    return """# Little Tree Clock - 集控服务器\n\n## 启动\n\n1. 安装 Python 3.11+\n2. 在本目录执行：\n\npython main.py --host 127.0.0.1 --port 18900\n\n默认管理员密码：admin123\n建议首次登录后立即修改。\n\n## API\n\n- GET /api/status\n- POST /api/auth/login\n- POST /api/auth/change_password\n- GET /api/policy\n- PUT /api/policy\n- POST /api/policy/push\n- POST /api/device/heartbeat\n- GET /api/devices\n\n## 插件\n\n可选目录：plugins_ext\n\n仅包含 register_central_events(server_api) 的插件会被加载。\n"""


def _server_main_py() -> str:
    return """from __future__ import annotations\n\nimport argparse\nimport importlib.util\nimport json\nimport secrets\nimport threading\nimport time\nfrom datetime import datetime\nfrom http.server import BaseHTTPRequestHandler, ThreadingHTTPServer\nfrom pathlib import Path\nfrom typing import Any\nfrom urllib.parse import parse_qs, urlparse\n\nBASE_DIR = Path(__file__).resolve().parent\nDATA_DIR = BASE_DIR / \"data\"\nPOLICY_PATH = DATA_DIR / \"policy.json\"\nDEVICES_PATH = DATA_DIR / \"devices.json\"\nSERVER_PATH = DATA_DIR / \"server.json\"\nPLUGINS_DIR = BASE_DIR / \"plugins_ext\"\n\n\ndef now_text() -> str:\n    return datetime.now().strftime(\"%Y-%m-%d %H:%M:%S\")\n\n\ndef load_json(path: Path, default: Any):\n    if not path.exists():\n        return default\n    try:\n        return json.loads(path.read_text(encoding=\"utf-8\"))\n    except Exception:\n        return default\n\n\ndef save_json(path: Path, data: Any) -> None:\n    path.parent.mkdir(parents=True, exist_ok=True)\n    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding=\"utf-8\")\n\n\ndef default_policy() -> dict[str, Any]:\n    return {\n        \"enabled\": False,\n        \"version\": 1,\n        \"updated_at\": \"\",\n        \"updated_by\": \"\",\n        \"global_settings\": {},\n        \"blocked_features\": [],\n        \"blocked_permission_items\": [],\n        \"deny_plugin_install\": False,\n        \"managed_plugins\": [],\n        \"fullscreen_clock_list\": [],\n        \"forced_layouts\": {},\n        \"plugin_configs\": {},\n        \"managed_devices\": [],\n        \"central_events\": {},\n        \"note\": \"\",\n    }\n\n\nclass Store:\n    def __init__(self) -> None:\n        DATA_DIR.mkdir(parents=True, exist_ok=True)\n        self.policy = default_policy()\n        self.policy.update(load_json(POLICY_PATH, {}))\n        self.devices = load_json(DEVICES_PATH, [])\n        if not isinstance(self.devices, list):\n            self.devices = []\n        self.server_cfg = {\n            \"admin_password\": \"admin123\",\n            \"token_ttl_sec\": 28800,\n            \"bind_host\": \"127.0.0.1\",\n            \"bind_port\": 18900,\n        }\n        self.server_cfg.update(load_json(SERVER_PATH, {}))\n\n        self.tokens: dict[str, float] = {}\n        self.lock = threading.Lock()\n        self.event_handlers: dict[str, list] = {}\n\n    def save_policy(self) -> None:\n        save_json(POLICY_PATH, self.policy)\n\n    def save_devices(self) -> None:\n        save_json(DEVICES_PATH, self.devices)\n\n    def save_server_cfg(self) -> None:\n        save_json(SERVER_PATH, self.server_cfg)\n\n    def login(self, password: str) -> str | None:\n        if str(password or \"\") != str(self.server_cfg.get(\"admin_password\", \"admin123\")):\n            return None\n        token = secrets.token_hex(24)\n        expire = time.time() + int(self.server_cfg.get(\"token_ttl_sec\", 28800))\n        with self.lock:\n            self.tokens[token] = expire\n        return token\n\n    def verify_token(self, token: str) -> bool:\n        if not token:\n            return False\n        now = time.time()\n        with self.lock:\n            expire = self.tokens.get(token)\n            if expire is None:\n                return False\n            if expire < now:\n                self.tokens.pop(token, None)\n                return False\n        return True\n\n    def _cleanup_tokens(self) -> None:\n        now = time.time()\n        with self.lock:\n            for token, expire in list(self.tokens.items()):\n                if expire < now:\n                    self.tokens.pop(token, None)\n\n    def upsert_device(self, payload: dict[str, Any]) -> None:\n        device_id = str(payload.get(\"device_id\") or \"\").strip()\n        if not device_id:\n            return\n\n        found = None\n        for item in self.devices:\n            if str(item.get(\"device_id\") or \"\") == device_id:\n                found = item\n                break\n\n        if found is None:\n            found = {\"device_id\": device_id}\n            self.devices.append(found)\n\n        found[\"device_name\"] = str(payload.get(\"device_name\") or found.get(\"device_name\") or \"\")\n        found[\"app_version\"] = str(payload.get(\"app_version\") or \"\")\n        found[\"capabilities\"] = payload.get(\"capabilities\", {})\n        found[\"last_seen\"] = now_text()\n        found[\"last_ip\"] = str(payload.get(\"ip\") or \"\")\n\n        target_ids = self.policy.get(\"target_device_ids\", [])\n        found[\"targeted\"] = bool(target_ids and device_id in target_ids)\n\n        self.save_devices()\n\n    def register_event(self, event_key: str, callback) -> None:\n        key = str(event_key or \"\").strip()\n        if not key:\n            return\n        self.event_handlers.setdefault(key, []).append(callback)\n\n    def emit_event(self, event_key: str, payload: dict[str, Any] | None = None) -> None:\n        key = str(event_key or \"\").strip()\n        handlers = list(self.event_handlers.get(key, []))\n        data = dict(payload or {})\n        for cb in handlers:\n            try:\n                cb(data)\n            except Exception:\n                pass\n\n\nstore = Store()\n\n\ndef load_server_plugins() -> None:\n    if not PLUGINS_DIR.exists():\n        return\n\n    class _ServerAPI:\n        def on(self, event_key: str, callback) -> None:\n            store.register_event(event_key, callback)\n\n        def emit(self, event_key: str, payload: dict[str, Any] | None = None) -> None:\n            store.emit_event(event_key, payload)\n\n        def get_policy(self) -> dict[str, Any]:\n            return dict(store.policy)\n\n        def set_policy(self, policy: dict[str, Any]) -> None:\n            if isinstance(policy, dict):\n                store.policy.update(policy)\n                store.save_policy()\n\n    server_api = _ServerAPI()\n\n    for path in sorted(PLUGINS_DIR.iterdir()):\n        entry = None\n        if path.is_dir() and (path / \"__init__.py\").exists():\n            entry = path / \"__init__.py\"\n        elif path.is_file() and path.suffix.lower() == \".py\":\n            entry = path\n        if entry is None:\n            continue\n\n        module_name = f\"_cc_server_plugin_{path.stem}_{abs(hash(str(path))) % 100000}\"\n        try:\n            spec = importlib.util.spec_from_file_location(module_name, entry)\n            if spec is None or spec.loader is None:\n                continue\n            module = importlib.util.module_from_spec(spec)\n            spec.loader.exec_module(module)\n            register = getattr(module, \"register_central_events\", None)\n            if callable(register):\n                register(server_api)\n                print(f\"[plugin] loaded: {path.name}\")\n            else:\n                print(f\"[plugin] skipped (no register_central_events): {path.name}\")\n        except Exception as exc:\n            print(f\"[plugin] failed: {path.name} -> {exc}\")\n\n\nclass Handler(BaseHTTPRequestHandler):\n    server_version = \"LTC-Central-Server/1.0\"\n\n    def _json(self, code: int, data: dict[str, Any]) -> None:\n        body = json.dumps(data, ensure_ascii=False).encode(\"utf-8\")\n        self.send_response(code)\n        self.send_header(\"Content-Type\", \"application/json; charset=utf-8\")\n        self.send_header(\"Content-Length\", str(len(body)))\n        self.end_headers()\n        self.wfile.write(body)\n\n    def _read_json(self) -> dict[str, Any]:\n        length = int(self.headers.get(\"Content-Length\", \"0\") or 0)\n        if length <= 0:\n            return {}\n        raw = self.rfile.read(length)\n        if not raw:\n            return {}\n        try:\n            data = json.loads(raw.decode(\"utf-8\"))\n            return data if isinstance(data, dict) else {}\n        except Exception:\n            return {}\n\n    def _bearer_token(self) -> str:\n        auth = str(self.headers.get(\"Authorization\") or \"\")\n        if not auth.lower().startswith(\"bearer \"):\n            return \"\"\n        return auth[7:].strip()\n\n    def _require_admin(self) -> bool:\n        token = self._bearer_token()\n        if store.verify_token(token):\n            return True\n        self._json(401, {\"ok\": False, \"message\": \"unauthorized\"})\n        return False\n\n    def do_GET(self):\n        store._cleanup_tokens()\n        parsed = urlparse(self.path)\n        path = parsed.path\n\n        if path == \"/api/status\":\n            self._json(200, {\n                \"ok\": True,\n                \"server_time\": now_text(),\n                \"policy_version\": int(store.policy.get(\"version\", 1)),\n                \"devices\": len(store.devices),\n            })\n            return\n\n        if path == \"/api/policy\":\n            qs = parse_qs(parsed.query)\n            device_id = (qs.get(\"device_id\") or [\"\"])[0]\n            data = {\n                \"ok\": True,\n                \"policy\": store.policy,\n                \"server_time\": now_text(),\n                \"targeted\": bool(store.policy.get(\"target_device_ids\") and device_id in store.policy.get(\"target_device_ids\", [])),\n            }\n            self._json(200, data)\n            return\n\n        if path == \"/api/devices\":\n            if not self._require_admin():\n                return\n            self._json(200, {\n                \"ok\": True,\n                \"devices\": store.devices,\n            })\n            return\n\n        self._json(404, {\"ok\": False, \"message\": \"not found\"})\n\n    def do_POST(self):\n        store._cleanup_tokens()\n        path = urlparse(self.path).path\n        data = self._read_json()\n\n        if path == \"/api/auth/login\":\n            token = store.login(str(data.get(\"password\") or \"\"))\n            if not token:\n                self._json(403, {\"ok\": False, \"message\": \"invalid password\"})\n                return\n            self._json(200, {\"ok\": True, \"token\": token})\n            return\n\n        if path == \"/api/auth/change_password\":\n            if not self._require_admin():\n                return\n            new_password = str(data.get(\"new_password\") or \"\")\n            if not new_password:\n                self._json(400, {\"ok\": False, \"message\": \"new_password required\"})\n                return\n            store.server_cfg[\"admin_password\"] = new_password\n            store.save_server_cfg()\n            self._json(200, {\"ok\": True, \"message\": \"password updated\"})\n            return\n\n        if path == \"/api/device/heartbeat\":\n            data[\"ip\"] = self.client_address[0] if self.client_address else \"\"\n            store.upsert_device(data)\n            store.emit_event(\"device.heartbeat\", data)\n            self._json(200, {\"ok\": True, \"server_time\": now_text()})\n            return\n\n        if path == \"/api/policy/push\":\n            if not self._require_admin():\n                return\n            policy = data.get(\"policy\")\n            if not isinstance(policy, dict):\n                self._json(400, {\"ok\": False, \"message\": \"policy required\"})\n                return\n            store.policy.update(policy)\n            store.policy[\"version\"] = int(store.policy.get(\"version\", 1)) + 1\n            store.policy[\"updated_at\"] = now_text()\n            store.policy[\"updated_by\"] = \"api/policy/push\"\n            store.policy[\"target_device_ids\"] = [str(x) for x in data.get(\"device_ids\", []) if str(x).strip()]\n            store.save_policy()\n            store.emit_event(\"policy.updated\", {\"policy\": store.policy})\n            self._json(200, {\"ok\": True, \"message\": \"policy pushed\"})\n            return\n\n        self._json(404, {\"ok\": False, \"message\": \"not found\"})\n\n    def do_PUT(self):\n        store._cleanup_tokens()\n        path = urlparse(self.path).path\n        if path != \"/api/policy\":\n            self._json(404, {\"ok\": False, \"message\": \"not found\"})\n            return\n        if not self._require_admin():\n            return\n\n        data = self._read_json()\n        policy = data.get(\"policy\")\n        if not isinstance(policy, dict):\n            self._json(400, {\"ok\": False, \"message\": \"policy required\"})\n            return\n\n        store.policy.update(policy)\n        store.policy[\"version\"] = int(store.policy.get(\"version\", 1)) + 1\n        store.policy[\"updated_at\"] = now_text()\n        store.policy[\"updated_by\"] = \"api/policy\"\n        store.policy[\"target_device_ids\"] = []\n        store.save_policy()\n        store.emit_event(\"policy.updated\", {\"policy\": store.policy})\n        self._json(200, {\"ok\": True, \"message\": \"policy updated\"})\n\n\ndef main() -> None:\n    parser = argparse.ArgumentParser()\n    parser.add_argument(\"--host\", default=str(store.server_cfg.get(\"bind_host\", \"127.0.0.1\")))\n    parser.add_argument(\"--port\", type=int, default=int(store.server_cfg.get(\"bind_port\", 18900)))\n    args = parser.parse_args()\n\n    load_server_plugins()\n\n    httpd = ThreadingHTTPServer((args.host, args.port), Handler)\n    print(f\"[central-server] listening on http://{args.host}:{args.port}\")\n    print(\"[central-server] admin password default: admin123\")\n    try:\n        httpd.serve_forever()\n    except KeyboardInterrupt:\n        pass\n    finally:\n        httpd.server_close()\n\n\nif __name__ == \"__main__\":\n    main()\n"""

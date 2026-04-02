"""U盘登录插件：绑定U盘序列号，作为独立权限系统登录方式。"""
from __future__ import annotations

import json
import os
import hashlib
import secrets
import string
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, ComboBox, MessageBox, PrimaryPushButton, PushButton, SubtitleLabel

from app.plugins import BasePlugin, PluginAPI, PluginMeta
from app.services.permission_service import AuthMethodConfigPage, AuthMethodConfigSpec


@dataclass
class _UsbDevice:
    mount: str
    label: str
    serial: str


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _token_file_path(mount: str) -> Path:
    return Path(mount) / ".ltc_usb_auth.token"


def _write_token_file(mount: str, token: str) -> tuple[bool, str]:
    path = _token_file_path(mount)
    payload = {
        "version": 1,
        "token": token,
        "updated_at": _now_text(),
    }
    try:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return True, ""
    except Exception as exc:
        return False, str(exc)


def _read_token_file(mount: str) -> str:
    path = _token_file_path(mount)
    if not path.exists():
        return ""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return ""
        return str(raw.get("token") or "").strip()
    except Exception:
        return ""


def _token_hash(token: str) -> str:
    text = str(token or "").strip()
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _list_removable_usb_devices() -> list[_UsbDevice]:
    if os.name != "nt":
        return []

    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32
    get_drive_type = kernel32.GetDriveTypeW
    get_volume_info = kernel32.GetVolumeInformationW

    drive_removable = 2
    max_len = 261

    devices: dict[str, _UsbDevice] = {}
    for letter in string.ascii_uppercase:
        mount = f"{letter}:\\"
        if not os.path.exists(mount):
            continue

        drive_type = int(get_drive_type(ctypes.c_wchar_p(mount)))
        if drive_type != drive_removable:
            continue

        volume_name = ctypes.create_unicode_buffer(max_len)
        fs_name = ctypes.create_unicode_buffer(max_len)
        serial = wintypes.DWORD(0)
        max_component = wintypes.DWORD(0)
        flags = wintypes.DWORD(0)

        ok = bool(
            get_volume_info(
                ctypes.c_wchar_p(mount),
                volume_name,
                max_len,
                ctypes.byref(serial),
                ctypes.byref(max_component),
                ctypes.byref(flags),
                fs_name,
                max_len,
            )
        )
        if not ok:
            continue

        serial_hex = f"{int(serial.value):08X}"
        label = str(volume_name.value or "未命名U盘").strip() or "未命名U盘"
        devices[serial_hex] = _UsbDevice(mount=mount, label=label, serial=serial_hex)

    return sorted(devices.values(), key=lambda item: (item.label.lower(), item.serial))


class _UsbAuthSettingsWidget(QWidget):
    def __init__(self, plugin: "Plugin", parent=None):
        super().__init__(parent)
        self._plugin = plugin

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        root.addWidget(SubtitleLabel("U盘登录配置", self))

        self._status = BodyLabel("", self)
        self._status.setWordWrap(True)
        root.addWidget(self._status)

        self._device_combo = ComboBox(self)
        root.addWidget(self._device_combo)

        row = QVBoxLayout()
        row.setSpacing(8)

        self._refresh_btn = PushButton("刷新U盘列表", self)
        self._bind_btn = PrimaryPushButton("绑定当前选择U盘", self)
        self._unbind_btn = PushButton("解绑选中绑定项", self)
        self._clear_btn = PushButton("清空全部绑定", self)

        row.addWidget(self._refresh_btn)
        row.addWidget(self._bind_btn)
        row.addWidget(self._unbind_btn)
        row.addWidget(self._clear_btn)
        root.addLayout(row)

        root.addWidget(BodyLabel("已绑定U盘：", self))
        self._bound_list = QListWidget(self)
        root.addWidget(self._bound_list, 1)

        self._refresh_btn.clicked.connect(self._refresh_devices)
        self._bind_btn.clicked.connect(self._bind_current)
        self._unbind_btn.clicked.connect(self._unbind_selected)
        self._clear_btn.clicked.connect(self._clear_all)

        self._refresh_devices()
        self._refresh_bound_list()

    def _refresh_devices(self) -> None:
        devices = self._plugin.list_usb_devices()
        self._device_combo.clear()
        for dev in devices:
            self._device_combo.addItem(f"{dev.label} ({dev.mount}) [{dev.serial}]", userData=dev.serial)

        if devices:
            self._status.setText("检测到可用U盘，请选择并绑定。")
            self._bind_btn.setEnabled(True)
        else:
            self._status.setText("未检测到可用U盘。请插入U盘后点击刷新。")
            self._bind_btn.setEnabled(False)

    def _refresh_bound_list(self) -> None:
        self._bound_list.clear()
        for serial, item in self._plugin.list_bound_items():
            text = f"{item.get('label', '未命名U盘')} [{serial}]"
            line = QListWidgetItem(text)
            line.setData(Qt.ItemDataRole.UserRole, serial)
            self._bound_list.addItem(line)

        self._unbind_btn.setEnabled(self._bound_list.count() > 0)
        self._clear_btn.setEnabled(self._bound_list.count() > 0)

    def _bind_current(self) -> None:
        serial = str(self._device_combo.currentData() or "").strip()
        if not serial:
            self._status.setText("请先选择一个U盘。")
            return

        ok, msg = self._plugin.bind_usb(serial)
        self._status.setText(msg)
        if ok:
            self._refresh_bound_list()

    def _unbind_selected(self) -> None:
        item = self._bound_list.currentItem()
        if item is None:
            self._status.setText("请先选择要解绑的记录。")
            return

        box = MessageBox(
            "确认解绑",
            "解绑后该 U 盘将无法用于登录验证，是否继续？",
            self,
        )
        box.yesButton.setText("确认解绑")
        box.cancelButton.setText("取消")
        if not box.exec():
            return

        serial = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
        ok, msg = self._plugin.unbind_usb(serial)
        self._status.setText(msg)
        if ok:
            self._refresh_bound_list()

    def _clear_all(self) -> None:
        box = MessageBox(
            "确认清空",
            "清空后所有 U 盘都将失去登录能力，是否继续？",
            self,
        )
        box.yesButton.setText("确认清空")
        box.cancelButton.setText("取消")
        if not box.exec():
            return

        self._plugin.clear_bindings()
        self._status.setText("已清空全部U盘绑定。")
        self._refresh_bound_list()


class _UsbAuthIntroWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 8, 12, 8)
        root.setSpacing(10)

        root.addWidget(SubtitleLabel("配置说明", self))
        tip = BodyLabel(
            "将可信U盘绑定到当前账号后，插入任一已绑定U盘即可通过登录验证。\n"
            "建议至少绑定 1 个常用U盘，并妥善保管。\n"
            "请勿删除 U 盘根目录下的 .ltc_usb_auth.token 文件，否则该 U 盘将无法登录。",
            self,
        )
        tip.setWordWrap(True)
        root.addWidget(tip)
        root.addStretch(1)


class Plugin(BasePlugin):
    meta = PluginMeta(
        id="usb_auth_login",
        name="U盘登录",
        version="1.0.0",
        description="绑定U盘序列号并作为权限系统登录方式",
    )

    _METHOD_ID = "usb_auth_login.usb_key"

    def __init__(self):
        self._api: PluginAPI | None = None
        self._settings_widget: _UsbAuthSettingsWidget | None = None
        self._binding_path: Path | None = None
        self._bindings: dict[str, dict[str, Any]] = {}

    def on_load(self, api: PluginAPI) -> None:
        self._api = api
        self._binding_path = api.resolve_permission_data_path("usb_bindings.json")
        if self._binding_path is None:
            api.show_toast("U盘登录", "无法获取权限数据目录，登录方式未启用", level="error")
            return

        self._load_bindings()

        ok = api.register_permission_auth_method(
            self._METHOD_ID,
            "U盘登录",
            self._verify_usb_login,
            supported_levels=["user", "admin"],
            config_provider=self._build_auth_config_spec,
        )
        if not ok:
            api.show_toast("U盘登录", "注册登录方式失败", level="error")
            return

        api.show_toast("U盘登录", "已注册U盘登录方式", level="success")

    def on_unload(self) -> None:
        self._settings_widget = None

    def has_settings_widget(self) -> bool:
        # 出于安全考虑，不在应用设置中暴露该插件的直接管理面板。
        return False

    def create_settings_widget(self) -> QWidget:
        if self._settings_widget is None:
            self._settings_widget = _UsbAuthSettingsWidget(self)
        return self._settings_widget

    def _load_bindings(self) -> None:
        if self._binding_path is None:
            self._bindings = {}
            return

        if not self._binding_path.exists():
            self._bindings = {}
            self._save_bindings()
            return

        try:
            raw = json.loads(self._binding_path.read_text(encoding="utf-8"))
            items = raw.get("bindings", []) if isinstance(raw, dict) else []
            bindings: dict[str, dict[str, Any]] = {}
            legacy_count = 0
            migrated_plain_token_count = 0
            for item in items:
                if not isinstance(item, dict):
                    continue
                serial = str(item.get("serial") or "").strip().upper()
                if not serial:
                    continue
                token_hash = str(item.get("token_hash") or "").strip().lower()
                if not token_hash:
                    legacy_token = str(item.get("token") or "").strip()
                    if legacy_token:
                        token_hash = _token_hash(legacy_token)
                        migrated_plain_token_count += 1
                if not token_hash:
                    legacy_count += 1
                bindings[serial] = {
                    "serial": serial,
                    "label": str(item.get("label") or "").strip() or "未命名U盘",
                    "mount": str(item.get("mount") or "").strip(),
                    "bound_at": str(item.get("bound_at") or "").strip(),
                    "token_hash": token_hash,
                }
            self._bindings = bindings
            if migrated_plain_token_count > 0:
                self._save_bindings()
                if self._api is not None:
                    self._api.show_toast(
                        "U盘登录",
                        f"已完成 {migrated_plain_token_count} 条绑定数据安全升级。",
                        level="success",
                    )
            if legacy_count > 0 and self._api is not None:
                self._api.show_toast(
                    "U盘登录",
                    f"检测到 {legacy_count} 条旧版绑定，请重新绑定后方可登录。",
                    level="warning",
                )
        except Exception:
            self._bindings = {}
            if self._api is not None:
                self._api.show_toast("U盘登录", "绑定数据损坏，已重置", level="warning")
            self._save_bindings()

    def _save_bindings(self) -> None:
        if self._binding_path is None:
            return

        payload = {
            "version": 1,
            "updated_at": _now_text(),
            "bindings": [
                self._bindings[k]
                for k in sorted(self._bindings.keys())
            ],
        }
        self._binding_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _verify_usb_login(self, _required_level, _payload, _parent=None) -> bool:
        if not self._bindings:
            return False

        current_devices = _list_removable_usb_devices()
        if not current_devices:
            return False

        for dev in current_devices:
            bound = self._bindings.get(dev.serial)
            if not bound:
                continue

            expected_token_hash = str(bound.get("token_hash") or "").strip().lower()
            if not expected_token_hash:
                # 旧版本绑定数据没有令牌时，拒绝通过，要求重新绑定。
                continue

            actual_token = _read_token_file(dev.mount)
            actual_token_hash = _token_hash(actual_token)
            if actual_token_hash and secrets.compare_digest(expected_token_hash, actual_token_hash):
                return True
        return False

    def list_usb_devices(self) -> list[_UsbDevice]:
        return _list_removable_usb_devices()

    def list_bound_items(self) -> list[tuple[str, dict[str, Any]]]:
        return sorted(self._bindings.items(), key=lambda item: item[0])

    def bind_usb(self, serial: str) -> tuple[bool, str]:
        target = str(serial or "").strip().upper()
        if not target:
            return False, "无效的U盘序列号。"

        devices = {dev.serial: dev for dev in self.list_usb_devices()}
        dev = devices.get(target)
        if dev is None:
            return False, "当前未检测到该U盘，请刷新后重试。"

        token = secrets.token_urlsafe(24)
        ok, err = _write_token_file(dev.mount, token)
        if not ok:
            return False, f"无法写入 U 盘安全令牌文件（{err}），请确认 U 盘可写后重试。"

        self._bindings[target] = {
            "serial": target,
            "label": dev.label,
            "mount": dev.mount,
            "bound_at": _now_text(),
            "token_hash": _token_hash(token),
        }
        self._save_bindings()
        return (
            True,
            f"已绑定U盘：{dev.label} [{target}]，并已写入安全令牌。"
            "请勿删除 U 盘根目录下的 .ltc_usb_auth.token 文件。",
        )

    def unbind_usb(self, serial: str) -> tuple[bool, str]:
        target = str(serial or "").strip().upper()
        if not target:
            return False, "无效的绑定项。"
        if target not in self._bindings:
            return False, "该序列号未绑定。"

        self._bindings.pop(target, None)
        self._save_bindings()
        return True, f"已解绑：[{target}]"

    def clear_bindings(self) -> None:
        self._bindings = {}
        self._save_bindings()

    def _build_auth_config_spec(self, _service, _method_id: str) -> AuthMethodConfigSpec:
        def _intro_factory(parent: QWidget | None, _state: dict[str, Any]) -> QWidget:
            return _UsbAuthIntroWidget(parent)

        def _binding_factory(parent: QWidget | None, _state: dict[str, Any]) -> QWidget:
            return _UsbAuthSettingsWidget(self, parent)

        def _finish(_state: dict[str, Any]) -> tuple[bool, str]:
            if not self._bindings:
                return False, "请至少绑定一个U盘后再完成配置。"
            return True, ""

        return AuthMethodConfigSpec(
            window_title="配置登录方式：U盘登录",
            pages=[
                AuthMethodConfigPage(
                    page_id="intro",
                    title="说明",
                    widget_factory=_intro_factory,
                ),
                AuthMethodConfigPage(
                    page_id="binding",
                    title="绑定U盘",
                    widget_factory=_binding_factory,
                ),
            ],
            initial_state={},
            on_finish=_finish,
        )

"""集控管理窗口（FluentWidget）。"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QStackedWidget,
    QLineEdit,
    QCompleter,
    QListWidget,
    QListWidgetItem,
    QFileDialog,
    QInputDialog,
)
from qfluentwidgets import (
    FluentWidget,
    SegmentedWidget,
    SubtitleLabel,
    BodyLabel,
    CaptionLabel,
    PushButton,
    PrimaryPushButton,
    SwitchButton,
    SpinBox,
    LineEdit,
    PasswordLineEdit,
    PlainTextEdit,
    InfoBar,
    InfoBarPosition,
)

from app.services.central_control_service import CentralControlService
from app.services.i18n_service import tr
from app.services.permission_service import PermissionService


class CentralControlWindow(FluentWidget):
    """集控管理主窗口。"""

    def __init__(
        self,
        service: CentralControlService,
        permission_service: PermissionService | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self._svc = service
        self._perm = permission_service
        self._feature_completer: QCompleter | None = None

        self.setWindowTitle(tr("cc.title"))
        self.resize(1080, 760)
        self.setMinimumSize(900, 620)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, self.titleBar.height(), 0, 0)
        root.setSpacing(0)

        self._seg = SegmentedWidget(self)
        self._stack = QStackedWidget(self)
        self._stack.setStyleSheet("QStackedWidget{background:transparent;}")

        seg_row = QHBoxLayout()
        seg_row.setContentsMargins(20, 8, 20, 0)
        seg_row.addWidget(self._seg, 0, Qt.AlignmentFlag.AlignLeft)

        root.addLayout(seg_row)
        root.addSpacing(6)
        root.addWidget(self._stack, 1)

        self._init_status_page()
        self._init_policy_page()
        self._init_devices_page()
        self._init_server_page()

        self._svc.changed.connect(self.refresh_all)
        self._svc.policyApplied.connect(self._refresh_status_snapshot)
        self._svc.devicesUpdated.connect(self._refresh_device_list)
        self._svc.syncStateChanged.connect(self._refresh_status_snapshot)
        if self._perm is not None:
            self._perm.registryChanged.connect(self._refresh_feature_completer)

        self._seg.setCurrentItem("status")
        self._stack.setCurrentWidget(self._status_page)
        self._refresh_feature_completer()
        self.refresh_all()

    # ------------------------------------------------------------------ #
    # 页面初始化
    # ------------------------------------------------------------------ #

    def _add_page(self, widget: QWidget, key: str, text: str) -> None:
        widget.setObjectName(key)
        self._stack.addWidget(widget)
        self._seg.addItem(routeKey=key, text=text, onClick=lambda: self._stack.setCurrentWidget(widget))

    def _init_status_page(self) -> None:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 16, 24, 20)
        layout.setSpacing(10)

        layout.addWidget(SubtitleLabel(tr("cc.status.section_title"), page))
        layout.addWidget(CaptionLabel(tr("cc.status.section_desc"), page))

        enable_row = QHBoxLayout()
        enable_row.addWidget(BodyLabel(tr("cc.status.master_switch"), page))
        enable_row.addStretch(1)
        self._enabled_switch = SwitchButton(page)
        enable_row.addWidget(self._enabled_switch)
        layout.addLayout(enable_row)

        url_row = QHBoxLayout()
        self._server_url_edit = LineEdit(page)
        self._server_url_edit.setPlaceholderText(tr("cc.status.server_url_ph"))
        self._server_url_edit.setClearButtonEnabled(True)
        self._device_id_edit = LineEdit(page)
        self._device_id_edit.setPlaceholderText(tr("cc.status.device_id_ph"))
        self._device_id_edit.setClearButtonEnabled(True)
        url_row.addWidget(self._server_url_edit, 2)
        url_row.addWidget(self._device_id_edit, 1)
        layout.addLayout(url_row)

        name_row = QHBoxLayout()
        self._device_name_edit = LineEdit(page)
        self._device_name_edit.setPlaceholderText(tr("cc.status.device_name_ph"))
        self._device_name_edit.setClearButtonEnabled(True)
        self._poll_spin = SpinBox(page)
        self._poll_spin.setRange(10, 3600)
        self._poll_spin.setSuffix(tr("cc.status.poll_suffix"))
        name_row.addWidget(self._device_name_edit, 2)
        name_row.addWidget(self._poll_spin, 1)
        layout.addLayout(name_row)

        btn_row = QHBoxLayout()
        self._save_basic_btn = PrimaryPushButton(tr("cc.btn.save_basic"), page)
        self._ping_btn = PushButton(tr("cc.btn.test_connection"), page)
        self._heartbeat_btn = PushButton(tr("cc.btn.heartbeat"), page)
        self._pull_policy_btn = PushButton(tr("cc.btn.pull_policy"), page)
        self._sync_now_btn = PushButton(tr("cc.btn.sync_now"), page)
        btn_row.addWidget(self._save_basic_btn)
        btn_row.addWidget(self._ping_btn)
        btn_row.addWidget(self._heartbeat_btn)
        btn_row.addWidget(self._pull_policy_btn)
        btn_row.addWidget(self._sync_now_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        self._status_text = BodyLabel("", page)
        self._status_text.setWordWrap(True)
        layout.addWidget(self._status_text)

        self._applied_text = PlainTextEdit(page)
        self._applied_text.setReadOnly(True)
        self._applied_text.setPlaceholderText(tr("cc.status.applied_ph"))
        self._applied_text.setMinimumHeight(260)
        layout.addWidget(self._applied_text, 1)

        self._enabled_switch.checkedChanged.connect(self._on_switch_enabled)
        self._save_basic_btn.clicked.connect(self._on_save_basic)
        self._ping_btn.clicked.connect(self._on_ping)
        self._heartbeat_btn.clicked.connect(self._on_heartbeat)
        self._pull_policy_btn.clicked.connect(self._on_pull_policy)
        self._sync_now_btn.clicked.connect(self._on_sync_now)

        self._status_page = page
        self._add_page(page, "status", tr("cc.tab.status"))

    def _init_policy_page(self) -> None:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 16, 24, 20)
        layout.setSpacing(10)

        layout.addWidget(SubtitleLabel(tr("cc.policy.section_title"), page))
        layout.addWidget(CaptionLabel(tr("cc.policy.section_desc"), page))

        line1 = QHBoxLayout()
        line1.addWidget(BodyLabel(tr("cc.policy.enabled"), page))
        line1.addStretch(1)
        self._policy_enabled_switch = SwitchButton(page)
        line1.addWidget(self._policy_enabled_switch)
        layout.addLayout(line1)

        line2 = QHBoxLayout()
        line2.addWidget(BodyLabel(tr("cc.policy.deny_install"), page))
        line2.addStretch(1)
        self._deny_install_switch = SwitchButton(page)
        line2.addWidget(self._deny_install_switch)
        layout.addLayout(line2)

        self._blocked_features_edit = LineEdit(page)
        self._blocked_features_edit.setPlaceholderText(tr("cc.policy.blocked_features_ph"))
        self._blocked_features_edit.setClearButtonEnabled(True)
        self._blocked_features_edit.textEdited.connect(self._on_blocked_features_text_edited)
        layout.addWidget(self._blocked_features_edit)

        self._blocked_perm_items_edit = LineEdit(page)
        self._blocked_perm_items_edit.setPlaceholderText(tr("cc.policy.blocked_perm_ph"))
        self._blocked_perm_items_edit.setClearButtonEnabled(True)
        layout.addWidget(self._blocked_perm_items_edit)

        self._managed_plugins_edit = LineEdit(page)
        self._managed_plugins_edit.setPlaceholderText(tr("cc.policy.managed_plugins_ph"))
        self._managed_plugins_edit.setClearButtonEnabled(True)
        layout.addWidget(self._managed_plugins_edit)

        self._fullscreen_list_edit = LineEdit(page)
        self._fullscreen_list_edit.setPlaceholderText(tr("cc.policy.fullscreen_list_ph"))
        self._fullscreen_list_edit.setClearButtonEnabled(True)
        layout.addWidget(self._fullscreen_list_edit)

        layout.addWidget(CaptionLabel(tr("cc.policy.global_settings_label"), page))
        self._global_settings_edit = PlainTextEdit(page)
        self._global_settings_edit.setPlaceholderText('{"theme": "dark", "language": "zh-CN"}')
        self._global_settings_edit.setMinimumHeight(100)
        layout.addWidget(self._global_settings_edit)

        layout.addWidget(CaptionLabel(tr("cc.policy.plugin_configs_label"), page))
        self._plugin_configs_edit = PlainTextEdit(page)
        self._plugin_configs_edit.setMinimumHeight(120)
        layout.addWidget(self._plugin_configs_edit)

        layout.addWidget(CaptionLabel(tr("cc.policy.forced_layouts_label"), page))
        self._forced_layouts_edit = PlainTextEdit(page)
        self._forced_layouts_edit.setMinimumHeight(140)
        layout.addWidget(self._forced_layouts_edit)

        push_row = QHBoxLayout()
        self._admin_pwd_edit = PasswordLineEdit(page)
        self._admin_pwd_edit.setPlaceholderText(tr("cc.policy.admin_pwd_ph"))
        self._save_policy_btn = PrimaryPushButton(tr("cc.btn.save_policy_local"), page)
        self._push_policy_btn = PushButton(tr("cc.btn.push_policy"), page)
        push_row.addWidget(self._admin_pwd_edit, 2)
        push_row.addWidget(self._save_policy_btn)
        push_row.addWidget(self._push_policy_btn)
        layout.addLayout(push_row)

        self._save_policy_btn.clicked.connect(self._on_save_policy_local)
        self._push_policy_btn.clicked.connect(self._on_push_policy)

        self._policy_page = page
        self._add_page(page, "policy", tr("cc.tab.policy"))

    def _init_devices_page(self) -> None:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 16, 24, 20)
        layout.setSpacing(10)

        layout.addWidget(SubtitleLabel(tr("cc.devices.section_title"), page))
        layout.addWidget(CaptionLabel(tr("cc.devices.section_desc"), page))

        row = QHBoxLayout()
        self._device_admin_pwd_edit = PasswordLineEdit(page)
        self._device_admin_pwd_edit.setPlaceholderText(tr("cc.devices.admin_pwd_ph"))
        self._refresh_devices_btn = PushButton(tr("cc.btn.refresh_devices"), page)
        self._sync_managed_btn = PushButton(tr("cc.btn.sync_managed"), page)
        self._push_to_selected_btn = PrimaryPushButton(tr("cc.btn.push_selected"), page)
        row.addWidget(self._device_admin_pwd_edit, 2)
        row.addWidget(self._refresh_devices_btn)
        row.addWidget(self._sync_managed_btn)
        row.addWidget(self._push_to_selected_btn)
        layout.addLayout(row)

        self._devices_list = QListWidget(page)
        self._devices_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        layout.addWidget(self._devices_list, 1)

        self._refresh_devices_btn.clicked.connect(self._on_refresh_devices)
        self._sync_managed_btn.clicked.connect(self._on_sync_managed_devices)
        self._push_to_selected_btn.clicked.connect(self._on_push_selected_devices)

        self._devices_page = page
        self._add_page(page, "devices", tr("cc.tab.devices"))

    def _init_server_page(self) -> None:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 16, 24, 20)
        layout.setSpacing(10)

        layout.addWidget(SubtitleLabel(tr("cc.server.section_title"), page))
        layout.addWidget(CaptionLabel(tr("cc.server.section_desc"), page))

        dir_row = QHBoxLayout()
        self._bundle_dir_edit = LineEdit(page)
        self._bundle_dir_edit.setPlaceholderText(tr("cc.server.bundle_dir_ph"))
        self._bundle_dir_edit.setClearButtonEnabled(True)
        self._choose_dir_btn = PushButton(tr("cc.btn.choose_dir"), page)
        self._build_bundle_btn = PrimaryPushButton(tr("cc.btn.build_bundle"), page)
        self._open_dir_btn = PushButton(tr("cc.btn.open_dir"), page)
        dir_row.addWidget(self._bundle_dir_edit, 1)
        dir_row.addWidget(self._choose_dir_btn)
        dir_row.addWidget(self._build_bundle_btn)
        dir_row.addWidget(self._open_dir_btn)
        layout.addLayout(dir_row)

        self._run_hint = PlainTextEdit(page)
        self._run_hint.setReadOnly(True)
        self._run_hint.setMinimumHeight(120)
        layout.addWidget(self._run_hint)

        layout.addWidget(SubtitleLabel(tr("cc.server.manage_pwd_title"), page))
        pwd_row = QHBoxLayout()
        self._manage_pwd_edit = PasswordLineEdit(page)
        self._manage_pwd_edit.setPlaceholderText(tr("cc.server.manage_pwd_ph"))
        self._set_manage_pwd_btn = PrimaryPushButton(tr("cc.btn.set_pwd"), page)
        self._clear_manage_pwd_btn = PushButton(tr("cc.btn.clear_pwd"), page)
        self._lock_manage_btn = PushButton(tr("cc.btn.lock_session"), page)
        pwd_row.addWidget(self._manage_pwd_edit, 1)
        pwd_row.addWidget(self._set_manage_pwd_btn)
        pwd_row.addWidget(self._clear_manage_pwd_btn)
        pwd_row.addWidget(self._lock_manage_btn)
        layout.addLayout(pwd_row)

        self._manage_hint = CaptionLabel("", page)
        layout.addWidget(self._manage_hint)
        layout.addStretch(1)

        self._choose_dir_btn.clicked.connect(self._on_choose_bundle_dir)
        self._build_bundle_btn.clicked.connect(self._on_build_bundle)
        self._open_dir_btn.clicked.connect(self._on_open_bundle_dir)
        self._set_manage_pwd_btn.clicked.connect(self._on_set_manage_pwd)
        self._clear_manage_pwd_btn.clicked.connect(self._on_clear_manage_pwd)
        self._lock_manage_btn.clicked.connect(self._on_lock_manage)

        self._server_page = page
        self._add_page(page, "server", tr("cc.tab.server"))

    # ------------------------------------------------------------------ #
    # 权限与提示
    # ------------------------------------------------------------------ #

    def _require_manage_access(self, reason: str) -> bool:
        if self._perm is not None:
            if not self._perm.ensure_access("central.manage", parent=self, reason=reason):
                deny_reason = self._perm.get_last_denied_reason("central.manage")
                if deny_reason:
                    self._toast_error(deny_reason)
                return False

        if self._svc.is_manage_unlocked():
            return True

        text, ok = QInputDialog.getText(
            self,
            tr("cc.dlg.pwd_title"),
            tr("cc.dlg.pwd_prompt"),
            QLineEdit.EchoMode.Password,
        )
        if not ok:
            return False
        if self._svc.unlock_manage_session(text):
            return True

        self._toast_error(tr("cc.err.wrong_pwd"))
        return False

    def _toast_success(self, content: str) -> None:
        InfoBar.success(tr("cc.title"), content, parent=self, position=InfoBarPosition.TOP_RIGHT, duration=2600)

    def _toast_warn(self, content: str) -> None:
        InfoBar.warning(tr("cc.title"), content, parent=self, position=InfoBarPosition.TOP_RIGHT, duration=3200)

    def _toast_error(self, content: str) -> None:
        InfoBar.error(tr("cc.title"), content, parent=self, position=InfoBarPosition.TOP_RIGHT, duration=4200)

    # ------------------------------------------------------------------ #
    # 数据刷新
    # ------------------------------------------------------------------ #

    def _feature_completion_keys(self) -> list[str]:
        values: list[str] = []
        if self._perm is not None:
            for item in self._perm.list_items():
                key = str(getattr(item, "key", "") or "").strip()
                if key:
                    values.append(key)

        values.extend([
            "debug.open",
            "settings.modify",
            "plugin.install",
            "plugin.manage",
            "layout.edit",
            "layout.add_widget",
            "layout.edit_widget",
            "layout.delete_widget",
            "layout.import_export",
            "world_time.manage",
            "central.manage",
            "permission.manage",
        ])

        for value in self._svc.policy.get("blocked_features", []) or []:
            text = str(value or "").strip()
            if text:
                values.append(text)

        return sorted({text for text in values if text})

    def _refresh_feature_completer(self) -> None:
        if not hasattr(self, "_blocked_features_edit"):
            return

        keys = self._feature_completion_keys()
        if not keys:
            return

        completer = QCompleter(keys, self._blocked_features_edit)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setMaxVisibleItems(12)
        completer.activated.connect(self._on_feature_completion_selected)
        self._feature_completer = completer
        self._blocked_features_edit.setCompleter(completer)

    def _on_blocked_features_text_edited(self, text: str) -> None:
        if self._feature_completer is None:
            return
        token = str(text or "").rsplit(",", 1)[-1].strip()
        self._feature_completer.setCompletionPrefix(token)

    def _on_feature_completion_selected(self, selected_key: str) -> None:
        selected = str(selected_key or "").strip()
        if not selected:
            return

        raw = self._blocked_features_edit.text()
        parts = [part.strip() for part in raw.split(",")]
        if not parts:
            parts = [""]
        parts[-1] = selected

        values: list[str] = []
        seen: set[str] = set()
        for part in parts:
            text = str(part or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            values.append(text)

        merged = ", ".join(values)
        if merged:
            merged += ", "
        self._blocked_features_edit.setText(merged)
        self._blocked_features_edit.setFocus()
        self._blocked_features_edit.setCursorPosition(len(merged))

    def refresh_all(self) -> None:
        snapshot = self._svc.status_snapshot()
        self._refresh_feature_completer()

        self._enabled_switch.blockSignals(True)
        self._enabled_switch.setChecked(bool(snapshot.get("enabled", False)))
        self._enabled_switch.blockSignals(False)

        self._server_url_edit.setText(self._svc.server_url)
        self._device_id_edit.setText(self._svc.device_id)
        self._device_name_edit.setText(self._svc.device_name)
        self._poll_spin.setValue(self._svc.poll_interval_sec)
        self._bundle_dir_edit.setText(self._svc.server_bundle_dir)

        self._policy_enabled_switch.blockSignals(True)
        self._policy_enabled_switch.setChecked(bool(self._svc.policy.get("enabled", False)))
        self._policy_enabled_switch.blockSignals(False)

        self._deny_install_switch.blockSignals(True)
        self._deny_install_switch.setChecked(bool(self._svc.policy.get("deny_plugin_install", False)))
        self._deny_install_switch.blockSignals(False)

        self._blocked_features_edit.setText(",".join(self._svc.policy.get("blocked_features", [])))
        self._blocked_perm_items_edit.setText(",".join(self._svc.policy.get("blocked_permission_items", [])))
        self._managed_plugins_edit.setText(",".join(self._svc.policy.get("managed_plugins", [])))
        self._fullscreen_list_edit.setText(",".join(self._svc.policy.get("fullscreen_clock_list", [])))

        self._global_settings_edit.setPlainText(
            json.dumps(self._svc.policy.get("global_settings", {}), ensure_ascii=False, indent=2)
        )
        self._plugin_configs_edit.setPlainText(
            json.dumps(self._svc.policy.get("plugin_configs", {}), ensure_ascii=False, indent=2)
        )
        self._forced_layouts_edit.setPlainText(
            json.dumps(self._svc.policy.get("forced_layouts", {}), ensure_ascii=False, indent=2)
        )

        self._refresh_status_snapshot()
        self._refresh_device_list()

        self._manage_hint.setText(tr("cc.manage.unlocked") if self._svc.is_manage_unlocked() else tr("cc.manage.locked"))
        self._run_hint.setPlainText(self._bundle_run_hint_text(self._svc.server_bundle_dir))

    def _refresh_status_snapshot(self) -> None:
        snap = self._svc.status_snapshot()
        status_lines = [
            tr("cc.snapshot.central_switch", value=tr("cc.value.on") if snap.get("enabled") else tr("cc.value.off")),
            tr(
                "cc.snapshot.policy_effective",
                value=tr("cc.value.yes") if (snap.get("enabled") and snap.get("policy_enabled")) else tr("cc.value.no"),
            ),
            tr("cc.snapshot.policy_version", value=snap.get("policy_version")),
            tr(
                "cc.snapshot.auto_sync",
                status=tr("cc.value.running") if snap.get("auto_sync_active") else tr("cc.value.not_running"),
                interval=snap.get("poll_interval_sec"),
            ),
            tr(
                "cc.snapshot.sync_status",
                value=tr("cc.value.syncing")
                if snap.get("syncing")
                else (tr("common.success") if snap.get("last_sync_ok") else tr("cc.value.not_synced")),
            ),
            tr("cc.snapshot.last_sync", value=snap.get("last_sync_at") or "-"),
            tr("cc.snapshot.last_heartbeat", value=snap.get("last_heartbeat_at") or "-"),
            tr("cc.snapshot.last_pull", value=snap.get("last_policy_pull_at") or "-"),
            tr("cc.snapshot.cached_devices", value=snap.get("cached_devices")),
        ]
        self._status_text.setText("\n".join(status_lines))

        lines = []
        applied = snap.get("applied_settings", []) or []
        if applied:
            lines.append(tr("cc.applied.header"))
            lines.extend([f"- {item}" for item in applied])
        else:
            lines.append(tr("cc.applied.none"))

        blocked = snap.get("blocked_features", []) or []
        lines.append("")
        lines.append(tr("cc.applied.blocked_features"))
        lines.extend([f"- {item}" for item in blocked] if blocked else [tr("cc.applied.none_item")])

        blocked_perm = snap.get("blocked_permission_items", []) or []
        lines.append("")
        lines.append(tr("cc.applied.blocked_perm"))
        lines.extend([f"- {item}" for item in blocked_perm] if blocked_perm else [tr("cc.applied.none_item")])

        lines.append("")
        lines.append(tr("cc.applied.sync_summary"))
        lines.append(tr("cc.applied.sync_reason", value=snap.get("last_sync_reason") or "-"))
        lines.append(tr("cc.applied.sync_message", value=snap.get("last_sync_message") or "-"))

        self._applied_text.setPlainText("\n".join(lines))

    def _refresh_device_list(self) -> None:
        self._devices_list.clear()
        devices = self._svc.cached_devices()
        managed = set(self._svc.policy.get("managed_devices", []))
        for item in devices:
            device_id = str(item.get("device_id") or "")
            device_name = str(item.get("device_name") or "")
            app_version = str(item.get("app_version") or "")
            last_seen = str(item.get("last_seen") or "")
            line = tr(
                "cc.devices.row",
                name=device_name or device_id,
                id=device_id,
                version=app_version,
                last_seen=last_seen,
            )
            row = QListWidgetItem(line)
            row.setData(Qt.ItemDataRole.UserRole, device_id)
            row.setFlags(row.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            row.setCheckState(Qt.CheckState.Checked if device_id in managed else Qt.CheckState.Unchecked)
            self._devices_list.addItem(row)

    # ------------------------------------------------------------------ #
    # 事件
    # ------------------------------------------------------------------ #

    def _on_switch_enabled(self, checked: bool) -> None:
        if not self._require_manage_access(tr("cc.reason.toggle_switch")):
            self.refresh_all()
            return
        self._svc.set_enabled(bool(checked))
        self._toast_success(tr("cc.msg.switch_updated"))

    def _on_save_basic(self) -> bool:
        if not self._require_manage_access(tr("cc.reason.save_basic")):
            return False
        self._svc.set_server_url(self._server_url_edit.text().strip())
        self._svc.set_device_id(self._device_id_edit.text().strip())
        self._svc.set_device_name(self._device_name_edit.text().strip())
        self._svc.set_poll_interval_sec(self._poll_spin.value())
        self._toast_success(tr("cc.msg.basic_saved"))
        return True

    def _on_ping(self) -> None:
        if not self._on_save_basic():
            return
        ok, msg, data = self._svc.ping_server()
        if ok:
            extra = ""
            if data:
                extra = tr("cc.msg.ping_extra", version=data.get("policy_version"))
            self._toast_success(tr("cc.msg.ping_ok", extra=extra))
        else:
            self._toast_error(msg)

    def _on_heartbeat(self) -> None:
        if not self._on_save_basic():
            return
        ok, msg = self._svc.heartbeat()
        if ok:
            self._toast_success(msg)
        else:
            self._toast_error(msg)

    def _on_pull_policy(self) -> None:
        if not self._on_save_basic():
            return
        ok, msg = self._svc.pull_policy()
        if ok:
            self._toast_success(msg)
        else:
            self._toast_error(msg)

    def _on_sync_now(self) -> None:
        if not self._on_save_basic():
            return
        ok, msg = self._svc.sync_once(reason="manual:status_page")
        if ok:
            self._toast_success(msg)
        else:
            self._toast_error(msg)

    def _collect_policy_from_ui(self) -> dict | None:
        try:
            global_settings = json.loads(self._global_settings_edit.toPlainText().strip() or "{}")
            plugin_configs = json.loads(self._plugin_configs_edit.toPlainText().strip() or "{}")
            forced_layouts = json.loads(self._forced_layouts_edit.toPlainText().strip() or "{}")
        except Exception as exc:
            self._toast_error(tr("cc.err.json_parse", error=exc))
            return None

        if not isinstance(global_settings, dict):
            self._toast_error(tr("cc.err.global_settings_not_obj"))
            return None
        if not isinstance(plugin_configs, dict):
            self._toast_error(tr("cc.err.plugin_configs_not_obj"))
            return None
        if not isinstance(forced_layouts, dict):
            self._toast_error(tr("cc.err.forced_layouts_not_obj"))
            return None

        policy = self._svc.policy
        policy["enabled"] = bool(self._policy_enabled_switch.isChecked())
        policy["deny_plugin_install"] = bool(self._deny_install_switch.isChecked())
        policy["blocked_features"] = [s.strip() for s in self._blocked_features_edit.text().split(",") if s.strip()]
        policy["blocked_permission_items"] = [s.strip() for s in self._blocked_perm_items_edit.text().split(",") if s.strip()]
        policy["managed_plugins"] = [s.strip() for s in self._managed_plugins_edit.text().split(",") if s.strip()]
        policy["fullscreen_clock_list"] = [s.strip() for s in self._fullscreen_list_edit.text().split(",") if s.strip()]
        policy["global_settings"] = global_settings
        policy["plugin_configs"] = plugin_configs
        policy["forced_layouts"] = forced_layouts
        policy["updated_at"] = ""
        policy["updated_by"] = "local-ui"
        return policy

    def _on_save_policy_local(self) -> None:
        if not self._require_manage_access(tr("cc.reason.save_policy")):
            return
        policy = self._collect_policy_from_ui()
        if policy is None:
            return
        self._svc.replace_policy(policy, apply_now=True)
        self._toast_success(tr("cc.msg.policy_saved_local"))

    def _on_push_policy(self) -> None:
        if not self._require_manage_access(tr("cc.reason.push_policy")):
            return
        policy = self._collect_policy_from_ui()
        if policy is None:
            return
        self._svc.replace_policy(policy, apply_now=True)

        admin_pwd = self._admin_pwd_edit.text().strip() or self._svc.server_admin_password
        if not admin_pwd:
            self._toast_warn(tr("cc.warn.enter_admin_pwd"))
            return
        self._svc.set_server_admin_password(admin_pwd)

        ok, msg = self._svc.push_policy(admin_pwd)
        if ok:
            self._toast_success(msg)
        else:
            self._toast_error(msg)

    def _on_refresh_devices(self) -> None:
        admin_pwd = self._device_admin_pwd_edit.text().strip() or self._svc.server_admin_password
        if not admin_pwd:
            self._toast_warn(tr("cc.warn.enter_admin_pwd"))
            return
        self._svc.set_server_admin_password(admin_pwd)

        ok, msg, _devices = self._svc.fetch_devices(admin_pwd)
        if ok:
            self._toast_success(msg)
        else:
            self._toast_error(msg)

    def _on_sync_managed_devices(self) -> None:
        if not self._require_manage_access(tr("cc.reason.sync_managed")):
            return
        selected_ids = self._checked_device_ids()
        policy = self._svc.policy
        policy["managed_devices"] = selected_ids
        self._svc.replace_policy(policy, apply_now=False)
        self._toast_success(tr("cc.msg.synced_managed", count=len(selected_ids)))

    def _on_push_selected_devices(self) -> None:
        if not self._require_manage_access(tr("cc.reason.batch_push")):
            return
        selected_ids = self._checked_device_ids()
        if not selected_ids:
            self._toast_warn(tr("cc.warn.select_device"))
            return

        admin_pwd = self._device_admin_pwd_edit.text().strip() or self._svc.server_admin_password
        if not admin_pwd:
            self._toast_warn(tr("cc.warn.enter_admin_pwd"))
            return
        self._svc.set_server_admin_password(admin_pwd)

        ok, msg = self._svc.push_policy(admin_pwd, target_device_ids=selected_ids)
        if ok:
            self._toast_success(msg)
        else:
            self._toast_error(msg)

    def _checked_device_ids(self) -> list[str]:
        values: list[str] = []
        for i in range(self._devices_list.count()):
            row = self._devices_list.item(i)
            if row.checkState() != Qt.CheckState.Checked:
                continue
            device_id = str(row.data(Qt.ItemDataRole.UserRole) or "").strip()
            if device_id:
                values.append(device_id)
        return values

    def _on_choose_bundle_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, tr("cc.dlg.choose_bundle_dir"), self._bundle_dir_edit.text().strip() or "")
        if path:
            self._bundle_dir_edit.setText(path)

    def _on_build_bundle(self) -> None:
        if not self._require_manage_access(tr("cc.reason.build_bundle")):
            return
        target = self._bundle_dir_edit.text().strip()
        if not target:
            self._toast_warn(tr("cc.warn.choose_dir"))
            return
        ok, msg = self._svc.create_server_bundle(target)
        if ok:
            self._toast_success(msg)
            self.refresh_all()
        else:
            self._toast_error(msg)

    def _on_open_bundle_dir(self) -> None:
        path = self._bundle_dir_edit.text().strip() or self._svc.server_bundle_dir
        if not path:
            self._toast_warn(tr("cc.warn.no_bundle_dir"))
            return
        target = Path(path)
        if not target.exists():
            self._toast_error(tr("cc.err.dir_not_exist"))
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    def _on_set_manage_pwd(self) -> None:
        text = self._manage_pwd_edit.text().strip()
        if not text:
            self._toast_warn(tr("cc.warn.enter_pwd"))
            return
        self._svc.set_manage_password(text)
        self._svc.unlock_manage_session(text)
        self._manage_pwd_edit.clear()
        self.refresh_all()
        self._toast_success(tr("cc.msg.pwd_set"))

    def _on_clear_manage_pwd(self) -> None:
        if not self._require_manage_access(tr("cc.reason.clear_pwd")):
            return
        self._svc.clear_manage_password()
        self.refresh_all()
        self._toast_success(tr("cc.msg.pwd_cleared"))

    def _on_lock_manage(self) -> None:
        self._svc.reset_manage_unlock()
        self.refresh_all()
        self._toast_success(tr("cc.msg.session_locked"))

    def _bundle_run_hint_text(self, bundle_dir: str) -> str:
        if not bundle_dir:
            return tr("cc.server.run_hint_empty")
        return tr("cc.server.run_hint", dir=bundle_dir)

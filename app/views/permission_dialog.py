"""插件权限请求对话框（库安装 & 系统权限通用）"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout
from qfluentwidgets import (
    MessageBoxBase, SubtitleLabel, BodyLabel, CaptionLabel,
    PrimaryPushButton, PushButton, CardWidget,
)

from app.plugins.plugin_manager import PermissionLevel, PERMISSION_NAMES
from app.services.i18n_service import I18nService


class _BasePermDialog(MessageBoxBase):
    """权限对话框基类，提供三按钮布局（始终允许 / 本次允许 / 拒绝）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._result = PermissionLevel.DENY
        self._i18n = I18nService.instance()

        # 隐藏父类默认按钮
        self.yesButton.hide()
        self.cancelButton.hide()

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._always_btn = PrimaryPushButton(self._i18n.t("perm.dialog.always"), self)
        self._once_btn   = PushButton(self._i18n.t("perm.dialog.once"), self)
        self._deny_btn   = PushButton(self._i18n.t("perm.dialog.deny"), self)
        self._always_btn.setMinimumWidth(112)
        self._once_btn.setMinimumWidth(96)
        self._deny_btn.setMinimumWidth(76)

        btn_row.addStretch()
        btn_row.addWidget(self._always_btn)
        btn_row.addWidget(self._once_btn)
        btn_row.addWidget(self._deny_btn)

        self.viewLayout.addSpacing(8)
        self.viewLayout.addLayout(btn_row)

        self._always_btn.clicked.connect(self._on_always)
        self._once_btn.clicked.connect(self._on_once)
        self._deny_btn.clicked.connect(self._on_deny)

        self.widget.setMinimumWidth(440)

    def _on_always(self) -> None:
        self._result = PermissionLevel.ALWAYS_ALLOW
        self.accept()

    def _on_once(self) -> None:
        self._result = PermissionLevel.ASK_EACH_TIME
        self.accept()

    def _on_deny(self) -> None:
        self._result = PermissionLevel.DENY
        self.reject()

    @property
    def permission(self) -> PermissionLevel:
        return self._result


# ──────────────────────────────────────────────────────────────────── #

class InstallPermissionDialog(_BasePermDialog):
    """当插件需要安装第三方库时弹出的权限请求对话框。"""

    def __init__(
        self,
        plugin_name: str,
        packages: list[str],
        parent=None,
    ):
        super().__init__(parent)
        i18n = I18nService.instance()

        # 安装权限使用：允许（始终）/ 拒绝（本次）/ 永久拒绝
        self._always_btn.setText(i18n.t("perm.dialog.install.allow", default="允许"))
        self._once_btn.setText(i18n.t("perm.dialog.install.deny_once", default="拒绝"))
        self._deny_btn.setText(i18n.t("perm.dialog.install.deny_forever", default="永久拒绝"))

        self.titleLabel = SubtitleLabel(i18n.t("perm.dialog.install.title"), self)

        desc = BodyLabel(
            i18n.t("perm.dialog.install.desc", plugin=plugin_name),
            self,
        )
        desc.setWordWrap(True)

        pkg_card = CardWidget(self)
        pkg_layout = QVBoxLayout(pkg_card)
        pkg_layout.setContentsMargins(12, 8, 12, 8)
        pkg_layout.setSpacing(2)
        for pkg in packages:
            pkg_layout.addWidget(CaptionLabel(f"• {pkg}", pkg_card))

        notice = CaptionLabel(
            i18n.t("perm.dialog.install.notice"),
            self,
        )
        notice.setWordWrap(True)

        self.viewLayout.insertWidget(0, self.titleLabel)
        self.viewLayout.insertSpacing(1, 4)
        self.viewLayout.insertWidget(2, desc)
        self.viewLayout.insertWidget(3, pkg_card)
        self.viewLayout.insertWidget(4, notice)

    @classmethod
    def ask(
        cls,
        plugin_name: str,
        packages: list[str],
        parent=None,
    ) -> PermissionLevel:
        dlg = cls(plugin_name, packages, parent)
        dlg.exec()
        return dlg.permission


# ──────────────────────────────────────────────────────────────────── #

class SysPermissionDialog(_BasePermDialog):
    """当插件首次请求某系统权限时弹出的确认对话框。"""

    # 权限对应的风险描述
    _RISK: dict[str, tuple[str, str]] = {
        "network":      ("🌐", "perm.risk.network"),
        "fs_read":      ("📂", "perm.risk.fs_read"),
        "fs_write":     ("✏️", "perm.risk.fs_write"),
        "os_exec":      ("⚙️", "perm.risk.os_exec"),
        "os_env":       ("🔑", "perm.risk.os_env"),
        "clipboard":    ("📋", "perm.risk.clipboard"),
        "notification": ("🔔", "perm.risk.notification"),
        "install_pkg":  ("📦", "perm.risk.install_pkg"),
    }

    def __init__(
        self,
        plugin_name: str,
        perm_key: str,
        perm_display: str,
        parent=None,
        reason: str = "",
    ):
        super().__init__(parent)
        i18n = I18nService.instance()

        icon, risk_key = self._RISK.get(perm_key, ("🔒", ""))
        risk_desc = i18n.t(risk_key, default=perm_display) if risk_key else perm_display

        self.titleLabel = SubtitleLabel(i18n.t("perm.dialog.sys.title", icon=icon), self)

        desc = BodyLabel(
            i18n.t("perm.dialog.sys.desc", plugin=plugin_name),
            self,
        )
        desc.setWordWrap(True)

        perm_card = CardWidget(self)
        perm_layout = QVBoxLayout(perm_card)
        perm_layout.setContentsMargins(12, 8, 12, 8)
        perm_layout.setSpacing(4)
        name_lbl = BodyLabel(f"<b>{perm_display}</b>", perm_card)
        risk_lbl = CaptionLabel(risk_desc, perm_card)
        risk_lbl.setWordWrap(True)
        perm_layout.addWidget(name_lbl)
        perm_layout.addWidget(risk_lbl)

        notice = CaptionLabel(
            i18n.t("perm.dialog.sys.notice"),
            self,
        )
        notice.setWordWrap(True)

        reason_lbl = None
        if reason:
            reason_lbl = CaptionLabel(reason, self)
            reason_lbl.setWordWrap(True)
            reason_lbl.setStyleSheet("color: #888;")

        self.viewLayout.insertWidget(0, self.titleLabel)
        self.viewLayout.insertSpacing(1, 4)
        self.viewLayout.insertWidget(2, desc)
        self.viewLayout.insertWidget(3, perm_card)
        insert_index = 4
        if reason_lbl is not None:
            self.viewLayout.insertWidget(insert_index, reason_lbl)
            insert_index += 1
        self.viewLayout.insertWidget(insert_index, notice)

    @classmethod
    def ask(
        cls,
        plugin_name: str,
        perm_key: str,
        perm_display: str,
        parent=None,
        *,
        reason: str = "",
    ) -> PermissionLevel:
        dlg = cls(plugin_name, perm_key, perm_display, parent, reason=reason)
        dlg.exec()
        return dlg.permission

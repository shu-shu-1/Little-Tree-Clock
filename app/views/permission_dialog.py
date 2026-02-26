"""插件权限请求对话框（库安装 & 系统权限通用）"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout
from qfluentwidgets import (
    MessageBoxBase, SubtitleLabel, BodyLabel, CaptionLabel,
    PrimaryPushButton, PushButton, CardWidget,
)

from app.plugins.plugin_manager import PermissionLevel, PERMISSION_NAMES


class _BasePermDialog(MessageBoxBase):
    """权限对话框基类，提供三按钮布局（始终允许 / 本次允许 / 拒绝）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._result = PermissionLevel.DENY

        # 隐藏父类默认按钮
        self.yesButton.hide()
        self.cancelButton.hide()

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._always_btn = PrimaryPushButton("始终允许", self)
        self._once_btn   = PushButton("本次允许", self)
        self._deny_btn   = PushButton("拒绝", self)

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

        self.titleLabel = SubtitleLabel("📦  安装库权限请求", self)

        desc = BodyLabel(
            f"插件 <b>{plugin_name}</b> 需要安装以下第三方库才能正常运行：",
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
            "这些库将被下载并安装到插件私有目录，不会影响系统 Python 环境。",
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
        "network":      ("🌐", "访问互联网，可能发送或接收数据"),
        "fs_read":      ("📂", "读取系统中的任意文件"),
        "fs_write":     ("✏️",  "修改或删除系统中的任意文件"),
        "os_exec":      ("⚙️",  "以当前用户身份执行任意外部命令"),
        "os_env":       ("🔑", "读取或修改系统环境变量"),
        "clipboard":    ("📋", "读取或写入系统剪贴板"),
        "notification": ("🔔", "弹出系统级通知"),
        "install_pkg":  ("📦", "向插件目录安装第三方 Python 库"),
    }

    def __init__(
        self,
        plugin_name: str,
        perm_key: str,
        perm_display: str,
        parent=None,
    ):
        super().__init__(parent)

        icon, risk_desc = self._RISK.get(perm_key, ("🔒", perm_display))

        self.titleLabel = SubtitleLabel(f"{icon}  系统权限请求", self)

        desc = BodyLabel(
            f"插件 <b>{plugin_name}</b> 请求以下系统权限：",
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
            "授予权限后，插件可在每次运行时使用该能力。您可随时在插件管理界面撤销。",
            self,
        )
        notice.setWordWrap(True)

        self.viewLayout.insertWidget(0, self.titleLabel)
        self.viewLayout.insertSpacing(1, 4)
        self.viewLayout.insertWidget(2, desc)
        self.viewLayout.insertWidget(3, perm_card)
        self.viewLayout.insertWidget(4, notice)

    @classmethod
    def ask(
        cls,
        plugin_name: str,
        perm_key: str,
        perm_display: str,
        parent=None,
    ) -> PermissionLevel:
        dlg = cls(plugin_name, perm_key, perm_display, parent)
        dlg.exec()
        return dlg.permission

"""独立权限系统的认证弹窗。"""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QWidget, QLineEdit
from qfluentwidgets import SubtitleLabel, BodyLabel, ComboBox, PushButton, PrimaryPushButton

from app.services.permission_service import PermissionService, AccessLevel


class PermissionAuthDialog(QDialog):
    """当功能需要更高权限时弹出的登录窗口。"""

    def __init__(
        self,
        service: PermissionService,
        required_level: AccessLevel,
        method_ids: list[str],
        feature_name: str,
        reason: str = "",
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._service = service
        self._required_level = AccessLevel.from_value(required_level)
        self._method_ids = list(method_ids)
        self._feature_name = str(feature_name or "受保护功能")
        self._reason = str(reason or "")
        self._ok = False

        self.setWindowTitle("权限验证")
        self.setModal(True)
        self.setMinimumWidth(420)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 16)
        root.setSpacing(10)

        title = SubtitleLabel("需要权限验证", self)
        root.addWidget(title)

        desc = BodyLabel(
            f"功能：{self._feature_name}\n"
            f"最低权限：{self._required_level.label}",
            self,
        )
        desc.setWordWrap(True)
        root.addWidget(desc)

        if self._reason:
            reason_label = BodyLabel(f"说明：{self._reason}", self)
            reason_label.setWordWrap(True)
            root.addWidget(reason_label)

        self._method_combo = ComboBox(self)
        for method_id in self._method_ids:
            method = self._service.get_auth_method(method_id)
            text = method.display_name if method else method_id
            self._method_combo.addItem(text, userData=method_id)
        root.addWidget(self._method_combo)

        self._password_edit = QLineEdit(self)
        self._password_edit.setPlaceholderText("请输入密码")
        self._password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        root.addWidget(self._password_edit)

        self._status_label = BodyLabel("", self)
        self._status_label.setStyleSheet("color:#d13438;")
        self._status_label.hide()
        root.addWidget(self._status_label)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._cancel_btn = PushButton("取消", self)
        self._ok_btn = PrimaryPushButton("验证", self)
        btn_row.addWidget(self._cancel_btn)
        btn_row.addWidget(self._ok_btn)
        root.addLayout(btn_row)

        self._cancel_btn.clicked.connect(self.reject)
        self._ok_btn.clicked.connect(self._on_verify)
        self._method_combo.currentIndexChanged.connect(self._on_method_changed)

        self._on_method_changed(self._method_combo.currentIndex())

    @property
    def approved(self) -> bool:
        return self._ok

    def _set_error(self, text: str) -> None:
        self._status_label.setText(text)
        self._status_label.show()

    def _clear_error(self) -> None:
        self._status_label.hide()
        self._status_label.setText("")

    def _on_method_changed(self, _index: int) -> None:
        method_id = str(self._method_combo.currentData() or "")
        need_password = (method_id == "password")
        self._password_edit.setVisible(need_password)
        if need_password:
            self._password_edit.setFocus()
        self._clear_error()

    def _on_verify(self) -> None:
        method_id = str(self._method_combo.currentData() or "")
        if not method_id:
            self._set_error("未选择登录方式")
            return

        payload = {}
        if method_id == "password":
            password = self._password_edit.text()
            if not password:
                self._set_error("请输入密码")
                return
            payload["password"] = password

        ok = self._service.authenticate(
            self._required_level,
            method_id,
            payload,
            parent=self,
        )
        if ok:
            self._ok = True
            self.accept()
            return

        if method_id == "password" and not self._service.has_password(self._required_level):
            self._set_error(f"{self._required_level.label} 级密码尚未设置")
            return
        self._set_error("验证失败，请重试")

    @classmethod
    def ask(
        cls,
        service: PermissionService,
        required_level: AccessLevel,
        method_ids: list[str],
        feature_name: str,
        reason: str = "",
        parent: Optional[QWidget] = None,
    ) -> bool:
        dlg = cls(service, required_level, method_ids, feature_name, reason=reason, parent=parent)
        dlg.exec()
        return dlg.approved

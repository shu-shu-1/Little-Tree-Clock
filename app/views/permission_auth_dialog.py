"""独立权限系统的认证弹窗。"""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QWidget
from qfluentwidgets import (
    BodyLabel,
    ComboBox,
    MessageBox,
    FluentIcon as FIF,
    PasswordLineEdit,
)

from app.services.permission_service import PermissionService, AccessLevel
from app.services.i18n_service import I18nService


def _t(key: str, default: str = "", **kwargs) -> str:
    return I18nService.instance().t(key, default, **kwargs)


class PermissionAuthDialog(MessageBox):
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
        super().__init__(_t("perm.dialog.title", "权限验证"), "", parent)
        self._service = service
        self._required_level = AccessLevel.from_value(required_level)
        self._method_ids = list(method_ids)
        self._feature_name = str(feature_name or "受保护功能")
        self._reason = str(reason or "")
        self._ok = False

        self.setModal(True)
        self.widget.setFixedSize(460, 320)
        self.contentLabel.hide()
        self.textLayout.setContentsMargins(20, 16, 20, 14)
        self.textLayout.setSpacing(10)

        self.yesButton.setText(_t("perm.dialog.verify", "验证"))
        self.cancelButton.setText(_t("perm.dialog.cancel", "取消"))
        self.yesButton.setIcon(FIF.ACCEPT)
        self.cancelButton.setIcon(FIF.CANCEL.icon())

        desc = BodyLabel(
            f"{_t('perm.dialog.feature', '功能')}: {self._feature_name}\n"
            f"{_t('perm.dialog.level', '最低权限')}: {self._required_level.label}",
            self,
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("background: transparent;")
        self.textLayout.addWidget(desc)

        if self._reason:
            reason_label = BodyLabel(f"{_t('perm.dialog.reason', '说明')}: {self._reason}", self)
            reason_label.setWordWrap(True)
            reason_label.setStyleSheet("background: transparent;")
            self.textLayout.addWidget(reason_label)

        self._method_combo = ComboBox(self)
        for method_id in self._method_ids:
            method = self._service.get_auth_method(method_id)
            text = method.display_name if method else method_id
            self._method_combo.addItem(text, userData=method_id)
        self.textLayout.addWidget(self._method_combo)

        self._password_edit = PasswordLineEdit(self)
        self._password_edit.setPlaceholderText(_t("perm.dialog.enter_password", "请输入密码"))
        self._password_edit.setClearButtonEnabled(True)
        self.textLayout.addWidget(self._password_edit)
        self._password_edit.returnPressed.connect(self._on_verify)

        self._status_label = BodyLabel("", self)
        self._status_label.setStyleSheet("color:#d13438; background: transparent;")
        self._status_label.hide()
        self.textLayout.addWidget(self._status_label)

        self.yesButton.clicked.connect(self._on_verify)
        self.cancelButton.clicked.connect(self.reject)
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
        self._clear_error()
        method_id = str(self._method_combo.currentData() or "")
        if not method_id:
            self._set_error(_t("perm.dialog.no_method", "未选择登录方式"))
            return

        payload = {}
        if method_id == "password":
            password = self._password_edit.text()
            if not password:
                self._set_error(_t("perm.dialog.password_required", "请输入密码"))
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
            self._set_error(_t("perm.dialog.password_not_set", "{level} 级密码尚未设置", level=self._required_level.label))
            return
        self._set_error(_t("perm.dialog.failed", "验证失败，请重试"))

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

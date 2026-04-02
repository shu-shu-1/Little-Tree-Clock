"""密码设置对话框 - 分离用户密码和管理员密码设置窗口。"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QWidget
from qfluentwidgets import (
    SubtitleLabel,
    BodyLabel,
    CaptionLabel,
    PasswordLineEdit,
    PrimaryPushButton,
    PushButton,
    InfoBar,
    InfoBarPosition,
)

from app.services.permission_service import PermissionService, AccessLevel
from app.services.i18n_service import I18nService


def _t(key: str, default: str = "", **kwargs) -> str:
    return I18nService.instance().t(key, default, **kwargs)


class _PasswordSetDialog(QDialog):
    """通用密码设置对话框（用于 user 或 admin 级别）。"""

    passwordChanged = Signal()

    def __init__(
        self,
        service: PermissionService,
        level: AccessLevel,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._service = service
        self._level = AccessLevel.from_value(level)
        self._has_existing = service.has_password(self._level)
        self._i18n = I18nService.instance()

        self.setWindowTitle(_t("perm.password.set_title", "设置{level}级密码", level=self._level.label))
        self.setModal(True)
        self.setMinimumWidth(400)

        self._setup_ui()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 16)
        root.setSpacing(12)

        title_text = _t("perm.password.set_title", "设置{level}级密码", level=self._level.label)
        root.addWidget(SubtitleLabel(title_text, self))

        if self._has_existing:
            hint_text = _t("perm.password.has_existing", "已设置过{level}级密码，输入新密码将覆盖原密码。", level=self._level.label)
        else:
            hint_text = _t("perm.password.no_existing", "请输入新的{level}级密码。", level=self._level.label)
        hint = CaptionLabel(hint_text, self)
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #8a8a8a; margin: 0px; padding: 0px;")
        root.addWidget(hint)

        placeholder = _t("perm.password.enter", "输入{level}级密码", level=self._level.label)
        self._password_edit = PasswordLineEdit(self)
        self._password_edit.setPlaceholderText(placeholder)
        self._password_edit.setClearButtonEnabled(True)
        root.addWidget(self._password_edit)

        confirm_placeholder = _t("perm.password.confirm", "再次输入密码以确认")
        self._confirm_edit = PasswordLineEdit(self)
        self._confirm_edit.setPlaceholderText(confirm_placeholder)
        self._confirm_edit.setClearButtonEnabled(True)
        root.addWidget(self._confirm_edit)

        self._status_label = CaptionLabel("", self)
        self._status_label.setStyleSheet("color: #d13438;")
        self._status_label.hide()
        root.addWidget(self._status_label)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self._clear_btn = PushButton(_t("perm.password.clear_btn", "清除密码"), self)
        self._ok_btn = PrimaryPushButton(_t("perm.password.save_btn", "保存"), self)

        btn_row.addWidget(self._clear_btn)
        btn_row.addWidget(self._ok_btn)
        root.addLayout(btn_row)

        self._clear_btn.setVisible(self._has_existing)
        self._clear_btn.clicked.connect(self._on_clear)
        self._ok_btn.clicked.connect(self._on_save)
        self._password_edit.returnPressed.connect(self._on_save)

        self._password_edit.setFocus()

    def _set_error(self, text: str) -> None:
        self._status_label.setText(text)
        self._status_label.show()

    def _clear_error(self) -> None:
        self._status_label.hide()
        self._status_label.setText("")

    def _on_clear(self) -> None:
        self._service.clear_password(self._level)
        cleared_text = _t("perm.password.cleared", "已清除{level}级密码", level=self._level.label)
        InfoBar.success(
            _t("perm.password.set_title", "密码设置", level=self._level.label),
            cleared_text,
            parent=self.window(),
            position=InfoBarPosition.TOP_RIGHT,
            duration=2200,
        )
        self.passwordChanged.emit()
        self.accept()

    def _on_save(self) -> None:
        self._clear_error()
        password = self._password_edit.text()
        confirm = self._confirm_edit.text()

        if not password:
            self._set_error(_t("perm.password.error.empty", "密码不能为空"))
            return

        if len(password) < 4:
            self._set_error(_t("perm.password.error.too_short", "密码长度至少为 4 个字符"))
            return

        if password != confirm:
            self._set_error(_t("perm.password.error.mismatch", "两次输入的密码不一致"))
            return

        ok, msg = self._service.set_password(self._level, password)
        if not ok:
            self._set_error(msg or _t("perm.dialog.failed", "保存失败"))
            return

        saved_text = _t("perm.password.saved", "{level}级密码已保存", level=self._level.label)
        InfoBar.success(
            _t("perm.password.set_title", "密码设置", level=self._level.label),
            saved_text,
            parent=self.window(),
            position=InfoBarPosition.TOP_RIGHT,
            duration=2200,
        )
        self.passwordChanged.emit()
        self.accept()


def set_user_password(parent: QWidget | None = None, service: PermissionService | None = None) -> None:
    """打开用户级密码设置对话框。"""
    if service is None:
        service = PermissionService.instance()
    dlg = _PasswordSetDialog(service, AccessLevel.USER, parent)
    dlg.exec()


def set_admin_password(parent: QWidget | None = None, service: PermissionService | None = None) -> None:
    """打开管理员级密码设置对话框。"""
    if service is None:
        service = PermissionService.instance()
    dlg = _PasswordSetDialog(service, AccessLevel.ADMIN, parent)
    dlg.exec()

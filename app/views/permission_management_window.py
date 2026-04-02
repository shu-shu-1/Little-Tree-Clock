"""独立权限管理窗口（MSFluentWindow）。"""
from __future__ import annotations

from collections import defaultdict

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
)
from qfluentwidgets import (
    MSFluentWindow,
    NavigationItemPosition,
    FluentIcon as FIF,
    SubtitleLabel,
    BodyLabel,
    CaptionLabel,
    CardWidget,
    ComboBox,
    PushButton,
    PrimaryPushButton,
    CheckBox,
    SmoothScrollArea,
    SearchLineEdit,
    SwitchButton,
    InfoBar,
    InfoBarPosition,
)

from app.services.permission_service import PermissionService, AccessLevel
from app.services.i18n_service import I18nService
from app.views.permission_auth_method_config_window import PermissionAuthMethodConfigWindow


def _t(key: str, default: str = "", **kwargs) -> str:
    return I18nService.instance().t(key, default, **kwargs)


def _clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()


class _FeaturePermissionPage(QWidget):
    def __init__(self, service: PermissionService, parent=None):
        super().__init__(parent)
        self._service = service
        self.setObjectName("permissionFeaturesPage")

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(10)

        root.addWidget(SubtitleLabel(_t("perm.features.title", "功能权限分级"), self))
        root.addWidget(CaptionLabel(_t("perm.features.hint", "为每个功能设置最低权限等级。"), self))

        self._search_edit = SearchLineEdit(self)
        self._search_edit.setPlaceholderText(_t("perm.features.search", "搜索功能名、功能 key、分类或描述"))
        self._search_edit.setClearButtonEnabled(True)
        self._search_edit.textChanged.connect(lambda _=None: self.refresh())
        self._search_edit.searchSignal.connect(lambda _text: self.refresh())
        root.addWidget(self._search_edit)

        self._scroll = SmoothScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(self._scroll.Shape.NoFrame)
        self._scroll.enableTransparentBackground()

        self._container = QWidget(self._scroll)
        self._container.setObjectName("permissionFeatureContainer")
        self._container.setStyleSheet("QWidget#permissionFeatureContainer{background: transparent;}")
        self._list_layout = QVBoxLayout(self._container)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(8)
        self._scroll.setWidget(self._container)
        root.addWidget(self._scroll, 1)

        self.refresh()

    def _on_level_changed(self, feature_key: str, combo: ComboBox) -> None:
        level = AccessLevel.from_value(combo.currentData(), default=AccessLevel.NORMAL)
        self._service.set_item_level(feature_key, level)

    def refresh(self) -> None:
        _clear_layout(self._list_layout)

        query = self._search_edit.text().strip().lower()

        by_category = defaultdict(list)
        for item in self._service.list_items():
            if query:
                haystack = " ".join([
                    str(item.category or ""),
                    str(item.name or ""),
                    str(item.key or ""),
                    str(item.description or ""),
                ]).lower()
                if query not in haystack:
                    continue
            by_category[item.category].append(item)

        if not by_category:
            self._list_layout.addWidget(CaptionLabel(_t("perm.features.no_match", "没有匹配的功能权限项。"), self._container))
            self._list_layout.addStretch(1)
            return

        for category in sorted(by_category.keys()):
            self._list_layout.addWidget(SubtitleLabel(category, self._container))
            for item in by_category[category]:
                card = CardWidget(self._container)
                row = QHBoxLayout(card)
                row.setContentsMargins(14, 10, 14, 10)
                row.setSpacing(10)

                text_col = QVBoxLayout()
                name_label = BodyLabel(item.name, card)
                key_label = CaptionLabel(f"{item.key}  ·  {item.description}" if item.description else item.key, card)
                key_label.setStyleSheet("color: #8a8a8a;")
                text_col.addWidget(name_label)
                text_col.addWidget(key_label)

                combo = ComboBox(card)
                combo.addItem(AccessLevel.NORMAL.label, userData=AccessLevel.NORMAL.key)
                combo.addItem(AccessLevel.USER.label, userData=AccessLevel.USER.key)
                combo.addItem(AccessLevel.ADMIN.label, userData=AccessLevel.ADMIN.key)
                current_level = self._service.get_item_level(item.key)
                idx = combo.findData(current_level.key)
                combo.setCurrentIndex(idx if idx >= 0 else 0)
                combo.currentIndexChanged.connect(
                    lambda _=0, k=item.key, c=combo: self._on_level_changed(k, c)
                )

                row.addLayout(text_col, 1)
                row.addWidget(combo)
                self._list_layout.addWidget(card)

        self._list_layout.addStretch(1)


class _AuthMethodPage(QWidget):
    def __init__(self, service: PermissionService, parent=None):
        super().__init__(parent)
        self._service = service
        self.setObjectName("permissionAuthPage")

        self._level_method_checks: dict[str, dict[str, CheckBox]] = {
            AccessLevel.USER.key: {},
            AccessLevel.ADMIN.key: {},
        }
        self._config_windows: list[PermissionAuthMethodConfigWindow] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(10)

        root.addWidget(SubtitleLabel(_t("perm.auth.title", "登录方式与口令"), self))
        root.addWidget(CaptionLabel(_t("perm.auth.hint", "若用户/管理员等级未配置任何登录方式，则该等级功能默认直接可用。"), self))

        self._scroll = SmoothScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(self._scroll.Shape.NoFrame)
        self._scroll.enableTransparentBackground()

        self._container = QWidget(self._scroll)
        self._container.setObjectName("permissionAuthContainer")
        self._container.setStyleSheet("QWidget#permissionAuthContainer{background: transparent;}")
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(12)
        self._scroll.setWidget(self._container)
        root.addWidget(self._scroll, 1)

        self._service.changed.connect(self.refresh)

        self.refresh()

    def _save_methods(self, level: AccessLevel) -> None:
        key = level.key
        checks = self._level_method_checks.get(key, {})
        method_ids = [method_id for method_id, cb in checks.items() if cb.isChecked()]
        self._service.set_enabled_methods_for_level(level, [str(mid) for mid in method_ids if mid])

    def _open_method_config(self, method_id: str) -> None:
        """打开配置窗口（非阻塞）。"""
        spec = self._service.get_auth_method_config_spec(method_id)
        if spec is None:
            InfoBar.info(
                _t("perm.auth.method_no_config", "权限管理"),
                _t("perm.auth.method_no_config", "该登录方式暂无可配置页面"),
                parent=self.window(),
                position=InfoBarPosition.TOP_RIGHT,
                duration=2200,
            )
            return

        win = PermissionAuthMethodConfigWindow(spec, parent=None)
        win.saved.connect(
            lambda: InfoBar.success(
                _t("perm.auth.method_no_config", "权限管理"),
                _t("perm.auth.method_saved", "登录方式配置已保存"),
                parent=self.window(),
                position=InfoBarPosition.TOP_RIGHT,
                duration=2200,
            )
        )
        win.destroyed.connect(lambda *_: self._config_windows.remove(win) if win in self._config_windows else None)
        self._config_windows.append(win)
        win.show()
        win.raise_()
        win.activateWindow()

    def _open_method_config_modal(self, method_id: str) -> bool:
        """打开配置窗口（阻塞），返回是否完成配置。"""
        spec = self._service.get_auth_method_config_spec(method_id)
        if spec is None:
            return True

        win = PermissionAuthMethodConfigWindow(spec, parent=self.window())
        win.saved.connect(
            lambda: InfoBar.success(
                _t("perm.auth.method_no_config", "权限管理"),
                _t("perm.auth.method_saved", "登录方式配置已保存"),
                parent=self.window(),
                position=InfoBarPosition.TOP_RIGHT,
                duration=2200,
            )
        )
        if win.exec() != win.Accepted:
            return False
        return True

    def _on_method_toggled(self, level: AccessLevel, method_id: str, checked: bool) -> None:
        # 需要配置的方法：启用时必须先完成配置
        spec = self._service.get_auth_method_config_spec(method_id)
        if checked and spec is not None:
            # 先尝试完成配置（使用 exec 模式阻塞）
            if not self._open_method_config_modal(method_id):
                # 用户取消配置，回滚 checkbox
                self._revert_checkbox(level, method_id)
                return
            # 配置完成，继续保存启用状态
            self._save_methods(level)
        else:
            self._save_methods(level)

    def _revert_checkbox(self, level: AccessLevel, method_id: str) -> None:
        """回滚复选框到未选中状态。"""
        checks = self._level_method_checks.get(level.key, {})
        check = checks.get(method_id)
        if check is not None:
            check.blockSignals(True)
            check.setChecked(False)
            check.blockSignals(False)

    def _build_level_block(self, level: AccessLevel) -> CardWidget:
        card = CardWidget(self._container)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        layout.addWidget(SubtitleLabel(_t("perm.auth.level_block", "{level} 级", level=level.label), card))

        method_row = QVBoxLayout()
        method_row.setSpacing(8)
        enabled = set(self._service.get_enabled_methods_for_level(level))

        checks: dict[str, CheckBox] = {}
        for method in self._service.list_auth_methods_for_level(level):
            row = QHBoxLayout()
            row.setSpacing(8)

            check = CheckBox(method.display_name, card)
            check.setChecked(method.method_id in enabled)
            row.addWidget(check)

            row.addStretch(1)

            config_btn = PushButton(_t("perm.auth.config_btn", "配置"), card)
            config_btn.setEnabled(self._service.get_auth_method_config_spec(method.method_id) is not None)
            config_btn.clicked.connect(lambda _=False, mid=method.method_id: self._open_method_config(mid))
            row.addWidget(config_btn)

            check.stateChanged.connect(
                lambda state, lvl=level, mid=method.method_id: self._on_method_toggled(
                    lvl,
                    mid,
                    bool(state),
                )
            )

            checks[method.method_id] = check
            method_row.addLayout(row)

        self._level_method_checks[level.key] = checks
        layout.addLayout(method_row)

        hint = CaptionLabel(_t("perm.auth.enabled_hint", "启用后会参与该权限等级的登录验证流程。"), card)
        hint.setStyleSheet("color: #8a8a8a;")
        layout.addWidget(hint)
        return card

    def refresh(self) -> None:
        _clear_layout(self._layout)
        self._layout.addWidget(self._build_level_block(AccessLevel.USER))
        self._layout.addWidget(self._build_level_block(AccessLevel.ADMIN))
        self._layout.addStretch(1)


class _SessionPage(QWidget):
    def __init__(self, service: PermissionService, parent=None):
        super().__init__(parent)
        self._service = service
        self.setObjectName("permissionSessionPage")

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(10)

        root.addWidget(SubtitleLabel(_t("perm.session.title", "当前会话"), self))

        self._level_label = BodyLabel("", self)
        root.addWidget(self._level_label)

        keep_row = QHBoxLayout()
        keep_row.setSpacing(8)
        keep_row.addWidget(BodyLabel(_t("perm.session.keep_login", "保持登录状态"), self))
        keep_row.addStretch(1)
        self._keep_session_switch = SwitchButton(self)
        keep_row.addWidget(self._keep_session_switch)
        root.addLayout(keep_row)

        self._keep_hint = CaptionLabel("", self)
        self._keep_hint.setWordWrap(True)
        root.addWidget(self._keep_hint)

        tip = CaptionLabel(_t("perm.session.tip", '已通过验证的最高等级在当前应用会话内有效，点击"退出登录"可清除。'), self)
        tip.setWordWrap(True)
        root.addWidget(tip)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self._logout_btn = PrimaryPushButton(_t("perm.session.logout", "退出登录"), self)
        btn_row.addWidget(self._logout_btn)
        root.addLayout(btn_row)
        root.addStretch(1)

        self._logout_btn.clicked.connect(self._on_logout)
        self._keep_session_switch.checkedChanged.connect(self._on_keep_session_changed)
        self.refresh()

    def _on_keep_session_changed(self, checked: bool) -> None:
        self._service.set_keep_login_session_enabled(bool(checked))
        self.refresh()
        if checked:
            InfoBar.success(
                _t("perm.auth.method_no_config", "权限管理"),
                _t("perm.session.keep_enabled", "已开启保持登录，会在会话内复用验证结果"),
                parent=self.window(),
                position=InfoBarPosition.TOP_RIGHT,
                duration=2200,
            )
        else:
            InfoBar.warning(
                _t("perm.auth.method_no_config", "权限管理"),
                _t("perm.session.keep_disabled", "已关闭保持登录，每次访问受限功能都需要重新验证"),
                parent=self.window(),
                position=InfoBarPosition.TOP_RIGHT,
                duration=2600,
            )

    def _on_logout(self) -> None:
        self._service.logout()
        self.refresh()
        InfoBar.success(
            _t("perm.auth.method_no_config", "权限管理"),
            _t("perm.session.logout_done", "已退出权限会话"),
            parent=self.window(),
            position=InfoBarPosition.TOP_RIGHT,
            duration=2200,
        )

    def refresh(self) -> None:
        level = self._service.session_level
        self._level_label.setText(_t("perm.session.level", "当前等级：{level}", level=level.label))

        keep_enabled = self._service.keep_login_session_enabled
        self._keep_session_switch.blockSignals(True)
        self._keep_session_switch.setChecked(keep_enabled)
        self._keep_session_switch.blockSignals(False)

        if keep_enabled:
            self._keep_hint.setText(_t("perm.session.keep_on", "开启后：在本次应用会话中，已通过验证的等级会被复用。"))
        else:
            self._keep_hint.setText(_t("perm.session.keep_off", "关闭后：每次访问受限功能都将重新弹出权限验证。"))


class PermissionManagementWindow(MSFluentWindow):
    """独立权限管理主窗口。"""

    def __init__(self, service: PermissionService, parent=None):
        super().__init__(parent)
        self._service = service

        self._feature_page = _FeaturePermissionPage(service, self)
        self._auth_page = _AuthMethodPage(service, self)
        self._session_page = _SessionPage(service, self)

        self.addSubInterface(self._feature_page, FIF.SETTING, _t("perm.features.title", "功能权限"))
        self.addSubInterface(self._auth_page, FIF.CERTIFICATE, _t("perm.auth.title", "登录方式"))
        self.addSubInterface(
            self._session_page,
            FIF.CERTIFICATE,
            _t("perm.session.title", "会话状态"),
            position=NavigationItemPosition.BOTTOM,
        )

        self.resize(980, 720)
        self.setWindowTitle(_t("perm.auth.method_no_config", "权限管理"))

        self._service.registryChanged.connect(self.refresh_all)
        self._service.changed.connect(self.refresh_all)
        self._service.sessionChanged.connect(lambda _=None: self._session_page.refresh())

    def refresh_all(self) -> None:
        self._feature_page.refresh()
        self._auth_page.refresh()
        self._session_page.refresh()

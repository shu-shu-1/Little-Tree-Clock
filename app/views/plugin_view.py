"""插件管理视图"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from PySide6.QtCore import Qt, Slot, QSize, QTimer
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QWidget, QFileDialog, QLabel,
)
from qfluentwidgets import (
    SmoothScrollArea, FluentIcon as FIF, PushButton,
    CardWidget, BodyLabel, CaptionLabel, TitleLabel,
    SwitchButton, InfoBar, InfoBarPosition,
    TransparentPushButton, TransparentToolButton,
    StrongBodyLabel, PrimaryPushButton,
    PrimaryDropDownPushButton, RoundMenu, Action,
    isDarkTheme, qconfig,
)

from app.plugins.plugin_manager import (
    PluginManager, PermissionLevel, PERMISSION_NAMES, _collect_deps, _collect_missing_deps,
)
from app.plugins import PluginMeta, PluginPermission
from app.services.i18n_service import I18nService
from app.views.permission_dialog import (
    InstallPermissionDialog, SysPermissionDialog,
)
from app.views.toast_notification import PermissionToastItem, _PERM_RISK
from app.constants import PLUGINS_DIR

# ──────────────────────── 权限级别展示配置 ──────────────────────── #
_PERM_DISPLAY_COLORS: dict[PermissionLevel | None, str] = {
    PermissionLevel.ALWAYS_ALLOW:  "#27ae60",
    PermissionLevel.ASK_EACH_TIME: "#e67e22",
    PermissionLevel.DENY:          "#e74c3c",
    None:                          "#e67e22",
}


def _perm_label(
    level: PermissionLevel | None,
    *,
    runtime_granted: bool = False,
) -> tuple[str, str]:
    i18n = I18nService.instance()
    if runtime_granted and level != PermissionLevel.ALWAYS_ALLOW:
        return i18n.t("plugin.perm.runtime_allowed", default="本次已允许"), _PERM_DISPLAY_COLORS[PermissionLevel.ALWAYS_ALLOW]
    key = {
        PermissionLevel.ALWAYS_ALLOW: "perm.level.always",
        PermissionLevel.ASK_EACH_TIME: "perm.level.ask",
        PermissionLevel.DENY: "perm.level.deny",
        None: "perm.level.ask",
    }.get(level, "perm.level.ask")
    text = i18n.t(key)
    color = _PERM_DISPLAY_COLORS.get(level, _PERM_DISPLAY_COLORS[None])
    return text, color


def _perm_key_text(perm_key: str | PluginPermission) -> str:
    return perm_key.value if isinstance(perm_key, PluginPermission) else str(perm_key)


_AUDIT_SOURCE_LABELS: dict[str, str] = {
    "startup": "启动审查",
    "runtime": "运行期申请",
    "install": "依赖安装",
    "settings": "手动修改",
}

_AUDIT_DECISION_LABELS: dict[str, str] = {
    "allow_saved": "按已保存策略允许",
    "deny_saved": "按已保存策略拒绝",
    "allow_prompt_always": "已允许并记住",
    "allow_prompt_once": "本次允许",
    "deny_prompt": "已拒绝",
    "allow_no_callback": "无界面回调，已自动允许",
    "allow_cached": "当前会话已允许",
    "deny_unloaded": "插件未加载，申请被拒绝",
    "deny_unsupported": "当前流程不支持该申请",
    "deny_undeclared": "未声明该权限，申请被拒绝",
    "set_always": "已改为始终允许",
    "set_ask": "已改为每次询问",
    "set_deny": "已改为始终拒绝",
}

_AUDIT_DECISION_COLORS: dict[str, str] = {
    "allow_saved": "#27ae60",
    "allow_prompt_always": "#27ae60",
    "allow_no_callback": "#27ae60",
    "allow_cached": "#27ae60",
    "set_always": "#27ae60",
    "allow_prompt_once": "#e67e22",
    "set_ask": "#e67e22",
    "deny_saved": "#e74c3c",
    "deny_prompt": "#e74c3c",
    "deny_unloaded": "#e74c3c",
    "deny_unsupported": "#e74c3c",
    "deny_undeclared": "#e74c3c",
    "set_deny": "#e74c3c",
}


def _format_audit_time(raw: str) -> str:
    if not raw:
        return "--"
    return raw.replace("T", " ", 1)[:16]


def _format_audit_entry(entry: dict) -> tuple[str, str, str]:
    when = _format_audit_time(str(entry.get("timestamp", "")))
    source = _AUDIT_SOURCE_LABELS.get(str(entry.get("source", "")), "权限记录")
    decision_key = str(entry.get("decision", ""))
    decision = _AUDIT_DECISION_LABELS.get(decision_key, decision_key or "已记录")
    perm_key = str(entry.get("permission", ""))
    perm_name = PERMISSION_NAMES.get(perm_key, perm_key or "未知权限")
    summary = f"{when} · {source} · {perm_name}：{decision}"

    details: list[str] = []
    detail_value = entry.get("details")
    if detail_value not in (None, "", [], {}):
        if isinstance(detail_value, str):
            details.append(f"详情：{detail_value}")
        else:
            details.append(f"详情：{json.dumps(detail_value, ensure_ascii=False)}")
    reason = str(entry.get("reason") or "").strip()
    if reason:
        details.append(f"原因：{reason}")

    return summary, "\n".join(details), _AUDIT_DECISION_COLORS.get(decision_key, "")


# ─────────── 系统权限的图标映射 ─────────── #
_PERM_ICONS: dict[str, str] = {
    PluginPermission.NETWORK:      "🌐",
    PluginPermission.FS_READ:      "📂",
    PluginPermission.FS_WRITE:     "✏️",
    PluginPermission.OS_EXEC:      "⚙️",
    PluginPermission.OS_ENV:       "🔑",
    PluginPermission.CLIPBOARD:    "📋",
    PluginPermission.NOTIFICATION: "🔔",
    PluginPermission.INSTALL_PKG:  "📦",
}


class PluginCard(CardWidget):
    def __init__(
        self,
        meta: PluginMeta,
        enabled: bool,
        reloadable: bool,
        error: str | None,
        dep_warning: str | None,
        deps: list[str],
        missing_deps: list[str],
        sys_perms: dict[str, PermissionLevel],
        runtime_perms: set[str],
        audit_entries: list[dict],
        parent=None,
    ):
        super().__init__(parent)
        self._meta      = meta
        self._deps      = deps
        self._missing_deps = missing_deps
        self._sys_perms = sys_perms
        self._runtime_perms = set(runtime_perms)
        # {perm_key: CaptionLabel}
        self._sys_perm_lbls: dict[str, CaptionLabel] = {}
        self._sys_perm_btns: dict[str, TransparentPushButton] = {}
        self._i18n = I18nService.instance()
        lang = self._i18n.language

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(4)

        # ── 顶行：名称 + 版本 + 开关 ──
        top_row = QHBoxLayout()
        info = QVBoxLayout()

        name_row = QHBoxLayout()
        name_lbl = BodyLabel(meta.get_name(lang))
        ver_lbl  = CaptionLabel(f" v{meta.version}")
        name_row.addWidget(name_lbl)
        name_row.addWidget(ver_lbl)
        name_row.addStretch()

        desc_lbl   = CaptionLabel(meta.get_description(lang) or self._i18n.t("plugin.no_desc"))
        author_lbl = CaptionLabel(self._i18n.t("plugin.author", author=meta.author) if meta.author else "")

        info.addLayout(name_row)
        info.addWidget(desc_lbl)
        if meta.author:
            info.addWidget(author_lbl)

        self.reload_btn = TransparentPushButton(self._i18n.t("plugin.reload.one", default="热重载"))
        self.reload_btn.setFixedHeight(28)
        self.reload_btn.setEnabled(reloadable)
        self.reload_btn.setToolTip(
            self._i18n.t(
                "plugin.reload.disabled",
                default="插件已禁用，请先启用后再热重载",
            ) if not reloadable else self._i18n.t("plugin.reload.one", default="热重载")
        )

        self.switch = SwitchButton()
        self.switch.setChecked(enabled)

        top_row.addLayout(info, 1)
        top_row.addWidget(self.reload_btn)
        top_row.addWidget(self.switch)
        outer.addLayout(top_row)

        # ── 依赖库安装状态展示（仅有依赖时显示）──
        if deps:
            missing_set = set(missing_deps)
            # 标题行
            deps_header = CaptionLabel(f"📦 {self._i18n.t('plugin.deps.label', default='依赖库：')}")
            outer.addWidget(deps_header)
            for dep in deps:
                installed = dep not in missing_set
                icon   = "✅" if installed else "⚠️"
                status = self._i18n.t("plugin.deps.installed", default="已安装") if installed \
                         else self._i18n.t("plugin.deps.missing", default="未安装")
                dep_lbl = CaptionLabel(f"  {icon} {dep}  [{status}]")
                if not installed:
                    dep_lbl.setStyleSheet("color: #e67e22;")
                outer.addWidget(dep_lbl)

        # ── 系统权限行（依据 meta.permissions 列表）──
        declared_sys = [
            p for p in meta.permissions
            if p != PluginPermission.INSTALL_PKG
        ]
        for perm_key in declared_sys:
            icon   = _PERM_ICONS.get(perm_key, "🔒")
            name   = PERMISSION_NAMES.get(perm_key, perm_key)
            saved  = sys_perms.get(perm_key)
            lbl, btn = self._make_perm_row(
                f"{icon} {name}：",
                saved,
                outer,
                runtime_granted=(_perm_key_text(perm_key) in self._runtime_perms),
                is_pkg=False,
            )
            self._sys_perm_lbls[perm_key] = lbl
            self._sys_perm_btns[perm_key] = btn

        if audit_entries:
            audit_title = CaptionLabel(
                f"🧾 {self._i18n.t('plugin.perm.audit.title', default='最近权限记录：')}"
            )
            outer.addWidget(audit_title)
            for audit in audit_entries[:3]:
                text, tooltip, color = _format_audit_entry(audit)
                audit_lbl = CaptionLabel(f"  • {text}")
                audit_lbl.setWordWrap(True)
                if color:
                    audit_lbl.setStyleSheet(f"color: {color};")
                if tooltip:
                    audit_lbl.setToolTip(tooltip)
                outer.addWidget(audit_lbl)

        # ── 依赖警告（依赖安装失败/被拒绝，插件仍运行）──
        if dep_warning:
            dep_lbl = CaptionLabel(f"⚠️ {dep_warning}")
            dep_lbl.setStyleSheet("color: #e67e22;")
            dep_lbl.setWordWrap(True)
            outer.addWidget(dep_lbl)

        # ── 错误提示（on_load 失败等致命错误，插件未运行）──
        if error:
            err_lbl = CaptionLabel(f"❌ {error}")
            err_lbl.setStyleSheet("color: #e74c3c;")
            err_lbl.setWordWrap(True)
            outer.addWidget(err_lbl)
            self.setToolTip(f"错误：{error}")

    # ------------------------------------------------------------------ #

    def _make_perm_row(
        self,
        label_text: str,
        level: PermissionLevel | None,
        parent_layout: QVBoxLayout,
        *,
        runtime_granted: bool = False,
        is_pkg: bool = False,
    ) -> tuple[CaptionLabel, TransparentPushButton]:
        row = QHBoxLayout()
        row.setContentsMargins(0, 2, 0, 0)
        row.setSpacing(6)

        icon_lbl = CaptionLabel(label_text)
        status_lbl = CaptionLabel("")
        _apply_perm_style(status_lbl, level, runtime_granted=runtime_granted)

        row.addWidget(icon_lbl)
        row.addWidget(status_lbl)
        row.addStretch()

        btn = TransparentPushButton("更改")
        btn.setText(self._i18n.t("plugin.perm.change"))
        btn.setFixedHeight(22)
        row.addWidget(btn)

        parent_layout.addLayout(row)
        return status_lbl, btn

    # ------------------------------------------------------------------ #

    def sys_perm_button(self, perm_key: str) -> TransparentPushButton | None:
        return self._sys_perm_btns.get(perm_key)

    def reload_button(self) -> TransparentPushButton:
        return self.reload_btn


def _apply_perm_style(
    lbl: CaptionLabel,
    level: PermissionLevel | None,
    *,
    runtime_granted: bool = False,
) -> None:
    text, color = _perm_label(level, runtime_granted=runtime_granted)
    lbl.setText(text)
    lbl.setStyleSheet(f"color: {color}; font-weight: bold;")


# ────────────────────── 安全警告横幅 ────────────────────── #

class SecurityBanner(CardWidget):
    """插件界面顶部的可关闭安全警告横幅。

    首次显示，点击「不再提示」后永久隐藏（写入 ui_prefs.json）。
    """

    _PREFS_PATH = Path(PLUGINS_DIR) / "._data" / "ui_prefs.json"

    @classmethod
    def should_show(cls) -> bool:
        """Return True 当用户没有永久隐藏该横幅时。"""
        try:
            if cls._PREFS_PATH.exists():
                prefs = json.loads(
                    cls._PREFS_PATH.read_text(encoding="utf-8")
                )
                return not prefs.get("plugin_security_banner_dismissed", False)
        except Exception:
            pass
        return True

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("securityBanner")
        self._build_ui()
        self._apply_theme()
        qconfig.themeChangedFinished.connect(self._apply_theme)

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 14)
        outer.setSpacing(8)

        main_row = QHBoxLayout()
        main_row.setSpacing(12)

        icon_lbl = QLabel("🛡️")
        icon_lbl.setFixedWidth(32)
        icon_lbl.setStyleSheet("font-size: 22px;")
        main_row.addWidget(icon_lbl)

        text_col = QVBoxLayout()
        text_col.setSpacing(4)

        i18n = I18nService.instance()
        self._title_lbl = StrongBodyLabel(i18n.t("plugin.security.title"))
        self._title_lbl.setStyleSheet("font-size: 15px;")

        self._desc_lbl = BodyLabel(i18n.t("plugin.security.desc"))
        self._desc_lbl.setStyleSheet("font-size: 13px;")
        self._desc_lbl.setWordWrap(True)

        self._detail_lbl = CaptionLabel(i18n.t(
            "plugin.security.detail",
            default="已支持运行期权限申请、宿主敏感服务过滤、模块卸载清理和权限审计；但这仍是软隔离而非强沙箱。请仅安装可信来源插件。",
        ))
        self._detail_lbl.setWordWrap(True)

        text_col.addWidget(self._title_lbl)
        text_col.addWidget(self._desc_lbl)
        text_col.addWidget(self._detail_lbl)
        main_row.addLayout(text_col, 1)

        btn_col = QHBoxLayout()
        btn_col.setSpacing(4)
        btn_col.setContentsMargins(0, 0, 0, 0)

        dismiss_btn = TransparentPushButton(i18n.t("plugin.security.dismiss"))
        dismiss_btn.setFixedHeight(28)
        dismiss_btn.setMinimumWidth(132)
        dismiss_btn.clicked.connect(self._on_dismiss_forever)

        self._close_btn = TransparentToolButton()
        self._close_btn.setObjectName("closeBtn")
        self._close_btn.setIcon(FIF.CLOSE)
        self._close_btn.setIconSize(QSize(14, 14))
        self._close_btn.setFixedSize(28, 28)
        self._close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close_btn.clicked.connect(self.hide)

        btn_col.addStretch()
        btn_col.addWidget(dismiss_btn)
        btn_col.addWidget(self._close_btn)

        main_row.addLayout(btn_col)
        outer.addLayout(main_row)

    def _apply_theme(self) -> None:
        dark = isDarkTheme()
        if dark:
            bg      = "rgba(56, 42, 0, 100)"
            border  = "rgba(252, 185, 0, 40)"
            title_c = "#fcb900"
            desc_c  = "#b0b0b0"
            close_btn_icon = "#bbbbbb"
        else:
            bg      = "rgba(255, 248, 220, 100)"
            border  = "rgba(218, 165, 32, 60)"
            title_c = "#9d5d00"
            desc_c  = "#5a5a5a"
            close_btn_icon = "#666666"

        self.setStyleSheet(
            "#securityBanner {"
            f"  background: {bg};"
            f"  border: 1px solid {border};"
            "  border-radius: 10px;"
            "}"
        )
        self._title_lbl.setStyleSheet(
            f"color: {title_c}; font-weight: bold; font-size: 15px;"
        )
        self._desc_lbl.setStyleSheet(
            f"color: {desc_c}; font-size: 13px;"
        )
        self._detail_lbl.setStyleSheet(
            f"color: {desc_c}; font-size: 12px;"
        )
        self._close_btn.setStyleSheet(f"color: {close_btn_icon};")

    def _on_dismiss_forever(self) -> None:
        """永久隐藏横幅，将偏好写入 ui_prefs.json。"""
        try:
            self._PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
            prefs: dict = {}
            if self._PREFS_PATH.exists():
                try:
                    prefs = json.loads(
                        self._PREFS_PATH.read_text(encoding="utf-8")
                    )
                except Exception:
                    pass
            prefs["plugin_security_banner_dismissed"] = True
            self._PREFS_PATH.write_text(
                json.dumps(prefs, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass
        self.hide()


# ──────────────────────────────────────────────────────────────────── #

class PluginView(SmoothScrollArea):
    def __init__(self, plugin_manager: PluginManager, toast_mgr=None,
                 safe_mode: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("pluginView")
        self._mgr = plugin_manager
        self._toast_mgr = toast_mgr
        self._safe_mode = safe_mode
        self._i18n = I18nService.instance()

        # 注册权限回调
        plugin_manager.set_permission_callback(self._on_pkg_perm_request)
        plugin_manager.set_sys_permission_callback(self._on_sys_perm_request)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(8)

        layout.addWidget(TitleLabel(self._i18n.t("plugin.title")))

        # ── 安全模式提示横幅 ──
        if safe_mode:
            from qfluentwidgets import InfoBar, InfoBarPosition
            safe_banner = CardWidget()
            safe_banner.setObjectName("safeBanner")
            _sb_layout = QHBoxLayout(safe_banner)
            _sb_layout.setContentsMargins(16, 12, 16, 12)
            _icon = QLabel("🛡️")
            _icon.setStyleSheet("font-size: 20px;")
            _msg = BodyLabel(self._i18n.t("boot.safe_mode.plugin_hint",
                             default="安全模式已开启，插件未加载。重开并选择「正常启动」可恢复插件功能。"))
            _msg.setWordWrap(True)
            _sb_layout.addWidget(_icon)
            _sb_layout.addWidget(_msg, 1)
            _sb_layout.addStretch()
            from qfluentwidgets import isDarkTheme, qconfig
            def _apply_safe_theme():
                dark = isDarkTheme()
                safe_banner.setStyleSheet(
                    "#safeBanner{background:%s;border:1px solid %s;border-radius:8px;}" % (
                        ("rgba(30,60,90,110)" if dark else "rgba(220,235,255,120)"),
                        ("rgba(80,140,220,50)" if dark else "rgba(60,120,220,40)"),
                    )
                )
            _apply_safe_theme()
            qconfig.themeChangedFinished.connect(_apply_safe_theme)
            layout.addWidget(safe_banner)

        # ── 安全提示横幅（首次显示）──
        if SecurityBanner.should_show():
            self._banner: SecurityBanner | None = SecurityBanner()
            layout.addWidget(self._banner)
        else:
            self._banner = None

        # ── 工具栏 ──
        bar = QHBoxLayout()

        # 「导入插件」下拉按钮
        import_menu = RoundMenu(parent=self)
        import_menu.addAction(
            Action(FIF.FOLDER, self._i18n.t("plugin.import.from_dir"), triggered=self._on_import_dir)
        )
        import_menu.addAction(
            Action(FIF.ZIP_FOLDER, self._i18n.t("plugin.import.from_zip"), triggered=self._on_import_zip)
        )
        import_btn = PrimaryDropDownPushButton(FIF.DOWN, self._i18n.t("plugin.import"), self)
        import_btn.setMenu(import_menu)

        reload_btn = PushButton(FIF.SYNC, self._i18n.t("plugin.rescan"))
        reload_btn.clicked.connect(self._on_reload)
        bar.addStretch()
        bar.addWidget(import_btn)
        bar.addWidget(reload_btn)
        layout.addLayout(bar)

        # ── 空状态提示 ──
        self._empty_lbl = CaptionLabel(self._i18n.t("plugin.empty"))
        self._empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_lbl.hide()

        self._cards_layout = QVBoxLayout()
        self._cards_layout.setSpacing(6)
        layout.addWidget(self._empty_lbl)
        layout.addLayout(self._cards_layout)
        layout.addStretch()

        self.setWidget(container)
        self.setWidgetResizable(True)
        self.enableTransparentBackground()

        self._cards_dirty = True
        self._cards_reload_scheduled = False

        plugin_manager.pluginLoaded.connect(lambda _: self._mark_cards_dirty())
        plugin_manager.pluginUnloaded.connect(lambda _: self._mark_cards_dirty())
        plugin_manager.pluginError.connect(lambda *_: self._mark_cards_dirty())
        plugin_manager.scanCompleted.connect(self._mark_cards_dirty)
        plugin_manager.pluginPermWarn.connect(self._on_perm_warn)
        plugin_manager.pluginRuntimePermissionChanged.connect(lambda *_: self._mark_cards_dirty())
        plugin_manager.pluginPermissionAuditLogged.connect(lambda *_: self._mark_cards_dirty())

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._schedule_cards_reload()

    def _mark_cards_dirty(self) -> None:
        self._cards_dirty = True
        if self.isVisible():
            self._schedule_cards_reload()

    def _schedule_cards_reload(self) -> None:
        if not self._cards_dirty or self._cards_reload_scheduled:
            return
        self._cards_reload_scheduled = True
        QTimer.singleShot(0, self._load_cards_if_needed)

    def _load_cards_if_needed(self) -> None:
        self._cards_reload_scheduled = False
        if not self._cards_dirty:
            return
        if not self.isVisible():
            return
        self._cards_dirty = False
        self._load_cards()

    # ------------------------------------------------------------------ #
    # 权限回调
    # ------------------------------------------------------------------ #

    def _on_pkg_perm_request(
        self,
        plugin_id: str,
        plugin_name: str,
        packages: list[str],
    ) -> PermissionLevel:
        if self._toast_mgr is None:
            return InstallPermissionDialog.ask(plugin_name, packages, self.window())
        # 构造简短的库名摘要
        sep = "、" if self._i18n.language == "zh-CN" else ", "
        pkg_str = sep.join(packages[:3])
        if len(packages) > 3:
            pkg_str += " " + self._i18n.t("plugin.toast.install_req.more", count=len(packages))
        toast = PermissionToastItem(
            self._i18n.t("plugin.toast.install_req.title"),
            self._i18n.t("plugin.toast.install_req.content", plugin=plugin_name, packages=pkg_str),
            install_mode=True,
        )
        self._toast_mgr.add_item(toast)
        result = toast.exec()
        if result == "always":
            return PermissionLevel.ALWAYS_ALLOW
        elif result == "once":
            return PermissionLevel.ASK_EACH_TIME
        else:
            return PermissionLevel.DENY

    def _on_sys_perm_request(
        self,
        plugin_id: str,
        plugin_name: str,
        perm_key: str,
        perm_display: str,
        reason: str = "",
    ) -> PermissionLevel:
        if self._toast_mgr is None:
            return SysPermissionDialog.ask(plugin_name, perm_key, perm_display, self.window(), reason=reason)
        icon = _PERM_RISK.get(perm_key, ("🔒",))[0]
        extra = f"\n{reason}" if reason else ""
        toast = PermissionToastItem(
            self._i18n.t("plugin.toast.sys_req.title", icon=icon),
            self._i18n.t("plugin.toast.sys_req.content", plugin=plugin_name, perm=perm_display) + extra,
        )
        self._toast_mgr.add_item(toast)
        result = toast.exec()
        if result == "always":
            return PermissionLevel.ALWAYS_ALLOW
        elif result == "once":
            return PermissionLevel.ASK_EACH_TIME
        else:
            return PermissionLevel.DENY

    # ------------------------------------------------------------------ #

    @Slot(str, str, object)
    def _on_perm_warn(
        self,
        plugin_id: str,
        plugin_name: str,
        undeclared: list,
    ) -> None:
        """接收静态扫描发现的未声明权限信号，展示警告 InfoBar。"""
        names = [self._i18n.t(f"perm.{k}", default=PERMISSION_NAMES.get(k, k)) for k in undeclared]
        InfoBar.warning(
            self._i18n.t("plugin.perm.scan_warn.title"),
            self._i18n.t("plugin.perm.scan_warn.content", plugin=plugin_name, names=", ".join(names)),
            parent=self.window(),
            position=InfoBarPosition.TOP_RIGHT,
            duration=7000,
        )

    # ------------------------------------------------------------------ #

    def _load_cards(self) -> None:
        while self._cards_layout.count():
            item = self._cards_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        known = self._mgr.all_known_plugins()
        if not known:
            self._empty_lbl.show()
            return
        self._empty_lbl.hide()

        for meta, enabled, error, dep_warning in known:
            lang = self._i18n.language
            plugin_path = Path(PLUGINS_DIR) / meta.id
            deps: list[str] = []
            missing_deps: list[str] = []
            reloadable = not self._mgr.is_disabled(meta.id)
            if plugin_path.is_dir():
                deps = _collect_deps(plugin_path)
                missing_deps = _collect_missing_deps(plugin_path)

            sys_perms = self._mgr.get_sys_permissions(meta.id)
            runtime_perms = self._mgr.get_runtime_permissions(meta.id)
            audit_entries = self._mgr.get_permission_audit_entries(meta.id, limit=3)

            card = PluginCard(
                meta,
                enabled,
                reloadable,
                error,
                dep_warning,
                deps,
                missing_deps,
                sys_perms,
                runtime_perms,
                audit_entries,
            )
            card.switch.checkedChanged.connect(
                lambda checked, pid=meta.id: self._mgr.set_enabled(pid, checked)
            )
            card.reload_button().clicked.connect(
                lambda _, pid=meta.id, pname=meta.get_name(lang): self._reload_plugin(pid, pname)
            )


            # 系统权限（每个 key 一个按钮）
            for perm_key in [p for p in meta.permissions if p != PluginPermission.INSTALL_PKG]:
                btn = card.sys_perm_button(perm_key)
                if btn is not None:
                    btn.clicked.connect(
                        lambda _, pid=meta.id, pname=meta.get_name(lang), pk=perm_key:
                            self._change_sys_perm(pid, pname, pk)
                    )

            self._cards_layout.addWidget(card)

    # ------------------------------------------------------------------ #

    def _change_sys_perm(self, pid: str, pname: str, perm_key: str) -> None:
        perm_display = self._i18n.t(f"perm.{perm_key}", default=PERMISSION_NAMES.get(perm_key, perm_key))
        level = SysPermissionDialog.ask(pname, perm_key, perm_display, self.window())
        self._mgr.set_sys_permission(pid, perm_key, level)
        text, _ = _perm_label(level)
        InfoBar.success(self._i18n.t("plugin.perm.updated"),
                self._i18n.t("plugin.perm.updated.sys", plugin=pname, perm=perm_display, level=text),
                        parent=self.window(),
                        position=InfoBarPosition.TOP_RIGHT, duration=2500)
        self._load_cards()

    def _reload_plugin(self, plugin_id: str, plugin_name: str) -> None:
        ok, message, _reloaded_ids, failed_ids = self._mgr.reload_plugin(plugin_id)
        self._load_cards()
        if ok and failed_ids:
            InfoBar.warning(
                self._i18n.t("plugin.reload.one", default="热重载"),
                message,
                parent=self.window(),
                position=InfoBarPosition.TOP_RIGHT,
                duration=5000,
            )
            return
        if ok:
            InfoBar.success(
                self._i18n.t("plugin.reload.one", default="热重载"),
                message,
                parent=self.window(),
                position=InfoBarPosition.TOP_RIGHT,
                duration=2500,
            )
            return
        InfoBar.error(
            self._i18n.t("plugin.reload.one", default="热重载"),
            message or self._i18n.t("plugin.reload.fail", default=f"「{plugin_name}」热重载失败"),
            parent=self.window(),
            position=InfoBarPosition.TOP_RIGHT,
            duration=5000,
        )

    # ------------------------------------------------------------------ #
    # 导入插件
    # ------------------------------------------------------------------ #

    def _do_import(self, paths: list[str]) -> None:
        """执行实际导入逻辑，paths 为文件/目录路径列表。"""
        if not paths:
            return
        ok_count  = 0
        fail_msgs: list[str] = []
        for p in paths:
            ok, msg = self._mgr.import_plugin(Path(p))
            if ok:
                ok_count += 1
            else:
                fail_msgs.append(msg)
        if ok_count:
            self._mgr.discover_and_load()
            InfoBar.success(
                self._i18n.t("plugin.import.ok"),
                self._i18n.t("plugin.import.ok_content", count=ok_count),
                parent=self.window(),
                position=InfoBarPosition.TOP_RIGHT,
                duration=3000,
            )
        for msg in fail_msgs:
            InfoBar.error(
                self._i18n.t("plugin.import.fail"), msg,
                parent=self.window(),
                position=InfoBarPosition.TOP_RIGHT,
                duration=4000,
            )

    @Slot()
    def _on_import_zip(self) -> None:
        """从 .zip 插件包导入。"""
        paths, _ = QFileDialog.getOpenFileNames(
            self.window(),
            self._i18n.t("plugin.dialog.choose_zip"),
            "",
            self._i18n.t("plugin.dialog.filter_zip"),
        )
        self._do_import(paths)

    @Slot()
    def _on_import_dir(self) -> None:
        """从文件夹导入插件目录。"""
        dir_path = QFileDialog.getExistingDirectory(
            self.window(),
            self._i18n.t("plugin.dialog.choose_dir"),
            "",
        )
        if dir_path:
            self._do_import([dir_path])

    @Slot()
    def _on_reload(self) -> None:
        self._mgr.discover_and_load()
        self._load_cards()
        InfoBar.success(self._i18n.t("plugin.title"), self._i18n.t("plugin.scan.done"), parent=self.window(),
                        position=InfoBarPosition.TOP_RIGHT, duration=2000)


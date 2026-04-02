"""插件管理视图"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from pathlib import Path

from PySide6.QtCore import Qt, Slot, QTimer, QUrl, QObject, QThread, Signal
from PySide6.QtGui import QColor, QDesktopServices, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QWidget, QFileDialog, QLabel, QStackedWidget,
)
from qfluentwidgets import (
    SmoothScrollArea, FluentIcon as FIF, PushButton,
    CardWidget, BodyLabel, CaptionLabel, TitleLabel,
    SwitchButton, InfoBar, InfoBarIcon, InfoBarPosition,
    TransparentPushButton,
    IconWidget,
    PrimaryPushButton,
    PrimaryDropDownPushButton, RoundMenu, Action,
    LineEdit, SearchLineEdit, ComboBox, CheckBox, Pivot,
    InfoBadge, CommandBar, MessageBox,
    themeColor,
)

from app.plugins.plugin_manager import (
    PluginManager, PermissionLevel, PERMISSION_NAMES,
    PLUGIN_PACKAGE_EXTENSION,
    _collect_deps, _collect_missing_deps,
)
from app.plugins import PluginMeta, PluginPermission
from app.services.permission_service import PermissionService
from app.services.central_control_service import CentralControlService
from app.services.i18n_service import I18nService, LANG_EN_US
from app.utils.fs import write_text_with_uac
from app.utils.logger import logger
from app.views.permission_dialog import (
    InstallPermissionDialog, SysPermissionDialog,
)
from app.views.toast_notification import PermissionToastItem
from app.constants import PLUGINS_DIR, APP_VERSION
from app.services.remote_resource_service import (
    StorePlugin,
    RemoteResourceService,
    compare_versions,
    current_os_key,
    normalize_plugin_lookup_key,
)

# ──────────────────────── 权限级别展示配置 ──────────────────────── #
_PERM_DISPLAY_COLORS: dict[PermissionLevel | None, str] = {
    PermissionLevel.ALWAYS_ALLOW:  "#27ae60",
    PermissionLevel.ASK_EACH_TIME: "#e67e22",
    PermissionLevel.DENY:          "#e74c3c",
    None:                          "#e67e22",
}


def _tr(zh: str, en: str) -> str:
    return en if I18nService.instance().language == LANG_EN_US else zh


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


_AUDIT_SOURCE_LABELS: dict[str, tuple[str, str]] = {
    "startup": ("启动审查", "Startup check"),
    "runtime": ("运行期申请", "Runtime request"),
    "install": ("依赖安装", "Dependency install"),
    "settings": ("手动修改", "Manual update"),
}

_AUDIT_DECISION_LABELS: dict[str, tuple[str, str]] = {
    "allow_saved": ("按已保存策略允许", "Allowed by saved policy"),
    "deny_saved": ("按已保存策略拒绝", "Denied by saved policy"),
    "allow_prompt_always": ("已允许并记住", "Allowed and remembered"),
    "allow_prompt_once": ("本次允许", "Allowed this time"),
    "deny_prompt": ("已拒绝", "Denied"),
    "allow_no_callback": ("无界面回调，已自动允许", "No UI callback, auto-allowed"),
    "allow_cached": ("当前会话已允许", "Allowed in current session"),
    "deny_unloaded": ("插件未加载，申请被拒绝", "Plugin not loaded, request denied"),
    "deny_unsupported": ("当前流程不支持该申请", "Unsupported request in current flow"),
    "deny_undeclared": ("未声明该权限，申请被拒绝", "Permission undeclared, request denied"),
    "set_always": ("已改为始终允许", "Set to always allow"),
    "set_ask": ("已改为每次询问", "Set to ask each time"),
    "set_deny": ("已改为始终拒绝", "Set to always deny"),
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
    i18n = I18nService.instance()
    is_en = i18n.language == LANG_EN_US

    when = _format_audit_time(str(entry.get("timestamp", "")))
    source_pair = _AUDIT_SOURCE_LABELS.get(str(entry.get("source", "")))
    source = source_pair[1] if (source_pair and is_en) else source_pair[0] if source_pair else _tr("权限记录", "Permission record")
    decision_key = str(entry.get("decision", ""))
    decision_pair = _AUDIT_DECISION_LABELS.get(decision_key)
    decision = decision_pair[1] if (decision_pair and is_en) else decision_pair[0] if decision_pair else (decision_key or _tr("已记录", "Recorded"))
    perm_key = str(entry.get("permission", ""))
    perm_name = i18n.t(f"perm.{perm_key}", default=PERMISSION_NAMES.get(perm_key, perm_key or _tr("未知权限", "Unknown Permission")))
    summary = _tr(
        f"{when} · {source} · {perm_name}：{decision}",
        f"{when} · {source} · {perm_name}: {decision}",
    )

    details: list[str] = []
    detail_value = entry.get("details")
    if detail_value not in (None, "", [], {}):
        if isinstance(detail_value, str):
            details.append(_tr(f"详情：{detail_value}", f"Details: {detail_value}"))
        else:
            details.append(_tr(
                f"详情：{json.dumps(detail_value, ensure_ascii=False)}",
                f"Details: {json.dumps(detail_value, ensure_ascii=False)}",
            ))
    reason = str(entry.get("reason") or "").strip()
    if reason:
        details.append(_tr(f"原因：{reason}", f"Reason: {reason}"))

    return summary, "\n".join(details), _AUDIT_DECISION_COLORS.get(decision_key, "")


# ─────────── 系统权限的图标映射 ─────────── #
_PERM_ICONS: dict[str, FIF] = {
    PluginPermission.NETWORK:      FIF.GLOBE,
    PluginPermission.FS_READ:      FIF.FOLDER,
    PluginPermission.FS_WRITE:     FIF.EDIT,
    PluginPermission.OS_EXEC:      FIF.SETTING,
    PluginPermission.OS_ENV:       FIF.CERTIFICATE,
    PluginPermission.CLIPBOARD:    FIF.DOCUMENT,
    PluginPermission.NOTIFICATION: FIF.RINGER,
    PluginPermission.INSTALL_PKG:  FIF.DOWNLOAD,
}


def _plugin_initial_text(meta: PluginMeta, language: str) -> str:
    raw = (meta.get_name(language) or meta.name or meta.id or "?").strip()
    first = next((ch for ch in raw if not ch.isspace()), "?")
    if "a" <= first <= "z" or "A" <= first <= "Z":
        return first.upper()
    return first


def _avatar_text_color(bg: QColor) -> str:
    # YIQ 对比度公式：亮背景用深色字，暗背景用白字。
    yiq = (bg.red() * 299 + bg.green() * 587 + bg.blue() * 114) / 1000
    return "#0f172a" if yiq >= 160 else "#ffffff"


def _create_tag_badge(tag: str) -> InfoBadge:
    return InfoBadge.custom(str(tag), "#1f6feb", "#eaf2ff")


def _decode_base64_icon_payload(icon_spec: str) -> bytes | None:
    text = str(icon_spec or "").strip()
    if not text:
        return None

    payload = text
    lower = text.lower()
    if lower.startswith("data:image/"):
        marker = ";base64,"
        idx = lower.find(marker)
        if idx < 0:
            return None
        payload = text[idx + len(marker):].strip()
    else:
        compact = text.replace("\r", "").replace("\n", "").replace(" ", "")
        if len(compact) < 64 or not re.fullmatch(r"[A-Za-z0-9+/=]+", compact):
            return None
        payload = compact

    if not payload:
        return None

    padding = (-len(payload)) % 4
    if padding:
        payload += "=" * padding

    try:
        return base64.b64decode(payload, validate=False)
    except (binascii.Error, ValueError):
        return None


def _rounded_square_pixmap(source: QPixmap, size: int, radius: int = 8) -> QPixmap:
    scaled = source.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    target = QPixmap(size, size)
    target.fill(Qt.GlobalColor.transparent)

    painter = QPainter(target)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    clip = QPainterPath()
    clip.addRoundedRect(0.0, 0.0, float(size), float(size), float(radius), float(radius))
    painter.setClipPath(clip)
    painter.drawPixmap(0, 0, scaled)
    painter.end()
    return target


def _load_plugin_icon_pixmap(meta: PluginMeta, *, size: int = 40) -> QPixmap | None:
    icon_spec = str(getattr(meta, "icon", "") or "").strip()
    if not icon_spec:
        return None

    payload = _decode_base64_icon_payload(icon_spec)
    if payload:
        pixmap = QPixmap()
        if pixmap.loadFromData(payload):
            return _rounded_square_pixmap(pixmap, size)

    try:
        icon_path = Path(icon_spec).expanduser()
    except Exception:
        return None

    candidates: list[Path] = []
    if icon_path.is_absolute():
        candidates.append(icon_path)
    else:
        candidates.append(icon_path)
        candidates.append((Path(PLUGINS_DIR) / meta.id / icon_path).resolve(strict=False))

    for candidate in candidates:
        try:
            if not candidate.is_file():
                continue
            pixmap = QPixmap(str(candidate))
            if not pixmap.isNull():
                return _rounded_square_pixmap(pixmap, size)
        except OSError:
            continue

    return None


def _build_plugin_avatar_label(
    meta: PluginMeta,
    *,
    language: str,
    parent: QWidget | None = None,
) -> QLabel:
    label = QLabel(parent)
    label.setFixedSize(40, 40)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)

    pixmap = _load_plugin_icon_pixmap(meta, size=40)
    if pixmap is not None and not pixmap.isNull():
        label.setPixmap(pixmap)
        label.setStyleSheet("background: transparent; border-radius: 8px;")
        return label

    bg = themeColor()
    label.setText(_plugin_initial_text(meta, language))
    label.setStyleSheet(
        f"background: {bg.name()};"
        "border-radius: 8px;"
        f"color: {_avatar_text_color(bg)};"
        "font-size: 18px;"
        "font-weight: 700;"
    )
    return label


def _store_plugin_initial_text(plugin: StorePlugin, language: str) -> str:
    raw = (plugin.display_name(language) or plugin.stable_id or "?").strip()
    first = next((ch for ch in raw if not ch.isspace()), "?")
    if "a" <= first <= "z" or "A" <= first <= "Z":
        return first.upper()
    return first


def _store_icon_source_key(icon_spec: str) -> str:
    text = str(icon_spec or "").strip()
    if not text:
        return ""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


_SECURITY_PREFS_PATH = Path(PLUGINS_DIR) / "._data" / "ui_prefs.json"


def _should_show_plugin_security_notice() -> bool:
    try:
        if _SECURITY_PREFS_PATH.exists():
            prefs = json.loads(_SECURITY_PREFS_PATH.read_text(encoding="utf-8"))
            return not prefs.get("plugin_security_banner_dismissed", False)
    except Exception:
        pass
    return True


def _set_plugin_security_notice_dismissed() -> None:
    try:
        prefs: dict = {}
        if _SECURITY_PREFS_PATH.exists():
            try:
                prefs = json.loads(_SECURITY_PREFS_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass
        prefs["plugin_security_banner_dismissed"] = True
        write_text_with_uac(
            _SECURITY_PREFS_PATH,
            json.dumps(prefs, ensure_ascii=False, indent=2),
            encoding="utf-8",
            ensure_parent=True,
        )
    except Exception:
        pass


def _load_store_icon_bytes(icon_spec: str) -> bytes | None:
    text = str(icon_spec or "").strip()
    if not text:
        return None

    payload = _decode_base64_icon_payload(text)
    if payload:
        return payload

    lower = text.lower()
    if lower.startswith("http://") or lower.startswith("https://"):
        session = RemoteResourceService._build_session()
        try:
            resp = session.get(text, timeout=(5, 12))
            resp.raise_for_status()
            content = resp.content
            if not content or len(content) > 2 * 1024 * 1024:
                return None
            return content
        except Exception:
            return None
        finally:
            try:
                session.close()
            except Exception:
                pass

    try:
        path = Path(text).expanduser()
        if path.is_file():
            return path.read_bytes()
    except OSError:
        return None

    return None


class _StoreIconWorker(QObject):
    """后台加载商店图标内容。"""

    finished = Signal(str, str, object)
    failed = Signal(str, str)

    def __init__(self, plugin_id: str, source_key: str, icon_spec: str):
        super().__init__()
        self._plugin_id = plugin_id
        self._source_key = source_key
        self._icon_spec = icon_spec

    @Slot()
    def run(self) -> None:
        try:
            payload = _load_store_icon_bytes(self._icon_spec)
        except Exception:
            logger.exception("商店图标加载异常: {}", self._plugin_id)
            self.failed.emit(self._plugin_id, self._source_key)
            return
        self.finished.emit(self._plugin_id, self._source_key, payload)


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
        *,
        selection_mode: bool = False,
        selected: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self._sys_perm_lbls: dict[str, CaptionLabel] = {}
        self._sys_perm_btns: dict[str, TransparentPushButton] = {}
        self._selector: CheckBox | None = None
        self._delete_btn: PushButton | None = None
        self._i18n = I18nService.instance()
        lang = self._i18n.language
        declared_sys = [
            p for p in meta.permissions
            if p != PluginPermission.INSTALL_PKG
        ]

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(6)

        top_row = QHBoxLayout()
        top_row.setSpacing(10)
        avatar = _build_plugin_avatar_label(meta, language=lang, parent=self)

        info = QVBoxLayout()
        info.setSpacing(3)

        name_row = QHBoxLayout()
        name_row.setSpacing(6)
        name_lbl = BodyLabel(meta.get_name(lang))
        ver_lbl = CaptionLabel(f"v{meta.version}")
        name_row.addWidget(name_lbl)
        name_row.addWidget(ver_lbl)
        name_row.addStretch()

        desc_lbl = CaptionLabel(meta.get_description(lang) or self._i18n.t("plugin.no_desc"))
        desc_lbl.setWordWrap(True)
        author_lbl = CaptionLabel(self._i18n.t("plugin.author", author=meta.author) if meta.author else "")

        info.addLayout(name_row)
        info.addWidget(desc_lbl)
        if meta.author:
            info.addWidget(author_lbl)

        if meta.tags:
            tags_row = QHBoxLayout()
            tags_row.setSpacing(6)
            tags_row.addWidget(CaptionLabel(self._i18n.t("plugin.tags", default="标签：")))
            for tag in meta.tags:
                tags_row.addWidget(_create_tag_badge(tag))
            tags_row.addStretch()
            info.addLayout(tags_row)

        self.reload_btn = TransparentPushButton(FIF.SYNC, self._i18n.t("plugin.reload.one", default="热重载"))
        self.reload_btn.setFixedHeight(28)
        self.reload_btn.setEnabled(reloadable)
        self.reload_btn.setToolTip(
            self._i18n.t(
                "plugin.reload.disabled",
                default="插件已禁用，请先启用后再热重载",
            ) if not reloadable else self._i18n.t("plugin.reload.one", default="热重载")
        )

        self._expand_btn = TransparentPushButton(FIF.DOWN, "", self)
        self._expand_btn.setFixedHeight(28)
        self._expand_btn.clicked.connect(self._toggle_detail)

        self.switch = SwitchButton()
        self.switch.setChecked(enabled)

        top_row.addWidget(avatar, 0, Qt.AlignmentFlag.AlignTop)
        if selection_mode:
            selector = CheckBox(self)
            selector.setText("")
            selector.setChecked(selected)
            selector.setToolTip(self._i18n.t("plugin.select.one", default="选择此插件"))
            selector.setFixedWidth(10)
            self._selector = selector
            top_row.addWidget(selector, 0, Qt.AlignmentFlag.AlignTop)

        top_row.addLayout(info, 1)

        action_row = QHBoxLayout()
        action_row.setSpacing(4)
        action_row.addWidget(self.reload_btn)
        action_row.addWidget(self._expand_btn)
        action_row.addWidget(self.switch)
        top_row.addLayout(action_row)
        outer.addLayout(top_row)

        summary_row = QHBoxLayout()
        summary_row.setSpacing(8)
        if deps:
            missing_count = len(missing_deps)
            self._append_summary(
                summary_row,
                FIF.DOWNLOAD,
                self._i18n.t(
                    "plugin.card.summary.deps",
                    default="依赖 {total}（缺失 {missing}）",
                    total=len(deps),
                    missing=missing_count,
                ),
                color="#e67e22" if missing_count else "",
            )
        if declared_sys:
            self._append_summary(
                summary_row,
                FIF.CERTIFICATE,
                self._i18n.t(
                    "plugin.card.summary.permissions",
                    default="权限 {count}",
                    count=len(declared_sys),
                ),
            )
        if audit_entries:
            self._append_summary(
                summary_row,
                FIF.DOCUMENT,
                self._i18n.t(
                    "plugin.card.summary.audit",
                    default="审计记录 {count}",
                    count=min(3, len(audit_entries)),
                ),
            )
        if dep_warning:
            self._append_summary(
                summary_row,
                FIF.INFO,
                self._i18n.t("plugin.card.summary.warning", default="依赖警告"),
                color="#e67e22",
            )
        if error:
            self._append_summary(
                summary_row,
                FIF.CLOSE,
                self._i18n.t("plugin.card.summary.error", default="加载错误"),
                color="#e74c3c",
            )
        summary_row.addStretch()
        outer.addLayout(summary_row)

        self._detail_widget = QWidget(self)
        self._detail_widget.setVisible(False)
        detail_layout = QVBoxLayout(self._detail_widget)
        detail_layout.setContentsMargins(0, 4, 0, 0)
        detail_layout.setSpacing(8)

        if deps:
            self._add_section_title(
                detail_layout,
                FIF.DOWNLOAD,
                self._i18n.t("plugin.deps.label", default="依赖"),
            )
            missing_set = set(missing_deps)
            for dep in deps:
                installed = dep not in missing_set
                status = self._i18n.t("plugin.deps.installed", default="已安装") if installed else self._i18n.t("plugin.deps.missing", default="缺失")
                dep_lbl = self._add_detail_text_row(
                    detail_layout,
                    FIF.ACCEPT if installed else FIF.INFO,
                    f"{dep}  [{status}]",
                    color="" if installed else "#e67e22",
                )
                if not installed:
                    dep_lbl.setToolTip(self._i18n.t("plugin.deps.missing", default="缺失"))

        if declared_sys:
            self._add_section_title(
                detail_layout,
                FIF.CERTIFICATE,
                self._i18n.t("plugin.card.section.permissions", default="系统权限"),
            )
            for perm_key in declared_sys:
                icon = _PERM_ICONS.get(perm_key, FIF.CERTIFICATE)
                name = PERMISSION_NAMES.get(perm_key, perm_key)
                saved = sys_perms.get(perm_key)
                lbl, btn = self._make_perm_row(
                    icon,
                    str(name),
                    saved,
                    detail_layout,
                    runtime_granted=(_perm_key_text(perm_key) in runtime_perms),
                )
                self._sys_perm_lbls[perm_key] = lbl
                self._sys_perm_btns[perm_key] = btn

        if audit_entries:
            self._add_section_title(
                detail_layout,
                FIF.DOCUMENT,
                self._i18n.t("plugin.perm.audit.title", default="权限审计"),
            )
            for audit in audit_entries[:3]:
                text, tooltip, color = _format_audit_entry(audit)
                audit_lbl = self._add_detail_text_row(
                    detail_layout,
                    FIF.INFO,
                    text,
                    color=color,
                )
                if tooltip:
                    audit_lbl.setToolTip(tooltip)

        if dep_warning:
            self._add_detail_text_row(
                detail_layout,
                FIF.INFO,
                dep_warning,
                color="#e67e22",
            )

        if error:
            self._add_detail_text_row(
                detail_layout,
                FIF.CLOSE,
                error,
                color="#e74c3c",
            )
            self.setToolTip(_tr(f"错误：{error}", f"Error: {error}"))

        self._add_section_title(
            detail_layout,
            FIF.DEVELOPER_TOOLS,
            self._i18n.t("plugin.card.section.actions", default="插件操作"),
        )
        delete_row = QHBoxLayout()
        delete_row.setContentsMargins(0, 0, 0, 0)
        delete_row.setSpacing(6)
        delete_row.addStretch()

        self._delete_btn = PushButton(
            self._i18n.t("plugin.local.delete.one", default="删除插件"),
            self,
        )
        self._delete_btn.setFixedHeight(30)
        self._delete_btn.setToolTip(
            self._i18n.t("plugin.local.delete.tip", default="删除插件（需二次确认）")
        )
        delete_row.addWidget(self._delete_btn)
        detail_layout.addLayout(delete_row)

        outer.addWidget(self._detail_widget)
        self._set_expand_state(False)

    def _append_summary(
        self,
        layout: QHBoxLayout,
        icon,
        text: str,
        *,
        color: str = "",
    ) -> None:
        icon_widget = IconWidget(icon, self)
        icon_widget.setFixedSize(14, 14)
        label = CaptionLabel(text, self)
        if color:
            label.setStyleSheet(f"color: {color};")
        layout.addWidget(icon_widget, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(label, 0, Qt.AlignmentFlag.AlignVCenter)

    def _add_section_title(self, parent_layout: QVBoxLayout, icon, text: str) -> None:
        row = QHBoxLayout()
        row.setContentsMargins(0, 2, 0, 0)
        row.setSpacing(6)

        icon_widget = IconWidget(icon, self)
        icon_widget.setFixedSize(16, 16)
        title_lbl = BodyLabel(text, self)
        title_lbl.setStyleSheet("font-weight: 600;")

        row.addWidget(icon_widget, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(title_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addStretch()
        parent_layout.addLayout(row)

    def _add_detail_text_row(
        self,
        parent_layout: QVBoxLayout,
        icon,
        text: str,
        *,
        color: str = "",
    ) -> CaptionLabel:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        icon_widget = IconWidget(icon, self)
        icon_widget.setFixedSize(14, 14)
        label = CaptionLabel(text, self)
        label.setWordWrap(True)
        if color:
            label.setStyleSheet(f"color: {color};")

        row.addWidget(icon_widget, 0, Qt.AlignmentFlag.AlignTop)
        row.addWidget(label, 1)
        parent_layout.addLayout(row)
        return label

    def _toggle_detail(self) -> None:
        self._set_expand_state(not self._detail_widget.isVisible())

    def _set_expand_state(self, expanded: bool) -> None:
        self._detail_widget.setVisible(expanded)
        self._expand_btn.setIcon(FIF.UP if expanded else FIF.DOWN)
        self._expand_btn.setText(
            self._i18n.t("plugin.card.collapse", default="收起详情") if expanded
            else self._i18n.t("plugin.card.expand", default="展开详情")
        )
        self._expand_btn.setToolTip(self._expand_btn.text())

    def _make_perm_row(
        self,
        icon,
        label_text: str,
        level: PermissionLevel | None,
        parent_layout: QVBoxLayout,
        *,
        runtime_granted: bool = False,
    ) -> tuple[CaptionLabel, TransparentPushButton]:
        row = QHBoxLayout()
        row.setContentsMargins(0, 2, 0, 0)
        row.setSpacing(6)

        icon_widget = IconWidget(icon, self)
        icon_widget.setFixedSize(14, 14)
        name_lbl = CaptionLabel(f"{label_text}：")
        status_lbl = CaptionLabel("")
        _apply_perm_style(status_lbl, level, runtime_granted=runtime_granted)

        row.addWidget(icon_widget, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(name_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(status_lbl)
        row.addStretch()

        btn = TransparentPushButton(self._i18n.t("plugin.perm.change"))
        btn.setFixedHeight(22)
        row.addWidget(btn)

        parent_layout.addLayout(row)
        return status_lbl, btn

    def sys_perm_button(self, perm_key: str) -> TransparentPushButton | None:
        return self._sys_perm_btns.get(perm_key)

    def reload_button(self) -> TransparentPushButton:
        return self.reload_btn

    def delete_button(self) -> PushButton | None:
        return self._delete_btn

    def selection_checkbox(self) -> CheckBox | None:
        return self._selector


def _apply_perm_style(
    lbl: CaptionLabel,
    level: PermissionLevel | None,
    *,
    runtime_granted: bool = False,
) -> None:
    text, color = _perm_label(level, runtime_granted=runtime_granted)
    lbl.setText(text)
    lbl.setStyleSheet(f"color: {color}; font-weight: bold;")


_STORE_OS_LABELS: dict[str, str] = {
    "windows": "Windows",
    "macos": "macOS",
    "linux": "Linux",
}


class StorePluginCard(CardWidget):
    """插件商店卡片。"""

    def __init__(
        self,
        plugin: StorePlugin,
        *,
        status_text: str,
        status_color: str,
        action_text: str,
        action_enabled: bool,
        parent=None,
    ):
        super().__init__(parent)
        self._plugin = plugin
        self._i18n = I18nService.instance()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(6)

        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        self._avatar = QLabel(self)
        self._avatar.setFixedSize(40, 40)
        self._avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._apply_placeholder_avatar()
        top_row.addWidget(self._avatar, 0, Qt.AlignmentFlag.AlignTop)

        name_row = QHBoxLayout()
        name_row.setSpacing(4)
        name_label = BodyLabel(plugin.display_name(self._i18n.language))
        name_label.setWordWrap(True)
        version_label = CaptionLabel(f"v{plugin.version or '--'}")
        name_row.addWidget(name_label)
        name_row.addWidget(version_label)
        name_row.addStretch()

        self._status_label = CaptionLabel(status_text)
        self._status_label.setStyleSheet(f"color: {status_color}; font-weight: bold;")
        top_row.addLayout(name_row, 1)
        top_row.addWidget(self._status_label, 0, Qt.AlignTop)
        outer.addLayout(top_row)

        desc = CaptionLabel(
            plugin.display_description(self._i18n.language)
            or self._i18n.t("plugin.no_desc")
        )
        desc.setWordWrap(True)
        outer.addWidget(desc)

        meta_bits: list[str] = []
        if plugin.author:
            meta_bits.append(
                self._i18n.t("plugin.store.author", default="作者：{author}", author=plugin.author)
            )
        if plugin.updated_at:
            meta_bits.append(
                self._i18n.t("plugin.store.updated", default="更新：{date}", date=plugin.updated_at)
            )
        if plugin.min_app_version:
            meta_bits.append(
                self._i18n.t(
                    "plugin.store.min_app",
                    default="最低版本：{version}",
                    version=plugin.min_app_version,
                )
            )
        if meta_bits:
            meta_label = CaptionLabel(" · ".join(meta_bits))
            meta_label.setWordWrap(True)
            outer.addWidget(meta_label)

        if plugin.tags:
            tags_row = QHBoxLayout()
            tags_row.setSpacing(6)
            tags_row.addWidget(CaptionLabel(_tr("标签：", "Tags:")))
            for tag in plugin.tags:
                tags_row.addWidget(_create_tag_badge(tag))
            tags_row.addStretch()
            outer.addLayout(tags_row)

        if plugin.supported_os:
            supported = ", ".join(_STORE_OS_LABELS.get(item, item) for item in plugin.supported_os)
            os_label = CaptionLabel(
                self._i18n.t(
                    "plugin.store.supported_os",
                    default="支持系统：{systems}",
                    systems=supported,
                )
            )
            os_label.setWordWrap(True)
            outer.addWidget(os_label)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch()

        self._homepage_button = PushButton(
            FIF.LINK,
            self._i18n.t("plugin.store.homepage", default="主页"),
            self,
        )
        self._homepage_button.setVisible(bool(plugin.homepage))
        btn_row.addWidget(self._homepage_button)

        self._action_button = PrimaryPushButton(action_text, self)
        self._action_button.setEnabled(action_enabled)
        btn_row.addWidget(self._action_button)
        outer.addLayout(btn_row)

    def _apply_placeholder_avatar(self) -> None:
        bg = themeColor()
        self._avatar.setText(_store_plugin_initial_text(self._plugin, self._i18n.language))
        self._avatar.setPixmap(QPixmap())
        self._avatar.setStyleSheet(
            f"background: {bg.name()};"
            "border-radius: 8px;"
            f"color: {_avatar_text_color(bg)};"
            "font-size: 18px;"
            "font-weight: 700;"
        )

    def set_icon_pixmap(self, pixmap: QPixmap | None) -> None:
        if pixmap is None or pixmap.isNull():
            self._apply_placeholder_avatar()
            return
        self._avatar.setPixmap(pixmap)
        self._avatar.setStyleSheet("background: transparent; border-radius: 8px;")
        self._avatar.setText("")

    def action_button(self) -> PrimaryPushButton:
        return self._action_button

    def homepage_button(self) -> PushButton:
        return self._homepage_button


# ──────────────────────────────────────────────────────────────────── #

class PluginView(SmoothScrollArea):
    _STORE_PAGE_SIZE = 6
    _STORE_SEARCH_MIN_WIDTH = 150

    def __init__(
        self,
        plugin_manager: PluginManager,
        resource_service: RemoteResourceService | None = None,
        toast_mgr=None,
        safe_mode: bool = False,
        permission_service: PermissionService | None = None,
        central_control_service: CentralControlService | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("pluginView")
        self._mgr = plugin_manager
        self._resource_service = resource_service
        self._toast_mgr = toast_mgr
        self._safe_mode = safe_mode
        self._permission_service = permission_service
        self._central_control_service = central_control_service
        self._i18n = I18nService.instance()
        self._store_plugins: list[StorePlugin] = list(resource_service.store_plugins) if resource_service else []
        self._store_loading = False
        self._store_last_error = ""
        self._store_installing_ids: set[str] = set()
        self._store_current_os = current_os_key()
        self._store_tag_options: list[str] = []
        self._store_icon_cache: dict[str, QPixmap] = {}
        self._store_icon_loading_ids: set[str] = set()
        self._store_icon_failed_ids: set[str] = set()
        self._store_icon_source_keys: dict[str, str] = {}
        self._store_icon_tasks: dict[str, tuple[QThread, _StoreIconWorker]] = {}
        self._store_visible_cards: dict[str, StorePluginCard] = {}
        self._local_tag_options: list[str] = []
        self._local_select_mode = False
        self._local_selected_ids: set[str] = set()
        self._local_filtered_ids: list[str] = []
        self._safe_mode_notice: InfoBar | None = None
        self._security_notice: InfoBar | None = None
        self._sync_store_icon_state(self._store_plugins)

        # 注册权限回调
        plugin_manager.set_permission_callback(self._on_pkg_perm_request)
        plugin_manager.set_sys_permission_callback(self._on_sys_perm_request)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(8)

        layout.addWidget(TitleLabel(self._i18n.t("plugin.title")))

        self._notice_host = QWidget(container)
        self._notice_host.setAutoFillBackground(False)
        self._notice_layout = QVBoxLayout(self._notice_host)
        self._notice_layout.setContentsMargins(0, 0, 0, 0)
        self._notice_layout.setSpacing(8)
        self._notice_host.hide()
        layout.addWidget(self._notice_host)

        self._pivot = Pivot()
        layout.addWidget(self._pivot, 0, Qt.AlignLeft)

        self._stacked = QStackedWidget()
        layout.addWidget(self._stacked, 1)

        # ── 本地插件页 ──
        self._local_page = QWidget()
        local_layout = QVBoxLayout(self._local_page)
        local_layout.setContentsMargins(0, 0, 0, 0)
        local_layout.setSpacing(8)

        local_bar = QHBoxLayout()
        local_bar.setSpacing(8)

        self._local_search_edit = SearchLineEdit(self._local_page)
        self._local_search_edit.setPlaceholderText(
            self._i18n.t("plugin.local.search.placeholder", default="搜索名称、作者、简介、ID 或标签")
        )
        self._local_search_edit.textChanged.connect(lambda *_: self._on_local_filters_changed())
        local_bar.addWidget(self._local_search_edit, 1)

        self._local_state_combo = ComboBox(self._local_page)
        self._local_state_combo.addItem(
            self._i18n.t("plugin.local.filter.state.all", default="全部状态"),
            userData="all",
        )
        self._local_state_combo.addItem(
            self._i18n.t("plugin.local.filter.state.enabled", default="仅启用"),
            userData="enabled",
        )
        self._local_state_combo.addItem(
            self._i18n.t("plugin.local.filter.state.disabled", default="仅禁用"),
            userData="disabled",
        )
        self._local_state_combo.currentIndexChanged.connect(lambda *_: self._on_local_filters_changed())
        local_bar.addWidget(self._local_state_combo)

        self._local_tag_combo = ComboBox(self._local_page)
        self._local_tag_combo.addItem(
            self._i18n.t("plugin.local.filter.tag.all", default="全部标签"),
            userData="all",
        )
        self._local_tag_combo.currentIndexChanged.connect(lambda *_: self._on_local_filters_changed())
        local_bar.addWidget(self._local_tag_combo)

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

        self._local_select_btn = PushButton(FIF.CHECKBOX, self._i18n.t("plugin.local.select.enter", default="选择"), self)
        self._local_select_btn.clicked.connect(self._toggle_local_select_mode)

        local_bar.addStretch()
        local_bar.addWidget(self._local_select_btn)
        local_bar.addWidget(import_btn)
        local_bar.addWidget(reload_btn)
        local_layout.addLayout(local_bar)

        self._local_command_bar = CommandBar(self._local_page)
        self._local_command_bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._local_command_bar.hide()
        self._local_selection_hint = CaptionLabel(
            self._i18n.t("plugin.local.select.none", default="当前未选择插件")
        )
        self._local_command_bar.addWidget(self._local_selection_hint)

        self._cmd_select_all_btn = self._local_command_bar.addAction(
            Action(
                FIF.ACCEPT,
                self._i18n.t("plugin.local.select.all", default="全选"),
                triggered=self._select_all_local_plugins,
            )
        )
        self._cmd_clear_selection_btn = self._local_command_bar.addAction(
            Action(
                FIF.CLEAR_SELECTION,
                self._i18n.t("plugin.local.select.clear", default="取消全选"),
                triggered=self._clear_local_selection,
            )
        )
        self._cmd_batch_disable_btn = self._local_command_bar.addAction(
            Action(
                FIF.PAUSE,
                self._i18n.t("plugin.local.batch.disable", default="批量禁用"),
                triggered=lambda: self._batch_set_local_plugins_enabled(False),
            )
        )
        self._cmd_batch_enable_btn = self._local_command_bar.addAction(
            Action(
                FIF.PLAY,
                self._i18n.t("plugin.local.batch.enable", default="批量启用"),
                triggered=lambda: self._batch_set_local_plugins_enabled(True),
            )
        )
        self._cmd_batch_reload_btn = self._local_command_bar.addAction(
            Action(
                FIF.SYNC,
                self._i18n.t("plugin.local.batch.reload", default="批量热重载"),
                triggered=self._batch_reload_local_plugins,
            )
        )
        self._cmd_batch_delete_btn = self._local_command_bar.addAction(
            Action(
                FIF.DELETE,
                self._i18n.t("plugin.local.batch.delete", default="批量删除"),
                triggered=self._batch_delete_local_plugins,
            )
        )
        self._cmd_batch_delete_btn.setStyleSheet("color: #d13438; font-weight: 600;")
        local_layout.addWidget(self._local_command_bar)

        self._empty_lbl = CaptionLabel(self._i18n.t("plugin.empty"))
        self._empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_lbl.hide()

        self._cards_layout = QVBoxLayout()
        self._cards_layout.setSpacing(6)
        local_layout.addWidget(self._empty_lbl)
        local_layout.addLayout(self._cards_layout)
        local_layout.addStretch()

        self._stacked.addWidget(self._local_page)
        self._pivot.addItem(
            routeKey="localPage",
            text=self._i18n.t("plugin.tab.local", default="本地"),
            onClick=lambda: self._stacked.setCurrentWidget(self._local_page),
        )

        # ── 插件商店页 ──
        self._store_page = QWidget()
        store_layout = QVBoxLayout(self._store_page)
        store_layout.setContentsMargins(0, 0, 0, 0)
        store_layout.setSpacing(8)

        store_bar = QHBoxLayout()
        store_bar.setSpacing(8)

        self._store_search_edit = LineEdit(self._store_page)
        self._store_search_edit.setClearButtonEnabled(True)
        self._store_search_edit.setMinimumWidth(self._STORE_SEARCH_MIN_WIDTH)
        self._store_search_edit.setPlaceholderText(
            self._i18n.t("plugin.store.search.placeholder", default="搜索名称、作者、描述或标签")
        )
        self._store_search_edit.textChanged.connect(lambda *_: self._on_store_filters_changed())
        store_bar.addWidget(self._store_search_edit, 1)

        self._store_os_combo = ComboBox(self._store_page)
        self._store_os_combo.addItem(
            self._i18n.t("plugin.store.filter.os.compatible", default="仅显示兼容当前系统"),
            userData="compatible",
        )
        self._store_os_combo.addItem(
            self._i18n.t("plugin.store.filter.os.all", default="全部系统"),
            userData="all",
        )
        self._store_os_combo.addItem("Windows", userData="windows")
        self._store_os_combo.addItem("macOS", userData="macos")
        self._store_os_combo.addItem("Linux", userData="linux")
        self._store_os_combo.currentIndexChanged.connect(lambda *_: self._on_store_filters_changed())
        store_bar.addWidget(self._store_os_combo)

        self._store_tag_combo = ComboBox(self._store_page)
        self._store_tag_combo.addItem(
            self._i18n.t("plugin.store.filter.tag.all", default="全部标签"),
            userData="all",
        )
        self._store_tag_combo.currentIndexChanged.connect(lambda *_: self._on_store_filters_changed())
        store_bar.addWidget(self._store_tag_combo)

        self._store_refresh_btn = PushButton(FIF.SYNC, self._i18n.t("plugin.store.refresh", default="刷新商店"))
        self._store_refresh_btn.clicked.connect(self._refresh_store_plugins)
        store_bar.addWidget(self._store_refresh_btn)

        store_layout.addLayout(store_bar)

        self._store_status_lbl = CaptionLabel("")
        self._store_status_lbl.setWordWrap(True)
        store_layout.addWidget(self._store_status_lbl)

        self._store_cards_layout = QVBoxLayout()
        self._store_cards_layout.setSpacing(6)
        store_layout.addLayout(self._store_cards_layout)

        store_pager = QHBoxLayout()
        store_pager.addStretch()
        self._store_prev_btn = PushButton(
            self._i18n.t("plugin.store.page.prev", default="上一页"),
            self._store_page,
        )
        self._store_prev_btn.clicked.connect(self._goto_prev_store_page)
        self._store_page_lbl = CaptionLabel("")
        self._store_next_btn = PushButton(
            self._i18n.t("plugin.store.page.next", default="下一页"),
            self._store_page,
        )
        self._store_next_btn.clicked.connect(self._goto_next_store_page)
        store_pager.addWidget(self._store_prev_btn)
        store_pager.addWidget(self._store_page_lbl)
        store_pager.addWidget(self._store_next_btn)
        store_layout.addLayout(store_pager)
        store_layout.addStretch()

        self._store_page_index = 0
        self._stacked.addWidget(self._store_page)
        self._pivot.addItem(
            routeKey="storePage",
            text=self._i18n.t("plugin.tab.store", default="商店"),
            onClick=lambda: self._stacked.setCurrentWidget(self._store_page),
        )
        self._stacked.currentChanged.connect(self._on_page_changed)
        self._stacked.setCurrentWidget(self._local_page)
        self._pivot.setCurrentItem("localPage")

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

        if self._resource_service is not None:
            self._resource_service.storePluginsUpdated.connect(self._on_store_plugins_updated)
            self._resource_service.storePluginsFailed.connect(self._on_store_plugins_failed)
            self._resource_service.storeLoadingChanged.connect(self._on_store_loading_changed)
            self._resource_service.storePluginInstalled.connect(self._on_store_plugin_installed)

        self._rebuild_inline_notices()
        self._refresh_local_select_ui()
        self._rebuild_store_tag_filter()
        self._refresh_store_cards()

    def _ensure_access(self, feature_key: str, reason: str) -> bool:
        if self._permission_service is None:
            return True
        ok = self._permission_service.ensure_access(
            feature_key,
            parent=self.window(),
            reason=reason,
        )
        if ok:
            return True
        deny_reason = self._permission_service.get_last_denied_reason(feature_key)
        InfoBar.warning(
            self._i18n.t("plugin.title"),
            deny_reason or self._i18n.t("perm.access.denied", default="权限不足，无法执行该操作。"),
            parent=self.window(),
            position=InfoBarPosition.TOP_RIGHT,
            duration=2500,
        )
        return False

    def _ensure_managed_plugin_allowed(self, plugin_id: str, *, show_tip: bool = True) -> bool:
        svc = self._central_control_service
        if svc is None:
            return True
        ok, reason = svc.is_plugin_allowed(plugin_id)
        if ok:
            return True
        if show_tip:
            InfoBar.warning(
                self._i18n.t("plugin.title"),
                reason or self._i18n.t("perm.access.denied", default="权限不足，无法执行该操作。"),
                parent=self.window(),
                position=InfoBarPosition.TOP_RIGHT,
                duration=3000,
            )
        return False

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._schedule_cards_reload()
        if self._stacked.currentWidget() is self._store_page:
            self._ensure_store_data_loaded()

    def _add_inline_notice(
        self,
        *,
        level: str,
        title: str,
        content: str,
        is_closable: bool,
        duration: int = -1,
    ) -> InfoBar:
        icon = {
            "success": InfoBarIcon.SUCCESS,
            "warning": InfoBarIcon.WARNING,
            "error": InfoBarIcon.ERROR,
            "info": InfoBarIcon.INFORMATION,
        }.get(level, InfoBarIcon.INFORMATION)

        bar = InfoBar(
            icon=icon,
            title=title,
            content=content,
            orient=Qt.Orientation.Vertical if "\n" in content else Qt.Orientation.Horizontal,
            isClosable=is_closable,
            duration=duration,
            position=InfoBarPosition.NONE,
            parent=self._notice_host,
        )
        self._notice_layout.addWidget(bar)
        bar.show()
        return bar

    def _sync_notice_host_visibility(self) -> None:
        has_visible_notice = False
        for i in range(self._notice_layout.count()):
            item = self._notice_layout.itemAt(i)
            widget = item.widget() if item is not None else None
            if widget is not None and not widget.isHidden():
                has_visible_notice = True
                break
        self._notice_host.setVisible(has_visible_notice)

    def _clear_inline_notices(self) -> None:
        while self._notice_layout.count():
            item = self._notice_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.close()
        self._safe_mode_notice = None
        self._security_notice = None
        self._notice_host.hide()

    def _rebuild_inline_notices(self) -> None:
        self._clear_inline_notices()

        if self._safe_mode:
            self._safe_mode_notice = self._add_inline_notice(
                level="warning",
                title=self._i18n.t("plugin.title"),
                content=self._i18n.t(
                    "boot.safe_mode.plugin_hint",
                    default="安全模式已开启，插件未加载。重开并选择「正常启动」可恢复插件功能。",
                ),
                is_closable=False,
                duration=-1,
            )

        if _should_show_plugin_security_notice():
            content = self._i18n.t("plugin.security.desc")
            detail = self._i18n.t(
                "plugin.security.detail",
                default="已支持运行期权限申请、宿主敏感服务过滤、模块卸载清理和权限审计；但这仍是软隔离而非强沙箱。请仅安装可信来源插件。",
            )
            merged = f"{content}\n{detail}" if detail else content
            self._security_notice = self._add_inline_notice(
                level="warning",
                title=self._i18n.t("plugin.security.title"),
                content=merged,
                is_closable=True,
                duration=-1,
            )
            dismiss_btn = PushButton(self._i18n.t("plugin.security.dismiss"), self._security_notice)
            dismiss_btn.clicked.connect(self._dismiss_security_notice_forever)
            self._security_notice.addWidget(dismiss_btn)
            self._security_notice.closedSignal.connect(self._on_security_notice_closed)

        self._sync_notice_host_visibility()

    def _dismiss_security_notice_forever(self) -> None:
        _set_plugin_security_notice_dismissed()
        if self._security_notice is not None:
            self._security_notice.close()

    def _on_security_notice_closed(self) -> None:
        self._security_notice = None
        QTimer.singleShot(0, self._sync_notice_host_visibility)

    def _mark_cards_dirty(self) -> None:
        self._cards_dirty = True
        self._refresh_store_cards()
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

    def _on_page_changed(self, index: int) -> None:
        widget = self._stacked.widget(index)
        if widget is self._local_page:
            self._pivot.setCurrentItem("localPage")
            self._schedule_cards_reload()
            return
        if widget is self._store_page:
            self._pivot.setCurrentItem("storePage")
            self._ensure_store_data_loaded()
            self._refresh_store_cards()

    def _ensure_store_data_loaded(self) -> None:
        if self._resource_service is None:
            self._store_status_lbl.setText(
                self._i18n.t("plugin.store.error.no_service", default="插件商店服务不可用")
            )
            return
        if self._store_plugins or self._store_loading:
            return
        self._refresh_store_plugins()

    def _refresh_store_plugins(self) -> None:
        if self._resource_service is None:
            self._store_status_lbl.setText(
                self._i18n.t("plugin.store.error.no_service", default="插件商店服务不可用")
            )
            return
        self._store_last_error = ""
        started = self._resource_service.refresh_store_plugins()
        if started:
            self._refresh_store_cards()

    def _on_store_loading_changed(self, loading: bool) -> None:
        self._store_loading = bool(loading)
        self._store_refresh_btn.setEnabled(not self._store_loading)
        self._store_refresh_btn.setText(
            self._i18n.t("plugin.store.refresh.loading", default="刷新中…")
            if self._store_loading else
            self._i18n.t("plugin.store.refresh", default="刷新商店")
        )
        self._refresh_store_cards()

    @Slot(object)
    def _on_store_plugins_updated(self, plugins: object) -> None:
        self._store_last_error = ""
        next_plugins = list(plugins) if isinstance(plugins, list) else []
        self._sync_store_icon_state(next_plugins)
        self._store_plugins = next_plugins
        self._rebuild_store_tag_filter()
        self._store_page_index = 0
        self._refresh_store_cards()

    @Slot(str)
    def _on_store_plugins_failed(self, error: str) -> None:
        self._store_last_error = error
        self._refresh_store_cards()
        InfoBar.error(
            self._i18n.t("plugin.tab.store", default="商店"),
            self._i18n.t("plugin.store.error.fetch", default="插件商店加载失败：{error}", error=error),
            parent=self.window(),
            position=InfoBarPosition.TOP_RIGHT,
            duration=5000,
        )

    @Slot(str, bool, str)
    def _on_store_plugin_installed(self, plugin_id: str, ok: bool, message: str) -> None:
        self._store_installing_ids.discard(plugin_id)
        self._refresh_store_cards()
        if ok:
            self._mgr.discover_and_load()
            self._mark_cards_dirty()
            InfoBar.success(
                self._i18n.t("plugin.tab.store", default="商店"),
                self._i18n.t("plugin.store.install.success", default="插件已安装：{id}", id=plugin_id),
                parent=self.window(),
                position=InfoBarPosition.TOP_RIGHT,
                duration=3000,
            )
            return
        InfoBar.error(
            self._i18n.t("plugin.tab.store", default="商店"),
            self._i18n.t("plugin.store.install.fail", default="插件安装失败：{error}", error=message),
            parent=self.window(),
            position=InfoBarPosition.TOP_RIGHT,
            duration=5000,
        )

    def _on_store_filters_changed(self) -> None:
        self._store_page_index = 0
        self._refresh_store_cards()

    def _goto_prev_store_page(self) -> None:
        if self._store_page_index <= 0:
            return
        self._store_page_index -= 1
        self._refresh_store_cards()

    def _goto_next_store_page(self) -> None:
        filtered = self._filtered_store_plugins()
        page_count = max(1, (len(filtered) + self._STORE_PAGE_SIZE - 1) // self._STORE_PAGE_SIZE)
        if self._store_page_index >= page_count - 1:
            return
        self._store_page_index += 1
        self._refresh_store_cards()

    def _rebuild_store_tag_filter(self) -> None:
        tags = sorted({tag for plugin in self._store_plugins for tag in plugin.tags})
        current = self._store_tag_combo.currentData()
        self._store_tag_combo.blockSignals(True)
        self._store_tag_combo.clear()
        self._store_tag_combo.addItem(
            self._i18n.t("plugin.store.filter.tag.all", default="全部标签"),
            userData="all",
        )
        for tag in tags:
            self._store_tag_combo.addItem(tag, userData=tag)
        index = self._store_tag_combo.findData(current)
        self._store_tag_combo.setCurrentIndex(index if index >= 0 else 0)
        self._store_tag_combo.blockSignals(False)
        self._store_tag_options = tags

    def _clear_store_cards(self) -> None:
        self._store_visible_cards.clear()
        while self._store_cards_layout.count():
            item = self._store_cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _clear_local_cards(self) -> None:
        while self._cards_layout.count():
            item = self._cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _on_local_filters_changed(self) -> None:
        self._cards_dirty = True
        self._schedule_cards_reload()

    def _rebuild_local_tag_filter(self, known_plugins: list[tuple]) -> None:
        tags = sorted({
            tag
            for meta, _enabled, _error, _dep_warning in known_plugins
            for tag in (meta.tags or [])
        })
        current = self._local_tag_combo.currentData()
        self._local_tag_combo.blockSignals(True)
        self._local_tag_combo.clear()
        self._local_tag_combo.addItem(
            self._i18n.t("plugin.local.filter.tag.all", default="全部标签"),
            userData="all",
        )
        for tag in tags:
            self._local_tag_combo.addItem(tag, userData=tag)
        index = self._local_tag_combo.findData(current)
        self._local_tag_combo.setCurrentIndex(index if index >= 0 else 0)
        self._local_tag_combo.blockSignals(False)
        self._local_tag_options = tags

    def _filtered_local_plugins(self, known_plugins: list[tuple]) -> list[tuple]:
        query = self._local_search_edit.text().strip().lower()
        state_filter = self._local_state_combo.currentData() or "all"
        tag_filter = self._local_tag_combo.currentData() or "all"

        def _matches(item: tuple) -> bool:
            meta, enabled, _error, _dep_warning = item
            if query:
                haystack = " ".join([
                    meta.id,
                    meta.get_name(self._i18n.language),
                    meta.get_description(self._i18n.language),
                    meta.author,
                    " ".join(meta.tags or []),
                ]).lower()
                if query not in haystack:
                    return False

            if state_filter == "enabled" and not enabled:
                return False
            if state_filter == "disabled" and enabled:
                return False
            if tag_filter != "all" and tag_filter not in (meta.tags or []):
                return False
            return True

        return [item for item in known_plugins if _matches(item)]

    def _toggle_local_select_mode(self) -> None:
        self._local_select_mode = not self._local_select_mode
        if not self._local_select_mode:
            self._local_selected_ids.clear()
        self._refresh_local_select_ui()
        self._cards_dirty = True
        self._schedule_cards_reload()

    def _selected_local_plugin_ids(self) -> list[str]:
        known_ids = {
            meta.id
            for meta, _enabled, _error, _dep_warning in self._mgr.all_known_plugins()
        }
        selected = [pid for pid in self._local_selected_ids if pid in known_ids]
        self._local_selected_ids = set(selected)
        return selected

    def _on_local_card_selected(self, plugin_id: str, selected: bool) -> None:
        if selected:
            self._local_selected_ids.add(plugin_id)
        else:
            self._local_selected_ids.discard(plugin_id)
        self._refresh_local_select_ui()

    def _select_all_local_plugins(self) -> None:
        if not self._local_select_mode:
            return
        self._local_selected_ids.update(self._local_filtered_ids)
        self._refresh_local_select_ui()
        self._cards_dirty = True
        self._schedule_cards_reload()

    def _clear_local_selection(self) -> None:
        self._local_selected_ids.clear()
        self._refresh_local_select_ui()
        self._cards_dirty = True
        self._schedule_cards_reload()

    def _refresh_local_select_ui(self) -> None:
        if not hasattr(self, "_local_command_bar"):
            return

        selected_count = len(self._selected_local_plugin_ids())
        visible_count = len(self._local_filtered_ids)
        self._local_command_bar.setVisible(self._local_select_mode)
        self._local_select_btn.setText(
            self._i18n.t("plugin.local.select.exit", default="退出选择")
            if self._local_select_mode else
            self._i18n.t("plugin.local.select.enter", default="选择")
        )
        self._local_selection_hint.setText(
            _tr(f"已选择{selected_count}个插件", f"Selected {selected_count} plugins")
            if self._local_select_mode else
            self._i18n.t("plugin.local.select.none", default="当前未选择插件")
        )

        can_select_all = self._local_select_mode and visible_count > 0
        self._cmd_select_all_btn.setEnabled(can_select_all)
        self._cmd_clear_selection_btn.setEnabled(self._local_select_mode and selected_count > 0)

        can_batch = self._local_select_mode and selected_count > 0
        self._cmd_batch_disable_btn.setEnabled(can_batch)
        self._cmd_batch_enable_btn.setEnabled(can_batch)
        self._cmd_batch_reload_btn.setEnabled(can_batch)
        self._cmd_batch_delete_btn.setEnabled(can_batch)

    def _batch_set_local_plugins_enabled(self, enabled: bool) -> None:
        if not self._ensure_access("plugin.manage", "批量启用或禁用插件"):
            return
        plugin_ids = self._selected_local_plugin_ids()
        if not plugin_ids:
            return

        changed = 0
        blocked_by_policy: list[str] = []
        for plugin_id in plugin_ids:
            if enabled and not self._mgr.is_disabled(plugin_id):
                continue
            if (not enabled) and self._mgr.is_disabled(plugin_id):
                continue
            if enabled and not self._ensure_managed_plugin_allowed(plugin_id, show_tip=False):
                blocked_by_policy.append(plugin_id)
                continue
            self._mgr.set_enabled(plugin_id, enabled)
            changed += 1

        if changed:
            InfoBar.success(
                self._i18n.t("plugin.title"),
                self._i18n.t(
                    "plugin.local.batch.enabled.ok",
                    default="已批量{action} {count} 个插件",
                    action=("启用" if enabled else "禁用"),
                    count=changed,
                ),
                parent=self.window(),
                position=InfoBarPosition.TOP_RIGHT,
                duration=3000,
            )

        if blocked_by_policy:
            preview = ", ".join(blocked_by_policy[:5])
            if len(blocked_by_policy) > 5:
                preview += " ..."
            InfoBar.warning(
                self._i18n.t("plugin.title"),
                self._i18n.t(
                    "plugin.local.batch.enabled.blocked_by_policy",
                    default="以下插件不在集控受管列表，已跳过：{ids}",
                    ids=preview,
                ),
                parent=self.window(),
                position=InfoBarPosition.TOP_RIGHT,
                duration=5000,
            )

        self._cards_dirty = True
        self._schedule_cards_reload()
        self._refresh_store_cards()

    def _batch_reload_local_plugins(self) -> None:
        if not self._ensure_access("plugin.manage", "批量热重载插件"):
            return
        plugin_ids = self._selected_local_plugin_ids()
        if not plugin_ids:
            return

        success = 0
        failed: list[str] = []
        for plugin_id in plugin_ids:
            if self._mgr.is_disabled(plugin_id):
                failed.append(plugin_id)
                continue
            ok, _message, _reloaded_ids, _failed_ids = self._mgr.reload_plugin(plugin_id)
            if ok:
                success += 1
            else:
                failed.append(plugin_id)

        if success:
            InfoBar.success(
                self._i18n.t("plugin.reload.one", default="热重载"),
                self._i18n.t(
                    "plugin.local.batch.reload.ok",
                    default="已热重载 {count} 个插件",
                    count=success,
                ),
                parent=self.window(),
                position=InfoBarPosition.TOP_RIGHT,
                duration=3000,
            )
        if failed:
            InfoBar.warning(
                self._i18n.t("plugin.reload.one", default="热重载"),
                self._i18n.t(
                    "plugin.local.batch.reload.fail",
                    default="以下插件未能热重载：{ids}",
                    ids=", ".join(failed),
                ),
                parent=self.window(),
                position=InfoBarPosition.TOP_RIGHT,
                duration=5000,
            )

        self._cards_dirty = True
        self._schedule_cards_reload()

    def _batch_delete_local_plugins(self) -> None:
        if not self._ensure_access("plugin.manage", "批量删除插件"):
            return
        plugin_ids = self._selected_local_plugin_ids()
        if not plugin_ids:
            return

        confirm = MessageBox(
            self._i18n.t("plugin.local.batch.delete.confirm.title", default="确认删除插件"),
            _tr(
                f"将删除{len(plugin_ids)}个已选插件，此操作不可撤销。是否继续？",
                f"This will delete {len(plugin_ids)} selected plugins permanently. Continue?",
            ),
            self.window(),
        )
        confirm.yesButton.setText(self._i18n.t("common.delete", default="删除"))
        confirm.cancelButton.setText(self._i18n.t("common.cancel", default="取消"))
        if not confirm.exec():
            return

        deleted = 0
        failed_msgs: list[str] = []
        for plugin_id in plugin_ids:
            ok, message = self._mgr.delete_plugin(plugin_id)
            if ok:
                deleted += 1
                self._local_selected_ids.discard(plugin_id)
            else:
                failed_msgs.append(f"{plugin_id}: {message}")

        self._mgr.discover_and_load()
        self._cards_dirty = True
        self._schedule_cards_reload()
        self._refresh_store_cards()
        self._refresh_local_select_ui()

        if deleted:
            InfoBar.success(
                self._i18n.t("plugin.title"),
                self._i18n.t(
                    "plugin.local.batch.delete.ok",
                    default="已删除 {count} 个插件",
                    count=deleted,
                ),
                parent=self.window(),
                position=InfoBarPosition.TOP_RIGHT,
                duration=3500,
            )
        if failed_msgs:
            InfoBar.warning(
                self._i18n.t("plugin.title"),
                self._i18n.t(
                    "plugin.local.batch.delete.partial",
                    default="部分插件删除失败：{msg}",
                    msg="；".join(failed_msgs[:3]),
                ),
                parent=self.window(),
                position=InfoBarPosition.TOP_RIGHT,
                duration=6000,
            )

    def _sync_store_icon_state(self, plugins: list[StorePlugin]) -> None:
        source_keys = {
            plugin.stable_id: _store_icon_source_key(plugin.icon)
            for plugin in plugins
            if plugin.stable_id
        }
        active_ids = set(source_keys)

        for plugin_id in list(self._store_icon_source_keys):
            if plugin_id in active_ids:
                continue
            self._store_icon_source_keys.pop(plugin_id, None)
            self._store_icon_cache.pop(plugin_id, None)
            self._store_icon_failed_ids.discard(plugin_id)

        for plugin_id, source_key in source_keys.items():
            if self._store_icon_source_keys.get(plugin_id) == source_key:
                if source_key:
                    self._store_icon_failed_ids.discard(plugin_id)
                continue
            self._store_icon_cache.pop(plugin_id, None)
            self._store_icon_failed_ids.discard(plugin_id)

        self._store_icon_source_keys = source_keys

    def _start_store_icon_task(self, plugin: StorePlugin) -> None:
        plugin_id = plugin.stable_id
        if not plugin_id or plugin_id in self._store_icon_loading_ids:
            return

        icon_spec = str(plugin.icon or "").strip()
        source_key = self._store_icon_source_keys.get(plugin_id, "")
        if not icon_spec or not source_key:
            self._store_icon_failed_ids.add(plugin_id)
            return

        thread = QThread(self)
        worker = _StoreIconWorker(plugin_id, source_key, icon_spec)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_store_icon_loaded)
        worker.failed.connect(self._on_store_icon_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(lambda pid=plugin_id: self._cleanup_store_icon_task(pid))

        self._store_icon_tasks[plugin_id] = (thread, worker)
        self._store_icon_loading_ids.add(plugin_id)
        thread.start()

    @Slot(str, str, object)
    def _on_store_icon_loaded(self, plugin_id: str, source_key: str, payload: object) -> None:
        if self._store_icon_source_keys.get(plugin_id, "") != source_key:
            return

        pixmap: QPixmap | None = None
        if isinstance(payload, (bytes, bytearray)):
            source = QPixmap()
            if source.loadFromData(bytes(payload)):
                pixmap = _rounded_square_pixmap(source, 40)

        if pixmap is None or pixmap.isNull():
            self._store_icon_failed_ids.add(plugin_id)
            return

        self._store_icon_cache[plugin_id] = pixmap
        self._store_icon_failed_ids.discard(plugin_id)
        card = self._store_visible_cards.get(plugin_id)
        if card is not None:
            card.set_icon_pixmap(pixmap)

    @Slot(str, str)
    def _on_store_icon_failed(self, plugin_id: str, source_key: str) -> None:
        if self._store_icon_source_keys.get(plugin_id, "") != source_key:
            return
        self._store_icon_failed_ids.add(plugin_id)

    def _cleanup_store_icon_task(self, plugin_id: str) -> None:
        thread, worker = self._store_icon_tasks.pop(plugin_id, (None, None))
        self._store_icon_loading_ids.discard(plugin_id)
        if worker is not None:
            worker.deleteLater()
        if thread is not None:
            thread.deleteLater()

        if plugin_id not in self._store_icon_source_keys:
            return
        if plugin_id in self._store_icon_cache or plugin_id in self._store_icon_failed_ids:
            return
        plugin = next((item for item in self._store_plugins if item.stable_id == plugin_id), None)
        if plugin is not None:
            self._start_store_icon_task(plugin)

    def _apply_store_card_icon(self, card: StorePluginCard, plugin: StorePlugin) -> None:
        plugin_id = plugin.stable_id
        cached = self._store_icon_cache.get(plugin_id)
        if cached is not None and not cached.isNull():
            card.set_icon_pixmap(cached)
            return

        card.set_icon_pixmap(None)
        if plugin_id in self._store_icon_failed_ids or plugin_id in self._store_icon_loading_ids:
            return
        self._start_store_icon_task(plugin)

    def _filtered_store_plugins(self) -> list[StorePlugin]:
        query = self._store_search_edit.text().strip().lower()
        os_filter = self._store_os_combo.currentData() or "compatible"
        tag_filter = self._store_tag_combo.currentData() or "all"

        def _matches(plugin: StorePlugin) -> bool:
            if query:
                haystack = " ".join([
                    plugin.stable_id,
                    plugin.display_name(self._i18n.language),
                    plugin.display_description(self._i18n.language),
                    plugin.author,
                    " ".join(plugin.tags),
                ]).lower()
                if query not in haystack:
                    return False

            if os_filter == "compatible":
                if plugin.supported_os and self._store_current_os not in plugin.supported_os:
                    return False
            elif os_filter != "all":
                if os_filter not in plugin.supported_os:
                    return False

            if tag_filter != "all" and tag_filter not in plugin.tags:
                return False
            return True

        return [plugin for plugin in self._store_plugins if _matches(plugin)]

    def _local_plugin_maps(self) -> tuple[dict[str, PluginMeta], dict[str, PluginMeta]]:
        exact: dict[str, PluginMeta] = {}
        normalized: dict[str, PluginMeta] = {}
        for meta, _enabled, _error, _dep_warning in self._mgr.all_known_plugins():
            exact[meta.id] = meta
            normalized.setdefault(normalize_plugin_lookup_key(meta.id), meta)
        return exact, normalized

    def _local_meta_for_store_plugin(self, plugin: StorePlugin) -> PluginMeta | None:
        exact, normalized = self._local_plugin_maps()
        if plugin.stable_id in exact:
            return exact[plugin.stable_id]
        return normalized.get(normalize_plugin_lookup_key(plugin.stable_id))

    def _store_action_state(self, plugin: StorePlugin) -> tuple[str, str, str, str, bool]:
        if plugin.stable_id in self._store_installing_ids:
            return (
                "installing",
                self._i18n.t("plugin.store.status.installing", default="安装中…"),
                "#e67e22",
                self._i18n.t("plugin.store.action.installing", default="安装中…"),
                False,
            )

        if plugin.supported_os and self._store_current_os not in plugin.supported_os:
            return (
                "unsupported_os",
                self._i18n.t("plugin.store.status.unsupported_os", default="当前系统不支持"),
                "#e74c3c",
                self._i18n.t("plugin.store.action.unavailable", default="不可安装"),
                False,
            )

        if plugin.min_app_version and compare_versions(APP_VERSION, plugin.min_app_version) < 0:
            return (
                "unsupported_app",
                self._i18n.t(
                    "plugin.store.status.unsupported_app",
                    default="需应用版本 ≥ {version}",
                    version=plugin.min_app_version,
                ),
                "#e74c3c",
                self._i18n.t("plugin.store.action.unavailable", default="不可安装"),
                False,
            )

        local_meta = self._local_meta_for_store_plugin(plugin)
        if local_meta is None:
            return (
                "not_installed",
                self._i18n.t("plugin.store.status.not_installed", default="未安装"),
                "#8a8a8a",
                self._i18n.t("plugin.store.action.install", default="安装"),
                True,
            )

        version_cmp = compare_versions(local_meta.version, plugin.version)
        if version_cmp < 0:
            return (
                "updatable",
                self._i18n.t("plugin.store.status.updatable", default="可更新"),
                "#2d8cf0",
                self._i18n.t("plugin.store.action.update", default="更新"),
                True,
            )
        if version_cmp == 0:
            return (
                "installed",
                self._i18n.t("plugin.store.status.installed", default="已安装"),
                "#27ae60",
                self._i18n.t("plugin.store.action.reinstall", default="重新安装"),
                True,
            )
        return (
            "local_newer",
            self._i18n.t("plugin.store.status.local_newer", default="本地版本较新"),
            "#27ae60",
            self._i18n.t("plugin.store.action.reinstall", default="重新安装"),
            True,
        )

    def _refresh_store_cards(self) -> None:
        if not hasattr(self, "_store_cards_layout"):
            return
        self._clear_store_cards()

        filtered = self._filtered_store_plugins()
        total = len(filtered)
        page_count = max(1, (total + self._STORE_PAGE_SIZE - 1) // self._STORE_PAGE_SIZE) if total else 1
        self._store_page_index = max(0, min(self._store_page_index, page_count - 1))

        if self._store_loading and not self._store_plugins:
            self._store_status_lbl.setText(
                self._i18n.t("plugin.store.loading", default="正在加载插件商店…")
            )
        elif self._store_last_error and not self._store_plugins:
            self._store_status_lbl.setText(
                self._i18n.t("plugin.store.error.fetch", default="插件商店加载失败：{error}", error=self._store_last_error)
            )
        elif not self._store_plugins:
            self._store_status_lbl.setText(
                self._i18n.t("plugin.store.empty.remote", default="暂无商店数据，可点击右上角刷新。")
            )
        elif not filtered:
            self._store_status_lbl.setText(
                self._i18n.t("plugin.store.empty.filtered", default="没有符合当前筛选条件的插件。")
            )
        else:
            page_no = self._store_page_index + 1
            base_text = self._i18n.t(
                "plugin.store.summary",
                default="共 {total} 个插件，第 {page}/{pages} 页",
                total=total,
                page=page_no,
                pages=page_count,
            )
            if self._store_loading:
                base_text += " · " + self._i18n.t("plugin.store.loading.short", default="正在刷新")
            elif self._store_last_error:
                base_text += " · " + self._i18n.t("plugin.store.error.cached", default="刷新失败，已显示缓存")
            self._store_status_lbl.setText(base_text)

        if total:
            start = self._store_page_index * self._STORE_PAGE_SIZE
            end = start + self._STORE_PAGE_SIZE
            for plugin in filtered[start:end]:
                _state, status_text, status_color, action_text, action_enabled = self._store_action_state(plugin)
                card = StorePluginCard(
                    plugin,
                    status_text=status_text,
                    status_color=status_color,
                    action_text=action_text,
                    action_enabled=action_enabled,
                    parent=self._store_page,
                )
                self._store_visible_cards[plugin.stable_id] = card
                self._apply_store_card_icon(card, plugin)
                card.action_button().clicked.connect(
                    lambda _, pid=plugin.stable_id: self._install_store_plugin(pid)
                )
                if plugin.homepage:
                    card.homepage_button().clicked.connect(
                        lambda _, url=plugin.homepage: self._open_store_plugin_homepage(url)
                    )
                self._store_cards_layout.addWidget(card)

        self._store_page_lbl.setText(
            self._i18n.t(
                "plugin.store.page.label",
                default="第 {page}/{pages} 页",
                page=(self._store_page_index + 1) if total else 0,
                pages=page_count if total else 0,
            )
        )
        self._store_prev_btn.setEnabled(total > 0 and self._store_page_index > 0)
        self._store_next_btn.setEnabled(total > 0 and self._store_page_index < page_count - 1)

    def _open_store_plugin_homepage(self, url: str) -> None:
        if not url:
            return
        if not QDesktopServices.openUrl(QUrl(url)):
            InfoBar.warning(
                self._i18n.t("plugin.tab.store", default="商店"),
                self._i18n.t("plugin.store.homepage.fail", default="无法打开插件主页"),
                parent=self.window(),
                position=InfoBarPosition.TOP_RIGHT,
                duration=3500,
            )

    def _install_store_plugin(self, plugin_id: str) -> None:
        if not plugin_id or self._resource_service is None:
            return
        if not self._ensure_access("plugin.install", "安装或更新插件"):
            return
        if not self._ensure_managed_plugin_allowed(plugin_id):
            return
        if plugin_id in self._store_installing_ids:
            return
        self._store_installing_ids.add(plugin_id)
        self._refresh_store_cards()
        started = self._resource_service.install_store_plugin(plugin_id)
        if not started:
            self._store_installing_ids.discard(plugin_id)
            self._refresh_store_cards()

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
        perm_title = self._i18n.t(
            f"perm.{perm_key}",
            default=PERMISSION_NAMES.get(perm_key, perm_display),
        )
        extra = f"\n{reason}" if reason else ""
        toast = PermissionToastItem(
            self._i18n.t("plugin.toast.sys_req.title", icon=perm_title),
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
        self._clear_local_cards()

        known = self._mgr.all_known_plugins()
        self._rebuild_local_tag_filter(known)
        known_ids = {meta.id for meta, _enabled, _error, _dep_warning in known}
        self._local_selected_ids.intersection_update(known_ids)

        filtered = self._filtered_local_plugins(known)
        self._local_filtered_ids = [meta.id for meta, _enabled, _error, _dep_warning in filtered]
        self._refresh_local_select_ui()

        if not known:
            self._empty_lbl.setText(self._i18n.t("plugin.empty"))
            self._empty_lbl.show()
            self._refresh_store_cards()
            return
        if not filtered:
            self._empty_lbl.setText(
                self._i18n.t("plugin.local.empty.filtered", default="没有符合当前筛选条件的已安装插件。")
            )
            self._empty_lbl.show()
            self._refresh_store_cards()
            return

        self._empty_lbl.hide()
        for meta, enabled, error, dep_warning in filtered:
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
                selection_mode=self._local_select_mode,
                selected=(meta.id in self._local_selected_ids),
            )
            selector = card.selection_checkbox()
            if selector is not None:
                selector.checkStateChanged.connect(
                    lambda state, pid=meta.id: self._on_local_card_selected(
                        pid,
                        state == Qt.CheckState.Checked or state == Qt.CheckState.Checked.value,
                    )
                )
            card.switch.checkedChanged.connect(
                lambda checked, pid=meta.id, pname=meta.get_name(lang):
                    self._set_plugin_enabled_with_auth(pid, bool(checked), pname)
            )
            card.reload_button().clicked.connect(
                lambda _, pid=meta.id, pname=meta.get_name(lang): self._reload_plugin(pid, pname)
            )
            delete_btn = card.delete_button()
            if delete_btn is not None:
                delete_btn.clicked.connect(
                    lambda _, pid=meta.id, pname=(meta.get_name(lang) or meta.id): self._delete_local_plugin(pid, pname)
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

        self._refresh_store_cards()

    # ------------------------------------------------------------------ #

    def _set_plugin_enabled_with_auth(self, plugin_id: str, enabled: bool, plugin_name: str) -> None:
        action_text = "启用插件" if enabled else "禁用插件"
        if not self._ensure_access("plugin.manage", action_text):
            self._cards_dirty = True
            self._schedule_cards_reload()
            return
        if enabled and not self._ensure_managed_plugin_allowed(plugin_id):
            self._cards_dirty = True
            self._schedule_cards_reload()
            return
        self._mgr.set_enabled(plugin_id, enabled)

    def _change_sys_perm(self, pid: str, pname: str, perm_key: str) -> None:
        if not self._ensure_access("plugin.manage", "修改插件权限策略"):
            return
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
        if not self._ensure_access("plugin.manage", "热重载插件"):
            return
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

    def _delete_local_plugin(self, plugin_id: str, plugin_name: str) -> None:
        if not self._ensure_access("plugin.manage", "删除插件"):
            return
        display_name = plugin_name or plugin_id
        confirm = MessageBox(
            self._i18n.t("plugin.local.delete.confirm.title", default="确认删除插件"),
            self._i18n.t(
                "plugin.local.delete.confirm.content",
                default="将永久删除插件「{name}」，此操作不可撤销。是否继续？",
                name=display_name,
            ),
            self.window(),
        )
        confirm.yesButton.setText(self._i18n.t("plugin.local.delete.confirm.action", default="确认删除"))
        confirm.cancelButton.setText(self._i18n.t("common.cancel", default="取消"))
        confirm.yesButton.setStyleSheet("color: #d13438; font-weight: 600;")
        if not confirm.exec():
            return

        ok, message = self._mgr.delete_plugin(plugin_id)
        if not ok:
            InfoBar.error(
                self._i18n.t("plugin.title"),
                message or self._i18n.t("plugin.local.delete.fail", default="删除插件失败"),
                parent=self.window(),
                position=InfoBarPosition.TOP_RIGHT,
                duration=5000,
            )
            return

        self._local_selected_ids.discard(plugin_id)
        self._mgr.discover_and_load()
        self._cards_dirty = True
        self._schedule_cards_reload()
        self._refresh_store_cards()
        self._refresh_local_select_ui()

        InfoBar.success(
            self._i18n.t("plugin.title"),
            self._i18n.t(
                "plugin.local.delete.ok",
                default="已删除插件：{name}",
                name=display_name,
            ),
            parent=self.window(),
            position=InfoBarPosition.TOP_RIGHT,
            duration=3500,
        )

    # ------------------------------------------------------------------ #
    # 导入插件
    # ------------------------------------------------------------------ #

    def _do_import(self, paths: list[str]) -> None:
        """执行实际导入逻辑，paths 为文件/目录路径列表。"""
        if not paths:
            return
        if not self._ensure_access("plugin.install", "导入插件包"):
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
        """从插件包文件导入（.ltcplugin）。"""
        default_filter = _tr(
            f"插件包 (*{PLUGIN_PACKAGE_EXTENSION});;所有文件 (*)",
            f"Plugin package (*{PLUGIN_PACKAGE_EXTENSION});;All files (*)",
        )
        paths, _ = QFileDialog.getOpenFileNames(
            self.window(),
            self._i18n.t("plugin.dialog.choose_zip"),
            "",
            self._i18n.t("plugin.dialog.filter_zip", default=default_filter),
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
        if not self._ensure_access("plugin.manage", "重新扫描并加载插件"):
            return
        self._mgr.discover_and_load()
        self._load_cards()
        InfoBar.success(self._i18n.t("plugin.title"), self._i18n.t("plugin.scan.done"), parent=self.window(),
                        position=InfoBarPosition.TOP_RIGHT, duration=2000)


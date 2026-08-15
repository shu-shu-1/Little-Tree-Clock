"""世界时间视图"""
from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import (
    Qt, Slot, Signal, QPoint, QSize, QTimer, QMimeData,
    QEasingCurve, QParallelAnimationGroup, QPropertyAnimation,
)
from PySide6.QtGui import QKeyEvent, QColor, QPalette, QDrag, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QVBoxLayout, QHBoxLayout, QWidget, QFileDialog,
    QFrame, QSizePolicy, QPushButton, QAbstractButton,
    QSlider,
)
from qfluentwidgets import (
    SmoothScrollArea, FluentIcon as FIF, PushButton, Theme,
    CardWidget, BodyLabel, TitleLabel, CaptionLabel, SubtitleLabel,
    ComboBox, RoundMenu, Action,
    TransparentToolButton, ColorPickerButton, SpinBox,
    InfoBar, InfoBarPosition, MessageBox, LineEdit,
)

from app.constants import PRESET_TIMEZONES, SHOW_WATERMARK
from app.widgets.watermark import WatermarkOverlay
from app.models.world_zone import WorldZone, WorldZoneStore
from app.services.background_canvas_service import BackgroundCanvasService
from app.services.clock_service import ClockService
from app.services.central_control_service import CentralControlService
from app.services.i18n_service import I18nService
from app.services.permission_service import PermissionService
from app.services.recommendation_service import (
    RecommendationService,
    build_fullscreen_clock_feature,
    fullscreen_clock_feature_label,
)
from app.services.settings_service import SettingsService
from app.services.world_zone_service import format_zone_display_name, get_localized_timezone_name
from app.services import url_scheme_service as uss
from app.utils.fs import mkdir_with_uac, write_text_with_uac
from app.utils.time_utils import now_in_zone, format_time, format_date, utc_offset_str
from app.utils.logger import logger


def _drag_distance_threshold() -> int:
    app = QApplication.instance()
    if app is None:
        return 10
    try:
        return int(app.startDragDistance())
    except Exception:
        return 10


def _local_offset_diff_str(zone_tz: str) -> str:
    """返回目标时区与本地时区的差值字符串，如 '+3h'、'-5h 30m'、'(本地时间)'"""
    i18n = I18nService.instance()
    local_text = i18n.t("world_time.local", default="(本地时间)")
    now_local = datetime.now().astimezone()
    if zone_tz == "local":
        return local_text
    try:
        from app.utils.time_utils import now_in_zone as _nizone
        now_zone = _nizone(zone_tz)
    except Exception:
        return ""

    local_off = now_local.utcoffset()
    zone_off  = now_zone.utcoffset()
    if local_off is None or zone_off is None:
        return ""
    diff_secs = int((zone_off - local_off).total_seconds())
    if diff_secs == 0:
        return local_text
    sign = "+" if diff_secs > 0 else "-"
    diff_secs = abs(diff_secs)
    hours, rem = divmod(diff_secs, 3600)
    minutes = rem // 60
    if minutes:
        return f"{sign}{hours}h {minutes}m"
    return f"{sign}{hours}h"


_INVALID_WIN_FILENAME_RE = re.compile(r'[<>:"/\\|?*]+')


def _desktop_shortcut_supported() -> bool:
    return sys.platform == "win32"


def _get_desktop_path() -> Path:
    import winreg  # type: ignore[import-not-found]

    key = winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders",
    )
    try:
        desktop = winreg.QueryValueEx(key, "Desktop")[0]
    finally:
        winreg.CloseKey(key)
    return Path(str(desktop))


def _desktop_shortcut_dir() -> Path:
    if _desktop_shortcut_supported():
        try:
            desktop = _get_desktop_path()
            logger.debug("通过注册表读取桌面路径: {}", desktop)
            return desktop
        except Exception:
            logger.exception("通过注册表读取桌面路径失败，回退到 Home/Desktop")

    return Path.home() / "Desktop"


def _safe_shortcut_filename(zone_name: str) -> str:
    i18n = I18nService.instance()
    is_en = i18n.language == "en-US"
    default_name = i18n.t(
        "world_time.shortcut.file_default",
        default="Fullscreen Clock" if is_en else "全屏时钟",
    )
    prefix = i18n.t(
        "world_time.shortcut.file_prefix",
        default="Little Tree Clock" if is_en else "小树时钟",
    )
    raw_name = str(zone_name or default_name).strip() or default_name
    safe = _INVALID_WIN_FILENAME_RE.sub("_", raw_name).rstrip(". ").strip() or default_name
    safe = re.sub(r"\s+", " ", safe)
    return f"{prefix} - {safe}.url"


def _create_fullscreen_desktop_shortcut(zone_id: str, zone_name: str) -> tuple[bool, str]:
    i18n = I18nService.instance()
    if not _desktop_shortcut_supported():
        return False, i18n.t("world_time.desktop_shortcut.unsupported")

    desktop_dir = _desktop_shortcut_dir()
    logger.info("创建桌面快捷方式: zone_id='{}', zone_name='{}', desktop='{}'", zone_id, zone_name, desktop_dir)

    try:
        if desktop_dir.exists() and not desktop_dir.is_dir():
            msg = i18n.t("world_time.shortcut.failed.content", detail=f"desktop path is not a directory: {desktop_dir}")
            logger.error(msg)
            return False, msg
    except Exception as exc:
        logger.exception("读取桌面路径状态失败: {}", desktop_dir)
        return False, str(exc)

    shortcut_path = desktop_dir / _safe_shortcut_filename(zone_name)
    if shortcut_path.exists() and shortcut_path.is_dir():
        base_stem = shortcut_path.stem
        for i in range(2, 100):
            candidate = desktop_dir / f"{base_stem} ({i}).url"
            if not candidate.exists():
                shortcut_path = candidate
                break

    url = uss.build_fullscreen_url(zone_id)
    lines = ["[InternetShortcut]", f"URL={url}"]
    try:
        lines.append(f"IconFile={Path(sys.executable).resolve()}")
        lines.append("IconIndex=0")
    except Exception:
        logger.exception("解析程序图标路径失败，将使用系统默认图标")

    try:
        if not desktop_dir.exists():
            mkdir_with_uac(desktop_dir, parents=True, exist_ok=True)
        write_text_with_uac(
            shortcut_path,
            "\n".join(lines) + "\n",
            encoding="utf-8",
            ensure_parent=True,
        )
        logger.success("桌面快捷方式创建成功: {}", shortcut_path)
        return True, str(shortcut_path)
    except Exception as exc:
        logger.exception("创建桌面快捷方式失败: desktop='{}', target='{}'", desktop_dir, shortcut_path)
        return False, str(exc)


class _RenameZoneDialog(MessageBox):
    def __init__(self, *, current_name: str, actual_name: str, i18n: I18nService, parent=None):
        super().__init__(
            i18n.t("world_time.rename", default="编辑名称"),
            "",
            parent,
        )
        self._i18n = i18n
        self._actual_name = str(actual_name or "").strip()
        self.widget.setMinimumWidth(460)
        self.yesButton.setText(i18n.t("common.save", default="保存"))
        self.cancelButton.setText(i18n.t("common.cancel", default="取消"))
        self.contentLabel.hide()

        prompt = BodyLabel(
            i18n.t(
                "world_time.rename.prompt",
                default="输入显示名称；留空时显示实际时区/本地时间。",
            )
        )
        prompt.setWordWrap(True)
        prompt.setMinimumHeight(prompt.fontMetrics().lineSpacing() * 2 + 8)
        self.textLayout.addWidget(prompt)

        self._actual_label = CaptionLabel("")
        self._actual_label.setWordWrap(True)
        self._actual_label.setMinimumHeight(self._actual_label.fontMetrics().lineSpacing() * 2 + 8)
        self.textLayout.addWidget(self._actual_label)

        self._name_edit = LineEdit()
        self._name_edit.setPlaceholderText(self._actual_name)
        self._name_edit.setText(current_name)
        self._name_edit.textChanged.connect(self._refresh_actual_preview)
        self.textLayout.addWidget(self._name_edit)

        self._refresh_actual_preview()

    def _preview_name(self) -> str:
        custom_name = self.shown_name()
        if custom_name and self._actual_name and custom_name != self._actual_name:
            return f"{custom_name} ({self._actual_name})"
        return custom_name or self._actual_name

    def _refresh_actual_preview(self) -> None:
        self._actual_label.setText(
            self._i18n.t(
                "world_time.rename.actual",
                default="实际显示：{name}",
                name=self._preview_name(),
            )
        )

    def shown_name(self) -> str:
        return self._name_edit.text().strip()


class _CanvasCustomizePanel(QFrame):
    """画布级自定义设置浮动面板。"""

    def __init__(self, zone_id: str, parent=None):
        super().__init__(parent)
        self._zone_id = zone_id
        self.on_changed = None
        self.setObjectName("canvasCustomizePanel")
        self.setFixedSize(400, 400)
        self.hide()
        self._build_ui()
        self._apply_theme()
        self._load_settings()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        i18n = I18nService.instance()
        self._i18n_ref = i18n

        title = BodyLabel(i18n.t("world_time.fs.customize.title"))
        title.setStyleSheet("font-size:14px; font-weight:bold;")
        layout.addWidget(title)

        # 深浅色
        theme_row = QHBoxLayout()
        theme_lbl = BodyLabel(i18n.t("world_time.fs.customize.theme"))
        theme_lbl.setFixedWidth(72)
        self._theme_combo = ComboBox()
        self._theme_combo.addItems([
            i18n.t("world_time.fs.customize.theme.app"),
            i18n.t("world_time.fs.customize.theme.system"),
            i18n.t("world_time.fs.customize.theme.dark"),
            i18n.t("world_time.fs.customize.theme.light"),
        ])
        self._theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        theme_row.addWidget(theme_lbl)
        theme_row.addWidget(self._theme_combo, 1)
        layout.addLayout(theme_row)

        # 背景颜色
        bg_row = QHBoxLayout()
        bg_lbl = BodyLabel(i18n.t("world_time.fs.customize.bg_color"))
        bg_lbl.setFixedWidth(72)
        self._bg_color_btn = ColorPickerButton(QColor("#080808"), "", self.window())
        self._bg_color_btn.setFixedSize(52, 32)
        self._bg_color_btn.colorChanged.connect(self._on_bg_color_changed)
        self._bg_color_clear = QPushButton(i18n.t("world_time.fs.customize.clear"))
        self._bg_color_clear.setFixedHeight(32)
        self._bg_color_clear.clicked.connect(self._on_bg_color_clear)
        bg_row.addWidget(bg_lbl)
        bg_row.addWidget(self._bg_color_btn)
        bg_row.addStretch()
        bg_row.addWidget(self._bg_color_clear)
        layout.addLayout(bg_row)

        # 背景图片
        img_row = QHBoxLayout()
        img_lbl = BodyLabel(i18n.t("world_time.fs.customize.bg_image"))
        img_lbl.setFixedWidth(72)
        self._img_path_edit = LineEdit()
        self._img_path_edit.setPlaceholderText(i18n.t("world_time.fs.customize.bg_image_hint"))
        self._img_path_edit.setReadOnly(True)
        self._img_browse_btn = QPushButton(i18n.t("world_time.fs.customize.browse"))
        self._img_browse_btn.setFixedHeight(32)
        self._img_browse_btn.clicked.connect(self._on_browse_image)
        self._img_clear_btn = QPushButton(i18n.t("world_time.fs.customize.clear"))
        self._img_clear_btn.setFixedHeight(32)
        self._img_clear_btn.clicked.connect(self._on_clear_image)
        img_row.addWidget(img_lbl)
        img_row.addWidget(self._img_path_edit, 1)
        img_row.addWidget(self._img_browse_btn)
        img_row.addWidget(self._img_clear_btn)
        layout.addLayout(img_row)

        # 背景图片缩放方式
        scale_row = QHBoxLayout()
        scale_lbl = BodyLabel(i18n.t("world_time.fs.customize.bg_scale"))
        scale_lbl.setFixedWidth(72)
        self._scale_combo = ComboBox()
        self._scale_combo.addItems([
            i18n.t("world_time.fs.customize.bg_scale.fill"),
            i18n.t("world_time.fs.customize.bg_scale.fit"),
            i18n.t("world_time.fs.customize.bg_scale.stretch"),
        ])
        self._scale_combo.currentIndexChanged.connect(self._on_scale_changed)
        scale_row.addWidget(scale_lbl)
        scale_row.addWidget(self._scale_combo, 1)
        layout.addLayout(scale_row)

        # 网格线颜色
        grid_row = QHBoxLayout()
        grid_lbl = BodyLabel(i18n.t("world_time.fs.customize.grid_color"))
        grid_lbl.setFixedWidth(72)
        self._grid_color_btn = ColorPickerButton(QColor("#cccccc"), "", self.window())
        self._grid_color_btn.setFixedSize(52, 32)
        self._grid_color_btn.colorChanged.connect(self._on_grid_color_changed)
        self._grid_color_clear = QPushButton(i18n.t("world_time.fs.customize.clear"))
        self._grid_color_clear.setFixedHeight(32)
        self._grid_color_clear.clicked.connect(self._on_grid_color_clear)
        grid_row.addWidget(grid_lbl)
        grid_row.addWidget(self._grid_color_btn)
        grid_row.addStretch()
        grid_row.addWidget(self._grid_color_clear)
        layout.addLayout(grid_row)

        # 背景图片遮罩颜色
        overlay_color_row = QHBoxLayout()
        overlay_color_lbl = BodyLabel(i18n.t("world_time.fs.customize.bg_overlay_color"))
        overlay_color_lbl.setFixedWidth(72)
        self._overlay_color_btn = ColorPickerButton(QColor("#000000"), "", self.window())
        self._overlay_color_btn.setFixedSize(52, 32)
        self._overlay_color_btn.colorChanged.connect(self._on_overlay_color_changed)
        self._overlay_color_clear = QPushButton(i18n.t("world_time.fs.customize.clear"))
        self._overlay_color_clear.setFixedHeight(32)
        self._overlay_color_clear.clicked.connect(self._on_overlay_color_clear)
        overlay_color_row.addWidget(overlay_color_lbl)
        overlay_color_row.addWidget(self._overlay_color_btn)
        overlay_color_row.addStretch()
        overlay_color_row.addWidget(self._overlay_color_clear)
        layout.addLayout(overlay_color_row)

        # 背景图片遮罩透明度
        overlay_opacity_row = QHBoxLayout()
        overlay_opacity_lbl = BodyLabel(i18n.t("world_time.fs.customize.bg_overlay_opacity"))
        overlay_opacity_lbl.setFixedWidth(72)
        self._overlay_opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._overlay_opacity_slider.setMinimumHeight(22)
        self._overlay_opacity_slider.setRange(0, 100)
        self._overlay_opacity_slider.setSingleStep(5)
        self._overlay_opacity_slider.setPageStep(10)
        self._overlay_opacity_slider.valueChanged.connect(self._on_overlay_opacity_changed)
        self._overlay_opacity_val_lbl = CaptionLabel("0%")
        self._overlay_opacity_val_lbl.setFixedWidth(40)
        overlay_opacity_row.addWidget(overlay_opacity_lbl)
        overlay_opacity_row.addWidget(self._overlay_opacity_slider, 1)
        overlay_opacity_row.addWidget(self._overlay_opacity_val_lbl)
        layout.addLayout(overlay_opacity_row)

        layout.addStretch()

    def _i18n(self, key: str) -> str:
        return I18nService.instance().t(key)

    def _apply_theme(self):
        from app.utils.theme_utils import widget_colors, is_widget_dark
        c = widget_colors(self._zone_id)
        dark = is_widget_dark(self._zone_id)
        panel_bg = "rgb(30,30,30)" if dark else "rgb(248,248,248)"
        self.setStyleSheet(
            f"QFrame#canvasCustomizePanel{{"
            f"background:{panel_bg};"
            f"border:1px solid {c['border']};"
            f"border-radius:12px;}}"
        )
        text_color = c["primary"]
        for lbl in self.findChildren(BodyLabel):
            lbl.setStyleSheet(f"color:{text_color}; background:transparent;")
        self._overlay_opacity_val_lbl.setStyleSheet(
            f"color:{text_color}; background:transparent;"
        )

        groove_color = "rgba(255,255,255,115)" if dark else "rgba(0,0,0,100)"
        handle_bg = "rgb(69,69,69)" if dark else "white"
        handle_border = "rgba(0,0,0,90)" if dark else "rgba(0,0,0,25)"
        self._overlay_opacity_slider.setStyleSheet(
            "QSlider::groove:horizontal {"
            f"background:{groove_color}; height:4px; border-radius:2px;"
            "}"
            "QSlider::sub-page:horizontal {"
            f"background:{c['accent']}; border-radius:2px;"
            "}"
            "QSlider::handle:horizontal {"
            f"background:{handle_bg}; border:1px solid {handle_border};"
            "width:18px; height:18px; margin:-7px 0; border-radius:9px;"
            "}"
        )

    def _load_settings(self):
        from app.widgets.layout_store import WidgetLayoutStore
        cs = WidgetLayoutStore.instance().get_canvas_settings(self._zone_id)

        theme = cs.get("theme", "global")
        theme_map = {"global": 0, "system": 1, "dark": 2, "light": 3}
        self._theme_combo.setCurrentIndex(theme_map.get(theme, 0))

        bg_color = cs.get("bg_color", "")
        if bg_color:
            self._bg_color_btn.setColor(QColor(bg_color))
        else:
            from app.utils.theme_utils import widget_colors
            self._bg_color_btn.setColor(QColor(widget_colors(self._zone_id)["canvas_bg"]))

        bg_image = cs.get("bg_image", "")
        self._img_path_edit.setText(bg_image)

        scale = cs.get("bg_scale", "fill")
        scale_map = {"fill": 0, "fit": 1, "stretch": 2}
        self._scale_combo.setCurrentIndex(scale_map.get(scale, 0))

        grid_color = cs.get("grid_color", "")
        if grid_color:
            self._grid_color_btn.setColor(QColor(grid_color))
        else:
            from app.utils.theme_utils import widget_colors
            self._grid_color_btn.setColor(QColor(widget_colors(self._zone_id)["grid_line"]))

        overlay_color = cs.get("bg_overlay_color", "")
        if overlay_color:
            self._overlay_color_btn.setColor(QColor(overlay_color))
        else:
            self._overlay_color_btn.setColor(QColor("#000000"))

        overlay_opacity = cs.get("bg_overlay_opacity", 0)
        self._overlay_opacity_slider.setValue(overlay_opacity)
        self._overlay_opacity_val_lbl.setText(f"{overlay_opacity}%")

    def _save(self, **overrides):
        from app.widgets.layout_store import WidgetLayoutStore
        store = WidgetLayoutStore.instance()
        cs = store.get_canvas_settings(self._zone_id)
        cs.update(overrides)
        for k in ("bg_color", "bg_image", "grid_color", "bg_overlay_color"):
            if k in cs and not cs[k]:
                del cs[k]
        if cs.get("theme") == "global":
            del cs["theme"]
        store.save_canvas_settings(self._zone_id, cs)
        if self.on_changed:
            self.on_changed()

    def _on_theme_changed(self, index):
        themes = ["global", "system", "dark", "light"]
        self._save(theme=themes[index])
        self._apply_theme()

    def _on_bg_color_changed(self, color: QColor):
        self._save(bg_color=color.name())

    def _on_bg_color_clear(self):
        self._save(bg_color="")
        from app.utils.theme_utils import widget_colors
        self._bg_color_btn.setColor(QColor(widget_colors(self._zone_id)["canvas_bg"]))

    def _on_browse_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self.window(),
            self._i18n_ref.t("world_time.fs.customize.bg_image"),
            "",
            "Images (*.png *.jpg *.jpeg *.bmp *.webp *.gif);;All Files (*)",
        )
        if path:
            self._img_path_edit.setText(path)
            self._save(bg_image=path)

    def _on_clear_image(self):
        self._img_path_edit.setText("")
        self._save(bg_image="")

    def _on_scale_changed(self, index):
        modes = ["fill", "fit", "stretch"]
        self._save(bg_scale=modes[index])

    def _on_grid_color_changed(self, color: QColor):
        self._save(grid_color=color.name())

    def _on_grid_color_clear(self):
        self._save(grid_color="")
        from app.utils.theme_utils import widget_colors
        self._grid_color_btn.setColor(QColor(widget_colors(self._zone_id)["grid_line"]))

    def _on_overlay_color_changed(self, color: QColor):
        self._save(bg_overlay_color=color.name())

    def _on_overlay_color_clear(self):
        self._save(bg_overlay_color="")
        self._overlay_color_btn.setColor(QColor("#000000"))

    def _on_overlay_opacity_changed(self, value: int):
        self._overlay_opacity_val_lbl.setText(f"{value}%")
        self._save(bg_overlay_opacity=value)


class FullscreenClockWindow(QWidget):
    """全屏可编辑小组件画布窗口。

    - Esc / 右上角 ✕ ：退出全屏
    - Tab / 右上角"编辑"按钮：切换编辑模式
    - H / 右上角收起按钮：隐藏/显示顶栏
    - 编辑模式：显示网格线，组件可拖拽，右键编辑/删除，可添加组件
    """

    def __init__(
        self,
        zone: WorldZone,
        clock_service: ClockService | None = None,
        plugin_manager=None,
        notification_service=None,
        permission_service: PermissionService | None = None,
        automation_engine=None,
        parent=None,
    ):
        super().__init__(parent)
        self._zone          = zone
        self._clock_service = clock_service
        self._notif_service = notification_service
        self._plugin_manager = plugin_manager
        self._permission_service = permission_service
        self._automation_engine = automation_engine
        self._plugin_refresh_scheduled = False
        self._layout_reload_scheduled = False
        self._reco_feature_id = build_fullscreen_clock_feature(zone.id)
        self._reco_session_started = False
        self._i18n = I18nService.instance()

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAutoFillBackground(True)
        self._bg_pixmap = None
        self._bg_image_path = None
        self._apply_canvas_bg()

        # ── 画布（占满全屏）──
        from app.widgets.canvas import WidgetCanvas
        services = {
            "timezone":            zone.timezone,
            "clock_service":       clock_service,
            "notification_service": notification_service,
            "fullscreen_window":   self,
            "permission_service":  permission_service,
            "automation_engine":   self._automation_engine,
        }
        # 延迟分批加载组件，提升全屏打开速度
        self._canvas = WidgetCanvas(zone.id, services, plugin_manager, self, lazy_load=True)

        # ── 顶栏覆盖层 ──
        self._topbar_visible = True
        self._topbar = QFrame(self)
        self._topbar.setObjectName("fsTopBar")
        self._topbar.setStyleSheet(
            f"QFrame#fsTopBar{{background:{self._fs_c('topbar_bg')};"
            f"border-bottom:1px solid {self._fs_c('bar_border')};}}"
        )
        tb = QHBoxLayout(self._topbar)
        tb.setContentsMargins(16, 0, 12, 0)
        tb.setSpacing(6)

        # 城市名
        self._zone_lbl = SubtitleLabel(format_zone_display_name(zone, fallback=zone.id))
        self._zone_lbl.setStyleSheet(
            f"color:{self._fs_c('secondary')}; background:transparent;"
        )

        # 编辑切换按钮
        self._edit_btn = QPushButton(
            FIF.EDIT.icon(self._fs_icon_theme()),
            self._i18n.t("world_time.fs.edit"),
        )
        self._edit_btn.setIconSize(QSize(16, 16))
        self._edit_btn.setStyleSheet(
            f"QPushButton{{"
            f"color:{self._fs_c('btn_text')};"
            f"background:{self._fs_c('btn_bg')};"
            f"border:1px solid {self._fs_c('border')};"
            f"border-radius:8px;"
            f"padding:5px 14px;"
            f"font-size:13px;}}"
            f"QPushButton:hover{{"
            f"background:{self._fs_c('btn_bg_hover')};}}"
            f"QPushButton:pressed{{"
            f"background:{self._fs_c('btn_bg_press')};}}"
        )
        self._edit_btn.clicked.connect(self._toggle_edit)

        # 顶栏显示/隐藏切换按钮
        self._topbar_toggle_btn = QPushButton(FIF.UP.icon(self._fs_icon_theme()), "")
        self._topbar_toggle_btn.setIconSize(QSize(14, 14))
        self._topbar_toggle_btn.setFixedSize(36, 36)
        self._topbar_toggle_btn.setStyleSheet(
            f"QPushButton{{"
            f"background:{self._fs_c('btn_bg_dis')};"
            f"border:1px solid {self._fs_c('border')};"
            f"border-radius:8px;}}"
            f"QPushButton:hover{{"
            f"background:{self._fs_c('btn_bg_hover')};}}"
            f"QPushButton:pressed{{"
            f"background:{self._fs_c('btn_bg_press')};}}"
        )
        self._topbar_toggle_btn.clicked.connect(self._toggle_topbar)
        self._topbar_toggle_btn.setToolTip(self._i18n.t("world_time.fs.hide_topbar"))

        # 关闭按钮
        self._close_btn = QPushButton(FIF.CLOSE.icon(self._fs_icon_theme()), "")
        self._close_btn.setIconSize(QSize(14, 14))
        self._close_btn.setFixedSize(36, 36)
        self._close_btn.setStyleSheet(
            f"QPushButton{{"
            f"background:{self._fs_c('btn_bg_dis')};"
            f"border:1px solid {self._fs_c('border')};"
            f"border-radius:8px;}}"
            f"QPushButton:hover{{"
            f"background:{self._fs_c('close_hover')};"
            f"border-color:transparent;}}"
            f"QPushButton:pressed{{"
            f"background:{self._fs_c('close_press')};}}"
        )
        self._close_btn.clicked.connect(self.close)
        self._close_btn.setToolTip(self._i18n.t("world_time.fs.close"))

        tb.addWidget(self._zone_lbl)
        tb.addStretch()
        self._plugin_btn_host = QWidget(self._topbar)
        self._plugin_btn_layout = QHBoxLayout(self._plugin_btn_host)
        self._plugin_btn_layout.setContentsMargins(0, 0, 0, 0)
        self._plugin_btn_layout.setSpacing(6)
        tb.addWidget(self._plugin_btn_host)
        tb.addWidget(self._edit_btn)
        tb.addWidget(self._topbar_toggle_btn)
        tb.addWidget(self._close_btn)
        self._refresh_plugin_topbar_buttons()

        # ── 顶栏隐藏后的迷你浮动控件（仅保留切换+关闭按钮）──
        self._mini_bar = QFrame(self)
        self._mini_bar.setObjectName("fsMiniBar")
        self._mini_bar.setStyleSheet(
            f"QFrame#fsMiniBar{{background:{self._fs_c('topbar_bg')};"
            f"border:1px solid {self._fs_c('bar_border')};"
            f"border-radius:10px;}}"
        )
        mb = QHBoxLayout(self._mini_bar)
        mb.setContentsMargins(6, 4, 6, 4)
        mb.setSpacing(4)

        self._mini_toggle_btn = QPushButton(FIF.DOWN.icon(self._fs_icon_theme()), "")
        self._mini_toggle_btn.setIconSize(QSize(14, 14))
        self._mini_toggle_btn.setFixedSize(32, 32)
        self._mini_toggle_btn.setStyleSheet(
            f"QPushButton{{"
            f"background:{self._fs_c('btn_bg_dis')};"
            f"border:1px solid {self._fs_c('border')};"
            f"border-radius:8px;}}"
            f"QPushButton:hover{{"
            f"background:{self._fs_c('btn_bg_hover')};}}"
            f"QPushButton:pressed{{"
            f"background:{self._fs_c('btn_bg_press')};}}"
        )
        self._mini_toggle_btn.clicked.connect(self._toggle_topbar)
        self._mini_toggle_btn.setToolTip(self._i18n.t("world_time.fs.show_topbar"))

        self._mini_close_btn = QPushButton(FIF.CLOSE.icon(self._fs_icon_theme()), "")
        self._mini_close_btn.setIconSize(QSize(14, 14))
        self._mini_close_btn.setFixedSize(32, 32)
        self._mini_close_btn.setStyleSheet(
            f"QPushButton{{"
            f"background:{self._fs_c('btn_bg_dis')};"
            f"border:1px solid {self._fs_c('border')};"
            f"border-radius:8px;}}"
            f"QPushButton:hover{{"
            f"background:{self._fs_c('close_hover')};"
            f"border-color:transparent;}}"
            f"QPushButton:pressed{{"
            f"background:{self._fs_c('close_press')};}}"
        )
        self._mini_close_btn.clicked.connect(self.close)
        self._mini_close_btn.setToolTip(self._i18n.t("world_time.fs.close"))

        mb.addWidget(self._mini_toggle_btn)
        mb.addWidget(self._mini_close_btn)
        self._mini_bar.hide()

        # 底部提示
        self._hint_lbl = CaptionLabel(self._i18n.t("world_time.fs.hint"))
        self._hint_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint_lbl.setStyleSheet(
            f"color:{self._fs_c('hint_text')}; background:transparent;"
        )
        self._hint_lbl.setParent(self)

        # 画布自定义按钮
        self._customize_btn = QPushButton(FIF.PALETTE.icon(self._fs_icon_theme()), "")
        self._customize_btn.setIconSize(QSize(16, 16))
        self._customize_btn.setFixedSize(36, 36)
        self._customize_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._customize_btn.setStyleSheet(
            f"QPushButton{{"
            f"background:{self._fs_c('btn_bg_dis')};"
            f"border:1px solid {self._fs_c('border')};"
            f"border-radius:8px;}}"
            f"QPushButton:hover{{background:{self._fs_c('btn_bg_hover')};}}"
            f"QPushButton:pressed{{background:{self._fs_c('btn_bg_press')};}}"
        )
        self._customize_btn.clicked.connect(self._toggle_customize_panel)
        self._customize_btn.setToolTip(self._i18n.t("world_time.fs.customize"))
        self._customize_btn.setParent(self)

        # 画布自定义面板
        self._customize_panel = None

        # 测试版水印
        if SHOW_WATERMARK:
            from app.services.settings_service import SettingsService as _SS
            self._watermark = WatermarkOverlay(self)
            self._watermark.setGeometry(self.rect())
            _wm_settings = _SS.instance()
            self._watermark.setVisible(_wm_settings.watermark_worldtime_visible)
            self._watermark.raise_()
            _wm_settings.changed.connect(self._apply_watermark_visibility)
        # topbar 和提示始终在水印之上
        self._topbar.raise_()
        self._hint_lbl.raise_()

        # 连接时钟
        if clock_service:
            clock_service.secondTick.connect(self._canvas.refresh_all)

        from app.services.settings_service import SettingsService
        SettingsService.instance().changed.connect(self._reapply_theme)

        app = QApplication.instance()
        self._system_theme_hints = app.styleHints() if app is not None else None
        if self._system_theme_hints is not None:
            self._system_theme_hints.colorSchemeChanged.connect(
                self._on_system_color_scheme_changed
            )

    def _start_recommendation_session(self) -> None:
        if self._reco_session_started:
            return
        try:
            RecommendationService.instance().on_session_start(
                self._reco_feature_id,
                label=fullscreen_clock_feature_label(
                    format_zone_display_name(self._zone, fallback=self._zone.id)
                ),
            )
            self._reco_session_started = True
        except Exception:
            logger.exception("[世界时间全屏] 记录推荐会话开始失败: zone_id={}", self._zone.id)

    def _end_recommendation_session(self) -> None:
        if not self._reco_session_started:
            return
        try:
            RecommendationService.instance().on_session_end(self._reco_feature_id)
        except Exception:
            logger.exception("[世界时间全屏] 记录推荐会话结束失败: zone_id={}", self._zone.id)
        finally:
            self._reco_session_started = False

    def _fs_c(self, key: str) -> str:
        from app.utils.theme_utils import widget_colors
        return widget_colors(self._zone.id).get(key, "#888")

    def _fs_icon_theme(self):
        from app.utils.theme_utils import is_widget_dark
        return Theme.DARK if is_widget_dark(self._zone.id) else Theme.LIGHT

    def _apply_canvas_bg(self) -> None:
        from app.utils.theme_utils import widget_colors
        from app.widgets.layout_store import WidgetLayoutStore
        c = widget_colors(self._zone.id)
        cs = WidgetLayoutStore.instance().get_canvas_settings(self._zone.id)
        bg_image = cs.get("bg_image")
        self._bg_image_path = bg_image
        self._bg_pixmap = None
        if bg_image:
            from pathlib import Path
            p = Path(bg_image)
            if p.exists():
                from PySide6.QtGui import QPixmap
                self._bg_pixmap = QPixmap(str(p))
        self._bg_overlay_color = cs.get("bg_overlay_color", "")
        self._bg_overlay_opacity = cs.get("bg_overlay_opacity", 0)
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(c["canvas_bg"]))
        self.setPalette(palette)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        wr = self.rect()
        if self._bg_pixmap and not self._bg_pixmap.isNull():
            from app.widgets.layout_store import WidgetLayoutStore
            cs = WidgetLayoutStore.instance().get_canvas_settings(self._zone.id)
            scale_mode = cs.get("bg_scale", "fill")
            pm = self._bg_pixmap
            if scale_mode == "fit":
                scaled = pm.scaled(wr.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                x = (wr.width() - scaled.width()) // 2
                y = (wr.height() - scaled.height()) // 2
                painter.drawPixmap(x, y, scaled)
            elif scale_mode == "stretch":
                scaled = pm.scaled(wr.size(), Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
                painter.drawPixmap(0, 0, scaled)
            else:
                scaled = pm.scaled(wr.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
                x = (wr.width() - scaled.width()) // 2
                y = (wr.height() - scaled.height()) // 2
                painter.drawPixmap(x, y, scaled)
        overlay_color = getattr(self, "_bg_overlay_color", "")
        overlay_opacity = getattr(self, "_bg_overlay_opacity", 0)
        if overlay_opacity > 0:
            color = QColor(overlay_color or "#000000")
            color.setAlpha(int(overlay_opacity * 255 / 100))
            painter.fillRect(wr, color)
        painter.end()

    def _reapply_theme(self) -> None:
        from app.utils.theme_utils import widget_colors
        c = widget_colors(self._zone.id)
        icon_t = self._fs_icon_theme()

        self._apply_canvas_bg()

        self._topbar.setStyleSheet(
            f"QFrame#fsTopBar{{background:{c['topbar_bg']};"
            f"border-bottom:1px solid {c['bar_border']};}}"
        )
        self._zone_lbl.setStyleSheet(f"color:{c['secondary']}; background:transparent;")

        self._edit_btn.setIcon(FIF.EDIT.icon(icon_t) if not self._canvas.edit_mode else FIF.ACCEPT.icon(icon_t))
        self._edit_btn.setStyleSheet(
            f"QPushButton{{"
            f"color:{c['btn_text']};"
            f"background:{c['btn_bg']};"
            f"border:1px solid {c['border']};"
            f"border-radius:8px;"
            f"padding:5px 14px;"
            f"font-size:13px;}}"
            f"QPushButton:hover{{background:{c['btn_bg_hover']};}}"
            f"QPushButton:pressed{{background:{c['btn_bg_press']};}}"
        )

        for btn in (self._topbar_toggle_btn, self._mini_toggle_btn):
            btn.setStyleSheet(
                f"QPushButton{{"
                f"background:{c['btn_bg_dis']};"
                f"border:1px solid {c['border']};"
                f"border-radius:8px;}}"
                f"QPushButton:hover{{background:{c['btn_bg_hover']};}}"
                f"QPushButton:pressed{{background:{c['btn_bg_press']};}}"
            )

        self._topbar_toggle_btn.setIcon(FIF.UP.icon(icon_t))
        self._mini_toggle_btn.setIcon(FIF.DOWN.icon(icon_t))

        for btn in (self._close_btn, self._mini_close_btn):
            btn.setStyleSheet(
                f"QPushButton{{"
                f"background:{c['btn_bg_dis']};"
                f"border:1px solid {c['border']};"
                f"border-radius:8px;}}"
                f"QPushButton:hover{{background:{c['close_hover']};"
                f"border-color:transparent;}}"
                f"QPushButton:pressed{{background:{c['close_press']};}}"
            )
        self._close_btn.setIcon(FIF.CLOSE.icon(icon_t))
        self._mini_close_btn.setIcon(FIF.CLOSE.icon(icon_t))

        self._mini_bar.setStyleSheet(
            f"QFrame#fsMiniBar{{background:{c['topbar_bg']};"
            f"border:1px solid {c['bar_border']};"
            f"border-radius:10px;}}"
        )

        self._hint_lbl.setStyleSheet(f"color:{c['hint_text']}; background:transparent;")
        self._customize_btn.setStyleSheet(
            f"QPushButton{{"
            f"background:{c['btn_bg_dis']};"
            f"border:1px solid {c['border']};"
            f"border-radius:8px;}}"
            f"QPushButton:hover{{background:{c['btn_bg_hover']};}}"
            f"QPushButton:pressed{{background:{c['btn_bg_press']};}}"
        )
        self._customize_btn.setIcon(FIF.PALETTE.icon(icon_t))
        self._canvas.refresh_theme()
        if self._customize_panel is not None:
            self._customize_panel._apply_theme()
        self._refresh_plugin_topbar_buttons()

    def _on_system_color_scheme_changed(self, _scheme) -> None:
        from app.utils.theme_utils import invalidate_widget_color_cache

        invalidate_widget_color_cache(self._zone.id)
        self._reapply_theme()

    def _toggle_customize_panel(self) -> None:
        if self._customize_panel is not None and self._customize_panel.isVisible():
            self._customize_panel.hide()
            self._customize_panel = None
            return
        self._customize_panel = _CanvasCustomizePanel(self._zone.id, self)
        self._customize_panel.on_changed = self._on_canvas_customized
        btn = self._customize_btn
        panel = self._customize_panel
        px = btn.x() - panel.width() + btn.width()
        py = btn.y() - panel.height() - 4
        if px < 4:
            px = 4
        if py < 4:
            py = btn.y() + btn.height() + 4
        panel.move(px, py)
        panel.show()
        panel.raise_()

    def _on_canvas_customized(self) -> None:
        self._apply_canvas_bg()
        self._reapply_theme()
        self.update()
        self._canvas.update()

    # ------------------------------------------------------------------ #

    def _ensure_access(self, feature_key: str, reason: str) -> bool:
        if self._permission_service is None:
            return True
        ok = self._permission_service.ensure_access(feature_key, parent=self, reason=reason)
        if ok:
            return True
        deny_reason = self._permission_service.get_last_denied_reason(feature_key)
        InfoBar.warning(
            self._i18n.t("wt.perm_denied_title"),
            deny_reason or self._i18n.t("wt.perm_denied_content"),
            parent=self,
            position=InfoBarPosition.TOP_RIGHT,
            duration=2500,
        )
        return False

    def _toggle_edit(self) -> None:
        if self._canvas.edit_mode:
            self._canvas.leave_edit_mode()
            self._edit_btn.setText(self._i18n.t("world_time.fs.edit"))
            self._edit_btn.setIcon(FIF.EDIT.icon(self._fs_icon_theme()))
            self._hint_lbl.show()
        else:
            if not self._ensure_access("layout.edit", self._i18n.t("wt.reason.toggle_edit")):
                return
            self._canvas.enter_edit_mode()
            self._edit_btn.setText(self._i18n.t("world_time.fs.done"))
            self._edit_btn.setIcon(FIF.ACCEPT.icon(self._fs_icon_theme()))
            self._hint_lbl.hide()

    def _toggle_topbar(self) -> None:
        self._topbar_visible = not self._topbar_visible
        if self._topbar_visible:
            self._topbar.show()
            self._mini_bar.hide()
            self._topbar_toggle_btn.setIcon(FIF.UP.icon(self._fs_icon_theme()))
            self._topbar_toggle_btn.setToolTip(self._i18n.t("world_time.fs.hide_topbar"))
        else:
            self._topbar.hide()
            self._mini_bar.show()
            self._mini_bar.raise_()
            self._mini_toggle_btn.setIcon(FIF.DOWN.icon(self._fs_icon_theme()))
            self._mini_toggle_btn.setToolTip(self._i18n.t("world_time.fs.show_topbar"))

    # ------------------------------------------------------------------ #

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            if self._canvas.edit_mode:
                self._canvas.leave_edit_mode()
                self._edit_btn.setText(self._i18n.t("world_time.fs.edit"))
                self._edit_btn.setIcon(FIF.EDIT.icon(self._fs_icon_theme()))
            else:
                self.close()
        elif event.key() == Qt.Key.Key_Tab:
            self._toggle_edit()
        elif event.key() == Qt.Key.Key_H and not self._canvas.edit_mode:
            self._toggle_topbar()
        else:
            super().keyPressEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        w, h = self.width(), self.height()
        self._canvas.setGeometry(0, 0, w, h)
        topbar_h = 52
        # 水印先铺满，再把功能控件置顶
        if SHOW_WATERMARK and hasattr(self, "_watermark"):
            self._watermark.setGeometry(self.rect())
            self._watermark.raise_()
        self._topbar.setGeometry(0, 0, w, topbar_h)
        self._topbar.raise_()
        # 迷你浮动栏定位在右上角
        self._mini_bar.adjustSize()
        mb_w = self._mini_bar.width()
        mb_h = self._mini_bar.height()
        self._mini_bar.setGeometry(w - mb_w - 12, 8, mb_w, mb_h)
        if not self._topbar_visible:
            self._mini_bar.raise_()
        # 提示标签放在画布工具栏上方，避免遇层
        hint_h = 24
        toolbar_h = 52
        self._hint_lbl.setGeometry(0, h - toolbar_h - hint_h - 4, w, hint_h)
        self._hint_lbl.raise_()
        self._customize_btn.move(w - 48, h - toolbar_h - 44)
        self._customize_btn.raise_()

    def _apply_watermark_visibility(self) -> None:
        """根据设置刷新世界时间视图水印可见性"""
        if SHOW_WATERMARK and hasattr(self, "_watermark"):
            visible = SettingsService.instance().watermark_worldtime_visible
            self._watermark.setVisible(visible)
            if visible:
                self._watermark.raise_()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._start_recommendation_session()
        try:
            from app.events import EventBus, EventType
            EventBus.emit(EventType.FULLSCREEN_OPENED, zone_id=self._zone.id)
            EventBus.subscribe(EventType.WIDGET_LAYOUT_CHANGED, self._on_layout_changed)
            EventBus.subscribe(EventType.PLUGIN_LOADED, self._on_plugin_runtime_changed)
            EventBus.subscribe(EventType.PLUGIN_UNLOADED, self._on_plugin_runtime_changed)
        except Exception:
            pass

    def _refresh_plugin_topbar_buttons(self) -> None:
        while self._plugin_btn_layout.count():
            item = self._plugin_btn_layout.takeAt(0)
            widget = item.widget() if item else None
            if widget is not None:
                widget.deleteLater()

        if self._plugin_manager is None:
            return

        try:
            for button in self._plugin_manager.collect_canvas_topbar_buttons(self._zone.id):
                self._plugin_btn_layout.addWidget(button)
        except Exception:
            pass

    def _schedule_plugin_runtime_refresh(self) -> None:
        if self._plugin_refresh_scheduled:
            return
        self._plugin_refresh_scheduled = True
        QTimer.singleShot(0, self._refresh_plugin_runtime_extensions)

    def _schedule_layout_reload(self, *, reason: str) -> None:
        if self._layout_reload_scheduled:
            return
        self._layout_reload_scheduled = True
        logger.debug("[世界时间全屏] 已排队布局重载: zone_id={}, reason={}", self._zone.id, reason)
        QTimer.singleShot(0, self._reload_layout_now)

    def _reload_layout_now(self) -> None:
        self._layout_reload_scheduled = False
        try:
            self._canvas.reload_layout()
            logger.info("[世界时间全屏] 布局重载完成: zone_id={}", self._zone.id)
        except Exception:
            logger.exception("[世界时间全屏] 布局重载失败: zone_id={}", self._zone.id)

    def _refresh_plugin_runtime_extensions(self) -> None:
        self._plugin_refresh_scheduled = False
        self._refresh_plugin_topbar_buttons()
        self._schedule_layout_reload(reason="plugin_runtime")

    def refresh_zone_meta(self, zone: WorldZone) -> None:
        self._zone = zone
        self._zone_lbl.setText(format_zone_display_name(zone, fallback=zone.id))

    def _on_plugin_runtime_changed(self, **_) -> None:
        self._schedule_plugin_runtime_refresh()

    def _on_layout_changed(self, zone_id: str = "", **_) -> None:
        """响应插件的 apply_canvas_layout 调用，仅当 zone_id 匹配时重新加载画布布局。"""
        if zone_id and zone_id != self._zone.id:
            return
        self._schedule_layout_reload(reason="layout_changed_event")

    def closeEvent(self, event) -> None:
        if self._system_theme_hints is not None:
            try:
                self._system_theme_hints.colorSchemeChanged.disconnect(
                    self._on_system_color_scheme_changed
                )
            except (RuntimeError, TypeError):
                pass
        try:
            self._canvas._save_layout()
        except Exception:
            logger.exception("[世界时间全屏] 保存布局失败: zone_id={}", self._zone.id)
        try:
            self._canvas.persist_background_widgets()
        except Exception:
            logger.exception("[世界时间全屏] 挂起后台组件失败: zone_id={}", self._zone.id)
        try:
            self._canvas._orphan_detached_windows()
        except Exception:
            logger.exception("[世界时间全屏] 孤立化分离窗口失败: zone_id={}", self._zone.id)
        self._end_recommendation_session()
        try:
            from app.events import EventBus, EventType
            EventBus.emit(EventType.FULLSCREEN_CLOSED, zone_id=self._zone.id)
            EventBus.unsubscribe(EventType.WIDGET_LAYOUT_CHANGED, self._on_layout_changed)
            EventBus.unsubscribe(EventType.PLUGIN_LOADED, self._on_plugin_runtime_changed)
            EventBus.unsubscribe(EventType.PLUGIN_UNLOADED, self._on_plugin_runtime_changed)
        except Exception:
            pass
        if self._clock_service:
            try:
                self._clock_service.secondTick.disconnect(self._canvas.refresh_all)
            except Exception:
                pass
        super().closeEvent(event)


class _ZoneCardList(QWidget):
    """支持拖拽重排的时区卡片容器。"""

    orderChanged = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._settings = SettingsService.instance()
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(6)
        self._cards: list[ZoneCard] = []
        self._drop_index = -1
        self._active_animations: list[QParallelAnimationGroup] = []

    def clear_cards(self) -> None:
        for card in self._cards:
            self._layout.removeWidget(card)
            card.deleteLater()
        self._cards.clear()
        self._drop_index = -1
        self.update()

    def add_card(self, card: "ZoneCard") -> None:
        card.dragRequested.connect(self._on_drag_requested)
        self._cards.append(card)
        self._layout.addWidget(card)

    def remove_card(self, card: "ZoneCard") -> None:
        if card in self._cards:
            self._cards.remove(card)
        self._layout.removeWidget(card)

    def cards(self) -> list["ZoneCard"]:
        return list(self._cards)

    def _on_drag_requested(self, _zone_id: str) -> None:
        # 仅用于确保信号链路有效；重排在 dropEvent 统一处理。
        pass

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat("application/x-world-zone-id"):
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasFormat("application/x-world-zone-id"):
            event.acceptProposedAction()
            self._drop_index = self._pos_to_index(event.position().y())
            self.update()

    def dragLeaveEvent(self, event) -> None:
        self._drop_index = -1
        self.update()

    def dropEvent(self, event) -> None:
        if event.mimeData().hasFormat("application/x-world-zone-id"):
            zone_id = bytes(event.mimeData().data("application/x-world-zone-id")).decode(errors="ignore")
            dst = self._pos_to_index(event.position().y())
            self._move_card(zone_id, dst)
            event.acceptProposedAction()
        self._drop_index = -1
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._drop_index < 0:
            return
        painter = QPainter(self)
        painter.setPen(QPen(QColor("#0078d4"), 2))
        y = self._indicator_y(self._drop_index)
        painter.drawLine(0, y, self.width(), y)

    def _pos_to_index(self, y: float) -> int:
        for i, card in enumerate(self._cards):
            if y < card.geometry().center().y():
                return i
        return len(self._cards)

    def _indicator_y(self, index: int) -> int:
        if index <= 0 or not self._cards:
            return 0
        if index >= len(self._cards):
            last = self._cards[-1]
            return last.y() + last.height()
        prev = self._cards[index - 1]
        curr = self._cards[index]
        return (prev.y() + prev.height() + curr.y()) // 2

    def _move_card(self, zone_id: str, dst: int) -> None:
        src = next((i for i, c in enumerate(self._cards) if c.zone_id == zone_id), -1)
        if src < 0 or src == dst:
            return

        old_positions = {c.zone_id: c.pos() for c in self._cards}
        card = self._cards.pop(src)
        if dst > src:
            dst -= 1
        dst = max(0, min(dst, len(self._cards)))
        self._cards.insert(dst, card)
        for c in self._cards:
            self._layout.removeWidget(c)
        for c in self._cards:
            self._layout.addWidget(c)
        self._layout.activate()
        self._animate_reorder(old_positions)
        self.orderChanged.emit([c.zone_id for c in self._cards])

    def _animate_reorder(self, old_positions: dict[str, QPoint]) -> None:
        for animation in list(self._active_animations):
            animation.stop()
        self._active_animations.clear()

        if not self._settings.ui_smooth_scroll_enabled:
            return

        group = QParallelAnimationGroup(self)
        for card in self._cards:
            old_pos = old_positions.get(card.zone_id)
            if old_pos is None:
                continue
            new_pos = card.pos()
            if old_pos == new_pos:
                continue
            card.move(old_pos)
            card.raise_()

            pos_ani = QPropertyAnimation(card, b"pos", self)
            pos_ani.setDuration(180)
            pos_ani.setStartValue(old_pos)
            pos_ani.setEndValue(new_pos)
            pos_ani.setEasingCurve(QEasingCurve.Type.OutCubic)
            group.addAnimation(pos_ani)

        if group.animationCount() == 0:
            group.deleteLater()
            return

        self._active_animations.append(group)

        def _cleanup() -> None:
            if group in self._active_animations:
                self._active_animations.remove(group)

        group.finished.connect(_cleanup)
        group.start()


class ZoneCard(CardWidget):
    """单张时区卡片"""

    dragRequested = Signal(str)

    def __init__(
        self,
        zone: WorldZone,
        on_remove,
        clock_service: ClockService | None = None,
        plugin_manager=None,
        notification_service=None,
        permission_service: PermissionService | None = None,
        central_control_service: CentralControlService | None = None,
        automation_engine=None,
        parent=None,
    ):
        super().__init__(parent)
        self.zone_id         = zone.id
        self._zone           = zone
        self._on_remove      = on_remove
        self._clock_service  = clock_service
        self._plugin_mgr     = plugin_manager
        self._notif_service  = notification_service
        self._permission_service = permission_service
        self._central_control_service = central_control_service
        self._automation_engine = automation_engine
        self._fs_window: FullscreenClockWindow | None = None
        self._i18n = I18nService.instance()
        self._settings = SettingsService.instance()
        self._background_service = BackgroundCanvasService.instance()
        self._drag_hold_timer = QTimer(self)
        self._drag_hold_timer.setSingleShot(True)
        self._drag_hold_timer.setInterval(240)
        self._drag_hold_timer.timeout.connect(self._start_drag)
        self._drag_press_pos: QPoint | None = None
        self._drag_started = False

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(2)

        # 城市/标签行
        top  = QHBoxLayout()
        self.label_lbl  = BodyLabel(zone.label or zone.timezone)
        self._bg_badge = CaptionLabel("")
        self._bg_badge.setObjectName("backgroundRuntimeBadge")
        self._bg_badge.setStyleSheet(
            "padding:1px 8px; border-radius:9px;"
            "background:rgba(39,174,96,0.16); color:#2c974b;"
        )
        self._bg_badge.hide()
        self.offset_lbl = CaptionLabel("")
        self.offset_lbl.setObjectName("offsetLabel")
        top.addWidget(self.label_lbl)
        top.addStretch()
        top.addWidget(self._bg_badge)
        top.addSpacing(6)
        top.addWidget(self.offset_lbl)

        # 时间大字
        self.time_lbl = TitleLabel("--:--:--")
        self.time_lbl.setAlignment(Qt.AlignCenter)

        # 日期 + 差值行
        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        self.date_lbl = CaptionLabel("")
        self.diff_lbl = CaptionLabel("")
        self.diff_lbl.setObjectName("diffLabel")
        if zone.show_date:
            bottom.addWidget(self.date_lbl)
        bottom.addStretch()
        bottom.addWidget(self.diff_lbl)

        # 右下角：全屏按钮 + 菜单按钮
        self._fs_btn = TransparentToolButton(FIF.FULL_SCREEN, self)
        self._fs_btn.setFixedSize(28, 28)
        self._fs_btn.setToolTip(self._i18n.t("world_time.fullscreen"))
        self._fs_btn.clicked.connect(self._open_fullscreen)
        bottom.addWidget(self._fs_btn)

        self._shortcut_btn = TransparentToolButton(FIF.LINK, self)
        self._shortcut_btn.setFixedSize(28, 28)
        supported = _desktop_shortcut_supported()
        self._shortcut_btn.setEnabled(supported)
        self._shortcut_btn.setToolTip(
            self._i18n.t(
                "world_time.desktop_shortcut",
                default="添加桌面快捷方式",
            ) if supported else self._i18n.t(
                "world_time.desktop_shortcut.unsupported",
                default="当前操作系统不支持桌面快捷方式",
            )
        )
        self._shortcut_btn.clicked.connect(self._create_desktop_shortcut)
        bottom.addWidget(self._shortcut_btn)

        self._menu_btn = TransparentToolButton(FIF.MORE, self)
        self._menu_btn.setFixedSize(28, 28)
        self._menu_btn.setToolTip(self._i18n.t("common.more"))
        self._menu_btn.clicked.connect(self._show_menu)
        bottom.addWidget(self._menu_btn)

        root.addLayout(top)
        root.addWidget(self.time_lbl)
        root.addLayout(bottom)

        self.setFixedHeight(116)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.refresh(zone)
        self.setToolTip(self._i18n.t("automation.drag.sort"))
        self._background_service.changed.connect(self._refresh_background_badge)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            child = self.childAt(event.position().toPoint())
            if child is None or not isinstance(child, QAbstractButton):
                self._drag_press_pos = event.position().toPoint()
                self._drag_started = False
                self._drag_hold_timer.start()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if (event.buttons() & Qt.MouseButton.LeftButton) and self._drag_press_pos is not None:
            if not self._drag_started:
                delta = event.position().toPoint() - self._drag_press_pos
                if delta.manhattanLength() > _drag_distance_threshold():
                    self._drag_hold_timer.stop()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_hold_timer.stop()
        self._drag_press_pos = None
        self._drag_started = False
        super().mouseReleaseEvent(event)

    def _start_drag(self) -> None:
        if self._drag_press_pos is None:
            return
        self._drag_started = True
        self.dragRequested.emit(self.zone_id)
        try:
            if self._settings.ui_smooth_scroll_enabled:
                self.setWindowOpacity(0.78)

            drag = QDrag(self)
            mime = QMimeData()
            mime.setData("application/x-world-zone-id", self.zone_id.encode("utf-8"))
            drag.setMimeData(mime)
            drag.exec(Qt.DropAction.MoveAction)
        finally:
            self.setWindowOpacity(1.0)
            self._drag_hold_timer.stop()
            self._drag_press_pos = None
            self._drag_started = False

    def _open_fullscreen(self) -> bool:
        """打开全屏小组件画布窗口。"""
        if self._central_control_service is not None:
            allowed, reason = self._central_control_service.is_fullscreen_zone_allowed(self.zone_id)
            if not allowed:
                InfoBar.warning(
                    self._i18n.t("world_time.title"),
                    reason or self._i18n.t("perm.access.denied", default="权限不足，无法执行该操作。"),
                    parent=self.window(),
                    position=InfoBarPosition.TOP_RIGHT,
                    duration=2500,
                )
                return False

        if self._fs_window is not None and not self._fs_window.isHidden():
            logger.debug("[世界时间] 全屏窗口已存在，激活：zone_id={}", self.zone_id)
            self._fs_window.raise_()
            self._fs_window.activateWindow()
            return True
        logger.info(
            "[世界时间] 打开全屏窗口：zone_id={}, label='{}'",
            self.zone_id,
            format_zone_display_name(self._zone, fallback=self.zone_id),
        )
        self._fs_window = FullscreenClockWindow(
            self._zone, self._clock_service, self._plugin_mgr,
            notification_service=self._notif_service,
            permission_service=self._permission_service,
            automation_engine=self._automation_engine,
        )
        self._fs_window.showFullScreen()
        return True

    def _fullscreen_url(self) -> str:
        return uss.build_fullscreen_url(self.zone_id)

    def _copy_fullscreen_url(self) -> None:
        if not uss.is_registered():
            if self._notif_service is not None:
                self._notif_service.show(
                    self._i18n.t("world_time.url_scheme.not_registered.title"),
                    self._i18n.t("world_time.url_scheme.not_registered.content"),
                    level="warning",
                )
            return
        url = self._fullscreen_url()
        QApplication.clipboard().setText(url)
        logger.info("[世界时间] 已复制全屏链接：zone_id={}, url='{}'", self.zone_id, url)
        if self._notif_service is not None:
            self._notif_service.show(
                self._i18n.t("world_time.copy_fullscreen_url.done_title", default="全屏链接已复制"),
                self._i18n.t("world_time.copy_fullscreen_url.done_content", default="已复制：{url}", url=url),
            )

    def _create_desktop_shortcut(self) -> None:
        if not uss.is_registered():
            if self._notif_service is not None:
                self._notif_service.show(
                    self._i18n.t("world_time.url_scheme.not_registered.title"),
                    self._i18n.t("world_time.url_scheme.not_registered.content"),
                    level="warning",
                )
            return

        if not _desktop_shortcut_supported():
            if self._notif_service is not None:
                self._notif_service.show(
                    self._i18n.t("world_time.shortcut.unavailable.title"),
                    self._i18n.t("world_time.desktop_shortcut.unsupported"),
                    level="warning",
                )
            return

        zone_name = format_zone_display_name(self._zone, fallback=self.zone_id)
        ok, detail = _create_fullscreen_desktop_shortcut(self.zone_id, zone_name)
        if self._notif_service is None:
            return
        if ok:
            self._notif_service.show(
                self._i18n.t("world_time.shortcut.created.title"),
                self._i18n.t("world_time.shortcut.created.content", name=zone_name),
                level="success",
            )
        else:
            logger.warning("快捷方式创建失败，zone_id='{}', zone_name='{}', reason='{}'", self.zone_id, zone_name, detail)
            self._notif_service.show(
                self._i18n.t("world_time.shortcut.failed.title"),
                self._i18n.t("world_time.shortcut.failed.content", detail=detail),
                level="warning",
            )

    def _show_menu(self) -> None:
        menu = RoundMenu(parent=self)
        menu.addAction(Action(FIF.FULL_SCREEN, self._i18n.t("world_time.fullscreen"), triggered=self._open_fullscreen))
        menu.addAction(Action(
            FIF.EDIT,
            self._i18n.t("world_time.rename", default="编辑名称"),
            triggered=self._edit_name,
        ))
        menu.addAction(Action(
            FIF.LINK,
            self._i18n.t("world_time.copy_fullscreen_url", default="复制全屏链接"),
            triggered=self._copy_fullscreen_url,
        ))
        shortcut_action = Action(
            FIF.LINK,
            self._i18n.t("world_time.desktop_shortcut", default="添加桌面快捷方式"),
            triggered=self._create_desktop_shortcut,
        )
        shortcut_action.setEnabled(_desktop_shortcut_supported())
        menu.addAction(shortcut_action)
        menu.addSeparator()
        menu.addAction(Action(FIF.DELETE, self._i18n.t("common.delete"), triggered=lambda: self._on_remove(self.zone_id)))
        # 菜单弹出位置：按钮右下角对齐
        btn_pos = self._menu_btn.mapToGlobal(QPoint(self._menu_btn.width(), self._menu_btn.height()))
        menu.exec(btn_pos)

    def _ensure_access(self, feature_key: str, reason: str) -> bool:
        if self._permission_service is None:
            return True
        ok = self._permission_service.ensure_access(feature_key, parent=self.window(), reason=reason)
        if ok:
            return True
        deny_reason = self._permission_service.get_last_denied_reason(feature_key)
        InfoBar.warning(
            self._i18n.t("world_time.title"),
            deny_reason or self._i18n.t("perm.access.denied", default="权限不足，无法执行该操作。"),
            parent=self.window(),
            position=InfoBarPosition.TOP_RIGHT,
            duration=2500,
        )
        return False

    def _edit_name(self) -> None:
        if not self._ensure_access("world_time.manage", self._i18n.t("wt.reason.rename")):
            return

        current_name = str(self._zone.label or "").strip()
        actual_name = get_localized_timezone_name(self._zone.timezone, fallback=self.zone_id)
        dialog = _RenameZoneDialog(
            current_name=current_name,
            actual_name=actual_name,
            i18n=self._i18n,
            parent=self.window(),
        )
        if dialog.exec() != 1:
            return

        new_name = dialog.shown_name()
        if new_name == current_name:
            return

        self._zone.label = new_name
        WorldZoneStore().update(self._zone)
        self.refresh(self._zone)
        if self._fs_window is not None and not self._fs_window.isHidden():
            self._fs_window.refresh_zone_meta(self._zone)
        logger.info("[世界时间] 更新时区名称：zone_id={}, label='{}', timezone='{}'", self.zone_id, self._zone.label, self._zone.timezone)

    def _refresh_background_badge(self) -> None:
        count = self._background_service.background_count(self.zone_id)
        if count <= 0:
            self._bg_badge.hide()
            self._bg_badge.setText("")
            self._bg_badge.setToolTip("")
            return
        self._bg_badge.setText(
            self._i18n.t(
                "world_time.background.badge",
                default="后台 {count}",
                count=count,
            )
        )
        self._bg_badge.setToolTip(
            self._i18n.t(
                "world_time.background.tooltip",
                default="该画布当前在后台运行，包含 {count} 个后台组件。",
                count=count,
            )
        )
        self._bg_badge.show()

    def refresh(self, zone: WorldZone) -> None:
        self._zone = zone
        dt = now_in_zone(zone.timezone)
        self.time_lbl.setText(format_time(dt))
        self.date_lbl.setText(format_date(dt))
        self.offset_lbl.setText(utc_offset_str(dt))
        self.label_lbl.setText(format_zone_display_name(zone, fallback=zone.id))
        self.diff_lbl.setText(_local_offset_diff_str(zone.timezone))
        self._refresh_background_badge()


class WorldTimeView(SmoothScrollArea):
    """世界时间主视图"""

    def __init__(
        self,
        clock_service: ClockService,
        plugin_manager=None,
        notification_service=None,
        permission_service: PermissionService | None = None,
        central_control_service: CentralControlService | None = None,
        automation_engine=None,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("worldTimeView")
        self._clock_service = clock_service
        self._plugin_mgr    = plugin_manager
        self._notif_service = notification_service
        self._permission_service = permission_service
        self._central_control_service = central_control_service
        self._automation_engine = automation_engine
        self._i18n = I18nService.instance()

        self._store  = WorldZoneStore()
        self._cards: dict[str, ZoneCard] = {}

        # 内容容器
        self._container = QWidget()
        self._layout    = QVBoxLayout(self._container)
        self._layout.setContentsMargins(24, 16, 24, 16)
        self._layout.setSpacing(8)

        self._layout.addWidget(TitleLabel(self._i18n.t("world_time.title")))

        # 工具栏
        bar = QHBoxLayout()
        self._combo = ComboBox()
        self._combo.setPlaceholderText(self._i18n.t("world_time.select"))
        for label, tz in PRESET_TIMEZONES:
            self._combo.addItem(label, userData=tz)
        self._add_btn = PushButton(FIF.ADD, self._i18n.t("common.add"))
        self._add_btn.clicked.connect(self._on_add)
        bar.addWidget(self._combo, 1)
        bar.addWidget(self._add_btn)
        self._layout.addLayout(bar)

        # 卡片区域
        self._cards_list = _ZoneCardList(self._container)
        self._cards_list.orderChanged.connect(self._on_zone_cards_reordered)
        self._layout.addWidget(self._cards_list)
        self._layout.addStretch()

        self.setWidget(self._container)
        self.setWidgetResizable(True)
        self.enableTransparentBackground()

        self._load_cards()

        clock_service.secondTick.connect(self._refresh_all)

    # ------------------------------------------------------------------ #

    def _load_cards(self) -> None:
        # 清空旧卡片
        self._cards_list.clear_cards()
        self._cards.clear()

        for zone in self._store.all():
            self._add_card(zone)
        logger.debug("[世界时间] 已加载时区卡片 {} 张", len(self._cards))

    def _add_card(self, zone: WorldZone) -> None:
        card = ZoneCard(
            zone,
            self._on_remove,
            self._clock_service,
            self._plugin_mgr,
            self._notif_service,
            self._permission_service,
            self._central_control_service,
            self._automation_engine,
            self._container,
        )
        self._cards[zone.id] = card
        self._cards_list.add_card(card)
        logger.debug("[世界时间] 卡片已添加到界面：zone_id={}, label='{}'", zone.id, zone.label or zone.timezone)

    @Slot(list)
    def _on_zone_cards_reordered(self, zone_ids: list[str]) -> None:
        if not zone_ids:
            return
        self._store.reorder(zone_ids)

    def _ensure_access(self, feature_key: str, reason: str) -> bool:
        if self._permission_service is None:
            return True
        ok = self._permission_service.ensure_access(feature_key, parent=self.window(), reason=reason)
        if ok:
            return True
        deny_reason = self._permission_service.get_last_denied_reason(feature_key)
        InfoBar.warning(
            self._i18n.t("world_time.title"),
            deny_reason or self._i18n.t("perm.access.denied", default="权限不足，无法执行该操作。"),
            parent=self.window(),
            position=InfoBarPosition.TOP_RIGHT,
            duration=2500,
        )
        return False

    def open_fullscreen_by_zone_id(self, zone_id: str) -> bool:
        """按 zone_id 打开指定时区的全屏时钟。"""
        zid = str(zone_id or "").strip()
        if not zid:
            logger.warning("[世界时间] 通过 zone_id 打开全屏失败：zone_id 为空")
            return False

        card = self._cards.get(zid)
        if card is None:
            target_zone = next((z for z in self._store.all() if z.id == zid), None)
            if target_zone is None:
                logger.warning("[世界时间] 通过 zone_id 打开全屏失败：zone_id={} 不存在", zid)
                return False
            self._add_card(target_zone)
            card = self._cards.get(zid)
            if card is None:
                logger.warning("[世界时间] 通过 zone_id 打开全屏失败：zone_id={} 卡片创建失败", zid)
                return False

        if card._open_fullscreen():
            logger.info("[世界时间] 通过 zone_id 打开全屏成功：zone_id={}", zid)
        else:
            logger.warning("[世界时间] 通过 zone_id 打开全屏被策略拒绝：zone_id={}", zid)
        return True

    # ------------------------------------------------------------------ #
    # Slots
    # ------------------------------------------------------------------ #

    @Slot()
    def _on_add(self) -> None:
        if not self._ensure_access("world_time.manage", self._i18n.t("wt.reason.add_zone")):
            return
        tz = self._combo.currentData()
        if not tz:
            logger.warning("[世界时间] 新增时区失败：未选择时区")
            return
        label = self._combo.currentText()
        zone  = WorldZone(label=label, timezone=tz)
        self._store.add(zone)
        self._add_card(zone)
        logger.info("[世界时间] 新增时区：id={}, label='{}', timezone='{}'", zone.id, zone.label, zone.timezone)

    def _on_remove(self, zone_id: str) -> None:
        if not self._ensure_access("world_time.manage", self._i18n.t("wt.reason.remove_zone")):
            return
        BackgroundCanvasService.instance().clear_page(zone_id)
        self._store.remove(zone_id)
        card = self._cards.pop(zone_id, None)
        if card:
            self._cards_list.remove_card(card)
            card.deleteLater()
            logger.info("[世界时间] 移除时区卡片：zone_id={}", zone_id)
        else:
            logger.warning("[世界时间] 移除时区卡片未命中：zone_id={}", zone_id)

    @Slot()
    def _refresh_all(self) -> None:
        for zone in self._store.all():
            card = self._cards.get(zone.id)
            if card:
                card.refresh(zone)

"""应用设置视图"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QHBoxLayout, QWidget, QListWidgetItem
from qfluentwidgets import (
    SmoothScrollArea, FluentIcon as FIF, PushButton, ToolButton,
    SettingCardGroup, SettingCard, CardWidget,
    BodyLabel, TitleLabel, CaptionLabel,
    SwitchButton, ComboBox, SpinBox, Slider,
    VBoxLayout,
    InfoBar, InfoBarPosition, ListWidget,
    setTheme, Theme, isDarkTheme, qconfig,
    MessageBoxBase, CheckBox, SubtitleLabel,
)

from app.services import ringtone_service as rs
from app.views.toast_notification import (
    POSITION_LABELS, ALL_POSITIONS,
)

from app.constants import URL_SCHEME, IS_BETA, APP_VERSION, APP_NAME, PIP_MIRRORS
from app.services.i18n_service import I18nService, LANG_EN_US
from app.services.ntp_service import NtpService, NTP_SERVERS
from app.services.settings_service import SettingsService
from app.services.update_service import UpdateService
from app.widgets.lazy_factory_widget import LazyFactoryWidget
from app.services import url_scheme_service as uss
from app.services import startup_service as startup
from app.services.file_type_open_service import FileTypeOpenService
from app.plugins.plugin_manager import PLUGIN_PACKAGE_EXTENSION


def _tr(i18n: I18nService, zh: str, en: str) -> str:
    return en if i18n.language == LANG_EN_US else zh


def _theme_options(i18n: I18nService) -> list[tuple[str, str]]:
    return [
        (i18n.t("settings.theme.auto"), "auto"),
        (i18n.t("settings.theme.light"), "light"),
        (i18n.t("settings.theme.dark"), "dark"),
    ]


_LANGUAGE_OPTIONS = [
    ("lang.zh-CN", "zh-CN"),
    ("lang.en-US", "en-US"),
]


def _precision_labels(i18n: I18nService) -> list[str]:
    return [
        i18n.t("settings.precision.0"),
        i18n.t("settings.precision.1"),
        i18n.t("settings.precision.2"),
    ]


def _update_channel_options(i18n: I18nService) -> list[tuple[str, str]]:
    return [
        (_tr(i18n, "稳定版（推荐）", "Stable (recommended)"), "stable"),
        (_tr(i18n, "测试版", "Beta"), "beta"),
        (_tr(i18n, "开发版", "Dev"), "dev"),
    ]


def _position_label(i18n: I18nService, pos_key: str) -> str:
    return i18n.t(f"settings.pos.{pos_key}", default=POSITION_LABELS.get(pos_key, pos_key))


def _make_card(icon, title: str, content: str, parent=None) -> SettingCard:
    """创建基础设置卡"""
    return SettingCard(icon, title, content, parent)


# ─────────────────────────────────────────────────────────────────────────── #
# 测试版水印声明对话框
# ─────────────────────────────────────────────────────────────────────────── #

class _WatermarkDisclaimerDialog(MessageBoxBase):
    """关闭测试版水印前必须同意的声明对话框"""

    def __init__(self, watermark_label: str, parent=None):
        super().__init__(parent)
        i18n = I18nService.instance()
        self.setWindowTitle(_tr(i18n, f"关闭水印 - {watermark_label}", f"Disable Watermark - {watermark_label}"))

        title_lbl = SubtitleLabel(_tr(i18n, f"关闭水印 - {watermark_label}", f"Disable Watermark - {watermark_label}"))
        self.viewLayout.addWidget(title_lbl)
        self.viewLayout.addSpacing(4)

        disclaimer = _tr(
            i18n,
            (
                "您正在尝试关闭测试版水印。请在继续前仔细阅读以下声明：\n\n"
                "1. 本软件当前为测试版，界面及功能并非最终状态，可能存在不稳定或不完整。\n\n"
                "2. 关闭水印后，截图或录屏将不再带有测试标识。若对外传播，请注明非最终效果，避免误解。\n\n"
                "3. 测试版内容的对外传播可能影响正式发布节奏，请谨慎分享截图和录屏。\n\n"
                "4. 关闭水印不改变软件测试版属性，也不代表获得超出测试协议范围的授权。"
            ),
            (
                "You are about to disable the beta watermark. Please read before continuing:\n\n"
                "1. This software is currently in beta. UI and features may be unstable or incomplete.\n\n"
                "2. After disabling the watermark, screenshots/recordings will no longer show beta markings. "
                "If shared publicly, please indicate they are not final to avoid misunderstanding.\n\n"
                "3. Public sharing of beta content may affect official release plans. Please share with caution.\n\n"
                "4. Disabling watermark does not change beta status and does not grant permissions beyond the beta agreement."
            ),
        )

        desc = BodyLabel(disclaimer)
        desc.setWordWrap(True)
        desc.setFixedWidth(420)
        self.viewLayout.addWidget(desc)
        self.viewLayout.addSpacing(8)

        self._agree_cb = CheckBox(
            _tr(
                i18n,
                "我已阅读并理解以上声明，同意关闭此水印",
                "I have read and understood the statement above and agree to disable this watermark",
            )
        )
        self.viewLayout.addWidget(self._agree_cb)

        self.yesButton.setText(_tr(i18n, "确认关闭", "Confirm Disable"))
        self.cancelButton.setText(i18n.t("common.cancel"))
        self.yesButton.setEnabled(False)

        self._agree_cb.stateChanged.connect(
            lambda: self.yesButton.setEnabled(self._agree_cb.isChecked())
        )
        self.widget.setMinimumWidth(460)


class _RingtoneCard(CardWidget):
    """铃声列表卡片（嵌入 SettingCardGroup 内）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        i18n = I18nService.instance()
        layout = VBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)

        hint = CaptionLabel(i18n.t("settings.ringtone.hint"))
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.listWidget = ListWidget()
        self.listWidget.setFixedHeight(150)
        layout.addWidget(self.listWidget)

        btn_row = QHBoxLayout()
        self.addBtn = PushButton(FIF.ADD, i18n.t("settings.ringtone.add"))
        self.previewBtn = PushButton(FIF.PLAY, i18n.t("settings.ringtone.preview"))
        self.deleteBtn = ToolButton(FIF.DELETE)
        btn_row.addWidget(self.addBtn)
        btn_row.addWidget(self.previewBtn)
        btn_row.addStretch()
        btn_row.addWidget(self.deleteBtn)
        layout.addLayout(btn_row)

        self._update_border()
        qconfig.themeChanged.connect(self._update_border)

    @Slot()
    def _update_border(self) -> None:
        border_color = "#555555" if isDarkTheme() else "#e0e0e0"
        self.listWidget.setStyleSheet(
            f"QListWidget{{border:1px solid {border_color};border-radius:6px;background:transparent;}}"
        )


class SettingsView(SmoothScrollArea):
    """设置视图"""

    _BUILTIN_FILE_TYPE_BINDINGS = (
        (PLUGIN_PACKAGE_EXTENSION, "插件包", "内置"),
        (".ltcconfig", "配置包", "内置"),
        (".ltlayout", "布局文件", "内置"),
    )

    def __init__(self, plugin_manager=None, permission_service=None, file_type_open_service=None, update_service=None, open_update_window=None, parent=None):
        super().__init__(parent)
        self.setObjectName("settingsView")

        self._ntp = NtpService.instance()
        self._app_settings = SettingsService.instance()
        self._i18n = I18nService.instance()
        self._plugin_manager = plugin_manager
        self._permission_service = permission_service
        self._file_type_service = (
            file_type_open_service
            if isinstance(file_type_open_service, FileTypeOpenService)
            else FileTypeOpenService()
        )
        self._update_service = update_service if isinstance(update_service, UpdateService) else None
        self._open_update_window = open_update_window or (lambda: None)
        # plugin_id -> SettingCardGroup widget
        self._plugin_setting_groups: dict[str, QWidget] = {}

        container = QWidget()
        layout = VBoxLayout(container)
        layout.setContentsMargins(32, 20, 32, 32)
        layout.setSpacing(16)
        self._layout = layout

        layout.addWidget(TitleLabel(self._i18n.t("settings.title")))

        # ── 外观 ─────────────────────────────────────────────────────────────── #
        appear_group = SettingCardGroup(self._i18n.t("settings.group.appearance"))

        language_card = _make_card(
            FIF.GLOBE,
            self._i18n.t("settings.language.label"),
            self._i18n.t("settings.language.desc"),
            appear_group,
        )
        self._language_combo = ComboBox()
        for label_key, key in _LANGUAGE_OPTIONS:
            self._language_combo.addItem(self._i18n.t(label_key), userData=key)
        cur_lang = self._app_settings.language
        for i in range(self._language_combo.count()):
            if self._language_combo.itemData(i) == cur_lang:
                self._language_combo.setCurrentIndex(i)
                break
        self._language_combo.currentIndexChanged.connect(self._on_language_changed)
        language_card.hBoxLayout.addWidget(self._language_combo)
        language_card.hBoxLayout.addSpacing(16)
        appear_group.addSettingCard(language_card)

        theme_card = _make_card(
            FIF.BRUSH,
            self._i18n.t("settings.theme.label"),
            self._i18n.t("settings.theme.desc"),
            appear_group,
        )
        self._theme_combo = ComboBox()
        for label, key in _theme_options(self._i18n):
            self._theme_combo.addItem(label, userData=key)
        cur_theme = self._app_settings.theme
        for i in range(self._theme_combo.count()):
            if self._theme_combo.itemData(i) == cur_theme:
                self._theme_combo.setCurrentIndex(i)
                break
        self._theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        theme_card.hBoxLayout.addWidget(self._theme_combo)
        theme_card.hBoxLayout.addSpacing(16)
        appear_group.addSettingCard(theme_card)

        smooth_scroll_card = _make_card(
            FIF.LAYOUT,
            _tr(self._i18n, "动画开关", "Animation Switch"),
            _tr(
                self._i18n,
                "控制界面过渡动画与平滑滚动效果；关闭后相关页面将以静态方式切换。",
                "Controls UI transition animations and smooth scrolling; when disabled, related pages switch without animation.",
            ),
            appear_group,
        )
        self._smooth_scroll_switch = SwitchButton()
        self._smooth_scroll_switch.setChecked(self._app_settings.ui_smooth_scroll_enabled)
        self._smooth_scroll_switch.checkedChanged.connect(self._on_smooth_scroll_toggle)
        smooth_scroll_card.hBoxLayout.addWidget(self._smooth_scroll_switch)
        smooth_scroll_card.hBoxLayout.addSpacing(16)
        appear_group.addSettingCard(smooth_scroll_card)

        layout.addWidget(appear_group)

        # ── 全屏时钟 ──────────────────────────────────────── #
        wt_group = SettingCardGroup(_tr(self._i18n, "全屏时钟", "Fullscreen Clock"))

        cell_size_card = _make_card(
            FIF.LAYOUT,
            _tr(self._i18n, "组件格子大小", "Widget Grid Size"),
            _tr(self._i18n, "全屏时钟画布的单格像素尺寸，调整后所有组件按比例缩放", "Pixel size of one canvas grid cell; all widgets scale proportionally"),
            wt_group,
        )
        self._cell_size_card = cell_size_card
        self._cell_size_desc = _tr(self._i18n, "全屏时钟画布的单格像素尺寸，调整后所有组件按比例缩放", "Pixel size of one canvas grid cell; all widgets scale proportionally")
        self._cell_size_slider = Slider(Qt.Horizontal)
        self._cell_size_slider.setRange(60, 300)
        self._cell_size_slider.setSingleStep(10)
        self._cell_size_slider.setPageStep(20)
        self._cell_size_slider.setValue(self._app_settings.widget_cell_size)
        self._cell_size_slider.setMinimumWidth(160)
        self._cell_size_val_lbl = CaptionLabel(f"{self._app_settings.widget_cell_size} px")
        self._cell_size_val_lbl.setFixedWidth(52)
        self._cell_size_slider.valueChanged.connect(self._on_cell_size_changed)
        cell_size_card.hBoxLayout.addWidget(self._cell_size_slider, 1)
        cell_size_card.hBoxLayout.addWidget(self._cell_size_val_lbl)
        cell_size_card.hBoxLayout.addSpacing(16)
        wt_group.addSettingCard(cell_size_card)
        self._update_cell_size_preview(self._app_settings.widget_cell_size)

        detached_opacity_card = _make_card(
            FIF.TRANSPARENT,
            _tr(self._i18n, "分离窗口背景透明度", "Detached Window Background Opacity"),
            _tr(self._i18n, "控制分离出的小组件窗口背景透明度；0% 表示完全透明", "Opacity of detached widget windows; 0% means fully transparent"),
            wt_group,
        )
        self._detached_opacity_slider = Slider(Qt.Horizontal)
        self._detached_opacity_slider.setRange(0, 100)
        self._detached_opacity_slider.setSingleStep(5)
        self._detached_opacity_slider.setPageStep(10)
        self._detached_opacity_slider.setValue(self._app_settings.detached_widget_background_opacity)
        self._detached_opacity_slider.setMinimumWidth(160)
        self._detached_opacity_val_lbl = CaptionLabel(
            f"{self._app_settings.detached_widget_background_opacity}%"
        )
        self._detached_opacity_val_lbl.setFixedWidth(48)
        self._detached_opacity_slider.valueChanged.connect(self._on_detached_opacity_changed)
        detached_opacity_card.hBoxLayout.addWidget(self._detached_opacity_slider, 1)
        detached_opacity_card.hBoxLayout.addWidget(self._detached_opacity_val_lbl)
        detached_opacity_card.hBoxLayout.addSpacing(16)
        wt_group.addSettingCard(detached_opacity_card)

        canvas_overlap_group_card = _make_card(
            FIF.LAYOUT,
            _tr(self._i18n, "画布重叠自动生成组件组", "Auto-group on Canvas Overlap"),
            _tr(self._i18n, "编辑模式拖拽组件重叠时，自动生成可整体拖拽的组件组。", "When widgets overlap in edit mode, automatically generate a movable widget group."),
            wt_group,
        )
        self._canvas_overlap_group_switch = SwitchButton()
        self._canvas_overlap_group_switch.setChecked(self._app_settings.widget_canvas_overlap_group_enabled)
        self._canvas_overlap_group_switch.checkedChanged.connect(self._on_canvas_overlap_group_toggle)
        canvas_overlap_group_card.hBoxLayout.addWidget(self._canvas_overlap_group_switch)
        canvas_overlap_group_card.hBoxLayout.addSpacing(16)
        wt_group.addSettingCard(canvas_overlap_group_card)

        detached_overlap_merge_card = _make_card(
            FIF.LAYOUT,
            _tr(self._i18n, "分离窗口重叠自动并组", "Auto-merge Detached Windows"),
            _tr(self._i18n, "分离窗口发生重叠时自动合并为同一个组件组窗口。", "Merge overlapping detached windows into one grouped window automatically."),
            wt_group,
        )
        self._detached_overlap_merge_switch = SwitchButton()
        self._detached_overlap_merge_switch.setChecked(self._app_settings.widget_detached_overlap_merge_enabled)
        self._detached_overlap_merge_switch.checkedChanged.connect(self._on_detached_overlap_merge_toggle)
        detached_overlap_merge_card.hBoxLayout.addWidget(self._detached_overlap_merge_switch)
        detached_overlap_merge_card.hBoxLayout.addSpacing(16)
        wt_group.addSettingCard(detached_overlap_merge_card)

        auto_fill_gap_card = _make_card(
            FIF.ALIGNMENT,
            _tr(self._i18n, "新增组件自动补齐空位", "Auto-fill Gaps for New Widgets"),
            _tr(self._i18n, "开启后优先搜索画布空位；关闭后所有新组件都叠放在左上角。", "When enabled, new widgets search for free slots first; when disabled, all new widgets stack at top-left."),
            wt_group,
        )
        self._auto_fill_gap_switch = SwitchButton()
        self._auto_fill_gap_switch.setChecked(self._app_settings.widget_auto_fill_gap_enabled)
        self._auto_fill_gap_switch.checkedChanged.connect(self._on_auto_fill_gap_toggle)
        auto_fill_gap_card.hBoxLayout.addWidget(self._auto_fill_gap_switch)
        auto_fill_gap_card.hBoxLayout.addSpacing(16)
        wt_group.addSettingCard(auto_fill_gap_card)

        prevent_new_overflow_card = _make_card(
            FIF.BROOM,
            _tr(self._i18n, "阻止新增组件溢出", "Prevent New Widget Overflow"),
            _tr(self._i18n, "开启后无空位时阻止新增；关闭后无空位时从左上角开始覆盖排列。", "When enabled, block insertion if no space exists; when disabled, placement restarts from top-left when full."),
            wt_group,
        )
        self._prevent_new_overflow_switch = SwitchButton()
        self._prevent_new_overflow_switch.setChecked(self._app_settings.widget_prevent_new_overflow_enabled)
        self._prevent_new_overflow_switch.checkedChanged.connect(self._on_prevent_new_overflow_toggle)
        prevent_new_overflow_card.hBoxLayout.addWidget(self._prevent_new_overflow_switch)
        prevent_new_overflow_card.hBoxLayout.addSpacing(16)
        wt_group.addSettingCard(prevent_new_overflow_card)

        self._sync_new_widget_placement_controls()

        layout.addWidget(wt_group)

        # ── NTP 网络时间同步 ──────────────────────────────────────────────── #
        ntp_group = SettingCardGroup(self._i18n.t("settings.group.ntp"))

        # 启用开关
        ntp_switch_card = _make_card(
            FIF.SYNC,
            self._i18n.t("settings.ntp.enable.label"),
            self._i18n.t("settings.ntp.enable.desc"),
            ntp_group,
        )
        self._ntp_switch = SwitchButton()
        self._ntp_switch.setChecked(self._ntp.enabled)
        self._ntp_switch.checkedChanged.connect(self._on_ntp_toggle)
        ntp_switch_card.hBoxLayout.addWidget(self._ntp_switch)
        ntp_switch_card.hBoxLayout.addSpacing(16)
        ntp_group.addSettingCard(ntp_switch_card)

        # 服务器选择
        server_card = _make_card(
            FIF.GLOBE,
            self._i18n.t("settings.ntp.server.label"),
            self._i18n.t("settings.ntp.server.desc"),
            ntp_group,
        )
        self._server_combo = ComboBox()
        for s in NTP_SERVERS:
            self._server_combo.addItem(s)
        idx = self._server_combo.findText(self._ntp.server)
        if idx >= 0:
            self._server_combo.setCurrentIndex(idx)
        self._server_combo.currentTextChanged.connect(self._on_server_changed)
        server_card.hBoxLayout.addWidget(self._server_combo)
        server_card.hBoxLayout.addSpacing(16)
        ntp_group.addSettingCard(server_card)

        # 同步间隔
        interval_card = _make_card(
            FIF.HISTORY,
            self._i18n.t("settings.ntp.interval.label"),
            self._i18n.t("settings.ntp.interval.desc"),
            ntp_group,
        )
        self._interval_spin = SpinBox()
        self._interval_spin.setRange(1, 1440)
        self._interval_spin.setValue(self._ntp.sync_interval_min)
        self._interval_spin.setSuffix(self._i18n.t("settings.unit.minute"))
        self._interval_spin.valueChanged.connect(self._on_interval_changed)
        interval_card.hBoxLayout.addWidget(self._interval_spin)
        interval_card.hBoxLayout.addSpacing(16)
        ntp_group.addSettingCard(interval_card)

        # 同步状态 + 立即同步
        self._sync_status_card = _make_card(FIF.INFO, self._i18n.t("settings.ntp.status.label"), self._status_text(), ntp_group)
        self._sync_btn = PushButton(FIF.SYNC, self._i18n.t("settings.ntp.sync_now"))
        self._sync_btn.clicked.connect(self._on_sync_now)
        self._sync_status_card.hBoxLayout.addWidget(self._sync_btn)
        self._sync_status_card.hBoxLayout.addSpacing(16)
        ntp_group.addSettingCard(self._sync_status_card)

        layout.addWidget(ntp_group)

        # ── 时间偏移──────────────────────────────────────────────── #
        time_debug_group = SettingCardGroup(self._i18n.t("settings.group.time_offset", default="时间偏移"))

        # 手动时间偏移
        time_offset_card = _make_card(
            FIF.CALENDAR,
            self._i18n.t("settings.time_offset.label", default="时间偏移"),
            self._i18n.t("settings.time_offset.desc", default="手动设置时间偏移（秒）"),
            time_debug_group,
        )
        self._time_offset_spin = SpinBox()
        self._time_offset_spin.setRange(-86400, 86400)  # -1天 ~ +1天
        self._time_offset_spin.setValue(self._app_settings.time_offset_seconds)
        self._time_offset_spin.setSuffix(self._i18n.t("settings.unit.second", default=" 秒"))
        self._time_offset_spin.valueChanged.connect(self._on_time_offset_changed)
        time_offset_card.hBoxLayout.addWidget(self._time_offset_spin)
        time_offset_card.hBoxLayout.addSpacing(16)
        time_debug_group.addSettingCard(time_offset_card)

        # 重置按钮
        reset_offset_card = _make_card(
            FIF.CANCEL,
            self._i18n.t("settings.time_offset.reset.label", default="重置偏移"),
            self._i18n.t("settings.time_offset.reset.desc", default="将时间偏移重置为 0"),
            time_debug_group,
        )
        self._reset_offset_btn = PushButton(FIF.CANCEL, self._i18n.t("common.reset", default="重置"))
        self._reset_offset_btn.clicked.connect(self._on_reset_time_offset)
        reset_offset_card.hBoxLayout.addWidget(self._reset_offset_btn)
        reset_offset_card.hBoxLayout.addSpacing(16)
        time_debug_group.addSettingCard(reset_offset_card)

        layout.addWidget(time_debug_group)

        # ── URL Scheme ────────────────────────────────────────────────── #
        url_group = SettingCardGroup(self._i18n.t("settings.group.url"))

        # 协议名称 + 可用地址
        open_view_keys = sorted(uss.list_open_views().keys())
        url_hint_lines = [uss.build_open_url(key) for key in open_view_keys]
        url_hint_lines.append(f"{URL_SCHEME}://fullscreen/<zone_id>")
        url_name_card = _make_card(
            FIF.LINK,
            self._i18n.t("settings.url.name.label"),
            self._i18n.t("settings.url.name.desc", scheme=URL_SCHEME, views="  |  ".join(url_hint_lines)),
            url_group,
        )
        url_group.addSettingCard(url_name_card)

        # 注册状态 + 操作按钮
        self._url_status_card = _make_card(FIF.CERTIFICATE, self._i18n.t("settings.url.status.label"), self._url_status_text(), url_group)
        self._url_reg_btn = PushButton(FIF.LINK, "")
        self._url_reg_btn.setMinimumWidth(140)
        self._url_reg_btn.clicked.connect(self._on_url_toggle)
        self._refresh_url_btn_text()
        self._url_status_card.hBoxLayout.addWidget(self._url_reg_btn)
        self._url_status_card.hBoxLayout.addSpacing(16)
        url_group.addSettingCard(self._url_status_card)

        layout.addWidget(url_group)

        # ── 秒表 / 计时器 ────────────────────────────────── #
        sw_group = SettingCardGroup(self._i18n.t("settings.group.timer"))

        # 秒表精度
        sw_card = _make_card(
            FIF.STOP_WATCH,
            self._i18n.t("settings.timer.sw_precision.label"),
            self._i18n.t("settings.timer.sw_precision.desc"),
            sw_group,
        )
        self._sw_precision_combo = ComboBox()
        for label in _precision_labels(self._i18n):
            self._sw_precision_combo.addItem(label)
        self._sw_precision_combo.setCurrentIndex(self._app_settings.stopwatch_precision)
        self._sw_precision_combo.currentIndexChanged.connect(self._on_sw_precision_changed)
        sw_card.hBoxLayout.addWidget(self._sw_precision_combo)
        sw_card.hBoxLayout.addSpacing(16)
        sw_group.addSettingCard(sw_card)

        # 计时器精度
        timer_card = _make_card(
            FIF.STOP_WATCH,
            self._i18n.t("settings.timer.timer_precision.label"),
            self._i18n.t("settings.timer.timer_precision.desc"),
            sw_group,
        )
        self._timer_precision_combo = ComboBox()
        for label in _precision_labels(self._i18n):
            self._timer_precision_combo.addItem(label)
        self._timer_precision_combo.setCurrentIndex(self._app_settings.timer_precision)
        self._timer_precision_combo.currentIndexChanged.connect(self._on_timer_precision_changed)
        timer_card.hBoxLayout.addWidget(self._timer_precision_combo)
        timer_card.hBoxLayout.addSpacing(16)
        sw_group.addSettingCard(timer_card)

        # 小窗不透明度
        opacity_card = _make_card(
            FIF.TRANSPARENT,
            self._i18n.t("settings.timer.opacity.label"),
            self._i18n.t("settings.timer.opacity.desc"),
            sw_group,
        )
        self._float_opacity_slider = Slider(Qt.Horizontal)
        self._float_opacity_slider.setRange(10, 100)
        self._float_opacity_slider.setValue(self._app_settings.float_opacity)
        self._float_opacity_slider.setMinimumWidth(160)
        self._float_opacity_val_lbl = CaptionLabel(f"{self._app_settings.float_opacity} %")
        self._float_opacity_val_lbl.setFixedWidth(40)
        self._float_opacity_slider.valueChanged.connect(self._on_opacity_changed)
        opacity_card.hBoxLayout.addWidget(self._float_opacity_slider, 1)
        opacity_card.hBoxLayout.addWidget(self._float_opacity_val_lbl)
        opacity_card.hBoxLayout.addSpacing(16)
        sw_group.addSettingCard(opacity_card)

        layout.addWidget(sw_group)

        # ── 铃声列表 ──────────────────────────────────────────── #
        ring_group = SettingCardGroup(self._i18n.t("settings.group.ringtone"))
        self._ring_card = _RingtoneCard(ring_group)
        self._ring_card.addBtn.clicked.connect(self._on_ring_add)
        self._ring_card.previewBtn.clicked.connect(self._on_ring_preview)
        self._ring_card.deleteBtn.clicked.connect(self._on_ring_delete)
        ring_group.vBoxLayout.addWidget(self._ring_card)
        layout.addWidget(ring_group)
        self._refresh_ring_list()

        # ── 通知系统 ──────────────────────────────────────────── #
        notif_group = SettingCardGroup(self._i18n.t("settings.group.notification"))

        # 出现位置
        notif_pos_card = _make_card(
            FIF.PIN,
            self._i18n.t("settings.notif.pos.label"),
            self._i18n.t("settings.notif.pos.desc"),
            notif_group,
        )
        self._notif_pos_combo = ComboBox()
        for key in ALL_POSITIONS:
            self._notif_pos_combo.addItem(_position_label(self._i18n, key), userData=key)
        cur_pos = self._app_settings.notification_position
        for i in range(self._notif_pos_combo.count()):
            if self._notif_pos_combo.itemData(i) == cur_pos:
                self._notif_pos_combo.setCurrentIndex(i)
                break
        self._notif_pos_combo.currentIndexChanged.connect(self._on_notif_pos_changed)
        notif_pos_card.hBoxLayout.addWidget(self._notif_pos_combo)
        notif_pos_card.hBoxLayout.addSpacing(16)
        notif_group.addSettingCard(notif_pos_card)

        # 停留时间
        notif_dur_card = _make_card(
            FIF.STOP_WATCH,
            self._i18n.t("settings.notif.duration.label"),
            self._i18n.t("settings.notif.duration.desc"),
            notif_group,
        )
        self._notif_dur_spin = SpinBox()
        self._notif_dur_spin.setRange(0, 60)
        self._notif_dur_spin.setValue(self._app_settings.notification_duration_ms // 1000)
        self._notif_dur_spin.setSuffix(self._i18n.t("settings.unit.second"))
        self._notif_dur_spin.setSpecialValueText(self._i18n.t("settings.notif.sticky"))
        self._notif_dur_spin.valueChanged.connect(self._on_notif_dur_changed)
        notif_dur_card.hBoxLayout.addWidget(self._notif_dur_spin)
        notif_dur_card.hBoxLayout.addSpacing(16)
        notif_group.addSettingCard(notif_dur_card)

        # 测试通知
        notif_test_card = _make_card(
            FIF.SEND,
            self._i18n.t("settings.notif.test.label"),
            self._i18n.t("settings.notif.test.desc"),
            notif_group,
        )
        self._notif_test_btn = PushButton(FIF.RINGER, self._i18n.t("settings.notif.test.label"))
        self._notif_test_btn.clicked.connect(self._on_notif_test)
        notif_test_card.hBoxLayout.addWidget(self._notif_test_btn)
        notif_test_card.hBoxLayout.addSpacing(16)
        notif_group.addSettingCard(notif_test_card)

        layout.addWidget(notif_group)

        # ── 闹钟 ─────────────────────────────────────────────────── #
        alarm_group = SettingCardGroup(self._i18n.t("settings.group.alarm"))

        alert_dur_card = _make_card(
            FIF.STOP_WATCH,
            self._i18n.t("settings.alarm.alert.label"),
            self._i18n.t("settings.alarm.alert.desc"),
            alarm_group,
        )
        self._alarm_alert_dur_spin = SpinBox()
        self._alarm_alert_dur_spin.setRange(10, 600)
        self._alarm_alert_dur_spin.setValue(self._app_settings.alarm_alert_duration_sec)
        self._alarm_alert_dur_spin.setSuffix(self._i18n.t("settings.unit.second"))
        self._alarm_alert_dur_spin.valueChanged.connect(self._on_alarm_alert_dur_changed)
        alert_dur_card.hBoxLayout.addWidget(self._alarm_alert_dur_spin)
        alert_dur_card.hBoxLayout.addSpacing(16)
        alarm_group.addSettingCard(alert_dur_card)

        layout.addWidget(alarm_group)

        # ── 文件类型打开 ──────────────────────────────────────────── #
        filetype_group = SettingCardGroup(
            _tr(self._i18n, "文件类型打开", "File Type Open")
        )
        self._file_type_list = ListWidget()
        self._file_type_list.setFixedHeight(120)
        self._refresh_file_type_list()
        filetype_list_card = CardWidget(filetype_group)
        filetype_list_card_layout = VBoxLayout(filetype_list_card)
        filetype_list_card_layout.setContentsMargins(20, 16, 20, 16)
        hint = CaptionLabel(
            _tr(
                self._i18n,
                "以下展示程序内置和插件注册的文件类型打开方式",
                "The following file type open methods include built-in and plugin-registered entries.",
            )
        )
        hint.setWordWrap(True)
        filetype_list_card_layout.addWidget(hint)
        filetype_list_card_layout.addWidget(self._file_type_list)
        filetype_group.vBoxLayout.addWidget(filetype_list_card)
        layout.addWidget(filetype_group)

        # ── 测试版水印（仅 IS_BETA 时显示）──────────────────────────── #
        if IS_BETA:
            beta_group = SettingCardGroup(_tr(self._i18n, "测试版水印", "Beta Watermark"))

            # 主窗口水印开关
            wm_main_card = _make_card(
                FIF.VIEW,
                _tr(self._i18n, "主窗口水印", "Main Window Watermark"),
                _tr(self._i18n, "对角平铺及右下角版本信息水印（主界面）", "Diagonal tiled watermark and bottom-right version info watermark (main window)"),
                beta_group,
            )
            self._wm_main_switch = SwitchButton()
            self._wm_main_switch.setChecked(self._app_settings.watermark_main_visible)
            self._wm_main_switch.checkedChanged.connect(self._on_wm_main_toggle)
            wm_main_card.hBoxLayout.addWidget(self._wm_main_switch)
            wm_main_card.hBoxLayout.addSpacing(16)
            beta_group.addSettingCard(wm_main_card)

            # 世界时间视图水印开关
            wm_wt_card = _make_card(
                FIF.VIEW,
                _tr(self._i18n, "世界时间视图水印", "World Time View Watermark"),
                _tr(self._i18n, "全屏世界时钟画布上的测试版水印", "Beta watermark on fullscreen world-time canvas"),
                beta_group,
            )
            self._wm_wt_switch = SwitchButton()
            self._wm_wt_switch.setChecked(self._app_settings.watermark_worldtime_visible)
            self._wm_wt_switch.checkedChanged.connect(self._on_wm_wt_toggle)
            wm_wt_card.hBoxLayout.addWidget(self._wm_wt_switch)
            wm_wt_card.hBoxLayout.addSpacing(16)
            beta_group.addSettingCard(wm_wt_card)

            layout.addWidget(beta_group)

        # ── 启动选项 ─────────────────────────────────────────────────── #
        startup_group = SettingCardGroup(self._i18n.t("settings.group.startup",
                                                       default="启动选项"))

        autostart_card = _make_card(
            FIF.PLAY,
            self._i18n.t("settings.startup.autostart.label", default="开机自启动"),
            self._i18n.t(
                "settings.startup.autostart.desc",
                default="登录 Windows 后自动启动小树时钟",
            ),
            startup_group,
        )
        self._autostart_switch = SwitchButton()
        self._autostart_switch.setChecked(startup.is_enabled())
        self._autostart_switch.checkedChanged.connect(self._on_autostart_toggle)
        autostart_card.hBoxLayout.addWidget(self._autostart_switch)
        autostart_card.hBoxLayout.addSpacing(16)
        startup_group.addSettingCard(autostart_card)

        # 开机自启动时隐藏到托盘
        hide_to_tray_card = _make_card(
            FIF.MINIMIZE,
            self._i18n.t("settings.startup.hide_to_tray.label", default="自启动时隐藏到托盘"),
            self._i18n.t(
                "settings.startup.hide_to_tray.desc",
                default="开机自启动时不显示主窗口，仅在系统托盘运行",
            ),
            startup_group,
        )
        self._hide_to_tray_switch = SwitchButton()
        self._hide_to_tray_switch.setChecked(self._app_settings.autostart_hide_to_tray)
        self._hide_to_tray_switch.checkedChanged.connect(self._on_hide_to_tray_toggle)
        hide_to_tray_card.hBoxLayout.addWidget(self._hide_to_tray_switch)
        hide_to_tray_card.hBoxLayout.addSpacing(16)
        startup_group.addSettingCard(hide_to_tray_card)

        boot_menu_card = _make_card(
            FIF.PLAY,
            self._i18n.t("settings.startup.boot_menu.label", default="下次启动打开启动菜单"),
            self._i18n.t("settings.startup.boot_menu.desc",
                          default="下次启动时显示启动选项菜单（正常/安全/隐藏/自定义），仅生效一次"),
            startup_group,
        )
        self._boot_menu_switch = SwitchButton()
        self._boot_menu_switch.setChecked(self._app_settings.show_boot_menu_next_start)
        self._boot_menu_switch.checkedChanged.connect(self._on_boot_menu_toggle)
        boot_menu_card.hBoxLayout.addWidget(self._boot_menu_switch)
        boot_menu_card.hBoxLayout.addSpacing(16)
        startup_group.addSettingCard(boot_menu_card)

        layout.addWidget(startup_group)

        # ── 更新 ─────────────────────────────────────────────────────── #
        update_group = SettingCardGroup(_tr(self._i18n, "更新", "Updates"))

        update_channel_card = _make_card(
            FIF.GLOBE,
            _tr(self._i18n, "更新频道", "Update Channel"),
            _tr(
                self._i18n,
                "选择接收的更新渠道。稳定版推荐日常使用；测试版和开发版用于预览新功能。",
                "Choose which release channel to receive. Stable is recommended for daily use; Beta and Dev are preview channels.",
            ),
            update_group,
        )
        self._update_channel_combo = ComboBox()
        for label, key in _update_channel_options(self._i18n):
            self._update_channel_combo.addItem(label, userData=key)
        for i in range(self._update_channel_combo.count()):
            if self._update_channel_combo.itemData(i) == self._app_settings.update_channel:
                self._update_channel_combo.setCurrentIndex(i)
                break
        self._update_channel_combo.currentIndexChanged.connect(self._on_update_channel_changed)
        update_channel_card.hBoxLayout.addWidget(self._update_channel_combo)
        update_channel_card.hBoxLayout.addSpacing(16)
        update_group.addSettingCard(update_channel_card)

        update_auto_check_card = _make_card(
            FIF.SYNC,
            _tr(self._i18n, "启动后自动检查", "Check on Startup"),
            _tr(
                self._i18n,
                "程序启动并完成初始化后自动检查一次更新。",
                "Automatically check for updates once after app startup finishes initialization.",
            ),
            update_group,
        )
        self._update_auto_check_switch = SwitchButton()
        self._update_auto_check_switch.setChecked(self._app_settings.update_auto_check_enabled)
        self._update_auto_check_switch.checkedChanged.connect(self._on_update_auto_check_toggle)
        update_auto_check_card.hBoxLayout.addWidget(self._update_auto_check_switch)
        update_auto_check_card.hBoxLayout.addSpacing(16)
        update_group.addSettingCard(update_auto_check_card)

        update_popup_card = _make_card(
            FIF.MESSAGE,
            _tr(self._i18n, "启动时弹出更新窗口", "Show Update Window on Startup"),
            _tr(
                self._i18n,
                "检测到新版本时，在本次启动阶段自动弹出一次更新窗口。",
                "When a newer version is found, automatically show the update window once during startup.",
            ),
            update_group,
        )
        self._update_popup_switch = SwitchButton()
        self._update_popup_switch.setChecked(self._app_settings.update_startup_popup_enabled)
        self._update_popup_switch.checkedChanged.connect(self._on_update_popup_toggle)
        update_popup_card.hBoxLayout.addWidget(self._update_popup_switch)
        update_popup_card.hBoxLayout.addSpacing(16)
        update_group.addSettingCard(update_popup_card)

        self._update_status_card = _make_card(
            FIF.DOWNLOAD,
            _tr(self._i18n, "检查更新", "Check for Updates"),
            "",
            update_group,
        )
        self._check_update_btn = PushButton(FIF.SYNC, _tr(self._i18n, "检查更新", "Check Now"))
        self._check_update_btn.clicked.connect(self._on_check_updates_clicked)
        self._update_status_card.hBoxLayout.addWidget(self._check_update_btn)
        self._update_status_card.hBoxLayout.addSpacing(16)
        update_group.addSettingCard(self._update_status_card)

        layout.addWidget(update_group)

        # ── 插件 ─────────────────────────────────────────────────────── #
        plugin_group = SettingCardGroup(_tr(self._i18n, "插件", "Plugins"))

        pip_mirror_card = _make_card(
            FIF.DOWNLOAD,
            _tr(self._i18n, "依赖安装来源", "Dependency Source"),
            _tr(self._i18n, "安装插件第三方依赖时使用的 pip 镜像源，国内用户建议选择清华或阿里云", "pip mirror used when installing plugin dependencies"),
            plugin_group,
        )
        self._pip_mirror_combo = ComboBox()
        for name, url in PIP_MIRRORS:
            self._pip_mirror_combo.addItem(name, userData=url)
        _cur_mirror = self._app_settings.pip_mirror
        for i in range(self._pip_mirror_combo.count()):
            if self._pip_mirror_combo.itemData(i) == _cur_mirror:
                self._pip_mirror_combo.setCurrentIndex(i)
                break
        self._pip_mirror_combo.currentIndexChanged.connect(self._on_pip_mirror_changed)
        pip_mirror_card.hBoxLayout.addWidget(self._pip_mirror_combo)
        pip_mirror_card.hBoxLayout.addSpacing(16)
        plugin_group.addSettingCard(pip_mirror_card)

        layout.addWidget(plugin_group)

        # 插件设置的动态插入位置（在「关于」之前）
        self._plugin_settings_insert_idx = layout.count()

        # 将已加载插件的设置面板注入（插件先于设置视图初始化的情况）
        if plugin_manager is not None:
            for entry in plugin_manager.all_entries():
                try:
                    if entry.plugin.has_settings_widget():
                        pid = entry.meta.id
                        display = entry.meta.get_name(self._i18n.language) if entry.meta else pid
                        self._insert_plugin_settings_factory(
                            pid,
                            display,
                            entry.plugin.create_settings_widget,
                        )
                except Exception:
                    pass

        # ── 配置迁移 ─────────────────────────────────────────────── #
        migration_group = SettingCardGroup(_tr(self._i18n, "配置迁移", "Config Migration"))

        migration_card = _make_card(
            FIF.SYNC,
            _tr(self._i18n, "配置迁移", "Config Migration"),
            _tr(self._i18n, "导出或导入应用配置、插件及其数据", "Export or import app settings, plugins and their data"),
            migration_group,
        )
        self._migration_btn = PushButton(FIF.SYNC, _tr(self._i18n, "打开迁移工具", "Open Migration Tool"))
        self._migration_btn.setMinimumWidth(140)
        self._migration_btn.clicked.connect(self._on_migration_clicked)
        migration_card.hBoxLayout.addWidget(self._migration_btn)
        migration_card.hBoxLayout.addSpacing(16)
        migration_group.addSettingCard(migration_card)

        layout.addWidget(migration_group)

        # ── 关于 ──────────────────────────────────────────────────── #
        about_group = SettingCardGroup(_tr(self._i18n, "关于", "About"))

        about_card = _make_card(
            FIF.INFO,
            _tr(self._i18n, f"关于 {APP_NAME}", f"About {APP_NAME}"),
            _tr(self._i18n, f"版本 {APP_VERSION}  ·  查看项目信息、依赖列表、鸣谢与赞助", f"Version {APP_VERSION} · Project info, dependencies, acknowledgements and sponsors"),
            about_group,
        )
        self._about_btn = PushButton(FIF.INFO, _tr(self._i18n, "关于本项目", "About This Project"))
        self._about_btn.setMinimumWidth(120)
        self._about_btn.clicked.connect(self._on_about_clicked)
        about_card.hBoxLayout.addWidget(self._about_btn)
        about_card.hBoxLayout.addSpacing(16)
        about_group.addSettingCard(about_card)

        layout.addWidget(about_group)

        layout.addWidget(BodyLabel(self._i18n.t("settings.more")))
        layout.addStretch()

        self.setWidget(container)
        self.setWidgetResizable(True)
        self.enableTransparentBackground()

        # 每 5 秒刷新一次 NTP 状态文字
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(5_000)
        self._refresh_timer.timeout.connect(self._refresh_status)
        self._refresh_timer.start()

        if self._update_service is not None:
            self._update_service.stateChanged.connect(self._refresh_update_settings_status)

        self._update_controls_state()
        self._update_notif_controls()
        self._refresh_update_settings_status()
        self._about_window = None
        self._migration_window = None

    def _ensure_settings_permission(self, reason: str) -> bool:
        if self._permission_service is None:
            return True
        ok = self._permission_service.ensure_access(
            "settings.modify",
            parent=self.window(),
            reason=reason,
        )
        if ok:
            return True
        deny_reason = self._permission_service.get_last_denied_reason("settings.modify")
        InfoBar.warning(
            self._i18n.t("app.nav.settings", default="设置"),
            deny_reason or self._i18n.t("perm.access.denied", default="权限不足，无法执行该操作。"),
            parent=self.window(),
            position=InfoBarPosition.TOP_RIGHT,
            duration=2500,
        )
        return False

    # ------------------------------------------------------------------ #
    # 全屏时钟
    # ------------------------------------------------------------------ #

    @Slot(int)
    def _on_cell_size_changed(self, value: int) -> None:
        if not self._ensure_settings_permission("调整全屏时钟格子大小"):
            return
        # 滑出和到最近10的倍数，避免每一个像素都触发一次重排
        snapped = round(value / 10) * 10
        self._cell_size_val_lbl.setText(f"{snapped} px")
        self._update_cell_size_preview(snapped)
        self._app_settings.set_widget_cell_size(snapped)

    def _update_cell_size_preview(self, cell_size: int) -> None:
        cols, rows = self._estimate_fullscreen_grid(cell_size)
        if cols > 0 and rows > 0:
            extra = _tr(
                self._i18n,
                f"\n预计完整格子数：{cols} × {rows} = {cols * rows} 格（按主屏幕估算）",
                f"\nEstimated full cells: {cols} × {rows} = {cols * rows} (based on primary screen)",
            )
        else:
            extra = _tr(
                self._i18n,
                "\n预计完整格子数：0 格（当前格子尺寸已超过主屏幕尺寸）",
                "\nEstimated full cells: 0 (current cell size exceeds primary screen)",
            )
        self._cell_size_card.contentLabel.setText(f"{self._cell_size_desc}{extra}")

    def _estimate_fullscreen_grid(self, cell_size: int) -> tuple[int, int]:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return 0, 0
        geometry = screen.geometry()
        if cell_size <= 0:
            return 0, 0
        return max(0, geometry.width() // cell_size), max(0, geometry.height() // cell_size)

    @Slot(int)
    def _on_detached_opacity_changed(self, value: int) -> None:
        if not self._ensure_settings_permission("调整分离窗口背景透明度"):
            return
        snapped = round(value / 5) * 5
        self._detached_opacity_val_lbl.setText(f"{snapped}%")
        self._app_settings.set_detached_widget_background_opacity(snapped)

    @Slot(bool)
    def _on_canvas_overlap_group_toggle(self, checked: bool) -> None:
        if not self._ensure_settings_permission("切换画布重叠自动分组"):
            return
        self._app_settings.set_widget_canvas_overlap_group_enabled(checked)

    @Slot(bool)
    def _on_detached_overlap_merge_toggle(self, checked: bool) -> None:
        if not self._ensure_settings_permission("切换分离窗口重叠自动并组"):
            return
        self._app_settings.set_widget_detached_overlap_merge_enabled(checked)

    @Slot(bool)
    def _on_auto_fill_gap_toggle(self, checked: bool) -> None:
        if not self._ensure_settings_permission("切换新增组件自动补齐空位"):
            return
        self._app_settings.set_widget_auto_fill_gap_enabled(checked)
        self._sync_new_widget_placement_controls()

    @Slot(bool)
    def _on_prevent_new_overflow_toggle(self, checked: bool) -> None:
        if not self._ensure_settings_permission("切换新增组件溢出防护"):
            return
        self._app_settings.set_widget_prevent_new_overflow_enabled(checked)
        self._sync_new_widget_placement_controls()

    def _sync_new_widget_placement_controls(self) -> None:
        auto_fill = self._app_settings.widget_auto_fill_gap_enabled
        prevent_overflow = self._app_settings.widget_prevent_new_overflow_enabled

        self._prevent_new_overflow_switch.setEnabled(auto_fill)
        self._prevent_new_overflow_switch.blockSignals(True)
        self._prevent_new_overflow_switch.setChecked(prevent_overflow)
        self._prevent_new_overflow_switch.blockSignals(False)

    # ------------------------------------------------------------------ #
    # NTP
    # ------------------------------------------------------------------ #

    def _status_text(self) -> str:
        if not self._ntp.enabled:
            return self._i18n.t("settings.ntp.status.off")
        if self._ntp.is_syncing:
            return self._i18n.t("settings.ntp.status.syncing")
        err = self._ntp.last_error
        if err:
            return self._i18n.t("settings.ntp.status.failed", error=err)
        offset = self._ntp.offset_str()
        t = self._ntp.last_sync_time_str()
        return self._i18n.t("settings.ntp.status.ok", time=t, offset=offset)

    @Slot()
    def _refresh_status(self) -> None:
        self._sync_status_card.contentLabel.setText(self._status_text())

    @Slot(bool)
    def _on_ntp_toggle(self, checked: bool) -> None:
        if not self._ensure_settings_permission("切换 NTP 网络校时"):
            return
        self._ntp.set_enabled(checked)
        self._update_controls_state()
        self._refresh_status()

    @Slot(str)
    def _on_server_changed(self, server: str) -> None:
        if not self._ensure_settings_permission("修改 NTP 服务器"):
            return
        self._ntp.set_server(server)

    @Slot(int)
    def _on_interval_changed(self, value: int) -> None:
        if not self._ensure_settings_permission("修改 NTP 同步间隔"):
            return
        self._ntp.set_sync_interval(value)

    @Slot()
    def _on_sync_now(self) -> None:
        if not self._ntp.enabled:
            InfoBar.warning(
                title=self._i18n.t("settings.ntp.not_enabled.title"),
                content=self._i18n.t("settings.ntp.not_enabled.content"),
                parent=self,
                position=InfoBarPosition.TOP,
                duration=3000,
            )
            return
        self._ntp.sync_once()
        self._sync_status_card.contentLabel.setText(self._i18n.t("settings.ntp.status.syncing"))
        QTimer.singleShot(3500, self._refresh_status)

    def _update_controls_state(self) -> None:
        enabled = self._ntp.enabled
        self._server_combo.setEnabled(enabled)
        self._interval_spin.setEnabled(enabled)
        self._sync_btn.setEnabled(enabled)

    # ------------------------------------------------------------------ #
    # 时间调试
    # ------------------------------------------------------------------ #

    @Slot(int)
    def _on_time_offset_changed(self, value: int) -> None:
        if not self._ensure_settings_permission("修改时间偏移"):
            return
        self._app_settings.set_time_offset_seconds(value)

    @Slot()
    def _on_reset_time_offset(self) -> None:
        if not self._ensure_settings_permission("重置时间偏移"):
            return
        self._time_offset_spin.setValue(0)
        self._app_settings.set_time_offset_seconds(0)

    # ------------------------------------------------------------------ #
    # 秒表 / 计时器
    # ------------------------------------------------------------------ #

    @Slot(int)
    def _on_language_changed(self, index: int) -> None:
        if not self._ensure_settings_permission("切换语言"):
            return
        key = self._language_combo.itemData(index)
        if not key:
            return
        self._app_settings.set_language(str(key))
        self._i18n.set_language(str(key))
        InfoBar.success(
            title=self._i18n.t("settings.language.saved_title"),
            content=self._i18n.t(
                "settings.language.saved_content",
                language=self._i18n.t(f"lang.{str(key)}"),
            ),
            parent=self,
            position=InfoBarPosition.TOP,
            duration=3500,
        )

    @Slot(int)
    def _on_sw_precision_changed(self, index: int) -> None:
        if not self._ensure_settings_permission("修改秒表精度"):
            return
        self._app_settings.set_stopwatch_precision(index)

    @Slot(int)
    def _on_timer_precision_changed(self, index: int) -> None:
        if not self._ensure_settings_permission("修改计时器精度"):
            return
        self._app_settings.set_timer_precision(index)

    @Slot(int)
    def _on_opacity_changed(self, value: int) -> None:
        if not self._ensure_settings_permission("修改悬浮窗不透明度"):
            return
        self._float_opacity_val_lbl.setText(f"{value} %")
        self._app_settings.set_float_opacity(value)

    # ------------------------------------------------------------------ #
    # URL Scheme
    # ------------------------------------------------------------------ #

    def _url_status_text(self) -> str:
        if not uss.is_registered():
            return self._i18n.t("settings.url.status.off")
        return self._i18n.t("settings.url.status.on", scheme=URL_SCHEME)

    def _refresh_url_btn_text(self) -> None:
        if uss.is_registered():
            self._url_reg_btn.setText(self._i18n.t("settings.url.unregister"))
        else:
            self._url_reg_btn.setText(self._i18n.t("settings.url.register"))

    @Slot()
    def _on_url_toggle(self) -> None:
        if not self._ensure_settings_permission("注册或注销 URL 协议"):
            return
        if uss.is_registered():
            ok, msg = uss.unregister()
        else:
            ok, msg = uss.register()

        self._url_status_card.contentLabel.setText(self._url_status_text())
        self._refresh_url_btn_text()

        if ok:
            InfoBar.success(
                title=self._i18n.t("settings.url.infobar_title"),
                content=msg,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self,
            )
        else:
            InfoBar.error(
                title=self._i18n.t("settings.url.infobar_title"),
                content=msg,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=5000,
                parent=self,
            )

    # ------------------------------------------------------------------ #
    # 铃声列表
    # ------------------------------------------------------------------ #

    def _refresh_ring_list(self) -> None:
        lw = self._ring_card.listWidget
        lw.clear()
        for r in self._app_settings.ringtones:
            item = QListWidgetItem(f"{r['name']}  |  {r['path']}")
            item.setData(Qt.UserRole, r["path"])
            lw.addItem(item)

    @Slot()
    def _on_ring_add(self) -> None:
        if not self._ensure_settings_permission("添加铃声"):
            return
        result = rs.select_sound_path(self.window())
        if result is None:
            return
        name, path = result
        self._app_settings.add_ringtone(name, path)
        self._refresh_ring_list()
        InfoBar.success(
            title=self._i18n.t("settings.ringtone.added.title"),
            content=self._i18n.t("settings.ringtone.added.content", name=name),
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=3000,
            parent=self,
        )

    @Slot()
    def _on_ring_preview(self) -> None:
        item = self._ring_card.listWidget.currentItem()
        if item:
            rs.play_sound(item.data(Qt.UserRole))
        else:
            rs.play_default()

    @Slot()
    def _on_ring_delete(self) -> None:
        if not self._ensure_settings_permission("删除铃声"):
            return
        item = self._ring_card.listWidget.currentItem()
        if not item:
            return
        path = item.data(Qt.UserRole)
        name = item.text().split("  |  ")[0]
        self._app_settings.remove_ringtone(path)
        self._refresh_ring_list()
        InfoBar.success(
            title=self._i18n.t("settings.ringtone.removed.title"),
            content=self._i18n.t("settings.ringtone.removed.content", name=name),
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=2000,
            parent=self,
        )

    # ------------------------------------------------------------------ #
    # 文件类型打开
    # ------------------------------------------------------------------ #

    def _refresh_file_type_list(self) -> None:
        if not hasattr(self, "_file_type_list") or self._file_type_list is None:
            return
        lw = self._file_type_list
        lw.clear()
        seen_extensions: set[str] = set()

        for ext, title, source in self._BUILTIN_FILE_TYPE_BINDINGS:
            normalized_ext = str(ext or "").strip().lower()
            if not normalized_ext:
                continue
            seen_extensions.add(normalized_ext)
            lw.addItem(f"{normalized_ext}  |  {title}  |  {source}")

        for item in self._file_type_service.list_registered_extensions():
            ext = item.get("extension", "")
            title = item.get("title", "")
            plugin_id = item.get("plugin_id", "")
            normalized_ext = str(ext or "").strip().lower()
            if not normalized_ext or normalized_ext in seen_extensions:
                continue
            seen_extensions.add(normalized_ext)
            lw.addItem(f"{ext}  |  {title}  |  {plugin_id}")

    # ------------------------------------------------------------------ #
    # 通知系统
    # ------------------------------------------------------------------ #

    def _update_notif_controls(self) -> None:
        # 始终展示，应用内置通知不可关闭
        self._notif_pos_combo.setEnabled(True)
        self._notif_dur_spin.setEnabled(True)
        self._notif_test_btn.setEnabled(True)

    @Slot(int)
    def _on_notif_pos_changed(self, _: int) -> None:
        if not self._ensure_settings_permission("修改通知位置"):
            return
        key = self._notif_pos_combo.currentData()
        if key:
            self._app_settings.set_notification_position(key)
            self._sync_toast_manager()

    @Slot(int)
    def _on_notif_dur_changed(self, seconds: int) -> None:
        if not self._ensure_settings_permission("修改通知停留时长"):
            return
        self._app_settings.set_notification_duration_ms(seconds * 1000)
        self._sync_toast_manager()

    def _sync_toast_manager(self) -> None:
        """将当前设置同步到 ToastManager（若已注入）"""
        try:
            w = self.window()
            if hasattr(w, '_toast_mgr') and w._toast_mgr is not None:
                w._toast_mgr.set_position(self._app_settings.notification_position)
                w._toast_mgr.set_duration(self._app_settings.notification_duration_ms)
        except Exception:
            pass

    @Slot()
    def _on_notif_test(self) -> None:
        try:
            w = self.window()
            if hasattr(w, '_toast_mgr') and w._toast_mgr is not None:
                w._toast_mgr.show_toast(
                    self._i18n.t("settings.notif.test.msg_title"),
                    self._i18n.t("settings.notif.test.msg_content"),
                )
        except Exception as e:
            InfoBar.error(
                title=self._i18n.t("settings.notif.test.error"),
                content=str(e),
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self,
            )

    # ------------------------------------------------------------------ #
    # 闹钟
    # ------------------------------------------------------------------ #

    @Slot(int)
    def _on_alarm_alert_dur_changed(self, value: int) -> None:
        if not self._ensure_settings_permission("修改闹钟提醒时长"):
            return
        self._app_settings.set_alarm_alert_duration_sec(value)

    # ------------------------------------------------------------------ #
    # 测试版水印
    # ------------------------------------------------------------------ #

    @Slot(bool)
    def _on_wm_main_toggle(self, checked: bool) -> None:
        if not self._ensure_settings_permission("切换主窗口水印"):
            return
        if not checked:
            dlg = _WatermarkDisclaimerDialog(_tr(self._i18n, "主窗口水印", "Main Window Watermark"), self.window())
            if not dlg.exec():
                # 用户取消 / 未同意 → 恢复开关，阻断信号避免循环
                self._wm_main_switch.blockSignals(True)
                self._wm_main_switch.setChecked(True)
                self._wm_main_switch.blockSignals(False)
                return
        self._app_settings.set_watermark_main_visible(checked)

    @Slot(bool)
    def _on_wm_wt_toggle(self, checked: bool) -> None:
        if not self._ensure_settings_permission("切换世界时间水印"):
            return
        if not checked:
            dlg = _WatermarkDisclaimerDialog(_tr(self._i18n, "世界时间视图水印", "World Time View Watermark"), self.window())
            if not dlg.exec():
                self._wm_wt_switch.blockSignals(True)
                self._wm_wt_switch.setChecked(True)
                self._wm_wt_switch.blockSignals(False)
                return
        self._app_settings.set_watermark_worldtime_visible(checked)

    # ------------------------------------------------------------------ #
    # 外观主题
    # ------------------------------------------------------------------ #

    @Slot(int)
    def _on_theme_changed(self, _: int) -> None:
        if not self._ensure_settings_permission("切换主题"):
            return
        key = self._theme_combo.currentData()
        if key:
            self._app_settings.set_theme(key)
            if key == "dark":
                setTheme(Theme.DARK)
            elif key == "light":
                setTheme(Theme.LIGHT)
            else:
                setTheme(Theme.AUTO)

    @Slot(bool)
    def _on_smooth_scroll_toggle(self, checked: bool) -> None:
        if not self._ensure_settings_permission("切换动画开关"):
            return
        self._app_settings.set_ui_smooth_scroll_enabled(checked)

    # ------------------------------------------------------------------ #
    # 启动选项
    # ------------------------------------------------------------------ #

    @Slot(bool)
    def _on_autostart_toggle(self, checked: bool) -> None:
        if not self._ensure_settings_permission("切换开机自启动"):
            return
        ok, msg = startup.set_enabled_with_settings(checked)
        if not ok:
            self._autostart_switch.blockSignals(True)
            self._autostart_switch.setChecked(not checked)
            self._autostart_switch.blockSignals(False)
            InfoBar.error(
                title=self._i18n.t("settings.startup.autostart.label", default="开机自启动"),
                content=msg,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=4500,
                parent=self,
            )
            return

        InfoBar.success(
            title=self._i18n.t("settings.startup.autostart.label", default="开机自启动"),
            content=msg,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=3000,
            parent=self,
        )

    @Slot(bool)
    def _on_hide_to_tray_toggle(self, checked: bool) -> None:
        if not self._ensure_settings_permission("切换自启动隐藏到托盘"):
            return
        self._app_settings.set_autostart_hide_to_tray(checked)
        # 如果已启用自启动，需要重新注册以更新启动参数
        if startup.is_enabled():
            ok, msg = startup.set_enabled_with_settings(True)
            if ok:
                InfoBar.success(
                    title=self._i18n.t("settings.startup.hide_to_tray.label", default="自启动时隐藏到托盘"),
                    content=self._i18n.t(
                        "settings.startup.hide_to_tray.updated",
                        default="设置已更新，下次开机生效",
                    ),
                    isClosable=True,
                    position=InfoBarPosition.TOP,
                    duration=3000,
                    parent=self,
                )

    @Slot(bool)
    def _on_boot_menu_toggle(self, checked: bool) -> None:
        if not self._ensure_settings_permission("切换下次启动菜单"):
            return
        self._app_settings.set_show_boot_menu_next_start(checked)

    # ------------------------------------------------------------------ #
    # 更新
    # ------------------------------------------------------------------ #

    def _update_status_text(self) -> str:
        channel_map = {
            "stable": _tr(self._i18n, "稳定版（推荐）", "Stable (recommended)"),
            "beta": _tr(self._i18n, "测试版", "Beta"),
            "dev": _tr(self._i18n, "开发版", "Dev"),
        }
        channel_text = channel_map.get(self._app_settings.update_channel, self._app_settings.update_channel)

        if self._update_service is None:
            return _tr(
                self._i18n,
                f"当前版本 v{APP_VERSION} · 频道 {channel_text} · 更新服务未注入",
                f"Current version v{APP_VERSION} · Channel {channel_text} · Update service not injected",
            )

        info = self._update_service.latest_info
        if self._update_service.is_checking:
            return _tr(
                self._i18n,
                f"当前版本 v{APP_VERSION} · 频道 {channel_text} · 正在检查更新…",
                f"Current version v{APP_VERSION} · Channel {channel_text} · Checking for updates...",
            )
        if info is not None and self._update_service.is_update_available(info):
            return _tr(
                self._i18n,
                f"当前版本 v{APP_VERSION} · 检测到 v{info.version}（{info.release_date or '--'}）",
                f"Current version v{APP_VERSION} · New version v{info.version} detected ({info.release_date or '--'})",
            )
        if info is not None and info.version:
            return _tr(
                self._i18n,
                f"当前版本 v{APP_VERSION} · 频道 {channel_text} 已是最新版本",
                f"Current version v{APP_VERSION} · Channel {channel_text} is up to date",
            )
        if self._update_service.last_error:
            return _tr(
                self._i18n,
                f"当前版本 v{APP_VERSION} · 上次检查失败：{self._update_service.last_error}",
                f"Current version v{APP_VERSION} · Last check failed: {self._update_service.last_error}",
            )
        return _tr(
            self._i18n,
            f"当前版本 v{APP_VERSION} · 频道 {channel_text} 尚未检查更新",
            f"Current version v{APP_VERSION} · Channel {channel_text} has not been checked yet",
        )

    @Slot()
    def _refresh_update_settings_status(self) -> None:
        if not hasattr(self, "_update_status_card"):
            return
        self._update_status_card.contentLabel.setText(self._update_status_text())
        if hasattr(self, "_check_update_btn"):
            checking = self._update_service is not None and self._update_service.is_checking
            self._check_update_btn.setEnabled(not checking)
            self._check_update_btn.setText(
                _tr(self._i18n, "检查中…", "Checking...") if checking else _tr(self._i18n, "检查更新", "Check Now")
            )

    @Slot(int)
    def _on_update_channel_changed(self, _index: int) -> None:
        if not self._ensure_settings_permission("切换更新频道"):
            return
        channel = self._update_channel_combo.currentData()
        if not channel:
            return
        self._app_settings.set_update_channel(str(channel))
        if self._update_service is not None:
            self._update_service.set_channel(str(channel))
        self._refresh_update_settings_status()

    @Slot(bool)
    def _on_update_auto_check_toggle(self, checked: bool) -> None:
        if not self._ensure_settings_permission("切换启动自动检查更新"):
            return
        self._app_settings.set_update_auto_check_enabled(checked)

    @Slot(bool)
    def _on_update_popup_toggle(self, checked: bool) -> None:
        if not self._ensure_settings_permission("切换启动更新弹窗"):
            return
        self._app_settings.set_update_startup_popup_enabled(checked)

    @Slot()
    def _on_check_updates_clicked(self) -> None:
        if self._update_service is None:
            InfoBar.warning(
                title=_tr(self._i18n, "检查更新", "Check for Updates"),
                content=_tr(self._i18n, "更新服务未注入，无法检查更新。", "Update service was not injected."),
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self,
            )
            return

        try:
            self._open_update_window()
        except Exception:
            pass

        started = self._update_service.check_for_updates()
        if not started and self._update_service.is_checking:
            InfoBar.info(
                title=_tr(self._i18n, "检查更新", "Check for Updates"),
                content=_tr(self._i18n, "更新检查已经在进行中。", "An update check is already running."),
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=2500,
                parent=self,
            )

    # ------------------------------------------------------------------ #
    # 插件设置（动态注入 / 移除）
    # ------------------------------------------------------------------ #

    def _insert_plugin_settings(self, plugin_id: str, display_name: str, widget: QWidget) -> None:
        """将插件设置 widget 注入到设置页（内部实现）。"""
        if plugin_id in self._plugin_setting_groups:
            return
        group = SettingCardGroup(f"{_tr(self._i18n, '插件', 'Plugin')} · {display_name}")
        widget.setParent(group)
        group.vBoxLayout.addWidget(widget)
        self._layout.insertWidget(self._plugin_settings_insert_idx, group)
        self._plugin_settings_insert_idx += 1
        self._plugin_setting_groups[plugin_id] = group

    def _insert_plugin_settings_factory(
        self,
        plugin_id: str,
        display_name: str,
        factory: Callable[[], Optional[QWidget]],
    ) -> None:
        """将插件设置工厂以延迟创建形式注入到设置页。"""
        if plugin_id in self._plugin_setting_groups:
            return
        group = SettingCardGroup(f"{_tr(self._i18n, '插件', 'Plugin')} · {display_name}")
        lazy_widget = LazyFactoryWidget(
            factory,
            loading_text=_tr(self._i18n, f"正在加载「{display_name}」设置…", f"Loading '{display_name}' settings..."),
            empty_text=_tr(self._i18n, "插件未提供设置面板", "Plugin does not provide settings panel"),
            error_text=_tr(self._i18n, "插件设置加载失败", "Failed to load plugin settings"),
            debug_name=f"plugin settings:{plugin_id}",
            parent=group,
        )
        group.vBoxLayout.addWidget(lazy_widget)
        self._layout.insertWidget(self._plugin_settings_insert_idx, group)
        self._plugin_settings_insert_idx += 1
        self._plugin_setting_groups[plugin_id] = group

    def add_plugin_settings(self, plugin_id: str, display_name: str, widget: QWidget) -> None:
        """外部调用：插件加载后将其设置面板插入设置页。"""
        self._insert_plugin_settings(plugin_id, display_name, widget)

    def add_plugin_settings_factory(
        self,
        plugin_id: str,
        display_name: str,
        factory: Callable[[], Optional[QWidget]],
    ) -> None:
        """外部调用：插件加载后按需插入其设置面板。"""
        self._insert_plugin_settings_factory(plugin_id, display_name, factory)

    def remove_plugin_settings(self, plugin_id: str) -> None:
        """外部调用：插件卸载后移除其设置面板。"""
        group = self._plugin_setting_groups.pop(plugin_id, None)
        if group is None:
            return
        # 将 parent 置为 None 会自动从所在布局中移除，
        # 不依赖 qfluentwidgets VBoxLayout 的内部 widgets 列表
        group.setParent(None)
        group.deleteLater()
        self._plugin_settings_insert_idx -= 1

    # ------------------------------------------------------------------ #
    # 插件
    # ------------------------------------------------------------------ #

    @Slot(int)
    def _on_pip_mirror_changed(self, index: int) -> None:
        if not self._ensure_settings_permission("修改插件依赖镜像源"):
            return
        url = self._pip_mirror_combo.itemData(index) or ""
        self._app_settings.set_pip_mirror(str(url))

    # ------------------------------------------------------------------ #
    # 关于
    # ------------------------------------------------------------------ #

    @Slot()
    def _on_about_clicked(self) -> None:
        from app.views.about_view import AboutWindow
        if self._about_window is None:
            self._about_window = AboutWindow(parent=None)
        self._about_window.show()
        self._about_window.raise_()
        self._about_window.activateWindow()

    @Slot()
    def _on_migration_clicked(self) -> None:
        self.open_migration_window()

    def open_migration_window(
        self,
        import_file_path: str | Path | None = None,
        *,
        jump_to_import: bool = False,
    ):
        from app.views.config_migration_view import ConfigMigrationWindow
        if not hasattr(self, '_migration_window') or self._migration_window is None:
            self._migration_window = ConfigMigrationWindow(
                parent=None,
                plugin_manager=self._plugin_manager,
            )

        self._migration_window.show()
        self._migration_window.raise_()
        self._migration_window.activateWindow()

        if import_file_path:
            ok = self._migration_window.open_import_file(
                Path(import_file_path),
                jump_to_selection=jump_to_import,
            )
            if not ok:
                return None

        return self._migration_window

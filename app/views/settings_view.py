"""应用设置视图"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtWidgets import QHBoxLayout, QWidget, QListWidget, QListWidgetItem
from qfluentwidgets import (
    SmoothScrollArea, FluentIcon as FIF, PushButton, ToolButton,
    SettingCardGroup, SettingCard, CardWidget,
    BodyLabel, TitleLabel, CaptionLabel, StrongBodyLabel,
    SwitchButton, ComboBox, SpinBox, Slider,
    VBoxLayout,
    InfoBar, InfoBarPosition, ListWidget,
    setTheme, Theme, isDarkTheme, qconfig,
    MessageBoxBase, CheckBox, SubtitleLabel,
)

from app.services import ringtone_service as rs
from app.views.toast_notification import (
    ToastManager, POSITION_LABELS, ALL_POSITIONS, POS_BOTTOM_RIGHT,
)

from app.constants import SETTINGS_CONFIG, URL_SCHEME, URL_VIEW_MAP, IS_BETA
from app.services.i18n_service import I18nService
from app.services.ntp_service import NtpService, NTP_SERVERS
from app.services.settings_service import SettingsService
from app.services import url_scheme_service as uss


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

    _DISCLAIMER = (
        "您正在尝试关闭测试版水印。请在继续前仔细阅读以下声明：\n\n"
        "1. 本软件当前为\u300c测试版\u300d，界面及功能并非最终状态，"
        "存在不稳定、不完整的可能。\n\n"
        "2. 关闭水印后，截图或录屏所得画面将不再带有测试标识。"
        "若您将此类内容对外传播或分享，请务必注明\u300c非最终效果\u300d，"
        "以免引起误解。\n\n"
        "3. 本软件的测试版内容对外传播可能对软件的正式发布造成影响，"
        "请谨慎对待截图和录屏的分享。\n\n"
        "4. 关闭水印不影响软件本身的测试版状态，"
        "也不代表您获得了任何超出测试协议范围的授权。"
    )

    def __init__(self, watermark_label: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"关闭水印 — {watermark_label}")

        title_lbl = SubtitleLabel(f"关闭水印 — {watermark_label}")
        self.viewLayout.addWidget(title_lbl)
        self.viewLayout.addSpacing(4)

        desc = BodyLabel(self._DISCLAIMER)
        desc.setWordWrap(True)
        desc.setFixedWidth(420)
        self.viewLayout.addWidget(desc)
        self.viewLayout.addSpacing(8)

        self._agree_cb = CheckBox("我已阅读并理解以上声明，同意关闭此水印")
        self.viewLayout.addWidget(self._agree_cb)

        self.yesButton.setText("确认关闭")
        self.cancelButton.setText("取消")
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

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("settingsView")

        self._ntp = NtpService.instance()
        self._app_settings = SettingsService.instance()
        self._i18n = I18nService.instance()

        container = QWidget()
        layout = VBoxLayout(container)
        layout.setContentsMargins(32, 20, 32, 32)
        layout.setSpacing(16)

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

        layout.addWidget(appear_group)

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

        # ── URL Scheme ────────────────────────────────────────────────── #
        url_group = SettingCardGroup(self._i18n.t("settings.group.url"))

        # 协议名称 + 可用地址
        url_hint_lines = [f"{URL_SCHEME}://open/{key}" for key in URL_VIEW_MAP]
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

        # 自定义通知开关
        notif_switch_card = _make_card(
            FIF.RINGER,
            self._i18n.t("settings.notif.custom.label"),
            self._i18n.t("settings.notif.custom.desc"),
            notif_group,
        )
        self._notif_custom_switch = SwitchButton()
        self._notif_custom_switch.setChecked(self._app_settings.notification_use_custom)
        self._notif_custom_switch.checkedChanged.connect(self._on_notif_custom_toggle)
        notif_switch_card.hBoxLayout.addWidget(self._notif_custom_switch)
        notif_switch_card.hBoxLayout.addSpacing(16)
        notif_group.addSettingCard(notif_switch_card)

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

        # ── 测试版水印（仅 IS_BETA 时显示）──────────────────────────── #
        if IS_BETA:
            beta_group = SettingCardGroup("测试版水印")

            # 主窗口水印开关
            wm_main_card = _make_card(
                FIF.VIEW,
                "主窗口水印",
                "对角平铺及右下角版本信息水印（主界面）",
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
                "世界时间视图水印",
                "全屏世界时钟画布上的测试版水印",
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

        self._update_controls_state()
        self._update_notif_controls()

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
        self._ntp.set_enabled(checked)
        self._update_controls_state()
        self._refresh_status()

    @Slot(str)
    def _on_server_changed(self, server: str) -> None:
        self._ntp.set_server(server)

    @Slot(int)
    def _on_interval_changed(self, value: int) -> None:
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
    # 秒表 / 计时器
    # ------------------------------------------------------------------ #

    @Slot(int)
    def _on_language_changed(self, index: int) -> None:
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
        self._app_settings.set_stopwatch_precision(index)

    @Slot(int)
    def _on_timer_precision_changed(self, index: int) -> None:
        self._app_settings.set_timer_precision(index)

    @Slot(int)
    def _on_opacity_changed(self, value: int) -> None:
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
    # 通知系统
    # ------------------------------------------------------------------ #

    def _update_notif_controls(self) -> None:
        enabled = self._app_settings.notification_use_custom
        self._notif_pos_combo.setEnabled(enabled)
        self._notif_dur_spin.setEnabled(enabled)
        self._notif_test_btn.setEnabled(enabled)

    @Slot(bool)
    def _on_notif_custom_toggle(self, checked: bool) -> None:
        self._app_settings.set_notification_use_custom(checked)
        self._update_notif_controls()

    @Slot(int)
    def _on_notif_pos_changed(self, _: int) -> None:
        key = self._notif_pos_combo.currentData()
        if key:
            self._app_settings.set_notification_position(key)
            self._sync_toast_manager()

    @Slot(int)
    def _on_notif_dur_changed(self, seconds: int) -> None:
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
        self._app_settings.set_alarm_alert_duration_sec(value)

    # ------------------------------------------------------------------ #
    # 测试版水印
    # ------------------------------------------------------------------ #

    @Slot(bool)
    def _on_wm_main_toggle(self, checked: bool) -> None:
        if not checked:
            dlg = _WatermarkDisclaimerDialog("主窗口水印", self.window())
            if not dlg.exec():
                # 用户取消 / 未同意 → 恢复开关，阻断信号避免循环
                self._wm_main_switch.blockSignals(True)
                self._wm_main_switch.setChecked(True)
                self._wm_main_switch.blockSignals(False)
                return
        self._app_settings.set_watermark_main_visible(checked)

    @Slot(bool)
    def _on_wm_wt_toggle(self, checked: bool) -> None:
        if not checked:
            dlg = _WatermarkDisclaimerDialog("世界时间视图水印", self.window())
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
        key = self._theme_combo.currentData()
        if key:
            self._app_settings.set_theme(key)
            if key == "dark":
                setTheme(Theme.DARK)
            elif key == "light":
                setTheme(Theme.LIGHT)
            else:
                setTheme(Theme.AUTO)

    # ------------------------------------------------------------------ #
    # 启动选项
    # ------------------------------------------------------------------ #

    @Slot(bool)
    def _on_boot_menu_toggle(self, checked: bool) -> None:
        self._app_settings.set_show_boot_menu_next_start(checked)

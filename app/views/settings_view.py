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
)

from app.services import ringtone_service as rs
from app.views.toast_notification import (
    ToastManager, POSITION_LABELS, ALL_POSITIONS, POS_BOTTOM_RIGHT,
)

from app.constants import SETTINGS_CONFIG, URL_SCHEME, URL_VIEW_MAP
from app.services.ntp_service import NtpService, NTP_SERVERS
from app.services.settings_service import SettingsService
from app.services import url_scheme_service as uss


# 外观主题选项
_THEME_OPTIONS = [
    ("跟随系统", "auto"),
    ("浅色模式", "light"),
    ("深色模式", "dark"),
]

# 精度选项
_PRECISION_LABELS = ["0 位（MM:SS）", "1 位（MM:SS.d）", "2 位（MM:SS.cs）"]


def _make_card(icon, title: str, content: str, parent=None) -> SettingCard:
    """创建基础设置卡"""
    return SettingCard(icon, title, content, parent)


class _RingtoneCard(CardWidget):
    """铃声列表卡片（嵌入 SettingCardGroup 内）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = VBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)

        hint = CaptionLabel("在此管理铃声文件（仅支持 .wav）。闹钟、计时器、专注模式均从此列表中选取铃声。")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.listWidget = ListWidget()
        self.listWidget.setFixedHeight(150)
        layout.addWidget(self.listWidget)

        btn_row = QHBoxLayout()
        self.addBtn = PushButton(FIF.ADD, "添加铃声")
        self.previewBtn = PushButton(FIF.PLAY, "试听")
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

        container = QWidget()
        layout = VBoxLayout(container)
        layout.setContentsMargins(32, 20, 32, 32)
        layout.setSpacing(16)

        layout.addWidget(TitleLabel("设置"))

        # ── 外观 ─────────────────────────────────────────────────────────────── #
        appear_group = SettingCardGroup("外观")

        theme_card = _make_card(FIF.BRUSH, "界面主题", "调整应用的整体外观配色", appear_group)
        self._theme_combo = ComboBox()
        for label, key in _THEME_OPTIONS:
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
        ntp_group = SettingCardGroup("NTP 网络时间同步")

        # 启用开关
        ntp_switch_card = _make_card(FIF.SYNC, "启用 NTP 同步", "从网络服务器校准系统时间偏移", ntp_group)
        self._ntp_switch = SwitchButton()
        self._ntp_switch.setChecked(self._ntp.enabled)
        self._ntp_switch.checkedChanged.connect(self._on_ntp_toggle)
        ntp_switch_card.hBoxLayout.addWidget(self._ntp_switch)
        ntp_switch_card.hBoxLayout.addSpacing(16)
        ntp_group.addSettingCard(ntp_switch_card)

        # 服务器选择
        server_card = _make_card(FIF.GLOBE, "NTP 服务器", "选择用于时间同步的服务器地址", ntp_group)
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
        interval_card = _make_card(FIF.HISTORY, "同步间隔", "设置自动同步的时间间隔（1 ~ 1440 分钟）", ntp_group)
        self._interval_spin = SpinBox()
        self._interval_spin.setRange(1, 1440)
        self._interval_spin.setValue(self._ntp.sync_interval_min)
        self._interval_spin.setSuffix(" 分钟")
        self._interval_spin.valueChanged.connect(self._on_interval_changed)
        interval_card.hBoxLayout.addWidget(self._interval_spin)
        interval_card.hBoxLayout.addSpacing(16)
        ntp_group.addSettingCard(interval_card)

        # 同步状态 + 立即同步
        self._sync_status_card = _make_card(FIF.INFO, "同步状态", self._status_text(), ntp_group)
        self._sync_btn = PushButton(FIF.SYNC, "立即同步")
        self._sync_btn.clicked.connect(self._on_sync_now)
        self._sync_status_card.hBoxLayout.addWidget(self._sync_btn)
        self._sync_status_card.hBoxLayout.addSpacing(16)
        ntp_group.addSettingCard(self._sync_status_card)

        layout.addWidget(ntp_group)

        # ── URL Scheme ────────────────────────────────────────────────── #
        url_group = SettingCardGroup("URL Scheme 协议")

        # 协议名称 + 可用地址
        url_hint_lines = [f"{URL_SCHEME}://open/{key}" for key in URL_VIEW_MAP]
        url_name_card = _make_card(
            FIF.LINK, "协议名称",
            f"协议：{URL_SCHEME}://   可用地址：{'  |  '.join(url_hint_lines)}",
            url_group,
        )
        url_group.addSettingCard(url_name_card)

        # 注册状态 + 操作按钮
        self._url_status_card = _make_card(FIF.CERTIFICATE, "注册状态", self._url_status_text(), url_group)
        self._url_reg_btn = PushButton(FIF.LINK, "")
        self._url_reg_btn.setFixedWidth(110)
        self._url_reg_btn.clicked.connect(self._on_url_toggle)
        self._refresh_url_btn_text()
        self._url_status_card.hBoxLayout.addWidget(self._url_reg_btn)
        self._url_status_card.hBoxLayout.addSpacing(16)
        url_group.addSettingCard(self._url_status_card)

        layout.addWidget(url_group)

        # ── 秒表 / 计时器 ────────────────────────────────── #
        sw_group = SettingCardGroup("秒表 / 计时器")

        # 秒表精度
        sw_card = _make_card(FIF.STOP_WATCH, "秒表小数位", "控制秒表的时间显示精度", sw_group)
        self._sw_precision_combo = ComboBox()
        for label in _PRECISION_LABELS:
            self._sw_precision_combo.addItem(label)
        self._sw_precision_combo.setCurrentIndex(self._app_settings.stopwatch_precision)
        self._sw_precision_combo.currentIndexChanged.connect(self._on_sw_precision_changed)
        sw_card.hBoxLayout.addWidget(self._sw_precision_combo)
        sw_card.hBoxLayout.addSpacing(16)
        sw_group.addSettingCard(sw_card)

        # 计时器精度
        timer_card = _make_card(FIF.STOP_WATCH, "计时器小数位", "控制计时器的时间显示精度", sw_group)
        self._timer_precision_combo = ComboBox()
        for label in _PRECISION_LABELS:
            self._timer_precision_combo.addItem(label)
        self._timer_precision_combo.setCurrentIndex(self._app_settings.timer_precision)
        self._timer_precision_combo.currentIndexChanged.connect(self._on_timer_precision_changed)
        timer_card.hBoxLayout.addWidget(self._timer_precision_combo)
        timer_card.hBoxLayout.addSpacing(16)
        sw_group.addSettingCard(timer_card)

        # 小窗不透明度
        opacity_card = _make_card(FIF.TRANSPARENT, "小窗不透明度", "悬浮小窗的透明程度（10% ~ 100%）", sw_group)
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
        ring_group = SettingCardGroup("铃声列表")
        self._ring_card = _RingtoneCard(ring_group)
        self._ring_card.addBtn.clicked.connect(self._on_ring_add)
        self._ring_card.previewBtn.clicked.connect(self._on_ring_preview)
        self._ring_card.deleteBtn.clicked.connect(self._on_ring_delete)
        ring_group.vBoxLayout.addWidget(self._ring_card)
        layout.addWidget(ring_group)
        self._refresh_ring_list()

        # ── 通知系统 ──────────────────────────────────────────── #
        notif_group = SettingCardGroup("通知系统")

        # 自定义通知开关
        notif_switch_card = _make_card(
            FIF.RINGER, "使用自定义通知",
            "开启后将使用悬浮 Toast 窗口代替系统托盘气泡",
            notif_group,
        )
        self._notif_custom_switch = SwitchButton()
        self._notif_custom_switch.setChecked(self._app_settings.notification_use_custom)
        self._notif_custom_switch.checkedChanged.connect(self._on_notif_custom_toggle)
        notif_switch_card.hBoxLayout.addWidget(self._notif_custom_switch)
        notif_switch_card.hBoxLayout.addSpacing(16)
        notif_group.addSettingCard(notif_switch_card)

        # 出现位置
        notif_pos_card = _make_card(FIF.PIN, "出现位置", "Toast 通知弹出的屏幕位置", notif_group)
        self._notif_pos_combo = ComboBox()
        for key in ALL_POSITIONS:
            self._notif_pos_combo.addItem(POSITION_LABELS[key], userData=key)
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
        notif_dur_card = _make_card(FIF.STOP_WATCH, "停留时间", "通知显示时长（0 秒 = 常驻，需手动关闭）", notif_group)
        self._notif_dur_spin = SpinBox()
        self._notif_dur_spin.setRange(0, 60)
        self._notif_dur_spin.setValue(self._app_settings.notification_duration_ms // 1000)
        self._notif_dur_spin.setSuffix(" 秒")
        self._notif_dur_spin.setSpecialValueText("常驻")
        self._notif_dur_spin.valueChanged.connect(self._on_notif_dur_changed)
        notif_dur_card.hBoxLayout.addWidget(self._notif_dur_spin)
        notif_dur_card.hBoxLayout.addSpacing(16)
        notif_group.addSettingCard(notif_dur_card)

        # 测试通知
        notif_test_card = _make_card(FIF.SEND, "发送测试通知", "点击右侧按钮发送一条测试 Toast 通知", notif_group)
        self._notif_test_btn = PushButton(FIF.RINGER, "发送测试通知")
        self._notif_test_btn.clicked.connect(self._on_notif_test)
        notif_test_card.hBoxLayout.addWidget(self._notif_test_btn)
        notif_test_card.hBoxLayout.addSpacing(16)
        notif_group.addSettingCard(notif_test_card)

        layout.addWidget(notif_group)

        # ── 闹钟 ─────────────────────────────────────────────────── #
        alarm_group = SettingCardGroup("闹钟")

        alert_dur_card = _make_card(
            FIF.STOP_WATCH, "提醒等待时长",
            "提醒窗口 / 全屏显示时间，超时后自动启用稍后提醒（10 ~ 600 秒）",
            alarm_group,
        )
        self._alarm_alert_dur_spin = SpinBox()
        self._alarm_alert_dur_spin.setRange(10, 600)
        self._alarm_alert_dur_spin.setValue(self._app_settings.alarm_alert_duration_sec)
        self._alarm_alert_dur_spin.setSuffix(" 秒")
        self._alarm_alert_dur_spin.valueChanged.connect(self._on_alarm_alert_dur_changed)
        alert_dur_card.hBoxLayout.addWidget(self._alarm_alert_dur_spin)
        alert_dur_card.hBoxLayout.addSpacing(16)
        alarm_group.addSettingCard(alert_dur_card)

        layout.addWidget(alarm_group)

        layout.addWidget(BodyLabel("更多设置选项持续开发中……"))
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
            return "未启用"
        if self._ntp.is_syncing:
            return "同步中…"
        err = self._ntp.last_error
        if err:
            return f"上次同步失败：{err}"
        offset = self._ntp.offset_str()
        t = self._ntp.last_sync_time_str()
        return f"最后同步：{t}  偏移：{offset}"

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
                title="NTP 未启用",
                content="请先开启 NTP 同步，再执行立即同步。",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=3000,
            )
            return
        self._ntp.sync_once()
        self._sync_status_card.contentLabel.setText("同步中…")
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
            return "未注册（无法通过 URL 唤起）"
        return f"已注册：{URL_SCHEME}://open/<视图>"

    def _refresh_url_btn_text(self) -> None:
        if uss.is_registered():
            self._url_reg_btn.setText("取消注册")
        else:
            self._url_reg_btn.setText("立即注册")

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
                title="URL Scheme",
                content=msg,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self,
            )
        else:
            InfoBar.error(
                title="URL Scheme",
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
            title="铃声已添加",
            content=f"已将「{name}」添加到铃声列表。",
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
            title="铃声已删除",
            content=f"已从列表中移除「{name}」。",
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
                w._toast_mgr.show_toast("测试通知", "这是一条自定义 Toast 通知示例。")
        except Exception as e:
            InfoBar.error(
                title="测试失败",
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

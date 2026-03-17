"""首次使用设置窗口。"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget

from qfluentwidgets import (
    BodyLabel,
    BreadcrumbBar,
    CaptionLabel,
    ComboBox,
    FluentIcon as FIF,
    FluentWidget,
    PrimaryPushButton,
    PushButton,
    SettingCard,
    SpinBox,
    StrongBodyLabel,
    SubtitleLabel,
    SwitchButton,
    Theme,
    TitleLabel,
    setTheme,
)

from app.constants import APP_NAME, ICON_PATH, URL_SCHEME
from app.services import url_scheme_service
from app.services import startup_service
from app.services.i18n_service import I18nService
from app.services.ntp_service import NTP_SERVERS, NtpService
from app.services.settings_service import SettingsService
from app.views.toast_notification import ALL_POSITIONS

# PyPI 镜像源选项
_PIP_MIRROR_OPTIONS: list[tuple[str, str, str]] = [
    ("", "first_use.network.pypi.default", "PyPI 官方"),
    ("https://mirrors.aliyun.com/pypi/simple/", "first_use.network.pypi.aliyun", "阿里云"),
    ("https://pypi.tuna.tsinghua.edu.cn/simple/", "first_use.network.pypi.tsinghua", "清华大学"),
    ("https://mirrors.cloud.tencent.com/pypi/simple/", "first_use.network.pypi.tencent", "腾讯云"),
    ("https://repo.huaweicloud.com/repository/pypi/simple/", "first_use.network.pypi.huawei", "华为云"),
    ("https://mirror.nju.edu.cn/pypi/web/simple/", "first_use.network.pypi.nju", "南京大学"),
]

_LANGUAGE_OPTIONS: list[tuple[str, str]] = [
    ("lang.zh-CN", "zh-CN"),
    ("lang.en-US", "en-US"),
]

_THEME_OPTIONS: list[tuple[str, str]] = [
    ("settings.theme.auto", "auto"),
    ("settings.theme.light", "light"),
    ("settings.theme.dark", "dark"),
]

_THEME_LABEL_KEYS: dict[str, str] = {
    "auto": "settings.theme.auto",
    "light": "settings.theme.light",
    "dark": "settings.theme.dark",
}

_HELLO_PHRASES: tuple[str, ...] = (
    "你好",
    "Hello",
    "こんにちは",
    "안녕하세요",
    "Bonjour",
    "Hola",
    "Hallo",
    "Ciao",
    "Привет",
    "مرحبا",
)


def _precision_labels(i18n: I18nService) -> list[str]:
    return [
        i18n.t("settings.precision.0", default="1秒"),
        i18n.t("settings.precision.1", default="0.1秒"),
        i18n.t("settings.precision.2", default="0.01秒"),
    ]


def _position_label(i18n: I18nService, pos_key: str) -> str:
    return i18n.t(f"settings.pos.{pos_key}", default=pos_key)


def _make_setting_card(icon, title: str, content: str, parent=None) -> SettingCard:
    return SettingCard(icon, title, content, parent)


class FirstUseSetupWindow(FluentWidget):
    """首次启动向导窗口。"""

    setupCompleted = Signal()
    setupCanceled = Signal()

    _ROUTE_WELCOME = "first_use_welcome"
    _ROUTE_APPEARANCE = "first_use_appearance"
    _ROUTE_NETWORK = "first_use_network"
    _ROUTE_SYSTEM = "first_use_system"
    _ROUTE_NOTIFICATION = "first_use_notification"
    _ROUTE_LEARNING = "first_use_learning"
    _ROUTE_FINISH = "first_use_finish"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings = SettingsService.instance()
        self._i18n = I18nService.instance()
        self._ntp = NtpService.instance()

        self._hello_index = -1
        self._is_completed = False
        self._syncing_breadcrumb = False
        self._max_unlocked_step = 0

        self._steps: list[tuple[str, str, str]] = [
            (self._ROUTE_WELCOME, "first_use.breadcrumb.welcome", "欢迎"),
            (self._ROUTE_APPEARANCE, "first_use.breadcrumb.preferences", "外观"),
            (self._ROUTE_NETWORK, "first_use.breadcrumb.network", "网络"),
            (self._ROUTE_SYSTEM, "first_use.breadcrumb.system", "系统"),
            (self._ROUTE_NOTIFICATION, "first_use.breadcrumb.notification", "通知"),
            (self._ROUTE_LEARNING, "first_use.breadcrumb.learning", "计时"),
            (self._ROUTE_FINISH, "first_use.breadcrumb.finish", "完成"),
        ]
        self._route_to_step = {route: idx for idx, (route, _, _) in enumerate(self._steps)}

        self._hello_timer = QTimer(self)
        self._hello_timer.setInterval(1200)
        self._hello_timer.timeout.connect(self._rotate_hello)

        self._stack = QStackedWidget(self)
        self._breadcrumb = BreadcrumbBar(self)
        self._breadcrumb.setSpacing(10)

        self._back_button = PushButton(FIF.LEFT_ARROW, "", self)
        self._next_button = PrimaryPushButton(FIF.RIGHT_ARROW, "", self)
        self._finish_button = PrimaryPushButton(FIF.ACCEPT, "", self)

        self._build_ui()
        self._bind_signals()
        self._set_step(0)
        self._retranslate()

        self._hello_timer.start()
        self._rotate_hello()

    def _build_ui(self) -> None:
        self.resize(820, 620)
        self.setMinimumSize(760, 560)
        if ICON_PATH:
            self.setWindowIcon(QIcon(ICON_PATH))

        root = QVBoxLayout(self)
        root.setContentsMargins(26, self.titleBar.height() + 16, 26, 24)
        root.setSpacing(12)

        self._header_title = TitleLabel("", self)
        self._header_subtitle = BodyLabel("", self)
        self._header_subtitle.setWordWrap(True)

        root.addWidget(self._header_title)
        root.addWidget(self._header_subtitle)
        root.addSpacing(4)

        root.addWidget(self._breadcrumb)

        self._build_welcome_page()
        self._build_appearance_page()
        self._build_network_page()
        self._build_system_page()
        self._build_notification_page()
        self._build_learning_page()
        self._build_finish_page()

        root.addWidget(self._stack, 1)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        footer.addStretch()

        self._back_button.setMinimumWidth(112)
        self._next_button.setMinimumWidth(112)
        self._finish_button.setMinimumWidth(112)

        footer.addWidget(self._back_button)
        footer.addWidget(self._next_button)
        footer.addWidget(self._finish_button)
        root.addLayout(footer)

    def _build_welcome_page(self) -> None:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(14)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._welcome_title = SubtitleLabel("", page)
        self._welcome_title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._hello_label = StrongBodyLabel("", page)
        self._hello_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hello_label.setStyleSheet("font-size: 36px; font-weight: 600;")

        self._welcome_hint = BodyLabel("", page)
        self._welcome_hint.setWordWrap(True)
        self._welcome_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._welcome_quick_hint = CaptionLabel("", page)
        self._welcome_quick_hint.setWordWrap(True)
        self._welcome_quick_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)

        quick_row = QHBoxLayout()
        quick_row.setSpacing(10)
        quick_row.addStretch()
        self._quick_lang_zh = PushButton("", page)
        self._quick_lang_en = PushButton("", page)
        self._quick_lang_zh.setMinimumWidth(130)
        self._quick_lang_en.setMinimumWidth(130)
        quick_row.addWidget(self._quick_lang_zh)
        quick_row.addWidget(self._quick_lang_en)
        quick_row.addStretch()

        self._language_card = _make_setting_card(FIF.GLOBE, "", "", page)
        self._language_combo = ComboBox(self._language_card)
        self._language_card.hBoxLayout.addWidget(self._language_combo)
        self._language_card.hBoxLayout.addSpacing(16)

        layout.addStretch()
        layout.addWidget(self._welcome_title)
        layout.addWidget(self._hello_label)
        layout.addWidget(self._welcome_hint)
        layout.addWidget(self._welcome_quick_hint)
        layout.addLayout(quick_row)
        layout.addWidget(self._language_card)
        layout.addStretch()

        self._stack.addWidget(page)

    def _build_appearance_page(self) -> None:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(12)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._appearance_title = SubtitleLabel("", page)
        self._appearance_desc = BodyLabel("", page)
        self._appearance_desc.setWordWrap(True)

        self._theme_card = _make_setting_card(FIF.BRUSH, "", "", page)
        self._theme_combo = ComboBox(self._theme_card)
        self._theme_card.hBoxLayout.addWidget(self._theme_combo)
        self._theme_card.hBoxLayout.addSpacing(16)

        self._appearance_tip = CaptionLabel("", page)
        self._appearance_tip.setWordWrap(True)

        layout.addWidget(self._appearance_title)
        layout.addWidget(self._appearance_desc)
        layout.addWidget(self._theme_card)
        layout.addWidget(self._appearance_tip)
        layout.addStretch()

        self._stack.addWidget(page)

    def _build_network_page(self) -> None:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(12)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._network_title = SubtitleLabel("", page)
        self._network_desc = BodyLabel("", page)
        self._network_desc.setWordWrap(True)

        # NTP 开关
        self._network_ntp_card = _make_setting_card(FIF.SYNC, "", "", page)
        self._network_ntp_switch = SwitchButton("", self._network_ntp_card)
        self._network_ntp_switch.setChecked(True)  # 默认开启
        self._network_ntp_card.hBoxLayout.addWidget(self._network_ntp_switch)
        self._network_ntp_card.hBoxLayout.addSpacing(16)

        # NTP 服务器选择
        self._network_ntp_server_card = _make_setting_card(FIF.GLOBE, "", "", page)
        self._network_ntp_server_combo = ComboBox(self._network_ntp_server_card)
        for server in NTP_SERVERS:
            self._network_ntp_server_combo.addItem(server)
        self._network_ntp_server_card.hBoxLayout.addWidget(self._network_ntp_server_combo)
        self._network_ntp_server_card.hBoxLayout.addSpacing(16)

        # NTP 同步间隔
        self._network_ntp_interval_card = _make_setting_card(FIF.HISTORY, "", "", page)
        self._network_ntp_interval_spin = SpinBox(self._network_ntp_interval_card)
        self._network_ntp_interval_spin.setRange(1, 1440)
        self._network_ntp_interval_spin.setValue(self._ntp.sync_interval_min)
        self._network_ntp_interval_card.hBoxLayout.addWidget(self._network_ntp_interval_spin)
        self._network_ntp_interval_card.hBoxLayout.addSpacing(16)

        # PyPI 镜像源选择
        self._network_pypi_card = _make_setting_card(FIF.DOWNLOAD, "", "", page)
        self._network_pypi_combo = ComboBox(self._network_pypi_card)
        self._network_pypi_card.hBoxLayout.addWidget(self._network_pypi_combo)
        self._network_pypi_card.hBoxLayout.addSpacing(16)

        self._network_tip = CaptionLabel("", page)
        self._network_tip.setWordWrap(True)

        layout.addWidget(self._network_title)
        layout.addWidget(self._network_desc)
        layout.addWidget(self._network_ntp_card)
        layout.addWidget(self._network_ntp_server_card)
        layout.addWidget(self._network_ntp_interval_card)
        layout.addWidget(self._network_pypi_card)
        layout.addWidget(self._network_tip)
        layout.addStretch()

        self._stack.addWidget(page)

    def _build_system_page(self) -> None:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(12)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._system_title = SubtitleLabel("", page)
        self._system_desc = BodyLabel("", page)
        self._system_desc.setWordWrap(True)

        self._url_card = _make_setting_card(FIF.LINK, "", "", page)
        self._url_switch = SwitchButton("", self._url_card)
        self._url_switch.setChecked(url_scheme_service.is_registered())
        self._url_card.hBoxLayout.addWidget(self._url_switch)
        self._url_card.hBoxLayout.addSpacing(16)

        self._autostart_card = _make_setting_card(FIF.PLAY, "", "", page)
        self._autostart_switch = SwitchButton("", self._autostart_card)
        self._autostart_switch.setChecked(startup_service.is_enabled())
        self._autostart_card.hBoxLayout.addWidget(self._autostart_switch)
        self._autostart_card.hBoxLayout.addSpacing(16)

        layout.addWidget(self._system_title)
        layout.addWidget(self._system_desc)
        layout.addWidget(self._url_card)
        layout.addWidget(self._autostart_card)
        layout.addStretch()

        self._stack.addWidget(page)

    def _build_notification_page(self) -> None:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(12)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._notification_title = SubtitleLabel("", page)
        self._notification_desc = BodyLabel("", page)
        self._notification_desc.setWordWrap(True)

        self._notification_position_card = _make_setting_card(FIF.PIN, "", "", page)
        self._notification_position_combo = ComboBox(self._notification_position_card)
        self._notification_position_card.hBoxLayout.addWidget(self._notification_position_combo)
        self._notification_position_card.hBoxLayout.addSpacing(16)

        self._notification_duration_card = _make_setting_card(FIF.STOP_WATCH, "", "", page)
        self._notification_duration_spin = SpinBox(self._notification_duration_card)
        self._notification_duration_spin.setRange(0, 60)
        self._notification_duration_card.hBoxLayout.addWidget(self._notification_duration_spin)
        self._notification_duration_card.hBoxLayout.addSpacing(16)

        layout.addWidget(self._notification_title)
        layout.addWidget(self._notification_desc)
        layout.addWidget(self._notification_position_card)
        layout.addWidget(self._notification_duration_card)
        layout.addStretch()

        self._stack.addWidget(page)

    def _build_learning_page(self) -> None:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(12)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._learning_title = SubtitleLabel("", page)
        self._learning_desc = BodyLabel("", page)
        self._learning_desc.setWordWrap(True)

        self._stopwatch_precision_card = _make_setting_card(FIF.STOP_WATCH, "", "", page)
        self._stopwatch_precision_combo = ComboBox(self._stopwatch_precision_card)
        self._stopwatch_precision_card.hBoxLayout.addWidget(self._stopwatch_precision_combo)
        self._stopwatch_precision_card.hBoxLayout.addSpacing(16)

        self._timer_precision_card = _make_setting_card(FIF.CALENDAR, "", "", page)
        self._timer_precision_combo = ComboBox(self._timer_precision_card)
        self._timer_precision_card.hBoxLayout.addWidget(self._timer_precision_combo)
        self._timer_precision_card.hBoxLayout.addSpacing(16)

        layout.addWidget(self._learning_title)
        layout.addWidget(self._learning_desc)
        layout.addWidget(self._stopwatch_precision_card)
        layout.addWidget(self._timer_precision_card)
        layout.addStretch()

        self._stack.addWidget(page)

    def _build_finish_page(self) -> None:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._finish_title = SubtitleLabel("", page)
        self._finish_desc = BodyLabel("", page)
        self._finish_desc.setWordWrap(True)

        self._summary_language = BodyLabel("", page)
        self._summary_theme = BodyLabel("", page)
        self._summary_ntp = BodyLabel("", page)
        self._summary_pypi = BodyLabel("", page)
        self._summary_url = BodyLabel("", page)
        self._summary_autostart = BodyLabel("", page)
        self._summary_notification_position = BodyLabel("", page)
        self._summary_notification_duration = BodyLabel("", page)
        self._summary_stopwatch_precision = BodyLabel("", page)
        self._summary_timer_precision = BodyLabel("", page)

        self._finish_tip = CaptionLabel("", page)
        self._finish_tip.setWordWrap(True)

        layout.addWidget(self._finish_title)
        layout.addWidget(self._finish_desc)
        layout.addWidget(self._summary_language)
        layout.addWidget(self._summary_theme)
        layout.addWidget(self._summary_ntp)
        layout.addWidget(self._summary_pypi)
        layout.addWidget(self._summary_url)
        layout.addWidget(self._summary_autostart)
        layout.addWidget(self._summary_notification_position)
        layout.addWidget(self._summary_notification_duration)
        layout.addWidget(self._summary_stopwatch_precision)
        layout.addWidget(self._summary_timer_precision)
        layout.addWidget(self._finish_tip)
        layout.addStretch()

        self._stack.addWidget(page)

    def _bind_signals(self) -> None:
        self._back_button.clicked.connect(self._go_previous)
        self._next_button.clicked.connect(self._go_next)
        self._finish_button.clicked.connect(self._finish_setup)

        self._quick_lang_zh.clicked.connect(lambda: self._apply_language("zh-CN"))
        self._quick_lang_en.clicked.connect(lambda: self._apply_language("en-US"))
        self._language_combo.currentIndexChanged.connect(self._on_language_changed)
        self._theme_combo.currentIndexChanged.connect(self._on_theme_changed)

        self._network_ntp_switch.checkedChanged.connect(self._on_network_ntp_enable_changed)
        self._network_ntp_server_combo.currentTextChanged.connect(self._on_network_ntp_server_changed)
        self._network_ntp_interval_spin.valueChanged.connect(self._on_network_ntp_interval_changed)
        self._network_pypi_combo.currentIndexChanged.connect(self._on_network_pypi_changed)

        self._url_switch.checkedChanged.connect(self._on_url_switch_changed)
        self._autostart_switch.checkedChanged.connect(self._on_autostart_switch_changed)

        self._notification_position_combo.currentIndexChanged.connect(self._on_notification_position_changed)
        self._notification_duration_spin.valueChanged.connect(self._on_notification_duration_changed)

        self._stopwatch_precision_combo.currentIndexChanged.connect(self._on_stopwatch_precision_changed)
        self._timer_precision_combo.currentIndexChanged.connect(self._on_timer_precision_changed)

        self._breadcrumb.currentItemChanged.connect(self._on_breadcrumb_changed)
        self._i18n.languageChanged.connect(lambda _: self._retranslate())

    def _reload_language_combo(self) -> None:
        current = self._settings.language
        self._language_combo.blockSignals(True)
        self._language_combo.clear()
        current_index = 0
        for idx, (label_key, key) in enumerate(_LANGUAGE_OPTIONS):
            self._language_combo.addItem(self._i18n.t(label_key), userData=key)
            if key == current:
                current_index = idx
        self._language_combo.setCurrentIndex(current_index)
        self._language_combo.blockSignals(False)

    def _reload_theme_combo(self) -> None:
        current = self._settings.theme
        self._theme_combo.blockSignals(True)
        self._theme_combo.clear()
        current_index = 0
        for idx, (label_key, key) in enumerate(_THEME_OPTIONS):
            self._theme_combo.addItem(self._i18n.t(label_key), userData=key)
            if key == current:
                current_index = idx
        self._theme_combo.setCurrentIndex(current_index)
        self._theme_combo.blockSignals(False)

    def _reload_notification_position_combo(self) -> None:
        current = self._settings.notification_position
        self._notification_position_combo.blockSignals(True)
        self._notification_position_combo.clear()
        current_index = 0
        for idx, key in enumerate(ALL_POSITIONS):
            self._notification_position_combo.addItem(_position_label(self._i18n, key), userData=key)
            if key == current:
                current_index = idx
        self._notification_position_combo.setCurrentIndex(current_index)
        self._notification_position_combo.blockSignals(False)

    def _reload_precision_combos(self) -> None:
        labels = _precision_labels(self._i18n)

        self._stopwatch_precision_combo.blockSignals(True)
        self._stopwatch_precision_combo.clear()
        self._stopwatch_precision_combo.addItems(labels)
        self._stopwatch_precision_combo.setCurrentIndex(self._settings.stopwatch_precision)
        self._stopwatch_precision_combo.blockSignals(False)

        self._timer_precision_combo.blockSignals(True)
        self._timer_precision_combo.clear()
        self._timer_precision_combo.addItems(labels)
        self._timer_precision_combo.setCurrentIndex(self._settings.timer_precision)
        self._timer_precision_combo.blockSignals(False)

    def _reload_network_widgets(self) -> None:
        # NTP 开关
        self._network_ntp_switch.blockSignals(True)
        self._network_ntp_switch.setChecked(self._ntp.enabled)
        self._network_ntp_switch.blockSignals(False)

        # NTP 服务器
        self._network_ntp_server_combo.blockSignals(True)
        idx = self._network_ntp_server_combo.findText(self._ntp.server)
        if idx >= 0:
            self._network_ntp_server_combo.setCurrentIndex(idx)
        self._network_ntp_server_combo.blockSignals(False)

        # NTP 同步间隔
        self._network_ntp_interval_spin.blockSignals(True)
        self._network_ntp_interval_spin.setValue(self._ntp.sync_interval_min)
        self._network_ntp_interval_spin.blockSignals(False)

        # PyPI 镜像源
        self._network_pypi_combo.blockSignals(True)
        self._network_pypi_combo.clear()
        current_mirror = self._settings.pip_mirror
        current_index = 0
        for idx, (url, label_key, default_text) in enumerate(_PIP_MIRROR_OPTIONS):
            self._network_pypi_combo.addItem(self._i18n.t(label_key, default=default_text), userData=url)
            if url == current_mirror:
                current_index = idx
        self._network_pypi_combo.setCurrentIndex(current_index)
        self._network_pypi_combo.blockSignals(False)

        self._update_network_ntp_controls_state()

    def _update_network_ntp_controls_state(self) -> None:
        enabled = self._network_ntp_switch.isChecked()
        self._network_ntp_server_combo.setEnabled(enabled)
        self._network_ntp_interval_spin.setEnabled(enabled)
        if enabled:
            self._network_ntp_switch.setText(self._i18n.t("first_use.switch.enabled", default="已开启"))
        else:
            self._network_ntp_switch.setText(self._i18n.t("first_use.switch.disabled", default="已关闭"))

    def _refresh_breadcrumb(self) -> None:
        current_step = self._stack.currentIndex()
        if current_step < 0:
            return

        self._syncing_breadcrumb = True
        self._breadcrumb.blockSignals(True)
        try:
            self._breadcrumb.clear()
            for step in range(0, self._max_unlocked_step + 1):
                route_key, text_key, default_text = self._steps[step]
                self._breadcrumb.addItem(route_key, self._i18n.t(text_key, default=default_text))
            self._breadcrumb.setCurrentItem(self._steps[current_step][0])
        finally:
            self._breadcrumb.blockSignals(False)
            self._syncing_breadcrumb = False

    def _update_language_quick_buttons(self) -> None:
        is_zh = self._settings.language == "zh-CN"
        self._quick_lang_zh.setText(("✓ " if is_zh else "") + self._i18n.t("first_use.welcome.quick.zh", default="中文"))
        self._quick_lang_en.setText(("✓ " if not is_zh else "") + self._i18n.t("first_use.welcome.quick.en", default="English"))

    def _update_url_switch_text(self) -> None:
        if self._url_switch.isChecked():
            self._url_switch.setText(self._i18n.t("first_use.switch.enabled", default="已开启"))
        else:
            self._url_switch.setText(self._i18n.t("first_use.switch.disabled", default="已关闭"))

    def _update_autostart_switch_text(self) -> None:
        if self._autostart_switch.isChecked():
            self._autostart_switch.setText(self._i18n.t("first_use.switch.enabled", default="已开启"))
        else:
            self._autostart_switch.setText(self._i18n.t("first_use.switch.disabled", default="已关闭"))

    def _update_ntp_controls_state(self) -> None:
        enabled = self._ntp_enable_switch.isChecked()
        self._ntp_server_combo.setEnabled(enabled)
        self._ntp_interval_spin.setEnabled(enabled)
        if enabled:
            self._ntp_enable_switch.setText(self._i18n.t("first_use.switch.enabled", default="已开启"))
        else:
            self._ntp_enable_switch.setText(self._i18n.t("first_use.switch.disabled", default="已关闭"))

    def _retranslate(self) -> None:
        self.setWindowTitle(f"{APP_NAME} - {self._i18n.t('first_use.header.title', default='首次使用设置')}")

        self._header_title.setText(self._i18n.t("first_use.header.title", default="首次使用设置"))
        self._header_subtitle.setText(
            self._i18n.t(
                "first_use.header.subtitle",
                default="先完成基础偏好设置，随后再进入主界面并加载插件。",
            )
        )

        self._welcome_title.setText(self._i18n.t("first_use.welcome.title", default="欢迎使用小树时钟"))
        self._welcome_hint.setText(
            self._i18n.t(
                "first_use.welcome.subtitle",
                default="如果当前语言看不懂，不用担心，直接点击下方 English / 中文 即可切换。",
            )
        )
        self._welcome_quick_hint.setText(
            self._i18n.t(
                "first_use.welcome.quick_hint",
                default="看不懂当前文字？点击 English；If unreadable, click 中文 or English.",
            )
        )
        self._language_card.titleLabel.setText(self._i18n.t("first_use.welcome.language.label", default="界面语言"))
        self._language_card.contentLabel.setText(
            self._i18n.t("first_use.welcome.language.desc", default="语言会立即生效，并用于后续所有页面。")
        )

        self._appearance_title.setText(self._i18n.t("first_use.preferences.title", default="外观偏好"))
        self._appearance_desc.setText(
            self._i18n.t("first_use.preferences.subtitle", default="先设置主题；后续仍可在设置页面修改。")
        )
        self._theme_card.titleLabel.setText(self._i18n.t("first_use.preferences.theme.label", default="界面主题"))
        self._theme_card.contentLabel.setText(self._i18n.t("first_use.preferences.theme.desc", default="设置主界面的整体观感"))
        self._appearance_tip.setText(
            self._i18n.t("first_use.preferences.tip", default="主题将立即生效，方便你边选边看。")
        )

        # 网络页面
        self._network_title.setText(self._i18n.t("first_use.network.title", default="网络设置"))
        self._network_desc.setText(
            self._i18n.t("first_use.network.subtitle", default="配置 NTP 时间同步与 PyPI 镜像源，加速插件依赖下载。")
        )
        self._network_ntp_card.titleLabel.setText(self._i18n.t("first_use.network.ntp.label", default="NTP 时间校准"))
        self._network_ntp_card.contentLabel.setText(self._i18n.t("first_use.network.ntp.desc", default="自动从网络校准时间，确保时钟精准"))
        self._network_ntp_server_card.titleLabel.setText(self._i18n.t("settings.ntp.server.label", default="NTP 服务器"))
        self._network_ntp_server_card.contentLabel.setText(self._i18n.t("settings.ntp.server.desc", default="选择网络授时服务器"))
        self._network_ntp_interval_card.titleLabel.setText(self._i18n.t("settings.ntp.interval.label", default="同步间隔"))
        self._network_ntp_interval_card.contentLabel.setText(self._i18n.t("settings.ntp.interval.desc", default="每隔多久同步一次网络时间"))
        self._network_ntp_interval_spin.setSuffix(self._i18n.t("settings.unit.minute", default="分钟"))
        self._network_pypi_card.titleLabel.setText(self._i18n.t("first_use.network.pypi.label", default="PyPI 镜像源"))
        self._network_pypi_card.contentLabel.setText(self._i18n.t("first_use.network.pypi.desc", default="插件安装依赖时使用的下载源"))
        self._network_tip.setText(
            self._i18n.t("first_use.network.tip", default="国内用户建议选择国内镜像以加速下载。")
        )
        self._reload_network_widgets()

        self._system_title.setText(self._i18n.t("first_use.system.title", default="系统设置"))
        self._system_desc.setText(
            self._i18n.t("first_use.system.subtitle", default="配置 URL Scheme 与开机自启动。")
        )
        open_view_keys = sorted(url_scheme_service.list_open_views().keys())
        url_hint_lines = [url_scheme_service.build_open_url(key) for key in open_view_keys]
        url_hint_lines.append(f"{URL_SCHEME}://fullscreen/<zone_id>")
        self._url_card.titleLabel.setText(self._i18n.t("first_use.system.url.label", default="注册 URL Scheme"))
        self._url_card.contentLabel.setText(
            self._i18n.t(
                "first_use.system.url.desc",
                default="注册后可通过 {scheme}:// 拉起应用。示例：{views}",
                scheme=URL_SCHEME,
                views="  |  ".join(url_hint_lines),
            )
        )
        self._autostart_card.titleLabel.setText(
            self._i18n.t("first_use.system.autostart.label", default="开机自启动")
        )
        self._autostart_card.contentLabel.setText(
            self._i18n.t(
                "first_use.system.autostart.desc",
                default="登录 Windows 后自动启动小树时钟（后台隐藏启动）",
            )
        )

        self._notification_title.setText(self._i18n.t("first_use.notification.title", default="通知设置"))
        self._notification_desc.setText(
            self._i18n.t("first_use.notification.subtitle", default="只保留通知位置和停留时长两个核心选项。")
        )
        self._notification_position_card.titleLabel.setText(self._i18n.t("settings.notif.pos.label", default="通知位置"))
        self._notification_position_card.contentLabel.setText(self._i18n.t("settings.notif.pos.desc", default="选择通知出现位置"))
        self._notification_duration_card.titleLabel.setText(self._i18n.t("settings.notif.duration.label", default="通知时长"))
        self._notification_duration_card.contentLabel.setText(self._i18n.t("settings.notif.duration.desc", default="通知自动消失前停留时间"))
        self._notification_duration_spin.setSuffix(self._i18n.t("settings.unit.second", default="秒"))
        self._notification_duration_spin.setSpecialValueText(self._i18n.t("settings.notif.sticky", default="常驻"))

        self._learning_title.setText(self._i18n.t("first_use.learning.title", default="计时设置"))
        self._learning_desc.setText(
            self._i18n.t("first_use.learning.subtitle", default="配置秒表与计时器的显示精度。")
        )
        self._stopwatch_precision_card.titleLabel.setText(
            self._i18n.t("settings.timer.sw_precision.label", default="秒表精度")
        )
        self._stopwatch_precision_card.contentLabel.setText(
            self._i18n.t("settings.timer.sw_precision.desc", default="秒表显示位数")
        )
        self._timer_precision_card.titleLabel.setText(
            self._i18n.t("settings.timer.timer_precision.label", default="计时器精度")
        )
        self._timer_precision_card.contentLabel.setText(
            self._i18n.t("settings.timer.timer_precision.desc", default="计时器显示位数")
        )

        self._finish_title.setText(self._i18n.t("first_use.finish.title", default="准备完成"))
        self._finish_desc.setText(
            self._i18n.t("first_use.finish.subtitle", default="确认以下配置后即可进入主窗口。")
        )
        self._finish_tip.setText(
            self._i18n.t("first_use.finish.tip", default="点击“完成并进入”后，应用将按所选设置启动。")
        )

        self._back_button.setText(self._i18n.t("first_use.action.back", default="上一步"))
        self._finish_button.setText(self._i18n.t("first_use.action.finish", default="完成并进入"))

        self._reload_language_combo()
        self._reload_theme_combo()
        self._reload_notification_position_combo()
        self._reload_precision_combos()
        self._notification_duration_spin.blockSignals(True)
        self._notification_duration_spin.setValue(self._settings.notification_duration_ms // 1000)
        self._notification_duration_spin.blockSignals(False)
        self._update_language_quick_buttons()
        self._update_url_switch_text()
        self._update_autostart_switch_text()
        self._refresh_breadcrumb()
        self._refresh_summary()

        if self._stack.currentIndex() == 0:
            self._next_button.setText(self._i18n.t("first_use.action.start", default="开始设置"))
        else:
            self._next_button.setText(self._i18n.t("first_use.action.next", default="下一步"))

    def _set_step(self, index: int) -> None:
        last_step = len(self._steps) - 1
        index = max(0, min(last_step, index))
        self._max_unlocked_step = max(self._max_unlocked_step, index)

        self._stack.setCurrentIndex(index)
        self._refresh_breadcrumb()

        self._back_button.setVisible(index > 0)
        self._next_button.setVisible(index < last_step)
        self._finish_button.setVisible(index == last_step)

        if index == 0:
            self._next_button.setText(self._i18n.t("first_use.action.start", default="开始设置"))
        else:
            self._next_button.setText(self._i18n.t("first_use.action.next", default="下一步"))

        if index == last_step:
            self._refresh_summary()

    def _refresh_summary(self) -> None:
        lang_key = self._settings.language
        lang_name = self._i18n.t(f"lang.{lang_key}", default=lang_key)

        theme_key = self._settings.theme
        theme_name = self._i18n.t(_THEME_LABEL_KEYS.get(theme_key, "settings.theme.auto"), default=theme_key)

        url_state = self._i18n.t("first_use.switch.enabled", default="已开启") if self._url_switch.isChecked() else self._i18n.t("first_use.switch.disabled", default="已关闭")
        autostart_state = self._i18n.t("first_use.switch.enabled", default="已开启") if self._autostart_switch.isChecked() else self._i18n.t("first_use.switch.disabled", default="已关闭")
        ntp_state = self._i18n.t("first_use.switch.enabled", default="已开启") if self._network_ntp_switch.isChecked() else self._i18n.t("first_use.switch.disabled", default="已关闭")

        # PyPI 镜像源名称
        pypi_index = self._network_pypi_combo.currentIndex()
        pypi_mirror_name = self._network_pypi_combo.itemText(pypi_index) if pypi_index >= 0 else ""

        pos_key = self._settings.notification_position
        pos_name = _position_label(self._i18n, pos_key)

        duration_sec = self._settings.notification_duration_ms // 1000
        if duration_sec == 0:
            duration_text = self._i18n.t("settings.notif.sticky", default="常驻")
        else:
            duration_text = f"{duration_sec}{self._i18n.t('settings.unit.second', default='秒')}"

        precision_options = _precision_labels(self._i18n)
        sw_precision = precision_options[self._settings.stopwatch_precision]
        timer_precision = precision_options[self._settings.timer_precision]

        self._summary_language.setText(
            self._i18n.t("first_use.finish.summary.language", default="界面语言：{language}", language=lang_name)
        )
        self._summary_theme.setText(
            self._i18n.t("first_use.finish.summary.theme", default="界面主题：{theme}", theme=theme_name)
        )
        self._summary_ntp.setText(
            self._i18n.t(
                "first_use.finish.summary.ntp",
                default="NTP 同步：{state}（{server}）",
                state=ntp_state,
                server=self._ntp.server,
            )
        )
        self._summary_pypi.setText(
            self._i18n.t(
                "first_use.finish.summary.pypi",
                default="PyPI 镜像：{mirror}",
                mirror=pypi_mirror_name,
            )
        )
        self._summary_url.setText(
            self._i18n.t("first_use.finish.summary.url", default="URL 协议注册：{value}", value=url_state)
        )
        self._summary_autostart.setText(
            self._i18n.t(
                "first_use.finish.summary.autostart",
                default="开机自启动：{value}",
                value=autostart_state,
            )
        )
        self._summary_notification_position.setText(
            self._i18n.t(
                "first_use.finish.summary.notification_position",
                default="通知位置：{position}",
                position=pos_name,
            )
        )
        self._summary_notification_duration.setText(
            self._i18n.t(
                "first_use.finish.summary.notification_duration",
                default="通知时长：{duration}",
                duration=duration_text,
            )
        )
        self._summary_stopwatch_precision.setText(
            self._i18n.t(
                "first_use.finish.summary.stopwatch_precision",
                default="秒表精度：{precision}",
                precision=sw_precision,
            )
        )
        self._summary_timer_precision.setText(
            self._i18n.t(
                "first_use.finish.summary.timer_precision",
                default="计时器精度：{precision}",
                precision=timer_precision,
            )
        )

    def _apply_language(self, language: str) -> None:
        self._settings.set_language(language)
        self._i18n.set_language(language)
        self._update_language_quick_buttons()

    @Slot()
    def _rotate_hello(self) -> None:
        if not _HELLO_PHRASES:
            return
        self._hello_index = (self._hello_index + 1) % len(_HELLO_PHRASES)
        self._hello_label.setText(_HELLO_PHRASES[self._hello_index])

    @Slot(str)
    def _on_breadcrumb_changed(self, route_key: str) -> None:
        if self._syncing_breadcrumb:
            return
        step = self._route_to_step.get(route_key)
        if step is None or step > self._max_unlocked_step:
            return
        self._set_step(step)

    @Slot(int)
    def _on_language_changed(self, index: int) -> None:
        key = self._language_combo.itemData(index)
        if key:
            self._apply_language(str(key))

    @Slot(int)
    def _on_theme_changed(self, index: int) -> None:
        key = self._theme_combo.itemData(index)
        if not key:
            return

        theme = str(key)
        self._settings.set_theme(theme)
        self._apply_theme(theme)
        self._refresh_summary()

    @Slot(bool)
    def _on_network_ntp_enable_changed(self, checked: bool) -> None:
        self._ntp.set_enabled(checked)
        self._update_network_ntp_controls_state()
        self._refresh_summary()

    @Slot(str)
    def _on_network_ntp_server_changed(self, server: str) -> None:
        self._ntp.set_server(server)
        self._refresh_summary()

    @Slot(int)
    def _on_network_pypi_changed(self, index: int) -> None:
        url = self._network_pypi_combo.itemData(index)
        if url is not None:
            self._settings.set_pip_mirror(str(url))
            self._refresh_summary()

    @Slot(int)
    def _on_network_ntp_interval_changed(self, value: int) -> None:
        self._ntp.set_sync_interval(value)

    @Slot(bool)
    def _on_url_switch_changed(self, checked: bool) -> None:
        if checked:
            ok, _ = url_scheme_service.register()
        else:
            ok, _ = url_scheme_service.unregister()

        if not ok:
            self._url_switch.blockSignals(True)
            self._url_switch.setChecked(not checked)
            self._url_switch.blockSignals(False)

        self._update_url_switch_text()
        self._refresh_summary()

    @Slot(bool)
    def _on_autostart_switch_changed(self, checked: bool) -> None:
        ok, _ = startup_service.set_enabled(checked, hidden=True)

        if not ok:
            self._autostart_switch.blockSignals(True)
            self._autostart_switch.setChecked(not checked)
            self._autostart_switch.blockSignals(False)

        self._update_autostart_switch_text()
        self._refresh_summary()

    @Slot(int)
    def _on_notification_position_changed(self, _: int) -> None:
        key = self._notification_position_combo.currentData()
        if key:
            self._settings.set_notification_position(str(key))
            self._refresh_summary()

    @Slot(int)
    def _on_notification_duration_changed(self, seconds: int) -> None:
        self._settings.set_notification_duration_ms(seconds * 1000)
        self._refresh_summary()

    @Slot(int)
    def _on_stopwatch_precision_changed(self, index: int) -> None:
        self._settings.set_stopwatch_precision(index)
        self._refresh_summary()

    @Slot(int)
    def _on_timer_precision_changed(self, index: int) -> None:
        self._settings.set_timer_precision(index)
        self._refresh_summary()

    @staticmethod
    def _apply_theme(theme: str) -> None:
        if theme == "dark":
            setTheme(Theme.DARK)
        elif theme == "light":
            setTheme(Theme.LIGHT)
        else:
            setTheme(Theme.AUTO)

    @Slot()
    def _go_previous(self) -> None:
        self._set_step(self._stack.currentIndex() - 1)

    @Slot()
    def _go_next(self) -> None:
        self._set_step(self._stack.currentIndex() + 1)

    @Slot()
    def _finish_setup(self) -> None:
        self._settings.set_first_use_completed(True)
        self._is_completed = True
        self.setupCompleted.emit()
        self.close()

    def closeEvent(self, event) -> None:
        if self._hello_timer.isActive():
            self._hello_timer.stop()

        if not self._is_completed:
            self.setupCanceled.emit()

        super().closeEvent(event)
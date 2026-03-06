"""主窗口：FluentWindow 骨架，负责导航和系统托盘"""
from qfluentwidgets import (
    FluentWindow, FluentIcon as FIF, SplashScreen,
    NavigationItemPosition, RoundMenu, Action,
    InfoBar, InfoBarPosition,
    setTheme, Theme,
)
from PySide6.QtWidgets import QApplication, QSystemTrayIcon
from PySide6.QtGui import QIcon
from PySide6.QtCore import Qt, QSize, QTimer

from app.constants import APP_NAME, LONG_VER, ICON_PATH, CONFIG_DIR, TEMP_DIR, PLUGINS_DIR, IS_BETA
from app.widgets.lazy_factory_widget import LazyFactoryWidget
from app.widgets.watermark import WatermarkOverlay, SafeModeWatermark

# 服务层
from app.services.clock_service        import ClockService
from app.services.alarm_service        import AlarmService
from app.services.notification_service import NotificationService
from app.services.ntp_service          import NtpService

# 数据层
from app.models.alarm_model      import AlarmStore
from app.models.automation_model import AutomationStore

# 插件系统
from PySide6.QtGui import QIcon as _QIcon
from app.plugins.plugin_manager import PluginManager
from app.plugins.base_plugin    import PluginAPI

# 自动化引擎
from app.automation.engine       import AutomationEngine
from app.models.automation_model import TriggerType

# 工具
from app.utils.fs import ensure_dirs
from app.utils.logger import logger

# URL Scheme
from app.services.url_scheme_service import parse_url

# 视图
from app.views.world_time_view  import WorldTimeView
from app.views.home_view        import HomeView
from app.views.alarm_view       import AlarmView
from app.views.timer_view       import TimerView
from app.views.stopwatch_view   import StopwatchView
from app.views.focus_view       import FocusView
from app.views.plugin_view      import PluginView
from app.views.automation_view  import AutomationView
from app.views.settings_view    import SettingsView
from app.views.debug_view       import DebugWindow
from app.views.toast_notification import ToastManager

from app.services.focus_service import FocusService
from app.services.settings_service import SettingsService
from app.services.i18n_service import I18nService
from app.services.recommendation_service import (
    RecommendationService,
    FEATURE_WORLD_TIME, FEATURE_ALARM, FEATURE_TIMER,
    FEATURE_STOPWATCH, FEATURE_FOCUS, FEATURE_PLUGIN, FEATURE_AUTOMATION,
)


class MainWindow(FluentWindow):
    """应用主窗口"""

    def __init__(self, safe_mode: bool = False, hidden_mode: bool = False, extra_args: str = ""):
        super().__init__()
        self._safe_mode   = safe_mode
        self._hidden_mode = hidden_mode

        # 确保目录存在
        ensure_dirs(CONFIG_DIR, TEMP_DIR, PLUGINS_DIR)

        # ------------------------------------------------------------------
        # 基础服务（无 UI 依赖，先初始化）
        # ------------------------------------------------------------------
        # NTP 服务必须最先初始化，供其他时间相关模块使用
        self._ntp_service   = NtpService.instance()
        self._clock_service = ClockService(self)
        self._alarm_store   = AlarmStore()
        self._alarm_service = AlarmService(self._alarm_store, self)
        self._notif_service = NotificationService(parent=self)
        self._plugin_api    = PluginAPI()
        self._auto_store    = AutomationStore()
        self._auto_engine   = AutomationEngine(
            self._auto_store,
            self._plugin_api,
            self._notif_service,
            self,
        )
        self._focus_service = FocusService(self)

        # Toast 通知管理器（需在 NotificationService 之后创建）
        _settings = SettingsService.instance()
        self._i18n = I18nService.instance()
        self._i18n.set_language(_settings.language)
        self._toast_mgr = ToastManager(self)
        self._toast_mgr.set_position(_settings.notification_position)
        self._toast_mgr.set_duration(_settings.notification_duration_ms)
        self._notif_service.set_toast_manager(self._toast_mgr)

        # 启动时应用保存的主题
        self._apply_theme(_settings.theme)

        # 插件管理器（需在所有服务初始化完成后创建，确保 services 字典完整）
        self._plugin_mgr = PluginManager(
            shared_api     = self._plugin_api,
            services       = {
                "alarm_service":        self._alarm_service,
                "focus_service":        self._focus_service,
                "settings_service":     _settings,
                "ntp_service":          self._ntp_service,
                "notification_service": self._notif_service,
            },
            toast_callback = self._notif_service.show,
            parent         = self,
        )

        # 注入自动化引擎，使插件可通过 api.fire_trigger() 触发规则执行
        self._plugin_mgr.set_automation_engine(self._auto_engine)
        self._plugin_mgr.set_startup_context(
            hidden_mode=hidden_mode,
            extra_args=extra_args,
        )

        # ------------------------------------------------------------------
        # 视图
        # ------------------------------------------------------------------
        self.home_view       = HomeView()
        self.world_time_view = WorldTimeView(self._clock_service, self._plugin_mgr,
                                              notification_service=self._notif_service)
        self.alarm_view      = AlarmView(self._alarm_service, self._notif_service)
        self.timer_view      = TimerView(self._clock_service, self._notif_service)
        self.stopwatch_view  = StopwatchView(self._clock_service)
        self.focus_view      = FocusView(
            self._focus_service,
            self._notif_service,
        )
        self.plugin_view     = PluginView(self._plugin_mgr, toast_mgr=self._toast_mgr,
                                           safe_mode=safe_mode)
        self.automation_view = AutomationView(self._auto_engine, self._plugin_api,
                                              safe_mode=safe_mode)
        self.settings_view   = SettingsView(plugin_manager=self._plugin_mgr)
        # 调试窗口：独立浮窗，不注册到导航栏，仅可通过 URL 唤起
        self._debug_window   = DebugWindow(
            clock_service  = self._clock_service,
            alarm_service  = self._alarm_service,
            ntp_service    = self._ntp_service,
            plugin_manager = self._plugin_mgr,
            auto_engine    = self._auto_engine,
            home_view      = self.home_view,
        )

        # ------------------------------------------------------------------
        # 窗口初始化
        # ------------------------------------------------------------------
        self._init_window()
        self._init_splash()
        self._init_navigation()
        self._init_tray()
        self._init_connections()

        # 视图映射：objectName → widget（供 URL 导航使用）
        self._url_view_map: dict[str, object] = {
            "homeView":       self.home_view,
            "worldTimeView":  self.world_time_view,
            "alarmView":      self.alarm_view,
            "timerView":      self.timer_view,
            "stopwatchView":  self.stopwatch_view,
            "focusView":      self.focus_view,
            "pluginView":     self.plugin_view,
            "automationView": self.automation_view,
            "settingsView":   self.settings_view,
            # debugView 不在此处；在 handle_url 中直接弹出独立窗口
        }

        # 测试版水印
        if IS_BETA:
            self._watermark = WatermarkOverlay(self)
            self._watermark.setGeometry(self.rect())
            self._watermark.setVisible(_settings.watermark_main_visible)
            self._watermark.raise_()
            _settings.changed.connect(self._apply_watermark_visibility)

        # 安全模式右下角水印
        if safe_mode:
            self._safe_watermark = SafeModeWatermark(self)
            self._safe_watermark.setGeometry(self.rect())
            self._safe_watermark.show()
            self._safe_watermark.raise_()

        # 插件侧边栏面板追踪表：plugin_id -> QWidget
        self._plugin_sidebar_widgets: dict[str, object] = {}
        self._plugin_mgr.pluginLoaded.connect(self._on_plugin_loaded)
        self._plugin_mgr.pluginUnloaded.connect(self._on_plugin_unloaded)

        # 启动后触发自动化 & 延迟加载插件（splash 仍显示中，300ms 足够 UI 就绪）
        # 注入主窗口和专注服务到引擎（用于 show/hide/focus 动作）
        self._auto_engine.set_main_window(self)
        self._auto_engine.set_focus_service(self._focus_service)
        # 安全模式下跳过自动化启动事件和插件加载
        if not safe_mode:
            QTimer.singleShot(500, self._auto_engine.fire_startup)
            QTimer.singleShot(300, self._plugin_mgr.discover_and_load)
        else:
            logger.info("安全模式已开启，跳过插件加载和自动化启动事件")
            # 安全模式下也需要触发 scanCompleted 以关闭 Splash
            QTimer.singleShot(600, self._plugin_mgr.scanCompleted.emit)
        logger.info("{} 已启动，版本：{}{}", APP_NAME, LONG_VER,
                    "（安全模式）" if safe_mode else "")

    # ------------------------------------------------------------------
    # 初始化
    # ------------------------------------------------------------------

    def _on_plugin_loaded(self, plugin_id: str) -> None:
        """插件加载后，按需注入侧边栏与设置页扩展。"""
        entry = self._plugin_mgr.get_entry(plugin_id)
        if entry is None:
            return
        if entry.plugin.has_sidebar_widget():
            try:
                # 解析图标
                icon_raw = entry.plugin.get_sidebar_icon()
                if icon_raw is None:
                    icon = FIF.APPLICATION
                elif isinstance(icon_raw, str):
                    import os
                    if not os.path.isfile(icon_raw):
                        logger.warning("插件 {} 侧边栏图标路径不存在: {}，使用默认图标", plugin_id, icon_raw)
                        icon = FIF.APPLICATION
                    else:
                        icon = _QIcon(icon_raw)
                else:
                    icon = icon_raw  # FluentIconBase 或 QIcon 直接使用

                label = entry.plugin.get_sidebar_label() or entry.plugin.meta.name
                if hasattr(entry.plugin.meta, "get_name"):
                    label = entry.plugin.get_sidebar_label() or entry.plugin.meta.get_name(self._i18n.language)

                widget = LazyFactoryWidget(
                    entry.plugin.create_sidebar_widget,
                    loading_text=f"正在加载「{label}」…",
                    empty_text="插件未提供侧边栏内容",
                    error_text="插件侧边栏加载失败",
                    debug_name=f"plugin sidebar:{plugin_id}",
                    parent=self,
                )
                widget.setObjectName(f"pluginSidebar_{plugin_id}")

                self.addSubInterface(widget, icon, label)
                self._plugin_sidebar_widgets[plugin_id] = widget
                logger.debug("插件 '{}' 侧边栏面板已注册（延迟创建）：{}", plugin_id, label)
            except Exception:
                logger.exception("插件 {} 侧边栏面板注册失败", plugin_id)

        # 注入插件设置面板（延迟创建，避免启动时同步构建全部插件 UI）
        if entry.plugin.has_settings_widget():
            try:
                display = entry.plugin.meta.name if entry.plugin.meta else plugin_id
                if hasattr(entry.plugin.meta, "get_name"):
                    display = entry.plugin.meta.get_name(self._i18n.language)
                self.settings_view.add_plugin_settings_factory(
                    plugin_id,
                    display,
                    entry.plugin.create_settings_widget,
                )
            except Exception:
                logger.exception("插件 {} 设置面板注入失败", plugin_id)

    def _on_plugin_unloaded(self, plugin_id: str) -> None:
        """插件卸载后，移除其侧边栏导航项。"""
        widget = self._plugin_sidebar_widgets.pop(plugin_id, None)
        if widget is None:
            return
        try:
            self.removeInterface(widget, isDelete=True)
            logger.debug("插件 '{}' 侧边栏面板已移除", plugin_id)
        except Exception:
            logger.exception("插件 {} 侧边栏面板移除失败", plugin_id)

        # 移除插件设置面板
        self.settings_view.remove_plugin_settings(plugin_id)

    @staticmethod
    def _apply_theme(theme: str) -> None:
        """将配置的主题值应用到 qfluentwidgets"""
        if theme == "dark":
            setTheme(Theme.DARK)
        elif theme == "light":
            setTheme(Theme.LIGHT)
        else:
            setTheme(Theme.AUTO)

    def _init_window(self):
        self.resize(960, 720)
        self.setWindowIcon(QIcon(ICON_PATH) if ICON_PATH else QIcon())
        self.setWindowTitle(f"{APP_NAME}  {LONG_VER}")

    def _init_splash(self):
        self.splash = SplashScreen(self.windowIcon(), self)
        self.splash.setIconSize(QSize(102, 102))
        if not self._hidden_mode:
            self.show()

    def _init_navigation(self):
        # 首页（推荐面板）
        self.addSubInterface(self.home_view,  FIF.HOME,      "首页")

        # 主功能
        self.addSubInterface(self.world_time_view, FIF.GLOBE,       self._i18n.t("app.nav.world_time"))
        self.addSubInterface(self.alarm_view,      FIF.RINGER,      self._i18n.t("app.nav.alarm"))
        self.addSubInterface(self.timer_view,      FIF.HISTORY,     self._i18n.t("app.nav.timer"))
        self.addSubInterface(self.stopwatch_view,  FIF.STOP_WATCH,  self._i18n.t("app.nav.stopwatch"))
        self.addSubInterface(self.focus_view,      FIF.CAFE,        self._i18n.t("app.nav.focus"))

        self.navigationInterface.addSeparator()

        # 系统功能
        self.addSubInterface(self.plugin_view,     FIF.APPLICATION, self._i18n.t("app.nav.plugin"))
        self.addSubInterface(self.automation_view, FIF.FLAG,        self._i18n.t("app.nav.automation"))

        # 底部
        self.addSubInterface(
            self.settings_view, FIF.SETTING, self._i18n.t("app.nav.settings"),
            NavigationItemPosition.BOTTOM,
        )

        InfoBar.info(
            title=APP_NAME,
            content=LONG_VER,
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.BOTTOM_RIGHT,
            duration=4000,
            parent=self,
        )

    def _init_tray(self):
        self._tray = QSystemTrayIcon(self)
        self._tray.setIcon(QIcon(ICON_PATH) if ICON_PATH else QIcon())
        self._notif_service.set_tray(self._tray)

        menu = RoundMenu()
        menu.addActions([
            Action(FIF.LINK,  self._i18n.t("app.tray.show"), triggered=self.showNormal),
            Action(FIF.EMBED, self._i18n.t("app.tray.exit"), triggered=self._quit),
        ])
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

    def _init_connections(self):
        """连接跨模块信号"""
        # 闹钟触发 → 自动化引擎
        self._alarm_service.alarmFired.connect(
            lambda aid: self._auto_engine.fire_event(TriggerType.ALARM_FIRED, alarm_id=aid)
        )

        # 专注服务信号 → 自动化引擎
        from app.services.focus_service import FocusPhase
        def _on_phase_changed(phase, cycle_idx):
            if phase == FocusPhase.BREAK:
                self._auto_engine.fire_event(TriggerType.FOCUS_BREAK_START)
            elif phase == FocusPhase.FOCUS:
                self._auto_engine.fire_event(TriggerType.FOCUS_BREAK_END)
        self._focus_service.phaseChanged.connect(_on_phase_changed)

        def _on_phase_finished(phase):
            if phase == FocusPhase.FOCUS:
                self._auto_engine.fire_event(TriggerType.FOCUS_SESSION_DONE)
        self._focus_service.phaseFinished.connect(_on_phase_finished)

        # 不专注提醒 → 自动化引擎（触发 FOCUS_DISTRACTED 事件）
        self._focus_service.distractedAlert.connect(
            lambda sec: self._auto_engine.fire_event(TriggerType.FOCUS_DISTRACTED, distracted_sec=sec)
        )

        # 插件扫描完成 / 即将弹出权限对话框 → 关闭启动页面（只执行一次）
        self._splash_finished = False

        def _finish_splash_once():
            if not self._splash_finished:
                self._splash_finished = True
                self.splash.finish()

        self._plugin_mgr.scanCompleted.connect(_finish_splash_once)
        # 权限询问已改为常驻 Toast（WindowStaysOnTopHint），无需提前关闭启动界面

        # 插件加载错误 → 通知
        self._plugin_mgr.pluginError.connect(
            lambda pid, err: self._notif_service.show(self._i18n.t("app.plugin.load_error"), f"{pid}: {err}")
        )

        # 插件扫描完成 → 刷新自动化视图的插件动作/触发器列表
        self._plugin_mgr.scanCompleted.connect(
            lambda: self.automation_view.refresh_plugin_actions(self._plugin_api)
        )

        # APP_STARTUP 事件（延迟 600ms，确保 UI 已完成初始化）
        from PySide6.QtCore import QTimer as _QTimer
        _QTimer.singleShot(600, lambda: self._emit_app_event("startup"))

        # ── 首页推荐服务注入 ───────────────────────────────────────── #
        self._reco = RecommendationService.instance()

        # 首页视图依赖注入：导航切揢回调
        _FEATURE_TO_VIEW_OBJ = {
            "world_time": self.world_time_view,
            "alarm":      self.alarm_view,
            "timer":      self.timer_view,
            "stopwatch":  self.stopwatch_view,
            "focus":      self.focus_view,
            "plugin":     self.plugin_view,
            "automation": self.automation_view,
            "home":       self.home_view,
        }

        def _navigate(view_key: str):
            view = _FEATURE_TO_VIEW_OBJ.get(view_key)
            if view:
                self.showNormal()
                self.activateWindow()
                self.switchTo(view)

        self.home_view.set_services(
            timer_view           = self.timer_view,
            stopwatch_view       = self.stopwatch_view,
            focus_service        = self._focus_service,
            alarm_service        = self._alarm_service,
            alarm_store          = self._alarm_store,
            clock_service        = self._clock_service,
            plugin_manager       = self._plugin_mgr,
            notification_service = self._notif_service,
            navigate_to          = _navigate,
        )

        # 连接 EventBus → 推荐服务（会话轨迹记录）
        try:
            from app.events import EventBus, EventType
            EventBus.subscribe(EventType.TIMER_STARTED,
                lambda **_: self._reco.on_session_start(FEATURE_TIMER))
            EventBus.subscribe(EventType.TIMER_DONE,
                lambda **_: self._reco.on_session_end(FEATURE_TIMER))
            EventBus.subscribe(EventType.FOCUS_STARTED,
                lambda **_: self._reco.on_session_start(FEATURE_FOCUS))
            EventBus.subscribe(EventType.FOCUS_ENDED,
                lambda **_: self._reco.on_session_end(FEATURE_FOCUS))
            EventBus.subscribe(EventType.ALARM_FIRED,
                lambda **_: self._reco.on_session_start(FEATURE_ALARM))
        except Exception:
            pass

    def _emit_app_event(self, name: str) -> None:
        try:
            from app.events import EventBus, EventType
            event = getattr(EventType, f"APP_{name.upper()}", None)
            if event:
                EventBus.emit(event)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # URL 导航
    # ------------------------------------------------------------------

    def switchTo(self, widget) -> None:
        """Override: 切换视图时无山映射功能 ID 并通知推荐服务记录访问"""
        super().switchTo(widget)
        reco = getattr(self, "_reco", None)
        if reco is None:
            return
        _VIEW_FEATURE_MAP = {
            id(self.home_view):        None,           # 首页本身不记录
            id(self.world_time_view):  FEATURE_WORLD_TIME,
            id(self.alarm_view):       FEATURE_ALARM,
            id(self.timer_view):       FEATURE_TIMER,
            id(self.stopwatch_view):   FEATURE_STOPWATCH,
            id(self.focus_view):       FEATURE_FOCUS,
            id(self.plugin_view):      FEATURE_PLUGIN,
            id(self.automation_view):  FEATURE_AUTOMATION,
        }
        feat = _VIEW_FEATURE_MAP.get(id(widget))
        if feat is not None:
            reco.on_view_shown(feat)

    def handle_url(self, url: str) -> None:
        """
        解析并导航到 URL 指定的视图。

        支持格式：``ltclock://open/<view_key>``
        """
        object_name = parse_url(url)
        if not object_name:
            logger.warning("无法识别的 URL：{}", url)
            InfoBar.warning(
                title=self._i18n.t("app.url.invalid_title"),
                content=self._i18n.t("app.url.invalid_content", url=url),
                isClosable=True,
                position=InfoBarPosition.TOP_RIGHT,
                duration=3000,
                parent=self,
            )
            return

        # 调试窗口单独弹出，不切换主窗口
        if object_name == "debugView":
            self._debug_window.show()
            self._debug_window.activateWindow()
            self._debug_window.raise_()
            logger.info("URL 导航 → 调试窗口")
            return

        view = self._url_view_map.get(object_name)
        if view is None:
            logger.warning("URL 对应视图不存在：{}", object_name)
            return

        # 唤起窗口并切换到目标视图
        self.showNormal()
        self.activateWindow()
        self.raise_()
        self.switchTo(view)
        logger.info("URL 导航 → {} ({})", url, object_name)

    # ------------------------------------------------------------------
    # 事件
    # ------------------------------------------------------------------

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if IS_BETA and hasattr(self, "_watermark"):
            self._watermark.setGeometry(self.rect())
            self._watermark.raise_()
        if hasattr(self, "_safe_watermark"):
            self._safe_watermark.setGeometry(self.rect())
            self._safe_watermark.raise_()

    def _apply_watermark_visibility(self) -> None:
        """根据设置刷新主窗口水印可见性"""
        if IS_BETA and hasattr(self, "_watermark"):
            visible = SettingsService.instance().watermark_main_visible
            self._watermark.setVisible(visible)
            if visible:
                self._watermark.raise_()

    def closeEvent(self, event):
        """关闭窗口时最小化到系统托盘"""
        if self._tray.isVisible():
            self.hide()
            event.ignore()
            self._emit_app_event("hidden")

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.showNormal()
            self._emit_app_event("shown")

    def _quit(self):
        self._auto_engine.fire_event(TriggerType.APP_SHUTDOWN)
        self._emit_app_event("shutdown")
        self._plugin_mgr.unload_all()
        self._tray.hide()
        logger.info("{} 已退出", APP_NAME)
        QApplication.quit()

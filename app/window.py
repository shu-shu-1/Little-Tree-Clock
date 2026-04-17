"""主窗口：FluentWindow 骨架，负责导航和系统托盘"""

import inspect
import json
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Dict, List

from qfluentwidgets import (
    FluentWindow,
    FluentIcon as FIF,
    SplashScreen,
    NavigationItemPosition,
    RoundMenu,
    Action,
    InfoBar,
    InfoBarPosition,
    FluentTitleBarButton,
    TransparentToolButton,
    setTheme,
    Theme,
)
from PySide6.QtWidgets import QApplication, QInputDialog, QSystemTrayIcon, QWidget
from PySide6.QtGui import QIcon
from PySide6.QtCore import QSize, QTimer

from app.constants import (
    APP_NAME,
    LONG_VER,
    ICON_PATH,
    CONFIG_DIR,
    TEMP_DIR,
    PLUGINS_DIR,
    IS_BETA,
)
from app.widgets.lazy_factory_widget import LazyFactoryWidget
from app.widgets.watermark import WatermarkOverlay, SafeModeWatermark

# 服务层
from app.services.clock_service import ClockService
from app.services.alarm_service import AlarmService
from app.services.notification_service import NotificationService
from app.services.ntp_service import NtpService

# 数据层
from app.models.alarm_model import AlarmStore
from app.models.automation_model import AutomationStore

# 插件系统
from PySide6.QtGui import QIcon as _QIcon
from app.plugins.plugin_manager import PluginManager, PLUGIN_PACKAGE_EXTENSION
from app.plugins.base_plugin import PluginAPI

# 自动化引擎
from app.automation.engine import AutomationEngine
from app.models.automation_model import TriggerType

# 工具
from app.utils.fs import ensure_dirs
from app.utils.logger import logger

# URL Scheme
from app.services import url_scheme_service as uss
from app.services.url_scheme_service import parse_url_target

# 视图
from app.views.world_time_view import WorldTimeView
from app.views.home_view import HomeView
from app.views.alarm_view import AlarmView
from app.views.timer_view import TimerView
from app.views.stopwatch_view import StopwatchView
from app.views.focus_view import FocusView
from app.views.plugin_view import PluginView
from app.views.automation_view import AutomationView
from app.views.settings_view import SettingsView
from app.views.plugin_file_open_view import PluginFileOpenWindow
from app.views.layout_file_open_view import LayoutFileOpenWindow
from app.views.file_type_open_view import FileTypeOpenWindow
from app.views.debug_view import DebugWindow
from app.views.central_control_window import CentralControlWindow
from app.views.permission_management_window import PermissionManagementWindow
from app.views.permission_auth_dialog import PermissionAuthDialog
from app.views.toast_notification import ToastManager

from app.services.focus_service import FocusService
from app.services.settings_service import SettingsService
from app.services.i18n_service import I18nService
from app.services.permission_service import PermissionService, AccessLevel
from app.services.central_control_service import CentralControlService
from app.services.layout_file_open_service import LayoutFileOpenService
from app.services.file_type_open_service import FileTypeOpenService
from app.services.remote_resource_service import RemoteResourceService
from app.services.update_service import UpdateInfo, UpdateService
from app.services.world_zone_service import WorldZoneService
from app.services.recommendation_service import (
    RecommendationService,
    FEATURE_WORLD_TIME,
    FEATURE_ALARM,
    FEATURE_TIMER,
    FEATURE_STOPWATCH,
    FEATURE_FOCUS,
    FEATURE_PLUGIN,
    FEATURE_AUTOMATION,
)
from app.views.announcement_widgets import AnnouncementPopupDialog
from app.views.update_window import UpdateWindow
from app.widgets.base_widget import WidgetConfig


class MainWindow(FluentWindow):
    """应用主窗口"""

    def __init__(
        self, safe_mode: bool = False, hidden_mode: bool = False, extra_args: str = ""
    ):
        super().__init__()
        self._safe_mode = safe_mode
        self._hidden_mode = hidden_mode

        # 确保目录存在
        ensure_dirs(CONFIG_DIR, TEMP_DIR, PLUGINS_DIR)

        # ------------------------------------------------------------------
        # 基础服务（无 UI 依赖，先初始化）
        # ------------------------------------------------------------------
        # NTP 服务必须最先初始化，供其他时间相关模块使用
        self._ntp_service = NtpService.instance()
        self._clock_service = ClockService(self)
        self._alarm_store = AlarmStore()
        self._alarm_service = AlarmService(self._alarm_store, self)
        self._notif_service = NotificationService(parent=self)
        self._plugin_api = PluginAPI()
        self._auto_store = AutomationStore()
        self._auto_engine = AutomationEngine(
            self._auto_store,
            self._plugin_api,
            self._notif_service,
            self,
        )
        self._focus_service = FocusService(self)
        self._world_zone_service = WorldZoneService()
        self._reco = RecommendationService.instance()
        self._layout_file_open_service = LayoutFileOpenService()
        self._file_type_open_service = FileTypeOpenService()

        # Toast 通知管理器（需在 NotificationService 之后创建）
        _settings = SettingsService.instance()
        self._settings_service = _settings
        self._i18n = I18nService.instance()
        self._i18n.set_language(_settings.language)
        self._permission_service = PermissionService.instance()
        self._central_control_service = CentralControlService.instance()
        self._toast_mgr = ToastManager(self)
        self._toast_mgr.set_position(_settings.notification_position)
        self._toast_mgr.set_duration(_settings.notification_duration_ms)
        self._notif_service.set_toast_manager(self._toast_mgr)
        self._remote_resources = RemoteResourceService(parent=self)
        self._update_service = UpdateService(settings_service=_settings, parent=self)

        # 启动时应用保存的主题
        self._apply_theme(_settings.theme)

        # 插件管理器（需在所有服务初始化完成后创建，确保 services 字典完整）
        self._plugin_mgr = PluginManager(
            shared_api=self._plugin_api,
            services={
                "alarm_service": self._alarm_service,
                "focus_service": self._focus_service,
                "settings_service": _settings,
                "ntp_service": self._ntp_service,
                "notification_service": self._notif_service,
                "world_zone_service": self._world_zone_service,
                "recommendation_service": self._reco,
                "url_scheme_service": uss,
                "layout_file_open_service": self._layout_file_open_service,
                "file_type_open_service": self._file_type_open_service,
                "permission_service": self._permission_service,
                "central_control_service": self._central_control_service,
                "update_service": self._update_service,
            },
            toast_callback=self._notif_service.show,
            parent=self,
        )

        self._central_control_service.bind_dependencies(
            settings_service=_settings,
            plugin_manager=self._plugin_mgr,
            world_zone_service=self._world_zone_service,
        )
        self._permission_service.set_feature_blocker_callback(
            self._central_control_service.is_feature_blocked
        )
        self._permission_service.set_auth_prompt_callback(self._prompt_permission_auth)

        # 注入自动化引擎，使插件可通过 api.fire_trigger() 触发规则执行
        self._plugin_mgr.set_automation_engine(self._auto_engine)
        self._plugin_mgr.set_startup_context(
            hidden_mode=hidden_mode,
            extra_args=extra_args,
        )

        # ------------------------------------------------------------------
        # 视图
        # ------------------------------------------------------------------
        self.home_view = HomeView()
        self.world_time_view = WorldTimeView(
            self._clock_service,
            self._plugin_mgr,
            notification_service=self._notif_service,
            permission_service=self._permission_service,
            central_control_service=self._central_control_service,
        )
        self.alarm_view = AlarmView(self._alarm_service, self._notif_service)
        self.timer_view = TimerView(self._clock_service, self._notif_service)
        self.stopwatch_view = StopwatchView(self._clock_service)
        self.focus_view = FocusView(
            self._focus_service,
            self._notif_service,
        )
        self.plugin_view = PluginView(
            self._plugin_mgr,
            resource_service=self._remote_resources,
            toast_mgr=self._toast_mgr,
            safe_mode=safe_mode,
            permission_service=self._permission_service,
            central_control_service=self._central_control_service,
        )
        self.automation_view = AutomationView(
            self._auto_engine, self._plugin_api, safe_mode=safe_mode
        )
        self.settings_view = SettingsView(
            plugin_manager=self._plugin_mgr,
            permission_service=self._permission_service,
            file_type_open_service=self._file_type_open_service,
            update_service=self._update_service,
            open_update_window=self._open_update_window,
        )
        # 调试窗口改为按需创建，降低启动阶段的 UI 构建开销。
        self._debug_window: DebugWindow | None = None
        self._central_control_window: CentralControlWindow | None = None
        self._permission_window: PermissionManagementWindow | None = None
        self._update_window: UpdateWindow | None = None
        self._title_menu_button = None

        # ------------------------------------------------------------------
        # 窗口初始化
        # ------------------------------------------------------------------
        self._init_window()
        self._init_splash()
        self._init_navigation()
        self._init_title_menu_button()
        self._init_tray()
        self._init_connections()

        # 视图映射：objectName → widget（供 URL 导航使用）
        self._url_view_map: dict[str, object] = {
            "homeView": self.home_view,
            "worldTimeView": self.world_time_view,
            "alarmView": self.alarm_view,
            "timerView": self.timer_view,
            "stopwatchView": self.stopwatch_view,
            "focusView": self.focus_view,
            "pluginView": self.plugin_view,
            "automationView": self.automation_view,
            "settingsView": self.settings_view,
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
        self._migration_window = None
        self._plugin_open_window = None
        self._layout_open_window = None
        self._file_type_open_window = None
        self._pending_error_announcements = []
        self._shown_error_announcement_ids: set[str] = set()
        self._showing_error_announcement_popup = False
        self._startup_announcements_requested = False
        self._startup_update_sequence_requested = False
        self._startup_update_popup_shown = False
        self._startup_post_update_shown = False
        self._startup_update_check_pending = False
        self._plugin_mgr.pluginLoaded.connect(self._on_plugin_loaded)
        self._plugin_mgr.pluginUnloaded.connect(self._on_plugin_unloaded)

        # 启动后触发自动化 & 延迟加载插件（splash 仍显示中，300ms 足够 UI 就绪）
        # 注入主窗口和专注服务到引擎（用于 show/hide/focus 动作）
        self._auto_engine.set_main_window(self)
        self._auto_engine.set_focus_service(self._focus_service)
        # 安全模式下跳过自动化启动事件和插件加载
        if not safe_mode:
            QTimer.singleShot(500, self._auto_engine.fire_startup)
            # 先让主界面尽快可见，再延后执行插件扫描，提升低配设备启动体感。
            QTimer.singleShot(900, self._plugin_mgr.discover_and_load)
        else:
            logger.info("安全模式已开启，跳过插件加载和自动化启动事件")
            # 安全模式下也需要触发 scanCompleted 以关闭 Splash
            QTimer.singleShot(600, self._plugin_mgr.scanCompleted.emit)
        logger.info(
            "{} 已启动，版本：{}{}",
            APP_NAME,
            LONG_VER,
            "（安全模式）" if safe_mode else "",
        )

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
                        logger.warning(
                            "插件 {} 侧边栏图标路径不存在: {}，使用默认图标",
                            plugin_id,
                            icon_raw,
                        )
                        icon = FIF.APPLICATION
                    else:
                        icon = _QIcon(icon_raw)
                else:
                    icon = icon_raw  # FluentIconBase 或 QIcon 直接使用

                label = entry.plugin.get_sidebar_label() or entry.plugin.meta.name
                if hasattr(entry.plugin.meta, "get_name"):
                    label = (
                        entry.plugin.get_sidebar_label()
                        or entry.plugin.meta.get_name(self._i18n.language)
                    )

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
                self._url_view_map[widget.objectName()] = widget
                logger.debug(
                    "插件 '{}' 侧边栏面板已注册（延迟创建）：{}", plugin_id, label
                )
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
        if widget is not None:
            try:
                self.removeInterface(widget, isDelete=True)
                logger.debug("插件 '{}' 侧边栏面板已移除", plugin_id)
            except Exception:
                logger.exception("插件 {} 侧边栏面板移除失败", plugin_id)
            self._url_view_map.pop(widget.objectName(), None)

        # 移除插件设置面板 / 权限项 / 集控事件注册
        self.settings_view.remove_plugin_settings(plugin_id)
        self._permission_service.unregister_plugin_entries(plugin_id)
        self._central_control_service.unregister_owner_events(f"plugin:{plugin_id}")

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
        self.addSubInterface(self.home_view, FIF.HOME, "首页")

        # 主功能
        self.addSubInterface(
            self.world_time_view, FIF.GLOBE, self._i18n.t("app.nav.world_time")
        )
        self.addSubInterface(self.alarm_view, FIF.RINGER, self._i18n.t("app.nav.alarm"))
        self.addSubInterface(
            self.timer_view, FIF.HISTORY, self._i18n.t("app.nav.timer")
        )
        self.addSubInterface(
            self.stopwatch_view, FIF.STOP_WATCH, self._i18n.t("app.nav.stopwatch")
        )
        self.addSubInterface(self.focus_view, FIF.CAFE, self._i18n.t("app.nav.focus"))

        self.navigationInterface.addSeparator()

        # 系统功能
        self.addSubInterface(
            self.plugin_view, FIF.APPLICATION, self._i18n.t("app.nav.plugin")
        )
        self.addSubInterface(
            self.automation_view, FIF.FLAG, self._i18n.t("app.nav.automation")
        )

        # 底部
        self.addSubInterface(
            self.settings_view,
            FIF.SETTING,
            self._i18n.t("app.nav.settings"),
            NavigationItemPosition.BOTTOM,
        )

        # InfoBar.info(
        #     title=APP_NAME,
        #     content=LONG_VER,
        #     orient=Qt.Horizontal,
        #     isClosable=True,
        #     position=InfoBarPosition.BOTTOM_RIGHT,
        #     duration=4000,
        #     parent=self,
        # )

    def _prompt_permission_auth(
        self,
        required_level: AccessLevel,
        method_ids: list[str],
        feature_name: str,
        reason: str,
        parent_widget: object | None,
    ) -> bool:
        parent = parent_widget if isinstance(parent_widget, QWidget) else self
        return PermissionAuthDialog.ask(
            self._permission_service,
            required_level,
            method_ids,
            feature_name,
            reason=reason,
            parent=parent,
        )

    def _open_debug_window(self) -> None:
        if not self._permission_service.ensure_access(
            "debug.open",
            parent=self,
            reason="打开调试面板",
        ):
            return
        if self._debug_window is None:
            self._debug_window = DebugWindow(
                clock_service=self._clock_service,
                alarm_service=self._alarm_service,
                ntp_service=self._ntp_service,
                plugin_manager=self._plugin_mgr,
                auto_engine=self._auto_engine,
                home_view=self.home_view,
                notification_service=self._notif_service,
                update_service=self._update_service,
                open_update_window=self._open_update_window,
                open_post_update_window=self._open_cached_post_update_window,
            )
        self._debug_window.show()
        self._debug_window.activateWindow()
        self._debug_window.raise_()

    def _ensure_update_window(self) -> UpdateWindow:
        if self._update_window is None:
            self._update_window = UpdateWindow(self._update_service, parent=None)
            self._update_window.launchInstallerRequested.connect(
                self._launch_update_installer_and_quit
            )
        return self._update_window

    def _open_update_window(self) -> None:
        window = self._ensure_update_window()
        info = self._update_service.latest_info
        if info is not None and self._update_service.is_update_available(info):
            window.show_available(info)
            return
        window.show_status(info)
        if info is None and not self._update_service.is_checking:
            self._update_service.check_for_updates()

    def _open_cached_post_update_window(self) -> None:
        info = self._update_service.peek_post_update_notice()
        if info is None:
            self._open_update_window()
            return
        self._ensure_update_window().show_post_update(info)

    def _show_post_update_notice_once(self) -> None:
        if self._hidden_mode or self._startup_post_update_shown:
            return
        info = self._update_service.consume_post_update_notice()
        if info is None:
            return
        self._startup_post_update_shown = True
        self._ensure_update_window().show_post_update(info)

    def _schedule_startup_update_check(self) -> None:
        self._startup_update_check_pending = True
        if not self._update_service.check_for_updates():
            self._startup_update_check_pending = False

    def _on_update_check_finished(self, info: object, has_update: bool) -> None:
        if isinstance(info, UpdateInfo):
            logger.info(
                "更新检查完成: channel={}, version={}, has_update={}",
                info.channel,
                info.version,
                has_update,
            )

        startup_check = self._startup_update_check_pending
        self._startup_update_check_pending = False
        if (
            startup_check
            and has_update
            and not self._hidden_mode
            and self._settings_service.update_startup_popup_enabled
            and not self._startup_update_popup_shown
            and not self._startup_post_update_shown
        ):
            self._startup_update_popup_shown = True
            QTimer.singleShot(0, self._open_update_window)

    def _on_update_check_failed(self, error: str) -> None:
        self._startup_update_check_pending = False
        logger.warning("更新检查失败：{}", error)

    def _launch_update_installer_and_quit(self, installer_path: str, info: object) -> None:
        path = Path(str(installer_path or "").strip())
        if not path.exists() or not path.is_file():
            InfoBar.error(
                self._i18n.t("update.failed.title", default="更新失败"),
                self._i18n.t("update.failed.missing_installer", default="安装程序文件不存在。"),
                duration=4000,
                position=InfoBarPosition.TOP_RIGHT,
                parent=self,
            )
            return

        update_info = info if isinstance(info, UpdateInfo) else self._update_service.latest_info
        if update_info is not None:
            self._update_service.prepare_post_update_notice(update_info)

        log_dir = Path(TEMP_DIR) / "updates"
        ensure_dirs(str(log_dir))
        log_path = log_dir / f"installer-{path.stem}.log"
        cmd = UpdateService.build_installer_command(path, log_path=log_path)

        try:
            subprocess.Popen(cmd, cwd=str(path.parent))
        except Exception:
            self._update_service.clear_post_update_notice()
            logger.exception("启动安装程序失败：{}", path)
            InfoBar.error(
                self._i18n.t("update.failed.title", default="更新失败"),
                self._i18n.t("update.failed.launch_installer", default="无法启动安装程序。"),
                duration=4000,
                position=InfoBarPosition.TOP_RIGHT,
                parent=self,
            )
            return

        logger.info("更新安装程序已启动：{}", path)
        QTimer.singleShot(150, self._quit)

    def _open_central_control_window(self) -> None:
        if not self._permission_service.ensure_access(
            "central.manage",
            parent=self,
            reason="打开集控管理窗口",
        ):
            return
        if self._central_control_window is None:
            self._central_control_window = CentralControlWindow(
                self._central_control_service,
                permission_service=self._permission_service,
                parent=None,
            )
        self._central_control_window.show()
        self._central_control_window.raise_()
        self._central_control_window.activateWindow()

    def _open_permission_window(self) -> None:
        if not self._permission_service.ensure_access(
            "permission.manage",
            parent=self,
            reason="打开权限管理窗口",
        ):
            return
        if self._permission_window is None:
            self._permission_window = PermissionManagementWindow(
                self._permission_service,
                parent=None,
            )
        self._permission_window.show()
        self._permission_window.raise_()
        self._permission_window.activateWindow()

    def _show_title_menu(self) -> None:
        if self._title_menu_button is None:
            return
        menu = RoundMenu(parent=self)
        menu.addActions(
            [
                Action(
                    FIF.DEVELOPER_TOOLS, "调试面板", triggered=self._open_debug_window
                ),
                Action(
                    FIF.ROBOT, "集控管理", triggered=self._open_central_control_window
                ),
                Action(
                    FIF.CERTIFICATE, "权限管理", triggered=self._open_permission_window
                ),
            ]
        )
        btn = self._title_menu_button
        popup_pos = btn.mapToGlobal(btn.rect().bottomRight())
        menu.exec(popup_pos)

    def _init_title_menu_button(self) -> None:
        if self._title_menu_button is not None:
            return
        try:
            button = FluentTitleBarButton(FIF.MORE)
        except Exception:
            button = TransparentToolButton(FIF.MORE, self.titleBar)

        button.setToolTip("更多入口")
        button.clicked.connect(self._show_title_menu)
        self._title_menu_button = button

        if hasattr(self.titleBar, "buttonLayout"):
            self.titleBar.buttonLayout.insertWidget(0, button)
        elif hasattr(self.titleBar, "hBoxLayout"):
            layout = self.titleBar.hBoxLayout
            layout.insertWidget(max(0, layout.count() - 3), button)

    def _init_tray(self):
        self._tray = QSystemTrayIcon(self)
        self._tray.setIcon(QIcon(ICON_PATH) if ICON_PATH else QIcon())
        self._notif_service.set_tray(self._tray)

        menu = RoundMenu()
        menu.addActions(
            [
                Action(
                    FIF.LINK, self._i18n.t("app.tray.show"), triggered=self.showNormal
                ),
                # Action(FIF.SYNC,  self._i18n.t("app.tray.restart"), triggered=self._restart), # 重启功能暂未实现
                Action(FIF.EMBED, self._i18n.t("app.tray.exit"), triggered=self._quit),
            ]
        )
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

    def _init_connections(self):
        """连接跨模块信号"""
        # 闹钟触发 → 自动化引擎
        self._alarm_service.alarmFired.connect(
            lambda aid: self._auto_engine.fire_event(
                TriggerType.ALARM_FIRED, alarm_id=aid
            )
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
            lambda sec: self._auto_engine.fire_event(
                TriggerType.FOCUS_DISTRACTED, distracted_sec=sec
            )
        )

        # 插件扫描完成 / 即将弹出权限对话框 → 关闭启动页面（只执行一次）
        self._splash_finished = False

        def _finish_splash_once():
            if not self._splash_finished:
                self._splash_finished = True
                self.splash.finish()

        self._plugin_mgr.scanCompleted.connect(_finish_splash_once)
        # 兜底：即使插件扫描耗时较长，也不要让启动页长时间阻塞主界面显示。
        QTimer.singleShot(650, _finish_splash_once)
        # 权限询问已改为常驻 Toast（WindowStaysOnTopHint），无需提前关闭启动界面

        def _refresh_announcements_once():
            if self._startup_announcements_requested:
                return
            self._startup_announcements_requested = True
            QTimer.singleShot(200, self._remote_resources.refresh_announcements)

        self._plugin_mgr.scanCompleted.connect(_refresh_announcements_once)

        def _startup_updates_once():
            if self._startup_update_sequence_requested:
                return
            self._startup_update_sequence_requested = True
            QTimer.singleShot(280, self._show_post_update_notice_once)
            if self._settings_service.update_auto_check_enabled:
                QTimer.singleShot(520, self._schedule_startup_update_check)

        self._plugin_mgr.scanCompleted.connect(_startup_updates_once)

        # 插件加载错误 → 通知
        self._plugin_mgr.pluginError.connect(
            lambda pid, err: self._notif_service.show(
                self._i18n.t("app.plugin.load_error"), f"{pid}: {err}"
            )
        )

        self._remote_resources.announcementsUpdated.connect(
            self._on_announcements_updated
        )
        self._remote_resources.announcementsFailed.connect(
            lambda err: logger.warning("公告拉取失败：{}", err)
        )
        self._update_service.checkFinished.connect(self._on_update_check_finished)
        self._update_service.checkFailed.connect(self._on_update_check_failed)

        # 插件扫描完成 → 刷新自动化视图的插件动作/触发器列表
        self._plugin_mgr.scanCompleted.connect(
            lambda: self.automation_view.refresh_plugin_actions(self._plugin_api)
        )

        # APP_STARTUP 事件（延迟 600ms，确保 UI 已完成初始化）
        from PySide6.QtCore import QTimer as _QTimer

        _QTimer.singleShot(600, lambda: self._emit_app_event("startup"))

        # ── 首页推荐服务注入 ───────────────────────────────────────── #
        # 首页视图依赖注入：导航切揢回调
        _FEATURE_TO_VIEW_OBJ = {
            "world_time": self.world_time_view,
            "alarm": self.alarm_view,
            "timer": self.timer_view,
            "stopwatch": self.stopwatch_view,
            "focus": self.focus_view,
            "plugin": self.plugin_view,
            "automation": self.automation_view,
            "home": self.home_view,
        }

        def _navigate(view_key: str):
            view = _FEATURE_TO_VIEW_OBJ.get(view_key)
            if view:
                self.showNormal()
                self.activateWindow()
                self.switchTo(view)

        self.home_view.set_services(
            timer_view=self.timer_view,
            stopwatch_view=self.stopwatch_view,
            focus_service=self._focus_service,
            alarm_service=self._alarm_service,
            alarm_store=self._alarm_store,
            clock_service=self._clock_service,
            plugin_manager=self._plugin_mgr,
            notification_service=self._notif_service,
            resource_service=self._remote_resources,
            update_service=self._update_service,
            navigate_to=_navigate,
            open_update_window=self._open_update_window,
        )

        # 连接 EventBus → 推荐服务（会话轨迹记录）
        try:
            from app.events import EventBus, EventType

            EventBus.subscribe(
                EventType.TIMER_STARTED,
                lambda **_: self._reco.on_session_start(FEATURE_TIMER),
            )
            EventBus.subscribe(
                EventType.TIMER_DONE,
                lambda **_: self._reco.on_session_end(FEATURE_TIMER),
            )
            EventBus.subscribe(
                EventType.FOCUS_STARTED,
                lambda **_: self._reco.on_session_start(FEATURE_FOCUS),
            )
            EventBus.subscribe(
                EventType.FOCUS_ENDED,
                lambda **_: self._reco.on_session_end(FEATURE_FOCUS),
            )
            EventBus.subscribe(
                EventType.ALARM_FIRED,
                lambda **_: self._reco.on_session_start(FEATURE_ALARM),
            )
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

    def _on_announcements_updated(self, announcements) -> None:
        existing_ids = {
            item.stable_id
            for item in self._pending_error_announcements
            if getattr(item, "stable_id", "")
        }
        for announcement in announcements or []:
            ann_id = getattr(announcement, "stable_id", "")
            if not ann_id or getattr(announcement, "level", "") != "error":
                continue
            if ann_id in self._shown_error_announcement_ids or ann_id in existing_ids:
                continue
            if self._remote_resources.is_announcement_popup_muted(ann_id):
                continue
            self._pending_error_announcements.append(announcement)
            existing_ids.add(ann_id)

        if self._pending_error_announcements and not self._hidden_mode:
            QTimer.singleShot(0, self._show_next_error_announcement_popup)

    def _show_next_error_announcement_popup(self) -> None:
        if self._hidden_mode or self._showing_error_announcement_popup:
            return
        if not self._pending_error_announcements:
            return

        announcement = self._pending_error_announcements.pop(0)
        ann_id = getattr(announcement, "stable_id", "")
        if not ann_id:
            QTimer.singleShot(0, self._show_next_error_announcement_popup)
            return
        if ann_id in self._shown_error_announcement_ids:
            QTimer.singleShot(0, self._show_next_error_announcement_popup)
            return
        if self._remote_resources.is_announcement_popup_muted(ann_id):
            self._shown_error_announcement_ids.add(ann_id)
            QTimer.singleShot(0, self._show_next_error_announcement_popup)
            return

        self._showing_error_announcement_popup = True
        try:
            self.showNormal()
            self.raise_()
            self.activateWindow()
        except Exception:
            pass

        dialog = AnnouncementPopupDialog(announcement, self)
        dialog.exec()
        if dialog.mute_requested:
            self._remote_resources.mute_announcement_popup(ann_id)

        self._shown_error_announcement_ids.add(ann_id)
        self._showing_error_announcement_popup = False
        QTimer.singleShot(0, self._show_next_error_announcement_popup)

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
            id(self.home_view): None,  # 首页本身不记录
            id(self.world_time_view): FEATURE_WORLD_TIME,
            id(self.alarm_view): FEATURE_ALARM,
            id(self.timer_view): FEATURE_TIMER,
            id(self.stopwatch_view): FEATURE_STOPWATCH,
            id(self.focus_view): FEATURE_FOCUS,
            id(self.plugin_view): FEATURE_PLUGIN,
            id(self.automation_view): FEATURE_AUTOMATION,
        }
        feat = _VIEW_FEATURE_MAP.get(id(widget))
        if feat is not None:
            reco.on_view_shown(feat)

    def _activate_main_window(self) -> None:
        self.showNormal()
        self.activateWindow()
        self.raise_()

    def _ensure_splash_closed(self) -> None:
        """处理外部唤起前确保启动遮罩已关闭，避免拦截主窗口点击。"""
        splash = getattr(self, "splash", None)
        if splash is None:
            return
        try:
            if splash.isVisible():
                splash.finish()
        except Exception:
            pass

    def _resolve_manifest_text(self, value: Any, default: str = "") -> str:
        if isinstance(value, str):
            return value.strip() or default
        if isinstance(value, dict):
            try:
                resolved = self._i18n.resolve_text(value, default)
                return str(resolved or default).strip()
            except Exception:
                return default
        return default

    @staticmethod
    def _normalize_zip_member_name(value: str) -> str:
        text = str(value or "").replace("\\", "/").strip()
        if not text:
            return ""
        while text.startswith("./"):
            text = text[2:]
        return text.strip("/")

    def _resolve_plugin_icon_member(
        self,
        manifest: dict[str, Any],
        manifest_member_name: str,
        archive_members: list[str],
    ) -> str:
        member_names = [
            item for item in archive_members if item and not item.endswith("/")
        ]
        if not member_names:
            return ""

        normalized_map = {
            self._normalize_zip_member_name(
                item
            ).lower(): self._normalize_zip_member_name(item)
            for item in member_names
            if self._normalize_zip_member_name(item)
        }

        manifest_member = self._normalize_zip_member_name(manifest_member_name)
        manifest_parent = (
            PurePosixPath(manifest_member).parent.as_posix() if manifest_member else ""
        )
        if manifest_parent == ".":
            manifest_parent = ""

        candidates: list[str] = []

        def add_candidate(path_value: str) -> None:
            normalized = self._normalize_zip_member_name(path_value)
            if normalized and normalized not in candidates:
                candidates.append(normalized)

        def add_with_manifest_parent(path_value: str) -> None:
            normalized = self._normalize_zip_member_name(path_value)
            if not normalized:
                return
            if manifest_parent and not normalized.startswith(f"{manifest_parent}/"):
                add_candidate(f"{manifest_parent}/{normalized}")
            add_candidate(normalized)

        for icon_key in ("icon", "icon_path", "logo"):
            icon_path = manifest.get(icon_key)
            if isinstance(icon_path, str) and icon_path.strip():
                add_with_manifest_parent(icon_path)

        if not candidates:
            for fallback_name in (
                "assets/icon.png",
                "assets/icon.jpg",
                "assets/icon.jpeg",
                "assets/icon.webp",
                "icon.png",
                "icon.jpg",
                "icon.jpeg",
                "logo.png",
                "logo.jpg",
            ):
                add_with_manifest_parent(fallback_name)

        for candidate in candidates:
            hit = normalized_map.get(candidate.lower())
            if hit:
                return hit
        return ""

    def _inspect_plugin_package_info(self, file_path: Path) -> dict[str, Any]:
        info = {
            "name": file_path.stem,
            "id": "",
            "version": "",
            "description": "",
            "author": "",
            "plugin_type": "feature",
            "homepage": "",
            "icon_name": "",
            "icon_bytes": b"",
        }
        try:
            with zipfile.ZipFile(file_path, "r") as zf:
                candidates = [
                    name
                    for name in zf.namelist()
                    if name.endswith("plugin.json") and not name.endswith("/")
                ]
                if not candidates:
                    return info
                manifest_name = sorted(candidates, key=lambda item: item.count("/"))[0]
                manifest = json.loads(zf.read(manifest_name).decode("utf-8"))

                icon_member = self._resolve_plugin_icon_member(
                    manifest, manifest_name, zf.namelist()
                )
                if icon_member:
                    icon_bytes = zf.read(icon_member)
                    if icon_bytes:
                        info["icon_name"] = PurePosixPath(icon_member).name
                        info["icon_bytes"] = icon_bytes

            plugin_id = str(manifest.get("id") or "").strip()
            version = str(manifest.get("version") or "").strip()
            author = str(manifest.get("author") or "").strip()
            plugin_type = (
                str(manifest.get("plugin_type") or "feature").strip() or "feature"
            )
            homepage = str(manifest.get("homepage") or "").strip()

            name = self._resolve_manifest_text(
                manifest.get("name_i18n"),
                self._resolve_manifest_text(
                    manifest.get("name"), plugin_id or info["name"]
                ),
            )
            description = self._resolve_manifest_text(
                manifest.get("description_i18n"),
                self._resolve_manifest_text(manifest.get("description"), ""),
            )

            info["name"] = name or info["name"]
            info["id"] = plugin_id
            info["version"] = version
            info["description"] = description
            info["author"] = author
            info["plugin_type"] = plugin_type
            info["homepage"] = homepage
            return info
        except Exception:
            return info

    def _inspect_plugin_package_name(self, file_path: Path) -> str:
        return self._inspect_plugin_package_info(file_path).get("name", file_path.stem)

    def _read_layout_widget_configs(self, file_path: Path) -> list[dict[str, Any]]:
        raw = json.loads(file_path.read_text(encoding="utf-8"))
        widgets_data = raw.get("widgets", []) if isinstance(raw, dict) else raw
        if not isinstance(widgets_data, list):
            raise ValueError(
                self._i18n.t(
                    "layout.open.read.invalid_widgets",
                    default="布局文件缺少组件列表",
                )
            )

        configs: list[dict[str, Any]] = []
        for idx, item in enumerate(widgets_data, start=1):
            if not isinstance(item, dict):
                raise ValueError(
                    self._i18n.t(
                        "layout.open.read.invalid_widget_item",
                        default="布局文件中第 {idx} 个组件配置无效",
                        idx=idx,
                    )
                )
            configs.append(WidgetConfig.from_dict(dict(item)).to_dict())
        return configs

    def _apply_layout_file_to_fullscreen(
        self,
        file_path: Path,
        *,
        parent=None,
        context: dict[str, Any] | None = None,
    ) -> bool:
        try:
            configs = self._read_layout_widget_configs(file_path)
        except Exception as exc:
            InfoBar.error(
                self._i18n.t("layout.open.apply.failed.title", default="布局导入失败"),
                str(exc),
                duration=4000,
                position=InfoBarPosition.TOP_RIGHT,
                parent=self,
            )
            return False

        zone_options = list(self._world_zone_service.list_zone_options())
        if not zone_options:
            InfoBar.warning(
                self._i18n.t(
                    "layout.open.apply.no_canvas.title", default="没有可用画布"
                ),
                self._i18n.t(
                    "layout.open.apply.no_canvas.content",
                    default="当前未配置世界时钟画布，无法应用布局。",
                ),
                duration=3000,
                position=InfoBarPosition.TOP_RIGHT,
                parent=self,
            )
            return False

        labels = [
            str(
                opt.get("display_name")
                or opt.get("label")
                or opt.get("timezone")
                or opt.get("id")
                or self._i18n.t(
                    "layout.open.apply.canvas.unnamed", default="未命名画布"
                )
            )
            for opt in zone_options
        ]
        selected_index = -1
        if isinstance(context, dict):
            target_zone_id = str(context.get("target_zone_id") or "").strip()
            if target_zone_id:
                for idx, option in enumerate(zone_options):
                    if str(option.get("id") or "").strip() == target_zone_id:
                        selected_index = idx
                        break

        if selected_index < 0:
            selected, ok = QInputDialog.getItem(
                self,
                self._i18n.t(
                    "layout.open.apply.select_canvas.title", default="选择目标画布"
                ),
                self._i18n.t(
                    "layout.open.apply.select_canvas.content",
                    default="将布局应用到哪个全屏时钟画布：",
                ),
                labels,
                0,
                False,
            )
            if not ok:
                return False
            selected_index = labels.index(selected)

        target_zone_id = str(zone_options[selected_index].get("id") or "")
        if not target_zone_id:
            return False

        self._plugin_api.apply_canvas_layout(target_zone_id, configs)
        opened = self.world_time_view.open_fullscreen_by_zone_id(target_zone_id)
        if not opened:
            self.switchTo(self.world_time_view)

        InfoBar.success(
            self._i18n.t("layout.open.apply.success.title", default="已应用布局"),
            self._i18n.t(
                "layout.open.apply.success.content",
                default="布局已应用到 {target}",
                target=labels[selected_index],
            ),
            duration=3000,
            position=InfoBarPosition.TOP_RIGHT,
            parent=self,
        )
        return True

    def _collect_layout_open_actions(self) -> list[dict[str, Any]]:
        zone_options = list(self._world_zone_service.list_zone_options())
        wizard_options: list[dict[str, Any]] = []
        for opt in zone_options:
            zone_id = str(opt.get("id") or "").strip()
            if not zone_id:
                continue
            label = str(
                opt.get("display_name")
                or opt.get("label")
                or opt.get("timezone")
                or zone_id
            )
            detail = str(opt.get("timezone") or "")
            wizard_options.append(
                {
                    "value": zone_id,
                    "label": label,
                    "description": detail,
                }
            )

        actions: list[dict[str, Any]] = [
            {
                "action_id": "builtin.apply_fullscreen",
                "plugin_id": "__builtin__",
                "title": self._i18n.t(
                    "layout.open.action.builtin.apply_fullscreen.title",
                    default="应用到全屏时钟",
                ),
                "description": self._i18n.t(
                    "layout.open.action.builtin.apply_fullscreen.content",
                    default="选择目标画布并立即应用布局",
                ),
                "content": self._i18n.t(
                    "layout.open.action.builtin.apply_fullscreen.content",
                    default="选择目标画布并立即应用布局",
                ),
                "breadcrumb": [
                    self._i18n.t(
                        "layout.open.action.builtin.breadcrumb.builtin", default="内置"
                    ),
                    self._i18n.t(
                        "layout.open.action.builtin.breadcrumb.fullscreen",
                        default="全屏时钟",
                    ),
                ],
                "wizard_pages": [
                    {
                        "type": "select",
                        "title": self._i18n.t(
                            "layout.open.action.builtin.step.select_canvas.title",
                            default="选择目标全屏时钟",
                        ),
                        "description": self._i18n.t(
                            "layout.open.action.builtin.step.select_canvas.description",
                            default="请选择要应用布局的全屏时钟画布。",
                        ),
                        "field": "target_zone_id",
                        "required": True,
                        "empty_text": self._i18n.t(
                            "layout.open.action.builtin.step.select_canvas.empty_text",
                            default="当前没有可用画布，请先在世界时间中创建画布。",
                        ),
                        "options": wizard_options,
                    }
                ],
                "handler": self._apply_layout_file_to_fullscreen,
                "order": -100,
            }
        ]
        for action in self._layout_file_open_service.list_actions():
            handler = action.get("handler")
            if not callable(handler):
                continue
            actions.append(action)
        return actions

    def _import_plugin_package(self, file_path: Path) -> None:
        ok, message = self._plugin_mgr.import_plugin(file_path)
        if ok:
            self._plugin_mgr.discover_and_load()
            self.switchTo(self.plugin_view)
            InfoBar.success(
                "导入成功",
                message,
                duration=3000,
                position=InfoBarPosition.TOP_RIGHT,
                parent=self,
            )
            return

        InfoBar.error(
            "导入失败",
            message,
            duration=4000,
            position=InfoBarPosition.TOP_RIGHT,
            parent=self,
        )

    def _on_plugin_import_requested(self, file_path: str) -> None:
        path = Path(str(file_path or "").strip())
        if not path.exists() or not path.is_file():
            InfoBar.warning(
                "文件不存在",
                str(path),
                duration=3000,
                position=InfoBarPosition.TOP_RIGHT,
                parent=self,
            )
            return
        self._import_plugin_package(path)

    def _handle_open_plugin_package(self, file_path: Path) -> None:
        package_info = self._inspect_plugin_package_info(file_path)
        if self._plugin_open_window is None:
            self._plugin_open_window = PluginFileOpenWindow(parent=None)
            self._plugin_open_window.importRequested.connect(
                self._on_plugin_import_requested
            )
        self._plugin_open_window.open_package(file_path, package_info)

    def _handle_open_config_package(self, file_path: Path) -> None:
        window = self.settings_view.open_migration_window(
            import_file_path=file_path,
            jump_to_import=True,
        )
        if window is not None:
            self.switchTo(self.settings_view)

    def _handle_open_layout_file(self, file_path: Path) -> None:
        actions = self._collect_layout_open_actions()
        if not actions:
            InfoBar.warning(
                self._i18n.t("layout.open.no_actions.title", default="无法打开布局"),
                self._i18n.t(
                    "layout.open.no_actions.content",
                    default="当前没有可用的布局打开方式。",
                ),
                duration=3000,
                position=InfoBarPosition.TOP_RIGHT,
                parent=self,
            )
            return

        if self._layout_open_window is None:
            self._layout_open_window = LayoutFileOpenWindow(parent=None)
            self._layout_open_window.actionRequested.connect(
                self._on_layout_open_action_requested
            )
        self._layout_open_window.open_layout(file_path, actions)

    def _on_layout_open_action_requested(
        self,
        file_path: str,
        action_id: str,
        context: Any = None,
    ) -> None:
        path = Path(str(file_path or "").strip())
        target_action = next(
            (
                item
                for item in self._collect_layout_open_actions()
                if str(item.get("action_id") or "") == action_id
            ),
            None,
        )
        if target_action is None:
            InfoBar.warning(
                self._i18n.t(
                    "layout.open.action.not_found.title", default="操作不存在"
                ),
                self._i18n.t(
                    "layout.open.action.not_found.content",
                    default="所选布局处理方式已失效，请重试。",
                ),
                duration=3000,
                position=InfoBarPosition.TOP_RIGHT,
                parent=self,
            )
            return

        handler: Callable[[Path], Any] = target_action.get("handler")  # type: ignore[assignment]
        if not callable(handler):
            return

        context_payload = context if isinstance(context, dict) else {}
        call_kwargs: dict[str, Any] = {"parent": self}
        try:
            signature = inspect.signature(handler)
            has_context = "context" in signature.parameters or any(
                param.kind == inspect.Parameter.VAR_KEYWORD
                for param in signature.parameters.values()
            )
            if has_context:
                call_kwargs["context"] = context_payload
        except Exception:
            call_kwargs["context"] = context_payload

        try:
            handler(path, **call_kwargs)
        except Exception:
            logger.exception(
                "处理布局文件失败: action_id={}, file={}",
                target_action.get("action_id"),
                path,
            )
            InfoBar.error(
                self._i18n.t(
                    "layout.open.action.execute.failed.title", default="处理失败"
                ),
                self._i18n.t(
                    "layout.open.action.execute.failed.content",
                    default="执行所选布局处理方式时发生异常。",
                ),
                duration=4000,
                position=InfoBarPosition.TOP_RIGHT,
                parent=self,
            )

    def _handle_open_file_by_type(
        self,
        file_path: Path,
        file_extension: str,
        actions: List[Dict[str, Any]],
    ) -> None:
        """处理通过文件类型打开服务打开的文件。"""
        if not actions:
            InfoBar.warning(
                self._i18n.t("filetype.open.no_actions.title", default="无法打开文件"),
                self._i18n.t(
                    "filetype.open.no_actions.content",
                    default="当前没有可用的打开方式。",
                ),
                duration=3000,
                position=InfoBarPosition.TOP_RIGHT,
                parent=self,
            )
            return

        if self._file_type_open_window is None:
            self._file_type_open_window = FileTypeOpenWindow(parent=None)
            self._file_type_open_window.actionRequested.connect(
                self._on_file_type_open_action_requested
            )
        self._file_type_open_window.open_file(file_path, file_extension, actions)

    def _on_file_type_open_action_requested(
        self,
        file_path: str,
        action_id: str,
        context: Any = None,
    ) -> None:
        """处理文件类型打开请求。"""
        path = Path(str(file_path or "").strip())
        handler = self._file_type_open_service.get_handler(action_id)
        if not callable(handler):
            InfoBar.warning(
                self._i18n.t(
                    "filetype.open.action.not_found.title", default="操作不存在"
                ),
                self._i18n.t(
                    "filetype.open.action.not_found.content",
                    default="所选处理方式已失效，请重试。",
                ),
                duration=3000,
                position=InfoBarPosition.TOP_RIGHT,
                parent=self,
            )
            return

        context_payload = context if isinstance(context, dict) else {}
        call_kwargs: dict[str, Any] = {"parent": self}
        try:
            signature = inspect.signature(handler)
            has_context = "context" in signature.parameters or any(
                param.kind == inspect.Parameter.VAR_KEYWORD
                for param in signature.parameters.values()
            )
            if has_context:
                call_kwargs["context"] = context_payload
        except Exception:
            call_kwargs["context"] = context_payload

        try:
            handler(path, **call_kwargs)
        except Exception:
            logger.exception("处理文件失败: action_id={}, file={}", action_id, path)
            InfoBar.error(
                self._i18n.t(
                    "filetype.open.action.execute.failed.title", default="处理失败"
                ),
                self._i18n.t(
                    "filetype.open.action.execute.failed.content",
                    default="执行所选处理方式时发生异常。",
                ),
                duration=4000,
                position=InfoBarPosition.TOP_RIGHT,
                parent=self,
            )

    def handle_open_file(self, file_path: str) -> None:
        self._ensure_splash_closed()

        text = str(file_path or "").strip().strip('"')
        if not text:
            return

        path = Path(text).expanduser()
        if not path.exists() or not path.is_file():
            InfoBar.warning(
                "文件不存在",
                str(path),
                duration=3000,
                position=InfoBarPosition.TOP_RIGHT,
                parent=self,
            )
            return

        suffix = path.suffix.lower()
        self._activate_main_window()

        if suffix == PLUGIN_PACKAGE_EXTENSION:
            self._handle_open_plugin_package(path)
            return
        if suffix == ".ltcconfig":
            self._handle_open_config_package(path)
            return
        if suffix == ".ltlayout":
            self._handle_open_layout_file(path)
            return

        # 尝试通过文件类型打开服务处理
        actions = self._file_type_open_service.get_actions_for_extension(suffix)
        if actions:
            self._handle_open_file_by_type(path, suffix, actions)
            return

        InfoBar.warning(
            "不支持的文件类型",
            f"无法通过小树时钟打开该文件：{path.name}",
            duration=3000,
            position=InfoBarPosition.TOP_RIGHT,
            parent=self,
        )

    def handle_url(self, url: str) -> None:
        """
        解析并导航到 URL 指定的视图。

        支持格式：
        - ``ltclock://open/<view_key>``
        - ``ltclock://fullscreen/<zone_id>``
        """
        self._ensure_splash_closed()

        target = parse_url_target(url)
        if not target:
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

        if target.action == "fullscreen":
            self._activate_main_window()
            if not self.world_time_view.open_fullscreen_by_zone_id(target.zone_id):
                logger.warning("URL 全屏目标不存在：{}", target.zone_id)
                InfoBar.warning(
                    title=self._i18n.t("app.url.invalid_title"),
                    content=self._i18n.t(
                        "app.url.fullscreen_not_found",
                        default="未找到对应的全屏时钟：{zone_id}",
                        zone_id=target.zone_id,
                    ),
                    isClosable=True,
                    position=InfoBarPosition.TOP_RIGHT,
                    duration=3000,
                    parent=self,
                )
                return
            logger.info("URL 导航 → {} (fullscreen:{})", url, target.zone_id)
            return

        object_name = target.object_name
        if not object_name:
            logger.warning("URL 未解析到有效视图：{}", url)
            return

        # 调试窗口单独弹出，不切换主窗口
        if object_name == "debugView":
            self._open_debug_window()
            logger.info("URL 导航 → 调试窗口（带权限验证）")
            return

        view = self._url_view_map.get(object_name)
        if view is None:
            logger.warning("URL 对应视图不存在：{}", object_name)
            return

        # 唤起窗口并切换到目标视图
        self._activate_main_window()
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
            self.raise_()
            self.activateWindow()
            self._emit_app_event("shown")

    def _restart(self):
        # 使用内部参数避免新进程在旧进程退出前触发重复启动弹窗
        restart_args = [arg for arg in sys.argv[1:] if arg != "--restarting"]
        restart_cmd = [sys.executable] + restart_args + ["--restarting"]
        try:
            subprocess.Popen(restart_cmd)
        except Exception:
            logger.exception("重启失败：无法拉起新进程")
            return

        logger.info("已发起重启，正在退出当前实例")
        self._quit()

    def _quit(self):
        self._auto_engine.fire_event(TriggerType.APP_SHUTDOWN)
        self._emit_app_event("shutdown")
        try:
            self._reco.flush_pending_save()
        except Exception:
            logger.exception("退出时刷新推荐统计失败")
        try:
            self._update_service.shutdown()
        except Exception:
            logger.exception("退出时清理更新线程失败")
        try:
            self._remote_resources.shutdown()
        except Exception:
            logger.exception("退出时清理远程资源线程失败")
        self._plugin_mgr.unload_all()
        self._tray.hide()
        logger.info("{} 已退出", APP_NAME)
        QApplication.quit()

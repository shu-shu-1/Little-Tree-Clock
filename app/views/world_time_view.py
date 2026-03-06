"""世界时间视图"""
from __future__ import annotations

from datetime import datetime
from PySide6.QtCore import Qt, Slot, QPoint, QSize
from PySide6.QtGui import QKeyEvent, QColor, QPalette
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QWidget,
    QFrame, QSizePolicy, QPushButton,
)
from qfluentwidgets import (
    SmoothScrollArea, FluentIcon as FIF, PushButton, Theme,
    CardWidget, BodyLabel, TitleLabel, CaptionLabel, SubtitleLabel,
    ComboBox, RoundMenu, Action,
    TransparentToolButton,
)

from app.constants import PRESET_TIMEZONES, IS_BETA
from app.widgets.watermark import WatermarkOverlay
from app.models.world_zone import WorldZone, WorldZoneStore
from app.services.clock_service import ClockService
from app.services.i18n_service import I18nService
from app.services.settings_service import SettingsService
from app.utils.time_utils import now_in_zone, format_time, format_date, utc_offset_str


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


class FullscreenClockWindow(QWidget):
    """全屏可编辑小组件画布窗口。

    - Esc / 右上角 ✕ ：退出全屏
    - Tab / 右上角"编辑"按钮：切换编辑模式
    - 编辑模式：显示网格线，组件可拖拽，右键编辑/删除，可添加组件
    """

    def __init__(self, zone: WorldZone, clock_service: ClockService | None = None,
                 plugin_manager=None, notification_service=None, parent=None):
        super().__init__(parent)
        self._zone          = zone
        self._clock_service = clock_service
        self._notif_service = notification_service
        self._i18n = I18nService.instance()

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(8, 8, 8))
        self.setPalette(palette)

        # ── 画布（占满全屏）──
        from app.widgets.canvas import WidgetCanvas
        services = {
            "timezone":            zone.timezone,
            "clock_service":       clock_service,
            "notification_service": notification_service,
        }
        self._canvas = WidgetCanvas(zone.id, services, plugin_manager, self)

        # ── 顶栏覆盖层 ──
        self._topbar = QFrame(self)
        self._topbar.setObjectName("fsTopBar")
        self._topbar.setStyleSheet(
            "QFrame#fsTopBar{background:rgba(0,0,0,100);"
            "border-bottom:1px solid rgba(255,255,255,25);}"
        )
        tb = QHBoxLayout(self._topbar)
        tb.setContentsMargins(16, 0, 12, 0)
        tb.setSpacing(6)

        # 城市名
        self._zone_lbl = SubtitleLabel(zone.label or zone.timezone)
        self._zone_lbl.setStyleSheet(
            "color:rgba(255,255,255,160); background:transparent;"
        )

        # 编辑切换按钮（始终深色背景，强制用 Theme.DARK 图标保证白色）
        self._edit_btn = QPushButton(
            FIF.EDIT.icon(Theme.DARK),
            self._i18n.t("world_time.fs.edit"),
        )
        self._edit_btn.setIconSize(QSize(16, 16))
        self._edit_btn.setStyleSheet(
            "QPushButton{"
            "color:rgba(255,255,255,200);"
            "background:rgba(255,255,255,15);"
            "border:1px solid rgba(255,255,255,50);"
            "border-radius:8px;"
            "padding:5px 14px;"
            "font-size:13px;}"
            "QPushButton:hover{"
            "background:rgba(255,255,255,30);"
            "border-color:rgba(255,255,255,80);}"
            "QPushButton:pressed{"
            "background:rgba(255,255,255,18);}"
        )
        self._edit_btn.clicked.connect(self._toggle_edit)

        # 关闭按钮
        self._close_btn = QPushButton(FIF.CLOSE.icon(Theme.DARK), "")
        self._close_btn.setIconSize(QSize(14, 14))
        self._close_btn.setFixedSize(36, 36)
        self._close_btn.setStyleSheet(
            "QPushButton{"
            "background:rgba(255,255,255,8);"
            "border:1px solid rgba(255,255,255,25);"
            "border-radius:8px;}"
            "QPushButton:hover{"
            "background:rgba(196,43,43,200);"
            "border-color:transparent;}"
            "QPushButton:pressed{"
            "background:rgba(160,30,30,220);}"
        )
        self._close_btn.clicked.connect(self.close)
        self._close_btn.setToolTip(self._i18n.t("world_time.fs.close"))

        tb.addWidget(self._zone_lbl)
        tb.addStretch()
        # ── 插件注入的顶栏按钮（在编辑/关闭钮之前）──
        if plugin_manager is not None:
            try:
                for _btn in plugin_manager.collect_canvas_topbar_buttons(zone.id):
                    tb.addWidget(_btn)
            except Exception:
                pass
        tb.addWidget(self._edit_btn)
        tb.addWidget(self._close_btn)

        # 底部提示
        self._hint_lbl = CaptionLabel(self._i18n.t("world_time.fs.hint"))
        self._hint_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint_lbl.setStyleSheet(
            "color:rgba(255,255,255,50); background:transparent;"
        )
        self._hint_lbl.setParent(self)

        # 测试版水印
        if IS_BETA:
            self._watermark = WatermarkOverlay(self)
            self._watermark.setGeometry(self.rect())
            _wm_settings = SettingsService.instance()
            self._watermark.setVisible(_wm_settings.watermark_worldtime_visible)
            self._watermark.raise_()
            _wm_settings.changed.connect(self._apply_watermark_visibility)
        # topbar 和提示始终在水印之上
        self._topbar.raise_()
        self._hint_lbl.raise_()

        # 连接时钟
        if clock_service:
            clock_service.secondTick.connect(self._canvas.refresh_all)

    # ------------------------------------------------------------------ #

    def _toggle_edit(self) -> None:
        if self._canvas.edit_mode:
            self._canvas.leave_edit_mode()
            self._edit_btn.setText(self._i18n.t("world_time.fs.edit"))
            self._edit_btn.setIcon(FIF.EDIT.icon(Theme.DARK))
            self._hint_lbl.show()
        else:
            self._canvas.enter_edit_mode()
            self._edit_btn.setText(self._i18n.t("world_time.fs.done"))
            self._edit_btn.setIcon(FIF.ACCEPT.icon(Theme.DARK))
            self._hint_lbl.hide()  # 编辑模式下提示隐藏，避免遇层

    # ------------------------------------------------------------------ #

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            if self._canvas.edit_mode:
                self._canvas.leave_edit_mode()
                self._edit_btn.setText(self._i18n.t("world_time.fs.edit"))
                self._edit_btn.setIcon(FIF.EDIT.icon(Theme.DARK))
            else:
                self.close()
        elif event.key() == Qt.Key.Key_Tab:
            self._toggle_edit()
        else:
            super().keyPressEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        w, h = self.width(), self.height()
        self._canvas.setGeometry(0, 0, w, h)
        topbar_h = 52
        # 水印先铺满，再把功能控件置顶
        if IS_BETA and hasattr(self, "_watermark"):
            self._watermark.setGeometry(self.rect())
            self._watermark.raise_()
        self._topbar.setGeometry(0, 0, w, topbar_h)
        self._topbar.raise_()
        # 提示标签放在画布工具栏上方，避免遇层
        hint_h = 24
        toolbar_h = 52
        self._hint_lbl.setGeometry(0, h - toolbar_h - hint_h - 4, w, hint_h)
        self._hint_lbl.raise_()

    def _apply_watermark_visibility(self) -> None:
        """根据设置刷新世界时间视图水印可见性"""
        if IS_BETA and hasattr(self, "_watermark"):
            visible = SettingsService.instance().watermark_worldtime_visible
            self._watermark.setVisible(visible)
            if visible:
                self._watermark.raise_()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        try:
            from app.events import EventBus, EventType
            EventBus.emit(EventType.FULLSCREEN_OPENED, zone_id=self._zone.id)
            EventBus.subscribe(EventType.WIDGET_LAYOUT_CHANGED, self._on_layout_changed)
        except Exception:
            pass

    def _on_layout_changed(self, zone_id: str = "", **_) -> None:
        """响应插件的 apply_canvas_layout 调用，仅当 zone_id 匹配时重新加载画布布局。"""
        if zone_id and zone_id != self._zone.id:
            return
        try:
            self._canvas.reload_layout()
        except Exception:
            pass

    def closeEvent(self, event) -> None:
        try:
            from app.events import EventBus, EventType
            EventBus.emit(EventType.FULLSCREEN_CLOSED, zone_id=self._zone.id)
            EventBus.unsubscribe(EventType.WIDGET_LAYOUT_CHANGED, self._on_layout_changed)
        except Exception:
            pass
        if self._clock_service:
            try:
                self._clock_service.secondTick.disconnect(self._canvas.refresh_all)
            except Exception:
                pass
        super().closeEvent(event)


class ZoneCard(CardWidget):
    """单张时区卡片"""

    def __init__(self, zone: WorldZone, on_remove, clock_service: ClockService | None = None,
                 plugin_manager=None, notification_service=None, parent=None):
        super().__init__(parent)
        self.zone_id         = zone.id
        self._zone           = zone
        self._on_remove      = on_remove
        self._clock_service  = clock_service
        self._plugin_mgr     = plugin_manager
        self._notif_service  = notification_service
        self._fs_window: FullscreenClockWindow | None = None
        self._i18n = I18nService.instance()

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(2)

        # 城市/标签行
        top  = QHBoxLayout()
        self.label_lbl  = BodyLabel(zone.label or zone.timezone)
        self.offset_lbl = CaptionLabel("")
        self.offset_lbl.setObjectName("offsetLabel")
        top.addWidget(self.label_lbl)
        top.addStretch()
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

    def _open_fullscreen(self) -> None:
        """打开全屏小组件画布窗口。"""
        if self._fs_window is not None and not self._fs_window.isHidden():
            self._fs_window.raise_()
            self._fs_window.activateWindow()
            return
        self._fs_window = FullscreenClockWindow(
            self._zone, self._clock_service, self._plugin_mgr,
            notification_service=self._notif_service,
        )
        self._fs_window.showFullScreen()

    def _show_menu(self) -> None:
        menu = RoundMenu(parent=self)
        menu.addAction(Action(FIF.FULL_SCREEN, self._i18n.t("world_time.fullscreen"), triggered=self._open_fullscreen))
        menu.addSeparator()
        menu.addAction(Action(FIF.DELETE, self._i18n.t("common.delete"), triggered=lambda: self._on_remove(self.zone_id)))
        # 菜单弹出位置：按钮右下角对齐
        btn_pos = self._menu_btn.mapToGlobal(QPoint(self._menu_btn.width(), self._menu_btn.height()))
        menu.exec(btn_pos)

    def refresh(self, zone: WorldZone) -> None:
        self._zone = zone
        dt = now_in_zone(zone.timezone)
        self.time_lbl.setText(format_time(dt))
        self.date_lbl.setText(format_date(dt))
        self.offset_lbl.setText(utc_offset_str(dt))
        self.label_lbl.setText(zone.label or zone.timezone)
        self.diff_lbl.setText(_local_offset_diff_str(zone.timezone))


class WorldTimeView(SmoothScrollArea):
    """世界时间主视图"""

    def __init__(self, clock_service: ClockService, plugin_manager=None,
                 notification_service=None, parent=None):
        super().__init__(parent)
        self.setObjectName("worldTimeView")
        self._clock_service = clock_service
        self._plugin_mgr    = plugin_manager
        self._notif_service = notification_service
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
        self._cards_layout = QVBoxLayout()
        self._cards_layout.setSpacing(6)
        self._layout.addLayout(self._cards_layout)
        self._layout.addStretch()

        self.setWidget(self._container)
        self.setWidgetResizable(True)
        self.enableTransparentBackground()

        self._load_cards()

        clock_service.secondTick.connect(self._refresh_all)

    # ------------------------------------------------------------------ #

    def _load_cards(self) -> None:
        # 清空旧卡片
        for card in self._cards.values():
            card.deleteLater()
        self._cards.clear()

        for zone in self._store.all():
            self._add_card(zone)

    def _add_card(self, zone: WorldZone) -> None:
        card = ZoneCard(zone, self._on_remove, self._clock_service, self._plugin_mgr,
                        self._notif_service, self._container)
        self._cards[zone.id] = card
        self._cards_layout.addWidget(card)

    # ------------------------------------------------------------------ #
    # Slots
    # ------------------------------------------------------------------ #

    @Slot()
    def _on_add(self) -> None:
        tz = self._combo.currentData()
        if not tz:
            return
        label = self._combo.currentText()
        zone  = WorldZone(label=label, timezone=tz)
        self._store.add(zone)
        self._add_card(zone)

    def _on_remove(self, zone_id: str) -> None:
        self._store.remove(zone_id)
        card = self._cards.pop(zone_id, None)
        if card:
            self._cards_layout.removeWidget(card)
            card.deleteLater()

    @Slot()
    def _refresh_all(self) -> None:
        for zone in self._store.all():
            card = self._cards.get(zone.id)
            if card:
                card.refresh(zone)

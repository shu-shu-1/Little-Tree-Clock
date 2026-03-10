"""
首页视图 — 智能推荐卡片面板

布局结构
--------
SmoothScrollArea
  └─ container (QWidget)
       ├─ 顶部标题栏（应用名 + 刷新按钮）
       ├─ 分区标签（"正在运行" / "为你推荐" / "快速入口" / "小贴士 & 统计"）
       └─ _FlowGrid  ← 自适应列数的卡片网格

推荐逻辑
--------
1. 永远置顶：GreetingCard（时段问候）
2. 活跃状态（有则显示）：
     - 每个运行中的计时器 → ActiveTimerCard
     - 秒表运行中 → ActiveStopwatchCard
     - 专注会话进行中 → ActiveFocusCard
3. 下一个闹钟：NextAlarmCard
4. 推荐功能（按使用历史综合分排序）：
     - timer / focus → 专用快速启动卡
     - 其余 → QuickActionCard
5. 统计摘要 + 随机小贴士
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Callable

from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
)
from qfluentwidgets import (
    FluentIcon as FIF,
    SmoothScrollArea,
    TitleLabel, CaptionLabel, StrongBodyLabel,
    TransparentToolButton,
)

from app.services.recommendation_service import (
    RecommendationService,
    ALL_FEATURES,
    FEATURE_TIMER, FEATURE_STOPWATCH, FEATURE_FOCUS, FEATURE_ALARM,
    FEATURE_WORLD_TIME,
)
from app.services.i18n_service import I18nService
from app.services.remote_resource_service import Announcement, RemoteResourceService
from app.views.announcement_widgets import AnnouncementBannerCard
from app.constants import APP_NAME, APP_VERSION


# ─────────────────────────────────────────────────────────────────────────── #
# 自适应流式卡片网格
# ─────────────────────────────────────────────────────────────────────────── #

_CARD_MIN_W = 300    # 卡片最小宽度（px）
_CARD_GAP   = 14     # 行列间距（px）


class _FlowGrid(QWidget):
    """
    将子 Widget 按行排列，每行尽可能多放（≥1）。
    宽度不足时自动换行。调用 set_cards() 刷新内容。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAutoFillBackground(False)
        self._cards: list[QWidget] = []
        self._grid = QGridLayout(self)
        self._grid.setSpacing(_CARD_GAP)
        self._grid.setContentsMargins(0, 0, 0, 0)

    def set_cards(self, cards: list[QWidget]) -> None:
        for card in self._cards:
            self._grid.removeWidget(card)
            card.setParent(None)
        self._cards = list(cards)
        self._reflow()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._reflow()

    def _reflow(self) -> None:
        if not self._cards:
            return
        cols = max(1, self.width() // (_CARD_MIN_W + _CARD_GAP))
        for i, card in enumerate(self._cards):
            row, col = divmod(i, cols)
            self._grid.addWidget(card, row, col, Qt.AlignTop | Qt.AlignLeft)
        self._grid.setColumnStretch(cols, 1)

    def sizeHint(self) -> QSize:
        cols = max(1, self.width() // (_CARD_MIN_W + _CARD_GAP))
        rows = math.ceil(len(self._cards) / cols) if self._cards else 0
        max_h = max((c.height() for c in self._cards), default=160)
        return QSize(self.width(), rows * (max_h + _CARD_GAP))


# ─────────────────────────────────────────────────────────────────────────── #
# 首页主视图
# ─────────────────────────────────────────────────────────────────────────── #

class HomeView(QWidget):
    """
    应用首页，展示智能推荐卡片。

    调用 ``set_services(...)`` 注入运行时依赖。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("homeView")
        self.setAutoFillBackground(False)

        self._reco  = RecommendationService.instance()
        self._i18n  = I18nService.instance()

        # 运行时依赖（window.py 通过 set_services 注入）
        self._timer_view     = None
        self._stopwatch_view = None
        self._focus_service  = None
        self._alarm_store    = None
        self._clock_service  = None
        self._plugin_mgr     = None
        self._notif_service  = None
        self._resource_service: RemoteResourceService | None = None
        self._navigate_to: Callable[[str], None] = lambda _: None
        self._announcements: list[Announcement] = []
        self._dismissed_announcement_ids: set[str] = set()

        self._demo_mode = False      # 调试面板的 Demo 模式标志

        self._build_ui()

        self._reco.updated.connect(self._schedule_refresh)

        self._auto_refresh = QTimer(self)
        self._auto_refresh.setInterval(60_000)
        self._auto_refresh.timeout.connect(self._build_cards)
        self._auto_refresh.start()

        QTimer.singleShot(300, self._build_cards)

    # ── 依赖注入 ──────────────────────────────────────────────────────── #

    def set_services(
        self,
        timer_view=None,
        stopwatch_view=None,
        focus_service=None,
        alarm_service=None,
        alarm_store=None,
        clock_service=None,
        plugin_manager=None,
        notification_service=None,
        resource_service: RemoteResourceService | None = None,
        navigate_to: Callable[[str], None] | None = None,
    ) -> None:
        self._timer_view     = timer_view
        self._stopwatch_view = stopwatch_view
        self._focus_service  = focus_service
        self._alarm_store    = alarm_store
        self._clock_service  = clock_service
        self._plugin_mgr     = plugin_manager
        self._notif_service  = notification_service
        if navigate_to:
            self._navigate_to = navigate_to
        self.set_resource_service(resource_service)
        if focus_service:
            focus_service.phaseChanged.connect(lambda *_: self._schedule_refresh())
            focus_service.sessionFinished.connect(self._schedule_refresh)
        self._build_cards()

    def set_resource_service(self, resource_service: RemoteResourceService | None) -> None:
        if resource_service is self._resource_service:
            return

        if self._resource_service is not None:
            try:
                self._resource_service.announcementsUpdated.disconnect(self._on_announcements_updated)
            except Exception:
                pass

        self._resource_service = resource_service
        if resource_service is not None:
            resource_service.announcementsUpdated.connect(self._on_announcements_updated)
            self._on_announcements_updated(resource_service.announcements)
        else:
            self._on_announcements_updated([])

    def set_demo_mode(self, enabled: bool) -> None:
        """调试模式：展示所有类型卡片（忽略推荐算法）"""
        self._demo_mode = enabled
        self._build_cards()

    # ── UI 骨架 ───────────────────────────────────────────────────────── #

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = SmoothScrollArea(self)
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)

        container = QWidget()
        container.setAutoFillBackground(False)   # 透传云母/亚克力背景
        self._root = QVBoxLayout(container)
        self._root.setContentsMargins(28, 20, 28, 28)
        self._root.setSpacing(14)

        # 标题行
        title_row = QHBoxLayout()
        title_row.addWidget(TitleLabel(APP_NAME))
        title_row.addSpacing(8)
        ver_lbl = CaptionLabel(f"v{APP_VERSION}")
        ver_lbl.setStyleSheet("color:gray;")
        title_row.addWidget(ver_lbl)
        title_row.addStretch()
        self._last_refresh_lbl = CaptionLabel("")
        self._last_refresh_lbl.setStyleSheet("color:gray;font-size:11px;")
        title_row.addWidget(self._last_refresh_lbl)
        refresh_btn = TransparentToolButton(FIF.SYNC)
        refresh_btn.setToolTip("刷新推荐")
        refresh_btn.clicked.connect(self._build_cards)
        title_row.addWidget(refresh_btn)
        self._root.addLayout(title_row)

        self._announcement_host = QWidget()
        self._announcement_host.setAutoFillBackground(False)
        self._announcement_layout = QVBoxLayout(self._announcement_host)
        self._announcement_layout.setContentsMargins(0, 0, 0, 0)
        self._announcement_layout.setSpacing(10)
        self._announcement_host.hide()
        self._root.addWidget(self._announcement_host)

        # 内容容器（动态填充）
        self._content = QWidget()
        self._content.setAutoFillBackground(False)
        self._content_lay = QVBoxLayout(self._content)
        self._content_lay.setSpacing(14)
        self._content_lay.setContentsMargins(0, 0, 0, 0)
        self._root.addWidget(self._content)
        self._root.addStretch()

        scroll.setWidget(container)
        scroll.enableTransparentBackground()

    # ── 内容构建 ──────────────────────────────────────────────────────── #

    def _clear_content(self) -> None:
        while self._content_lay.count():
            item = self._content_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _clear_announcement_banners(self) -> None:
        while self._announcement_layout.count():
            item = self._announcement_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _on_announcements_updated(self, announcements: list[Announcement]) -> None:
        self._announcements = list(announcements)
        self._render_announcements()

    def _render_announcements(self) -> None:
        self._clear_announcement_banners()

        visible_items = [
            announcement
            for announcement in self._announcements
            if announcement.stable_id not in self._dismissed_announcement_ids
        ]
        self._announcement_host.setVisible(bool(visible_items))
        if not visible_items:
            return

        for announcement in visible_items:
            card = AnnouncementBannerCard(announcement, self._announcement_host)
            card.dismissed.connect(self._dismiss_announcement_banner)
            self._announcement_layout.addWidget(card)

    def _dismiss_announcement_banner(self, announcement_id: str) -> None:
        key = str(announcement_id).strip()
        if not key:
            return
        self._dismissed_announcement_ids.add(key)
        self._render_announcements()

    def _section(self, title: str) -> None:
        self._content_lay.addWidget(StrongBodyLabel(title))

    def _flow(self, cards: list) -> None:
        if not cards:
            return
        g = _FlowGrid()
        g.set_cards(cards)
        self._content_lay.addWidget(g)

    def _schedule_refresh(self) -> None:
        QTimer.singleShot(600, self._build_cards)

    def _build_cards(self) -> None:
        from app.views.home_cards import (
            GreetingCard, ActiveTimerCard, ActiveStopwatchCard,
            ActiveFocusCard, NextAlarmCard, QuickTimerCard,
            QuickFocusCard, QuickActionCard, TipCard, StatsCard,
            EchoCard,
            make_demo_cards,
        )

        self._clear_content()
        nav = self._navigate_to

        # ── Demo 模式 ──────────────────────────────────────────────────── #
        if self._demo_mode:
            self._section("🖥️  Demo 模式 — 所有卡片类型预览")
            self._flow(make_demo_cards(nav))
            self._last_refresh_lbl.setText(
                f"Demo · {datetime.now().strftime('%H:%M:%S')}"
            )
            return

        # ── 1. 问候卡片 ───────────────────────────────────────────────── #
        self._content_lay.addWidget(GreetingCard(nav))

        # ── 2. 活跃状态卡片 ──────────────────────────────────────────── #
        active_cards: list = []
        active_feats: set[str] = set()

        if self._timer_view is not None:
            for item in self._timer_view._items.values():
                if item.running and not item.done:
                    c = ActiveTimerCard(item, nav)
                    c.pause_requested.connect(self._on_timer_pause)
                    c.resume_requested.connect(self._on_timer_resume)
                    active_cards.append(c)
                    active_feats.add(FEATURE_TIMER)

        if self._stopwatch_view is not None and self._stopwatch_view._running:
            sw = self._stopwatch_view
            active_cards.append(ActiveStopwatchCard(
                elapsed_ms_getter=lambda: sw._elapsed_ms,
                is_running_getter=lambda: sw._running,
                navigate_to=nav,
            ))
            active_feats.add(FEATURE_STOPWATCH)

        if self._focus_service is not None:
            from app.services.focus_service import FocusPhase
            if self._focus_service.phase in (FocusPhase.FOCUS, FocusPhase.BREAK):
                active_cards.append(ActiveFocusCard(self._focus_service, nav))
                active_feats.add(FEATURE_FOCUS)

        # ── 3. 下一个闹钟 ─────────────────────────────────────────────── #
        next_alarm_card = self._next_alarm_card(nav)

        all_priority = active_cards[:]
        if next_alarm_card:
            all_priority.append(next_alarm_card)

        if all_priority:
            self._section("🔔  正在运行 / 即将触发")
            self._flow(all_priority)

        # ── 4. 排除已展示的功能，计算推荐排名 ────────────────────────── #
        shown_feats = set(active_feats)
        if next_alarm_card:
            shown_feats.add(FEATURE_ALARM)

        ranked = self._reco.ranked(active_feats, exclude=shown_feats)

        quick_cards: list = []
        for feat_id, score in ranked[:8]:
            c = self._quick_card(feat_id, nav)
            if c is not None:
                quick_cards.append(c)
            if len(quick_cards) >= 6:
                break

        if quick_cards:
            self._section("✨  为你推荐")
            self._flow(quick_cards)
        else:
            # 首次使用，无历史数据 → 展示全部功能入口
            self._section("🚀  快速入口")
            self._flow([QuickActionCard(f, navigate_to=nav) for f in ALL_FEATURES])

        # ── 5. 统计 + 小贴士 + 回声洞 ───────────────────────────── #
        extra: list = []
        all_ranked = self._reco.ranked()
        if any(s > 0 for _, s in all_ranked):
            extra.append(StatsCard(all_ranked, nav))
        extra.append(TipCard(navigate_to=nav))
        extra.append(EchoCard(navigate_to=nav))
        self._section("💡  小贴士 & 统计")
        self._flow(extra)

        self._last_refresh_lbl.setText(
            f"上次更新：{datetime.now().strftime('%H:%M:%S')}"
        )
        self._content_lay.addStretch()

    # ── 辅助 ──────────────────────────────────────────────────────────── #

    def _next_alarm_card(self, nav) -> object | None:
        from app.views.home_cards import NextAlarmCard
        if self._alarm_store is None:
            return None
        now = datetime.now()
        best, best_min = None, 99_999
        for alarm in self._alarm_store.all():
            if not alarm.enabled:
                continue
            alarm_td = timedelta(hours=alarm.hour, minutes=alarm.minute)
            now_td   = timedelta(hours=now.hour, minutes=now.minute, seconds=now.second)
            diff = alarm_td - now_td
            if diff.total_seconds() <= 0:
                diff += timedelta(days=1)
            minutes = int(diff.total_seconds() / 60)
            if minutes < best_min:
                best_min = minutes
                best     = alarm
        if best is None:
            return None
        return NextAlarmCard(best.label, best.time_str, best_min, nav)

    def _quick_card(self, feat_id: str, nav) -> object | None:
        from app.views.home_cards import (
            QuickTimerCard, QuickFocusCard, QuickActionCard, FullscreenClockCard,
        )

        reason = self._reco.get_reason(feat_id)

        if feat_id == FEATURE_TIMER and self._timer_view is not None:
            items = list(self._timer_view._items.values())
            if items:
                candidates = [i for i in items if not i.running and not i.done]
                item = candidates[0] if candidates else items[-1]
                card = QuickTimerCard(
                    item.label,
                    item.total_ms,
                    nav,
                    reason=reason,
                    timer_id=item.id,
                )
                card.start_requested.connect(self._on_quick_timer_start)
                return card

        if feat_id == FEATURE_FOCUS:
            try:
                from app.models.focus_model import FocusStore
                presets = FocusStore().all()
                if presets:
                    card = QuickFocusCard(presets[0], nav, reason=reason)
                    card.start_requested.connect(self._on_quick_focus_start)
                    return card
            except Exception:
                pass

        # 对世界时间深度推荐：如果用户配置了时区，直接展示全屏卡片
        if feat_id == FEATURE_WORLD_TIME:
            try:
                from app.models.world_zone import WorldZoneStore
                zones = WorldZoneStore().all()
                if zones:
                    return FullscreenClockCard(
                        zones[0],
                        clock_service=self._clock_service,
                        plugin_manager=self._plugin_mgr,
                        notification_service=self._notif_service,
                        navigate_to=nav,
                        reason=reason,
                    )
            except Exception:
                pass

        _fallback: dict[str, str] = {
            FEATURE_WORLD_TIME: "查看全球多个时区的当前时间",
            FEATURE_ALARM:      "设置闹钟，不再错过重要时刻",
            FEATURE_TIMER:      "开始一个倒计时",
            FEATURE_STOPWATCH:  "启动秒表，精确计时",
            FEATURE_FOCUS:      "用番茄钟保持高效专注",
            "plugin":           "探索更多插件功能",
            "automation":       "设置自动化规则，解放双手",
        }
        display_reason = reason or _fallback.get(feat_id, "")
        return QuickActionCard(feat_id, display_reason, nav)

    def _on_timer_pause(self, timer_id: str) -> None:
        if self._timer_view:
            item = self._timer_view._items.get(timer_id)
            if item:
                item.pause()

    def _on_timer_resume(self, timer_id: str) -> None:
        if self._timer_view:
            item = self._timer_view._items.get(timer_id)
            if item:
                item.start()

    def _on_quick_timer_start(self, timer_id: str, label: str, total_ms: int) -> None:
        """首页快速启动计时器：优先启动已有计时器，否则新建后跳转到计时器页面。"""
        if self._timer_view is not None:
            started = False
            if timer_id:
                started = self._timer_view.start_or_restart(timer_id)
            if not started:
                self._timer_view.quick_start(label, total_ms)
            self._reco.on_session_start(FEATURE_TIMER)
        self._navigate_to("timer")
        if self._timer_view is not None and timer_id:
            QTimer.singleShot(0, lambda tid=timer_id: self._timer_view.reveal_timer(tid))
        self._schedule_refresh()

    def _on_quick_focus_start(self, preset) -> None:
        """首页快速启动专注会话：启动后跳转到专注页面"""
        if self._focus_service is not None:
            self._focus_service.start(preset)
            self._reco.on_session_start(FEATURE_FOCUS)
        self._navigate_to("focus")
        self._schedule_refresh()

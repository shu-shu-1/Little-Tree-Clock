"""  
首页推荐卡片组件库  

包含所有推荐卡片类型：
  - GreetingCard        时段问候 + 日期
  - ActiveTimerCard     正在运行的计时器（实时进度）
  - ActiveStopwatchCard 正在运行的秒表
  - ActiveFocusCard     正在进行的专注会话
  - NextAlarmCard       下一个闹钟
  - QuickTimerCard      快速启动上次计时器
  - QuickFocusCard      快速启动专注预设
  - QuickActionCard     通用功能跳转建议卡
  - TipCard             使用小贴士
  - EchoCard            回声洞（打字机动画随机语录）

每张卡片均为独立 QWidget，可直接放入布局。
卡片通过 navigate_to 回调进行页面跳转，避免与主窗口紧耦合。
"""
from __future__ import annotations

import random
from datetime import datetime
from typing import Callable

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
)
from qfluentwidgets import (
    CardWidget,
    SubtitleLabel, BodyLabel, CaptionLabel,
    PushButton, PrimaryPushButton, TransparentPushButton,
    FluentIcon as FIF,
    ProgressRing,
    IconWidget,
)

from app.utils.time_utils import format_duration
from app.services.settings_service import SettingsService

# ─────────────────────────────────────────────────────────────────────────── #
# 工具
# ─────────────────────────────────────────────────────────────────────────── #

def _card_w() -> int:  return 300
def _card_h() -> int:  return 160

def _greeting_text() -> tuple[str, object]:
    """返回 (问候语, FluentIcon)"""
    h = datetime.now().hour
    if 5 <= h < 9:
        return "早上好", FIF.SYNC          # 清晨
    elif 9 <= h < 12:
        return "上午好", FIF.HISTORY        # 上午
    elif 12 <= h < 14:
        return "午好", FIF.CAFE            # 午间
    elif 14 <= h < 18:
        return "下午好", FIF.HISTORY        # 下午
    elif 18 <= h < 22:
        return "晚上好", FIF.QUIET_HOURS    # 傍晚/晚间
    else:
        return "夜深了", FIF.QUIET_HOURS    # 深夜


_TIPS: list[str] = [
    "使用 ltclock://open/timer 可从其他应用直接打开计时器",
    "专注模式支持检测窗口焦点，离开目标程序会立即提醒",
    "自动化规则可以在计时器结束时自动执行任何操作",
    "秒表支持记圈功能，每圈时间一目了然",
    "闹钟支持多次重复，可设置工作日、周末等模式",
    "世界时间支持同屏对比多个时区",
    "插件系统支持安装社区共享的扩展功能",
    "按住计时器卡片可以拖动到悬浮小窗模式",
    "长按通知可以快速操作（稍后提醒 / 关闭）",
    "NTP 自动同步让时钟精度达到毫秒级",
]

_ECHOES: list[str] = [
    "你所浪费的今天，是昨天死去的人渴望的明天。",
    "时间是最公平的资源，每个人每天都只有 24 小时。",
    "不是每件重要的事都紧急，不是每件紧急的事都重要。",
    "专注不是拒绝一切，而是把最好的资源给最值得的事。",
    "番茄钟的本质：把无限的时间切成有限的承诺。",
    "做完比做好更重要——先完成，再完善。",
    "拖延的本质不是懒惰，而是对不确定的回避。",
    "习惯是思维的快捷方式，让大脑节省能量给真正的决策。",
    "你开始的那一刻，就已经领先了还没开始的人。",
    "计划不如变化快，但没有计划更快变成混乱。",
    "睡眠是最被低估的生产力工具。",
    "不要用战术的勤奋，掩盖战略的懒惰。",
    "进度不需要是完美的，只需要是真实的。",
    "每次只做一件事，比同时做五件事快三倍。",
    "打断是专注力的天敌，需要 23 分钟才能回到深度工作状态。",
    "你不是在管理时间，你是在管理注意力。",
    "完成一件事的最快方式，是不做其他事。",
    "休息是生产力的一部分，不是生产力的对立面。",
    "把每一分钟花在刀刃上，你会得到一把锋利的人生。",
    "最难的那一步，是从椅子上站起来。",
    "没有什么比'从现在开始'更早的开始。",
    "时间不够用时，往往是因为目标太模糊。",
    "优先级是一种稀缺资源，不是所有事都能放在第一位。",
    "深度工作是竞争力，浅层忙碌是幻觉。",
    "每个'以后再说'都是一个未兑现的承诺。",
    "为什么软件要做本地化？？？其它界面还得单独适配",
    "请输入文本",
    "这是一条回声洞，回声回声回声回声回声回声回声回声回声回声回声回声回声回声回声回声",
    
]


# ─────────────────────────────────────────────────────────────────────────── #
# 基础卡片（统一尺寸 / 阴影 / 悬停效果）
# ─────────────────────────────────────────────────────────────────────────── #

class _BaseCard(CardWidget):
    """所有推荐卡片的基类，约定最小尺寸和通用布局工具。"""

    card_type: str = "base"

    def __init__(self, navigate_to: Callable[[str], None] | None = None, parent=None):
        super().__init__(parent)
        self._nav = navigate_to or (lambda _: None)
        self.setFixedSize(_card_w(), _card_h())
        self.setCursor(Qt.PointingHandCursor)

    def _root_layout(self) -> QVBoxLayout:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)
        return lay

    def _label_row(self, icon, title: str) -> QHBoxLayout:
        """构造图标 + 分类文字行。
        icon 可传 FluentIcon（推荐）或 str（emoji 兼容）。
        """
        row = QHBoxLayout()
        if isinstance(icon, str):
            icon_w: QWidget = CaptionLabel(icon)
            icon_w.setStyleSheet("font-size:16px;")
        else:
            icon_w = IconWidget(icon)
            icon_w.setFixedSize(16, 16)
        title_lbl = CaptionLabel(title)
        title_lbl.setStyleSheet("color: gray;")
        row.addWidget(icon_w)
        row.addSpacing(6)
        row.addWidget(title_lbl)
        row.addStretch()
        return row


# ─────────────────────────────────────────────────────────────────────────── #
# 1. GreetingCard — 问候卡片
# ─────────────────────────────────────────────────────────────────────────── #

class GreetingCard(_BaseCard):
    """时段问候 + 当天日期 + 星期"""

    card_type = "greeting"

    def __init__(self, navigate_to=None, parent=None):
        super().__init__(navigate_to, parent)
        self.setFixedSize(300, 140)
        lay = self._root_layout()

        greeting, icon = _greeting_text()

        top = QHBoxLayout()
        icon_w = IconWidget(icon)
        icon_w.setFixedSize(16, 16)
        top.addWidget(icon_w)
        top.addSpacing(6)
        top.addWidget(CaptionLabel(datetime.now().strftime("%Y年%m月%d日 %A")))
        top.addStretch()
        lay.addLayout(top)

        self._greet_lbl = SubtitleLabel(greeting)
        font = self._greet_lbl.font()
        font.setPointSize(18)
        font.setBold(True)
        self._greet_lbl.setFont(font)
        lay.addWidget(self._greet_lbl)

        self._hint_lbl = CaptionLabel("今天也要好好利用时间哦")
        self._hint_lbl.setStyleSheet("color: gray;")
        lay.addWidget(self._hint_lbl)
        lay.addStretch()

        # 1 分钟刷新问候语
        self._timer = QTimer(self)
        self._timer.setInterval(60_000)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()

    def _refresh(self) -> None:
        greeting, emoji = _greeting_text()
        self._greet_lbl.setText(greeting)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)


# ─────────────────────────────────────────────────────────────────────────── #
# 2. ActiveTimerCard — 运行中的计时器
# ─────────────────────────────────────────────────────────────────────────── #

class ActiveTimerCard(_BaseCard):
    """显示一个正在运行（或暂停）的计时器，含实时进度和暂停/继续按钮。"""

    card_type = "active_timer"

    # 信号：用户点击了暂停 / 恢复 / 停止操作
    pause_requested  = Signal(str)   # timer_id
    resume_requested = Signal(str)
    stop_requested   = Signal(str)

    def __init__(self, timer_item, navigate_to=None, parent=None):
        """
        Parameters
        ----------
        timer_item : TimerItem  （来自 timer_view 的 TimerItem 实例）
        """
        super().__init__(navigate_to, parent)
        self._item = timer_item
        self._settings = SettingsService.instance()
        lay = self._root_layout()

        # 标题行
        lay.addLayout(self._label_row(FIF.HISTORY, "计时器运行中"))

        # 内容行：进度环 + 时间 + 标签
        content = QHBoxLayout()
        content.setSpacing(12)

        # 小进度环（固定 72px）
        ring_container = QWidget()
        ring_container.setFixedSize(72, 72)
        ring_container.setStyleSheet("background:transparent;")
        self._ring = ProgressRing(ring_container)
        self._ring.setFixedSize(72, 72)
        self._ring.setRange(0, 1000)
        self._ring.setValue(int(timer_item.progress * 1000))
        self._ring.setTextVisible(False)
        self._ring.setStrokeWidth(7)
        self._ring.move(0, 0)
        self._time_lbl_ring = CaptionLabel(
            format_duration(timer_item.remaining, self._settings.timer_precision),
            ring_container,
        )
        self._time_lbl_ring.setAlignment(Qt.AlignCenter)
        self._time_lbl_ring.setFixedSize(72, 72)
        self._time_lbl_ring.setStyleSheet("background:transparent;font-size:11px;")
        self._time_lbl_ring.move(0, 0)
        self._time_lbl_ring.raise_()
        content.addWidget(ring_container)

        # 右侧信息
        info = QVBoxLayout()
        self._name_lbl = BodyLabel(timer_item.label or "计时器")
        self._time_lbl = SubtitleLabel(
            format_duration(timer_item.remaining, self._settings.timer_precision)
        )
        self._time_lbl.setStyleSheet("font-size:20px; font-weight:600;")
        info.addWidget(self._name_lbl)
        info.addWidget(self._time_lbl)
        info.addStretch()
        content.addLayout(info, 1)
        lay.addLayout(content)

        # 按钮行
        btn_row = QHBoxLayout()
        self._pause_btn = PushButton(
            FIF.PAUSE if timer_item.running else FIF.PLAY,
            "暂停" if timer_item.running else "继续",
        )
        self._pause_btn.setFixedHeight(28)
        self._pause_btn.clicked.connect(self._on_pause_toggle)

        open_btn = TransparentPushButton(FIF.LINK, "前往")
        open_btn.setFixedHeight(28)
        open_btn.clicked.connect(lambda: self._nav("timer"))

        btn_row.addWidget(self._pause_btn)
        btn_row.addStretch()
        btn_row.addWidget(open_btn)
        lay.addLayout(btn_row)

        # 连接 item 信号
        timer_item.updated.connect(self._refresh)

    def _refresh(self) -> None:
        prec = self._settings.timer_precision
        text = format_duration(self._item.remaining, prec)
        self._time_lbl.setText(text)
        self._time_lbl_ring.setText(text)
        self._ring.setValue(int(self._item.progress * 1000))
        if self._item.running:
            self._pause_btn.setIcon(FIF.PAUSE)
            self._pause_btn.setText("暂停")
        else:
            self._pause_btn.setIcon(FIF.PLAY)
            self._pause_btn.setText("继续")

    def _on_pause_toggle(self) -> None:
        if self._item.running:
            self.pause_requested.emit(self._item.id)
        else:
            self.resume_requested.emit(self._item.id)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        if event.button() == Qt.LeftButton:
            self._nav("timer")


# ─────────────────────────────────────────────────────────────────────────── #
# 3. ActiveStopwatchCard — 运行中的秒表
# ─────────────────────────────────────────────────────────────────────────── #

class ActiveStopwatchCard(_BaseCard):
    """显示秒表正在运行的当前时长，点击可导航到秒表页。"""

    card_type = "active_stopwatch"

    def __init__(
        self,
        elapsed_ms_getter: Callable[[], int],
        is_running_getter: Callable[[], bool],
        navigate_to=None,
        parent=None,
    ):
        super().__init__(navigate_to, parent)
        self._get_elapsed   = elapsed_ms_getter
        self._is_running    = is_running_getter
        self._settings      = SettingsService.instance()

        lay = self._root_layout()
        lay.addLayout(self._label_row(FIF.STOP_WATCH, "秒表运行中"))

        self._time_lbl = SubtitleLabel("00:00.0")
        font = self._time_lbl.font()
        font.setPointSize(22)
        font.setBold(True)
        self._time_lbl.setFont(font)
        lay.addWidget(self._time_lbl)

        self._status_lbl = CaptionLabel("计时中...")
        self._status_lbl.setStyleSheet("color: gray;")
        lay.addWidget(self._status_lbl)
        lay.addStretch()

        btn_row = QHBoxLayout()
        open_btn = PushButton(FIF.STOP_WATCH, "前往秒表")
        open_btn.setFixedHeight(28)
        open_btn.clicked.connect(lambda: self._nav("stopwatch"))
        btn_row.addStretch()
        btn_row.addWidget(open_btn)
        lay.addLayout(btn_row)

        # 每 100ms 刷新一次显示
        self._tick = QTimer(self)
        self._tick.setInterval(100)
        self._tick.timeout.connect(self._refresh)
        self._tick.start()

    def _refresh(self) -> None:
        prec = self._settings.stopwatch_precision
        elapsed = self._get_elapsed()
        self._time_lbl.setText(format_duration(elapsed, prec))
        self._status_lbl.setText("计时中..." if self._is_running() else "已暂停")

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        if event.button() == Qt.LeftButton:
            self._nav("stopwatch")


# ─────────────────────────────────────────────────────────────────────────── #
# 4. ActiveFocusCard — 正在进行的专注会话
# ─────────────────────────────────────────────────────────────────────────── #

class ActiveFocusCard(_BaseCard):
    """显示正在进行中的专注会话，含进度和当前阶段。"""

    card_type = "active_focus"

    def __init__(self, focus_service, navigate_to=None, parent=None):
        super().__init__(navigate_to, parent)
        self._svc = focus_service
        lay = self._root_layout()
        lay.addLayout(self._label_row(FIF.CAFE, "专注会话进行中"))

        info = QHBoxLayout()
        self._ring = ProgressRing()
        self._ring.setFixedSize(64, 64)
        self._ring.setRange(0, 1000)
        self._ring.setTextVisible(False)
        self._ring.setStrokeWidth(7)
        info.addWidget(self._ring)
        info.addSpacing(12)

        right = QVBoxLayout()
        self._phase_lbl = BodyLabel("专注中")
        self._time_lbl  = SubtitleLabel("--:--")
        self._time_lbl.setStyleSheet("font-size:20px; font-weight:600;")
        right.addWidget(self._phase_lbl)
        right.addWidget(self._time_lbl)
        right.addStretch()
        info.addLayout(right, 1)
        lay.addLayout(info)

        btn_row = QHBoxLayout()
        open_btn = PushButton(FIF.CAFE, "前往专注")
        open_btn.setFixedHeight(28)
        open_btn.clicked.connect(lambda: self._nav("focus"))
        btn_row.addStretch()
        btn_row.addWidget(open_btn)
        lay.addLayout(btn_row)

        self._tick = QTimer(self)
        self._tick.setInterval(1_000)
        self._tick.timeout.connect(self._refresh)
        self._tick.start()
        self._refresh()

        focus_service.tick.connect(self._on_tick)

    def _on_tick(self, elapsed_ms: int, remaining_ms: int, phase) -> None:
        from app.services.focus_service import FocusPhase
        total = elapsed_ms + remaining_ms
        progress = elapsed_ms / total if total > 0 else 0
        self._ring.setValue(int(progress * 1000))
        mins, secs = divmod(remaining_ms // 1000, 60)
        self._time_lbl.setText(f"{mins:02d}:{secs:02d}")
        if phase == FocusPhase.FOCUS:
            self._phase_lbl.setText("🎯 专注中")
        elif phase == FocusPhase.BREAK:
            self._phase_lbl.setText("☕ 休息中")

    def _refresh(self) -> None:
        pass  # 实际刷新通过 tick 信号驱动

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        if event.button() == Qt.LeftButton:
            self._nav("focus")


# ─────────────────────────────────────────────────────────────────────────── #
# 5. NextAlarmCard — 下一个闹钟
# ─────────────────────────────────────────────────────────────────────────── #

class NextAlarmCard(_BaseCard):
    """显示距离最近的下一个闹钟的时间和倒计时。"""

    card_type = "next_alarm"

    def __init__(
        self,
        alarm_label: str,
        alarm_time_str: str,   # "HH:MM"
        countdown_min: int,    # 距现在的分钟数
        navigate_to=None,
        parent=None,
    ):
        super().__init__(navigate_to, parent)
        lay = self._root_layout()
        lay.addLayout(self._label_row(FIF.RINGER, "下一个闹钟"))

        time_lbl = SubtitleLabel(alarm_time_str)
        font = time_lbl.font()
        font.setPointSize(24)
        font.setBold(True)
        time_lbl.setFont(font)
        lay.addWidget(time_lbl)

        label_lbl = BodyLabel(alarm_label)
        lay.addWidget(label_lbl)

        if countdown_min < 60:
            countdown_str = f"{countdown_min} 分钟后"
        elif countdown_min < 1440:
            h, m = divmod(countdown_min, 60)
            countdown_str = f"{h} 小时 {m} 分钟后"
        else:
            d = countdown_min // 1440
            countdown_str = f"{d} 天后"
        self._cd_lbl = CaptionLabel(f"还有 {countdown_str}")
        self._cd_lbl.setStyleSheet("color: gray;")
        lay.addWidget(self._cd_lbl)
        lay.addStretch()

        btn_row = QHBoxLayout()
        open_btn = TransparentPushButton(FIF.RINGER, "管理闹钟")
        open_btn.setFixedHeight(28)
        open_btn.clicked.connect(lambda: self._nav("alarm"))
        btn_row.addStretch()
        btn_row.addWidget(open_btn)
        lay.addLayout(btn_row)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        if event.button() == Qt.LeftButton:
            self._nav("alarm")


# ─────────────────────────────────────────────────────────────────────────── #
# 6. QuickTimerCard — 快速启动计时器
# ─────────────────────────────────────────────────────────────────────────── #

class QuickTimerCard(_BaseCard):
    """显示最近使用的计时器配置，一键重新启动。"""

    card_type = "quick_timer"

    start_requested = Signal(str, str, int)   # (timer_id, label, total_ms)

    def __init__(
        self,
        label: str,
        total_ms: int,
        navigate_to=None,
        parent=None,
        reason: str = "",
        timer_id: str = "",
    ):
        super().__init__(navigate_to, parent)
        self._timer_id = timer_id
        self._label    = label
        self._total_ms = total_ms

        lay = self._root_layout()
        lay.addLayout(self._label_row(FIF.HISTORY, "快速计时器"))

        total_sec = total_ms // 1000
        m, s = divmod(total_sec, 60)
        h, m = divmod(m, 60)
        if h > 0:
            time_str = f"{h:02d}:{m:02d}:{s:02d}"
        else:
            time_str = f"{m:02d}:{s:02d}"

        time_lbl = SubtitleLabel(time_str)
        font = time_lbl.font()
        font.setPointSize(20)
        font.setBold(True)
        time_lbl.setFont(font)
        lay.addWidget(time_lbl)

        lay.addWidget(BodyLabel(label))

        if reason:
            reason_lbl = CaptionLabel(f"💡 {reason}")
            reason_lbl.setStyleSheet("color: gray; font-size: 10px;")
            reason_lbl.setWordWrap(True)
            lay.addWidget(reason_lbl)

        lay.addStretch()

        btn_row = QHBoxLayout()
        start_btn = PrimaryPushButton(FIF.PLAY, "快速启动")
        start_btn.setFixedHeight(28)
        start_btn.clicked.connect(
            lambda: self.start_requested.emit(self._timer_id, self._label, self._total_ms)
        )

        open_btn = TransparentPushButton(FIF.LINK, "前往")
        open_btn.setFixedHeight(28)
        open_btn.clicked.connect(lambda: self._nav("timer"))

        btn_row.addWidget(start_btn)
        btn_row.addStretch()
        btn_row.addWidget(open_btn)
        lay.addLayout(btn_row)


# ─────────────────────────────────────────────────────────────────────────── #
# 7. QuickFocusCard — 快速启动专注预设
# ─────────────────────────────────────────────────────────────────────────── #

class QuickFocusCard(_BaseCard):
    """展示某个专注预设，点击可立即开始。"""

    card_type = "quick_focus"

    start_requested = Signal(object)   # FocusPreset

    def __init__(self, preset, navigate_to=None, parent=None, reason: str = ""):
        """
        Parameters
        ----------
        preset : FocusPreset
        reason : str  推荐原因文字，为空则不显示
        """
        super().__init__(navigate_to, parent)
        self._preset = preset
        lay = self._root_layout()
        lay.addLayout(self._label_row(FIF.CAFE, "快速专注"))

        name_lbl = SubtitleLabel(preset.name or "专注模式")
        font = name_lbl.font()
        font.setPointSize(16)
        font.setBold(True)
        name_lbl.setFont(font)
        lay.addWidget(name_lbl)

        detail = f"专注 {preset.focus_minutes} 分钟 / 休息 {preset.break_minutes} 分钟"
        if preset.cycles and preset.cycles > 1:
            detail += f" × {preset.cycles} 轮"
        detail_lbl = CaptionLabel(detail)
        detail_lbl.setStyleSheet("color: gray;")
        lay.addWidget(detail_lbl)

        if reason:
            reason_lbl = CaptionLabel(f"💡 {reason}")
            reason_lbl.setStyleSheet("color: gray; font-size: 10px;")
            reason_lbl.setWordWrap(True)
            lay.addWidget(reason_lbl)

        lay.addStretch()

        btn_row = QHBoxLayout()
        start_btn = PrimaryPushButton(FIF.PLAY, "开始专注")
        start_btn.setFixedHeight(28)
        start_btn.clicked.connect(lambda: self.start_requested.emit(self._preset))

        open_btn = TransparentPushButton(FIF.LINK, "前往")
        open_btn.setFixedHeight(28)
        open_btn.clicked.connect(lambda: self._nav("focus"))

        btn_row.addWidget(start_btn)
        btn_row.addStretch()
        btn_row.addWidget(open_btn)
        lay.addLayout(btn_row)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)


# ─────────────────────────────────────────────────────────────────────────── #
# 8. QuickActionCard — 通用功能跳转卡片
# ─────────────────────────────────────────────────────────────────────────── #

# FluentIcon 映射（替代 emoji，供 QuickActionCard / StatsCard 使用）
_FEATURE_FIF: dict[str, FIF] = {
    "world_time": FIF.GLOBE,
    "alarm":      FIF.RINGER,
    "timer":      FIF.HISTORY,
    "stopwatch":  FIF.STOP_WATCH,
    "focus":      FIF.CAFE,
    "plugin":     FIF.APPLICATION,
    "automation": FIF.FLAG,
}

_FEATURE_DESC: dict[str, str] = {
    "world_time": "查看多个时区的当前时间",
    "alarm":      "设置闹钟，按时提醒",
    "timer":      "倒计时计时器，精确到百分位",
    "stopwatch":  "正计时，支持记圈",
    "focus":      "番茄钟 + 专注状态监测",
    "plugin":     "扩展应用功能",
    "automation": "设置自动化规则",
}


class QuickActionCard(_BaseCard):
    """推荐用户前往某个功能页面的通用跳转卡片。"""

    card_type = "quick_action"

    def __init__(
        self,
        feature_id: str,
        reason: str = "",
        navigate_to=None,
        parent=None,
    ):
        super().__init__(navigate_to, parent)
        self._feature = feature_id
        icon  = _FEATURE_FIF.get(feature_id, FIF.FLAG)
        name  = _get_feature_name(feature_id)
        desc  = reason or _FEATURE_DESC.get(feature_id, "")

        lay = self._root_layout()
        lay.addLayout(self._label_row(icon, "为你推荐"))

        name_lbl = SubtitleLabel(name)
        font = name_lbl.font()
        font.setPointSize(16)
        font.setBold(True)
        name_lbl.setFont(font)
        lay.addWidget(name_lbl)

        desc_lbl = CaptionLabel(desc)
        desc_lbl.setStyleSheet("color: gray;")
        desc_lbl.setWordWrap(True)
        lay.addWidget(desc_lbl)
        lay.addStretch()

        btn_row = QHBoxLayout()
        go_btn = PushButton(FIF.LINK, f"前往{name}")
        go_btn.setFixedHeight(28)
        go_btn.clicked.connect(lambda: self._nav(feature_id))
        btn_row.addStretch()
        btn_row.addWidget(go_btn)
        lay.addLayout(btn_row)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        if event.button() == Qt.LeftButton:
            self._nav(self._feature)


def _get_feature_name(feature_id: str) -> str:
    _NAMES: dict[str, str] = {
        "world_time": "世界时间",
        "alarm":      "闹钟",
        "timer":      "计时器",
        "stopwatch":  "秒表",
        "focus":      "专注模式",
        "plugin":     "插件",
        "automation": "自动化",
    }
    return _NAMES.get(feature_id, feature_id)


# ─────────────────────────────────────────────────────────────────────────── #
# 9. TipCard — 使用小贴士
# ─────────────────────────────────────────────────────────────────────────── #

class TipCard(_BaseCard):
    """随机显示一条使用小贴士。点击卡片可切换下一条。"""

    card_type = "tip"

    def __init__(self, tip_text: str = "", navigate_to=None, parent=None):
        super().__init__(navigate_to, parent)
        self.setFixedSize(300, 110)
        self._tip_pool: list[str] = list(_TIPS)  # 剪载剪载尝试顺序
        self._shown_tip: str = ""
        lay = self._root_layout()
        lay.addLayout(self._label_row(FIF.HELP, "小贴士  点击刷新"))

        initial = tip_text or self._pick_tip()
        self._tip_lbl = BodyLabel(initial)
        self._tip_lbl.setWordWrap(True)
        lay.addWidget(self._tip_lbl)
        lay.addStretch()

    def _pick_tip(self) -> str:
        """\u4ece尚未连续显示过的条目中随机选一条，避免立刻重复。"""
        pool = [t for t in _TIPS if t != self._shown_tip]
        tip  = random.choice(pool) if pool else random.choice(_TIPS)
        self._shown_tip = tip
        return tip

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        super().mousePressEvent(event)
        if event.button() == Qt.LeftButton:
            self._tip_lbl.setText(self._pick_tip())


# ─────────────────────────────────────────────────────────────────────────── #
# 10. EchoCard — 回声洞（打字机语录）
# ─────────────────────────────────────────────────────────────────────────── #

class EchoCard(_BaseCard):
    """
    回声洞：点击后随机抽取一条语录，以打字机动画（逐字出现 + 光标闪烁）
    形式展示；再次点击可刷新。默认为未展开状态，提示用户点击查看。
    """

    card_type = "echo"

    #: 打字速度（毫秒/字）
    _CHAR_INTERVAL = 45
    #: 光标闪烁周期（毫秒）
    _CURSOR_INTERVAL = 450
    #: 打字完成后光标继续闪烁的时长（毫秒）
    _CURSOR_LINGER = 2_500

    def __init__(self, navigate_to=None, parent=None):
        super().__init__(navigate_to, parent)
        self.setFixedSize(300, 130)

        lay = self._root_layout()
        lay.addLayout(self._label_row(FIF.CHAT, "回声洞  点击刷新"))

        self._text_lbl = BodyLabel("点击查看作者和朋友们的语录")
        self._text_lbl.setWordWrap(True)
        self._text_lbl.setStyleSheet("color: gray; font-style: italic;")
        lay.addWidget(self._text_lbl)
        lay.addStretch()

        self._full_text:    str  = ""
        self._current_pos:  int  = 0
        self._typing:       bool = False
        self._cursor_on:    bool = True
        self._ever_shown:   bool = False

        self._type_timer = QTimer(self)
        self._type_timer.setInterval(self._CHAR_INTERVAL)
        self._type_timer.timeout.connect(self._type_next)

        self._cursor_timer = QTimer(self)
        self._cursor_timer.setInterval(self._CURSOR_INTERVAL)
        self._cursor_timer.timeout.connect(self._blink)

    # ── 内部逻辑 ─────────────────────────────────────────────────────── #

    def _pick_echo(self) -> str:
        pool = [e for e in _ECHOES if e != self._full_text]
        return random.choice(pool) if pool else random.choice(_ECHOES)

    def _start_typing(self, text: str) -> None:
        """停止所有计时器，重新开始打字动画。"""
        self._type_timer.stop()
        self._cursor_timer.stop()

        self._full_text   = text
        self._current_pos = 0
        self._typing      = True
        self._cursor_on   = True

        # 切换为正常字体（去掉斜体提示样式）
        self._text_lbl.setStyleSheet("")
        self._text_lbl.setText("|")   # 仅光标，像等待输入

        self._type_timer.start()
        self._cursor_timer.start()

    def _type_next(self) -> None:
        """每帧追加一个字符。"""
        self._current_pos += 1
        if self._current_pos >= len(self._full_text):
            self._type_timer.stop()
            self._typing = False
            # 打字完成后光标再闪 _CURSOR_LINGER ms 然后停
            QTimer.singleShot(self._CURSOR_LINGER, self._stop_cursor)
        self._render()

    def _blink(self) -> None:
        self._cursor_on = not self._cursor_on
        self._render()

    def _render(self) -> None:
        shown  = self._full_text[:self._current_pos]
        cursor = "|" if self._cursor_on else ""
        self._text_lbl.setText(shown + cursor)

    def _stop_cursor(self) -> None:
        self._cursor_timer.stop()
        self._cursor_on = False
        self._render()

    # ── 交互 ─────────────────────────────────────────────────────────── #

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        super().mousePressEvent(event)
        if event.button() == Qt.LeftButton:
            self._ever_shown = True
            self._start_typing(self._pick_echo())


# ─────────────────────────────────────────────────────────────────────────── #
# 11. StatsCard — 使用统计摘要卡片
# ─────────────────────────────────────────────────────────────────────────── #

class StatsCard(_BaseCard):
    """展示使用统计摘要：最多使用的功能 Top3。"""

    card_type = "stats"

    def __init__(self, ranked: list[tuple[str, float]], navigate_to=None, parent=None):
        super().__init__(navigate_to, parent)
        self.setFixedSize(300, 160)
        lay = self._root_layout()
        lay.addLayout(self._label_row(FIF.LAYOUT, "使用统计"))

        top3 = ranked[:3]
        if not top3:
            lay.addWidget(CaptionLabel("暂无使用记录"))
        else:
            medals = ["#1", "#2", "#3"]
            for rank, (fid, score) in enumerate(top3, 1):
                fif  = _FEATURE_FIF.get(fid, FIF.FLAG)
                name = _get_feature_name(fid)
                row  = QHBoxLayout()
                medal_lbl = CaptionLabel(medals[rank - 1])
                medal_lbl.setFixedWidth(20)
                medal_lbl.setStyleSheet("color:gray;font-weight:bold;")
                icon_w = IconWidget(fif)
                icon_w.setFixedSize(14, 14)
                row.addWidget(medal_lbl)
                row.addWidget(icon_w)
                row.addSpacing(4)
                row.addWidget(BodyLabel(name))
                row.addStretch()
                wrap = QWidget()
                wrap.setLayout(row)
                lay.addWidget(wrap)

        lay.addStretch()


# ─────────────────────────────────────────────────────────────────────────── #
# 11. FullscreenClockCard — 世界时钟全屏推荐
# ─────────────────────────────────────────────────────────────────────────── #

class FullscreenClockCard(_BaseCard):
    """推荐某个世界时区的全屏时钟，含实时时间显示和快速开启按钮。"""

    card_type = "fullscreen_clock"

    def __init__(self, zone, clock_service=None, plugin_manager=None,
                 notification_service=None, navigate_to=None, parent=None,
                 reason: str = ""):
        super().__init__(navigate_to, parent)
        self.setFixedHeight(176)
        self._zone        = zone
        self._clock_svc   = clock_service
        self._plugin_mgr  = plugin_manager
        self._notif_svc   = notification_service

        lay = self._root_layout()
        lay.addLayout(self._label_row(FIF.GLOBE, "世界时钟"))

        # 时区名称
        zone_lbl = BodyLabel(zone.label or zone.timezone)
        zone_lbl.setStyleSheet("font-weight:bold;font-size:14px;")
        lay.addWidget(zone_lbl)

        # 实时当前时间
        self._time_lbl = SubtitleLabel(self._current_time())
        time_font = self._time_lbl.font()
        time_font.setPointSize(24)
        time_font.setBold(True)
        self._time_lbl.setFont(time_font)
        self._time_lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._time_lbl.setMinimumHeight(56)
        lay.addWidget(self._time_lbl)

        if reason:
            reason_lbl = CaptionLabel(f"💡 {reason}")
            reason_lbl.setStyleSheet("color: gray; font-size: 10px;")
            reason_lbl.setWordWrap(True)
            lay.addWidget(reason_lbl)

        lay.addStretch()

        # 按钮行
        btn_row = QHBoxLayout()
        open_btn = PrimaryPushButton("开启全屏时钟")
        open_btn.setFixedHeight(28)
        open_btn.clicked.connect(self._open_fullscreen)
        btn_row.addWidget(open_btn)
        nav_btn = TransparentPushButton("前往世界时间")
        nav_btn.setFixedHeight(28)
        nav_btn.clicked.connect(lambda: self._nav("world_time"))
        btn_row.addWidget(nav_btn)
        lay.addLayout(btn_row)

        # 每秒刷新时间显示
        self._tick = QTimer(self)
        self._tick.setInterval(1_000)
        self._tick.timeout.connect(lambda: self._time_lbl.setText(self._current_time()))
        self._tick.start()

    def _current_time(self) -> str:
        try:
            import zoneinfo
            from datetime import datetime as _dt
            tz_name = self._zone.timezone
            tz = None if tz_name == "local" else zoneinfo.ZoneInfo(tz_name)
            return _dt.now(tz).strftime("%H:%M:%S")
        except Exception:
            return datetime.now().strftime("%H:%M:%S")

    def _open_fullscreen(self) -> None:
        try:
            from app.views.world_time_view import FullscreenClockWindow
            # 必须保留实例引用，防止 Python GC 在 show() 之后翌放窗口
            self._fs_win = FullscreenClockWindow(
                self._zone,
                self._clock_svc,
                self._plugin_mgr,
                self._notif_svc,
            )
            self._fs_win.show()
            screen = self._fs_win.screen()
            if screen:
                self._fs_win.setGeometry(screen.geometry())
            self._fs_win.showFullScreen()
        except Exception:
            self._nav("world_time")


# ─────────────────────────────────────────────────────────────────────────── #
# 工厂函数（供调试面板批量创建 demo 卡片）
# ─────────────────────────────────────────────────────────────────────────── #

def make_demo_cards(navigate_to=None) -> list[_BaseCard]:
    """
    创建所有类型卡片的 Demo 实例，用于调试面板预览。
    不依赖任何运行时服务，使用占位数据。
    """
    from app.models.focus_model import FocusPreset

    dummy_preset = FocusPreset(
        name="番茄25",
        focus_minutes=25,
        break_minutes=5,
        cycles=4,
    )

    class _FakeFocusSvc:
        """最小化 FocusService 接口，避免真实服务依赖"""
        class tick:
            @staticmethod
            def connect(_): pass
        class sessionFinished:
            @staticmethod
            def connect(_): pass

    class _FakeTimerItem:
        id       = "demo-timer"
        label    = "番茄工作法"
        total_ms = 25 * 60 * 1000
        remaining = 18 * 60 * 1000 + 37_000
        running  = True
        done     = False
        progress = 1 - remaining / total_ms
        class updated:
            @staticmethod
            def connect(_): pass
        class finished:
            @staticmethod
            def connect(_): pass

    ranked_demo = [
        ("timer", 0.85),
        ("focus", 0.72),
        ("stopwatch", 0.58),
    ]

    from app.models.world_zone import WorldZone as _WZ
    demo_zone = _WZ(label="北京", timezone="Asia/Shanghai")

    cards: list[_BaseCard] = [
        GreetingCard(navigate_to),
        # ── 活跃状态卡片 ──
        ActiveTimerCard(_FakeTimerItem(), navigate_to),
        ActiveStopwatchCard(
            elapsed_ms_getter=lambda: 185_430,
            is_running_getter=lambda: True,
            navigate_to=navigate_to,
        ),
        ActiveFocusCard(_FakeFocusSvc(), navigate_to),
        # ── 下一个闹钟 ──
        NextAlarmCard("起床", "07:00", 420, navigate_to),
        # ── 快速启动卡（含推荐原因）──
        QuickTimerCard("喝水提醒", 30 * 60 * 1000, navigate_to,
                       reason="你通常在下午使用计时器"),
        QuickFocusCard(dummy_preset, navigate_to,
                       reason="番茄25是你最常使用的专注预设"),
        FullscreenClockCard(demo_zone, navigate_to=navigate_to,
                            reason="你最近频繁查看世界时间"),
        # ── 通用跳转卡（含推荐原因）──
        QuickActionCard("world_time", "你已经很久没看世界时间了", navigate_to),
        QuickActionCard("automation", "试试自动化规则，解放双手", navigate_to),
        QuickActionCard("alarm", "设置闹钟，不再错过重要时刻", navigate_to),
        QuickActionCard("stopwatch", "还没试过秒表？来探索一下吧", navigate_to),
        # ── 小贴士 & 统计 ──
        TipCard("", navigate_to),
        EchoCard(navigate_to),
        StatsCard(ranked_demo, navigate_to),
    ]
    return cards

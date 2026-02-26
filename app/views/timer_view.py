"""计时器视图（倒计时）"""
from __future__ import annotations

from datetime import datetime, timedelta

from PySide6.QtCore import Qt, QPoint, Slot, Signal, QObject
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QWidget,
)
from qfluentwidgets import (
    FluentIcon as FIF, PushButton, ToolButton,
    TitleLabel, SubtitleLabel, BodyLabel, CaptionLabel,
    CardWidget, LineEdit, InfoBar, InfoBarPosition,
    ProgressBar, ProgressRing,
    TransparentPushButton, TransparentToolButton, MessageBox,
    isDarkTheme, qconfig,
)

from app.services.clock_service import ClockService
from app.services.notification_service import NotificationService
from app.services.settings_service import SettingsService
from app.services import ringtone_service as rs
from app.utils.time_utils import format_duration, load_json, save_json
from app.constants import TIMER_TICK_MS, TIMER_CONFIG
from app.views.duration_picker import DurationPicker


# --------------------------------------------------------------------------- #
# 单个计时器（数据 + 逻辑）
# --------------------------------------------------------------------------- #

class TimerItem(QObject):
    """单条计时器状态机"""

    updated  = Signal()
    finished = Signal(str)   # timer_id

    def __init__(self, timer_id: str, label: str, total_ms: int, sound: str = ""):
        super().__init__()
        self.id        = timer_id
        self.label     = label
        self.total_ms  = total_ms
        self.sound     = sound      # 选择的铃声文件路径，""表示系统默认
        self.remaining = total_ms   # 毫秒
        self.running   = False
        self.done      = False

    def tick(self) -> None:
        if not self.running or self.done:
            return
        self.remaining = max(0, self.remaining - TIMER_TICK_MS)
        self.updated.emit()
        if self.remaining == 0:
            self.running = False
            self.done    = True
            self.finished.emit(self.id)
            try:
                from app.events import EventBus, EventType
                EventBus.emit(EventType.TIMER_DONE, timer_id=self.id, label=self.label)
            except Exception:
                pass

    def start(self) -> None:
        if not self.done:
            self.running = True
            self.updated.emit()
            try:
                from app.events import EventBus, EventType
                EventBus.emit(EventType.TIMER_STARTED, timer_id=self.id, label=self.label,
                              total_ms=self.total_ms)
            except Exception:
                pass

    def pause(self) -> None:
        self.running = False
        self.updated.emit()
        try:
            from app.events import EventBus, EventType
            EventBus.emit(EventType.TIMER_PAUSED, timer_id=self.id, label=self.label)
        except Exception:
            pass

    def reset(self) -> None:
        self.remaining = self.total_ms
        self.running   = False
        self.done      = False
        self.updated.emit()
        try:
            from app.events import EventBus, EventType
            EventBus.emit(EventType.TIMER_RESET, timer_id=self.id, label=self.label)
        except Exception:
            pass

    @property
    def progress(self) -> float:
        if self.total_ms == 0:
            return 0.0
        return 1.0 - self.remaining / self.total_ms

    def to_dict(self) -> dict:
        return {
            "id":        self.id,
            "label":     self.label,
            "total_ms":  self.total_ms,
            "remaining": self.remaining,
            "sound":     self.sound,
            "done":      self.done,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TimerItem":
        item = cls(d["id"], d["label"], d["total_ms"], d.get("sound", ""))
        item.remaining = d.get("remaining", d["total_ms"])
        item.done      = d.get("done", False)
        return item


# --------------------------------------------------------------------------- #
# 全局共享计时器字典（供画布计时器组件访问活跃实例）
# --------------------------------------------------------------------------- #

_shared_items: dict[str, "TimerItem"] = {}


# --------------------------------------------------------------------------- #
# 计时器悬浮小窗
# --------------------------------------------------------------------------- #

class TimerFloatWindow(QWidget):
    """方形悬浮小窗：进度环 + 时间 + 暂停/重置按钮"""

    def __init__(self, item: TimerItem, parent=None):
        super().__init__(parent, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._item = item
        self._settings = SettingsService.instance()
        self._drag_pos: QPoint | None = None

        self._build_ui()
        self._apply_card_style()
        item.updated.connect(self._refresh)
        item.finished.connect(lambda _: self._on_finished())
        self._settings.changed.connect(self._refresh)
        self._settings.changed.connect(self._apply_card_style)
        qconfig.themeChangedFinished.connect(self._apply_card_style)

    def _build_ui(self) -> None:
        WINDOW_SIZE = 200
        self.setFixedSize(WINDOW_SIZE, WINDOW_SIZE)

        # 背景卡片
        self._card = QWidget(self)
        self._card.setObjectName("floatCard")
        self._card.setFixedSize(WINDOW_SIZE, WINDOW_SIZE)

        outer = QVBoxLayout(self._card)
        outer.setContentsMargins(12, 10, 12, 12)
        outer.setSpacing(6)

        # 标题行（标签 + 关闭按钮）
        title_row = QHBoxLayout()
        self._title_lbl = CaptionLabel(self._item.label or "计时器")
        close_btn = TransparentToolButton(FIF.CLOSE)
        close_btn.setFixedSize(20, 20)
        close_btn.clicked.connect(self.close)
        title_row.addWidget(self._title_lbl, 1)
        title_row.addWidget(close_btn)
        outer.addLayout(title_row)

        # 进度环 + 时间叠加层
        RING_SIZE = 120
        ring_container = QWidget()
        ring_container.setFixedSize(RING_SIZE, RING_SIZE)
        ring_container.setStyleSheet("background:transparent;")

        self._ring = ProgressRing(ring_container)
        self._ring.setFixedSize(RING_SIZE, RING_SIZE)
        self._ring.setRange(0, 1000)
        self._ring.setValue(int(self._item.progress * 1000))
        self._ring.setTextVisible(False)
        self._ring.setStrokeWidth(8)
        self._ring.move(0, 0)

        self._time_lbl = SubtitleLabel(
            format_duration(self._item.remaining, self._settings.timer_precision),
            ring_container,
        )
        self._time_lbl.setAlignment(Qt.AlignCenter)
        self._time_lbl.setFixedSize(RING_SIZE, RING_SIZE)
        self._time_lbl.setStyleSheet("background:transparent;")
        self._time_lbl.move(0, 0)
        self._time_lbl.raise_()

        ring_row = QHBoxLayout()
        ring_row.addStretch()
        ring_row.addWidget(ring_container)
        ring_row.addStretch()
        outer.addLayout(ring_row, 1)

        # 按钮行（仅图标）
        btn_row = QHBoxLayout()
        btn_row.setSpacing(16)
        self._toggle_btn = TransparentToolButton(
            FIF.PAUSE if self._item.running else FIF.PLAY
        )
        self._toggle_btn.setFixedSize(32, 32)
        self._toggle_btn.setToolTip("开始/暂停")
        self._reset_btn = TransparentToolButton(FIF.SYNC)
        self._reset_btn.setFixedSize(32, 32)
        self._reset_btn.setToolTip("重置")
        if self._item.done:
            self._toggle_btn.setEnabled(False)
        self._toggle_btn.clicked.connect(self._toggle)
        self._reset_btn.clicked.connect(self._on_reset)
        btn_row.addStretch()
        btn_row.addWidget(self._toggle_btn)
        btn_row.addWidget(self._reset_btn)
        btn_row.addStretch()
        outer.addLayout(btn_row)

    def _apply_card_style(self) -> None:
        """根据深浅色主题切换背景和文字颜色，并应用透明度"""
        dark = isDarkTheme()
        if dark:
            bg      = "rgb(30,30,30)"
            title_c = "rgba(255,255,255,160)"
            time_c  = "white"
        else:
            bg      = "rgb(248,248,248)"
            title_c = "rgba(0,0,0,140)"
            time_c  = "#1a1a1a"
        self._card.setStyleSheet(
            f"QWidget#floatCard{{background:{bg};border-radius:16px;}}"
        )
        self._title_lbl.setStyleSheet(f"color:{title_c};")
        self._time_lbl.setStyleSheet(f"color:{time_c};background:transparent;")
        # TransparentToolButton 由 qfluentwidgets 自行处理图标颜色，不触动其 stylesheet
        # 窗口整体透明度（100% = 完全不透明）
        opacity = self._settings.float_opacity / 100.0
        self.setWindowOpacity(max(0.1, min(1.0, opacity)))

    # ---- 状态同步 ----

    def _toggle(self) -> None:
        if self._item.running:
            self._item.pause()
            self._toggle_btn.setIcon(FIF.PLAY)
        elif not self._item.done:
            self._item.start()
            self._toggle_btn.setIcon(FIF.PAUSE)

    def _on_reset(self) -> None:
        self._item.reset()
        self._toggle_btn.setEnabled(True)
        self._toggle_btn.setIcon(FIF.PLAY)
        self._ring.setValue(0)

    def _refresh(self) -> None:
        self._time_lbl.setText(format_duration(self._item.remaining, self._settings.timer_precision))
        self._ring.setValue(int(self._item.progress * 1000))
        # 始终与 item 状态同步按钮图标
        if self._item.running:
            self._toggle_btn.setIcon(FIF.PAUSE)
        elif not self._item.done:
            self._toggle_btn.setIcon(FIF.PLAY)

    def _on_finished(self) -> None:
        self._time_lbl.setText(format_duration(0, self._settings.timer_precision))
        self._ring.setValue(1000)
        self._toggle_btn.setEnabled(False)

    # ---- 拖拽移动 ----

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_pos is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_pos = None
        super().mouseReleaseEvent(event)


# --------------------------------------------------------------------------- #
# 计时器创建对话框
# --------------------------------------------------------------------------- #

class TimerDialog(MessageBox):
    """新建计时器弹窗"""

    def __init__(self, parent=None):
        super().__init__("添加计时器", "", parent)
        self.yesButton.setText("开始")
        self.cancelButton.setText("取消")
        self.contentLabel.hide()

        form = QWidget()
        fl = QVBoxLayout(form)
        fl.setSpacing(10)
        fl.setContentsMargins(0, 0, 0, 0)

        # 标签
        lb_row = QHBoxLayout()
        lb_row.addWidget(BodyLabel("标签："))
        self._label_edit = LineEdit()
        self._label_edit.setPlaceholderText("计时器（可不填）")
        lb_row.addWidget(self._label_edit, 1)
        fl.addLayout(lb_row)

        # 时长
        dur_row = QHBoxLayout()
        dur_row.addWidget(BodyLabel("时长："))
        self._duration_picker = DurationPicker(showSeconds=True)
        # self._duration_picker.setTotalSeconds(25 * 60)   # 默认 25 分钟
        dur_row.addWidget(self._duration_picker, 1)
        fl.addLayout(dur_row)

        # 铃声
        snd_row = QHBoxLayout()
        snd_row.addWidget(BodyLabel("铃声："))
        from app.services.settings_service import SettingsService
        self._sound_combo = rs.make_sound_combo(SettingsService.instance().ringtones)
        snd_row.addWidget(self._sound_combo, 1)
        fl.addLayout(snd_row)

        self.textLayout.addWidget(form)

        # 默认光标到时长选择器
        self._duration_picker.setFocus()

    def get_params(self) -> tuple[str, int, str] | None:
        """
        返回 (label, total_ms, sound_path)。
        输入无效时返回 None。
        """
        ms = self._duration_picker.totalMs()
        if ms <= 0:
            return None
        label = self._label_edit.text().strip()
        sound = rs.get_combo_sound(self._sound_combo)
        return label, ms, sound


# --------------------------------------------------------------------------- #
# 单条计时器卡片
# --------------------------------------------------------------------------- #

class TimerCard(CardWidget):
    requestDelete = Signal(str)   # timer_id

    def __init__(self, item: TimerItem, parent=None):
        super().__init__(parent)
        self._item = item
        self._settings = SettingsService.instance()
        self._float_win: TimerFloatWindow | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 14, 20, 14)
        root.setSpacing(8)

        # 标签行
        top = QHBoxLayout()
        self.label_lbl = BodyLabel(item.label)
        popup_btn = ToolButton(FIF.MINIMIZE)
        popup_btn.setToolTip("悬浮小窗")
        popup_btn.clicked.connect(self._open_float)
        del_btn = ToolButton(FIF.DELETE)
        del_btn.clicked.connect(lambda: self.requestDelete.emit(item.id))
        top.addWidget(self.label_lbl, 1)
        top.addWidget(popup_btn)
        top.addWidget(del_btn)
        root.addLayout(top)

        # 时间显示
        self.time_lbl = TitleLabel(format_duration(item.remaining, self._settings.timer_precision))
        self.time_lbl.setAlignment(Qt.AlignCenter)
        root.addWidget(self.time_lbl)

        # 进度条
        self.progress_bar = ProgressBar()
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)
        root.addWidget(self.progress_bar)

        # 预计完成时间
        self.eta_lbl = CaptionLabel("")
        self.eta_lbl.setAlignment(Qt.AlignCenter)
        self.eta_lbl.hide()
        root.addWidget(self.eta_lbl)

        # 按钮行
        btn_row = QHBoxLayout()
        self.start_btn = PushButton(FIF.PLAY, "开始")
        self.reset_btn = TransparentPushButton(FIF.SYNC, "重置")
        self.start_btn.clicked.connect(self._toggle)
        self.reset_btn.clicked.connect(self._on_reset)
        btn_row.addWidget(self.start_btn)
        btn_row.addWidget(self.reset_btn)
        root.addLayout(btn_row)

        self.setFixedHeight(190)
        item.updated.connect(self._refresh)
        item.finished.connect(lambda _: self._on_finished())
        self._settings.changed.connect(self._refresh)

        # ── 恢复持久化状态（重启后同步进度条与按钮文字）──
        self.progress_bar.setValue(int(item.progress * 1000))
        if item.done:
            self.start_btn.setEnabled(False)
            self.start_btn.setText("已结束")
        elif item.remaining < item.total_ms:
            self.start_btn.setText("继续")

    def _toggle(self) -> None:
        if self._item.running:
            self._item.pause()
            self.start_btn.setIcon(FIF.PLAY)
            self.start_btn.setText("继续")
            self._update_eta()
        elif not self._item.done:
            self._item.start()
            self.start_btn.setIcon(FIF.PAUSE)
            self.start_btn.setText("暂停")
            self._update_eta()

    def _refresh(self) -> None:
        self.time_lbl.setText(format_duration(self._item.remaining, self._settings.timer_precision))
        # 更新进度条（0~1000）
        self.progress_bar.setValue(int(self._item.progress * 1000))
        # 始终与 item 状态同步按钮
        if self._item.running:
            self.start_btn.setIcon(FIF.PAUSE)
            self.start_btn.setText("暂停")
        elif not self._item.done:
            self.start_btn.setIcon(FIF.PLAY)
            self.start_btn.setText("开始" if self._item.remaining == self._item.total_ms else "继续")
        # 更新预计完成时间
        self._update_eta()

    def _update_eta(self) -> None:
        """仅在运行中时显示预计完成时间，跨天时标注天数偏移"""
        if self._item.running and not self._item.done:
            now = datetime.now()
            eta = now + timedelta(milliseconds=self._item.remaining)
            days_diff = (eta.date() - now.date()).days
            if days_diff == 0:
                suffix = ""
            elif days_diff == 1:
                suffix = "（+1天）"
            else:
                suffix = f"（+{days_diff}天）"
            self.eta_lbl.setText(f"预计 {eta.strftime('%H:%M:%S')} 结束{suffix}")
            self.eta_lbl.show()
        else:
            self.eta_lbl.hide()

    def _on_reset(self) -> None:
        self._item.reset()
        self.start_btn.setEnabled(True)
        self.start_btn.setIcon(FIF.PLAY)
        self.start_btn.setText("开始")
        self.progress_bar.setValue(0)
        self.eta_lbl.hide()

    def _on_finished(self) -> None:
        self.time_lbl.setText(format_duration(0, self._settings.timer_precision))
        self.progress_bar.setValue(1000)
        self.start_btn.setEnabled(False)
        self.start_btn.setText("已结束")
        self.eta_lbl.hide()

    def _open_float(self) -> None:
        """打开/聚焦悬浮小窗"""
        if self._float_win is None or not self._float_win.isVisible():
            self._float_win = TimerFloatWindow(self._item)
            # 居中于卡片所在屏幕
            geo = self.window().geometry()
            fw = self._float_win
            fw.move(
                geo.center().x() - fw.width() // 2,
                geo.center().y() - fw.height() // 2,
            )
            self._float_win.show()
        else:
            self._float_win.raise_()
            self._float_win.activateWindow()


# --------------------------------------------------------------------------- #
# 计时器主视图
# --------------------------------------------------------------------------- #

class TimerView(QWidget):
    def __init__(
        self,
        clock_service: ClockService,
        notif_service: NotificationService,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("timerView")
        self.setAutoFillBackground(False)
        self._notif   = notif_service
        self._clock   = clock_service
        self._items: dict[str, TimerItem] = {}
        self._counter = 0
        self._save_tick = 0

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 16, 24, 16)
        root.setSpacing(10)
        root.addWidget(TitleLabel("计时器"))
        # 工具栏：仅保留“添加计时器”按鈕
        bar = QHBoxLayout()
        add_btn = PushButton(FIF.ADD, "添加计时器")
        add_btn.clicked.connect(self._on_add)
        bar.addStretch()
        bar.addWidget(add_btn)
        root.addLayout(bar)

        # 卡片滚动区
        from qfluentwidgets import ScrollArea
        self._scroll = ScrollArea()
        self._scroll.setWidgetResizable(True)
        inner = QWidget()
        self._cards_layout = QVBoxLayout(inner)
        self._cards_layout.setSpacing(8)
        self._cards_layout.addStretch()
        self._scroll.setWidget(inner)
        self._scroll.enableTransparentBackground()
        root.addWidget(self._scroll, 1)

        clock_service.tick.connect(self._on_tick)
        self._load_timers()

    # ------------------------------------------------------------------ #

    def _save_timers(self) -> None:
        save_json(TIMER_CONFIG, [item.to_dict() for item in self._items.values()])

    def _load_timers(self) -> None:
        data = load_json(TIMER_CONFIG, default=[])
        if not isinstance(data, list):
            return
        layout = self._scroll.widget().layout()
        for d in data:
            try:
                item = TimerItem.from_dict(d)
            except Exception:
                continue
            item.finished.connect(self._on_timer_done)
            card = TimerCard(item)
            card.requestDelete.connect(self._on_delete)
            self._items[item.id] = item
            _shared_items[item.id] = item
            layout.insertWidget(layout.count() - 1, card)
            # 同步计数器，避免新增 ID 冲突
            num_str = item.id.lstrip("t")
            if num_str.isdigit():
                self._counter = max(self._counter, int(num_str))

    @Slot()
    def _on_add(self) -> None:
        dlg = TimerDialog(parent=self.window())
        if not dlg.exec():
            return

        params = dlg.get_params()
        if params is None:
            InfoBar.error("输入无效", "请输入正确的时长，如 05:00",
                          parent=self.window(),
                          position=InfoBarPosition.TOP_RIGHT, duration=3000)
            return

        label_text, ms, sound = params
        self._counter += 1
        label = label_text or f"计时器 {self._counter}"
        item  = TimerItem(f"t{self._counter}", label, ms, sound=sound)
        item.finished.connect(self._on_timer_done)

        card = TimerCard(item)
        card.requestDelete.connect(self._on_delete)
        self._items[item.id] = item
        _shared_items[item.id] = item

        layout = self._scroll.widget().layout()
        layout.insertWidget(layout.count() - 1, card)  # 插到 stretch 前
        self._save_timers()

    def _on_delete(self, timer_id: str) -> None:
        self._items.pop(timer_id, None)
        _shared_items.pop(timer_id, None)
        layout = self._scroll.widget().layout()
        for i in range(layout.count()):
            w = layout.itemAt(i).widget()
            if isinstance(w, TimerCard) and w._item.id == timer_id:
                layout.removeWidget(w)
                w.deleteLater()
                break
        self._save_timers()

    @Slot(str)
    def _on_timer_done(self, timer_id: str) -> None:
        from app.utils.logger import logger
        item = self._items.get(timer_id)
        logger.warning("[计时器] 完成：{} | item={} | sound={}",
                       timer_id, item, item.sound if item else 'NO ITEM')
        label = item.label if item else "计时器"
        # 播放铃声
        if item and item.sound:
            rs.play_sound(item.sound)
        else:
            rs.play_default()
        self._notif.show("⏱ 计时器", f"「{label}」已结束！")
        InfoBar.success(
            title="⏱ 计时器结束",
            content=f"「{label}」已结束！",
            position=InfoBarPosition.TOP_RIGHT,
            duration=5000,
            parent=self.window(),
        )
        self._save_timers()

    @Slot()
    def _on_tick(self) -> None:
        for item in self._items.values():
            item.tick()
        # 每 ~1 秒定期持久化计时器状态
        self._save_tick += 1
        if self._save_tick >= 100:
            self._save_tick = 0
            self._save_timers()


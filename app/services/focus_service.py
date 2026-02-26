"""
专注时钟服务

职责
----
1. 管理专注会话的生命周期（专注阶段 / 休息阶段 / 循环）
2. 根据专注规则持续检测"是否专注"：
   - MUST_USE_PC：监听全局鼠标/键盘活动，超时无活动 → 不专注
   - FOCUSED_APP：轮询前台窗口标题，焦点离开目标程序 → 不专注
   - NO_PC_USE  ：监听全局鼠标/键盘活动，有活动 → 不专注
3. 不专注持续时间超过 tolerance_sec 后发出 distractedAlert 信号
4. 阶段结束发出 phaseFinished；全部循环结束发出 sessionFinished
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import time
from enum import Enum, auto
from typing import Optional

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from app.models.focus_model import FocusPreset, FocusRule
from app.utils.logger import logger


# ──────────────────────────────────────────────────────────────────────────── #
# 辅助：获取当前前台窗口标题（Windows 专属；其他平台返回空字符串）
# ──────────────────────────────────────────────────────────────────────────── #

def _get_foreground_window_title() -> str:
    try:
        user32 = ctypes.windll.user32
        hwnd   = user32.GetForegroundWindow()
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return ""
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value
    except Exception:
        return ""


# ──────────────────────────────────────────────────────────────────────────── #
# 会话阶段
# ──────────────────────────────────────────────────────────────────────────── #

class FocusPhase(Enum):
    IDLE    = auto()   # 未开始
    FOCUS   = auto()   # 专注中
    BREAK   = auto()   # 休息中
    DONE    = auto()   # 全部完成


# ──────────────────────────────────────────────────────────────────────────── #
# 专注服务
# ──────────────────────────────────────────────────────────────────────────── #

class FocusService(QObject):
    """
    信号
    ----
    tick(elapsed_ms, remaining_ms, phase)      — 每秒刷新（供 UI 显示进度）
    phaseChanged(phase, cycle_index)           — 阶段切换
    distractedAlert(distracted_sec)            — 不专注超限警告
    distractedStateChanged(is_distracted)      — 是否不专注状态变化（供 UI 染色）
    phaseFinished(phase)                       — 某阶段结束
    sessionFinished()                          — 全部循环结束
    """

    tick                = Signal(int, int, object)   # elapsed_ms, remaining_ms, FocusPhase
    phaseChanged        = Signal(object, int)         # FocusPhase, cycle_index (0-based)
    distractedAlert     = Signal(int)                 # distracted_sec
    distractedStateChanged = Signal(bool)             # is_distracted
    phaseFinished       = Signal(object)              # FocusPhase
    sessionFinished     = Signal()

    # 服务级单例：只需一个 pynput 监听器
    _instance: Optional["FocusService"] = None

    @classmethod
    def instance(cls) -> "FocusService":
        if cls._instance is None:
            cls._instance = FocusService()
        return cls._instance

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)

        self._preset:          Optional[FocusPreset] = None
        self._phase:           FocusPhase = FocusPhase.IDLE
        self._cycle_index:     int = 0        # 当前第几个循环（0-based）
        self._phase_elapsed_ms:int = 0        # 本阶段已过毫秒
        self._phase_total_ms:  int = 0        # 本阶段总毫秒

        # 不专注跟踪
        self._last_activity_time: float = 0.0   # 最后活动时间（time.monotonic）
        self._distracted_sec:     int   = 0      # 累计不专注秒数
        self._is_distracted:      bool  = False
        self._alert_fired:        bool  = False  # 本次不专注已发过警告
        self._paused_by_distraction: bool = False  # 是否因超限不专注而暂停

        # pynput 监听器（全局）
        self._mouse_listener  = None
        self._kb_listener     = None
        self._listeners_active = False

        # 主轮询定时器（1 秒）
        self._timer = QTimer(self)
        self._timer.setInterval(1_000)
        self._timer.timeout.connect(self._tick)

        # 不专注专用检测定时器（主计时器暂停时依然运行）
        self._distract_check_timer = QTimer(self)
        self._distract_check_timer.setInterval(500)
        self._distract_check_timer.timeout.connect(self._check_distraction_only)

    # ------------------------------------------------------------------ #
    # 公共接口
    # ------------------------------------------------------------------ #

    @property
    def phase(self) -> FocusPhase:
        return self._phase

    @property
    def cycle_index(self) -> int:
        return self._cycle_index

    @property
    def is_running(self) -> bool:
        return self._phase in (FocusPhase.FOCUS, FocusPhase.BREAK)

    @property
    def is_distracted(self) -> bool:
        return self._is_distracted

    @property
    def distracted_sec(self) -> int:
        """当前不专注已持续秒数"""
        return self._distracted_sec

    @property
    def is_paused_by_distraction(self) -> bool:
        """是否因超限不专注而暂停"""
        return self._paused_by_distraction

    def start(self, preset: FocusPreset) -> None:
        """启动一个专注会话"""
        if self.is_running:
            self.stop()
        self._preset       = preset
        self._cycle_index  = 0
        self._start_phase(FocusPhase.FOCUS)
        if preset.detect_focus and preset.rule in (FocusRule.MUST_USE_PC, FocusRule.NO_PC_USE):
            self._start_listeners()
        self._timer.start()
        try:
            from app.events import EventBus, EventType
            EventBus.emit(EventType.FOCUS_STARTED, total_cycles=preset.cycles or 1,
                          preset_name=preset.name)
        except Exception:
            pass
        if preset.detect_focus:
            logger.info("[专注] 会话启动：{} | 规则：{}", preset.name, preset.rule)
        else:
            logger.info("[专注] 会话启动：{} | 不检测专注状态", preset.name)

    def stop(self) -> None:
        """强制停止会话"""
        self._timer.stop()
        self._distract_check_timer.stop()
        self._stop_listeners()
        old_phase   = self._phase
        self._phase = FocusPhase.IDLE
        self._reset_distracted()
        logger.info("[专注] 会话停止，前阶段：{}", old_phase)

    def pause(self) -> None:
        """暂停计时（不影响监听）"""
        self._timer.stop()

    def resume(self) -> None:
        """恢复计时"""
        if self.is_running:
            self._distract_check_timer.stop()
            self._timer.start()

    # ------------------------------------------------------------------ #
    # 阶段管理
    # ------------------------------------------------------------------ #

    def _start_phase(self, phase: FocusPhase) -> None:
        self._phase            = phase
        self._phase_elapsed_ms = 0
        self._reset_distracted()
        if phase == FocusPhase.FOCUS:
            self._phase_total_ms = (self._preset.focus_minutes or 25) * 60_000
        else:
            self._phase_total_ms = (self._preset.break_minutes or 5) * 60_000
        self.phaseChanged.emit(phase, self._cycle_index)
        try:
            from app.events import EventBus, EventType
            EventBus.emit(EventType.FOCUS_PHASE_CHANGED,
                          phase=phase.name.lower(), cycle_index=self._cycle_index)
        except Exception:
            pass
        logger.info("[专注] 阶段开始：{} | 循环 {}", phase, self._cycle_index)

    def _finish_phase(self) -> None:
        self.phaseFinished.emit(self._phase)
        if self._phase == FocusPhase.FOCUS:
            # 有休息时间 → 进入休息；否则直接下一循环
            if self._preset and self._preset.break_minutes > 0:
                self._start_phase(FocusPhase.BREAK)
                return
        # 休息完毕 / 无休息 → 检查循环
        self._cycle_index += 1
        max_cycles = self._preset.cycles if self._preset else 1
        if max_cycles > 0 and self._cycle_index >= max_cycles:
            self._phase = FocusPhase.DONE
            self._timer.stop()
            self._distract_check_timer.stop()
            self._stop_listeners()
            self.sessionFinished.emit()
            try:
                from app.events import EventBus, EventType
                EventBus.emit(EventType.FOCUS_ENDED)
            except Exception:
                pass
            logger.info("[专注] 会话全部完成，共 {} 循环", self._cycle_index)
        else:
            self._start_phase(FocusPhase.FOCUS)

    # ------------------------------------------------------------------ #
    # 主 tick
    # ------------------------------------------------------------------ #

    @Slot()
    def _tick(self) -> None:
        if not self.is_running or self._preset is None:
            return

        self._phase_elapsed_ms += 1_000
        remaining = max(0, self._phase_total_ms - self._phase_elapsed_ms)

        # 检测是否不专注
        self._check_distraction()

        self.tick.emit(self._phase_elapsed_ms, remaining, self._phase)

        if remaining == 0:
            self._finish_phase()

    # ------------------------------------------------------------------ #
    # 不专注检测
    # ------------------------------------------------------------------ #

    def _detect_distraction_state(self) -> bool:
        """计算当前是否处于不专注状态（仅判断，不计数）"""
        if self._preset is None:
            return False
        rule = self._preset.rule

        if rule == FocusRule.MUST_USE_PC:
            idle_sec = time.monotonic() - self._last_activity_time
            currently_distracted = (idle_sec > 1.5)

        elif rule == FocusRule.NO_PC_USE:
            idle_sec = time.monotonic() - self._last_activity_time
            currently_distracted = (idle_sec <= 1.5)

        elif rule == FocusRule.FOCUSED_APP:
            title   = _get_foreground_window_title().lower()
            keyword = (self._preset.app_name_filter or "").lower().strip()
            currently_distracted = bool(keyword) and keyword not in title

        else:
            currently_distracted = False

        # 只在专注阶段检查（休息阶段不计算）
        if self._phase != FocusPhase.FOCUS:
            currently_distracted = False

        return currently_distracted

    def _apply_distraction_state(self, currently_distracted: bool) -> None:
        """根据当前检测结果更新不专注状态、发出信号、处理恢复计时"""
        if currently_distracted == self._is_distracted:
            return
        self._is_distracted = currently_distracted
        self.distractedStateChanged.emit(currently_distracted)
        if not currently_distracted:
            # 恢复专注 → 重置计数
            self._distracted_sec = 0
            self._alert_fired    = False
            # 仅当因超限暂停时才恢复主计时器
            if self._paused_by_distraction:
                self._paused_by_distraction = False
                self._distract_check_timer.stop()
                self._timer.start()

    def _check_distraction(self) -> None:
        """完整检测（含计数 & 告警），由主定时器 _tick 调用（每秒）"""
        if self._preset and not self._preset.detect_focus:
            return
        currently_distracted = self._detect_distraction_state()
        self._apply_distraction_state(currently_distracted)

        if currently_distracted and self._preset:
            self._distracted_sec += 1
            tolerance = self._preset.tolerance_sec or 30
            if self._distracted_sec >= tolerance and not self._alert_fired:
                self._alert_fired = True
                self.distractedAlert.emit(self._distracted_sec)
                try:
                    from app.events import EventBus, EventType
                    EventBus.emit(EventType.FOCUS_DISTRACTED,
                                  distracted_sec=self._distracted_sec)
                except Exception:
                    pass
                logger.info("[专注] 不专注超限：{}s", self._distracted_sec)
                # 达到容忍值后才暂停计时
                if self._preset.pause_on_distracted and not self._paused_by_distraction:
                    self._paused_by_distraction = True
                    self._timer.stop()
                    if not self._distract_check_timer.isActive():
                        self._distract_check_timer.start()

    def _reset_distracted(self) -> None:
        self._distracted_sec       = 0
        self._is_distracted        = False
        self._alert_fired          = False
        self._paused_by_distraction = False

    @Slot()
    def _check_distraction_only(self) -> None:
        """轻量检测：仅更新不专注状态，不计数，供主计时器暂停期间调用"""
        if not self.is_running or self._preset is None:
            self._distract_check_timer.stop()
            return
        if not self._preset.detect_focus:
            return
        currently_distracted = self._detect_distraction_state()
        self._apply_distraction_state(currently_distracted)

    # ------------------------------------------------------------------ #
    # pynput 全局监听
    # ------------------------------------------------------------------ #

    def _start_listeners(self) -> None:
        if self._listeners_active:
            return
        try:
            from pynput import mouse as _mouse, keyboard as _keyboard

            def _on_activity(*_args, **_kwargs):
                self._last_activity_time = time.monotonic()

            self._mouse_listener = _mouse.Listener(
                on_move=_on_activity,
                on_click=_on_activity,
                on_scroll=_on_activity,
            )
            self._kb_listener = _keyboard.Listener(
                on_press=_on_activity,
            )

            # 在后台线程运行（pynput 要求）
            self._mouse_listener.start()
            self._kb_listener.start()
            self._last_activity_time = time.monotonic()
            self._listeners_active = True
            logger.debug("[专注] 输入监听器已启动")
        except Exception as e:
            logger.warning("[专注] 启动输入监听器失败：{}", e)

    def _stop_listeners(self) -> None:
        if not self._listeners_active:
            return
        try:
            if self._mouse_listener:
                self._mouse_listener.stop()
                self._mouse_listener = None
            if self._kb_listener:
                self._kb_listener.stop()
                self._kb_listener = None
            self._listeners_active = False
            logger.debug("[专注] 输入监听器已停止")
        except Exception as e:
            logger.warning("[专注] 停止输入监听器失败：{}", e)

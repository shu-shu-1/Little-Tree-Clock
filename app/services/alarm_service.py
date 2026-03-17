"""
闹钟服务

每秒（ALARM_CHECK_INTERVAL_MS）对本地时间做一次检查：
- 若当前 HH:MM 与某个已启用闹钟匹配，则发出 alarmFired 信号
- 防重复触发：同一分钟内同一闹钟只触发一次
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from app.models.alarm_model import Alarm, AlarmRepeat, AlarmStore
from app.constants import ALARM_CHECK_INTERVAL_MS
from app.utils.logger import logger


# ISO weekday：周一=1 … 周日=7 → AlarmRepeat bit 位
_WEEKDAY_TO_FLAG = {
    1: AlarmRepeat.MONDAY,
    2: AlarmRepeat.TUESDAY,
    3: AlarmRepeat.WEDNESDAY,
    4: AlarmRepeat.THURSDAY,
    5: AlarmRepeat.FRIDAY,
    6: AlarmRepeat.SATURDAY,
    7: AlarmRepeat.SUNDAY,
}


class AlarmService(QObject):
    """
    信号
    ----
    alarmFired(alarm_id: str)  — 某个闹钟触发（UI 层监听此信号显示弹窗/播放铃声）
    """

    alarmFired = Signal(str)   # alarm_id

    def __init__(self, store: AlarmStore, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._store   = store
        self._fired_this_minute: set[str] = set()   # 本分钟已触发的 alarm_id
        self._last_minute: str = ""                  # "HH:MM"

        self._timer = QTimer(self)
        self._timer.setInterval(ALARM_CHECK_INTERVAL_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        logger.debug("AlarmService 已启动: interval_ms={}", ALARM_CHECK_INTERVAL_MS)

    # ------------------------------------------------------------------ #
    # 内部检查
    # ------------------------------------------------------------------ #

    @Slot()
    def _tick(self) -> None:
        now = datetime.now()
        cur_minute = f"{now.hour:02d}:{now.minute:02d}"

        # 换分钟时清空防重集合
        if cur_minute != self._last_minute:
            self._fired_this_minute.clear()
            self._last_minute = cur_minute

        try:
            alarms = list(self._store.all())
        except Exception:
            logger.exception("读取闹钟列表失败")
            return

        for alarm in alarms:
            if not alarm.enabled:
                continue
            if alarm.id in self._fired_this_minute:
                continue
            if alarm.hour != now.hour or alarm.minute != now.minute:
                continue

            # 检查重复日
            repeat = alarm.repeat_flag
            if repeat != AlarmRepeat.NONE:
                today_flag = _WEEKDAY_TO_FLAG.get(now.isoweekday(), AlarmRepeat.NONE)
                if not (repeat & today_flag):
                    continue
            # else: 仅一次 — 任意日期都触发，触发后禁用
            elif repeat == AlarmRepeat.NONE:
                # 触发后自动禁用（仅一次模式）
                self._store.set_enabled(alarm.id, False)
                logger.info("一次性闹钟已触发并禁用: alarm_id={}", alarm.id)

            self._fired_this_minute.add(alarm.id)
            self.alarmFired.emit(alarm.id)
            logger.info(
                "闹钟触发: alarm_id={}, time={:02d}:{:02d}, repeat_flag={}",
                alarm.id,
                alarm.hour,
                alarm.minute,
                int(alarm.repeat_flag),
            )
            try:
                from app.events import EventBus, EventType
                EventBus.emit(EventType.ALARM_FIRED, alarm_id=alarm.id)
            except Exception:
                logger.exception("分发闹钟事件失败: alarm_id={}", alarm.id)

    # ------------------------------------------------------------------ #
    # 公共控制
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        if not self._timer.isActive():
            self._timer.start()
            logger.info("AlarmService 定时器已启动")

    def stop(self) -> None:
        if self._timer.isActive():
            self._timer.stop()
            logger.info("AlarmService 定时器已停止")

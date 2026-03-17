"""闹钟数据模型"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from enum import IntFlag, auto
from typing import List

from app.utils.time_utils import load_json, save_json
from app.constants import ALARM_CONFIG
from app.utils.logger import logger


class AlarmRepeat(IntFlag):
    """重复日标志位（与 Qt.DayOfWeek 对齐：周一=1 … 周日=7）"""
    NONE      = 0
    MONDAY    = auto()   # 1
    TUESDAY   = auto()   # 2
    WEDNESDAY = auto()   # 4
    THURSDAY  = auto()   # 8
    FRIDAY    = auto()   # 16
    SATURDAY  = auto()   # 32
    SUNDAY    = auto()   # 64
    WEEKDAYS  = MONDAY | TUESDAY | WEDNESDAY | THURSDAY | FRIDAY
    WEEKEND   = SATURDAY | SUNDAY
    EVERY_DAY = WEEKDAYS | WEEKEND

    def label(self) -> str:
        if self == AlarmRepeat.NONE:
            return "仅一次"
        if self == AlarmRepeat.EVERY_DAY:
            return "每天"
        if self == AlarmRepeat.WEEKDAYS:
            return "工作日"
        if self == AlarmRepeat.WEEKEND:
            return "周末"
        names = {
            AlarmRepeat.MONDAY:    "周一",
            AlarmRepeat.TUESDAY:   "周二",
            AlarmRepeat.WEDNESDAY: "周三",
            AlarmRepeat.THURSDAY:  "周四",
            AlarmRepeat.FRIDAY:    "周五",
            AlarmRepeat.SATURDAY:  "周六",
            AlarmRepeat.SUNDAY:    "周日",
        }
        return "、".join(v for k, v in names.items() if k in self)


@dataclass
class Alarm:
    """单条闹钟记录"""
    id:        str  = field(default_factory=lambda: str(uuid.uuid4()))
    label:     str  = "闹钟"
    hour:      int  = 8
    minute:    int  = 0
    enabled:   bool = True
    repeat:    int  = 0          # AlarmRepeat 按位整数
    sound:     str  = ""         # 铃声文件路径，空=系统默认
    snooze_min: int = 5          # 稍后提醒分钟数，0=禁用
    fullscreen: bool = True      # 是否启用全屏提醒

    @property
    def time_str(self) -> str:
        return f"{self.hour:02d}:{self.minute:02d}"

    @property
    def repeat_flag(self) -> AlarmRepeat:
        return AlarmRepeat(self.repeat)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Alarm":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class AlarmStore:
    """闹钟持久化仓库"""

    def __init__(self):
        self._alarms: List[Alarm] = []
        self._load()

    # ------------------------------------------------------------------ #

    def all(self) -> List[Alarm]:
        return list(self._alarms)

    def get(self, alarm_id: str) -> Alarm | None:
        return next((a for a in self._alarms if a.id == alarm_id), None)

    def add(self, alarm: Alarm) -> None:
        self._alarms.append(alarm)
        self._save()
        logger.info("闹钟已添加: alarm_id={}, time={}, repeat={}, enabled={}", alarm.id, alarm.time_str, int(alarm.repeat_flag), alarm.enabled)

    def update(self, alarm: Alarm) -> None:
        updated = False
        for i, a in enumerate(self._alarms):
            if a.id == alarm.id:
                self._alarms[i] = alarm
                updated = True
                break
        self._save()
        if updated:
            logger.info("闹钟已更新: alarm_id={}, time={}, repeat={}, enabled={}", alarm.id, alarm.time_str, int(alarm.repeat_flag), alarm.enabled)
        else:
            logger.warning("更新闹钟未命中，已执行保存: alarm_id={}", alarm.id)

    def remove(self, alarm_id: str) -> None:
        before_count = len(self._alarms)
        self._alarms = [a for a in self._alarms if a.id != alarm_id]
        self._save()
        logger.info("闹钟已删除: alarm_id={}, removed={}", alarm_id, before_count - len(self._alarms))

    def set_enabled(self, alarm_id: str, enabled: bool) -> None:
        a = self.get(alarm_id)
        if a:
            a.enabled = enabled
            self._save()
            logger.info("闹钟启用状态已更新: alarm_id={}, enabled={}", alarm_id, enabled)
        else:
            logger.warning("更新闹钟启用状态失败，闹钟不存在: alarm_id={}", alarm_id)

    # ------------------------------------------------------------------ #

    def _load(self):
        data = load_json(ALARM_CONFIG, default=[])
        if not isinstance(data, list):
            logger.warning("闹钟配置格式异常，已回退为空列表: {}", ALARM_CONFIG)
            data = []
        self._alarms = [Alarm.from_dict(d) for d in data]
        logger.debug("闹钟配置已加载: path={}, count={}", ALARM_CONFIG, len(self._alarms))

    def _save(self):
        save_json(ALARM_CONFIG, [a.to_dict() for a in self._alarms])
        logger.debug("闹钟配置已保存: path={}, count={}", ALARM_CONFIG, len(self._alarms))

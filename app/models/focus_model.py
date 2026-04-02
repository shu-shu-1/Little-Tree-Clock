"""专注时钟数据模型"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import List, Optional

from app.utils.time_utils import load_json, save_json
from app.constants import FOCUS_CONFIG
from app.utils.logger import logger


def _migrate_alert_mode(val: str) -> str:
    """将旧的 'automation' 值迁移为 'notification'"""
    if val == "automation":
        return AlertMode.NOTIFICATION
    return val


class FocusRule(str, Enum):
    """专注检测规则"""
    MUST_USE_PC  = "must_use_pc"   # 必须使用电脑（无活动则不专注）
    FOCUSED_APP  = "focused_app"   # 专注于特定程序（焦点离开则不专注）
    NO_PC_USE    = "no_pc_use"     # 不允许使用电脑（有活动则不专注）


class AlertMode(str, Enum):
    """不专注触发动作"""
    NOTIFICATION = "notification"   # 弹出系统通知
    FULLSCREEN   = "fullscreen"     # 全屏提醒（仿闹钟）


@dataclass
class FocusPreset:
    """一个专注预设（可保存多个）"""
    id:                  str      = field(default_factory=lambda: str(uuid.uuid4()))
    name:                str      = "新专注预设"
    # 时长
    focus_minutes:       int      = 25      # 专注时长（分钟）
    break_minutes:       int      = 5       # 休息时长（分钟，0=不休息）
    cycles:              int      = 4       # 循环次数（0=无限）
    # 规则
    rule:                str      = FocusRule.MUST_USE_PC
    app_name_filter:     str      = ""      # FOCUSED_APP 规则时的程序名关键词
    tolerance_sec:       int      = 30      # 容忍不专注秒数后触发提醒
    # 提醒
    alert_mode:          str      = AlertMode.NOTIFICATION
    # 铃声
    break_start_sound:   str      = ""      # 休息开始铃声（专注阶段结束）
    break_end_sound:     str      = ""      # 休息结束铃声
    # 检测开关
    detect_focus:        bool     = True    # 是否启用专注状态检测
    # 不专注行为
    pause_on_distracted: bool     = False   # 触发不专注时自动暂停计时

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "FocusPreset":
        return cls(
            id=d.get("id") or str(uuid.uuid4()),
            name=d.get("name", "新专注预设"),
            focus_minutes=d.get("focus_minutes", 25),
            break_minutes=d.get("break_minutes", 5),
            cycles=d.get("cycles", 4),
            rule=d.get("rule", FocusRule.MUST_USE_PC),
            app_name_filter=d.get("app_name_filter", ""),
            tolerance_sec=d.get("tolerance_sec", 30),
            alert_mode=_migrate_alert_mode(d.get("alert_mode", AlertMode.NOTIFICATION)),
            break_start_sound=d.get("break_start_sound", ""),
            break_end_sound=d.get("break_end_sound", ""),
            detect_focus=d.get("detect_focus", True),
            pause_on_distracted=d.get("pause_on_distracted", False),
        )


class FocusStore:
    """专注预设持久化仓库"""

    _cache_mtime_ns: int | None = None
    _cache_presets: list[dict] | None = None

    def __init__(self):
        self._presets: List[FocusPreset] = []
        self._load()

    # ------------------------------------------------------------------ #

    def _load(self) -> None:
        path = Path(FOCUS_CONFIG)
        mtime_ns: int | None = None
        try:
            if path.exists():
                mtime_ns = path.stat().st_mtime_ns
        except OSError:
            mtime_ns = None

        if (
            self.__class__._cache_presets is not None
            and self.__class__._cache_mtime_ns == mtime_ns
        ):
            self._presets = [FocusPreset.from_dict(d) for d in self.__class__._cache_presets]
            return

        data = load_json(FOCUS_CONFIG, default=[])
        if not isinstance(data, list):
            logger.warning("专注配置格式异常，已回退为空列表: {}", FOCUS_CONFIG)
            data = []
        self._presets = [FocusPreset.from_dict(d) for d in data]
        self.__class__._cache_presets = [p.to_dict() for p in self._presets]
        self.__class__._cache_mtime_ns = mtime_ns
        # 若有旧数据 id 为空字符串，from_dict 已修复；立即回写以持久化
        if any(not d.get("id") for d in data):
            logger.info("检测到旧版专注配置，正在执行 id 迁移保存")
            self._save()
        logger.debug("专注配置已加载: path={}, count={}", FOCUS_CONFIG, len(self._presets))

    def _save(self) -> None:
        save_json(FOCUS_CONFIG, [p.to_dict() for p in self._presets])
        self.__class__._cache_presets = [p.to_dict() for p in self._presets]
        try:
            self.__class__._cache_mtime_ns = Path(FOCUS_CONFIG).stat().st_mtime_ns
        except OSError:
            self.__class__._cache_mtime_ns = None
        logger.debug("专注配置已保存: path={}, count={}", FOCUS_CONFIG, len(self._presets))

    # ------------------------------------------------------------------ #

    def all(self) -> List[FocusPreset]:
        return list(self._presets)

    def get(self, preset_id: str) -> Optional[FocusPreset]:
        for p in self._presets:
            if p.id == preset_id:
                return p
        return None

    def add(self, preset: FocusPreset) -> None:
        self._presets.append(preset)
        self._save()
        logger.info("专注预设已添加: preset_id={}, name={}", preset.id, preset.name)

    def update(self, preset: FocusPreset) -> None:
        for i, p in enumerate(self._presets):
            if p.id == preset.id:
                self._presets[i] = preset
                self._save()
                logger.info("专注预设已更新: preset_id={}, name={}", preset.id, preset.name)
                return
        logger.warning("更新专注预设失败，预设不存在: preset_id={}", preset.id)

    def remove(self, preset_id: str) -> None:
        before_count = len(self._presets)
        self._presets = [p for p in self._presets if p.id != preset_id]
        self._save()
        logger.info("专注预设已删除: preset_id={}, removed={}", preset_id, before_count - len(self._presets))

"""自动化规则数据模型"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List

from app.utils.time_utils import load_json, save_json
from app.constants import AUTOMATION_CONFIG
from app.utils.logger import logger


class TriggerType(str, Enum):
    """内置触发器类型"""
    NONE              = "none"              # 无触发器（仅手动执行）
    TIME_OF_DAY       = "time_of_day"       # 每天某时刻
    SCHEDULE_INTERVAL = "schedule_interval" # 每隔 N 分钟
    ALARM_FIRED       = "alarm_fired"       # 某个闹钟响起
    TIMER_DONE        = "timer_done"        # 计时器结束
    APP_STARTUP       = "app_startup"       # 应用启动
    APP_SHUTDOWN      = "app_shutdown"      # 应用退出
    MANUAL            = "manual"            # 手动触发（仅测试用）
    PLUGIN            = "plugin"            # 由插件注册的自定义触发器
    FOCUS_DISTRACTED  = "focus_distracted"  # 专注时钟：不专注超限
    FOCUS_SESSION_DONE = "focus_session_done" # 专注会话结束（一轮完成）
    FOCUS_BREAK_START  = "focus_break_start"  # 休息开始
    FOCUS_BREAK_END    = "focus_break_end"    # 休息结束


class ActionType(str, Enum):
    """内置动作类型"""
    NOTIFICATION   = "notification"    # 弹出系统通知
    PLAY_SOUND     = "play_sound"      # 播放音效
    RUN_COMMAND    = "run_command"     # 运行系统命令
    OPEN_URL       = "open_url"        # 打开 URL
    PLUGIN         = "plugin"          # 由插件注册的自定义动作
    SET_ALARM      = "set_alarm"       # 启用/禁用闹钟
    LOG            = "log"             # 写入日志（调试）
    SHOW_WINDOW    = "show_window"     # 显示主窗口
    HIDE_WINDOW    = "hide_window"     # 隐藏主窗口
    START_FOCUS    = "start_focus"     # 开始专注（使用当前预设）
    STOP_FOCUS     = "stop_focus"      # 停止专注
    WAIT           = "wait"            # 等待 N 秒后执行后续动作


@dataclass
class TriggerConfig:
    type: str             = TriggerType.NONE
    params: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "TriggerConfig":
        return cls(type=d.get("type", TriggerType.MANUAL),
                   params=d.get("params", {}))


@dataclass
class ActionConfig:
    type: str             = ActionType.NOTIFICATION
    params: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ActionConfig":
        return cls(type=d.get("type", ActionType.NOTIFICATION),
                   params=d.get("params", {}))


@dataclass
class AutomationRule:
    """一条自动化规则（一个触发器 → 多个动作）"""
    id:       str               = field(default_factory=lambda: str(uuid.uuid4()))
    name:     str               = "新规则"
    enabled:  bool              = True
    trigger:  TriggerConfig     = field(default_factory=TriggerConfig)
    actions:  List[ActionConfig] = field(default_factory=list)
    description: str            = ""

    def to_dict(self) -> dict:
        return {
            "id":          self.id,
            "name":        self.name,
            "enabled":     self.enabled,
            "description": self.description,
            "trigger":     self.trigger.to_dict(),
            "actions":     [a.to_dict() for a in self.actions],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AutomationRule":
        return cls(
            id=d.get("id", str(uuid.uuid4())),
            name=d.get("name", "新规则"),
            enabled=d.get("enabled", True),
            description=d.get("description", ""),
            trigger=TriggerConfig.from_dict(d.get("trigger", {})),
            actions=[ActionConfig.from_dict(a) for a in d.get("actions", [])],
        )


class AutomationStore:
    """自动化规则持久化仓库"""

    def __init__(self):
        self._rules: List[AutomationRule] = []
        self._load()

    def all(self) -> List[AutomationRule]:
        return list(self._rules)

    def get(self, rule_id: str) -> AutomationRule | None:
        return next((r for r in self._rules if r.id == rule_id), None)

    def add(self, rule: AutomationRule) -> None:
        self._rules.append(rule)
        self._save()
        logger.info("自动化规则已添加: rule_id={}, name={}, enabled={}", rule.id, rule.name, rule.enabled)

    def update(self, rule: AutomationRule) -> None:
        updated = False
        for i, r in enumerate(self._rules):
            if r.id == rule.id:
                self._rules[i] = rule
                updated = True
                break
        self._save()
        if updated:
            logger.info("自动化规则已更新: rule_id={}, name={}, enabled={}", rule.id, rule.name, rule.enabled)
        else:
            logger.warning("更新自动化规则未命中，已执行保存: rule_id={}", rule.id)

    def remove(self, rule_id: str) -> None:
        before_count = len(self._rules)
        self._rules = [r for r in self._rules if r.id != rule_id]
        self._save()
        logger.info("自动化规则已删除: rule_id={}, removed={}", rule_id, before_count - len(self._rules))

    def set_enabled(self, rule_id: str, enabled: bool) -> None:
        r = self.get(rule_id)
        if r:
            r.enabled = enabled
            self._save()
            logger.info("自动化规则启用状态已更新: rule_id={}, enabled={}", rule_id, enabled)
        else:
            logger.warning("更新自动化规则启用状态失败，规则不存在: rule_id={}", rule_id)

    # ------------------------------------------------------------------ #

    def _load(self):
        data = load_json(AUTOMATION_CONFIG, default=[])
        if not isinstance(data, list):
            logger.warning("自动化配置格式异常，已回退为空列表: {}", AUTOMATION_CONFIG)
            data = []
        self._rules = [AutomationRule.from_dict(d) for d in data]
        logger.debug("自动化配置已加载: path={}, count={}", AUTOMATION_CONFIG, len(self._rules))

    def _save(self):
        save_json(AUTOMATION_CONFIG, [r.to_dict() for r in self._rules])
        logger.debug("自动化配置已保存: path={}, count={}", AUTOMATION_CONFIG, len(self._rules))

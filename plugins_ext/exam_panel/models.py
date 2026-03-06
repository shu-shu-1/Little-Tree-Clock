"""考试面板插件 — 数据模型"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List


# ─────────────────────────────────────────────────────────────────────────── #
# 科目
# ─────────────────────────────────────────────────────────────────────────── #

@dataclass
class ExamSubject:
    """一门考试科目。"""
    id:    str = field(default_factory=lambda: str(uuid.uuid4()))
    name:  str = ""
    color: str = "#4CAF50"   # 主题色（CSS/hex）

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ExamSubject":
        return cls(
            id    = d.get("id", str(uuid.uuid4())),
            name  = d.get("name", ""),
            color = d.get("color", "#4CAF50"),
        )


# ─────────────────────────────────────────────────────────────────────────── #
# 提醒项
# ─────────────────────────────────────────────────────────────────────────── #

@dataclass
class ExamReminder:
    """单条考试提醒配置。"""
    id:                  str  = field(default_factory=lambda: str(uuid.uuid4()))
    minutes_before_end:  int  = 30      # 考试结束前 X 分钟触发
    mode:                str  = "fullscreen"   # "fullscreen" | "voice" | "both"
    fullscreen_flash:    bool = False   # 全屏模式是否闪烁
    message:             str  = ""      # 自定义提醒文字（为空时自动生成）

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ExamReminder":
        return cls(
            id                 = d.get("id", str(uuid.uuid4())),
            minutes_before_end = d.get("minutes_before_end", 30),
            mode               = d.get("mode", "fullscreen"),
            fullscreen_flash   = d.get("fullscreen_flash", False),
            message            = d.get("message", ""),
        )


# ─────────────────────────────────────────────────────────────────────────── #
# 考试计划（一门科目对应一个时间段的考试安排）
# ─────────────────────────────────────────────────────────────────────────── #

@dataclass
class ExamPlan:
    """一门科目的考试规划。"""
    id:                 str              = field(default_factory=lambda: str(uuid.uuid4()))
    subject_id:         str              = ""
    start_time:         str              = ""     # "HH:MM"（24h）
    end_time:           str              = ""     # "HH:MM"（24h）
    answer_sheet_count: int              = 0      # 答题卡张数
    answer_sheet_page_count: int         = 0      # 答题卡页数
    paper_count:        int              = 0      # 试卷张数
    paper_page_count:   int              = 0      # 试卷页数
    prep_min:           int              = 5      # 提前进入准备状态的分钟数
    reminders:          List[ExamReminder] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["reminders"] = [r.to_dict() for r in self.reminders]
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ExamPlan":
        reminders = [ExamReminder.from_dict(r) for r in d.get("reminders", [])]
        return cls(
            id                 = d.get("id", str(uuid.uuid4())),
            subject_id         = d.get("subject_id", ""),
            start_time         = d.get("start_time", ""),
            end_time           = d.get("end_time", ""),
            answer_sheet_count = d.get("answer_sheet_count", 0),
            answer_sheet_page_count = d.get("answer_sheet_page_count", d.get("answer_sheet_pages", 0)),
            paper_count        = d.get("paper_count", d.get("paper_counts", 0)),
            paper_page_count   = d.get("paper_page_count", 0),
            prep_min           = d.get("prep_min", 5),
            reminders          = reminders,
        )


# ─────────────────────────────────────────────────────────────────────────── #
# 布局预设（命名的 widget_config 列表快照）
# ─────────────────────────────────────────────────────────────────────────── #

@dataclass
class LayoutPreset:
    """一个命名的画布布局预设（独立于 zone，可应用到任意 zone）。"""
    id:          str            = field(default_factory=lambda: str(uuid.uuid4()))
    name:        str            = "未命名预设"
    description: str            = ""
    zone_id:     str            = ""     # 创建时的来源 zone（参考信息）
    configs:     List[Dict[str, Any]] = field(default_factory=list)  # WidgetConfig.to_dict()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id":          self.id,
            "name":        self.name,
            "description": self.description,
            "zone_id":     self.zone_id,
            "configs":     self.configs,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "LayoutPreset":
        return cls(
            id          = d.get("id", str(uuid.uuid4())),
            name        = d.get("name", "未命名预设"),
            description = d.get("description", ""),
            zone_id     = d.get("zone_id", ""),
            configs     = d.get("configs", []),
        )


# ─────────────────────────────────────────────────────────────────────────── #
# 科目-预设 绑定（切换科目时自动切换到该科目绑定的预设）
# ─────────────────────────────────────────────────────────────────────────── #

@dataclass
class SubjectPresetBinding:
    """科目与布局预设的绑定关系。"""
    subject_id: str = ""   # 绑定的科目 ID
    preset_id:  str = ""   # 绑定的预设 ID（空字符串=不绑定）
    zone_id:    str = ""   # 绑定针对哪个 zone（空字符串=全局）

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SubjectPresetBinding":
        return cls(
            subject_id = d.get("subject_id", ""),
            preset_id  = d.get("preset_id", ""),
            zone_id    = d.get("zone_id", ""),
        )

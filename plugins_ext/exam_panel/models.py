"""考试面板插件 — 数据模型"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class ExamSubject:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    color: str = "#4CAF50"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ExamSubject":
        return cls(
            id=d.get("id", str(uuid.uuid4())),
            name=d.get("name", ""),
            color=d.get("color", "#4CAF50"),
        )


@dataclass
class ExamReminder:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    minutes_before_end: int = 30  # 考试结束前 X 分钟触发
    mode: str = "fullscreen"  # "fullscreen" | "voice" | "both"
    fullscreen_flash: bool = False
    message: str = ""  # 为空时自动生成

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ExamReminder":
        return cls(
            id=d.get("id", str(uuid.uuid4())),
            minutes_before_end=d.get("minutes_before_end", 30),
            mode=d.get("mode", "fullscreen"),
            fullscreen_flash=d.get("fullscreen_flash", False),
            message=d.get("message", ""),
        )


@dataclass
class ExamPlan:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    subject_id: str = ""
    start_time: str = ""  # "HH:MM"（24h）
    end_time: str = ""  # "HH:MM"（24h）
    answer_sheet_count: int = 0
    answer_sheet_page_count: int = 0
    paper_count: int = 0
    paper_page_count: int = 0
    prep_min: int = 5  # 提前进入准备状态的分钟数
    reminders: list[ExamReminder] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["reminders"] = [r.to_dict() for r in self.reminders]
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ExamPlan":
        reminders = [ExamReminder.from_dict(r) for r in d.get("reminders", [])]
        return cls(
            id=d.get("id", str(uuid.uuid4())),
            subject_id=d.get("subject_id", ""),
            start_time=d.get("start_time", ""),
            end_time=d.get("end_time", ""),
            answer_sheet_count=d.get("answer_sheet_count", 0),
            answer_sheet_page_count=d.get("answer_sheet_page_count", d.get("answer_sheet_pages", 0)),
            paper_count=d.get("paper_count", d.get("paper_counts", 0)),
            paper_page_count=d.get("paper_page_count", 0),
            prep_min=d.get("prep_min", 5),
            reminders=reminders,
        )


@dataclass
class LayoutPreset:
    """可应用到任意 zone 的命名布局预设。"""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = "未命名预设"
    description: str = ""
    zone_id: str = ""  # 创建时的来源 zone
    configs: list[dict[str, Any]] = field(default_factory=list)  # WidgetConfig.to_dict()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "zone_id": self.zone_id,
            "configs": self.configs,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "LayoutPreset":
        return cls(
            id=d.get("id", str(uuid.uuid4())),
            name=d.get("name", "未命名预设"),
            description=d.get("description", ""),
            zone_id=d.get("zone_id", ""),
            configs=d.get("configs", []),
        )


@dataclass
class SubjectPresetBinding:
    subject_id: str = ""
    preset_id: str = ""  # 空字符串=不绑定
    zone_id: str = ""  # 空字符串=全局

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SubjectPresetBinding":
        return cls(
            subject_id=d.get("subject_id", ""),
            preset_id=d.get("preset_id", ""),
            zone_id=d.get("zone_id", ""),
        )

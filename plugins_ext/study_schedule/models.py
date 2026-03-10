"""自习时间安排数据模型。"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List

WEEKDAY_LABELS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def normalize_weekdays(values: List[int]) -> List[int]:
    result = []
    seen: set[int] = set()
    for value in values:
        try:
            day = int(value)
        except (TypeError, ValueError):
            continue
        if 0 <= day <= 6 and day not in seen:
            seen.add(day)
            result.append(day)
    return sorted(result)


def format_weekdays(values: List[int]) -> str:
    days = normalize_weekdays(values)
    if not days:
        return "未指定"
    return "、".join(WEEKDAY_LABELS[day] for day in days)


@dataclass
class StudyItem:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    description: str = ""
    start_time: str = "09:00"
    end_time: str = "10:00"
    preset_id: str = ""
    enabled: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "preset_id": self.preset_id,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StudyItem":
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            name=data.get("name", ""),
            description=data.get("description", ""),
            start_time=data.get("start_time", "09:00"),
            end_time=data.get("end_time", "10:00"),
            preset_id=data.get("preset_id", ""),
            enabled=bool(data.get("enabled", True)),
        )


@dataclass
class StudyGroup:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    description: str = ""
    weekdays: List[int] = field(default_factory=list)
    preset_id: str = ""
    items: List[StudyItem] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "weekdays": normalize_weekdays(self.weekdays),
            "preset_id": self.preset_id,
            "items": [item.to_dict() for item in self.items],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StudyGroup":
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            name=data.get("name", ""),
            description=data.get("description", ""),
            weekdays=normalize_weekdays(list(data.get("weekdays", []))),
            preset_id=data.get("preset_id", ""),
            items=[StudyItem.from_dict(item) for item in data.get("items", []) if isinstance(item, dict)],
        )

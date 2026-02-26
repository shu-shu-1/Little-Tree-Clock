"""世界时区数据模型"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from typing import List

from app.utils.time_utils import load_json, save_json
from app.constants import WORLD_TIME_CONFIG, PRESET_TIMEZONES


@dataclass
class WorldZone:
    """一张世界时钟卡片"""
    id:       str = field(default_factory=lambda: str(uuid.uuid4()))
    label:    str = ""            # 自定义显示名称
    timezone: str = "UTC"         # IANA 时区名 或 "local"
    show_date: bool = True

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "WorldZone":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class WorldZoneStore:
    """世界时区列表持久化仓库"""

    def __init__(self):
        self._zones: List[WorldZone] = []
        self._load()

    def all(self) -> List[WorldZone]:
        return list(self._zones)

    def add(self, zone: WorldZone) -> None:
        self._zones.append(zone)
        self._save()

    def remove(self, zone_id: str) -> None:
        self._zones = [z for z in self._zones if z.id != zone_id]
        self._save()

    def reorder(self, new_order: List[str]) -> None:
        """按 id 列表重排"""
        mapping = {z.id: z for z in self._zones}
        self._zones = [mapping[i] for i in new_order if i in mapping]
        self._save()

    def update(self, zone: WorldZone) -> None:
        for i, z in enumerate(self._zones):
            if z.id == zone.id:
                self._zones[i] = zone
                break
        self._save()

    # ------------------------------------------------------------------ #

    def _load(self):
        data = load_json(WORLD_TIME_CONFIG, default=None)
        if data is None:
            # 首次运行：写入预设时区
            self._zones = [
                WorldZone(label=label, timezone=tz)
                for label, tz in PRESET_TIMEZONES[:5]
            ]
            self._save()
        else:
            self._zones = [WorldZone.from_dict(d) for d in data]

    def _save(self):
        save_json(WORLD_TIME_CONFIG, [z.to_dict() for z in self._zones])

"""世界时区数据模型"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List

from app.utils.time_utils import load_json, save_json
from app.utils.logger import logger
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

    _cache_mtime_ns: int | None = None
    _cache_zones: list[dict] | None = None

    def __init__(self):
        self._zones: List[WorldZone] = []
        self._load()

    def all(self) -> List[WorldZone]:
        return list(self._zones)

    def add(self, zone: WorldZone) -> None:
        self._zones.append(zone)
        self._save()
        logger.info("[世界时间] 新增时区卡片：id={}, label='{}', timezone='{}'", zone.id, zone.label, zone.timezone)

    def remove(self, zone_id: str) -> None:
        before = len(self._zones)
        self._zones = [z for z in self._zones if z.id != zone_id]
        self._save()
        if len(self._zones) == before:
            logger.warning("[世界时间] 删除时区卡片未命中：id={}", zone_id)
        else:
            logger.info("[世界时间] 删除时区卡片：id={}", zone_id)

    def reorder(self, new_order: List[str]) -> None:
        """按 id 列表重排"""
        mapping = {z.id: z for z in self._zones}
        self._zones = [mapping[i] for i in new_order if i in mapping]
        self._save()
        logger.debug("[世界时间] 重排时区卡片：requested={}, applied={}", len(new_order), len(self._zones))

    def update(self, zone: WorldZone) -> None:
        updated = False
        for i, z in enumerate(self._zones):
            if z.id == zone.id:
                self._zones[i] = zone
                updated = True
                break
        self._save()
        if updated:
            logger.info("[世界时间] 更新时区卡片：id={}, label='{}', timezone='{}'", zone.id, zone.label, zone.timezone)
        else:
            logger.warning("[世界时间] 更新时区卡片未命中：id={}", zone.id)

    # ------------------------------------------------------------------ #

    def _load(self):
        path = Path(WORLD_TIME_CONFIG)
        mtime_ns: int | None = None
        try:
            if path.exists():
                mtime_ns = path.stat().st_mtime_ns
        except OSError:
            mtime_ns = None

        if (
            self.__class__._cache_zones is not None
            and self.__class__._cache_mtime_ns == mtime_ns
        ):
            self._zones = [WorldZone.from_dict(d) for d in self.__class__._cache_zones]
            return

        data = load_json(WORLD_TIME_CONFIG, default=None)
        if data is None:
            # 首次运行：写入预设时区
            self._zones = [
                WorldZone(label=label, timezone=tz)
                for label, tz in PRESET_TIMEZONES[:5]
            ]
            self._save()
            logger.info("[世界时间] 初始化默认时区卡片 {} 个", len(self._zones))
        else:
            if not isinstance(data, list):
                logger.warning("[世界时间] 配置格式异常，期望 list，实际 {}，已忽略", type(data).__name__)
                self._zones = []
                return
            self._zones = [WorldZone.from_dict(d) for d in data]
            self.__class__._cache_zones = [z.to_dict() for z in self._zones]
            self.__class__._cache_mtime_ns = mtime_ns
            logger.debug("[世界时间] 已加载时区卡片 {} 个", len(self._zones))

    def _save(self):
        save_json(WORLD_TIME_CONFIG, [z.to_dict() for z in self._zones])
        self.__class__._cache_zones = [z.to_dict() for z in self._zones]
        try:
            self.__class__._cache_mtime_ns = Path(WORLD_TIME_CONFIG).stat().st_mtime_ns
        except OSError:
            self.__class__._cache_mtime_ns = None
        logger.debug("[世界时间] 已保存时区卡片 {} 个", len(self._zones))

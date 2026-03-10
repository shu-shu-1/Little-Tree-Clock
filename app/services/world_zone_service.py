"""世界时区宿主服务。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.models.world_zone import WorldZone, WorldZoneStore


class WorldZoneService:
    """向插件暴露世界时区列表的只读访问能力。"""

    def list_zones(self) -> List[WorldZone]:
        return WorldZoneStore().all()

    def list_zone_options(self) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []
        for zone in self.list_zones():
            result.append({
                "id": zone.id,
                "label": zone.label,
                "timezone": zone.timezone,
                "show_date": zone.show_date,
                "display_name": self.get_zone_display_name(zone.id, zone=zone),
            })
        return result

    def get_zone(self, zone_id: str) -> Optional[WorldZone]:
        for zone in self.list_zones():
            if zone.id == zone_id:
                return zone
        return None

    def exists(self, zone_id: str) -> bool:
        return self.get_zone(zone_id) is not None

    def get_zone_display_name(
        self,
        zone_id: str,
        *,
        zone: WorldZone | None = None,
        fallback: str = "",
    ) -> str:
        target = zone or self.get_zone(zone_id)
        if target is None:
            return fallback or zone_id
        return target.label or target.timezone or fallback or zone_id

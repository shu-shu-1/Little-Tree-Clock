"""世界时区宿主服务。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.constants import PRESET_TIMEZONES
from app.models.world_zone import WorldZone, WorldZoneStore
from app.services.i18n_service import I18nService
from app.utils.logger import logger


_EN_US_TIMEZONE_LABELS: dict[str, str] = {
    "local": "Local Time",
    "UTC": "Coordinated Universal Time",
    "Asia/Shanghai": "Beijing / Shanghai",
    "Asia/Tokyo": "Tokyo",
    "Asia/Seoul": "Seoul",
    "Asia/Singapore": "Singapore",
    "Asia/Dubai": "Dubai",
    "Europe/Moscow": "Moscow",
    "Europe/Berlin": "Berlin / Paris",
    "Europe/London": "London",
    "America/New_York": "New York",
    "America/Chicago": "Chicago",
    "America/Los_Angeles": "Los Angeles",
    "America/Sao_Paulo": "Sao Paulo",
    "Australia/Sydney": "Sydney",
}


def get_localized_timezone_name(timezone_name: str, *, fallback: str = "") -> str:
    normalized = str(timezone_name or "").strip()
    if not normalized:
        return fallback

    i18n = I18nService.instance()
    if normalized == "local":
        local_text = i18n.t("world_time.local", default="(本地时间)").strip()
        if local_text.startswith("(") and local_text.endswith(")") and len(local_text) > 2:
            return local_text[1:-1].strip() or local_text
        return local_text or fallback or normalized

    zh_cn_labels = {tz: label for label, tz in PRESET_TIMEZONES}
    if i18n.language == "zh-CN":
        return zh_cn_labels.get(normalized, fallback or normalized)

    if i18n.language == "en-US":
        return _EN_US_TIMEZONE_LABELS.get(normalized, fallback or normalized)

    return fallback or normalized


def _actual_zone_name(timezone_name: str) -> str:
    return get_localized_timezone_name(timezone_name, fallback=str(timezone_name or "").strip())


def format_zone_display_name(zone: WorldZone | None, fallback: str = "") -> str:
    if zone is None:
        return fallback

    custom_name = str(zone.label or "").strip()
    actual_name = _actual_zone_name(zone.timezone)
    if custom_name and actual_name and custom_name != actual_name:
        return f"{custom_name} ({actual_name})"
    return custom_name or actual_name or fallback


class WorldZoneService:
    """向插件暴露世界时区列表的只读访问能力。"""

    def list_zones(self) -> List[WorldZone]:
        try:
            zones = WorldZoneStore().all()
            logger.debug("读取世界时区列表: count={}", len(zones))
            return zones
        except Exception:
            logger.exception("读取世界时区列表失败")
            return []

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
        logger.debug("生成世界时区选项: count={}", len(result))
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
            if zone_id:
                logger.debug("世界时区不存在，使用回退名称: zone_id={}", zone_id)
            return fallback or zone_id
        return format_zone_display_name(target, fallback=fallback or zone_id)

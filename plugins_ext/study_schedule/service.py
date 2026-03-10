"""自习时间安排核心服务。"""
from __future__ import annotations

import json
from datetime import datetime, time as dtime, timedelta
from pathlib import Path
from typing import Any, Optional

from PySide6.QtCore import QObject, QTimer, Signal

from .models import StudyGroup, StudyItem


class StudyScheduleService(QObject):
    groups_updated = Signal()
    current_group_changed = Signal(str)
    current_item_changed = Signal(str)
    settings_changed = Signal(str, object)
    target_zone_changed = Signal(str)

    _DEFAULT_SETTINGS: dict[str, Any] = {
        "auto_switch_by_weekday": True,
        "auto_switch_by_time": True,
        "auto_apply_preset": True,
        "check_interval_sec": 30,
        "target_zone_id": "",
    }

    def __init__(self, data_dir: Path, api, preset_service=None, world_zone_service=None, parent=None):
        super().__init__(parent)
        self._data_dir = data_dir
        self._api = api
        self._preset_service = preset_service
        self._world_zone_service = world_zone_service
        self._groups: list[StudyGroup] = []
        self._settings: dict[str, Any] = dict(self._DEFAULT_SETTINGS)
        self._current_group_id: str = ""
        self._current_item_id: str = ""
        self._last_zone_id: str = ""
        self._load()

        if self._preset_service is not None and hasattr(self._preset_service, "presets_updated"):
            self._preset_service.presets_updated.connect(self._cleanup_missing_presets)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_runtime_state)
        self._apply_timer_interval()
        self._refresh_runtime_state()

    # ------------------------------------------------------------------ #
    # 持久化
    # ------------------------------------------------------------------ #

    def _data_path(self) -> Path:
        return self._data_dir / "study_schedule.json"

    def _load(self) -> None:
        path = self._data_path()
        if not path.exists():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            self._groups = []
            self._settings = dict(self._DEFAULT_SETTINGS)
            self._current_group_id = ""
            self._current_item_id = ""
            self._last_zone_id = ""
            return

        self._groups = [StudyGroup.from_dict(item) for item in raw.get("groups", []) if isinstance(item, dict)]
        settings = dict(self._DEFAULT_SETTINGS)
        if isinstance(raw.get("settings"), dict):
            settings.update(raw["settings"])
        self._settings = settings
        self._current_group_id = str(raw.get("current_group_id", "") or "")
        self._current_item_id = str(raw.get("current_item_id", "") or "")
        self._last_zone_id = str(raw.get("last_zone_id", "") or "")

    def _save(self) -> None:
        path = self._data_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "groups": [group.to_dict() for group in self._groups],
                    "settings": self._settings,
                    "current_group_id": self._current_group_id,
                    "current_item_id": self._current_item_id,
                    "last_zone_id": self._last_zone_id,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------ #
    # 预设与画布
    # ------------------------------------------------------------------ #

    def available_presets(self):
        if self._preset_service is None or not hasattr(self._preset_service, "presets"):
            return []
        try:
            return list(self._preset_service.presets())
        except Exception:
            return []

    def get_preset(self, preset_id: str):
        if self._preset_service is None or not hasattr(self._preset_service, "get_preset"):
            return None
        try:
            return self._preset_service.get_preset(preset_id)
        except Exception:
            return None

    def has_preset(self, preset_id: str) -> bool:
        if not preset_id:
            return False
        if self._preset_service is None:
            return False
        if hasattr(self._preset_service, "has_preset"):
            try:
                return bool(self._preset_service.has_preset(preset_id))
            except Exception:
                return False
        return self.get_preset(preset_id) is not None

    def list_zones(self) -> list[dict[str, Any]]:
        service = self._world_zone_service
        if service is None:
            return []
        if hasattr(service, "list_zone_options"):
            try:
                return list(service.list_zone_options())
            except Exception:
                return []
        return []

    def get_zone_display_name(self, zone_id: str, fallback: str = "") -> str:
        service = self._world_zone_service
        if service is not None and hasattr(service, "get_zone_display_name"):
            try:
                return str(service.get_zone_display_name(zone_id, fallback=fallback) or fallback or zone_id)
            except Exception:
                pass
        for zone in self.list_zones():
            if zone.get("id") == zone_id:
                return str(zone.get("display_name") or zone.get("label") or zone.get("timezone") or fallback or zone_id)
        return fallback or zone_id

    def target_zone_id(self) -> str:
        return str(self._settings.get("target_zone_id", "") or "")

    def effective_zone_id(self) -> str:
        zone_ids = {str(zone.get("id") or "") for zone in self.list_zones()}
        selected = self.target_zone_id() or self._last_zone_id
        if selected and (not zone_ids or selected in zone_ids):
            return selected
        return next(iter(zone_ids), "")

    def set_target_zone(self, zone_id: str) -> None:
        zone_id = str(zone_id or "")
        zone_ids = {str(zone.get("id") or "") for zone in self.list_zones()}
        if zone_id and zone_ids and zone_id not in zone_ids:
            zone_id = ""
        if zone_id == self.target_zone_id():
            return
        self._settings["target_zone_id"] = zone_id
        self._save()
        self.target_zone_changed.emit(self.effective_zone_id())

    def set_last_zone(self, zone_id: str) -> None:
        zone_id = str(zone_id or "")
        if zone_id == self._last_zone_id:
            return
        self._last_zone_id = zone_id
        self._save()
        if not self.target_zone_id():
            self.target_zone_changed.emit(self.effective_zone_id())

    def _apply_effective_preset(self, *, force: bool = False) -> None:
        if self._preset_service is None:
            return
        if not force and not bool(self.get_setting("auto_apply_preset", True)):
            return
        zone_id = self.effective_zone_id()
        if not zone_id:
            return
        preset_id = self.resolve_preset_id(self._current_group_id, self._current_item_id)
        if preset_id:
            self._preset_service.apply_preset(preset_id, zone_id)
        elif hasattr(self._preset_service, "clear_active_preset"):
            self._preset_service.clear_active_preset(zone_id)

    def _cleanup_missing_presets(self) -> None:
        changed = False
        for group in self._groups:
            if group.preset_id and not self.has_preset(group.preset_id):
                group.preset_id = ""
                changed = True
            for item in group.items:
                if item.preset_id and not self.has_preset(item.preset_id):
                    item.preset_id = ""
                    changed = True
        if changed:
            self._save()
            self.groups_updated.emit()

    def resolve_preset_id(self, group_id: str, item_id: str = "") -> str:
        item = self.get_item(group_id, item_id) if item_id else None
        if item and item.preset_id and self.has_preset(item.preset_id):
            return item.preset_id
        group = self.get_group(group_id)
        if group and group.preset_id and self.has_preset(group.preset_id):
            return group.preset_id
        return ""

    # ------------------------------------------------------------------ #
    # 分组与事项管理
    # ------------------------------------------------------------------ #

    def groups(self) -> list[StudyGroup]:
        return list(self._groups)

    def get_group(self, group_id: str) -> Optional[StudyGroup]:
        for group in self._groups:
            if group.id == group_id:
                return group
        return None

    def save_group(self, group: StudyGroup) -> None:
        for index, current in enumerate(self._groups):
            if current.id == group.id:
                self._groups[index] = group
                break
        else:
            self._groups.append(group)
        self._save()
        self.groups_updated.emit()
        if not self._current_group_id:
            self.set_current_group(group.id, apply_preset=False)

    def delete_group(self, group_id: str) -> None:
        self._groups = [group for group in self._groups if group.id != group_id]
        if self._current_group_id == group_id:
            self._update_current_group_id("")
            self._update_current_item_id("")
        self._save()
        self.groups_updated.emit()
        self._refresh_runtime_state()

    def items(self, group_id: str) -> list[StudyItem]:
        group = self.get_group(group_id)
        return list(group.items) if group else []

    def get_item(self, group_id: str, item_id: str) -> Optional[StudyItem]:
        group = self.get_group(group_id)
        if group is None:
            return None
        for item in group.items:
            if item.id == item_id:
                return item
        return None

    def _sort_items(self, items: list[StudyItem]) -> list[StudyItem]:
        return sorted(items, key=lambda item: (item.start_time or "99:99", item.end_time or "99:99", item.name))

    def save_item(self, group_id: str, item: StudyItem) -> None:
        group = self.get_group(group_id)
        if group is None:
            return
        for index, current in enumerate(group.items):
            if current.id == item.id:
                group.items[index] = item
                break
        else:
            group.items.append(item)
        group.items = self._sort_items(group.items)
        self._save()
        self.groups_updated.emit()
        self._refresh_runtime_state()

    def delete_item(self, group_id: str, item_id: str) -> None:
        group = self.get_group(group_id)
        if group is None:
            return
        group.items = [item for item in group.items if item.id != item_id]
        if self._current_group_id == group_id and self._current_item_id == item_id:
            self._update_current_item_id("")
        self._save()
        self.groups_updated.emit()
        self._refresh_runtime_state()

    # ------------------------------------------------------------------ #
    # 当前状态
    # ------------------------------------------------------------------ #

    def get_current_group(self) -> Optional[StudyGroup]:
        return self.get_group(self._current_group_id)

    def get_current_item(self) -> Optional[StudyItem]:
        if not self._current_group_id or not self._current_item_id:
            return None
        return self.get_item(self._current_group_id, self._current_item_id)

    @property
    def current_group_id(self) -> str:
        return self._current_group_id

    @property
    def current_item_id(self) -> str:
        return self._current_item_id

    def _update_current_group_id(self, group_id: str) -> None:
        group_id = str(group_id or "")
        if group_id == self._current_group_id:
            return
        self._current_group_id = group_id
        self.current_group_changed.emit(group_id)

    def _update_current_item_id(self, item_id: str) -> None:
        item_id = str(item_id or "")
        if item_id == self._current_item_id:
            return
        self._current_item_id = item_id
        self.current_item_changed.emit(item_id)

    def set_current_group(self, group_id: str, *, apply_preset: bool = True) -> None:
        group = self.get_group(group_id)
        normalized = group.id if group else ""
        self._update_current_group_id(normalized)
        if group is None:
            self._update_current_item_id("")
            self._save()
            if apply_preset:
                self._apply_effective_preset(force=True)
            return

        if self.get_setting("auto_switch_by_time", True):
            item = self._resolve_current_item_for_group(group, datetime.now())
            self._update_current_item_id(item.id if item else "")
        elif self.get_item(normalized, self._current_item_id) is None:
            self._update_current_item_id("")

        self._save()
        if apply_preset:
            self._apply_effective_preset(force=True)

    def set_current_item(self, item_id: str, *, apply_preset: bool = True) -> None:
        group = self.get_current_group()
        if group is None:
            return
        item = self.get_item(group.id, item_id)
        self._update_current_item_id(item.id if item else "")
        self._save()
        if apply_preset:
            self._apply_effective_preset(force=True)

    # ------------------------------------------------------------------ #
    # 设置
    # ------------------------------------------------------------------ #

    def get_setting(self, key: str, default: Any = None) -> Any:
        return self._settings.get(key, default)

    def set_setting(self, key: str, value: Any) -> None:
        if self._settings.get(key) == value:
            return
        self._settings[key] = value
        if key == "check_interval_sec":
            self._apply_timer_interval()
        self._save()
        self.settings_changed.emit(key, value)
        if key in {"auto_switch_by_weekday", "auto_switch_by_time", "auto_apply_preset"}:
            self._refresh_runtime_state()

    def _apply_timer_interval(self) -> None:
        interval_sec = self.get_setting("check_interval_sec", 30)
        try:
            interval_sec = max(5, min(300, int(interval_sec)))
        except (TypeError, ValueError):
            interval_sec = 30
        self._settings["check_interval_sec"] = interval_sec
        self._timer.setInterval(interval_sec * 1000)

    # ------------------------------------------------------------------ #
    # 时间计算
    # ------------------------------------------------------------------ #

    @staticmethod
    def _parse_time(value: str) -> Optional[dtime]:
        try:
            return dtime.fromisoformat(value)
        except ValueError:
            return None

    def _item_range(self, item: StudyItem, now_dt: datetime) -> tuple[Optional[datetime], Optional[datetime]]:
        start_t = self._parse_time(item.start_time)
        end_t = self._parse_time(item.end_time)
        if start_t is None or end_t is None:
            return None, None
        start_dt = datetime.combine(now_dt.date(), start_t)
        end_dt = datetime.combine(now_dt.date(), end_t)
        if end_dt <= start_dt:
            end_dt += timedelta(days=1)
            previous_start = start_dt - timedelta(days=1)
            previous_end = end_dt - timedelta(days=1)
            if previous_start <= now_dt <= previous_end:
                return previous_start, previous_end
        return start_dt, end_dt

    def _next_start_today(self, item: StudyItem, now_dt: datetime) -> Optional[datetime]:
        start_t = self._parse_time(item.start_time)
        if start_t is None:
            return None
        start_dt = datetime.combine(now_dt.date(), start_t)
        if start_dt < now_dt:
            return None
        return start_dt

    def _resolve_group_for_now(self, now_dt: datetime) -> Optional[StudyGroup]:
        if not self._groups:
            return None
        if not bool(self.get_setting("auto_switch_by_weekday", True)):
            return self.get_current_group() or self._groups[0]

        today = now_dt.weekday()
        current = self.get_current_group()
        weekday_groups = [group for group in self._groups if today in group.weekdays]
        if current and current in weekday_groups:
            return current
        if weekday_groups:
            return weekday_groups[0]
        if current and not current.weekdays:
            return current
        fallback_groups = [group for group in self._groups if not group.weekdays]
        if fallback_groups:
            return fallback_groups[0]
        return current or self._groups[0]

    def _resolve_current_item_for_group(self, group: Optional[StudyGroup], now_dt: datetime) -> Optional[StudyItem]:
        if group is None:
            return None
        candidates: list[tuple[datetime, StudyItem]] = []
        for item in group.items:
            if not item.enabled:
                continue
            start_dt, end_dt = self._item_range(item, now_dt)
            if start_dt is None or end_dt is None:
                continue
            if start_dt <= now_dt <= end_dt:
                candidates.append((start_dt, item))
        if not candidates:
            return None
        candidates.sort(key=lambda entry: entry[0])
        return candidates[0][1]

    def get_next_item(self, now_dt: Optional[datetime] = None) -> tuple[Optional[StudyGroup], Optional[StudyItem]]:
        now_dt = now_dt or datetime.now()
        group = self.get_current_group() or self._resolve_group_for_now(now_dt)
        if group is None:
            return None, None
        candidates: list[tuple[datetime, StudyItem]] = []
        for item in group.items:
            if not item.enabled:
                continue
            start_dt = self._next_start_today(item, now_dt)
            if start_dt is not None:
                candidates.append((start_dt, item))
        if not candidates:
            return group, None
        candidates.sort(key=lambda entry: entry[0])
        return group, candidates[0][1]

    # ------------------------------------------------------------------ #
    # 运行期刷新
    # ------------------------------------------------------------------ #

    def _refresh_runtime_state(self) -> None:
        now_dt = datetime.now().replace(second=0, microsecond=0)
        changed = False

        target_group = self._resolve_group_for_now(now_dt)
        target_group_id = target_group.id if target_group else ""
        if target_group_id != self._current_group_id:
            self._update_current_group_id(target_group_id)
            changed = True

        if bool(self.get_setting("auto_switch_by_time", True)):
            target_item = self._resolve_current_item_for_group(target_group, now_dt)
            target_item_id = target_item.id if target_item else ""
            if target_item_id != self._current_item_id:
                self._update_current_item_id(target_item_id)
                changed = True
        elif self._current_group_id and self.get_item(self._current_group_id, self._current_item_id) is None:
            self._update_current_item_id("")
            changed = True

        if changed:
            self._save()
            self._apply_effective_preset(force=False)


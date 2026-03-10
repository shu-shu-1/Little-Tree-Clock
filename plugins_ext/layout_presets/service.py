"""共享布局预设服务。"""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping, Optional

from PySide6.QtCore import QObject, Signal

from app.widgets.base_widget import WidgetConfig

from .models import LayoutPreset


class LayoutPresetService(QObject):
    """跨插件共享的画布布局预设服务。"""

    presets_updated = Signal()
    active_preset_changed = Signal(str, str)
    current_zone_changed = Signal(str)

    def __init__(self, data_dir: Path, api, world_zone_service=None, parent=None):
        super().__init__(parent)
        self._data_dir = data_dir
        self._api = api
        self._world_zone_service = world_zone_service
        self._presets: list[LayoutPreset] = []
        self._active_preset_ids: dict[str, str] = {}
        self._current_zone_id: str = ""
        self._load()

    # ------------------------------------------------------------------ #
    # 持久化
    # ------------------------------------------------------------------ #

    def _data_path(self) -> Path:
        return self._data_dir / "layout_presets.json"

    def _load(self) -> None:
        path = self._data_path()
        if not path.exists():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            self._presets = []
            return
        self._presets = [
            LayoutPreset.from_dict(item)
            for item in raw.get("presets", [])
            if isinstance(item, dict)
        ]

    def _save(self) -> None:
        path = self._data_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {"presets": [preset.to_dict() for preset in self._presets]},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------ #
    # zone 访问
    # ------------------------------------------------------------------ #

    @property
    def current_zone_id(self) -> str:
        return self._current_zone_id

    def set_current_zone(self, zone_id: str) -> None:
        zone_id = str(zone_id or "")
        if zone_id == self._current_zone_id:
            return
        self._current_zone_id = zone_id
        self.current_zone_changed.emit(zone_id)

    def list_zones(self) -> list[dict[str, Any]]:
        service = self._world_zone_service
        if service is None:
            return []
        if hasattr(service, "list_zone_options"):
            try:
                return list(service.list_zone_options())
            except Exception:
                return []
        if not hasattr(service, "list_zones"):
            return []
        result: list[dict[str, Any]] = []
        try:
            for zone in service.list_zones():
                result.append({
                    "id": getattr(zone, "id", ""),
                    "label": getattr(zone, "label", ""),
                    "timezone": getattr(zone, "timezone", ""),
                    "display_name": getattr(zone, "label", "") or getattr(zone, "timezone", ""),
                })
        except Exception:
            return []
        return result

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

    def normalize_zone_id(self, zone_id: str = "") -> str:
        requested = str(zone_id or self._current_zone_id or "")
        zones = self.list_zones()
        if not zones:
            return requested
        zone_ids = {str(zone.get("id") or "") for zone in zones}
        if requested and requested in zone_ids:
            return requested
        return str(zones[0].get("id") or "")

    def _resolve_import_zone_id(self, raw_zone_id: str, fallback_zone_id: str = "") -> str:
        raw_zone_id = str(raw_zone_id or "")
        if raw_zone_id:
            zone_ids = {str(zone.get("id") or "") for zone in self.list_zones()}
            if not zone_ids or raw_zone_id in zone_ids:
                return raw_zone_id
        fallback_zone_id = str(fallback_zone_id or "")
        return self.normalize_zone_id(fallback_zone_id) if fallback_zone_id else ""

    def build_preset_from_layout_file(self, file_path: str | Path, *, fallback_zone_id: str = "") -> LayoutPreset:
        path = Path(file_path)
        raw = json.loads(path.read_text(encoding="utf-8"))

        raw_name = ""
        raw_description = ""
        raw_zone_id = ""
        widgets_data: Any = []

        if isinstance(raw, Mapping):
            raw_name = str(raw.get("name") or "")
            raw_description = str(raw.get("description") or "")
            raw_zone_id = str(raw.get("page_id") or raw.get("zone_id") or "")
            widgets_data = raw.get("widgets")
            if widgets_data is None:
                widgets_data = raw.get("configs", [])
        elif isinstance(raw, list):
            widgets_data = raw
        else:
            raise ValueError("布局文件格式不正确")

        if not isinstance(widgets_data, list):
            raise ValueError("布局文件中缺少可导入的组件列表")

        configs: list[dict[str, Any]] = []
        for index, item in enumerate(widgets_data, start=1):
            if not isinstance(item, Mapping):
                raise ValueError(f"布局文件中的第 {index} 个组件配置无效")
            configs.append(WidgetConfig.from_dict(dict(item)).to_dict())

        return LayoutPreset(
            name=raw_name or path.stem or "未命名预设",
            description=raw_description,
            zone_id=self._resolve_import_zone_id(raw_zone_id, fallback_zone_id),
            configs=configs,
        )

    # ------------------------------------------------------------------ #
    # 预设管理
    # ------------------------------------------------------------------ #

    def presets(self) -> list[LayoutPreset]:
        return list(self._presets)

    def has_preset(self, preset_id: str) -> bool:
        return self.get_preset(preset_id) is not None

    def get_preset(self, preset_id: str) -> Optional[LayoutPreset]:
        for preset in self._presets:
            if preset.id == preset_id:
                return LayoutPreset.from_dict(preset.to_dict())
        return None

    def _coerce_preset(self, preset_like: Any) -> LayoutPreset:
        if isinstance(preset_like, LayoutPreset):
            return LayoutPreset.from_dict(preset_like.to_dict())
        if isinstance(preset_like, Mapping):
            return LayoutPreset.from_dict(dict(preset_like))
        data = {
            "id": getattr(preset_like, "id", ""),
            "name": getattr(preset_like, "name", "未命名预设"),
            "description": getattr(preset_like, "description", ""),
            "zone_id": getattr(preset_like, "zone_id", ""),
            "configs": deepcopy(getattr(preset_like, "configs", [])),
        }
        return LayoutPreset.from_dict(data)

    def save_preset(self, preset_like: Any) -> LayoutPreset:
        preset = self._coerce_preset(preset_like)
        for index, current in enumerate(self._presets):
            if current.id == preset.id:
                self._presets[index] = preset
                self._save()
                self.presets_updated.emit()
                return LayoutPreset.from_dict(preset.to_dict())
        self._presets.append(preset)
        self._save()
        self.presets_updated.emit()
        return LayoutPreset.from_dict(preset.to_dict())

    def create_preset(self, name: str, description: str = "", zone_id: str = "", configs=None) -> LayoutPreset:
        preset = LayoutPreset(
            name=name or "未命名预设",
            description=description,
            zone_id=zone_id,
            configs=deepcopy(list(configs or [])),
        )
        return self.save_preset(preset)

    def capture_zone_layout(self, zone_id: str) -> list[dict[str, Any]]:
        zone_id = self.normalize_zone_id(zone_id)
        if not zone_id:
            return []
        return list(self._api.get_canvas_layout(zone_id))

    def create_preset_from_zone(
        self,
        zone_id: str,
        *,
        name: str,
        description: str = "",
        preset_id: str = "",
    ) -> Optional[LayoutPreset]:
        zone_id = self.normalize_zone_id(zone_id)
        if not zone_id:
            return None
        configs = self.capture_zone_layout(zone_id)
        if preset_id:
            preset = self.get_preset(preset_id)
            if preset is None:
                return None
            preset.name = name or preset.name
            preset.description = description
            preset.zone_id = zone_id
            preset.configs = configs
            return self.save_preset(preset)
        return self.create_preset(name=name, description=description, zone_id=zone_id, configs=configs)

    def update_preset_from_zone(self, preset_id: str, zone_id: str) -> Optional[LayoutPreset]:
        preset = self.get_preset(preset_id)
        if preset is None:
            return None
        return self.create_preset_from_zone(
            zone_id,
            name=preset.name,
            description=preset.description,
            preset_id=preset.id,
        )

    def delete_preset(self, preset_id: str) -> None:
        self._presets = [preset for preset in self._presets if preset.id != preset_id]
        for zone_id, active_id in list(self._active_preset_ids.items()):
            if active_id == preset_id:
                self._active_preset_ids.pop(zone_id, None)
                self.active_preset_changed.emit(zone_id, "")
        self._save()
        self.presets_updated.emit()

    # ------------------------------------------------------------------ #
    # 当前应用状态
    # ------------------------------------------------------------------ #

    def get_active_preset_id(self, zone_id: str) -> str:
        return self._active_preset_ids.get(zone_id, "")

    def get_active_preset(self, zone_id: str) -> Optional[LayoutPreset]:
        preset_id = self.get_active_preset_id(zone_id)
        return self.get_preset(preset_id) if preset_id else None

    def clear_active_preset(self, zone_id: str) -> None:
        zone_id = str(zone_id or "")
        if not zone_id:
            return
        if zone_id in self._active_preset_ids:
            self._active_preset_ids.pop(zone_id, None)
            self.active_preset_changed.emit(zone_id, "")

    def apply_preset(self, preset_id: str, zone_id: str) -> bool:
        zone_id = self.normalize_zone_id(zone_id)
        preset = self.get_preset(preset_id)
        if preset is None or not zone_id:
            return False
        self._api.apply_canvas_layout(zone_id, deepcopy(preset.configs))
        self._active_preset_ids[zone_id] = preset.id
        self.active_preset_changed.emit(zone_id, preset.id)
        self.set_current_zone(zone_id)
        return True

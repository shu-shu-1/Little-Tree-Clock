"""小组件布局持久化"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List

from app.widgets.base_widget import WidgetConfig
from app.constants import WIDGET_LAYOUT_CONFIG


class WidgetLayoutStore:
    """按 page_id 存储各页的小组件布局列表。

    数据格式（widget_layouts.json）：
    {
        "zone_abc123": [
            {"widget_id": "...", "widget_type": "clock", "grid_x": 0, ...},
            ...
        ]
    }
    """

    def __init__(self):
        self._path = Path(WIDGET_LAYOUT_CONFIG)
        self._data: dict[str, list[dict]] = {}
        self._load()

    # ------------------------------------------------------------------ #

    def get(self, page_id: str) -> List[WidgetConfig]:
        return [WidgetConfig.from_dict(d) for d in self._data.get(page_id, [])]

    def save(self, page_id: str, configs: List[WidgetConfig]) -> None:
        self._data[page_id] = [c.to_dict() for c in configs]
        self._persist()

    # ------------------------------------------------------------------ #

    def _load(self) -> None:
        try:
            if self._path.exists():
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            self._data = {}

    def _persist(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

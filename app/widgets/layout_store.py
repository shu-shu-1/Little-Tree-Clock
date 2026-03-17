"""小组件布局持久化"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, List

from app.widgets.base_widget import WidgetConfig
from app.constants import WIDGET_LAYOUT_CONFIG
from app.utils.fs import write_text_with_uac
from app.utils.logger import logger


class WidgetLayoutStore:
    """按 page_id 存储各页的小组件布局列表。

    数据格式（widget_layouts.json）：
    {
        "zone_abc123": [
            {"widget_id": "...", "widget_type": "clock", "grid_x": 0, ...},
            ...
        ],

        # 新格式（兼容旧格式）
        "zone_def456": {
            "widgets": [
                {"widget_id": "...", "widget_type": "clock", "grid_x": 0, ...}
            ],
            "detached": [
                {
                    "origin_x": 10,
                    "origin_y": 5,
                    "entries": [
                        {
                            "offset_x": 0,
                            "offset_y": 0,
                            "widget": {"widget_id": "...", "widget_type": "calendar", ...}
                        }
                    ]
                }
            ]
        }
    }
    """

    def __init__(self):
        self._path = Path(WIDGET_LAYOUT_CONFIG)
        self._data: dict[str, Any] = {}
        self._load()

    # ------------------------------------------------------------------ #

    def get(self, page_id: str) -> List[WidgetConfig]:
        record = self._page_record(page_id)
        return [WidgetConfig.from_dict(d) for d in record["widgets"]]

    def reload(self) -> None:
        """从磁盘重新加载布局缓存。"""
        self._load()

    def get_detached(self, page_id: str) -> list[dict[str, Any]]:
        """读取页面的分离窗口布局记录。"""
        record = self._page_record(page_id)
        return self._normalize_detached_layout(record["detached"])

    def has_page(self, page_id: str) -> bool:
        """返回某个 page_id 是否已经有过持久化记录（即使记录为空列表）。"""
        return page_id in self._data

    def save(self, page_id: str, configs: List[WidgetConfig]) -> None:
        self.save_with_detached(page_id, configs, [])

    def save_with_detached(
        self,
        page_id: str,
        configs: List[WidgetConfig],
        detached_layout: list[dict[str, Any]],
    ) -> None:
        widgets_payload = [c.to_dict() for c in configs]
        detached_payload = self._normalize_detached_layout(detached_layout)

        # 无分离窗口时仍写旧格式，降低对外部调用方影响。
        if detached_payload:
            self._data[page_id] = {
                "widgets": widgets_payload,
                "detached": detached_payload,
            }
        else:
            self._data[page_id] = widgets_payload

        self._persist()
        logger.debug(
            "[画布布局] 已保存页面 {}，组件 {} 个，分离窗口 {} 个",
            page_id,
            len(configs),
            len(detached_payload),
        )

    # ------------------------------------------------------------------ #

    def _page_record(self, page_id: str) -> dict[str, list[Any]]:
        raw = self._data.get(page_id)

        if isinstance(raw, dict):
            widgets = raw.get("widgets", [])
            detached = raw.get("detached", [])
            if not isinstance(widgets, list):
                widgets = []
            if not isinstance(detached, list):
                detached = []
            return {
                "widgets": widgets,
                "detached": detached,
            }

        if isinstance(raw, list):
            return {
                "widgets": raw,
                "detached": [],
            }

        return {
            "widgets": [],
            "detached": [],
        }

    @staticmethod
    def _to_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _normalize_detached_layout(self, detached_layout: list[Any]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for raw_record in detached_layout:
            if not isinstance(raw_record, dict):
                continue
            raw_entries = raw_record.get("entries", [])
            if not isinstance(raw_entries, list):
                continue

            entries: list[dict[str, Any]] = []
            for raw_entry in raw_entries:
                if not isinstance(raw_entry, dict):
                    continue
                raw_widget = raw_entry.get("widget")
                if not isinstance(raw_widget, dict):
                    continue

                entries.append(
                    {
                        "offset_x": self._to_int(raw_entry.get("offset_x", 0), 0),
                        "offset_y": self._to_int(raw_entry.get("offset_y", 0), 0),
                        "widget": copy.deepcopy(raw_widget),
                    }
                )

            if not entries:
                continue

            normalized.append(
                {
                    "origin_x": self._to_int(raw_record.get("origin_x", 0), 0),
                    "origin_y": self._to_int(raw_record.get("origin_y", 0), 0),
                    "entries": entries,
                }
            )

        return normalized

    def _load(self) -> None:
        try:
            if self._path.exists():
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._data = data if isinstance(data, dict) else {}
                logger.debug("[画布布局] 已加载页面 {} 个", len(self._data))
        except Exception:
            logger.exception("[画布布局] 读取布局文件失败：{}", self._path)
            self._data = {}

    def _persist(self) -> None:
        try:
            write_text_with_uac(
                self._path,
                json.dumps(self._data, ensure_ascii=False, indent=2),
                encoding="utf-8",
                ensure_parent=True,
            )
        except Exception:
            logger.exception("[画布布局] 写入布局文件失败：{}", self._path)
            raise

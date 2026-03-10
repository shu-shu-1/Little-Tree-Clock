"""共享布局预设模型。"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class LayoutPreset:
    """一个可复用的全屏画布布局预设。"""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = "未命名预设"
    description: str = ""
    zone_id: str = ""
    configs: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "zone_id": self.zone_id,
            "configs": self.configs,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LayoutPreset":
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            name=data.get("name", "未命名预设"),
            description=data.get("description", ""),
            zone_id=data.get("zone_id", ""),
            configs=list(data.get("configs", [])),
        )

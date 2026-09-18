"""pytest 全局配置：将项目根目录加入 sys.path 以便导入 `app` 包。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """将所有数据模型的持久化路径指向 tmp_path 下的 config/。

    各 store 模块通过 `from app.constants import XXX_CONFIG` 在自身命名空间绑定路径名，
    需逐模块 monkeypatch；并重置带类级缓存的 store（WorldZoneStore / FocusStore）防止跨测试污染。
    """
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    import app.models.alarm_model as alarm_model
    import app.models.automation_model as automation_model
    import app.models.focus_model as focus_model
    import app.models.world_zone as world_zone

    monkeypatch.setattr(alarm_model, "ALARM_CONFIG", str(config_dir / "alarms.json"))
    monkeypatch.setattr(automation_model, "AUTOMATION_CONFIG", str(config_dir / "automation.json"))
    monkeypatch.setattr(focus_model, "FOCUS_CONFIG", str(config_dir / "focus.json"))
    monkeypatch.setattr(world_zone, "WORLD_TIME_CONFIG", str(config_dir / "world_time.json"))

    world_zone.WorldZoneStore._cache_mtime_ns = None
    world_zone.WorldZoneStore._cache_zones = None
    focus_model.FocusStore._cache_mtime_ns = None
    focus_model.FocusStore._cache_presets = None

    yield config_dir

    world_zone.WorldZoneStore._cache_mtime_ns = None
    world_zone.WorldZoneStore._cache_zones = None
    focus_model.FocusStore._cache_mtime_ns = None
    focus_model.FocusStore._cache_presets = None

"""app.widgets.canvas 层级压缩单元测试：用桩对象直接调用 _compact_layers，避免实例化 Qt 画布。"""

from __future__ import annotations

from dataclasses import dataclass

from app.widgets.base_widget import WidgetConfig
from app.widgets.canvas import WidgetCanvas


@dataclass
class _StubItem:
    config: WidgetConfig


class _StubCanvas:
    _compact_layers = WidgetCanvas._compact_layers

    def __init__(self, layers: list[int]) -> None:
        self._items = [_StubItem(WidgetConfig(widget_type="clock", layer=layer)) for layer in layers]

    def layers(self) -> list[int]:
        return [it.config.layer for it in self._items]


class TestCompactLayers:
    def test_removes_gaps_and_renumbers(self):
        canvas = _StubCanvas([0, 2, 5])
        changed = canvas._compact_layers()
        # 相对顺序不变：0 -> 0, 2 -> 1, 5 -> 2
        assert canvas.layers() == [0, 1, 2]
        assert len(changed) == 2

    def test_no_change_when_already_compact(self):
        canvas = _StubCanvas([1, 0, 2])  # 乱序但层号连续
        changed = canvas._compact_layers()
        assert canvas.layers() == [1, 0, 2]
        assert changed == []

    def test_duplicate_layers_get_stable_numbers(self):
        canvas = _StubCanvas([1, 1, 0])
        changed = canvas._compact_layers()
        # 重复层号按原有先后顺序拆分为 1、2，第三项保持 0
        assert canvas.layers() == [1, 2, 0]
        assert len(changed) == 1

    def test_negative_layer_is_normalized(self):
        canvas = _StubCanvas([-1, 0, 3])
        changed = canvas._compact_layers()
        assert sorted(canvas.layers()) == [0, 1, 2]
        assert len(changed) == 3

    def test_empty_canvas(self):
        canvas = _StubCanvas([])
        assert canvas._compact_layers() == []

    def test_single_item_with_high_layer(self):
        canvas = _StubCanvas([7])
        changed = canvas._compact_layers()
        assert canvas.layers() == [0]
        assert len(changed) == 1

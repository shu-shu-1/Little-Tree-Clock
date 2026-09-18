"""分离组件窗口（DetachedWidgetWindow）行为测试：后台识别、合并回画布、重进画布不丢组件。"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")
pytest.importorskip("qfluentwidgets")

from app.widgets.base_widget import WidgetBase, WidgetConfig


class _StubWidget(WidgetBase):
    WIDGET_TYPE = "_test_stub_"
    WIDGET_NAME = "测试组件"

    def refresh(self) -> None:  # pragma: no cover
        pass


class _StubBackgroundWidget(_StubWidget):
    WIDGET_TYPE = "_test_stub_bg_"
    RUNS_IN_BACKGROUND = True


@pytest.fixture(scope="module")
def qtapp():
    from PySide6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])


@pytest.fixture()
def isolated_layout_store(tmp_path, monkeypatch):
    """将布局持久化指向临时目录，避免读写真实 config/widget_layouts.json。"""
    import app.widgets.layout_store as layout_store

    monkeypatch.setattr(layout_store, "WIDGET_LAYOUT_CONFIG", str(tmp_path / "widget_layouts.json"))
    layout_store.WidgetLayoutStore._instance = None
    yield layout_store.WidgetLayoutStore.instance()
    layout_store.WidgetLayoutStore._instance = None


@pytest.fixture()
def clean_detached_registry(qtapp, isolated_layout_store):
    """每个测试前后清空分离窗口全局注册表，避免跨测试污染。"""
    from app.widgets.canvas import DetachedWidgetWindow

    DetachedWidgetWindow._instances.clear()
    DetachedWidgetWindow._orphaned.clear()
    yield DetachedWidgetWindow
    for win in list(DetachedWidgetWindow._instances):
        try:
            win._settings.changed.disconnect(win._apply_container_style)
        except Exception:
            pass
    DetachedWidgetWindow._instances.clear()
    DetachedWidgetWindow._orphaned.clear()


@pytest.fixture()
def clean_background_service(qtapp):
    from app.services.background_canvas_service import BackgroundCanvasService

    svc = BackgroundCanvasService.instance()
    svc._pages.clear()
    yield svc
    svc.shutdown()


def _make_canvas(page_id: str = "zone_test"):
    from app.widgets.canvas import WidgetCanvas

    return WidgetCanvas(page_id, {}, parent=None, lazy_load=False)


def _make_entry(widget_cls=_StubWidget, **cfg_kwargs):
    cfg = WidgetConfig(widget_type=widget_cls.WIDGET_TYPE, grid_w=2, grid_h=2, **cfg_kwargs)
    widget = widget_cls(cfg, {})
    return cfg, widget


def _detached_record(widget_id: str, origin=(1, 1)):
    return {
        "origin_x": origin[0],
        "origin_y": origin[1],
        "entries": [
            {
                "offset_x": 0,
                "offset_y": 0,
                "widget": {"widget_id": widget_id, "widget_type": "_test_stub_"},
            }
        ],
    }


class TestDetachedCountedAsBackground:
    """要求 1：只要有组件被分离，页面就被识别为有后台组件。"""

    def test_orphaned_window_entries_counted(self, clean_detached_registry, clean_background_service):
        svc = clean_background_service
        canvas = _make_canvas("zone_bg")

        cfg1, w1 = _make_entry()
        cfg2, w2 = _make_entry()
        win = canvas._build_detached_window(
            [
                {"config": cfg1, "widget": w1, "offset_x": 0, "offset_y": 0},
                {"config": cfg2, "widget": w2, "offset_x": 2, "offset_y": 0},
            ],
            origin_x=1,
            origin_y=1,
        )
        assert win is not None

        # 画布仍在（未孤立）时不计为后台
        assert svc.page_component_count("zone_bg") == 0
        assert svc.is_page_running("zone_bg") is False
        assert all(item["page_id"] != "zone_bg" for item in svc.active_pages())

        # 画布关闭 → 窗口孤立 → 2 个分离组件被识别为后台组件
        canvas._orphan_detached_windows()
        assert svc.page_component_count("zone_bg") == 2
        assert svc.is_page_running("zone_bg") is True
        assert {"page_id": "zone_bg", "component_count": 2} in svc.active_pages()

    def test_active_pages_includes_detached_only_page(self, clean_detached_registry, clean_background_service):
        svc = clean_background_service
        canvas = _make_canvas("zone_only_detached")

        cfg, w = _make_entry()
        canvas._build_detached_window(
            [{"config": cfg, "widget": w, "offset_x": 0, "offset_y": 0}],
            origin_x=0,
            origin_y=0,
        )
        canvas._orphan_detached_windows()

        # 该页面没有任何挂起实例，仅凭分离窗口也应出现在 active_pages
        assert not svc._pages
        assert {item["page_id"] for item in svc.active_pages()} == {"zone_only_detached"}

    def test_close_orphaned_for_page_clears_background(
        self, clean_detached_registry, clean_background_service, isolated_layout_store
    ):
        from app.widgets.canvas import DetachedWidgetWindow

        svc = clean_background_service
        page = "zone_close_all"
        canvas = _make_canvas(page)

        for _ in range(2):
            cfg, w = _make_entry()
            canvas._build_detached_window(
                [{"config": cfg, "widget": w, "offset_x": 0, "offset_y": 0}],
                origin_x=0,
                origin_y=0,
            )
        canvas._save_layout()
        assert len(isolated_layout_store.get_detached(page)) == 2

        canvas._orphan_detached_windows()
        assert svc.page_component_count(page) == 2

        # 首页"关闭后台运行"：孤立分离窗口一并清理（含持久化记录）
        closed = DetachedWidgetWindow.close_orphaned_for_page(page)
        assert closed == 2
        assert svc.page_component_count(page) == 0
        assert isolated_layout_store.get_detached(page) == []
        assert DetachedWidgetWindow.orphaned_page_ids() == set()


class TestReenterCanvasKeepsDetached:
    """要求 3：重进画布时分离的组件不会消失。"""

    def test_reenter_adopts_orphaned_window(
        self, clean_detached_registry, clean_background_service, isolated_layout_store
    ):
        from shiboken6 import isValid

        page = "zone_reenter"
        canvas1 = _make_canvas(page)

        cfg, w = _make_entry(grid_x=2, grid_y=2)
        win = canvas1._build_detached_window(
            [{"config": cfg, "widget": w, "offset_x": 0, "offset_y": 0}],
            origin_x=3,
            origin_y=2,
        )
        assert win is not None

        # 关闭全屏画布：保存布局并将分离窗口孤立化
        canvas1._save_layout()
        canvas1._orphan_detached_windows()

        # 重进画布（新画布实例加载同一页面）
        canvas2 = _make_canvas(page)

        # 窗口本体存活、被新画布收养，组件实例未销毁
        assert isValid(win)
        assert win.is_orphaned() is False
        assert win in canvas2._active_detached_windows()
        assert win._merge_callback is not None
        assert win._entries and win._entries[0]["widget"] is w

        # 持久化记录仍在，且不会重复恢复同一组件
        records = isolated_layout_store.get_detached(page)
        assert len(records) == 1
        assert records[0]["entries"][0]["widget"]["widget_id"] == cfg.widget_id
        assert len(canvas2._active_detached_windows()) == 1

        # 画布重新打开后，页面不再被识别为后台运行
        assert clean_background_service.page_component_count(page) == 0

    def test_user_close_orphan_prunes_records(
        self, clean_detached_registry, clean_background_service, isolated_layout_store
    ):
        from app.widgets.canvas import DetachedWidgetWindow

        page = "zone_user_close"
        canvas = _make_canvas(page)
        cfg, w = _make_entry()
        canvas._build_detached_window(
            [{"config": cfg, "widget": w, "offset_x": 0, "offset_y": 0}],
            origin_x=1,
            origin_y=1,
        )
        canvas._save_layout()
        canvas._orphan_detached_windows()

        # 用户在画布关闭期间直接关闭分离窗口 = 删除该分离组件
        win = DetachedWidgetWindow._instances[0]
        win.close_for_delete()

        assert isolated_layout_store.get_detached(page) == []
        assert clean_background_service.page_component_count(page) == 0

    def test_reload_while_canvas_open_rebuilds_from_records(
        self, clean_detached_registry, clean_background_service, isolated_layout_store
    ):
        from app.widgets.canvas import DetachedWidgetWindow

        page = "zone_reload"
        canvas = _make_canvas(page)
        canvas.resize(600, 400)

        cfg, w = _make_entry(grid_x=1, grid_y=1)
        canvas._build_detached_window(
            [{"config": cfg, "widget": w, "offset_x": 0, "offset_y": 0}],
            origin_x=2,
            origin_y=1,
        )
        canvas._save_layout()

        # 画布存活期间的布局重载：窗口按记录重建，组件不消失
        canvas.reload_layout()

        wins = canvas._active_detached_windows()
        assert len(wins) == 1
        assert wins[0]._entries[0]["config"].widget_id == cfg.widget_id
        assert len(DetachedWidgetWindow._instances) == 1


class TestMergeDetachedBackToCanvas:
    """要求 2：分离组件能合并回画布。"""

    def test_merge_restores_widget_into_canvas_items(
        self, clean_detached_registry, clean_background_service, isolated_layout_store
    ):
        page = "zone_merge"
        canvas = _make_canvas(page)
        canvas.resize(600, 400)

        cfg, w = _make_entry(grid_x=4, grid_y=3)
        win = canvas._build_detached_window(
            [{"config": cfg, "widget": w, "offset_x": 0, "offset_y": 0}],
            origin_x=4,
            origin_y=3,
        )
        canvas._save_layout()
        assert win is not None

        canvas._merge_detached_window_to_canvas(win)

        # 组件回到画布 items 中，实例保持不变
        items = [it for it in canvas._items if it.config.widget_id == cfg.widget_id]
        assert len(items) == 1
        assert items[0]._widget is w
        assert canvas._active_detached_windows() == []

        # 持久化：分离记录清空，画布布局包含该组件
        assert isolated_layout_store.get_detached(page) == []
        saved_ids = {c.widget_id for c in isolated_layout_store.get(page)}
        assert cfg.widget_id in saved_ids

    def test_merge_after_reenter(self, clean_detached_registry, clean_background_service, isolated_layout_store):
        # 分离 → 关闭画布 → 重进画布 → 合并回画布，全链路可用
        page = "zone_merge_reenter"
        canvas1 = _make_canvas(page)
        canvas1.resize(600, 400)

        cfg, w = _make_entry(grid_x=2, grid_y=2)
        win = canvas1._build_detached_window(
            [{"config": cfg, "widget": w, "offset_x": 0, "offset_y": 0}],
            origin_x=2,
            origin_y=2,
        )
        canvas1._save_layout()
        canvas1._orphan_detached_windows()
        assert win is not None

        canvas2 = _make_canvas(page)
        canvas2.resize(600, 400)
        assert win in canvas2._active_detached_windows()

        canvas2._merge_detached_window_to_canvas(win)
        items = [it for it in canvas2._items if it.config.widget_id == cfg.widget_id]
        assert len(items) == 1
        assert items[0]._widget is w  # 仍是分离前的原实例
        assert isolated_layout_store.get_detached(page) == []


class TestPruneKeepsDetachedBackgroundInstances:
    """分离中的后台组件实例在画布重载时不被误删。"""

    def test_prune_keeps_widget_id_in_detached_records(
        self, clean_detached_registry, clean_background_service, isolated_layout_store
    ):
        from app.services.background_canvas_service import BackgroundCanvasService

        page = "zone_prune"
        canvas = _make_canvas(page)
        svc = BackgroundCanvasService.instance()

        cfg, w = _make_entry(widget_cls=_StubBackgroundWidget)
        assert svc.park_widget(page, w) is True
        assert svc.page_component_count(page) == 1

        # 组件同时存在于分离记录中（画布外的分离形态）→ 剪枝应保留实例
        isolated_layout_store.save_with_detached(page, [], [_detached_record(cfg.widget_id)], [])
        canvas._prune_background_runtime([])
        assert svc.page_component_count(page) == 1

        # 分离记录被清除后 → 实例才允许被回收
        isolated_layout_store.save_with_detached(page, [], [], [])
        canvas._prune_background_runtime([])
        assert svc.page_component_count(page) == 0

"""一言编辑面板 UI 布局测试（离屏 Qt）：验证外部源单选项分组与"全部"筛选两项修复。"""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")
pytest.importorskip("qfluentwidgets")

_PLUGINS_EXT = Path(__file__).resolve().parent.parent / "plugins_ext"
_HITOKOTO_PKG = "panel_test_hitokoto"
_GAOKAO_PKG = "panel_test_gaokao"


def _load_pkg(name: str, pkg_dir: Path):
    spec = importlib.util.spec_from_file_location(
        name, pkg_dir / "__init__.py", submodule_search_locations=[str(pkg_dir)]
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return mod


def _cleanup_pkg(name: str) -> None:
    for key in [k for k in sys.modules if k == name or k.startswith(name + ".")]:
        sys.modules.pop(key, None)


@pytest.fixture(scope="module")
def qtapp():
    from PySide6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])


@pytest.fixture()
def panel_env(qtapp):
    hitokoto = _load_pkg(_HITOKOTO_PKG, _PLUGINS_EXT / "hitokoto_widget")
    gaokao = _load_pkg(_GAOKAO_PKG, _PLUGINS_EXT / "gaokao_poetry")
    widget_mod = importlib.import_module(f"{_HITOKOTO_PKG}.widget")

    iface = hitokoto.Plugin().export()
    assert iface.register_data_source(
        gaokao.SOURCE_ID,
        gaokao.fetch_poetry,
        name="高考古诗词",
        owner_plugin_id="gaokao_poetry",
        options=gaokao.build_options(),
    )
    yield hitokoto, gaokao, widget_mod
    _cleanup_pkg(_HITOKOTO_PKG)
    _cleanup_pkg(_GAOKAO_PKG)


def _form_row(panel, widget) -> int:
    """返回控件在编辑面板表单中的行号（找不到返回 -1）。"""
    row, _role = panel.layout().getWidgetPosition(widget)
    return row


def test_external_radio_grouped_with_builtin_sources(panel_env):
    """外部源单选项必须紧跟内置来源，位于所有设置区之前。"""
    _hitokoto, _gaokao, widget_mod = panel_env
    panel = widget_mod._EditPanel({"source": "hitokoto"})

    row_local = _form_row(panel, panel._rb_local)
    row_ext = _form_row(panel, panel._ext_radios["gaokao_poetry"])
    row_cat = _form_row(panel, panel._cat_section)  # 第一个设置区（一言分类）
    row_file = _form_row(panel, panel._file_section)  # 最后一个内置设置区
    row_ext_sec = _form_row(panel, panel._ext_sections["gaokao_poetry"])

    # 单选项连续：本地文件 < 高考古诗词 < 任何设置区
    assert row_local != -1 and row_ext != -1
    assert row_local < row_ext < row_cat
    # 外部源设置区在全部单选项之后，与其他设置区并列
    assert row_ext_sec > row_ext and row_ext_sec > row_file


def test_filters_support_select_all(panel_env):
    """篇目/作者筛选的"全部"项存在、可选且取数为不过滤。"""
    _hitokoto, gaokao, widget_mod = panel_env
    panel = widget_mod._EditPanel({"source": "gaokao_poetry"})

    controls = panel._ext_controls["gaokao_poetry"]
    title_combo = controls["title_filter"]
    author_combo = controls["author_filter"]

    # 首项即"全部"，值为空字符串
    assert title_combo.itemData(0) == ""
    assert title_combo.itemText(0).startswith("全部篇目")
    assert author_combo.itemData(0) == ""
    assert author_combo.itemText(0).startswith("全部作者")

    # 显式选中"全部"后收集属性，两项筛选均为空
    title_combo.setCurrentIndex(0)
    author_combo.setCurrentIndex(0)
    props = panel.collect_props()
    opts = props["ext_options"]["gaokao_poetry"]
    assert opts["title_filter"] == ""
    assert opts["author_filter"] == ""

    # 空 = 不过滤：从全部 651 句中抽取
    text, source_info, _extras = gaokao.fetch_poetry(opts, props)
    assert text.strip() and source_info.startswith("——")


def test_filters_roundtrip_specific_choice(panel_env):
    """从"全部"切到具体篇目再切回"全部"，取值正确往返。"""
    _hitokoto, _gaokao, widget_mod = panel_env
    panel = widget_mod._EditPanel({"source": "gaokao_poetry"})
    title_combo = panel._ext_controls["gaokao_poetry"]["title_filter"]

    # 选中"琵琶行"（按 itemText 查找，模拟用户操作）
    idx = next(i for i in range(title_combo.count()) if title_combo.itemText(i).startswith("琵琶行"))
    title_combo.setCurrentIndex(idx)
    assert panel.collect_props()["ext_options"]["gaokao_poetry"]["title_filter"] == "琵琶行"

    # 切回"全部"
    title_combo.setCurrentIndex(0)
    assert panel.collect_props()["ext_options"]["gaokao_poetry"]["title_filter"] == ""


def test_gaokao_panel_has_textbook_toggle(panel_env):
    """编辑面板的"高考古诗词"配置区包含"显示教材"开关，默认开启。"""
    _hitokoto, _gaokao, widget_mod = panel_env
    panel = widget_mod._EditPanel({"source": "gaokao_poetry"})
    toggle = panel._ext_controls["gaokao_poetry"]["show_textbook"]
    assert toggle.isChecked() is True

    toggle.setChecked(False)
    assert panel.collect_props()["ext_options"]["gaokao_poetry"]["show_textbook"] is False


def test_worker_emits_extras(panel_env):
    """fetch 返回三元组时，后台 worker 把扩展行随 done 信号传出。"""
    _hitokoto, gaokao, widget_mod = panel_env
    signals = widget_mod._FetchSignals()
    results: list[tuple] = []
    signals.done.connect(lambda *args: results.append(args))

    props = {"source": "gaokao_poetry", "ext_options": {"gaokao_poetry": {"title_filter": "琵琶行"}}}
    widget_mod._FetchWorker(signals, props).run()

    assert len(results) == 1
    text, source_info, extras = results[0]
    assert text.strip() and source_info.endswith("《琵琶行》")
    expected = gaokao._filtered_poems("琵琶行", "")[0]["textbook"]
    assert extras == [("", expected)]  # 已归一化为 (label, text) 行


def test_widget_renders_extra_rows(panel_env):
    """组件为每条扩展行新建一个徽章显示行，并可随出处行隐藏。"""
    from app.widgets.base_widget import WidgetConfig

    _hitokoto, _gaokao, widget_mod = panel_env
    # 禁用抓取以保证测试确定性（不触发后台线程）
    widget_mod.set_central_config({"disable_fetch": True})
    try:
        config = WidgetConfig(widget_type="hitokoto", props={"source": "gaokoto_poetry", "show_author": True})
        w = widget_mod.HitokotoWidget(config, services={})
        w._on_fetch_done("正文内容", "——白居易《琵琶行》", [("", "选择性必修上"), ("教材", "必修上")])

        assert [lbl.text() for lbl in w._extra_labels] == ["选择性必修上", "教材：必修上"]
        # 组件未 show，用 isVisibleTo 断言相对父组件的可见性
        assert w._extra_container.isVisibleTo(w) is True

        # 关闭"显示出处 / 作者"后扩展行一并隐藏
        w.config.props["show_author"] = False
        w._redraw()
        assert w._extra_container.isVisibleTo(w) is False

        # 无扩展行时容器隐藏
        w._on_fetch_done("另一句", "——李白《静夜思》", [])
        assert w._extra_labels == []
        assert w._extra_container.isVisibleTo(w) is False
        w.deleteLater()
    finally:
        widget_mod.set_central_config({})

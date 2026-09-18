"""高考古诗词插件核心逻辑测试（不依赖 Qt 事件循环），插件 `__init__.py` 无相对导入，可按文件路径独立加载。"""

from __future__ import annotations

import importlib.util
import sys
from collections import Counter
from pathlib import Path

import pytest

_PLUGIN_PATH = Path(__file__).resolve().parent.parent / "plugins_ext" / "gaokao_poetry" / "__init__.py"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    # dataclass 等机制依赖 sys.modules 中能找到所属模块
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return mod


@pytest.fixture(scope="module")
def poetry():
    return _load_module("gaokao_poetry_under_test", _PLUGIN_PATH)


def test_builtin_data_loaded(poetry):
    poems = poetry._ensure_poems()
    assert len(poems) == 651
    for item in poems:
        assert item["title"]
        assert item["author"]
        assert item["content"]
        assert "textbook" in item  # 新版数据全量带教材标注


def test_textbook_values(poetry):
    """教材字段取值应为五本教材或"教材无"。"""
    valid = {"必修上", "必修下", "选择性必修上", "选择性必修中", "选择性必修下", "教材无"}
    for item in poetry._ensure_poems():
        assert item["textbook"] in valid, item["textbook"]


def test_options_choices_built_from_data(poetry):
    options = poetry.build_options()
    by_key = {opt["key"]: opt for opt in options}
    assert set(by_key) == {"title_filter", "author_filter", "show_textbook", "no_repeat"}
    assert by_key["show_textbook"]["type"] == "bool"
    assert by_key["show_textbook"]["default"] is True

    # 篇目/作者下拉均含"全部"空值项，且数量与数据一致
    titles = [pair[0] for pair in by_key["title_filter"]["choices"]]
    authors = [pair[0] for pair in by_key["author_filter"]["choices"]]
    assert titles[0] == "" and len(titles) == 61  # 60 个唯一篇目 + 全部
    assert authors[0] == "" and len(authors) == 47  # 46 个唯一作者 + 全部

    assert by_key["no_repeat"]["type"] == "bool"
    assert by_key["no_repeat"]["default"] is True


def test_fetch_returns_text_and_source(poetry):
    text, source_info, extras = poetry.fetch_poetry({}, {})
    assert text.strip()
    assert source_info.startswith("——")
    assert "《" in source_info or source_info.startswith("——《")
    assert isinstance(extras, list)


def test_fetch_filters_by_title(poetry):
    target = "琵琶行"
    for _ in range(10):
        _text, source_info, _extras = poetry.fetch_poetry({"title_filter": target}, {})
        assert source_info.endswith(f"《{target}》")


def test_fetch_filters_by_author(poetry):
    target = "李白"
    for _ in range(10):
        _text, source_info, _extras = poetry.fetch_poetry({"author_filter": target}, {})
        assert source_info.startswith(f"——{target}")


def test_fetch_combined_filters_and(poetry):
    for _ in range(10):
        _text, source_info, _extras = poetry.fetch_poetry({"title_filter": "琵琶行", "author_filter": "白居易"}, {})
        assert source_info == "——白居易《琵琶行》"


def test_fetch_impossible_filter_raises(poetry):
    with pytest.raises(ValueError):
        poetry.fetch_poetry({"title_filter": "琵琶行", "author_filter": "李白"}, {})


def test_no_repeat_covers_whole_pool(poetry):
    """开启不重复后，连续抽取 pool 大小次应覆盖全部句子。"""
    target = "山居秋暝"  # 恰好 2 条
    seen = set()
    for _ in range(2):
        text, _info, _extras = poetry.fetch_poetry({"title_filter": target, "no_repeat": True}, {})
        seen.add(text)
    assert len(seen) == 2


def test_no_repeat_resets_after_round(poetry):
    """一轮抽完后自动重置，之后仍能抽到内容。"""
    target = "涉江采芙蓉"  # 恰好 2 条
    got = [poetry.fetch_poetry({"title_filter": target, "no_repeat": True}, {}) for _ in range(4)]
    assert len({result[0] for result in got}) == 2  # 2 条句子反复出现，无异常


def test_repeat_allowed_when_disabled(poetry):
    """关闭不重复后，短期内同一句可以再次出现（不受 recent 记录限制）。"""
    target = "山居秋暝"
    texts = [poetry.fetch_poetry({"title_filter": target, "no_repeat": False}, {})[0] for _ in range(50)]
    # 2 条句子，50 次抽取应两者都出现过（未漏抽）
    assert len(set(texts)) == 2


def test_fetch_textbook_extras(poetry):
    """开启"显示教材"时，扩展行携带该篇教材徽章文本。"""
    pool = poetry._filtered_poems("琵琶行", "")
    expected = pool[0]["textbook"]
    for _ in range(10):
        _text, _info, extras = poetry.fetch_poetry({"title_filter": "琵琶行"}, {})
        assert extras == [expected]


def test_fetch_textbook_extras_hidden_when_disabled(poetry):
    _text, _info, extras = poetry.fetch_poetry({"title_filter": "琵琶行", "show_textbook": False}, {})
    assert extras == []


def test_fetch_textbook_extras_skip_no_textbook(poetry):
    """教材为"教材无"的篇目不产生徽章。"""
    no_tb_titles = {p["title"] for p in poetry._ensure_poems() if p["textbook"] == "教材无"}
    assert no_tb_titles  # 数据中存在此类篇目
    target = sorted(no_tb_titles)[0]
    _text, _info, extras = poetry.fetch_poetry({"title_filter": target}, {})
    assert extras == []


def test_source_info_bracket_handling(poetry):
    plain = {"title": "静夜思", "author": "李白", "content": ["床前明月光"]}
    assert poetry._format_source_info(plain) == "——李白《静夜思》"

    quoted = {"title": "《论语》十二章", "author": "孔子弟子及再传弟子", "content": ["子曰……"]}
    # 标题自带书名号时不再重复包裹
    assert poetry._format_source_info(quoted) == "——孔子弟子及再传弟子《论语》十二章"

    no_author = {"title": "无名篇", "author": "", "content": ["x"]}
    assert poetry._format_source_info(no_author) == "——《无名篇》"


def test_options_and_fetch_pass_registry_validation(poetry):
    """用真实注册表验证本插件注册时声明的 options 与 fetch 符合契约。"""
    sources = _load_module(
        "hitokoto_sources_for_gaokao",
        Path(_PLUGIN_PATH).parent.parent / "hitokoto_widget" / "sources.py",
    )

    ok = sources.register_external_source(
        poetry.SOURCE_ID,
        poetry.fetch_poetry,
        name="高考古诗词",
        name_i18n={"zh-CN": "高考古诗词", "en-US": "Gaokao Poetry"},
        owner_plugin_id="gaokao_poetry",
        options=poetry.build_options(),
    )
    assert ok is True

    ext = sources.get_external_source(poetry.SOURCE_ID)
    assert ext is not None

    # 通过 read_ext_options 走完整取数路径（模拟 widget 的调用方式）
    options = sources.read_ext_options(
        {"source": poetry.SOURCE_ID, "ext_options": {poetry.SOURCE_ID: {"title_filter": "琵琶行"}}},
        poetry.SOURCE_ID,
    )
    text, source_info, extras = ext.fetch(options, {"source": poetry.SOURCE_ID})
    assert text.strip()
    assert source_info.endswith("《琵琶行》")
    assert extras and isinstance(extras, list)

    sources.clear_external_sources()


def test_title_counts_match_data(poetry):
    """下拉选项里的句数标注与实际数据一致。"""
    options = poetry.build_options()
    title_opt = next(o for o in options if o["key"] == "title_filter")
    counts = Counter(p["title"] for p in poetry._ensure_poems())
    total = len(poetry._ensure_poems())

    for value, label in title_opt["choices"]:
        if value == "":
            assert label == f"全部篇目（共 {total} 句）"
            continue
        assert label == f"{value}（{counts[value]} 句）", label

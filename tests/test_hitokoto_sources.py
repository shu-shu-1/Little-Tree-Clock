"""「随机一言」外部数据源注册表（sources.py）单元测试：按文件路径独立加载，避免依赖插件包与 Qt。"""

from __future__ import annotations

import importlib.util
import sys
import threading
from pathlib import Path

import pytest

_SOURCES_PATH = Path(__file__).resolve().parent.parent / "plugins_ext" / "hitokoto_widget" / "sources.py"


def _load_sources():
    name = "hitokoto_sources_under_test"
    spec = importlib.util.spec_from_file_location(name, _SOURCES_PATH)
    mod = importlib.util.module_from_spec(spec)
    # dataclass 等机制依赖 sys.modules 中能找到所属模块
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.modules.pop(name, None)
    return mod


@pytest.fixture
def sources():
    mod = _load_sources()
    yield mod
    mod.clear_external_sources()


def test_register_and_get(sources):
    ok = sources.register_external_source(
        "demo",
        lambda options, props: ("hi", "——测试"),
        name="演示",
        owner_plugin_id="demo_plugin",
    )
    assert ok is True

    ext = sources.get_external_source("demo")
    assert ext is not None
    assert ext.name == "演示"
    assert ext.owner_plugin_id == "demo_plugin"
    assert ext.display_name("en-US") == "演示"  # 无 en-US 时回退
    assert callable(ext.fetch)
    assert sources.get_external_source("nope") is None


def test_register_rejects_invalid_ids(sources):
    fetch = lambda options, props: ("hi", "")  # noqa: E731

    # 非法字符 / 空 / 与内置来源重名 一律拒绝
    assert sources.register_external_source("Bad_ID", fetch) is False
    assert sources.register_external_source("", fetch) is False
    assert sources.register_external_source("1abc", fetch) is False
    for builtin in sources.BUILTIN_SOURCE_IDS:
        assert sources.register_external_source(builtin, fetch) is False


def test_register_rejects_non_callable(sources):
    assert sources.register_external_source("demo", "not-callable") is False


def test_same_owner_can_replace_other_owner_cannot(sources):
    fetch = lambda options, props: ("hi", "")  # noqa: E731

    assert sources.register_external_source("demo", fetch, name="第一版", owner_plugin_id="a") is True
    # 同一提供方可覆盖更新
    assert sources.register_external_source("demo", fetch, name="第二版", owner_plugin_id="a") is True
    assert sources.get_external_source("demo").name == "第二版"
    # 其他提供方不能抢占
    assert sources.register_external_source("demo", fetch, name="劫持", owner_plugin_id="b") is False
    assert sources.get_external_source("demo").name == "第二版"


def test_unregister_ownership(sources):
    fetch = lambda options, props: ("hi", "")  # noqa: E731
    sources.register_external_source("demo", fetch, owner_plugin_id="a")

    # 归属不符拒绝
    assert sources.unregister_external_source("demo", owner_plugin_id="b") is False
    assert sources.get_external_source("demo") is not None
    # 归属相符成功
    assert sources.unregister_external_source("demo", owner_plugin_id="a") is True
    assert sources.get_external_source("demo") is None
    # 不存在的来源
    assert sources.unregister_external_source("demo") is False


def test_unregister_sources_of_and_clear(sources):
    fetch = lambda options, props: ("hi", "")  # noqa: E731
    sources.register_external_source("a1", fetch, owner_plugin_id="a")
    sources.register_external_source("a2", fetch, owner_plugin_id="a")
    sources.register_external_source("b1", fetch, owner_plugin_id="b")

    assert sources.unregister_sources_of("a") == ["a1", "a2"]
    assert [e.source_id for e in sources.all_external_sources()] == ["b1"]

    assert set(sources.clear_external_sources()) == {"b1"}
    assert sources.all_external_sources() == []


def test_options_normalization(sources):
    ok = sources.register_external_source(
        "demo",
        lambda options, props: ("hi", ""),
        options=[
            {"key": "theme", "label": "主题", "type": "choice", "choices": [("x", "甲"), ("y", "乙")], "default": "y"},
            {"key": "verbose", "label": "详细", "type": "bool", "default": True},
            {"key": "Bad Key", "label": "非法键", "type": "bool"},  # 键非法 → 跳过
            {"key": "weird", "label": "未知类型", "type": "slider"},  # 类型未知 → 跳过
            "不是dict",  # 整条非法 → 跳过
        ],
    )
    assert ok is True
    ext = sources.get_external_source("demo")
    assert [opt.key for opt in ext.options] == ["theme", "verbose"]

    theme = ext.options[0]
    assert theme.default == "y"
    assert theme.choices == (("x", "甲"), ("y", "乙"))

    verbose = ext.options[1]
    assert verbose.type == "bool"
    assert verbose.default is True


def test_choice_default_falls_back_to_first(sources):
    ok = sources.register_external_source(
        "demo",
        lambda options, props: ("hi", ""),
        options=[{"key": "t", "type": "choice", "choices": [("x", "甲")], "default": "不存在"}],
    )
    assert ok is True
    assert sources.get_external_source("demo").options[0].default == "x"


def test_choice_requires_nonempty_choices(sources):
    ok = sources.register_external_source(
        "demo",
        lambda options, props: ("hi", ""),
        options=[{"key": "t", "type": "choice", "choices": []}],
    )
    assert ok is True
    assert sources.get_external_source("demo").options == ()


def test_read_ext_options_merges_defaults(sources):
    sources.register_external_source(
        "demo",
        lambda options, props: ("hi", ""),
        owner_plugin_id="a",
        options=[
            {"key": "theme", "type": "choice", "choices": [("x", "甲"), ("y", "乙")], "default": "x"},
            {"key": "verbose", "type": "bool", "default": False},
        ],
    )
    props = {"ext_options": {"demo": {"theme": "y"}}}
    merged = sources.read_ext_options(props, "demo")
    assert merged == {"theme": "y", "verbose": False}  # 未设置的键取默认值

    # 未注册的来源返回空；结构异常的 props 回退到该来源的全部默认值
    assert sources.read_ext_options({"ext_options": {"demo": {"theme": "y"}}}, "other") == {}
    assert sources.read_ext_options(None, "demo") == {"theme": "x", "verbose": False}
    assert sources.read_ext_options({"ext_options": "坏结构"}, "demo") == {"theme": "x", "verbose": False}


def test_resolve_localized(sources):
    mapping = {"en-US": "Hello", "zh-CN": "你好"}
    assert sources.resolve_localized(mapping, "fallback", "en-US") == "Hello"
    assert sources.resolve_localized(mapping, "fallback", "fr-FR") == "你好"  # 回退 zh-CN
    assert sources.resolve_localized({"ja": "こんにちは"}, "fb", "en-US") == "こんにちは"
    assert sources.resolve_localized(None, "fb", "en-US") == "fb"
    assert sources.resolve_localized({}, "fb", "zh-CN") == "fb"


def test_normalize_extras_accepts_common_forms(sources):
    # 字符串列表 → 无 label 行
    assert sources.normalize_extras(["选择性必修上"]) == [("", "选择性必修上")]
    # (label, text) 列表
    assert sources.normalize_extras([("教材", "必修上")]) == [("教材", "必修上")]
    # dict 按插入序
    assert sources.normalize_extras({"教材": "必修上", "版本": "人教"}) == [("教材", "必修上"), ("版本", "人教")]
    # dict 条目列表
    assert sources.normalize_extras([{"label": "教材", "text": "必修上"}]) == [("教材", "必修上")]


def test_normalize_extras_tolerates_garbage(sources):
    assert sources.normalize_extras(None) == []
    assert sources.normalize_extras([]) == []
    assert sources.normalize_extras("字符串") == []
    # 空文本项被丢弃，label 缺省为空
    assert sources.normalize_extras(["  ", ("教材", ""), ("", "保留")]) == [("", "保留")]


def test_concurrent_register_and_fetch(sources):
    """多线程同时注册不同来源，注册表保持一致。"""

    def worker(n: int) -> None:
        sources.register_external_source(
            f"src_{n}",
            lambda options, props: (f"t{n}", ""),
            owner_plugin_id="bench",
        )

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    ids = {e.source_id for e in sources.all_external_sources()}
    assert ids == {f"src_{i}" for i in range(8)}

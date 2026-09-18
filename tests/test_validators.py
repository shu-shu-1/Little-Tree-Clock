"""app.utils.validators 单元测试"""

from __future__ import annotations

import enum

from app.utils.validators import (
    CallbackList,
    Singleton,
    clamp_float,
    clamp_int,
    lazy_property,
    safe_call,
    safe_cast,
    safe_get,
    safe_json_loads,
    validate_enum,
    validate_path,
    validate_range,
)


class Color(enum.Enum):
    RED = "red"
    GREEN = "green"


class TestClamp:
    def test_clamp_int_within_range(self):
        assert clamp_int(5, 0, 10, 0) == 5

    def test_clamp_int_below_min(self):
        assert clamp_int(-5, 0, 10, 7) == 0

    def test_clamp_int_above_max(self):
        assert clamp_int(99, 0, 10, 7) == 10

    def test_clamp_int_coerces_numeric_string(self):
        assert clamp_int("5", 0, 10, 0) == 5

    def test_clamp_int_invalid_returns_default(self):
        assert clamp_int("abc", 0, 10, 3) == 3
        assert clamp_int(None, 0, 10, 3) == 3

    def test_clamp_float(self):
        assert clamp_float(0.5, 0.0, 1.0, 0.0) == 0.5
        assert clamp_float(2.0, 0.0, 1.0, 0.0) == 1.0
        assert clamp_float("bad", 0.0, 1.0, 0.7) == 0.7


class TestValidateEnum:
    def test_valid_value(self):
        assert validate_enum("red", Color, Color.GREEN) == Color.RED

    def test_enum_member_passthrough(self):
        assert validate_enum(Color.GREEN, Color, Color.RED) == Color.GREEN

    def test_invalid_returns_default(self):
        assert validate_enum("blue", Color, Color.GREEN) == Color.GREEN

    def test_none_returns_default(self):
        assert validate_enum(None, Color, Color.RED) == Color.RED


class TestSafeGet:
    def test_nested_value(self):
        data = {"a": {"b": {"c": 1}}}
        assert safe_get(data, "a", "b", "c") == 1

    def test_missing_key_returns_default(self):
        data = {"a": {"b": {"c": 1}}}
        assert safe_get(data, "a", "z", default="fallback") == "fallback"

    def test_none_in_path_returns_default(self):
        data = {"x": None}
        assert safe_get(data, "x", "y", default="d") == "d"

    def test_no_keys_returns_dict(self):
        data = {"a": 1}
        assert safe_get(data) == {"a": 1}

    def test_traverse_through_non_dict(self):
        assert safe_get({"a": 1}, "a", "b", default="d") == "d"


class TestSafeJsonLoads:
    def test_valid_json(self):
        assert safe_json_loads('{"a": 1}') == {"a": 1}

    def test_invalid_json_returns_default(self):
        assert safe_json_loads("{bad", default=[]) == []

    def test_none_default(self):
        assert safe_json_loads("not json") is None


class TestSafeCall:
    def test_returns_result(self):
        assert safe_call(lambda a, b: a + b, 1, 2) == 3

    def test_exception_returns_default(self):
        def boom():
            raise ValueError()

        assert safe_call(boom, default="safe") == "safe"


class TestSafeCast:
    def test_cast_success(self):
        assert safe_cast("42", int, 0) == 42
        assert safe_cast(3.9, int, 0) == 3

    def test_cast_failure_returns_default(self):
        assert safe_cast("abc", int, -1) == -1
        assert safe_cast(None, int, 0) == 0  # int(None) 抛 TypeError → 默认值


class TestValidatePath:
    def test_normalizes_path(self, tmp_path):
        result = validate_path(str(tmp_path / "file.txt"))
        assert result == str(tmp_path / "file.txt")

    def test_none_returns_none(self):
        assert validate_path(None) is None

    def test_strips_quotes(self):
        result = validate_path('"C:\\some\\path"')
        assert result == "C:\\some\\path"

    def test_must_exist(self, tmp_path):
        assert validate_path(str(tmp_path), must_exist=True) == str(tmp_path)
        missing = tmp_path / "nope.txt"
        assert validate_path(str(missing), must_exist=True) is None


class TestValidateRange:
    def test_valid_value(self):
        assert validate_range("a", {"a", "b"}, "c") == "a"

    def test_invalid_returns_default(self):
        assert validate_range("z", {"a", "b"}, "c") == "c"


class TestLazyProperty:
    def test_computed_once(self):
        calls = []

        class Obj:
            @lazy_property
            def value(self):
                calls.append(1)
                return 42

        obj = Obj()
        assert obj.value == 42
        assert obj.value == 42
        assert len(calls) == 1

    def test_instances_independent(self):
        class Obj:
            @lazy_property
            def value(self):
                return object()

        a, b = Obj(), Obj()
        assert a.value is not b.value


class TestSingleton:
    def test_same_instance(self):
        class Service(Singleton):
            pass

        a, b = Service(), Service()
        assert a is b

    def test_reset(self):
        class Service(Singleton):
            pass

        a = Service()
        Service.reset()
        b = Service()
        assert a is not b

    def teardown_method(self):
        Singleton.reset()


class TestCallbackList:
    def test_add_and_emit(self):
        cb = CallbackList()
        results = []
        cb.add(lambda x: results.append(x))
        cb.emit("hello")
        assert results == ["hello"]

    def test_no_duplicates(self):
        cb = CallbackList()
        fn = lambda: None
        cb.add(fn)
        cb.add(fn)
        assert len(cb) == 1

    def test_remove(self):
        cb = CallbackList()
        fn = lambda: None
        cb.add(fn)
        cb.remove(fn)
        assert len(cb) == 0

    def test_emit_returns_results(self):
        cb = CallbackList()
        cb.add(lambda: 1)
        cb.add(lambda: 2)
        assert cb.emit() == [1, 2]

    def test_emit_swallows_exceptions(self):
        cb = CallbackList()

        def boom():
            raise RuntimeError()

        cb.add(boom)
        cb.add(lambda: "ok")
        assert cb.emit() == ["ok"]

    def test_clear_and_bool(self):
        cb = CallbackList()
        assert not cb
        cb.add(lambda: None)
        assert cb
        cb.clear()
        assert len(cb) == 0

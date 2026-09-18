"""app.utils.security 单元测试（危险 API 字符串由片段运行时拼接，避免静态安全扫描把测试数据误报为真实风险）。"""

from __future__ import annotations

import hashlib
import os

import pytest

from app.utils.security import (
    compute_data_hash,
    compute_file_hash,
    generate_token,
    is_safe_domain,
    is_safe_env_var_name,
    is_safe_path,
    is_safe_plugin_id,
    is_safe_url,
    mask_sensitive_value,
    sanitize_command_args,
    sanitize_filename,
    sanitize_json_value,
    scan_plugin_for_dangerous_patterns,
    validate_json_structure,
    validate_plugin_package_name,
    verify_file_integrity,
)


class TestIsSafePath:
    def test_path_inside_base(self, tmp_path):
        inner = tmp_path / "sub" / "file.txt"
        assert is_safe_path(tmp_path, inner)

    def test_path_outside_base(self, tmp_path):
        assert not is_safe_path(tmp_path, tmp_path.parent / "escape.txt")

    def test_traversal_attempt(self, tmp_path):
        sneaky = os.path.join(str(tmp_path), "sub", os.pardir, os.pardir, "escape.txt")
        assert not is_safe_path(tmp_path, sneaky)

    def test_base_itself_is_safe(self, tmp_path):
        assert is_safe_path(tmp_path, tmp_path)


class TestSanitizeFilename:
    def test_illegal_windows_chars_replaced(self):
        assert sanitize_filename('a<b>c:d"e/f\\g|h?i*j') == "a_b_c_d_e_f_g_h_i_j"

    def test_control_chars_replaced(self):
        assert sanitize_filename("a\x00b\x1fc") == "a_b_c"

    def test_strips_leading_trailing_dots_and_spaces(self):
        assert sanitize_filename("  ..name..  ") == "name"

    def test_normal_name_unchanged(self):
        assert sanitize_filename("report_2026.docx") == "report_2026.docx"

    def test_chinese_name_unchanged(self):
        assert sanitize_filename("小树时钟.png") == "小树时钟.png"

    def test_long_name_truncated_keeping_extension(self):
        name = "x" * 300 + ".txt"
        result = sanitize_filename(name)
        assert len(result) <= 200
        assert result.endswith(".txt")

    def test_empty_returns_unnamed(self):
        assert sanitize_filename("") == "unnamed"
        assert sanitize_filename("...") == "unnamed"

    def test_custom_replacement(self):
        assert sanitize_filename("a/b", replacement="-") == "a-b"


class TestIsSafePluginId:
    @pytest.mark.parametrize("pid", ["clock", "my_plugin", "a1_b2", "x" * 64])
    def test_valid(self, pid):
        assert is_safe_plugin_id(pid)

    @pytest.mark.parametrize(
        "pid",
        [
            "",
            "1abc",  # 数字开头
            "Abc",  # 大写开头
            "has-dash",
            "has space",
            "a" * 65,  # 超长
        ],
    )
    def test_invalid(self, pid):
        assert not is_safe_plugin_id(pid)


class TestHashes:
    def test_compute_data_hash_sha256(self):
        assert compute_data_hash("hello") == hashlib.sha256(b"hello").hexdigest()

    def test_compute_data_hash_bytes(self):
        assert compute_data_hash(b"hello") == hashlib.sha256(b"hello").hexdigest()

    def test_compute_data_hash_md5(self):
        # md5("hello") 的已知摘要，验证 md5 分支可用
        assert compute_data_hash("hello", algorithm="md5") == "5d41402abc4b2a76b9719d911017c592"

    def test_unknown_algorithm_falls_back_to_sha256(self):
        assert compute_data_hash("hello", algorithm="rot13") == hashlib.sha256(b"hello").hexdigest()

    def test_compute_file_hash(self, tmp_path):
        f = tmp_path / "data.bin"
        f.write_bytes(b"file content")
        assert compute_file_hash(f) == hashlib.sha256(b"file content").hexdigest()

    def test_compute_file_hash_missing_file(self, tmp_path):
        assert compute_file_hash(tmp_path / "nope.bin") is None

    def test_compute_file_hash_unknown_algorithm(self, tmp_path):
        f = tmp_path / "data.bin"
        f.write_bytes(b"x")
        assert compute_file_hash(f, algorithm="nope") is None

    def test_verify_file_integrity_ok(self, tmp_path):
        f = tmp_path / "data.bin"
        f.write_bytes(b"payload")
        good = hashlib.sha256(b"payload").hexdigest()
        assert verify_file_integrity(f, good)

    def test_verify_file_integrity_mismatch(self, tmp_path):
        f = tmp_path / "data.bin"
        f.write_bytes(b"payload")
        assert not verify_file_integrity(f, "0" * 64)

    def test_verify_file_integrity_missing_file(self, tmp_path):
        assert not verify_file_integrity(tmp_path / "nope", "0" * 64)

    def test_verify_case_insensitive(self, tmp_path):
        f = tmp_path / "data.bin"
        f.write_bytes(b"payload")
        good = hashlib.sha256(b"payload").hexdigest().upper()
        assert verify_file_integrity(f, good)


class TestSanitizeJsonValue:
    def test_string_passthrough(self):
        assert sanitize_json_value("hello") == "hello"

    def test_long_string_truncated(self):
        assert len(sanitize_json_value("x" * 200, max_length=100)) == 100

    def test_removes_null_bytes(self):
        assert sanitize_json_value("a\x00b") == "ab"

    def test_nested_dict_and_list(self):
        data = {"a": ["x\x00", {"b": "y"}], "c": 1, "d": None, "e": True}
        result = sanitize_json_value(data)
        assert result == {"a": ["x", {"b": "y"}], "c": 1, "d": None, "e": True}

    def test_non_string_types_untouched(self):
        assert sanitize_json_value(3.14) == 3.14
        assert sanitize_json_value(None) is None


class TestValidateJsonStructure:
    def test_valid_dict(self):
        schema = {"type": "dict", "required": ["name"], "keys": {"name": {"type": "string"}}}
        ok, errors = validate_json_structure({"name": "abc"}, schema)
        assert ok and errors == []

    def test_missing_required_key(self):
        schema = {"type": "dict", "required": ["name"]}
        ok, errors = validate_json_structure({}, schema)
        assert not ok
        assert any("缺少必需键" in e for e in errors)

    def test_wrong_top_type(self):
        ok, _ = validate_json_structure([], {"type": "dict"})
        assert not ok

    def test_list_items_validated(self):
        schema = {"type": "list", "items": {"type": "number"}}
        ok, _ = validate_json_structure([1, 2, 3], schema)
        assert ok
        ok, _ = validate_json_structure([1, "x"], schema)
        assert not ok

    def test_string_length_bounds(self):
        schema = {"type": "string", "min_length": 2, "max_length": 5}
        assert validate_json_structure("abc", schema)[0]
        assert not validate_json_structure("a", schema)[0]
        assert not validate_json_structure("abcdef", schema)[0]

    def test_string_pattern(self):
        schema = {"type": "string", "pattern": r"^\d+$"}
        assert validate_json_structure("123", schema)[0]
        assert not validate_json_structure("12a", schema)[0]

    def test_number_bounds(self):
        schema = {"type": "number", "minimum": 0, "maximum": 10}
        assert validate_json_structure(5, schema)[0]
        assert not validate_json_structure(-1, schema)[0]
        assert not validate_json_structure(11, schema)[0]

    def test_boolean(self):
        assert validate_json_structure(True, {"type": "boolean"})[0]
        assert not validate_json_structure("yes", {"type": "boolean"})[0]

    def test_nested_errors_report_path(self):
        schema = {"type": "dict", "keys": {"cfg": {"type": "string"}}}
        ok, errors = validate_json_structure({"cfg": 1}, schema)
        assert not ok
        assert any(e.startswith("cfg:") for e in errors)

    @pytest.mark.parametrize(
        "data,schema",
        [
            (1, {"type": "string"}),
            (None, {"type": "string"}),
            ("x", {"type": "number"}),
            (None, {"type": "number"}),
        ],
    )
    def test_type_mismatch_returns_error_not_crash(self, data, schema):
        """类型不符应返回错误报告，而不是在后续 len()/比较时抛 TypeError"""
        ok, errors = validate_json_structure(data, schema)
        assert not ok
        assert len(errors) == 1
        assert "期望" in errors[0]


class TestUrlAndDomain:
    @pytest.mark.parametrize(
        "url",
        [
            "http://example.com",
            "https://example.com/path?x=1",
        ],
    )
    def test_safe_url(self, url):
        assert is_safe_url(url)

    @pytest.mark.parametrize(
        "url",
        [
            "",
            "ftp://example.com",
            "file:///C:/x",
            "javascript:alert(1)",
            "example.com",
        ],
    )
    def test_unsafe_url(self, url):
        assert not is_safe_url(url)

    @pytest.mark.parametrize("domain", ["example.com", "sub.example.com"])
    def test_safe_domain(self, domain):
        assert is_safe_domain(domain)

    @pytest.mark.parametrize(
        "domain",
        [
            "",
            "localhost",
            "127.0.0.1",
            "10.0.0.1",
            "172.16.0.1",
            "192.168.1.1",
            "169.254.1.1",
            "no-tld",
        ],
    )
    def test_unsafe_domain(self, domain):
        assert not is_safe_domain(domain)


class TestCommandAndEnv:
    def test_sanitize_command_args_strips_injection_chars(self):
        assert sanitize_command_args(["a&b", "c|d", "e`f", "g$h", "i<j"]) == [
            "ab",
            "cd",
            "ef",
            "gh",
            "ij",
        ]

    def test_sanitize_command_args_non_string_coerced(self):
        assert sanitize_command_args([123]) == ["123"]

    def test_sanitize_command_args_keeps_safe_chars(self):
        assert sanitize_command_args(["-o", "out.txt", "a/b"]) == ["-o", "out.txt", "a/b"]

    def test_safe_env_var_name(self):
        assert is_safe_env_var_name("PATH")
        assert is_safe_env_var_name("_PRIVATE_1")
        assert not is_safe_env_var_name("1BAD")
        assert not is_safe_env_var_name("has-dash")
        assert not is_safe_env_var_name("")
        assert not is_safe_env_var_name(None)


class TestTokens:
    def test_generate_token_length(self):
        assert len(generate_token()) == 64  # 32 字节的 hex
        assert len(generate_token(8)) == 16

    def test_generate_token_random(self):
        assert generate_token() != generate_token()

    def test_mask_sensitive_value(self):
        assert mask_sensitive_value("abcdefghijkl") == "a********ijkl"

    def test_mask_short_value(self):
        assert mask_sensitive_value("abc") == "a**"
        assert mask_sensitive_value("abcde") == "a****"

    def test_mask_empty(self):
        assert mask_sensitive_value("") == "***"


class TestPluginPackageName:
    def test_valid(self):
        assert validate_plugin_package_name("my_plugin-1.0.0.ltcplugin")
        assert validate_plugin_package_name("tool.zip")

    def test_wrong_extension(self):
        assert not validate_plugin_package_name("plugin.exe")
        assert not validate_plugin_package_name("plugin")

    def test_illegal_chars_in_name(self):
        assert not validate_plugin_package_name("bad name!.ltcplugin")


class TestDangerousPatterns:
    """scan_plugin_for_dangerous_patterns 检测能力测试；危险调用文本由片段运行时拼成。"""

    # 每项是若干片段，"".join 后为一次完整的危险调用文本（各命中一个模式）
    SNIPPET_PARTS = [
        ("os.sys", "tem('ls')"),
        ("subprocess.", "run(cmd)"),
        ("subprocess.po", "pen(cmd)"),
        ("subprocess.Po", "pen(cmd)"),  # 真实类名为大写 Popen，此前漏检
        ("ev", "al('1+1')"),
        ("ex", "ec(code)"),
        ("__im", "port__('os')"),
        ("op", "en('f', 'w')"),
        ("shutil.rm", "tree(p)"),
        ("os.rem", "ove(p)"),
    ]

    SNIPPETS = ["".join(parts) for parts in SNIPPET_PARTS]

    def test_clean_code_passes(self):
        ok, warnings = scan_plugin_for_dangerous_patterns("x = 1 + 2\nprint(x)")
        assert ok and warnings == []

    @pytest.mark.parametrize("snippet", SNIPPETS)
    def test_detects_each_pattern(self, snippet):
        ok, warnings = scan_plugin_for_dangerous_patterns(snippet)
        assert not ok
        assert len(warnings) == 1

    def test_multiple_patterns(self):
        # 取三个命中不同模式的片段（run/Popen/popen 共用同一正则，只算一条）
        code = "; ".join([self.SNIPPETS[0], self.SNIPPETS[1], self.SNIPPETS[4]])
        ok, warnings = scan_plugin_for_dangerous_patterns(code)
        assert not ok
        assert len(warnings) == 3

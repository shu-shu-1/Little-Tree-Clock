"""app.utils.string_utils 单元测试"""

from __future__ import annotations

import pytest

from app.utils.string_utils import (
    camel_to_snake,
    coalesce,
    contains_chinese,
    count_chinese_chars,
    count_words,
    extract_numbers,
    highlight_keywords,
    indent_text,
    is_ascii,
    is_blank,
    levenshtein_distance,
    normalize_whitespace,
    remove_accents,
    similarity,
    slugify,
    snake_to_camel,
    strip_html,
    truncate,
    word_wrap,
)


class TestTruncate:
    def test_short_text_unchanged(self):
        assert truncate("hello", 10) == "hello"

    def test_exact_length_unchanged(self):
        assert truncate("hello", 5) == "hello"

    def test_long_text_truncated_with_suffix(self):
        assert truncate("hello world", 8) == "hello..."

    def test_custom_suffix(self):
        # 截取 7-1=6 个字符（"hello "含尾随空格）再拼后缀
        assert truncate("hello world", 7, suffix="…") == "hello …"

    def test_empty_text(self):
        assert truncate("", 5) == ""


class TestRemoveAccents:
    def test_removes_accents(self):
        assert remove_accents("café") == "cafe"
        assert remove_accents("naïve") == "naive"

    def test_plain_text_unchanged(self):
        assert remove_accents("hello") == "hello"

    def test_chinese_unchanged(self):
        assert remove_accents("中文") == "中文"


class TestSlugify:
    def test_basic(self):
        assert slugify("Hello World") == "hello-world"

    def test_multiple_spaces_collapse(self):
        assert slugify("Hello   World") == "hello-world"

    def test_removes_special_chars(self):
        assert slugify("Hello, World!") == "hello-world"

    def test_custom_separator(self):
        assert slugify("Hello World", separator="_") == "hello_world"

    def test_max_length(self):
        assert len(slugify("Hello World", max_length=5)) == 5

    def test_strips_separators(self):
        assert slugify("  Hello  ") == "hello"


class TestNameConversions:
    @pytest.mark.parametrize(
        "camel,snake",
        [
            ("helloWorld", "hello_world"),
            ("HTTPResponse", "http_response"),
            ("parseJSONData", "parse_json_data"),
            ("simple", "simple"),
        ],
    )
    def test_camel_to_snake(self, camel, snake):
        assert camel_to_snake(camel) == snake

    def test_snake_to_camel(self):
        assert snake_to_camel("hello_world") == "helloWorld"
        # 默认将首组件转小写
        assert snake_to_camel("Hello_world") == "helloWorld"

    def test_snake_to_camel_capitalize_first(self):
        # capitalize_first 保持首组件原样
        assert snake_to_camel("hello_world", capitalize_first=True) == "helloWorld"
        assert snake_to_camel("Hello_world", capitalize_first=True) == "HelloWorld"


class TestBlankAndCoalesce:
    def test_is_blank(self):
        assert is_blank("")
        assert is_blank("   ")
        assert is_blank(None)
        assert not is_blank("x")

    def test_coalesce(self):
        assert coalesce(None, "", "  ", "first", "second") == "first"
        assert coalesce(None, "", "") is None


class TestIndentAndWrap:
    def test_indent_text(self):
        assert indent_text("a\nb", indent=2) == "  a\n  b"

    def test_indent_custom_char(self):
        assert indent_text("a", indent=1, indent_char="\t") == "\ta"

    def test_word_wrap(self):
        text = "one two three four five"
        wrapped = word_wrap(text, width=9)
        assert wrapped == "one two\nthree\nfour five"


class TestStripHtml:
    def test_removes_tags(self):
        assert strip_html("<p>hello</p>") == "hello"

    def test_removes_comments(self):
        assert strip_html("a<!-- c -->b") == "ab"

    def test_decodes_entities(self):
        assert strip_html("a &amp; b") == "a & b"
        assert strip_html("&lt;tag&gt;") == "<tag>"
        assert strip_html("&nbsp;") == " "


class TestNumbers:
    def test_extract_numbers(self):
        assert extract_numbers("a1 b2.5 c-3") == [1.0, 2.5, -3.0]

    def test_extract_numbers_empty(self):
        assert extract_numbers("no numbers") == []

    def test_count_words(self):
        assert count_words("hello world foo") == 3

    def test_count_chinese_chars(self):
        assert count_chinese_chars("你好world世界") == 4


class TestHighlight:
    def test_highlight_keywords(self):
        assert highlight_keywords("hello world", ["world"]) == "hello **world**"

    def test_case_insensitive(self):
        assert highlight_keywords("Hello", ["hello"]) == "**hello**"

    def test_custom_markers(self):
        assert highlight_keywords("abc", ["abc"], prefix="[", suffix="]") == "[abc]"

    def test_empty_keyword_ignored(self):
        assert highlight_keywords("abc", [""]) == "abc"


class TestLevenshtein:
    @pytest.mark.parametrize(
        "s1,s2,dist",
        [
            ("", "", 0),
            ("abc", "", 3),
            ("", "abc", 3),
            ("kitten", "sitting", 3),
            ("abc", "abc", 0),
            ("abc", "abd", 1),
            ("flaw", "lawn", 2),
        ],
    )
    def test_distance(self, s1, s2, dist):
        assert levenshtein_distance(s1, s2) == dist

    def test_similarity_identical(self):
        assert similarity("abc", "abc") == 1.0

    def test_similarity_empty(self):
        assert similarity("", "abc") == 0.0

    def test_similarity_range(self):
        s = similarity("kitten", "sitting")
        assert 0.0 <= s <= 1.0


class TestMisc:
    def test_normalize_whitespace(self):
        assert normalize_whitespace("  a\t b\n\nc  ") == "a b c"

    def test_is_ascii(self):
        assert is_ascii("abc123")
        assert not is_ascii("中文")

    def test_contains_chinese(self):
        assert contains_chinese("abc中文")
        assert not contains_chinese("abc")

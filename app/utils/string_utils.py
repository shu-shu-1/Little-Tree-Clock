"""字符串和文本处理工具"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional


def truncate(text: str, max_length: int, suffix: str = "...") -> str:
    """截断字符串到指定长度，添加后缀

    Args:
        text: 原始文本
        max_length: 最大长度
        suffix: 截断后缀

    Returns:
        截断后的文本
    """
    if len(text) <= max_length:
        return text
    return text[:max_length - len(suffix)] + suffix


def remove_accents(text: str) -> str:
    """移除字符串中的重音符号

    Args:
        text: 原始文本

    Returns:
        移除重音后的文本
    """
    nfd = unicodedata.normalize('NFD', text)
    return ''.join(c for c in nfd if unicodedata.category(c) != 'Mn')


def slugify(text: str, max_length: Optional[int] = None, separator: str = "-") -> str:
    """将文本转换为 URL 安全的 slug

    Args:
        text: 原始文本
        max_length: 最大长度限制
        separator: 分隔符

    Returns:
        slug 格式的字符串
    """
    # 转换为小写并移除重音
    text = remove_accents(text.lower())

    # 替换非字母数字为分隔符
    text = re.sub(r'[^\w\s-]', '', text)

    # 替换空白字符为单个分隔符
    text = re.sub(r'[-\s]+', separator, text)

    # 移除首尾分隔符
    text = text.strip(separator)

    if max_length:
        text = truncate(text, max_length, "")

    return text


def camel_to_snake(text: str) -> str:
    """将驼峰命名转换为蛇形命名

    Args:
        text: 驼峰格式字符串

    Returns:
        蛇形格式字符串
    """
    # 处理连续大写字母的情况（如 HTTPResponse -> http_response）
    text = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1_\2', text)
    text = re.sub(r'([a-z\d])([A-Z])', r'\1_\2', text)
    return text.lower()


def snake_to_camel(text: str, capitalize_first: bool = False) -> str:
    """将蛇形命名转换为驼峰命名

    Args:
        text: 蛇形格式字符串
        capitalize_first: 是否大写首字母

    Returns:
        驼峰格式字符串
    """
    components = text.split('_')
    if capitalize_first:
        return components[0] + ''.join(x.title() for x in components[1:])
    return components[0].lower() + ''.join(x.title() for x in components[1:])


def is_blank(text: Optional[str]) -> bool:
    """检查字符串是否为空或仅包含空白字符"""
    return not text or not text.strip()


def coalesce(*values: Optional[str]) -> Optional[str]:
    """返回第一个非空字符串"""
    for value in values:
        if value and value.strip():
            return value
    return None


def indent_text(text: str, indent: int = 4, indent_char: str = " ") -> str:
    """为文本添加缩进

    Args:
        text: 原始文本
        indent: 缩进空格数
        indent_char: 缩进字符

    Returns:
        添加缩进后的文本
    """
    padding = indent_char * indent
    return "\n".join(padding + line for line in text.split("\n"))


def word_wrap(text: str, width: int = 80) -> str:
    """简单的单词换行处理

    Args:
        text: 原始文本
        width: 最大行宽度

    Returns:
        换行后的文本
    """
    lines = []
    current_line = []

    for word in text.split():
        if sum(len(w) for w in current_line) + len(current_line) + len(word) <= width:
            current_line.append(word)
        else:
            if current_line:
                lines.append(" ".join(current_line))
            current_line = [word]

    if current_line:
        lines.append(" ".join(current_line))

    return "\n".join(lines)


def strip_html(text: str) -> str:
    """移除 HTML 标签

    Args:
        text: 包含 HTML 的文本

    Returns:
        移除 HTML 后的纯文本
    """
    # 移除 HTML 注释
    text = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)
    # 移除 HTML 标签
    text = re.sub(r'<[^>]+>', '', text)
    # 解码 HTML 实体
    html_entities = {
        '&nbsp;': ' ',
        '&amp;': '&',
        '&lt;': '<',
        '&gt;': '>',
        '&quot;': '"',
        '&#39;': "'",
        '&apos;': "'",
    }
    for entity, char in html_entities.items():
        text = text.replace(entity, char)
    return text


def extract_numbers(text: str) -> list[float]:
    """从文本中提取所有数字

    Args:
        text: 原始文本

    Returns:
        数字列表
    """
    pattern = r'-?\d+\.?\d*'
    matches = re.findall(pattern, text)
    return [float(m) for m in matches if m]


def highlight_keywords(text: str, keywords: list[str], prefix: str = "**", suffix: str = "**") -> str:
    """在文本中高亮关键词

    Args:
        text: 原始文本
        keywords: 关键词列表
        prefix: 高亮前缀
        suffix: 高亮后缀

    Returns:
        高亮后的文本
    """
    for keyword in keywords:
        if keyword:
            pattern = re.compile(re.escape(keyword), re.IGNORECASE)
            text = pattern.sub(f"{prefix}{keyword}{suffix}", text)
    return text


def levenshtein_distance(s1: str, s2: str) -> int:
    """计算两个字符串之间的编辑距离（Levenshtein Distance）

    Args:
        s1: 第一个字符串
        s2: 第二个字符串

    Returns:
        编辑距离
    """
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)

    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]


def similarity(s1: str, s2: str) -> float:
    """计算两个字符串的相似度（0-1）

    Args:
        s1: 第一个字符串
        s2: 第二个字符串

    Returns:
        相似度（0-1 之间）
    """
    if not s1 or not s2:
        return 0.0

    max_len = max(len(s1), len(s2))
    if max_len == 0:
        return 1.0

    distance = levenshtein_distance(s1, s2)
    return 1.0 - (distance / max_len)


def normalize_whitespace(text: str) -> str:
    """规范化空白字符（将多个连续空白替换为单个空格）"""
    return re.sub(r'\s+', ' ', text).strip()


def is_ascii(text: str) -> bool:
    """检查字符串是否仅包含 ASCII 字符"""
    try:
        text.encode('ascii')
        return True
    except UnicodeEncodeError:
        return False


def contains_chinese(text: str) -> bool:
    """检查字符串是否包含中文字符"""
    return bool(re.search(r'[\u4e00-\u9fff]', text))


def count_words(text: str) -> int:
    """统计单词数量"""
    return len(re.findall(r'\w+', text))


def count_chinese_chars(text: str) -> int:
    """统计中文字符数量"""
    return len(re.findall(r'[\u4e00-\u9fff]', text))


__all__ = [
    "truncate",
    "remove_accents",
    "slugify",
    "camel_to_snake",
    "snake_to_camel",
    "is_blank",
    "coalesce",
    "indent_text",
    "word_wrap",
    "strip_html",
    "extract_numbers",
    "highlight_keywords",
    "levenshtein_distance",
    "similarity",
    "normalize_whitespace",
    "is_ascii",
    "contains_chinese",
    "count_words",
    "count_chinese_chars",
]

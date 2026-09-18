"""安全检查工具"""

from __future__ import annotations

import hashlib
import re
import secrets
from pathlib import Path
from typing import Any

from app.utils.logger import logger


def is_safe_path(base_dir: str | Path, target_path: str | Path) -> bool:
    """检查目标路径是否在基础目录内（防止路径穿越攻击）。"""
    try:
        base = Path(base_dir).resolve()
        target = Path(target_path).resolve()

        return str(target).startswith(str(base))
    except (OSError, ValueError):
        return False


def sanitize_filename(filename: str, replacement: str = "_") -> str:
    """清理文件名，移除不安全的字符。"""
    illegal_chars = r'<>:"/\|?*'
    for char in illegal_chars:
        filename = filename.replace(char, replacement)

    filename = re.sub(r"[\x00-\x1f\x7f]", replacement, filename)

    filename = filename.strip(". ")

    # 限制长度（Windows 最大 255）
    if len(filename) > 200:
        name, ext = Path(filename).stem, Path(filename).suffix
        max_name_len = 200 - len(ext)
        filename = name[:max_name_len] + ext

    return filename or "unnamed"


def is_safe_plugin_id(plugin_id: str) -> bool:
    """校验插件 ID：小写字母开头，仅含小写字母、数字、下划线，最长 64 字符。"""
    if not plugin_id:
        return False

    if len(plugin_id) > 64:
        return False

    pattern = r"^[a-z][a-z0-9_]*$"
    return bool(re.match(pattern, plugin_id))


def compute_file_hash(file_path: str | Path, algorithm: str = "sha256") -> str | None:
    """计算文件的哈希值，支持 md5/sha1/sha256/sha512，失败返回 None。"""
    hash_func = {
        "md5": hashlib.md5,
        "sha1": hashlib.sha1,
        "sha256": hashlib.sha256,
        "sha512": hashlib.sha512,
    }.get(algorithm.lower())

    if hash_func is None:
        logger.warning(f"[安全] 不支持的哈希算法: {algorithm}")
        return None

    try:
        h = hash_func()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError as e:
        logger.warning(f"[安全] 计算文件哈希失败: {e}")
        return None


def compute_data_hash(data: str | bytes, algorithm: str = "sha256") -> str:
    """计算数据的哈希值，未知算法回退 sha256。"""
    hash_func = {
        "md5": hashlib.md5,
        "sha1": hashlib.sha1,
        "sha256": hashlib.sha256,
        "sha512": hashlib.sha512,
    }.get(algorithm.lower(), hashlib.sha256)

    if isinstance(data, str):
        data = data.encode("utf-8")

    return hash_func(data).hexdigest()


def verify_file_integrity(file_path: str | Path, expected_hash: str, algorithm: str = "sha256") -> bool:
    """验证文件哈希是否与期望值一致。"""
    actual_hash = compute_file_hash(file_path, algorithm)
    if actual_hash is None:
        return False

    return secrets.compare_digest(actual_hash.lower(), expected_hash.lower())


def sanitize_json_value(value: Any, max_length: int = 10000) -> Any:
    """清理 JSON 值：截断超长字符串并移除 null 字节。"""
    if isinstance(value, str):
        if len(value) > max_length:
            value = value[:max_length]
        value = value.replace("\x00", "")
        return value

    if isinstance(value, dict):
        return {k: sanitize_json_value(v, max_length) for k, v in value.items()}

    if isinstance(value, list):
        return [sanitize_json_value(item, max_length) for item in value]

    return value


def validate_json_structure(data: Any, schema: dict) -> tuple[bool, list[str]]:
    """按 schema 验证 JSON 结构，支持 dict/list/string/number/boolean。"""
    errors = []
    expected_type = schema.get("type")

    if expected_type == "dict":
        if not isinstance(data, dict):
            return False, ["期望字典类型"]

        required = schema.get("required", [])
        for key in required:
            if key not in data:
                errors.append(f"缺少必需键: {key}")

        key_schemas = schema.get("keys", {})
        for key, value in data.items():
            if key in key_schemas:
                key_valid, key_errors = validate_json_structure(value, key_schemas[key])
                if not key_valid:
                    errors.extend([f"{key}: {e}" for e in key_errors])

    elif expected_type == "list":
        if not isinstance(data, list):
            return False, ["期望列表类型"]

        item_schema = schema.get("items")
        if item_schema:
            for i, item in enumerate(data):
                item_valid, item_errors = validate_json_structure(item, item_schema)
                if not item_valid:
                    errors.extend([f"[{i}]: {e}" for e in item_errors])

    elif expected_type == "string":
        if not isinstance(data, str):
            return False, ["期望字符串类型"]

        min_length = schema.get("min_length", 0)
        max_length = schema.get("max_length", 0)
        pattern = schema.get("pattern")

        if len(data) < min_length:
            errors.append(f"字符串长度小于最小值 {min_length}")
        if max_length and len(data) > max_length:
            errors.append(f"字符串长度超过最大值 {max_length}")
        if pattern and not re.match(pattern, data):
            errors.append(f"字符串不符合格式要求: {pattern}")

    elif expected_type == "number":
        if not isinstance(data, (int, float)):
            return False, ["期望数字类型"]

        minimum = schema.get("minimum")
        maximum = schema.get("maximum")

        if minimum is not None and data < minimum:
            errors.append(f"数值小于最小值 {minimum}")
        if maximum is not None and data > maximum:
            errors.append(f"数值超过最大值 {maximum}")

    elif expected_type == "boolean":
        if not isinstance(data, bool):
            # 允许 0/1 作为布尔值
            if data not in (0, 1, "true", "false", "True", "False"):
                errors.append("期望布尔类型")

    return len(errors) == 0, errors


def is_safe_url(url: str) -> bool:
    """检查 URL 是否安全（只允许 http/https）。"""
    if not url:
        return False

    try:
        from urllib.parse import urlparse

        result = urlparse(url)
        return result.scheme in ("http", "https")
    except Exception:
        return False


def is_safe_domain(domain: str) -> bool:
    """检查域名是否安全，排除 localhost、私有 IP 与内网地址。"""
    if not domain:
        return False

    domain = domain.lower().strip()

    if domain in ("localhost", "127.0.0.1", "::1"):
        return False

    private_patterns = [
        r"^10\.",
        r"^172\.(1[6-9]|2[0-9]|3[0-1])\.",
        r"^192\.168\.",
        r"^169\.254\.",
        r"^fc00:",
        r"^fe80:",
    ]
    for pattern in private_patterns:
        if re.match(pattern, domain):
            return False

    if not re.match(r"^[a-z0-9][a-z0-9.-]*\.[a-z]+$", domain):
        return False

    return True


def sanitize_command_args(args: list) -> list:
    """清理命令行参数，移除 shell 元字符。"""
    sanitized = []
    for arg in args:
        if not isinstance(arg, str):
            arg = str(arg)

        sanitized_arg = re.sub(r"[<>&|`$\\]", "", arg)
        sanitized.append(sanitized_arg)

    return sanitized


def is_safe_env_var_name(name: str) -> bool:
    """检查环境变量名是否安全。"""
    if not name:
        return False

    return bool(re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name))


def generate_token(length: int = 32) -> str:
    """生成安全的随机令牌（十六进制编码）。"""
    return secrets.token_hex(length)


def mask_sensitive_value(value: str, visible_chars: int = 4) -> str:
    """遮蔽敏感值，仅保留首字符与末尾若干字符。"""
    if not value:
        return "***"

    if len(value) <= visible_chars * 2:
        return value[0] + "*" * (len(value) - 1)

    masked_length = len(value) - visible_chars
    return value[:1] + "*" * masked_length + value[-visible_chars:]


def validate_plugin_package_name(filename: str) -> bool:
    """验证插件包文件名是否合法。"""
    allowed_extensions = {".ltcplugin", ".zip"}

    try:
        path = Path(filename)
        ext = path.suffix.lower()

        if ext not in allowed_extensions:
            return False

        name = path.stem
        if not re.match(r"^[a-zA-Z0-9_.-]+$", name):
            return False

        return True
    except (ValueError, OSError):
        return False


def scan_plugin_for_dangerous_patterns(source_code: str) -> tuple[bool, list[str]]:
    """扫描插件代码中的危险模式。"""
    warnings = []
    dangerous_patterns = [
        (r"os\.system\s*\(", "os.system() 调用可能存在安全风险"),
        # Popen 是 subprocess 真实类名，正则需同时覆盖大写形式
        (r"subprocess\s*\.\s*(call|run|popen|Popen|spawn)", "subprocess 调用可能存在安全风险"),
        (r"eval\s*\(", "eval() 可能执行任意代码"),
        (r"exec\s*\(", "exec() 可能执行任意代码"),
        (r"__import__\s*\(", "动态导入可能存在安全风险"),
        (r"compile\s*\(", "动态编译可能存在安全风险"),
        (r"open\s*\([^)]*['\"]w['\"]", "写入文件操作"),
        (r"shutil\.rmtree\s*\(", "删除目录操作"),
        (r"os\.remove\s*\(", "删除文件操作"),
    ]

    for pattern, description in dangerous_patterns:
        if re.search(pattern, source_code):
            warnings.append(description)

    return len(warnings) == 0, warnings


__all__ = [
    "is_safe_path",
    "sanitize_filename",
    "is_safe_plugin_id",
    "compute_file_hash",
    "compute_data_hash",
    "verify_file_integrity",
    "sanitize_json_value",
    "validate_json_structure",
    "is_safe_url",
    "is_safe_domain",
    "sanitize_command_args",
    "is_safe_env_var_name",
    "generate_token",
    "mask_sensitive_value",
    "validate_plugin_package_name",
    "scan_plugin_for_dangerous_patterns",
]

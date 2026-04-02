"""配置 Schema 定义和验证工具"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Union

from app.utils.logger import logger


@dataclass
class FieldSchema:
    """单个字段的 Schema 定义"""
    name: str
    type: type | tuple[type, ...]
    required: bool = False
    default: Any = None
    validator: Optional[callable] = None
    description: str = ""


@dataclass
class Schema:
    """配置 Schema 验证器"""
    fields: list[FieldSchema] = field(default_factory=list)
    allow_extra: bool = True

    def validate(self, data: dict) -> tuple[bool, dict, list[str]]:
        """验证数据是否符合 Schema。

        Args:
            data: 要验证的字典数据

        Returns:
            (is_valid, validated_data, errors)
        """
        if not isinstance(data, dict):
            return False, {}, ["数据必须是字典类型"]

        result = {}
        errors = []

        # 验证必需字段
        for field_def in self.fields:
            if field_def.name not in data:
                if field_def.required:
                    errors.append(f"缺少必需字段: {field_def.name}")
                else:
                    result[field_def.name] = field_def.default
                continue

            value = data[field_def.name]

            # 类型检查
            expected_type = field_def.type
            if not isinstance(value, expected_type):
                # 尝试类型转换
                if expected_type == bool and isinstance(value, (int, str)):
                    result[field_def.name] = bool(value)
                elif expected_type == int and isinstance(value, (str, float)):
                    try:
                        result[field_def.name] = int(float(value))
                    except (ValueError, TypeError):
                        errors.append(f"字段 {field_def.name} 类型错误，期望 {expected_type}")
                        continue
                elif expected_type == str and value is not None:
                    result[field_def.name] = str(value)
                else:
                    errors.append(f"字段 {field_def.name} 类型错误，期望 {expected_type}")
                    continue
            else:
                result[field_def.name] = value

            # 自定义验证器
            if field_def.validator and field_def.name in result:
                try:
                    validated = field_def.validator(result[field_def.name])
                    if validated is not None:
                        result[field_def.name] = validated
                except Exception as e:
                    errors.append(f"字段 {field_def.name} 验证失败: {e}")

        # 处理额外字段
        if not self.allow_extra:
            extra_keys = set(data.keys()) - {f.name for f in self.fields}
            if extra_keys:
                for key in extra_keys:
                    result[key] = data[key]

        return len(errors) == 0, result, errors


# ─────────────────────────────────────────────────────────────────────────── #
# 预定义 Schema
# ─────────────────────────────────────────────────────────────────────────── #

def _validate_theme(value: Any) -> Any:
    if value in ("auto", "light", "dark"):
        return value
    return "auto"


def _validate_language(value: Any) -> Any:
    if value in ("zh-CN", "en-US"):
        return value
    return "zh-CN"


def _validate_position(value: Any) -> Any:
    valid_positions = {
        "top-left", "top-center", "top-right",
        "bottom-left", "bottom-center", "bottom-right",
        "center"
    }
    if value in valid_positions:
        return value
    return "bottom-right"


def _validate_opacity(value: Any) -> Any:
    if isinstance(value, (int, float)):
        return max(0, min(100, value))
    return 90


def _validate_positive_int(value: Any) -> Any:
    if isinstance(value, int) and value > 0:
        return value
    return None


# Settings Schema
SETTINGS_SCHEMA = Schema(fields=[
    FieldSchema("theme", str, default="auto", validator=_validate_theme),
    FieldSchema("language", str, default="zh-CN", validator=_validate_language),
    FieldSchema("float_opacity", (int, float), default=90, validator=_validate_opacity),
    FieldSchema("notification_position", str, default="bottom-right", validator=_validate_position),
    FieldSchema("notification_duration_ms", int, default=5000, validator=_validate_positive_int),
    FieldSchema("alarm_alert_duration_sec", int, default=60, validator=_validate_positive_int),
    FieldSchema("stopwatch_precision", int, default=1),
    FieldSchema("timer_precision", int, default=1),
    FieldSchema("time_offset_seconds", int, default=0),
    FieldSchema("widget_cell_size", int, default=120, validator=lambda v: max(60, min(300, v))),
    FieldSchema("pip_mirror", str, default=""),
    FieldSchema("notification_use_custom", bool, default=False),
    FieldSchema("ui_smooth_scroll_enabled", bool, default=True),
    FieldSchema("watermark_main_visible", bool, default=True),
    FieldSchema("watermark_worldtime_visible", bool, default=True),
    FieldSchema("show_boot_menu_next_start", bool, default=False),
    FieldSchema("first_use_completed", bool, default=False),
    FieldSchema("autostart_hide_to_tray", bool, default=True),
    FieldSchema("widget_canvas_overlap_group_enabled", bool, default=False),
    FieldSchema("widget_detached_overlap_merge_enabled", bool, default=False),
    FieldSchema("widget_auto_fill_gap_enabled", bool, default=True),
    FieldSchema("detached_widget_background_opacity", int, default=75, validator=_validate_opacity),
], allow_extra=True)


def load_config_with_schema(
    path: str,
    schema: Optional[Schema] = None,
    default: Optional[dict] = None,
    log_name: str = ""
) -> dict:
    """使用 Schema 验证加载配置文件。

    Args:
        path: 配置文件路径
        schema: Schema 验证器，None 时返回原始数据
        default: 解析失败时的默认值
        log_name: 日志中使用的配置名称

    Returns:
        验证后的配置字典
    """
    p = Path(path)
    if not p.exists():
        logger.warning(f"[配置] 文件不存在: {path}")
        return default if default is not None else {}

    try:
        raw_data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        logger.error(f"[配置] {log_name} JSON 解析失败: {e}")
        return default if default is not None else {}
    except OSError as e:
        logger.error(f"[配置] {log_name} 文件读取失败: {e}")
        return default if default is not None else {}

    if not isinstance(raw_data, dict):
        logger.warning(f"[配置] {log_name} 格式错误(非对象)")
        return default if default is not None else {}

    if schema is None:
        return raw_data

    is_valid, validated_data, errors = schema.validate(raw_data)

    if errors:
        logger.warning(f"[配置] {log_name} 验证警告: {errors}")

    if not is_valid:
        logger.error(f"[配置] {log_name} 验证失败: {errors}")
        # 合并已验证的字段和默认值
        result = {}
        for field_def in schema.fields:
            if field_def.name in validated_data:
                result[field_def.name] = validated_data[field_def.name]
            elif field_def.name in raw_data:
                result[field_def.name] = raw_data[field_def.name]
            else:
                result[field_def.name] = field_def.default
        return result

    return validated_data


__all__ = [
    "FieldSchema",
    "Schema",
    "SETTINGS_SCHEMA",
    "load_config_with_schema",
]

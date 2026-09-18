"""外部数据源注册表，供其他插件向「随机一言」组件提供自定义内容来源（不依赖 Qt）。"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from typing import Callable

# 与宿主插件 ID 规则一致：小写字母开头，仅小写字母/数字/下划线，最长 64
_VALID_SOURCE_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_VALID_OPTION_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

# 内置来源 ID，外部来源不得占用
BUILTIN_SOURCE_IDS: frozenset[str] = frozenset({"hitokoto", "zhaoyu", "custom_api", "local_file"})

# fetch 回调签名：(options, props) -> (text, source_info[, extras])
FetchCallable = Callable[[dict, dict], tuple]


def _canonical_language(value: object) -> str:
    """已知语言码归一化为规范形式，未知语言码按小写原样保留。"""
    # 懒加载 I18nService：本模块在无 UI 环境下也能独立使用
    from app.services.i18n_service import I18nService

    raw = str(value or "").strip()
    if not raw:
        return ""
    if I18nService.is_known_language(raw):
        return I18nService.normalize_language(raw)
    return raw.lower()


def _normalize_i18n_map(value: object) -> dict[str, str]:
    """归一化为 {规范语言码: 文本}，空白或非映射输入按空处理。"""
    if not isinstance(value, dict):
        return {}
    result: dict[str, str] = {}
    for lang, text in value.items():
        lang_key = _canonical_language(lang)
        text_value = str(text or "").strip()
        if lang_key and text_value:
            result[lang_key] = text_value
    return result


def resolve_localized(mapping: object, fallback: str, lang: str = "zh-CN") -> str:
    """按 当前语言 → zh-CN → 任意非空 → fallback 的顺序解析本地化文本。"""
    if isinstance(mapping, dict) and mapping:
        for target in (_canonical_language(lang), "zh-CN"):
            if not target:
                continue
            for key, value in mapping.items():
                if _canonical_language(key) == target:
                    hit = str(value or "").strip()
                    if hit:
                        return hit
        for value in mapping.values():
            hit = str(value or "").strip()
            if hit:
                return hit
    return fallback


@dataclass(frozen=True)
class SourceOption:
    """编辑面板中渲染的一个配置项。

    type 为 "choice" 时提供 choices（(value, label) 列表，value 为字符串）；
    type 为 "bool" 时值为布尔。
    """

    key: str
    label: str
    type: str = "choice"
    default: object = ""
    choices: tuple[tuple[str, str], ...] = ()
    label_i18n: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ExternalDataSource:
    source_id: str
    fetch: FetchCallable
    name: str
    name_i18n: dict[str, str] = field(default_factory=dict)
    owner_plugin_id: str = ""
    options: tuple[SourceOption, ...] = ()

    def display_name(self, lang: str = "zh-CN") -> str:
        return resolve_localized(self.name_i18n, self.name, lang)

    def option_label(self, option: SourceOption, lang: str = "zh-CN") -> str:
        return resolve_localized(option.label_i18n, option.label, lang)

    def default_options(self) -> dict:
        return {opt.key: opt.default for opt in self.options}


_REGISTRY: dict[str, ExternalDataSource] = {}
_LOCK = threading.RLock()


def _normalize_option(spec: object) -> SourceOption | None:
    """非法或无法识别的 option 声明返回 None。"""
    if isinstance(spec, SourceOption):
        return spec
    if not isinstance(spec, dict):
        return None

    key = str(spec.get("key", "")).strip()
    if not _VALID_OPTION_KEY_RE.match(key):
        return None

    label = str(spec.get("label", "")).strip() or key
    label_i18n = _normalize_i18n_map(spec.get("label_i18n"))
    opt_type = str(spec.get("type", "choice")).strip().lower()

    if opt_type == "bool":
        return SourceOption(
            key=key,
            label=label,
            type="bool",
            default=bool(spec.get("default", False)),
            label_i18n=label_i18n,
        )

    if opt_type == "choice":
        choices: list[tuple[str, str]] = []
        raw_choices = spec.get("choices")
        if not isinstance(raw_choices, (list, tuple)):
            return None
        for item in raw_choices:
            if isinstance(item, dict):
                value, text = item.get("value", ""), item.get("label", item.get("value", ""))
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                value, text = item[0], item[1]
            else:
                value, text = item, item
            value_str = str(value)
            # 允许空字符串值（常用于“全部/不过滤”占位项），仅按值去重
            if not any(v == value_str for v, _ in choices):
                choices.append((value_str, str(text)))
        if not choices:
            return None
        default = str(spec.get("default", "") or "")
        if not any(v == default for v, _ in choices):
            default = choices[0][0]
        return SourceOption(
            key=key,
            label=label,
            type="choice",
            default=default,
            choices=tuple(choices),
            label_i18n=label_i18n,
        )

    return None


def register_external_source(
    source_id: str,
    fetch: FetchCallable,
    *,
    name: str = "",
    name_i18n: object = None,
    owner_plugin_id: str = "",
    options: object = None,
) -> bool:
    """注册或由同提供方覆盖更新数据源；参数非法或来源 ID 被他人占用返回 False。"""
    sid = str(source_id or "").strip()
    if not _VALID_SOURCE_ID_RE.match(sid) or sid in BUILTIN_SOURCE_IDS:
        return False
    if not callable(fetch):
        return False

    display = str(name or "").strip() or sid
    i18n_map = _normalize_i18n_map(name_i18n)
    owner = str(owner_plugin_id or "").strip()

    raw_options = options if isinstance(options, (list, tuple)) else []
    normalized: list[SourceOption] = []
    seen_keys: set[str] = set()
    for spec in raw_options:
        opt = _normalize_option(spec)
        if opt is None or opt.key in seen_keys:
            continue
        seen_keys.add(opt.key)
        normalized.append(opt)

    with _LOCK:
        existing = _REGISTRY.get(sid)
        if existing is not None and existing.owner_plugin_id != owner:
            return False
        _REGISTRY[sid] = ExternalDataSource(
            source_id=sid,
            fetch=fetch,
            name=display,
            name_i18n=i18n_map,
            owner_plugin_id=owner,
            options=tuple(normalized),
        )
    return True


def unregister_external_source(source_id: str, *, owner_plugin_id: object = None) -> bool:
    """注销数据源；owner_plugin_id 非 None 时仅原提供方可以注销。"""
    sid = str(source_id or "").strip()
    owner = None if owner_plugin_id is None else str(owner_plugin_id).strip()
    with _LOCK:
        existing = _REGISTRY.get(sid)
        if existing is None:
            return False
        if owner is not None and existing.owner_plugin_id != owner:
            return False
        del _REGISTRY[sid]
    return True


def unregister_sources_of(owner_plugin_id: str) -> list[str]:
    owner = str(owner_plugin_id or "").strip()
    removed: list[str] = []
    with _LOCK:
        for sid in [s for s, src in _REGISTRY.items() if src.owner_plugin_id == owner]:
            del _REGISTRY[sid]
            removed.append(sid)
    return removed


def clear_external_sources() -> list[str]:
    with _LOCK:
        removed = list(_REGISTRY.keys())
        _REGISTRY.clear()
    return removed


def get_external_source(source_id: object) -> ExternalDataSource | None:
    sid = str(source_id or "").strip()
    with _LOCK:
        return _REGISTRY.get(sid)


def all_external_sources() -> list[ExternalDataSource]:
    with _LOCK:
        return list(_REGISTRY.values())


def normalize_extras(extras: object) -> list[tuple[str, str]]:
    """将 fetch 返回的第三项归一化为有序的 ``[(label, text), ...]``。

    兼容 None、字符串列表、二元组列表、条目 dict 及整体 dict，去空白、丢空项，不抛异常。
    """
    rows: list[tuple[str, str]] = []

    def _append(label: object, text: object) -> None:
        label_str = str(label or "").strip()
        text_str = str(text or "").strip()
        if text_str:
            rows.append((label_str, text_str))

    if extras is None:
        return rows
    if isinstance(extras, dict):
        for key, value in extras.items():
            _append(key, value)
        return rows
    if isinstance(extras, (list, tuple)):
        for item in extras:
            if isinstance(item, dict):
                _append(item.get("label", ""), item.get("text", item.get("value", "")))
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                _append(item[0], item[1])
            else:
                _append("", item)
    return rows


def read_ext_options(props: object, source_id: str) -> dict:
    """读取 props 中指定来源的选项值并合并注册声明的默认值，结构异常时按空处理。"""
    stored: dict = {}
    if isinstance(props, dict):
        raw_ext = props.get("ext_options")
        if isinstance(raw_ext, dict):
            raw_values = raw_ext.get(source_id)
            if isinstance(raw_values, dict):
                stored = dict(raw_values)

    source = get_external_source(source_id)
    if source is None:
        return stored

    merged = source.default_options()
    for key, value in stored.items():
        if key in merged:
            merged[key] = value
    return merged

"""应用国际化服务。"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Mapping

from PySide6.QtCore import QObject, Signal


LANG_ZH_CN = "zh-CN"
LANG_EN_US = "en-US"
SUPPORTED_LANGUAGES = (LANG_ZH_CN, LANG_EN_US)

_LANGUAGE_ALIASES: dict[str, str] = {
    "zh": LANG_ZH_CN,
    "zh-cn": LANG_ZH_CN,
    "zh-hans": LANG_ZH_CN,
    "en": LANG_EN_US,
    "en-us": LANG_EN_US,
}


def _get_translations_file() -> Path:
    """获取翻译文件路径，支持打包后的环境"""
    if getattr(sys, 'frozen', False):
        base_dir = Path(sys._MEIPASS).parent
    else:
        base_dir = Path(__file__).resolve().parents[2]
    return base_dir / "config" / "i18n.json"


_TRANSLATIONS_FILE = _get_translations_file()


def _load_translations() -> dict[str, dict[str, str]]:
    try:
        data = json.loads(_TRANSLATIONS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}

    if not isinstance(data, dict):
        return {}

    translations: dict[str, dict[str, str]] = {}
    for key, value in data.items():
        if not isinstance(key, str) or not isinstance(value, Mapping):
            continue
        item: dict[str, str] = {}
        for lang, text in value.items():
            if isinstance(lang, str) and isinstance(text, str):
                item[lang] = text
        if item:
            translations[key] = item
    return translations


_TRANSLATIONS: dict[str, dict[str, str]] = _load_translations()


class I18nService(QObject):
    """全局国际化服务。"""

    languageChanged = Signal(str)

    _instance: "I18nService | None" = None

    @classmethod
    def instance(cls) -> "I18nService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @staticmethod
    def normalize_language(language: str | None) -> str:
        if not language:
            return LANG_ZH_CN
        lang = str(language).strip().lower()
        if lang in _LANGUAGE_ALIASES:
            return _LANGUAGE_ALIASES[lang]
        if language in SUPPORTED_LANGUAGES:
            return language
        return LANG_ZH_CN

    def __init__(self, parent=None):
        super().__init__(parent)
        self._language = LANG_ZH_CN

    @property
    def language(self) -> str:
        return self._language

    def set_language(self, language: str) -> None:
        normalized = self.normalize_language(language)
        if normalized == self._language:
            return
        self._language = normalized
        self.languageChanged.emit(normalized)

    def t(self, key: str, default: str | None = None, **kwargs: Any) -> str:
        bundle = _TRANSLATIONS.get(key)
        if bundle is None:
            return default if default is not None else key
        text = bundle.get(self._language) or bundle.get(LANG_ZH_CN) or bundle.get(LANG_EN_US)
        if text is None:
            return default if default is not None else key
        if kwargs:
            try:
                return text.format(**kwargs)
            except Exception:
                return text
        return text

    def resolve_text(self, value: Any, default: str = "") -> str:
        if isinstance(value, str):
            return value
        if not isinstance(value, Mapping):
            return default

        def _pick(mapping: Mapping[str, Any], lang: str) -> str | None:
            for k in (lang, lang.lower(), lang.replace("-", "_"), lang.replace("-", "_").lower()):
                v = mapping.get(k)
                if isinstance(v, str) and v:
                    return v
            return None

        chosen = _pick(value, self._language)
        if chosen:
            return chosen
        chosen = _pick(value, LANG_ZH_CN) or _pick(value, LANG_EN_US)
        if chosen:
            return chosen
        for v in value.values():
            if isinstance(v, str) and v:
                return v
        return default

"""应用国际化服务。"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Mapping

from PySide6.QtCore import QObject, Signal

from app.utils.logger import logger


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
    """加载翻译文件"""
    if not _TRANSLATIONS_FILE.exists():
        logger.warning("翻译文件不存在: {}", _TRANSLATIONS_FILE)
        return {}

    try:
        data = json.loads(_TRANSLATIONS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.exception("加载翻译文件失败: {}", _TRANSLATIONS_FILE)
        return {}

    if not isinstance(data, dict):
        logger.warning("翻译文件格式错误(非对象): {}", _TRANSLATIONS_FILE)
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

    logger.info("翻译词条已加载: count={}", len(translations))
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
        """规范化语言代码"""
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
        logger.debug("I18nService 初始化完成: language={}", self._language)

    @property
    def language(self) -> str:
        return self._language

    def set_language(self, language: str) -> None:
        normalized = self.normalize_language(language)
        if normalized == self._language:
            return
        old_language = self._language
        self._language = normalized
        logger.info("语言已切换: {} -> {}", old_language, normalized)
        self.languageChanged.emit(normalized)

    def t(self, key: str, default: str | None = None, **kwargs: Any) -> str:
        """获取翻译文本，支持参数替换"""
        bundle = _TRANSLATIONS.get(key)
        if bundle is None:
            return default if default is not None else key

        text = (
            bundle.get(self._language)
            or bundle.get(LANG_ZH_CN)
            or bundle.get(LANG_EN_US)
        )
        if text is None:
            return default if default is not None else key

        if kwargs:
            try:
                return text.format(**kwargs)
            except (KeyError, ValueError) as e:
                logger.warning("翻译文本格式化失败: key={}, error={}", key, e)
                return text

        return text

    def resolve_text(self, value: Any, default: str = "") -> str:
        """从 {lang: text} 映射中解析文本"""
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

    def has_key(self, key: str) -> bool:
        """检查翻译键是否存在"""
        return key in _TRANSLATIONS

    def get_available_languages(self) -> list[str]:
        """获取可用的语言列表"""
        return list(SUPPORTED_LANGUAGES)

    def reload_translations(self) -> int:
        """重新加载翻译文件，返回加载的词条数"""
        global _TRANSLATIONS
        _TRANSLATIONS = _load_translations()
        return len(_TRANSLATIONS)

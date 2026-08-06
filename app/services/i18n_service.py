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


def _get_i18n_dir() -> Path:
    """翻译分片目录：config/i18n/*.json，按模块拆分，便于并行维护"""
    return _get_translations_file().parent / "i18n"


_TRANSLATIONS_FILE = _get_translations_file()


def _parse_translation_dict(
    data: object, source: str, sink: dict[str, dict[str, str]]
) -> int:
    """将单个翻译字典解析并入 sink，返回新增词条数"""
    if not isinstance(data, Mapping):
        logger.warning("翻译文件格式错误(非对象): {}", source)
        return 0

    added = 0
    for key, value in data.items():
        if not isinstance(key, str) or not isinstance(value, Mapping):
            continue
        item: dict[str, str] = {}
        for lang, text in value.items():
            if isinstance(lang, str) and isinstance(text, str):
                item[lang] = text
        if item:
            sink[key] = item
            added += 1
    return added


def _load_translations() -> dict[str, dict[str, str]]:
    """加载翻译文件：主文件 config/i18n.json + 分片 config/i18n/*.json

    分片文件采用与主文件相同的 {key: {lang: text}} 格式，按模块命名（如
    canvas.json、central_control.json），便于多人/多模块并行维护且互不冲突。
    主文件中的同名键优先级最高（后加载覆盖分片）。
    """
    translations: dict[str, dict[str, str]] = {}

    # 1) 分片文件（config/i18n/*.json）
    i18n_dir = _get_i18n_dir()
    if i18n_dir.is_dir():
        for frag_path in sorted(i18n_dir.glob("*.json")):
            try:
                data = json.loads(frag_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                logger.exception("加载翻译分片失败: {}", frag_path)
                continue
            count = _parse_translation_dict(data, str(frag_path), translations)
            logger.debug("翻译分片已加载: {} (count={})", frag_path.name, count)

    # 2) 主文件（优先级最高，覆盖同名键）
    if _TRANSLATIONS_FILE.exists():
        try:
            data = json.loads(_TRANSLATIONS_FILE.read_text(encoding="utf-8"))
            _parse_translation_dict(data, str(_TRANSLATIONS_FILE), translations)
        except (json.JSONDecodeError, OSError):
            logger.exception("加载翻译文件失败: {}", _TRANSLATIONS_FILE)
    else:
        logger.warning("翻译文件不存在: {}", _TRANSLATIONS_FILE)

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

    def _format_text(self, key: str, text: str, **kwargs: Any) -> str:
        if not kwargs:
            return text
        try:
            return text.format(**kwargs)
        except (KeyError, ValueError) as e:
            logger.warning("翻译文本格式化失败: key={}, error={}", key, e)
            return text

    def t(self, key: str, default: str | None = None, **kwargs: Any) -> str:
        """获取翻译文本，支持参数替换"""
        bundle = _TRANSLATIONS.get(key)
        if bundle is None:
            text = default if default is not None else key
            return self._format_text(key, text, **kwargs)

        text = (
            bundle.get(self._language)
            or bundle.get(LANG_ZH_CN)
            or bundle.get(LANG_EN_US)
        )
        if text is None:
            text = default if default is not None else key
            return self._format_text(key, text, **kwargs)

        return self._format_text(key, text, **kwargs)

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


# ─────────────────────────────────────────────────────────────────────────── #
# 模块级便捷函数：消除各视图文件中重复的翻译辅助函数
# ─────────────────────────────────────────────────────────────────────────── #

def tr(key: str, default: str | None = None, **kwargs: Any) -> str:
    """模块级翻译快捷函数。

    等价于 ``I18nService.instance().t(key, default=default, **kwargs)``，
    供无法持有 :class:`I18nService` 引用的模块/函数直接调用。
    新代码应优先使用本函数，而非在各文件内自定义 ``_t`` 包装。
    """
    return I18nService.instance().t(key, default=default, **kwargs)


def pick(zh: str, en: str) -> str:
    """根据当前界面语言在中/英文之间二选一。

    用于尚未迁入 ``i18n.json`` 的少量内联文案。新增文案应优先使用 :func:`tr`
    并在 ``i18n.json`` 中登记键名，以便统一审计与复用。
    """
    return en if I18nService.instance().language == LANG_EN_US else zh

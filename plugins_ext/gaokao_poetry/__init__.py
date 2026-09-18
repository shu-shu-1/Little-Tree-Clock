"""高考古诗词插件：内置高考必背古诗文，向「随机一言」注册数据源（数据来自 gaokao-poetry，CC BY-SA 4.0）。"""

from __future__ import annotations

import json
import random
import threading
from pathlib import Path

from app.plugins import BasePlugin, PluginAPI, PluginMeta

# 注册到「随机一言」的数据源 ID
SOURCE_ID = "gaokao_poetry"

_DATA_FILE = Path(__file__).resolve().parent / "data" / "gaokao_poems.json"
# 本轮不重复的记忆上限（覆盖全部 651 条仍有余量）
_RECENT_CAP = 800

_lock = threading.RLock()  # 可重入：_title_options/_author_options 持锁时内部还会调用 _ensure_poems
_poems: list[dict] | None = None
_recent_keys: list[str] = []  # 最近抽过的句子 key（FIFO）
_title_choices: list[list[str]] | None = None
_author_choices: list[list[str]] | None = None


def _ensure_poems() -> list[dict]:
    """惰性加载并归一化内置句子库（线程安全）。"""
    global _poems
    with _lock:
        if _poems is None:
            poems: list[dict] = []
            try:
                raw = json.loads(_DATA_FILE.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                raw = []
            if isinstance(raw, list):
                for item in raw:
                    if not isinstance(item, dict):
                        continue
                    title = str(item.get("title", "") or "").strip()
                    author = str(item.get("author", "") or "").strip()
                    textbook = str(item.get("textbook", "") or "").strip()
                    content = [str(line).strip() for line in (item.get("content") or []) if str(line).strip()]
                    if not title or not content:
                        continue
                    poems.append({"title": title, "author": author, "textbook": textbook, "content": content})
            _poems = poems
        return _poems


def _ordered_unique(values: list[str], with_count: dict[str, int], all_label: str) -> list[list[str]]:
    """按首次出现顺序去重，生成 [["", all_label], [值, "标签（N 句）"], …]。"""
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            ordered.append(value)
    return [["", all_label]] + [[v, f"{v}（{with_count[v]} 句）"] for v in ordered]


def _title_options() -> list[list[str]]:
    global _title_choices
    with _lock:
        if _title_choices is None:
            poems = _ensure_poems()
            counts: dict[str, int] = {}
            for item in poems:
                counts[item["title"]] = counts.get(item["title"], 0) + 1
            _title_choices = _ordered_unique([p["title"] for p in poems], counts, f"全部篇目（共 {len(poems)} 句）")
        return _title_choices


def _author_options() -> list[list[str]]:
    global _author_choices
    with _lock:
        if _author_choices is None:
            poems = _ensure_poems()
            counts: dict[str, int] = {}
            for item in poems:
                if item["author"]:
                    counts[item["author"]] = counts.get(item["author"], 0) + 1
            _author_choices = _ordered_unique([p["author"] for p in poems], counts, f"全部作者（共 {len(poems)} 句）")
        return _author_choices


# 抓取回调在「随机一言」的后台线程中被调用


def _item_key(item: dict) -> str:
    body = "\n".join(item["content"])
    return f"{item['title']}\n{body}"


def _filtered_poems(title_filter: str, author_filter: str) -> list[dict]:
    poems = _ensure_poems()
    if title_filter:
        poems = [p for p in poems if p["title"] == title_filter]
    if author_filter:
        poems = [p for p in poems if p["author"] == author_filter]
    return poems


def _format_source_info(item: dict) -> str:
    author = item["author"]
    title = item["title"]
    # 标题自带书名号（《论语》十二章）时不再重复包裹
    if title.startswith("《"):
        return f"——{author}{title}" if author else f"——{title}"
    return f"——{author}《{title}》" if author else f"——《{title}》"


def fetch_poetry(options: dict, props: dict) -> tuple[str, str, list[str]]:
    """随机抽取一条高考古诗文；仅当开启显示教材且教材可用时，扩展行携带教材徽章文本。"""
    opts = options if isinstance(options, dict) else {}
    title_filter = str(opts.get("title_filter", "") or "")
    author_filter = str(opts.get("author_filter", "") or "")
    no_repeat = bool(opts.get("no_repeat", True))
    show_textbook = bool(opts.get("show_textbook", True))

    pool = _filtered_poems(title_filter, author_filter)
    if not pool:
        raise ValueError("当前筛选条件下没有句子，请调整篇目/作者筛选")

    global _recent_keys
    with _lock:
        if no_repeat:
            recent = set(_recent_keys)
            fresh = [item for item in pool if _item_key(item) not in recent]
            if not fresh:
                _recent_keys = []
                fresh = pool
            pool = fresh

        item = random.choice(pool)

        if no_repeat:
            key = _item_key(item)
            if key not in _recent_keys:
                _recent_keys.append(key)
            if len(_recent_keys) > _RECENT_CAP:
                del _recent_keys[: len(_recent_keys) - _RECENT_CAP]

    extras: list[str] = []
    textbook = item["textbook"]
    if show_textbook and textbook and textbook != "教材无":
        extras.append(textbook)

    text = "\n".join(item["content"])
    return text, _format_source_info(item), extras


def build_options() -> list[dict]:
    return [
        {
            "key": "title_filter",
            "label": "篇目筛选",
            "label_i18n": {
                "zh-CN": "篇目筛选",
                "en-US": "Filter by title",
            },
            "type": "choice",
            "choices": _title_options(),
            "default": "",
        },
        {
            "key": "author_filter",
            "label": "作者筛选",
            "label_i18n": {
                "zh-CN": "作者筛选",
                "en-US": "Filter by author",
            },
            "type": "choice",
            "choices": _author_options(),
            "default": "",
        },
        {
            "key": "show_textbook",
            "label": "显示教材",
            "label_i18n": {
                "zh-CN": "显示教材",
                "en-US": "Show textbook",
            },
            "type": "bool",
            "default": True,
        },
        {
            "key": "no_repeat",
            "label": "本轮不重复",
            "label_i18n": {
                "zh-CN": "本轮不重复",
                "en-US": "No repeat in this round",
            },
            "type": "bool",
            "default": True,
        },
    ]


class Plugin(BasePlugin):
    meta = PluginMeta(
        id="gaokao_poetry",
        name="高考古诗词",
        version="1.1.0",
        description="内置 651 句高考必背古诗文（含教材标注），为「随机一言」提供数据源，支持按篇目/作者筛选、不重复抽取与教材徽章显示",
        requires=["hitokoto_widget"],
        homepage="https://github.com/clover-yan/gaokao-poetry",
        tags=["poetry", "quote", "study"],
    )

    def __init__(self):
        self._api: PluginAPI | None = None

    def on_load(self, api: PluginAPI) -> None:
        self._api = api

        hitokoto = api.get_plugin("hitokoto_widget")
        if hitokoto is None:
            api.show_toast(
                "高考古诗词",
                "未找到「随机一言」插件，无法注册数据源",
                level="warning",
            )
            return

        ok = hitokoto.register_data_source(
            SOURCE_ID,
            fetch_poetry,
            name="高考古诗词",
            name_i18n={
                "zh-CN": "高考古诗词",
                "en-US": "Gaokao Poetry",
            },
            owner_plugin_id="gaokao_poetry",
            options=build_options(),
        )
        if ok:
            api.show_toast(
                "高考古诗词",
                f"已注册数据源（{len(_ensure_poems())} 句），编辑「随机一言」组件即可选择",
                level="success",
            )
        else:
            api.show_toast(
                "高考古诗词",
                "数据源注册失败，请检查插件版本",
                level="error",
            )

    def on_unload(self) -> None:
        api = self._api
        if api is None:
            return
        try:
            hitokoto = api.get_plugin("hitokoto_widget")
            if hitokoto is not None:
                hitokoto.unregister_data_source(SOURCE_ID, owner_plugin_id="gaokao_poetry")
        except Exception:
            pass

"""示例依赖插件（LibraryPlugin）：提供可复用的工具方法。

主入口类必须名为 ``Plugin`` 并继承 LibraryPlugin，plugin.json 中 ``plugin_type``
须为 ``"library"``。实现 ``export()`` 返回公开接口对象供其他插件调用；依赖插件
同样可以声明 ``requires``，但不应直接修改 UI。
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime

from app.plugins import LibraryPlugin, PluginAPI, PluginMeta, PluginType


# 公开接口对象（推荐与插件实现分离）


class ExampleLibInterface:
    """供其他插件调用的公开接口：文本、时间与哈希工具。

    用法::

        lib = api.get_plugin("example_lib")
        if lib:
            ts = lib.format_timestamp(datetime.now())
            h  = lib.md5("hello")
    """

    # 文本工具

    def truncate(self, text: str, max_len: int = 50, ellipsis: str = "…") -> str:
        if len(text) <= max_len:
            return text
        return text[: max_len - len(ellipsis)] + ellipsis

    def strip_html(self, html: str) -> str:
        return re.sub(r"<[^>]+>", "", html).strip()

    # 时间工具

    def format_timestamp(self, dt: datetime, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
        return dt.strftime(fmt)

    def friendly_duration(self, seconds: int) -> str:
        """将秒数转为人类可读时长，例如 3661 → "1 小时 1 分 1 秒"。"""
        if seconds < 0:
            return "0 秒"
        parts = []
        h = seconds // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60
        if h:
            parts.append(f"{h} 小时")
        if m:
            parts.append(f"{m} 分")
        if s or not parts:
            parts.append(f"{s} 秒")
        return " ".join(parts)

    # 哈希工具

    def md5(self, text: str, encoding: str = "utf-8") -> str:
        return hashlib.md5(text.encode(encoding)).hexdigest()

    def sha256(self, text: str, encoding: str = "utf-8") -> str:
        return hashlib.sha256(text.encode(encoding)).hexdigest()


# 依赖插件主类


class Plugin(LibraryPlugin):
    """plugin.json 已声明 plugin_type，此处 meta 仅作无清单时的回退。"""

    meta = PluginMeta(
        id="example_lib",
        name="示例工具库",
        version="1.0.0",
        description="演示依赖插件格式：提供文本、时间、哈希工具方法",
        plugin_type=PluginType.LIBRARY,
    )

    def __init__(self):
        self._interface = ExampleLibInterface()

    def on_load(self, api: PluginAPI) -> None:
        # 依赖插件可在此初始化，但不要修改 UI；本示例只准备接口对象。
        pass

    def export(self) -> ExampleLibInterface:
        return self._interface

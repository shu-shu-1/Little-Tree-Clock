"""全屏时钟画布组件主题色工具。

提供统一的深浅色判断与配色接口，供所有内置组件和插件组件使用。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from qfluentwidgets import isDarkTheme

# 哨兵：区分「缓存未命中」与「缓存了 falsy 值」
_NO_CACHE: object = object()

# ─────────────────────────────────────────────────────────────────
# 静态配色表（深 / 浅）。作为模块级常量，避免每次调用时重建 ~30 项字典。
# ─────────────────────────────────────────────────────────────────
_DARK_COLORS: dict[str, str] = {
    "primary":       "#ffffff",
    "secondary":     "#aaaaaa",
    "tertiary":      "#888888",
    "hint":          "#555555",
    "accent":        "#c8a96e",
    "positive":      "#5c5c5c",
    "negative":      "#e55555",
    "btn_bg":        "rgba(255,255,255,35)",
    "btn_bg_hover":  "rgba(255,255,255,65)",
    "btn_bg_press":  "rgba(255,255,255,18)",
    "btn_bg_dis":    "rgba(255,255,255,10)",
    "btn_text":      "white",
    "btn_text_dis":  "rgba(255,255,255,70)",
    "card_bg":       "rgba(255,255,255,30)",
    "border":        "rgba(255,255,255,25)",
    "bar_bg":        "rgba(10,10,10,200)",
    "bar_border":    "rgba(255,255,255,20)",
    "topbar_bg":     "rgba(0,0,0,100)",
    "hint_text":     "rgba(255,255,255,50)",
    "canvas_bg":     "#080808",
    "grid_line":     "#19ffffff",
    "edit_border":   "#78ffffff",
    "close_hover":   "rgba(196,43,43,200)",
    "close_press":   "rgba(160,30,30,220)",
    "display_bg":    "rgba(0,0,0,40)",
    "empty_hint":    "#666666",
    "calculator_num":"rgba(255,255,255,20)",
    "calculator_op": "rgba(255,160,0,30)",
    "calculator_eq": "rgba(100,180,255,120)",
    "calculator_clr":"rgba(255,80,80,30)",
}

_LIGHT_COLORS: dict[str, str] = {
    "primary":       "#1a1a1a",
    "secondary":     "#555555",
    "tertiary":      "#777777",
    "hint":          "#999999",
    "accent":        "#9a7b3c",
    "positive":      "#2e7d32",
    "negative":      "#c62828",
    "btn_bg":        "rgba(0,0,0,25)",
    "btn_bg_hover":  "rgba(0,0,0,50)",
    "btn_bg_press":  "rgba(0,0,0,15)",
    "btn_bg_dis":    "rgba(0,0,0,8)",
    "btn_text":      "#1a1a1a",
    "btn_text_dis":  "rgba(0,0,0,70)",
    "card_bg":       "rgba(0,0,0,18)",
    "border":        "rgba(0,0,0,20)",
    "bar_bg":        "rgba(240,240,240,220)",
    "bar_border":    "rgba(0,0,0,15)",
    "topbar_bg":     "rgba(255,255,255,160)",
    "hint_text":     "rgba(0,0,0,60)",
    "canvas_bg":     "#f0f0f0",
    "grid_line":     "#cccccc",
    "edit_border":   "#3c000000",
    "close_hover":   "rgba(196,43,43,200)",
    "close_press":   "rgba(160,30,30,220)",
    "display_bg":    "rgba(0,0,0,25)",
    "empty_hint":    "#aaaaaa",
    "calculator_num":"rgba(0,0,0,15)",
    "calculator_op": "rgba(255,160,0,30)",
    "calculator_eq": "rgba(100,180,255,140)",
    "calculator_clr":"rgba(255,80,80,30)",
}

# ─────────────────────────────────────────────────────────────────
# 结果缓存
#
# widget_colors / is_widget_dark 在每次 paintEvent 与每秒 refresh 中被大量
# 调用（每个画布组件都会触发），是渲染热路径。其结果仅取决于：
#   1) 画布级独立主题 / 自定义颜色（zone_id 对应的 canvas_settings）
#   2) 全局全屏主题（fullscreen_theme）
#   3) 系统主题（QStyleHints.colorScheme）或应用主题（isDarkTheme）
# 因此按 zone_id 缓存最近一次结果，并在上述任一输入变化时显式失效。
# ─────────────────────────────────────────────────────────────────
_dark_cache: dict[str | None, bool] = {}
_colors_cache: dict[str | None, dict[str, str]] = {}


def invalidate_widget_color_cache(zone_id: str | None = None) -> None:
    """使配色 / 深浅缓存失效。

    画布自定义颜色或全局主题变更后应调用。``zone_id`` 为 None 时清空全部缓存。
    """
    if zone_id is None:
        _dark_cache.clear()
        _colors_cache.clear()
    else:
        _dark_cache.pop(zone_id, None)
        _colors_cache.pop(zone_id, None)


def is_widget_dark(zone_id: str | None = None) -> bool:
    """判断当前全屏时钟画布是否应使用深色模式。

    优先使用画布级独立主题设置，其次全局全屏主题，最后回退到应用主题。
    """
    cached = _dark_cache.get(zone_id, _NO_CACHE)
    if cached is not _NO_CACHE:
        return cached  # type: ignore[return-value]

    from app.services.settings_service import SettingsService

    result: bool
    if zone_id is not None:
        from app.widgets.layout_store import WidgetLayoutStore
        cs = WidgetLayoutStore.instance().get_canvas_settings(zone_id)
        t = cs.get("theme")
        if t == "dark":
            result = True
        elif t == "light":
            result = False
        elif t == "system":
            result = is_system_dark()
        elif t == "app":
            result = isDarkTheme()
        else:
            theme = SettingsService.instance().fullscreen_theme
            result = _theme_to_dark(theme)
    else:
        theme = SettingsService.instance().fullscreen_theme
        result = _theme_to_dark(theme)

    _dark_cache[zone_id] = result
    return result


def _theme_to_dark(theme: str) -> bool:
    if theme == "dark":
        return True
    if theme == "light":
        return False
    if theme == "system":
        return is_system_dark()
    return isDarkTheme()


def is_system_dark() -> bool:
    """直接读取操作系统配色，不受应用当前主题影响。"""
    app = QGuiApplication.instance()
    if app is not None:
        scheme = app.styleHints().colorScheme()
        if scheme == Qt.ColorScheme.Dark:
            return True
        if scheme == Qt.ColorScheme.Light:
            return False

    # Qt 无法识别系统配色时，保持与当前应用主题一致作为保底。
    return isDarkTheme()


def widget_colors(zone_id: str | None = None) -> dict[str, str]:
    """返回当前主题下的画布组件配色字典。

    当提供 zone_id 时，画布级自定义颜色会覆盖全局默认值。
    """
    cached = _colors_cache.get(zone_id, _NO_CACHE)
    if cached is not _NO_CACHE:
        return cached  # type: ignore[return-value]

    dark = is_widget_dark(zone_id)
    base = _DARK_COLORS if dark else _LIGHT_COLORS

    if zone_id is not None:
        from app.widgets.layout_store import WidgetLayoutStore
        cs = WidgetLayoutStore.instance().get_canvas_settings(zone_id)
        bg_color = cs.get("bg_color")
        grid_color = cs.get("grid_color")
        if bg_color or grid_color:
            # 仅在有自定义覆盖时复制一份，避免污染常量表。
            merged = dict(base)
            if bg_color:
                merged["canvas_bg"] = bg_color
            if grid_color:
                merged["grid_line"] = grid_color
            result = merged
        else:
            result = base
    else:
        result = base

    _colors_cache[zone_id] = result
    return result

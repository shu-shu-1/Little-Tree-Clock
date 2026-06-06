"""全屏时钟画布组件主题色工具。

提供统一的深浅色判断与配色接口，供所有内置组件和插件组件使用。
"""
from __future__ import annotations

from qfluentwidgets import isDarkTheme, qconfig


def is_widget_dark(zone_id: str | None = None) -> bool:
    """判断当前全屏时钟画布是否应使用深色模式。

    优先使用画布级独立主题设置，其次全局全屏主题，最后回退到应用主题。
    """
    from app.services.settings_service import SettingsService

    if zone_id is not None:
        from app.widgets.layout_store import WidgetLayoutStore
        cs = WidgetLayoutStore.instance().get_canvas_settings(zone_id)
        t = cs.get("theme")
        if t == "dark":
            return True
        if t == "light":
            return False
        if t == "app":
            return isDarkTheme()

    theme = SettingsService.instance().fullscreen_theme
    if theme == "dark":
        return True
    if theme == "light":
        return False
    return isDarkTheme()


def widget_colors(zone_id: str | None = None) -> dict[str, str]:
    """返回当前主题下的画布组件配色字典。

    当提供 zone_id 时，画布级自定义颜色会覆盖全局默认值。
    """
    dark = is_widget_dark(zone_id)
    if dark:
        base = {
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
    else:
        base = {
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

    if zone_id is not None:
        from app.widgets.layout_store import WidgetLayoutStore
        cs = WidgetLayoutStore.instance().get_canvas_settings(zone_id)
        bg_color = cs.get("bg_color")
        if bg_color:
            base["canvas_bg"] = bg_color
        grid_color = cs.get("grid_color")
        if grid_color:
            base["grid_line"] = grid_color

    return base

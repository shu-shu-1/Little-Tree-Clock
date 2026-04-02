"""应用通用设置服务（持久化到 settings.json）"""
from __future__ import annotations

from typing import Any, Optional

from PySide6.QtCore import QObject, Signal

from app.constants import SETTINGS_CONFIG
from app.services.i18n_service import I18nService
from app.utils.logger import logger
from app.utils.time_utils import load_json, save_json
from app.utils.validators import clamp_int, validate_range
from app.utils.performance import profile


class SettingsService(QObject):
    """
    单例设置服务。

    信号
    ----
    changed()  — 任意设置项变更时发出
    """

    changed = Signal()
    cell_size_changed = Signal(int)   # 全屏时钟格子大小变更，携带新值

    _instance: "SettingsService | None" = None

    @classmethod
    def instance(cls) -> "SettingsService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._data: dict[str, Any] = load_json(SETTINGS_CONFIG, {})
        self._last_saved_data: dict[str, Any] = dict(self._data)
        logger.debug("[设置] 已加载配置项 {} 个", len(self._data))

    # ─────────────────────────────────────────────────────────────────────────── #
    # 内部工具
    # ─────────────────────────────────────────────────────────────────────────── #

    @staticmethod
    def _short_repr(value: Any, max_len: int = 80) -> str:
        text = repr(value)
        return text if len(text) <= max_len else f"{text[:max_len - 3]}..."

    @staticmethod
    def _valid_precision(v: Any) -> int:
        """验证精度值：0=整秒, 1=十分位, 2=百分位"""
        return clamp_int(v, 0, 2, 1)

    def _get_int(self, key: str, default: int, min_val: int = 0, max_val: int = 999999) -> int:
        """获取整数配置项，带范围限制"""
        return clamp_int(self._data.get(key, default), min_val, max_val, default)

    def _get_str(self, key: str, default: str = "") -> str:
        """获取字符串配置项"""
        return str(self._data.get(key, default))

    def _get_bool(self, key: str, default: bool = False) -> bool:
        """获取布尔配置项"""
        return bool(self._data.get(key, default))

    def _set_and_save(self, key: str, value: Any, emit_changed: bool = True) -> None:
        """通用设置保存方法"""
        self._data[key] = value
        self._save()
        if emit_changed:
            self.changed.emit()

    # ─────────────────────────────────────────────────────────────────────────── #
    # 秒表 / 计时器精度
    # ─────────────────────────────────────────────────────────────────────────── #

    @property
    def stopwatch_precision(self) -> int:
        """秒表精度：0 = 整秒  1 = 十分位  2 = 百分位（默认 1）"""
        v = self._data.get("stopwatch_precision", self._data.get("duration_precision", 1))
        return self._valid_precision(v)

    def set_stopwatch_precision(self, value: int) -> None:
        self._set_and_save("stopwatch_precision", clamp_int(value, 0, 2, 1))

    @property
    def timer_precision(self) -> int:
        """计时器精度：0 = 整秒  1 = 十分位  2 = 百分位（默认 1）"""
        v = self._data.get("timer_precision", self._data.get("duration_precision", 1))
        return self._valid_precision(v)

    def set_timer_precision(self, value: int) -> None:
        self._set_and_save("timer_precision", clamp_int(value, 0, 2, 1))

    # 向后兼容旧属性名
    @property
    def duration_precision(self) -> int:
        return self.stopwatch_precision

    def set_duration_precision(self, value: int) -> None:
        self.set_stopwatch_precision(value)

    # ─────────────────────────────────────────────────────────────────────────── #
    # 悬浮小窗透明度
    # ─────────────────────────────────────────────────────────────────────────── #

    @property
    def float_opacity(self) -> int:
        """悬浮小窗不透明度：10~100（整数百分比），默认 90"""
        return self._get_int("float_opacity", 90, min_val=10, max_val=100)

    def set_float_opacity(self, value: int) -> None:
        self._set_and_save("float_opacity", clamp_int(value, 10, 100, 90))

    # ─────────────────────────────────────────────────────────────────────────── #
    # 铃声列表
    # ─────────────────────────────────────────────────────────────────────────── #

    @property
    def ringtones(self) -> list[dict[str, str]]:
        """返回 [{name: str, path: str}, ...] 铃声列表"""
        data = self._data.get("ringtones", [])
        return [{"name": str(r.get("name", "")), "path": str(r.get("path", ""))} for r in data if isinstance(r, dict)]

    def add_ringtone(self, name: str, path: str) -> None:
        """添加一个铃声（path 相同时跳过）"""
        lst = self.ringtones
        if any(r["path"] == path for r in lst):
            return
        lst.append({"name": name.strip() or path, "path": path})
        self._set_and_save("ringtones", lst)

    def remove_ringtone(self, path: str) -> None:
        """按 path 删除铃声"""
        lst = [r for r in self.ringtones if r["path"] != path]
        self._set_and_save("ringtones", lst)

    # ─────────────────────────────────────────────────────────────────────────── #
    # 插件依赖安装镜像源
    # ─────────────────────────────────────────────────────────────────────────── #

    @property
    def pip_mirror(self) -> str:
        """插件依赖安装使用的 pip 镜像源 URL（空字符串表示 PyPI 官方）。"""
        return self._get_str("pip_mirror")

    def set_pip_mirror(self, url: str) -> None:
        self._set_and_save("pip_mirror", url.strip() if url else "")

    # ─────────────────────────────────────────────────────────────────────────── #
    # 自定义 Toast 通知
    # ─────────────────────────────────────────────────────────────────────────── #

    @property
    def notification_use_custom(self) -> bool:
        """是否使用自定义 Toast 通知（代替系统通知）"""
        return self._get_bool("notification_use_custom")

    def set_notification_use_custom(self, value: bool) -> None:
        self._set_and_save("notification_use_custom", bool(value))

    @property
    def notification_position(self) -> str:
        """Toast 出现位置，默认右下角"""
        from app.views.toast_notification import ALL_POSITIONS, POS_BOTTOM_RIGHT
        v = self._get_str("notification_position")
        return validate_range(v, ALL_POSITIONS, POS_BOTTOM_RIGHT)

    def set_notification_position(self, value: str) -> None:
        from app.views.toast_notification import ALL_POSITIONS, POS_BOTTOM_RIGHT
        validated = validate_range(value, ALL_POSITIONS, POS_BOTTOM_RIGHT)
        self._set_and_save("notification_position", validated)

    @property
    def notification_duration_ms(self) -> int:
        """Toast 停留时长（毫秒），0 = 常驻"""
        return self._get_int("notification_duration_ms", 5000, min_val=0)

    def set_notification_duration_ms(self, value: int) -> None:
        self._set_and_save("notification_duration_ms", max(0, int(value)))

    # ─────────────────────────────────────────────────────────────────────────── #
    # 闹钟提醒
    # ─────────────────────────────────────────────────────────────────────────── #

    @property
    def alarm_alert_duration_sec(self) -> int:
        """闹钟提醒等待时长（秒），10~600，默认 60"""
        return self._get_int("alarm_alert_duration_sec", 60, min_val=10, max_val=600)

    def set_alarm_alert_duration_sec(self, value: int) -> None:
        self._set_and_save("alarm_alert_duration_sec", clamp_int(value, 10, 600, 60))

    # ─────────────────────────────────────────────────────────────────────────── #
    # 时间偏移（调试用）
    # ─────────────────────────────────────────────────────────────────────────── #

    @property
    def time_offset_seconds(self) -> int:
        """手动时间偏移（秒），用于调试特殊场景，默认 0"""
        return self._get_int("time_offset_seconds", 0)

    def set_time_offset_seconds(self, value: int) -> None:
        self._set_and_save("time_offset_seconds", int(value))

    # ─────────────────────────────────────────────────────────────────────────── #
    # 外观主题
    # ─────────────────────────────────────────────────────────────────────────── #

    @property
    def theme(self) -> str:
        """界面主题：'auto' | 'light' | 'dark'，默认 'auto'"""
        return validate_range(self._get_str("theme"), {"auto", "light", "dark"}, "auto")

    def set_theme(self, value: str) -> None:
        self._set_and_save("theme", validate_range(value, {"auto", "light", "dark"}, "auto"))

    # ─────────────────────────────────────────────────────────────────────────── #
    # 全局平滑滚动
    # ─────────────────────────────────────────────────────────────────────────── #

    @property
    def ui_smooth_scroll_enabled(self) -> bool:
        """是否启用全局平滑滚动（默认 True）"""
        return self._get_bool("ui_smooth_scroll_enabled", default=True)

    def set_ui_smooth_scroll_enabled(self, value: bool) -> None:
        enabled = bool(value)
        if enabled == self.ui_smooth_scroll_enabled:
            return
        self._set_and_save("ui_smooth_scroll_enabled", enabled)

    # ─────────────────────────────────────────────────────────────────────────── #
    # 语言
    # ─────────────────────────────────────────────────────────────────────────── #

    @property
    def language(self) -> str:
        """界面语言：'zh-CN' | 'en-US'，默认 'zh-CN'"""
        raw = self._get_str("language")
        return I18nService.normalize_language(raw)

    def set_language(self, value: str) -> None:
        normalized = I18nService.normalize_language(value)
        if normalized != self._get_str("language"):
            self._set_and_save("language", normalized)

    # ─────────────────────────────────────────────────────────────────────────── #
    # 测试版水印可见性
    # ─────────────────────────────────────────────────────────────────────────── #

    @property
    def watermark_main_visible(self) -> bool:
        """主窗口水印是否显示（默认 True）"""
        return self._get_bool("watermark_main_visible", default=True)

    def set_watermark_main_visible(self, value: bool) -> None:
        self._set_and_save("watermark_main_visible", bool(value))

    @property
    def watermark_worldtime_visible(self) -> bool:
        """世界时间视图水印是否显示（默认 True）"""
        return self._get_bool("watermark_worldtime_visible", default=True)

    def set_watermark_worldtime_visible(self, value: bool) -> None:
        self._set_and_save("watermark_worldtime_visible", bool(value))

    # ─────────────────────────────────────────────────────────────────────────── #
    # 启动菜单
    # ─────────────────────────────────────────────────────────────────────────── #

    @property
    def show_boot_menu_next_start(self) -> bool:
        """下次启动时是否显示启动选项菜单（一次性，显示后自动重置为 False）"""
        return self._get_bool("show_boot_menu_next_start")

    def set_show_boot_menu_next_start(self, value: bool) -> None:
        self._set_and_save("show_boot_menu_next_start", bool(value))

    # ─────────────────────────────────────────────────────────────────────────── #
    # 首次启动向导
    # ─────────────────────────────────────────────────────────────────────────── #

    @property
    def first_use_completed(self) -> bool:
        """首次启动向导是否已完成（默认 False）"""
        return self._get_bool("first_use_completed")

    def set_first_use_completed(self, value: bool) -> None:
        self._set_and_save("first_use_completed", bool(value))

    # ─────────────────────────────────────────────────────────────────────────── #
    # 开机自启动隐藏到托盘
    # ─────────────────────────────────────────────────────────────────────────── #

    @property
    def autostart_hide_to_tray(self) -> bool:
        """开机自启动时是否隐藏到托盘（默认 True）"""
        return self._get_bool("autostart_hide_to_tray", default=True)

    def set_autostart_hide_to_tray(self, value: bool) -> None:
        self._set_and_save("autostart_hide_to_tray", bool(value))

    # ─────────────────────────────────────────────────────────────────────────── #
    # 全屏时钟格子大小
    # ─────────────────────────────────────────────────────────────────────────── #

    @property
    def widget_cell_size(self) -> int:
        """全屏时钟画布的单格像素尺寸：60~300，默认 120"""
        from app.constants import WIDGET_CELL_SIZE as _DEFAULT
        return self._get_int("widget_cell_size", _DEFAULT, min_val=60, max_val=300)

    def set_widget_cell_size(self, value: int) -> None:
        from app.constants import WIDGET_CELL_SIZE as _DEFAULT
        clamped = clamp_int(value, 60, 300, _DEFAULT)
        if clamped == self.widget_cell_size:
            return
        self._data["widget_cell_size"] = clamped
        self._save()
        self.changed.emit()
        self.cell_size_changed.emit(clamped)

    @property
    def widget_canvas_overlap_group_enabled(self) -> bool:
        """画布内拖拽重叠时是否自动生成组件组（默认 False）"""
        legacy = self._get_bool("widget_overlap_merge_enabled")
        return self._get_bool("widget_canvas_overlap_group_enabled", default=legacy)

    def set_widget_canvas_overlap_group_enabled(self, value: bool) -> None:
        enabled = bool(value)
        if enabled == self.widget_canvas_overlap_group_enabled:
            return
        self._data["widget_canvas_overlap_group_enabled"] = enabled
        if enabled == self.widget_detached_overlap_merge_enabled:
            self._data["widget_overlap_merge_enabled"] = enabled
        self._save()
        self.changed.emit()

    @property
    def widget_detached_overlap_merge_enabled(self) -> bool:
        """分离窗口重叠时是否自动合并为一个组件组窗口（默认 False）"""
        legacy = self._get_bool("widget_overlap_merge_enabled")
        return self._get_bool("widget_detached_overlap_merge_enabled", default=legacy)

    def set_widget_detached_overlap_merge_enabled(self, value: bool) -> None:
        enabled = bool(value)
        if enabled == self.widget_detached_overlap_merge_enabled:
            return
        self._data["widget_detached_overlap_merge_enabled"] = enabled
        if enabled == self.widget_canvas_overlap_group_enabled:
            self._data["widget_overlap_merge_enabled"] = enabled
        self._save()
        self.changed.emit()

    @property
    def widget_overlap_merge_enabled(self) -> bool:
        """兼容旧字段：仅当画布与分离窗口两侧都开启时返回 True"""
        return self.widget_canvas_overlap_group_enabled and self.widget_detached_overlap_merge_enabled

    def set_widget_overlap_merge_enabled(self, value: bool) -> None:
        """兼容旧接口：同时设置画布与分离窗口两侧开关"""
        enabled = bool(value)
        if (
            enabled == self.widget_canvas_overlap_group_enabled
            and enabled == self.widget_detached_overlap_merge_enabled
        ):
            return
        self._data["widget_canvas_overlap_group_enabled"] = enabled
        self._data["widget_detached_overlap_merge_enabled"] = enabled
        self._data["widget_overlap_merge_enabled"] = enabled
        self._save()
        self.changed.emit()

    @property
    def widget_auto_fill_gap_enabled(self) -> bool:
        """新增组件时是否优先自动补齐空位（默认 True）"""
        return self._get_bool("widget_auto_fill_gap_enabled", default=True)

    def set_widget_auto_fill_gap_enabled(self, value: bool) -> None:
        enabled = bool(value)
        changed = enabled != self.widget_auto_fill_gap_enabled
        if not enabled and bool(self._data.get("widget_prevent_new_overflow_enabled", False)):
            self._data["widget_prevent_new_overflow_enabled"] = False
            changed = True
        if not changed:
            return
        self._data["widget_auto_fill_gap_enabled"] = enabled
        if not enabled:
            self._data["widget_prevent_new_overflow_enabled"] = False
        self._save()
        self.changed.emit()

    @property
    def widget_prevent_new_overflow_enabled(self) -> bool:
        """新增组件时是否阻止溢出；当自动补齐空位关闭时此项强制为 False"""
        if not self.widget_auto_fill_gap_enabled:
            return False
        return self._get_bool("widget_prevent_new_overflow_enabled", default=True)

    def set_widget_prevent_new_overflow_enabled(self, value: bool) -> None:
        if not self.widget_auto_fill_gap_enabled:
            if bool(self._data.get("widget_prevent_new_overflow_enabled", False)):
                self._data["widget_prevent_new_overflow_enabled"] = False
                self._save()
                self.changed.emit()
            return
        enabled = bool(value)
        if enabled == self.widget_prevent_new_overflow_enabled:
            return
        self._set_and_save("widget_prevent_new_overflow_enabled", enabled)

    @property
    def detached_widget_background_opacity(self) -> int:
        """分离窗口背景不透明度：0~100，默认 75"""
        return self._get_int("detached_widget_background_opacity", 75, min_val=0, max_val=100)

    def set_detached_widget_background_opacity(self, value: int) -> None:
        clamped = clamp_int(value, 0, 100, 75)
        if clamped == self.detached_widget_background_opacity:
            return
        self._set_and_save("detached_widget_background_opacity", clamped)

    # ─────────────────────────────────────────────────────────────────────────── #
    # 配置变更追踪与保存
    # ─────────────────────────────────────────────────────────────────────────── #

    @profile
    def _save(self) -> None:
        """保存配置到磁盘"""
        sentinel = object()
        before = getattr(self, "_last_saved_data", {})
        keys = sorted(set(before.keys()) | set(self._data.keys()))
        changes: list[tuple[str, object, object]] = []

        for key in keys:
            old_value = before.get(key, sentinel)
            new_value = self._data.get(key, sentinel)
            if old_value != new_value:
                changes.append((
                    key,
                    "<unset>" if old_value is sentinel else old_value,
                    "<unset>" if new_value is sentinel else new_value,
                ))

        try:
            save_json(SETTINGS_CONFIG, self._data)
        except OSError:
            logger.exception("[设置] 保存配置失败")
            raise

        if changes:
            preview = "; ".join(
                f"{k}: {self._short_repr(o)} -> {self._short_repr(n)}"
                for k, o, n in changes[:8]
            )
            if len(changes) > 8:
                preview = f"{preview}; ..."
            logger.debug("[设置] 已保存 {} 项变更：{}", len(changes), preview)

        self._last_saved_data = dict(self._data)

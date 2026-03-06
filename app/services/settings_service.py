"""应用通用设置服务（持久化到 settings.json）"""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from app.constants import SETTINGS_CONFIG
from app.services.i18n_service import I18nService
from app.utils.time_utils import load_json, save_json


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

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data: dict = load_json(SETTINGS_CONFIG, {})

    # ------------------------------------------------------------------ #
    # 秒表 / 计时器精度（分别独立）
    # ------------------------------------------------------------------ #

    @staticmethod
    def _valid_precision(v) -> int:
        return int(v) if v in (0, 1, 2) else 1

    @property
    def stopwatch_precision(self) -> int:
        """秒表精度：0 = 整秒  1 = 十分位  2 = 百分位（默认 1）"""
        v = self._data.get("stopwatch_precision",
            self._data.get("duration_precision", 1))  # 兼容旧配置
        return self._valid_precision(v)

    def set_stopwatch_precision(self, value: int) -> None:
        self._data["stopwatch_precision"] = int(value)
        self._save()
        self.changed.emit()

    @property
    def timer_precision(self) -> int:
        """计时器精度：0 = 整秒  1 = 十分位  2 = 百分位（默认 1）"""
        v = self._data.get("timer_precision",
            self._data.get("duration_precision", 1))  # 兼容旧配置
        return self._valid_precision(v)

    def set_timer_precision(self, value: int) -> None:
        self._data["timer_precision"] = int(value)
        self._save()
        self.changed.emit()

    # ------------------------------------------------------------------ #
    # 悬浮小窗透明度
    # ------------------------------------------------------------------ #

    @property
    def float_opacity(self) -> int:
        """悬浮小窗不透明度：10~100（整数百分比），默认 90"""
        v = self._data.get("float_opacity", 90)
        try:
            return max(10, min(100, int(v)))
        except (ValueError, TypeError):
            return 90

    def set_float_opacity(self, value: int) -> None:
        self._data["float_opacity"] = max(10, min(100, int(value)))
        self._save()
        self.changed.emit()

    # 向后兼容旧属性名（外部代码如有引用不会报错）
    @property
    def duration_precision(self) -> int:
        return self.stopwatch_precision

    def set_duration_precision(self, value: int) -> None:
        self.set_stopwatch_precision(value)

    # ------------------------------------------------------------------ #
    # 铃声列表
    # ------------------------------------------------------------------ #

    @property
    def ringtones(self) -> list[dict]:
        """返回 [{name: str, path: str}, ...] 铃声列表"""
        return list(self._data.get("ringtones", []))

    def add_ringtone(self, name: str, path: str) -> None:
        """添加一个铃声（path 相同时跳过）"""
        lst = self.ringtones
        if any(r["path"] == path for r in lst):
            return
        lst.append({"name": name.strip() or path, "path": path})
        self._data["ringtones"] = lst
        self._save()
        self.changed.emit()

    def remove_ringtone(self, path: str) -> None:
        """按 path 删除铃声"""
        lst = [r for r in self.ringtones if r["path"] != path]
        self._data["ringtones"] = lst
        self._save()
        self.changed.emit()

    # ------------------------------------------------------------------ #
    # 插件依赖安装镜像源
    # ------------------------------------------------------------------ #

    @property
    def pip_mirror(self) -> str:
        """插件依赖安装使用的 pip 镜像源 URL（空字符串表示 PyPI 官方）。"""
        return str(self._data.get("pip_mirror", ""))

    def set_pip_mirror(self, url: str) -> None:
        self._data["pip_mirror"] = url.strip()
        self._save()
        self.changed.emit()

    # ------------------------------------------------------------------ #
    # 自定义 Toast 通知
    # ------------------------------------------------------------------ #

    @property
    def notification_use_custom(self) -> bool:
        """是否使用自定义 Toast 通知（代替系统通知）"""
        return bool(self._data.get("notification_use_custom", False))

    def set_notification_use_custom(self, value: bool) -> None:
        self._data["notification_use_custom"] = bool(value)
        self._save()
        self.changed.emit()

    @property
    def notification_position(self) -> str:
        """Toast 出现位置，默认右下角"""
        from app.views.toast_notification import ALL_POSITIONS, POS_BOTTOM_RIGHT
        v = self._data.get("notification_position", POS_BOTTOM_RIGHT)
        return v if v in ALL_POSITIONS else POS_BOTTOM_RIGHT

    def set_notification_position(self, value: str) -> None:
        self._data["notification_position"] = value
        self._save()
        self.changed.emit()

    @property
    def notification_duration_ms(self) -> int:
        """Toast 停留时长（毫秒），0 = 常驻"""
        v = self._data.get("notification_duration_ms", 5000)
        try:
            return max(0, int(v))
        except (ValueError, TypeError):
            return 5000

    def set_notification_duration_ms(self, value: int) -> None:
        self._data["notification_duration_ms"] = max(0, int(value))
        self._save()
        self.changed.emit()

    # ------------------------------------------------------------------ #
    # 闹钟提醒
    # ------------------------------------------------------------------ #

    @property
    def alarm_alert_duration_sec(self) -> int:
        """闹钟提醒等待时长（秒），10~600，默认 60"""
        v = self._data.get("alarm_alert_duration_sec", 60)
        try:
            return max(10, min(600, int(v)))
        except (ValueError, TypeError):
            return 60

    def set_alarm_alert_duration_sec(self, value: int) -> None:
        self._data["alarm_alert_duration_sec"] = max(10, min(600, int(value)))
        self._save()
        self.changed.emit()

    # ------------------------------------------------------------------ #
    # 外观主题
    # ------------------------------------------------------------------ #

    @property
    def theme(self) -> str:
        """界面主题：'auto' | 'light' | 'dark'，默认 'auto'（跟随系统）"""
        v = self._data.get("theme", "auto")
        return v if v in ("auto", "light", "dark") else "auto"

    def set_theme(self, value: str) -> None:
        if value not in ("auto", "light", "dark"):
            value = "auto"
        self._data["theme"] = value
        self._save()
        self.changed.emit()

    # ------------------------------------------------------------------ #
    # 语言
    # ------------------------------------------------------------------ #

    @property
    def language(self) -> str:
        """界面语言：'zh-CN' | 'en-US'，默认 'zh-CN'。"""
        raw = self._data.get("language", "zh-CN")
        return I18nService.normalize_language(raw)

    def set_language(self, value: str) -> None:
        self._data["language"] = I18nService.normalize_language(value)
        self._save()
        self.changed.emit()

    # ------------------------------------------------------------------ #
    # 测试版水印可见性
    # ------------------------------------------------------------------ #

    @property
    def watermark_main_visible(self) -> bool:
        """主窗口水印是否显示（默认 True）"""
        return bool(self._data.get("watermark_main_visible", True))

    def set_watermark_main_visible(self, value: bool) -> None:
        self._data["watermark_main_visible"] = bool(value)
        self._save()
        self.changed.emit()

    @property
    def watermark_worldtime_visible(self) -> bool:
        """世界时间视图水印是否显示（默认 True）"""
        return bool(self._data.get("watermark_worldtime_visible", True))

    def set_watermark_worldtime_visible(self, value: bool) -> None:
        self._data["watermark_worldtime_visible"] = bool(value)
        self._save()
        self.changed.emit()

    # ------------------------------------------------------------------ #
    # 启动菜单
    # ------------------------------------------------------------------ #

    @property
    def show_boot_menu_next_start(self) -> bool:
        """下次启动时是否显示启动选项菜单（一次性，显示后自动重置为 False）"""
        return bool(self._data.get("show_boot_menu_next_start", False))

    def set_show_boot_menu_next_start(self, value: bool) -> None:
        self._data["show_boot_menu_next_start"] = bool(value)
        self._save()
        self.changed.emit()

    # ------------------------------------------------------------------ #
    # 全屏时钟格子大小
    # ------------------------------------------------------------------ #

    @property
    def widget_cell_size(self) -> int:
        """全屏时钟画布的单格像素尺寸：60~300，默认 120。"""
        from app.constants import WIDGET_CELL_SIZE as _DEFAULT
        v = self._data.get("widget_cell_size", _DEFAULT)
        try:
            return max(60, min(300, int(v)))
        except (ValueError, TypeError):
            return _DEFAULT

    def set_widget_cell_size(self, value: int) -> None:
        from app.constants import WIDGET_CELL_SIZE as _DEFAULT
        clamped = max(60, min(300, int(value)))
        if clamped == self.widget_cell_size:
            return
        self._data["widget_cell_size"] = clamped
        self._save()
        self.changed.emit()
        self.cell_size_changed.emit(clamped)

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #

    def _save(self) -> None:
        save_json(SETTINGS_CONFIG, self._data)

"""自习时间安排核心服务。"""
from __future__ import annotations

import json
from datetime import datetime, time as dtime, timedelta
from pathlib import Path
from typing import Any, Optional

from PySide6.QtCore import QObject, QTimer, Signal

from app.utils.fs import write_bytes_with_uac, write_text_with_uac
from app.utils.logger import logger

from .models import StudyGroup, StudyItem


class StudyScheduleService(QObject):
    groups_updated = Signal()
    current_group_changed = Signal(str)
    current_item_changed = Signal(str)
    settings_changed = Signal(str, object)
    target_zone_changed = Signal(str)
    volume_report_ready = Signal(object)

    _DEFAULT_SETTINGS: dict[str, Any] = {
        "auto_switch_by_weekday": True,
        "auto_switch_by_time": True,
        "auto_apply_preset": True,
        "check_interval_sec": 30,
        "target_zone_id": "",
        "volume_report_enabled": False,
        "volume_report_auto_close_sec": 10,
        "volume_report_auto_save": False,
        "volume_report_threshold_db": -20,
        "volume_report_dedup_sec": 1.5,
        "volume_report_sample_sec": 0.2,
        "volume_report_calibration_db": 0,
    }

    def __init__(self, data_dir: Path, api, preset_service=None, world_zone_service=None, clock_service=None, parent=None):
        super().__init__(parent)
        self._data_dir = data_dir
        self._api = api
        self._preset_service = preset_service
        self._world_zone_service = world_zone_service
        self._clock_service = clock_service
        self._groups: list[StudyGroup] = []
        self._settings: dict[str, Any] = dict(self._DEFAULT_SETTINGS)
        self._current_group_id: str = ""
        self._current_item_id: str = ""
        self._last_zone_id: str = ""
        self._volume_api = None
        self._volume_session_handle = None
        self._current_item_started_at: Optional[datetime] = None
        self._load()
        logger.info(
            "StudyScheduleService 初始化: groups={}, current_group_id={}, current_item_id={}",
            len(self._groups),
            self._current_group_id,
            self._current_item_id,
        )

        if self._preset_service is not None and hasattr(self._preset_service, "presets_updated"):
            self._preset_service.presets_updated.connect(self._cleanup_missing_presets)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_runtime_state)
        self._apply_timer_interval()
        self._refresh_runtime_state()
        if self._clock_service is not None and hasattr(self._clock_service, "secondTick"):
            try:
                self._clock_service.secondTick.connect(self._refresh_runtime_state)
            except Exception:
                logger.exception("绑定 clock_service secondTick 失败")

    # ------------------------------------------------------------------ #
    # 音量联动
    # ------------------------------------------------------------------ #

    def attach_volume_api(self, api) -> None:
        """注入音量检测插件导出的接口。"""
        if api is self._volume_api:
            return
        self._volume_api = api
        logger.info("音量检测接口状态更新: available={}", bool(api))
        self._sync_volume_session(
            self._now(),
            dispatch_report=True,
            reason="api_binding_changed",
            refresh_binding=False,
        )

    def _refresh_volume_api_binding(self) -> None:
        """同步当前运行时可用的音量检测 API，处理插件重载/启停场景。"""
        resolver = getattr(self._api, "get_plugin", None)
        if not callable(resolver):
            return

        runtime_api = None
        try:
            runtime_api = resolver("volume_detector")
        except Exception:
            logger.exception("读取音量检测插件接口失败")
            runtime_api = None

        if runtime_api is self._volume_api:
            return

        self._volume_api = runtime_api
        logger.info("音量检测接口状态更新: available={}", bool(runtime_api))

    def _sync_volume_session(
        self,
        now_dt: datetime,
        *,
        dispatch_report: bool,
        reason: str,
        refresh_binding: bool = True,
    ) -> None:
        """确保音量会话与当前事项和插件可用性保持一致。"""
        if refresh_binding:
            self._refresh_volume_api_binding()

        enabled = bool(self.get_setting("volume_report_enabled", False))
        has_item = bool(self._current_item_id)
        item_active = self._is_item_in_time_range(
            self._current_group_id,
            self._current_item_id,
            now_dt,
        ) if has_item else False
        can_record = enabled and has_item and item_active and self._volume_api is not None

        if can_record:
            if self._volume_session_handle is None:
                self._start_volume_session(self._current_group_id, self._current_item_id, now_dt)
            return

        if self._volume_session_handle is None:
            return

        if not enabled:
            stop_reason = reason
        elif not has_item:
            stop_reason = "no_current_item"
        elif not item_active:
            stop_reason = "item_time_ended"
        elif self._volume_api is None:
            stop_reason = "volume_api_unavailable"
        else:
            stop_reason = reason

        logger.info(
            "音量会话停止检查触发: reason={}, enabled={}, has_item={}, item_active={}, api_available={}",
            stop_reason,
            enabled,
            has_item,
            item_active,
            self._volume_api is not None,
        )

        report = self._stop_volume_session(
            self._current_group_id,
            self._current_item_id,
            now_dt,
            reason=stop_reason,
        )
        if report and dispatch_report:
            self._dispatch_volume_report(report)

    def _volume_link_enabled(self) -> bool:
        return self._volume_api is not None and bool(self.get_setting("volume_report_enabled", False))

    def _is_item_in_time_range(self, group_id: str, item_id: str, now_dt: datetime) -> bool:
        if not group_id or not item_id:
            return False
        item = self.get_item(group_id, item_id)
        if item is None or not item.enabled:
            return False
        start_dt, end_dt = self._item_range(item, now_dt)
        if start_dt is None or end_dt is None:
            return False
        return start_dt <= now_dt <= end_dt

    @staticmethod
    def _clamped_int(value: Any, default: int, *, min_value: Optional[int] = None, max_value: Optional[int] = None) -> int:
        try:
            result = int(value)
        except (TypeError, ValueError):
            result = default
        if min_value is not None:
            result = max(min_value, result)
        if max_value is not None:
            result = min(max_value, result)
        return result

    @staticmethod
    def _clamped_float(value: Any, default: float, *, min_value: float, max_value: float) -> float:
        try:
            result = float(value)
        except (TypeError, ValueError):
            result = default
        return max(min_value, min(max_value, result))

    @staticmethod
    def _slug_text(text: str) -> str:
        cleaned = "".join(ch if ch.isalnum() else "-" for ch in str(text or ""))
        return cleaned.strip("-") or "session"

    # ------------------------------------------------------------------ #
    # 时间工具
    # ------------------------------------------------------------------ #

    def now(self) -> datetime:
        """获取校正后的当前时间（公开 API，供 widgets 使用）。

        返回的时间已经过 NTP 校正和手动时间偏移校正。
        """
        return self._api.get_corrected_time()

    def _now(self) -> datetime:
        """获取校正后的当前时间（内部使用）。"""
        return self._api.get_corrected_time()

    # ------------------------------------------------------------------ #
    # 持久化
    # ------------------------------------------------------------------ #

    def _data_path(self) -> Path:
        return self._data_dir / "study_schedule.json"

    @staticmethod
    def _legacy_data_path() -> Path:
        return Path(__file__).resolve().parent / "study_schedule.json"

    @staticmethod
    def _legacy_report_dir() -> Path:
        return Path(__file__).resolve().parent / "volume_reports"

    def _try_migrate_legacy_data(self, target_path: Path) -> None:
        if not target_path.exists():
            legacy_path = self._legacy_data_path()
            if legacy_path.exists() and legacy_path.is_file():
                try:
                    write_text_with_uac(
                        target_path,
                        legacy_path.read_text(encoding="utf-8"),
                        encoding="utf-8",
                        ensure_parent=True,
                    )
                    logger.info("[自习安排] 已迁移旧版数据文件：{} -> {}", legacy_path, target_path)
                except Exception:
                    logger.exception("[自习安排] 迁移旧版数据文件失败：{} -> {}", legacy_path, target_path)

        new_report_dir = self._data_dir / "volume_reports"
        legacy_report_dir = self._legacy_report_dir()
        if new_report_dir.exists() or not legacy_report_dir.exists() or not legacy_report_dir.is_dir():
            return

        copied = 0
        for legacy_file in legacy_report_dir.rglob("*"):
            if not legacy_file.is_file():
                continue
            try:
                rel = legacy_file.relative_to(legacy_report_dir)
                write_bytes_with_uac(
                    new_report_dir / rel,
                    legacy_file.read_bytes(),
                    ensure_parent=True,
                )
                copied += 1
            except Exception:
                logger.exception("[自习安排] 迁移音量报告文件失败：{}", legacy_file)

        if copied:
            logger.info("[自习安排] 已迁移旧版音量报告 {} 个文件到 {}", copied, new_report_dir)

    def _load(self) -> None:
        path = self._data_path()
        self._try_migrate_legacy_data(path)
        if not path.exists():
            logger.info("自习配置不存在，使用默认配置: {}", path)
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("读取自习配置失败，已回退默认配置: {}", path)
            self._groups = []
            self._settings = dict(self._DEFAULT_SETTINGS)
            self._current_group_id = ""
            self._current_item_id = ""
            self._last_zone_id = ""
            return

        self._groups = [StudyGroup.from_dict(item) for item in raw.get("groups", []) if isinstance(item, dict)]
        settings = dict(self._DEFAULT_SETTINGS)
        if isinstance(raw.get("settings"), dict):
            settings.update(raw["settings"])
        self._settings = settings
        self._current_group_id = str(raw.get("current_group_id", "") or "")
        self._current_item_id = str(raw.get("current_item_id", "") or "")
        self._last_zone_id = str(raw.get("last_zone_id", "") or "")
        logger.debug(
            "自习配置已加载: path={}, groups={}, current_group_id={}, current_item_id={}",
            path,
            len(self._groups),
            self._current_group_id,
            self._current_item_id,
        )

    def _save(self) -> None:
        path = self._data_path()
        write_text_with_uac(
            path,
            json.dumps(
                {
                    "groups": [group.to_dict() for group in self._groups],
                    "settings": self._settings,
                    "current_group_id": self._current_group_id,
                    "current_item_id": self._current_item_id,
                    "last_zone_id": self._last_zone_id,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
            ensure_parent=True,
        )
        logger.debug(
            "自习配置已保存: path={}, groups={}, current_group_id={}, current_item_id={}, last_zone_id={}",
            path,
            len(self._groups),
            self._current_group_id,
            self._current_item_id,
            self._last_zone_id,
        )

    # ------------------------------------------------------------------ #
    # 预设与画布
    # ------------------------------------------------------------------ #

    def available_presets(self):
        if self._preset_service is None or not hasattr(self._preset_service, "presets"):
            return []
        try:
            return list(self._preset_service.presets())
        except Exception:
            logger.exception("读取预设列表失败")
            return []

    def get_preset(self, preset_id: str):
        if self._preset_service is None or not hasattr(self._preset_service, "get_preset"):
            return None
        try:
            return self._preset_service.get_preset(preset_id)
        except Exception:
            logger.exception("读取预设失败: preset_id={}", preset_id)
            return None

    def has_preset(self, preset_id: str) -> bool:
        if not preset_id:
            return False
        if self._preset_service is None:
            return False
        if hasattr(self._preset_service, "has_preset"):
            try:
                return bool(self._preset_service.has_preset(preset_id))
            except Exception:
                logger.exception("检查预设存在性失败: preset_id={}", preset_id)
                return False
        return self.get_preset(preset_id) is not None

    def list_zones(self) -> list[dict[str, Any]]:
        service = self._world_zone_service
        if service is None:
            return []
        if hasattr(service, "list_zone_options"):
            try:
                return list(service.list_zone_options())
            except Exception:
                logger.exception("读取世界时区选项失败")
                return []
        return []

    def get_zone_display_name(self, zone_id: str, fallback: str = "") -> str:
        service = self._world_zone_service
        if service is not None and hasattr(service, "get_zone_display_name"):
            try:
                return str(service.get_zone_display_name(zone_id, fallback=fallback) or fallback or zone_id)
            except Exception:
                logger.exception("读取时区展示名失败: zone_id={}", zone_id)
                pass
        for zone in self.list_zones():
            if zone.get("id") == zone_id:
                return str(zone.get("display_name") or zone.get("label") or zone.get("timezone") or fallback or zone_id)
        return fallback or zone_id

    def target_zone_id(self) -> str:
        return str(self._settings.get("target_zone_id", "") or "")

    def effective_zone_id(self) -> str:
        zone_ids = {str(zone.get("id") or "") for zone in self.list_zones()}
        selected = self.target_zone_id() or self._last_zone_id
        if selected and (not zone_ids or selected in zone_ids):
            return selected
        return next(iter(zone_ids), "")

    def set_target_zone(self, zone_id: str) -> None:
        zone_id = str(zone_id or "")
        zone_ids = {str(zone.get("id") or "") for zone in self.list_zones()}
        if zone_id and zone_ids and zone_id not in zone_ids:
            logger.warning("目标画布不存在，已回退为空: zone_id={}", zone_id)
            zone_id = ""
        if zone_id == self.target_zone_id():
            return
        previous = self.target_zone_id()
        self._settings["target_zone_id"] = zone_id
        self._save()
        logger.info("自习目标画布已更新: {} -> {}", previous, zone_id)
        self.target_zone_changed.emit(self.effective_zone_id())

    def set_last_zone(self, zone_id: str) -> None:
        zone_id = str(zone_id or "")
        if zone_id == self._last_zone_id:
            return
        previous = self._last_zone_id
        self._last_zone_id = zone_id
        self._save()
        logger.debug("自习最近画布已更新: {} -> {}", previous, zone_id)
        if not self.target_zone_id():
            self.target_zone_changed.emit(self.effective_zone_id())

    def _apply_effective_preset(self, *, force: bool = False) -> None:
        if self._preset_service is None:
            return
        if not force and not bool(self.get_setting("auto_apply_preset", True)):
            return
        zone_id = self.effective_zone_id()
        if not zone_id:
            return
        preset_id = self.resolve_preset_id(self._current_group_id, self._current_item_id)
        if preset_id:
            logger.info(
                "应用自习预设: preset_id={}, zone_id={}, group_id={}, item_id={}, force={}",
                preset_id,
                zone_id,
                self._current_group_id,
                self._current_item_id,
                force,
            )
            self._preset_service.apply_preset(preset_id, zone_id)
        elif hasattr(self._preset_service, "clear_active_preset"):
            logger.info("清除自习画布激活预设: zone_id={}", zone_id)
            self._preset_service.clear_active_preset(zone_id)

    def _cleanup_missing_presets(self) -> None:
        changed = False
        cleared_count = 0
        for group in self._groups:
            if group.preset_id and not self.has_preset(group.preset_id):
                group.preset_id = ""
                changed = True
                cleared_count += 1
            for item in group.items:
                if item.preset_id and not self.has_preset(item.preset_id):
                    item.preset_id = ""
                    changed = True
                    cleared_count += 1
        if changed:
            self._save()
            logger.info("已清理失效自习预设引用: count={}", cleared_count)
            self.groups_updated.emit()

    def resolve_preset_id(self, group_id: str, item_id: str = "") -> str:
        item = self.get_item(group_id, item_id) if item_id else None
        if item and item.preset_id and self.has_preset(item.preset_id):
            return item.preset_id
        group = self.get_group(group_id)
        if group and group.preset_id and self.has_preset(group.preset_id):
            return group.preset_id
        return ""

    # ------------------------------------------------------------------ #
    # 分组与事项管理
    # ------------------------------------------------------------------ #

    def groups(self) -> list[StudyGroup]:
        return list(self._groups)

    def get_group(self, group_id: str) -> Optional[StudyGroup]:
        for group in self._groups:
            if group.id == group_id:
                return group
        return None

    def save_group(self, group: StudyGroup) -> None:
        action = "update"
        for index, current in enumerate(self._groups):
            if current.id == group.id:
                self._groups[index] = group
                break
        else:
            action = "create"
            self._groups.append(group)
        self._save()
        logger.info("自习分组已保存: action={}, group_id={}, name={}", action, group.id, group.name)
        self.groups_updated.emit()
        if not self._current_group_id:
            self.set_current_group(group.id, apply_preset=False)
        else:
            self._refresh_runtime_state(dispatch_report=False, switch_reason="schedule_edit")

    def delete_group(self, group_id: str) -> None:
        before_count = len(self._groups)
        self._groups = [group for group in self._groups if group.id != group_id]
        if self._current_group_id == group_id:
            self._update_current_group_id("")
            self._update_current_item_id("", dispatch_report=False, switch_reason="schedule_edit")
        self._save()
        logger.info("自习分组已删除: group_id={}, removed={}", group_id, before_count - len(self._groups))
        self.groups_updated.emit()
        self._refresh_runtime_state(dispatch_report=False, switch_reason="schedule_edit")

    def items(self, group_id: str) -> list[StudyItem]:
        group = self.get_group(group_id)
        return list(group.items) if group else []

    def get_item(self, group_id: str, item_id: str) -> Optional[StudyItem]:
        group = self.get_group(group_id)
        if group is None:
            return None
        for item in group.items:
            if item.id == item_id:
                return item
        return None

    def _sort_items(self, items: list[StudyItem]) -> list[StudyItem]:
        return sorted(items, key=lambda item: (item.start_time or "99:99", item.end_time or "99:99", item.name))

    def save_item(self, group_id: str, item: StudyItem) -> None:
        group = self.get_group(group_id)
        if group is None:
            logger.warning("保存自习事项失败，分组不存在: group_id={}, item_id={}", group_id, item.id)
            return
        action = "update"
        for index, current in enumerate(group.items):
            if current.id == item.id:
                group.items[index] = item
                break
        else:
            action = "create"
            group.items.append(item)
        group.items = self._sort_items(group.items)
        self._save()
        logger.info(
            "自习事项已保存: action={}, group_id={}, item_id={}, name={}",
            action,
            group_id,
            item.id,
            item.name,
        )
        self.groups_updated.emit()
        self._refresh_runtime_state(dispatch_report=False, switch_reason="schedule_edit")

    def delete_item(self, group_id: str, item_id: str) -> None:
        group = self.get_group(group_id)
        if group is None:
            logger.warning("删除自习事项失败，分组不存在: group_id={}, item_id={}", group_id, item_id)
            return
        before_count = len(group.items)
        group.items = [item for item in group.items if item.id != item_id]
        if self._current_group_id == group_id and self._current_item_id == item_id:
            self._update_current_item_id("", dispatch_report=False, switch_reason="schedule_edit")
        self._save()
        logger.info(
            "自习事项已删除: group_id={}, item_id={}, removed={}",
            group_id,
            item_id,
            before_count - len(group.items),
        )
        self.groups_updated.emit()
        self._refresh_runtime_state(dispatch_report=False, switch_reason="schedule_edit")

    # ------------------------------------------------------------------ #
    # 当前状态
    # ------------------------------------------------------------------ #

    def get_current_group(self) -> Optional[StudyGroup]:
        return self.get_group(self._current_group_id)

    def get_current_item(self) -> Optional[StudyItem]:
        if not self._current_group_id or not self._current_item_id:
            return None
        return self.get_item(self._current_group_id, self._current_item_id)

    def get_runtime_group(self, now_dt: Optional[datetime] = None) -> Optional[StudyGroup]:
        """按当前日期/设置解析此刻应展示的事项组。"""
        now_dt = now_dt or self._now()
        return self._resolve_group_for_now(now_dt)

    def get_runtime_item(
        self,
        now_dt: Optional[datetime] = None,
        group: Optional[StudyGroup] = None,
    ) -> Optional[StudyItem]:
        """按当前时间解析此刻正在进行的事项。"""
        now_dt = now_dt or self._now()
        group = group or self.get_runtime_group(now_dt)
        return self._resolve_current_item_for_group(group, now_dt)

    @property
    def current_group_id(self) -> str:
        return self._current_group_id

    @property
    def current_item_id(self) -> str:
        return self._current_item_id

    def _update_current_group_id(self, group_id: str) -> None:
        group_id = str(group_id or "")
        if group_id == self._current_group_id:
            return
        previous = self._current_group_id
        self._current_group_id = group_id
        logger.debug("当前自习分组已切换: {} -> {}", previous, group_id)
        self.current_group_changed.emit(group_id)

    def _update_current_item_id(
        self,
        item_id: str,
        *,
        now_dt: Optional[datetime] = None,
        prev_group_id: Optional[str] = None,
        dispatch_report: bool = True,
        switch_reason: str = "item_switch",
    ) -> None:
        now_dt = now_dt or self._now()
        item_id = str(item_id or "")
        if item_id == self._current_item_id:
            return
        previous = self._current_item_id
        effective_prev_group = prev_group_id or self._current_group_id
        self._handle_volume_item_switch(
            effective_prev_group,
            self._current_item_id,
            item_id,
            now_dt,
            dispatch_report=dispatch_report,
            reason=switch_reason,
        )
        self._current_item_id = item_id
        logger.debug(
            "当前自习事项已切换: {} -> {}, group_id={}, reason={}",
            previous,
            item_id,
            self._current_group_id,
            switch_reason,
        )
        self.current_item_changed.emit(item_id)

    def _volume_options(self) -> dict[str, Any]:
        return {
            "threshold": self._clamped_int(
                self.get_setting("volume_report_threshold_db", -20),
                -20,
                min_value=-80,
                max_value=0,
            ),
            "dedup": self._clamped_float(
                self.get_setting("volume_report_dedup_sec", 1.5),
                1.5,
                min_value=0.1,
                max_value=30.0,
            ),
            "sample": self._clamped_float(
                self.get_setting("volume_report_sample_sec", 0.2),
                0.2,
                min_value=0.05,
                max_value=2.0,
            ),
            "calibration": self._clamped_int(
                self.get_setting("volume_report_calibration_db", 0),
                0,
                min_value=-40,
                max_value=40,
            ),
        }

    def _handle_volume_item_switch(
        self,
        prev_group_id: str,
        prev_item_id: str,
        new_item_id: str,
        now_dt: datetime,
        *,
        dispatch_report: bool = True,
        reason: str = "item_switch",
    ) -> None:
        if self._volume_session_handle is not None:
            report = self._stop_volume_session(prev_group_id, prev_item_id, now_dt, reason=reason)
            if report and dispatch_report:
                self._dispatch_volume_report(report)

        if self._volume_link_enabled() and new_item_id:
            self._start_volume_session(self._current_group_id or prev_group_id, new_item_id, now_dt)
        else:
            self._volume_session_handle = None
            self._current_item_started_at = None

    def _start_volume_session(self, group_id: str, item_id: str, now_dt: datetime) -> None:
        if self._volume_api is None:
            return
        opts = self._volume_options()
        try:
            handle = self._volume_api.start_session(
                threshold_db=opts["threshold"],
                dedup_interval_sec=opts["dedup"],
                sample_interval_sec=opts["sample"],
                calibration_db=opts["calibration"],
                metadata={
                    "source": "study_schedule",
                    "group_id": group_id,
                    "item_id": item_id,
                },
            )
            self._volume_session_handle = handle
            self._current_item_started_at = now_dt
            logger.info(
                "音量会话已启动: group_id={}, item_id={}, threshold={}, sample={}, dedup={}",
                group_id,
                item_id,
                opts["threshold"],
                opts["sample"],
                opts["dedup"],
            )
        except Exception:
            logger.exception("启动音量监测失败")
            self._volume_session_handle = None
            self._current_item_started_at = None

    def _stop_volume_session(
        self,
        prev_group_id: str,
        prev_item_id: str,
        now_dt: datetime,
        *,
        reason: str = "",
    ) -> Optional[dict]:
        handle = self._volume_session_handle
        self._volume_session_handle = None
        started_at_dt = self._current_item_started_at
        self._current_item_started_at = None

        if handle is None:
            return None
        try:
            report = handle.stop() or {}
        except Exception:
            logger.exception("停止音量监测失败")
            return None

        group = self.get_group(prev_group_id)
        item = self.get_item(prev_group_id, prev_item_id) if prev_group_id and prev_item_id else None
        report.update(
            {
                "group_id": prev_group_id,
                "group_name": group.name if group else "",
                "item_id": prev_item_id,
                "item_name": item.name if item else "",
                "study_started_at": started_at_dt.isoformat(timespec="seconds") if isinstance(started_at_dt, datetime) else report.get("started_at", ""),
                "study_ended_at": now_dt.isoformat(timespec="seconds"),
                "end_reason": reason,
            }
        )
        return report

    def _dispatch_volume_report(self, report: dict) -> None:
        if not report:
            return
        saved_path = None
        if bool(self.get_setting("volume_report_auto_save", False)):
            try:
                saved_path = self._save_volume_report(report)
                report["saved_path"] = str(saved_path)
            except Exception:
                logger.exception("保存音量报告失败")
        logger.info(
            "音量报告已生成: group_id={}, item_id={}, saved_path={}",
            report.get("group_id", ""),
            report.get("item_id", ""),
            report.get("saved_path", saved_path) or "",
        )
        self.volume_report_ready.emit(report)

    def _save_volume_report(self, report: dict) -> Path:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        slug = self._slug_text(report.get("item_name") or report.get("item_id") or "session")
        path = self._data_dir / "volume_reports" / f"{ts}-{slug}.json"
        write_text_with_uac(
            path,
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
            ensure_parent=True,
        )
        return path

    def set_current_group(self, group_id: str, *, apply_preset: bool = True) -> None:
        now_dt = self._now()
        prev_group_id = self._current_group_id
        group = self.get_group(group_id)
        normalized = group.id if group else ""
        logger.info(
            "手动设置当前分组: request_group_id={}, normalized_group_id={}, apply_preset={}",
            group_id,
            normalized,
            apply_preset,
        )
        self._update_current_group_id(normalized)
        if group is None:
            self._update_current_item_id("", now_dt=now_dt, prev_group_id=prev_group_id)
            self._save()
            if apply_preset:
                self._apply_effective_preset(force=True)
            return

        if self.get_setting("auto_switch_by_time", True):
            item = self._resolve_current_item_for_group(group, now_dt)
            self._update_current_item_id(item.id if item else "", now_dt=now_dt, prev_group_id=prev_group_id)
        elif self.get_item(normalized, self._current_item_id) is None:
            self._update_current_item_id("", now_dt=now_dt, prev_group_id=prev_group_id)

        self._save()
        if apply_preset:
            self._apply_effective_preset(force=True)

    def set_current_item(self, item_id: str, *, apply_preset: bool = True) -> None:
        now_dt = self._now()
        group = self.get_current_group()
        if group is None:
            logger.warning("手动设置当前事项失败，当前分组为空: item_id={}", item_id)
            return
        item = self.get_item(group.id, item_id)
        logger.info(
            "手动设置当前事项: group_id={}, request_item_id={}, normalized_item_id={}, apply_preset={}",
            group.id,
            item_id,
            item.id if item else "",
            apply_preset,
        )
        self._update_current_item_id(item.id if item else "", now_dt=now_dt, prev_group_id=group.id)
        self._save()
        if apply_preset:
            self._apply_effective_preset(force=True)

    # ------------------------------------------------------------------ #
    # 设置
    # ------------------------------------------------------------------ #

    def get_setting(self, key: str, default: Any = None) -> Any:
        return self._settings.get(key, default)

    def set_setting(self, key: str, value: Any) -> None:
        previous = self._settings.get(key)
        if previous == value:
            return
        self._settings[key] = value
        if key == "check_interval_sec":
            self._apply_timer_interval()
        self._save()
        logger.info("自习设置已更新: key={}, old={}, new={}", key, previous, value)
        self.settings_changed.emit(key, value)
        if key in {"auto_switch_by_weekday", "auto_switch_by_time", "auto_apply_preset"}:
            self._refresh_runtime_state(dispatch_report=False, switch_reason="settings_change")
        if key == "volume_report_enabled":
            now_dt = self._now()
            self._sync_volume_session(
                now_dt,
                dispatch_report=True,
                reason="volume_setting_changed",
                refresh_binding=True,
            )
            if bool(value) and self._volume_api is None:
                try:
                    self._api.show_toast("音量报告不可用", "需要先安装并启用音量检测插件", level="warning")
                except Exception:
                    pass

    def _apply_timer_interval(self) -> None:
        interval_sec = self.get_setting("check_interval_sec", 30)
        try:
            interval_sec = max(5, min(300, int(interval_sec)))
        except (TypeError, ValueError):
            interval_sec = 30
        self._settings["check_interval_sec"] = interval_sec
        self._timer.setInterval(interval_sec * 1000)
        logger.debug("自习定时检查间隔已更新: interval_sec={}", interval_sec)

    # ------------------------------------------------------------------ #
    # 时间计算
    # ------------------------------------------------------------------ #

    @staticmethod
    def _parse_time(value: str) -> Optional[dtime]:
        try:
            return dtime.fromisoformat(value)
        except ValueError:
            return None

    def _item_range(self, item: StudyItem, now_dt: datetime) -> tuple[Optional[datetime], Optional[datetime]]:
        start_t = self._parse_time(item.start_time)
        end_t = self._parse_time(item.end_time)
        if start_t is None or end_t is None:
            return None, None
        tz = now_dt.tzinfo
        start_dt = datetime.combine(now_dt.date(), start_t).replace(tzinfo=tz)
        end_dt = datetime.combine(now_dt.date(), end_t).replace(tzinfo=tz)
        if end_dt <= start_dt:
            end_dt += timedelta(days=1)
            previous_start = start_dt - timedelta(days=1)
            previous_end = end_dt - timedelta(days=1)
            if previous_start <= now_dt <= previous_end:
                return previous_start, previous_end
        return start_dt, end_dt

    def _next_start_today(self, item: StudyItem, now_dt: datetime) -> Optional[datetime]:
        start_t = self._parse_time(item.start_time)
        if start_t is None:
            return None
        tz = now_dt.tzinfo
        start_dt = datetime.combine(now_dt.date(), start_t).replace(tzinfo=tz)
        if start_dt < now_dt:
            return None
        return start_dt

    def _resolve_group_for_now(self, now_dt: datetime) -> Optional[StudyGroup]:
        if not self._groups:
            return None
        if not bool(self.get_setting("auto_switch_by_weekday", True)):
            return self.get_current_group() or self._groups[0]

        today = now_dt.weekday()
        current = self.get_current_group()
        weekday_groups = [group for group in self._groups if today in group.weekdays]
        if current and current in weekday_groups:
            return current
        if weekday_groups:
            return weekday_groups[0]
        if current and not current.weekdays:
            return current
        fallback_groups = [group for group in self._groups if not group.weekdays]
        if fallback_groups:
            return fallback_groups[0]
        return current or self._groups[0]

    def _resolve_current_item_for_group(self, group: Optional[StudyGroup], now_dt: datetime) -> Optional[StudyItem]:
        if group is None:
            return None
        candidates: list[tuple[datetime, StudyItem]] = []
        for item in group.items:
            if not item.enabled:
                continue
            start_dt, end_dt = self._item_range(item, now_dt)
            if start_dt is None or end_dt is None:
                continue
            if start_dt <= now_dt <= end_dt:
                candidates.append((start_dt, item))
        if not candidates:
            return None
        candidates.sort(key=lambda entry: entry[0])
        return candidates[0][1]

    def get_next_item(self, now_dt: Optional[datetime] = None) -> tuple[Optional[StudyGroup], Optional[StudyItem]]:
        now_dt = now_dt or self._now()
        group = self.get_runtime_group(now_dt) or self.get_current_group()
        if group is None:
            return None, None
        candidates: list[tuple[datetime, StudyItem]] = []
        for item in group.items:
            if not item.enabled:
                continue
            start_dt = self._next_start_today(item, now_dt)
            if start_dt is not None:
                candidates.append((start_dt, item))
        if not candidates:
            return group, None
        candidates.sort(key=lambda entry: entry[0])
        return group, candidates[0][1]

    # ------------------------------------------------------------------ #
    # 运行期刷新
    # ------------------------------------------------------------------ #

    def _refresh_runtime_state(
        self,
        *,
        dispatch_report: bool = True,
        switch_reason: str = "time_point",
    ) -> None:
        now_dt = self._now()
        changed = False

        prev_group_id = self._current_group_id

        target_group = self._resolve_group_for_now(now_dt)
        target_group_id = target_group.id if target_group else ""
        if target_group_id != self._current_group_id:
            self._update_current_group_id(target_group_id)
            changed = True

        if bool(self.get_setting("auto_switch_by_time", True)):
            target_item = self._resolve_current_item_for_group(target_group, now_dt)
            target_item_id = target_item.id if target_item else ""
            if target_item_id != self._current_item_id:
                self._update_current_item_id(
                    target_item_id,
                    now_dt=now_dt,
                    prev_group_id=prev_group_id,
                    dispatch_report=dispatch_report,
                    switch_reason=switch_reason,
                )
                changed = True
        elif self._current_group_id and self.get_item(self._current_group_id, self._current_item_id) is None:
            self._update_current_item_id(
                "",
                now_dt=now_dt,
                prev_group_id=prev_group_id,
                dispatch_report=dispatch_report,
                switch_reason=switch_reason,
            )
            changed = True

        self._sync_volume_session(
            now_dt,
            dispatch_report=dispatch_report,
            reason=f"runtime_sync:{switch_reason}",
            refresh_binding=True,
        )

        if changed:
            self._save()
            self._apply_effective_preset(force=False)
            logger.info(
                "自习运行态已刷新: reason={}, group_id={}, item_id={}",
                switch_reason,
                self._current_group_id,
                self._current_item_id,
            )

    def shutdown(self) -> None:
        """在插件卸载时停止定时器并终止音量会话。"""
        try:
            self._timer.stop()
        except Exception:
            pass
        if self._volume_session_handle is not None:
            try:
                self._volume_session_handle.stop()
            except Exception:
                logger.exception("停止音量会话失败")
            self._volume_session_handle = None


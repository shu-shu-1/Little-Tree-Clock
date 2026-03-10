"""考试面板插件 — 核心服务

ExamService 是单例服务，负责：
- 维护科目列表、考试计划、科目-预设绑定
- 跟踪“当前科目”和每个 zone 的当前预设
- 定时检测考试时间段，自动切换科目/预设并触发提醒
- 提供信号供 UI 组件订阅刷新
"""
from __future__ import annotations

import json
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QObject, QTimer, Signal

from .models import ExamPlan, ExamSubject, LayoutPreset, SubjectPresetBinding


class ExamService(QObject):
    """考试状态管理服务（单例，由插件 ``on_load`` 创建）。

    Signals
    -------
    subject_changed(subject_id: str)
        当前科目切换时发出（空字符串表示清除科目）。
    subjects_updated()
        科目列表变更时发出。
    plan_updated()
        考试计划数据变更时发出。
    preset_updated()
        绑定关系、默认预设或共享预设目录变化时发出。
    settings_changed(key: str, value: object)
        插件设置项变更时发出。
    active_preset_changed(zone_id: str, preset_id: str)
        指定 zone 当前应用的预设变化时发出。
    reminder_triggered(subject_id, plan_id, reminder_id, message)
        考试提醒触发时发出。
    exam_phase_changed(phase: str)
        考试阶段变化时发出：
          "idle"  — 非考试时间
          "prep"  — 准备阶段（提前准备时间段内）
          "active"— 考试进行中
    """

    subject_changed = Signal(str)
    subjects_updated = Signal()
    plan_updated = Signal()
    preset_updated = Signal()
    settings_changed = Signal(str, object)
    active_preset_changed = Signal(str, str)
    reminder_triggered = Signal(str, str, str, str)
    exam_phase_changed = Signal(str)

    _EXAM_WIDGET_TYPES = {
        "exam_subject",
        "exam_time_period",
        "exam_answer_sheets",
        "exam_paper_pages",
    }

    _DEFAULT_SETTINGS: Dict[str, Any] = {
        "auto_switch_preset": True,
        "auto_reminder": True,
        "voice_enabled": True,
        "show_countdown": True,
        "show_subject_status_color": True,
        "check_interval_sec": 30,
    }

    def __init__(self, data_dir: Path, api, preset_service=None, parent=None):
        super().__init__(parent)
        self._data_dir = data_dir
        self._api = api
        self._preset_service = preset_service

        # 持久化数据
        self._subjects: List[ExamSubject] = []
        self._plans: List[ExamPlan] = []
        self._legacy_presets: List[LayoutPreset] = []
        self._bindings: List[SubjectPresetBinding] = []
        self._default_preset_id: str = ""

        # 运行时状态
        self._current_subject_id: str = ""
        self._current_zone_id: str = ""
        self._active_preset_ids: Dict[str, str] = {}
        self._fired_reminders: set[tuple[str, str]] = set()
        self._last_phase: str = "idle"
        self._last_reminder_day: date = date.today()

        # 设置
        self._settings: Dict[str, Any] = dict(self._DEFAULT_SETTINGS)

        self._load()

        if self._preset_service is not None:
            presets_updated = getattr(self._preset_service, "presets_updated", None)
            if hasattr(presets_updated, "connect"):
                presets_updated.connect(self._on_preset_catalog_changed)
            active_changed = getattr(self._preset_service, "active_preset_changed", None)
            if hasattr(active_changed, "connect"):
                active_changed.connect(self._on_shared_active_preset_changed)
            self._migrate_legacy_presets()
            self._on_preset_catalog_changed()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._check_exam_phase)
        self._apply_timer_interval()
        self._timer.start()
        self._check_exam_phase()

    # ------------------------------------------------------------------ #
    # 持久化
    # ------------------------------------------------------------------ #

    def _data_path(self) -> Path:
        return self._data_dir / "exam_data.json"

    def _load(self) -> None:
        path = self._data_path()
        if not path.exists():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            self._subjects = [ExamSubject.from_dict(d) for d in raw.get("subjects", [])]
            self._plans = [ExamPlan.from_dict(d) for d in raw.get("plans", [])]
            self._legacy_presets = [LayoutPreset.from_dict(d) for d in raw.get("presets", [])]
            self._bindings = [SubjectPresetBinding.from_dict(d) for d in raw.get("bindings", [])]
            self._default_preset_id = raw.get("default_preset_id", "")
            merged_settings = dict(self._DEFAULT_SETTINGS)
            saved_settings = raw.get("settings", {})
            if isinstance(saved_settings, dict):
                merged_settings.update(saved_settings)
            self._settings = merged_settings
            self._current_subject_id = raw.get("current_subject_id", "")
        except Exception:
            self._subjects = []
            self._plans = []
            self._legacy_presets = []
            self._bindings = []
            self._default_preset_id = ""
            self._settings = dict(self._DEFAULT_SETTINGS)
            self._current_subject_id = ""

    def _save(self) -> None:
        self._data_path().parent.mkdir(parents=True, exist_ok=True)
        data = {
            "subjects": [s.to_dict() for s in self._subjects],
            "plans": [p.to_dict() for p in self._plans],
            "bindings": [b.to_dict() for b in self._bindings],
            "default_preset_id": self._default_preset_id,
            "settings": self._settings,
            "current_subject_id": self._current_subject_id,
        }
        self._data_path().write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------ #
    # 科目管理
    # ------------------------------------------------------------------ #

    def subjects(self) -> List[ExamSubject]:
        return list(self._subjects)

    def get_subject(self, subject_id: str) -> Optional[ExamSubject]:
        for subject in self._subjects:
            if subject.id == subject_id:
                return subject
        return None

    def get_current_subject(self) -> Optional[ExamSubject]:
        return self.get_subject(self._current_subject_id)

    def set_current_subject(
        self,
        subject_id: str,
        zone_id: str = "",
        apply_preset: bool = True,
    ) -> None:
        """切换当前科目。"""
        self._current_subject_id = subject_id
        if zone_id:
            self._current_zone_id = zone_id
        self._save()
        self.subject_changed.emit(subject_id)

        target_zone = zone_id or self._current_zone_id
        if not target_zone:
            return
        if apply_preset:
            self._do_switch_preset_for_subject(subject_id, target_zone)
        else:
            self._push_subject_to_canvas(subject_id, target_zone)

    def save_subject(self, subject: ExamSubject) -> None:
        for index, current in enumerate(self._subjects):
            if current.id == subject.id:
                self._subjects[index] = subject
                self._save()
                self.subjects_updated.emit()
                self.plan_updated.emit()
                return
        self._subjects.append(subject)
        self._save()
        self.subjects_updated.emit()
        self.plan_updated.emit()

    def delete_subject(self, subject_id: str) -> None:
        self._subjects = [s for s in self._subjects if s.id != subject_id]
        self._bindings = [b for b in self._bindings if b.subject_id != subject_id]
        self._plans = [p for p in self._plans if p.subject_id != subject_id]
        if self._current_subject_id == subject_id:
            self._current_subject_id = ""
            self.subject_changed.emit("")
            if self._current_zone_id:
                self._push_subject_to_canvas("", self._current_zone_id)
        self._save()
        self.subjects_updated.emit()
        self.plan_updated.emit()
        self.preset_updated.emit()

    # ------------------------------------------------------------------ #
    # 考试计划管理
    # ------------------------------------------------------------------ #

    def plans(self) -> List[ExamPlan]:
        return list(self._plans)

    def get_plan(self, plan_id: str) -> Optional[ExamPlan]:
        for plan in self._plans:
            if plan.id == plan_id:
                return plan
        return None

    def get_plan_for_subject(self, subject_id: str) -> Optional[ExamPlan]:
        for plan in self._plans:
            if plan.subject_id == subject_id:
                return plan
        return None

    def save_plan(self, plan: ExamPlan) -> None:
        for index, current in enumerate(self._plans):
            if current.id == plan.id:
                self._plans[index] = plan
                self._save()
                self.plan_updated.emit()
                return
        self._plans.append(plan)
        self._save()
        self.plan_updated.emit()

    def delete_plan(self, plan_id: str) -> None:
        self._plans = [plan for plan in self._plans if plan.id != plan_id]
        self._save()
        self.plan_updated.emit()

    # ------------------------------------------------------------------ #
    # 布局预设管理
    # ------------------------------------------------------------------ #

    def presets(self) -> List[LayoutPreset]:
        if self._preset_service is None or not hasattr(self._preset_service, "presets"):
            return []
        try:
            return list(self._preset_service.presets())
        except Exception:
            return []

    def get_preset(self, preset_id: str) -> Optional[LayoutPreset]:
        if not preset_id or self._preset_service is None or not hasattr(self._preset_service, "get_preset"):
            return None
        try:
            return self._preset_service.get_preset(preset_id)
        except Exception:
            return None

    def get_default_preset(self) -> Optional[LayoutPreset]:
        return self.get_preset(self._default_preset_id)

    def set_default_preset(self, preset_id: str) -> None:
        if preset_id and self.get_preset(preset_id) is None:
            preset_id = ""
        self._default_preset_id = preset_id
        self._save()
        self.preset_updated.emit()

    def save_preset(self, preset: LayoutPreset) -> None:
        if self._preset_service is None or not hasattr(self._preset_service, "save_preset"):
            return
        self._preset_service.save_preset(preset)

    def delete_preset(self, preset_id: str) -> None:
        if self._preset_service is None or not hasattr(self._preset_service, "delete_preset"):
            return
        self._preset_service.delete_preset(preset_id)

    # ------------------------------------------------------------------ #
    # 科目-预设绑定
    # ------------------------------------------------------------------ #

    def bindings(self) -> List[SubjectPresetBinding]:
        return list(self._bindings)

    def get_binding(self, subject_id: str, zone_id: str = "") -> Optional[SubjectPresetBinding]:
        """返回指定科目在指定 zone 的绑定（优先精确匹配，再回退全局绑定）。"""
        if zone_id:
            for binding in self._bindings:
                if binding.subject_id == subject_id and binding.zone_id == zone_id:
                    return binding
        for binding in self._bindings:
            if binding.subject_id == subject_id and binding.zone_id == "":
                return binding
        return None

    def set_binding(self, subject_id: str, preset_id: str, zone_id: str = "") -> None:
        if preset_id and self.get_preset(preset_id) is None:
            preset_id = ""
        for binding in self._bindings:
            if binding.subject_id == subject_id and binding.zone_id == zone_id:
                if preset_id:
                    binding.preset_id = preset_id
                else:
                    self._bindings = [
                        item for item in self._bindings
                        if not (item.subject_id == subject_id and item.zone_id == zone_id)
                    ]
                self._save()
                self.preset_updated.emit()
                return
        if preset_id:
            self._bindings.append(
                SubjectPresetBinding(subject_id=subject_id, preset_id=preset_id, zone_id=zone_id)
            )
            self._save()
            self.preset_updated.emit()

    # ------------------------------------------------------------------ #
    # 插件设置
    # ------------------------------------------------------------------ #

    def get_setting(self, key: str, default: Any = None) -> Any:
        return self._settings.get(key, default)

    def set_setting(self, key: str, value: Any) -> None:
        if self._settings.get(key) == value:
            return
        self._settings[key] = value
        if key == "check_interval_sec":
            self._apply_timer_interval()
        self._save()
        self.settings_changed.emit(key, value)
        if key == "auto_switch_preset" and value:
            self._check_exam_phase()

    def _apply_timer_interval(self) -> None:
        interval_sec = self.get_setting("check_interval_sec", 30)
        try:
            interval_sec = max(5, min(300, int(interval_sec)))
        except (TypeError, ValueError):
            interval_sec = 30
        self._settings["check_interval_sec"] = interval_sec
        self._timer.setInterval(interval_sec * 1000)

    # ------------------------------------------------------------------ #
    # 当前预设状态
    # ------------------------------------------------------------------ #

    def get_active_preset_id(self, zone_id: str) -> str:
        return self._active_preset_ids.get(zone_id, "")

    def get_current_preset_id(self, zone_id: str) -> str:
        active_id = self.get_active_preset_id(zone_id)
        if active_id:
            return active_id
        if self._current_subject_id:
            binding = self.get_binding(self._current_subject_id, zone_id)
            if binding and binding.preset_id:
                return binding.preset_id
        return self._default_preset_id

    def get_current_preset(self, zone_id: str) -> Optional[LayoutPreset]:
        preset_id = self.get_current_preset_id(zone_id)
        return self.get_preset(preset_id) if preset_id else None

    # ------------------------------------------------------------------ #
    # 预设切换逻辑
    # ------------------------------------------------------------------ #

    def apply_preset(self, preset_id: str, zone_id: str) -> bool:
        """将指定预设应用到指定 zone 的画布。返回是否成功。"""
        if self._preset_service is None or not hasattr(self._preset_service, "apply_preset"):
            return False
        try:
            return bool(self._preset_service.apply_preset(preset_id, zone_id))
        except Exception:
            return False

    def _do_switch_preset_for_subject(self, subject_id: str, zone_id: str) -> None:
        """切换科目时自动应用对应预设。"""
        preset_applied = False
        binding = self.get_binding(subject_id, zone_id)
        if binding and binding.preset_id:
            preset_applied = self.apply_preset(binding.preset_id, zone_id)
        elif self._default_preset_id:
            preset_applied = self.apply_preset(self._default_preset_id, zone_id)

        if not preset_applied and zone_id:
            if self._preset_service is not None and hasattr(self._preset_service, "clear_active_preset"):
                self._preset_service.clear_active_preset(zone_id)
            else:
                self._active_preset_ids.pop(zone_id, None)
                self.active_preset_changed.emit(zone_id, "")

        self._push_subject_to_canvas(subject_id, zone_id)

    def _migrate_legacy_presets(self) -> None:
        if not self._legacy_presets or self._preset_service is None or not hasattr(self._preset_service, "save_preset"):
            return
        for preset in self._legacy_presets:
            if self.get_preset(preset.id) is None:
                self._preset_service.save_preset(preset)
        self._legacy_presets = []

    def _on_preset_catalog_changed(self) -> None:
        changed = False
        valid_ids = {preset.id for preset in self.presets()}
        if self._default_preset_id and self._default_preset_id not in valid_ids:
            self._default_preset_id = ""
            changed = True

        filtered: list[SubjectPresetBinding] = []
        for binding in self._bindings:
            if binding.preset_id and binding.preset_id not in valid_ids:
                changed = True
                continue
            filtered.append(binding)
        if len(filtered) != len(self._bindings):
            self._bindings = filtered

        for zone_id, preset_id in list(self._active_preset_ids.items()):
            if preset_id and preset_id not in valid_ids:
                self._active_preset_ids.pop(zone_id, None)
                self.active_preset_changed.emit(zone_id, "")
                changed = True

        if changed:
            self._save()
        self.preset_updated.emit()

    def _on_shared_active_preset_changed(self, zone_id: str, preset_id: str) -> None:
        if preset_id:
            self._active_preset_ids[zone_id] = preset_id
        else:
            self._active_preset_ids.pop(zone_id, None)
        self.active_preset_changed.emit(zone_id, preset_id)

    def _push_subject_to_canvas(self, subject_id: str, zone_id: str) -> None:
        """将科目 ID 写入目标 zone 中的考试组件 props。"""
        if not zone_id:
            return
        try:
            configs = self._api.get_canvas_layout(zone_id)
            changed = False
            for cfg in configs:
                if cfg.get("widget_type") not in self._EXAM_WIDGET_TYPES:
                    continue
                props = cfg.setdefault("props", {})
                if props.get("subject_id", "") == subject_id:
                    continue
                props["subject_id"] = subject_id
                changed = True
            if changed:
                self._api.apply_canvas_layout(zone_id, configs)
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # 考试时间段检测与提醒
    # ------------------------------------------------------------------ #

    def _parse_time(self, value: str) -> Optional[dtime]:
        try:
            return dtime.fromisoformat(value)
        except ValueError:
            return None

    def _plan_range(self, plan: ExamPlan, now_dt: datetime) -> tuple[Optional[datetime], Optional[datetime]]:
        start_t = self._parse_time(plan.start_time)
        end_t = self._parse_time(plan.end_time)
        if start_t is None or end_t is None:
            return None, None
        start_dt = datetime.combine(now_dt.date(), start_t)
        end_dt = datetime.combine(now_dt.date(), end_t)
        if end_dt < start_dt:
            end_dt += timedelta(days=1)
        return start_dt, end_dt

    def get_plan_phase(self, plan: ExamPlan, now_dt: Optional[datetime] = None) -> str:
        now_dt = now_dt or datetime.now()
        start_dt, end_dt = self._plan_range(plan, now_dt)
        if start_dt is None or end_dt is None:
            return "idle"
        prep_start_dt = start_dt - timedelta(minutes=max(0, int(plan.prep_min)))
        if prep_start_dt <= now_dt < start_dt:
            return "prep"
        if start_dt <= now_dt <= end_dt:
            return "active"
        return "idle"

    def _select_scheduled_plan(self, now_dt: datetime) -> tuple[Optional[ExamPlan], str]:
        candidates: list[tuple[int, datetime, ExamPlan, str]] = []
        for plan in self._plans:
            phase = self.get_plan_phase(plan, now_dt)
            if phase == "idle":
                continue
            start_dt, _ = self._plan_range(plan, now_dt)
            if start_dt is None:
                continue
            priority = 0 if phase == "active" else 1
            candidates.append((priority, start_dt, plan, phase))
        if not candidates:
            return None, "idle"
        candidates.sort(key=lambda item: (item[0], item[1]))
        _priority, _start_dt, plan, phase = candidates[0]
        return plan, phase

    def _check_exam_phase(self) -> None:
        """定时检查考试阶段，并在需要时自动切换科目/预设与触发提醒。"""
        now_dt = datetime.now().replace(second=0, microsecond=0)
        if now_dt.date() != self._last_reminder_day:
            self._fired_reminders.clear()
            self._last_reminder_day = now_dt.date()

        auto_switch = bool(self.get_setting("auto_switch_preset", True))
        selected_plan: Optional[ExamPlan] = None
        selected_phase = "idle"
        did_switch_subject = False

        if auto_switch:
            selected_plan, selected_phase = self._select_scheduled_plan(now_dt)
            if selected_plan and selected_plan.subject_id != self._current_subject_id:
                self.set_current_subject(
                    selected_plan.subject_id,
                    self._current_zone_id,
                    apply_preset=True,
                )
                did_switch_subject = True
        elif self._current_subject_id:
            selected_plan = self.get_plan_for_subject(self._current_subject_id)
            if selected_plan is not None:
                selected_phase = self.get_plan_phase(selected_plan, now_dt)

        previous_phase = self._last_phase
        new_phase = selected_phase if selected_plan is not None else "idle"

        if (
            auto_switch
            and selected_plan is not None
            and selected_phase in ("prep", "active")
            and previous_phase == "idle"
            and self._current_zone_id
            and not did_switch_subject
        ):
            self._do_switch_preset_for_subject(selected_plan.subject_id, self._current_zone_id)

        if new_phase != previous_phase:
            self._last_phase = new_phase
            self.exam_phase_changed.emit(new_phase)
        elif selected_plan is None:
            self._last_phase = "idle"

        if selected_plan is not None and new_phase == "active":
            _start_dt, end_dt = self._plan_range(selected_plan, now_dt)
            if end_dt is not None:
                self._check_reminders(selected_plan, now_dt, end_dt)

    def _check_reminders(self, plan: ExamPlan, now_dt: datetime, end_dt: datetime) -> None:
        for reminder in plan.reminders:
            key = (plan.id, reminder.id)
            if key in self._fired_reminders:
                continue
            trigger_dt = end_dt - timedelta(minutes=reminder.minutes_before_end)
            if trigger_dt > now_dt or now_dt > end_dt:
                continue
            self._fired_reminders.add(key)
            subject = self.get_subject(plan.subject_id)
            subject_name = subject.name if subject else "考试"
            message = reminder.message or f"距离 {subject_name} 考试结束还有 {reminder.minutes_before_end} 分钟"
            self.reminder_triggered.emit(plan.subject_id, plan.id, reminder.id, message)

    # ------------------------------------------------------------------ #
    # 属性访问
    # ------------------------------------------------------------------ #

    @property
    def current_subject_id(self) -> str:
        return self._current_subject_id

    @property
    def current_zone_id(self) -> str:
        return self._current_zone_id

    def set_current_zone(self, zone_id: str) -> None:
        self._current_zone_id = zone_id

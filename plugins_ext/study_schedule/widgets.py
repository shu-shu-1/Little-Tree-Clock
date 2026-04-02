"""自习时间安排画布小组件。"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFormLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    CaptionLabel,
    CheckBox,
    ComboBox,
    ProgressBar,
    SpinBox,
    SubtitleLabel,
    TitleLabel,
)

from app.widgets.base_widget import WidgetBase, WidgetConfig
from app.widgets.fluent_font_picker import FluentFontPicker


_TEXT_PRIMARY = "background: transparent; color: rgba(255,255,255,235);"
_TEXT_SECONDARY = "background: transparent; color: rgba(255,255,255,170);"
_TEXT_MUTED = "background: transparent; color: rgba(255,255,255,120);"

_ALIGN_MAP = {
    "left": Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
    "center": Qt.AlignmentFlag.AlignCenter,
    "right": Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
}

_BLOCK_ALIGN_MAP = {
    "left": Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
    "center": Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
    "right": Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop,
}


def _get_service(services: dict):
    return services.get("study_service")


def _safe_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _font_size(props: dict, key: str, default: int) -> int:
    return max(8, min(144, _safe_int(props.get(key, default), default)))


def _remember_default_font(label) -> None:
    if getattr(label, "_ltc_default_font", None) is None:
        label._ltc_default_font = QFont(label.font())


def _apply_font(label, props: dict, size_key: str, default_size: int) -> None:
    base_font = getattr(label, "_ltc_default_font", None)
    font = QFont(base_font) if isinstance(base_font, QFont) else QFont(label.font())
    family = str(props.get("font_family", "") or "").strip()
    if family:
        font.setFamilies([family])
    font.setPointSize(_font_size(props, size_key, default_size))
    label.setFont(font)


def _build_align_combo(form: QFormLayout, props: dict) -> ComboBox:
    combo = ComboBox()
    for label, value in (("居中", "center"), ("左对齐", "left"), ("右对齐", "right")):
        combo.addItem(label, userData=value)
    current = str(props.get("align", "center") or "center")
    index = next((i for i in range(combo.count()) if combo.itemData(i) == current), 0)
    combo.setCurrentIndex(index)
    form.addRow("对齐方式:", combo)
    return combo


def _build_font_controls(
    form: QFormLayout,
    props: dict,
    *,
    main_key: str,
    main_default: int,
    sub_key: str,
    sub_default: int,
    main_label: str,
    sub_label: str,
):
    font_combo = FluentFontPicker()
    font_combo.setCurrentFontFamily(str(props.get("font_family", "") or "").strip())

    main_spin = SpinBox()
    main_spin.setRange(8, 144)
    main_spin.setSuffix(" pt")
    main_spin.setValue(_font_size(props, main_key, main_default))

    sub_spin = SpinBox()
    sub_spin.setRange(8, 144)
    sub_spin.setSuffix(" pt")
    sub_spin.setValue(_font_size(props, sub_key, sub_default))

    form.addRow("字体:", font_combo)
    form.addRow(main_label, main_spin)
    form.addRow(sub_label, sub_spin)
    return font_combo, main_spin, sub_spin


def _collect_font_props(font_combo, main_spin, sub_spin, *, main_key: str, sub_key: str) -> dict:
    return {
        "font_family": font_combo.currentFontFamily(),
        main_key: main_spin.value(),
        sub_key: sub_spin.value(),
    }


def _build_grid_controls(
    form: QFormLayout,
    props: dict,
    *,
    min_w: int,
    min_h: int,
    default_w: int,
    default_h: int,
):
    width_spin = SpinBox()
    width_spin.setRange(min_w, 20)
    width_spin.setValue(max(min_w, _safe_int(props.get("grid_w", default_w), default_w)))
    form.addRow("横向格数:", width_spin)

    height_spin = SpinBox()
    height_spin.setRange(min_h, 20)
    height_spin.setValue(max(min_h, _safe_int(props.get("grid_h", default_h), default_h)))
    form.addRow("纵向格数:", height_spin)
    return width_spin, height_spin


def _collect_grid_props(width_spin, height_spin) -> dict:
    return {
        "grid_w": width_spin.value(),
        "grid_h": height_spin.value(),
    }


def _apply_grid_size(widget: WidgetBase, props: dict) -> None:
    widget.config.grid_w = max(widget.MIN_W, _safe_int(props.get("grid_w", widget.DEFAULT_W), widget.DEFAULT_W))
    widget.config.grid_h = max(widget.MIN_H, _safe_int(props.get("grid_h", widget.DEFAULT_H), widget.DEFAULT_H))


def _set_optional_text(label, text: str) -> None:
    label.setText(text or "")
    label.setVisible(bool(text))


def _countdown_text(target: datetime, svc=None) -> str:
    """计算到目标时间的倒计时文本。

    Parameters
    ----------
    target : datetime
        目标时间。
    svc : StudyScheduleService, optional
        服务实例，用于获取校正后的时间。
        若不传则使用系统时间（非调试模式）。
    """
    now = svc.now() if svc else datetime.now().astimezone()
    delta = max(0, int((target - now).total_seconds()))
    hours, rem = divmod(delta, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def _study_runtime_context(svc, now_dt: Optional[datetime] = None) -> dict:
    context = {
        "state": "empty",
        "group": None,
        "item": None,
        "start_dt": None,
        "end_dt": None,
        "progress": None,
    }
    if svc is None:
        return context

    now_dt = now_dt or svc.now()
    if hasattr(svc, "get_runtime_group"):
        group = svc.get_runtime_group(now_dt)
    else:
        group = svc.get_current_group()

    if hasattr(svc, "get_runtime_item"):
        item = svc.get_runtime_item(now_dt, group)
    else:
        resolver = getattr(svc, "_resolve_current_item_for_group", None)
        item = resolver(group, now_dt) if callable(resolver) else svc.get_current_item()

    if item is not None:
        start_dt, end_dt = svc._item_range(item, now_dt)
        progress = None
        if start_dt is not None and end_dt is not None and end_dt > start_dt:
            total_seconds = max(1, int((end_dt - start_dt).total_seconds()))
            elapsed_seconds = max(0, min(total_seconds, int((now_dt - start_dt).total_seconds())))
            progress = elapsed_seconds / total_seconds
        context.update({
            "state": "active",
            "group": group,
            "item": item,
            "start_dt": start_dt,
            "end_dt": end_dt,
            "progress": progress,
        })
        return context

    next_group, next_item = svc.get_next_item(now_dt)
    if next_item is not None:
        context.update({
            "state": "upcoming",
            "group": next_group,
            "item": next_item,
            "start_dt": svc._next_start_today(next_item, now_dt),
        })
        return context

    if group is not None:
        context.update({"state": "completed", "group": group})
    return context


def _update_progress(progress_bar: ProgressBar, *, visible: bool, progress: Optional[float]) -> None:
    if visible and progress is not None:
        progress_bar.setValue(int(max(0.0, min(1.0, progress)) * 1000))
        progress_bar.show()
        return
    progress_bar.setValue(0)
    progress_bar.hide()


def _resolve_today_group(svc, now_dt: Optional[datetime] = None):
    if svc is None:
        return None
    if now_dt is None:
        now_dt = svc.now() if hasattr(svc, "now") else datetime.now()
    if hasattr(svc, "get_runtime_group"):
        group = svc.get_runtime_group(now_dt)
        if group is not None:
            return group
    group = svc.get_current_group()
    if group is not None:
        return group
    resolver = getattr(svc, "_resolve_group_for_now", None)
    return resolver(now_dt) if callable(resolver) else None


def _today_schedule_entries(svc, now_dt: Optional[datetime] = None):
    now_dt = now_dt or svc.now()
    group = _resolve_today_group(svc, now_dt)
    if group is None:
        return None, []

    if hasattr(svc, "get_runtime_item"):
        current_item = svc.get_runtime_item(now_dt, group)
    else:
        current_item = svc.get_current_item() if hasattr(svc, "get_current_item") else None
    entries = []
    for item in getattr(group, "items", []):
        if not getattr(item, "enabled", True):
            continue
        start_dt, end_dt = svc._item_range(item, now_dt)
        if start_dt is None or end_dt is None:
            continue
        if now_dt < start_dt:
            state = "upcoming"
        elif now_dt <= end_dt:
            state = "active"
        else:
            state = "completed"
        entries.append({
            "item": item,
            "state": state,
            "start_dt": start_dt,
            "end_dt": end_dt,
            "is_current": current_item is not None and getattr(current_item, "id", "") == getattr(item, "id", ""),
        })
    entries.sort(key=lambda entry: entry["start_dt"])
    return group, entries


def _format_schedule_entry(entry: dict, *, show_markers: bool, show_time_range: bool, show_description: bool) -> str:
    item = entry["item"]
    marker = ""
    if show_markers:
        marker = {
            "active": "[当前]",
            "completed": "[已过]",
            "upcoming": "[待开始]",
        }.get(str(entry.get("state") or ""), "[事项]")

    parts: list[str] = []
    if marker:
        parts.append(marker)
    if show_time_range:
        parts.append(f"{item.start_time} — {item.end_time}")
    parts.append(item.name)

    lines = ["  ".join(part for part in parts if part)]
    if show_description and item.description:
        lines.append(f"    {item.description}")
    return "\n".join(lines)


def _next_item_context(svc, now_dt: Optional[datetime] = None) -> dict:
    context = {
        "group": None,
        "item": None,
        "start_dt": None,
        "current_item": None,
    }
    if svc is None:
        return context

    now_dt = now_dt or datetime.now()
    runtime_group = _resolve_today_group(svc, now_dt)
    group, item = svc.get_next_item(now_dt)
    context["group"] = group or runtime_group
    context["item"] = item
    if hasattr(svc, "get_runtime_item"):
        context["current_item"] = svc.get_runtime_item(now_dt, runtime_group)
    else:
        context["current_item"] = svc.get_current_item() if hasattr(svc, "get_current_item") else None
    if item is not None:
        context["start_dt"] = svc._next_start_today(item, now_dt)
    return context


class _StudyWidgetBase(WidgetBase):
    def __init__(self, config: WidgetConfig, services: dict, parent=None):
        super().__init__(config, services, parent)
        self._svc = _get_service(services)
        self._clock_service = services.get("clock_service")

        if self._svc is not None:
            self._svc.current_group_changed.connect(self._refresh_slot)
            self._svc.current_item_changed.connect(self._refresh_slot)
            self._svc.groups_updated.connect(self._refresh_slot)
            self._svc.settings_changed.connect(self._refresh_slot)
        if self._clock_service is not None:
            self._clock_service.secondTick.connect(self._refresh_slot)

    def _refresh_slot(self, *_, **__) -> None:
        """Qt 信号回调，保证对象销毁后自动断开。"""
        self.refresh()


class _CurrentItemEditPanel(QWidget):
    def __init__(self, props: dict, widget_cls, parent=None):
        super().__init__(parent)
        form = QFormLayout(self)
        form.setVerticalSpacing(8)

        self._align_combo = _build_align_combo(form, props)

        self._show_group = CheckBox()
        self._show_group.setChecked(bool(props.get("show_group_name", True)))
        form.addRow("显示分组名:", self._show_group)

        self._show_time = CheckBox()
        self._show_time.setChecked(bool(props.get("show_time_range", True)))
        form.addRow("显示时间段:", self._show_time)

        self._show_desc = CheckBox()
        self._show_desc.setChecked(bool(props.get("show_description", False)))
        form.addRow("显示事项说明:", self._show_desc)

        self._show_remaining = CheckBox()
        self._show_remaining.setChecked(bool(props.get("show_remaining", False)))
        form.addRow("显示剩余时间:", self._show_remaining)

        self._show_progress = CheckBox()
        self._show_progress.setChecked(bool(props.get("show_progress", False)))
        form.addRow("显示进度条:", self._show_progress)

        self._font_combo, self._title_size, self._secondary_size = _build_font_controls(
            form,
            props,
            main_key="title_font_size",
            main_default=30,
            sub_key="secondary_font_size",
            sub_default=14,
            main_label="标题字号:",
            sub_label="辅助字号:",
        )
        self._grid_w, self._grid_h = _build_grid_controls(
            form,
            props,
            min_w=widget_cls.MIN_W,
            min_h=widget_cls.MIN_H,
            default_w=widget_cls.DEFAULT_W,
            default_h=widget_cls.DEFAULT_H,
        )

    def collect_props(self) -> dict:
        props = {
            "align": self._align_combo.currentData() or "center",
            "show_group_name": self._show_group.isChecked(),
            "show_time_range": self._show_time.isChecked(),
            "show_description": self._show_desc.isChecked(),
            "show_remaining": self._show_remaining.isChecked(),
            "show_progress": self._show_progress.isChecked(),
        }
        props.update(
            _collect_font_props(
                self._font_combo,
                self._title_size,
                self._secondary_size,
                main_key="title_font_size",
                sub_key="secondary_font_size",
            )
        )
        props.update(_collect_grid_props(self._grid_w, self._grid_h))
        return props


class _TimePeriodEditPanel(QWidget):
    def __init__(self, props: dict, widget_cls, parent=None):
        super().__init__(parent)
        form = QFormLayout(self)
        form.setVerticalSpacing(8)

        self._align_combo = _build_align_combo(form, props)

        self._show_item_name = CheckBox()
        self._show_item_name.setChecked(bool(props.get("show_item_name", False)))
        form.addRow("显示事项名称:", self._show_item_name)

        self._show_countdown = CheckBox()
        self._show_countdown.setChecked(bool(props.get("show_countdown", True)))
        form.addRow("显示倒计时:", self._show_countdown)

        self._show_progress = CheckBox()
        self._show_progress.setChecked(bool(props.get("show_progress", False)))
        form.addRow("显示进度条:", self._show_progress)

        self._font_combo, self._period_size, self._secondary_size = _build_font_controls(
            form,
            props,
            main_key="period_font_size",
            main_default=24,
            sub_key="secondary_font_size",
            sub_default=14,
            main_label="主文字号:",
            sub_label="辅助字号:",
        )
        self._grid_w, self._grid_h = _build_grid_controls(
            form,
            props,
            min_w=widget_cls.MIN_W,
            min_h=widget_cls.MIN_H,
            default_w=widget_cls.DEFAULT_W,
            default_h=widget_cls.DEFAULT_H,
        )

    def collect_props(self) -> dict:
        props = {
            "align": self._align_combo.currentData() or "center",
            "show_item_name": self._show_item_name.isChecked(),
            "show_countdown": self._show_countdown.isChecked(),
            "show_progress": self._show_progress.isChecked(),
        }
        props.update(
            _collect_font_props(
                self._font_combo,
                self._period_size,
                self._secondary_size,
                main_key="period_font_size",
                sub_key="secondary_font_size",
            )
        )
        props.update(_collect_grid_props(self._grid_w, self._grid_h))
        return props


class _RemainingTimeEditPanel(QWidget):
    def __init__(self, props: dict, widget_cls, parent=None):
        super().__init__(parent)
        form = QFormLayout(self)
        form.setVerticalSpacing(8)

        self._align_combo = _build_align_combo(form, props)

        self._show_label = CheckBox()
        self._show_label.setChecked(bool(props.get("show_label", True)))
        form.addRow("显示说明标签:", self._show_label)

        self._show_item_name = CheckBox()
        self._show_item_name.setChecked(bool(props.get("show_item_name", True)))
        form.addRow("显示事项名称:", self._show_item_name)

        self._show_progress = CheckBox()
        self._show_progress.setChecked(bool(props.get("show_progress", True)))
        form.addRow("显示进度条:", self._show_progress)

        self._font_combo, self._value_size, self._secondary_size = _build_font_controls(
            form,
            props,
            main_key="value_font_size",
            main_default=40,
            sub_key="secondary_font_size",
            sub_default=14,
            main_label="时间字号:",
            sub_label="辅助字号:",
        )
        self._grid_w, self._grid_h = _build_grid_controls(
            form,
            props,
            min_w=widget_cls.MIN_W,
            min_h=widget_cls.MIN_H,
            default_w=widget_cls.DEFAULT_W,
            default_h=widget_cls.DEFAULT_H,
        )

    def collect_props(self) -> dict:
        props = {
            "align": self._align_combo.currentData() or "center",
            "show_label": self._show_label.isChecked(),
            "show_item_name": self._show_item_name.isChecked(),
            "show_progress": self._show_progress.isChecked(),
        }
        props.update(
            _collect_font_props(
                self._font_combo,
                self._value_size,
                self._secondary_size,
                main_key="value_font_size",
                sub_key="secondary_font_size",
            )
        )
        props.update(_collect_grid_props(self._grid_w, self._grid_h))
        return props


class _TodayScheduleEditPanel(QWidget):
    def __init__(self, props: dict, widget_cls, parent=None):
        super().__init__(parent)
        form = QFormLayout(self)
        form.setVerticalSpacing(8)

        self._align_combo = _build_align_combo(form, props)

        self._show_group = CheckBox()
        self._show_group.setChecked(bool(props.get("show_group_name", True)))
        form.addRow("显示分组标题:", self._show_group)

        self._show_time = CheckBox()
        self._show_time.setChecked(bool(props.get("show_time_range", True)))
        form.addRow("显示时间段:", self._show_time)

        self._show_desc = CheckBox()
        self._show_desc.setChecked(bool(props.get("show_description", False)))
        form.addRow("显示事项说明:", self._show_desc)

        self._show_markers = CheckBox()
        self._show_markers.setChecked(bool(props.get("show_state_markers", True)))
        form.addRow("显示状态标识:", self._show_markers)

        self._font_combo, self._title_size, self._content_size = _build_font_controls(
            form,
            props,
            main_key="title_font_size",
            main_default=20,
            sub_key="content_font_size",
            sub_default=13,
            main_label="标题字号:",
            sub_label="列表字号:",
        )
        self._grid_w, self._grid_h = _build_grid_controls(
            form,
            props,
            min_w=widget_cls.MIN_W,
            min_h=widget_cls.MIN_H,
            default_w=widget_cls.DEFAULT_W,
            default_h=widget_cls.DEFAULT_H,
        )

    def collect_props(self) -> dict:
        props = {
            "align": self._align_combo.currentData() or "center",
            "show_group_name": self._show_group.isChecked(),
            "show_time_range": self._show_time.isChecked(),
            "show_description": self._show_desc.isChecked(),
            "show_state_markers": self._show_markers.isChecked(),
        }
        props.update(
            _collect_font_props(
                self._font_combo,
                self._title_size,
                self._content_size,
                main_key="title_font_size",
                sub_key="content_font_size",
            )
        )
        props.update(_collect_grid_props(self._grid_w, self._grid_h))
        return props


class _NextItemEditPanel(QWidget):
    def __init__(self, props: dict, widget_cls, parent=None):
        super().__init__(parent)
        form = QFormLayout(self)
        form.setVerticalSpacing(8)

        self._align_combo = _build_align_combo(form, props)

        self._show_group = CheckBox()
        self._show_group.setChecked(bool(props.get("show_group_name", True)))
        form.addRow("显示分组名:", self._show_group)

        self._show_time = CheckBox()
        self._show_time.setChecked(bool(props.get("show_time_range", True)))
        form.addRow("显示时间段:", self._show_time)

        self._show_desc = CheckBox()
        self._show_desc.setChecked(bool(props.get("show_description", False)))
        form.addRow("显示事项说明:", self._show_desc)

        self._show_countdown = CheckBox()
        self._show_countdown.setChecked(bool(props.get("show_countdown", True)))
        form.addRow("显示开始倒计时:", self._show_countdown)

        self._show_current = CheckBox()
        self._show_current.setChecked(bool(props.get("show_current_item", False)))
        form.addRow("显示当前事项:", self._show_current)

        self._font_combo, self._title_size, self._secondary_size = _build_font_controls(
            form,
            props,
            main_key="title_font_size",
            main_default=28,
            sub_key="secondary_font_size",
            sub_default=14,
            main_label="标题字号:",
            sub_label="辅助字号:",
        )
        self._grid_w, self._grid_h = _build_grid_controls(
            form,
            props,
            min_w=widget_cls.MIN_W,
            min_h=widget_cls.MIN_H,
            default_w=widget_cls.DEFAULT_W,
            default_h=widget_cls.DEFAULT_H,
        )

    def collect_props(self) -> dict:
        props = {
            "align": self._align_combo.currentData() or "center",
            "show_group_name": self._show_group.isChecked(),
            "show_time_range": self._show_time.isChecked(),
            "show_description": self._show_desc.isChecked(),
            "show_countdown": self._show_countdown.isChecked(),
            "show_current_item": self._show_current.isChecked(),
        }
        props.update(
            _collect_font_props(
                self._font_combo,
                self._title_size,
                self._secondary_size,
                main_key="title_font_size",
                sub_key="secondary_font_size",
            )
        )
        props.update(_collect_grid_props(self._grid_w, self._grid_h))
        return props


class StudyCurrentItemWidget(_StudyWidgetBase):
    WIDGET_TYPE = "study_schedule.current_item"
    WIDGET_NAME = "当前自习事项"
    DELETABLE = True
    MIN_W = 2
    MIN_H = 1
    DEFAULT_W = 3
    DEFAULT_H = 2

    def __init__(self, config: WidgetConfig, services: dict, parent=None):
        super().__init__(config, services, parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        self._title = TitleLabel("—")
        self._meta = CaptionLabel("")
        self._extra = CaptionLabel("")
        self._progress = ProgressBar()
        self._progress.setRange(0, 1000)
        self._progress.setFixedHeight(6)

        for label in (self._title, self._meta, self._extra):
            _remember_default_font(label)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setWordWrap(True)
        self._title.setStyleSheet(_TEXT_PRIMARY)
        self._meta.setStyleSheet(_TEXT_SECONDARY)
        self._extra.setStyleSheet(_TEXT_SECONDARY)

        layout.addStretch()
        layout.addWidget(self._title)
        layout.addWidget(self._meta)
        layout.addWidget(self._extra)
        layout.addWidget(self._progress)
        layout.addStretch()

        self.refresh()

    def refresh(self) -> None:
        props = self.config.props
        align = _ALIGN_MAP.get(str(props.get("align", "center") or "center"), Qt.AlignmentFlag.AlignCenter)
        for label in (self._title, self._meta, self._extra):
            label.setAlignment(align)
        _apply_font(self._title, props, "title_font_size", 30)
        _apply_font(self._meta, props, "secondary_font_size", 14)
        _apply_font(self._extra, props, "secondary_font_size", 14)

        svc = self._svc
        if svc is None:
            self._title.setText("（未加载服务）")
            self._title.setStyleSheet(_TEXT_MUTED)
            _set_optional_text(self._meta, "")
            _set_optional_text(self._extra, "")
            _update_progress(self._progress, visible=False, progress=None)
            return

        context = _study_runtime_context(svc)
        group = context.get("group")
        item = context.get("item")
        state = context.get("state")
        show_group = bool(props.get("show_group_name", True))
        show_time = bool(props.get("show_time_range", True))
        show_desc = bool(props.get("show_description", False))
        show_remaining = bool(props.get("show_remaining", False))
        show_progress = bool(props.get("show_progress", False))

        self._meta.setStyleSheet(_TEXT_SECONDARY)
        self._extra.setStyleSheet(_TEXT_SECONDARY)

        if state == "active" and item is not None:
            self._title.setText(item.name)
            self._title.setStyleSheet(_TEXT_PRIMARY)
            meta_parts: list[str] = []
            if show_group and group is not None:
                meta_parts.append(group.name)
            if show_time:
                meta_parts.append(f"{item.start_time} — {item.end_time}")
            _set_optional_text(self._meta, " · ".join(meta_parts))

            extra_parts: list[str] = []
            if show_desc and item.description:
                extra_parts.append(item.description)
            if show_remaining and context.get("end_dt") is not None:
                extra_parts.append(f"剩余 {_countdown_text(context['end_dt'], self._svc)}")
            _set_optional_text(self._extra, "\n".join(extra_parts))
            _update_progress(self._progress, visible=show_progress, progress=context.get("progress"))
            return

        _update_progress(self._progress, visible=False, progress=None)

        if state == "upcoming" and group is not None:
            self._title.setText(group.name)
            self._title.setStyleSheet(_TEXT_PRIMARY)
            _set_optional_text(self._meta, "当前没有进行中的事项")

            extra_parts: list[str] = []
            if item is not None:
                preview = item.name
                if show_time:
                    preview = f"{preview} · {item.start_time} — {item.end_time}"
                extra_parts.append(f"下一项：{preview}")
                if show_desc and item.description:
                    extra_parts.append(item.description)
                if show_remaining and context.get("start_dt") is not None:
                    extra_parts.append(f"距离开始 {_countdown_text(context['start_dt'], self._svc)}")
            _set_optional_text(self._extra, "\n".join(extra_parts))
            return

        if state == "completed" and group is not None:
            self._title.setText(group.name)
            self._title.setStyleSheet(_TEXT_PRIMARY)
            _set_optional_text(self._meta, "今日事项已完成")
            _set_optional_text(self._extra, "")
            return

        self._title.setText("暂无事项组")
        self._title.setStyleSheet(_TEXT_MUTED)
        _set_optional_text(self._meta, "请先在侧边栏创建自习事项组")
        _set_optional_text(self._extra, "")

    def get_edit_widget(self) -> QWidget:
        props = dict(self.config.props)
        props["grid_w"] = self.config.grid_w
        props["grid_h"] = self.config.grid_h
        return _CurrentItemEditPanel(props, type(self))

    def apply_props(self, props: dict) -> None:
        self.config.props.update(props)
        _apply_grid_size(self, props)
        self.refresh()


class StudyTimePeriodWidget(_StudyWidgetBase):
    WIDGET_TYPE = "study_schedule.time_period"
    WIDGET_NAME = "自习时间段"
    DELETABLE = True
    MIN_W = 2
    MIN_H = 1
    DEFAULT_W = 3
    DEFAULT_H = 2

    def __init__(self, config: WidgetConfig, services: dict, parent=None):
        super().__init__(config, services, parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        self._item_name = CaptionLabel("")
        self._period = SubtitleLabel("—")
        self._countdown = CaptionLabel("")
        self._progress = ProgressBar()
        self._progress.setRange(0, 1000)
        self._progress.setFixedHeight(6)

        for label in (self._item_name, self._period, self._countdown):
            _remember_default_font(label)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setWordWrap(True)
        self._item_name.setStyleSheet(_TEXT_SECONDARY)
        self._period.setStyleSheet(_TEXT_PRIMARY)
        self._countdown.setStyleSheet(_TEXT_SECONDARY)

        layout.addStretch()
        layout.addWidget(self._item_name)
        layout.addWidget(self._period)
        layout.addWidget(self._countdown)
        layout.addWidget(self._progress)
        layout.addStretch()

        self.refresh()

    def refresh(self) -> None:
        props = self.config.props
        align = _ALIGN_MAP.get(str(props.get("align", "center") or "center"), Qt.AlignmentFlag.AlignCenter)
        for label in (self._item_name, self._period, self._countdown):
            label.setAlignment(align)
        _apply_font(self._item_name, props, "secondary_font_size", 14)
        _apply_font(self._period, props, "period_font_size", 24)
        _apply_font(self._countdown, props, "secondary_font_size", 14)

        svc = self._svc
        if svc is None:
            self._period.setText("（未加载服务）")
            self._period.setStyleSheet(_TEXT_MUTED)
            _set_optional_text(self._item_name, "")
            _set_optional_text(self._countdown, "")
            _update_progress(self._progress, visible=False, progress=None)
            return

        context = _study_runtime_context(svc)
        item = context.get("item")
        group = context.get("group")
        state = context.get("state")
        show_item_name = bool(props.get("show_item_name", False))
        show_countdown = bool(props.get("show_countdown", True))
        show_progress = bool(props.get("show_progress", False))

        if state == "active" and item is not None:
            _set_optional_text(self._item_name, item.name if show_item_name else "")
            self._period.setText(f"{item.start_time} — {item.end_time}")
            self._period.setStyleSheet(_TEXT_PRIMARY)
            if show_countdown and context.get("end_dt") is not None:
                _set_optional_text(self._countdown, f"距离结束 {_countdown_text(context['end_dt'], self._svc)}")
            else:
                _set_optional_text(self._countdown, "")
            self._countdown.setStyleSheet(_TEXT_SECONDARY)
            _update_progress(self._progress, visible=show_progress, progress=context.get("progress"))
            return

        _update_progress(self._progress, visible=False, progress=None)

        if state == "upcoming" and item is not None:
            _set_optional_text(self._item_name, item.name if show_item_name else "")
            if show_item_name:
                self._period.setText(f"{item.start_time} — {item.end_time}")
            else:
                self._period.setText(f"下一个：{item.name}")
            self._period.setStyleSheet(_TEXT_PRIMARY)
            if show_countdown:
                countdown = f"{item.start_time} 开始"
                if context.get("start_dt") is not None:
                    countdown = f"{countdown} · {_countdown_text(context['start_dt'], self._svc)}"
                _set_optional_text(self._countdown, countdown)
            else:
                _set_optional_text(self._countdown, "")
            self._countdown.setStyleSheet(_TEXT_SECONDARY)
            return

        if state == "completed" and group is not None:
            _set_optional_text(self._item_name, group.name if show_item_name else "")
            self._period.setText("今日事项已完成")
            self._period.setStyleSheet(_TEXT_SECONDARY)
            _set_optional_text(self._countdown, "可以切换分组或稍后再看" if show_countdown else "")
            self._countdown.setStyleSheet(_TEXT_SECONDARY)
            return

        _set_optional_text(self._item_name, "")
        self._period.setText("暂无时间安排")
        self._period.setStyleSheet(_TEXT_MUTED)
        _set_optional_text(self._countdown, "请先创建事项组和事项" if show_countdown else "")
        self._countdown.setStyleSheet(_TEXT_SECONDARY)

    def get_edit_widget(self) -> QWidget:
        props = dict(self.config.props)
        props["grid_w"] = self.config.grid_w
        props["grid_h"] = self.config.grid_h
        return _TimePeriodEditPanel(props, type(self))

    def apply_props(self, props: dict) -> None:
        self.config.props.update(props)
        _apply_grid_size(self, props)
        self.refresh()


class StudyRemainingTimeWidget(_StudyWidgetBase):
    WIDGET_TYPE = "study_schedule.remaining_time"
    WIDGET_NAME = "自习剩余时间"
    DELETABLE = True
    MIN_W = 2
    MIN_H = 1
    DEFAULT_W = 3
    DEFAULT_H = 2

    def __init__(self, config: WidgetConfig, services: dict, parent=None):
        super().__init__(config, services, parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        self._label = CaptionLabel("")
        self._value = TitleLabel("--:--")
        self._meta = CaptionLabel("")
        self._progress = ProgressBar()
        self._progress.setRange(0, 1000)
        self._progress.setFixedHeight(6)

        for label in (self._label, self._value, self._meta):
            _remember_default_font(label)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setWordWrap(True)
        self._label.setStyleSheet(_TEXT_SECONDARY)
        self._value.setStyleSheet(_TEXT_PRIMARY)
        self._meta.setStyleSheet(_TEXT_SECONDARY)

        layout.addStretch()
        layout.addWidget(self._label)
        layout.addWidget(self._value)
        layout.addWidget(self._meta)
        layout.addWidget(self._progress)
        layout.addStretch()

        self.refresh()

    def refresh(self) -> None:
        props = self.config.props
        align = _ALIGN_MAP.get(str(props.get("align", "center") or "center"), Qt.AlignmentFlag.AlignCenter)
        for label in (self._label, self._value, self._meta):
            label.setAlignment(align)
        _apply_font(self._label, props, "secondary_font_size", 14)
        _apply_font(self._value, props, "value_font_size", 40)
        _apply_font(self._meta, props, "secondary_font_size", 14)

        svc = self._svc
        if svc is None:
            _set_optional_text(self._label, "")
            self._value.setText("--:--")
            self._value.setStyleSheet(_TEXT_MUTED)
            _set_optional_text(self._meta, "（未加载服务）")
            _update_progress(self._progress, visible=False, progress=None)
            return

        context = _study_runtime_context(svc)
        group = context.get("group")
        item = context.get("item")
        state = context.get("state")
        show_label = bool(props.get("show_label", True))
        show_item_name = bool(props.get("show_item_name", True))
        show_progress = bool(props.get("show_progress", True))

        self._value.setStyleSheet(_TEXT_PRIMARY)
        self._meta.setStyleSheet(_TEXT_SECONDARY)

        if state == "active" and item is not None:
            _set_optional_text(self._label, "当前剩余" if show_label else "")
            self._value.setText(_countdown_text(context["end_dt"], self._svc) if context.get("end_dt") is not None else "--:--")
            meta_parts: list[str] = []
            if show_item_name:
                meta_parts.append(item.name)
            if group is not None:
                meta_parts.append(group.name)
            meta_parts.append(f"{item.end_time} 结束")
            _set_optional_text(self._meta, " · ".join(meta_parts))
            _update_progress(self._progress, visible=show_progress, progress=context.get("progress"))
            return

        _update_progress(self._progress, visible=False, progress=None)

        if state == "upcoming" and item is not None:
            _set_optional_text(self._label, "距离开始" if show_label else "")
            self._value.setText(_countdown_text(context["start_dt"], self._svc) if context.get("start_dt") is not None else "--:--")
            meta_parts: list[str] = []
            if show_item_name:
                meta_parts.append(item.name)
            if group is not None:
                meta_parts.append(group.name)
            meta_parts.append(f"{item.start_time} 开始")
            _set_optional_text(self._meta, " · ".join(meta_parts))
            return

        if state == "completed" and group is not None:
            _set_optional_text(self._label, group.name if show_label else "")
            self._value.setText("已完成")
            _set_optional_text(self._meta, "今日事项已全部完成")
            return

        _set_optional_text(self._label, "当前剩余" if show_label else "")
        self._value.setText("--:--")
        self._value.setStyleSheet(_TEXT_MUTED)
        _set_optional_text(self._meta, "请先创建事项组和事项")

    def get_edit_widget(self) -> QWidget:
        props = dict(self.config.props)
        props["grid_w"] = self.config.grid_w
        props["grid_h"] = self.config.grid_h
        return _RemainingTimeEditPanel(props, type(self))

    def apply_props(self, props: dict) -> None:
        self.config.props.update(props)
        _apply_grid_size(self, props)
        self.refresh()


class StudyTodayScheduleWidget(_StudyWidgetBase):
    WIDGET_TYPE = "study_schedule.today_schedule"
    WIDGET_NAME = "今日自习安排"
    DELETABLE = True
    MIN_W = 3
    MIN_H = 2
    DEFAULT_W = 4
    DEFAULT_H = 3

    def __init__(self, config: WidgetConfig, services: dict, parent=None):
        super().__init__(config, services, parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self._title = SubtitleLabel("今日自习安排")
        self._content = CaptionLabel("")
        self._footer = CaptionLabel("")

        for label in (self._title, self._content, self._footer):
            _remember_default_font(label)
            label.setWordWrap(True)

        self._title.setStyleSheet(_TEXT_PRIMARY)
        self._content.setStyleSheet(_TEXT_SECONDARY)
        self._footer.setStyleSheet(_TEXT_MUTED)

        layout.addWidget(self._title)
        layout.addWidget(self._content, 1)
        layout.addWidget(self._footer)

        self.refresh()

    def refresh(self) -> None:
        props = self.config.props
        align_key = str(props.get("align", "center") or "center")
        title_align = _ALIGN_MAP.get(align_key, Qt.AlignmentFlag.AlignCenter)
        block_align = _BLOCK_ALIGN_MAP.get(align_key, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)

        self._title.setAlignment(title_align)
        self._content.setAlignment(block_align)
        self._footer.setAlignment(title_align)
        _apply_font(self._title, props, "title_font_size", 20)
        _apply_font(self._content, props, "content_font_size", 13)
        _apply_font(self._footer, props, "content_font_size", 13)

        svc = self._svc
        if svc is None:
            self._title.setText("（未加载服务）")
            self._title.setStyleSheet(_TEXT_MUTED)
            _set_optional_text(self._content, "")
            _set_optional_text(self._footer, "")
            return

        group, entries = _today_schedule_entries(svc)
        show_group = bool(props.get("show_group_name", True))
        show_time = bool(props.get("show_time_range", True))
        show_desc = bool(props.get("show_description", False))
        show_markers = bool(props.get("show_state_markers", True))

        self._title.setStyleSheet(_TEXT_PRIMARY)
        self._content.setStyleSheet(_TEXT_SECONDARY)
        self._footer.setStyleSheet(_TEXT_MUTED)

        if group is None:
            self._title.setText("今日自习安排")
            self._content.setText("暂无事项组")
            self._footer.setText("请先在侧边栏创建事项组和事项")
            self._content.show()
            self._footer.show()
            return

        self._title.setText(group.name if show_group else "今日自习安排")

        if not entries:
            self._content.setText("当前分组今日没有可用事项")
            self._footer.setText("可检查事项是否启用，或是否已设置开始/结束时间")
            self._content.show()
            self._footer.show()
            return

        self._content.setText(
            "\n\n".join(
                _format_schedule_entry(
                    entry,
                    show_markers=show_markers,
                    show_time_range=show_time,
                    show_description=show_desc,
                )
                for entry in entries
            )
        )
        self._content.show()

        footer_parts = [f"共 {len(entries)} 项"]
        current_entry = next((entry for entry in entries if entry.get("state") == "active"), None)
        next_entry = next((entry for entry in entries if entry.get("state") == "upcoming"), None)
        if current_entry is not None:
            footer_parts.append(f"当前：{current_entry['item'].name}")
        elif next_entry is not None:
            footer_parts.append(f"下一项：{next_entry['item'].name}")
        else:
            footer_parts.append("今日已完成")
        self._footer.setText(" · ".join(footer_parts))
        self._footer.show()

    def get_edit_widget(self) -> QWidget:
        props = dict(self.config.props)
        props["grid_w"] = self.config.grid_w
        props["grid_h"] = self.config.grid_h
        return _TodayScheduleEditPanel(props, type(self))

    def apply_props(self, props: dict) -> None:
        self.config.props.update(props)
        _apply_grid_size(self, props)
        self.refresh()


class StudyNextItemWidget(_StudyWidgetBase):
    WIDGET_TYPE = "study_schedule.next_item"
    WIDGET_NAME = "下一个自习事项"
    DELETABLE = True
    MIN_W = 2
    MIN_H = 2
    DEFAULT_W = 3
    DEFAULT_H = 2

    def __init__(self, config: WidgetConfig, services: dict, parent=None):
        super().__init__(config, services, parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        self._title = TitleLabel("—")
        self._meta = CaptionLabel("")
        self._countdown = CaptionLabel("")
        self._extra = CaptionLabel("")

        for label in (self._title, self._meta, self._countdown, self._extra):
            _remember_default_font(label)
            label.setWordWrap(True)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._title.setStyleSheet(_TEXT_PRIMARY)
        self._meta.setStyleSheet(_TEXT_SECONDARY)
        self._countdown.setStyleSheet(_TEXT_SECONDARY)
        self._extra.setStyleSheet(_TEXT_MUTED)

        layout.addStretch()
        layout.addWidget(self._title)
        layout.addWidget(self._meta)
        layout.addWidget(self._countdown)
        layout.addWidget(self._extra)
        layout.addStretch()

        self.refresh()

    def refresh(self) -> None:
        props = self.config.props
        align = _ALIGN_MAP.get(str(props.get("align", "center") or "center"), Qt.AlignmentFlag.AlignCenter)
        for label in (self._title, self._meta, self._countdown, self._extra):
            label.setAlignment(align)
        _apply_font(self._title, props, "title_font_size", 28)
        _apply_font(self._meta, props, "secondary_font_size", 14)
        _apply_font(self._countdown, props, "secondary_font_size", 14)
        _apply_font(self._extra, props, "secondary_font_size", 14)

        svc = self._svc
        if svc is None:
            self._title.setText("（未加载服务）")
            self._title.setStyleSheet(_TEXT_MUTED)
            _set_optional_text(self._meta, "")
            _set_optional_text(self._countdown, "")
            _set_optional_text(self._extra, "")
            return

        context = _next_item_context(svc)
        group = context.get("group")
        item = context.get("item")
        current_item = context.get("current_item")
        show_group = bool(props.get("show_group_name", True))
        show_time = bool(props.get("show_time_range", True))
        show_desc = bool(props.get("show_description", False))
        show_countdown = bool(props.get("show_countdown", True))
        show_current = bool(props.get("show_current_item", False))

        self._title.setStyleSheet(_TEXT_PRIMARY)
        self._meta.setStyleSheet(_TEXT_SECONDARY)
        self._countdown.setStyleSheet(_TEXT_SECONDARY)
        self._extra.setStyleSheet(_TEXT_MUTED)

        if item is not None:
            self._title.setText(item.name)

            meta_parts: list[str] = []
            if show_group and group is not None:
                meta_parts.append(group.name)
            if show_time:
                meta_parts.append(f"{item.start_time} — {item.end_time}")
            _set_optional_text(self._meta, " · ".join(meta_parts))

            if show_countdown and context.get("start_dt") is not None:
                _set_optional_text(self._countdown, f"距离开始 {_countdown_text(context['start_dt'], self._svc)}")
            else:
                _set_optional_text(self._countdown, "")

            extra_parts: list[str] = []
            if show_desc and item.description:
                extra_parts.append(item.description)
            if show_current and current_item is not None and getattr(current_item, "id", "") != getattr(item, "id", ""):
                extra_parts.append(f"当前：{current_item.name}")
            _set_optional_text(self._extra, "\n".join(extra_parts))
            return

        if group is not None:
            self._title.setText("今日没有下一项")
            _set_optional_text(self._meta, group.name if show_group else "")
            _set_optional_text(self._countdown, "")
            if show_current and current_item is not None:
                _set_optional_text(self._extra, f"当前：{current_item.name}")
            else:
                _set_optional_text(self._extra, "今日安排已接近尾声")
            return

        self._title.setText("暂无事项组")
        self._title.setStyleSheet(_TEXT_MUTED)
        _set_optional_text(self._meta, "请先在侧边栏创建事项组和事项")
        _set_optional_text(self._countdown, "")
        _set_optional_text(self._extra, "")

    def get_edit_widget(self) -> QWidget:
        props = dict(self.config.props)
        props["grid_w"] = self.config.grid_w
        props["grid_h"] = self.config.grid_h
        return _NextItemEditPanel(props, type(self))

    def apply_props(self, props: dict) -> None:
        self.config.props.update(props)
        _apply_grid_size(self, props)
        self.refresh()

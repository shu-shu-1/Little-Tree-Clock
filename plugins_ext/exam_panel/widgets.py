"""考试面板插件 — 画布小组件。

1. ExamSubjectWidget     — 当前科目名称与状态
2. ExamTimePeriodWidget  — 当前科目考试时间段与倒计时
3. ExamAnswerSheetWidget — 答题卡（张数 / 页数）
4. ExamPaperPagesWidget  — 试卷（张数 / 页数）
"""
from __future__ import annotations

from datetime import datetime, time as dtime, timedelta
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFormLayout, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    CaptionLabel,
    CheckBox,
    ComboBox,
    LineEdit,
    PushButton,
    SpinBox,
    SubtitleLabel,
    TitleLabel,
)

from app.widgets.fluent_font_picker import FluentFontPicker
from app.widgets.base_widget import WidgetBase, WidgetConfig


_TEXT_PRIMARY = "background: transparent; color: rgba(255,255,255,235);"
_TEXT_SECONDARY = "background: transparent; color: rgba(255,255,255,170);"
_TEXT_MUTED = "background: transparent; color: rgba(255,255,255,120);"
_COUNT_STYLE = "background: transparent; color: rgba(255,255,255,240);"
_ADJUST_BTN_STYLE = (
    "PushButton{"
    "background:rgba(255,255,255,20);"
    "color:white;"
    "border:1px solid rgba(255,255,255,40);"
    "border-radius:14px;"
    "font-size:18px;"
    "font-weight:700;"
    "padding:0;}"
    "PushButton:hover{background:rgba(255,255,255,38);}"
    "PushButton:pressed{background:rgba(255,255,255,26);}"
    "PushButton:disabled{color:rgba(255,255,255,80);border-color:rgba(255,255,255,20);background:rgba(255,255,255,10);}"
)

_ALIGN_MAP = {
    "left": Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
    "center": Qt.AlignmentFlag.AlignCenter,
    "right": Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
}


def _get_exam_service(services: dict):
    """从 services 字典中安全获取 ExamService。"""
    return services.get("exam_service")


def _safe_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _font_size(props: dict, key: str, default: int) -> int:
    return max(8, min(144, _safe_int(props.get(key, default), default)))


def _apply_font(label, props: dict, size_key: str, default_size: int) -> None:
    font = label.font()
    family = str(props.get("font_family", "") or "").strip()
    if family:
        font.setFamily(family)
    font.setPointSize(_font_size(props, size_key, default_size))
    label.setFont(font)


def _build_subject_combo(form: QFormLayout, svc, props: dict) -> ComboBox:
    combo = ComboBox()
    combo.addItem("跟随当前科目", userData="")
    if svc:
        for subject in svc.subjects():
            combo.addItem(subject.name, userData=subject.id)
    current_subject_id = str(props.get("subject_id", "") or "")
    index = next(
        (i for i in range(combo.count()) if combo.itemData(i) == current_subject_id),
        0,
    )
    combo.setCurrentIndex(index)
    form.addRow("绑定科目:", combo)
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
    current_family = str(props.get("font_family", "") or "").strip()
    font_combo.setCurrentFontFamily(current_family)

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


def _resolve_subject(widget: WidgetBase):
    svc = getattr(widget, "_svc", None)
    if svc is None:
        return None
    subject_id = str(widget.config.props.get("subject_id", "") or "")
    if subject_id:
        return svc.get_subject(subject_id)
    return svc.get_current_subject()


def _resolve_phase_for_subject(svc, subject_id: str) -> str:
    if svc is None or not subject_id:
        return "idle"
    plan = svc.get_plan_for_subject(subject_id)
    if plan is None:
        return "idle"
    return svc.get_plan_phase(plan)


def _phase_color(phase: str, enabled: bool = True) -> str:
    if not enabled:
        return "rgba(255,255,255,180)"
    return {
        "idle": "rgba(255,255,255,160)",
        "prep": "#FFB74D",
        "active": "#4CAF50",
    }.get(phase, "rgba(255,255,255,160)")


def _phase_label(phase: str) -> str:
    return {
        "idle": "待考",
        "prep": "准备中",
        "active": "进行中",
    }.get(phase, "")


def _countdown_to(target_time: dtime) -> str:
    now = datetime.now()
    target_dt = datetime.combine(now.date(), target_time)
    if target_dt < now:
        target_dt += timedelta(days=1)
    delta = target_dt - now
    total = max(0, int(delta.total_seconds()))
    hours, rem = divmod(total, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def _metric_value(props: dict, default_metric: str) -> str:
    metric = str(props.get("metric", default_metric) or default_metric)
    return metric if metric in {"count", "pages"} else default_metric


def _default_metric_label(widget_kind: str, metric: str) -> str:
    if widget_kind == "answer_sheet":
        return "答题卡页数" if metric == "pages" else "答题卡张数"
    return "试卷页数" if metric == "pages" else "试卷张数"


def _display_label(props: dict, widget_kind: str, metric: str) -> str:
    custom_label = str(props.get("label", "") or "").strip()
    if not custom_label or ("metric" not in props and custom_label in {"答题卡", "试卷"}):
        return _default_metric_label(widget_kind, metric)
    return custom_label


def _plan_metric_value(plan, widget_kind: str, metric: str) -> int:
    if plan is None:
        return 0
    if widget_kind == "answer_sheet":
        return plan.answer_sheet_page_count if metric == "pages" else plan.answer_sheet_count
    return plan.paper_page_count if metric == "pages" else plan.paper_count


def _metric_field_name(widget_kind: str, metric: str) -> str:
    if widget_kind == "answer_sheet":
        return "answer_sheet_page_count" if metric == "pages" else "answer_sheet_count"
    return "paper_page_count" if metric == "pages" else "paper_count"


def _make_adjust_button(text: str, tooltip: str, parent=None) -> PushButton:
    button = PushButton(text, parent)
    button.setFixedSize(28, 28)
    button.setToolTip(tooltip)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setStyleSheet(_ADJUST_BTN_STYLE)
    return button


def _request_layout_save(widget: WidgetBase) -> None:
    parent = widget.parentWidget()
    while parent is not None:
        save = getattr(parent, "_save_layout", None)
        if callable(save):
            save()
            return
        parent = parent.parentWidget()


def _change_metric_value(widget: WidgetBase, widget_kind: str, delta: int) -> None:
    props = widget.config.props
    metric = _metric_value(props, "count" if widget_kind == "answer_sheet" else "pages")
    override = _safe_int(props.get("override_value", props.get("override_count", 0)), 0)
    if override > 0:
        widget.config.props["override_value"] = max(0, override + delta)
        _request_layout_save(widget)
        widget.refresh()
        return

    svc = getattr(widget, "_svc", None)
    subject = _resolve_subject(widget)
    if svc is None or subject is None:
        return

    plan = svc.get_plan_for_subject(subject.id)
    if plan is None:
        from .models import ExamPlan
        plan = ExamPlan(subject_id=subject.id)

    field_name = _metric_field_name(widget_kind, metric)
    current_value = max(0, _safe_int(getattr(plan, field_name, 0), 0))
    setattr(plan, field_name, max(0, current_value + delta))
    svc.save_plan(plan)


class _SubjectEditPanel(QWidget):
    def __init__(self, props: dict, svc, parent=None):
        super().__init__(parent)
        form = QFormLayout(self)
        self._subject_combo = _build_subject_combo(form, svc, props)

        self._align = ComboBox()
        for label, value in (("居中", "center"), ("左对齐", "left"), ("右对齐", "right")):
            self._align.addItem(label, userData=value)
        current_align = props.get("align", "center")
        index = next(
            (i for i in range(self._align.count()) if self._align.itemData(i) == current_align),
            0,
        )
        self._align.setCurrentIndex(index)

        self._show_status = CheckBox()
        self._show_status.setChecked(bool(props.get("show_status", True)))
        form.addRow("对齐方式:", self._align)
        form.addRow("显示状态:", self._show_status)

        self._font_combo, self._name_size, self._status_size = _build_font_controls(
            form,
            props,
            main_key="name_font_size",
            main_default=30,
            sub_key="status_font_size",
            sub_default=14,
            main_label="科目字号:",
            sub_label="状态字号:",
        )

    def collect_props(self) -> dict:
        props = {
            "subject_id": self._subject_combo.currentData() or "",
            "align": self._align.currentData(),
            "show_status": self._show_status.isChecked(),
        }
        props.update(
            _collect_font_props(
                self._font_combo,
                self._name_size,
                self._status_size,
                main_key="name_font_size",
                sub_key="status_font_size",
            )
        )
        return props


class ExamSubjectWidget(WidgetBase):
    """显示当前考试科目名称与阶段状态。"""

    WIDGET_TYPE = "exam_subject"
    WIDGET_NAME = "当前科目"
    DELETABLE = True
    MIN_W = 2
    MIN_H = 1
    DEFAULT_W = 3
    DEFAULT_H = 2

    def __init__(self, config: WidgetConfig, services: dict, parent=None):
        super().__init__(config, services, parent)
        self._svc = _get_exam_service(services) or getattr(type(self), "_svc", None)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        self._name_lbl = TitleLabel("—")
        self._status_lbl = CaptionLabel("")
        self._name_lbl.setStyleSheet(_TEXT_PRIMARY)
        self._status_lbl.setStyleSheet(_TEXT_SECONDARY)

        layout.addStretch()
        layout.addWidget(self._name_lbl)
        layout.addWidget(self._status_lbl)
        layout.addStretch()

        if self._svc:
            self._svc.subject_changed.connect(lambda *_: self.refresh())
            self._svc.subjects_updated.connect(self.refresh)
            self._svc.plan_updated.connect(self.refresh)
            self._svc.exam_phase_changed.connect(lambda *_: self.refresh())
            self._svc.settings_changed.connect(lambda *_: self.refresh())

        self.refresh()

    def refresh(self) -> None:
        props = self.config.props
        align = _ALIGN_MAP.get(props.get("align", "center"), Qt.AlignmentFlag.AlignCenter)
        self._name_lbl.setAlignment(align)
        self._status_lbl.setAlignment(align)
        _apply_font(self._name_lbl, props, "name_font_size", 30)
        _apply_font(self._status_lbl, props, "status_font_size", 14)

        svc = self._svc
        if svc is None:
            self._name_lbl.setText("（未加载服务）")
            self._name_lbl.setStyleSheet(_TEXT_MUTED)
            self._status_lbl.hide()
            return

        subject = _resolve_subject(self)
        if subject is None:
            self._name_lbl.setText("—")
            self._name_lbl.setStyleSheet(_TEXT_PRIMARY)
            self._status_lbl.hide()
            return

        self._name_lbl.setText(subject.name)
        self._name_lbl.setStyleSheet(f"background: transparent; color: {subject.color};")

        if not bool(props.get("show_status", True)):
            self._status_lbl.hide()
            return

        phase = _resolve_phase_for_subject(svc, subject.id)
        use_status_color = bool(svc.get_setting("show_subject_status_color", True))
        self._status_lbl.setText(_phase_label(phase))
        self._status_lbl.setStyleSheet(
            f"background: transparent; color: {_phase_color(phase, use_status_color)};"
        )
        self._status_lbl.show()

    def get_edit_widget(self) -> Optional[QWidget]:
        return _SubjectEditPanel(self.config.props, self._svc)

    def apply_props(self, props: dict) -> None:
        self.config.props.update(props)
        self.refresh()


class _TimePeriodEditPanel(QWidget):
    def __init__(self, props: dict, svc, parent=None):
        super().__init__(parent)
        form = QFormLayout(self)
        self._subject_combo = _build_subject_combo(form, svc, props)
        self._show_countdown = CheckBox()
        self._show_countdown.setChecked(bool(props.get("show_countdown", True)))
        form.addRow("显示倒计时:", self._show_countdown)

        self._font_combo, self._period_size, self._countdown_size = _build_font_controls(
            form,
            props,
            main_key="period_font_size",
            main_default=24,
            sub_key="countdown_font_size",
            sub_default=14,
            main_label="时间字号:",
            sub_label="倒计时字号:",
        )

    def collect_props(self) -> dict:
        props = {
            "subject_id": self._subject_combo.currentData() or "",
            "show_countdown": self._show_countdown.isChecked(),
        }
        props.update(
            _collect_font_props(
                self._font_combo,
                self._period_size,
                self._countdown_size,
                main_key="period_font_size",
                sub_key="countdown_font_size",
            )
        )
        return props


class ExamTimePeriodWidget(WidgetBase):
    """显示当前科目的考试时间段和倒计时。"""

    WIDGET_TYPE = "exam_time_period"
    WIDGET_NAME = "考试时间段"
    DELETABLE = True
    MIN_W = 2
    MIN_H = 1
    DEFAULT_W = 3
    DEFAULT_H = 2

    def __init__(self, config: WidgetConfig, services: dict, parent=None):
        super().__init__(config, services, parent)
        self._svc = _get_exam_service(services) or getattr(type(self), "_svc", None)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        self._period_lbl = SubtitleLabel("—")
        self._countdown_lbl = CaptionLabel("")
        self._period_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._countdown_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._period_lbl.setStyleSheet(_TEXT_PRIMARY)
        self._countdown_lbl.setStyleSheet(_TEXT_SECONDARY)

        layout.addStretch()
        layout.addWidget(self._period_lbl)
        layout.addWidget(self._countdown_lbl)
        layout.addStretch()

        if self._svc:
            self._svc.subject_changed.connect(lambda *_: self.refresh())
            self._svc.subjects_updated.connect(self.refresh)
            self._svc.plan_updated.connect(self.refresh)
            self._svc.exam_phase_changed.connect(lambda *_: self.refresh())
            self._svc.settings_changed.connect(lambda *_: self.refresh())

        self.refresh()

    def refresh(self) -> None:
        props = self.config.props
        _apply_font(self._period_lbl, props, "period_font_size", 24)
        _apply_font(self._countdown_lbl, props, "countdown_font_size", 14)

        svc = self._svc
        if svc is None:
            self._period_lbl.setText("（未加载服务）")
            self._period_lbl.setStyleSheet(_TEXT_MUTED)
            self._countdown_lbl.setText("")
            return

        subject = _resolve_subject(self)
        if subject is None:
            self._period_lbl.setText("—")
            self._period_lbl.setStyleSheet(_TEXT_PRIMARY)
            self._countdown_lbl.setText("")
            return

        plan = svc.get_plan_for_subject(subject.id)
        if plan is None or not plan.start_time or not plan.end_time:
            self._period_lbl.setText("（未设置时间段）")
            self._period_lbl.setStyleSheet(_TEXT_SECONDARY)
            self._countdown_lbl.setText("")
            return

        self._period_lbl.setText(f"{plan.start_time} — {plan.end_time}")
        self._period_lbl.setStyleSheet(_TEXT_PRIMARY)

        show_countdown = props.get("show_countdown", svc.get_setting("show_countdown", True))
        if not bool(show_countdown):
            self._countdown_lbl.setText("")
            return

        now = datetime.now().time().replace(second=0, microsecond=0)
        try:
            start_time = dtime.fromisoformat(plan.start_time)
            end_time = dtime.fromisoformat(plan.end_time)
        except ValueError:
            self._countdown_lbl.setText("")
            self._countdown_lbl.setStyleSheet(_TEXT_MUTED)
            return
        if now < start_time:
            self._countdown_lbl.setText(f"开始：{_countdown_to(start_time)}")
            self._countdown_lbl.setStyleSheet(f"background: transparent; color: {_phase_color('prep')};")
        elif now <= end_time:
            self._countdown_lbl.setText(f"结束：{_countdown_to(end_time)}")
            self._countdown_lbl.setStyleSheet(f"background: transparent; color: {_phase_color('active')};")
        else:
            self._countdown_lbl.setText("已结束")
            self._countdown_lbl.setStyleSheet(_TEXT_MUTED)

    def get_edit_widget(self) -> Optional[QWidget]:
        return _TimePeriodEditPanel(self.config.props, self._svc)

    def apply_props(self, props: dict) -> None:
        self.config.props.update(props)
        self.refresh()


class _MetricValueEditPanel(QWidget):
    def __init__(self, props: dict, svc, widget_kind: str, default_metric: str, parent=None):
        super().__init__(parent)
        self._widget_kind = widget_kind
        form = QFormLayout(self)

        self._subject_combo = _build_subject_combo(form, svc, props)

        self._metric_combo = ComboBox()
        self._metric_combo.addItem("张数", userData="count")
        self._metric_combo.addItem("页数", userData="pages")
        metric = _metric_value(props, default_metric)
        index = next(
            (i for i in range(self._metric_combo.count()) if self._metric_combo.itemData(i) == metric),
            0,
        )
        self._metric_combo.setCurrentIndex(index)

        self._label = LineEdit()
        self._label.setText(str(props.get("label", "") or ""))
        self._sync_label_placeholder()
        self._metric_combo.currentIndexChanged.connect(self._sync_label_placeholder)

        self._override_value = SpinBox()
        self._override_value.setRange(0, 999)
        self._override_value.setValue(_safe_int(props.get("override_value", props.get("override_count", 0)), 0))
        self._override_value.setToolTip("0 = 从考试计划自动读取")

        self._show_adjust = CheckBox()
        self._show_adjust.setChecked(bool(props.get("show_adjust_buttons", False)))

        form.addRow("显示内容:", self._metric_combo)
        form.addRow("显示标签:", self._label)
        form.addRow("固定数值(0=自动):", self._override_value)
        form.addRow("显示加减按钮:", self._show_adjust)

        self._font_combo, self._value_size, self._label_size = _build_font_controls(
            form,
            props,
            main_key="value_font_size",
            main_default=48,
            sub_key="label_font_size",
            sub_default=14,
            main_label="数值字号:",
            sub_label="标签字号:",
        )

    def _sync_label_placeholder(self) -> None:
        metric = self._metric_combo.currentData() or "count"
        self._label.setPlaceholderText(f"留空自动显示为{_default_metric_label(self._widget_kind, metric)}")

    def collect_props(self) -> dict:
        props = {
            "subject_id": self._subject_combo.currentData() or "",
            "metric": self._metric_combo.currentData() or "count",
            "label": self._label.text().strip(),
            "override_value": self._override_value.value(),
            "show_adjust_buttons": self._show_adjust.isChecked(),
        }
        props.update(
            _collect_font_props(
                self._font_combo,
                self._value_size,
                self._label_size,
                main_key="value_font_size",
                sub_key="label_font_size",
            )
        )
        return props


class ExamAnswerSheetWidget(WidgetBase):
    """显示答题卡张数或页数。"""

    WIDGET_TYPE = "exam_answer_sheets"
    WIDGET_NAME = "答题卡（张/页）"
    DELETABLE = True
    MIN_W = 1
    MIN_H = 1
    DEFAULT_W = 2
    DEFAULT_H = 2

    def __init__(self, config: WidgetConfig, services: dict, parent=None):
        super().__init__(config, services, parent)
        self._svc = _get_exam_service(services) or getattr(type(self), "_svc", None)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        self._count_lbl = TitleLabel("0")
        self._count_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._count_lbl.setStyleSheet(_COUNT_STYLE)
        self._label_lbl = CaptionLabel("答题卡张数")
        self._label_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label_lbl.setStyleSheet(_TEXT_SECONDARY)

        self._count_row = QHBoxLayout()
        self._count_row.setContentsMargins(0, 0, 0, 0)
        self._count_row.setSpacing(8)
        self._minus_btn = _make_adjust_button("−", "减少 1", self)
        self._plus_btn = _make_adjust_button("+", "增加 1", self)
        self._minus_btn.clicked.connect(lambda: _change_metric_value(self, "answer_sheet", -1))
        self._plus_btn.clicked.connect(lambda: _change_metric_value(self, "answer_sheet", 1))
        self._count_row.addStretch()
        self._count_row.addWidget(self._minus_btn)
        self._count_row.addWidget(self._count_lbl)
        self._count_row.addWidget(self._plus_btn)
        self._count_row.addStretch()

        layout.addStretch()
        layout.addLayout(self._count_row)
        layout.addWidget(self._label_lbl)
        layout.addStretch()

        if self._svc:
            self._svc.subject_changed.connect(lambda *_: self.refresh())
            self._svc.subjects_updated.connect(self.refresh)
            self._svc.plan_updated.connect(self.refresh)

        self.refresh()

    def refresh(self) -> None:
        props = self.config.props
        metric = _metric_value(props, "count")
        _apply_font(self._count_lbl, props, "value_font_size", 48)
        _apply_font(self._label_lbl, props, "label_font_size", 14)
        self._label_lbl.setText(_display_label(props, "answer_sheet", metric))

        override = _safe_int(props.get("override_value", props.get("override_count", 0)), 0)
        show_adjust = bool(props.get("show_adjust_buttons", False))
        subject = _resolve_subject(self)
        can_adjust = override > 0 or subject is not None
        if override:
            self._count_lbl.setText(str(override))
            self._update_adjust_buttons(show_adjust, can_adjust, override, use_override=True)
            return

        svc = self._svc
        if svc is None:
            self._count_lbl.setText("0")
            self._update_adjust_buttons(show_adjust, False, 0, use_override=False)
            return

        if subject is None:
            self._count_lbl.setText("0")
            self._update_adjust_buttons(show_adjust, False, 0, use_override=False)
            return

        plan = svc.get_plan_for_subject(subject.id)
        value = _plan_metric_value(plan, "answer_sheet", metric)
        self._count_lbl.setText(str(value))
        self._update_adjust_buttons(show_adjust, True, value, use_override=False)

    def _update_adjust_buttons(self, visible: bool, can_adjust: bool, value: int, *, use_override: bool) -> None:
        self._minus_btn.setVisible(visible)
        self._plus_btn.setVisible(visible)
        self._minus_btn.setEnabled(visible and can_adjust and value > 0)
        self._plus_btn.setEnabled(visible and can_adjust)
        source_text = "固定数值" if use_override else "考试计划"
        self._minus_btn.setToolTip(f"减少 1（修改{source_text}）")
        self._plus_btn.setToolTip(f"增加 1（修改{source_text}）")

    def get_edit_widget(self) -> Optional[QWidget]:
        return _MetricValueEditPanel(self.config.props, self._svc, "answer_sheet", "count")

    def apply_props(self, props: dict) -> None:
        self.config.props.update(props)
        self.refresh()


class ExamPaperPagesWidget(WidgetBase):
    """显示试卷张数或页数。"""

    WIDGET_TYPE = "exam_paper_pages"
    WIDGET_NAME = "试卷（张/页）"
    DELETABLE = True
    MIN_W = 1
    MIN_H = 1
    DEFAULT_W = 2
    DEFAULT_H = 2

    def __init__(self, config: WidgetConfig, services: dict, parent=None):
        super().__init__(config, services, parent)
        self._svc = _get_exam_service(services) or getattr(type(self), "_svc", None)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        self._count_lbl = TitleLabel("0")
        self._count_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._count_lbl.setStyleSheet(_COUNT_STYLE)
        self._label_lbl = CaptionLabel("试卷页数")
        self._label_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label_lbl.setStyleSheet(_TEXT_SECONDARY)

        self._count_row = QHBoxLayout()
        self._count_row.setContentsMargins(0, 0, 0, 0)
        self._count_row.setSpacing(8)
        self._minus_btn = _make_adjust_button("−", "减少 1", self)
        self._plus_btn = _make_adjust_button("+", "增加 1", self)
        self._minus_btn.clicked.connect(lambda: _change_metric_value(self, "paper", -1))
        self._plus_btn.clicked.connect(lambda: _change_metric_value(self, "paper", 1))
        self._count_row.addStretch()
        self._count_row.addWidget(self._minus_btn)
        self._count_row.addWidget(self._count_lbl)
        self._count_row.addWidget(self._plus_btn)
        self._count_row.addStretch()

        layout.addStretch()
        layout.addLayout(self._count_row)
        layout.addWidget(self._label_lbl)
        layout.addStretch()

        if self._svc:
            self._svc.subject_changed.connect(lambda *_: self.refresh())
            self._svc.subjects_updated.connect(self.refresh)
            self._svc.plan_updated.connect(self.refresh)

        self.refresh()

    def refresh(self) -> None:
        props = self.config.props
        metric = _metric_value(props, "pages")
        _apply_font(self._count_lbl, props, "value_font_size", 48)
        _apply_font(self._label_lbl, props, "label_font_size", 14)
        self._label_lbl.setText(_display_label(props, "paper", metric))

        override = _safe_int(props.get("override_value", props.get("override_count", 0)), 0)
        show_adjust = bool(props.get("show_adjust_buttons", False))
        subject = _resolve_subject(self)
        can_adjust = override > 0 or subject is not None
        if override:
            self._count_lbl.setText(str(override))
            self._update_adjust_buttons(show_adjust, can_adjust, override, use_override=True)
            return

        svc = self._svc
        if svc is None:
            self._count_lbl.setText("0")
            self._update_adjust_buttons(show_adjust, False, 0, use_override=False)
            return

        if subject is None:
            self._count_lbl.setText("0")
            self._update_adjust_buttons(show_adjust, False, 0, use_override=False)
            return

        plan = svc.get_plan_for_subject(subject.id)
        value = _plan_metric_value(plan, "paper", metric)
        self._count_lbl.setText(str(value))
        self._update_adjust_buttons(show_adjust, True, value, use_override=False)

    def _update_adjust_buttons(self, visible: bool, can_adjust: bool, value: int, *, use_override: bool) -> None:
        self._minus_btn.setVisible(visible)
        self._plus_btn.setVisible(visible)
        self._minus_btn.setEnabled(visible and can_adjust and value > 0)
        self._plus_btn.setEnabled(visible and can_adjust)
        source_text = "固定数值" if use_override else "考试计划"
        self._minus_btn.setToolTip(f"减少 1（修改{source_text}）")
        self._plus_btn.setToolTip(f"增加 1（修改{source_text}）")

    def get_edit_widget(self) -> Optional[QWidget]:
        return _MetricValueEditPanel(self.config.props, self._svc, "paper", "pages")

    def apply_props(self, props: dict) -> None:
        self.config.props.update(props)
        self.refresh()

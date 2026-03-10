"""考试面板插件 — 侧边栏面板

包含三个 Tab：
  科目管理   — 新建/编辑/删除科目
    预设绑定   — 绑定共享布局预设、设置默认预设
  考试规划   — 给每个科目配置时间段、张数、提醒
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QTime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget,
    QFrame,
)
from qfluentwidgets import (
    FluentIcon as FIF,
    PushButton,
    BodyLabel, CaptionLabel, StrongBodyLabel, SubtitleLabel,
    LineEdit, SpinBox, ComboBox, TimePicker,
    CheckBox,
    ListWidget,
    InfoBar, InfoBarPosition, MessageBox,
    SmoothScrollArea,
    Pivot,
)

from PySide6.QtWidgets import QListWidgetItem

from .models import ExamSubject, ExamPlan, ExamReminder


def _wrap_layout(layout, parent=None) -> QWidget:
    """将布局包装为独立 widget，便于在 Fluent 风格纵向表单中复用。"""
    widget = QWidget(parent)
    widget.setLayout(layout)
    return widget


def _make_field_block(title: str, content: QWidget, *, description: str = "", parent=None) -> QWidget:
    """构建适配 qfluentwidgets 的纵向字段块。"""
    block = QWidget(parent)
    layout = QVBoxLayout(block)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)

    layout.addWidget(BodyLabel(title))

    if description:
        desc = CaptionLabel(description)
        desc.setWordWrap(True)
        layout.addWidget(desc)

    layout.addWidget(content)
    return block


def _make_scroll_page(content: QWidget, parent=None) -> SmoothScrollArea:
    """为较高的侧边栏页面提供滚动能力，避免撑高主窗口。"""
    scroll = SmoothScrollArea(parent)
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.enableTransparentBackground()
    content.setStyleSheet("background: transparent;")
    scroll.setWidget(content)
    return scroll


# ─────────────────────────────────────────────────────────────────────────── #
# 模态对话框辅助
# ─────────────────────────────────────────────────────────────────────────── #

class _SubjectDialog(MessageBox):
    """新建/编辑科目对话框。"""

    def __init__(self, subject: Optional[ExamSubject] = None, parent=None):
        title = "编辑科目" if subject else "新建科目"
        super().__init__(title, "", parent)
        self.yesButton.setText("保存")
        self.cancelButton.setText("取消")
        self.contentLabel.hide()

        self._subject = subject or ExamSubject()

        form = QVBoxLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(12)

        self._name_edit = LineEdit()
        self._name_edit.setPlaceholderText("科目名称，如「语文」")
        self._name_edit.setText(self._subject.name)

        # 颜色选择（简单的预设色块选择器）
        self._color_combo = ComboBox()
        _PRESET_COLORS = [
            ("蓝色", "#2196F3"), ("绿色", "#4CAF50"), ("橙色", "#FF9800"),
            ("红色", "#F44336"), ("紫色", "#9C27B0"), ("青色", "#00BCD4"),
            ("金色", "#FFC107"), ("粉色", "#E91E63"),
        ]
        for label_c, hex_c in _PRESET_COLORS:
            self._color_combo.addItem(label_c, userData=hex_c)
        # 选中当前颜色
        cur_color = self._subject.color
        idx = next(
            (i for i in range(self._color_combo.count())
             if self._color_combo.itemData(i) == cur_color),
            0,
        )
        self._color_combo.setCurrentIndex(idx)

        form.addWidget(_make_field_block("科目名称", self._name_edit))
        form.addWidget(_make_field_block("主题颜色", self._color_combo))

        self.textLayout.addLayout(form)

    def accept(self) -> None:
        name = self._name_edit.text().strip()
        if not name:
            InfoBar.warning(
                "提示", "科目名称不能为空",
                duration=2000, parent=self,
                position=InfoBarPosition.TOP,
            )
            return
        self._subject.name  = name
        self._subject.color = self._color_combo.currentData() or "#4CAF50"
        super().accept()

    def result_subject(self) -> ExamSubject:
        return self._subject


class _ReminderDialog(MessageBox):
    """新建/编辑提醒项对话框。"""

    def __init__(self, reminder: Optional[ExamReminder] = None, parent=None):
        title = "编辑提醒" if reminder else "新建提醒"
        super().__init__(title, "", parent)
        self.yesButton.setText("保存")
        self.cancelButton.setText("取消")
        self.contentLabel.hide()

        self._reminder = reminder or ExamReminder()

        form = QVBoxLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(12)

        self._min_spin = SpinBox()
        self._min_spin.setRange(1, 120)
        self._min_spin.setSuffix(" 分钟前")
        self._min_spin.setValue(self._reminder.minutes_before_end)

        self._mode_combo = ComboBox()
        for lbl, val in [
            ("全屏显示", "fullscreen"),
            ("语音播报", "voice"),
            ("全屏+语音", "both"),
        ]:
            self._mode_combo.addItem(lbl, userData=val)
        cur_mode = self._reminder.mode
        idx = next(
            (i for i in range(self._mode_combo.count())
             if self._mode_combo.itemData(i) == cur_mode),
            0,
        )
        self._mode_combo.setCurrentIndex(idx)
        self._mode_combo.currentIndexChanged.connect(self._sync_flash_state)

        self._flash_cb = CheckBox("全屏时闪烁")
        self._flash_cb.setChecked(self._reminder.fullscreen_flash)

        self._msg_edit = LineEdit()
        self._msg_edit.setPlaceholderText("留空则自动生成提醒文字")
        self._msg_edit.setText(self._reminder.message)

        form.addWidget(_make_field_block("提前时间", self._min_spin))
        form.addWidget(_make_field_block("提醒方式", self._mode_combo))
        form.addWidget(_make_field_block("全屏附加效果", self._flash_cb))
        form.addWidget(_make_field_block("自定义文字", self._msg_edit))
        self.textLayout.addLayout(form)
        self._sync_flash_state()

    def _sync_flash_state(self) -> None:
        mode = self._mode_combo.currentData() or "fullscreen"
        enabled = mode in ("fullscreen", "both")
        self._flash_cb.setEnabled(enabled)
        if not enabled:
            self._flash_cb.setChecked(False)

    def accept(self) -> None:
        self._reminder.minutes_before_end = self._min_spin.value()
        self._reminder.mode               = self._mode_combo.currentData() or "fullscreen"
        self._reminder.fullscreen_flash   = self._flash_cb.isChecked()
        self._reminder.message            = self._msg_edit.text().strip()
        super().accept()

    def result_reminder(self) -> ExamReminder:
        return self._reminder


# ─────────────────────────────────────────────────────────────────────────── #
# Tab 1：科目管理
# ─────────────────────────────────────────────────────────────────────────── #

class _SubjectTab(QWidget):
    def __init__(self, svc, parent=None):
        super().__init__(parent)
        self._svc = svc

        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(12, 12, 12, 12)
        vbox.setSpacing(8)

        # 操作按钮行
        btn_row = QHBoxLayout()
        self._add_btn = PushButton(FIF.ADD, "新建科目")
        self._add_btn.clicked.connect(self._on_add)
        btn_row.addWidget(self._add_btn)
        self._activate_btn = PushButton(FIF.PLAY, "设为当前科目")
        self._activate_btn.clicked.connect(self._on_activate)
        btn_row.addWidget(self._activate_btn)
        btn_row.addStretch()
        vbox.addLayout(btn_row)

        # 列表（qfluentwidgets ListWidget）
        self._list = ListWidget()
        self._list.itemDoubleClicked.connect(self._on_edit)
        vbox.addWidget(self._list, 1)

        # 底部操作
        bot = QHBoxLayout()
        self._edit_btn = PushButton(FIF.EDIT,   "编辑")
        self._del_btn  = PushButton(FIF.DELETE, "删除")
        self._edit_btn.clicked.connect(self._on_edit)
        self._del_btn.clicked.connect(self._on_delete)
        bot.addWidget(self._edit_btn)
        bot.addWidget(self._del_btn)
        bot.addStretch()
        vbox.addLayout(bot)

        svc.subjects_updated.connect(self._refresh_list)
        svc.plan_updated.connect(self._refresh_list)
        svc.subject_changed.connect(self._refresh_list)
        self._refresh_list()

    def _refresh_list(self) -> None:
        self._list.clear()
        for subj in self._svc.subjects():
            text = subj.name
            if subj.id == self._svc.current_subject_id:
                text = f"{subj.name}  （当前）"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, subj.id)
            self._list.addItem(item)

    def _selected_id(self) -> Optional[str]:
        item = self._list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _on_add(self) -> None:
        dlg = _SubjectDialog(parent=self.window())
        if dlg.exec():
            self._svc.save_subject(dlg.result_subject())

    def _on_activate(self) -> None:
        sid = self._selected_id()
        if not sid:
            return
        self._svc.set_current_subject(
            sid,
            self._svc.current_zone_id,
            apply_preset=bool(self._svc.current_zone_id),
        )

    def _on_edit(self) -> None:
        sid = self._selected_id()
        if not sid:
            return
        subj = self._svc.get_subject(sid)
        if not subj:
            return
        dlg = _SubjectDialog(subject=subj, parent=self.window())
        if dlg.exec():
            self._svc.save_subject(dlg.result_subject())

    def _on_delete(self) -> None:
        sid = self._selected_id()
        if not sid:
            return
        subj = self._svc.get_subject(sid)
        if not subj:
            return
        box = MessageBox(
            "确认删除",
            f"确定删除科目「{subj.name}」及其所有考试计划？",
            self.window(),
        )
        box.yesButton.setText("删除")
        box.cancelButton.setText("取消")
        if box.exec():
            self._svc.delete_subject(sid)


# ─────────────────────────────────────────────────────────────────────────── #
# Tab 2：预设管理
# ─────────────────────────────────────────────────────────────────────────── #

class _PresetTab(QWidget):
    def __init__(self, svc, parent=None):
        super().__init__(parent)
        self._svc = svc

        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(12, 12, 12, 12)
        vbox.setSpacing(8)

        note = CaptionLabel(
            "提示：布局预设的创建、覆盖当前布局和手动应用已迁移到独立的“布局预设”侧边栏页面；此处仅负责绑定到考试科目。"
        )
        note.setWordWrap(True)
        vbox.addWidget(note)

        # 默认预设选择
        def_row = QHBoxLayout()
        def_row.addWidget(BodyLabel("默认预设:"))
        self._default_combo = ComboBox()
        self._default_combo.setMinimumWidth(140)
        self._default_combo.currentIndexChanged.connect(self._on_default_changed)
        def_row.addWidget(self._default_combo, 1)
        vbox.addLayout(def_row)

        # 列表（qfluentwidgets ListWidget）
        self._list = ListWidget()
        vbox.addWidget(self._list, 1)

        # 操作按钮
        bot = QHBoxLayout()
        self._bind_btn   = PushButton(FIF.LINK,   "绑定/更换预设")
        self._clear_btn  = PushButton(FIF.CLOSE,  "清除绑定")
        for b in (self._bind_btn, self._clear_btn):
            bot.addWidget(b)
        bot.addStretch()
        vbox.addLayout(bot)

        self._bind_btn.clicked.connect(self._on_bind)
        self._clear_btn.clicked.connect(self._on_clear)

        svc.preset_updated.connect(self._refresh)
        svc.subjects_updated.connect(self._refresh)
        svc.subject_changed.connect(lambda *_: self._refresh())
        self._refresh()

    def _refresh(self) -> None:
        # 刷新默认预设下拉
        self._default_combo.blockSignals(True)
        self._default_combo.clear()
        self._default_combo.addItem("（无默认预设）", userData="")
        for preset in self._svc.presets():
            self._default_combo.addItem(preset.name, userData=preset.id)
        default_preset = self._svc.get_default_preset()
        dft = default_preset.id if default_preset else ""
        idx = next(
            (i for i in range(self._default_combo.count())
             if self._default_combo.itemData(i) == dft),
            0,
        )
        self._default_combo.setCurrentIndex(idx)
        self._default_combo.blockSignals(False)

        # 刷新列表
        self._list.clear()
        default_preset = self._svc.get_default_preset()
        for subj in self._svc.subjects():
            title = subj.name
            if subj.id == self._svc.current_subject_id:
                title += "  [当前科目]"

            binding = self._svc.get_binding(subj.id)
            bound_preset = self._svc.get_preset(binding.preset_id) if binding and binding.preset_id else None

            meta_parts = []
            if bound_preset is not None:
                meta_parts.append(f"绑定：{bound_preset.name}")
            elif binding and binding.preset_id:
                meta_parts.append("绑定：预设已删除")
            else:
                meta_parts.append("绑定：未单独绑定")

            if default_preset is not None:
                meta_parts.append(f"默认：{default_preset.name}")
            else:
                meta_parts.append("默认：无")

            item = QListWidgetItem(f"{title}\n{' · '.join(meta_parts)}")
            item.setData(Qt.ItemDataRole.UserRole, subj.id)
            self._list.addItem(item)

    def _selected_id(self) -> Optional[str]:
        item = self._list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _on_default_changed(self, idx: int) -> None:
        pid = self._default_combo.itemData(idx) or ""
        self._svc.set_default_preset(pid)

    def _on_bind(self) -> None:
        subject_id = self._selected_id()
        if not subject_id:
            return
        presets = self._svc.presets()
        if not presets:
            InfoBar.warning("提示", "当前还没有共享布局预设，请先前往“布局预设”页面创建", duration=2500,
                            parent=self.window(), position=InfoBarPosition.BOTTOM)
            return

        subject = self._svc.get_subject(subject_id)
        box = MessageBox("绑定预设", f"为科目「{subject.name if subject else ''}」选择预设：", self.window())
        box.yesButton.setText("保存")
        box.cancelButton.setText("取消")
        box.contentLabel.hide()

        combo = ComboBox()
        combo.addItem("（不单独绑定，继承默认预设）", userData="")
        for preset in presets:
            combo.addItem(preset.name, userData=preset.id)

        current_binding = self._svc.get_binding(subject_id)
        current_id = current_binding.preset_id if current_binding else ""
        current_index = next(
            (i for i in range(combo.count()) if combo.itemData(i) == current_id),
            0,
        )
        combo.setCurrentIndex(current_index)

        box.textLayout.addWidget(combo)
        if box.exec():
            self._svc.set_binding(subject_id, combo.currentData() or "")

    def _on_clear(self) -> None:
        subject_id = self._selected_id()
        if not subject_id:
            return
        self._svc.set_binding(subject_id, "")


# ─────────────────────────────────────────────────────────────────────────── #
# Tab 3：考试规划（单科目编辑）
# ─────────────────────────────────────────────────────────────────────────── #

class _PlanTab(QWidget):
    """为每个科目配置考试时间段、张数、提醒。"""

    def __init__(self, svc, parent=None):
        super().__init__(parent)
        self._svc = svc
        self._current_plan_id: Optional[str] = None

        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(12, 12, 12, 12)
        vbox.setSpacing(8)

        # 科目选择器
        sel_row = QHBoxLayout()
        sel_row.addWidget(BodyLabel("选择科目:"))
        self._subj_combo = ComboBox()
        self._subj_combo.setMinimumWidth(120)
        self._subj_combo.currentIndexChanged.connect(self._on_subject_changed)
        sel_row.addWidget(self._subj_combo, 1)
        vbox.addLayout(sel_row)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background: rgba(128,128,128,50);")
        vbox.addWidget(sep)

        # 表单（时间段、张数、备考时间）
        form = QVBoxLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(12)

        self._time_enabled_cb = CheckBox("启用考试时间段")
        self._time_enabled_cb.checkStateChanged.connect(lambda *_: self._sync_time_inputs())

        self._start_picker = TimePicker(self)
        self._start_picker.setTime(QTime(9, 0))
        self._start_picker.setFixedWidth(140)

        self._end_picker = TimePicker(self)
        self._end_picker.setTime(QTime(11, 0))
        self._end_picker.setFixedWidth(140)

        time_row = QVBoxLayout()
        time_row.setContentsMargins(0, 0, 0, 0)
        time_row.setSpacing(6)
        time_row.addWidget(self._time_enabled_cb)

        time_picker_row = QHBoxLayout()
        time_picker_row.setContentsMargins(0, 0, 0, 0)
        time_picker_row.addWidget(self._start_picker)
        time_picker_row.addWidget(BodyLabel("—"))
        time_picker_row.addWidget(self._end_picker)
        time_picker_row.addStretch()
        time_row.addLayout(time_picker_row)

        self._ans_count_spin = SpinBox()
        self._ans_count_spin.setRange(0, 999)
        self._ans_count_spin.setSuffix(" 张")
        self._ans_count_spin.setFixedWidth(140)

        self._ans_page_spin = SpinBox()
        self._ans_page_spin.setRange(0, 999)
        self._ans_page_spin.setSuffix(" 页")
        self._ans_page_spin.setFixedWidth(140)

        self._paper_count_spin = SpinBox()
        self._paper_count_spin.setRange(0, 999)
        self._paper_count_spin.setSuffix(" 张")
        self._paper_count_spin.setFixedWidth(140)

        self._paper_page_spin = SpinBox()
        self._paper_page_spin.setRange(0, 999)
        self._paper_page_spin.setSuffix(" 页")
        self._paper_page_spin.setFixedWidth(140)

        self._prep_spin   = SpinBox()
        self._prep_spin.setRange(0, 30)
        self._prep_spin.setSuffix(" 分钟")
        self._prep_spin.setToolTip("提前进入准备状态")
        self._prep_spin.setFixedWidth(140)

        form.addWidget(
            _make_field_block(
                "考试时间段",
                _wrap_layout(time_row),
                description="启用后可设置考试开始与结束时间。",
            )
        )
        form.addWidget(_make_field_block("答题卡张数", self._ans_count_spin))
        form.addWidget(_make_field_block("答题卡页数", self._ans_page_spin))
        form.addWidget(_make_field_block("试卷张数", self._paper_count_spin))
        form.addWidget(_make_field_block("试卷页数", self._paper_page_spin))
        form.addWidget(
            _make_field_block(
                "提前准备",
                self._prep_spin,
                description="在考试开始前提前进入准备状态。",
            )
        )
        vbox.addLayout(form)

        # 保存计划按钮
        self._save_btn = PushButton(FIF.SAVE, "保存计划")
        self._save_btn.clicked.connect(self._on_save_plan)
        vbox.addWidget(self._save_btn)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet("background: rgba(128,128,128,50);")
        vbox.addWidget(sep2)

        # 提醒列表
        vbox.addWidget(StrongBodyLabel("提醒设置"))
        rem_btn_row = QHBoxLayout()
        self._add_rem_btn = PushButton(FIF.ADD,    "添加提醒")
        self._add_rem_btn.clicked.connect(self._on_add_reminder)
        rem_btn_row.addWidget(self._add_rem_btn)
        rem_btn_row.addStretch()
        vbox.addLayout(rem_btn_row)

        self._rem_list = ListWidget()
        self._rem_list.setMaximumHeight(160)
        vbox.addWidget(self._rem_list)

        rem_bot = QHBoxLayout()
        self._edit_rem_btn = PushButton(FIF.EDIT,   "编辑")
        self._del_rem_btn  = PushButton(FIF.DELETE, "删除")
        self._edit_rem_btn.clicked.connect(self._on_edit_reminder)
        self._del_rem_btn.clicked.connect(self._on_delete_reminder)
        rem_bot.addWidget(self._edit_rem_btn)
        rem_bot.addWidget(self._del_rem_btn)
        rem_bot.addStretch()
        vbox.addLayout(rem_bot)

        vbox.addStretch()

        svc.subjects_updated.connect(self._refresh_subjects)
        svc.plan_updated.connect(self._refresh_subjects)
        svc.subject_changed.connect(self._refresh_subjects)
        self._refresh_subjects()

    def _sync_time_inputs(self) -> None:
        enabled = self._time_enabled_cb.isEnabled() and self._time_enabled_cb.isChecked()
        self._start_picker.setEnabled(enabled)
        self._end_picker.setEnabled(enabled)

    # ── 数据刷新 ─────────────────────────────────────────────────────── #

    def _refresh_subjects(self) -> None:
        old_id = self._subj_combo.currentData()
        self._subj_combo.blockSignals(True)
        self._subj_combo.clear()
        self._subj_combo.addItem("（选择科目）", userData="")
        for s in self._svc.subjects():
            self._subj_combo.addItem(s.name, userData=s.id)
        # 恢复选中
        idx = next(
            (i for i in range(self._subj_combo.count())
             if self._subj_combo.itemData(i) == old_id),
            0,
        )
        self._subj_combo.setCurrentIndex(idx)
        self._subj_combo.blockSignals(False)
        self._on_subject_changed()

    def _on_subject_changed(self) -> None:
        sid = self._subj_combo.currentData() or ""
        plan = self._svc.get_plan_for_subject(sid) if sid else None
        enabled = bool(sid)
        for w in (self._time_enabled_cb, self._ans_count_spin,
                  self._ans_page_spin, self._paper_count_spin,
                  self._paper_page_spin, self._prep_spin, self._save_btn,
                  self._add_rem_btn, self._edit_rem_btn, self._del_rem_btn):
            w.setEnabled(enabled)
        self._rem_list.setEnabled(enabled)

        if plan:
            self._current_plan_id = plan.id
            has_time = bool(plan.start_time and plan.end_time)
            self._time_enabled_cb.setChecked(has_time)
            if has_time:
                start_time = QTime.fromString(plan.start_time, "HH:mm")
                end_time = QTime.fromString(plan.end_time, "HH:mm")
                if start_time.isValid():
                    self._start_picker.setTime(start_time)
                if end_time.isValid():
                    self._end_picker.setTime(end_time)
            self._ans_count_spin.setValue(plan.answer_sheet_count)
            self._ans_page_spin.setValue(plan.answer_sheet_page_count)
            self._paper_count_spin.setValue(plan.paper_count)
            self._paper_page_spin.setValue(plan.paper_page_count)
            self._prep_spin.setValue(plan.prep_min)
            self._refresh_reminders(plan)
        else:
            self._current_plan_id = None
            self._time_enabled_cb.setChecked(False)
            self._start_picker.setTime(QTime(9, 0))
            self._end_picker.setTime(QTime(11, 0))
            self._ans_count_spin.setValue(0)
            self._ans_page_spin.setValue(0)
            self._paper_count_spin.setValue(0)
            self._paper_page_spin.setValue(0)
            self._prep_spin.setValue(5)
            self._rem_list.clear()

        self._sync_time_inputs()

    def _refresh_reminders(self, plan: ExamPlan) -> None:
        self._rem_list.clear()
        for r in plan.reminders:
            mode_map = {"fullscreen": "全屏", "voice": "语音", "both": "全屏+语音"}
            mode_lbl = mode_map.get(r.mode, r.mode)
            flash_info = "（闪烁）" if r.fullscreen_flash else ""
            text = f"结束前 {r.minutes_before_end} 分钟  {mode_lbl}{flash_info}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, r.id)
            self._rem_list.addItem(item)

    # ── 计划保存 ──────────────────────────────────────────────────────── #

    def _on_save_plan(self) -> None:
        sid = self._subj_combo.currentData() or ""
        if not sid:
            return
        if self._time_enabled_cb.isChecked():
            start_text = self._start_picker.getTime().toString("HH:mm")
            end_text = self._end_picker.getTime().toString("HH:mm")
        else:
            start_text = ""
            end_text = ""

        plan = self._svc.get_plan_for_subject(sid)
        if plan is None:
            from .models import ExamPlan
            plan = ExamPlan(subject_id=sid)

        plan.start_time         = start_text
        plan.end_time           = end_text
        plan.answer_sheet_count = self._ans_count_spin.value()
        plan.answer_sheet_page_count = self._ans_page_spin.value()
        plan.paper_count        = self._paper_count_spin.value()
        plan.paper_page_count   = self._paper_page_spin.value()
        plan.prep_min           = self._prep_spin.value()
        self._svc.save_plan(plan)
        InfoBar.success("已保存", "考试计划已更新", duration=2000,
                        parent=self.window(), position=InfoBarPosition.BOTTOM)

    # ── 提醒操作 ──────────────────────────────────────────────────────── #

    def _current_plan(self) -> Optional[ExamPlan]:
        sid = self._subj_combo.currentData() or ""
        return self._svc.get_plan_for_subject(sid) if sid else None

    def _on_add_reminder(self) -> None:
        plan = self._current_plan()
        if plan is None:
            # 先保存一次计划
            self._on_save_plan()
            plan = self._current_plan()
            if plan is None:
                return
        dlg = _ReminderDialog(parent=self.window())
        if dlg.exec():
            plan.reminders.append(dlg.result_reminder())
            self._svc.save_plan(plan)
            self._refresh_reminders(plan)

    def _on_edit_reminder(self) -> None:
        plan = self._current_plan()
        if plan is None:
            return
        item = self._rem_list.currentItem()
        if item is None:
            return
        rid = item.data(Qt.ItemDataRole.UserRole)
        reminder = next((r for r in plan.reminders if r.id == rid), None)
        if reminder is None:
            return
        dlg = _ReminderDialog(reminder=reminder, parent=self.window())
        if dlg.exec():
            plan.reminders = [
                (dlg.result_reminder() if r.id == rid else r)
                for r in plan.reminders
            ]
            self._svc.save_plan(plan)
            self._refresh_reminders(plan)

    def _on_delete_reminder(self) -> None:
        plan = self._current_plan()
        if plan is None:
            return
        item = self._rem_list.currentItem()
        if item is None:
            return
        rid = item.data(Qt.ItemDataRole.UserRole)
        plan.reminders = [r for r in plan.reminders if r.id != rid]
        self._svc.save_plan(plan)
        self._refresh_reminders(plan)


# ─────────────────────────────────────────────────────────────────────────── #
# 侧边栏主面板
# ─────────────────────────────────────────────────────────────────────────── #

class ExamSidebarPanel(QWidget):
    """考试面板侧边栏，包含科目管理、预设管理、考试规划三个 Tab。

    使用 qfluentwidgets Pivot 作为选项卡导航。
    """

    def __init__(self, svc, parent=None):
        super().__init__(parent)
        self.setObjectName("examSidebarPanel")
        self.setStyleSheet("QWidget#examSidebarPanel { background: transparent; }")
        self._svc = svc

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── 标题行 ─────────────────────────────────────────────────────── #
        header = QWidget()
        header.setFixedHeight(52)
        hb = QHBoxLayout(header)
        hb.setContentsMargins(20, 0, 16, 0)
        hb.addWidget(SubtitleLabel("考试面板"))
        hb.addStretch()
        root.addWidget(header)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: rgba(128,128,128,60);")
        root.addWidget(sep)

        # ── Pivot 导航 ─────────────────────────────────────────────────── #
        self._pivot = Pivot()
        self._pivot.setContentsMargins(12, 0, 12, 0)
        root.addWidget(self._pivot)

        # ── 内容区（QStackedWidget） ───────────────────────────────────── #
        self._stack = QStackedWidget()
        self._stack.setStyleSheet("QStackedWidget { background: transparent; }")
        root.addWidget(self._stack, 1)

        self._subject_tab = _SubjectTab(svc)
        self._preset_tab  = _PresetTab(svc)
        self._plan_tab    = _PlanTab(svc)

        self._subject_page = _make_scroll_page(self._subject_tab, self)
        self._preset_page  = _make_scroll_page(self._preset_tab, self)
        self._plan_page    = _make_scroll_page(self._plan_tab, self)

        _tabs = [
            ("subject", "科目", self._subject_page),
            ("preset",  "绑定", self._preset_page),
            ("plan",    "规划", self._plan_page),
        ]
        for key, label, widget in _tabs:
            self._stack.addWidget(widget)
            self._pivot.addItem(
                routeKey=key,
                text=label,
                onClick=lambda checked, w=widget: self._stack.setCurrentWidget(w),
            )

        # 默认显示第一个
        self._pivot.setCurrentItem("subject")
        self._stack.setCurrentWidget(self._subject_page)

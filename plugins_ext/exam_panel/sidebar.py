"""考试面板插件 — 侧边栏面板

包含三个 Tab：
  科目管理   — 新建/编辑/删除科目
  预设管理   — 命名布局预设、绑定科目、设置默认预设
  考试规划   — 给每个科目配置时间段、张数、提醒
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QTime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget,
    QFrame, QFormLayout,
)
from qfluentwidgets import (
    FluentIcon as FIF,
    PushButton,
    BodyLabel, StrongBodyLabel, SubtitleLabel,
    LineEdit, SpinBox, ComboBox, TimePicker,
    CheckBox,
    ListWidget,
    InfoBar, InfoBarPosition, MessageBox,
    Pivot,
)

from PySide6.QtWidgets import QListWidgetItem

from .models import ExamSubject, ExamPlan, ExamReminder, LayoutPreset


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

        form = QFormLayout()
        form.setVerticalSpacing(10)

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

        form.addRow("科目名称:", self._name_edit)
        form.addRow("主题颜色:", self._color_combo)

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


class _PresetDialog(MessageBox):
    """新建/编辑预设对话框（仅名称和描述）。"""

    def __init__(self, preset: Optional[LayoutPreset] = None, parent=None):
        title = "编辑预设" if preset else "新建预设"
        super().__init__(title, "", parent)
        self.yesButton.setText("保存")
        self.cancelButton.setText("取消")
        self.contentLabel.hide()

        self._preset = preset or LayoutPreset()

        form = QFormLayout()
        form.setVerticalSpacing(10)
        self._name_edit = LineEdit()
        self._name_edit.setPlaceholderText("预设名称")
        self._name_edit.setText(self._preset.name)
        self._desc_edit = LineEdit()
        self._desc_edit.setPlaceholderText("可选说明")
        self._desc_edit.setText(self._preset.description)
        form.addRow("预设名称:", self._name_edit)
        form.addRow("说明:", self._desc_edit)
        self.textLayout.addLayout(form)

    def accept(self) -> None:
        name = self._name_edit.text().strip()
        if not name:
            InfoBar.warning("提示", "预设名称不能为空", duration=2000, parent=self,
                            position=InfoBarPosition.TOP)
            return
        self._preset.name        = name
        self._preset.description = self._desc_edit.text().strip()
        super().accept()

    def result_preset(self) -> LayoutPreset:
        return self._preset


class _ReminderDialog(MessageBox):
    """新建/编辑提醒项对话框。"""

    def __init__(self, reminder: Optional[ExamReminder] = None, parent=None):
        title = "编辑提醒" if reminder else "新建提醒"
        super().__init__(title, "", parent)
        self.yesButton.setText("保存")
        self.cancelButton.setText("取消")
        self.contentLabel.hide()

        self._reminder = reminder or ExamReminder()

        form = QFormLayout()
        form.setVerticalSpacing(10)

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

        form.addRow("提前时间:", self._min_spin)
        form.addRow("提醒方式:", self._mode_combo)
        form.addRow("", self._flash_cb)
        form.addRow("自定义文字:", self._msg_edit)
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
    def __init__(self, svc, zone_id_provider, parent=None):
        """
        Parameters
        ----------
        zone_id_provider : Callable[[], str]
            返回当前活动 zone_id 的函数（用于"保存当前布局"）。
        """
        super().__init__(parent)
        self._svc              = svc
        self._zone_id_provider = zone_id_provider

        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(12, 12, 12, 12)
        vbox.setSpacing(8)

        # 顶部操作
        top = QHBoxLayout()
        self._save_cur_btn = PushButton(FIF.SAVE,  "保存当前布局到预设")
        self._save_cur_btn.clicked.connect(self._on_save_current)
        top.addWidget(self._save_cur_btn)
        top.addStretch()
        vbox.addLayout(top)

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
        self._apply_btn  = PushButton(FIF.PLAY,   "应用")
        self._rename_btn = PushButton(FIF.EDIT,   "重命名")
        self._bind_btn   = PushButton(FIF.LINK,   "绑定科目")
        self._del_btn    = PushButton(FIF.DELETE, "删除")
        for b in (self._apply_btn, self._rename_btn, self._bind_btn, self._del_btn):
            bot.addWidget(b)
        bot.addStretch()
        vbox.addLayout(bot)

        self._apply_btn.clicked.connect(self._on_apply)
        self._rename_btn.clicked.connect(self._on_rename)
        self._bind_btn.clicked.connect(self._on_bind)
        self._del_btn.clicked.connect(self._on_delete)

        svc.preset_updated.connect(self._refresh)
        svc.subjects_updated.connect(self._refresh)
        svc.active_preset_changed.connect(lambda *_: self._refresh())
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
        current_zone_id = self._zone_id_provider() or ""
        current_preset_id = self._svc.get_current_preset_id(current_zone_id) if current_zone_id else ""
        default_preset = self._svc.get_default_preset()
        for preset in self._svc.presets():
            text = preset.name
            # 显示绑定的科目
            bindings = [
                b for b in self._svc.bindings()
                if b.preset_id == preset.id
            ]
            if bindings:
                subj_names = []
                for b in bindings:
                    s = self._svc.get_subject(b.subject_id)
                    if s:
                        subj_names.append(s.name)
                if subj_names:
                    text += f"  [→ {', '.join(subj_names)}]"
            if default_preset and preset.id == default_preset.id:
                text += "  [默认]"
            if current_preset_id and preset.id == current_preset_id:
                text += "  [当前]"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, preset.id)
            self._list.addItem(item)

    def _selected_id(self) -> Optional[str]:
        item = self._list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _on_default_changed(self, idx: int) -> None:
        pid = self._default_combo.itemData(idx) or ""
        self._svc.set_default_preset(pid)

    def _on_save_current(self) -> None:
        zone_id = self._zone_id_provider()
        if not zone_id:
            InfoBar.warning("提示", "请先打开一个全屏时钟", duration=2500,
                            parent=self.window(), position=InfoBarPosition.BOTTOM)
            return
        # 读取当前布局
        try:
            configs = self._svc._api.get_canvas_layout(zone_id)
        except Exception:
            InfoBar.error("错误", "无法读取当前布局", duration=2500,
                          parent=self.window(), position=InfoBarPosition.BOTTOM)
            return

        # 询问预设名称（简单选择：新建或覆盖）
        dlg = _PresetDialog(parent=self.window())
        if not dlg.exec():
            return
        preset = dlg.result_preset()
        preset.zone_id = zone_id
        preset.configs = configs
        self._svc.save_preset(preset)
        self._svc.apply_preset(preset.id, zone_id)
        if self._svc.current_subject_id:
            self._svc.set_current_subject(self._svc.current_subject_id, zone_id, apply_preset=False)
        InfoBar.success("已保存", f"预设「{preset.name}」已保存", duration=2500,
                        parent=self.window(), position=InfoBarPosition.BOTTOM)

    def _on_apply(self) -> None:
        pid = self._selected_id()
        if not pid:
            return
        zone_id = self._zone_id_provider()
        if not zone_id:
            InfoBar.warning("提示", "请先打开一个全屏时钟", duration=2500,
                            parent=self.window(), position=InfoBarPosition.BOTTOM)
            return
        ok = self._svc.apply_preset(pid, zone_id)
        if ok:
            if self._svc.current_subject_id:
                self._svc.set_current_subject(
                    self._svc.current_subject_id,
                    zone_id,
                    apply_preset=False,
                )
            InfoBar.success("已应用", "预设已切换", duration=2000,
                            parent=self.window(), position=InfoBarPosition.BOTTOM)

    def _on_rename(self) -> None:
        pid = self._selected_id()
        if not pid:
            return
        preset = self._svc.get_preset(pid)
        if not preset:
            return
        dlg = _PresetDialog(preset=preset, parent=self.window())
        if dlg.exec():
            self._svc.save_preset(dlg.result_preset())

    def _on_bind(self) -> None:
        """将预设绑定到某个科目。"""
        pid = self._selected_id()
        if not pid:
            return
        subjects = self._svc.subjects()
        if not subjects:
            InfoBar.warning("提示", "请先创建科目", duration=2500,
                            parent=self.window(), position=InfoBarPosition.BOTTOM)
            return

        # 简单的科目选择弹窗
        box = MessageBox("绑定科目", "选择要与此预设绑定的科目：", self.window())
        box.yesButton.setText("绑定")
        box.cancelButton.setText("取消")
        box.contentLabel.hide()

        combo = ComboBox()
        combo.addItem("（解除绑定）", userData="")
        for s in subjects:
            combo.addItem(s.name, userData=s.id)

        box.textLayout.addWidget(combo)
        if box.exec():
            subject_id = combo.currentData() or ""
            if subject_id:
                self._svc.set_binding(subject_id, pid)
            else:
                # 解除所有绑定该预设的科目
                for b in list(self._svc.bindings()):
                    if b.preset_id == pid:
                        self._svc.set_binding(b.subject_id, "", b.zone_id)

    def _on_delete(self) -> None:
        pid = self._selected_id()
        if not pid:
            return
        preset = self._svc.get_preset(pid)
        if not preset:
            return
        box = MessageBox("确认删除",
                         f"确定删除预设「{preset.name}」？\n\n已绑定此预设的科目将解除绑定。",
                         self.window())
        box.yesButton.setText("删除")
        box.cancelButton.setText("取消")
        if box.exec():
            self._svc.delete_preset(pid)


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
        form = QFormLayout()
        form.setVerticalSpacing(8)

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

        self._ans_page_spin = SpinBox()
        self._ans_page_spin.setRange(0, 999)
        self._ans_page_spin.setSuffix(" 页")

        self._paper_count_spin = SpinBox()
        self._paper_count_spin.setRange(0, 999)
        self._paper_count_spin.setSuffix(" 张")

        self._paper_page_spin = SpinBox()
        self._paper_page_spin.setRange(0, 999)
        self._paper_page_spin.setSuffix(" 页")

        self._prep_spin   = SpinBox()
        self._prep_spin.setRange(0, 30)
        self._prep_spin.setSuffix(" 分钟")
        self._prep_spin.setToolTip("提前进入准备状态")

        form.addRow("考试时间段:", time_row)
        form.addRow("答题卡张数:", self._ans_count_spin)
        form.addRow("答题卡页数:", self._ans_page_spin)
        form.addRow("试卷张数:",   self._paper_count_spin)
        form.addRow("试卷页数:",   self._paper_page_spin)
        form.addRow("提前准备:",   self._prep_spin)
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
        root.addWidget(self._stack, 1)

        self._subject_tab = _SubjectTab(svc)
        self._preset_tab  = _PresetTab(svc, zone_id_provider=lambda: svc.current_zone_id)
        self._plan_tab    = _PlanTab(svc)

        _tabs = [
            ("subject", "科目", self._subject_tab),
            ("preset",  "预设", self._preset_tab),
            ("plan",    "规划", self._plan_tab),
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
        self._stack.setCurrentWidget(self._subject_tab)

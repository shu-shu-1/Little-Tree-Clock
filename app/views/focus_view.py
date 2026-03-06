"""专注时钟视图（番茄钟++）"""
from __future__ import annotations

import uuid
from typing import Optional

from PySide6.QtCore import Qt, Signal, Slot, QRectF
from PySide6.QtGui import QPainter, QColor, QPen, QFont
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QWidget,
    QSizePolicy, QButtonGroup, QRadioButton,
    QAbstractItemView,
)
from qfluentwidgets import (
    FluentIcon as FIF, PushButton, ToolButton,
    BodyLabel, CaptionLabel, StrongBodyLabel,
    CardWidget, LineEdit, SpinBox,
    InfoBar, InfoBarPosition, MessageBox,
    ComboBox, CheckBox,
    ListWidget, PrimaryPushButton, TransparentPushButton,
    isDarkTheme, qconfig, TitleLabel,
)

from app.models.focus_model import FocusPreset, FocusRule, AlertMode, FocusStore
from app.services.focus_service import FocusService, FocusPhase
from app.services.notification_service import NotificationService
from app.services.settings_service import SettingsService
from app.services.i18n_service import I18nService
from app.services import ringtone_service as rs
from app.utils.logger import logger


# ──────────────────────────────────────────────────────────────────────────── #
# 圆形进度 Widget
# ──────────────────────────────────────────────────────────────────────────── #

class CircleProgress(QWidget):
    """极简圆形进度显示"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._progress  = 0.0    # 0.0~1.0
        self._text      = "00:00"
        self._sub_text  = ""
        self._color     = QColor("#0078d4")
        self._distracted = False
        self.setMinimumSize(200, 200)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._i18n = I18nService.instance()
        self._sub_text = self._i18n.t("focus.phase.focusing")
        # 主题切换时重绘
        qconfig.themeChanged.connect(self.update)

    def set_progress(self, progress: float, text: str, sub_text: str = "") -> None:
        self._progress = max(0.0, min(1.0, progress))
        self._text     = text
        self._sub_text = sub_text
        self.update()

    def set_distracted(self, is_distracted: bool) -> None:
        self._distracted = is_distracted
        self._color = QColor("#e81123") if is_distracted else QColor("#0078d4")
        self.update()

    def set_phase_color(self, phase: FocusPhase) -> None:
        if phase == FocusPhase.BREAK:
            self._color = QColor("#107c10")
        elif phase == FocusPhase.FOCUS:
            self._color = QColor("#0078d4")
        else:
            self._color = QColor("#888888")
        self._distracted = False
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        size  = min(w, h) - 20
        x     = (w - size) / 2
        y     = (h - size) / 2
        rect  = QRectF(x, y, size, size)
        thick = max(8, size * 0.06)

        # 背景圆
        track_color = QColor("#555555") if isDarkTheme() else QColor("#e0e0e0")
        bg_pen = QPen(track_color, thick)
        bg_pen.setCapStyle(Qt.RoundCap)
        painter.setPen(bg_pen)
        painter.drawArc(rect.adjusted(thick/2, thick/2, -thick/2, -thick/2),
                        90 * 16, -360 * 16)

        # 进度弧
        if self._progress > 0:
            prog_pen = QPen(self._color, thick)
            prog_pen.setCapStyle(Qt.RoundCap)
            painter.setPen(prog_pen)
            span = -int(self._progress * 360 * 16)
            painter.drawArc(rect.adjusted(thick/2, thick/2, -thick/2, -thick/2),
                            90 * 16, span)

        # 主时间文字
        font = QFont()
        font.setPointSize(max(14, int(size * 0.14)))
        font.setBold(True)
        painter.setFont(font)
        text_color = QColor("#f0f0f0") if isDarkTheme() else QColor("#1a1a1a")
        painter.setPen(QPen(text_color, 1))
        painter.drawText(rect, Qt.AlignCenter | Qt.AlignVCenter, self._text)

        # 副文字
        if self._sub_text:
            sub_rect = QRectF(x, y + size * 0.58, size, size * 0.15)
            font2 = QFont()
            font2.setPointSize(max(9, int(size * 0.075)))
            painter.setFont(font2)
            painter.setPen(QPen(self._color, 1))
            painter.drawText(sub_rect, Qt.AlignCenter, self._sub_text)

        painter.end()


# ──────────────────────────────────────────────────────────────────────────── ## 不专注全屏提醒
# ──────────────────────────────────────────────────────────────────────────────── #

class FocusDistractedAlert(QWidget):
    """不专注全屏提醒窗口（仿闹钟全屏），用户点击"继续专注"后关闭"""

    dismissed = Signal()   # 用户主动关闭

    def __init__(self, preset_name: str, rule_hint: str, distracted_sec: int, parent=None):
        super().__init__(parent)
        self._preset_name   = preset_name
        self._rule_hint     = rule_hint
        self._distracted_sec = distracted_sec
        self._i18n          = I18nService.instance()

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._build_ui()

    def _build_ui(self) -> None:
        from PySide6.QtWidgets import QPushButton, QLabel
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setContentsMargins(0, 0, 0, 0)

        inner = QWidget()
        inner.setFixedWidth(400)
        inner.setStyleSheet("background: transparent;")
        il = QVBoxLayout(inner)
        il.setSpacing(16)
        il.setContentsMargins(0, 0, 0, 0)
        il.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon_lbl = QLabel("⚠️")
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet("font-size: 64px; background: transparent;")
        il.addWidget(icon_lbl)

        title_lbl = QLabel(self._i18n.t("focus.distraction_warning"))
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_lbl.setStyleSheet(
            "font-size: 28px; font-weight: bold; color: #ff6b6b;"
            " background: transparent;"
        )
        il.addWidget(title_lbl)

        preset_lbl = QLabel(self._preset_name)
        preset_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preset_lbl.setStyleSheet(
            "font-size: 18px; color: rgba(255,255,255,200);"
            " background: transparent;"
        )
        il.addWidget(preset_lbl)

        hint_lbl = QLabel(f"{self._rule_hint}，{self._i18n.t('focus.distracted_time', f'已不专注 {self._distracted_sec} 秒')}")
        hint_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint_lbl.setWordWrap(True)
        hint_lbl.setStyleSheet(
            "font-size: 15px; color: rgba(255,255,255,170);"
            " background: transparent;"
        )
        il.addWidget(hint_lbl)

        il.addSpacing(24)

        resume_btn = QPushButton("▶  继续专注")
        resume_btn.setFixedSize(180, 54)
        resume_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        resume_btn.setStyleSheet(
            "QPushButton {"
            "  background: rgba(255,255,255,220); color: #1a1a1a;"
            "  border-radius: 27px; font-size: 16px; font-weight: 600; border: none;"
            "}"
            "QPushButton:hover { background: white; }"
            "QPushButton:pressed { background: rgba(220,220,220,210); }"
        )
        resume_btn.clicked.connect(self._on_dismiss)
        il.addWidget(resume_btn, 0, Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(inner, 0, Qt.AlignmentFlag.AlignCenter)

    def show_fullscreen(self) -> None:
        from PySide6.QtWidgets import QApplication
        screen = QApplication.primaryScreen()
        if screen:
            self.setGeometry(screen.geometry())
        self.show()
        self.raise_()
        self.activateWindow()

    def _on_dismiss(self) -> None:
        self.close()
        self.dismissed.emit()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self._on_dismiss()

    def paintEvent(self, event) -> None:  # noqa: N802
        from PySide6.QtGui import QPainter, QColor
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(20, 8, 8, 220))
        super().paintEvent(event)


# ──────────────────────────────────────────────────────────────────────────────── ## 专注规则编辑对话框（从预设编辑对话框分离）
# ──────────────────────────────────────────────────────────────────────────── #

class FocusRuleDialog(MessageBox):
    """专注检测规则 / 提醒设置对话框"""

    def __init__(
        self,
        rule_data: dict,
        parent=None,
    ):
        self._i18n = I18nService.instance()
        super().__init__(self._i18n.t("focus.edit_rule"), "", parent)
        self.yesButton.setText(self._i18n.t("common.ok"))
        self.cancelButton.setText(self._i18n.t("common.cancel"))
        self.contentLabel.hide()

        form = QWidget()
        fl   = QVBoxLayout(form)
        fl.setSpacing(10)
        fl.setContentsMargins(0, 0, 0, 0)

        # ── 专注规则 ──────────────────────────────────────────────
        fl.addWidget(StrongBodyLabel(self._i18n.t("focus.rule_name")))
        rule_group = QButtonGroup(form)

        self._rb_must_use = QRadioButton(self._i18n.t("focus.must_use_pc") + "（" + self._i18n.t("focus.no_activity_hint", "无活动则提醒") + "）")
        self._rb_focused  = QRadioButton(self._i18n.t("focus.focus_on_app", "专注于特定程序") + "（" + self._i18n.t("focus.app_lost_hint", "焦点离开则提醒") + "）")
        self._rb_no_use   = QRadioButton(self._i18n.t("focus.no_pc_use"))

        rule_group.addButton(self._rb_must_use, 0)
        rule_group.addButton(self._rb_focused,  1)
        rule_group.addButton(self._rb_no_use,   2)
        self._rb_must_use.setChecked(True)

        fl.addWidget(self._rb_must_use)

        # 程序名行（FOCUSED_APP 时可见）
        app_row = QHBoxLayout()
        app_row.addSpacing(20)
        app_row.addWidget(BodyLabel("程序窗口标题关键词："))
        self._app_edit = LineEdit()
        self._app_edit.setPlaceholderText("例如：Chrome / 代码 / Notepad")
        app_row.addWidget(self._app_edit, 1)
        self._app_row_widget = QWidget()
        self._app_row_widget.setLayout(app_row)
        self._app_row_widget.setVisible(False)

        fl.addWidget(self._rb_focused)
        fl.addWidget(self._app_row_widget)
        fl.addWidget(self._rb_no_use)

        self._rb_focused.toggled.connect(self._app_row_widget.setVisible)

        # 容忍秒数
        tol_row = QHBoxLayout()
        tol_row.addWidget(BodyLabel("容忍不专注秒数（超过后提醒）："))
        self._tol_spin = SpinBox()
        self._tol_spin.setRange(5, 3600)
        self._tol_spin.setValue(30)
        tol_row.addWidget(self._tol_spin)
        fl.addLayout(tol_row)

        # ── 不专注提醒 ────────────────────────────────────────────
        fl.addWidget(StrongBodyLabel(self._i18n.t("focus.distraction_warning")))

        alert_row = QHBoxLayout()
        alert_row.addWidget(BodyLabel(self._i18n.t("focus.alert_method", "提醒方式：")))
        self._alert_combo = ComboBox()
        self._alert_combo.addItem(self._i18n.t("focus.notification_alert"), userData=AlertMode.NOTIFICATION.value)
        self._alert_combo.addItem(self._i18n.t("focus.fullscreen_alert"), userData=AlertMode.FULLSCREEN.value)
        alert_row.addWidget(self._alert_combo, 1)
        fl.addLayout(alert_row)

        # 不专注时暂停计时
        self._pause_on_distracted_cb = CheckBox(self._i18n.t("focus.pause_on_distract"))
        fl.addWidget(self._pause_on_distracted_cb)

        self.textLayout.addWidget(form)

        # ── 填入现有数据 ──────────────────────────────────────────
        rule_val = rule_data.get("rule", FocusRule.MUST_USE_PC)
        rule_map = {
            FocusRule.MUST_USE_PC: self._rb_must_use,
            FocusRule.FOCUSED_APP: self._rb_focused,
            FocusRule.NO_PC_USE:   self._rb_no_use,
        }
        rb = rule_map.get(rule_val)
        if rb:
            rb.setChecked(True)

        self._app_edit.setText(rule_data.get("app_name_filter", ""))
        self._tol_spin.setValue(rule_data.get("tolerance_sec", 30))

        # 确保用纯 str 比较（AlertMode 为 str Enum，Qt findData 按类型比较）
        alert_val = str(getattr(rule_data.get("alert_mode", AlertMode.NOTIFICATION), "value",
                                rule_data.get("alert_mode", AlertMode.NOTIFICATION)))
        idx = self._alert_combo.findData(alert_val)
        if idx >= 0:
            self._alert_combo.setCurrentIndex(idx)

        self._pause_on_distracted_cb.setChecked(rule_data.get("pause_on_distracted", False))

    def get_data(self) -> dict:
        """返回规则相关字段字典"""
        if self._rb_focused.isChecked():
            rule = FocusRule.FOCUSED_APP
        elif self._rb_no_use.isChecked():
            rule = FocusRule.NO_PC_USE
        else:
            rule = FocusRule.MUST_USE_PC

        return dict(
            rule=rule,
            app_name_filter=self._app_edit.text().strip(),
            tolerance_sec=self._tol_spin.value(),
            alert_mode=self._alert_combo.currentData() or AlertMode.NOTIFICATION.value,
            pause_on_distracted=self._pause_on_distracted_cb.isChecked(),
        )


# ──────────────────────────────────────────────────────────────────────────── #
# 预设编辑对话框
# ──────────────────────────────────────────────────────────────────────────── #

class PresetDialog(MessageBox):
    """新建 / 编辑专注预设"""

    _DEFAULT_RULE_DATA = dict(
        rule=FocusRule.MUST_USE_PC,
        app_name_filter="",
        tolerance_sec=30,
        alert_mode=AlertMode.NOTIFICATION,
        pause_on_distracted=False,
    )

    def __init__(
        self,
        preset: Optional[FocusPreset] = None,
        parent=None,
    ):
        self._i18n = I18nService.instance()
        title = self._i18n.t("focus.edit_preset") if preset else self._i18n.t("focus.new_preset")
        super().__init__(title, "", parent)
        self.yesButton.setText(self._i18n.t("common.save"))
        self.cancelButton.setText(self._i18n.t("common.cancel"))
        self.contentLabel.hide()

        # 规则相关字段缓存（由 FocusRuleDialog 填写）
        self._rule_data: dict = dict(self._DEFAULT_RULE_DATA)

        form = QWidget()
        fl   = QVBoxLayout(form)
        fl.setSpacing(10)
        fl.setContentsMargins(0, 0, 0, 0)

        # 名称
        row = QHBoxLayout()
        row.addWidget(BodyLabel(self._i18n.t("focus.preset_name", "预设名称：")))
        self._name_edit = LineEdit()
        self._name_edit.setPlaceholderText(self._i18n.t("focus.my_focus"))
        row.addWidget(self._name_edit, 1)
        fl.addLayout(row)

        # 专注时长
        row2 = QHBoxLayout()
        row2.addWidget(BodyLabel(self._i18n.t("focus.duration", "专注时长（分钟）：")))
        self._focus_spin = SpinBox()
        self._focus_spin.setRange(1, 240)
        self._focus_spin.setValue(25)
        row2.addWidget(self._focus_spin)
        fl.addLayout(row2)

        # 休息时长
        row3 = QHBoxLayout()
        row3.addWidget(BodyLabel(self._i18n.t("focus.break_duration", "休息时长（分钟）：")))
        self._break_spin = SpinBox()
        self._break_spin.setRange(0, 60)
        self._break_spin.setValue(5)
        row3.addWidget(self._break_spin)
        fl.addLayout(row3)

        # 循环次数
        row4 = QHBoxLayout()
        row4.addWidget(BodyLabel("循环次数（0=无限）："))
        self._cycles_spin = SpinBox()
        self._cycles_spin.setRange(0, 99)
        self._cycles_spin.setValue(4)
        row4.addWidget(self._cycles_spin)
        fl.addLayout(row4)

        # 检测专注状态 + 编辑规则按钮
        detect_row = QHBoxLayout()
        self._detect_focus_cb = CheckBox(self._i18n.t("focus.detect_focus"))
        self._detect_focus_cb.setChecked(True)
        detect_row.addWidget(self._detect_focus_cb)
        detect_row.addStretch(1)
        self._edit_rule_btn = PushButton(FIF.EDIT, self._i18n.t("focus.rule_editor"))
        detect_row.addWidget(self._edit_rule_btn)
        fl.addLayout(detect_row)

        self._detect_focus_cb.checkStateChanged.connect(self._on_detect_focus_changed)
        self._edit_rule_btn.clicked.connect(self._open_rule_dialog)

        # 铃声设置
        fl.addWidget(StrongBodyLabel(self._i18n.t("focus.ringtone_settings")))
        _settings = SettingsService.instance()
        _ringtones = _settings.ringtones

        bs_row = QHBoxLayout()
        bs_row.addWidget(BodyLabel("休息开始铃声："))
        self._break_start_combo = rs.make_sound_combo(_ringtones)
        bs_row.addWidget(self._break_start_combo, 1)
        fl.addLayout(bs_row)

        be_row = QHBoxLayout()
        be_row.addWidget(BodyLabel("休息结束铃声："))
        self._break_end_combo = rs.make_sound_combo(_ringtones)
        be_row.addWidget(self._break_end_combo, 1)
        fl.addLayout(be_row)

        self.textLayout.addWidget(form)

        # 填入现有数据
        if preset:
            self._name_edit.setText(preset.name)
            self._focus_spin.setValue(preset.focus_minutes)
            self._break_spin.setValue(preset.break_minutes)
            self._cycles_spin.setValue(preset.cycles)
            self._detect_focus_cb.setChecked(preset.detect_focus)
            self._rule_data = dict(
                rule=preset.rule,
                app_name_filter=preset.app_name_filter,
                tolerance_sec=preset.tolerance_sec,
                alert_mode=preset.alert_mode,
                pause_on_distracted=preset.pause_on_distracted,
            )
            self._on_detect_focus_changed()

            for combo, val in [
                (self._break_start_combo, preset.break_start_sound),
                (self._break_end_combo,   preset.break_end_sound),
            ]:
                if val:
                    rs.set_combo_sound(combo, val)

        # 兜底：确保按钮可见性与复选框状态一致
        self._edit_rule_btn.setVisible(self._detect_focus_cb.isChecked())

    def _on_detect_focus_changed(self) -> None:
        self._edit_rule_btn.setVisible(self._detect_focus_cb.isChecked())

    def _open_rule_dialog(self) -> None:
        dlg = FocusRuleDialog(self._rule_data, parent=self)
        if dlg.exec():
            self._rule_data = dlg.get_data()

    def get_preset(self, existing_id: str = "") -> FocusPreset:
        """读取表单，返回 FocusPreset 实例"""
        rd = self._rule_data
        return FocusPreset(
            id=existing_id if existing_id else str(uuid.uuid4()),
            name=self._name_edit.text().strip() or self._i18n.t("focus.new_preset_name"),
            focus_minutes=self._focus_spin.value(),
            break_minutes=self._break_spin.value(),
            cycles=self._cycles_spin.value(),
            detect_focus=self._detect_focus_cb.isChecked(),
            rule=rd.get("rule", FocusRule.MUST_USE_PC),
            app_name_filter=rd.get("app_name_filter", ""),
            tolerance_sec=rd.get("tolerance_sec", 30),
            alert_mode=rd.get("alert_mode", AlertMode.NOTIFICATION),
            pause_on_distracted=rd.get("pause_on_distracted", False),
            break_start_sound=rs.get_combo_sound(self._break_start_combo),
            break_end_sound=rs.get_combo_sound(self._break_end_combo),
        )


# ──────────────────────────────────────────────────────────────────────────── #
# 主专注视图
# ──────────────────────────────────────────────────────────────────────────── #

class FocusView(QWidget):
    """专注时钟主视图"""

    def __init__(
        self,
        focus_service: FocusService,
        notif_service: NotificationService,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("focusView")
        self.setAutoFillBackground(False)

        self._svc   = focus_service
        self._notif = notif_service
        self._store = FocusStore()
        self._i18n  = I18nService.instance()
        self._distracted_alert_win: Optional[FocusDistractedAlert] = None
        self._active_preset: Optional[FocusPreset] = None

        # ---------------------------------------------------------------- #
        # 外层：标题 + 水平内容
        # ---------------------------------------------------------------- #
        _outer = QVBoxLayout(self)
        _outer.setContentsMargins(16, 16, 16, 16)
        _outer.setSpacing(12)

        _outer.addWidget(TitleLabel(self._i18n.t("focus.title")))

        # ---------------------------------------------------------------- #
        # 内层布局：左侧预设列表 + 右侧主面板
        # ---------------------------------------------------------------- #
        root = QHBoxLayout()
        root.setSpacing(16)

        # ── 左侧：预设列表 ──────────────────────────────────────────────
        left_card = CardWidget()
        left_layout = QVBoxLayout(left_card)
        left_layout.setContentsMargins(12, 12, 12, 12)
        left_layout.setSpacing(8)
        left_card.setFixedWidth(220)

        left_label = StrongBodyLabel(self._i18n.t("focus.preset_list"))
        left_layout.addWidget(left_label)

        self._preset_list = ListWidget()
        self._preset_list.setFocusPolicy(Qt.NoFocus)
        self._preset_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self._preset_list.currentRowChanged.connect(self._on_preset_selected)
        left_layout.addWidget(self._preset_list, 1)

        preset_btn_row = QHBoxLayout()
        add_btn  = ToolButton(FIF.ADD)
        edit_btn = ToolButton(FIF.EDIT)
        del_btn  = ToolButton(FIF.DELETE)
        add_btn.clicked.connect(self._on_add_preset)
        edit_btn.clicked.connect(self._on_edit_preset)
        del_btn.clicked.connect(self._on_delete_preset)
        preset_btn_row.addWidget(add_btn)
        preset_btn_row.addWidget(edit_btn)
        preset_btn_row.addWidget(del_btn)
        preset_btn_row.addStretch()
        left_layout.addLayout(preset_btn_row)

        root.addWidget(left_card)

        # ── 右侧：主面板 ────────────────────────────────────────────────
        right = QVBoxLayout()
        right.setSpacing(12)

        # 圆形进度 + 状态信息
        progress_card = CardWidget()
        prog_layout = QVBoxLayout(progress_card)
        prog_layout.setAlignment(Qt.AlignCenter)
        prog_layout.setContentsMargins(20, 20, 20, 20)
        prog_layout.setSpacing(8)

        self._circle = CircleProgress()
        self._circle.setMinimumSize(220, 220)
        self._circle.setMaximumSize(280, 280)
        prog_layout.addWidget(self._circle, alignment=Qt.AlignCenter)

        # 循环计数 & 状态
        status_row = QHBoxLayout()
        self._cycle_label    = BodyLabel("—")
        self._distract_label = CaptionLabel("")
        self._distract_label.setStyleSheet("color: #e81123;")
        status_row.addStretch()
        status_row.addWidget(self._cycle_label)
        status_row.addSpacing(12)
        status_row.addWidget(self._distract_label)
        status_row.addStretch()
        prog_layout.addLayout(status_row)

        right.addWidget(progress_card, 2)

        # ── 预设信息卡 ──────────────────────────────────────────────────
        info_card = CardWidget()
        info_layout = QVBoxLayout(info_card)
        info_layout.setContentsMargins(16, 12, 16, 12)
        info_layout.setSpacing(4)

        self._preset_name_lbl  = StrongBodyLabel(self._i18n.t("focus.select_preset"))
        self._preset_info_lbl  = CaptionLabel("")
        info_layout.addWidget(self._preset_name_lbl)
        info_layout.addWidget(self._preset_info_lbl)
        right.addWidget(info_card)

        # ── 控制按钮 ────────────────────────────────────────────────────
        btn_card = CardWidget()
        btn_layout = QHBoxLayout(btn_card)
        btn_layout.setContentsMargins(16, 12, 16, 12)
        btn_layout.setSpacing(12)

        self._start_btn = PrimaryPushButton(FIF.PLAY, self._i18n.t("focus.start_focus"))
        self._pause_btn = PushButton(FIF.PAUSE, self._i18n.t("focus.pause"))
        self._stop_btn  = TransparentPushButton(FIF.CLOSE, self._i18n.t("focus.stop"))

        self._start_btn.setEnabled(False)
        self._pause_btn.setEnabled(False)
        self._stop_btn.setEnabled(False)

        self._start_btn.clicked.connect(self._on_start)
        self._pause_btn.clicked.connect(self._on_pause)
        self._stop_btn.clicked.connect(self._on_stop)

        btn_layout.addStretch()
        btn_layout.addWidget(self._start_btn)
        btn_layout.addWidget(self._pause_btn)
        btn_layout.addWidget(self._stop_btn)
        btn_layout.addStretch()
        right.addWidget(btn_card)

        root.addLayout(right, 1)
        _outer.addLayout(root, 1)

        # ---------------------------------------------------------------- #
        # 连接服务信号
        # ---------------------------------------------------------------- #
        self._svc.tick.connect(self._on_tick)
        self._svc.phaseChanged.connect(self._on_phase_changed)
        self._svc.distractedAlert.connect(self._on_distracted_alert)
        self._svc.distractedStateChanged.connect(self._on_distracted_state)
        self._svc.phaseFinished.connect(self._on_phase_finished)
        self._svc.sessionFinished.connect(self._on_session_finished)

        # ---------------------------------------------------------------- #
        # 初始化
        # ---------------------------------------------------------------- #
        self._preset_ids: list[str] = []   # 与列表行一一对应，替代 UserRole
        self._refresh_preset_list()
        self._update_circle_idle()
        # 如果已在运行（如从首页快速启动），同步一次 UI 状态
        self._sync_with_service()

    # ------------------------------------------------------------------ #
    # 内部状态同步
    # ------------------------------------------------------------------ #

    def showEvent(self, event) -> None:  # type: ignore[override]
        """\u5207换到本页时，同步服务状态到 UI（修复从首页启动后按钮失效问题）"""
        super().showEvent(event)
        self._sync_with_service()

    def _sync_with_service(self) -> None:
        """\u5c06按钮状态、预设选择等根据 FocusService 实际运行状能整乌。

        处理场景：从首页快速卡片启动专注会话后导航到本页。
        """
        if not self._svc.is_running:
            return
        # --- 服务正在运行 / 正在运行 ---
        svc_preset = self._svc.preset
        if svc_preset is not None and self._active_preset is None:
            # 尝试在列表中选中对应行
            if svc_preset.id in self._preset_ids:
                row = self._preset_ids.index(svc_preset.id)
                self._preset_list.blockSignals(True)
                self._preset_list.setCurrentRow(row)
                self._preset_list.blockSignals(False)
            self._active_preset = svc_preset
            self._update_preset_info(svc_preset)
        # --- 刷新按钮 ---
        self._start_btn.setEnabled(False)
        self._pause_btn.setEnabled(True)
        self._stop_btn.setEnabled(True)
        # 如果已暴暂停，把按钮扩为“继续”状态
        if not self._svc._timer.isActive() and self._svc.is_running:
            self._pause_btn.setIcon(FIF.PLAY)
            self._pause_btn.setText(self._i18n.t("focus.continue"))
            try:
                self._pause_btn.clicked.disconnect()
            except RuntimeError:
                pass
            self._pause_btn.clicked.connect(self._on_resume)
        else:
            self._pause_btn.setIcon(FIF.PAUSE)
            self._pause_btn.setText(self._i18n.t("focus.pause"))
            try:
                self._pause_btn.clicked.disconnect()
            except RuntimeError:
                pass
            self._pause_btn.clicked.connect(self._on_pause)

    # ------------------------------------------------------------------ #
    # 预设管理
    # ------------------------------------------------------------------ #

    def _refresh_preset_list(self) -> None:
        self._preset_list.clear()
        self._preset_ids = []
        for p in self._store.all():
            self._preset_list.addItem(p.name)
            self._preset_ids.append(p.id)

    def _selected_preset_id(self) -> Optional[str]:
        row = self._preset_list.currentRow()
        return self._preset_ids[row] if 0 <= row < len(self._preset_ids) else None

    def _selected_preset(self) -> Optional[FocusPreset]:
        pid = self._selected_preset_id()
        return self._store.get(pid) if pid else None

    @Slot(int)
    def _on_preset_selected(self, _row: int) -> None:
        pid = self._preset_ids[_row] if 0 <= _row < len(self._preset_ids) else None
        p   = self._store.get(pid) if pid else None
        logger.debug("[FocusView] 预设列表选中行号={} | pid={} | 预设名={}",
                     _row, pid, p.name if p else None)
        if p:
            self._active_preset = p
            self._update_preset_info(p)
        else:
            self._active_preset = None
        self._start_btn.setEnabled(bool(p) and not self._svc.is_running)

    def _update_preset_info(self, p: FocusPreset) -> None:
        self._preset_name_lbl.setText(p.name)
        cycles_text = f"{p.cycles} {self._i18n.t('focus.cycles_count')}" if p.cycles > 0 else self._i18n.t("focus.infinite")
        base = f"{self._i18n.t('focus.focus')} {p.focus_minutes}min · {self._i18n.t('focus.break')} {p.break_minutes}min · {cycles_text}"
        if p.detect_focus:
            rule_text = {
                FocusRule.MUST_USE_PC: self._i18n.t("focus.rule_must_use"),
                FocusRule.FOCUSED_APP: f"{self._i18n.t('focus.focusing_on', '专注于：')}{p.app_name_filter or self._i18n.t('focus.not_set', '（未设置）')}",
                FocusRule.NO_PC_USE:   self._i18n.t("focus.rule_no_use"),
            }.get(p.rule, p.rule)
            alert_text = self._i18n.t("focus.fullscreen_alert") if p.alert_mode == AlertMode.FULLSCREEN else self._i18n.t("focus.notification_only")
            pause_text = f" · {self._i18n.t('focus.pause_on_distract_short', '不专注暂停')}" if p.pause_on_distracted else ""
            detect_info = f" | {self._i18n.t('focus.rule', '规则：')}{rule_text} · {self._i18n.t('focus.tolerance', '容忍')}{p.tolerance_sec}s · {alert_text}{pause_text}"
        else:
            detect_info = f" | {self._i18n.t('focus.no_detect', '不检测专注状态')}"
        self._preset_info_lbl.setText(base + detect_info)

    @Slot()
    def _on_add_preset(self) -> None:
        dlg = PresetDialog(parent=self.window())
        if dlg.exec():
            preset = dlg.get_preset()
            self._store.add(preset)
            self._refresh_preset_list()
            # 选中新建的
            try:
                self._preset_list.setCurrentRow(self._preset_ids.index(preset.id))
            except ValueError:
                pass

    @Slot()
    def _on_edit_preset(self) -> None:
        p = self._active_preset
        if not p:
            InfoBar.warning(self._i18n.t("focus.warning"), self._i18n.t("focus.select_preset_first"), isClosable=True,
                            position=InfoBarPosition.TOP_RIGHT, duration=2000, parent=self.window())
            return
        dlg = PresetDialog(preset=p, parent=self.window())
        if dlg.exec():
            updated = dlg.get_preset(existing_id=p.id)
            self._store.update(updated)
            self._refresh_preset_list()
            # 重新选中
            try:
                self._preset_list.setCurrentRow(self._preset_ids.index(updated.id))
            except ValueError:
                pass

    @Slot()
    def _on_delete_preset(self) -> None:
        p = self._active_preset
        if not p:
            return
        box = MessageBox(self._i18n.t("focus.confirm_delete"), self._i18n.t("focus.delete_msg").format(name=p.name), self.window())
        if box.exec():
            self._store.remove(p.id)
            self._active_preset = None
            self._refresh_preset_list()
            self._preset_name_lbl.setText(self._i18n.t("focus.select_preset"))
            self._preset_info_lbl.setText("")
            self._start_btn.setEnabled(False)

    # ------------------------------------------------------------------ #
    # 会话控制
    # ------------------------------------------------------------------ #

    @Slot()
    def _on_start(self) -> None:
        p = self._active_preset
        if not p:
            return
        self._svc.start(p)
        self._start_btn.setEnabled(False)
        self._pause_btn.setEnabled(True)
        self._stop_btn.setEnabled(True)
        self._distract_label.setText("")

    @Slot()
    def _on_pause(self) -> None:
        if self._svc.is_running:
            self._svc.pause()
            self._pause_btn.setIcon(FIF.PLAY)
            self._pause_btn.setText(self._i18n.t("focus.continue"))
            self._pause_btn.clicked.disconnect()
            self._pause_btn.clicked.connect(self._on_resume)
        
    @Slot()
    def _on_resume(self) -> None:
        self._svc.resume()
        self._pause_btn.setIcon(FIF.PAUSE)
        self._pause_btn.setText(self._i18n.t("focus.pause"))
        self._pause_btn.clicked.disconnect()
        self._pause_btn.clicked.connect(self._on_pause)

    @Slot()
    def _on_stop(self) -> None:
        self._svc.stop()
        self._start_btn.setEnabled(True)
        self._pause_btn.setEnabled(False)
        self._pause_btn.setIcon(FIF.PAUSE)
        self._pause_btn.setText(self._i18n.t("focus.pause"))
        try:
            self._pause_btn.clicked.disconnect()
        except RuntimeError:
            pass
        self._pause_btn.clicked.connect(self._on_pause)
        self._stop_btn.setEnabled(False)
        self._update_circle_idle()
        self._cycle_label.setText("—")
        self._distract_label.setText("")

    # ------------------------------------------------------------------ #
    # 服务信号响应
    # ------------------------------------------------------------------ #

    @Slot(int, int, object)
    def _on_tick(self, elapsed_ms: int, remaining_ms: int, phase) -> None:
        if self._active_preset is None:
            return
        total_ms = (
            self._active_preset.focus_minutes * 60_000
            if phase == FocusPhase.FOCUS
            else self._active_preset.break_minutes * 60_000
        )
        progress = 1.0 - (remaining_ms / total_ms) if total_ms > 0 else 1.0
        mins, secs = divmod(remaining_ms // 1000, 60)
        time_text = f"{mins:02d}:{secs:02d}"
        phase_text = self._i18n.t("focus.phase.focusing") if phase == FocusPhase.FOCUS else self._i18n.t("focus.phase.break")
        self._circle.set_progress(progress, time_text, phase_text)

        # 更新循环标签
        p = self._active_preset
        total = p.cycles if p.cycles > 0 else "∞"
        self._cycle_label.setText(
            f"{self._i18n.t('focus.cycle', f'第 {self._svc.cycle_index + 1} / {total} 循环')}"
        )

        # 不专注倍计时显示
        if self._svc.is_distracted and p.pause_on_distracted and not self._svc.is_paused_by_distraction:
            d_sec = self._svc.distracted_sec
            tol   = p.tolerance_sec
            self._distract_label.setText(self._i18n.t("focus.distracted_time").format(d_sec=d_sec, tol=tol))

    @Slot(object, int)
    def _on_phase_changed(self, phase, cycle_index: int) -> None:
        self._circle.set_phase_color(phase)
        self._distract_label.setText("")

    @Slot(int)
    def _on_distracted_alert(self, distracted_sec: int) -> None:
        if not self._active_preset:
            return
        preset = self._active_preset
        if preset.pause_on_distracted:
            self._distract_label.setText(self._i18n.t("focus.distracted_paused"))

        rule_hint = {
            "must_use_pc": self._i18n.t("focus.return_to_pc"),
            "no_pc_use":   self._i18n.t("focus.stop_using_pc"),
            "focused_app": f"{self._i18n.t('focus.please_focus_back', '请回到')}「{preset.app_name_filter}」",
        }.get(preset.rule, self._i18n.t("focus.please_focus"))

        if preset.alert_mode == AlertMode.FULLSCREEN:
            # 全屏提醒（仅当当前无全屏窗口时弹出）
            if self._distracted_alert_win is None or not self._distracted_alert_win.isVisible():
                self._distracted_alert_win = FocusDistractedAlert(
                    preset.name, rule_hint, distracted_sec
                )
                self._distracted_alert_win.show_fullscreen()
        else:
            # 系统通知
            self._notif.show(
                f"⚠ {self._i18n.t('focus.alert_title', '专注提醒')} — {preset.name}",
                f"{self._i18n.t('focus.distracted_duration', f'已不专注 {distracted_sec} 秒')}，{rule_hint}",
            )

    @Slot(bool)
    def _on_distracted_state(self, is_distracted: bool) -> None:
        self._circle.set_distracted(is_distracted)
        if is_distracted:
            self._distract_label.setText(self._i18n.t("focus.distracted"))
        else:
            self._distract_label.setText("")

    @Slot(object)
    def _on_phase_finished(self, phase) -> None:
        preset = self._active_preset
        if phase == FocusPhase.FOCUS:
            # 专注阶段结束 → 休息开始
            sound = preset.break_start_sound if preset else ""
            if sound:
                rs.play_sound(sound)
            else:
                rs.play_default()
            self._notif.show(self._i18n.t("focus.session_complete"), self._i18n.t("focus.session_complete_msg"))
        elif phase == FocusPhase.BREAK:
            # 休息阶段结束 → 休息结束
            sound = preset.break_end_sound if preset else ""
            if sound:
                rs.play_sound(sound)
            else:
                rs.play_default()
            self._notif.show(self._i18n.t("focus.break_end"), self._i18n.t("focus.break_end_msg"))

    @Slot()
    def _on_session_finished(self) -> None:
        self._start_btn.setEnabled(True)
        self._pause_btn.setEnabled(False)
        self._stop_btn.setEnabled(False)
        self._update_circle_idle()
        self._cycle_label.setText(self._i18n.t("stopwatch.completed"))
        p = self._active_preset
        if p:
            self._notif.show(
                self._i18n.t("focus.session_done"),
                f"{self._i18n.t('focus.preset_done', f'预设「{p.name}」已完成全部 {p.cycles} 个循环！')}",
            )

    # ------------------------------------------------------------------ #
    # 辅助
    # ------------------------------------------------------------------ #

    def _update_circle_idle(self) -> None:
        self._circle.set_phase_color(FocusPhase.IDLE)
        self._circle.set_progress(0.0, "—", self._i18n.t("focus.not_started"))

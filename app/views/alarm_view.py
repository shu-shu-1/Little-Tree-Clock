from __future__ import annotations

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QWidget,
)
from qfluentwidgets import (
    SmoothScrollArea,
    FluentIcon as FIF,
    PushButton,
    ToolButton,
    CardWidget,
    BodyLabel,
    TitleLabel,
    CaptionLabel,
    SwitchButton,
    TimePicker,
    CheckBox,
    LineEdit,
    MessageBox,
    InfoBar,
    InfoBarPosition,
)
from PySide6.QtCore import QTime

from app.models.alarm_model import Alarm, AlarmRepeat
from app.services.alarm_service import AlarmService
from app.services.notification_service import NotificationService
from app.services.settings_service import SettingsService
from app.services.i18n_service import I18nService, pick
from app.services.permission_service import PermissionService
from app.services import ringtone_service as rs
from app.views.alarm_alert import AlarmAlertController


class AlarmDialog(MessageBox):
    def __init__(self, alarm: Alarm | None = None, parent=None):
        self._i18n = I18nService.instance()
        title = self._i18n.t("alarm.edit") if alarm else self._i18n.t("alarm.add")
        super().__init__(title, "", parent)
        self.yesButton.setText(self._i18n.t("common.save"))
        self.cancelButton.setText(self._i18n.t("common.cancel"))

        self.contentLabel.hide()

        form = QWidget()
        fl = QVBoxLayout(form)
        fl.setSpacing(10)

        lb_row = QHBoxLayout()
        lb_row.addWidget(BodyLabel(self._i18n.t("automation.name")))
        self._label_edit = LineEdit()
        self._label_edit.setPlaceholderText(self._i18n.t("alarm.title"))
        lb_row.addWidget(self._label_edit, 1)
        fl.addLayout(lb_row)

        tm_row = QHBoxLayout()
        tm_row.addWidget(BodyLabel(self._i18n.t("alarm.time", "时间：")))
        self._time_edit = TimePicker(self)
        tm_row.addWidget(self._time_edit, 1)
        fl.addLayout(tm_row)

        fl.addWidget(BodyLabel(self._i18n.t("alarm.repeat", "重复：")))
        repeat_widget = QWidget()
        repeat_row = QGridLayout(repeat_widget)
        repeat_row.setContentsMargins(0, 0, 0, 0)
        repeat_row.setHorizontalSpacing(10)
        repeat_row.setVerticalSpacing(6)
        self._day_checks: list[CheckBox] = []
        day_names = [
            self._i18n.t("widget.week.1"),
            self._i18n.t("widget.week.2"),
            self._i18n.t("widget.week.3"),
            self._i18n.t("widget.week.4"),
            self._i18n.t("widget.week.5"),
            self._i18n.t("widget.week.6"),
            self._i18n.t("widget.week.7"),
        ]
        for idx, name in enumerate(day_names):
            cb = CheckBox(name)
            cb.setMinimumWidth(72)
            self._day_checks.append(cb)
            repeat_row.addWidget(cb, idx // 4, idx % 4)
        fl.addWidget(repeat_widget)

        snooze_row = QHBoxLayout()
        snooze_row.addWidget(BodyLabel(self._i18n.t("alarm.snooze", "稍后提醒（分钟）：")))
        self._snooze_edit = LineEdit()
        self._snooze_edit.setPlaceholderText(self._i18n.t("alarm.snooze.ph"))
        snooze_row.addWidget(self._snooze_edit, 1)
        fl.addLayout(snooze_row)

        fs_row = QHBoxLayout()
        fs_row.addWidget(BodyLabel(pick("全屏提醒：", "Fullscreen alert:")))
        self._fullscreen_cb = CheckBox(pick("启用（推荐）", "Enable (recommended)"))
        self._fullscreen_cb.setChecked(True)
        fs_row.addWidget(self._fullscreen_cb, 1)
        fl.addLayout(fs_row)

        sound_row = QHBoxLayout()
        sound_row.addWidget(BodyLabel(pick("铃声：", "Ringtone:")))
        settings = SettingsService.instance()
        self._sound_combo = rs.make_sound_combo(settings.ringtones)
        sound_row.addWidget(self._sound_combo, 1)
        fl.addLayout(sound_row)

        self.textLayout.addWidget(form)

        if alarm:
            self._label_edit.setText(alarm.label)
            self._time_edit.setTime(QTime(alarm.hour, alarm.minute))

            flags = [
                AlarmRepeat.MONDAY,
                AlarmRepeat.TUESDAY,
                AlarmRepeat.WEDNESDAY,
                AlarmRepeat.THURSDAY,
                AlarmRepeat.FRIDAY,
                AlarmRepeat.SATURDAY,
                AlarmRepeat.SUNDAY,
            ]
            for cb, flag in zip(self._day_checks, flags):
                cb.setChecked(bool(alarm.repeat_flag & flag))
            self._snooze_edit.setText(str(alarm.snooze_min))
            self._fullscreen_cb.setChecked(alarm.fullscreen)
            if alarm.sound:
                rs.set_combo_sound(self._sound_combo, alarm.sound)

    def get_alarm(self, base: Alarm | None = None) -> Alarm:
        a = base or Alarm()
        a.label = self._label_edit.text().strip() or self._i18n.t("alarm.title")
        t = self._time_edit.getTime()
        a.hour = t.hour()
        a.minute = t.minute()
        flags = [
            AlarmRepeat.MONDAY,
            AlarmRepeat.TUESDAY,
            AlarmRepeat.WEDNESDAY,
            AlarmRepeat.THURSDAY,
            AlarmRepeat.FRIDAY,
            AlarmRepeat.SATURDAY,
            AlarmRepeat.SUNDAY,
        ]
        rep = AlarmRepeat.NONE
        for cb, flag in zip(self._day_checks, flags):
            if cb.isChecked():
                rep |= flag
        a.repeat = rep.value
        try:
            a.snooze_min = max(0, int(self._snooze_edit.text()))
        except ValueError:
            a.snooze_min = 5
        a.fullscreen = self._fullscreen_cb.isChecked()
        a.sound = rs.get_combo_sound(self._sound_combo)
        return a


class AlarmCard(CardWidget):
    def __init__(self, alarm: Alarm, parent=None):
        super().__init__(parent)
        self.alarm_id = alarm.id

        row = QHBoxLayout(self)
        row.setContentsMargins(16, 10, 16, 10)

        info = QVBoxLayout()
        self.time_lbl = TitleLabel(alarm.time_str)
        self.label_lbl = BodyLabel(alarm.label)
        self.repeat_lbl = CaptionLabel(alarm.repeat_flag.label())
        info.addWidget(self.time_lbl)
        info.addWidget(self.label_lbl)
        info.addWidget(self.repeat_lbl)

        self.switch = SwitchButton()
        self.switch.setChecked(alarm.enabled)

        self.edit_btn = ToolButton(FIF.EDIT)
        self.del_btn = ToolButton(FIF.DELETE)

        row.addLayout(info, 1)
        row.addWidget(self.switch)
        row.addWidget(self.edit_btn)
        row.addWidget(self.del_btn)

        self.setFixedHeight(90)

    def refresh(self, alarm: Alarm) -> None:
        self.time_lbl.setText(alarm.time_str)
        self.label_lbl.setText(alarm.label)
        self.repeat_lbl.setText(alarm.repeat_flag.label())
        self.switch.setChecked(alarm.enabled)


class AlarmView(SmoothScrollArea):
    def __init__(
        self,
        alarm_service: AlarmService,
        notif_service: NotificationService,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("alarmView")
        self._store = alarm_service._store
        self._service = alarm_service
        self._notif = notif_service
        self._i18n = I18nService.instance()
        self._permission_service = PermissionService.instance()
        self._cards: dict[str, AlarmCard] = {}
        self._active_controllers: dict[str, AlarmAlertController] = {}

        container = QWidget()
        self._layout = QVBoxLayout(container)
        self._layout.setContentsMargins(24, 16, 24, 16)
        self._layout.setSpacing(8)

        self._layout.addWidget(TitleLabel(self._i18n.t("alarm.title")))

        bar = QHBoxLayout()
        add_btn = PushButton(FIF.ADD, self._i18n.t("alarm.add"))
        add_btn.clicked.connect(self._on_add)
        bar.addStretch()
        bar.addWidget(add_btn)
        self._layout.addLayout(bar)

        self._empty_card = CardWidget()
        empty_lay = QVBoxLayout(self._empty_card)
        empty_lay.setContentsMargins(24, 20, 24, 20)
        empty_lay.setSpacing(8)
        empty_lay.setAlignment(Qt.AlignCenter)
        empty_lay.addWidget(TitleLabel(pick("还没有闹钟", "No alarms yet")), 0, Qt.AlignCenter)
        empty_lay.addWidget(
            CaptionLabel(pick("添加一个闹钟开始提醒吧", "Add an alarm to get reminders")), 0, Qt.AlignCenter
        )
        empty_add_btn = PushButton(FIF.ADD, self._i18n.t("alarm.add"))
        empty_add_btn.clicked.connect(self._on_add)
        empty_lay.addWidget(empty_add_btn, 0, Qt.AlignCenter)
        self._layout.addWidget(self._empty_card)

        self._cards_layout = QVBoxLayout()
        self._cards_layout.setSpacing(6)
        self._layout.addLayout(self._cards_layout)
        self._layout.addStretch()

        self.setWidget(container)
        self.setWidgetResizable(True)
        self.enableTransparentBackground()

        self._load_cards()
        alarm_service.alarmFired.connect(self._on_alarm_fired)

    def _load_cards(self) -> None:
        for alarm in self._store.all():
            self._append_card(alarm)
        self._refresh_empty_state()

    def _append_card(self, alarm: Alarm) -> None:
        card = AlarmCard(alarm, self.widget())
        card.switch.checkedChanged.connect(lambda checked, aid=alarm.id: self._store.set_enabled(aid, checked))
        card.edit_btn.clicked.connect(lambda _, a=alarm: self._on_edit(a))
        card.del_btn.clicked.connect(lambda _, aid=alarm.id: self._on_delete(aid))
        self._cards[alarm.id] = card
        self._cards_layout.addWidget(card)
        self._refresh_empty_state()

    def _refresh_empty_state(self) -> None:
        self._empty_card.setVisible(not bool(self._cards))

    @Slot()
    def _on_add(self) -> None:
        if not self._ensure_alarm_permission("alarm.perm.reason.add"):
            return
        dlg = AlarmDialog(parent=self.window())
        if dlg.exec():
            alarm = dlg.get_alarm()
            self._store.add(alarm)
            self._append_card(alarm)

    def _on_edit(self, alarm: Alarm) -> None:
        if not self._ensure_alarm_permission("alarm.perm.reason.edit"):
            return
        dlg = AlarmDialog(alarm=alarm, parent=self.window())
        if dlg.exec():
            updated = dlg.get_alarm(alarm)
            self._store.update(updated)
            card = self._cards.get(alarm.id)
            if card:
                card.refresh(updated)

    def _on_delete(self, alarm_id: str) -> None:
        if not self._ensure_alarm_permission("alarm.perm.reason.delete"):
            return
        self._store.remove(alarm_id)
        card = self._cards.pop(alarm_id, None)
        if card:
            self._cards_layout.removeWidget(card)
            card.deleteLater()
        self._refresh_empty_state()

    def _ensure_alarm_permission(self, reason_key: str) -> bool:
        if self._permission_service is None:
            return True
        ok = self._permission_service.ensure_access(
            "clock.alarm.manage",
            parent=self.window(),
            reason=self._i18n.t(reason_key, default="管理闹钟"),
        )
        if ok:
            return True
        deny_reason = self._permission_service.get_last_denied_reason("clock.alarm.manage")
        InfoBar.warning(
            self._i18n.t("alarm.title"),
            deny_reason or self._i18n.t("perm.access.denied", default="权限不足，无法执行该操作。"),
            parent=self.window(),
            position=InfoBarPosition.TOP_RIGHT,
            duration=2500,
        )
        return False

    @Slot(str)
    def _on_alarm_fired(self, alarm_id: str) -> None:
        alarm = self._store.get(alarm_id)
        if alarm is None:
            return

        # 如果已有同一闹钟的控制器仍在运行，跳过（防重）
        if alarm_id in self._active_controllers:
            return

        # 一次性闹钟已被 AlarmService 自动禁用，同步卡片开关
        card = self._cards.get(alarm_id)
        if card:
            card.refresh(alarm)

        # 获取 ToastManager（用于稍后提醒 Toast 入队）
        toast_mgr = None
        try:
            w = self.window()
            if hasattr(w, "_toast_mgr"):
                toast_mgr = w._toast_mgr
        except Exception:
            pass

        controller = AlarmAlertController(alarm, toast_manager=toast_mgr, parent=self)
        self._active_controllers[alarm_id] = controller
        controller.finished.connect(lambda aid=alarm_id: self._active_controllers.pop(aid, None))
        controller.start()

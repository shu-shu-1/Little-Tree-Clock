"""自习时间安排设置面板。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget
from qfluentwidgets import (
    FluentIcon as FIF,
    SettingCard,
    SettingCardGroup,
    SpinBox,
    SwitchButton,
    VBoxLayout,
)


def _make_card(icon, title: str, desc: str, parent=None) -> SettingCard:
    return SettingCard(icon, title, desc, parent)


class StudyScheduleSettingsWidget(QWidget):
    def __init__(self, svc, parent: QWidget | None = None):
        super().__init__(parent)
        self._svc = svc

        vbox = VBoxLayout(self)
        vbox.setAlignment(Qt.AlignmentFlag.AlignTop)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(16)

        auto_group = SettingCardGroup("自动切换")

        weekday_card = _make_card(
            FIF.HISTORY,
            "按星期切换事项组",
            "根据事项组配置的星期几自动切换当前事项组；未指定星期的分组会作为回退。",
            auto_group,
        )
        self._weekday_sw = SwitchButton()
        self._weekday_sw.setChecked(bool(svc.get_setting("auto_switch_by_weekday", True)))
        self._weekday_sw.checkedChanged.connect(lambda value: svc.set_setting("auto_switch_by_weekday", value))
        weekday_card.hBoxLayout.addWidget(self._weekday_sw)
        weekday_card.hBoxLayout.addSpacing(16)
        auto_group.addSettingCard(weekday_card)

        item_card = _make_card(
            FIF.SYNC,
            "按时间切换事项",
            "按当前分组中事项的时间段自动切换当前事项。",
            auto_group,
        )
        self._item_sw = SwitchButton()
        self._item_sw.setChecked(bool(svc.get_setting("auto_switch_by_time", True)))
        self._item_sw.checkedChanged.connect(lambda value: svc.set_setting("auto_switch_by_time", value))
        item_card.hBoxLayout.addWidget(self._item_sw)
        item_card.hBoxLayout.addSpacing(16)
        auto_group.addSettingCard(item_card)

        apply_card = _make_card(
            FIF.LAYOUT,
            "自动应用预设",
            "当前事项或事项组绑定了布局预设时，自动切换目标画布布局。",
            auto_group,
        )
        self._apply_sw = SwitchButton()
        self._apply_sw.setChecked(bool(svc.get_setting("auto_apply_preset", True)))
        self._apply_sw.checkedChanged.connect(lambda value: svc.set_setting("auto_apply_preset", value))
        apply_card.hBoxLayout.addWidget(self._apply_sw)
        apply_card.hBoxLayout.addSpacing(16)
        auto_group.addSettingCard(apply_card)

        interval_card = _make_card(
            FIF.STOP_WATCH,
            "检查间隔",
            "后台检测星期和事项切换的频率。",
            auto_group,
        )
        self._interval_spin = SpinBox()
        self._interval_spin.setRange(5, 300)
        self._interval_spin.setSuffix(" 秒")
        self._interval_spin.setValue(int(svc.get_setting("check_interval_sec", 30)))
        self._interval_spin.valueChanged.connect(lambda value: svc.set_setting("check_interval_sec", value))
        interval_card.hBoxLayout.addWidget(self._interval_spin)
        interval_card.hBoxLayout.addSpacing(16)
        auto_group.addSettingCard(interval_card)

        vbox.addWidget(auto_group)

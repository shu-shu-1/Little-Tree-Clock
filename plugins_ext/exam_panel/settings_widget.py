"""考试面板插件 — 设置面板；无独立滚动区域，由 SettingsView 外层统一滚动。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget
from qfluentwidgets import (
    FluentIcon as FIF,
    SettingCard,
    SettingCardGroup,
    SwitchButton,
    SpinBox,
    VBoxLayout,
)


def _make_card(icon, title: str, desc: str, parent=None) -> SettingCard:
    """与 settings_view.py 保持一致的设置卡工厂。"""
    return SettingCard(icon, title, desc, parent)


def _add_switch_card(group, icon, title: str, desc: str, checked, on_changed) -> SwitchButton:
    card = _make_card(icon, title, desc, group)
    switch = SwitchButton()
    switch.setChecked(checked)
    switch.checkedChanged.connect(on_changed)
    card.hBoxLayout.addWidget(switch)
    card.hBoxLayout.addSpacing(16)
    group.addSettingCard(card)
    return switch


class ExamSettingsWidget(QWidget):
    def __init__(self, svc, parent: QWidget | None = None):
        super().__init__(parent)
        self._svc = svc

        vbox = VBoxLayout(self)
        vbox.setAlignment(Qt.AlignmentFlag.AlignTop)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(16)

        auto_group = SettingCardGroup("自动化")

        _add_switch_card(
            auto_group,
            FIF.SYNC,
            "自动切换预设",
            "在考试时间段内，根据当前科目的绑定或默认预设自动切换共享布局预设",
            svc.get_setting("auto_switch_preset", False),
            lambda v: svc.set_setting("auto_switch_preset", v),
        )

        _add_switch_card(
            auto_group,
            FIF.RINGER,
            "自动触发提醒",
            "按照考试规划中配置的时间，自动弹出全屏提醒或语音播报",
            svc.get_setting("auto_reminder", True),
            lambda v: svc.set_setting("auto_reminder", v),
        )

        interval_card = _make_card(
            FIF.HISTORY,
            "检查间隔",
            "后台检测考试时间段和提醒触发的频率（默认 30 秒）",
            auto_group,
        )
        self._interval_spin = SpinBox()
        self._interval_spin.setRange(5, 300)
        self._interval_spin.setValue(svc.get_setting("check_interval_sec", 30))
        self._interval_spin.setSuffix(" 秒")
        self._interval_spin.valueChanged.connect(lambda v: svc.set_setting("check_interval_sec", v))
        interval_card.hBoxLayout.addWidget(self._interval_spin)
        interval_card.hBoxLayout.addSpacing(16)
        auto_group.addSettingCard(interval_card)

        vbox.addWidget(auto_group)

        voice_group = SettingCardGroup("语音播报")

        _add_switch_card(
            voice_group,
            FIF.MEGAPHONE,
            "启用语音播报",
            "提醒触发时通过系统 TTS 朗读提醒内容（需要 Windows SAPI 或 pyttsx3）",
            svc.get_setting("voice_enabled", True),
            lambda v: svc.set_setting("voice_enabled", v),
        )

        vbox.addWidget(voice_group)

        display_group = SettingCardGroup("显示")

        _add_switch_card(
            display_group,
            FIF.STOP_WATCH,
            "显示倒计时",
            "在时间段组件上额外显示距离考试结束的剩余时间",
            svc.get_setting("show_countdown", True),
            lambda v: svc.set_setting("show_countdown", v),
        )

        _add_switch_card(
            display_group,
            FIF.TAG,
            "显示科目状态颜色",
            "根据考试阶段（准备中 / 进行中 / 已结束）在科目组件上以颜色标注",
            svc.get_setting("show_subject_status_color", True),
            lambda v: svc.set_setting("show_subject_status_color", v),
        )

        vbox.addWidget(display_group)

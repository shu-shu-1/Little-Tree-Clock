"""考试面板插件 — 设置面板。

返回的 widget 无内置滚动区域，由 SettingsView 外层统一滚动。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget
from qfluentwidgets import (
    FluentIcon as FIF,
    SettingCard, SettingCardGroup,
    SwitchButton, SpinBox,
    VBoxLayout,
)


def _make_card(icon, title: str, desc: str, parent=None) -> SettingCard:
    """创建标准设置卡（与 settings_view.py 保持一致）。"""
    return SettingCard(icon, title, desc, parent)


class ExamSettingsWidget(QWidget):
    """插件自定义设置面板，嵌入宿主设置页，无独立滚动区域。"""

    def __init__(self, svc, parent: QWidget | None = None):
        super().__init__(parent)
        self._svc = svc

        vbox = VBoxLayout(self)
        vbox.setAlignment(Qt.AlignmentFlag.AlignTop)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(16)

        # ── 自动化 ─────────────────────────────────────────────────────── #
        auto_group = SettingCardGroup("自动化")

        # 自动切换预设
        auto_preset_card = _make_card(
            FIF.SYNC, "自动切换预设",
            "在考试时间段内，根据当前科目的绑定自动切换画布布局预设",
            auto_group,
        )
        self._auto_preset_sw = SwitchButton()
        self._auto_preset_sw.setChecked(svc.get_setting("auto_switch_preset", False))
        self._auto_preset_sw.checkedChanged.connect(
            lambda v: svc.set_setting("auto_switch_preset", v)
        )
        auto_preset_card.hBoxLayout.addWidget(self._auto_preset_sw)
        auto_preset_card.hBoxLayout.addSpacing(16)
        auto_group.addSettingCard(auto_preset_card)

        # 自动触发提醒
        auto_remind_card = _make_card(
            FIF.RINGER, "自动触发提醒",
            "按照考试规划中配置的时间，自动弹出全屏提醒或语音播报",
            auto_group,
        )
        self._auto_remind_sw = SwitchButton()
        self._auto_remind_sw.setChecked(svc.get_setting("auto_reminder", True))
        self._auto_remind_sw.checkedChanged.connect(
            lambda v: svc.set_setting("auto_reminder", v)
        )
        auto_remind_card.hBoxLayout.addWidget(self._auto_remind_sw)
        auto_remind_card.hBoxLayout.addSpacing(16)
        auto_group.addSettingCard(auto_remind_card)

        # 检查间隔
        interval_card = _make_card(
            FIF.HISTORY, "检查间隔",
            "后台检测考试时间段和提醒触发的频率（默认 30 秒）",
            auto_group,
        )
        self._interval_spin = SpinBox()
        self._interval_spin.setRange(5, 300)
        self._interval_spin.setValue(svc.get_setting("check_interval_sec", 30))
        self._interval_spin.setSuffix(" 秒")
        self._interval_spin.valueChanged.connect(
            lambda v: svc.set_setting("check_interval_sec", v)
        )
        interval_card.hBoxLayout.addWidget(self._interval_spin)
        interval_card.hBoxLayout.addSpacing(16)
        auto_group.addSettingCard(interval_card)

        vbox.addWidget(auto_group)

        # ── 语音播报 ───────────────────────────────────────────────────── #
        voice_group = SettingCardGroup("语音播报")

        # 启用语音
        voice_enable_card = _make_card(
            FIF.MEGAPHONE, "启用语音播报",
            "提醒触发时通过系统 TTS 朗读提醒内容（需要 Windows SAPI 或 pyttsx3）",
            voice_group,
        )
        self._voice_sw = SwitchButton()
        self._voice_sw.setChecked(svc.get_setting("voice_enabled", True))
        self._voice_sw.checkedChanged.connect(
            lambda v: svc.set_setting("voice_enabled", v)
        )
        voice_enable_card.hBoxLayout.addWidget(self._voice_sw)
        voice_enable_card.hBoxLayout.addSpacing(16)
        voice_group.addSettingCard(voice_enable_card)

        vbox.addWidget(voice_group)

        # ── 显示 ────────────────────────────────────────────────────────── #
        display_group = SettingCardGroup("显示")

        # 显示倒计时
        countdown_card = _make_card(
            FIF.STOP_WATCH, "显示倒计时",
            "在时间段组件上额外显示距离考试结束的剩余时间",
            display_group,
        )
        self._countdown_sw = SwitchButton()
        self._countdown_sw.setChecked(svc.get_setting("show_countdown", True))
        self._countdown_sw.checkedChanged.connect(
            lambda v: svc.set_setting("show_countdown", v)
        )
        countdown_card.hBoxLayout.addWidget(self._countdown_sw)
        countdown_card.hBoxLayout.addSpacing(16)
        display_group.addSettingCard(countdown_card)

        # 显示科目状态颜色
        status_color_card = _make_card(
            FIF.TAG, "显示科目状态颜色",
            "根据考试阶段（准备中 / 进行中 / 已结束）在科目组件上以颜色标注",
            display_group,
        )
        self._status_color_sw = SwitchButton()
        self._status_color_sw.setChecked(
            svc.get_setting("show_subject_status_color", True)
        )
        self._status_color_sw.checkedChanged.connect(
            lambda v: svc.set_setting("show_subject_status_color", v)
        )
        status_color_card.hBoxLayout.addWidget(self._status_color_sw)
        status_color_card.hBoxLayout.addSpacing(16)
        display_group.addSettingCard(status_color_card)

        vbox.addWidget(display_group)

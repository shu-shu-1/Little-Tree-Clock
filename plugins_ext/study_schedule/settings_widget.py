"""自习时间安排设置面板。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget
from qfluentwidgets import (
    ComboBox,
    FluentIcon as FIF,
    SettingCard,
    SettingCardGroup,
    SpinBox,
    SwitchButton,
    ToolButton,
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

        target_zone_card = _make_card(
            FIF.GLOBE,
            "自动应用目标画布",
            "选择自动应用预设到哪个全屏时钟；可设置为跟随最近打开的全屏画布。",
            auto_group,
        )
        self._target_zone_combo = ComboBox()
        self._target_zone_combo.setMinimumWidth(220)
        self._target_zone_combo.currentIndexChanged.connect(self._on_target_zone_changed)
        self._target_zone_refresh_btn = ToolButton(FIF.SYNC)
        self._target_zone_refresh_btn.setToolTip("刷新全屏画布列表")
        self._target_zone_refresh_btn.clicked.connect(self._refresh_target_zones)
        target_zone_card.hBoxLayout.addWidget(self._target_zone_combo)
        target_zone_card.hBoxLayout.addWidget(self._target_zone_refresh_btn)
        target_zone_card.hBoxLayout.addSpacing(16)
        auto_group.addSettingCard(target_zone_card)

        if hasattr(svc, "target_zone_changed"):
            svc.target_zone_changed.connect(lambda *_: self._refresh_target_zones())
        self._refresh_target_zones()

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

        volume_group = SettingCardGroup("音量报告")

        volume_switch_card = _make_card(
            FIF.MEGAPHONE,
            "开启音量报告",
            "依赖音量检测插件；每个时段结束后弹出音量报告。",
            volume_group,
        )
        self._volume_sw = SwitchButton()
        self._volume_sw.setChecked(bool(svc.get_setting("volume_report_enabled", False)))
        self._volume_sw.checkedChanged.connect(lambda value: svc.set_setting("volume_report_enabled", value))
        volume_switch_card.hBoxLayout.addWidget(self._volume_sw)
        volume_switch_card.hBoxLayout.addSpacing(16)
        volume_group.addSettingCard(volume_switch_card)

        auto_close_card = _make_card(
            FIF.POWER_BUTTON,
            "自动关闭秒数",
            "0 表示仅手动关闭；无论是否自动关闭都会显示关闭按钮（自动关闭时会显示倒计时）",
            volume_group,
        )
        self._auto_close_spin = SpinBox()
        self._auto_close_spin.setRange(0, 180)
        self._auto_close_spin.setSuffix(" 秒")
        self._auto_close_spin.setValue(int(svc.get_setting("volume_report_auto_close_sec", 10)))
        self._auto_close_spin.valueChanged.connect(lambda value: svc.set_setting("volume_report_auto_close_sec", value))
        auto_close_card.hBoxLayout.addWidget(self._auto_close_spin)
        auto_close_card.hBoxLayout.addSpacing(16)
        volume_group.addSettingCard(auto_close_card)

        autosave_card = _make_card(
            FIF.SAVE,
            "自动保存报告",
            "保存到插件数据目录的 volume_reports/ 下，文件名包含时间与事项名。",
            volume_group,
        )
        self._autosave_sw = SwitchButton()
        self._autosave_sw.setChecked(bool(svc.get_setting("volume_report_auto_save", False)))
        self._autosave_sw.checkedChanged.connect(lambda value: svc.set_setting("volume_report_auto_save", value))
        autosave_card.hBoxLayout.addWidget(self._autosave_sw)
        autosave_card.hBoxLayout.addSpacing(16)
        volume_group.addSettingCard(autosave_card)

        threshold_card = _make_card(
            FIF.SPEAKERS,
            "阈值 (dB)",
            "用于计算超阈值时长与次数。",
            volume_group,
        )
        self._threshold_spin = SpinBox()
        self._threshold_spin.setRange(-80, 0)
        self._threshold_spin.setSuffix(" dB")
        self._threshold_spin.setValue(int(svc.get_setting("volume_report_threshold_db", -20)))
        self._threshold_spin.valueChanged.connect(lambda value: svc.set_setting("volume_report_threshold_db", value))
        threshold_card.hBoxLayout.addWidget(self._threshold_spin)
        threshold_card.hBoxLayout.addSpacing(16)
        volume_group.addSettingCard(threshold_card)

        dedup_card = _make_card(
            FIF.SYNC,
            "超阈值计数去抖",
            "排除短时间内重复触发的计数间隔（秒）",
            volume_group,
        )
        self._dedup_spin = SpinBox()
        self._dedup_spin.setRange(1, 30)
        self._dedup_spin.setSuffix(" 秒")
        self._dedup_spin.setValue(int(svc.get_setting("volume_report_dedup_sec", 2)))
        self._dedup_spin.valueChanged.connect(lambda value: svc.set_setting("volume_report_dedup_sec", value))
        dedup_card.hBoxLayout.addWidget(self._dedup_spin)
        dedup_card.hBoxLayout.addSpacing(16)
        volume_group.addSettingCard(dedup_card)

        vbox.addWidget(volume_group)

    def _refresh_target_zones(self) -> None:
        if not hasattr(self, "_target_zone_combo"):
            return
        current = self._svc.target_zone_id() if hasattr(self._svc, "target_zone_id") else ""
        self._target_zone_combo.blockSignals(True)
        self._target_zone_combo.clear()
        self._target_zone_combo.addItem("（跟随最近打开的全屏画布）", userData="")
        for zone in self._svc.list_zones():
            self._target_zone_combo.addItem(
                str(zone.get("display_name") or zone.get("label") or zone.get("timezone") or zone.get("id") or "未命名画布"),
                userData=str(zone.get("id") or ""),
            )
        index = next(
            (i for i in range(self._target_zone_combo.count()) if self._target_zone_combo.itemData(i) == current),
            0,
        )
        self._target_zone_combo.setCurrentIndex(index)
        self._target_zone_combo.blockSignals(False)

    def _on_target_zone_changed(self, _index: int) -> None:
        zone_id = self._target_zone_combo.currentData() or ""
        if hasattr(self._svc, "set_target_zone"):
            self._svc.set_target_zone(zone_id)

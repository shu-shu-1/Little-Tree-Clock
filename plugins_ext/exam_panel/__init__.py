"""考试面板插件 — 主入口

通过 Plugin.on_load(api) 注册：
    - 4 个画布组件类型
    - 全屏画布顶栏按钮（切换科目）
    - 提醒信号监听（全屏叠加层 / 语音播报）
    - 侧边栏面板（科目管理 / 预设绑定 / 考试规划）
    - 设置面板
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import QWidget, QPushButton
from qfluentwidgets import (
    RoundMenu,
    FluentIcon as FIF,
    Action,
    Theme,
)

from app.plugins.base_plugin import BasePlugin

from .exam_service import ExamService
from .widgets import (
    ExamSubjectWidget,
    ExamTimePeriodWidget,
    ExamAnswerSheetWidget,
    ExamPaperPagesWidget,
)


# ─────────────────────────────────────────────────────────────────────────── #
# 插件类
# ─────────────────────────────────────────────────────────────────────────── #

class Plugin(BasePlugin):
    """考试面板插件。"""

    def on_load(self, api) -> None:  # noqa: ANN001
        self._api = api
        data_dir = api.get_data_dir() or (Path(__file__).parent / "_data")
        preset_service = api.get_plugin("layout_presets")
        if preset_service is None:
            raise RuntimeError("layout_presets 不可用")

        # ── 1. 创建核心服务 ──────────────────────────────────────────── #
        self._svc = ExamService(data_dir=data_dir, api=api, preset_service=preset_service)
        api.register_canvas_service("exam_service", self._svc)

        # ── 2. 注册画布组件类型 ──────────────────────────────────────── #
        for widget_cls in (
            ExamSubjectWidget,
            ExamTimePeriodWidget,
            ExamAnswerSheetWidget,
            ExamPaperPagesWidget,
        ):
            widget_cls._svc = self._svc          # 注入服务引用
            api.register_widget_type(widget_cls)

        # ── 3. 注册顶栏按钮工厂 ──────────────────────────────────────── #
        api.register_canvas_topbar_btn_factory(self._make_topbar_buttons)

        # ── 4. 连接提醒信号 ──────────────────────────────────────────── #
        self._svc.reminder_triggered.connect(self._on_reminder)

    def on_unload(self) -> None:
        # 停止后台定时器
        if hasattr(self, "_svc") and self._svc:
            self._svc._timer.stop()
        # 注销组件类型（使用 on_load 中存储的 api 引用）
        if hasattr(self, "_api") and self._api:
            for wtype in (
                ExamSubjectWidget.WIDGET_TYPE,
                ExamTimePeriodWidget.WIDGET_TYPE,
                ExamAnswerSheetWidget.WIDGET_TYPE,
                ExamPaperPagesWidget.WIDGET_TYPE,
            ):
                self._api.unregister_widget_type(wtype)

    def create_sidebar_widget(self) -> Optional[QWidget]:
        from .sidebar import ExamSidebarPanel
        return ExamSidebarPanel(self._svc)

    def create_settings_widget(self) -> Optional[QWidget]:
        from .settings_widget import ExamSettingsWidget
        return ExamSettingsWidget(self._svc)

    def get_sidebar_icon(self):
        return FIF.TAG

    # ------------------------------------------------------------------ #
    # 顶栏按钮工厂
    # ------------------------------------------------------------------ #

    def _make_topbar_buttons(self, zone_id: str):
        """返回要插入全屏时钟顶栏的按钮列表（工厂函数）。"""
        svc = self._svc
        # 记录当前操作的 zone
        svc.set_current_zone(zone_id)
        return [
            _SubjectSwitchButton(svc, zone_id),
        ]

    # ------------------------------------------------------------------ #
    # 提醒处理
    # ------------------------------------------------------------------ #

    def _on_reminder(
        self,
        subject_id: str,
        plan_id: str,
        reminder_id: str,
        message: str,
    ) -> None:
        if not self._svc.get_setting("auto_reminder", True):
            return

        subject = self._svc.get_subject(subject_id)
        subj_name = subject.name  if subject else "考试"
        subj_color = subject.color if subject else "#2196F3"

        plan = self._svc.get_plan(plan_id)
        reminder = next(
            (r for r in (plan.reminders if plan else []) if r.id == reminder_id),
            None,
        )
        mode  = reminder.mode             if reminder else "fullscreen"
        flash = reminder.fullscreen_flash if reminder else False

        # voice 受设置开关控制
        if mode in ("voice", "both") and not self._svc.get_setting("voice_enabled", True):
            mode = "fullscreen"

        from .reminder import trigger_reminder

        trigger_reminder(
            subject_name=subj_name,
            message=message,
            color=subj_color,
            mode=mode,
            flash=flash,
        )


# ─────────────────────────────────────────────────────────────────────────── #
# 顶栏按钮组件
# ─────────────────────────────────────────────────────────────────────────── #

_TOPBAR_STYLE = (
    "QPushButton{"
    "color:rgba(255,255,255,200);"
    "background:rgba(255,255,255,15);"
    "border:1px solid rgba(255,255,255,50);"
    "border-radius:8px;"
    "padding:5px 14px;"
    "font-size:13px;}"
    "QPushButton:hover{"
    "background:rgba(255,255,255,30);"
    "border-color:rgba(255,255,255,80);}"
    "QPushButton:pressed{"
    "background:rgba(255,255,255,18);}"
)


class _TopbarButton(QPushButton):
    def __init__(self, icon, text: str, parent=None):
        super().__init__(parent)
        self.setText(text)
        self.setIcon(icon.icon(Theme.DARK))
        self.setIconSize(QSize(16, 16))
        self.setFixedHeight(36)
        self.setMinimumWidth(96)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(_TOPBAR_STYLE)


class _SubjectSwitchButton(_TopbarButton):
    """「切换科目」下拉按钮。"""

    def __init__(self, svc: ExamService, zone_id: str, parent=None):
        super().__init__(FIF.TAG, "切换科目", parent)
        self._svc     = svc
        self._zone_id = zone_id

        svc.subject_changed.connect(self._refresh_text)
        svc.subjects_updated.connect(self._refresh_text)
        self._refresh_text()
        self.clicked.connect(self._show_menu)

    def _refresh_text(self) -> None:
        subj = self._svc.get_current_subject()
        self.setToolTip(f"当前科目：{subj.name}" if subj else "当前未选择科目")

    def _show_menu(self) -> None:
        menu = RoundMenu(parent=self)

        subjects = self._svc.subjects()
        if not subjects:
            act = Action(FIF.TAG, "（暂无科目）")
            act.setEnabled(False)
            menu.addAction(act)
        else:
            cur_id = self._svc.current_subject_id
            for subj in subjects:
                act = Action(FIF.TAG, subj.name)
                act.setCheckable(True)
                act.setChecked(subj.id == cur_id)
                act.triggered.connect(
                    lambda _checked=False, sid=subj.id:
                    self._svc.set_current_subject(sid, self._zone_id, apply_preset=True)
                )
                menu.addAction(act)
        menu.addSeparator()
        clear_act = Action(FIF.CLOSE, "清除当前科目")
        clear_act.triggered.connect(
            lambda _checked=False: self._svc.set_current_subject("", self._zone_id, apply_preset=False)
        )
        menu.addAction(clear_act)
        menu.exec(self.mapToGlobal(self.rect().bottomLeft()))

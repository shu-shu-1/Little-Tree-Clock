"""
调试窗口

仅可通过 URL 打开（不出现在导航栏）：
    ltclock://open/debug

使用 FluentWindow 作为基础，包含多个子页面：
    - 概览页：运行时基础信息（PID、Python 版本、运行时长、内存）
    - 计时器页：核心 QTimer 状态、Qt 线程、Python 线程列表
    - 服务页：NTP 服务状态、插件加载状态
    - 日志页：自动化引擎日志、应用日志（带高级筛选）
    - 推荐页：首页推荐系统统计、时间调试
"""

from __future__ import annotations

import os
import sys
import threading
import time
import re
import html as _html
from datetime import datetime
from typing import Callable, Optional

from PySide6.QtCore import Qt, QTimer, QThread, QDateTime, QMetaObject, Slot
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
    QTableWidgetItem,
    QHeaderView,
    QAbstractItemView,
    QSizePolicy,
    QDateTimeEdit,
    QStackedWidget,
)
from qfluentwidgets import (
    MSFluentWindow,
    FluentIcon as FIF,
    PushButton,
    CardWidget,
    TitleLabel,
    StrongBodyLabel,
    CaptionLabel,
    TextEdit,
    ComboBox,
    ToolButton,
    BodyLabel,
    SwitchButton,
    CheckBox,
    PrimaryPushButton,
    TransparentPushButton,
    MessageBox,
    InfoBar,
    SmoothScrollArea,
    Pivot,
    TableWidget,
    SearchLineEdit,
)

from app.constants import APP_NAME, APP_VERSION, ICON_PATH
from app.services.i18n_service import I18nService, LANG_EN_US
from app.services.update_service import UpdateService, UpdateInfo
from app.utils.fs import write_text_with_uac
from app.utils.logger import memory_log, logger
from app.views.toast_notification import ToastAction

# ────────────────────────────────────────────────────────────────────────── #
# 可选：psutil 内存信息
# ────────────────────────────────────────────────────────────────────────── #
try:
    import psutil as _psutil  # type: ignore[import-not-found]

    _PROC = _psutil.Process()
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False

_START_TIME: float = time.monotonic()  # 记录模块首次导入时刻


def _tr(zh: str, en: str) -> str:
    return en if I18nService.instance().language == LANG_EN_US else zh


def _fmt_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _uptime_str(since: float) -> str:
    secs = int(time.monotonic() - since)
    h, r = divmod(secs, 3600)
    m, s = divmod(r, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


# ────────────────────────────────────────────────────────────────────────── #
# 内部只读 KV 表格（使用 QFluentWidgets 的 TableWidget）
# ────────────────────────────────────────────────────────────────────────── #


class _KVTable(TableWidget):
    """两列（字段 / 值）只读表格，高度随行数自适应。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(2)
        self.setHorizontalHeaderLabels([_tr("字段", "Field"), _tr("值", "Value")])
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

    def set_rows(self, rows: list[tuple[str, str]]) -> None:
        self.setRowCount(len(rows))
        for r, (k, v) in enumerate(rows):
            ki = QTableWidgetItem(k)
            ki.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            vi = QTableWidgetItem(str(v))
            vi.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            self.setItem(r, 0, ki)
            self.setItem(r, 1, vi)
        self.resizeRowsToContents()

    def ideal_height(self) -> int:
        h = self.horizontalHeader().height() + 6
        for r in range(self.rowCount()):
            h += self.rowHeight(r)
        return h


# ────────────────────────────────────────────────────────────────────────── #
# 基础调试页面基类
# ────────────────────────────────────────────────────────────────────────── #


class _DebugBasePage(QWidget):
    """调试页面基类，提供通用布局工具。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(24, 16, 24, 16)
        self._root.setSpacing(12)

    def _add_section_card(self, title: str) -> tuple[CardWidget, QVBoxLayout]:
        """添加带标题的卡片区域。"""
        self._root.addWidget(StrongBodyLabel(title))
        card = CardWidget()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 12, 16, 12)
        self._root.addWidget(card)
        return card, lay

    def _add_toolbar(self, title: str) -> QHBoxLayout:
        """添加工具栏标题行。"""
        toolbar = QHBoxLayout()
        toolbar.addWidget(StrongBodyLabel(title))
        toolbar.addStretch()
        self._root.addLayout(toolbar)
        return toolbar


# ────────────────────────────────────────────────────────────────────────── #
# 概览页面
# ────────────────────────────────────────────────────────────────────────── #


class OverviewPage(_DebugBasePage):
    """概览页：运行时基础信息。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("debugOverviewPage")
        self._root.addWidget(TitleLabel(_tr("运行时概览", "Runtime Overview")))
        self._root.addSpacing(8)

        _, rl = self._add_section_card(_tr("系统信息", "System Info"))
        self._runtime_table = _KVTable()
        rl.addWidget(self._runtime_table)

        self._root.addStretch()
        self._refresh_runtime()

    def refresh(self) -> None:
        self._refresh_runtime()

    def _refresh_runtime(self) -> None:
        rows: list[tuple[str, str]] = [
            ("PID", str(os.getpid())),
            ("Python", sys.version.split()[0]),
            (_tr("平台", "Platform"), sys.platform),
            (_tr("运行时长", "Uptime"), _uptime_str(_START_TIME)),
            (_tr("Python 线程数", "Python Threads"), str(threading.active_count())),
            (
                _tr("当前时间", "Current Time"),
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ),
        ]

        if _HAS_PSUTIL:
            try:
                mem = _PROC.memory_info()
                rows.insert(4, (_tr("RSS 内存", "RSS Memory"), _fmt_bytes(mem.rss)))
                rows.insert(5, (_tr("VMS 内存", "VMS Memory"), _fmt_bytes(mem.vms)))
                rows.insert(
                    6,
                    (
                        _tr("CPU 占用", "CPU Usage"),
                        f"{_PROC.cpu_percent(interval=None):.1f}%",
                    ),
                )
            except Exception:
                pass

        self._runtime_table.set_rows(rows)
        self._runtime_table.setFixedHeight(self._runtime_table.ideal_height())


# ────────────────────────────────────────────────────────────────────────── #
# 计时器与线程页面
# ────────────────────────────────────────────────────────────────────────── #


class TimerThreadPage(_DebugBasePage):
    """计时器与线程页：QTimer、QThread、Python 线程。"""

    def __init__(
        self, clock_service=None, alarm_service=None, ntp_service=None, parent=None
    ):
        super().__init__(parent)
        self.setObjectName("debugTimerThreadPage")
        self._clock = clock_service
        self._alarm = alarm_service
        self._ntp = ntp_service

        self._root.addWidget(TitleLabel(_tr("计时器与线程", "Timers & Threads")))
        self._root.addSpacing(8)

        _, tl = self._add_section_card(
            _tr("核心 QTimer / 线程", "Core QTimer / Threads")
        )
        self._timer_table = _KVTable()
        tl.addWidget(self._timer_table)

        _, qtl = self._add_section_card(
            _tr("Qt 线程（QThread）", "Qt Threads (QThread)")
        )
        self._qthread_table = _KVTable()
        qtl.addWidget(self._qthread_table)

        _, ptl = self._add_section_card(_tr("Python 线程", "Python Threads"))
        self._pythread_table = _KVTable()
        ptl.addWidget(self._pythread_table)

        self._root.addStretch()
        self.refresh()

    def refresh(self) -> None:
        self._refresh_timers()
        self._refresh_qthreads()
        self._refresh_pythreads()

    def _refresh_timers(self) -> None:
        rows: list[tuple[str, str]] = []

        def _qtimer_row(name: str, svc, attr: str) -> tuple[str, str]:
            try:
                tmr: QTimer = getattr(svc, attr)
                active = (
                    _tr("✓ 运行中", "✓ Running")
                    if tmr.isActive()
                    else _tr("✗ 已停止", "✗ Stopped")
                )
                interval = f"{tmr.interval()} ms"
                shot = (
                    _tr("单次", "Single")
                    if tmr.isSingleShot()
                    else _tr("循环", "Repeating")
                )
                remaining = f"{tmr.remainingTime()} ms" if tmr.isActive() else "-"
                return (
                    name,
                    f"{active}  |  {_tr('间隔', 'Interval')} {interval}  |  {shot}  |  {_tr('剩余', 'Remaining')} {remaining}",
                )
            except AttributeError:
                return (name, _tr("（服务未注入）", "(Service not injected)"))

        if self._clock:
            rows.append(
                _qtimer_row("ClockService._timer      [QTimer]", self._clock, "_timer")
            )

        if self._alarm:
            rows.append(
                _qtimer_row("AlarmService._timer      [QTimer]", self._alarm, "_timer")
            )

        if self._ntp:
            t = getattr(self._ntp, "_thread", None)
            if t is None:
                ntp_val = _tr("（线程未启动）", "(Thread not started)")
            else:
                alive = (
                    _tr("✓ 存活", "✓ Alive")
                    if t.is_alive()
                    else _tr("✗ 已终止", "✗ Terminated")
                )
                daemon = _tr("守护", "Daemon") if t.daemon else _tr("普通", "Normal")
                ntp_val = (
                    f"{alive}  |  {daemon} {_tr('线程', 'Thread')}  |  "
                    f"name={t.name}  |  id={t.ident}"
                )
            rows.append(("NtpService._thread   [Python Thread]", ntp_val))

        if not rows:
            rows = [
                (
                    _tr("（无）", "(None)"),
                    _tr(
                        "服务未注入到调试窗口",
                        "Services were not injected into debug window",
                    ),
                )
            ]

        self._timer_table.set_rows(rows)
        self._timer_table.setFixedHeight(self._timer_table.ideal_height())

    def _refresh_qthreads(self) -> None:
        app = QApplication.instance()
        rows: list[tuple[str, str]] = []
        if app:
            for obj in app.findChildren(QThread):
                name = obj.objectName() or obj.__class__.__name__
                alive = (
                    _tr("✓ 运行中", "✓ Running")
                    if obj.isRunning()
                    else _tr("✗ 已停止", "✗ Stopped")
                )
                rows.append((name, f"{alive}  |  id={id(obj):#x}"))

        if not rows:
            rows = [
                (
                    _tr("（无独立 QThread）", "(No dedicated QThread)"),
                    _tr("所有逻辑均在主线程完成", "All logic runs on the main thread"),
                )
            ]

        self._qthread_table.set_rows(rows)
        self._qthread_table.setFixedHeight(self._qthread_table.ideal_height())

    def _refresh_pythreads(self) -> None:
        main_id = threading.main_thread().ident
        rows: list[tuple[str, str]] = []

        for t in sorted(threading.enumerate(), key=lambda x: x.ident or 0):
            tag = _tr(" [主线程]", " [Main]") if t.ident == main_id else ""
            daemon = _tr("守护", "Daemon") if t.daemon else _tr("普通", "Normal")
            alive = (
                _tr("✓ 存活", "✓ Alive")
                if t.is_alive()
                else _tr("✗ 已终止", "✗ Terminated")
            )
            rows.append((f"#{t.ident}{tag}", f"{t.name}  |  {alive}  |  {daemon}"))

        self._pythread_table.set_rows(rows)
        self._pythread_table.setFixedHeight(self._pythread_table.ideal_height())


# ────────────────────────────────────────────────────────────────────────── #
# 服务状态页面
# ────────────────────────────────────────────────────────────────────────── #


class ServicesPage(_DebugBasePage):
    """服务状态页：NTP、插件。"""

    def __init__(self, ntp_service=None, plugin_manager=None, parent=None):
        super().__init__(parent)
        self.setObjectName("debugServicesPage")
        self._ntp = ntp_service
        self._plugins = plugin_manager

        self._root.addWidget(TitleLabel(_tr("服务状态", "Service Status")))
        self._root.addSpacing(8)

        _, nl = self._add_section_card(_tr("NTP 服务", "NTP Service"))
        self._ntp_table = _KVTable()
        nl.addWidget(self._ntp_table)

        _, pl = self._add_section_card(_tr("已加载插件", "Loaded Plugins"))
        self._plugin_table = _KVTable()
        pl.addWidget(self._plugin_table)

        self._root.addStretch()
        self.refresh()

    def refresh(self) -> None:
        self._refresh_ntp()
        self._refresh_plugins()

    def _refresh_ntp(self) -> None:
        if not self._ntp:
            self._ntp_table.set_rows([(_tr("（未注入）", "(Not injected)"), "-")])
            self._ntp_table.setFixedHeight(self._ntp_table.ideal_height())
            return

        ntp = self._ntp
        rows = [
            (
                _tr("已启用", "Enabled"),
                _tr("是", "Yes") if ntp.enabled else _tr("否", "No"),
            ),
            (_tr("服务器", "Server"), ntp.server),
            (
                _tr("同步间隔", "Sync Interval"),
                f"{ntp.sync_interval_min} {_tr('分钟', 'min')}",
            ),
            (
                _tr("同步中", "Syncing"),
                _tr("是", "Yes") if ntp.is_syncing else _tr("否", "No"),
            ),
            (_tr("最后同步", "Last Sync"), ntp.last_sync_time_str()),
            (_tr("偏移量", "Offset"), ntp.offset_str()),
            (_tr("上次错误", "Last Error"), ntp.last_error or _tr("无", "None")),
        ]
        self._ntp_table.set_rows(rows)
        self._ntp_table.setFixedHeight(self._ntp_table.ideal_height())

    def _refresh_plugins(self) -> None:
        if not self._plugins:
            self._plugin_table.set_rows([(_tr("（未注入）", "(Not injected)"), "-")])
            self._plugin_table.setFixedHeight(self._plugin_table.ideal_height())
            return

        entries = getattr(self._plugins, "_entries", {})
        if not entries:
            rows: list[tuple[str, str]] = [
                (
                    _tr("（无插件）", "(No plugins)"),
                    _tr(
                        "插件目录为空或尚未加载",
                        "Plugin directory is empty or not loaded yet",
                    ),
                )
            ]
        else:
            rows = []
            for pid, entry in entries.items():
                meta = entry.meta
                enabled = "✓" if entry.enabled else "✗"
                err = f"  {_tr('错误：', 'Error:')}{entry.error}" if entry.error else ""
                rows.append(
                    (
                        pid,
                        f"{enabled}  v{meta.version}  {_tr('作者：', 'Author:')}{meta.author}{err}",
                    )
                )

        self._plugin_table.set_rows(rows)
        self._plugin_table.setFixedHeight(self._plugin_table.ideal_height())


# ────────────────────────────────────────────────────────────────────────── #
# 日志页面（带高级筛选）
# ────────────────────────────────────────────────────────────────────────── #


class LogPage(_DebugBasePage):
    """日志页：自动化引擎日志、应用日志（带高级筛选）。"""

    # 每种级别对应的 HTML 颜色
    _LEVEL_COLOR = {
        "TRACE": "#888888",
        "DEBUG": "#888888",
        "INFO": "#1a73e8",
        "SUCCESS": "#107c10",
        "WARNING": "#e67e22",
        "ERROR": "#e81123",
        "CRITICAL": "#c50f1f",
    }

    def __init__(self, auto_engine=None, parent=None):
        super().__init__(parent)
        self.setObjectName("debugLogPage")
        self._engine = auto_engine
        self._applog_refresh_pending = False
        memory_log.subscribe(self._on_memory_log_written)
        self.destroyed.connect(
            lambda *_: memory_log.unsubscribe(self._on_memory_log_written)
        )

        self._root.addWidget(TitleLabel(_tr("日志查看器", "Log Viewer")))
        self._root.addSpacing(8)

        # ── 自动化引擎日志 ────────────────────────────────────────────── #
        self._add_toolbar(
            _tr(
                "自动化引擎日志（最近 50 条，最新在上）",
                "Automation Engine Logs (latest 50, newest first)",
            )
        )

        log_card = CardWidget()
        ll = QVBoxLayout(log_card)
        ll.setContentsMargins(16, 12, 16, 12)
        self._log_edit = TextEdit()
        self._log_edit.setReadOnly(True)
        self._log_edit.setMinimumHeight(150)
        self._log_edit.setStyleSheet(
            "font-family:Consolas,'Courier New',monospace;font-size:12px;"
        )
        ll.addWidget(self._log_edit)
        self._root.addWidget(log_card)

        # ── 应用日志（带高级筛选）──────────────────────────────────────── #
        self._setup_applog_section()

        self._root.addStretch()
        self.refresh()

    def _setup_applog_section(self) -> None:
        """设置应用日志区域，包含高级筛选功能。"""
        # 筛选工具栏
        filter_card = CardWidget()
        fcl = QHBoxLayout(filter_card)
        fcl.setContentsMargins(16, 12, 16, 12)
        fcl.setSpacing(12)

        # 级别筛选
        fcl.addWidget(BodyLabel(_tr("级别：", "Level:")))
        self._log_level_combo = ComboBox()
        for lvl in (
            "ALL",
            "TRACE",
            "DEBUG",
            "INFO",
            "SUCCESS",
            "WARNING",
            "ERROR",
            "CRITICAL",
        ):
            self._log_level_combo.addItem(lvl, userData=(lvl if lvl != "ALL" else ""))
        self._log_level_combo.setFixedWidth(100)
        self._log_level_combo.currentIndexChanged.connect(self._refresh_applog)
        fcl.addWidget(self._log_level_combo)

        fcl.addSpacing(8)

        # 搜索框
        fcl.addWidget(BodyLabel(_tr("搜索：", "Search:")))
        self._search_edit = SearchLineEdit()
        self._search_edit.setPlaceholderText(
            _tr("输入关键词筛选日志...", "Enter keywords to filter logs...")
        )
        self._search_edit.setFixedWidth(200)
        self._search_edit.textChanged.connect(self._refresh_applog)
        fcl.addWidget(self._search_edit)

        # 正则开关
        self._regex_switch = SwitchButton()
        self._regex_switch.setOffText(_tr("普通", "Plain"))
        self._regex_switch.setOnText(_tr("正则", "Regex"))
        self._regex_switch.checkedChanged.connect(self._refresh_applog)
        fcl.addWidget(BodyLabel(_tr("模式：", "Mode:")))
        fcl.addWidget(self._regex_switch)

        fcl.addSpacing(8)

        # 大小写敏感
        self._case_sensitive = CheckBox(_tr("区分大小写", "Case sensitive"))
        self._case_sensitive.stateChanged.connect(self._refresh_applog)
        fcl.addWidget(self._case_sensitive)

        fcl.addStretch()

        # 自动刷新开关
        self._auto_refresh_switch = SwitchButton()
        self._auto_refresh_switch.setChecked(True)
        self._auto_refresh_switch.setOffText(_tr("关闭", "Off"))
        self._auto_refresh_switch.setOnText(_tr("开启", "On"))
        fcl.addWidget(BodyLabel(_tr("自动刷新：", "Auto refresh:")))
        fcl.addWidget(self._auto_refresh_switch)

        fcl.addSpacing(8)

        # 清空按钮
        clear_btn = ToolButton(FIF.DELETE)
        clear_btn.setToolTip(_tr("清空内存日志", "Clear memory logs"))
        clear_btn.clicked.connect(self._clear_applog)
        fcl.addWidget(clear_btn)

        # 导出按钮
        export_btn = ToolButton(FIF.SAVE)
        export_btn.setToolTip(_tr("导出日志到文件", "Export logs to file"))
        export_btn.clicked.connect(self._export_applog)
        fcl.addWidget(export_btn)

        self._root.addWidget(
            StrongBodyLabel(
                _tr("应用日志（内存，最新在上）", "App Logs (memory, newest first)")
            )
        )
        self._root.addWidget(filter_card)

        # 日志显示区域
        applog_card = CardWidget()
        al = QVBoxLayout(applog_card)
        al.setContentsMargins(16, 12, 16, 12)
        self._applog_edit = TextEdit()
        self._applog_edit.setReadOnly(True)
        self._applog_edit.setMinimumHeight(200)
        self._applog_edit.setStyleSheet(
            "font-family:Consolas,'Courier New',monospace;font-size:12px;"
        )
        al.addWidget(self._applog_edit)
        self._root.addWidget(applog_card)

        # 状态栏
        self._log_status_lbl = CaptionLabel("")
        self._root.addWidget(self._log_status_lbl)

    def refresh(self) -> None:
        self._refresh_log()
        if self._auto_refresh_switch.isChecked():
            self._refresh_applog()

    def _on_memory_log_written(self, _record: dict) -> None:
        """内存日志写入回调（可能来自非 UI 线程）。"""
        QMetaObject.invokeMethod(
            self,
            "_on_memory_record_arrived",
            Qt.ConnectionType.QueuedConnection,
        )

    @Slot()
    def _on_memory_record_arrived(self) -> None:
        if self._auto_refresh_switch.isChecked():
            self._schedule_applog_refresh()

    def _schedule_applog_refresh(self) -> None:
        if self._applog_refresh_pending:
            return
        self._applog_refresh_pending = True
        QTimer.singleShot(0, self._flush_pending_applog_refresh)

    def _flush_pending_applog_refresh(self) -> None:
        self._applog_refresh_pending = False
        self._refresh_applog()

    def _filter_level_records(
        self, records: list[dict], level_filter: str
    ) -> list[dict]:
        if not level_filter:
            return records
        return [r for r in records if r.get("level") == level_filter]

    def _collect_filtered_records(self) -> tuple[list[dict], list[dict], list[dict]]:
        level_filter: str = self._log_level_combo.currentData() or ""
        all_records = memory_log.get()
        level_records = self._filter_level_records(all_records, level_filter)

        search_text = self._search_edit.text().strip()
        use_regex = self._regex_switch.isChecked()
        case_sensitive = self._case_sensitive.isChecked()

        filtered_records = self._filter_records(
            level_records, search_text, use_regex, case_sensitive
        )
        return all_records, level_records, filtered_records

    def _refresh_log(self) -> None:
        if not self._engine:
            self._log_edit.setPlainText(
                _tr("（自动化引擎未注入）", "(Automation engine not injected)")
            )
            return

        log: list[str] = getattr(self._engine, "_log", [])
        lines = log[-50:]
        text = (
            "\n".join(reversed(lines))
            if lines
            else _tr("（暂无日志）", "(No logs yet)")
        )

        if self._log_edit.toPlainText() != text:
            self._log_edit.setPlainText(text)

    def _refresh_applog(self) -> None:
        all_records, level_records, filtered_records = self._collect_filtered_records()

        if not all_records:
            self._applog_edit.setHtml(
                f"<span style='color:gray'>{_tr('（暂无日志）', '(No logs yet)')}</span>"
            )
            self._log_status_lbl.setText(_tr("共 0 条", "0 total"))
            return

        # 最多显示最新 1000 条
        display_records = filtered_records[-1000:]

        lines_html: list[str] = []
        for r in reversed(display_records):
            color = self._LEVEL_COLOR.get(r["level"], "#333333")
            escaped = _html.escape(r["text"])
            lines_html.append(f"<span style='color:{color}'>{escaped}</span>")

        html = (
            "<br>".join(lines_html)
            if lines_html
            else f"<span style='color:gray'>{_tr('（无匹配日志）', '(No matching logs)')}</span>"
        )
        self._applog_edit.setHtml(html)

        level_total = len(level_records)
        total = len(all_records)
        shown = len(display_records)
        filtered = len(filtered_records)
        search_text = self._search_edit.text().strip()
        if search_text:
            self._log_status_lbl.setText(
                _tr(
                    f"总计 {total} 条 | 级别筛选后 {level_total} 条 | 搜索后 {filtered} 条 | 显示 {shown} 条",
                    f"Total {total} | After level filter {level_total} | After search {filtered} | Showing {shown}",
                )
            )
        else:
            self._log_status_lbl.setText(
                _tr(
                    f"总计 {total} 条 | 级别筛选后 {level_total} 条 | 显示 {shown} 条",
                    f"Total {total} | After level filter {level_total} | Showing {shown}",
                )
            )

    def _filter_records(
        self, records, search_text: str, use_regex: bool, case_sensitive: bool
    ) -> list:
        """根据搜索条件筛选日志记录。"""
        if not search_text:
            return records

        flags = 0 if case_sensitive else re.IGNORECASE

        if use_regex:
            try:
                pattern = re.compile(search_text, flags)
                return [r for r in records if pattern.search(r["text"])]
            except re.error:
                # 正则表达式错误，回退到普通文本匹配
                pass

        # 普通文本匹配
        if case_sensitive:
            return [r for r in records if search_text in r["text"]]
        else:
            search_lower = search_text.lower()
            return [r for r in records if search_lower in r["text"].lower()]

    def _clear_applog(self) -> None:
        memory_log.clear()
        self._applog_edit.setHtml(
            f"<span style='color:gray'>{_tr('（已清空）', '(Cleared)')}</span>"
        )
        self._log_status_lbl.setText(_tr("共 0 条", "0 total"))

    def _export_applog(self) -> None:
        """导出日志到文件。"""
        from PySide6.QtWidgets import QFileDialog

        all_records, level_records, records = self._collect_filtered_records()

        if not records:
            InfoBar.warning(
                title=_tr("导出失败", "Export Failed"),
                content=_tr("没有日志可导出", "No logs to export"),
                parent=self,
            )
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            _tr("导出日志", "Export Logs"),
            f"little_tree_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
            _tr(
                "文本文件 (*.txt);;所有文件 (*.*)",
                "Text Files (*.txt);;All Files (*.*)",
            ),
        )

        if not file_path:
            return

        try:
            write_text_with_uac(
                file_path,
                "\n".join(r["text"] for r in records) + "\n",
                encoding="utf-8",
                ensure_parent=True,
            )
            logger.info(
                "[调试面板] 导出日志成功：total={}, level_filtered={}, exported={}, file='{}'",
                len(all_records),
                len(level_records),
                len(records),
                file_path,
            )
            InfoBar.success(
                title=_tr("导出成功", "Export Success"),
                content=_tr(
                    f"已导出 {len(records)} 条日志",
                    f"Exported {len(records)} log entries",
                ),
                parent=self,
            )
        except Exception as e:
            logger.exception("[调试面板] 导出日志失败：file='{}'", file_path)
            InfoBar.error(
                title=_tr("导出失败", "Export Failed"),
                content=str(e),
                parent=self,
            )


# ────────────────────────────────────────────────────────────────────────── #
# 推荐系统页面
# ────────────────────────────────────────────────────────────────────────── #


class RecommendationPage(_DebugBasePage):
    """推荐系统页：首页推荐统计、时间调试。"""

    def __init__(self, home_view=None, parent=None):
        super().__init__(parent)
        self.setObjectName("debugRecommendationPage")
        self._home_view = home_view

        self._root.addWidget(
            TitleLabel(_tr("首页推荐系统", "Home Recommendation System"))
        )
        self._root.addSpacing(8)

        # 工具栏
        toolbar = self._add_toolbar(_tr("使用统计", "Usage Stats"))

        # Demo 模式按钮
        self._demo_btn = PushButton(
            FIF.LAYOUT, _tr("展示所有卡片类型 (Demo)", "Show all card types (Demo)")
        )
        self._demo_btn.setCheckable(True)
        self._demo_btn.setChecked(False)
        self._demo_btn.clicked.connect(self._toggle_demo_mode)
        toolbar.addWidget(self._demo_btn)

        # 重置统计按钮
        reset_reco_btn = PushButton(
            FIF.DELETE, _tr("重置使用统计", "Reset Usage Stats")
        )
        reset_reco_btn.clicked.connect(self._reset_reco_stats)
        toolbar.addWidget(reset_reco_btn)

        # 统计表格
        reco_card = CardWidget()
        rcl = QVBoxLayout(reco_card)
        rcl.setContentsMargins(16, 12, 16, 12)
        self._reco_table = _KVTable()
        rcl.addWidget(self._reco_table)
        self._root.addWidget(reco_card)

        # 时间调试
        self._root.addSpacing(16)
        self._root.addWidget(StrongBodyLabel(_tr("时间调试", "Time Debug")))

        time_card = CardWidget()
        tcl = QVBoxLayout(time_card)
        tcl.setContentsMargins(16, 12, 16, 12)

        # 记录进入时的显示时间（固定不变）
        from app.utils.time_utils import _ntp_utc_now

        self._initial_time = _ntp_utc_now()

        # 直接修改时间
        time_row = QHBoxLayout()
        time_row.addWidget(BodyLabel(_tr("设置时间：", "Set time:")))
        self._datetime_edit = QDateTimeEdit()
        self._datetime_edit.setCalendarPopup(True)
        self._datetime_edit.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self._datetime_edit.setFixedWidth(180)
        # 设置初始时间为进入时的时间
        self._datetime_edit.setDateTime(
            QDateTime.fromString(
                self._initial_time.strftime("%Y-%m-%d %H:%M:%S"), "yyyy-MM-dd HH:mm:ss"
            )
        )
        time_row.addWidget(self._datetime_edit)

        apply_time_btn = PrimaryPushButton(FIF.ACCEPT, _tr("应用", "Apply"))
        apply_time_btn.clicked.connect(self._apply_custom_time)
        time_row.addWidget(apply_time_btn)

        reset_time_btn = TransparentPushButton(
            FIF.CANCEL, _tr("重置为当前时间", "Reset to current time")
        )
        reset_time_btn.clicked.connect(self._reset_time_offset)
        time_row.addWidget(reset_time_btn)

        time_row.addStretch()
        tcl.addLayout(time_row)

        # 当前偏移显示
        from app.services.settings_service import SettingsService

        current_offset = SettingsService.instance().time_offset_seconds
        self._offset_status_lbl = CaptionLabel(
            _tr(f"当前偏移：{current_offset} 秒", f"Current offset: {current_offset} s")
        )
        tcl.addWidget(self._offset_status_lbl)

        # 当前时间显示
        now_time = self._initial_time.strftime("%Y-%m-%d %H:%M:%S")
        self._current_time_lbl = CaptionLabel(
            _tr(f"实际当前时间：{now_time}", f"Real current time: {now_time}")
        )
        tcl.addWidget(self._current_time_lbl)

        self._root.addWidget(time_card)
        self._root.addStretch()

        self.refresh()

    def refresh(self) -> None:
        self._refresh_reco()
        self._refresh_time_debug()

    def _refresh_reco(self) -> None:
        try:
            from app.services.recommendation_service import RecommendationService
            from app.services.recommendation_service import ALL_FEATURES, FEATURE_LABELS

            reco = RecommendationService.instance()
            rows = reco.debug_rows()
            # 附加推荐原因
            rows.append(
                ("-", _tr("推荐原因（智能学习）", "Recommendation reasons (learning)"))
            )
            for fid in ALL_FEATURES:
                reason = reco.get_reason(fid)
                name = FEATURE_LABELS.get(fid, fid)
                rows.append(
                    (
                        f"  {name}",
                        reason if reason else _tr("（暂无原因）", "(No reason yet)"),
                    )
                )
            # 附加当前推荐排名
            rows.append(("-", _tr("综合排名", "Combined ranking")))
            ranked = reco.ranked()
            for rank, (fid, score) in enumerate(ranked, 1):
                rows.append(
                    (f"  {_tr('排名', 'Rank')} #{rank}", f"{fid}  ->  {score:.4f}")
                )
        except Exception as e:
            rows = [(_tr("错误", "Error"), str(e))]

        self._reco_table.set_rows(rows)
        self._reco_table.setFixedHeight(self._reco_table.ideal_height())

    def _toggle_demo_mode(self, checked: bool) -> None:
        if self._home_view is not None:
            self._home_view.set_demo_mode(checked)
            self._demo_btn.setText(
                _tr("退出 Demo 模式", "Exit Demo mode")
                if checked
                else _tr("展示所有卡片类型 (Demo)", "Show all card types (Demo)")
            )

    def _reset_reco_stats(self) -> None:
        try:
            from app.services.recommendation_service import RecommendationService

            box = MessageBox(
                _tr("重置使用统计", "Reset Usage Stats"),
                _tr(
                    "将清空所有首页推荐算法的历史记录，无法恢复。是否继续？",
                    "This will clear all history of home recommendation algorithm and cannot be undone. Continue?",
                ),
                self,
            )
            if box.exec():
                RecommendationService.instance().reset()
                self._refresh_reco()
        except Exception as e:
            from app.utils.logger import logger

            logger.error("重置推荐统计失败：{}", e)

    def _refresh_time_debug(self) -> None:
        """刷新时间调试信息"""
        try:
            from app.services.settings_service import SettingsService
            from datetime import datetime

            offset = SettingsService.instance().time_offset_seconds
            self._offset_status_lbl.setText(
                _tr(f"当前偏移：{offset} 秒", f"Current offset: {offset} s")
            )
            # 显示实际当前时间（无偏移）
            real_now = datetime.now()
            self._current_time_lbl.setText(
                _tr(
                    f"实际当前时间：{real_now.strftime('%Y-%m-%d %H:%M:%S')}",
                    f"Real current time: {real_now.strftime('%Y-%m-%d %H:%M:%S')}",
                )
            )
        except Exception:
            pass

    def _apply_custom_time(self) -> None:
        """应用自定义时间（计算偏移）"""
        try:
            from app.services.settings_service import SettingsService
            from datetime import datetime

            # 获取用户设置的时间
            custom_dt = self._datetime_edit.dateTime().toPython()
            # 获取实际当前时间
            real_now = datetime.now()
            # 计算偏移秒数
            offset = int((custom_dt - real_now).total_seconds())
            SettingsService.instance().set_time_offset_seconds(offset)
            self._refresh_time_debug()
        except Exception as e:
            from app.utils.logger import logger

            logger.error("应用自定义时间失败：{}", e)

    def _reset_time_offset(self) -> None:
        """重置时间偏移"""
        try:
            from app.services.settings_service import SettingsService
            from datetime import datetime

            SettingsService.instance().set_time_offset_seconds(0)
            # 重置后将输入框更新为当前实际时间
            now = datetime.now()
            self._datetime_edit.setDateTime(
                QDateTime.fromString(
                    now.strftime("%Y-%m-%d %H:%M:%S"), "yyyy-MM-dd HH:mm:ss"
                )
            )
            self._refresh_time_debug()
        except Exception as e:
            from app.utils.logger import logger

            logger.error("重置时间偏移失败：{}", e)


class NotificationDebugPage(_DebugBasePage):
    """通知调试页：覆盖按钮/进度/图片/可变及组合测试。"""

    def __init__(self, notification_service=None, icon_path: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("debugNotificationPage")
        self._notif = notification_service
        self._icon_path = icon_path
        self._timers: list[QTimer] = []

        self._root.addWidget(TitleLabel(_tr("通知测试", "Notification Tests")))
        self._root.addSpacing(8)

        _, card_lay = self._add_section_card(
            _tr("通知类型调试", "Notification Type Tests")
        )

        if self._notif is None:
            card_lay.addWidget(
                CaptionLabel(_tr("通知服务未注入", "Notification service not injected"))
            )
            return

        buttons: list[tuple[str, Callable[[], None]]] = [
            (_tr("基础通知", "Basic notification"), self._test_basic),
            (
                _tr("按钮通知（稍后提醒/权限风格）", "Action notification"),
                self._test_actions,
            ),
            (_tr("进度条通知", "Progress notification"), self._test_progress),
            (_tr("图片通知（小树图标）", "Image notification"), self._test_image),
            (_tr("可变通知（倒计时）", "Mutable countdown"), self._test_mutable),
            (_tr("全要素组合通知", "All-in-one combined"), self._test_combined),
        ]

        for text, handler in buttons:
            btn = PushButton(text)
            btn.clicked.connect(handler)
            card_lay.addWidget(btn)

        self._root.addStretch()

    def refresh(self) -> None:
        pass

    def _test_basic(self) -> None:
        self._notif.show_notification(
            _tr("测试通知", "Test Notification"),
            _tr("这是基础通知内容", "This is a basic notification"),
            level="info",
        )

    def _test_actions(self) -> None:
        handle = self._notif.show_notification(
            _tr("权限请求示例", "Permission Request Sample"),
            _tr("请选择处理动作", "Choose an action"),
            level="warning",
            duration_ms=0,
            actions=[
                ToastAction("always", _tr("始终允许", "Always allow"), kind="primary"),
                ToastAction("once", _tr("本次允许", "Allow once")),
                ToastAction("deny", _tr("拒绝", "Deny"), kind="danger"),
            ],
        )
        if handle is not None:
            handle.action_triggered.connect(
                lambda aid: self._notif.show(
                    _tr("操作结果", "Action result"), f"action={aid}"
                )
            )

    def _test_progress(self) -> None:
        handle = self._notif.show_notification(
            _tr("下载中", "Downloading"),
            _tr("正在获取资源...", "Fetching resources..."),
            level="info",
            duration_ms=0,
            progress=(0, 100),
            progress_text="0%",
        )
        if handle is None:
            return

        timer = QTimer(self)
        state = {"p": 0}

        def _tick() -> None:
            state["p"] += 10
            p = min(100, state["p"])
            handle.update(progress_value=p, progress_max=100, progress_text=f"{p}%")
            if p >= 100:
                timer.stop()
                handle.update(message=_tr("下载完成", "Download completed"))
                QTimer.singleShot(1200, handle.close)

        timer.timeout.connect(_tick)
        timer.start(300)
        self._timers.append(timer)

    def _test_image(self) -> None:
        self._notif.show_notification(
            _tr("图标通知", "Icon notification"),
            _tr("这是带图片的通知", "Notification with image"),
            level="success",
            image_path=self._icon_path,
        )

    def _test_mutable(self) -> None:
        total = 10
        handle = self._notif.show_notification(
            _tr("稍后提醒中", "Snooze active"),
            _tr("剩余 00:10", "Remaining 00:10"),
            duration_ms=0,
            level="warning",
            progress=(0, total),
            progress_text=_tr("倒计时进行中", "Countdown running"),
        )
        if handle is None:
            return

        timer = QTimer(self)
        state = {"elapsed": 0}

        def _tick() -> None:
            state["elapsed"] += 1
            left = max(0, total - state["elapsed"])
            handle.update(
                message=_tr(f"剩余 00:{left:02d}", f"Remaining 00:{left:02d}"),
                progress_value=state["elapsed"],
                progress_max=total,
            )
            if left <= 0:
                timer.stop()
                handle.update(title=_tr("倒计时结束", "Countdown finished"), message="")
                QTimer.singleShot(800, handle.close)

        timer.timeout.connect(_tick)
        timer.start(1000)
        self._timers.append(timer)

    def _test_combined(self) -> None:
        total = 20
        handle = self._notif.show_notification(
            _tr("组合通知示例", "Combined notification sample"),
            _tr(
                "同时包含按钮、进度、图片与可变内容",
                "Includes actions, progress, image and mutable content",
            ),
            duration_ms=0,
            level="info",
            image_path=self._icon_path,
            progress=(0, total),
            progress_text="0%",
            actions=[
                ToastAction("pause", _tr("暂停", "Pause")),
                ToastAction("done", _tr("完成", "Done"), kind="primary"),
                ToastAction("cancel", _tr("取消", "Cancel"), kind="danger"),
            ],
        )
        if handle is None:
            return

        timer = QTimer(self)
        state = {"elapsed": 0, "paused": False}

        def _tick() -> None:
            if state["paused"]:
                return
            state["elapsed"] += 1
            p = min(total, state["elapsed"])
            percent = int(p * 100 / total)
            handle.update(
                message=_tr(f"进行中 {percent}%", f"Running {percent}%"),
                progress_value=p,
                progress_max=total,
                progress_text=f"{percent}%",
            )
            if p >= total:
                timer.stop()
                handle.update(title=_tr("任务完成", "Task completed"), message="")
                QTimer.singleShot(1000, handle.close)

        def _on_action(action_id: str) -> None:
            if action_id == "pause":
                state["paused"] = not state["paused"]
            elif action_id == "done":
                state["elapsed"] = total
                _tick()
            elif action_id == "cancel":
                timer.stop()
                handle.close()

        handle.action_triggered.connect(_on_action)
        timer.timeout.connect(_tick)
        timer.start(500)
        self._timers.append(timer)


class UpdateDebugPage(_DebugBasePage):
    """更新系统调试页。"""

    def __init__(
        self,
        update_service: UpdateService | None = None,
        open_update_window: Callable[[], None] | None = None,
        open_post_update_window: Callable[[], None] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("debugUpdatePage")
        self._svc = update_service
        self._open_update_window = open_update_window or (lambda: None)
        self._open_post_update_window = open_post_update_window or (lambda: None)

        self._root.addWidget(TitleLabel(_tr("更新系统", "Update System")))
        self._root.addSpacing(8)

        toolbar = self._add_toolbar(_tr("调试操作", "Debug Actions"))
        toolbar.addWidget(BodyLabel(_tr("频道：", "Channel:")))
        self._channel_combo = ComboBox(self)
        for label, key in (
            (_tr("稳定版（推荐）", "Stable (recommended)"), "stable"),
            (_tr("测试版", "Beta"), "beta"),
            (_tr("开发版", "Dev"), "dev"),
        ):
            self._channel_combo.addItem(label, userData=key)
        self._channel_combo.currentIndexChanged.connect(self._on_channel_changed)
        toolbar.addWidget(self._channel_combo)

        self._check_btn = PushButton(FIF.SYNC, _tr("检查更新", "Check Updates"))
        self._check_btn.clicked.connect(self._on_check_clicked)
        toolbar.addWidget(self._check_btn)

        self._open_btn = PushButton(FIF.DOWNLOAD, _tr("打开更新窗口", "Open Update Window"))
        self._open_btn.clicked.connect(lambda: self._open_update_window())
        toolbar.addWidget(self._open_btn)

        self._open_post_btn = PushButton(FIF.INFO, _tr("打开更新后窗口", "Open Post-Update Window"))
        self._open_post_btn.clicked.connect(lambda: self._open_post_update_window())
        toolbar.addWidget(self._open_post_btn)

        self._clear_post_btn = TransparentPushButton(FIF.DELETE, _tr("清除更新后缓存", "Clear Post-Update Cache"))
        self._clear_post_btn.clicked.connect(self._on_clear_post_clicked)
        toolbar.addWidget(self._clear_post_btn)

        _, sl = self._add_section_card(_tr("状态摘要", "Status Summary"))
        self._status_table = _KVTable()
        sl.addWidget(self._status_table)

        _, cl = self._add_section_card(_tr("更新日志预览", "Changelog Preview"))
        self._changelog_edit = TextEdit(self)
        self._changelog_edit.setReadOnly(True)
        self._changelog_edit.setMinimumHeight(240)
        cl.addWidget(self._changelog_edit)

        self._root.addStretch()

        if self._svc is not None:
            self._svc.stateChanged.connect(self.refresh)

        self.refresh()

    def refresh(self) -> None:
        if self._svc is None:
            rows = [(_tr("更新服务", "Update Service"), _tr("未注入", "Not injected"))]
            self._status_table.set_rows(rows)
            self._status_table.setFixedHeight(self._status_table.ideal_height())
            self._changelog_edit.setPlainText(_tr("暂无数据", "No data"))
            return

        current_channel = self._svc.current_channel
        combo_index = -1
        for i in range(self._channel_combo.count()):
            if self._channel_combo.itemData(i) == current_channel:
                combo_index = i
                break
        if combo_index >= 0 and self._channel_combo.currentIndex() != combo_index:
            self._channel_combo.blockSignals(True)
            self._channel_combo.setCurrentIndex(combo_index)
            self._channel_combo.blockSignals(False)

        latest = self._svc.latest_info
        pending = self._svc.peek_post_update_notice()
        last_download = self._svc.last_download
        rows = [
            (_tr("当前版本", "Current Version"), APP_VERSION),
            (_tr("当前频道", "Current Channel"), str(current_channel)),
            (_tr("检查中", "Checking"), _tr("是", "Yes") if self._svc.is_checking else _tr("否", "No")),
            (_tr("下载中", "Downloading"), _tr("是", "Yes") if self._svc.is_downloading else _tr("否", "No")),
            (_tr("缓存最新版本", "Cached Latest Version"), latest.version if isinstance(latest, UpdateInfo) else "-"),
            (_tr("是否可更新", "Update Available"), _tr("是", "Yes") if self._svc.is_update_available(latest) else _tr("否", "No")),
            (_tr("发布日期", "Release Date"), latest.release_date if isinstance(latest, UpdateInfo) else "-"),
            (_tr("最低自动升级版本", "Min Auto-Upgrade Version"), latest.min_version if isinstance(latest, UpdateInfo) and latest.min_version else "-"),
            (_tr("强制更新", "Mandatory"), _tr("是", "Yes") if isinstance(latest, UpdateInfo) and latest.mandatory else _tr("否", "No")),
            (_tr("上次检查时间", "Last Check"), self._format_timestamp(self._svc.last_checked_at())),
            (_tr("待展示更新后说明", "Pending Post-Update Notice"), pending.version if isinstance(pending, UpdateInfo) else "-"),
            (_tr("下载的安装器", "Downloaded Installer"), last_download.get("installer_path", "-")),
            (_tr("上次错误", "Last Error"), self._svc.last_error or _tr("无", "None")),
        ]
        self._status_table.set_rows(rows)
        self._status_table.setFixedHeight(self._status_table.ideal_height())

        changelog = ""
        if isinstance(latest, UpdateInfo) and latest.changelog:
            changelog = latest.changelog
        elif isinstance(pending, UpdateInfo) and pending.changelog:
            changelog = pending.changelog
        else:
            changelog = _tr("暂无更新日志。", "No changelog available.")

        try:
            self._changelog_edit.setMarkdown(changelog)
        except Exception:
            self._changelog_edit.setPlainText(changelog)

        self._check_btn.setEnabled(not self._svc.is_checking)
        self._clear_post_btn.setEnabled(pending is not None)

    @staticmethod
    def _format_timestamp(value: float) -> str:
        if not value:
            return "-"
        try:
            return datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return "-"

    def _on_channel_changed(self, _: int) -> None:
        if self._svc is None:
            return
        channel = self._channel_combo.currentData()
        if not channel:
            return
        self._svc.set_channel(str(channel))
        self.refresh()

    def _on_check_clicked(self) -> None:
        if self._svc is None:
            return
        self._svc.check_for_updates()

    def _on_clear_post_clicked(self) -> None:
        if self._svc is None:
            return
        self._svc.clear_post_update_notice()
        self.refresh()


class PluginDebugPage(_DebugBasePage):
    """插件调试页：默认空，可由插件动态注册一个 Pivot 子页。"""

    def __init__(self, plugin_manager=None, parent=None):
        super().__init__(parent)
        self.setObjectName("debugPluginPage")
        self._plugins = plugin_manager
        self._pivot = Pivot()
        self._stacked = QStackedWidget(self)
        self._empty_tip = CaptionLabel(
            _tr(
                "暂无插件调试页，插件可通过 API 注册。",
                "No plugin debug page registered yet.",
            )
        )
        self._widgets: list[QWidget] = []
        self._page_signature: tuple[tuple[str, str], ...] = ()

        self._root.addWidget(TitleLabel(_tr("插件调试", "Plugin Debug")))
        self._root.addSpacing(8)
        self._root.addWidget(self._pivot, 0, Qt.AlignLeft)
        self._root.addWidget(self._stacked, 1)
        self._root.addWidget(self._empty_tip)

        self._rebuild_pages()

    def refresh(self) -> None:
        self._rebuild_pages()
        current = self._stacked.currentWidget()
        if current is not None and hasattr(current, "refresh"):
            try:
                current.refresh()
            except Exception:
                logger.exception("刷新插件调试页子面板失败")

    def _clear_pages(self) -> None:
        if hasattr(self._pivot, "clear"):
            self._pivot.clear()
        while self._stacked.count() > 0:
            widget = self._stacked.widget(0)
            self._stacked.removeWidget(widget)
            widget.deleteLater()
        self._widgets.clear()

    def _rebuild_pages(self) -> None:
        self._clear_pages()
        if self._plugins is None or not hasattr(self._plugins, "collect_debug_pages"):
            self._empty_tip.setText(
                _tr("插件管理器未注入。", "Plugin manager was not injected.")
            )
            self._empty_tip.show()
            self._pivot.hide()
            self._stacked.hide()
            return

        pages = self._plugins.collect_debug_pages()
        if not pages:
            self._page_signature = ()
            self._empty_tip.setText(
                _tr(
                    "暂无插件调试页，插件可通过 API 注册。",
                    "No plugin debug page registered yet.",
                )
            )
            self._empty_tip.show()
            self._pivot.hide()
            self._stacked.hide()
            return

        signature = tuple(
            (str(spec.get("plugin_id", "")), str(spec.get("label", "")))
            for spec in pages
        )
        if signature == self._page_signature and self._stacked.count() > 0:
            return
        self._page_signature = signature

        self._empty_tip.hide()
        self._pivot.show()
        self._stacked.show()

        for idx, spec in enumerate(pages):
            factory = spec.get("factory")
            if not callable(factory):
                continue
            try:
                try:
                    page = factory(self)
                except TypeError:
                    page = factory()
            except Exception:
                logger.exception("构建插件调试页失败: {}", spec.get("plugin_id", ""))
                continue
            if page is None or not isinstance(page, QWidget):
                continue

            route = f"pluginDebug.{spec.get('plugin_id', 'unknown')}"
            title = str(
                spec.get("label")
                or spec.get("plugin_name")
                or spec.get("plugin_id")
                or "Plugin"
            )
            self._stacked.addWidget(page)
            self._widgets.append(page)
            self._pivot.addItem(
                routeKey=route,
                text=title,
                onClick=lambda w=page: self._stacked.setCurrentWidget(w),
            )
            if idx == 0:
                self._stacked.setCurrentWidget(page)
                self._pivot.setCurrentItem(route)


# ────────────────────────────────────────────────────────────────────────── #
# 主调试窗口（FluentWindow）
# ────────────────────────────────────────────────────────────────────────── #


class DebugWindow(MSFluentWindow):
    """
    独立调试窗口，基于 MSFluentWindow，仅可通过 ltclock://open/debug 唤起。
    不注册到主窗口导航栏，直接 show() 弹出。
    """

    def __init__(
        self,
        clock_service=None,
        alarm_service=None,
        ntp_service=None,
        plugin_manager=None,
        auto_engine=None,
        home_view=None,
        notification_service=None,
        update_service: UpdateService | None = None,
        open_update_window: Callable[[], None] | None = None,
        open_post_update_window: Callable[[], None] | None = None,
    ):
        super().__init__()
        self.setWindowTitle(
            _tr(f"{APP_NAME}  —  调试面板", f"{APP_NAME} - Debug Panel")
        )
        self.setWindowIcon(QIcon(ICON_PATH) if ICON_PATH else QIcon())
        self.resize(960, 720)
        self.setMinimumSize(800, 600)

        self._clock = clock_service
        self._alarm = alarm_service
        self._ntp = ntp_service
        self._plugins = plugin_manager
        self._engine = auto_engine
        self._home_view = home_view
        self._notification_service = notification_service
        self._first_use_setup_window: Optional[QWidget] = None

        # 创建各页面并包装在滚动区域中
        self._overview_page = self._wrap_scroll(OverviewPage(), "overviewPage")
        self._timer_thread_page = self._wrap_scroll(
            TimerThreadPage(clock_service, alarm_service, ntp_service),
            "timerThreadPage",
        )
        self._services_page = self._wrap_scroll(
            ServicesPage(ntp_service, plugin_manager), "servicesPage"
        )
        self._log_page = self._wrap_scroll(LogPage(auto_engine), "logPage")
        self._recommendation_page = self._wrap_scroll(
            RecommendationPage(home_view), "recommendationPage"
        )
        self._notification_page = self._wrap_scroll(
            NotificationDebugPage(notification_service, ICON_PATH),
            "notificationPage",
        )
        self._update_page = self._wrap_scroll(
            UpdateDebugPage(
                update_service,
                open_update_window=open_update_window,
                open_post_update_window=open_post_update_window,
            ),
            "updatePage",
        )
        self._plugin_debug_page = self._wrap_scroll(
            PluginDebugPage(plugin_manager),
            "pluginDebugPage",
        )

        # 添加到导航
        self.addSubInterface(self._overview_page, FIF.HOME, _tr("概览", "Overview"))
        self.addSubInterface(
            self._timer_thread_page, FIF.SYNC, _tr("计时器与线程", "Timers & Threads")
        )
        self.addSubInterface(
            self._services_page, FIF.UPDATE, _tr("服务状态", "Service Status")
        )
        self.addSubInterface(self._log_page, FIF.DOCUMENT, _tr("日志", "Logs"))
        self.addSubInterface(
            self._recommendation_page, FIF.LAYOUT, _tr("推荐系统", "Recommendation")
        )
        self.addSubInterface(
            self._notification_page, FIF.RINGER, _tr("通知测试", "Notification")
        )
        self.addSubInterface(
            self._update_page, FIF.DOWNLOAD, _tr("更新系统", "Updates")
        )
        self.addSubInterface(
            self._plugin_debug_page, FIF.APPLICATION, _tr("插件调试", "Plugin Debug")
        )

        # 刷新按钮和状态标签添加到标题栏
        from qfluentwidgets import FluentTitleBarButton

        self._refresh_btn = FluentTitleBarButton(FIF.SYNC, self)
        self._refresh_btn.setToolTip(_tr("立即刷新", "Refresh now"))
        self._refresh_btn.clicked.connect(self.refresh)
        self.titleBar.buttonLayout.insertWidget(0, self._refresh_btn)

        self._first_use_btn = FluentTitleBarButton(FIF.SETTING, self)
        self._first_use_btn.setToolTip(_tr("打开初次使用设置", "Open first-use setup"))
        self._first_use_btn.clicked.connect(self._open_first_use_setup)
        self.titleBar.buttonLayout.insertWidget(1, self._first_use_btn)

        self._status_lbl = CaptionLabel("")
        self.titleBar.buttonLayout.insertWidget(2, self._status_lbl)

        # 自动刷新定时器
        self._auto_timer = QTimer(self)
        self._auto_timer.setInterval(2000)
        self._auto_timer.timeout.connect(self.refresh)

        self.refresh()

    def showEvent(self, event):
        super().showEvent(event)
        self._auto_timer.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._auto_timer.stop()

    @staticmethod
    def _wrap_scroll(page: QWidget, object_name: str) -> SmoothScrollArea:
        """将页面包装在滚动区域中"""
        scroll = SmoothScrollArea()
        scroll.setObjectName(object_name)
        scroll.setWidget(page)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.enableTransparentBackground()
        return scroll

    def refresh(self) -> None:
        """刷新所有页面数据。"""
        self._overview_page.widget().refresh()
        self._timer_thread_page.widget().refresh()
        self._services_page.widget().refresh()
        self._log_page.widget().refresh()
        self._recommendation_page.widget().refresh()
        self._notification_page.widget().refresh()
        self._update_page.widget().refresh()
        self._plugin_debug_page.widget().refresh()

        self._status_lbl.setText(
            _tr(
                f"最后刷新：{datetime.now().strftime('%H:%M:%S')}",
                f"Last refresh: {datetime.now().strftime('%H:%M:%S')}",
            )
        )

    def _open_first_use_setup(self) -> None:
        """在调试窗口中直接打开首次使用设置向导。"""
        existing = self._first_use_setup_window
        if existing is not None and existing.isVisible():
            existing.showNormal()
            existing.raise_()
            existing.activateWindow()
            return

        from app.views.first_use_setup import FirstUseSetupWindow

        window = FirstUseSetupWindow()
        self._first_use_setup_window = window
        window.destroyed.connect(self._on_first_use_window_destroyed)
        window.show()
        window.raise_()
        window.activateWindow()

    @Slot()
    def _on_first_use_window_destroyed(self) -> None:
        self._first_use_setup_window = None

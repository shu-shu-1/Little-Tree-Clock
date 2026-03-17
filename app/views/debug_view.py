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
from typing import Optional

from PySide6.QtCore import Qt, QTimer, QThread, QDateTime, QMetaObject, Slot
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication, QVBoxLayout, QHBoxLayout, QWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QSizePolicy, QFrame, QDateTimeEdit,
)
from qfluentwidgets import (
    FluentWindow, MSFluentWindow, FluentIcon as FIF, PushButton,
    CardWidget, SpinBox, TitleLabel, StrongBodyLabel, CaptionLabel,
    TextEdit, ComboBox, ToolButton, LineEdit,
    NavigationItemPosition, SubtitleLabel, BodyLabel,
    SwitchButton, CheckBox, PrimaryPushButton, TransparentPushButton,
    MessageBox, InfoBar, InfoBarPosition, SmoothScrollArea,
    TableWidget, SearchLineEdit,
)

from app.constants import APP_NAME, LONG_VER, ICON_PATH
from app.services.i18n_service import I18nService, LANG_EN_US
from app.utils.fs import write_text_with_uac
from app.utils.logger import memory_log, logger

# ────────────────────────────────────────────────────────────────────────── #
# 可选：psutil 内存信息
# ────────────────────────────────────────────────────────────────────────── #
try:
    import psutil as _psutil
    _PROC = _psutil.Process()
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False

_START_TIME: float = time.monotonic()   # 记录模块首次导入时刻


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

        self._refresh_runtime()

    def refresh(self) -> None:
        self._refresh_runtime()

    def _refresh_runtime(self) -> None:
        rows: list[tuple[str, str]] = [
            ("PID",           str(os.getpid())),
            ("Python",        sys.version.split()[0]),
            (_tr("平台", "Platform"),          sys.platform),
            (_tr("运行时长", "Uptime"),      _uptime_str(_START_TIME)),
            (_tr("Python 线程数", "Python Threads"), str(threading.active_count())),
            (_tr("当前时间", "Current Time"),      datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        ]

        if _HAS_PSUTIL:
            try:
                mem = _PROC.memory_info()
                rows.insert(4, (_tr("RSS 内存", "RSS Memory"), _fmt_bytes(mem.rss)))
                rows.insert(5, (_tr("VMS 内存", "VMS Memory"), _fmt_bytes(mem.vms)))
                rows.insert(6, (_tr("CPU 占用", "CPU Usage"), f"{_PROC.cpu_percent(interval=None):.1f}%"))
            except Exception:
                pass

        self._runtime_table.set_rows(rows)
        self._runtime_table.setFixedHeight(self._runtime_table.ideal_height())


# ────────────────────────────────────────────────────────────────────────── #
# 计时器与线程页面
# ────────────────────────────────────────────────────────────────────────── #

class TimerThreadPage(_DebugBasePage):
    """计时器与线程页：QTimer、QThread、Python 线程。"""

    def __init__(self, clock_service=None, alarm_service=None, ntp_service=None, parent=None):
        super().__init__(parent)
        self.setObjectName("debugTimerThreadPage")
        self._clock = clock_service
        self._alarm = alarm_service
        self._ntp = ntp_service

        self._root.addWidget(TitleLabel(_tr("计时器与线程", "Timers & Threads")))
        self._root.addSpacing(8)

        _, tl = self._add_section_card(_tr("核心 QTimer / 线程", "Core QTimer / Threads"))
        self._timer_table = _KVTable()
        tl.addWidget(self._timer_table)

        _, qtl = self._add_section_card(_tr("Qt 线程（QThread）", "Qt Threads (QThread)"))
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
                active    = _tr("✓ 运行中", "✓ Running") if tmr.isActive() else _tr("✗ 已停止", "✗ Stopped")
                interval  = f"{tmr.interval()} ms"
                shot      = _tr("单次", "Single") if tmr.isSingleShot() else _tr("循环", "Repeating")
                remaining = (f"{tmr.remainingTime()} ms"
                             if tmr.isActive() else "-")
                return (name, f"{active}  |  {_tr('间隔', 'Interval')} {interval}  |  {shot}  |  {_tr('剩余', 'Remaining')} {remaining}")
            except AttributeError:
                return (name, _tr("（服务未注入）", "(Service not injected)"))

        if self._clock:
            rows.append(_qtimer_row("ClockService._timer      [QTimer]",
                                    self._clock, "_timer"))

        if self._alarm:
            rows.append(_qtimer_row("AlarmService._timer      [QTimer]",
                                    self._alarm, "_timer"))

        if self._ntp:
            t = getattr(self._ntp, "_thread", None)
            if t is None:
                ntp_val = _tr("（线程未启动）", "(Thread not started)")
            else:
                alive  = _tr("✓ 存活", "✓ Alive") if t.is_alive() else _tr("✗ 已终止", "✗ Terminated")
                daemon = _tr("守护", "Daemon") if t.daemon else _tr("普通", "Normal")
                ntp_val = (f"{alive}  |  {daemon} {_tr('线程', 'Thread')}  |  "
                           f"name={t.name}  |  id={t.ident}")
            rows.append(("NtpService._thread   [Python Thread]", ntp_val))

        if not rows:
            rows = [(_tr("（无）", "(None)"), _tr("服务未注入到调试窗口", "Services were not injected into debug window"))]

        self._timer_table.set_rows(rows)
        self._timer_table.setFixedHeight(self._timer_table.ideal_height())

    def _refresh_qthreads(self) -> None:
        app = QApplication.instance()
        rows: list[tuple[str, str]] = []
        if app:
            for obj in app.findChildren(QThread):
                name  = obj.objectName() or obj.__class__.__name__
                alive = _tr("✓ 运行中", "✓ Running") if obj.isRunning() else _tr("✗ 已停止", "✗ Stopped")
                rows.append((name, f"{alive}  |  id={id(obj):#x}"))

        if not rows:
            rows = [(_tr("（无独立 QThread）", "(No dedicated QThread)"), _tr("所有逻辑均在主线程完成", "All logic runs on the main thread"))]

        self._qthread_table.set_rows(rows)
        self._qthread_table.setFixedHeight(self._qthread_table.ideal_height())

    def _refresh_pythreads(self) -> None:
        main_id = threading.main_thread().ident
        rows: list[tuple[str, str]] = []

        for t in sorted(threading.enumerate(), key=lambda x: x.ident or 0):
            tag    = _tr(" [主线程]", " [Main]") if t.ident == main_id else ""
            daemon = _tr("守护", "Daemon") if t.daemon else _tr("普通", "Normal")
            alive  = _tr("✓ 存活", "✓ Alive") if t.is_alive() else _tr("✗ 已终止", "✗ Terminated")
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
            (_tr("已启用", "Enabled"),   _tr("是", "Yes") if ntp.enabled else _tr("否", "No")),
            (_tr("服务器", "Server"),   ntp.server),
            (_tr("同步间隔", "Sync Interval"), f"{ntp.sync_interval_min} {_tr('分钟', 'min')}"),
            (_tr("同步中", "Syncing"),   _tr("是", "Yes") if ntp.is_syncing else _tr("否", "No")),
            (_tr("最后同步", "Last Sync"), ntp.last_sync_time_str()),
            (_tr("偏移量", "Offset"),   ntp.offset_str()),
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
            rows: list[tuple[str, str]] = [(_tr("（无插件）", "(No plugins)"), _tr("插件目录为空或尚未加载", "Plugin directory is empty or not loaded yet"))]
        else:
            rows = []
            for pid, entry in entries.items():
                meta    = entry.meta
                enabled = "✓" if entry.enabled else "✗"
                err     = f"  {_tr('错误：', 'Error:')}{entry.error}" if entry.error else ""
                rows.append((pid,
                             f"{enabled}  v{meta.version}  {_tr('作者：', 'Author:')}{meta.author}{err}"))

        self._plugin_table.set_rows(rows)
        self._plugin_table.setFixedHeight(self._plugin_table.ideal_height())


# ────────────────────────────────────────────────────────────────────────── #
# 日志页面（带高级筛选）
# ────────────────────────────────────────────────────────────────────────── #

class LogPage(_DebugBasePage):
    """日志页：自动化引擎日志、应用日志（带高级筛选）。"""

    # 每种级别对应的 HTML 颜色
    _LEVEL_COLOR = {
        "TRACE":    "#888888",
        "DEBUG":    "#888888",
        "INFO":     "#1a73e8",
        "SUCCESS":  "#107c10",
        "WARNING":  "#e67e22",
        "ERROR":    "#e81123",
        "CRITICAL": "#c50f1f",
    }

    def __init__(self, auto_engine=None, parent=None):
        super().__init__(parent)
        self.setObjectName("debugLogPage")
        self._engine = auto_engine
        self._applog_refresh_pending = False
        memory_log.subscribe(self._on_memory_log_written)
        self.destroyed.connect(lambda *_: memory_log.unsubscribe(self._on_memory_log_written))

        self._root.addWidget(TitleLabel(_tr("日志查看器", "Log Viewer")))
        self._root.addSpacing(8)

        # ── 自动化引擎日志 ────────────────────────────────────────────── #
        self._add_toolbar(_tr("自动化引擎日志（最近 50 条，最新在上）", "Automation Engine Logs (latest 50, newest first)"))

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
        for lvl in ("ALL", "TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"):
            self._log_level_combo.addItem(lvl, userData=(lvl if lvl != "ALL" else ""))
        self._log_level_combo.setFixedWidth(100)
        self._log_level_combo.currentIndexChanged.connect(self._refresh_applog)
        fcl.addWidget(self._log_level_combo)

        fcl.addSpacing(8)

        # 搜索框
        fcl.addWidget(BodyLabel(_tr("搜索：", "Search:")))
        self._search_edit = SearchLineEdit()
        self._search_edit.setPlaceholderText(_tr("输入关键词筛选日志...", "Enter keywords to filter logs..."))
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

        self._root.addWidget(StrongBodyLabel(_tr("应用日志（内存，最新在上）", "App Logs (memory, newest first)")))
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

    def _filter_level_records(self, records: list[dict], level_filter: str) -> list[dict]:
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
            self._log_edit.setPlainText(_tr("（自动化引擎未注入）", "(Automation engine not injected)"))
            return

        log: list[str] = getattr(self._engine, "_log", [])
        lines = log[-50:]
        text  = "\n".join(reversed(lines)) if lines else _tr("（暂无日志）", "(No logs yet)")

        if self._log_edit.toPlainText() != text:
            self._log_edit.setPlainText(text)

    def _refresh_applog(self) -> None:
        all_records, level_records, filtered_records = self._collect_filtered_records()

        if not all_records:
            self._applog_edit.setHtml(f"<span style='color:gray'>{_tr('（暂无日志）', '(No logs yet)')}</span>")
            self._log_status_lbl.setText(_tr("共 0 条", "0 total"))
            return

        # 最多显示最新 1000 条
        display_records = filtered_records[-1000:]

        lines_html: list[str] = []
        for r in reversed(display_records):
            color = self._LEVEL_COLOR.get(r["level"], "#333333")
            escaped = _html.escape(r["text"])
            lines_html.append(
                f"<span style='color:{color}'>{escaped}</span>"
            )

        html = "<br>".join(lines_html) if lines_html else f"<span style='color:gray'>{_tr('（无匹配日志）', '(No matching logs)')}</span>"
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

    def _filter_records(self, records, search_text: str, use_regex: bool, case_sensitive: bool) -> list:
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
        self._applog_edit.setHtml(f"<span style='color:gray'>{_tr('（已清空）', '(Cleared)')}</span>")
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
            _tr("文本文件 (*.txt);;所有文件 (*.*)", "Text Files (*.txt);;All Files (*.*)")
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
                content=_tr(f"已导出 {len(records)} 条日志", f"Exported {len(records)} log entries"),
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

        self._root.addWidget(TitleLabel(_tr("首页推荐系统", "Home Recommendation System")))
        self._root.addSpacing(8)

        # 工具栏
        toolbar = self._add_toolbar(_tr("使用统计", "Usage Stats"))

        # Demo 模式按钮
        self._demo_btn = PushButton(FIF.LAYOUT, _tr("展示所有卡片类型 (Demo)", "Show all card types (Demo)"))
        self._demo_btn.setCheckable(True)
        self._demo_btn.setChecked(False)
        self._demo_btn.clicked.connect(self._toggle_demo_mode)
        toolbar.addWidget(self._demo_btn)

        # 重置统计按钮
        reset_reco_btn = PushButton(FIF.DELETE, _tr("重置使用统计", "Reset Usage Stats"))
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
        self._datetime_edit.setDateTime(QDateTime.fromString(
            self._initial_time.strftime("%Y-%m-%d %H:%M:%S"),
            "yyyy-MM-dd HH:mm:ss"
        ))
        time_row.addWidget(self._datetime_edit)

        apply_time_btn = PrimaryPushButton(FIF.ACCEPT, _tr("应用", "Apply"))
        apply_time_btn.clicked.connect(self._apply_custom_time)
        time_row.addWidget(apply_time_btn)

        reset_time_btn = TransparentPushButton(FIF.CANCEL, _tr("重置为当前时间", "Reset to current time"))
        reset_time_btn.clicked.connect(self._reset_time_offset)
        time_row.addWidget(reset_time_btn)

        time_row.addStretch()
        tcl.addLayout(time_row)

        # 当前偏移显示
        from app.services.settings_service import SettingsService
        current_offset = SettingsService.instance().time_offset_seconds
        self._offset_status_lbl = CaptionLabel(_tr(f"当前偏移：{current_offset} 秒", f"Current offset: {current_offset} s"))
        tcl.addWidget(self._offset_status_lbl)

        # 当前时间显示
        now_time = self._initial_time.strftime("%Y-%m-%d %H:%M:%S")
        self._current_time_lbl = CaptionLabel(_tr(f"实际当前时间：{now_time}", f"Real current time: {now_time}"))
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
            rows.append(("-", _tr("推荐原因（智能学习）", "Recommendation reasons (learning)")))
            for fid in ALL_FEATURES:
                reason = reco.get_reason(fid)
                name = FEATURE_LABELS.get(fid, fid)
                rows.append((f"  {name}", reason if reason else _tr("（暂无原因）", "(No reason yet)")))
            # 附加当前推荐排名
            rows.append(("-", _tr("综合排名", "Combined ranking")))
            ranked = reco.ranked()
            for rank, (fid, score) in enumerate(ranked, 1):
                rows.append((f"  {_tr('排名', 'Rank')} #{rank}", f"{fid}  ->  {score:.4f}"))
        except Exception as e:
            rows = [(_tr("错误", "Error"), str(e))]

        self._reco_table.set_rows(rows)
        self._reco_table.setFixedHeight(self._reco_table.ideal_height())

    def _toggle_demo_mode(self, checked: bool) -> None:
        if self._home_view is not None:
            self._home_view.set_demo_mode(checked)
            self._demo_btn.setText(
                _tr("退出 Demo 模式", "Exit Demo mode") if checked else _tr("展示所有卡片类型 (Demo)", "Show all card types (Demo)")
            )

    def _reset_reco_stats(self) -> None:
        try:
            from app.services.recommendation_service import RecommendationService
            box = MessageBox(
                _tr("重置使用统计", "Reset Usage Stats"),
                _tr("将清空所有首页推荐算法的历史记录，无法恢复。是否继续？", "This will clear all history of home recommendation algorithm and cannot be undone. Continue?"),
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
            self._offset_status_lbl.setText(_tr(f"当前偏移：{offset} 秒", f"Current offset: {offset} s"))
            # 显示实际当前时间（无偏移）
            real_now = datetime.now()
            self._current_time_lbl.setText(_tr(
                f"实际当前时间：{real_now.strftime('%Y-%m-%d %H:%M:%S')}",
                f"Real current time: {real_now.strftime('%Y-%m-%d %H:%M:%S')}"
            ))
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
            self._datetime_edit.setDateTime(QDateTime.fromString(
                now.strftime("%Y-%m-%d %H:%M:%S"),
                "yyyy-MM-dd HH:mm:ss"
            ))
            self._refresh_time_debug()
        except Exception as e:
            from app.utils.logger import logger
            logger.error("重置时间偏移失败：{}", e)


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
    ):
        super().__init__()
        self.setWindowTitle(_tr(f"{APP_NAME}  —  调试面板", f"{APP_NAME} - Debug Panel"))
        self.setWindowIcon(QIcon(ICON_PATH) if ICON_PATH else QIcon())
        self.resize(960, 720)
        self.setMinimumSize(800, 600)

        self._clock = clock_service
        self._alarm = alarm_service
        self._ntp = ntp_service
        self._plugins = plugin_manager
        self._engine = auto_engine
        self._home_view = home_view
        self._first_use_setup_window: Optional[QWidget] = None

        # 创建各页面并包装在滚动区域中
        self._overview_page = self._wrap_scroll(OverviewPage(), "overviewPage")
        self._timer_thread_page = self._wrap_scroll(TimerThreadPage(clock_service, alarm_service, ntp_service), "timerThreadPage")
        self._services_page = self._wrap_scroll(ServicesPage(ntp_service, plugin_manager), "servicesPage")
        self._log_page = self._wrap_scroll(LogPage(auto_engine), "logPage")
        self._recommendation_page = self._wrap_scroll(RecommendationPage(home_view), "recommendationPage")

        # 添加到导航
        self.addSubInterface(self._overview_page, FIF.HOME, _tr("概览", "Overview"))
        self.addSubInterface(self._timer_thread_page, FIF.SYNC, _tr("计时器与线程", "Timers & Threads"))
        self.addSubInterface(self._services_page, FIF.UPDATE, _tr("服务状态", "Service Status"))
        self.addSubInterface(self._log_page, FIF.DOCUMENT, _tr("日志", "Logs"))
        self.addSubInterface(self._recommendation_page, FIF.LAYOUT, _tr("推荐系统", "Recommendation"))

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

        self._status_lbl.setText(_tr(
            f"最后刷新：{datetime.now().strftime('%H:%M:%S')}",
            f"Last refresh: {datetime.now().strftime('%H:%M:%S')}"
        ))

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


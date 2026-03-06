"""
调试窗口

仅可通过 URL 打开（不出现在导航栏）：
    ltclock://open/debug

显示内容：
    - 运行时基础信息（PID、Python 版本、运行时长、内存）
    - 核心 QTimer 状态
    - Qt 线程（QThread）
    - Python 线程列表
    - NTP 服务状态
    - 插件加载状态
    - 自动化引擎日志（最近 50 条）
"""
from __future__ import annotations

import os
import sys
import threading
import time
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, QThread
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication, QVBoxLayout, QHBoxLayout, QWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QSizePolicy,
)
from qfluentwidgets import (
    FluentIcon as FIF, PushButton,
    CardWidget, TitleLabel, StrongBodyLabel, CaptionLabel,
    TextEdit, SmoothScrollArea, ComboBox, ToolButton,
)

from app.constants import APP_NAME, LONG_VER, ICON_PATH
from app.utils.logger import memory_log

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
# 内部只读 KV 表格
# ────────────────────────────────────────────────────────────────────────── #

class _KVTable(QTableWidget):
    """两列（字段 / 值）只读表格，高度随行数自适应。"""

    def __init__(self, parent=None):
        super().__init__(0, 2, parent)
        self.setHorizontalHeaderLabels(["字段", "值"])
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
# 调试窗口
# ────────────────────────────────────────────────────────────────────────── #

class DebugWindow(QWidget):
    """
    独立调试浮窗，仅可通过 ltclock://open/debug 唤起。
    不注册到 FluentWindow 导航栏，直接 show() 弹出。
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
        # 无父级 → 作为独立顶层窗口显示
        super().__init__(None, Qt.Window)
        self.setWindowTitle(f"{APP_NAME}  —  调试面板")
        self.setWindowIcon(QIcon(ICON_PATH) if ICON_PATH else QIcon())
        self.resize(860, 700)
        self.setMinimumSize(640, 480)

        self._clock     = clock_service
        self._alarm     = alarm_service
        self._ntp       = ntp_service
        self._plugins   = plugin_manager
        self._engine    = auto_engine
        self._home_view = home_view

        # ── ScrollArea 作为内容区 ─────────────────────────────────────── #
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = SmoothScrollArea(self)
        outer.addWidget(scroll)

        container = QWidget()
        root = QVBoxLayout(container)
        root.setContentsMargins(28, 20, 28, 24)
        root.setSpacing(16)

        # ── 标题行 ────────────────────────────────────────────────────── #
        title_row = QHBoxLayout()
        title_lbl = TitleLabel("调试面板")

        badge = CaptionLabel("⚠  仅限 URL 访问")
        badge.setStyleSheet(
            "background:#d83b01;color:white;border-radius:4px;"
            "padding:2px 10px;font-weight:600;"
        )
        ver_lbl = CaptionLabel(LONG_VER)
        ver_lbl.setStyleSheet("color: gray;")

        self._last_refresh_lbl = CaptionLabel("")
        refresh_btn = PushButton(FIF.SYNC, "立即刷新")
        refresh_btn.clicked.connect(self.refresh)

        title_row.addWidget(title_lbl)
        title_row.addSpacing(10)
        title_row.addWidget(badge)
        title_row.addSpacing(10)
        title_row.addWidget(ver_lbl)
        title_row.addStretch()
        title_row.addWidget(self._last_refresh_lbl)
        title_row.addSpacing(8)
        title_row.addWidget(refresh_btn)
        root.addLayout(title_row)

        # ── 各信息卡片 ────────────────────────────────────────────────── #
        def _section(label: str) -> tuple[CardWidget, QVBoxLayout]:
            root.addWidget(StrongBodyLabel(label))
            card = CardWidget()
            lay = QVBoxLayout(card)
            lay.setContentsMargins(16, 12, 16, 12)
            root.addWidget(card)
            return card, lay

        _, rl = _section("运行时信息")
        self._runtime_table = _KVTable()
        rl.addWidget(self._runtime_table)

        _, tl = _section("核心 QTimer / 线程")
        self._timer_table = _KVTable()
        tl.addWidget(self._timer_table)

        _, qtl = _section("Qt 线程（QThread）")
        self._qthread_table = _KVTable()
        qtl.addWidget(self._qthread_table)

        _, ptl = _section("Python 线程")
        self._pythread_table = _KVTable()
        ptl.addWidget(self._pythread_table)

        _, nl = _section("NTP 服务")
        self._ntp_table = _KVTable()
        nl.addWidget(self._ntp_table)

        _, pl = _section("已加载插件")
        self._plugin_table = _KVTable()
        pl.addWidget(self._plugin_table)

        root.addWidget(StrongBodyLabel("自动化引擎日志（最近 50 条，最新在上）"))
        log_card = CardWidget()
        ll = QVBoxLayout(log_card)
        ll.setContentsMargins(16, 12, 16, 12)
        self._log_edit = TextEdit()
        self._log_edit.setReadOnly(True)
        self._log_edit.setMinimumHeight(180)
        self._log_edit.setStyleSheet(
            "font-family:Consolas,'Courier New',monospace;font-size:12px;"
        )
        ll.addWidget(self._log_edit)
        root.addWidget(log_card)

        # ── 应用日志面板 ──────────────────────────────────────────────── #
        applog_header = QHBoxLayout()
        applog_header.addWidget(StrongBodyLabel("应用日志（内存，最新在上）"))
        applog_header.addStretch()

        # 级别筛选
        applog_header.addWidget(CaptionLabel("级别："))
        self._log_level_combo = ComboBox()
        for lvl in ("ALL", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            self._log_level_combo.addItem(lvl, lvl if lvl != "ALL" else "")
        self._log_level_combo.setFixedWidth(110)
        self._log_level_combo.currentIndexChanged.connect(self._refresh_applog)
        applog_header.addWidget(self._log_level_combo)

        # 清空按钮
        clear_btn = ToolButton(FIF.DELETE)
        clear_btn.setToolTip("清空内存日志")
        clear_btn.clicked.connect(self._clear_applog)
        applog_header.addWidget(clear_btn)

        root.addLayout(applog_header)

        applog_card = CardWidget()
        al = QVBoxLayout(applog_card)
        al.setContentsMargins(16, 12, 16, 12)
        self._applog_edit = TextEdit()
        self._applog_edit.setReadOnly(True)
        self._applog_edit.setMinimumHeight(240)
        self._applog_edit.setStyleSheet(
            "font-family:Consolas,'Courier New',monospace;font-size:12px;"
        )
        al.addWidget(self._applog_edit)
        root.addWidget(applog_card)

        # ── 首页推荐系统 ──────────────────────────────────────────────── #
        reco_header = QHBoxLayout()
        reco_header.addWidget(StrongBodyLabel("首页推荐系统 — 使用统计"))
        reco_header.addStretch()

        # Demo 模式按钮
        self._demo_btn = PushButton(FIF.LAYOUT, "展示所有卡片类型 (Demo)")
        self._demo_btn.setCheckable(True)
        self._demo_btn.setChecked(False)
        self._demo_btn.clicked.connect(self._toggle_demo_mode)
        reco_header.addWidget(self._demo_btn)

        # 重置统计按钮
        reset_reco_btn = PushButton(FIF.DELETE, "重置使用统计")
        reset_reco_btn.clicked.connect(self._reset_reco_stats)
        reco_header.addWidget(reset_reco_btn)
        root.addLayout(reco_header)

        reco_card = CardWidget()
        rcl = QVBoxLayout(reco_card)
        rcl.setContentsMargins(16, 12, 16, 12)
        self._reco_table = _KVTable()
        rcl.addWidget(self._reco_table)
        root.addWidget(reco_card)

        root.addStretch()
        scroll.setWidget(container)
        scroll.setWidgetResizable(True)
        scroll.enableTransparentBackground()

        # ── 自动刷新（每 2 秒） ───────────────────────────────────────── #
        self._auto_timer = QTimer(self)
        self._auto_timer.setInterval(2_000)
        self._auto_timer.timeout.connect(self.refresh)

        self.refresh()

    # ------------------------------------------------------------------ #
    # 窗口事件
    # ------------------------------------------------------------------ #

    def showEvent(self, event):
        super().showEvent(event)
        self._auto_timer.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._auto_timer.stop()

    # ------------------------------------------------------------------ #
    # 刷新
    # ------------------------------------------------------------------ #

    def refresh(self) -> None:
        self._refresh_runtime()
        self._refresh_timers()
        self._refresh_qthreads()
        self._refresh_pythreads()
        self._refresh_ntp()
        self._refresh_plugins()
        self._refresh_log()
        self._refresh_applog()
        self._refresh_reco()
        self._last_refresh_lbl.setText(
            f"最后刷新：{datetime.now().strftime('%H:%M:%S')}"
        )

    # ── 运行时 ────────────────────────────────────────────────────────── #

    def _refresh_runtime(self) -> None:
        rows: list[tuple[str, str]] = [
            ("PID",           str(os.getpid())),
            ("Python",        sys.version.split()[0]),
            ("平台",          sys.platform),
            ("运行时长",      _uptime_str(_START_TIME)),
            ("Python 线程数", str(threading.active_count())),
            ("当前时间",      datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        ]

        if _HAS_PSUTIL:
            try:
                mem = _PROC.memory_info()
                rows.insert(4, ("RSS 内存", _fmt_bytes(mem.rss)))
                rows.insert(5, ("VMS 内存", _fmt_bytes(mem.vms)))
                rows.insert(6, ("CPU 占用", f"{_PROC.cpu_percent(interval=None):.1f}%"))
            except Exception:
                pass

        self._runtime_table.set_rows(rows)
        self._runtime_table.setFixedHeight(self._runtime_table.ideal_height())

    # ── 核心计时器 ────────────────────────────────────────────────────── #

    def _refresh_timers(self) -> None:
        rows: list[tuple[str, str]] = []

        def _qtimer_row(name: str, svc, attr: str) -> tuple[str, str]:
            try:
                tmr: QTimer = getattr(svc, attr)
                active    = "✓ 运行中" if tmr.isActive() else "✗ 已停止"
                interval  = f"{tmr.interval()} ms"
                shot      = "单次" if tmr.isSingleShot() else "循环"
                remaining = (f"{tmr.remainingTime()} ms"
                             if tmr.isActive() else "—")
                return (name, f"{active}  |  间隔 {interval}  |  {shot}  |  剩余 {remaining}")
            except AttributeError:
                return (name, "（服务未注入）")

        if self._clock:
            rows.append(_qtimer_row("ClockService._timer      [QTimer]",
                                    self._clock, "_timer"))

        if self._alarm:
            rows.append(_qtimer_row("AlarmService._timer      [QTimer]",
                                    self._alarm, "_timer"))

        # NTP 使用 Python 原生线程，不是 QTimer
        if self._ntp:
            t = getattr(self._ntp, "_thread", None)
            if t is None:
                ntp_val = "（线程未启动）"
            else:
                alive  = "✓ 存活" if t.is_alive() else "✗ 已终止"
                daemon = "守护" if t.daemon else "普通"
                ntp_val = (f"{alive}  |  {daemon}线程  |  "
                           f"name={t.name}  |  id={t.ident}")
            rows.append(("NtpService._thread   [Python Thread]", ntp_val))

        if not rows:
            rows = [("（无）", "服务未注入到调试窗口")]

        self._timer_table.set_rows(rows)
        self._timer_table.setFixedHeight(self._timer_table.ideal_height())

    # ── Qt 线程 ───────────────────────────────────────────────────────── #

    def _refresh_qthreads(self) -> None:
        app = QApplication.instance()
        rows: list[tuple[str, str]] = []
        if app:
            for obj in app.findChildren(QThread):
                name  = obj.objectName() or obj.__class__.__name__
                alive = "✓ 运行中" if obj.isRunning() else "✗ 已停止"
                rows.append((name, f"{alive}  |  id={id(obj):#x}"))

        if not rows:
            rows = [("（无独立 QThread）", "所有逻辑均在主线程完成")]

        self._qthread_table.set_rows(rows)
        self._qthread_table.setFixedHeight(self._qthread_table.ideal_height())

    # ── Python 线程 ───────────────────────────────────────────────────── #

    def _refresh_pythreads(self) -> None:
        main_id = threading.main_thread().ident
        rows: list[tuple[str, str]] = []

        for t in sorted(threading.enumerate(), key=lambda x: x.ident or 0):
            tag    = " [主线程]" if t.ident == main_id else ""
            daemon = "守护" if t.daemon else "普通"
            alive  = "✓ 存活" if t.is_alive() else "✗ 已终止"
            rows.append((f"#{t.ident}{tag}", f"{t.name}  |  {alive}  |  {daemon}"))

        self._pythread_table.set_rows(rows)
        self._pythread_table.setFixedHeight(self._pythread_table.ideal_height())

    # ── NTP 服务 ──────────────────────────────────────────────────────── #

    def _refresh_ntp(self) -> None:
        if not self._ntp:
            self._ntp_table.set_rows([("（未注入）", "—")])
            self._ntp_table.setFixedHeight(self._ntp_table.ideal_height())
            return

        ntp = self._ntp
        rows = [
            ("已启用",   "是" if ntp.enabled else "否"),
            ("服务器",   ntp.server),
            ("同步间隔", f"{ntp.sync_interval_min} 分钟"),
            ("同步中",   "是" if ntp.is_syncing else "否"),
            ("最后同步", ntp.last_sync_time_str()),
            ("偏移量",   ntp.offset_str()),
            ("上次错误", ntp.last_error or "无"),
        ]
        self._ntp_table.set_rows(rows)
        self._ntp_table.setFixedHeight(self._ntp_table.ideal_height())

    # ── 插件 ──────────────────────────────────────────────────────────── #

    def _refresh_plugins(self) -> None:
        if not self._plugins:
            self._plugin_table.set_rows([("（未注入）", "—")])
            self._plugin_table.setFixedHeight(self._plugin_table.ideal_height())
            return

        entries = getattr(self._plugins, "_entries", {})
        if not entries:
            rows: list[tuple[str, str]] = [("（无插件）", "插件目录为空或尚未加载")]
        else:
            rows = []
            for pid, entry in entries.items():
                meta    = entry.meta
                enabled = "✓" if entry.enabled else "✗"
                err     = f"  错误：{entry.error}" if entry.error else ""
                rows.append((pid,
                             f"{enabled}  v{meta.version}  作者：{meta.author}{err}"))

        self._plugin_table.set_rows(rows)
        self._plugin_table.setFixedHeight(self._plugin_table.ideal_height())

    # ── 自动化引擎日志 ────────────────────────────────────────────────── #

    def _refresh_log(self) -> None:
        if not self._engine:
            self._log_edit.setPlainText("（自动化引擎未注入）")
            return

        log: list[str] = getattr(self._engine, "_log", [])
        lines = log[-50:]
        text  = "\n".join(reversed(lines)) if lines else "（暂无日志）"

        if self._log_edit.toPlainText() != text:
            self._log_edit.setPlainText(text)

    # ── 应用日志（loguru 内存 sink） ──────────────────────────────────── #

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

    def _refresh_applog(self) -> None:
        import html as _html
        level_filter: str = self._log_level_combo.currentData() or ""
        records = memory_log.get(level_filter)

        if not records:
            self._applog_edit.setHtml("<span style='color:gray'>（暂无日志）</span>")
            return

        lines_html: list[str] = []
        for r in reversed(records[-1000:]):   # 最多显示最新 1000 条
            color = self._LEVEL_COLOR.get(r["level"], "#333333")
            escaped = _html.escape(r["text"])
            lines_html.append(
                f"<span style='color:{color}'>{escaped}</span>"
            )

        html = "<br>".join(lines_html)
        self._applog_edit.setHtml(html)

    def _clear_applog(self) -> None:
        memory_log.clear()
        self._applog_edit.setHtml("<span style='color:gray'>（已清空）</span>")

    # ── 首页推荐系统 ──────────────────────────────────────────────────── #

    def _refresh_reco(self) -> None:
        try:
            from app.services.recommendation_service import RecommendationService
            reco = RecommendationService.instance()
            rows = reco.debug_rows()
            # 附加推荐原因
            rows.append(("—", "推荐原因（智能学习）"))
            from app.services.recommendation_service import ALL_FEATURES, FEATURE_LABELS
            for fid in ALL_FEATURES:
                reason = reco.get_reason(fid)
                name = FEATURE_LABELS.get(fid, fid)
                rows.append((f"  {name}", reason if reason else "（暂无原因）"))
            # 附加当前推荐排名
            rows.append(("—", "综合排名"))
            ranked = reco.ranked()
            for rank, (fid, score) in enumerate(ranked, 1):
                rows.append((f"  排名 #{rank}", f"{fid}  →  {score:.4f}"))
        except Exception as e:
            rows = [("错误", str(e))]

        self._reco_table.set_rows(rows)
        self._reco_table.setFixedHeight(self._reco_table.ideal_height())

    def _toggle_demo_mode(self, checked: bool) -> None:
        if self._home_view is not None:
            self._home_view.set_demo_mode(checked)
            self._demo_btn.setText(
                "退出 Demo 模式" if checked else "展示所有卡片类型 (Demo)"
            )

    def _reset_reco_stats(self) -> None:
        try:
            from app.services.recommendation_service import RecommendationService
            from qfluentwidgets import MessageBox
            box = MessageBox(
                "重置使用统计",
                "将清空所有首页推荐算法的历史记录，无法恢复。是否继续？",
                self,
            )
            if box.exec():
                RecommendationService.instance().reset()
                self._refresh_reco()
        except Exception as e:
            from app.utils.logger import logger
            logger.error("重置推荐统计失败：{}", e)


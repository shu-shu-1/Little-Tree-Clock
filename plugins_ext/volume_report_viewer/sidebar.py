"""音量报告可视化侧边栏。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    FluentIcon as FIF,
    InfoBar,
    InfoBarPosition,
    ListWidget,
    MessageBox,
    PushButton,
    SmoothScrollArea,
    StrongBodyLabel,
    SubtitleLabel,
    isDarkTheme,
)

from .service import VolumeReportRecord, VolumeReportService


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _format_seconds(value: float) -> str:
    total = int(max(0, value))
    minutes, seconds = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def _format_datetime(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return "--"
    try:
        dt = datetime.fromisoformat(text)
    except Exception:
        return text
    return dt.strftime("%m-%d %H:%M:%S")


class _WaveformPreview(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._points: list[tuple[float, float]] = []
        self._threshold = -20.0
        self.setMinimumHeight(180)
        self.setObjectName("volumeReportWaveform")

    def set_report(self, report: dict[str, Any] | None) -> None:
        raw_waveform = (report or {}).get("waveform") or []
        points: list[tuple[float, float]] = []
        for item in raw_waveform:
            if not isinstance(item, dict):
                continue
            t = _safe_float(item.get("t"), -1.0)
            db = _safe_float(item.get("db"), -80.0)
            if t < 0:
                continue
            db = max(-80.0, min(0.0, db))
            points.append((t, db))
        points.sort(key=lambda point: point[0])
        self._points = points
        self._threshold = _safe_float((report or {}).get("threshold_db"), -20.0)
        self.update()

    def paintEvent(self, event):  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        dark = isDarkTheme()
        if dark:
            bg_color = QColor(12, 14, 18)
            axis_color = QColor(255, 255, 255, 36)
            line_color = QColor(77, 175, 255)
            threshold_color = QColor(231, 76, 60, 190)
            text_color = QColor(255, 255, 255, 160)
        else:
            bg_color = QColor(248, 250, 252)
            axis_color = QColor(15, 23, 42, 46)
            line_color = QColor(59, 130, 246)
            threshold_color = QColor(220, 38, 38, 175)
            text_color = QColor(71, 85, 105, 170)

        rect = self.rect()
        painter.fillRect(rect, bg_color)

        margin = 12
        width = max(1, rect.width() - margin * 2)
        height = max(1, rect.height() - margin * 2)
        origin_x = rect.left() + margin
        origin_y = rect.top() + margin

        painter.setPen(QPen(axis_color, 1))
        painter.drawRect(origin_x, origin_y, width, height)

        if not self._points:
            painter.setPen(QPen(text_color, 1))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "暂无音量数据")
            painter.end()
            return

        duration = max(self._points[-1][0], 0.001)
        db_min = -80.0
        db_max = 0.0

        def _map_point(t: float, db: float) -> tuple[float, float]:
            x = origin_x + (t / duration) * width
            ratio = (db - db_min) / (db_max - db_min)
            y = origin_y + (1.0 - max(0.0, min(1.0, ratio))) * height
            return x, y

        path = QPainterPath()
        first_x, first_y = _map_point(*self._points[0])
        path.moveTo(first_x, first_y)
        for t, db in self._points[1:]:
            x, y = _map_point(t, db)
            path.lineTo(x, y)

        painter.setPen(QPen(line_color, 2))
        painter.drawPath(path)

        threshold_y = _map_point(0, self._threshold)[1]
        painter.setPen(QPen(threshold_color, 1, Qt.PenStyle.DashLine))
        painter.drawLine(origin_x, threshold_y, origin_x + width, threshold_y)
        painter.end()


class VolumeReportSidebarPanel(QWidget):
    def __init__(self, service: VolumeReportService, parent=None):
        super().__init__(parent)
        self.setObjectName("volumeReportSidebarPanel")
        self._service = service
        self._records: list[VolumeReportRecord] = []
        self._record_map: dict[str, VolumeReportRecord] = {}
        self._current: VolumeReportRecord | None = None

        self.setStyleSheet(
            "QWidget#volumeReportSidebarPanel {"
            "background: transparent;"
            "}"
            "QWidget#volumeReportScrollBody {"
            "background: transparent;"
            "}"
            "QFrame#volumeReportDetailCard {"
            "border: 1px solid rgba(127,127,127,52);"
            "border-radius: 12px;"
            "background: rgba(127,127,127,16);"
            "}"
            "QFrame#volumeReportStatCard {"
            "border: 1px solid rgba(127,127,127,42);"
            "border-radius: 10px;"
            "background: rgba(127,127,127,14);"
            "}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QWidget(self)
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(20, 12, 16, 12)
        header_layout.setSpacing(6)
        header_layout.addWidget(SubtitleLabel("音量报告可视化"))
        self._summary = CaptionLabel("读取音量检测报告并展示波形，支持导出图片")
        self._summary.setWordWrap(True)
        header_layout.addWidget(self._summary)
        root.addWidget(header)

        sep = QFrame(self)
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: rgba(127,127,127,56);")
        root.addWidget(sep)

        body = QWidget(self)
        body.setObjectName("volumeReportScrollBody")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(12, 12, 12, 12)
        body_layout.setSpacing(10)

        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(8)
        self._refresh_btn = PushButton(FIF.SYNC, "刷新报告")
        self._import_btn = PushButton(FIF.DOWNLOAD, "导入报告")
        self._delete_btn = PushButton(FIF.DELETE, "删除报告")
        self._delete_btn.setEnabled(False)
        self._export_btn = PushButton(FIF.SAVE, "导出图片")
        self._export_btn.setEnabled(False)
        self._count_label = CaptionLabel("0 条")
        action_row.addWidget(self._refresh_btn)
        action_row.addWidget(self._import_btn)
        action_row.addWidget(self._delete_btn)
        action_row.addWidget(self._export_btn)
        action_row.addStretch()
        action_row.addWidget(self._count_label)
        body_layout.addLayout(action_row)

        self._source_label = CaptionLabel("")
        self._source_label.setWordWrap(True)
        body_layout.addWidget(self._source_label)

        list_title = BodyLabel("报告列表")
        body_layout.addWidget(list_title)

        self._list = ListWidget(self)
        self._list.setMinimumHeight(190)
        body_layout.addWidget(self._list, 2)

        self._detail_card = QFrame(self)
        self._detail_card.setObjectName("volumeReportDetailCard")
        detail_layout = QVBoxLayout(self._detail_card)
        detail_layout.setContentsMargins(10, 10, 10, 10)
        detail_layout.setSpacing(8)

        self._title_label = StrongBodyLabel("请选择一条报告")
        detail_layout.addWidget(self._title_label)

        self._time_label = CaptionLabel("--")
        self._time_label.setWordWrap(True)
        detail_layout.addWidget(self._time_label)

        stats_grid = QGridLayout()
        stats_grid.setContentsMargins(0, 0, 0, 0)
        stats_grid.setHorizontalSpacing(8)
        stats_grid.setVerticalSpacing(8)
        self._max_value = self._add_stat_card(stats_grid, 0, 0, "最高音量")
        self._avg_value = self._add_stat_card(stats_grid, 0, 1, "平均音量")
        self._exceed_value = self._add_stat_card(stats_grid, 1, 0, "超阈值时长")
        self._ratio_value = self._add_stat_card(stats_grid, 1, 1, "超阈值占比")
        detail_layout.addLayout(stats_grid)

        self._waveform = _WaveformPreview(self._detail_card)
        detail_layout.addWidget(self._waveform)

        self._status_label = CaptionLabel("状态：--")
        self._status_label.setWordWrap(True)
        detail_layout.addWidget(self._status_label)

        self._meta_label = CaptionLabel("")
        self._meta_label.setWordWrap(True)
        detail_layout.addWidget(self._meta_label)

        self._path_label = CaptionLabel("")
        self._path_label.setWordWrap(True)
        detail_layout.addWidget(self._path_label)

        body_layout.addWidget(self._detail_card, 3)

        self._scroll = SmoothScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.enableTransparentBackground()
        body.setStyleSheet("background: transparent;")
        self._scroll.setWidget(body)
        root.addWidget(self._scroll, 1)

        self._refresh_btn.clicked.connect(self._reload_reports)
        self._import_btn.clicked.connect(self._import_report)
        self._delete_btn.clicked.connect(self._delete_current_report)
        self._export_btn.clicked.connect(self._export_current_image)
        self._list.currentItemChanged.connect(self._on_record_selected)

        self._reload_reports()

    @staticmethod
    def _add_stat_card(layout: QGridLayout, row: int, col: int, title: str) -> StrongBodyLabel:
        card = QFrame()
        card.setObjectName("volumeReportStatCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(8, 6, 8, 6)
        card_layout.setSpacing(4)

        title_label = CaptionLabel(title)
        value_label = StrongBodyLabel("--")
        card_layout.addWidget(title_label)
        card_layout.addWidget(value_label)

        layout.addWidget(card, row, col)
        return value_label

    def _reload_reports(self) -> None:
        previous = str(self._current.path) if self._current is not None else ""

        self._records = self._service.list_records()
        self._record_map = {str(record.path): record for record in self._records}

        self._list.blockSignals(True)
        self._list.clear()
        for record in self._records:
            item = QListWidgetItem(self._list_item_text(record))
            item.setData(Qt.ItemDataRole.UserRole, str(record.path))
            self._list.addItem(item)
        self._list.blockSignals(False)

        self._count_label.setText(f"{len(self._records)} 条")
        self._source_label.setText(self._build_source_text())

        if not self._records:
            self._current = None
            self._apply_empty_state("未找到音量报告。可在自习安排中开启音量报告自动保存。")
            return

        target_index = 0
        if previous:
            for index in range(self._list.count()):
                item = self._list.item(index)
                if str(item.data(Qt.ItemDataRole.UserRole) or "") == previous:
                    target_index = index
                    break

        self._list.setCurrentRow(target_index)

    def _build_source_text(self) -> str:
        existing = self._service.existing_report_dirs()
        if existing:
            joined = "；".join(str(path) for path in existing)
            return f"扫描目录：{joined}"
        return f"扫描目录：{self._service.preferred_report_dir()}（当前目录暂无报告）"

    @staticmethod
    def _list_item_text(record: VolumeReportRecord) -> str:
        started = _format_datetime(record.started_at)
        return (
            f"{record.display_title}\n"
            f"{started} · 峰值 {record.max_db:.1f} dB · 来源 {record.source_plugin}"
        )

    def _on_record_selected(self, current, _previous) -> None:
        if current is None:
            self._current = None
            self._apply_empty_state("未选择报告")
            return

        key = str(current.data(Qt.ItemDataRole.UserRole) or "")
        record = self._record_map.get(key)
        if record is None:
            self._current = None
            self._apply_empty_state("报告不存在或已被删除")
            return

        self._current = record
        self._apply_record(record)

    def _apply_empty_state(self, reason: str) -> None:
        self._title_label.setText("暂无可视化报告")
        self._time_label.setText("--")
        self._max_value.setText("--")
        self._avg_value.setText("--")
        self._exceed_value.setText("--")
        self._ratio_value.setText("--")
        self._status_label.setText(f"状态：{reason}")
        self._meta_label.setText("")
        self._path_label.setText("")
        self._waveform.set_report(None)
        self._delete_btn.setEnabled(False)
        self._export_btn.setEnabled(False)

    def _apply_record(self, record: VolumeReportRecord) -> None:
        ratio = 0.0
        if record.duration_sec > 0:
            ratio = record.exceed_duration_sec / record.duration_sec * 100.0

        self._title_label.setText(record.display_title)
        self._time_label.setText(
            f"开始：{_format_datetime(record.started_at)} · 结束：{_format_datetime(record.ended_at)}"
        )

        self._max_value.setText(f"{record.max_db:.1f} dB")
        self._avg_value.setText(f"{record.avg_db:.1f} dB")
        self._exceed_value.setText(_format_seconds(record.exceed_duration_sec))
        self._ratio_value.setText(f"{ratio:.1f}%")

        quality_text = self._quality_text(record)
        self._status_label.setText(
            f"状态：{quality_text} · 阈值 {record.threshold_db:.1f} dB · 超阈值次数 {record.exceed_count}"
        )

        device_name = record.device_name or "默认输入设备"
        self._meta_label.setText(
            f"来源插件：{record.source_plugin} · 设备：{device_name} · 会话时长：{_format_seconds(record.duration_sec)}"
        )
        self._path_label.setText(f"文件：{record.path}")

        self._waveform.set_report(record.data)
        self._delete_btn.setEnabled(True)
        self._export_btn.setEnabled(True)

    @staticmethod
    def _quality_text(record: VolumeReportRecord) -> str:
        if record.exceed_duration_sec <= 5 and record.max_db <= record.threshold_db:
            return "安静良好"
        if record.exceed_duration_sec <= 20:
            return "总体可接受"
        return "需要注意"

    def _export_current_image(self) -> None:
        if self._current is None:
            InfoBar.warning(
                "提示",
                "请先选择一条报告后再导出图片。",
                duration=2200,
                parent=self.window(),
                position=InfoBarPosition.BOTTOM,
            )
            return

        default_name = self._service.suggest_export_name(self._current)
        default_path = str((self._current.path.parent / default_name).resolve())
        target_path, _ = QFileDialog.getSaveFileName(
            self,
            "导出音量报告图片",
            default_path,
            "PNG 图片 (*.png)",
        )
        if not target_path:
            return

        if not target_path.lower().endswith(".png"):
            target_path += ".png"

        pixmap = self._detail_card.grab()
        if pixmap.isNull() or not pixmap.save(target_path, "PNG"):
            InfoBar.error(
                "导出失败",
                "图片写入失败，请检查目标路径权限。",
                duration=2600,
                parent=self.window(),
                position=InfoBarPosition.BOTTOM,
            )
            return

        InfoBar.success(
            "导出成功",
            f"图片已保存到：{target_path}",
            duration=2600,
            parent=self.window(),
            position=InfoBarPosition.BOTTOM,
        )

    def _import_report(self) -> None:
        source_path, _ = QFileDialog.getOpenFileName(
            self,
            "导入音量报告",
            "",
            "JSON 文件 (*.json)",
        )
        if not source_path:
            return

        try:
            imported_path = self._service.import_report(source_path)
        except Exception as exc:
            InfoBar.error(
                "导入失败",
                str(exc),
                duration=3000,
                parent=self.window(),
                position=InfoBarPosition.BOTTOM,
            )
            return

        self._reload_reports()
        self._select_record(imported_path)
        InfoBar.success(
            "导入成功",
            f"已导入报告：{imported_path.name}",
            duration=2400,
            parent=self.window(),
            position=InfoBarPosition.BOTTOM,
        )

    def _delete_current_report(self) -> None:
        if self._current is None:
            InfoBar.warning(
                "提示",
                "请先选择一条报告再删除。",
                duration=2200,
                parent=self.window(),
                position=InfoBarPosition.BOTTOM,
            )
            return

        report = self._current
        confirm = MessageBox(
            "确认删除",
            f"确定删除报告文件\n{report.path.name}\n删除后无法恢复。",
            self.window(),
        )
        confirm.yesButton.setText("删除")
        confirm.cancelButton.setText("取消")
        if not confirm.exec():
            return

        try:
            self._service.delete_report(report.path)
        except Exception as exc:
            InfoBar.error(
                "删除失败",
                str(exc),
                duration=3000,
                parent=self.window(),
                position=InfoBarPosition.BOTTOM,
            )
            return

        self._reload_reports()
        InfoBar.success(
            "已删除",
            f"报告 {report.path.name} 已删除。",
            duration=2200,
            parent=self.window(),
            position=InfoBarPosition.BOTTOM,
        )

    def _select_record(self, path) -> None:
        key = str(path)
        for index in range(self._list.count()):
            item = self._list.item(index)
            if str(item.data(Qt.ItemDataRole.UserRole) or "") == key:
                self._list.setCurrentRow(index)
                self._list.scrollToItem(item)
                break

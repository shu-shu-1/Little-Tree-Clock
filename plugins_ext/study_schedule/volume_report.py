from __future__ import annotations

from typing import Iterable

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QTimer, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPainterPath
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    CaptionLabel,
    PrimaryPushButton,
    StrongBodyLabel,
    SubtitleLabel,
    TitleLabel,
    isDarkTheme,
)


def _format_seconds(value: float) -> str:
    total = int(max(0, value))
    minutes, seconds = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


_MAX_WAVEFORM_POINTS = 600


def _downsample_waveform(
    data: list[tuple[float, float]], max_points: int
) -> list[tuple[float, float]]:
    if len(data) <= max_points:
        return data
    bucket_size = len(data) / max_points
    result: list[tuple[float, float]] = []
    for i in range(max_points):
        start = int(i * bucket_size)
        end = int((i + 1) * bucket_size)
        bucket = data[start:end]
        if not bucket:
            continue
        t_mid = (bucket[0][0] + bucket[-1][0]) * 0.5
        db_max = max(db for _, db in bucket)
        db_min = min(db for _, db in bucket)
        result.append((t_mid, db_max))
        if i < max_points - 1 and db_max != db_min:
            result.append((t_mid, db_min))
    return result


class VolumeWaveformWidget(QFrame):
    def __init__(self, dark_mode: bool, parent=None):
        super().__init__(parent)
        self._threshold = -20.0
        self._dark_mode = dark_mode
        self._path: QPainterPath | None = None
        self._threshold_y = 0.0
        self._origin_x = 0
        self._origin_y = 0
        self._width = 0
        self._height = 0
        self._has_data = False
        self._raw_data: list[tuple[float, float]] = []
        self.setMinimumHeight(200)
        self.setObjectName("VolumeWaveform")
        if dark_mode:
            self.setStyleSheet(
                "QFrame#VolumeWaveform{"
                "background:qlineargradient(x1:0, y1:0, x2:0, y2:1,"
                "stop:0 rgba(255,255,255,12), stop:1 rgba(255,255,255,4));"
                "border:1px solid rgba(255,255,255,28);"
                "border-radius:14px;}"
            )
        else:
            self.setStyleSheet(
                "QFrame#VolumeWaveform{"
                "background:qlineargradient(x1:0, y1:0, x2:0, y2:1,"
                "stop:0 rgba(255,255,255,245), stop:1 rgba(245,248,252,245));"
                "border:1px solid rgba(15,23,42,26);"
                "border-radius:14px;}"
            )

    def set_report(self, report: dict) -> None:
        waveform = report.get("waveform") or []
        data: list[tuple[float, float]] = []
        for item in waveform:
            try:
                t = float(item.get("t", 0))
                db = float(item.get("db", -80))
                data.append((t, db))
            except Exception:
                continue
        data.sort(key=lambda p: p[0])

        self._has_data = bool(data)
        self._raw_data = data

        if not self._has_data:
            self._path = None
            self.update()
            return

        try:
            self._threshold = float(report.get("threshold_db", -20))
        except Exception:
            self._threshold = -20.0

        sampled = _downsample_waveform(data, _MAX_WAVEFORM_POINTS)
        self._build_path(sampled)
        self.update()

    def _build_path(self, data: list[tuple[float, float]]) -> None:
        rect = self.rect()
        margin = 14
        self._width = max(1, rect.width() - margin * 2)
        self._height = max(1, rect.height() - margin * 2)
        self._origin_x = rect.left() + margin
        self._origin_y = rect.top() + margin

        duration = max(p[0] for p in data)
        duration = duration if duration > 0 else 1.0
        db_min, db_max = -80.0, 0.0

        def _map_point(t: float, db: float) -> tuple[float, float]:
            x = self._origin_x + (t / duration) * self._width
            ratio = (db - db_min) / (db_max - db_min)
            y = self._origin_y + (1 - max(0.0, min(1.0, ratio))) * self._height
            return x, y

        path = QPainterPath()
        first_x, first_y = _map_point(*data[0])
        path.moveTo(first_x, first_y)
        for t, db in data[1:]:
            x, y = _map_point(t, db)
            path.lineTo(x, y)

        self._path = path
        threshold_y = _map_point(0, self._threshold)[1]
        self._threshold_y = threshold_y

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if not self._has_data:
            return
        raw = getattr(self, "_raw_data", None)
        if raw:
            self._build_path(_downsample_waveform(raw, _MAX_WAVEFORM_POINTS))
        self.update()

    def paintEvent(self, event):  # noqa: N802
        del event
        painter = QPainter(self)
        rect = self.rect()
        if self._dark_mode:
            painter.fillRect(rect, QColor(12, 14, 18))
            axis_color = QColor(255, 255, 255, 30)
            empty_color = QColor(255, 255, 255, 120)
        else:
            painter.fillRect(rect, QColor(248, 250, 252))
            axis_color = QColor(15, 23, 42, 38)
            empty_color = QColor(71, 85, 105, 160)

        margin = 14
        width = max(1, rect.width() - margin * 2)
        height = max(1, rect.height() - margin * 2)
        origin_x = rect.left() + margin
        origin_y = rect.top() + margin

        painter.setPen(QPen(axis_color, 1))
        painter.drawRect(int(origin_x), int(origin_y), int(width), int(height))

        if not self._has_data:
            painter.setPen(QPen(empty_color, 1))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "暂无音量数据")
            painter.end()
            return

        if self._path is not None:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QPen(QColor(77, 175, 255), 2))
            painter.drawPath(self._path)

        threshold_y = (
            self._origin_y
            + (1 - max(0.0, min(1.0, (self._threshold - (-80.0)) / 80.0)))
            * self._height
        )
        painter.setPen(QPen(QColor(231, 76, 60, 180), 1, Qt.PenStyle.DashLine))
        painter.drawLine(
            int(origin_x), int(threshold_y), int(origin_x + width), int(threshold_y)
        )

        painter.end()


class VolumeReportWindow(QWidget):
    def __init__(self, report: dict, *, auto_close_sec: int = 0, parent=None):
        super().__init__(parent)
        self._report = report
        self._auto_close = max(0, int(auto_close_sec))
        self._countdown = self._auto_close
        self._timer: QTimer | None = None
        self._dark_mode = isDarkTheme()

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setObjectName("VolumeReportWindow")
        self._apply_theme_style()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(12)

        title_row = QHBoxLayout()
        title_row.setSpacing(12)
        title = TitleLabel("音量报告")
        title.setStyleSheet(f"color:{self._primary_color()};")
        subtitle = SubtitleLabel(self._build_subtitle(report))
        subtitle.setStyleSheet(f"color:{self._secondary_color()};")
        badge = CaptionLabel(self._build_state_badge(report))
        badge.setStyleSheet(self._badge_style())
        title_row.addWidget(title)
        title_row.addStretch()
        title_row.addWidget(subtitle)
        title_row.addWidget(badge)
        layout.addLayout(title_row)

        stats_row = QHBoxLayout()
        stats_row.setSpacing(12)
        for idx, widget in enumerate(self._build_stat_widgets(report)):
            stats_row.addWidget(widget, 1)
            if idx < 3:
                stats_row.addWidget(self._build_stat_divider())
        layout.addLayout(stats_row)

        wave = VolumeWaveformWidget(self._dark_mode)
        wave.set_report(report)
        layout.addWidget(wave)

        note_row = QHBoxLayout()
        note_row.setSpacing(8)
        info = CaptionLabel(self._build_footer_text(report))
        info.setWordWrap(True)
        info.setStyleSheet(f"color:{self._muted_color()};")
        note_row.addWidget(info, 1)
        layout.addLayout(note_row)

        action_row = QHBoxLayout()
        action_row.addStretch()
        self._close_btn = PrimaryPushButton(self._close_text())
        self._close_btn.clicked.connect(self.close)
        action_row.addWidget(self._close_btn)
        layout.addLayout(action_row)

        if self._auto_close > 0:
            self._timer = QTimer(self)
            self._timer.setInterval(1000)
            self._timer.timeout.connect(self._tick)
            self._timer.start()

        screen = QApplication.primaryScreen()
        if screen:
            self.setGeometry(screen.geometry())
        self.show()
        self.raise_()
        self.activateWindow()
        self._animate_in()

    def _apply_theme_style(self) -> None:
        if self._dark_mode:
            self.setStyleSheet(
                "QWidget#VolumeReportWindow{"
                "background:qlineargradient(x1:0, y1:0, x2:0, y2:1,"
                "stop:0 #0e1119, stop:1 #0a0d13);"
                "color:rgba(255,255,255,220);}"
                "QLabel{background:transparent;}"
            )
        else:
            self.setStyleSheet(
                "QWidget#VolumeReportWindow{"
                "background:qlineargradient(x1:0, y1:0, x2:0, y2:1,"
                "stop:0 #f9fbff, stop:1 #eef3f8);"
                "color:#0f172a;}"
                "QLabel{background:transparent;}"
            )

    def _primary_color(self) -> str:
        return "#ffffff" if self._dark_mode else "#0f172a"

    def _secondary_color(self) -> str:
        return "rgba(255,255,255,170)" if self._dark_mode else "rgba(15,23,42,180)"

    def _muted_color(self) -> str:
        return "rgba(255,255,255,150)" if self._dark_mode else "rgba(71,85,105,190)"

    def _badge_style(self) -> str:
        if self._dark_mode:
            return (
                "padding:4px 10px; border-radius:10px;"
                "background:rgba(77,175,255,30);"
                "color:rgba(255,255,255,210);"
                "border:1px solid rgba(77,175,255,80);"
                "font-weight:600;"
            )
        return (
            "padding:4px 10px; border-radius:10px;"
            "background:rgba(59,130,246,18);"
            "color:#1d4ed8;"
            "border:1px solid rgba(59,130,246,46);"
            "font-weight:600;"
        )

    def _build_stat_divider(self) -> QWidget:
        divider = QFrame()
        divider.setFixedWidth(1)
        divider.setStyleSheet(
            f"background:{'rgba(255,255,255,18)' if self._dark_mode else 'rgba(15,23,42,18)'};"
        )
        return divider

    def _animate_in(self) -> None:
        anim = QPropertyAnimation(self, b"windowOpacity", self)
        anim.setDuration(220)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        anim.finished.connect(anim.deleteLater)
        anim.start()

    def _close_text(self) -> str:
        if self._auto_close > 0 and self._countdown >= 0:
            return f"关闭（{self._countdown} 秒）"
        return "关闭"

    def _tick(self) -> None:
        self._countdown -= 1
        if self._countdown <= 0:
            self.close()
            return
        self._close_btn.setText(self._close_text())

    def _build_subtitle(self, report: dict) -> str:
        item = report.get("item_name") or report.get("item_id") or "当前事项"
        group = report.get("group_name") or report.get("group_id") or ""
        start = report.get("study_started_at") or report.get("started_at") or ""
        end = report.get("study_ended_at") or report.get("ended_at") or ""
        parts = [item]
        if group:
            parts.append(f"分组: {group}")
        if start and end:
            parts.append(f"{start} — {end}")
        return "  |  ".join(parts)

    def _build_state_badge(self, report: dict) -> str:
        threshold = float(report.get("threshold_db", -20))
        max_db = float(report.get("max_db", -80))
        exceed = float(report.get("exceed_duration_sec", 0))
        if exceed <= 5 and max_db <= threshold:
            return "安静良好"
        if exceed <= 20:
            return "总体可接受"
        return "需注意控制音量"

    def _build_stat_widgets(self, report: dict) -> Iterable[QWidget]:
        stats = [
            ("最高音量", f"{report.get('max_db', -80):.1f} dB"),
            ("平均音量", f"{report.get('avg_db', -80):.1f} dB"),
            ("超阈值时长", _format_seconds(report.get("exceed_duration_sec", 0))),
            ("超阈值次数", str(report.get("exceed_count", 0))),
        ]
        cards: list[QWidget] = []
        for title, value in stats:
            card = QWidget()
            layout = QVBoxLayout(card)
            layout.setContentsMargins(6, 4, 6, 4)
            layout.setSpacing(4)
            title_lbl = CaptionLabel(title)
            title_lbl.setStyleSheet(f"color:{self._muted_color()};")
            value_lbl = StrongBodyLabel(value)
            value_lbl.setStyleSheet(f"color:{self._primary_color()}; font-size:18px;")
            layout.addWidget(title_lbl)
            layout.addWidget(value_lbl)
            layout.addStretch()
            cards.append(card)
        return cards

    def _build_footer_text(self, report: dict) -> str:
        threshold = report.get("threshold_db", "")
        device = report.get("device_name") or "默认输入设备"
        saved_path = report.get("saved_path")
        lines = [f"设备：{device}"]
        if threshold != "":
            lines.append(f"阈值：{threshold} dB")
        if saved_path:
            lines.append(f"已保存：{saved_path}")
        else:
            lines.append("可在设置中开启自动保存。")
        return "  ·  ".join(lines)

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.close()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):  # noqa: N802
        if self._timer is not None:
            self._timer.stop()
        super().closeEvent(event)

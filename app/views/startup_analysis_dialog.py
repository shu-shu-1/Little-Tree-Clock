"""启动分析报告对话框 — 显示各阶段耗时、瓶颈分析、系统信息，支持导出。"""
from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QTextEdit, QPushButton, QFileDialog,
)
from qfluentwidgets import (
    SubtitleLabel, BodyLabel, CaptionLabel,
    PrimaryPushButton, PushButton, FluentIcon as FIF,
    isDarkTheme, qconfig, CardWidget, StrongBodyLabel,
)

from app.services.i18n_service import I18nService, LANG_EN_US


def _tr(zh: str, en: str) -> str:
    i18n = I18nService.instance()
    return en if i18n.language == LANG_EN_US else zh


def _apply_dialog_style(dialog: QDialog) -> None:
    dark = isDarkTheme()
    bg = "#1e1e1e" if dark else "#f7f7f7"
    text = "#e0e0e0" if dark else "#1a1a1a"
    dialog.setStyleSheet(
        f"QDialog{{background:{bg};color:{text};border-radius:12px;}}"
    )


class StartupAnalysisDialog(QDialog):
    def __init__(self, export_text: str, analysis: dict, system_info: dict, parent=None):
        super().__init__(
            parent,
            Qt.WindowType.Window
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowMinMaxButtonsHint,
        )
        self._export_text = export_text
        self._analysis = analysis

        self.setWindowTitle(_tr("启动分析报告", "Startup Analysis Report"))
        self.setMinimumSize(720, 640)
        self.resize(800, 780)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 20)
        root.setSpacing(12)

        header_row = QHBoxLayout()
        header_row.setSpacing(10)
        title_lbl = SubtitleLabel(_tr("启动分析报告", "Startup Analysis Report"))
        header_row.addWidget(title_lbl, 1)

        self._export_btn = PrimaryPushButton(FIF.SAVE, _tr("导出报告", "Export Report"))
        self._export_btn.setFixedHeight(36)
        self._export_btn.clicked.connect(self._on_export)
        header_row.addWidget(self._export_btn)

        self._copy_btn = PushButton(FIF.COPY, _tr("复制到剪贴板", "Copy to Clipboard"))
        self._copy_btn.setFixedHeight(36)
        self._copy_btn.clicked.connect(self._on_copy)
        header_row.addWidget(self._copy_btn)

        root.addLayout(header_row)

        total_ms = analysis.get("total_ms", 0)
        summary_text = _tr(
            f"启动总耗时: {total_ms:.0f}ms",
            f"Total startup time: {total_ms:.0f}ms",
        )
        summary_lbl = StrongBodyLabel(summary_text)
        root.addWidget(summary_lbl)

        phase_card = CardWidget(self)
        phase_card.setObjectName("phaseCard")
        phase_layout = QVBoxLayout(phase_card)
        phase_layout.setContentsMargins(16, 12, 16, 12)
        phase_layout.setSpacing(6)

        phase_layout.addWidget(StrongBodyLabel(_tr("各阶段用时", "Phase Timings")))

        phases = analysis.get("phases", [])
        total = sum(elapsed for _, _, elapsed in phases) if phases else 1
        for key, label, elapsed in phases:
            pct = (elapsed / total * 100) if total > 0 else 0
            bar_width = max(4, int(pct / 100 * 280))

            dark = isDarkTheme()
            bar_bg = "rgba(255,255,255,0.08)" if dark else "rgba(0,0,0,0.06)"
            bar_fg = "#4cc2ff"

            row = QHBoxLayout()
            row.setSpacing(8)
            name_lbl = CaptionLabel(f"{label}")
            name_lbl.setFixedWidth(140)
            name_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            bar_container = QLabel()
            bar_container.setFixedHeight(16)
            bar_container.setFixedWidth(280)
            bar_container.setStyleSheet(
                f"background:{bar_bg};border-radius:4px;"
            )

            bar_inner = QLabel(bar_container)
            bar_inner.setFixedHeight(16)
            bar_inner.setFixedWidth(bar_width)
            bar_inner.setStyleSheet(
                f"background:{bar_fg};border-radius:4px;"
            )

            time_lbl = CaptionLabel(f"{elapsed * 1000:.0f}ms ({pct:.1f}%)")
            time_lbl.setFixedWidth(110)

            row.addWidget(name_lbl)
            row.addWidget(bar_container)
            row.addWidget(time_lbl)
            row.addStretch()
            phase_layout.addLayout(row)

        root.addWidget(phase_card)

        bottleneck_card = CardWidget(self)
        bottleneck_card.setObjectName("bottleneckCard")
        bottleneck_layout = QVBoxLayout(bottleneck_card)
        bottleneck_layout.setContentsMargins(16, 12, 16, 12)
        bottleneck_layout.setSpacing(6)

        bottleneck_layout.addWidget(StrongBodyLabel(_tr("瓶颈分析", "Bottleneck Analysis")))

        bn_label = analysis.get("bottleneck_label", "")
        bn_ms = analysis.get("bottleneck_ms", 0)
        bn_pct = analysis.get("bottleneck_pct", 0)
        if bn_label:
            bottleneck_text = _tr(
                f"最慢阶段: {bn_label}（{bn_ms:.0f}ms，占 {bn_pct:.1f}%）",
                f"Slowest phase: {bn_label} ({bn_ms:.0f}ms, {bn_pct:.1f}%)",
            )
            bottleneck_layout.addWidget(BodyLabel(bottleneck_text))

        hw_analysis = analysis.get("hardware_analysis", "")
        if hw_analysis:
            hw_lbl = BodyLabel(hw_analysis)
            hw_lbl.setWordWrap(True)
            bottleneck_layout.addWidget(hw_lbl)

        root.addWidget(bottleneck_card)

        sysinfo_card = CardWidget(self)
        sysinfo_card.setObjectName("sysinfoCard")
        sysinfo_layout = QVBoxLayout(sysinfo_card)
        sysinfo_layout.setContentsMargins(16, 12, 16, 12)
        sysinfo_layout.setSpacing(6)

        sysinfo_header = QHBoxLayout()
        sysinfo_header.addWidget(StrongBodyLabel(_tr("系统信息", "System Information")), 1)

        self._toggle_sysinfo_btn = PushButton(_tr("展开", "Expand"))
        self._toggle_sysinfo_btn.setFixedHeight(28)
        self._toggle_sysinfo_btn.clicked.connect(self._toggle_sysinfo)
        sysinfo_header.addWidget(self._toggle_sysinfo_btn)
        sysinfo_layout.addLayout(sysinfo_header)

        key_fields = [
            ("os", _tr("操作系统", "OS")),
            ("os_release", _tr("版本", "Version")),
            ("cpu_model", _tr("处理器型号", "CPU Model")),
            ("cpu_count_logical", _tr("逻辑核心数", "Logical Cores")),
            ("cpu_count_physical", _tr("物理核心数", "Physical Cores")),
            ("cpu_freq", _tr("CPU 频率", "CPU Frequency")),
            ("memory_total_gb", _tr("内存", "Memory")),
            ("memory_detail", _tr("内存详情", "Memory Detail")),
            ("python_version", "Python"),
            ("app_version", _tr("应用版本", "App Version")),
            ("pyside6_version", "PySide6"),
            ("qt_version", "Qt"),
            ("frozen", _tr("打包模式", "Packaged")),
            ("system_locale", _tr("系统语言", "Locale")),
            ("uptime", _tr("系统运行时间", "System Uptime")),
        ]

        for key, display_name in key_fields:
            value = system_info.get(key, "")
            if value is None or value == "" or value == "N/A":
                continue
            if isinstance(value, bool):
                value = _tr("是", "Yes") if value else _tr("否", "No")
            row = QHBoxLayout()
            row.setSpacing(8)
            k_lbl = CaptionLabel(f"{display_name}:")
            k_lbl.setFixedWidth(100)
            v_lbl = CaptionLabel(str(value))
            v_lbl.setWordWrap(True)
            row.addWidget(k_lbl)
            row.addWidget(v_lbl, 1)
            sysinfo_layout.addLayout(row)

        gpu_info = system_info.get("gpu")
        if gpu_info:
            sysinfo_layout.addSpacing(4)
            gpu_title = CaptionLabel("GPU:")
            gpu_title.setStyleSheet("font-weight:600;")
            sysinfo_layout.addWidget(gpu_title)
            if isinstance(gpu_info, list):
                for idx, gpu in enumerate(gpu_info):
                    name = gpu.get("name", f"GPU {idx + 1}")
                    vram = gpu.get("vram", "")
                    driver = gpu.get("driver_version", "")
                    mode = gpu.get("current_mode", "")
                    status = gpu.get("status", "")
                    refresh = gpu.get("refresh_rate", "")
                    proc = gpu.get("video_processor", "")
                    parts = [name]
                    if vram and vram != "N/A":
                        parts.append(f"VRAM: {vram}")
                    if driver:
                        parts.append(_tr("驱动", "Driver") + f": {driver}")
                    if mode:
                        parts.append(_tr("输出模式", "Mode") + f": {mode}")
                    if refresh and refresh != "N/A":
                        parts.append(refresh)
                    if status:
                        parts.append(_tr("状态", "Status") + f": {status}")
                    if proc:
                        parts.append(f"GPU: {proc}")
                    gpu_text = "  |  ".join(parts)
                    row = QHBoxLayout()
                    row.setSpacing(8)
                    idx_lbl = CaptionLabel(f"  GPU {idx + 1}:")
                    idx_lbl.setFixedWidth(100)
                    v_lbl = CaptionLabel(gpu_text)
                    v_lbl.setWordWrap(True)
                    row.addWidget(idx_lbl)
                    row.addWidget(v_lbl, 1)
                    sysinfo_layout.addLayout(row)
            else:
                row = QHBoxLayout()
                row.setSpacing(8)
                k_lbl = CaptionLabel("  GPU:")
                k_lbl.setFixedWidth(100)
                v_lbl = CaptionLabel(str(gpu_info))
                v_lbl.setWordWrap(True)
                row.addWidget(k_lbl)
                row.addWidget(v_lbl, 1)
                sysinfo_layout.addLayout(row)

        displays = system_info.get("displays")
        if displays:
            sysinfo_layout.addSpacing(4)
            disp_title = CaptionLabel(_tr("显示器:", "Displays:"))
            disp_title.setStyleSheet("font-weight:600;")
            sysinfo_layout.addWidget(disp_title)
            for disp in displays:
                name = disp.get("name", "")
                res = disp.get("resolution", "")
                logical_res = disp.get("logical_resolution", "")
                scale = disp.get("scale_factor", "")
                refresh = disp.get("refresh_rate", "")
                phys = disp.get("physical_size", "")
                dpi = disp.get("dpi", "")
                manufacturer = disp.get("manufacturer", "")
                model = disp.get("model", "")
                primary = disp.get("primary", False)

                parts: list[str] = []
                if res:
                    parts.append(res)
                if logical_res and logical_res != res:
                    parts.append(f"({logical_res}@{scale})")
                elif scale:
                    parts.append(f"缩放: {scale}")
                if refresh:
                    parts.append(refresh)
                if phys:
                    parts.append(phys)
                if dpi:
                    parts.append(f"DPI: {dpi}")
                if manufacturer:
                    parts.append(manufacturer)
                if model:
                    parts.append(model)
                if primary:
                    parts.append(_tr("(主显示器)", "(Primary)"))

                display_label = name if name else _tr("显示器", "Display")
                display_text = "  |  ".join(parts)
                row = QHBoxLayout()
                row.setSpacing(8)
                k_lbl = CaptionLabel(f"  {display_label}:")
                k_lbl.setFixedWidth(100)
                v_lbl = CaptionLabel(display_text)
                v_lbl.setWordWrap(True)
                row.addWidget(k_lbl)
                row.addWidget(v_lbl, 1)
                sysinfo_layout.addLayout(row)

        disks = system_info.get("disks")
        if disks:
            sysinfo_layout.addSpacing(4)
            disk_title = CaptionLabel(_tr("磁盘:", "Disks:"))
            disk_title.setStyleSheet("font-weight:600;")
            sysinfo_layout.addWidget(disk_title)
            for disk in disks:
                device = disk.get("device", "")
                total = disk.get("total_gb", "")
                used = disk.get("used_pct", "")
                fstype = disk.get("fstype", "")
                mount = disk.get("mountpoint", "")
                parts = [device]
                if total:
                    parts.append(f"{total}GB")
                if used:
                    parts.append(f"{used}")
                if fstype:
                    parts.append(fstype)
                if mount:
                    parts.append(mount)
                disk_text = "  |  ".join(parts)
                row = QHBoxLayout()
                row.setSpacing(8)
                k_lbl = CaptionLabel(f"  {device}:")
                k_lbl.setFixedWidth(100)
                v_lbl = CaptionLabel(disk_text)
                v_lbl.setWordWrap(True)
                row.addWidget(k_lbl)
                row.addWidget(v_lbl, 1)
                sysinfo_layout.addLayout(row)

        self._sysinfo_detail = QTextEdit()
        self._sysinfo_detail.setReadOnly(True)
        self._sysinfo_detail.setMaximumHeight(200)
        self._sysinfo_detail.setVisible(False)
        dark = isDarkTheme()
        detail_bg = "#2a2a2a" if dark else "#ffffff"
        detail_fg = "#d0d0d0" if dark else "#333333"
        detail_border = "#444" if dark else "#ddd"
        self._sysinfo_detail.setStyleSheet(
            f"QTextEdit{{background:{detail_bg};color:{detail_fg};border:1px solid {detail_border};"
            f"border-radius:6px;padding:8px;font-family:'Consolas','Microsoft YaHei UI',monospace;"
            f"font-size:12px;}}"
        )
        self._sysinfo_detail.setPlainText(json.dumps(system_info, ensure_ascii=False, indent=2))
        sysinfo_layout.addWidget(self._sysinfo_detail)

        root.addWidget(sysinfo_card)
        root.addStretch()

        _apply_dialog_style(self)
        qconfig.themeChangedFinished.connect(lambda: _apply_dialog_style(self))

        self._center_on_screen()

    def _toggle_sysinfo(self) -> None:
        visible = not self._sysinfo_detail.isVisible()
        self._sysinfo_detail.setVisible(visible)
        self._toggle_sysinfo_btn.setText(_tr("收起", "Collapse") if visible else _tr("展开", "Expand"))

    def _on_export(self) -> None:
        default_name = _tr("启动分析报告", "startup_analysis_report")
        path, _ = QFileDialog.getSaveFileName(
            self,
            _tr("导出启动分析报告", "Export Startup Analysis Report"),
            f"{default_name}.txt",
            "Text Files (*.txt);;All Files (*)",
        )
        if path:
            try:
                from pathlib import Path
                Path(path).write_text(self._export_text, encoding="utf-8")
            except Exception as exc:
                from qfluentwidgets import InfoBar, InfoBarPosition
                InfoBar.error(
                    _tr("导出失败", "Export Failed"),
                    str(exc),
                    duration=3000,
                    position=InfoBarPosition.TOP,
                    parent=self,
                )

    def _on_copy(self) -> None:
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(self._export_text)
            from qfluentwidgets import InfoBar, InfoBarPosition
            InfoBar.success(
                _tr("已复制", "Copied"),
                _tr("启动分析报告已复制到剪贴板", "Startup analysis report copied to clipboard"),
                duration=2000,
                position=InfoBarPosition.TOP,
                parent=self,
            )

    def _center_on_screen(self) -> None:
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            self.move(
                geo.center().x() - self.width() // 2,
                geo.center().y() - self.height() // 2,
            )

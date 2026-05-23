r"""启动分析服务：追踪各阶段启动耗时，智能分析瓶颈，收集系统信息。"""
from __future__ import annotations

import platform
import sys
import time
from pathlib import Path
from typing import Optional

from app.utils.logger import logger


class StartupAnalysisService:
    _instance: "StartupAnalysisService | None" = None

    @classmethod
    def instance(cls) -> "StartupAnalysisService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._phases: list[tuple[str, str, float, float]] = []
        self._phase_labels: dict[str, str] = {}
        self._start_time: float = 0.0
        self._phase_start: float = 0.0
        self._current_phase: str = ""

    def begin(self) -> None:
        self._start_time = time.perf_counter()
        self._phases.clear()
        self._phase_labels.clear()
        logger.debug("[启动分析] 开始追踪")

    def begin_phase(self, key: str, label: str) -> None:
        self._current_phase = key
        self._phase_start = time.perf_counter()
        self._phase_labels[key] = label
        logger.debug("[启动分析] 阶段开始: {} ({})", label, key)

    def end_phase(self, key: str) -> None:
        now = time.perf_counter()
        elapsed = now - self._phase_start
        label = self._phase_labels.get(key, key)
        for i, (k, _l, s, e) in enumerate(self._phases):
            if k == key and e < 0:
                self._phases[i] = (k, label, s, elapsed)
                break
        else:
            self._phases.append((key, label, self._phase_start - self._start_time, elapsed))
        logger.debug("[启动分析] 阶段结束: {} 耗时 {:.0f}ms", key, elapsed * 1000)

    def finish(self) -> None:
        self._total_elapsed = time.perf_counter() - self._start_time
        logger.debug("[启动分析] 总耗时 {:.0f}ms", self._total_elapsed * 1000)

    @property
    def phases(self) -> list[tuple[str, str, float]]:
        return [(k, label, elapsed) for k, label, _s, elapsed in self._phases]

    @property
    def total_elapsed(self) -> float:
        return getattr(self, "_total_elapsed", 0.0)

    def analyze_bottleneck(self) -> dict:
        phases = self.phases
        if not phases:
            return {"bottleneck_phase": None, "bottleneck_label": None, "analysis": [], "hardware_analysis": ""}

        total = sum(elapsed for _, _, elapsed in phases)
        sorted_phases = sorted(phases, key=lambda x: x[2], reverse=True)
        bottleneck = sorted_phases[0] if sorted_phases else None
        bottleneck_pct = (bottleneck[2] / total * 100) if total > 0 and bottleneck else 0

        analysis_items: list[str] = []
        for key, label, elapsed in sorted_phases[:3]:
            pct = (elapsed / total * 100) if total > 0 else 0
            analysis_items.append(f"{label}: {elapsed * 1000:.0f}ms ({pct:.1f}%)")

        hw_analysis = self._analyze_hardware_bottleneck(phases, total)

        return {
            "bottleneck_phase": bottleneck[0] if bottleneck else None,
            "bottleneck_label": bottleneck[1] if bottleneck else None,
            "bottleneck_ms": bottleneck[2] * 1000 if bottleneck else 0,
            "bottleneck_pct": bottleneck_pct,
            "analysis": analysis_items,
            "hardware_analysis": hw_analysis,
            "total_ms": total * 1000,
        }

    def _analyze_hardware_bottleneck(self, phases: list[tuple[str, str, float]], total: float) -> str:
        phase_map = {k: elapsed for k, _, elapsed in phases}

        io_phases = ["settings", "services"]
        io_total = sum(phase_map.get(k, 0) for k in io_phases)

        cpu_phases = ["views", "window"]
        cpu_total = sum(phase_map.get(k, 0) for k in cpu_phases)

        plugin_total = phase_map.get("plugins", 0)

        hints: list[str] = []

        if io_total > 0.3:
            hints.append("磁盘 I/O 可能较慢（配置加载耗时 {:.0f}ms），建议检查磁盘健康状况或将程序移至 SSD。".format(io_total * 1000))

        if cpu_total > 0.8:
            hints.append("界面构建耗时较长（{:.0f}ms），可能与 CPU 性能有关。".format(cpu_total * 1000))

        if plugin_total > 1.0:
            hints.append("插件加载耗时 {:.0f}ms，部分插件可能拖慢启动速度，可在安全模式下对比测试。".format(plugin_total * 1000))

        if total < 1.0:
            hints.append("启动速度正常，未检测到明显硬件瓶颈。")

        if not hints:
            if total < 2.0:
                hints.append("整体启动速度良好。")
            elif total < 5.0:
                hints.append("启动速度一般，可尝试减少启用的插件数量。")
            else:
                hints.append("启动较慢，建议在安全模式下排查，并检查磁盘和 CPU 性能。")

        return "\n".join(hints)

    @staticmethod
    def collect_system_info() -> dict:
        info: dict = {}
        info["os"] = platform.system()
        info["os_version"] = platform.version()
        info["os_release"] = platform.release()
        info["os_build"] = _get_os_build()
        info["architecture"] = platform.machine()
        info["processor"] = platform.processor()
        info["hostname"] = platform.node()
        info["python_version"] = sys.version
        info["python_path"] = sys.executable

        try:
            info["cpu_count_logical"] = _get_cpu_count()
            info["cpu_count_physical"] = _get_cpu_physical_count()
            info["cpu_freq"] = _get_cpu_freq()
            info["cpu_model"] = _get_cpu_model()
        except Exception:
            pass

        try:
            info["memory_total_gb"] = _get_memory_info()
            info["memory_detail"] = _get_memory_detail()
        except Exception:
            pass

        try:
            disks = _get_disk_info()
            if disks:
                info["disks"] = disks
        except Exception:
            pass

        try:
            gpu_list = _get_gpu_info_full()
            if gpu_list:
                info["gpu"] = gpu_list
            else:
                info["gpu"] = _get_gpu_info()
        except Exception:
            info["gpu"] = _get_gpu_info()

        try:
            displays = _get_display_info()
            if displays:
                info["displays"] = displays
        except Exception:
            pass

        try:
            info["qt_platform"] = _get_qt_platform_info()
        except Exception:
            pass

        try:
            info["system_locale"] = _get_system_locale()
        except Exception:
            pass

        try:
            info["uptime"] = _get_system_uptime()
        except Exception:
            pass

        try:
            from app.constants import APP_VERSION, LONG_VER, IS_BETA, VERSION_TYPE
            info["app_version"] = APP_VERSION
            info["app_long_version"] = LONG_VER
            info["app_is_beta"] = IS_BETA
            info["app_version_type"] = VERSION_TYPE
        except Exception:
            pass

        try:
            import PySide6
            info["pyside6_version"] = PySide6.__version__
            info["qt_version"] = PySide6.QtCore.__version__ if hasattr(PySide6, "QtCore") else "N/A"
        except Exception:
            pass

        try:
            from app.constants import CONFIG_DIR, TEMP_DIR, PLUGINS_DIR
            info["config_dir"] = CONFIG_DIR
            info["temp_dir"] = TEMP_DIR
            info["plugins_dir"] = PLUGINS_DIR
        except Exception:
            pass

        info["frozen"] = getattr(sys, "frozen", False)
        if info["frozen"]:
            try:
                info["executable_path"] = sys.executable
            except Exception:
                pass

        return info

    def generate_export_text(self) -> str:
        import json
        lines: list[str] = []
        lines.append("=" * 60)
        lines.append("小树时钟 — 启动分析报告")
        lines.append("=" * 60)
        lines.append("")

        lines.append(f"总耗时: {self.total_elapsed * 1000:.0f}ms")
        lines.append("")
        lines.append("─" * 40)
        lines.append("各阶段用时:")
        lines.append("─" * 40)
        for key, label, elapsed in self.phases:
            lines.append(f"  {label}: {elapsed * 1000:.0f}ms")
        lines.append("")

        analysis = self.analyze_bottleneck()
        lines.append("─" * 40)
        lines.append("瓶颈分析:")
        lines.append("─" * 40)
        if analysis["bottleneck_label"]:
            lines.append(f"  最慢阶段: {analysis['bottleneck_label']} ({analysis['bottleneck_ms']:.0f}ms, {analysis['bottleneck_pct']:.1f}%)")
        lines.append("")
        if analysis["hardware_analysis"]:
            lines.append("硬件分析:")
            for line in analysis["hardware_analysis"].split("\n"):
                lines.append(f"  {line}")
        lines.append("")

        lines.append("─" * 40)
        lines.append("系统信息:")
        lines.append("─" * 40)
        sys_info = self.collect_system_info()
        lines.append(json.dumps(sys_info, ensure_ascii=False, indent=2))

        return "\n".join(lines)


def _get_cpu_count() -> int:
    import os
    return os.cpu_count() or 0


def _get_cpu_physical_count() -> int:
    try:
        import psutil
        return psutil.cpu_count(logical=False) or 0
    except Exception:
        pass
    if platform.system() == "Windows":
        try:
            import subprocess
            result = subprocess.run(
                ["wmic", "cpu", "get", "NumberOfCores"],
                capture_output=True, text=True, timeout=5,
            )
            lines = [l.strip() for l in result.stdout.strip().split("\n") if l.strip()]
            if len(lines) >= 2:
                return sum(int(x.strip()) for x in lines[1:] if x.strip().isdigit())
        except Exception:
            pass
    return 0


def _get_cpu_model() -> str:
    if platform.system() == "Windows":
        try:
            import subprocess
            result = subprocess.run(
                ["wmic", "cpu", "get", "Name"],
                capture_output=True, text=True, timeout=5,
            )
            lines = [l.strip() for l in result.stdout.strip().split("\n") if l.strip()]
            if len(lines) >= 2:
                return lines[1]
        except Exception:
            pass
    return platform.processor()


def _get_cpu_freq() -> str:
    try:
        import psutil
        freq = psutil.cpu_freq()
        if freq:
            return f"{freq.current:.0f}MHz (max: {freq.max:.0f}MHz)"
    except Exception:
        pass
    try:
        if platform.system() == "Windows":
            import subprocess
            result = subprocess.run(
                ["wmic", "cpu", "get", "MaxClockSpeed"],
                capture_output=True, text=True, timeout=5,
            )
            lines = [l.strip() for l in result.stdout.strip().split("\n") if l.strip()]
            if len(lines) >= 2:
                return f"{lines[1]}MHz"
    except Exception:
        pass
    return "N/A"


def _get_memory_info() -> str:
    try:
        import psutil
        mem = psutil.virtual_memory()
        return f"{mem.total / (1024**3):.1f}GB (可用: {mem.available / (1024**3):.1f}GB)"
    except Exception:
        pass
    try:
        if platform.system() == "Windows":
            import subprocess
            result = subprocess.run(
                ["wmic", "OS", "get", "TotalVisibleMemorySize,FreePhysicalMemory"],
                capture_output=True, text=True, timeout=5,
            )
            lines = [l.strip() for l in result.stdout.strip().split("\n") if l.strip()]
            if len(lines) >= 2:
                parts = lines[1].split()
                if len(parts) >= 2:
                    total_gb = int(parts[0]) / (1024**2)
                    free_gb = int(parts[1]) / (1024**2)
                    return f"{total_gb:.1f}GB (可用: {free_gb:.1f}GB)"
    except Exception:
        pass
    return "N/A"


def _get_memory_detail() -> str:
    try:
        import psutil
        mem = psutil.virtual_memory()
        return (
            f"总计 {mem.total / (1024**3):.1f}GB, "
            f"已用 {mem.used / (1024**3):.1f}GB ({mem.percent}%), "
            f"可用 {mem.available / (1024**3):.1f}GB"
        )
    except Exception:
        return ""


def _get_disk_info() -> list[dict]:
    disks: list[dict] = []
    try:
        import psutil
        for part in psutil.disk_partitions():
            try:
                usage = psutil.disk_usage(part.mountpoint)
                disks.append({
                    "device": part.device,
                    "mountpoint": part.mountpoint,
                    "fstype": part.fstype,
                    "total_gb": f"{usage.total / (1024**3):.1f}",
                    "used_pct": f"{usage.percent}%",
                })
            except Exception:
                disks.append({"device": part.device, "mountpoint": part.mountpoint, "fstype": part.fstype})
    except Exception:
        pass
    return disks


def _get_gpu_info() -> str:
    try:
        if platform.system() == "Windows":
            import subprocess
            result = subprocess.run(
                ["wmic", "path", "win32_VideoController", "get", "Name"],
                capture_output=True, text=True, timeout=5,
            )
            lines = [l.strip() for l in result.stdout.strip().split("\n") if l.strip()]
            if len(lines) >= 2:
                return lines[1]
    except Exception:
        pass
    return "N/A"


def _get_gpu_info_full() -> list[dict]:
    gpus: list[dict] = []
    if platform.system() != "Windows":
        return gpus
    try:
        import subprocess
        props = ["Name", "AdapterRAM", "DriverVersion", "DriverDate", "VideoModeDescription",
                 "VideoProcessor", "Availability", "CurrentRefreshRate"]
        result = subprocess.run(
            ["wmic", "path", "win32_VideoController", "get"] + [",".join(props)],
            capture_output=True, text=True, timeout=8,
        )
        lines = [l.strip() for l in result.stdout.strip().split("\n") if l.strip()]
        if len(lines) < 2:
            return gpus
        header_parts = lines[0].split(",")
        col_count = len(header_parts)
        for line in lines[1:]:
            parts = line.split(",")
            while len(parts) < col_count:
                parts.append("")
            gpu: dict = {}
            for i, col in enumerate(header_parts):
                col = col.strip()
                val = parts[i].strip() if i < len(parts) else ""
                if col == "Name":
                    gpu["name"] = val
                elif col == "AdapterRAM":
                    try:
                        vram_bytes = int(val)
                        gpu["vram"] = f"{vram_bytes / (1024**3):.0f}GB"
                    except (ValueError, TypeError):
                        gpu["vram"] = val if val else "N/A"
                elif col == "DriverVersion":
                    gpu["driver_version"] = val
                elif col == "DriverDate":
                    gpu["driver_date"] = val
                elif col == "VideoModeDescription":
                    gpu["current_mode"] = val
                elif col == "VideoProcessor":
                    gpu["video_processor"] = val
                elif col == "Availability":
                    _avail_map = {
                        "1": "其他", "2": "未知", "3": "运行中/完全性能",
                        "4": "警告", "5": "测试中", "6": "不适用",
                        "7": "关闭", "8": "离线", "9": "降级",
                        "10": "未安装", "11": "安装错误",
                        "12": "节能", "13": "待机", "14": "忙",
                    }
                    gpu["status"] = _avail_map.get(val, val)
                elif col == "CurrentRefreshRate":
                    gpu["refresh_rate"] = f"{val}Hz" if val else "N/A"
            if gpu.get("name"):
                gpus.append(gpu)
    except Exception:
        pass
    return gpus


def _get_display_info() -> list[dict]:
    displays: list[dict] = []
    try:
        from PySide6.QtGui import QGuiApplication, QScreen
        app = QGuiApplication.instance()
        if app is None:
            return displays
        for idx, screen in enumerate(app.screens()):
            geo = screen.geometry()
            avail = screen.availableGeometry()
            phys_size = screen.physicalSize()
            dpr = screen.devicePixelRatio()
            logical_dpi = screen.logicalDotsPerInch()
            physical_dpi = screen.physicalDotsPerInch()
            refresh = screen.refreshRate()

            real_w = int(geo.width() * dpr)
            real_h = int(geo.height() * dpr)

            inch_w = phys_size.width() / 25.4 if phys_size.width() > 0 else 0
            inch_h = phys_size.height() / 25.4 if phys_size.height() > 0 else 0
            diag_inch = (inch_w**2 + inch_h**2) ** 0.5 if inch_w > 0 and inch_h > 0 else 0

            display: dict = {
                "name": screen.name() or f"显示器 {idx + 1}",
                "resolution": f"{real_w} x {real_h}",
                "logical_resolution": f"{geo.width()} x {geo.height()}",
                "scale_factor": f"{dpr:.1f}x",
                "refresh_rate": f"{refresh:.0f}Hz",
                "position": f"({geo.x()}, {geo.y()})",
                "available_area": f"{avail.width()} x {avail.height()}",
            }

            if diag_inch > 0:
                display["physical_size"] = f"{diag_inch:.1f}\" ({phys_size.width():.0f}mm x {phys_size.height():.0f}mm)"

            if logical_dpi > 0:
                display["dpi"] = f"{logical_dpi:.0f} (逻辑) / {physical_dpi:.0f} (物理)"

            if screen.manufacturer():
                display["manufacturer"] = screen.manufacturer()
            if screen.model():
                display["model"] = screen.model()
            if screen.serialNumber():
                display["serial"] = screen.serialNumber()

            is_primary = (geo.topLeft() == app.primaryScreen().geometry().topLeft()) if app.primaryScreen() else False
            display["primary"] = is_primary

            displays.append(display)
    except Exception:
        pass
    return displays


def _get_os_build() -> str:
    if platform.system() == "Windows":
        try:
            import subprocess
            result = subprocess.run(
                ["ver"], capture_output=True, text=True, timeout=5, shell=True,
            )
            return result.stdout.strip()
        except Exception:
            pass
    return ""


def _get_qt_platform_info() -> str:
    try:
        from PySide6.QtCore import QCoreApplication
        app = QCoreApplication.instance()
        if app:
            platform_name = ""
            try:
                from PySide6.QtGui import QGuiApplication
                if isinstance(app, QGuiApplication):
                    platform_name = app.platformName() or ""
            except Exception:
                pass
            return platform_name or "unknown"
    except Exception:
        pass
    return "N/A"


def _get_system_locale() -> str:
    import locale
    try:
        loc = locale.getdefaultlocale()
        if loc and loc[0]:
            return loc[0]
    except Exception:
        pass
    try:
        return locale.getlocale()[0] or "N/A"
    except Exception:
        return "N/A"


def _get_system_uptime() -> str:
    try:
        import psutil
        import datetime
        boot_ts = psutil.boot_time()
        now_ts = datetime.datetime.now().timestamp()
        delta_sec = int(now_ts - boot_ts)
        hours, remainder = divmod(delta_sec, 3600)
        minutes, seconds = divmod(remainder, 60)
        days = hours // 24
        hours = hours % 24
        parts: list[str] = []
        if days > 0:
            parts.append(f"{days}天")
        if hours > 0:
            parts.append(f"{hours}小时")
        parts.append(f"{minutes}分钟")
        return "".join(parts)
    except Exception:
        pass
    if platform.system() == "Windows":
        try:
            import subprocess
            result = subprocess.run(
                ["wmic", "os", "get", "LastBootUpTime"],
                capture_output=True, text=True, timeout=5,
            )
            lines = [l.strip() for l in result.stdout.strip().split("\n") if l.strip()]
            if len(lines) >= 2:
                import datetime
                boot_str = lines[1].split(".")[0]
                try:
                    boot_dt = datetime.datetime.strptime(boot_str, "%Y%m%d%H%M%S")
                    now = datetime.datetime.now()
                    delta = now - boot_dt
                    total_sec = int(delta.total_seconds())
                    hours, remainder = divmod(total_sec, 3600)
                    minutes, seconds = divmod(remainder, 60)
                    days = hours // 24
                    hours = hours % 24
                    parts = []
                    if days > 0:
                        parts.append(f"{days}天")
                    if hours > 0:
                        parts.append(f"{hours}小时")
                    parts.append(f"{minutes}分钟")
                    return "".join(parts)
                except Exception:
                    pass
        except Exception:
            pass
    return "N/A"

# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller Spec — 小树时钟
生成方式：由 build.py 调用，也可单独执行：
    pyinstaller little_tree.spec
"""
import os
import re
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules

# debug 模式：build.py --debug 时开启控制台窗口
_debug_console = os.environ.get("LITTLE_TREE_DEBUG") == "1"

block_cipher = None

# ── 收集所有官方插件声明的依赖（作为 hiddenimports）────────────────── #
_plugin_deps: set[str] = set()
for _req in Path("plugins_ext").rglob("requirements.txt"):
    for _line in _req.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#"):
            _pkg = re.split(r"[>=<!;\[]", _line)[0].strip().replace("-", "_")
            if _pkg:
                _plugin_deps.add(_pkg)

# ── 动态收集包含大量运行时组件的库 ───────────────────────────────────── #
_qfw_d,  _qfw_b,  _qfw_h  = collect_all("qfluentwidgets")
_qfrm_d, _qfrm_b, _qfrm_h = collect_all("qframelesswindow")
_pip_d,  _pip_b,  _pip_h  = collect_all("pip")      # 供插件运行时安装依赖

# ── Analysis ─────────────────────────────────────────────────────────── #
a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[
        *_qfw_b,
        *_qfrm_b,
        *_pip_b,
    ],
    datas=[
        ("icon.png", "."),      # 运行时通过 sys._MEIPASS/icon.png 访问
        *_qfw_d,
        *_qfrm_d,
        *_pip_d,
    ],
    hiddenimports=[
        # ── PySide6 额外模块 ──────────────────────────────────────────── #
        "PySide6.QtNetwork",        # QLocalServer / QLocalSocket（单实例）
        "PySide6.QtMultimedia",     # 铃声服务
        "PySide6.QtMultimediaWidgets",
        "PySide6.QtSvg",            # qfluentwidgets 图标依赖
        "PySide6.QtSvgWidgets",
        "PySide6.QtXml",
        "PySide6.QtPrintSupport",
        # ── qfluentwidgets / qframelesswindow ──────────────────────────── #
        *_qfw_h,
        *_qfrm_h,
        "darkdetect",               # qfluentwidgets 深色模式检测
        # ── pip（插件运行时依赖安装）────────────────────────────────────── #
        *_pip_h,
        # ── pynput（Windows 钩子）──────────────────────────────────────── #
        "pynput.keyboard._win32",
        "pynput.mouse._win32",
        # ── 时区 ─────────────────────────────────────────────────────── #
        "tzdata",
        "zoneinfo",
        "zoneinfo._tzpath",
        "zoneinfo._common",
        # ── 网络 ─────────────────────────────────────────────────────── #
        "requests",
        "requests.adapters",
        "urllib3",
        "urllib3.util.retry",
        "urllib3.util.timeout",
        "certifi",
        "charset_normalizer",
        "idna",
        # ── 图像 ─────────────────────────────────────────────────────── #
        "PIL",
        "PIL.Image",
        "PIL.ImageQt",
        # ── 其他 ─────────────────────────────────────────────────────── #
        "loguru",
        "ntplib",
        "importlib.metadata",
        "importlib.resources",
        # ── app 模块（供插件动态导入）────────────────────────────────── #
        "app.plugins",
        "app.plugins.base_plugin",
        "app.events",
        "app.widgets",
        "app.widgets.base_widget",
        "app.widgets.fluent_font_picker",
        # ── 官方插件声明的第三方依赖 ─────────────────────────────────── #
        *sorted(_plugin_deps),
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=["rthooks/pyi_rthook_pip_distlib.py"],
    excludes=[
        "tkinter",
        "matplotlib",
        "numpy",
        "pandas",
        "scipy",
        "IPython",
        "jupyter",
        "test",
        "unittest",
        # ── 不需要的 Qt 子系统（节省大量空间）──────────────────────────── #
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebEngineQuick",
        "PySide6.QtQml",
        "PySide6.QtQmlCore",
        "PySide6.QtQmlMeta",
        "PySide6.QtQmlModels",
        "PySide6.QtQmlNetwork",
        "PySide6.QtQmlWorkerScript",
        "PySide6.QtQmlXmlListModel",
        "PySide6.QtQuick",
        "PySide6.QtQuickControls2",
        "PySide6.QtQuickEffects",
        "PySide6.QtQuickLayouts",
        "PySide6.QtQuickParticles",
        "PySide6.QtQuickShapes",
        "PySide6.QtQuickTemplates2",
        "PySide6.QtQuickTest",
        "PySide6.QtQuickTimeline",
        "PySide6.QtQuickWidgets",
        "PySide6.QtShaderTools",
        "PySide6.Qt3DAnimation",
        "PySide6.Qt3DCore",
        "PySide6.Qt3DExtras",
        "PySide6.Qt3DInput",
        "PySide6.Qt3DLogic",
        "PySide6.Qt3DRender",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
        "PySide6.QtGraphs",
        "PySide6.QtLocation",
        "PySide6.QtPositioning",
        "PySide6.QtSensors",
        "PySide6.QtScxml",
        "PySide6.QtRemoteObjects",
        "PySide6.QtVirtualKeyboard",
        "PySide6.QtStateMachine",
        "PySide6.QtTest",
        "PySide6.QtSql",
        "PySide6.QtSerialPort",
        "PySide6.QtTextToSpeech",
        "PySide6.QtSpatialAudio",
        "PySide6.QtWebChannel",
        "PySide6.QtWebSockets",
        "PySide6.QtWebView",
        "PySide6.QtPdf",
        "PySide6.QtPdfWidgets",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# ── 过滤掉不需要的 Qt6 DLL（双保险，excludes 不能完全阻止 DLL 被收集）── #
_EXCLUDE_QT_DLL_PREFIXES = (
    "Qt6WebEngine",       # 192 MB，无 Web 功能
    "Qt6Qml",             # QML 运行时
    "Qt6Quick",           # Qt Quick UI 体系
    "Qt6ShaderTools",     # Quick 着色器编译
    "Qt63D",              # 3D 渲染
    "Qt6Charts",          # 图表
    "Qt6DataVisualization",
    "Qt6Graphs",
    "Qt6Location",
    "Qt6Positioning",
    "Qt6Sensors",
    "Qt6Scxml",
    "Qt6RemoteObjects",
    "Qt6VirtualKeyboard",
    "Qt6StateMachine",
    "Qt6Test",
    "Qt6Sql",
    "Qt6SerialPort",
    "Qt6TextToSpeech",
    "Qt6SpatialAudio",
    "Qt6WebChannel",
    "Qt6WebSockets",
    "Qt6WebView",
    "Qt6Pdf",
    "Qt6Labs",
)

def _keep_binary(entry):
    name = entry[0]  # (dest_name, src_path, type)
    import os
    basename = os.path.basename(name)
    return not any(basename.startswith(p) for p in _EXCLUDE_QT_DLL_PREFIXES)

a.binaries = TOC([b for b in a.binaries if _keep_binary(b)])
a.datas    = TOC([d for d in a.datas    if _keep_binary(d)])

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="小树时钟",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,              # 不用 UPX 压缩（防止误报杀毒）
    console=_debug_console,  # --debug 时开启控制台窗口，正常发布为 False
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="icon.png",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="小树时钟",
)

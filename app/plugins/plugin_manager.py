"""插件管理器 — 负责发现、加载、卸载插件"""
from __future__ import annotations

import argparse
from collections import deque
from datetime import datetime
import hashlib
import importlib
import importlib.util
import importlib.metadata
import json
import re
import shlex
import subprocess
import sys
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import QObject, Signal

from .base_plugin import (
    BasePlugin, LibraryPlugin, PluginAPI, PluginMeta,
    PluginPermission, PluginType, _SERVICE_PERMISSION_MAP,
)
from app.constants import PLUGINS_DIR
from app.services.i18n_service import I18nService
from app.utils.fs import append_text_with_uac, mkdir_with_uac, write_text_with_uac
from app.utils.logger import logger


class PermissionLevel(str, Enum):
    """权限级别：适用于安装包和系统权限两种场景。"""
    ALWAYS_ALLOW  = "always"  # 始终允许（记住选择）
    ASK_EACH_TIME = "ask"     # 每次询问
    DENY          = "deny"    # 拒绝（记住选择）


# 权限类型到可读名称的映射
PERMISSION_NAMES: dict[str, str] = {
    PluginPermission.NETWORK:      "网络请求",
    PluginPermission.FS_READ:      "读取文件",
    PluginPermission.FS_WRITE:     "写入/删除文件",
    PluginPermission.OS_EXEC:      "执行外部命令",
    PluginPermission.OS_ENV:       "读写环境变量",
    PluginPermission.CLIPBOARD:    "访问剪贴板",
    PluginPermission.NOTIFICATION: "发送系统通知",
    PluginPermission.INSTALL_PKG:  "安装第三方库",
}
_KNOWN_PERMISSION_KEYS = {perm.value for perm in PluginPermission}
_PERM_SCAN_CACHE: dict[str, tuple[tuple[tuple[str, int, int], ...], list[str]]] = {}
_PERMISSION_AUDIT_MAX_ENTRIES = 500
_INLINE_ICON_BASE64_RE = re.compile(r"^[A-Za-z0-9+/=\s]+$")


def _perm_display_name(perm_key: str) -> str:
    i18n_key = f"perm.{perm_key}"
    return I18nService.instance().t(i18n_key, default=PERMISSION_NAMES.get(perm_key, perm_key))


# ── 插件本地 site-packages 目录（打包后依赖装在这里）─────────────────── #
_PLUGIN_LIB_DIR = Path(PLUGINS_DIR) / "_lib"
_plugin_lib_str = str(_PLUGIN_LIB_DIR)
if _plugin_lib_str not in sys.path:
    sys.path.insert(0, _plugin_lib_str)

# ── 插件 ID 合法性校验（防路径穿越及注入）──────────────────────────── #
# 规则：以小写字母开头，仅含小写字母 / 数字 / 下划线，最多 64 个字符
_VALID_PLUGIN_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
# ── 插件包扩展名（文件内容仍为 ZIP）─────────────────────────────── #
PLUGIN_PACKAGE_EXTENSION = ".ltcplugin"
PLUGIN_PACKAGE_FILE_EXTENSIONS = {PLUGIN_PACKAGE_EXTENSION}
# ── 静态权限扫描模式 ────────────────────────────────────────── #
# 每个权限类型对应的关键词模式列表（在插件 .py 源码中执行逐行匹配）
_PERM_SCAN_PATTERNS: dict[str, list[str]] = {
    PluginPermission.NETWORK: [
        r"import\s+requests\b",   r"from\s+requests\b",
        r"import\s+httpx\b",      r"from\s+httpx\b",
        r"import\s+aiohttp\b",    r"from\s+aiohttp\b",
        r"urllib\.request",       r"http\.client",
        r"from\s+urllib\b",
    ],
    PluginPermission.OS_EXEC: [
        r"import\s+subprocess\b", r"from\s+subprocess\b",
        r"\bos\.system\s*\(",    r"\bos\.popen\s*\(",
    ],
    PluginPermission.OS_ENV: [
        r"\bos\.environ\b",       r"\bos\.getenv\s*\(",
        r"\bos\.putenv\s*\(",
    ],
    PluginPermission.CLIPBOARD: [
        r"import\s+pyperclip\b",  r"\bQClipboard\b",
    ],
}


def _iter_plugin_source_files(plugin_path: Path) -> list[Path]:
    if not plugin_path.is_dir():
        return []
    return sorted(
        py_file
        for py_file in plugin_path.rglob("*.py")
        if "_lib" not in py_file.parts
    )


def _plugin_source_signature(plugin_path: Path) -> tuple[tuple[str, int, int], ...]:
    signature: list[tuple[str, int, int]] = []
    for py_file in _iter_plugin_source_files(plugin_path):
        try:
            stat = py_file.stat()
            signature.append((
                py_file.relative_to(plugin_path).as_posix(),
                stat.st_mtime_ns,
                stat.st_size,
            ))
        except OSError:
            continue
    return tuple(signature)


def _dedupe_text_list(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _is_safe_requirement_spec(requirement: str) -> bool:
    req = requirement.strip()
    if not req:
        return False
    lowered = req.lower()
    if req.startswith("-"):
        return False
    if " @ " in req or "@" in req.split(";", 1)[0]:
        return False
    if "://" in lowered or lowered.startswith(("git+", "hg+", "svn+", "bzr+", "file:")):
        return False
    dist_name = _dist_name(req)
    if not dist_name:
        return False
    if any(sep in dist_name for sep in ("/", "\\")):
        return False
    return True


def _looks_like_inline_icon_data(icon_text: str) -> bool:
    """返回图标字段是否为 inline base64（data URI 或原始 base64 文本）。"""
    text = str(icon_text or "").strip()
    if not text:
        return False
    if text.lower().startswith("data:image/"):
        return True
    compact = text.replace("\r", "").replace("\n", "").replace(" ", "")
    return len(compact) >= 64 and bool(_INLINE_ICON_BASE64_RE.fullmatch(compact))


def _normalize_manifest(meta: PluginMeta, manifest_path: Path) -> PluginMeta:
    meta.id = str(meta.id).strip()
    meta.name = str(meta.name).strip() or meta.id
    meta.version = str(meta.version).strip() or "1.0.0"
    meta.author = str(meta.author).strip()
    meta.description = str(meta.description).strip()
    meta.homepage = str(meta.homepage).strip()
    meta.icon = str(meta.icon).strip()
    meta.min_host_version = str(meta.min_host_version).strip()

    if meta.icon and not _looks_like_inline_icon_data(meta.icon):
        # 相对路径按 plugin.json 所在目录解析，避免目录名与插件 ID 不一致时失效。
        if "://" not in meta.icon:
            icon_path = Path(meta.icon).expanduser()
            if not icon_path.is_absolute():
                icon_path = (manifest_path.parent / icon_path).resolve(strict=False)
            meta.icon = str(icon_path)

    meta.requires = _dedupe_text_list(meta.requires)
    if meta.id and meta.id in meta.requires:
        logger.warning("plugin.json 声明了自依赖，已忽略: {}", manifest_path)
        meta.requires = [dep for dep in meta.requires if dep != meta.id]

    normalized_deps: list[str] = []
    for dep in _dedupe_text_list(meta.dependencies):
        if _is_safe_requirement_spec(dep):
            normalized_deps.append(dep)
        else:
            logger.warning("plugin.json 含不安全依赖声明，已忽略: {} -> {}", manifest_path, dep)
    meta.dependencies = normalized_deps

    normalized_permissions: list[str] = []
    for perm in _dedupe_text_list(meta.permissions):
        if perm not in _KNOWN_PERMISSION_KEYS:
            logger.warning("plugin.json 含未知权限声明，已忽略: {} -> {}", manifest_path, perm)
            continue
        normalized_permissions.append(perm)
    meta.permissions = normalized_permissions

    meta.tags = _dedupe_text_list(meta.tags)
    return meta


def _build_plugin_module_prefix(plugin_key: str, path: Path) -> str:
    """为插件构造稳定且隔离的模块命名空间前缀。"""
    safe_key = re.sub(r"[^a-zA-Z0-9_]", "_", plugin_key) or "plugin"
    digest = hashlib.sha1(str(path.resolve()).encode("utf-8")).hexdigest()[:10]
    return f"_ltc_plugin_{safe_key}_{digest}"


def _scan_undeclared_perms(
    plugin_path: Path,
    declared: list[str],
) -> list[str]:
    """\u626b\u63cf\u63d2\u4ef6\u76ee\u5f55\u4e2d\u6240\u6709 .py \u6587\u4ef6\uff0c\u8fd4\u56de\u4ee3\u7801\u4e2d\u4f7f\u7528\u4e86\u4f46\u672a\u5728 permissions \u4e2d\u58f0\u660e\u7684\u6743\u9650\u952e\u5217\u8868\u3002

    \u626b\u63cf\u4ec5\u662f\u8f85\u52a9\u63d0\u793a\uff0c\u7ed3\u679c\u5305\u542b\u8bef\u62a5/\u6f0f\u62a5\uff0c\u4e0d\u80fd\u4fdd\u8bc1\u5b89\u5168\u3002
    """
    if not plugin_path.is_dir():
        return []

    cache_key = str(plugin_path.resolve())
    signature = _plugin_source_signature(plugin_path)
    cached = _PERM_SCAN_CACHE.get(cache_key)
    detected: list[str]

    if cached and cached[0] == signature:
        detected = cached[1]
    else:
        combined = []
        for py_file in _iter_plugin_source_files(plugin_path):
            try:
                combined.append(py_file.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                pass
        source = "\n".join(combined)

        detected = []
        for perm_key, patterns in _PERM_SCAN_PATTERNS.items():
            if any(re.search(p, source) for p in patterns):
                detected.append(perm_key)
        _PERM_SCAN_CACHE[cache_key] = (signature, detected)

    return [perm_key for perm_key in detected if perm_key not in declared]

def _normalize_pkg_name(name: str) -> str:
    """将依赖声明规范化为可用于 import 的顶层模块名。"""
    requirement = name.split(";", 1)[0].strip()
    match = re.match(r"^([A-Za-z0-9_.-]+)", requirement)
    base_name = match.group(1) if match else requirement
    return base_name.replace("-", "_")


def _dist_name(name: str) -> str:
    """从 requirement 字符串中提取发行包名。"""
    requirement = name.split(";", 1)[0].strip()
    match = re.match(r"^([A-Za-z0-9_.-]+)", requirement)
    return (match.group(1) if match else requirement).strip()


def _pkg_importable(pkg: str) -> bool:
    """返回包是否已可 import（检查 importlib.metadata 或直接 import）。"""
    normalized = _normalize_pkg_name(pkg)
    dist_name = _dist_name(pkg)
    # 先查 metadata（更准确，能识别已安装但尚未 import 的包）
    try:
        importlib.metadata.version(dist_name)
        return True
    except importlib.metadata.PackageNotFoundError:
        pass
    # 退而求其次，尝试直接 import
    try:
        importlib.import_module(normalized)
        return True
    except ImportError:
        return False


def _collect_deps(plugin_path: Path) -> list[str]:
    """收集插件声明的依赖列表（不检查是否已安装）。"""
    deps: list[str] = []
    req_file = plugin_path / "requirements.txt"
    if req_file.exists():
        for line in req_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                if _is_safe_requirement_spec(line):
                    deps.append(line)
                else:
                    logger.warning("插件 {} 的 requirements.txt 含不安全依赖声明，已忽略: {}", plugin_path.name, line)
    else:
        json_file = plugin_path / "plugin.json"
        if json_file.exists():
            try:
                meta = json.loads(json_file.read_text(encoding="utf-8"))
                raw_deps = meta.get("dependencies", [])
                for dep in raw_deps if isinstance(raw_deps, list) else []:
                    dep_text = str(dep).strip()
                    if not dep_text:
                        continue
                    if _is_safe_requirement_spec(dep_text):
                        deps.append(dep_text)
                    else:
                        logger.warning("插件 {} 的 plugin.json 含不安全依赖声明，已忽略: {}", plugin_path.name, dep_text)
            except Exception:
                pass
    return _dedupe_text_list(deps)


def _collect_missing_deps(plugin_path: Path) -> list[str]:
    """返回插件缺失（尚未安装）的依赖包名列表。"""
    deps = _collect_deps(plugin_path)
    return [d for d in deps if not _pkg_importable(d)]


def _ensure_plugin_deps(plugin_path: Path) -> list[str]:
    """检查并安装插件缺失的依赖，返回安装失败的包名列表。

    依赖来源（按优先级）：
    1. ``requirements.txt``
    2. ``plugin.json`` 中的 ``dependencies`` 字段

    安装目标：``plugins_ext/_lib/``（本地 site-packages）。
    安装器：``sys.executable -m pip``，打包后使用嵌入的 pip。
    """
    missing = _collect_missing_deps(plugin_path)
    if not missing:
        return []

    logger.info("插件 {} 缺少依赖 {}，尝试自动安装…", plugin_path.name, missing)
    mkdir_with_uac(_PLUGIN_LIB_DIR, parents=True, exist_ok=True)

    # 读取用户配置的镜像源（惰性导入，避免循环依赖）
    _mirror_url: str = ""
    try:
        from app.services.settings_service import SettingsService
        _mirror_url = SettingsService.instance().pip_mirror
    except Exception:
        pass

    def _build_pip_args(pkg: str) -> list[str]:
        """构建 pip install 参数列表，可选附加 --index-url"""
        args = [
            "install",
            "--isolated",
            "--disable-pip-version-check",
            "--quiet",
            "--target", str(_PLUGIN_LIB_DIR),
        ]
        if _mirror_url:
            args += ["--index-url", _mirror_url,
                     "--trusted-host", _mirror_url.split("/")[2]]
        args.append(pkg)
        return args

    failed: list[str] = []
    for pkg in missing:
        if getattr(sys, "frozen", False):
            # 打包后 sys.executable 是 app 本身的 .exe，一旦用 subprocess 调用
            # 会重新启动程序实例，导致无限窗口；改用 pip 内部 API 在当前进程内安装
            try:
                from pip._internal.cli.main import main as _pip_main  # type: ignore[import]
                rc = _pip_main(_build_pip_args(pkg))
                if rc == 0:
                    logger.success("插件依赖 '{}' 安装成功", pkg)
                else:
                    logger.error("插件依赖 '{}' 安装失败（pip 返回码 {}）", pkg, rc)
                    failed.append(pkg)
            except ImportError:
                logger.error(
                    "打包环境中 pip 不可用，无法自动安装 '{}'，请手动安装后重启", pkg
                )
                failed.append(pkg)
            except Exception:
                logger.exception("安装插件依赖 '{}' 时发生异常", pkg)
                failed.append(pkg)
        else:
            # 开发环境：通过 subprocess 调用当前 Python 解释器的 pip
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "pip"] + _build_pip_args(pkg),
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                if result.returncode == 0:
                    logger.success("插件依赖 '{}' 安装成功", pkg)
                else:
                    logger.error("插件依赖 '{}' 安装失败:\n{}", pkg, result.stderr.strip())
                    failed.append(pkg)
            except subprocess.TimeoutExpired:
                logger.error("插件依赖 '{}' 安装超时", pkg)
                failed.append(pkg)
            except FileNotFoundError:
                logger.error("无法调用 pip，请手动安装依赖: {}", pkg)
                failed.append(pkg)
            except Exception:
                logger.exception("安装插件依赖 '{}' 时发生异常", pkg)
                failed.append(pkg)

    # 安装完成后，确保 _lib 目录在 sys.path 中
    lib_str = str(_PLUGIN_LIB_DIR)
    if lib_str not in sys.path:
        sys.path.insert(0, lib_str)

    return failed


class PluginEntry:
    """插件运行时记录"""

    def __init__(self, plugin: BasePlugin, api: PluginAPI):
        self.plugin    = plugin
        self.api       = api
        self.enabled   = True
        self.error: Optional[str]     = None   # on_load 异常或其他致命错误
        self.dep_warning: Optional[str] = None  # 依赖安装失败/被拒绝的警告（插件仍运行）
        self.load_failed: bool = False          # True 时插件未成功完成 on_load
        # 记录哪些插件依赖了本插件（用于卷载驱逐检查）
        self.dependents: set[str]  = set()
        # 记录该插件注册的小组件类型（用于卸载时清理）
        self.widget_types: set[str] = set()
        # 记录该插件模块命名空间前缀（用于卸载时清理 sys.modules）
        self.module_prefix: str = ""

    @property
    def meta(self) -> PluginMeta:
        return self.plugin.meta

    @property
    def is_library(self) -> bool:
        return self.meta.plugin_type == PluginType.LIBRARY


class PluginManager(QObject):
    """插件管理器（单例挂载在 App 上）。

    外部插件目录结构（推荐包形式）::

        plugins_ext/
            my_lib/
                plugin.json       ← plugin_type: "library"
                __init__.py       ← Plugin(LibraryPlugin)
            my_plugin/
                plugin.json       ← plugin_type: "feature", requires: ["my_lib"]
                __init__.py       ← Plugin(BasePlugin)
            simple_plugin.py      ← 单文件插件（无清单文件）

    加载顺序：管理器根据 ``requires`` 对所有插件做拓扑排序，
    确保依赖插件在依赖方之前完成加载。
    """

    pluginLoaded   = Signal(str)         # plugin_id
    pluginUnloaded = Signal(str)
    pluginError    = Signal(str, str)    # plugin_id, error_message
    scanCompleted  = Signal()            # discover_and_load 完成
    aboutToShowPermDialog = Signal()     # 即将弹出权限对话框（用于关闭 SplashScreen）
    # 静态权限扫描发现未声明权限：(plugin_id, plugin_name, undeclared_perm_keys)
    pluginPermWarn = Signal(str, str, object)
    # 运行期权限变更：(plugin_id, perm_key, granted)
    pluginRuntimePermissionChanged = Signal(str, str, bool)
    # 权限审计日志新增记录：(plugin_id,)
    pluginPermissionAuditLogged = Signal(str)

    def __init__(self, shared_api: Optional[PluginAPI] = None,
                 services: Optional[Dict[str, Any]] = None,
                 toast_callback=None,
                 parent=None):
        super().__init__(parent)
        self._shared_api   = shared_api or PluginAPI()
        self._services     = services or {}
        self._toast_cb     = toast_callback
        self._entries: Dict[str, PluginEntry] = {}
        self._failed_entries: Dict[str, PluginEntry] = {}  # on_load 失败的插件（仍在 UI 中显示）
        self._disabled_ids: set[str] = set()          # 已禁用插件的 ID 集合（持久化用）
        self._disabled_metas: Dict[str, PluginMeta] = {}  # 已禁用但已扫描到的插件元数据
        # 权限回调：(plugin_id, plugin_name, packages) -> PermissionLevel
        # 返回 ALWAYS_ALLOW / ASK_EACH_TIME(本次允许) / DENY
        self._permission_callback: Optional[Callable[[str, str, list[str]], PermissionLevel]] = None
        self._permissions: Dict[str, PermissionLevel] = {}  # plugin_id -> 已保存的包安装权限
        # 系统权限：{plugin_id: {permission_key: PermissionLevel}}
        self._sys_permissions: Dict[str, Dict[str, PermissionLevel]] = {}
        # 系统权限询问回调：(plugin_id, plugin_name, perm_key, perm_display) -> PermissionLevel
        self._sys_perm_callback: Optional[
            Callable[[str, str, str, str, str], PermissionLevel]
        ] = None
        self._automation_engine = None   # 由外部调用 set_automation_engine 注入
        self._startup_context: Dict[str, Any] = {
            "hidden_mode": False,
            "extra_args":  "",
        }
        self._permission_audit: deque[dict[str, Any]] = deque(maxlen=_PERMISSION_AUDIT_MAX_ENTRIES)
        self._load_permissions()
        self._load_permission_audit_history()

    # ------------------------------------------------------------------ #
    # 属性
    # ------------------------------------------------------------------ #

    @property
    def api(self) -> PluginAPI:
        return self._shared_api

    def all_entries(self) -> List[PluginEntry]:
        return list(self._entries.values())

    def get_entry(self, plugin_id: str) -> Optional[PluginEntry]:
        return self._entries.get(plugin_id)

    @staticmethod
    def _normalize_permission_key(permission: str | PluginPermission) -> str:
        return permission.value if isinstance(permission, PluginPermission) else str(permission)

    def all_known_plugins(self) -> List[tuple]:
        """返回所有已发现插件（含已禁用）的信息四元组列表：
        ``(meta: PluginMeta, enabled: bool, error: str | None, dep_warning: str | None)``
        """
        result: List[tuple] = []
        seen: set[str] = set()
        for entry in self._entries.values():
            result.append((entry.meta, entry.enabled, entry.error, entry.dep_warning))
            seen.add(entry.meta.id)
        for pid, entry in self._failed_entries.items():
            if pid not in seen:
                result.append((entry.meta, False, entry.error, entry.dep_warning))
                seen.add(pid)
        for pid, meta in self._disabled_metas.items():
            if pid not in seen:
                result.append((meta, False, None, None))
        return result

    def _plugin_display_name(self, plugin_id: str) -> str:
        """返回插件当前可用于展示的名称。"""
        entry = self._entries.get(plugin_id) or self._failed_entries.get(plugin_id)
        if entry is not None:
            return entry.meta.get_name(I18nService.instance().language)
        meta = self._disabled_metas.get(plugin_id)
        if meta is not None:
            return meta.get_name(I18nService.instance().language)
        return plugin_id

    def _find_entry_by_widget_type(self, widget_type: str) -> Optional[PluginEntry]:
        for entry in self._entries.values():
            if widget_type in entry.widget_types:
                return entry
        return None

    def build_widget_services(
        self,
        widget_type: str,
        base_services: Dict[str, Any],
    ) -> Dict[str, Any]:
        """为指定组件类型构建隔离后的服务视图。"""
        services = dict(base_services)
        entry = self._find_entry_by_widget_type(widget_type)
        if entry is None:
            return services

        for service_name, required_perm in _SERVICE_PERMISSION_MAP.items():
            if service_name in services and not entry.api.has_permission(required_perm):
                services.pop(service_name, None)

        services.update(entry.api.list_canvas_services())
        return services

    @staticmethod
    def _cleanup_plugin_modules(module_prefix: str) -> None:
        """移除插件加载期间写入 sys.modules 的模块，降低重载污染。"""
        if not module_prefix:
            return
        targets = [
            name for name in list(sys.modules.keys())
            if name == module_prefix or name.startswith(f"{module_prefix}.")
        ]
        for name in targets:
            sys.modules.pop(name, None)

    # ------------------------------------------------------------------ #
    # 状态持久化
    # ------------------------------------------------------------------ #

    def set_permission_callback(
        self,
        callback: Callable[[str, str, list[str]], PermissionLevel],
    ) -> None:
        """设置包安装权限询问回调。

        ``callback(plugin_id, plugin_name, packages) -> PermissionLevel``
        将在插件需要安装缺失库时被调用（在主线程同步执行）。
        """
        self._permission_callback = callback

    def set_sys_permission_callback(
        self,
        callback: Callable[[str, str, str, str, str], PermissionLevel],
    ) -> None:
        """设置系统权限询问回调。

        ``callback(plugin_id, plugin_name, perm_key, perm_display, reason) -> PermissionLevel``
        将在插件首次加载且声明了某系统权限时被调用。
        """
        self._sys_perm_callback = callback

    def set_automation_engine(self, engine) -> None:
        """注入自动化引擎引用，插件可通过 api.fire_trigger() 触发规则执行。"""
        self._automation_engine = engine

    def set_startup_context(
        self,
        hidden_mode: bool = False,
        extra_args:  str  = "",
    ) -> None:
        """设置本次启动上下文，应在 ``discover_and_load`` 调用之前调用。

        每个插件的 ``PluginAPI`` 实例都会注入此上下文，可通过
        ``api.get_startup_args()`` 读取；``--extra-args`` 中的自定义参数在
        全部插件完成 ``on_load`` 后被解析并分发到对应的处理器。

        注意：安全模式下插件不会被加载，无需（也无法）通过此上下文感知安全状态。

        Parameters
        ----------
        hidden_mode : bool
            是否以隐藏模式启动（主窗口未显示）。
        extra_args : str
            ``--extra-args`` 原始字符串，留给插件自行注册并解析。
        """
        self._startup_context = {
            "hidden_mode": hidden_mode,
            "extra_args":  extra_args,
        }



    def _permissions_path(self) -> Path:
        return Path(PLUGINS_DIR) / "._data" / "plugin_permissions.json"

    def _sys_permissions_path(self) -> Path:
        return Path(PLUGINS_DIR) / "._data" / "plugin_sys_permissions.json"

    def _permission_audit_path(self) -> Path:
        return Path(PLUGINS_DIR) / "._data" / "plugin_permission_audit.jsonl"

    def _load_permissions(self) -> None:
        # 包安装权限
        path = self._permissions_path()
        if path.exists():
            try:
                raw: dict = json.loads(path.read_text(encoding="utf-8"))
                for pid, lvl in raw.items():
                    try:
                        self._permissions[pid] = PermissionLevel(lvl)
                    except ValueError:
                        pass
            except Exception:
                logger.exception("插件权限文件加载失败: {}", path)
        # 系统权限
        sys_path = self._sys_permissions_path()
        if sys_path.exists():
            try:
                raw2: dict = json.loads(sys_path.read_text(encoding="utf-8"))
                for pid, perms in raw2.items():
                    self._sys_permissions[pid] = {}
                    for key, lvl in perms.items():
                        try:
                            self._sys_permissions[pid][key] = PermissionLevel(lvl)
                        except ValueError:
                            pass
            except Exception:
                logger.exception("插件系统权限文件加载失败: {}", sys_path)

    def _load_permission_audit_history(self) -> None:
        """加载最近的插件权限审计记录。"""
        path = self._permission_audit_path()
        if not path.exists():
            return
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except Exception:
            logger.exception("插件权限审计日志加载失败: {}", path)
            return

        for line in lines[-_PERMISSION_AUDIT_MAX_ENTRIES:]:
            text = line.strip()
            if not text:
                continue
            try:
                item = json.loads(text)
            except Exception:
                continue
            if isinstance(item, dict):
                self._permission_audit.append(item)

    def _save_permissions(self) -> None:
        path = self._permissions_path()
        try:
            write_text_with_uac(
                path,
                json.dumps(
                    {pid: lvl.value for pid, lvl in self._permissions.items()},
                    ensure_ascii=False, indent=2,
                ),
                encoding="utf-8",
                ensure_parent=True,
            )
        except Exception:
            logger.exception("插件权限保存失败: {}", path)

    def _save_sys_permissions(self) -> None:
        sys_path = self._sys_permissions_path()
        try:
            write_text_with_uac(
                sys_path,
                json.dumps(
                    {
                        pid: {k: lvl.value for k, lvl in perms.items()}
                        for pid, perms in self._sys_permissions.items()
                    },
                    ensure_ascii=False, indent=2,
                ),
                encoding="utf-8",
                ensure_parent=True,
            )
        except Exception:
            logger.exception("插件系统权限保存失败: {}", sys_path)

    def _append_permission_audit(
        self,
        plugin_id: str,
        plugin_name: str,
        perm_key: str | PluginPermission,
        *,
        source: str,
        decision: str,
        reason: str = "",
        details: Any = None,
    ) -> None:
        """追加一条权限审计记录，并持久化为 JSONL。"""
        key = self._normalize_permission_key(perm_key)
        entry: dict[str, Any] = {
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            "plugin_id": plugin_id,
            "plugin_name": plugin_name or plugin_id,
            "permission": key,
            "source": source,
            "decision": decision,
        }
        if reason:
            entry["reason"] = reason
        if details not in (None, "", [], {}):
            entry["details"] = details

        self._permission_audit.append(entry)

        path = self._permission_audit_path()
        try:
            append_text_with_uac(
                path,
                json.dumps(entry, ensure_ascii=False) + "\n",
                encoding="utf-8",
                ensure_parent=True,
            )
        except Exception:
            logger.exception("插件权限审计日志保存失败: {}", path)

        logger.info(
            "插件权限审计 [{}] {} {} -> {}",
            source,
            plugin_id,
            key,
            decision,
        )
        self.pluginPermissionAuditLogged.emit(plugin_id)

    def get_permission(self, plugin_id: str) -> Optional[PermissionLevel]:
        """返回已持久化的包安装权限，未设置时返回 None。"""
        return self._permissions.get(plugin_id)

    def get_sys_permissions(self, plugin_id: str) -> Dict[str, PermissionLevel]:
        """返回插件的所有已持久化系统权限。"""
        return dict(self._sys_permissions.get(plugin_id, {}))

    def get_runtime_permissions(self, plugin_id: str) -> set[str]:
        """返回插件在当前会话中实际获准的权限集合。"""
        entry = self._entries.get(plugin_id) or self._failed_entries.get(plugin_id)
        if entry is None:
            return set()
        return set(entry.api.list_granted_permissions())

    def get_permission_audit_entries(
        self,
        plugin_id: str | None = None,
        *,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """返回最近的权限审计记录，按时间倒序排列。"""
        if limit <= 0:
            return []

        result: list[dict[str, Any]] = []
        for item in reversed(self._permission_audit):
            if plugin_id and item.get("plugin_id") != plugin_id:
                continue
            result.append(dict(item))
            if len(result) >= limit:
                break
        return result

    def _set_runtime_permission(
        self,
        plugin_id: str,
        perm_key: str | PluginPermission,
        granted: bool,
    ) -> bool:
        """更新运行期权限状态，并在变化时发出通知。"""
        entry = self._entries.get(plugin_id) or self._failed_entries.get(plugin_id)
        if entry is None:
            return False

        key = self._normalize_permission_key(perm_key)
        before = entry.api.has_permission(key)
        if granted:
            entry.api._grant_permission(key)
        else:
            entry.api._revoke_permission(key)
        after = entry.api.has_permission(key)

        if before != after:
            self.pluginRuntimePermissionChanged.emit(plugin_id, key, after)
            return True
        return False

    def request_plugin_permission(
        self,
        plugin_id: str,
        perm_key: str | PluginPermission,
        *,
        reason: str = "",
    ) -> bool:
        """供运行中的插件动态申请已声明系统权限。"""
        key = self._normalize_permission_key(perm_key)
        entry = self._entries.get(plugin_id)
        if entry is None:
            self._append_permission_audit(
                plugin_id,
                self._plugin_display_name(plugin_id),
                key,
                source="runtime",
                decision="deny_unloaded",
                reason=reason,
            )
            logger.warning("插件 {} 未处于已加载状态，无法动态申请权限", plugin_id)
            return False

        plugin_name = entry.meta.get_name(I18nService.instance().language)
        if key == PluginPermission.INSTALL_PKG.value:
            self._append_permission_audit(
                plugin_id,
                plugin_name,
                key,
                source="runtime",
                decision="deny_unsupported",
                reason=reason,
            )
            logger.warning("插件 {} 尝试动态申请 install_pkg，当前不支持", plugin_id)
            return False
        declared = {
            self._normalize_permission_key(p)
            for p in entry.meta.permissions
            if p
        }
        if key not in declared:
            self._append_permission_audit(
                plugin_id,
                plugin_name,
                key,
                source="runtime",
                decision="deny_undeclared",
                reason=reason,
            )
            logger.warning("插件 {} 动态申请了未声明权限 {}，请求已拒绝", plugin_id, key)
            return False
        if entry.api.has_permission(key):
            self._append_permission_audit(
                plugin_id,
                plugin_name,
                key,
                source="runtime",
                decision="allow_cached",
                reason=reason,
            )
            return True

        allowed = self._check_sys_permission(
            plugin_id,
            plugin_name,
            key,
            reason=reason,
            source="runtime",
        )
        if allowed:
            self._set_runtime_permission(plugin_id, key, True)
        return allowed

    def set_sys_permission(
        self, plugin_id: str, perm_key: str, level: PermissionLevel
    ) -> None:
        """手动设置并保存某系统权限。"""
        perm_key = self._normalize_permission_key(perm_key)
        if plugin_id not in self._sys_permissions:
            self._sys_permissions[plugin_id] = {}
        if level == PermissionLevel.ASK_EACH_TIME:
            self._sys_permissions[plugin_id].pop(perm_key, None)
            if not self._sys_permissions[plugin_id]:
                self._sys_permissions.pop(plugin_id, None)
        else:
            self._sys_permissions[plugin_id][perm_key] = level
        self._save_sys_permissions()
        self._set_runtime_permission(
            plugin_id,
            perm_key,
            granted=(level == PermissionLevel.ALWAYS_ALLOW),
        )
        self._append_permission_audit(
            plugin_id,
            self._plugin_display_name(plugin_id),
            perm_key,
            source="settings",
            decision={
                PermissionLevel.ALWAYS_ALLOW: "set_always",
                PermissionLevel.ASK_EACH_TIME: "set_ask",
                PermissionLevel.DENY: "set_deny",
            }[level],
        )

    def set_permission(self, plugin_id: str, level: PermissionLevel) -> None:
        """手动设置并保存包安装权限（由界面调用）。"""
        if level == PermissionLevel.ASK_EACH_TIME:
            self._permissions.pop(plugin_id, None)
        else:
            self._permissions[plugin_id] = level
        self._save_permissions()
        self._append_permission_audit(
            plugin_id,
            self._plugin_display_name(plugin_id),
            PluginPermission.INSTALL_PKG,
            source="settings",
            decision={
                PermissionLevel.ALWAYS_ALLOW: "set_always",
                PermissionLevel.ASK_EACH_TIME: "set_ask",
                PermissionLevel.DENY: "set_deny",
            }[level],
        )

    def _check_sys_permission(
        self,
        plugin_id: str,
        plugin_name: str,
        perm_key: str,
        reason: str = "",
        source: str = "startup",
    ) -> bool:
        """检查插件是否已获得指定系统权限，返回 True 表示本次允许。

        若权限已保存（ALWAYS_ALLOW/DENY）则直接返回；
        否则调用回调向用户询问。
        """
        perm_key = self._normalize_permission_key(perm_key)
        saved = self._sys_permissions.get(plugin_id, {}).get(perm_key)
        if saved == PermissionLevel.ALWAYS_ALLOW:
            self._append_permission_audit(
                plugin_id,
                plugin_name,
                perm_key,
                source=source,
                decision="allow_saved",
                reason=reason,
            )
            return True
        if saved == PermissionLevel.DENY:
            self._append_permission_audit(
                plugin_id,
                plugin_name,
                perm_key,
                source=source,
                decision="deny_saved",
                reason=reason,
            )
            logger.info("插件 {} 系统权限 {} 已被拒绝", plugin_id, perm_key)
            return False

        perm_display = _perm_display_name(perm_key)

        if self._sys_perm_callback is None:
            self._append_permission_audit(
                plugin_id,
                plugin_name,
                perm_key,
                source=source,
                decision="allow_no_callback",
                reason=reason,
            )
            logger.warning(
                "插件 {} 需要系统权限 {} 但未设置回调，将直接允许",
                plugin_id, perm_key,
            )
            return True

        self.aboutToShowPermDialog.emit()
        level = self._sys_perm_callback(plugin_id, plugin_name, perm_key, perm_display, reason)
        if level == PermissionLevel.ALWAYS_ALLOW:
            self._sys_permissions.setdefault(plugin_id, {})[perm_key] = PermissionLevel.ALWAYS_ALLOW
            self._save_sys_permissions()
            self._append_permission_audit(
                plugin_id,
                plugin_name,
                perm_key,
                source=source,
                decision="allow_prompt_always",
                reason=reason,
            )
            return True
        elif level == PermissionLevel.ASK_EACH_TIME:
            self._append_permission_audit(
                plugin_id,
                plugin_name,
                perm_key,
                source=source,
                decision="allow_prompt_once",
                reason=reason,
            )
            return True
        else:  # DENY
            self._sys_permissions.setdefault(plugin_id, {})[perm_key] = PermissionLevel.DENY
            self._save_sys_permissions()
            self._append_permission_audit(
                plugin_id,
                plugin_name,
                perm_key,
                source=source,
                decision="deny_prompt",
                reason=reason,
            )
            return False

    def _check_install_permission(
        self,
        plugin_id: str,
        plugin_name: str,
        packages: list[str],
    ) -> bool:
        """检查是否允许安装 packages，返回 True 表示允许本次安装。"""
        pkg_details = ", ".join(packages[:5])
        if len(packages) > 5:
            pkg_details += f" 等 {len(packages)} 个"

        saved = self._permissions.get(plugin_id)
        if saved == PermissionLevel.ALWAYS_ALLOW:
            self._append_permission_audit(
                plugin_id,
                plugin_name,
                PluginPermission.INSTALL_PKG,
                source="install",
                decision="allow_saved",
                details=pkg_details,
            )
            return True
        if saved == PermissionLevel.DENY:
            self._append_permission_audit(
                plugin_id,
                plugin_name,
                PluginPermission.INSTALL_PKG,
                source="install",
                decision="deny_saved",
                details=pkg_details,
            )
            logger.info("插件 {} 安装库已被拒绝（已保存权限）", plugin_id)
            return False

        # 需要询问用户
        if self._permission_callback is None:
            # 无回调时默认允许（兼容无 UI 的情景）
            self._append_permission_audit(
                plugin_id,
                plugin_name,
                PluginPermission.INSTALL_PKG,
                source="install",
                decision="allow_no_callback",
                details=pkg_details,
            )
            logger.warning(
                "插件 {} 需要安装 {} 但未设置权限回调，将直接安装",
                plugin_id, packages,
            )
            return True

        self.aboutToShowPermDialog.emit()
        level = self._permission_callback(plugin_id, plugin_name, packages)
        if level == PermissionLevel.ALWAYS_ALLOW:
            self._permissions[plugin_id] = PermissionLevel.ALWAYS_ALLOW
            self._save_permissions()
            self._append_permission_audit(
                plugin_id,
                plugin_name,
                PluginPermission.INSTALL_PKG,
                source="install",
                decision="allow_prompt_always",
                details=pkg_details,
            )
            return True
        elif level == PermissionLevel.ASK_EACH_TIME:
            # 本次允许（不保存），下次启动检测到缺失时仍会询问
            self._append_permission_audit(
                plugin_id,
                plugin_name,
                PluginPermission.INSTALL_PKG,
                source="install",
                decision="allow_prompt_once",
                details=pkg_details,
            )
            return True
        else:  # DENY（永久拒绝）
            self._permissions[plugin_id] = PermissionLevel.DENY
            self._save_permissions()
            self._append_permission_audit(
                plugin_id,
                plugin_name,
                PluginPermission.INSTALL_PKG,
                source="install",
                decision="deny_prompt",
                details=pkg_details,
            )
            return False

    # ------------------------------------------------------------------ #
    # 状态持久化
    # ------------------------------------------------------------------ #

    def _states_path(self) -> Path:
        """返回插件启用/禁用状态文件的路径。"""
        return Path(PLUGINS_DIR) / "._data" / "plugin_states.json"

    def _load_disabled_ids(self) -> None:
        """从磁盘加载被禁用的插件 ID 集合。"""
        path = self._states_path()
        if not path.exists():
            return
        try:
            states: dict = json.loads(path.read_text(encoding="utf-8"))
            self._disabled_ids = {pid for pid, enabled in states.items() if not enabled}
        except Exception:
            logger.exception("插件状态文件加载失败: {}", path)

    def _save_states(self) -> None:
        """将所有插件的启用/禁用状态持久化到磁盘。"""
        path = self._states_path()
        states: Dict[str, bool] = {}
        # 当前已加载插件的实际状态
        for pid, entry in self._entries.items():
            states[pid] = entry.enabled
        # 被禁用而未加载的插件（在 _disabled_ids 中但不在 _entries 中）
        for pid in self._disabled_ids:
            if pid not in states:
                states[pid] = False
        try:
            write_text_with_uac(
                path,
                json.dumps(states, ensure_ascii=False, indent=2),
                encoding="utf-8",
                ensure_parent=True,
            )
        except Exception:
            logger.exception("插件状态保存失败: {}", path)

    def is_disabled(self, plugin_id: str) -> bool:
        """返回插件是否处于禁用状态（含启动时跳过加载的插件）。"""
        entry = self._entries.get(plugin_id)
        if entry:
            return not entry.enabled
        return plugin_id in self._disabled_ids

    # ------------------------------------------------------------------ #
    # 加载
    # ------------------------------------------------------------------ #

    def _discover_plugin_paths(self) -> tuple[Dict[str, Path], Dict[str, List[str]]]:
        """扫描插件目录，返回插件路径映射和依赖图。"""
        id_to_path: Dict[str, Path] = {}
        dep_graph: Dict[str, List[str]] = {}

        base = Path(PLUGINS_DIR)
        if not base.exists():
            return id_to_path, dep_graph

        for path in sorted(base.iterdir()):
            is_pkg = path.is_dir() and (path / "__init__.py").exists()
            is_file = path.is_file() and path.suffix == ".py" and not path.name.startswith("_")
            if not (is_pkg or is_file):
                continue

            manifest = _load_manifest(path) if is_pkg else None
            plugin_id = manifest.id if manifest else path.stem
            if plugin_id in id_to_path:
                logger.error(
                    "发现重复插件 ID '{}'：{} 与 {}。后者已忽略",
                    plugin_id,
                    id_to_path[plugin_id].name,
                    path.name,
                )
                self.pluginError.emit(plugin_id, f"发现重复插件 ID：{id_to_path[plugin_id].name} / {path.name}")
                continue

            id_to_path[plugin_id] = path
            dep_graph[plugin_id] = manifest.requires if manifest else []

        return id_to_path, dep_graph

    def _plan_reload_order(self, plugin_id: str, dep_graph: Dict[str, List[str]]) -> list[str]:
        """计算单插件热重载的影响范围和重载顺序。"""
        if plugin_id not in dep_graph:
            return []

        reverse_graph: Dict[str, set[str]] = {}
        for pid, deps in dep_graph.items():
            for dep in deps:
                reverse_graph.setdefault(dep, set()).add(pid)

        affected: set[str] = {plugin_id}
        queue: deque[str] = deque([plugin_id])
        while queue:
            current = queue.popleft()
            for dependent_id in sorted(reverse_graph.get(current, set())):
                if dependent_id in self._disabled_ids or dependent_id in affected:
                    continue
                affected.add(dependent_id)
                queue.append(dependent_id)

        sub_graph = {
            pid: [dep for dep in dep_graph.get(pid, []) if dep in affected]
            for pid in affected
        }
        return [pid for pid in _topo_sort(sub_graph) if pid in affected]

    def discover_and_load(self) -> None:
        """扫描外部插件目录并尝试加载所有插件。

        加载顺序由 ``requires`` 依赖关系决定（拓扑排序）：依赖插件先于依赖方加载。
        """
        self._load_disabled_ids()
        self._disabled_metas.clear()   # 每次扫描前清空，重新收集
        self._failed_entries.clear()   # 清空失败记录，允许重新尝试加载
        base = Path(PLUGINS_DIR)
        if not base.exists():
            mkdir_with_uac(base, parents=True, exist_ok=True)
            return

        # 第一遍：收集有效插件路径，构建 id → path 映射和依赖图
        id_to_path, dep_graph = self._discover_plugin_paths()

        # 第二遍：拓扑排序，确保 requires 中声明的依赖插件先于依赖方加载
        for plugin_id in _topo_sort(dep_graph):
            path = id_to_path.get(plugin_id)
            if path is not None:
                self._load_from_path(path)

        # 分发自定义启动参数（各插件 on_load 已完成注册后调用）
        self._dispatch_startup_args()
        self.scanCompleted.emit()

    def reload_plugin(self, plugin_id: str) -> tuple[bool, str, list[str], list[str]]:
        """热重载单个插件，并联动重载依赖它的已启用插件。"""
        self._load_disabled_ids()
        if plugin_id in self._disabled_ids:
            return False, "插件已禁用，请先启用后再热重载", [], [plugin_id]

        id_to_path, dep_graph = self._discover_plugin_paths()
        if plugin_id not in id_to_path:
            return False, f"未找到插件：{plugin_id}", [], [plugin_id]

        reload_order = self._plan_reload_order(plugin_id, dep_graph)
        if not reload_order:
            reload_order = [plugin_id]

        for pid in reversed(reload_order):
            if pid in self._entries:
                self.unload(pid)
            else:
                self._failed_entries.pop(pid, None)

        reloaded_ids: list[str] = []
        failed_ids: list[str] = []
        for pid in reload_order:
            if pid in self._disabled_ids:
                continue
            self._disabled_metas.pop(pid, None)
            self._failed_entries.pop(pid, None)

            path = id_to_path.get(pid)
            if path is None:
                failed_ids.append(pid)
                continue

            self._load_from_path(path)
            entry = self._entries.get(pid)
            if entry is not None and not entry.load_failed:
                reloaded_ids.append(pid)
            else:
                failed_ids.append(pid)

        self._dispatch_startup_args()
        self.scanCompleted.emit()

        root_name = self._plugin_display_name(plugin_id)
        dependent_count = max(0, len(reloaded_ids) - (1 if plugin_id in reloaded_ids else 0))
        affected_count = max(0, len(reload_order) - 1)
        failed_names = [self._plugin_display_name(pid) for pid in failed_ids]

        if plugin_id in failed_ids:
            return False, f"「{root_name}」热重载失败，请查看日志。", reloaded_ids, failed_ids

        if failed_ids:
            detail = "、".join(failed_names)
            prefix = (
                f"「{root_name}」已热重载，并联动处理 {affected_count} 个关联插件；"
                if affected_count > 0 else
                f"「{root_name}」已热重载；"
            )
            return True, (
                f"{prefix}但以下插件未成功恢复：{detail}"
            ), reloaded_ids, failed_ids

        if dependent_count > 0:
            return True, f"「{root_name}」已热重载，并联动重载 {dependent_count} 个关联插件。", reloaded_ids, failed_ids
        return True, f"「{root_name}」已热重载。", reloaded_ids, failed_ids

    def _dispatch_startup_args(self) -> None:
        """解析 ``extra_args`` 并将自定义启动参数分发给各插件注册的处理器。

        在 :meth:`discover_and_load` 所有插件的 ``on_load`` 执行完毕后自动调用。
        仅处理 ``--extra-args`` 中由插件通过 :meth:`PluginAPI.register_startup_arg`
        注册的参数；未经注册的参数将被忽略。
        """
        pending_entries = [entry for entry in self._entries.values() if entry.api._startup_args_pending()]
        if not pending_entries:
            return

        extra_args_str = self._startup_context.get("extra_args", "").strip()
        if not extra_args_str:
            for entry in pending_entries:
                entry.api._mark_startup_args_dispatched()
            return

        # 汇总所有已加载插件注册的参数规格
        all_specs: Dict[str, tuple] = {}   # dest_name -> (spec_dict, PluginAPI, flag, plugin_id)
        flag_owner: Dict[str, str] = {}
        for entry in pending_entries:
            for name, spec in entry.api._get_startup_arg_specs().items():
                flag  = name if name.startswith("-") else f"--{name}"
                dest  = flag.lstrip("-").replace("-", "_")
                existing_owner = flag_owner.get(flag)
                if existing_owner is not None:
                    logger.warning(
                        "插件启动参数 {} 与插件 {} 冲突，插件 {} 的定义已忽略",
                        flag,
                        existing_owner,
                        entry.meta.id,
                    )
                    continue
                flag_owner[flag] = entry.meta.id
                all_specs[dest] = (spec, entry.api, flag, entry.meta.id)

        if not all_specs:
            for entry in pending_entries:
                entry.api._mark_startup_args_dispatched()
            return

        parser = argparse.ArgumentParser(add_help=False)
        for dest, (spec, _api, flag, _plugin_id) in all_specs.items():
            kwargs: Dict[str, Any] = {"dest": dest}
            action = spec.get("action", "store")
            kwargs["action"] = action
            if action == "store":
                if spec.get("nargs") is not None:
                    kwargs["nargs"] = spec["nargs"]
                if spec.get("default") is not None:
                    kwargs["default"] = spec["default"]
            if spec.get("help"):
                kwargs["help"] = spec["help"]
            try:
                parser.add_argument(flag, **kwargs)
            except Exception:
                logger.warning("插件启动参数 {} 注册到解析器失败", flag)

        try:
            tokens = shlex.split(extra_args_str)
            ns, unknown = parser.parse_known_args(tokens)
        except Exception:
            logger.warning("解析插件自定义启动参数失败: {}", extra_args_str)
            for entry in pending_entries:
                entry.api._mark_startup_args_dispatched()
            return

        if unknown:
            logger.debug("未被任何插件处理的启动参数: {}", unknown)

        for dest, (spec, api, flag, _plugin_id) in all_specs.items():
            value    = getattr(ns, dest, None)
            action   = spec.get("action", "store")
            default  = spec.get("default")
            handler  = spec["handler"]

            # 判断是否应该调用处理器
            if action == "store_true":
                should_call = (value is True)
            elif action == "store_false":
                should_call = (value is False)
            else:
                should_call = (value is not None and value != default)

            if should_call:
                try:
                    if action in ("store_true", "store_false"):
                        handler()
                    else:
                        handler(value)
                except Exception:
                    logger.exception("插件自定义启动参数 {} 处理器异常", flag)

        for entry in pending_entries:
            entry.api._mark_startup_args_dispatched()



    def load_builtin(self, plugin_cls: type[BasePlugin]) -> None:
        """直接注册内置插件类（无需文件扫描）。"""
        self._instantiate_and_register(plugin_cls)

    def _load_from_path(self, path: Path) -> None:
        is_pkg      = path.is_dir()
        entry_file  = (path / "__init__.py") if is_pkg else path

        # 读取 plugin.json（包形式才有）
        manifest: Optional[PluginMeta] = None
        if is_pkg:
            manifest = _load_manifest(path)

        # 若清单中的 ID 已被禁用，收集元数据后直接跳过（避免加载模块）
        if manifest and manifest.id in self._disabled_ids:
            self._disabled_metas[manifest.id] = manifest
            logger.debug("插件 {} 已禁用，跳过加载", manifest.id)
            return

        plugin_key = manifest.id if manifest else path.stem
        module_name = _build_plugin_module_prefix(plugin_key, path)

        # 检查并安装缺失的 Python 依赖（仅包形式插件有 requirements.txt）
        dep_warning: Optional[str] = None
        granted_permissions: list[str] = []
        if is_pkg:
            lang = I18nService.instance().language
            plugin_name = manifest.get_name(lang) if manifest else path.name
            plugin_id   = manifest.id   if manifest else path.stem

            # ── 0. 插件 ID 合法性校验（防止路径穿越及非预期字符）──
            if not _VALID_PLUGIN_ID_RE.match(plugin_id):
                logger.warning(
                    "插件 '{}' 的 ID '{}' 不符合命名规范（需以小写字母开头，仅含小写字母/数字/下划线），已跳过",
                    path.name, plugin_id,
                )
                self.pluginError.emit(
                    path.stem,
                    f"ID '{plugin_id}' 不符合命名规范",
                )
                return

            # ── 1. 系统权限审查（依据 plugin.json 中的 permissions 字段）──
            # 拒绝某项权限只会生成警告，不会阻止插件加载。
            if manifest and manifest.permissions:
                denied_perms: list[str] = []
                for perm_key in manifest.permissions:
                    if perm_key == PluginPermission.INSTALL_PKG:
                        continue  # 包安装权限在下面单独处理
                    allowed = self._check_sys_permission(
                        plugin_id,
                        plugin_name,
                        perm_key,
                        source="startup",
                    )
                    if not allowed:
                        logger.info(
                            "插件 {} 系统权限 {} 被拒绝，插件仍将加载，相关功能可能无法使用",
                            path.name, perm_key,
                        )
                        denied_perms.append(_perm_display_name(perm_key))
                    else:
                        granted_permissions.append(perm_key)
                if denied_perms:
                    perm_hint = f"以下权限被拒绝：{'、'.join(denied_perms)}，相关功能可能无法使用。"
                    dep_warning = (dep_warning + "\n" + perm_hint) if dep_warning else perm_hint

            # ── 2. 第三方库安装权限审查 ──
            missing = _collect_missing_deps(path)
            install_allowed = True
            if missing:
                if manifest is not None and PluginPermission.INSTALL_PKG not in manifest.permissions:
                    logger.warning(
                        "插件 {} 声明了依赖 {}，但未声明 install_pkg 权限，已跳过自动安装",
                        path.name,
                        missing,
                    )
                    install_allowed = False
                    dep_warning = f"检测到缺失依赖 {', '.join(missing)}，但插件未声明 install_pkg 权限，已跳过自动安装"
                else:
                    install_allowed = self._check_install_permission(plugin_id, plugin_name, missing)
                    if not install_allowed:
                        logger.info("插件 {} 依赖安装已被拒绝，继续加载但功能可能受限", path.name)
                        dep_warning = f"依赖安装被拒绝: {', '.join(missing)}，部分功能可能无法使用"
            if missing and install_allowed:
                failed_deps = _ensure_plugin_deps(path)
                if failed_deps:
                    logger.warning(
                        "插件 {} 依赖 {} 安装失败，插件可能无法正常工作",
                        path.name, failed_deps,
                    )
                    dep_warning = f"依赖安装失败: {', '.join(failed_deps)}，部分功能可能无法使用"

            # ── 3. 静态权限扫描（辅助提示、不阻断加载）──
            declared = list(manifest.permissions) if manifest else []
            undeclared = _scan_undeclared_perms(path, declared)
            if undeclared:
                self.pluginPermWarn.emit(
                    plugin_id,
                    plugin_name,
                    undeclared,
                )

        try:
            spec = importlib.util.spec_from_file_location(
                module_name,
                entry_file,
                submodule_search_locations=[str(path)] if is_pkg else None,
            )
            if spec is None or spec.loader is None:
                return
            mod = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = mod
            spec.loader.exec_module(mod)  # type: ignore[union-attr]

            plugin_cls = getattr(mod, "Plugin", None)
            if plugin_cls is None:
                logger.warning("插件 {} 未找到 Plugin 类，跳过", path.name)
                self._cleanup_plugin_modules(module_name)
                return

            # plugin.json 中的 meta 优先于代码中的 meta 属性
            if manifest is not None:
                plugin_cls.meta = manifest

            self._instantiate_and_register(
                plugin_cls,
                dep_warning=dep_warning,
                granted_permissions=granted_permissions,
                module_prefix=module_name,
                source_path=path,
            )
        except Exception:
            self._cleanup_plugin_modules(module_name)
            self.pluginError.emit(path.stem, "加载异常，查看日志")
            logger.exception("插件 {} 加载失败", path.name)

    def _instantiate_and_register(
        self,
        plugin_cls: type[BasePlugin],
        data_dir: Optional[Path] = None,
        dep_warning: Optional[str] = None,
        granted_permissions: Optional[list[str]] = None,
        module_prefix: str = "",
        source_path: Optional[Path] = None,
    ) -> None:
        plugin = plugin_cls()
        pid    = plugin.meta.id

        # 对没有清单文件的单文件插件（manifest 为 None 时）在此做禁用检查
        if pid in self._disabled_ids:
            self._disabled_metas[pid] = plugin.meta
            logger.debug("插件 {} 已禁用，跳过加载", pid)
            return

        if pid in self._entries:
            logger.debug("插件 {} 已加载，跳过", pid)
            return

        resolved_data_dir = data_dir
        if source_path is not None:
            # 统一外部插件的数据目录为 plugins_ext/._data/<plugin_id>
            data_dir_name = str(pid or "").strip().lower()
            if not _VALID_PLUGIN_ID_RE.match(data_dir_name):
                data_dir_name = re.sub(r"[^a-z0-9_]", "_", data_dir_name).strip("_") or "plugin_data"
                logger.warning(
                    "插件 {} 的 ID '{}' 不符合数据目录命名规范，已使用 '{}' 作为目录名",
                    pid,
                    plugin.meta.id,
                    data_dir_name,
                )
            resolved_data_dir = Path(PLUGINS_DIR) / "._data" / data_dir_name

        api = PluginAPI(plugin_data_dir=resolved_data_dir)
        api._set_plugin_resolver(self._resolve_plugin_export)
        api._set_identity(pid, plugin.meta.get_name(I18nService.instance().language))
        api._set_declared_permissions(list(plugin.meta.permissions))
        api._set_granted_permissions(granted_permissions or [])
        api._set_permission_requester(
            lambda perm_key, reason, plugin_id=pid: self.request_plugin_permission(
                plugin_id,
                perm_key,
                reason=reason,
            )
        )

        # 注入宿主服务与通知能力
        for svc_name, svc_obj in self._services.items():
            api._register_service(svc_name, svc_obj)
        if self._toast_cb:
            api._set_toast_callback(self._toast_cb)
        if self._automation_engine is not None:
            api._set_fire_trigger_callback(self._automation_engine.fire_plugin_trigger)

        # 注入本次启动上下文（插件可通过 api.get_startup_args() 读取）
        api._set_startup_context(self._startup_context)

        # 快照加载前的注册表，用于追踪该插件注册的小组件类型
        from app.widgets.registry import WidgetRegistry
        _reg = WidgetRegistry.instance()
        _types_before = set(_reg._registry.keys())

        entry = PluginEntry(plugin, api)
        entry.module_prefix = module_prefix
        if dep_warning:
            entry.dep_warning = dep_warning

        missing_requires = [dep for dep in plugin.meta.requires if dep not in self._entries]
        if missing_requires:
            entry.error = f"依赖插件不可用: {', '.join(missing_requires)}"
            entry.load_failed = True
            self._failed_entries[pid] = entry
            self._cleanup_plugin_modules(entry.module_prefix)
            self.pluginError.emit(pid, entry.error)
            logger.warning("插件 {} 依赖未满足，跳过加载: {}", pid, missing_requires)
            return

        try:
            plugin.on_load(_SharedAPIAdapter(api, self._shared_api))
            entry.widget_types = set(_reg._registry.keys()) - _types_before
            self._entries[pid] = entry
            for dep in plugin.meta.requires:
                dep_entry = self._entries.get(dep)
                if dep_entry is not None:
                    dep_entry.dependents.add(pid)
            self.pluginLoaded.emit(pid)
            try:
                from app.events import EventBus, EventType
                EventBus.emit(EventType.PLUGIN_LOADED,
                              plugin_id=pid, name=plugin.meta.name)
            except Exception:
                pass
            logger.success("插件 '{}' v{} 已加载", plugin.meta.name, plugin.meta.version)
        except Exception:
            entry.widget_types = set(_reg._registry.keys()) - _types_before
            self._cleanup_entry_runtime(entry, call_plugin_unload=False)
            entry.error = "on_load 异常，查看日志"
            entry.load_failed = True
            # 加载失败的插件保存到 _failed_entries，UI 中仍可显示并提示用户
            self._failed_entries[pid] = entry
            self.pluginError.emit(pid, entry.error)
            logger.exception("插件 {} on_load 异常", pid)

    # ------------------------------------------------------------------ #
    # 画布顶栏按钮聚合
    # ------------------------------------------------------------------ #

    def collect_canvas_topbar_buttons(self, zone_id: str) -> list:
        """收集所有已加载插件为指定画布注册的顶栏按钮 widget 列表。

        由 :class:`~app.views.world_time_view.FullscreenClockWindow` 在构造时调用，
        将返回的 widget 注入到顶栏"编辑布局"按钮左侧。

        Parameters
        ----------
        zone_id : str
            全屏画布窗口对应的 zone ID。

        Returns
        -------
        list[QWidget]
            各插件工厂函数返回的 widget 列表（顺序与插件加载顺序一致），
            已过滤掉返回 ``None`` 的工厂。
        """
        buttons = []
        from PySide6.QtWidgets import QWidget

        def _append_candidate(candidate: Any) -> None:
            if candidate is None:
                return
            if isinstance(candidate, (list, tuple)):
                for item in candidate:
                    _append_candidate(item)
                return
            if isinstance(candidate, QWidget):
                buttons.append(candidate)
                return
            logger.warning("插件顶栏按钮工厂返回了非 QWidget 对象，已忽略: {}", type(candidate).__name__)

        for entry in self._entries.values():
            for factory in entry.api._canvas_topbar_factories:
                try:
                    _append_candidate(factory(zone_id))
                except Exception:
                    logger.exception("插件 {} 画布顶栏按钮工厂调用异常", entry.meta.id)
        return buttons

    def collect_canvas_services(self) -> Dict[str, Any]:
        """汇总所有已加载插件注册的画布共享服务。"""
        services: Dict[str, Any] = {}
        for entry in self._entries.values():
            for name, service in entry.api.list_canvas_services().items():
                if name in services and services[name] is not service:
                    logger.warning("画布共享服务 '{}' 被后加载插件覆盖", name)
                services[name] = service
        return services

    def collect_home_card_factories(self, slot: str | None = None) -> list[dict[str, Any]]:
        """收集插件注册的首页卡片工厂。"""
        slot_filter = str(slot or "").strip().lower()
        items: list[dict[str, Any]] = []
        for entry in self._entries.values():
            for spec in entry.api.list_home_card_factories():
                current_slot = str(spec.get("slot", "recommend")).strip().lower()
                if slot_filter and current_slot != slot_filter:
                    continue
                factory = spec.get("factory")
                if not callable(factory):
                    continue
                items.append({
                    "plugin_id": entry.meta.id,
                    "plugin_name": entry.meta.get_name(I18nService.instance().language),
                    "factory": factory,
                    "slot": current_slot,
                    "order": int(spec.get("order", 100)),
                })
        items.sort(key=lambda x: (x["order"], x["plugin_id"]))
        return items

    def _resolve_plugin_export(self, plugin_id: str) -> Optional[Any]:
        """解析依赖插件的公开接口对象。"""
        entry = self._entries.get(plugin_id)
        if entry is None or entry.load_failed:
            return None
        plugin = entry.plugin
        export = getattr(plugin, "export", None)
        if callable(export):
            return export()
        return None

    def _cleanup_shared_registrations(self, api: PluginAPI) -> None:
        """从共享 API 中移除某个插件注册的钩子、触发器与动作。"""
        for hook_type, callbacks in list(api._hooks.items()):
            for callback in list(callbacks):
                self._shared_api.unregister_hook(hook_type, callback)

        for trigger_id in list(api._custom_triggers.keys()):
            self._shared_api.unregister_trigger(trigger_id)

        for action_id in list(api._custom_actions.keys()):
            self._shared_api.unregister_action(action_id)

    def _cleanup_entry_runtime(
        self,
        entry: PluginEntry,
        *,
        call_plugin_unload: bool,
    ) -> None:
        """清理插件运行时注册状态，供卸载与失败回滚复用。"""
        if call_plugin_unload and not entry.load_failed:
            try:
                entry.plugin.on_unload()
            except Exception:
                logger.exception("插件 {} on_unload 异常", entry.meta.id)

        try:
            entry.api._cleanup_event_subscriptions()
        except Exception:
            logger.exception("插件 {} 事件订阅清理异常", entry.meta.id)

        try:
            self._cleanup_shared_registrations(entry.api)
        except Exception:
            logger.exception("插件 {} 共享 API 清理异常", entry.meta.id)

        if entry.widget_types:
            try:
                from app.widgets.registry import WidgetRegistry

                reg = WidgetRegistry.instance()
                for wtype in entry.widget_types:
                    reg.unregister(wtype)
                logger.debug("已移除插件 {} 的小组件类型: {}", entry.meta.id, entry.widget_types)
            except Exception:
                logger.exception("插件 {} 小组件清理异常", entry.meta.id)

        try:
            entry.api._clear_runtime_registrations()
        except Exception:
            logger.exception("插件 {} 本地注册状态清理异常", entry.meta.id)

        try:
            self._cleanup_plugin_modules(entry.module_prefix)
        except Exception:
            logger.exception("插件 {} 模块命名空间清理异常", entry.meta.id)

    # ------------------------------------------------------------------ #
    # 卸载
    # ------------------------------------------------------------------ #

    def unload(self, plugin_id: str) -> None:
        # 优先从正常加载的 entries 中弹出，其次处理加载失败的 entries
        entry = self._entries.pop(plugin_id, None)
        if entry is None:
            self._failed_entries.pop(plugin_id, None)
            return
        for dep in entry.meta.requires:
            dep_entry = self._entries.get(dep)
            if dep_entry is not None:
                dep_entry.dependents.discard(plugin_id)
        self._cleanup_entry_runtime(entry, call_plugin_unload=not entry.load_failed)
        self.pluginUnloaded.emit(plugin_id)
        try:
            from app.events import EventBus, EventType
            name = entry.meta.name
            EventBus.emit(EventType.PLUGIN_UNLOADED, plugin_id=plugin_id, name=name)
        except Exception:
            pass

    def unload_all(self) -> None:
        for pid in list(self._entries.keys()):
            self.unload(pid)
        self._failed_entries.clear()

    # ------------------------------------------------------------------ #
    # 启用 / 禁用
    # ------------------------------------------------------------------ #

    def set_enabled(self, plugin_id: str, enabled: bool) -> None:
        """启用或禁用插件，并立即生效（禁用 → 卸载；启用 → 重新加载）。"""
        if enabled:
            # 从禁用列表移除；若之前加载失败，也清除失败记录以允许重试
            self._disabled_ids.discard(plugin_id)
            self._disabled_metas.pop(plugin_id, None)
            self._failed_entries.pop(plugin_id, None)
            self._save_states()
            self.discover_and_load()          # 幂等：已加载的跳过，新启用的被加载
        else:
            # 将插件加入禁用列表；若当前已加载则先卸载
            self._disabled_ids.add(plugin_id)
            entry = self._entries.get(plugin_id) or self._failed_entries.get(plugin_id)
            if entry:
                self._disabled_metas[plugin_id] = entry.meta
                self.unload(plugin_id)        # 发出 pluginUnloaded 信号
            # 从失败列表中也移除（避免再次出现在 UI 中）
            self._failed_entries.pop(plugin_id, None)
            self._save_states()

    def import_plugin(self, src: Path) -> tuple[bool, str]:
        """从外部路径导入插件到 plugins_ext 目录。

        Parameters
        ----------
        src : Path
            插件包文件（.ltcplugin）或插件目录的路径。

        Returns
        -------
        (success: bool, message: str)
        """
        import shutil
        import zipfile

        base = Path(PLUGINS_DIR)
        mkdir_with_uac(base, parents=True, exist_ok=True)

        src_suffix = src.suffix.lower()
        is_plugin_package = src.is_file() and src_suffix in PLUGIN_PACKAGE_FILE_EXTENSIONS

        if is_plugin_package:
            # ── 插件包文件（本质为 ZIP）────────────────────────────── #
            try:
                with zipfile.ZipFile(src) as zf:
                    # 探测顶层目录（要求 ZIP 内是单个文件夹）
                    top_dirs = {
                        p.split("/")[0]
                        for p in zf.namelist()
                        if p.strip("/")
                    }
                    # 过滤掉 __MACOSX 等系统垃圾
                    top_dirs = {d for d in top_dirs if not d.startswith("__")}

                    if len(top_dirs) == 1:
                        plugin_dir_name = top_dirs.pop()
                    else:
                        # 没有单一顶层目录：使用 ZIP 文件名
                        plugin_dir_name = src.stem

                    dest = base / plugin_dir_name
                    if dest.exists():
                        shutil.rmtree(dest)

                    # ── 路径穿越安全检查（防止恶意 ZIP 向插件目录外写文件）──
                    resolved_base = base.resolve()
                    for member_name in zf.namelist():
                        try:
                            (base / member_name).resolve().relative_to(resolved_base)
                        except ValueError:
                            return False, f"ZIP 包含危险路径条目，已拒绝导入：{member_name}"

                    zf.extractall(base)

                    # 如果解压出来原本有顶层目录且与 dest 一致则已完成；
                    # 否则将文件移动到 plugin_dir_name 目录内
                    if not dest.exists():
                        # 尝试找到实际解压目录
                        extracted = [
                            p for p in base.iterdir()
                            if p.is_dir() and p.name in top_dirs | {src.stem}
                        ]
                        if extracted:
                            extracted[0].rename(dest)

            except zipfile.BadZipFile:
                return False, "文件不是有效的插件包（应为 ZIP 内容）"
            except Exception as e:
                return False, f"解压失败: {e}"

        elif src.is_dir():
            # ── 目录形式插件 ────────────────────────────────────────── #
            dest = base / src.name
            if dest.exists():
                shutil.rmtree(dest)
            try:
                shutil.copytree(src, dest)
            except Exception as e:
                return False, f"复制失败: {e}"

        else:
            return False, (
                f"不支持的插件格式（请选择 {PLUGIN_PACKAGE_EXTENSION} 文件，或插件文件夹）"
            )

        # 验证目标目录包含 __init__.py
        dest = base / (src.stem if is_plugin_package else src.name)
        # 修正 zip 解压后的实际目录名
        if is_plugin_package:
            # 重新扫描，找到刚刚新增的目录
            after = {p.name for p in base.iterdir() if p.is_dir() and not p.name.startswith("_")}
            # dest.name 可能不对，取第一个含 plugin.json 或 __init__.py 的新目录
            for cand in base.iterdir():
                if cand.is_dir() and (cand / "__init__.py").exists():
                    dest = cand
                    break

        if not (dest / "__init__.py").exists():
            logger.warning("导入的插件 {} 缺少 __init__.py，可能无法加载", dest.name)

        logger.success("插件 '{}' 已导入到 {}", src.name, dest)
        return True, f"插件已导入：{dest.name}"

    def delete_plugin(self, plugin_id: str) -> tuple[bool, str]:
        """删除指定插件文件（目录插件或单文件插件）。"""
        target = str(plugin_id or "").strip()
        if not target:
            return False, "插件 ID 不能为空"

        id_to_path, _dep_graph = self._discover_plugin_paths()
        plugin_path = id_to_path.get(target)
        if plugin_path is None:
            return False, f"未找到插件：{target}"

        self.unload(target)
        self._failed_entries.pop(target, None)
        self._disabled_metas.pop(target, None)
        self._disabled_ids.discard(target)
        self._permissions.pop(target, None)
        self._sys_permissions.pop(target, None)

        import shutil

        try:
            if plugin_path.is_dir():
                shutil.rmtree(plugin_path)
            elif plugin_path.is_file():
                plugin_path.unlink()
            else:
                return False, f"插件路径不可用：{plugin_path}"
        except Exception as exc:
            return False, f"删除插件失败：{exc}"

        self._save_states()
        self._save_permissions()
        self._save_sys_permissions()
        return True, f"已删除插件：{target}"


# --------------------------------------------------------------------------- #
# 工具函数
# --------------------------------------------------------------------------- #

def _load_manifest(plugin_dir: Path) -> Optional[PluginMeta]:
    """从 plugin_dir/plugin.json 加载插件清单，失败返回 None。"""
    manifest_path = plugin_dir / "plugin.json"
    if not manifest_path.exists():
        return None
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        has_name = ("name" in data) or ("name_i18n" in data)
        if "id" not in data or not has_name:
            logger.warning("plugin.json 缺少必填字段 id/name(name_i18n): {}", manifest_path)
            return None
        return _normalize_manifest(PluginMeta.from_dict(data), manifest_path)
    except Exception:
        logger.exception("plugin.json 解析失败: {}", manifest_path)
        return None


def _topo_sort(dep_graph: Dict[str, List[str]]) -> List[str]:
    """对插件 ID 进行拓扑排序，返回加载顺序。

    Parameters
    ----------
    dep_graph : dict
        ``{plugin_id: [required_plugin_id, ...]}`` 拓扑图。

    Returns
    -------
    list[str]
        排序后的插件 ID 列表（依赖虽先）。
        循环依赖时会记录警告并尝试继续。
    """
    # Kahn 算法（BFS 拓扑排序）
    in_degree: Dict[str, int]       = {pid: 0 for pid in dep_graph}
    adj:       Dict[str, List[str]] = {pid: [] for pid in dep_graph}

    for pid, deps in dep_graph.items():
        for dep in deps:
            if dep not in dep_graph:
                # 依赖了一个不在扫描列表中的插件，后续加载时会实际报错
                logger.warning("插件 {} 声明依赖 '{}'，但该依赖未安装", pid, dep)
                continue
            adj[dep].append(pid)
            in_degree[pid] += 1

    queue = [pid for pid, deg in in_degree.items() if deg == 0]
    queue.sort()  # 确保相同入度的节点按字母顺序排列
    result: List[str] = []

    while queue:
        node = queue.pop(0)
        result.append(node)
        for neighbor in sorted(adj.get(node, [])):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if len(result) != len(dep_graph):
        remaining = set(dep_graph) - set(result)
        logger.warning("插件依赖存在循环，受影响的插件: {}，将按原始顺序加载", remaining)
        result.extend(sorted(remaining))

    return result


class _SharedAPIAdapter(PluginAPI):
    """透传适配器：让插件通过自己的局部 API 对象注册，
    但触发器/动作同步写入全局 shared_api。
    """

    def __init__(self, local_api: PluginAPI, shared_api: PluginAPI):
        # 不调用 super().__init__()，直接复用 local_api 的状态
        self.__dict__ = local_api.__dict__
        self._local   = local_api
        self._shared  = shared_api

    def register_hook(self, hook_type, callback):
        self._local.register_hook(hook_type, callback)
        self._shared.register_hook(hook_type, callback)

    def unregister_hook(self, hook_type, callback):
        self._local.unregister_hook(hook_type, callback)
        self._shared.unregister_hook(hook_type, callback)

    def register_trigger(
        self,
        trigger_id: str,
        handler=None,
        *,
        name: str = "",
        description: str = "",
        name_i18n: dict[str, str] | None = None,
        description_i18n: dict[str, str] | None = None,
    ):
        if (
            trigger_id not in self._local._custom_triggers
            and trigger_id in self._shared._custom_triggers
        ):
            logger.warning("共享触发器 ID '{}' 已存在，后续插件注册已忽略", trigger_id)
            return
        self._local.register_trigger(
            trigger_id,
            handler,
            name=name,
            description=description,
            name_i18n=name_i18n,
            description_i18n=description_i18n,
        )
        self._shared.register_trigger(
            trigger_id,
            handler,
            name=name,
            description=description,
            name_i18n=name_i18n,
            description_i18n=description_i18n,
        )

    def register_action(self, action_id: str, executor):
        if (
            action_id not in self._local._custom_actions
            and action_id in self._shared._custom_actions
        ):
            logger.warning("共享动作 ID '{}' 已存在，后续插件注册已忽略", action_id)
            return
        self._local.register_action(action_id, executor)
        self._shared.register_action(action_id, executor)

    def unregister_trigger(self, trigger_id: str):
        self._local.unregister_trigger(trigger_id)
        self._shared.unregister_trigger(trigger_id)

    def unregister_action(self, action_id: str):
        self._local.unregister_action(action_id)
        self._shared.unregister_action(action_id)


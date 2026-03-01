"""插件管理器 — 负责发现、加载、卸载插件"""
from __future__ import annotations

import argparse
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

from .base_plugin import BasePlugin, LibraryPlugin, PluginAPI, PluginMeta, PluginPermission, PluginType
from app.constants import PLUGINS_DIR
from app.services.i18n_service import I18nService
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


def _perm_display_name(perm_key: str) -> str:
    i18n_key = f"perm.{perm_key}"
    return I18nService.instance().t(i18n_key, default=PERMISSION_NAMES.get(perm_key, perm_key))


# ── 插件本地 site-packages 目录（打包后依赖装在这里）─────────────────── #
_PLUGIN_LIB_DIR = Path(PLUGINS_DIR) / "_lib"

# ── 插件 ID 合法性校验（防路径穿越及注入）──────────────────────────── #
# 规则：以小写字母开头，仅含小写字母 / 数字 / 下划线，最多 64 个字符
_VALID_PLUGIN_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
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


def _scan_undeclared_perms(
    plugin_path: Path,
    declared: list[str],
) -> list[str]:
    """\u626b\u63cf\u63d2\u4ef6\u76ee\u5f55\u4e2d\u6240\u6709 .py \u6587\u4ef6\uff0c\u8fd4\u56de\u4ee3\u7801\u4e2d\u4f7f\u7528\u4e86\u4f46\u672a\u5728 permissions \u4e2d\u58f0\u660e\u7684\u6743\u9650\u952e\u5217\u8868\u3002

    \u626b\u63cf\u4ec5\u662f\u8f85\u52a9\u63d0\u793a\uff0c\u7ed3\u679c\u5305\u542b\u8bef\u62a5/\u6f0f\u62a5\uff0c\u4e0d\u80fd\u4fdd\u8bc1\u5b89\u5168\u3002
    """
    if not plugin_path.is_dir():
        return []

    # \u62fc\u63a5\u6240\u6709 .py \u6e90\u7801\uff08\u8df3\u8fc7 _lib/ \u76ee\u5f55\uff09
    combined = []
    for py_file in plugin_path.rglob("*.py"):
        if "_lib" in py_file.parts:
            continue
        try:
            combined.append(py_file.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            pass
    source = "\n".join(combined)

    undeclared: list[str] = []
    for perm_key, patterns in _PERM_SCAN_PATTERNS.items():
        if perm_key in declared:
            continue
        if any(re.search(p, source) for p in patterns):
            undeclared.append(perm_key)

    return undeclared

def _normalize_pkg_name(name: str) -> str:
    """将包名规范化为可用于 import 的形式（连字符→下划线，取主包名）。"""
    return name.replace("-", "_").split("[")[0].strip()


def _pkg_importable(pkg: str) -> bool:
    """返回包是否已可 import（检查 importlib.metadata 或直接 import）。"""
    normalized = _normalize_pkg_name(pkg)
    # 先查 metadata（更准确，能识别已安装但尚未 import 的包）
    try:
        importlib.metadata.version(pkg.split("[")[0].strip())
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
                deps.append(line)
    else:
        json_file = plugin_path / "plugin.json"
        if json_file.exists():
            try:
                meta = json.loads(json_file.read_text(encoding="utf-8"))
                deps = meta.get("dependencies", [])
            except Exception:
                pass
    return deps


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
    _PLUGIN_LIB_DIR.mkdir(parents=True, exist_ok=True)

    failed: list[str] = []
    for pkg in missing:
        if getattr(sys, "frozen", False):
            # 打包后 sys.executable 是 app 本身的 .exe，一旦用 subprocess 调用
            # 会重新启动程序实例，导致无限窗口；改用 pip 内部 API 在当前进程内安装
            try:
                from pip._internal.cli.main import main as _pip_main  # type: ignore[import]
                rc = _pip_main([
                    "install",
                    "--isolated",
                    "--disable-pip-version-check",
                    "--quiet",
                    "--target", str(_PLUGIN_LIB_DIR),
                    pkg,
                ])
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
                    [
                        sys.executable, "-m", "pip", "install",
                        "--isolated",
                        "--disable-pip-version-check",
                        "--quiet",
                        "--target", str(_PLUGIN_LIB_DIR),
                        pkg,
                    ],
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
            Callable[[str, str, str, str], PermissionLevel]
        ] = None
        self._automation_engine = None   # 由外部调用 set_automation_engine 注入
        self._startup_context: Dict[str, Any] = {
            "hidden_mode": False,
            "extra_args":  "",
        }
        self._load_permissions()

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
        callback: Callable[[str, str, str, str], PermissionLevel],
    ) -> None:
        """设置系统权限询问回调。

        ``callback(plugin_id, plugin_name, perm_key, perm_display) -> PermissionLevel``
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

    def _save_permissions(self) -> None:
        path = self._permissions_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.write_text(
                json.dumps(
                    {pid: lvl.value for pid, lvl in self._permissions.items()},
                    ensure_ascii=False, indent=2,
                ),
                encoding="utf-8",
            )
        except Exception:
            logger.exception("插件权限保存失败: {}", path)

    def _save_sys_permissions(self) -> None:
        sys_path = self._sys_permissions_path()
        sys_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            sys_path.write_text(
                json.dumps(
                    {
                        pid: {k: lvl.value for k, lvl in perms.items()}
                        for pid, perms in self._sys_permissions.items()
                    },
                    ensure_ascii=False, indent=2,
                ),
                encoding="utf-8",
            )
        except Exception:
            logger.exception("插件系统权限保存失败: {}", sys_path)

    def get_permission(self, plugin_id: str) -> Optional[PermissionLevel]:
        """返回已持久化的包安装权限，未设置时返回 None。"""
        return self._permissions.get(plugin_id)

    def get_sys_permissions(self, plugin_id: str) -> Dict[str, PermissionLevel]:
        """返回插件的所有已持久化系统权限。"""
        return dict(self._sys_permissions.get(plugin_id, {}))

    def set_sys_permission(
        self, plugin_id: str, perm_key: str, level: PermissionLevel
    ) -> None:
        """手动设置并保存某系统权限。"""
        if plugin_id not in self._sys_permissions:
            self._sys_permissions[plugin_id] = {}
        if level == PermissionLevel.ASK_EACH_TIME:
            self._sys_permissions[plugin_id].pop(perm_key, None)
        else:
            self._sys_permissions[plugin_id][perm_key] = level
        self._save_sys_permissions()

    def set_permission(self, plugin_id: str, level: PermissionLevel) -> None:
        """手动设置并保存包安装权限（由界面调用）。"""
        if level == PermissionLevel.ASK_EACH_TIME:
            self._permissions.pop(plugin_id, None)
        else:
            self._permissions[plugin_id] = level
        self._save_permissions()

    def _check_sys_permission(
        self,
        plugin_id: str,
        plugin_name: str,
        perm_key: str,
    ) -> bool:
        """检查插件是否已获得指定系统权限，返回 True 表示本次允许。

        若权限已保存（ALWAYS_ALLOW/DENY）则直接返回；
        否则调用回调向用户询问。
        """
        saved = self._sys_permissions.get(plugin_id, {}).get(perm_key)
        if saved == PermissionLevel.ALWAYS_ALLOW:
            return True
        if saved == PermissionLevel.DENY:
            logger.info("插件 {} 系统权限 {} 已被拒绝", plugin_id, perm_key)
            return False

        perm_display = _perm_display_name(perm_key)

        if self._sys_perm_callback is None:
            logger.warning(
                "插件 {} 需要系统权限 {} 但未设置回调，将直接允许",
                plugin_id, perm_key,
            )
            return True

        self.aboutToShowPermDialog.emit()
        level = self._sys_perm_callback(plugin_id, plugin_name, perm_key, perm_display)
        if plugin_id not in self._sys_permissions:
            self._sys_permissions[plugin_id] = {}
        if level == PermissionLevel.ALWAYS_ALLOW:
            self._sys_permissions[plugin_id][perm_key] = PermissionLevel.ALWAYS_ALLOW
            self._save_sys_permissions()
            return True
        elif level == PermissionLevel.ASK_EACH_TIME:
            return True
        else:  # DENY
            self._sys_permissions[plugin_id][perm_key] = PermissionLevel.DENY
            self._save_sys_permissions()
            return False

    def _check_install_permission(
        self,
        plugin_id: str,
        plugin_name: str,
        packages: list[str],
    ) -> bool:
        """检查是否允许安装 packages，返回 True 表示允许本次安装。"""
        saved = self._permissions.get(plugin_id)
        if saved == PermissionLevel.ALWAYS_ALLOW:
            return True
        if saved == PermissionLevel.DENY:
            logger.info("插件 {} 安装库已被拒绝（已保存权限）", plugin_id)
            return False

        # 需要询问用户
        if self._permission_callback is None:
            # 无回调时默认允许（兼容无 UI 的情景）
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
            return True
        elif level == PermissionLevel.ASK_EACH_TIME:
            # 本次允许，不保存
            return True
        else:  # DENY
            self._permissions[plugin_id] = PermissionLevel.DENY
            self._save_permissions()
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
        path.parent.mkdir(parents=True, exist_ok=True)
        states: Dict[str, bool] = {}
        # 当前已加载插件的实际状态
        for pid, entry in self._entries.items():
            states[pid] = entry.enabled
        # 被禁用而未加载的插件（在 _disabled_ids 中但不在 _entries 中）
        for pid in self._disabled_ids:
            if pid not in states:
                states[pid] = False
        try:
            path.write_text(
                json.dumps(states, ensure_ascii=False, indent=2),
                encoding="utf-8",
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

    def discover_and_load(self) -> None:
        """扫描外部插件目录并尝试加载所有插件。

        加载顺序由 ``requires`` 依赖关系决定（拓扑排序）：依赖插件先于依赖方加载。
        """
        self._load_disabled_ids()
        self._disabled_metas.clear()   # 每次扫描前清空，重新收集
        self._failed_entries.clear()   # 清空失败记录，允许重新尝试加载
        base = Path(PLUGINS_DIR)
        if not base.exists():
            base.mkdir(parents=True, exist_ok=True)
            return

        # 第一遍：收集有效插件路径，构建 id → path 映射和依赖图
        id_to_path: Dict[str, Path] = {}
        dep_graph: Dict[str, List[str]] = {}
        for path in sorted(base.iterdir()):
            is_pkg  = path.is_dir() and (path / "__init__.py").exists()
            is_file = path.is_file() and path.suffix == ".py" and not path.name.startswith("_")
            if not (is_pkg or is_file):
                continue
            manifest  = _load_manifest(path) if is_pkg else None
            plugin_id = manifest.id if manifest else path.stem
            id_to_path[plugin_id] = path
            dep_graph[plugin_id]  = manifest.requires if manifest else []

        # 第二遍：拓扑排序，确保 requires 中声明的依赖插件先于依赖方加载
        for plugin_id in _topo_sort(dep_graph):
            path = id_to_path.get(plugin_id)
            if path is not None:
                self._load_from_path(path)

        # 分发自定义启动参数（各插件 on_load 已完成注册后调用）
        self._dispatch_startup_args()
        self.scanCompleted.emit()

    def _dispatch_startup_args(self) -> None:
        """解析 ``extra_args`` 并将自定义启动参数分发给各插件注册的处理器。

        在 :meth:`discover_and_load` 所有插件的 ``on_load`` 执行完毕后自动调用。
        仅处理 ``--extra-args`` 中由插件通过 :meth:`PluginAPI.register_startup_arg`
        注册的参数；未经注册的参数将被忽略。
        """
        extra_args_str = self._startup_context.get("extra_args", "").strip()
        if not extra_args_str:
            return

        # 汇总所有已加载插件注册的参数规格
        all_specs: Dict[str, tuple] = {}   # dest_name -> (spec_dict, PluginAPI)
        for entry in self._entries.values():
            for name, spec in entry.api._get_startup_arg_specs().items():
                flag  = name if name.startswith("-") else f"--{name}"
                dest  = flag.lstrip("-").replace("-", "_")
                all_specs[dest] = (spec, entry.api, flag)

        if not all_specs:
            return

        parser = argparse.ArgumentParser(add_help=False)
        for dest, (spec, _api, flag) in all_specs.items():
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
            return

        if unknown:
            logger.debug("未被任何插件处理的启动参数: {}", unknown)

        for dest, (spec, api, flag) in all_specs.items():
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



    def load_builtin(self, plugin_cls: type[BasePlugin]) -> None:
        """直接注册内置插件类（无需文件扫描）。"""
        self._instantiate_and_register(plugin_cls)

    def _load_from_path(self, path: Path) -> None:
        module_name = f"_plugin_{path.stem}"
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

        # 检查并安装缺失的 Python 依赖（仅包形式插件有 requirements.txt）
        dep_warning: Optional[str] = None
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
                    allowed = self._check_sys_permission(plugin_id, plugin_name, perm_key)
                    if not allowed:
                        logger.info(
                            "插件 {} 系统权限 {} 被拒绝，插件仍将加载，相关功能可能无法使用",
                            path.name, perm_key,
                        )
                        denied_perms.append(_perm_display_name(perm_key))
                if denied_perms:
                    perm_hint = f"以下权限被拒绝：{'、'.join(denied_perms)}，相关功能可能无法使用。"
                    dep_warning = (dep_warning + "\n" + perm_hint) if dep_warning else perm_hint

            # ── 2. 第三方库安装权限审查 ──
            missing = _collect_missing_deps(path)
            if missing:
                allowed = self._check_install_permission(plugin_id, plugin_name, missing)
                if not allowed:
                    logger.info("插件 {} 依赖安装已被拒绝，继续加载但功能可能受限", path.name)
                    dep_warning = f"依赖安装被拒绝: {', '.join(missing)}，部分功能可能无法使用"
            if not dep_warning:
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
            spec = importlib.util.spec_from_file_location(module_name, entry_file)
            if spec is None or spec.loader is None:
                return
            mod = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = mod
            spec.loader.exec_module(mod)  # type: ignore[union-attr]

            plugin_cls = getattr(mod, "Plugin", None)
            if plugin_cls is None:
                logger.warning("插件 {} 未找到 Plugin 类，跳过", path.name)
                return

            # plugin.json 中的 meta 优先于代码中的 meta 属性
            if manifest is not None:
                plugin_cls.meta = manifest

            # 每个包插件拥有独立的数据目录（单文件插件使用 plugins_ext/._data/<stem>）
            data_dir: Path
            if is_pkg:
                data_dir = path
            else:
                data_dir = Path(PLUGINS_DIR) / "._data" / path.stem

            self._instantiate_and_register(plugin_cls, data_dir=data_dir, dep_warning=dep_warning)
        except Exception:
            self.pluginError.emit(path.stem, "加载异常，查看日志")
            logger.exception("插件 {} 加载失败", path.name)

    def _instantiate_and_register(
        self,
        plugin_cls: type[BasePlugin],
        data_dir: Optional[Path] = None,
        dep_warning: Optional[str] = None,
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

        api = PluginAPI(plugin_data_dir=data_dir)

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
        if dep_warning:
            entry.dep_warning = dep_warning
        try:
            plugin.on_load(_SharedAPIAdapter(api, self._shared_api))
            entry.widget_types = set(_reg._registry.keys()) - _types_before
            self._entries[pid] = entry
            self.pluginLoaded.emit(pid)
            try:
                from app.events import EventBus, EventType
                EventBus.emit(EventType.PLUGIN_LOADED,
                              plugin_id=pid, name=plugin.meta.name)
            except Exception:
                pass
            logger.success("插件 '{}' v{} 已加载", plugin.meta.name, plugin.meta.version)
        except Exception:
            entry.error = "on_load 异常，查看日志"
            entry.load_failed = True
            # 加载失败的插件保存到 _failed_entries，UI 中仍可显示并提示用户
            self._failed_entries[pid] = entry
            self.pluginError.emit(pid, entry.error)
            logger.exception("插件 {} on_load 异常", pid)

    # ------------------------------------------------------------------ #
    # 卸载
    # ------------------------------------------------------------------ #

    def unload(self, plugin_id: str) -> None:
        # 优先从正常加载的 entries 中弹出，其次处理加载失败的 entries
        entry = self._entries.pop(plugin_id, None)
        if entry is None:
            self._failed_entries.pop(plugin_id, None)
            return
        if not entry.load_failed:
            try:
                entry.plugin.on_unload()
            except Exception:
                logger.exception("插件 {} on_unload 异常", plugin_id)
        # 自动取消该插件通过 api.subscribe_event 注册的所有事件订阅
        try:
            entry.api._cleanup_event_subscriptions()
        except Exception:
            logger.exception("插件 {} 事件订阅清理异常", plugin_id)
        # 从注册表中移除该插件注册的小组件类型
        if entry.widget_types:
            from app.widgets.registry import WidgetRegistry
            reg = WidgetRegistry.instance()
            for wtype in entry.widget_types:
                reg.unregister(wtype)
            logger.debug("已移除插件 {} 的小组件类型: {}", plugin_id, entry.widget_types)
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
            ZIP 文件（插件包）或插件目录的路径。

        Returns
        -------
        (success: bool, message: str)
        """
        import shutil
        import zipfile

        base = Path(PLUGINS_DIR)
        base.mkdir(parents=True, exist_ok=True)

        if src.is_file() and src.suffix.lower() == ".zip":
            # ── ZIP 插件包 ──────────────────────────────────────────── #
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
                return False, "文件不是有效的 ZIP 插件包"
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
            return False, "不支持的插件格式（请选择 .zip 文件或插件文件夹）"

        # 验证目标目录包含 __init__.py
        dest = base / (src.stem if src.suffix.lower() == ".zip" else src.name)
        # 修正 zip 解压后的实际目录名
        if src.suffix.lower() == ".zip":
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
        return PluginMeta.from_dict(data)
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
        self._local.register_action(action_id, executor)
        self._shared.register_action(action_id, executor)


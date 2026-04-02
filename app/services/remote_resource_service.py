"""远程资源服务：插件商店与公告。"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
import platform
import re
import time
from typing import Any, Callable
from urllib.parse import urljoin, urlparse

import requests
from requests.adapters import HTTPAdapter, Retry
from PySide6.QtCore import QObject, QThread, Signal, Slot

from app.constants import CONFIG_DIR, PLUGINS_DIR, USER_AGENT
from app.services.i18n_service import I18nService
from app.utils.fs import mkdir_with_uac, write_bytes_with_uac
from app.utils.logger import logger
from app.utils.time_utils import load_json, save_json


_API_BASE_URL = "https://clock.api.zsxiaoshu.cn/"
_STATE_PATH = Path(CONFIG_DIR) / "remote_resource_state.json"
_SUPPORTED_STORE_FILE_EXTS = {".py"}
_ANNOUNCEMENT_LEVEL_PRIORITY = {
    "error": 0,
    "warning": 1,
    "info": 2,
}
_REQUEST_TIMEOUT = (8, 20)
_REQUEST_MAX_ATTEMPTS = 3
_REQUEST_RETRY_BACKOFF_BASE_SEC = 0.8
_REQUEST_RETRY_STATUS = (429, 500, 502, 503, 504)
_STORE_DETAIL_MAX_WORKERS = 8


class RemoteResourceRequestError(RuntimeError):
    """远程资源请求失败（已重试）。"""


class _TaskWorker(QObject):
    """在独立线程中执行同步任务。"""

    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, task: Callable[[], object]):
        super().__init__()
        self._task = task

    @Slot()
    def run(self) -> None:
        try:
            result = self._task()
        except Exception as exc:
            if isinstance(exc, RemoteResourceRequestError):
                logger.warning("远程资源任务执行失败: {}", exc)
            else:
                logger.exception("远程资源任务执行失败")
            self.failed.emit(str(exc) or exc.__class__.__name__)
        else:
            self.finished.emit(result)


@dataclass(slots=True)
class StorePlugin:
    """插件商店中的插件元数据。"""

    id: str
    file: str = ""
    name: Any = ""
    description: Any = ""
    version: str = ""
    author: str = ""
    icon: str = ""
    download_url: str = ""
    homepage: str = ""
    tags: list[str] = field(default_factory=list)
    supported_os: list[str] = field(default_factory=list)
    updated_at: str = ""
    min_app_version: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StorePlugin":
        return cls(
            id=str(data.get("id", "")).strip(),
            file=str(data.get("file", "")).strip(),
            name=data.get("name", ""),
            description=data.get("description", ""),
            version=str(data.get("version", "")).strip(),
            author=str(data.get("author", "")).strip(),
            icon=str(data.get("icon", "")).strip(),
            download_url=str(data.get("download_url", "")).strip(),
            homepage=str(data.get("homepage", "")).strip(),
            tags=_string_list(data.get("tags", [])),
            supported_os=[item.lower() for item in _string_list(data.get("supported_os", []))],
            updated_at=str(data.get("updated_at", "")).strip(),
            min_app_version=str(data.get("min_app_version", "")).strip(),
        )

    @property
    def stable_id(self) -> str:
        return self.id.strip()

    def display_name(self, language: str | None = None) -> str:
        return _resolve_text(self.name, language=language, default=self.id)

    def display_description(self, language: str | None = None) -> str:
        return _resolve_text(self.description, language=language, default="")


@dataclass(slots=True)
class Announcement:
    """公告元数据。"""

    uuid: str
    id: str = ""
    title: Any = ""
    content: Any = ""
    date: str = ""
    level: str = "info"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Announcement":
        level = str(data.get("level", "info")).strip().lower() or "info"
        if level not in _ANNOUNCEMENT_LEVEL_PRIORITY:
            level = "info"
        return cls(
            uuid=str(data.get("uuid", "")).strip(),
            id=str(data.get("id", "")).strip(),
            title=data.get("title", ""),
            content=data.get("content", ""),
            date=str(data.get("date", "")).strip(),
            level=level,
        )

    @property
    def stable_id(self) -> str:
        return self.uuid or self.id

    def display_title(self, language: str | None = None) -> str:
        return _resolve_text(self.title, language=language, default=self.stable_id or "公告")

    def display_content(self, language: str | None = None) -> str:
        return _resolve_text(self.content, language=language, default="")


class RemoteResourceService(QObject):
    """负责拉取插件商店和公告数据。"""

    storePluginsUpdated = Signal(object)
    storePluginsFailed = Signal(str)
    storeLoadingChanged = Signal(bool)
    storePluginInstalled = Signal(str, bool, str)

    announcementsUpdated = Signal(object)
    announcementsFailed = Signal(str)
    announcementsLoadingChanged = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._store_plugins: list[StorePlugin] = []
        self._announcements: list[Announcement] = []

        self._store_thread: QThread | None = None
        self._store_worker: _TaskWorker | None = None
        self._announcement_thread: QThread | None = None
        self._announcement_worker: _TaskWorker | None = None
        self._install_threads: dict[str, tuple[QThread, _TaskWorker]] = {}

        self._muted_popup_ids: set[str] = set()
        self._load_state()

    @property
    def store_plugins(self) -> list[StorePlugin]:
        return list(self._store_plugins)

    @property
    def announcements(self) -> list[Announcement]:
        return list(self._announcements)

    def get_store_plugin(self, plugin_id: str) -> StorePlugin | None:
        target = str(plugin_id).strip()
        if not target:
            return None
        normalized = normalize_plugin_lookup_key(target)
        for plugin in self._store_plugins:
            if plugin.stable_id == target:
                return plugin
        for plugin in self._store_plugins:
            if normalize_plugin_lookup_key(plugin.stable_id) == normalized:
                return plugin
        return None

    def is_announcement_popup_muted(self, announcement_id: str) -> bool:
        return str(announcement_id).strip() in self._muted_popup_ids

    def mute_announcement_popup(self, announcement_id: str) -> None:
        key = str(announcement_id).strip()
        if not key:
            return
        if key in self._muted_popup_ids:
            return
        self._muted_popup_ids.add(key)
        self._save_state()

    def refresh_store_plugins(self) -> bool:
        if self._store_thread is not None:
            return False

        self.storeLoadingChanged.emit(True)
        self._store_thread = QThread(self)
        self._store_worker = _TaskWorker(self._fetch_store_plugins_sync)
        self._store_worker.moveToThread(self._store_thread)
        self._store_thread.started.connect(self._store_worker.run)
        self._store_worker.finished.connect(self._on_store_plugins_fetched)
        self._store_worker.failed.connect(self._on_store_plugins_failed)
        self._store_worker.finished.connect(self._store_thread.quit)
        self._store_worker.failed.connect(self._store_thread.quit)
        self._store_thread.finished.connect(self._cleanup_store_task)
        self._store_thread.start()
        return True

    def refresh_announcements(self) -> bool:
        if self._announcement_thread is not None:
            return False

        self.announcementsLoadingChanged.emit(True)
        self._announcement_thread = QThread(self)
        self._announcement_worker = _TaskWorker(self._fetch_announcements_sync)
        self._announcement_worker.moveToThread(self._announcement_thread)
        self._announcement_thread.started.connect(self._announcement_worker.run)
        self._announcement_worker.finished.connect(self._on_announcements_fetched)
        self._announcement_worker.failed.connect(self._on_announcements_failed)
        self._announcement_worker.finished.connect(self._announcement_thread.quit)
        self._announcement_worker.failed.connect(self._announcement_thread.quit)
        self._announcement_thread.finished.connect(self._cleanup_announcement_task)
        self._announcement_thread.start()
        return True

    def install_store_plugin(self, plugin_id: str) -> bool:
        plugin = self.get_store_plugin(plugin_id)
        if plugin is None:
            self.storePluginInstalled.emit(plugin_id, False, "未找到对应的商店插件")
            return False
        if plugin.stable_id in self._install_threads:
            return False

        thread = QThread(self)
        worker = _TaskWorker(lambda pid=plugin.stable_id: self._install_store_plugin_sync(pid))
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(lambda message, pid=plugin.stable_id: self._on_store_plugin_installed(pid, True, str(message)))
        worker.failed.connect(lambda error, pid=plugin.stable_id: self._on_store_plugin_installed(pid, False, error))
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(lambda pid=plugin.stable_id: self._cleanup_install_task(pid))

        self._install_threads[plugin.stable_id] = (thread, worker)
        thread.start()
        return True

    @Slot(object)
    def _on_store_plugins_fetched(self, plugins: object) -> None:
        self._store_plugins = list(plugins) if isinstance(plugins, list) else []
        self.storePluginsUpdated.emit(list(self._store_plugins))

    @Slot(str)
    def _on_store_plugins_failed(self, error: str) -> None:
        self.storePluginsFailed.emit(error)

    @Slot(object)
    def _on_announcements_fetched(self, announcements: object) -> None:
        self._announcements = list(announcements) if isinstance(announcements, list) else []
        self.announcementsUpdated.emit(list(self._announcements))

    @Slot(str)
    def _on_announcements_failed(self, error: str) -> None:
        self.announcementsFailed.emit(error)

    def _on_store_plugin_installed(self, plugin_id: str, ok: bool, message: str) -> None:
        self.storePluginInstalled.emit(plugin_id, ok, message)

    def _cleanup_store_task(self) -> None:
        if self._store_worker is not None:
            self._store_worker.deleteLater()
            self._store_worker = None
        if self._store_thread is not None:
            if not self._store_thread.isRunning():
                self._store_thread.deleteLater()
            self._store_thread = None
        self.storeLoadingChanged.emit(False)

    def _cleanup_announcement_task(self) -> None:
        if self._announcement_worker is not None:
            self._announcement_worker.deleteLater()
            self._announcement_worker = None
        if self._announcement_thread is not None:
            if not self._announcement_thread.isRunning():
                self._announcement_thread.deleteLater()
            self._announcement_thread = None
        self.announcementsLoadingChanged.emit(False)

    def _cleanup_install_task(self, plugin_id: str) -> None:
        thread, worker = self._install_threads.pop(plugin_id, (None, None))
        if worker is not None:
            worker.deleteLater()
        if thread is not None:
            if not thread.isRunning():
                thread.deleteLater()

    def _stop_thread(self, thread: QThread | None, *, timeout_ms: int, label: str) -> None:
        if thread is None:
            return
        if thread.isRunning():
            thread.quit()
            if not thread.wait(timeout_ms):
                logger.warning("远程资源线程退出超时，已强制终止: {}", label)
                thread.terminate()
                if not thread.wait(5000):
                    logger.error("远程资源线程强制终止后仍未退出: {}", label)

    def shutdown(self, *, timeout_ms: int = 1800) -> None:
        """停止远程资源后台线程，供应用退出前调用。"""
        self._stop_thread(self._store_thread, timeout_ms=timeout_ms, label="store")
        self._stop_thread(self._announcement_thread, timeout_ms=timeout_ms, label="announcement")

        for plugin_id, (thread, _worker) in list(self._install_threads.items()):
            self._stop_thread(thread, timeout_ms=timeout_ms, label=f"install:{plugin_id}")

        # 统一走清理逻辑，避免悬空 QObject 引用。
        self._cleanup_store_task()
        self._cleanup_announcement_task()
        for plugin_id in list(self._install_threads.keys()):
            self._cleanup_install_task(plugin_id)

    def _fetch_store_plugins_sync(self) -> list[StorePlugin]:
        payload = self._get_json("plugins/index.json")
        raw_plugins = payload.get("plugins", [])
        if not isinstance(raw_plugins, list):
            raise ValueError("插件商店列表格式无效")

        detail_specs: list[tuple[str, str]] = []
        for item in raw_plugins:
            if not isinstance(item, dict):
                continue
            file_name = str(item.get("file", "")).strip()
            plugin_id = str(item.get("id", "")).strip()
            if not file_name:
                if not plugin_id:
                    continue
                file_name = f"{plugin_id}.json"
            detail_specs.append((file_name, plugin_id))

        plugins: list[StorePlugin] = []
        if detail_specs:
            max_workers = min(_STORE_DETAIL_MAX_WORKERS, len(detail_specs))
            if max_workers <= 1:
                for file_name, plugin_id in detail_specs:
                    plugin = self._fetch_store_plugin_detail(file_name, plugin_id)
                    if plugin is not None:
                        plugins.append(plugin)
            else:
                with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="store-detail") as executor:
                    futures = {
                        executor.submit(self._fetch_store_plugin_detail, file_name, plugin_id): (file_name, plugin_id)
                        for file_name, plugin_id in detail_specs
                    }
                    for future in as_completed(futures):
                        file_name, _plugin_id = futures[future]
                        try:
                            plugin = future.result()
                        except Exception:
                            logger.exception("并行拉取插件详情异常，已跳过: file={}", file_name)
                            continue
                        if plugin is not None:
                            plugins.append(plugin)

        deduped: dict[str, StorePlugin] = {}
        for plugin in plugins:
            deduped[plugin.stable_id] = plugin
        result = sorted(
            deduped.values(),
            key=lambda item: (-_date_key(item.updated_at), item.display_name().lower()),
        )
        logger.info("插件商店数据已刷新，共 {} 个插件", len(result))
        return result

    def _fetch_store_plugin_detail(self, file_name: str, plugin_id: str) -> StorePlugin | None:
        """拉取单个插件详情，失败时返回 None。"""
        try:
            detail_data = self._get_json(f"plugins/{file_name}")
        except RemoteResourceRequestError as exc:
            logger.warning("拉取插件详情失败，已跳过: file={}, error={}", file_name, exc)
            return None

        if not isinstance(detail_data, dict):
            return None
        if plugin_id and not detail_data.get("id"):
            detail_data["id"] = plugin_id
        if file_name and not detail_data.get("file"):
            detail_data["file"] = file_name

        plugin = StorePlugin.from_dict(detail_data)
        if not plugin.stable_id:
            return None
        return plugin

    def _fetch_announcements_sync(self) -> list[Announcement]:
        payload = self._get_json("announcements/index.json")
        raw_announcements = payload.get("announcements", [])
        if not isinstance(raw_announcements, list):
            raise ValueError("公告列表格式无效")

        announcements: list[Announcement] = []
        for item in raw_announcements:
            if not isinstance(item, dict):
                continue
            announcement = Announcement.from_dict(item)
            if not announcement.stable_id:
                continue
            announcements.append(announcement)

        deduped: dict[str, Announcement] = {}
        for announcement in announcements:
            deduped[announcement.stable_id] = announcement

        result = sorted(
            deduped.values(),
            key=lambda item: (_ANNOUNCEMENT_LEVEL_PRIORITY.get(item.level, 99), -_date_key(item.date)),
        )
        logger.info("公告数据已刷新，共 {} 条公告", len(result))
        return result

    def _install_store_plugin_sync(self, plugin_id: str) -> str:
        plugin = self.get_store_plugin(plugin_id)
        if plugin is None:
            raise ValueError("未找到对应的商店插件")
        if not plugin.download_url:
            raise ValueError("该插件缺少下载地址")

        parsed = urlparse(plugin.download_url)
        suffix = Path(parsed.path).suffix.lower() or ".py"
        if suffix not in _SUPPORTED_STORE_FILE_EXTS:
            raise ValueError("当前插件商店仅支持 .py 插件安装包")

        resp = self._build_session().get(plugin.download_url, timeout=(8, 30))
        resp.raise_for_status()
        data = resp.content
        if not data:
            raise ValueError("下载内容为空")

        safe_id = re.sub(r"[^a-zA-Z0-9_-]", "-", plugin.stable_id).strip("-") or "plugin"
        dest = Path(PLUGINS_DIR)
        mkdir_with_uac(dest, parents=True, exist_ok=True)
        file_path = dest / f"{safe_id}{suffix}"
        write_bytes_with_uac(file_path, data, ensure_parent=True)
        logger.info("商店插件 {} 已下载到 {}", plugin.stable_id, file_path)
        return str(file_path)

    @staticmethod
    def _build_session() -> requests.Session:
        session = requests.Session()
        session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Connection": "close",
        })
        retry = Retry(
            total=2,
            connect=2,
            read=2,
            status=2,
            backoff_factor=0.6,
            status_forcelist=_REQUEST_RETRY_STATUS,
            allowed_methods=frozenset({"GET"}),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=8)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def _get_json(self, path: str, *, session: requests.Session | None = None) -> dict[str, Any]:
        client = session or self._build_session()
        url = urljoin(_API_BASE_URL, path.lstrip("/"))
        last_error: Exception | None = None

        for attempt in range(1, _REQUEST_MAX_ATTEMPTS + 1):
            try:
                response = client.get(url, timeout=_REQUEST_TIMEOUT)
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict):
                    raise ValueError(f"接口返回格式无效：{path}")
                if attempt > 1:
                    logger.info("远程请求重试成功: path={}, attempt={}", path, attempt)
                return data
            except requests.RequestException as exc:
                last_error = exc
                if attempt >= _REQUEST_MAX_ATTEMPTS:
                    break

                backoff = _REQUEST_RETRY_BACKOFF_BASE_SEC * (2 ** (attempt - 1))
                logger.warning(
                    "远程请求失败，准备重试: path={}, attempt={}/{}, wait={:.1f}s, error={}",
                    path,
                    attempt,
                    _REQUEST_MAX_ATTEMPTS,
                    backoff,
                    exc.__class__.__name__,
                )
                time.sleep(backoff)

        host = urlparse(url).netloc or "远程服务"
        if last_error is not None:
            raise RemoteResourceRequestError(
                f"连接 {host} 失败（已重试 {_REQUEST_MAX_ATTEMPTS} 次）"
            ) from last_error
        raise RemoteResourceRequestError(f"连接 {host} 失败")

    def _load_state(self) -> None:
        raw = load_json(str(_STATE_PATH), {})
        muted = raw.get("muted_announcement_popup_ids", []) if isinstance(raw, dict) else []
        self._muted_popup_ids = {
            str(item).strip()
            for item in muted
            if str(item).strip()
        }

    def _save_state(self) -> None:
        save_json(
            str(_STATE_PATH),
            {
                "muted_announcement_popup_ids": sorted(self._muted_popup_ids),
            },
        )


def current_os_key() -> str:
    system = platform.system().strip().lower()
    if system.startswith("win"):
        return "windows"
    if system == "darwin":
        return "macos"
    return "linux"


def normalize_plugin_lookup_key(plugin_id: str) -> str:
    return re.sub(r"[-_\s]+", "", str(plugin_id).strip().lower())


def compare_versions(left: str, right: str) -> int:
    """比较两个版本号。返回 1 / 0 / -1。"""

    def _parts(value: str) -> list[Any]:
        tokens = re.split(r"[^A-Za-z0-9]+", str(value).strip())
        result: list[Any] = []
        for token in tokens:
            if not token:
                continue
            if token.isdigit():
                result.append(int(token))
            else:
                result.append(token.lower())
        return result or [0]

    left_parts = _parts(left)
    right_parts = _parts(right)
    max_len = max(len(left_parts), len(right_parts))
    left_parts.extend([0] * (max_len - len(left_parts)))
    right_parts.extend([0] * (max_len - len(right_parts)))

    for l_item, r_item in zip(left_parts, right_parts):
        if l_item == r_item:
            continue
        if isinstance(l_item, int) and isinstance(r_item, int):
            return 1 if l_item > r_item else -1
        return 1 if str(l_item) > str(r_item) else -1
    return 0


def _resolve_text(value: Any, *, language: str | None = None, default: str = "") -> str:
    i18n = I18nService.instance()
    return i18n.resolve_text(value, default=default) if isinstance(value, dict) else str(value or default)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _date_key(value: str) -> int:
    digits = re.sub(r"\D", "", str(value))
    if not digits:
        return 0
    try:
        return int(digits)
    except ValueError:
        return 0

"""应用更新服务：负责检查更新、缓存更新信息与下载安装程序。"""
from __future__ import annotations

import re
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin, urlparse

import requests
from requests.adapters import HTTPAdapter, Retry
from PySide6.QtCore import QObject, QThread, Signal, Slot

from app.constants import APP_VERSION, TEMP_DIR, UPDATE_STATE_CONFIG, USER_AGENT
from app.services.remote_resource_service import compare_versions
from app.services.settings_service import SettingsService
from app.utils.fs import mkdir_with_uac, write_bytes_with_uac
from app.utils.logger import logger
from app.utils.time_utils import load_json, save_json


_UPDATE_API_BASE_URL = "https://clock.api.zsxiaoshu.cn/"
_UPDATE_DOCS_URL = "https://clock.api.zsxiaoshu.cn/docs"
_SUPPORTED_CHANNELS = ("stable", "beta", "dev")
_REQUEST_TIMEOUT = (8, 30)
_REQUEST_MAX_ATTEMPTS = 3
_REQUEST_RETRY_STATUS = (429, 500, 502, 503, 504)
_DOWNLOAD_DIR = Path(TEMP_DIR) / "updates"


class UpdateRequestError(RuntimeError):
    """更新服务网络请求失败。"""


class _TaskWorker(QObject):
    """在线程中执行同步任务。"""

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
            if isinstance(exc, UpdateRequestError):
                logger.warning("更新任务执行失败: {}", exc)
            else:
                logger.exception("更新任务执行失败")
            self.failed.emit(str(exc) or exc.__class__.__name__)
        else:
            self.finished.emit(result)


class _DownloadThread(QThread):
    """下载并解析安装程序。"""

    progressChanged = Signal(int, int, str)
    resultReady = Signal(object)
    failed = Signal(str)

    def __init__(self, update_info: "UpdateInfo", parent=None):
        super().__init__(parent)
        self._update_info = update_info

    def run(self) -> None:
        try:
            result = _download_installer_sync(self._update_info, self.progressChanged.emit)
        except Exception as exc:
            logger.exception("下载安装程序失败")
            self.failed.emit(str(exc) or exc.__class__.__name__)
        else:
            self.resultReady.emit(result)


@dataclass(slots=True)
class UpdateInfo:
    """更新元数据。"""

    channel: str = "stable"
    version: str = ""
    release_date: str = ""
    download_url: str = ""
    changelog: str = ""
    min_version: str = ""
    mandatory: bool = False
    detail_url: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UpdateInfo":
        channel = _normalize_channel(data.get("channel", "stable"))
        download_url = str(data.get("download_url", "")).strip()
        detail_url = str(data.get("detail_url", "")).strip()
        if not detail_url:
            detail_url = _derive_detail_url(download_url)
        return cls(
            channel=channel,
            version=str(data.get("version", "")).strip(),
            release_date=str(data.get("release_date", "")).strip(),
            download_url=download_url,
            changelog=str(data.get("changelog", "") or "").strip(),
            min_version=str(data.get("min_version", "")).strip(),
            mandatory=bool(data.get("mandatory", False)),
            detail_url=detail_url,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "version": self.version,
            "release_date": self.release_date,
            "download_url": self.download_url,
            "changelog": self.changelog,
            "min_version": self.min_version,
            "mandatory": self.mandatory,
            "detail_url": self.detail_url,
        }

    @property
    def stable_id(self) -> str:
        return f"{self.channel}:{self.version}".strip(":")

    @property
    def resolved_detail_url(self) -> str:
        return self.detail_url or _derive_detail_url(self.download_url)


class UpdateService(QObject):
    """检查更新、缓存更新元数据并下载安装程序。"""

    stateChanged = Signal()
    checkStarted = Signal(str)
    checkFinished = Signal(object, bool)
    checkFailed = Signal(str)

    downloadStarted = Signal(object)
    downloadProgress = Signal(int, int, str)
    downloadFinished = Signal(str, str, object)
    downloadFailed = Signal(str)

    def __init__(self, settings_service: SettingsService | None = None, parent=None):
        super().__init__(parent)
        self._settings = settings_service or SettingsService.instance()

        self._latest_cache: dict[str, UpdateInfo] = {}
        self._latest_info: UpdateInfo | None = None
        self._last_check_at: dict[str, float] = {}
        self._last_error = ""
        self._last_download: dict[str, str] = {}
        self._pending_post_update_notice: dict[str, Any] | None = None

        self._check_thread: QThread | None = None
        self._check_worker: _TaskWorker | None = None
        self._download_thread: _DownloadThread | None = None
        self._download_target: UpdateInfo | None = None

        self._load_state()
        self._latest_info = self._latest_cache.get(self.current_channel)

    @property
    def current_channel(self) -> str:
        return _normalize_channel(self._settings.update_channel)

    @property
    def latest_info(self) -> UpdateInfo | None:
        return self._latest_info

    @property
    def is_checking(self) -> bool:
        return self._check_thread is not None

    @property
    def is_downloading(self) -> bool:
        return self._download_thread is not None

    @property
    def last_error(self) -> str:
        return self._last_error

    @property
    def last_download(self) -> dict[str, str]:
        return dict(self._last_download)

    def last_checked_at(self, channel: str | None = None) -> float:
        return float(self._last_check_at.get(_normalize_channel(channel or self.current_channel), 0.0))

    def cached_info(self, channel: str | None = None) -> UpdateInfo | None:
        return self._latest_cache.get(_normalize_channel(channel or self.current_channel))

    def set_channel(self, channel: str) -> None:
        normalized = _normalize_channel(channel)
        if normalized != self.current_channel:
            self._settings.set_update_channel(normalized)
        self._latest_info = self._latest_cache.get(normalized)
        self.stateChanged.emit()

    def is_update_available(self, info: UpdateInfo | None = None) -> bool:
        target = info or self._latest_info
        return bool(target and target.version and compare_versions(target.version, APP_VERSION) > 0)

    def is_auto_upgrade_supported(self, info: UpdateInfo | None = None) -> bool:
        target = info or self._latest_info
        if target is None or not target.min_version:
            return True
        return compare_versions(APP_VERSION, target.min_version) >= 0

    def check_for_updates(self, channel: str | None = None) -> bool:
        if self._check_thread is not None:
            return False

        target_channel = _normalize_channel(channel or self.current_channel)
        self.checkStarted.emit(target_channel)

        self._check_thread = QThread(self)
        self._check_worker = _TaskWorker(lambda: self._fetch_update_info_sync(target_channel))
        self._check_worker.moveToThread(self._check_thread)
        self._check_thread.started.connect(self._check_worker.run)
        self._check_worker.finished.connect(self._on_check_finished)
        self._check_worker.failed.connect(self._on_check_failed)
        self._check_worker.finished.connect(self._check_thread.quit)
        self._check_worker.failed.connect(self._check_thread.quit)
        self._check_thread.finished.connect(self._cleanup_check_task)
        self._check_thread.start()
        self.stateChanged.emit()
        return True

    def download_update(self, info: UpdateInfo | None = None) -> bool:
        if self._download_thread is not None:
            return False

        target = info or self._latest_info
        if target is None:
            self.downloadFailed.emit("尚未获取更新信息")
            return False
        if not target.download_url:
            self.downloadFailed.emit("该更新缺少下载地址")
            return False
        if not self.is_auto_upgrade_supported(target):
            self.downloadFailed.emit("当前版本低于自动升级最低要求，请查看详情后手动升级")
            return False

        self._download_target = target
        self._download_thread = _DownloadThread(target, self)
        self._download_thread.progressChanged.connect(self._on_download_progress)
        self._download_thread.resultReady.connect(self._on_download_result)
        self._download_thread.failed.connect(self._on_download_failed)
        self._download_thread.finished.connect(self._cleanup_download_task)
        self.downloadStarted.emit(target)
        self._download_thread.start()
        self.stateChanged.emit()
        return True

    def peek_post_update_notice(self) -> UpdateInfo | None:
        payload = self._pending_post_update_notice
        if not isinstance(payload, dict):
            return None
        raw_info = payload.get("info")
        if not isinstance(raw_info, dict):
            return None
        target_version = str(payload.get("target_version") or raw_info.get("version") or "").strip()
        if not target_version or compare_versions(APP_VERSION, target_version) != 0:
            return None
        return UpdateInfo.from_dict(raw_info)

    def consume_post_update_notice(self) -> UpdateInfo | None:
        info = self.peek_post_update_notice()
        if info is None:
            return None
        self._pending_post_update_notice = None
        self._save_state()
        self.stateChanged.emit()
        return info

    def clear_post_update_notice(self) -> None:
        if self._pending_post_update_notice is None:
            return
        self._pending_post_update_notice = None
        self._save_state()
        self.stateChanged.emit()

    def prepare_post_update_notice(self, info: UpdateInfo) -> None:
        self._pending_post_update_notice = {
            "prepared_by_version": APP_VERSION,
            "target_version": info.version,
            "prepared_at": int(time.time()),
            "info": info.to_dict(),
        }
        self._save_state()
        self.stateChanged.emit()

    @staticmethod
    def build_installer_command(installer_path: str | Path, *, log_path: str | Path | None = None) -> list[str]:
        path = Path(installer_path)
        if path.suffix.lower() != ".exe":
            raise ValueError("当前仅支持启动 Inno Setup .exe 安装程序")
        cmd = [
            str(path),
            "/SP-",
            "/CLOSEAPPLICATIONS",
            "/FORCECLOSEAPPLICATIONS",
            "/NORESTART",
            "/NORESTARTAPPLICATIONS",
        ]
        if log_path:
            cmd.append(f"/LOG={str(log_path)}")
        return cmd

    def shutdown(self, *, timeout_ms: int = 1800) -> None:
        self._stop_thread(self._check_thread, timeout_ms=timeout_ms, label="update-check")
        self._stop_thread(self._download_thread, timeout_ms=timeout_ms, label="update-download")
        self._cleanup_check_task()
        self._cleanup_download_task()

    @Slot(object)
    def _on_check_finished(self, result: object) -> None:
        info = result if isinstance(result, UpdateInfo) else None
        if info is not None:
            self._latest_cache[info.channel] = info
            self._last_check_at[info.channel] = time.time()
            if info.channel == self.current_channel:
                self._latest_info = info
            self._last_error = ""
            self._save_state()
            self.checkFinished.emit(info, self.is_update_available(info))
        else:
            self.checkFinished.emit(None, False)
        self.stateChanged.emit()

    @Slot(str)
    def _on_check_failed(self, error: str) -> None:
        self._last_error = error
        self._save_state()
        self.checkFailed.emit(error)
        self.stateChanged.emit()

    @Slot(int, int, str)
    def _on_download_progress(self, received: int, total: int, text: str) -> None:
        self.downloadProgress.emit(received, total, text)

    @Slot(object)
    def _on_download_result(self, payload: object) -> None:
        if not isinstance(payload, dict):
            self._on_download_failed("下载结果无效")
            return

        archive_path = str(payload.get("archive_path") or "")
        installer_path = str(payload.get("installer_path") or "")
        info = self._download_target
        if info is not None:
            self._last_download = {
                "channel": info.channel,
                "version": info.version,
                "source_url": info.download_url,
                "archive_path": archive_path,
                "installer_path": installer_path,
                "saved_at": str(int(time.time())),
            }
            self._save_state()
            self.downloadFinished.emit(archive_path, installer_path, info)
        else:
            self.downloadFinished.emit(archive_path, installer_path, None)
        self.stateChanged.emit()

    @Slot(str)
    def _on_download_failed(self, error: str) -> None:
        self.downloadFailed.emit(error)
        self.stateChanged.emit()

    def _cleanup_check_task(self) -> None:
        if self._check_worker is not None:
            self._check_worker.deleteLater()
            self._check_worker = None
        if self._check_thread is not None:
            if not self._check_thread.isRunning():
                self._check_thread.deleteLater()
            self._check_thread = None
        self.stateChanged.emit()

    def _cleanup_download_task(self) -> None:
        if self._download_thread is not None:
            if not self._download_thread.isRunning():
                self._download_thread.deleteLater()
            self._download_thread = None
        self._download_target = None
        self.stateChanged.emit()

    def _stop_thread(self, thread: QThread | None, *, timeout_ms: int, label: str) -> None:
        if thread is None:
            return
        if thread.isRunning():
            thread.quit()
            if not thread.wait(timeout_ms):
                logger.warning("更新线程退出超时，已强制终止: {}", label)
                thread.terminate()
                thread.wait(5000)

    def _fetch_update_info_sync(self, channel: str) -> UpdateInfo:
        session = _build_session()
        data = _get_json(f"update/{channel}.json", session=session)
        info = UpdateInfo.from_dict(data)
        if not info.version:
            raise ValueError("更新接口缺少 version 字段")
        return info

    def _load_state(self) -> None:
        raw = load_json(UPDATE_STATE_CONFIG, {})
        if not isinstance(raw, dict):
            return

        latest_cache = raw.get("latest_cache", {})
        if isinstance(latest_cache, dict):
            for channel, payload in latest_cache.items():
                if not isinstance(payload, dict):
                    continue
                normalized = _normalize_channel(channel)
                self._latest_cache[normalized] = UpdateInfo.from_dict(payload)

        last_check_at = raw.get("last_check_at", {})
        if isinstance(last_check_at, dict):
            for channel, value in last_check_at.items():
                try:
                    self._last_check_at[_normalize_channel(channel)] = float(value)
                except (TypeError, ValueError):
                    continue

        self._last_error = str(raw.get("last_error", "") or "")
        self._pending_post_update_notice = raw.get("post_update_notice") if isinstance(raw.get("post_update_notice"), dict) else None

        last_download = raw.get("last_download", {})
        if isinstance(last_download, dict):
            self._last_download = {
                key: str(value)
                for key, value in last_download.items()
                if str(key).strip()
            }

    def _save_state(self) -> None:
        save_json(
            UPDATE_STATE_CONFIG,
            {
                "latest_cache": {
                    channel: info.to_dict()
                    for channel, info in self._latest_cache.items()
                },
                "last_check_at": dict(self._last_check_at),
                "last_error": self._last_error,
                "last_download": dict(self._last_download),
                "post_update_notice": dict(self._pending_post_update_notice) if isinstance(self._pending_post_update_notice, dict) else None,
            },
        )


def _normalize_channel(value: Any) -> str:
    text = str(value or "stable").strip().lower()
    return text if text in _SUPPORTED_CHANNELS else "stable"


def _safe_slug(*parts: str) -> str:
    raw = "-".join(str(part or "").strip() for part in parts if str(part or "").strip())
    return re.sub(r"[^0-9A-Za-z._-]+", "-", raw).strip("-._") or "update"


def _derive_detail_url(download_url: str) -> str:
    text = str(download_url or "").strip()
    if not text:
        return _UPDATE_DOCS_URL

    parsed = urlparse(text)
    marker = "/releases/download/"
    if parsed.netloc.lower() == "github.com" and marker in parsed.path:
        prefix, suffix = parsed.path.split(marker, 1)
        tag = suffix.split("/", 1)[0].strip()
        if prefix and tag:
            return f"{parsed.scheme}://{parsed.netloc}{prefix}/releases/tag/{tag}"
    return text


def _build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Connection": "close",
        }
    )
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
    adapter = HTTPAdapter(max_retries=retry, pool_connections=2, pool_maxsize=4)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def _get_json(path: str, *, session: requests.Session | None = None) -> dict[str, Any]:
    client = session or _build_session()
    url = urljoin(_UPDATE_API_BASE_URL, path.lstrip("/"))
    last_error: Exception | None = None

    for attempt in range(1, _REQUEST_MAX_ATTEMPTS + 1):
        try:
            response = client.get(url, timeout=_REQUEST_TIMEOUT)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError(f"接口返回格式无效：{path}")
            return data
        except requests.RequestException as exc:
            last_error = exc
            if attempt >= _REQUEST_MAX_ATTEMPTS:
                break
            time.sleep(0.8 * (2 ** (attempt - 1)))

    host = urlparse(url).netloc or "远程服务"
    if last_error is not None:
        raise UpdateRequestError(f"连接 {host} 失败（已重试 {_REQUEST_MAX_ATTEMPTS} 次）") from last_error
    raise UpdateRequestError(f"连接 {host} 失败")


def _download_installer_sync(
    update_info: UpdateInfo,
    progress_callback: Callable[[int, int, str], None],
) -> dict[str, str]:
    session = _build_session()
    response = session.get(update_info.download_url, timeout=(10, 60), stream=True)
    response.raise_for_status()

    total = int(response.headers.get("content-length", 0) or 0)
    received = 0
    payload = bytearray()
    for chunk in response.iter_content(chunk_size=64 * 1024):
        if not chunk:
            continue
        payload.extend(chunk)
        received += len(chunk)
        progress_callback(received, total, _format_progress_text(received, total))

    if not payload:
        raise ValueError("下载内容为空")

    mkdir_with_uac(_DOWNLOAD_DIR, parents=True, exist_ok=True)
    parsed = urlparse(update_info.download_url)
    suffix = Path(parsed.path).suffix.lower()
    if not suffix and payload[:2] == b"MZ":
        suffix = ".exe"
    if not suffix:
        suffix = ".bin"

    archive_name = f"{_safe_slug(update_info.channel, update_info.version)}{suffix}"
    archive_path = _DOWNLOAD_DIR / archive_name
    write_bytes_with_uac(archive_path, bytes(payload), ensure_parent=True)

    installer_path = archive_path
    if suffix == ".zip":
        installer_path = _extract_installer_from_zip(
            archive_path,
            _DOWNLOAD_DIR / _safe_slug(update_info.channel, update_info.version, "installer"),
        )
    elif suffix != ".exe":
        raise ValueError("下载文件不是可执行安装程序，且压缩包中未找到安装器")

    logger.info("更新安装包已下载：{} -> {}", archive_path, installer_path)
    return {
        "archive_path": str(archive_path),
        "installer_path": str(installer_path),
    }


def _extract_installer_from_zip(archive_path: Path, target_dir: Path) -> Path:
    with zipfile.ZipFile(archive_path, "r") as zf:
        members = [name for name in zf.namelist() if name and not name.endswith("/")]
        candidates = [
            name
            for name in members
            if Path(name).suffix.lower() == ".exe"
        ]
        if not candidates:
            raise ValueError("压缩包中未找到安装程序")

        candidates.sort(key=lambda item: (len(item), item.lower()))
        member = candidates[0]
        data = zf.read(member)
        if not data:
            raise ValueError("安装程序文件为空")

    mkdir_with_uac(target_dir, parents=True, exist_ok=True)
    installer_path = target_dir / Path(member).name
    write_bytes_with_uac(installer_path, data, ensure_parent=True)
    return installer_path


def _format_progress_text(received: int, total: int) -> str:
    if total > 0:
        percent = min(100, int(received * 100 / total))
        return f"{percent}% · {_format_size(received)} / {_format_size(total)}"
    return f"已下载 {_format_size(received)}"


def _format_size(value: int) -> str:
    amount = float(max(0, value))
    for unit in ("B", "KB", "MB", "GB"):
        if amount < 1024 or unit == "GB":
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{amount:.1f} GB"
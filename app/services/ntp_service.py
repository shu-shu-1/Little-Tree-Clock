"""
NTP 时间同步服务

功能
----
- 后台线程周期性从 NTP 服务器获取时间偏移量
- 其他模块通过 NtpService.instance() 访问全局单例
- 提供修正后的当前时间 now()
- 支持动态更改服务器 / 同步间隔 / 启用开关
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

import ntplib

from app.utils.logger import logger
from app.utils.time_utils import load_json, save_json


# 默认配置
_DEFAULT_CONFIG = {
    "enabled": True,
    "server": "pool.ntp.org",
    "sync_interval_min": 30,
}

# 常用 NTP 服务器预设
NTP_SERVERS = [
    "pool.ntp.org",
    "time.cloudflare.com",
    "time.google.com",
    "time.windows.com",
    "ntp.aliyun.com",
    "cn.ntp.org.cn",
    "ntp.tencent.com",
    "time.apple.com",
    "time.nist.gov",
]


class NtpService:
    """NTP 时间同步服务（单例）"""

    _instance: Optional["NtpService"] = None
    _lock = threading.Lock()

    # ---------- 单例访问 ---------- #

    @classmethod
    def instance(cls) -> "NtpService":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = NtpService()
        return cls._instance

    # ---------- 初始化 ---------- #

    def __init__(self, config_path: str = ""):
        from app.constants import NTP_CONFIG
        self._config_path = config_path or NTP_CONFIG

        cfg = load_json(self._config_path, _DEFAULT_CONFIG)
        self._enabled: bool = cfg.get("enabled", False)
        self._server: str   = cfg.get("server", "pool.ntp.org")
        self._interval_min: int = int(cfg.get("sync_interval_min", 30))

        # NTP 校正偏移（秒，float）
        self._offset: float = 0.0

        # 同步状态
        self._last_sync_ts: Optional[float] = None  # time.time() 时间戳
        self._last_error: Optional[str]     = None
        self._syncing: bool                 = False

        # 后台线程
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        if self._enabled:
            self.start()

    # ---------- 对外 API ---------- #

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def server(self) -> str:
        return self._server

    @property
    def sync_interval_min(self) -> int:
        return self._interval_min

    @property
    def offset(self) -> float:
        """当前 NTP 偏移（秒），未同步时为 0"""
        return self._offset

    @property
    def last_sync_ts(self) -> Optional[float]:
        return self._last_sync_ts

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    @property
    def is_syncing(self) -> bool:
        return self._syncing

    def now(self) -> datetime:
        """返回经 NTP 校正的当前 UTC 时间"""
        if self._enabled and self._offset != 0.0:
            return datetime.now(timezone.utc) + timedelta(seconds=self._offset)
        return datetime.now(timezone.utc)

    # ---------- 启停 ---------- #

    def start(self) -> None:
        """启动后台同步线程"""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._sync_loop,
            name="NtpSyncThread",
            daemon=True,
        )
        self._thread.start()
        logger.info("NTP 同步线程已启动，服务器：{}", self._server)

    def stop(self) -> None:
        """停止后台同步线程"""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("NTP 同步线程已停止")

    def sync_once(self) -> bool:
        """立即同步一次，在后台线程中运行（非阻塞）"""
        t = threading.Thread(target=self._do_sync, daemon=True)
        t.start()
        return True

    # ---------- 配置 ---------- #

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        if enabled:
            self.start()
        else:
            self.stop()
            self._offset = 0.0
        self._save_config()
        logger.info("NTP 已{}", "启用" if enabled else "禁用")

    def set_server(self, server: str) -> None:
        self._server = server
        self._save_config()
        logger.info("NTP 服务器已更改为：{}", server)

    def set_sync_interval(self, minutes: int) -> None:
        self._interval_min = max(1, minutes)
        self._save_config()

    def last_sync_time_str(self) -> str:
        if self._last_sync_ts is None:
            return "从未同步"
        dt = datetime.fromtimestamp(self._last_sync_ts)
        return dt.strftime("%H:%M:%S")

    def offset_str(self) -> str:
        if not self._enabled or self._last_sync_ts is None:
            return "N/A"
        sign = "+" if self._offset >= 0 else ""
        return f"{sign}{self._offset:.3f} 秒"

    # ---------- 私有 ---------- #

    def _sync_loop(self) -> None:
        """后台轮询循环"""
        # 首次立即同步
        self._do_sync()
        while not self._stop_event.wait(self._interval_min * 60):
            self._do_sync()

    def _do_sync(self) -> None:
        """执行一次 NTP 查询"""
        if self._syncing:
            return
        self._syncing = True
        try:
            client = ntplib.NTPClient()
            resp = client.request(self._server, version=3, timeout=5)
            self._offset = resp.offset
            self._last_sync_ts = time.time()
            self._last_error = None
            logger.info(
                "NTP 同步成功：服务器={}, 偏移={:.3f}s, 延迟={:.3f}ms",
                self._server,
                resp.offset,
                resp.delay * 1000,
            )
        except ntplib.NTPException as e:
            self._last_error = str(e)
            logger.warning("NTP 协议错误：{}", e)
        except OSError as e:
            self._last_error = str(e)
            logger.warning("NTP 网络错误：{}", e)
        except Exception as e:
            self._last_error = str(e)
            logger.warning("NTP 同步失败：{}", e)
        finally:
            self._syncing = False

    def _save_config(self) -> None:
        save_json(self._config_path, {
            "enabled": self._enabled,
            "server": self._server,
            "sync_interval_min": self._interval_min,
        })

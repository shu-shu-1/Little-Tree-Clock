"""HTTP 请求安全封装：仅允许 http/https，请求与每次重定向都先校验目标。"""

from __future__ import annotations

import ipaddress
import socket
import threading
from urllib.parse import urljoin, urlparse

import requests
from urllib3.util import connection as _urllib3_connection

_ALLOWED_SCHEMES = ("http", "https")
_BLOCKED_HOSTNAMES = {"localhost", "localhost.localdomain"}
_MAX_REDIRECTS = 3


class UnsafeUrlError(Exception):
    """URL 未通过安全校验时抛出，message 为中文拒绝原因。"""


_PIN_ATTR = "_ltc_url_guard_pins"
_shared_pins = getattr(_urllib3_connection, _PIN_ATTR, None)
if not isinstance(_shared_pins, dict):
    _shared_pins = {}
    setattr(_urllib3_connection, _PIN_ATTR, _shared_pins)
# 多个模块副本共享同一张 pin 表，避免同一文件被重复加载时校验失效
_pinned_ips: dict[str, str] = _shared_pins
_pin_lock = threading.Lock()
_ORIGINAL_CREATE_CONNECTION = _urllib3_connection.create_connection


def _create_connection_with_pin(address, *args, **kwargs):
    host, port = address[0], address[1]
    with _pin_lock:
        pinned = _pinned_ips.get(host)
    if pinned:
        address = (pinned, port)
    return _ORIGINAL_CREATE_CONNECTION(address, *args, **kwargs)


_create_connection_with_pin._ltc_url_guard = True
# 覆盖 urllib3 的 DNS 解析入口：只有已校验并固定的主机名会改连指定 IP，其余连接不受影响
if not getattr(_urllib3_connection.create_connection, "_ltc_url_guard", False):
    _urllib3_connection.create_connection = _create_connection_with_pin


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def _is_blocked_ip(ip: ipaddress._BaseAddress) -> bool:
    # IPv4-mapped IPv6（如 ::ffff:127.0.0.1）按其内嵌 IPv4 判断；只放行公网地址
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return not ip.is_global


def _resolve_target(parsed) -> tuple[str | None, list[str]]:
    """返回 (拒绝原因, 可用 IP 列表)；任何一步失败都按拒绝处理。"""
    host = (parsed.hostname or "").strip().rstrip(".")
    if not host:
        return "URL 中缺少主机名", []
    if host.lower() in _BLOCKED_HOSTNAMES:
        return "不允许访问本机（localhost）地址", []

    if _is_ip_literal(host):
        ip = ipaddress.ip_address(host)
        if _is_blocked_ip(ip):
            return f"不允许访问内网/保留地址（{ip}）", []
        return None, [str(ip)]

    try:
        infos = socket.getaddrinfo(
            host,
            parsed.port or (443 if parsed.scheme.lower() == "https" else 80),
            proto=socket.IPPROTO_TCP,
        )
    except (socket.gaierror, OSError):
        return "无法解析主机名", []

    addresses: list[str] = []
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if _is_blocked_ip(ip):
            return f"不允许访问内网/保留地址（{ip}）", []
        if str(ip) not in addresses:
            addresses.append(str(ip))
    if not addresses:
        return "无法解析主机名", []
    return None, addresses


def _pin_host(parsed, addresses: list[str], pins: list[tuple[str, str]]) -> None:
    host = (parsed.hostname or "").strip().rstrip(".")
    if not host or _is_ip_literal(host):
        return
    ip = addresses[0]
    with _pin_lock:
        _pinned_ips[host] = ip
    pins.append((host, ip))


def _unpin_all(pins: list[tuple[str, str]]) -> None:
    with _pin_lock:
        for host, ip in pins:
            if _pinned_ips.get(host) == ip:
                _pinned_ips.pop(host, None)


def validate_http_url(url: object) -> str | None:
    """校验外部请求 URL，合法返回 None，否则返回拒绝原因。"""
    parsed = urlparse(str(url or ""))
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        return "仅支持 http/https 协议"
    return _resolve_target(parsed)[0]


def safe_get(url: str, **kwargs) -> requests.Response:
    """requests.get 的安全封装：校验目标并固定 DNS 解析结果后再请求。

    入口和每个重定向跳都重新校验，实际连接地址固定到校验通过的 IP，
    避免校验后 DNS 重新解析到内网地址；代理会让地址校验失效，因此不予支持。
    """
    if kwargs.pop("proxies", None):
        raise UnsafeUrlError("安全请求不支持代理")
    kwargs.pop("allow_redirects", None)
    kwargs.setdefault("timeout", 10)

    pins: list[tuple[str, str]] = []
    try:
        with requests.Session() as session:
            session.trust_env = False
            for _ in range(_MAX_REDIRECTS + 1):
                parsed = urlparse(str(url or ""))
                if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
                    raise UnsafeUrlError("仅支持 http/https 协议")
                rejected, addresses = _resolve_target(parsed)
                if rejected:
                    raise UnsafeUrlError(rejected)
                _pin_host(parsed, addresses, pins)
                resp = session.get(url, allow_redirects=False, **kwargs)
                if not (resp.is_redirect or resp.is_permanent_redirect):
                    return resp
                url = urljoin(resp.url, resp.headers.get("Location", ""))
            raise UnsafeUrlError("重定向次数过多")
    finally:
        _unpin_all(pins)

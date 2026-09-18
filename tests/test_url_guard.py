"""url_guard 的 SSRF 校验测试：只做地址与协议判定，不产生网络请求。"""

from __future__ import annotations

import pytest

from plugins_ext.hitokoto_widget import url_guard
from plugins_ext.hitokoto_widget.url_guard import validate_http_url


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://10.0.0.1/",
        "http://172.16.0.1/",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://100.100.100.100/latest/meta-data/",
        "http://100.64.0.1/",
        "http://0.0.0.0/",
        "http://[::1]/",
        "http://[fc00::1]/",
        "http://localhost:8080/",
        "http://localhost.localdomain/",
        "ftp://example.com/",
        "file:///etc/passwd",
        "http:///no-host",
    ],
)
def test_rejects_non_public_targets(url: str) -> None:
    assert validate_http_url(url) is not None


@pytest.mark.parametrize(
    "url",
    [
        "http://8.8.8.8/",
        "https://1.1.1.1/dns-query",
        "https://[2606:4700:4700::1111]/",
    ],
)
def test_allows_public_literal(url: str) -> None:
    assert validate_http_url(url) is None


def test_urllib3_resolution_is_patched() -> None:
    import urllib3.connection
    import urllib3.util.connection

    assert getattr(urllib3.util.connection.create_connection, "_ltc_url_guard", False) is True
    assert getattr(urllib3.connection.connection.create_connection, "_ltc_url_guard", False) is True


def test_pin_overrides_connection_address(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple] = []

    def _record(address, *args, **kwargs):
        calls.append(address)
        return object()

    monkeypatch.setattr(url_guard, "_ORIGINAL_CREATE_CONNECTION", _record)
    url_guard._pinned_ips["example.com"] = "203.0.113.9"
    try:
        url_guard._create_connection_with_pin(("example.com", 80))
        url_guard._create_connection_with_pin(("other.example", 443))
    finally:
        url_guard._pinned_ips.pop("example.com", None)

    assert calls == [("203.0.113.9", 80), ("other.example", 443)]

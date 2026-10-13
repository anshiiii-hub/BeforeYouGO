"""SSRF protections in safe_fetch. No real network: DNS is patched and HTTP goes through httpx.MockTransport."""

from __future__ import annotations

import socket

import httpx
import pytest

from app.services import safe_fetch
from app.services.safe_fetch import (
    FetchBlocked,
    FetchError,
    FetchTooLarge,
    fetch,
    set_transport_override,
    validate_url,
)

PUBLIC_IP = "93.184.216.34"


@pytest.fixture(autouse=True)
def fake_dns(monkeypatch):
    table = {"public.test.example": PUBLIC_IP, "evil.test.example": "10.0.0.5", "meta.test.example": "169.254.169.254",
             "loop.test.example": "127.0.0.1", "v6.test.example": "::1", "mixed.test.example": "multi"}

    def getaddrinfo(host, port, *a, **k):
        ip = table.get(host)
        if ip is None:
            raise socket.gaierror("no such host (test)")
        if ip == "multi":
            return [(socket.AF_INET, 1, 6, "", (PUBLIC_IP, 0)), (socket.AF_INET, 1, 6, "", ("192.168.1.9", 0))]
        fam = socket.AF_INET6 if ":" in ip else socket.AF_INET
        return [(fam, 1, 6, "", (ip, 0))]

    monkeypatch.setattr(safe_fetch.socket, "getaddrinfo", getaddrinfo)


def mock(handler):
    set_transport_override(httpx.MockTransport(handler))


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/", "http://127.1.2.3:80/", "http://localhost/", "http://LOCALHOST./x", "http://10.0.0.1/", "http://172.16.5.4/",
    "http://192.168.0.1/", "http://169.254.169.254/latest/meta-data/", "http://[::1]/", "http://[fe80::1]/", "http://0.0.0.0/",
    "http://[::ffff:127.0.0.1]/", "http://[::ffff:169.254.169.254]/", "http://100.64.0.1/", "http://intranet/", "http://printer.local/",
    "http://db.internal/", "http://evil.test.example/", "http://meta.test.example/", "http://loop.test.example/", "http://v6.test.example/",
    "http://mixed.test.example/",
])
def test_private_and_internal_targets_blocked(url):
    with pytest.raises(FetchBlocked):
        validate_url(url)


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://public.test.example/x", "gopher://public.test.example/", "javascript:alert(1)",
                                 "data:text/plain,hi", "//public.test.example/x"])
def test_non_http_schemes_blocked(url):
    with pytest.raises(FetchBlocked):
        validate_url(url)


def test_credentials_nonstandard_ports_and_empty_host_blocked():
    for url in ("http://user:pw@public.test.example/", "http://public.test.example:8080/", "http://public.test.example:22/", "http://", "https://:443/"):
        with pytest.raises(FetchBlocked):
            validate_url(url)


def test_public_url_allowed_and_unresolvable_is_dns_failure():
    assert validate_url("https://public.test.example/x") == "https://public.test.example/x"
    with pytest.raises(FetchError) as e:
        validate_url("https://nowhere.test.example/")
    assert e.value.code == "dns_failure"


def test_blocked_request_never_reaches_transport():
    calls = []
    mock(lambda r: calls.append(r) or httpx.Response(200))
    with pytest.raises(FetchBlocked):
        fetch("http://169.254.169.254/latest/meta-data/")
    assert calls == []


def test_redirect_to_internal_ip_blocked():
    seen = []

    def h(req):
        seen.append(str(req.url))
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data/"})

    mock(h)
    with pytest.raises(FetchBlocked):
        fetch("https://public.test.example/start")
    assert seen == ["https://public.test.example/start"]


def test_redirect_to_hostname_resolving_private_blocked():
    mock(lambda req: httpx.Response(301, headers={"location": "https://evil.test.example/admin"}))
    with pytest.raises(FetchBlocked):
        fetch("https://public.test.example/")


def test_redirect_to_non_http_scheme_blocked():
    mock(lambda req: httpx.Response(302, headers={"location": "file:///etc/passwd"}))
    with pytest.raises(FetchBlocked):
        fetch("https://public.test.example/")


def test_safe_redirect_followed_and_final_url_reported():
    def h(req):
        if req.url.path == "/a":
            return httpx.Response(302, headers={"location": "/b"})
        return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}, content=b"<html>ok</html>")

    mock(h)
    doc = fetch("https://public.test.example/a")
    assert doc.final_url == "https://public.test.example/b" and doc.text == "<html>ok</html>" and doc.status_code == 200


def test_redirect_loop_stops():
    mock(lambda req: httpx.Response(302, headers={"location": "/again"}))
    with pytest.raises(FetchError) as e:
        fetch("https://public.test.example/")
    assert e.value.code == "too_many_redirects"


def test_size_limit_by_content_length_and_streamed_body(settings, monkeypatch):
    monkeypatch.setattr(settings, "fetch_max_bytes", 1000)
    mock(lambda req: httpx.Response(200, headers={"content-type": "text/plain", "content-length": "999999"}, content=b"x"))
    with pytest.raises(FetchTooLarge):
        fetch("https://public.test.example/big")
    mock(lambda req: httpx.Response(200, headers={"content-type": "text/plain"}, content=b"x" * 5000))
    with pytest.raises(FetchTooLarge):
        fetch("https://public.test.example/chunked")
    mock(lambda req: httpx.Response(200, headers={"content-type": "text/plain"}, content=b"x" * 900))
    assert len(fetch("https://public.test.example/ok").content) == 900


def test_content_type_allow_list_and_http_errors():
    mock(lambda req: httpx.Response(200, headers={"content-type": "application/x-msdownload"}, content=b"MZ"))
    with pytest.raises(FetchError) as e:
        fetch("https://public.test.example/")
    assert e.value.code == "unsupported_content_type"
    mock(lambda req: httpx.Response(503, headers={"content-type": "text/html"}))
    with pytest.raises(FetchError) as e2:
        fetch("https://public.test.example/")
    assert e2.value.code == "http_503"


def test_timeout_and_network_errors_are_mapped():
    def boom(req):
        raise httpx.ConnectTimeout("t", request=req)

    mock(boom)
    with pytest.raises(FetchError) as e:
        fetch("https://public.test.example/")
    assert e.value.code == "timeout"


def test_robots_disallow_respected():
    def h(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"User-agent: *\nDisallow: /private\n")
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"hi")

    mock(h)
    assert fetch("https://public.test.example/open", respect_robots=True).text == "hi"
    with pytest.raises(FetchError) as e:
        fetch("https://public.test.example/private/x", respect_robots=True)
    assert e.value.code == "robots_disallowed"


def test_allow_private_fetch_flag_is_test_only_switch(settings, monkeypatch):
    assert settings.allow_private_fetch is False  # default in tests: protections on
    monkeypatch.setattr(settings, "allow_private_fetch", True)
    mock(lambda req: httpx.Response(200, headers={"content-type": "text/plain"}, content=b"local"))
    assert fetch("http://127.0.0.1:9999/x").text == "local"


def test_analyzer_url_endpoint_refuses_internal_targets(client):
    r = client.post("/api/analyzer/url", json={"url": "http://169.254.169.254/latest/meta-data/"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "fetch_blocked"

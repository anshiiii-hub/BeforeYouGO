"""SSRF-safe outbound HTTP fetching.

Every hop of every request is validated: scheme, port, credentials in the URL,
hostname patterns, and every address the hostname resolves to must be globally
routable. Redirects are followed manually so each hop is re-validated. Bodies are
size-capped and content types are allow-listed.

Known limitation: the check resolves the name before connecting, so a hostile DNS
server could in theory answer differently at connect time (DNS rebinding). Deploy
behind an egress policy for defence in depth; this environment already does.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
import urllib.robotparser
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from app.core.config import get_settings

logger = logging.getLogger("byg.fetch")

DEFAULT_ALLOWED_TYPES = (
    "text/html",
    "application/xhtml+xml",
    "text/plain",
    "application/json",
    "text/calendar",
    "application/ld+json",
    "text/xml",
    "application/xml",
    "application/rss+xml",
    "application/atom+xml",
    "application/pdf",
)
MAX_REDIRECTS = 5

# Tests can inject an httpx transport (e.g. MockTransport) without touching the network.
_transport_override: httpx.BaseTransport | None = None


def set_transport_override(transport: httpx.BaseTransport | None) -> None:
    global _transport_override
    _transport_override = transport


class FetchError(Exception):
    code = "fetch_failed"

    def __init__(self, message: str, *, code: str | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code


class FetchBlocked(FetchError):
    code = "fetch_blocked"


class EgressDenied(FetchError):
    code = "egress_denied"


class FetchTooLarge(FetchError):
    code = "fetch_too_large"


class RobotsDisallowed(FetchError):
    code = "robots_disallowed"


@dataclass
class FetchedDocument:
    requested_url: str
    final_url: str
    status_code: int
    content_type: str
    content: bytes
    headers: dict[str, str] = field(default_factory=dict)
    fetched_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def text(self) -> str:
        enc = "utf-8"
        ct = self.headers.get("content-type", "")
        if "charset=" in ct:
            enc = ct.split("charset=")[-1].split(";")[0].strip() or "utf-8"
        try:
            return self.content.decode(enc, errors="replace")
        except LookupError:
            return self.content.decode("utf-8", errors="replace")


_BLOCKED_HOST_SUFFIXES = (".local", ".internal", ".localdomain", ".lan", ".home", ".corp", ".intranet")


def _ip_is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast and not ip.is_reserved and not ip.is_loopback


def validate_url(url: str, *, allow_private: bool | None = None) -> str:
    """Return the validated URL or raise FetchBlocked."""
    settings = get_settings()
    if allow_private is None:
        allow_private = settings.allow_private_fetch
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https"):
        raise FetchBlocked("Only http and https URLs can be fetched.")
    if parts.username or parts.password:
        raise FetchBlocked("URLs containing credentials are not allowed.")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        raise FetchBlocked("The URL has no hostname.")
    try:
        port = parts.port
    except ValueError as exc:
        raise FetchBlocked("The URL has an invalid port.") from exc
    if not allow_private and port not in (None, 80, 443):
        raise FetchBlocked("Only the standard web ports (80 and 443) are allowed.")
    if allow_private:
        return url
    if host == "localhost" or host.endswith(_BLOCKED_HOST_SUFFIXES) or "." not in host and ":" not in host:
        raise FetchBlocked("Internal hostnames cannot be fetched.")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if not _ip_is_public(literal):
            raise FetchBlocked("Private, loopback, link-local and reserved addresses cannot be fetched.")
        return url
    try:
        infos = socket.getaddrinfo(host, port or (443 if parts.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise FetchError(f"Could not resolve host '{host}'.", code="dns_failure") from exc
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr.split("%")[0])
        except ValueError:
            continue
        if not _ip_is_public(ip):
            raise FetchBlocked("The hostname resolves to a non-public address and cannot be fetched.")
    return url


def _client() -> httpx.Client:
    settings = get_settings()
    kwargs: dict[str, Any] = {
        "timeout": settings.fetch_timeout_seconds,
        "follow_redirects": False,
        "headers": {"User-Agent": settings.fetch_user_agent, "Accept": "*/*"},
    }
    if _transport_override is not None:
        kwargs["transport"] = _transport_override
    return httpx.Client(**kwargs)


def _content_type(value: str) -> str:
    return value.split(";")[0].strip().lower()


def fetch(
    url: str,
    *,
    allowed_types: tuple[str, ...] = DEFAULT_ALLOWED_TYPES,
    max_bytes: int | None = None,
    respect_robots: bool = False,
    extra_headers: dict[str, str] | None = None,
) -> FetchedDocument:
    settings = get_settings()
    limit = max_bytes or settings.fetch_max_bytes
    current = validate_url(url)
    if respect_robots:
        _check_robots(current)
    with _client() as client:
        for _hop in range(MAX_REDIRECTS + 1):
            try:
                with client.stream("GET", current, headers=extra_headers or {}) as resp:
                    if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get("location"):
                        current = validate_url(urljoin(current, resp.headers["location"]))
                        continue
                    ctype = _content_type(resp.headers.get("content-type", ""))
                    if resp.status_code >= 400:
                        raise FetchError(
                            f"The server answered HTTP {resp.status_code}.", code=f"http_{resp.status_code}"
                        )
                    if ctype and not any(ctype == a or ctype.endswith("+json") for a in allowed_types):
                        raise FetchError(f"Unsupported content type '{ctype}'.", code="unsupported_content_type")
                    declared = resp.headers.get("content-length")
                    if declared and declared.isdigit() and int(declared) > limit:
                        raise FetchTooLarge(f"The response is larger than the {limit // 1000} KB limit.")
                    chunks: list[bytes] = []
                    total = 0
                    for chunk in resp.iter_bytes():
                        total += len(chunk)
                        if total > limit:
                            raise FetchTooLarge(f"The response is larger than the {limit // 1000} KB limit.")
                        chunks.append(chunk)
                    return FetchedDocument(
                        requested_url=url,
                        final_url=current,
                        status_code=resp.status_code,
                        content_type=ctype,
                        content=b"".join(chunks),
                        headers={k.lower(): v for k, v in resp.headers.items()},
                    )
            except httpx.ProxyError as exc:
                raise EgressDenied(
                    "Outbound access to this host is blocked by the network egress policy.", code="egress_denied"
                ) from exc
            except httpx.TimeoutException as exc:
                raise FetchError("The request timed out.", code="timeout") from exc
            except httpx.TransportError as exc:
                raise FetchError(f"Network error: {type(exc).__name__}", code="network_error") from exc
        raise FetchError("Too many redirects.", code="too_many_redirects")


_robots_cache: dict[str, tuple[float, urllib.robotparser.RobotFileParser | None]] = {}


def _check_robots(url: str) -> None:
    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    now = datetime.now(UTC).timestamp()
    cached = _robots_cache.get(origin)
    parser: urllib.robotparser.RobotFileParser | None
    if cached and now - cached[0] < 3600:
        parser = cached[1]
    else:
        parser = None
        try:
            doc = fetch(f"{origin}/robots.txt", allowed_types=("text/plain", "text/html"), max_bytes=200_000)
            parser = urllib.robotparser.RobotFileParser()
            parser.parse(doc.text.splitlines())
        except EgressDenied:
            raise
        except FetchError:
            parser = None  # no readable robots.txt: treated as no restrictions
        _robots_cache[origin] = (now, parser)
    if parser is not None and not parser.can_fetch(get_settings().fetch_user_agent, url):
        raise RobotsDisallowed("The site's robots.txt does not allow automated access to this page.")


def clear_robots_cache() -> None:
    _robots_cache.clear()

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_TRACKING_PARAMS = {
    "fbclid",
    "gclid",
    "dclid",
    "msclkid",
    "mc_cid",
    "mc_eid",
    "ref",
    "ref_src",
    "source",
    "src",
    "igshid",
    "_hsenc",
    "_hsmi",
    "spm",
    "campaign",
}


def ensure_scheme(url: str) -> str:
    url = url.strip()
    if not url:
        return url
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://", url):
        return url
    if url.startswith("//"):
        return "https:" + url
    return "https://" + url


def canonicalize_url(url: str | None) -> str | None:
    """Normalise a URL for identity comparison.

    Lower-cases scheme/host, drops "www.", default ports, fragments, tracking
    parameters and trailing slashes, and sorts remaining query parameters.
    Returns None when the value is not a usable http(s) URL.
    """
    if not url or not url.strip():
        return None
    try:
        parts = urlsplit(ensure_scheme(url))
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        return None
    host = parts.hostname.lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    try:
        port = parts.port
    except ValueError:  # e.g. "javascript:alert(1)" read as host:port
        return None
    netloc = host if port in (None, 80, 443) else f"{host}:{port}"
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    query_pairs = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in _TRACKING_PARAMS and not k.lower().startswith("utm_")
    ]
    query = urlencode(sorted(query_pairs))
    # scheme is intentionally normalised to https for identity comparison
    return urlunsplit(("https", netloc, path, query, ""))


def display_url(url: str | None) -> str | None:
    """A cleaned URL that is safe to link to (keeps original scheme/host form)."""
    if not url or not url.strip():
        return None
    try:
        parts = urlsplit(ensure_scheme(url))
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        return None
    try:
        parts.port  # noqa: B018 - validates the port
    except ValueError:
        return None
    query_pairs = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in _TRACKING_PARAMS and not k.lower().startswith("utm_")
    ]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, urlencode(query_pairs), ""))


def is_safe_link(url: str | None) -> bool:
    """Used before rendering any externally supplied link."""
    if not url:
        return False
    try:
        return urlsplit(url.strip()).scheme.lower() in ("http", "https")
    except ValueError:
        return False

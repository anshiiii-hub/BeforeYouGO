"""Small in-process sliding-window rate limiter.

Limitation (documented): state is per process. Behind several workers, replace
the store with Redis. It still protects expensive endpoints on a single node.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable

from fastapi import Request

from app.core.config import get_settings
from app.core.errors import RateLimited

_lock = threading.Lock()
_hits: dict[str, deque[float]] = defaultdict(deque)


def reset_rate_limits() -> None:
    with _lock:
        _hits.clear()


def _client_key(request: Request) -> str:
    uid = getattr(request.state, "user_id", None)
    if uid:
        return f"u:{uid}"
    fwd = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    return f"ip:{fwd or (request.client.host if request.client else 'unknown')}"


def rate_limit(bucket: str, per_minute: Callable[[], int]) -> Callable[[Request], None]:
    def dependency(request: Request) -> None:
        limit = per_minute()
        key = f"{bucket}:{_client_key(request)}"
        now = time.monotonic()
        with _lock:
            q = _hits[key]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= limit:
                retry = max(1, int(60 - (now - q[0])))
                raise RateLimited(
                    f"Too many requests. Try again in about {retry} seconds.", code="rate_limited"
                )
            q.append(now)

    return dependency


expensive_limit = rate_limit("expensive", lambda: get_settings().rate_limit_per_minute_expensive)
auth_limit = rate_limit("auth", lambda: get_settings().rate_limit_per_minute_auth)

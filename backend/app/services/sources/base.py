from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from app.core.config import Settings, get_settings
from app.services.event_fields import NormalizedEvent
from app.services.safe_fetch import EgressDenied, FetchedDocument, FetchError

logger = logging.getLogger("byg.sources")


@dataclass
class RawRecord:
    source_event_id: str
    payload: dict[str, Any]
    source_url: str | None = None  # the URL this record was retrieved from
    event_url: str | None = None  # the event's own canonical URL, if the source provides it
    retrieved_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class FetchResult:
    records: list[RawRecord] = field(default_factory=list)
    # Complete means every intended document was retrieved successfully, so records that
    # are absent from this fetch can legitimately be flagged as no longer listed.
    complete: bool = False
    errors: list[dict[str, Any]] = field(default_factory=list)
    unchanged_documents: list[str] = field(default_factory=list)  # e.g. ETag 304: records stay as they are
    succeeded_documents: list[str] = field(default_factory=list)  # fetched (200 or 304): absence is meaningful here
    state_updates: dict[str, Any] = field(default_factory=dict)  # persisted into Source.config (e.g. ETags)
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SourceDescriptor:
    key: str
    name: str
    kind: str
    homepage: str | None
    access_method: str
    limitations: str
    rate_limit_note: str
    auth_requirement: str
    attribution: str
    terms_url: str | None = None
    license_note: str | None = None
    priority: int = 50


class SourceAdapter(ABC):
    """Common interface for every event source connector."""

    descriptor: SourceDescriptor

    @property
    def key(self) -> str:
        return self.descriptor.key

    def check_configured(self, settings: Settings) -> tuple[bool, str | None]:
        """Return (configured, reason-if-not)."""
        return True, None

    @abstractmethod
    def fetch(self, *, state: dict[str, Any], today: date) -> FetchResult:
        """Retrieve raw records. Must raise nothing for per-document failures: report them in errors."""

    @abstractmethod
    def normalize(self, raw: RawRecord) -> NormalizedEvent:
        """Map a raw record to the shared schema. Unknown values must stay unknown."""


Sleep = Callable[[float], None]


def retrying_fetch(
    fn: Callable[[], FetchedDocument],
    *,
    attempts: int | None = None,
    base_delay: float | None = None,
    sleep: Sleep = time.sleep,
    retryable_codes: tuple[str, ...] = ("timeout", "network_error", "http_429", "http_500", "http_502", "http_503", "http_504"),
) -> FetchedDocument:
    """Retry transient failures with exponential backoff. Policy denials are never retried."""
    settings = get_settings()
    attempts = attempts or settings.sync_max_attempts
    base_delay = settings.sync_backoff_base_seconds if base_delay is None else base_delay
    last: FetchError | None = None
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except EgressDenied:
            raise
        except FetchError as exc:
            last = exc
            if exc.code not in retryable_codes or attempt == attempts:
                raise
            delay = base_delay * (2 ** (attempt - 1))
            logger.info("retrying fetch after %s (attempt %s/%s, waiting %.1fs)", exc.code, attempt, attempts, delay)
            sleep(delay)
    assert last is not None
    raise last

"""Generic ICS (iCalendar) feed connector for operator-configured calendars."""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import UTC, date, datetime
from typing import Any

from icalendar import Calendar

from app.core.config import Settings
from app.services.event_fields import NormalizedEvent
from app.services.safe_fetch import EgressDenied, FetchError, fetch
from app.services.sources.base import (
    FetchResult,
    RawRecord,
    SourceAdapter,
    SourceDescriptor,
    retrying_fetch,
)
from app.services.taxonomy import classify_category, topics_from_text
from app.services.urls import display_url

logger = logging.getLogger("byg.sources.ics")
ICS_TYPES = ("text/calendar", "text/plain", "application/octet-stream", "application/ics")
_ONLINE_HINT = re.compile(r"\b(online|virtual|zoom|google meet|meet\.google|teams\.microsoft|webinar|livestream)\b", re.I)


def _plain(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _to_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


class IcsFeedAdapter(SourceAdapter):
    descriptor = SourceDescriptor(
        key="ics_feeds",
        name="Operator-configured ICS calendar feeds",
        kind="ics",
        homepage=None,
        access_method=(
            "Standard iCalendar (.ics) feeds listed in the ICS_FEED_URLS setting, for example an institution's "
            "published event calendar. Each VEVENT becomes one event; the feed URL is kept as provenance."
        ),
        limitations=(
            "Only feeds that an operator explicitly configures are read. Recurring events (RRULE) are imported "
            "as their first occurrence only. A feed rarely states fees or eligibility, so those stay unknown."
        ),
        rate_limit_note="One GET per feed per sync, with conditional requests when the server supports them.",
        auth_requirement="None for public feeds. Private/authenticated feeds are not supported.",
        attribution="Events attributed to the publisher of each configured feed.",
        terms_url=None,
        license_note="Operator is responsible for confirming each feed may be reused.",
        priority=70,
    )

    def __init__(self, urls: list[str] | None = None):
        self._urls = urls

    def urls(self, state: dict[str, Any], settings: Settings | None = None) -> list[str]:
        if self._urls is not None:
            return self._urls
        from app.core.config import get_settings

        configured = list(state.get("urls", []))
        for u in (settings or get_settings()).ics_feed_url_list:
            if u not in configured:
                configured.append(u)
        return configured

    def check_configured(self, settings: Settings) -> tuple[bool, str | None]:
        if self._urls or settings.ics_feed_url_list:
            return True, None
        return False, "No ICS feed URLs are configured (set ICS_FEED_URLS or add feeds in the admin console)."

    def fetch(self, *, state: dict[str, Any], today: date) -> FetchResult:
        result = FetchResult()
        urls = self.urls(state)
        if not urls:
            result.notes.append("No ICS feeds configured.")
            result.complete = False
            return result
        etags: dict[str, str] = dict(state.get("etags", {}))
        failures = 0
        for url in urls:
            headers = {"If-None-Match": etags[url]} if url in etags else {}
            try:
                doc = retrying_fetch(lambda url=url, headers=headers: fetch(url, allowed_types=ICS_TYPES, extra_headers=headers))
            except EgressDenied as exc:
                failures += 1
                result.errors.append({"document": url, "code": exc.code, "message": exc.message})
                continue
            except FetchError as exc:
                failures += 1
                result.errors.append({"document": url, "code": exc.code, "message": exc.message})
                continue
            if doc.status_code == 304:
                result.unchanged_documents.append(url)
                result.succeeded_documents.append(url)
                continue
            try:
                cal = Calendar.from_ical(doc.content)
            except Exception as exc:  # icalendar raises several types for malformed input
                failures += 1
                result.errors.append({"document": url, "code": "invalid_ics", "message": str(exc)[:200]})
                continue
            result.succeeded_documents.append(url)
            if doc.headers.get("etag"):
                etags[url] = doc.headers["etag"]
            for comp in cal.walk("VEVENT"):
                uid = _plain(comp.get("UID"))
                summary = _plain(comp.get("SUMMARY"))
                if not summary:
                    continue
                dtstart = comp.get("DTSTART")
                dtend = comp.get("DTEND")
                start_val = dtstart.dt if dtstart is not None else None
                end_val = dtend.dt if dtend is not None else None
                organizer = comp.get("ORGANIZER")
                payload: dict[str, Any] = {
                    "_file": url,
                    "uid": uid,
                    "summary": summary,
                    "description": _plain(comp.get("DESCRIPTION")),
                    "location": _plain(comp.get("LOCATION")),
                    "url": _plain(comp.get("URL")),
                    "status": _plain(comp.get("STATUS")),
                    "categories": _categories(comp.get("CATEGORIES")),
                    "start": start_val.isoformat() if start_val is not None else None,
                    "start_is_datetime": isinstance(start_val, datetime),
                    "end": end_val.isoformat() if end_val is not None else None,
                    "end_is_datetime": isinstance(end_val, datetime),
                    "organizer_name": _plain(getattr(organizer, "params", {}).get("CN")) if organizer is not None else None,
                    "organizer_value": _plain(organizer) if organizer is not None else None,
                    "has_rrule": comp.get("RRULE") is not None,
                }
                key = uid or hashlib.sha1(f"{summary}|{payload['start']}".encode()).hexdigest()[:24]
                result.records.append(
                    RawRecord(source_event_id=f"{hashlib.sha1(url.encode()).hexdigest()[:8]}:{key}", payload=payload, source_url=url, event_url=payload["url"], retrieved_at=doc.fetched_at)
                )
        result.state_updates["etags"] = etags
        result.complete = failures == 0
        return result

    def normalize(self, raw: RawRecord) -> NormalizedEvent:
        p = raw.payload
        n = NormalizedEvent(source_event_id=raw.source_event_id, title=p["summary"], source_url=raw.source_url)
        n.set("title", p["summary"])
        n.set("description", p.get("description"))
        n.set("canonical_url", display_url(p.get("url")))
        start = _parse(p.get("start"), p.get("start_is_datetime"))
        end = _parse(p.get("end"), p.get("end_is_datetime"))
        n.set("start_date", _to_date(start))
        # In all-day ICS events DTEND is exclusive (the day after the last day).
        end_date = _to_date(end)
        if end_date and start and not p.get("end_is_datetime") and _to_date(start) and end_date > _to_date(start):  # type: ignore[operator]
            from datetime import timedelta

            end_date = end_date - timedelta(days=1)
        n.set("end_date", end_date)
        if isinstance(start, datetime) and start.tzinfo is not None:
            n.set("start_at", start.astimezone(UTC))
        if isinstance(end, datetime) and end.tzinfo is not None:
            n.set("end_at", end.astimezone(UTC))
        location = p.get("location")
        n.set("venue", location)
        if location and _ONLINE_HINT.search(location):
            n.set("format", "online", "derived")
        status = (p.get("status") or "").upper()
        if status == "CANCELLED":
            n.set("lifecycle_status", "cancelled")
        elif status in ("CONFIRMED", "TENTATIVE", ""):
            n.set("lifecycle_status", "scheduled", "derived")
        n.set("organizer_name", p.get("organizer_name"))
        org_val = p.get("organizer_value") or ""
        if org_val.lower().startswith("mailto:"):
            n.set("contact_info", org_val[7:])
        cats = p.get("categories") or []
        n.set("tags", [{"key": "category", "value": c} for c in cats])
        text = f"{p['summary']} {' '.join(cats)} {p.get('description') or ''}"
        n.set("topics", sorted(set(topics_from_text(text))), "derived")
        n.set("category", classify_category(p["summary"], " ".join(cats) + " " + (p.get("description") or ""), default="other"), "derived")
        if p.get("has_rrule"):
            n.extras["recurring"] = True
        n.extraction_confidence = 0.85 if p.get("start") else 0.5
        return n


def _categories(value: Any) -> list[str]:
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    out: list[str] = []
    for item in items:
        cats = getattr(item, "cats", None)
        if cats is not None:
            out.extend(str(c) for c in cats)
        else:
            out.append(str(item))
    return [c.strip() for c in out if c and c.strip()]


def _parse(value: str | None, is_datetime: bool | None) -> datetime | date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value) if is_datetime else date.fromisoformat(value)
    except ValueError:
        return None

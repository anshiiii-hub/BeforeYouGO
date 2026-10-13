"""Organizer-published event pages: structured data (schema.org Event JSON-LD).

Used when an organizer connects a canonical URL or a person submits a public event
URL. Only structured data that the page itself publishes is read; robots.txt is
honoured; nothing is inferred from marketing copy here (that is the Promise
Analyzer's job and is labelled as AI/deterministic extraction).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from bs4 import BeautifulSoup

from app.services.event_fields import NormalizedEvent
from app.services.geo import canonical_city, canonical_country
from app.services.safe_fetch import FetchError, fetch
from app.services.sources.base import (
    FetchResult,
    RawRecord,
    SourceAdapter,
    SourceDescriptor,
    retrying_fetch,
)
from app.services.taxonomy import classify_category, topics_from_text
from app.services.urls import canonicalize_url, display_url

logger = logging.getLogger("byg.sources.pages")
HTML_TYPES = ("text/html", "application/xhtml+xml", "text/plain")


def _walk_jsonld(node: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if isinstance(node, list):
        for item in node:
            out.extend(_walk_jsonld(item))
    elif isinstance(node, dict):
        types = node.get("@type")
        type_list = types if isinstance(types, list) else [types]
        if any(isinstance(t, str) and t.endswith("Event") for t in type_list):
            out.append(node)
        for key in ("@graph", "subEvent", "event"):
            if key in node:
                out.extend(_walk_jsonld(node[key]))
    return out


def extract_jsonld_events(html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    found: list[dict[str, Any]] = []
    for tag in soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
        text = tag.string or tag.get_text() or ""
        try:
            data = json.loads(text)
        except ValueError:
            continue
        found.extend(_walk_jsonld(data))
    return found


def extract_open_graph(html: str) -> dict[str, str]:
    soup = BeautifulSoup(html, "lxml")
    og: dict[str, str] = {}
    for meta in soup.find_all("meta"):
        prop = meta.get("property") or meta.get("name")
        content = meta.get("content")
        if prop and content and (str(prop).startswith("og:") or prop in ("description", "twitter:title")):
            og[str(prop)] = str(content).strip()
    title = soup.find("title")
    if title and title.get_text(strip=True):
        og.setdefault("title", title.get_text(strip=True))
    return og


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        return _as_text(value.get("name") or value.get("@id") or value.get("url"))
    if isinstance(value, list) and value:
        return _as_text(value[0])
    return str(value)


def _parse_dt(value: Any) -> tuple[date | None, datetime | None]:
    text = _as_text(value)
    if not text:
        return None, None
    try:
        if len(text) <= 10:
            return date.fromisoformat(text), None
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None, None
    if dt.tzinfo is None:
        return dt.date(), None  # no timezone stated: keep only the date, do not guess a zone
    return dt.date(), dt.astimezone(UTC)


class EventPageAdapter(SourceAdapter):
    descriptor = SourceDescriptor(
        key="event_pages",
        name="Organizer and user-submitted event pages",
        kind="jsonld",
        homepage=None,
        access_method=(
            "Fetches a public event page through the SSRF-safe fetcher (robots.txt honoured) and reads its "
            "schema.org Event JSON-LD. URLs come from organizers connecting a canonical URL or from people "
            "submitting a link; known URLs are re-checked on each scheduled sync."
        ),
        limitations=(
            "Works only for pages that publish structured data and are reachable from this deployment's "
            "network. Pages without JSON-LD yield a low-confidence record (title/description only)."
        ),
        rate_limit_note="One GET per page per sync; robots.txt consulted and cached for an hour.",
        auth_requirement="None. Pages behind login are not retrieved.",
        attribution="Attributed to the page's own domain.",
        license_note="Only facts are stored; the original page remains the canonical source.",
        priority=80,
    )

    def fetch(self, *, state: dict[str, Any], today: date) -> FetchResult:
        result = FetchResult()
        urls: list[str] = list(state.get("urls", []))
        if not urls:
            result.notes.append("No event pages have been connected yet.")
            return result
        failures = 0
        for url in urls:
            try:
                records = self.fetch_page(url)
            except FetchError as exc:
                failures += 1
                result.errors.append({"document": url, "code": exc.code, "message": exc.message})
                continue
            result.succeeded_documents.append(url)
            result.records.extend(records)
        result.complete = failures == 0
        return result

    def fetch_page(self, url: str) -> list[RawRecord]:
        doc = retrying_fetch(lambda: fetch(url, allowed_types=HTML_TYPES, respect_robots=True, max_bytes=3_000_000))
        html = doc.text
        events = extract_jsonld_events(html)
        records: list[RawRecord] = []
        for idx, ev in enumerate(events):
            name = _as_text(ev.get("name"))
            if not name:
                continue
            canon = canonicalize_url(_as_text(ev.get("url")) or doc.final_url) or doc.final_url
            sid = hashlib.sha1(f"{canon}|{name}|{_as_text(ev.get('startDate')) or idx}".encode()).hexdigest()[:24]
            records.append(
                RawRecord(
                    source_event_id=sid,
                    payload={"_file": url, "kind": "jsonld", "event": ev, "page_url": doc.final_url},
                    source_url=doc.final_url,
                    event_url=_as_text(ev.get("url")) or doc.final_url,
                    retrieved_at=doc.fetched_at,
                )
            )
        if not records:
            og = extract_open_graph(html)
            title = og.get("og:title") or og.get("title")
            if title:
                sid = hashlib.sha1(f"{doc.final_url}|{title}".encode()).hexdigest()[:24]
                records.append(
                    RawRecord(
                        source_event_id=sid,
                        payload={"_file": url, "kind": "opengraph", "og": og, "page_url": doc.final_url},
                        source_url=doc.final_url,
                        event_url=doc.final_url,
                        retrieved_at=doc.fetched_at,
                    )
                )
        return records

    def normalize(self, raw: RawRecord) -> NormalizedEvent:
        p = raw.payload
        if p.get("kind") == "opengraph":
            og = p["og"]
            title = og.get("og:title") or og.get("title") or "Untitled page"
            n = NormalizedEvent(source_event_id=raw.source_event_id, title=title, source_url=raw.source_url)
            n.set("title", title)
            n.set("description", og.get("og:description") or og.get("description"))
            n.set("canonical_url", display_url(og.get("og:url") or p.get("page_url")))
            n.set("topics", sorted(set(topics_from_text(title))), "derived")
            n.set("category", classify_category(title), "derived")
            n.extraction_confidence = 0.35
            n.extras["note"] = "Page had no structured event data; only its title/description were read."
            return n

        ev = p["event"]
        title = _as_text(ev.get("name")) or "Untitled event"
        n = NormalizedEvent(source_event_id=raw.source_event_id, title=title, source_url=raw.source_url)
        n.set("title", title)
        n.set("description", _as_text(ev.get("description")))
        n.set("canonical_url", display_url(_as_text(ev.get("url")) or p.get("page_url")))
        sd, sat = _parse_dt(ev.get("startDate"))
        ed, eat = _parse_dt(ev.get("endDate"))
        n.set("start_date", sd)
        n.set("end_date", ed)
        n.set("start_at", sat)
        n.set("end_at", eat)
        org = ev.get("organizer")
        n.set("organizer_name", _as_text(org))
        if isinstance(org, dict):
            n.set("organizer_url", display_url(_as_text(org.get("url"))))

        mode = (_as_text(ev.get("eventAttendanceMode")) or "").lower()
        loc = ev.get("location")
        locs = loc if isinstance(loc, list) else [loc] if loc else []
        has_place = any(isinstance(item, dict) and str(item.get("@type", "")).lower() == "place" for item in locs)
        has_virtual = any(isinstance(item, dict) and "virtual" in str(item.get("@type", "")).lower() for item in locs)
        if "mixed" in mode or (has_place and has_virtual):
            n.set("format", "hybrid")
        elif "online" in mode or (has_virtual and not has_place):
            n.set("format", "online")
        elif "offline" in mode or has_place:
            n.set("format", "offline")
        for item in locs:
            if isinstance(item, dict) and str(item.get("@type", "")).lower() == "place":
                n.set("venue", _as_text(item.get("name")))
                addr = item.get("address")
                if isinstance(addr, dict):
                    n.set("city", canonical_city(_as_text(addr.get("addressLocality"))))
                    n.set("state", _as_text(addr.get("addressRegion")))
                    n.set("country", canonical_country(_as_text(addr.get("addressCountry"))))
                elif isinstance(addr, str):
                    n.set("venue", f"{_as_text(item.get('name')) or ''} {addr}".strip())
                break

        status = (_as_text(ev.get("eventStatus")) or "").lower()
        if "cancel" in status:
            n.set("lifecycle_status", "cancelled")
        elif "postpone" in status:
            n.set("lifecycle_status", "postponed")
        else:
            n.set("lifecycle_status", "scheduled", "derived")

        self._offers(n, ev.get("offers"))
        text = f"{title} {_as_text(ev.get('description')) or ''}"
        n.set("topics", sorted(set(topics_from_text(text))), "derived")
        n.set("category", classify_category(title, _as_text(ev.get("description")) or ""), "derived")
        n.set("registration_url", display_url(_first_offer_url(ev.get("offers"))))
        n.extraction_confidence = 0.8 if sd else 0.5
        return n

    @staticmethod
    def _offers(n: NormalizedEvent, offers: Any) -> None:
        items = offers if isinstance(offers, list) else [offers] if offers else []
        prices: list[Decimal] = []
        currency: str | None = None
        for o in items:
            if not isinstance(o, dict) or o.get("price") in (None, ""):
                continue
            try:
                prices.append(Decimal(str(o["price"]).replace(",", "")))
            except InvalidOperation:
                continue
            currency = currency or _as_text(o.get("priceCurrency"))
        if not prices:
            return  # no stated price: cost stays unknown, never "free"
        if all(p == 0 for p in prices):
            n.set("fee_status", "free")
        else:
            n.set("fee_status", "paid")
            n.set("fee_amount", min(p for p in prices if p > 0))
            n.set("fee_currency", (currency or "").upper() or None)


def _first_offer_url(offers: Any) -> str | None:
    items = offers if isinstance(offers, list) else [offers] if offers else []
    for o in items:
        if isinstance(o, dict) and o.get("url"):
            return str(o["url"])
    return None

"""Connectors for community-maintained conference datasets published on GitHub.

Both connectors read public JSON files from raw.githubusercontent.com. They are the
integrations that were verified against live data in this environment.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.services.event_fields import NormalizedEvent
from app.services.geo import canonical_city, canonical_country
from app.services.safe_fetch import EgressDenied, FetchError, fetch
from app.services.sources.base import (
    FetchResult,
    RawRecord,
    SourceAdapter,
    SourceDescriptor,
    retrying_fetch,
)
from app.services.taxonomy import classify_category, topics_from_text
from app.services.urls import canonicalize_url, display_url

logger = logging.getLogger("byg.sources.github")
JSON_TYPES = ("text/plain", "application/json", "application/octet-stream")


def _stable_id(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:24]


def _parse_iso_date(value: Any) -> date | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def _epoch_ms_to_date(value: Any) -> date | None:
    if not isinstance(value, int | float):
        return None
    try:
        return datetime.fromtimestamp(value / 1000, UTC).date()
    except (OverflowError, OSError, ValueError):
        return None


def _confidence(n: NormalizedEvent) -> float:
    """Transparent formula: start from 1.0 and subtract for each missing core field."""
    score = 1.0
    if "canonical_url" not in n.values:
        score -= 0.25
    if "start_date" not in n.values:
        score -= 0.3
    if "city" not in n.values and n.values.get("format") != "online":
        score -= 0.1
    score -= 0.05 * sum(1 for o in n.origins.values() if o == "derived")
    return round(max(0.1, score), 2)


class TechConferencesAdapter(SourceAdapter):
    BASE = "https://raw.githubusercontent.com/tech-conferences/conference-data/main/conferences"
    # Topic files documented in the repository README (a missing file is simply skipped).
    TOPICS = (
        "general", "javascript", "typescript", "css", "data", "devops", "security", "python", "java", "php",
        "ruby", "rust", "golang", "scala", "clojure", "elixir", "elm", "groovy", "haskell", "dotnet", "android",
        "ios", "iot", "ux", "accessibility", "api", "graphql", "identity", "leadership", "performance",
        "product", "tech-comm", "testing", "kotlin", "cpp", "ai",
    )

    descriptor = SourceDescriptor(
        key="tech_conferences",
        name="confs.tech conference data (GitHub)",
        kind="github_json",
        homepage="https://github.com/tech-conferences/conference-data",
        access_method=(
            "Public per-topic, per-year JSON files read from raw.githubusercontent.com "
            "(conferences/<year>/<topic>.json). Conditional requests (ETag) keep refreshes incremental."
        ),
        limitations=(
            "Technology conferences only: no hackathons, internships or competitions. Records carry name, "
            "URL, dates, city/country, online flag and CFP details. They do not carry fees, descriptions, "
            "eligibility or registration deadlines, so those fields stay unknown."
        ),
        rate_limit_note="Unauthenticated raw.githubusercontent.com. One conditional GET per topic file per year per sync.",
        auth_requirement="None.",
        attribution="Data from the confs.tech community dataset (tech-conferences/conference-data on GitHub).",
        terms_url="https://github.com/tech-conferences/conference-data",
        license_note="MIT licence (LICENSE.md in the repository).",
        priority=60,
    )

    def __init__(self, topics: tuple[str, ...] | None = None, years: tuple[int, ...] | None = None):
        self.topics = topics or self.TOPICS
        self.years = years

    def fetch(self, *, state: dict[str, Any], today: date) -> FetchResult:
        result = FetchResult()
        etags: dict[str, str] = dict(state.get("etags", {}))
        failures = 0
        years = self.years or (today.year, today.year + 1)
        for year in years:
            for topic in self.topics:
                doc_key = f"{year}/{topic}"
                url = f"{self.BASE}/{year}/{topic}.json"
                headers = {"If-None-Match": etags[doc_key]} if doc_key in etags else {}
                try:
                    doc = retrying_fetch(lambda url=url, headers=headers: fetch(url, allowed_types=JSON_TYPES, extra_headers=headers))
                except EgressDenied as exc:
                    result.errors.append({"document": doc_key, "code": exc.code, "message": exc.message})
                    result.notes.append("Network egress policy blocks this host; stopping early.")
                    return result
                except FetchError as exc:
                    if exc.code == "http_404":
                        continue  # not every topic has a file for every year
                    failures += 1
                    result.errors.append({"document": doc_key, "code": exc.code, "message": exc.message})
                    continue
                if doc.status_code == 304:
                    result.unchanged_documents.append(doc_key)
                    result.succeeded_documents.append(doc_key)
                    continue
                try:
                    items = json.loads(doc.text)
                    if not isinstance(items, list):
                        raise ValueError("expected a JSON array")
                except ValueError as exc:
                    failures += 1
                    result.errors.append({"document": doc_key, "code": "invalid_json", "message": str(exc)})
                    continue
                result.succeeded_documents.append(doc_key)
                if doc.headers.get("etag"):
                    etags[doc_key] = doc.headers["etag"]
                for item in items:
                    if not isinstance(item, dict) or not item.get("name"):
                        continue
                    canon = canonicalize_url(item.get("url")) or ""
                    sid = f"{topic}:{_stable_id(canon or item['name'], str(item.get('startDate', '')))}"
                    payload = dict(item)
                    payload["_file"] = doc_key
                    payload["_topic"] = topic
                    result.records.append(
                        RawRecord(source_event_id=sid, payload=payload, source_url=url, event_url=item.get("url"), retrieved_at=doc.fetched_at)
                    )
        result.state_updates["etags"] = etags
        result.complete = failures == 0
        return result

    def normalize(self, raw: RawRecord) -> NormalizedEvent:
        p = raw.payload
        n = NormalizedEvent(source_event_id=raw.source_event_id, title=str(p["name"]).strip(), source_url=raw.source_url)
        n.set("title", str(p["name"]).strip())
        url = display_url(p.get("url"))
        n.set("canonical_url", url)
        n.set("start_date", _parse_iso_date(p.get("startDate")))
        n.set("end_date", _parse_iso_date(p.get("endDate")))
        city = canonical_city(p.get("city"))
        n.set("city", city, "derived" if city and city != str(p.get("city", "")).strip() else "source")
        n.set("country", canonical_country(p.get("country")))
        online = p.get("online")
        if online is True and city:
            n.set("format", "hybrid", "derived")
        elif online is True:
            n.set("format", "online", "derived")
        elif online is False and city:
            n.set("format", "offline", "derived")
        topic = p.get("_topic")
        topic_keys = topics_from_text(f"{p['name']} {topic or ''}")
        if topic and topic != "general":
            topic_keys = sorted(set(topic_keys) | set(topics_from_text(str(topic).replace("-", " "))))
        n.set("topics", sorted(set(topic_keys)), "derived")
        n.set("tags", [{"key": "topic", "value": topic}] if topic else None)
        n.set("category", classify_category(str(p["name"]), default="conference"), "derived")
        n.set("lifecycle_status", "scheduled", "derived")

        cfp: dict[str, Any] = {}
        if p.get("cfpUrl"):
            cfp["url"] = p["cfpUrl"]
        if p.get("cfpEndDate"):
            cfp["until"] = p["cfpEndDate"]
        if cfp:
            # A call-for-papers deadline is for SPEAKERS. It is deliberately not a registration deadline.
            n.extras["cfp"] = cfp
        for key in ("cocUrl", "twitter", "bluesky", "mastodon", "locales", "discountCode"):
            if p.get(key):
                n.extras[key] = p[key]

        if p.get("offersSignLanguageOrCC") is True:
            n.accessibility["captioning_interpretation"] = {
                "state": "documented",
                "detail": "The source dataset flags this event as offering sign language interpretation or closed captions.",
                "excerpt": 'offersSignLanguageOrCC: true',
                "evidence_url": raw.source_url,
            }
            n.field_claims.append(
                {
                    "original_text": "offersSignLanguageOrCC: true",
                    "normalized_text": "The organizer offers sign language interpretation or closed captions.",
                    "category": "accessibility",
                    "claim_type": "specific",
                    "evidence_url": raw.source_url,
                    "missing_details": ["Which sessions are covered", "Language(s) of interpretation or captions"],
                    "verification_questions": ["Which sessions have captions or sign-language interpretation, and how can attendees request them?"],
                }
            )
        n.extraction_confidence = _confidence(n)
        return n


class DevelopersEventsAdapter(SourceAdapter):
    """developers.events (scraly/developers-conferences-agenda) combined event list."""

    URL = "https://raw.githubusercontent.com/scraly/developers-conferences-agenda/gh-pages/all-events.json"
    LOOKBACK_DAYS = 60
    MAX_BYTES = 25_000_000

    descriptor = SourceDescriptor(
        key="developers_events",
        name="developers.events calendar (GitHub)",
        kind="github_json",
        homepage="https://github.com/scraly/developers-conferences-agenda",
        access_method=(
            "The repository publishes its complete event list as JSON on its gh-pages branch, read through "
            "raw.githubusercontent.com. (The same data is advertised at developers.events/all-events.json; "
            "BeforeYouGo reads the GitHub copy.) Conditional requests (ETag) keep refreshes incremental."
        ),
        limitations=(
            "Developer conferences only. Records carry name, link, dates, city/country, tags and CFP data. "
            "No fees, descriptions, eligibility or registration deadlines. Dates are whole days (no times). "
            "No licence file was found at the repository root, so BeforeYouGo stores only the factual "
            "fields it needs and links back to the source rather than republishing the dataset."
        ),
        rate_limit_note="Unauthenticated raw.githubusercontent.com. One conditional GET (a few MB) per sync.",
        auth_requirement="None.",
        attribution="Event listing data from developers.events (scraly/developers-conferences-agenda).",
        terms_url="https://github.com/scraly/developers-conferences-agenda",
        license_note="Licence not confirmed at the repository root; attribution and a link to the source are always shown.",
        priority=50,
    )

    def __init__(self, url: str | None = None, lookback_days: int | None = None):
        self.url = url or self.URL
        self.lookback_days = lookback_days if lookback_days is not None else self.LOOKBACK_DAYS

    def fetch(self, *, state: dict[str, Any], today: date) -> FetchResult:
        result = FetchResult()
        etags: dict[str, str] = dict(state.get("etags", {}))
        doc_key = "all-events"
        headers = {"If-None-Match": etags[doc_key]} if doc_key in etags else {}
        try:
            doc = retrying_fetch(
                lambda: fetch(self.url, allowed_types=JSON_TYPES, max_bytes=self.MAX_BYTES, extra_headers=headers)
            )
        except FetchError as exc:
            result.errors.append({"document": doc_key, "code": exc.code, "message": exc.message})
            return result
        if doc.status_code == 304:
            result.unchanged_documents.append(doc_key)
            result.succeeded_documents.append(doc_key)
            result.complete = True
            return result
        try:
            items = json.loads(doc.text)
            if not isinstance(items, list):
                raise ValueError("expected a JSON array")
        except ValueError as exc:
            result.errors.append({"document": doc_key, "code": "invalid_json", "message": str(exc)})
            return result
        result.succeeded_documents.append(doc_key)
        if doc.headers.get("etag"):
            etags[doc_key] = doc.headers["etag"]
        result.state_updates["etags"] = etags
        cutoff = today - timedelta(days=self.lookback_days)
        kept = 0
        for item in items:
            if not isinstance(item, dict) or not item.get("name"):
                continue
            dates = item.get("date") or []
            end = _epoch_ms_to_date(dates[-1]) if dates else None
            if end is None or end < cutoff:
                continue
            canon = canonicalize_url(item.get("hyperlink")) or ""
            start = _epoch_ms_to_date(dates[0])
            sid = _stable_id(canon or str(item["name"]), start.isoformat() if start else "")
            payload = dict(item)
            payload["_file"] = doc_key
            result.records.append(
                RawRecord(source_event_id=sid, payload=payload, source_url=self.url, event_url=item.get("hyperlink"), retrieved_at=doc.fetched_at)
            )
            kept += 1
        result.notes.append(f"Kept {kept} of {len(items)} listed events (ended no earlier than {cutoff.isoformat()}).")
        result.complete = True
        return result

    def normalize(self, raw: RawRecord) -> NormalizedEvent:
        p = raw.payload
        title = str(p["name"]).strip()
        n = NormalizedEvent(source_event_id=raw.source_event_id, title=title, source_url=raw.source_url)
        n.set("title", title)
        n.set("canonical_url", display_url(p.get("hyperlink")))
        dates = p.get("date") or []
        if dates:
            n.set("start_date", _epoch_ms_to_date(dates[0]))
            n.set("end_date", _epoch_ms_to_date(dates[-1]))
        city = canonical_city(p.get("city"))
        n.set("city", city, "derived" if city and city != str(p.get("city", "")).strip() else "source")
        n.set("country", canonical_country(p.get("country")))
        location = str(p.get("location") or "")
        status = str(p.get("status") or "open").strip()
        low_status = status.lower()
        if location.strip().lower() == "online" or low_status == "virtualized":
            n.set("format", "online", "derived")
        elif city:
            n.set("format", "offline", "derived")
        if "cancel" in low_status:
            n.set("lifecycle_status", "cancelled", "derived")
        elif "postpone" in low_status or "delay" in low_status:
            n.set("lifecycle_status", "postponed", "derived")
        else:
            n.set("lifecycle_status", "scheduled", "derived")

        tags: list[dict[str, str]] = []
        languages: list[str] = []
        for t in p.get("tags") or []:
            if isinstance(t, dict) and t.get("value"):
                tags.append({"key": str(t.get("key", "tag")), "value": str(t["value"])})
                if t.get("key") == "language":
                    languages.append(str(t["value"]))
        n.set("tags", tags)
        tag_text = " ".join(t["value"].replace("-", " ") for t in tags if t["key"] != "language")
        n.set("topics", sorted(set(topics_from_text(f"{title} {tag_text}"))), "derived")
        n.set("category", classify_category(title, tag_text, default="conference"), "derived")

        cfp = p.get("cfp") or {}
        if isinstance(cfp, dict) and cfp:
            until = _epoch_ms_to_date(cfp.get("untilDate"))
            n.extras["cfp"] = {k: v for k, v in {"url": cfp.get("link"), "until": until.isoformat() if until else cfp.get("until")}.items() if v}
        if languages:
            n.extras["languages"] = languages
        if isinstance(p.get("attendees"), int | float):
            n.extras["expected_attendees"] = int(p["attendees"])
        if p.get("sponsoring"):
            n.extras["sponsoring_url"] = p["sponsoring"]
        if status and low_status != "open":
            n.extras["source_status"] = status

        if p.get("closedCaptions") is True:
            n.accessibility["captioning_interpretation"] = {
                "state": "documented",
                "detail": "The source dataset flags this event as offering closed captions.",
                "excerpt": "closedCaptions: true",
                "evidence_url": raw.source_url,
            }
            n.field_claims.append(
                {
                    "original_text": "closedCaptions: true",
                    "normalized_text": "The organizer offers closed captions.",
                    "category": "accessibility",
                    "claim_type": "specific",
                    "evidence_url": raw.source_url,
                    "missing_details": ["Which sessions are captioned", "Whether captions are live or post-event"],
                    "verification_questions": ["Which sessions will have closed captions, and are they live?"],
                }
            )
        if p.get("scholarship") is True:
            n.field_claims.append(
                {
                    "original_text": "scholarship: true",
                    "normalized_text": "The organizer offers a scholarship or diversity ticket programme.",
                    "category": "scholarship_discount",
                    "claim_type": "vague",
                    "evidence_url": raw.source_url,
                    "missing_details": ["Eligibility criteria", "Application deadline", "What the scholarship covers"],
                    "verification_questions": ["Who is eligible for the scholarship, what does it cover, and when is the application deadline?"],
                }
            )
        n.extraction_confidence = _confidence(n)
        return n

"""Ingestion core: dedupe, field-level provenance, merging, versioning and change detection.

Invariants
* A source record is stored verbatim (``raw``) and only refreshed, never rewritten.
* Every event field value is *derived* from current ``EventFieldAssertion`` rows. Nothing is
  copied onto ``events`` without an assertion that says who supplied it and when.
* Precedence per field: manual correction > organizer > connector priority > newest retrieval.
  Disagreeing sources are preserved and exposed as conflicts, never silently dropped.
* Unknown stays unknown: a field no assertion supplies is reset to its default / NULL.
* Fuzzy matches create review candidates; only exact identity (same canonical URL with
  compatible dates, or same title + date + place) merges automatically.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from rapidfuzz import fuzz
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.enums import ExtractionMethod, FieldOrigin, Lifecycle, OriginType
from app.models import (
    AccessibilityItem,
    DuplicateCandidate,
    Event,
    EventFieldAssertion,
    EventVersion,
    Source,
    SourceRecord,
)
from app.models.base import utcnow
from app.services.claims import create_claim
from app.services.event_fields import (
    DEFAULT_WHEN_UNASSERTED,
    FIELD_SPECS,
    NormalizedEvent,
    decode_value,
    encode_value,
    jsonable,
)
from app.services.sources.base import RawRecord, SourceAdapter
from app.services.urls import canonicalize_url

ORIGIN_RANK = {FieldOrigin.MANUAL.value: 10_000, FieldOrigin.ORGANIZER.value: 9_000}
AUTO_MERGE_URL_WINDOW_DAYS = 45


@dataclass
class IngestOutcome:
    kind: str  # created / updated / unchanged
    event_id: uuid.UUID
    version_created: bool = False


# ------------------------------------------------------------------ helpers


def norm_title(title: str) -> str:
    t = re.sub(r"[^a-z0-9 ]+", " ", title.lower())
    t = re.sub(r"\b(20\d\d|\d{1,2}(st|nd|rd|th)|edition|the)\b", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def content_hash(payload: dict[str, Any]) -> str:
    stable = {k: v for k, v in payload.items() if not k.startswith("_")}
    return hashlib.sha256(json.dumps(stable, sort_keys=True, default=str).encode()).hexdigest()


def event_snapshot(event: Event) -> dict[str, Any]:
    return {name: jsonable(getattr(event, name)) for name in FIELD_SPECS}


def _flatten_tags(tags: Any) -> str | None:
    if not isinstance(tags, list):
        return None
    parts = []
    for t in tags:
        if isinstance(t, dict):
            parts.append(str(t.get("value") or t.get("key") or ""))
        else:
            parts.append(str(t))
    text = " ".join(p for p in parts if p).strip()
    return text or None


def _rank(a: EventFieldAssertion, sources: dict[uuid.UUID, Source]) -> tuple[int, datetime]:
    base = ORIGIN_RANK.get(a.origin)
    if base is None:
        src = sources.get(a.source_id) if a.source_id else None
        base = src.priority if src else 0
    return base, a.retrieved_at


# ------------------------------------------------------------------ merge


def recompute_event(
    db: Session,
    event: Event,
    *,
    change_source: str,
    actor_id: uuid.UUID | None = None,
    force_version: bool = False,
) -> EventVersion | None:
    """Rebuild the event row from current assertions and append a version when anything changed."""
    assertions = list(
        db.scalars(
            select(EventFieldAssertion).where(
                EventFieldAssertion.event_id == event.id, EventFieldAssertion.is_current.is_(True)
            )
        )
    )
    source_ids = {a.source_id for a in assertions if a.source_id}
    sources = {s.id: s for s in db.scalars(select(Source).where(Source.id.in_(source_ids)))} if source_ids else {}
    by_field: dict[str, list[EventFieldAssertion]] = defaultdict(list)
    for a in assertions:
        if a.field_name in FIELD_SPECS:
            by_field[a.field_name].append(a)

    before = event_snapshot(event) if event.title is not None else {}
    for name in FIELD_SPECS:
        lst = by_field.get(name)
        if lst:
            best = max(lst, key=lambda a: _rank(a, sources))
            value = decode_value(name, best.value)
        else:
            value = DEFAULT_WHEN_UNASSERTED.get(name)
            if isinstance(value, list | dict):
                value = type(value)()
        setattr(event, name, value)
    if event.extras.get("removed_since") and event.lifecycle_status not in (
        Lifecycle.CANCELLED.value,
        Lifecycle.POSTPONED.value,
    ):
        event.lifecycle_status = Lifecycle.REMOVED_FROM_SOURCE.value
    event.canonical_url_norm = canonicalize_url(event.canonical_url)
    event.tags_text = _flatten_tags(event.tags)
    event.last_updated_at = utcnow()
    after = event_snapshot(event)

    diff = {k: [before.get(k), after[k]] for k in after if before and before.get(k) != after[k]}
    last_no = db.scalar(select(func.max(EventVersion.version_no)).where(EventVersion.event_id == event.id)) or 0
    if last_no and not diff and not force_version:
        return None
    material_fields = [k for k in diff if FIELD_SPECS[k].material]
    if last_no == 0:
        summary = "Initial record created."
        material = False
        diff = {}
    else:
        labels = [FIELD_SPECS[k].label for k in diff]
        summary = "Changed: " + ", ".join(labels) + "." if labels else "Re-saved without field changes."
        material = bool(material_fields)
        if material:
            summary += " Material fields: " + ", ".join(FIELD_SPECS[k].label for k in material_fields) + "."
    version = EventVersion(
        event_id=event.id,
        version_no=last_no + 1,
        changed_by=actor_id,
        change_source=change_source,
        snapshot=after,
        diff=diff,
        is_material=material,
        summary=summary,
    )
    db.add(version)
    db.flush()
    return version


def assert_fields(
    db: Session,
    event: Event,
    values: dict[str, Any],
    origins: dict[str, str],
    *,
    source: Source | None,
    record: SourceRecord | None,
    source_url: str | None,
    actor_id: uuid.UUID | None = None,
    default_origin: str = FieldOrigin.SOURCE.value,
    retrieved_at: datetime | None = None,
    retire_missing_for_source: bool = False,
) -> bool:
    """Write assertions for changed values. Returns True when any assertion changed."""
    now = retrieved_at or utcnow()
    changed = False
    query = select(EventFieldAssertion).where(
        EventFieldAssertion.event_id == event.id, EventFieldAssertion.is_current.is_(True)
    )
    if source is not None:
        query = query.where(EventFieldAssertion.source_id == source.id, EventFieldAssertion.origin.in_(["source", "derived", "ai_extracted"]))
    else:
        query = query.where(EventFieldAssertion.source_id.is_(None), EventFieldAssertion.origin == default_origin)
    current = {a.field_name: a for a in db.scalars(query)}

    for name, value in values.items():
        encoded = encode_value(value)
        origin = origins.get(name, default_origin)
        cur = current.get(name)
        if cur is not None and cur.value == encoded and cur.origin == origin:
            cur.retrieved_at = now  # re-confirmed
            continue
        if cur is not None:
            cur.is_current = False
            cur.superseded_at = now
        db.add(
            EventFieldAssertion(
                event_id=event.id,
                field_name=name,
                value=encoded,
                origin=origin,
                source_id=source.id if source else None,
                source_record_id=record.id if record else None,
                source_url=source_url,
                actor_id=actor_id,
                retrieved_at=now,
            )
        )
        changed = True
    if retire_missing_for_source:
        for name, cur in current.items():
            if name not in values:
                cur.is_current = False
                cur.superseded_at = now
                changed = True
    db.flush()
    return changed


# ------------------------------------------------------------------ dedupe


def _dates_compatible(a: date | None, b: date | None, window: int = AUTO_MERGE_URL_WINDOW_DAYS) -> bool:
    if a is None or b is None:
        return True
    return abs((a - b).days) <= window


def _same_place(nv_city: str | None, nv_country: str | None, ev: Event) -> bool:
    if nv_city and ev.city and nv_city.lower() != ev.city.lower():
        return False
    if nv_country and ev.country and nv_country.lower() != ev.country.lower():
        return False
    return True


def find_match(
    db: Session, nv: NormalizedEvent, *, exclude: uuid.UUID | None = None
) -> tuple[Event | None, list[tuple[Event, float, list[str]]]]:
    """Return (event to merge into | None, [(candidate, similarity, reasons)] needing human review)."""
    vals = nv.values
    start: date | None = vals.get("start_date")
    city, country = vals.get("city"), vals.get("country")
    candidates: list[tuple[Event, float, list[str]]] = []

    norm_url = canonicalize_url(vals.get("canonical_url"))
    if norm_url:
        for ev in db.scalars(select(Event).where(Event.canonical_url_norm == norm_url)):
            if ev.id == exclude:
                continue
            if _dates_compatible(start, ev.start_date):
                return ev, []
            candidates.append((ev, 0.6, ["Same website but different dates (possibly another edition)."]))

    nt = norm_title(nv.title)
    q = select(Event)
    if start:
        q = q.where(Event.start_date.between(start - timedelta(days=3), start + timedelta(days=3)))
    else:
        q = q.where(func.lower(Event.title) == nv.title.lower())
    for ev in db.scalars(q.limit(500)):
        if ev.id == exclude:
            continue
        et = norm_title(ev.title)
        if nt and nt == et and start and ev.start_date == start:
            if _same_place(city, country, ev):
                return ev, []
            candidates.append((ev, 0.7, ["Same title and date, but different location."]))
            continue
        score = fuzz.token_set_ratio(nt, et) if nt and et else 0
        if score >= 90 and _dates_compatible(start, ev.start_date, 3):
            candidates.append((ev, score / 100, [f"Very similar title ({score}% token match) on nearby dates."]))
    return None, candidates


def record_duplicate_candidates(
    db: Session, event: Event, candidates: list[tuple[Event, float, list[str]]]
) -> None:
    for other, sim, reasons in candidates:
        a, b = sorted([event.id, other.id], key=str)
        exists = db.scalar(
            select(DuplicateCandidate.id).where(DuplicateCandidate.event_a_id == a, DuplicateCandidate.event_b_id == b)
        )
        if not exists:
            db.add(DuplicateCandidate(event_a_id=a, event_b_id=b, similarity=round(sim, 2), reasons=reasons))
    db.flush()


# ------------------------------------------------------------------ accessibility + claims


def apply_accessibility(db: Session, event: Event, nv: NormalizedEvent) -> None:
    for key, item in nv.accessibility.items():
        row = db.scalar(
            select(AccessibilityItem).where(AccessibilityItem.event_id == event.id, AccessibilityItem.item_key == key)
        )
        if row is None:
            db.add(
                AccessibilityItem(
                    event_id=event.id,
                    item_key=key,
                    state=item.get("state", "documented"),
                    detail=item.get("detail"),
                    evidence_excerpt=item.get("excerpt"),
                    evidence_url=item.get("evidence_url"),
                    origin="source",
                )
            )
        elif row.origin == "source":
            row.state = item.get("state", row.state)
            row.detail = item.get("detail", row.detail)
            row.evidence_excerpt = item.get("excerpt", row.evidence_excerpt)
            row.evidence_url = item.get("evidence_url", row.evidence_url)
    db.flush()


def apply_field_claims(db: Session, event: Event, nv: NormalizedEvent) -> None:
    for c in nv.field_claims:
        create_claim(
            db,
            event,
            original_text=c["original_text"],
            normalized_text=c.get("normalized_text", c["original_text"]),
            category=c.get("category", "other"),
            claim_type=c.get("claim_type", "informational"),
            method=ExtractionMethod.SOURCE_FIELD,
            confidence=c.get("confidence"),
            responsible_party=c.get("responsible_party"),
            conditions=c.get("conditions"),
            numeric_values=c.get("numeric_values"),
            missing_details=c.get("missing_details"),
            verification_questions=c.get("verification_questions"),
            evidence_url=c.get("evidence_url"),
            evidence_excerpt=c.get("original_text"),
        )


# ------------------------------------------------------------------ main entry


def ingest_record(
    db: Session,
    source: Source,
    adapter: SourceAdapter,
    raw: RawRecord,
    *,
    origin_type: str = OriginType.INDEXED.value,
    now: datetime | None = None,
) -> IngestOutcome:
    now = now or utcnow()
    nv = adapter.normalize(raw)
    chash = content_hash(raw.payload)
    nv_values = dict(nv.values)

    rec = db.scalar(
        select(SourceRecord).where(
            SourceRecord.source_id == source.id, SourceRecord.source_event_id == raw.source_event_id
        )
    )
    if rec is not None and rec.event_id is not None:
        event = db.get(Event, rec.event_id)
        assert event is not None
        was_missing = rec.missing_since is not None
        unchanged = rec.content_hash == chash
        rec.last_seen_at = now
        rec.retrieved_at = raw.retrieved_at
        rec.missing_since = None
        event.last_refreshed_at = raw.retrieved_at
        if was_missing and event.extras.get("removed_since"):
            extras = dict(event.extras)
            extras.pop("removed_since", None)
            event.extras = extras
            event.lifecycle_status = Lifecycle.SCHEDULED.value
            recompute_event(db, event, change_source=source.key, force_version=True)
            return IngestOutcome("updated", event.id, True)
        if unchanged:
            return IngestOutcome("unchanged", event.id)
        rec.raw = raw.payload
        rec.normalized = jsonable({"title": nv.title, "values": nv_values, "extras": nv.extras})
        rec.content_hash = chash
        rec.extraction_confidence = nv.extraction_confidence
        rec.source_url = raw.source_url
        rec.event_url = raw.event_url
        _store_extras(event, source, nv)
        changed = assert_fields(
            db, event, nv_values, nv.origins, source=source, record=rec, source_url=raw.source_url,
            retrieved_at=raw.retrieved_at, retire_missing_for_source=True,
        )
        apply_accessibility(db, event, nv)
        apply_field_claims(db, event, nv)
        version = recompute_event(db, event, change_source=source.key)
        _refresh_confidence(db, event)
        return IngestOutcome("updated" if (changed or version) else "unchanged", event.id, version is not None)

    # new source record
    match, candidates = find_match(db, nv)
    created = match is None
    if created:
        event = Event(
            title=nv.title,
            origin_type=origin_type,
            verification_state="source_listed" if origin_type == OriginType.INDEXED.value else "unverified",
            extras={},
            first_discovered_at=now,
        )
        db.add(event)
        db.flush()
    else:
        event = match
    rec = SourceRecord(
        source_id=source.id,
        source_event_id=raw.source_event_id,
        source_url=raw.source_url,
        event_url=raw.event_url,
        event_id=event.id,
        raw=raw.payload,
        normalized=jsonable({"title": nv.title, "values": nv_values, "extras": nv.extras}),
        content_hash=chash,
        retrieved_at=raw.retrieved_at,
        last_seen_at=now,
        extraction_confidence=nv.extraction_confidence,
    )
    db.add(rec)
    db.flush()
    _store_extras(event, source, nv)
    event.last_refreshed_at = raw.retrieved_at
    assert_fields(
        db, event, nv_values, nv.origins, source=source, record=rec, source_url=raw.source_url,
        retrieved_at=raw.retrieved_at, retire_missing_for_source=not created,
    )
    apply_accessibility(db, event, nv)
    version = recompute_event(db, event, change_source=source.key)
    apply_field_claims(db, event, nv)
    _refresh_confidence(db, event)
    if candidates:
        record_duplicate_candidates(db, event, candidates)
    return IngestOutcome("created" if created else "updated", event.id, version is not None)


def _store_extras(event: Event, source: Source, nv: NormalizedEvent) -> None:
    extras = dict(event.extras or {})
    if nv.extras:
        extras[source.key] = jsonable(nv.extras)
    event.extras = extras


def _refresh_confidence(db: Session, event: Event) -> None:
    vals = [
        c for c in db.scalars(select(SourceRecord.extraction_confidence).where(SourceRecord.event_id == event.id)) if c is not None
    ]
    event.extraction_confidence = max(vals) if vals else None


def mark_missing_records(
    db: Session, source: Source, seen_ids: set[str], documents: set[str], now: datetime | None = None
) -> int:
    """Flag records absent from a complete fetch of their document. Absence is NOT proof of cancellation."""
    now = now or utcnow()
    count = 0
    for rec in db.scalars(select(SourceRecord).where(SourceRecord.source_id == source.id)):
        doc = (rec.raw or {}).get("_file")
        if doc is None or doc not in documents or rec.source_event_id in seen_ids or rec.missing_since is not None:
            continue
        rec.missing_since = now
        count += 1
        db.flush()  # sessions run with autoflush off: the liveness count below must see this change
        if rec.event_id is None:
            continue
        event = db.get(Event, rec.event_id)
        if event is None:
            continue
        live = db.scalar(
            select(func.count()).select_from(SourceRecord).where(
                SourceRecord.event_id == event.id, SourceRecord.missing_since.is_(None)
            )
        )
        if not live and event.origin_type == OriginType.INDEXED.value and event.owner_org_id is None:
            extras = dict(event.extras)
            extras["removed_since"] = now.isoformat()
            event.extras = extras
            recompute_event(db, event, change_source=source.key, force_version=True)
    db.flush()
    return count


def utc_today() -> date:
    return datetime.now(UTC).date()

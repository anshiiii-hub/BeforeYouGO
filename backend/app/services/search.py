"""Search over the indexed event database (never over "the whole internet").

Natural-language queries are interpreted into structured filters that are echoed back to
the user ("Free · hackathon · Delhi NCR"), so nothing is applied silently. Semantic
(embedding) search is not implemented; topic synonyms (taxonomy) provide the matching.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import Select, Text, and_, case, cast, exists, func, literal, literal_column, or_, select
from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY
from sqlalchemy.dialects.postgresql import array as pg_array
from sqlalchemy.orm import Session

from app.models import AccessibilityItem, Event, Source, SourceRecord
from app.services.geo import CITIES, canonical_city, city_coords, haversine_km, region_cities
from app.services.taxonomy import QUERY_TOPIC_HINTS, TOPIC_LABELS

CATEGORY_WORDS = {
    "hackathon": ("hackathon", "hackathons", "hack day", "buildathon", "ideathon", "datathon"),
    "workshop": ("workshop", "workshops", "bootcamp", "bootcamps", "masterclass", "training"),
    "conference": ("conference", "conferences", "summit", "summits", "symposium"),
    "meetup": ("meetup", "meetups"),
    "competition": ("competition", "competitions", "contest", "contests", "challenge", "challenges", "ctf"),
    "internship": ("internship", "internships", "fellowship"),
}
STOP = set("a an the and or for in on at of to with from near around me my i can where who that this these those events event "
           "opportunities opportunity find show get looking want any some under below above over than less more closing close "
           "this week month next year are is be build real project meet within upto up max maximum budget students student "
           "engineering college colleges teams team different allow allows low registration fee fees second third first final "
           "friendly".split())


@dataclass
class SearchParams:
    q: str | None = None
    category: list[str] = field(default_factory=list)
    format: list[str] = field(default_factory=list)
    city: str | None = None
    cities: list[str] = field(default_factory=list)
    country: str | None = None
    date_from: date | None = None
    date_to: date | None = None
    deadline_from: date | None = None
    deadline_to: date | None = None
    max_fee: float | None = None
    free_only: bool = False
    include_unknown_cost: bool = False
    topics: list[str] = field(default_factory=list)
    beginner: bool = False
    advanced: bool = False
    certificate: bool = False
    mentorship: bool = False
    has_prize: bool = False
    accessibility_documented: bool = False
    cross_college: bool = False
    source: str | None = None
    origin_type: str | None = None
    require_known: list[str] = field(default_factory=list)
    include_past: bool = False
    sort: str = "relevance"
    page: int = 1
    page_size: int = 20


@dataclass
class Interpretation:
    keywords: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)  # human-readable echo of what was understood
    distance_anchor: str | None = None
    distance_km: int | None = None


_MONEY_UNDER = re.compile(r"\b(?:under|below|less than|within|upto|up to|max(?:imum)?|at most|budget of?)\s*(?:₹|rs\.?|inr)?\s?(\d[\d,]*)(\s?k)?\b(?!\s?(?:days?|hours?|hrs?|weeks?|members?|people|km|kms|years?))", re.I)


def parse_query(q: str, p: SearchParams, today: date | None = None) -> Interpretation:
    """Fill ``p`` from natural language without overriding explicit filters. Returns what was understood."""
    today = today or datetime.now(UTC).date()
    it = Interpretation()
    low = f" {q.lower()} "
    consumed: list[str] = []

    def take(pattern: str) -> re.Match[str] | None:
        m = re.search(pattern, low)
        if m:
            consumed.append(m.group(0))
        return m

    if take(r"\bfree\b") and not p.free_only and p.max_fee is None:
        p.free_only = True
        it.reasons.append("Stated as free")
    m = _MONEY_UNDER.search(q)
    if m and p.max_fee is None and not p.free_only:
        val = float(m.group(1).replace(",", "")) * (1000 if m.group(2) else 1)
        p.max_fee = val
        it.reasons.append(f"Known fee up to ₹{val:g}")
        consumed.append(m.group(0).lower())
    for cat, words in CATEGORY_WORDS.items():
        for w in words:
            if re.search(rf"\b{re.escape(w)}\b", low):
                consumed.append(w)
                if cat not in p.category:
                    p.category.append(cat)
                    it.reasons.append(f"Category: {cat}")
    for fmt, pat in (("online", r"\b(online|virtual|remote)\b"), ("offline", r"\b(offline|in[- ]person|on[- ]site|on[- ]campus)\b"), ("hybrid", r"\bhybrid\b")):
        mm = take(pat)
        if mm and fmt not in p.format:
            p.format.append(fmt)
            it.reasons.append(f"Format: {fmt}")
    if take(r"\bbeginner[- ]?(friendly|level)?s?\b|\bno prior experience\b|\bintroductory\b|\bfirst[- ]time\b"):
        p.beginner = True
        it.reasons.append("Mentions beginner-level (text match)")
    if take(r"\badvanced\b"):
        p.advanced = True
        it.reasons.append("Mentions advanced-level (text match)")
    if take(r"\bcertificat\w*\b"):
        p.certificate = True
        it.reasons.append("Certificate mentioned")
    if take(r"\bmentor\w*\b"):
        p.mentorship = True
        it.reasons.append("Mentorship mentioned")
    if take(r"\bprizes?\b|\bprize money\b|\bcash prize\b"):
        p.has_prize = True
        it.reasons.append("Prize mentioned")
    if take(r"\b(different|multiple|any|cross|inter)[- ]?colleges?\b|\binter-?college\b|\bcross-?college\b"):
        p.cross_college = True
        it.reasons.append("Cross-college teams allowed (only events that state this)")
    if take(r"\baccessib\w+\b|\bwheelchair\b"):
        p.accessibility_documented = True
        it.reasons.append("Accessibility information documented")

    # time windows
    if take(r"\b(closing|closes|deadline)\b[^.]{0,20}\bthis week\b|\bthis week\b[^.]{0,20}\b(closing|deadline)\b") and p.deadline_to is None:
        p.deadline_from, p.deadline_to = today, today + timedelta(days=7)
        it.reasons.append("Registration deadline within 7 days (only events that state a deadline)")
    elif take(r"\b(closing|closes|deadline)\b[^.]{0,15}\bsoon\b") and p.deadline_to is None:
        p.deadline_from, p.deadline_to = today, today + timedelta(days=14)
        it.reasons.append("Registration deadline within 14 days (only events that state a deadline)")
    elif take(r"\bthis week\b") and p.date_to is None:
        p.date_from, p.date_to = today, today + timedelta(days=7)
        it.reasons.append("Starts within 7 days")
    elif take(r"\bthis weekend\b") and p.date_to is None:
        sat = today + timedelta(days=(5 - today.weekday()) % 7)
        p.date_from, p.date_to = sat, sat + timedelta(days=1)
        it.reasons.append("This weekend")
    elif take(r"\bthis month\b") and p.date_to is None:
        nxt = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
        p.date_from, p.date_to = today, nxt - timedelta(days=1)
        it.reasons.append("This month")
    elif take(r"\bnext month\b") and p.date_to is None:
        first = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
        last = ((first.replace(day=28) + timedelta(days=4)).replace(day=1)) - timedelta(days=1)
        p.date_from, p.date_to = first, last
        it.reasons.append("Next month")

    # location: region, "near X", "in X", or a bare known city
    for region in ("delhi ncr", "chandigarh tricity", "tricity", "ncr"):
        if f" {region} " in low:
            cities = region_cities(region) or []
            if not p.cities and not p.city:
                p.cities = cities
                it.reasons.append(f"Location: {region.title()} ({', '.join(cities[:4])}…)")
            consumed.append(region)
            break
    else:
        near = re.search(r"\b(near|around|close to|nearby)\s+([a-z .]+?)(?=\s(?:under|below|with|for|and|that|where|$)|[,.?]|$)", low)
        anchor = None
        if near:
            cand = canonical_city(near.group(2).strip().title())
            if cand in CITIES:
                anchor = cand
                consumed.append(near.group(0))
        if anchor and not p.city and not p.cities:
            it.distance_anchor, it.distance_km = anchor, 150
            alo = city_coords(anchor)
            p.cities = [c for c, (lat, lon, _, _) in CITIES.items() if alo and haversine_km(alo, (lat, lon)) <= 150]
            it.reasons.append(f"Location: within about 150 km of {anchor} (straight-line, approximate)")
        else:
            for name in sorted(CITIES, key=len, reverse=True):
                if re.search(rf"\b{re.escape(name.lower())}\b", low) and not p.city and not p.cities:
                    p.city = name
                    it.reasons.append(f"Location: {name}")
                    consumed.append(name.lower())
                    break

    # topics
    for topic, hints in QUERY_TOPIC_HINTS.items():
        for h in sorted(hints, key=len, reverse=True):
            if re.search(rf"(?<![a-z0-9]){re.escape(h)}(?![a-z0-9])", low):
                consumed.append(h)
                if topic not in p.topics:
                    p.topics.append(topic)
                    it.reasons.append(f"Topic: {TOPIC_LABELS.get(topic, topic)}")
                break
    leftover = low
    for c in consumed:
        leftover = leftover.replace(c, " ")
    it.keywords = [w for w in re.findall(r"[a-z0-9+#]{2,}", leftover) if w not in STOP]
    return it


# ----------------------------------------------------------------- query construction


def _base_filters(p: SearchParams, *, include_unknown_cost: bool | None = None, skip: str | None = None) -> list[Any]:
    f: list[Any] = [Event.is_published.is_(True)]
    today = datetime.now(UTC).date()
    if not p.include_past:
        f.append(or_(func.coalesce(Event.end_date, Event.start_date) >= today, and_(Event.start_date.is_(None), Event.end_date.is_(None))))
        f.append(Event.lifecycle_status.notin_(["cancelled", "removed_from_source"]))
    if p.category:
        f.append(Event.category.in_(p.category))
    if p.format:
        f.append(Event.format.in_([*p.format, *(["hybrid"] if any(x in p.format for x in ("online", "offline")) else [])]))
    if p.city:
        f.append(func.lower(Event.city) == p.city.lower())
    if p.cities:
        f.append(func.lower(Event.city).in_([c.lower() for c in p.cities]))
    if p.country:
        f.append(func.lower(Event.country) == p.country.lower())
    if p.date_from:
        f.append(func.coalesce(Event.end_date, Event.start_date) >= p.date_from)
    if p.date_to:
        f.append(Event.start_date <= p.date_to)
    if p.deadline_from or p.deadline_to:
        f.append(Event.registration_deadline.is_not(None))
        if p.deadline_from:
            f.append(Event.registration_deadline >= datetime.combine(p.deadline_from, datetime.min.time(), tzinfo=UTC))
        if p.deadline_to:
            f.append(Event.registration_deadline <= datetime.combine(p.deadline_to, datetime.max.time(), tzinfo=UTC))
    if p.free_only:
        f.append(Event.fee_status == "free")
    elif p.max_fee is not None and skip != "cost":
        known_ok = or_(Event.fee_status == "free", and_(Event.fee_status == "paid", Event.fee_currency == "INR", Event.fee_amount <= p.max_fee))
        unknown_ok = Event.fee_status == "unknown"
        inc = p.include_unknown_cost if include_unknown_cost is None else include_unknown_cost
        f.append(or_(known_ok, unknown_ok) if inc else known_ok)
    if p.topics:
        f.append(Event.topics.op("?|")(cast(pg_array(list(p.topics)), PG_ARRAY(Text))))
    text_blob = func.lower(func.concat_ws(" ", Event.title, Event.description, Event.prerequisites, Event.eligibility, Event.tags_text))
    if p.beginner:
        f.append(or_(*[text_blob.like(f"%{w}%") for w in ("beginner", "no prior experience", "introductory", "first-time", "from scratch")]))
    if p.advanced:
        f.append(text_blob.like("%advanced%"))
    if p.certificate:
        f.append(or_(Event.offers_certificate.is_(True), text_blob.like("%certificat%")))
    if p.mentorship:
        f.append(or_(Event.offers_mentorship.is_(True), text_blob.like("%mentor%")))
    if p.has_prize:
        f.append(or_(Event.prize_details.is_not(None), text_blob.like("%prize%")))
    if p.cross_college:
        f.append(Event.allows_cross_college_teams.is_(True))
    if p.accessibility_documented:
        f.append(exists().where(AccessibilityItem.event_id == Event.id, AccessibilityItem.state == "documented"))
    if p.source:
        f.append(exists().where(SourceRecord.event_id == Event.id, SourceRecord.source_id == Source.id, Source.key == p.source))
    if p.origin_type:
        f.append(Event.origin_type == p.origin_type)
    known_cols = {"deadline": Event.registration_deadline, "eligibility": Event.eligibility, "venue": Event.venue,
                  "schedule": Event.schedule_text, "contact": Event.contact_info}
    for k in p.require_known:
        if k == "fee":
            f.append(Event.fee_status.in_(["free", "paid"]))
        elif k in known_cols:
            f.append(known_cols[k].is_not(None))
    return f


def _fts_query(keywords: list[str], mode: str) -> Any:
    tokens = [re.sub(r"[^a-z0-9]", "", k) for k in keywords]
    tokens = [t for t in tokens if t]
    if not tokens:
        return None
    joiner = " & " if mode == "and" else " | "
    return func.to_tsquery("english", joiner.join(tokens))


def run_search(db: Session, p: SearchParams, interp: Interpretation | None = None) -> dict[str, Any]:
    interp = interp or Interpretation()
    sv = literal_column("events.search_vector")
    keywords = interp.keywords or []
    broadened = False
    ts = _fts_query(keywords, "and")

    def build(tsq: Any) -> tuple[Select[Any], Select[Any]]:
        filters = _base_filters(p)
        rank = func.ts_rank_cd(sv, tsq) if tsq is not None else literal(0.0)
        if tsq is not None:
            filters.append(sv.op("@@")(tsq))
        topic_boost = case((Event.topics.op("?|")(cast(pg_array(list(p.topics)), PG_ARRAY(Text))), 1), else_=0) if p.topics else literal(0)
        q = select(Event, (rank + 0.3 * topic_boost).label("rank")).where(*filters)
        cnt = select(func.count()).select_from(Event).where(*filters)
        return q, cnt

    q, cnt = build(ts)
    total = db.scalar(cnt) or 0
    if total == 0 and len(keywords) > 1:
        ts_or = _fts_query(keywords, "or")
        q2, cnt2 = build(ts_or)
        total2 = db.scalar(cnt2) or 0
        if total2:
            q, total, broadened = q2, total2, True
    far = datetime(9999, 1, 1, tzinfo=UTC)
    if p.sort == "date":
        q = q.order_by(Event.start_date.asc().nulls_last(), Event.title)
    elif p.sort == "deadline":
        q = q.order_by(Event.registration_deadline.asc().nulls_last(), Event.start_date.asc().nulls_last())
    else:
        q = q.order_by(literal_column("rank").desc(), Event.start_date.asc().nulls_last(), Event.title)
    _ = far
    rows = db.execute(q.limit(p.page_size).offset((p.page - 1) * p.page_size)).all()
    events = [r[0] for r in rows]

    notes: list[str] = []
    if broadened:
        notes.append("No event matched all of your keywords, so results match any of them.")
    unknown_hidden: dict[str, int] = {}
    if p.max_fee is not None and not p.free_only and not p.include_unknown_cost:
        n = db.scalar(select(func.count()).select_from(Event).where(*_base_filters(p, include_unknown_cost=True), Event.fee_status == "unknown")) or 0
        if n:
            unknown_hidden["unknown_cost"] = n
            notes.append(f"{n} more event(s) match but do not state a fee, so they are hidden by your budget filter. Unknown cost is not the same as free.")
    if (p.deadline_from or p.deadline_to) and total == 0:
        notes.append("Few sources publish registration deadlines; events without a stated deadline cannot match a deadline filter.")
    if p.cross_college and total == 0:
        notes.append("Cross-college team rules are rarely published in structured form; absence here is not evidence they are disallowed.")
    return {"events": events, "total": total, "broadened": broadened, "notes": notes, "unknown_hidden": unknown_hidden}


def index_status(db: Session) -> dict[str, Any]:
    total = db.scalar(select(func.count()).select_from(Event).where(Event.is_published.is_(True))) or 0
    srcs = list(db.scalars(select(Source).where(Source.kind != "platform")))
    active = [s for s in srcs if s.status == "active"]
    failing = [{"key": s.key, "name": s.name, "status": s.status, "detail": s.status_detail} for s in srcs if s.status in ("degraded", "blocked")]
    last = max((s.last_success_at for s in srcs if s.last_success_at), default=None)
    return {
        "events_indexed": total, "connectors": len(srcs), "connectors_active": len(active), "connectors_failing": failing,
        "last_successful_sync_at": last.isoformat() if last else None,
        "scope": "Results come only from connected sources and submitted records, not from the whole internet.",
        "state": "no_data" if total == 0 else ("degraded" if failing else "ok"),
    }

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select

from app.api.common import client_ip, get_event, profile_of
from app.core.deps import CurrentUser, DbSession, OptionalUser, can_manage_event
from app.core.errors import Forbidden, Unprocessable
from app.core.ratelimit import expensive_limit
from app.domain.enums import AnalysisInput, FieldOrigin, OriginType
from app.models import ComparisonHistory, Event, EventVersion, Source, SourceRecord
from app.schemas.api import CompareIn, SubmitTextIn, SubmitUrlIn
from app.services.analyzer.pipeline import analyze, event_corpus
from app.services.audit import audit
from app.services.geo import approx_distance_km
from app.services.ingest import assert_fields, recompute_event
from app.services.search import SearchParams, index_status, parse_query, run_search
from app.services.sync import submit_event_url
from app.services.taxonomy import classify_category, topics_from_text
from app.services.urls import display_url
from app.services.views import cards, event_detail

router = APIRouter(prefix="/api", tags=["events"])

CSV = Annotated[list[str] | None, Query()]


@router.get("/events")
def search_events(
    request: Request,
    db: DbSession,
    user: OptionalUser,
    q: str | None = Query(None, max_length=300),
    category: CSV = None,
    format: CSV = None,
    city: str | None = None,
    country: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    deadline_from: date | None = None,
    deadline_to: date | None = None,
    max_fee: float | None = Query(None, ge=0),
    free_only: bool = False,
    include_unknown_cost: bool = False,
    topics: CSV = None,
    beginner: bool = False,
    certificate: bool = False,
    mentorship: bool = False,
    has_prize: bool = False,
    accessibility_documented: bool = False,
    cross_college: bool = False,
    source: str | None = None,
    origin_type: str | None = None,
    require_known: CSV = None,
    include_past: bool = False,
    sort: str = Query("relevance", pattern="^(relevance|date|deadline)$"),
    page: int = Query(1, ge=1, le=500),
    page_size: int = Query(20, ge=1, le=50),
    personalize: bool = True,
) -> dict[str, Any]:
    p = SearchParams(
        q=q, category=list(category or []), format=list(format or []), city=city, country=country, date_from=date_from,
        date_to=date_to, deadline_from=deadline_from, deadline_to=deadline_to, max_fee=max_fee, free_only=free_only,
        include_unknown_cost=include_unknown_cost, topics=list(topics or []), beginner=beginner, certificate=certificate,
        mentorship=mentorship, has_prize=has_prize, accessibility_documented=accessibility_documented,
        cross_college=cross_college, source=source, origin_type=origin_type, require_known=list(require_known or []),
        include_past=include_past, sort=sort, page=page, page_size=page_size,
    )
    interp = parse_query(q, p) if q else None
    result = run_search(db, p, interp)
    profile = profile_of(db, user) if (user and personalize) else None
    reasons = interp.reasons if interp else []
    items = cards(db, result["events"], user.id if user else None, profile, reasons)
    status = index_status(db)
    state = "unavailable" if status["state"] == "no_data" else ("empty_result" if result["total"] == 0 else "ok")
    return {
        "items": items, "total": result["total"], "page": page, "page_size": page_size,
        "interpretation": {"understood": reasons, "keywords": interp.keywords if interp else [],
                           "applied": {"free_only": p.free_only, "max_fee": p.max_fee, "categories": p.category, "formats": p.format,
                                       "cities": p.cities or ([p.city] if p.city else []), "topics": p.topics}},
        "notes": result["notes"], "broadened": result["broadened"], "state": state, "index": status,
        "personalized": profile is not None,
    }


@router.get("/events/facets")
def facets(db: DbSession) -> dict[str, Any]:
    today = datetime.now(UTC).date()
    base = [Event.is_published.is_(True), func.coalesce(Event.end_date, Event.start_date) >= today,
            Event.lifecycle_status.notin_(["cancelled", "removed_from_source"])]

    def counts(col: Any, limit: int = 15) -> list[dict[str, Any]]:
        rows = db.execute(select(col, func.count()).where(*base, col.is_not(None)).group_by(col).order_by(func.count().desc()).limit(limit))
        return [{"value": r[0], "count": r[1]} for r in rows]

    topic_rows = db.execute(select(func.jsonb_array_elements_text(Event.topics).label("t"), func.count()).where(*base).group_by("t").order_by(func.count().desc()))
    src_rows = db.execute(
        select(Source.key, Source.name, func.count(func.distinct(SourceRecord.event_id)))
        .join(SourceRecord, SourceRecord.source_id == Source.id).join(Event, Event.id == SourceRecord.event_id)
        .where(*base).group_by(Source.key, Source.name).order_by(func.count().desc())
    )
    return {
        "categories": counts(Event.category), "formats": counts(Event.format), "countries": counts(Event.country),
        "cities": counts(Event.city, 30), "topics": [{"value": r[0], "count": r[1]} for r in topic_rows],
        "sources": [{"value": r[0], "label": r[1], "count": r[2]} for r in src_rows],
        "origins": counts(Event.origin_type),
        "fee": counts(Event.fee_status),
    }


@router.get("/events/{event_id}")
def get_event_detail(event_id: uuid.UUID, db: DbSession, user: OptionalUser) -> dict[str, Any]:
    event = get_event(db, event_id, include_unpublished_for=user)
    profile = profile_of(db, user)
    detail = event_detail(db, event, user, profile)
    detail["permissions"] = {
        "can_manage": bool(user and can_manage_event(db, user, event)),
        "can_review": bool(user and user.role in ("reviewer", "admin")),
        "can_submit_feedback": bool(user),
    }
    detail["is_published"] = event.is_published
    if user:
        from app.models import SavedEvent

        saved = db.get(SavedEvent, (user.id, event.id))
        detail["saved_info"] = ({"saved_at": saved.saved_at.isoformat(), "note": saved.note, "last_seen_version": saved.last_seen_version}
                                if saved else None)
    return detail


@router.get("/events/{event_id}/versions")
def event_versions(event_id: uuid.UUID, db: DbSession, user: OptionalUser) -> dict[str, Any]:
    event = get_event(db, event_id, include_unpublished_for=user)
    rows = db.scalars(select(EventVersion).where(EventVersion.event_id == event.id).order_by(EventVersion.version_no.desc()))
    return {"items": [{"version_no": v.version_no, "changed_at": v.changed_at.isoformat(), "change_source": v.change_source,
                       "is_material": v.is_material, "summary": v.summary, "diff": v.diff} for v in rows]}


# ------------------------------------------------------------------ comparison


def _span(e: dict[str, Any]) -> str:
    if not e["start_date"]:
        return "Not stated"
    return e["start_date"] if not e["end_date"] or e["end_date"] == e["start_date"] else f"{e['start_date']} → {e['end_date']}"


@router.post("/events/compare", dependencies=[Depends(expensive_limit)])
def compare(body: CompareIn, db: DbSession, user: OptionalUser) -> dict[str, Any]:
    ids = list(dict.fromkeys(body.event_ids))
    if len(ids) < 2:
        raise Unprocessable("Choose at least two different events.", code="need_two_events")
    events = []
    for i in ids:
        events.append(get_event(db, i, include_unpublished_for=user))
    profile = profile_of(db, user)
    details = [event_detail(db, e, user, profile) for e in events]

    def distance(d: dict[str, Any]) -> Any:
        if profile and profile.home_city and d["format"] in ("offline", "hybrid"):
            km = approx_distance_km(profile.home_city, d["city"])
            return f"≈{km:.0f} km from {profile.home_city} (straight-line)" if km is not None else "Unknown (city not recognised)"
        return "Online" if d["format"] == "online" else None

    def vague(d: dict[str, Any]) -> int:
        return sum(1 for c in d["claims"] if c["claim_type"] == "vague")

    def open_gaps(d: dict[str, Any], sev: str | None = None) -> int:
        return sum(1 for g in d["gaps"] if g["status"] == "open" and (sev is None or g["severity"] == sev))

    spec: list[tuple[str, str, Any]] = [
        ("dates", "Dates", lambda d: _span(d)),
        ("deadline", "Registration deadline", lambda d: d["registration_deadline"][:10] if d["registration_deadline"] else "Not stated"),
        ("format", "Format", lambda d: d["format"]),
        ("location", "Location", lambda d: d["location"] or "Not stated"),
        ("distance", "Distance from you", distance),
        ("fee", "Registration fee", lambda d: d["fee"]["label"]),
        ("other_costs", "Other costs (travel, materials)", lambda d: d["other_costs"] or "Not stated"),
        ("eligibility", "Eligibility", lambda d: d["eligibility"] or "Not stated"),
        ("prerequisites", "Prerequisites", lambda d: d["prerequisites"] or "Not stated"),
        ("team", "Team size", lambda d: (f"{d['team_size']['min'] or '?'}–{d['team_size']['max'] or '?'}" if d["team_size"]["max"] or d["team_size"]["min"] else "Not stated")),
        ("cross_college", "Cross-college teams", lambda d: {True: "Allowed", False: "Not allowed", None: "Not stated"}[d["allows_cross_college_teams"]]),
        ("certificate", "Certificate", lambda d: {True: "Offered", False: "Not offered", None: "Not stated"}[d["offers_certificate"]]),
        ("mentorship", "Mentorship", lambda d: {True: "Offered", False: "Not offered", None: "Not stated"}[d["offers_mentorship"]]),
        ("prize", "Prizes", lambda d: d["prize_details"] or "Not stated"),
        ("claims", "Advertised claims", lambda d: f"{len(d['claims'])} ({vague(d)} vague)"),
        ("gaps", "Open information gaps", lambda d: f"{open_gaps(d)} ({open_gaps(d, 'high')} high severity)"),
        ("completeness", "Information completeness", lambda d: f"{d['completeness']['filled']}/{d['completeness']['total']} details present"),
        ("accessibility", "Accessibility documented", lambda d: f"{d['accessibility']['documented_count']}/{d['accessibility']['total_count']} items"),
        ("evidence", "Evidence strength", lambda d: d["evidence_strength"]["level"].replace("_", " ")),
        ("freshness", "Data freshness", lambda d: d["freshness"]["message"]),
        ("sources", "Sources", lambda d: ", ".join(s["name"] for s in d["sources"]) or d["origin"]["label"]),
    ]
    rows = []
    for key, label, fn in spec:
        values = [fn(d) for d in details]
        if all(v is None for v in values):
            continue
        norm = [str(v).strip().lower() for v in values]
        rows.append({"key": key, "label": label, "values": values, "differs": len(set(norm)) > 1})

    highlights: list[str] = []
    known = [(d["title"], d["fee"]["amount"]) for d in details if d["fee"]["amount"] is not None or d["fee"]["status"] == "free"]
    unknown_fee = [d["title"] for d in details if d["fee"]["uncertain"]]
    if known:
        cheapest = min(known, key=lambda x: x[1] or 0)
        highlights.append(f"Lowest known fee: “{cheapest[0]}” ({'free' if not cheapest[1] else f'₹{cheapest[1]:.0f}'})."
                          + (f" Fee not stated for: {', '.join(unknown_fee)}, so they cannot be ranked on cost." if unknown_fee else ""))
    elif unknown_fee:
        highlights.append("None of these events states its fee, so cost cannot be compared.")
    dl = [(d["title"], d["registration_deadline"]) for d in details if d["registration_deadline"]]
    if dl:
        e = min(dl, key=lambda x: x[1])
        highlights.append(f"Earliest stated registration deadline: “{e[0]}” on {e[1][:10]}.")
    if len(dl) < len(details):
        highlights.append("Some events do not state a deadline; do not assume registration stays open.")
    best = max(details, key=lambda d: d["completeness"]["score"])
    highlights.append(f"Most complete listing: “{best['title']}” ({best['completeness']['filled']}/{best['completeness']['total']} details).")
    if profile:
        fits = [(d["title"], d["fit"]) for d in details if d.get("fit") and d["fit"].get("score") is not None]
        for t, f in fits:
            highlights.append(f"For you, “{t}”: {f['label']} ({f['score']}/100 weighted match, {round(f['coverage'] * 100)}% of factors known)"
                              + (f"; excluded by: {'; '.join(v['message'] for v in f['hard_violations'])}" if f["hard_violations"] else "") + ".")

    if user:
        db.add(ComparisonHistory(user_id=user.id, event_ids=[str(i) for i in ids]))
    return {
        "events": [{"id": d["id"], "title": d["title"], "organizer": d["organizer"], "canonical_url": d["canonical_url"],
                    "fit": d.get("fit"), "origin": d["origin"], "category": d["category"]} for d in details],
        "rows": rows, "highlights": highlights,
        "note": "Differences are highlighted only where stated values differ; “Not stated” means unknown, never zero or none.",
    }


# ------------------------------------------------------------------ analysis + submission


@router.post("/events/{event_id}/analyze", dependencies=[Depends(expensive_limit)])
def analyze_event(event_id: uuid.UUID, db: DbSession, user: CurrentUser, request: Request) -> dict[str, Any]:
    from app.models import Claim

    event = get_event(db, event_id, include_unpublished_for=user)
    has_claims = db.scalar(select(func.count()).select_from(Claim).where(Claim.event_id == event.id)) or 0
    if has_claims and not (can_manage_event(db, user, event) or user.role in ("reviewer", "admin")):
        raise Forbidden("This event has already been analysed. Only its organizer or a reviewer can re-run the analysis.", code="analysis_exists")
    result = analyze(db, text=event_corpus(event), input_type=AnalysisInput.EVENT, event=event, canonical_url=event.canonical_url,
                     actor=user, source_label="the stored event record")
    audit(db, actor=user, action="event.analyzed", target_type="event", target_id=event.id, ip=client_ip(request))
    return result


@router.post("/events/submit-url", status_code=201, dependencies=[Depends(expensive_limit)])
def submit_url(body: SubmitUrlIn, db: DbSession, user: CurrentUser) -> dict[str, Any]:
    out = submit_event_url(db, body.url, user=user)
    return {**out, "origin": "user_submitted",
            "note": "The record is labelled as user-submitted and its fields come from the page's own published data."}


@router.post("/events/submit-text", status_code=201, dependencies=[Depends(expensive_limit)])
def submit_text(body: SubmitTextIn, db: DbSession, user: CurrentUser) -> dict[str, Any]:
    """Create an explicitly labelled user-submitted record from pasted text, then analyse it.

    Only values that can be taken from what the user typed are stored; everything else stays unknown.
    """
    canon = display_url(body.url) if body.url else None
    if body.url and not canon:
        raise Unprocessable("The URL must start with http:// or https://.", code="invalid_url")
    origin = OriginType.ORGANIZER_SUBMITTED if user.role == "organizer" else OriginType.USER_SUBMITTED
    event = Event(title=body.title, origin_type=origin.value, verification_state="unverified", extras={}, is_published=True)
    db.add(event)
    db.flush()
    values: dict[str, Any] = {"title": body.title, "description": body.text,
                              "category": classify_category(body.title, body.text[:1500]), "topics": topics_from_text(f"{body.title} {body.text[:3000]}")}
    if canon:
        values["canonical_url"] = canon
    if body.organizer_name:
        values["organizer_name"] = body.organizer_name
    assert_fields(db, event, values, {}, source=None, record=None, source_url=canon, actor_id=user.id, default_origin=FieldOrigin.MANUAL.value)
    recompute_event(db, event, change_source="user_submission", actor_id=user.id)
    event.created_by = user.id
    result = analyze(db, text=f"{body.title}\n{body.text}", input_type=AnalysisInput.TEXT, event=event, actor=user,
                     source_label="the text you submitted")
    audit(db, actor=user, action="event.text_submitted", target_type="event", target_id=event.id)
    return {"event_id": str(event.id), "analysis": result["summary"], "origin": origin.value}




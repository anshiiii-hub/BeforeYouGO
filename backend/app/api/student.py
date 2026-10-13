from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import Text, and_, cast, func, or_, select
from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY
from sqlalchemy.dialects.postgresql import array as pg_array

from app.api.common import get_event, profile_of
from app.core.deps import CurrentUser, DbSession
from app.core.errors import Unprocessable
from app.models import (
    AccessibilityItem,
    ComparisonHistory,
    Event,
    EventVersion,
    FeedbackResponse,
    Participation,
    RecommendationFeedback,
    SavedEvent,
)
from app.schemas.api import ParticipationIn, RecFeedbackIn, SaveEventIn
from app.services import runtime_config
from app.services.claims import event_has_ended
from app.services.scoring import completeness, suitability
from app.services.taxonomy import topics_from_interests
from app.services.views import _bulk, card

router = APIRouter(prefix="/api/me", tags=["student"])


def _pool(db, profile, user_id) -> list[Event]:  # type: ignore[no-untyped-def]
    today = datetime.now(UTC).date()
    hidden = select(RecommendationFeedback.event_id).where(RecommendationFeedback.user_id == user_id, RecommendationFeedback.vote.in_(["hide", "not_relevant"]))
    base = [Event.is_published.is_(True), Event.lifecycle_status.notin_(["cancelled", "removed_from_source"]),
            or_(func.coalesce(Event.end_date, Event.start_date) >= today, and_(Event.start_date.is_(None), Event.end_date.is_(None))),
            Event.id.notin_(hidden)]
    topics = sorted(topics_from_interests(profile.interests or []))
    pool: list[Event] = []
    if topics:
        pool = list(db.scalars(select(Event).where(*base, Event.topics.op("?|")(cast(pg_array(topics), PG_ARRAY(Text)))).order_by(Event.start_date.asc().nulls_last()).limit(500)))
    if len(pool) < 30:
        have = {e.id for e in pool}
        extra = db.scalars(select(Event).where(*base).order_by(Event.start_date.asc().nulls_last()).limit(300))
        pool += [e for e in extra if e.id not in have]
    return pool


def build_recommendations(db, user, limit: int = 20) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    profile = profile_of(db, user)
    if profile is None:
        return {"needs_profile": True, "items": [], "excluded": {"count": 0, "reasons": [], "examples": []},
                "message": "Create a preference profile to get explainable recommendations. Without one, you can still search and compare."}
    weights = runtime_config.effective(db)["scoring_weights"]
    pool = _pool(db, profile, user.id)
    bulk = _bulk(db, pool, user.id)
    access_by_event: dict[Any, dict[str, str]] = defaultdict(dict)
    if profile.accessibility_needs and pool:
        for r in db.scalars(select(AccessibilityItem).where(AccessibilityItem.event_id.in_([e.id for e in pool]))):
            access_by_event[r.event_id][r.item_key] = r.state
    eligible: list[tuple[Event, dict[str, Any]]] = []
    excluded: list[tuple[Event, dict[str, Any]]] = []
    for e in pool:
        cats = {c.category for c in bulk["claims"].get(e.id, [])}
        fit = suitability(e, profile, claim_categories=cats, access=access_by_event.get(e.id), weights=weights)
        (eligible if fit["eligible"] else excluded).append((e, fit))
    rated = [(e, f) for e, f in eligible if f["score"] is not None and f["coverage"] >= 0.4]
    rated.sort(key=lambda x: (-x[1]["score"], -x[1]["coverage"], x[0].start_date or datetime.max.date()))
    unrated = [(e, f) for e, f in eligible if (e, f) not in rated]

    top = rated[:limit]
    items = []
    for i, (e, f) in enumerate(top):
        c = card(e, bulk, None)
        comp = completeness(e, bulk["access"].get(e.id, 0))
        alts = [{"id": str(a.id), "title": a.title, "score": af["score"], "why": (af["why_match"] or ["Similar topic"])[0]}
                for a, af in rated[:30] if a.id != e.id and a.category == e.category and set(a.topics or []) & set(e.topics or [])][:2]
        warnings = [u["message"] for u in f["unknowns"]][:4] + [f"Missing: {m}" for m in c["missing_information"][:3]]
        items.append({**c, "rank": i + 1, "fit": f, "alternatives": alts, "warnings": warnings,
                      "why_match": f["why_match"], "why_skip": f["why_skip"], "tradeoffs": f["tradeoffs"],
                      "completeness_detail": {"filled": comp["filled"], "total": comp["total"]}})
    reasons = Counter()
    for _, f in excluded:
        for v in f["hard_violations"]:
            reasons[v["key"]] += 1
    labels = {"event_ended": "Already ended", "registration_closed": "Registration closed", "budget": "Above your budget",
              "format": "Not in your required format", "schedule": "Outside your available dates", "travel": "Beyond your travel limit",
              "eligibility": "Not eligible (year of study)", "eligibility_level": "Not eligible (education level)", "cancelled": "Cancelled"}
    return {
        "needs_profile": False, "items": items, "considered": len(pool), "eligible": len(eligible),
        "not_rated": len(unrated),
        "excluded": {"count": len(excluded),
                     "reasons": [{"key": k, "label": labels.get(k, k.replace("_", " ").title()), "count": n} for k, n in reasons.most_common()],
                     "examples": [{"id": str(e.id), "title": e.title, "why": [v["message"] for v in f["hard_violations"]]} for e, f in excluded[:5]]},
        "weights": weights,
        "method": "Hard constraints (eligibility, budget, dates, format, travel, closed registration) exclude an event. The remaining events are ranked by a "
                  "weighted preference match over the factors that are known. It is not a probability of a good outcome.",
    }


@router.get("/recommendations")
def recommendations(db: DbSession, user: CurrentUser, limit: int = Query(20, ge=1, le=50)) -> dict[str, Any]:
    return build_recommendations(db, user, limit)


@router.post("/recommendation-feedback")
def rec_feedback(body: RecFeedbackIn, db: DbSession, user: CurrentUser) -> dict[str, Any]:
    get_event(db, body.event_id)
    row = db.scalar(select(RecommendationFeedback).where(RecommendationFeedback.user_id == user.id, RecommendationFeedback.event_id == body.event_id))
    if row is None:
        row = RecommendationFeedback(user_id=user.id, event_id=body.event_id, vote=body.vote, reason=body.reason)
        db.add(row)
    else:
        row.vote, row.reason = body.vote, body.reason
    return {"ok": True, "vote": body.vote, "effect": "This event will not be recommended again." if body.vote != "helpful" else "Noted."}


# ------------------------------------------------------------------ saved events


def _latest_version(db, event_id) -> int:  # type: ignore[no-untyped-def]
    return db.scalar(select(func.max(EventVersion.version_no)).where(EventVersion.event_id == event_id)) or 0


@router.put("/saved/{event_id}")
def save_event(event_id: uuid.UUID, body: SaveEventIn, db: DbSession, user: CurrentUser) -> dict[str, Any]:
    event = get_event(db, event_id)
    row = db.get(SavedEvent, (user.id, event.id))
    if row is None:
        row = SavedEvent(user_id=user.id, event_id=event.id, note=body.note, last_seen_version=_latest_version(db, event.id))
        db.add(row)
    else:
        row.note = body.note
    return {"saved": True}


@router.delete("/saved/{event_id}")
def unsave_event(event_id: uuid.UUID, db: DbSession, user: CurrentUser) -> dict[str, Any]:
    row = db.get(SavedEvent, (user.id, event_id))
    if row:
        db.delete(row)
    return {"saved": False}


@router.post("/saved/{event_id}/seen")
def mark_seen(event_id: uuid.UUID, db: DbSession, user: CurrentUser) -> dict[str, Any]:
    row = db.get(SavedEvent, (user.id, event_id))
    if row is None:
        raise Unprocessable("This event is not in your saved list.", code="not_saved")
    row.last_seen_version = _latest_version(db, event_id)
    return {"ok": True}


def saved_with_changes(db, user) -> list[dict[str, Any]]:  # type: ignore[no-untyped-def]
    rows = list(db.execute(select(SavedEvent, Event).join(Event, Event.id == SavedEvent.event_id).where(SavedEvent.user_id == user.id).order_by(SavedEvent.saved_at.desc())))
    if not rows:
        return []
    profile = profile_of(db, user)
    events = [e for _, e in rows]
    bulk = _bulk(db, events, user.id)
    out = []
    for s, e in rows:
        c = card(e, bulk, profile)
        changes = list(db.scalars(select(EventVersion).where(EventVersion.event_id == e.id, EventVersion.version_no > (s.last_seen_version or 0)).order_by(EventVersion.version_no)))
        c["note"] = s.note
        c["saved_at"] = s.saved_at.isoformat()
        c["changes_since_saved"] = [{"version_no": v.version_no, "changed_at": v.changed_at.isoformat(), "summary": v.summary, "is_material": v.is_material,
                                     "diff": v.diff, "change_source": v.change_source} for v in changes]
        c["material_change"] = any(v.is_material for v in changes)
        out.append(c)
    return out


@router.get("/saved")
def saved(db: DbSession, user: CurrentUser) -> dict[str, Any]:
    items = saved_with_changes(db, user)
    return {"items": items, "total": len(items)}


@router.get("/deadlines")
def deadlines(db: DbSession, user: CurrentUser) -> dict[str, Any]:
    now = datetime.now(UTC)
    items = saved_with_changes(db, user)
    dated = [i for i in items if i["registration_deadline"] and datetime.fromisoformat(i["registration_deadline"]) >= now]
    dated.sort(key=lambda i: i["registration_deadline"])
    undated = [i for i in items if not i["registration_deadline"]]
    closed = [i for i in items if i["registration_deadline"] and datetime.fromisoformat(i["registration_deadline"]) < now]
    for i in dated:
        i["days_left"] = (datetime.fromisoformat(i["registration_deadline"]) - now).days
    return {"upcoming": dated, "no_deadline_stated": undated, "closed": closed,
            "note": "Only events that state a registration deadline appear in the first list. Events without one may close at any time."}


@router.get("/comparisons")
def comparisons(db: DbSession, user: CurrentUser) -> dict[str, Any]:
    rows = list(db.scalars(select(ComparisonHistory).where(ComparisonHistory.user_id == user.id).order_by(ComparisonHistory.created_at.desc()).limit(20)))
    ids = {uuid.UUID(i) for r in rows for i in r.event_ids}
    titles = {e.id: e.title for e in db.scalars(select(Event).where(Event.id.in_(ids)))} if ids else {}
    return {"items": [{"id": str(r.id), "created_at": r.created_at.isoformat(),
                       "events": [{"id": i, "title": titles.get(uuid.UUID(i), "(no longer available)")} for i in r.event_ids]} for r in rows]}


# ------------------------------------------------------------------ participation


@router.post("/participations/{event_id}")
def declare_participation(event_id: uuid.UUID, body: ParticipationIn, db: DbSession, user: CurrentUser) -> dict[str, Any]:
    event = get_event(db, event_id)
    if event.start_date is None:
        raise Unprocessable("This event has no stated date, so participation cannot be declared yet.", code="no_event_date")
    if event.start_date > datetime.now(UTC).date():
        raise Unprocessable("You can declare participation once the event has started.", code="event_not_started")
    row = db.scalar(select(Participation).where(Participation.user_id == user.id, Participation.event_id == event.id))
    if row is None:
        row = Participation(user_id=user.id, event_id=event.id, level="self_declared", conflict_of_interest=body.conflict_of_interest)
        db.add(row)
    else:
        row.conflict_of_interest = body.conflict_of_interest
    db.flush()
    return {"participation": {"event_id": str(event.id), "level": row.level, "conflict_of_interest": row.conflict_of_interest,
                              "event_ended": event_has_ended(event)}}


@router.get("/participations")
def my_participations(db: DbSession, user: CurrentUser) -> dict[str, Any]:
    rows = list(db.execute(select(Participation, Event).join(Event, Event.id == Participation.event_id).where(Participation.user_id == user.id).order_by(Participation.created_at.desc())))
    fb = dict(db.execute(select(FeedbackResponse.event_id, func.count()).where(FeedbackResponse.user_id == user.id).group_by(FeedbackResponse.event_id)).all())
    return {"items": [{"event_id": str(e.id), "title": e.title, "start_date": e.start_date.isoformat() if e.start_date else None,
                       "end_date": e.end_date.isoformat() if e.end_date else None, "level": p.level, "event_ended": event_has_ended(e),
                       "feedback_items_submitted": fb.get(e.id, 0)} for p, e in rows]}


@router.get("/dashboard")
def dashboard(db: DbSession, user: CurrentUser) -> dict[str, Any]:
    recs = build_recommendations(db, user, 5)
    items = saved_with_changes(db, user)
    now = datetime.now(UTC)
    upcoming = sorted([i for i in items if i["registration_deadline"] and datetime.fromisoformat(i["registration_deadline"]) >= now], key=lambda i: i["registration_deadline"])[:5]
    parts = my_participations(db, user)["items"]
    return {
        "has_profile": not recs["needs_profile"], "recommendations": recs["items"], "recommendation_summary": {"considered": recs.get("considered", 0), "excluded": recs["excluded"]["count"]},
        "saved_count": len(items), "upcoming_deadlines": upcoming,
        "changed_saved": [i for i in items if i["changes_since_saved"]][:5],
        "pending_feedback": [p for p in parts if p["event_ended"] and p["feedback_items_submitted"] == 0],
        "participations": parts[:5],
    }



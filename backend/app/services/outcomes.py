"""Outcome analytics computed from stored records only. Every percentage carries its numerator and denominator."""

from __future__ import annotations

from collections import defaultdict
from types import SimpleNamespace
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    AccessibilityItem,
    Claim,
    Dispute,
    Event,
    EventVersion,
    FeedbackResponse,
    GapFinding,
    Participation,
)
from app.services.accessibility import applicable_items
from app.services.scoring import completeness

ESTABLISHED = ("fulfilled", "partially_fulfilled")
UNRESOLVED = ("advertised", "needs_clarification", "evidence_submitted", "corroborated", "unable_to_determine", "unverified")


def ratio(n: int, d: int) -> dict[str, Any]:
    return {"numerator": n, "denominator": d, "pct": round(100 * n / d) if d else None}


def _hours(delta) -> float:  # type: ignore[no-untyped-def]
    return round(delta.total_seconds() / 3600, 1)


def _snapshot_event(snapshot: dict[str, Any]) -> Any:
    keys = ["start_date", "registration_deadline", "registration_url", "canonical_url", "eligibility", "fee_status", "format", "organizer_name",
            "description", "schedule_text", "contact_info", "venue", "city", "category", "judging_criteria", "team_size_max"]
    d = {k: snapshot.get(k) for k in keys}
    d["fee_status"] = d["fee_status"] or "unknown"
    d["format"] = d["format"] or "unknown"
    return SimpleNamespace(**d)


def event_analytics(db: Session, event: Event) -> dict[str, Any]:
    claims = list(db.scalars(select(Claim).where(Claim.event_id == event.id, Claim.is_active.is_(True))))
    total = len(claims)
    by_status: dict[str, int] = defaultdict(int)
    for c in claims:
        by_status[c.status] += 1
    established = sum(by_status[s] for s in ESTABLISHED)
    unresolved = sum(by_status[s] for s in UNRESOLVED)

    versions = list(db.scalars(select(EventVersion).where(EventVersion.event_id == event.id).order_by(EventVersion.version_no)))
    first, last = (versions[0], versions[-1]) if versions else (None, None)
    before = completeness(_snapshot_event(first.snapshot), 0) if first else None
    after = completeness(_snapshot_event(last.snapshot), 0) if last else None
    corrections = [v for v in versions[1:] if v.change_source in ("organizer", "reviewer", "manual")]

    items = list(db.scalars(select(AccessibilityItem).where(AccessibilityItem.event_id == event.id)))
    applicable = applicable_items(event.format)
    keys = {i["key"] for i in applicable}
    documented = sum(1 for i in items if i.item_key in keys and i.state == "documented")
    answered = sum(1 for i in items if i.item_key in keys and i.state in ("documented", "confirmed_unavailable"))

    declared = db.scalar(select(func.count()).select_from(Participation).where(Participation.event_id == event.id)) or 0
    responded = db.scalar(select(func.count(func.distinct(FeedbackResponse.user_id))).where(FeedbackResponse.event_id == event.id)) or 0
    published = db.scalar(select(func.count()).select_from(FeedbackResponse).where(FeedbackResponse.event_id == event.id, FeedbackResponse.status == "published")) or 0
    pending = db.scalar(select(func.count()).select_from(FeedbackResponse).where(FeedbackResponse.event_id == event.id, FeedbackResponse.status == "pending")) or 0

    gaps = list(db.scalars(select(GapFinding).where(GapFinding.event_id == event.id)))
    closed_gaps = [g for g in gaps if g.status in ("resolved", "dismissed")]
    gap_times = [_hours(g.resolved_at - g.detected_at) for g in gaps if g.status == "resolved" and g.resolved_at and g.resolved_by is not None]
    disputes = list(db.scalars(select(Dispute).where(Dispute.event_id == event.id)))
    closed_disputes = [d for d in disputes if d.status in ("upheld", "rejected", "withdrawn")]
    dispute_times = [_hours(d.resolved_at - d.created_at) for d in closed_disputes if d.resolved_at]

    return {
        "event_id": str(event.id),
        "claims": {"total": total, "by_status": dict(by_status), "outcome_established": ratio(established, total),
                   "fulfilled": by_status["fulfilled"], "partially_fulfilled": by_status["partially_fulfilled"],
                   "disputed": by_status["disputed"], "unresolved": unresolved,
                   "note": "‘Established’ means fulfilled or partially fulfilled with the evidence the rules require. Unresolved is unknown, not failure."
                   if total else "No claims have been extracted yet."},
        "completeness": {"before": before, "after": after, "versions": len(versions), "organizer_corrections": len(corrections),
                         "change": (after["filled"] - before["filled"]) if before and after else None,
                         "note": "Compared between the first and current stored version; accessibility is reported separately."},
        "accessibility": {"documented": ratio(documented, len(applicable)), "answered": ratio(answered, len(applicable)),
                          "note": "Items not documented are unknown, not unavailable."},
        "feedback": {"participants_declared": declared, "participants_responded": responded, "response_rate": ratio(responded, declared),
                     "responses_published": published, "responses_pending_moderation": pending},
        "issues": {"gaps_total": len(gaps), "gaps_open": len([g for g in gaps if g.status == "open"]), "gap_resolution_rate": ratio(len(closed_gaps), len(gaps)),
                   "gap_median_hours_to_resolve": sorted(gap_times)[len(gap_times) // 2] if gap_times else None, "gap_resolved_by_people": len(gap_times),
                   "disputes_total": len(disputes), "disputes_closed": ratio(len(closed_disputes), len(disputes)),
                   "dispute_median_hours_to_resolve": sorted(dispute_times)[len(dispute_times) // 2] if dispute_times else None},
        "learning_outcomes": "Not measured. BeforeYouGo has no pre/post assessment data, so it makes no claim about learning gains.",
    }


def platform_analytics(db: Session) -> dict[str, Any]:
    ev = db.scalar(select(func.count()).select_from(Event)) or 0
    claims = db.scalar(select(func.count()).select_from(Claim).where(Claim.is_active.is_(True))) or 0
    by_status = dict(db.execute(select(Claim.status, func.count()).where(Claim.is_active.is_(True)).group_by(Claim.status)).all())
    est = sum(by_status.get(s, 0) for s in ESTABLISHED)
    gaps_total = db.scalar(select(func.count()).select_from(GapFinding)) or 0
    gaps_closed = db.scalar(select(func.count()).select_from(GapFinding).where(GapFinding.status.in_(["resolved", "dismissed"]))) or 0
    fb = dict(db.execute(select(FeedbackResponse.status, func.count()).group_by(FeedbackResponse.status)).all())
    disputes = dict(db.execute(select(Dispute.status, func.count()).group_by(Dispute.status)).all())
    return {"events": ev, "claims": {"total": claims, "by_status": by_status, "outcome_established": ratio(est, claims)},
            "gaps": {"total": gaps_total, "closed": ratio(gaps_closed, gaps_total)}, "feedback_by_status": fb, "disputes_by_status": disputes}

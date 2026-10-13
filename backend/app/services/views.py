"""Serialisation of events for the API. Everything shown to users carries its provenance."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    AccessibilityItem,
    Claim,
    DuplicateCandidate,
    Event,
    EventFieldAssertion,
    EventVersion,
    Evidence,
    GapFinding,
    SavedEvent,
    Source,
    SourceRecord,
    StudentProfile,
)
from app.services.accessibility import accessibility_panel
from app.services.event_fields import FIELD_SPECS, decode_value, jsonable
from app.services.scoring import completeness, evidence_strength, suitability

ORIGIN_LABELS = {
    "indexed": "Indexed from a connected source",
    "organizer_submitted": "Submitted by the organizer",
    "user_submitted": "Submitted by a user (from a public page)",
}


def fee_display(e: Event) -> dict[str, Any]:
    if e.fee_status == "free":
        return {"status": "free", "label": "Free (stated by source)", "amount": None, "currency": None, "uncertain": False}
    if e.fee_status == "paid":
        if e.fee_amount is not None:
            sym = "₹" if (e.fee_currency or "") == "INR" else f"{e.fee_currency or ''} "
            amt = f"{e.fee_amount:.0f}" if e.fee_amount == int(e.fee_amount) else f"{e.fee_amount:.2f}"
            return {"status": "paid", "label": f"From {sym}{amt}", "amount": float(e.fee_amount), "currency": e.fee_currency, "uncertain": False}
        return {"status": "paid", "label": "Paid (amount not stated)", "amount": None, "currency": None, "uncertain": True}
    return {"status": "unknown", "label": "Not stated (not the same as free)", "amount": None, "currency": None, "uncertain": True}


def freshness(e: Event, sources: list[dict[str, Any]]) -> dict[str, Any]:
    now = datetime.now(UTC)
    limit = get_settings().stale_after_days
    last = e.last_refreshed_at or e.last_updated_at
    age = (now - last).days if last else None
    degraded = [s["name"] for s in sources if s.get("source_status") in ("degraded", "blocked")]
    if e.origin_type != "indexed" and not sources:
        state, msg = "submitted", "Information supplied by a person; not refreshed automatically."
    elif age is None:
        state, msg = "unknown", "No retrieval time recorded."
    elif age > limit:
        state, msg = "stale", f"Last retrieved {age} days ago (policy: {limit} days). Check the original source."
    elif degraded:
        state, msg = "unconfirmed", f"Last retrieved {age} day(s) ago, but {', '.join(degraded)} could not be reached recently."
    else:
        state, msg = "fresh", f"Retrieved {age} day(s) ago."
    return {"state": state, "message": msg, "last_retrieved_at": last.isoformat() if last else None, "age_days": age}


def _bulk(db: Session, events: list[Event], user_id: Any | None) -> dict[str, Any]:
    ids = [e.id for e in events]
    if not ids:
        return {"sources": {}, "claims": {}, "access": {}, "saved": set()}
    src: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for r, s in db.execute(select(SourceRecord, Source).join(Source, Source.id == SourceRecord.source_id).where(SourceRecord.event_id.in_(ids))):
        src[r.event_id].append({"key": s.key, "name": s.name, "source_status": s.status, "retrieved_at": r.retrieved_at.isoformat(),
                                "source_url": r.source_url, "event_url": r.event_url, "attribution": s.attribution, "missing_since": r.missing_since.isoformat() if r.missing_since else None})
    claims: dict[Any, list[Claim]] = defaultdict(list)
    for c in db.scalars(select(Claim).where(Claim.event_id.in_(ids), Claim.is_active.is_(True))):
        claims[c.event_id].append(c)
    access: dict[Any, int] = defaultdict(int)
    for eid, n in db.execute(select(AccessibilityItem.event_id, func.count()).where(AccessibilityItem.event_id.in_(ids), AccessibilityItem.state == "documented").group_by(AccessibilityItem.event_id)):
        access[eid] = n
    saved = set(db.scalars(select(SavedEvent.event_id).where(SavedEvent.user_id == user_id, SavedEvent.event_id.in_(ids)))) if user_id else set()
    return {"sources": src, "claims": claims, "access": access, "saved": saved}


def _location(e: Event) -> str | None:
    parts = [p for p in (e.venue, e.city, e.state, e.country) if p]
    if e.format == "online":
        return "Online" + (f" ({e.country})" if e.country and not e.city else "")
    return ", ".join(parts) or None


def card(e: Event, bulk: dict[str, Any], profile: StudentProfile | None, reasons: list[str] | None = None) -> dict[str, Any]:
    sources = bulk["sources"].get(e.id, [])
    claims = bulk["claims"].get(e.id, [])
    comp = completeness(e, bulk["access"].get(e.id, 0))
    fit = None
    if profile is not None:
        fit = suitability(e, profile, claim_categories={c.category for c in claims})
        fit = {k: fit[k] for k in ("score", "label", "eligible", "hard_violations", "coverage", "why_match", "why_skip")}
    return {
        "id": str(e.id), "title": e.title, "organizer": e.organizer_name, "category": e.category, "format": e.format,
        "topics": e.topics or [], "start_date": e.start_date.isoformat() if e.start_date else None,
        "end_date": e.end_date.isoformat() if e.end_date else None,
        "registration_deadline": e.registration_deadline.isoformat() if e.registration_deadline else None,
        "deadline_stated": e.registration_deadline is not None, "location": _location(e), "city": e.city, "country": e.country,
        "fee": fee_display(e), "lifecycle_status": e.lifecycle_status, "canonical_url": e.canonical_url,
        "origin": {"type": e.origin_type, "label": ORIGIN_LABELS.get(e.origin_type, e.origin_type)},
        "sources": [{"key": s["key"], "name": s["name"], "retrieved_at": s["retrieved_at"]} for s in sources],
        "freshness": freshness(e, sources), "completeness": {"score": comp["score"], "filled": comp["filled"], "total": comp["total"]},
        "missing_information": [m["label"] for m in comp["missing"][:5]], "matched_because": reasons or [],
        "claims_count": len(claims), "verification_state": e.verification_state, "saved": e.id in bulk["saved"], "fit": fit,
    }


def cards(db: Session, events: list[Event], user_id: Any | None, profile: StudentProfile | None, reasons: list[str] | None = None) -> list[dict[str, Any]]:
    bulk = _bulk(db, events, user_id)
    return [card(e, bulk, profile, reasons) for e in events]


def provenance(db: Session, event: Event) -> dict[str, Any]:
    rows = list(db.execute(
        select(EventFieldAssertion, Source.key, Source.name).outerjoin(Source, Source.id == EventFieldAssertion.source_id)
        .where(EventFieldAssertion.event_id == event.id, EventFieldAssertion.is_current.is_(True))
    ))
    by_field: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for a, skey, sname in rows:
        by_field[a.field_name].append({"value": jsonable(decode_value(a.field_name, a.value)), "origin": a.origin, "source_key": skey,
                                       "source_name": sname or ("Organizer" if a.origin == "organizer" else "Manual correction" if a.origin == "manual" else None),
                                       "source_url": a.source_url, "retrieved_at": a.retrieved_at.isoformat()})
    fields, conflicts = {}, []
    for name, lst in by_field.items():
        distinct = {json.dumps(x["value"], sort_keys=True) for x in lst}
        fields[name] = {"label": FIELD_SPECS[name].label, "assertions": lst}
        if len(distinct) > 1:
            conflicts.append({"field": name, "label": FIELD_SPECS[name].label, "values": lst})
    return {"fields": fields, "conflicts": conflicts}


def claim_dict(c: Claim, ev_counts: dict[Any, dict[str, int]] | None = None) -> dict[str, Any]:
    return {
        "id": str(c.id), "original_text": c.original_text, "normalized_text": c.normalized_text, "category": c.category,
        "claim_type": c.claim_type, "responsible_party": c.responsible_party, "conditions": c.conditions,
        "numeric_values": c.numeric_values, "missing_details": c.missing_details, "verification_questions": c.verification_questions,
        "evidence_url": c.evidence_url, "evidence_excerpt": c.evidence_excerpt, "extraction_method": c.extraction_method,
        "extraction_confidence": c.extraction_confidence, "status": c.status, "status_updated_at": c.status_updated_at.isoformat(),
        "last_checked_at": c.last_checked_at.isoformat() if c.last_checked_at else None,
        "evidence_counts": (ev_counts or {}).get(c.id, {}),
        "provenance": {"llm": "ai_interpretation", "deterministic": "deterministic_rule", "source_field": "source_field", "manual": "manual"}.get(c.extraction_method, c.extraction_method),
    }


def event_detail(db: Session, e: Event, user: Any | None, profile: StudentProfile | None) -> dict[str, Any]:
    bulk = _bulk(db, [e], user.id if user else None)
    base = card(e, bulk, None)
    claims = sorted(bulk["claims"].get(e.id, []), key=lambda c: c.created_at)
    ev_counts: dict[Any, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    accepted_independent = 0
    for ev in db.scalars(select(Evidence).where(Evidence.event_id == e.id)):
        if ev.claim_id:
            ev_counts[ev.claim_id][f"{ev.kind}:{ev.review_status}"] += 1
        if ev.review_status == "accepted" and ev.kind in ("public_source", "independent_review") and ev.claim_specific:
            accepted_independent += 1
    gaps = list(db.scalars(select(GapFinding).where(GapFinding.event_id == e.id).order_by(GapFinding.detected_at)))
    sev = {"high": 0, "medium": 1, "low": 2}
    gaps.sort(key=lambda g: (g.status != "open", sev.get(g.severity, 3), g.rule_id))
    versions = list(db.scalars(select(EventVersion).where(EventVersion.event_id == e.id).order_by(EventVersion.version_no.desc()).limit(25)))
    panel = accessibility_panel(db, e)
    dup = list(db.scalars(select(DuplicateCandidate).where((DuplicateCandidate.event_a_id == e.id) | (DuplicateCandidate.event_b_id == e.id), DuplicateCandidate.status == "open")))
    detail = {
        **base,
        "description": e.description, "eligibility": e.eligibility, "prerequisites": e.prerequisites, "other_costs": e.other_costs,
        "prize_details": e.prize_details, "schedule_text": e.schedule_text, "judging_criteria": e.judging_criteria,
        "refund_policy": e.refund_policy, "contact_info": e.contact_info, "accommodation_info": e.accommodation_info,
        "time_commitment": e.time_commitment, "team_size": {"min": e.team_size_min, "max": e.team_size_max},
        "allows_cross_college_teams": e.allows_cross_college_teams, "offers_certificate": e.offers_certificate,
        "offers_mentorship": e.offers_mentorship, "registration_url": e.registration_url, "organizer_url": e.organizer_url,
        "extras": e.extras, "first_discovered_at": e.first_discovered_at.isoformat(), "owner_org_id": str(e.owner_org_id) if e.owner_org_id else None,
        "source_records": bulk["sources"].get(e.id, []), "provenance": provenance(db, e),
        "claims": [claim_dict(c, ev_counts) for c in claims],
        "gaps": [{"id": str(g.id), "rule_id": g.rule_id, "gap": g.gap, "source_text": g.source_text, "why_it_matters": g.why_it_matters,
                  "severity": g.severity, "severity_rule": g.severity_rule, "student_question": g.student_question,
                  "organizer_fix": g.organizer_fix, "scope_note": g.scope_note, "status": g.status,
                  "detected_at": g.detected_at.isoformat(), "resolution_note": g.resolution_note} for g in gaps],
        "accessibility": panel,
        "completeness": completeness(e, panel["documented_count"]),
        "evidence_strength": evidence_strength(len(bulk["sources"].get(e.id, [])), claims, accepted_independent, e.origin_type),
        "versions": [{"version_no": v.version_no, "changed_at": v.changed_at.isoformat(), "change_source": v.change_source,
                      "is_material": v.is_material, "summary": v.summary, "diff": v.diff} for v in versions],
        "possible_duplicates": [{"id": str(d.id), "other_event_id": str(d.event_b_id if d.event_a_id == e.id else d.event_a_id),
                                 "similarity": d.similarity, "reasons": d.reasons} for d in dup],
        "analysis_pending": len(claims) == 0,
    }
    detail["fit"] = suitability(e, profile, claim_categories={c.category for c in claims},
                                access={i["key"]: i["state"] for i in panel["items"]}) if profile else None
    return detail

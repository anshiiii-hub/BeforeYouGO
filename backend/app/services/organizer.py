"""Organizer workflows: create/edit listings, pre-publication audit, and the exportable audit report."""

from __future__ import annotations

import html
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import Unprocessable
from app.domain.enums import AnalysisInput, FieldOrigin, OriginType
from app.models import (
    AuditLog,
    Claim,
    Dispute,
    Event,
    EventVersion,
    GapFinding,
    Organization,
    OrganizerResponse,
    User,
)
from app.schemas.api import EventFieldsIn
from app.services.accessibility import accessibility_panel
from app.services.analyzer.pipeline import analyze, event_corpus
from app.services.ingest import assert_fields, recompute_event
from app.services.outcomes import event_analytics
from app.services.scoring import completeness, evidence_strength
from app.services.taxonomy import classify_category, topics_from_text
from app.services.urls import display_url
from app.services.views import claim_dict, provenance

IST = ZoneInfo("Asia/Kolkata")
SEV = {"high": 3, "medium": 2, "low": 1}


def _clean_values(data: EventFieldsIn) -> dict[str, Any]:
    raw = data.model_dump(exclude_unset=True, exclude_none=True)
    raw.pop("change_note", None)
    raw.pop("organization_id", None)
    raw.pop("publish", None)
    vals: dict[str, Any] = {}
    for k, v in raw.items():
        if isinstance(v, StrEnum):
            v = v.value
        vals[k] = v
    for k in ("canonical_url", "registration_url", "organizer_url"):
        if k in vals:
            cleaned = display_url(vals[k])
            if not cleaned:
                raise Unprocessable(f"{k.replace('_', ' ').capitalize()} must be a valid http(s) URL.", code="invalid_url")
            vals[k] = cleaned
    if isinstance(vals.get("registration_deadline"), datetime):
        dl = vals["registration_deadline"]
        vals["registration_deadline"] = dl.replace(tzinfo=IST) if dl.tzinfo is None else dl.astimezone(UTC)
    s, e = vals.get("start_date"), vals.get("end_date")
    if s and e and e < s:
        raise Unprocessable("The end date cannot be before the start date.", code="invalid_dates")
    mn, mx = vals.get("team_size_min"), vals.get("team_size_max")
    if mn and mx and mx < mn:
        raise Unprocessable("Maximum team size cannot be smaller than the minimum.", code="invalid_team_size")
    status, amount = vals.get("fee_status"), vals.get("fee_amount")
    if status == "free" and amount not in (None, Decimal(0)):
        raise Unprocessable("A free event cannot also state a fee amount.", code="fee_conflict")
    if amount is not None and Decimal(amount) > 0:
        vals["fee_status"] = "paid"
        vals.setdefault("fee_currency", "INR")
        vals["fee_currency"] = vals["fee_currency"].upper()
    elif status == "free":
        vals["fee_amount"] = Decimal(0)
        vals["fee_currency"] = vals.get("fee_currency", "INR").upper()
    return vals


def _check_dates_with_existing(event: Event | None, vals: dict[str, Any]) -> None:
    start = vals.get("start_date") or (event.start_date if event else None)
    end = vals.get("end_date") or (event.end_date if event else None) or start
    dl = vals.get("registration_deadline") or (event.registration_deadline if event else None)
    if start and end and end < start:
        raise Unprocessable("The end date cannot be before the start date.", code="invalid_dates")
    if dl and end and dl.astimezone(IST).date() > end:
        raise Unprocessable("The registration deadline cannot be after the event ends.", code="invalid_deadline")


def create_event(db: Session, user: User, org: Organization, data: EventFieldsIn, *, publish: bool) -> Event:
    vals = _clean_values(data)
    _check_dates_with_existing(None, vals)
    event = Event(title=vals["title"], origin_type=OriginType.ORGANIZER_SUBMITTED.value, verification_state="organizer_submitted", extras={},
                  owner_org_id=org.id, created_by=user.id, is_published=False)
    db.add(event)
    db.flush()
    vals.setdefault("organizer_name", org.name)
    if org.website:
        vals.setdefault("organizer_url", org.website)
    if "category" not in vals:
        vals["category"] = classify_category(vals["title"], vals.get("description", "")[:1500])
    topics = topics_from_text(f"{vals['title']} {vals.get('description', '')[:3000]}")
    if topics:
        vals["topics"] = topics
    assert_fields(db, event, vals, {}, source=None, record=None, source_url=vals.get("canonical_url"), actor_id=user.id, default_origin=FieldOrigin.ORGANIZER.value)
    recompute_event(db, event, change_source="organizer", actor_id=user.id)
    run_analysis(db, event, user)
    if publish:
        ensure_publishable(event)
        event.is_published = True
    return event


def update_event(db: Session, user: User, event: Event, data: EventFieldsIn, note: str | None) -> tuple[Event, list[str]]:
    vals = _clean_values(data)
    if not vals:
        raise Unprocessable("No changes were supplied.", code="no_changes")
    _check_dates_with_existing(event, vals)
    assert_fields(db, event, vals, {}, source=None, record=None, source_url=vals.get("canonical_url") or event.canonical_url, actor_id=user.id,
                  default_origin=FieldOrigin.ORGANIZER.value)
    version = recompute_event(db, event, change_source="organizer", actor_id=user.id)
    if version is not None and note:
        version.summary = f"{version.summary} Note: {note}"
    run_analysis(db, event, user)
    return event, sorted(vals)


def ensure_publishable(event: Event) -> None:
    problems = []
    if not event.title or len(event.title.strip()) < 3:
        problems.append("A title is required.")
    if not event.description or len(event.description.strip()) < 40:
        problems.append("Add a description of at least 40 characters so students can judge the event.")
    if problems:
        raise Unprocessable("This listing cannot be published yet.", details=problems, code="not_publishable")


def run_analysis(db: Session, event: Event, user: User | None) -> dict[str, Any]:
    return analyze(db, text=event_corpus(event), input_type=AnalysisInput.EVENT, event=event, canonical_url=event.canonical_url, actor=user,
                   source_label="the organizer's listing")


def _urgency(event: Event) -> tuple[int, str]:
    today = datetime.now(UTC).date()
    days: list[int] = []
    if event.start_date:
        days.append((event.start_date - today).days)
    if event.registration_deadline:
        days.append((event.registration_deadline.date() - today).days)
    if not days:
        return 2, "dates not stated"
    d = min(days)
    if d <= 7:
        return 3, "within 7 days"
    if d <= 30:
        return 2, "within 30 days"
    return 1, "more than 30 days away"


def gap_item(g: GapFinding, urgency: int, urgency_label: str) -> dict[str, Any]:
    impact = SEV.get(g.severity, 1)
    return {"id": str(g.id), "rule_id": g.rule_id, "gap": g.gap, "severity": g.severity, "severity_rule": g.severity_rule, "why_it_matters": g.why_it_matters,
            "student_question": g.student_question, "organizer_fix": g.organizer_fix, "source_text": g.source_text, "status": g.status, "scope_note": g.scope_note,
            "impact": impact, "urgency": urgency, "urgency_reason": urgency_label, "priority": impact * urgency, "resolution_note": g.resolution_note,
            "next_action": f"Edit the listing: {g.organizer_fix}"}


def publication_audit(db: Session, event: Event) -> dict[str, Any]:
    urgency, label = _urgency(event)
    gaps = list(db.scalars(select(GapFinding).where(GapFinding.event_id == event.id)))
    open_gaps = sorted((gap_item(g, urgency, label) for g in gaps if g.status == "open"), key=lambda x: (-x["priority"], x["rule_id"]))
    panel = accessibility_panel(db, event)
    comp = completeness(event, panel["documented_count"])
    claims = list(db.scalars(select(Claim).where(Claim.event_id == event.id, Claim.is_active.is_(True))))
    vague = [{"claim_id": str(c.id), "text": c.original_text, "missing_details": c.missing_details, "questions": c.verification_questions,
              "suggestion": "Replace the vague wording with a specific, checkable commitment (what, how many, by when, under what conditions)."}
             for c in claims if c.claim_type == "vague" and c.status in ("advertised", "needs_clarification")]
    blocking = []
    if not event.description or len(event.description.strip()) < 40:
        blocking.append("Add a description of at least 40 characters before publishing.")
    high = [g for g in open_gaps if g["severity"] == "high"]
    state = "blocked" if blocking else ("needs_attention" if high else "ready")
    next_actions = [{"label": g["gap"], "action": g["next_action"], "priority": g["priority"]} for g in open_gaps[:5]]
    return {
        "event_id": str(event.id), "is_published": event.is_published,
        "readiness": {"state": state, "blocking": blocking, "high_severity_open": len(high),
                      "summary": {"ready": "No high-severity gaps remain. You can publish.", "needs_attention": f"{len(high)} high-severity gap(s) remain; publishing is allowed but students will see them.",
                                  "blocked": "The listing cannot be published yet."}[state]},
        "completeness": comp, "issues": open_gaps, "vague_claims": vague, "accessibility": {"documented": panel["documented_count"], "total": panel["total_count"],
                                                                                          "checklist": panel["organizer_checklist"], "note": panel["completeness_note"]},
        "prioritisation": "Priority = impact (high 3, medium 2, low 1) × urgency (event or deadline within 7 days 3, within 30 days 2, later 1, dates unknown 2).",
        "next_actions": next_actions,
        "closed_issues": [gap_item(g, urgency, label) for g in gaps if g.status != "open"],
    }


def organizer_issues(db: Session, events: list[Event]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for e in events:
        urgency, label = _urgency(e)
        for g in db.scalars(select(GapFinding).where(GapFinding.event_id == e.id, GapFinding.status == "open")):
            out.append({**gap_item(g, urgency, label), "event_id": str(e.id), "event_title": e.title, "type": "information_gap"})
        for d in db.scalars(select(Dispute).where(Dispute.event_id == e.id, Dispute.status.in_(["open", "under_review"]))):
            out.append({"id": str(d.id), "type": "dispute", "event_id": str(e.id), "event_title": e.title, "gap": f"Open {d.kind.replace('_', ' ')}", "severity": "medium",
                        "priority": 6, "status": d.status, "why_it_matters": "Awaiting a reviewer decision.", "next_action": "Wait for review or add supporting evidence."})
        for c in db.scalars(select(Claim).where(Claim.event_id == e.id, Claim.status == "needs_clarification", Claim.is_active.is_(True))):
            out.append({"id": str(c.id), "type": "claim_clarification", "event_id": str(e.id), "event_title": e.title, "gap": f"Clarification requested: {c.original_text[:90]}",
                        "severity": "medium", "priority": 6, "status": c.status, "why_it_matters": "A reviewer asked for clarification of this promise.",
                        "next_action": "Respond with a written organizer response or evidence."})
    out.sort(key=lambda x: -x["priority"])
    return out


# ------------------------------------------------------------------ report


def build_report(db: Session, event: Event) -> dict[str, Any]:
    panel = accessibility_panel(db, event)
    claims = list(db.scalars(select(Claim).where(Claim.event_id == event.id).order_by(Claim.created_at)))
    from app.models import Evidence

    ev_counts: dict[Any, dict[str, int]] = {}
    for e in db.scalars(select(Evidence).where(Evidence.event_id == event.id)):
        if e.claim_id:
            ev_counts.setdefault(e.claim_id, {}).setdefault(f"{e.kind}:{e.review_status}", 0)
            ev_counts[e.claim_id][f"{e.kind}:{e.review_status}"] += 1
    accepted_ind = sum(1 for e in db.scalars(select(Evidence).where(Evidence.event_id == event.id)) if e.review_status == "accepted" and e.kind in ("public_source", "independent_review"))
    versions = list(db.scalars(select(EventVersion).where(EventVersion.event_id == event.id).order_by(EventVersion.version_no)))
    trail = list(db.scalars(select(AuditLog).where(AuditLog.target_type.in_(["event", "claim", "dispute", "evidence"]), AuditLog.details["event_id"].astext == str(event.id)).order_by(AuditLog.created_at.desc()).limit(100)))
    trail += list(db.scalars(select(AuditLog).where(AuditLog.target_type == "event", AuditLog.target_id == str(event.id)).order_by(AuditLog.created_at.desc()).limit(50)))
    trail = sorted({t.id: t for t in trail}.values(), key=lambda t: t.created_at, reverse=True)
    disputes = list(db.scalars(select(Dispute).where(Dispute.event_id == event.id).order_by(Dispute.created_at)))
    responses = list(db.scalars(select(OrganizerResponse).where(OrganizerResponse.event_id == event.id).order_by(OrganizerResponse.created_at)))
    audit_ = publication_audit(db, event)
    from app.api.accountability import outcome_summary  # local import avoids a cycle at module load

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "event": {"id": str(event.id), "title": event.title, "organizer": event.organizer_name, "canonical_url": event.canonical_url, "category": event.category,
                  "format": event.format, "start_date": event.start_date.isoformat() if event.start_date else None,
                  "end_date": event.end_date.isoformat() if event.end_date else None, "origin_type": event.origin_type, "is_published": event.is_published},
        "completeness": audit_["completeness"], "evidence_strength": evidence_strength(1, claims, accepted_ind, event.origin_type),
        "open_issues": audit_["issues"], "closed_issues": audit_["closed_issues"],
        "claims": [claim_dict(c, ev_counts) for c in claims], "accessibility": panel, "outcomes": outcome_summary(db, event),
        "analytics": event_analytics(db, event),
        "versions": [{"version_no": v.version_no, "changed_at": v.changed_at.isoformat(), "change_source": v.change_source, "summary": v.summary, "is_material": v.is_material} for v in versions],
        "disputes": [{"kind": d.kind, "status": d.status, "description": d.description, "created_at": d.created_at.isoformat(), "resolution_note": d.resolution_note} for d in disputes],
        "organizer_responses": [{"body": r.body, "created_at": r.created_at.isoformat()} for r in responses],
        "audit_trail": [{"at": t.created_at.isoformat(), "actor_role": t.actor_role, "action": t.action, "details": t.details} for t in trail],
        "provenance": provenance(db, event),
        "disclaimer": "This report lists advertised promises, what evidence has been reviewed and what is unknown. It does not rate the organizer's honesty.",
    }


def report_markdown(r: dict[str, Any]) -> str:
    e = r["event"]
    L = [f"# Audit report: {e['title']}", "", f"Generated {r['generated_at']}  ", f"Organizer: {e['organizer'] or 'not stated'} · Category: {e['category']} · Format: {e['format']}  ",
         f"Dates: {e['start_date'] or 'not stated'} to {e['end_date'] or 'not stated'}  ", f"Record origin: {e['origin_type']}", "",
         "## Information completeness", f"{r['completeness']['filled']} of {r['completeness']['total']} applicable details present.", ""]
    for m in r["completeness"]["missing"]:
        L.append(f"- Missing: {m['label']}")
    L += ["", f"## Open issues ({len(r['open_issues'])})"]
    for g in r["open_issues"]:
        L += [f"- **[{g['severity'].upper()}] {g['gap']}** — {g['why_it_matters']} Fix: {g['organizer_fix']}"]
    L += ["", f"## Advertised promises ({len(r['claims'])})"]
    for c in r["claims"]:
        L += [f"- “{c['original_text']}” — {c['category']}, {c['claim_type']}, status **{c['status']}**"]
    L += ["", "## Accessibility", r["accessibility"]["completeness_note"]]
    for i in r["accessibility"]["items"]:
        L.append(f"- {i['label']}: {i['state'].replace('_', ' ')}")
    o = r["outcomes"]
    L += ["", "## Participant outcomes", f"{o['participants_responded']} of {o['participants_declared']} declared participants responded."]
    for c in o["claims"]:
        L.append(f"- {c['text'][:100]} — {c['summary']}")
    L += ["", "## Change history"] + [f"- v{v['version_no']} {v['changed_at'][:10]} ({v['change_source']}): {v['summary']}" for v in r["versions"]]
    L += ["", f"> {r['disclaimer']}"]
    return "\n".join(L)


def report_html(r: dict[str, Any]) -> str:
    esc = html.escape
    e = r["event"]
    parts = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'><title>Audit report: {esc(e['title'])}</title>",
             "<style>body{font:15px/1.5 system-ui,sans-serif;max-width:860px;margin:2rem auto;padding:0 1rem;color:#111}h1{font-size:1.6rem}h2{margin-top:1.8rem;border-bottom:1px solid #ccc}"
             "table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccc;padding:.35rem .5rem;text-align:left;vertical-align:top}.sev-high{color:#b00020}</style></head><body>",
             f"<h1>Audit report: {esc(e['title'])}</h1><p>Generated {esc(r['generated_at'])}<br>Organizer: {esc(e['organizer'] or 'not stated')} · {esc(e['category'])} · {esc(e['format'])}<br>"
             f"Record origin: {esc(e['origin_type'])}</p>",
             f"<h2>Information completeness</h2><p>{r['completeness']['filled']} of {r['completeness']['total']} applicable details present.</p><ul>"
             + "".join(f"<li>Missing: {esc(m['label'])}</li>" for m in r["completeness"]["missing"]) + "</ul>",
             f"<h2>Open issues ({len(r['open_issues'])})</h2><table><tr><th>Severity</th><th>Gap</th><th>Why it matters</th><th>Suggested fix</th></tr>"
             + "".join(f"<tr><td class='sev-{esc(g['severity'])}'>{esc(g['severity'])}</td><td>{esc(g['gap'])}</td><td>{esc(g['why_it_matters'])}</td><td>{esc(g['organizer_fix'])}</td></tr>" for g in r["open_issues"]) + "</table>",
             f"<h2>Advertised promises ({len(r['claims'])})</h2><table><tr><th>Promise (as written)</th><th>Category</th><th>Type</th><th>Status</th></tr>"
             + "".join(f"<tr><td>{esc(c['original_text'])}</td><td>{esc(c['category'])}</td><td>{esc(c['claim_type'])}</td><td>{esc(c['status'])}</td></tr>" for c in r["claims"]) + "</table>",
             f"<h2>Accessibility</h2><p>{esc(r['accessibility']['completeness_note'])}</p><ul>"
             + "".join(f"<li>{esc(i['label'])}: {esc(i['state'].replace('_', ' '))}</li>" for i in r["accessibility"]["items"]) + "</ul>",
             f"<h2>Participant outcomes</h2><p>{r['outcomes']['participants_responded']} of {r['outcomes']['participants_declared']} declared participants responded.</p><ul>"
             + "".join(f"<li>{esc(c['text'][:120])} — {esc(c['summary'])}</li>" for c in r["outcomes"]["claims"]) + "</ul>",
             "<h2>Change history</h2><ul>" + "".join(f"<li>v{v['version_no']} {esc(v['changed_at'][:10])} ({esc(v['change_source'])}): {esc(v['summary'] or '')}</li>" for v in r["versions"]) + "</ul>",
             f"<p><em>{esc(r['disclaimer'])}</em></p></body></html>"]
    return "".join(parts)



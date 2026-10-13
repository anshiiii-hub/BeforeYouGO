from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from sqlalchemy import func, select

from app.api.accountability import claim_full
from app.api.common import client_ip, get_claim, get_event, require_owner
from app.core.deps import DbSession, RequireOrganizer, RequireOrganizerOnly, user_org_ids
from app.core.errors import Conflict, Forbidden, NotFound, Unprocessable
from app.domain.enums import ExtractionMethod
from app.models import (
    AccessibilityItem,
    Claim,
    Dispute,
    Event,
    EventClaimRequest,
    FeedbackResponse,
    GapFinding,
    Organization,
    OrganizationMember,
    OrganizerResponse,
)
from app.models.base import utcnow
from app.schemas.api import (
    AccessibilityIn,
    ClaimCorrectionIn,
    GapResolveIn,
    ManualClaimIn,
    OrganizerResponseIn,
    OrgEventCreateIn,
    OrgEventUpdateIn,
    OrgIn,
    OwnershipRequestIn,
)
from app.services import organizer as org_svc
from app.services.accessibility import BY_KEY, accessibility_panel
from app.services.analyzer.deterministic import extract_numbers
from app.services.analyzer.pipeline import reclassify
from app.services.audit import audit
from app.services.claims import create_claim
from app.services.outcomes import event_analytics
from app.services.urls import display_url
from app.services.views import _bulk, cards

router = APIRouter(prefix="/api/organizer", tags=["organizer"])


def _my_orgs(db, user) -> list[Organization]:  # type: ignore[no-untyped-def]
    ids = user_org_ids(db, user)
    return list(db.scalars(select(Organization).where(Organization.id.in_(ids)).order_by(Organization.name))) if ids else []


@router.post("/orgs", status_code=201)
def create_org(body: OrgIn, db: DbSession, user: RequireOrganizerOnly, request: Request) -> dict[str, Any]:
    if db.scalar(select(Organization.id).where(func.lower(Organization.name) == body.name.lower())):
        raise Conflict("An organization with this name already exists. Ask its administrator to add you.", code="org_exists")
    website = None
    if body.website:
        website = display_url(body.website)
        if not website:
            raise Unprocessable("The website must be a valid http(s) URL.", code="invalid_url")
    org = Organization(name=body.name, website=website, created_by=user.id)
    db.add(org)
    db.flush()
    db.add(OrganizationMember(organization_id=org.id, user_id=user.id))
    audit(db, actor=user, action="org.created", target_type="organization", target_id=org.id, ip=client_ip(request))
    return {"id": str(org.id), "name": org.name, "website": org.website}


@router.get("/orgs")
def my_orgs(db: DbSession, user: RequireOrganizer) -> dict[str, Any]:
    return {"items": [{"id": str(o.id), "name": o.name, "website": o.website} for o in _my_orgs(db, user)]}


def _owned_events(db, user) -> list[Event]:  # type: ignore[no-untyped-def]
    if user.role == "admin":
        return list(db.scalars(select(Event).where(Event.owner_org_id.is_not(None)).order_by(Event.last_updated_at.desc()).limit(200)))
    ids = user_org_ids(db, user)
    if not ids:
        return []
    return list(db.scalars(select(Event).where(Event.owner_org_id.in_(ids)).order_by(Event.last_updated_at.desc())))


@router.get("/events")
def my_events(db: DbSession, user: RequireOrganizer) -> dict[str, Any]:
    events = _owned_events(db, user)
    if not events:
        return {"items": [], "total": 0}
    bulk = _bulk(db, events, user.id)
    out = []
    for c, e in zip(cards(db, events, user.id, None), events, strict=True):
        gaps = list(db.scalars(select(GapFinding).where(GapFinding.event_id == e.id, GapFinding.status == "open")))
        c.update({"is_published": e.is_published, "open_gaps": len(gaps), "high_gaps": sum(1 for g in gaps if g.severity == "high"),
                  "pending_feedback": db.scalar(select(func.count()).select_from(FeedbackResponse).where(FeedbackResponse.event_id == e.id, FeedbackResponse.status == "pending")) or 0,
                  "open_disputes": db.scalar(select(func.count()).select_from(Dispute).where(Dispute.event_id == e.id, Dispute.status.in_(["open", "under_review"]))) or 0})
        out.append(c)
    _ = bulk
    return {"items": out, "total": len(out)}


@router.post("/events", status_code=201)
def create_event(body: OrgEventCreateIn, db: DbSession, user: RequireOrganizerOnly, request: Request) -> dict[str, Any]:
    org = db.get(Organization, body.organization_id)
    if org is None or (user.role != "admin" and org.id not in user_org_ids(db, user)):
        raise Forbidden("You can only create events for organizations you belong to.", code="not_org_member")
    event = org_svc.create_event(db, user, org, body, publish=body.publish)
    audit(db, actor=user, action="event.created", target_type="event", target_id=event.id, details={"org": str(org.id), "published": event.is_published}, ip=client_ip(request))
    return {"id": str(event.id), "is_published": event.is_published, "audit": org_svc.publication_audit(db, event)}


@router.patch("/events/{event_id}")
def update_event(event_id: uuid.UUID, body: OrgEventUpdateIn, db: DbSession, user: RequireOrganizerOnly, request: Request) -> dict[str, Any]:
    event = get_event(db, event_id, include_unpublished_for=user)
    require_owner(db, user, event)
    _, changed = org_svc.update_event(db, user, event, body, body.change_note)
    audit(db, actor=user, action="event.updated", target_type="event", target_id=event.id, details={"fields": changed}, ip=client_ip(request))
    return {"id": str(event.id), "changed_fields": changed, "audit": org_svc.publication_audit(db, event)}


@router.post("/events/{event_id}/publish")
def publish(event_id: uuid.UUID, db: DbSession, user: RequireOrganizerOnly, request: Request) -> dict[str, Any]:
    event = get_event(db, event_id, include_unpublished_for=user)
    require_owner(db, user, event)
    org_svc.ensure_publishable(event)
    event.is_published = True
    audit(db, actor=user, action="event.published", target_type="event", target_id=event.id, ip=client_ip(request))
    return {"is_published": True, "audit": org_svc.publication_audit(db, event)}


@router.post("/events/{event_id}/unpublish")
def unpublish(event_id: uuid.UUID, db: DbSession, user: RequireOrganizerOnly, request: Request) -> dict[str, Any]:
    event = get_event(db, event_id, include_unpublished_for=user)
    require_owner(db, user, event)
    event.is_published = False
    audit(db, actor=user, action="event.unpublished", target_type="event", target_id=event.id, ip=client_ip(request))
    return {"is_published": False}


@router.get("/events/{event_id}/audit")
def get_audit(event_id: uuid.UUID, db: DbSession, user: RequireOrganizer) -> dict[str, Any]:
    event = get_event(db, event_id, include_unpublished_for=user)
    require_owner(db, user, event)
    return org_svc.publication_audit(db, event)


@router.post("/events/{event_id}/audit")
def rerun_audit(event_id: uuid.UUID, db: DbSession, user: RequireOrganizerOnly) -> dict[str, Any]:
    event = get_event(db, event_id, include_unpublished_for=user)
    require_owner(db, user, event)
    org_svc.run_analysis(db, event, user)
    return org_svc.publication_audit(db, event)


@router.get("/issues")
def issues(db: DbSession, user: RequireOrganizer) -> dict[str, Any]:
    items = org_svc.organizer_issues(db, _owned_events(db, user))
    return {"items": items, "total": len(items), "ordering": "Highest priority first (impact × urgency)."}


# ------------------------------------------------------------------ claims, gaps, accessibility


@router.post("/events/{event_id}/claims", status_code=201)
def add_claim(event_id: uuid.UUID, body: ManualClaimIn, db: DbSession, user: RequireOrganizerOnly) -> dict[str, Any]:
    event = get_event(db, event_id, include_unpublished_for=user)
    require_owner(db, user, event)
    nums = extract_numbers(body.original_text)
    claim, created = create_claim(db, event, original_text=body.original_text, normalized_text=body.original_text, category=body.category.value,
                                  claim_type=body.claim_type.value, method=ExtractionMethod.MANUAL, responsible_party=body.responsible_party,
                                  conditions=body.conditions, numeric_values=nums, evidence_url=event.canonical_url, evidence_excerpt=body.original_text, actor=user)
    if not created:
        raise Conflict("This promise is already recorded for the event.", code="claim_exists")
    audit(db, actor=user, action="claim.added", target_type="claim", target_id=claim.id, details={"event_id": str(event.id)})
    return claim_full(db, claim, user)


@router.patch("/claims/{claim_id}")
def correct_claim(claim_id: uuid.UUID, body: ClaimCorrectionIn, db: DbSession, user: RequireOrganizerOnly) -> dict[str, Any]:
    """Fix an extraction mistake. The original quoted text is never altered; every change is audited."""
    claim = get_claim(db, claim_id)
    event = db.get(Event, claim.event_id)
    assert event is not None
    require_owner(db, user, event)
    before = {"normalized_text": claim.normalized_text, "category": claim.category, "claim_type": claim.claim_type, "is_active": claim.is_active}
    if body.normalized_text:
        claim.normalized_text = body.normalized_text
    if body.category:
        claim.category = body.category.value
    if body.claim_type:
        claim.claim_type = body.claim_type.value
    if body.responsible_party is not None:
        claim.responsible_party = body.responsible_party
    if body.conditions is not None:
        claim.conditions = body.conditions
    if body.withdraw is not None:
        claim.is_active = not body.withdraw
    if body.category and not body.claim_type:
        claim.claim_type = reclassify(claim.claim_type, claim.numeric_values or [], body.category).value
    audit(db, actor=user, action="claim.corrected", target_type="claim", target_id=claim.id,
          details={"event_id": str(event.id), "before": before, "reason": body.reason, "withdrawn": body.withdraw}, ip=None)
    return claim_full(db, claim, user)


@router.patch("/gaps/{gap_id}")
def resolve_gap(gap_id: uuid.UUID, body: GapResolveIn, db: DbSession, user: RequireOrganizerOnly) -> dict[str, Any]:
    gap = db.get(GapFinding, gap_id)
    if gap is None:
        raise NotFound("Issue not found.")
    event = db.get(Event, gap.event_id)
    assert event is not None
    require_owner(db, user, event)
    gap.status = body.status
    gap.resolution_note = body.note
    gap.resolved_at = utcnow() if body.status != "open" else None
    gap.resolved_by = user.id if body.status != "open" else None
    audit(db, actor=user, action=f"gap.{body.status}", target_type="gap", target_id=gap.id, details={"event_id": str(event.id), "rule": gap.rule_id, "note": body.note})
    return {"id": str(gap.id), "status": gap.status}


@router.put("/events/{event_id}/accessibility/{item_key}")
def set_accessibility(event_id: uuid.UUID, item_key: str, body: AccessibilityIn, db: DbSession, user: RequireOrganizerOnly) -> dict[str, Any]:
    if item_key not in BY_KEY:
        raise NotFound("Unknown accessibility item.", code="unknown_item")
    event = get_event(db, event_id, include_unpublished_for=user)
    require_owner(db, user, event)
    url = display_url(body.evidence_url) if body.evidence_url else None
    row = db.scalar(select(AccessibilityItem).where(AccessibilityItem.event_id == event.id, AccessibilityItem.item_key == item_key))
    if row is None:
        row = AccessibilityItem(event_id=event.id, item_key=item_key)
        db.add(row)
    # An organizer statement replaces a derived/source detection; the earlier excerpt is kept as evidence of what the page said.
    row.state, row.detail, row.evidence_url, row.origin, row.updated_by = body.state.value, body.detail, url or row.evidence_url, "organizer", user.id
    db.flush()
    audit(db, actor=user, action="accessibility.updated", target_type="event", target_id=event.id, details={"item": item_key, "state": body.state.value})
    return accessibility_panel(db, event)


# ------------------------------------------------------------------ feedback, responses, analytics, report


@router.get("/events/{event_id}/feedback")
def event_feedback(event_id: uuid.UUID, db: DbSession, user: RequireOrganizer, status: str | None = None) -> dict[str, Any]:
    event = get_event(db, event_id, include_unpublished_for=user)
    require_owner(db, user, event)
    q = select(FeedbackResponse, Claim.original_text).join(Claim, Claim.id == FeedbackResponse.claim_id).where(FeedbackResponse.event_id == event.id).order_by(FeedbackResponse.created_at.desc())
    if status:
        q = q.where(FeedbackResponse.status == status)
    else:
        q = q.where(FeedbackResponse.status.in_(["published", "pending"]))
    rows = list(db.execute(q.limit(200)))
    resp: dict[Any, list[dict[str, Any]]] = {}
    for r in db.scalars(select(OrganizerResponse).where(OrganizerResponse.event_id == event.id, OrganizerResponse.feedback_id.is_not(None))):
        resp.setdefault(r.feedback_id, []).append({"body": r.body, "created_at": r.created_at.isoformat()})
    # Reporter identity and moderator notes are never exposed to organizers.
    return {"items": [{"id": str(f.id), "claim_id": str(f.claim_id), "claim": text, "response": f.response, "comment": f.comment, "status": f.status,
                       "participation_level": f.participation_level, "created_at": f.created_at.isoformat(), "organizer_responses": resp.get(f.id, [])} for f, text in rows]}


@router.post("/responses", status_code=201)
def respond(body: OrganizerResponseIn, db: DbSession, user: RequireOrganizerOnly) -> dict[str, Any]:
    event = get_event(db, body.event_id, include_unpublished_for=user)
    require_owner(db, user, event)
    if not (body.claim_id or body.feedback_id):
        raise Unprocessable("Choose the promise or feedback you are responding to.", code="target_required")
    if body.claim_id:
        c = db.get(Claim, body.claim_id)
        if c is None or c.event_id != event.id:
            raise Unprocessable("That promise does not belong to this event.", code="claim_mismatch")
    if body.feedback_id:
        f = db.get(FeedbackResponse, body.feedback_id)
        if f is None or f.event_id != event.id:
            raise Unprocessable("That feedback does not belong to this event.", code="feedback_mismatch")
    r = OrganizerResponse(event_id=event.id, claim_id=body.claim_id, feedback_id=body.feedback_id, author_id=user.id, body=body.body)
    db.add(r)
    db.flush()
    audit(db, actor=user, action="organizer.responded", target_type="event", target_id=event.id, details={"claim_id": str(body.claim_id) if body.claim_id else None})
    return {"id": str(r.id), "created_at": r.created_at.isoformat()}


@router.get("/events/{event_id}/analytics")
def analytics(event_id: uuid.UUID, db: DbSession, user: RequireOrganizer) -> dict[str, Any]:
    event = get_event(db, event_id, include_unpublished_for=user)
    require_owner(db, user, event)
    return event_analytics(db, event)


@router.get("/events/{event_id}/report", response_model=None)
def report(event_id: uuid.UUID, db: DbSession, user: RequireOrganizer, request: Request, format: Literal["json", "md", "html"] = Query("json")):  # type: ignore[no-untyped-def]
    event = get_event(db, event_id, include_unpublished_for=user)
    require_owner(db, user, event)
    data = org_svc.build_report(db, event)
    audit(db, actor=user, action="report.exported", target_type="event", target_id=event.id, details={"format": format}, ip=client_ip(request))
    if format == "md":
        return PlainTextResponse(org_svc.report_markdown(data), media_type="text/markdown; charset=utf-8",
                                 headers={"Content-Disposition": f'attachment; filename="audit-{event.id}.md"'})
    if format == "html":
        return HTMLResponse(org_svc.report_html(data), headers={"Content-Disposition": f'attachment; filename="audit-{event.id}.html"', "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'"})
    return data


# ------------------------------------------------------------------ ownership of indexed events


@router.post("/ownership-requests", status_code=201)
def request_ownership(body: OwnershipRequestIn, event_id: uuid.UUID, db: DbSession, user: RequireOrganizerOnly) -> dict[str, Any]:
    event = get_event(db, event_id)
    org = db.get(Organization, body.organization_id)
    if org is None or org.id not in user_org_ids(db, user):
        raise Forbidden("You can only claim events on behalf of an organization you belong to.", code="not_org_member")
    if event.owner_org_id is not None:
        raise Conflict("This event already has an owner.", code="already_owned")
    proof = display_url(body.proof_url) if body.proof_url else None
    if body.proof_url and not proof:
        raise Unprocessable("The proof URL must be a valid http(s) URL.", code="invalid_url")
    if db.scalar(select(EventClaimRequest.id).where(EventClaimRequest.event_id == event.id, EventClaimRequest.organization_id == org.id, EventClaimRequest.status == "pending")):
        raise Conflict("A request for this event is already pending.", code="duplicate_request")
    r = EventClaimRequest(event_id=event.id, organization_id=org.id, requested_by=user.id, justification=body.justification, proof_url=proof)
    db.add(r)
    db.flush()
    audit(db, actor=user, action="ownership.requested", target_type="event", target_id=event.id, details={"org": str(org.id)})
    return {"id": str(r.id), "status": r.status}


@router.get("/ownership-requests")
def my_ownership_requests(db: DbSession, user: RequireOrganizer) -> dict[str, Any]:
    ids = user_org_ids(db, user)
    rows = list(db.execute(select(EventClaimRequest, Event.title).join(Event, Event.id == EventClaimRequest.event_id).where(EventClaimRequest.organization_id.in_(ids)).order_by(EventClaimRequest.created_at.desc()))) if ids else []
    return {"items": [{"id": str(r.id), "event_id": str(r.event_id), "event_title": t, "status": r.status, "created_at": r.created_at.isoformat(), "decision_note": r.decision_note} for r, t in rows]}



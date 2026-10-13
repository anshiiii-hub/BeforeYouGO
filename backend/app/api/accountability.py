from __future__ import annotations

import hashlib
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select

from app.api.common import client_ip, get_claim, get_event, require_owner
from app.core.config import get_settings
from app.core.deps import (
    CurrentUser,
    DbSession,
    OptionalUser,
    RequireReviewer,
    can_manage_event,
    has_conflict_of_interest,
    user_org_ids,
)
from app.core.errors import Conflict, Forbidden, NotFound, Unprocessable
from app.core.ratelimit import expensive_limit
from app.domain.enums import ClaimStatus, EvidenceKind, ModerationStatus, ReviewStatus, Role
from app.models import (
    Claim,
    ClaimStatusHistory,
    Dispute,
    Event,
    Evidence,
    FeedbackResponse,
    OrganizerResponse,
    Participation,
    Report,
)
from app.models.base import utcnow
from app.schemas.api import (
    DisputeIn,
    DisputeResolveIn,
    EvidenceIn,
    EvidenceReviewIn,
    FeedbackIn,
    ReportIn,
    TransitionIn,
)
from app.services import runtime_config
from app.services.analyzer.documents import sniff_mime
from app.services.audit import audit
from app.services.claims import allowed_transitions, event_has_ended, transition_claim
from app.services.urls import display_url, is_safe_link
from app.services.views import claim_dict

router = APIRouter(prefix="/api", tags=["accountability"])

_EXT = {"application/pdf": ".pdf", "image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "text/plain": ".txt"}
KIND_LABELS = {
    "organizer_provided": "Provided by the organizer",
    "public_source": "Public source",
    "participant_report": "Participant report",
    "independent_review": "Independently reviewed",
}


def evidence_dict(ev: Evidence, *, viewer: Any = None) -> dict[str, Any]:
    return {"id": str(ev.id), "claim_id": str(ev.claim_id) if ev.claim_id else None, "kind": ev.kind, "kind_label": KIND_LABELS.get(ev.kind, ev.kind),
            "url": ev.url, "excerpt": ev.excerpt, "file_name": ev.file_name, "mime_type": ev.mime_type, "file_size": ev.file_size,
            "has_file": bool(ev.file_path), "file_sha256": ev.file_sha256, "claim_specific": ev.claim_specific,
            "submitted_at": ev.submitted_at.isoformat(), "coi_declared": ev.coi_declared, "coi_statement": ev.coi_statement,
            "review_status": ev.review_status, "reviewed_at": ev.reviewed_at.isoformat() if ev.reviewed_at else None,
            "review_note": ev.review_note if viewer is not None else None}


def _policy(db) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    return runtime_config.effective(db)


def claim_full(db, claim: Claim, user: Any | None) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    event = db.get(Event, claim.event_id)
    evs = list(db.scalars(select(Evidence).where(Evidence.claim_id == claim.id).order_by(Evidence.submitted_at)))
    counts: dict[str, int] = defaultdict(int)
    for e in evs:
        counts[f"{e.kind}:{e.review_status}"] += 1
    history = list(db.scalars(select(ClaimStatusHistory).where(ClaimStatusHistory.claim_id == claim.id).order_by(ClaimStatusHistory.created_at)))
    responses = list(db.scalars(select(OrganizerResponse).where(OrganizerResponse.claim_id == claim.id).order_by(OrganizerResponse.created_at)))
    disputes = list(db.scalars(select(Dispute).where(Dispute.claim_id == claim.id).order_by(Dispute.created_at.desc())))
    role = user.role if user else None
    is_staff = role in ("reviewer", "admin")
    can_manage = bool(user and event and can_manage_event(db, user, event))
    trans = []
    for t in allowed_transitions(ClaimStatus(claim.status)):
        t["permitted_for_you"] = bool(user and role in t["roles"] and (role != "organizer" or can_manage))
        trans.append(t)
    d = claim_dict(claim, {claim.id: dict(counts)})
    d.update({
        "event_id": str(claim.event_id), "event_title": event.title if event else None, "is_active": claim.is_active,
        "history": [{"from_status": h.from_status, "to_status": h.to_status, "actor_role": h.actor_role, "reason": h.reason, "review_outcome": h.review_outcome,
                     "evidence_ids": h.evidence_ids, "at": h.created_at.isoformat()} for h in history],
        "evidence": [evidence_dict(e, viewer=user if (is_staff or can_manage) else None) for e in evs
                     if e.review_status != "rejected" or is_staff or can_manage or (user and e.submitted_by == user.id)],
        "organizer_responses": [{"id": str(r.id), "body": r.body, "created_at": r.created_at.isoformat()} for r in responses],
        "disputes": [{"id": str(x.id), "kind": x.kind, "status": x.status, "description": x.description, "created_at": x.created_at.isoformat(),
                      "resolution_note": x.resolution_note} for x in disputes],
        "transitions": trans, "status_note": "Status describes what has been established. 'Unverified' means no qualifying evidence was found; it is not a finding that the promise was broken.",
    })
    return d


@router.get("/claims/{claim_id}")
def get_claim_detail(claim_id: uuid.UUID, db: DbSession, user: OptionalUser) -> dict[str, Any]:
    claim = get_claim(db, claim_id)
    get_event(db, claim.event_id, include_unpublished_for=user)
    return claim_full(db, claim, user)


@router.post("/claims/{claim_id}/transition")
def claim_transition(claim_id: uuid.UUID, body: TransitionIn, db: DbSession, user: CurrentUser, request: Request) -> dict[str, Any]:
    claim = get_claim(db, claim_id)
    pol = _policy(db)
    transition_claim(db, claim, user, body.to_status, reason=body.reason, review_outcome=body.review_outcome, ip=client_ip(request),
                     participant_threshold=pol["participant_threshold"], grace_days=pol["unverified_grace_days"])
    return claim_full(db, claim, user)


# ------------------------------------------------------------------ evidence


def _store_file(event_id: uuid.UUID, data: bytes, filename: str) -> tuple[str, str, str, int]:
    settings = get_settings()
    limit = settings.max_upload_mb * 1024 * 1024
    if not data:
        raise Unprocessable("The uploaded file is empty.", code="empty_file")
    if len(data) > limit:
        raise Unprocessable(f"File is larger than the {settings.max_upload_mb} MB limit.", code="file_too_large")
    mime = sniff_mime(data, filename)
    sha = hashlib.sha256(data).hexdigest()
    folder = Path(settings.upload_dir) / str(event_id)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{sha}{_EXT[mime]}"
    if not path.exists():
        path.write_bytes(data)
    return str(path.relative_to(settings.upload_dir)), sha, mime, len(data)


def _resolve_kind(db, user, event: Event, requested: str | None) -> str:  # type: ignore[no-untyped-def]
    role = Role(user.role)
    if role in (Role.ORGANIZER,):
        require_owner(db, user, event)
        return EvidenceKind.ORGANIZER_PROVIDED.value
    if role in (Role.REVIEWER, Role.ADMIN):
        if role == Role.REVIEWER and has_conflict_of_interest(db, user, event):
            raise Forbidden("You belong to the organization that owns this event, so you cannot submit independent evidence for it.", code="conflict_of_interest")
        if requested in (EvidenceKind.PUBLIC_SOURCE.value, EvidenceKind.INDEPENDENT_REVIEW.value):
            return requested
        return EvidenceKind.INDEPENDENT_REVIEW.value
    # students: only participants can add a report
    part = db.scalar(select(Participation).where(Participation.user_id == user.id, Participation.event_id == event.id))
    if part is None:
        raise Forbidden("Only people who declared participation in this event can submit a participant report.", code="not_a_participant")
    return EvidenceKind.PARTICIPANT_REPORT.value


def _create_evidence(db, user, claim: Claim, *, url, excerpt, kind_req, claim_specific, coi_declared, coi_statement, file) -> Evidence:  # type: ignore[no-untyped-def]
    event = db.get(Event, claim.event_id)
    assert event is not None
    kind = _resolve_kind(db, user, event, kind_req)
    clean_url = None
    if url:
        clean_url = display_url(url)
        if not clean_url or not is_safe_link(clean_url):
            raise Unprocessable("The evidence URL must start with http:// or https://.", code="invalid_url")
    if not (clean_url or (excerpt and excerpt.strip()) or file):
        raise Unprocessable("Provide at least a URL, a quoted excerpt or a file.", code="evidence_empty")
    if kind == EvidenceKind.INDEPENDENT_REVIEW.value and not clean_url and not excerpt and not file:
        raise Unprocessable("Independent review evidence needs a reference.", code="evidence_empty")
    if coi_declared and not (coi_statement or "").strip():
        raise Unprocessable("Describe the conflict of interest you are declaring.", code="coi_statement_required")
    ev = Evidence(event_id=event.id, claim_id=claim.id, kind=kind, url=clean_url, excerpt=(excerpt or "").strip() or None,
                  claim_specific=claim_specific, submitted_by=user.id, coi_declared=coi_declared, coi_statement=coi_statement)
    if file:
        rel, sha, mime, size = file
        ev.file_path, ev.file_sha256, ev.mime_type, ev.file_size = rel, sha, mime, size
    db.add(ev)
    db.flush()
    return ev


@router.post("/claims/{claim_id}/evidence", status_code=201, dependencies=[Depends(expensive_limit)])
def add_evidence(claim_id: uuid.UUID, body: EvidenceIn, db: DbSession, user: CurrentUser, request: Request) -> dict[str, Any]:
    claim = get_claim(db, claim_id)
    get_event(db, claim.event_id, include_unpublished_for=user)
    ev = _create_evidence(db, user, claim, url=body.url, excerpt=body.excerpt, kind_req=body.kind, claim_specific=body.claim_specific,
                          coi_declared=body.coi_declared, coi_statement=body.coi_statement, file=None)
    audit(db, actor=user, action="evidence.submitted", target_type="evidence", target_id=ev.id, details={"claim_id": str(claim.id), "kind": ev.kind}, ip=client_ip(request))
    return evidence_dict(ev, viewer=user)


@router.post("/claims/{claim_id}/evidence/upload", status_code=201, dependencies=[Depends(expensive_limit)])
async def upload_evidence(claim_id: uuid.UUID, db: DbSession, user: CurrentUser, request: Request, file: UploadFile = File(...),
                          url: str | None = Form(None), excerpt: str | None = Form(None), kind: str | None = Form(None),
                          claim_specific: bool = Form(True), coi_declared: bool = Form(False), coi_statement: str | None = Form(None)) -> dict[str, Any]:
    claim = get_claim(db, claim_id)
    get_event(db, claim.event_id, include_unpublished_for=user)
    limit = get_settings().max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)
    stored = _store_file(claim.event_id, data, file.filename or "upload")
    ev = _create_evidence(db, user, claim, url=url, excerpt=excerpt, kind_req=kind, claim_specific=claim_specific, coi_declared=coi_declared,
                          coi_statement=coi_statement, file=stored)
    ev.file_name = (file.filename or "upload")[:300]
    audit(db, actor=user, action="evidence.uploaded", target_type="evidence", target_id=ev.id, details={"claim_id": str(claim.id), "sha256": ev.file_sha256}, ip=client_ip(request))
    return evidence_dict(ev, viewer=user)


@router.get("/evidence/{evidence_id}/file")
def download_evidence(evidence_id: uuid.UUID, db: DbSession, user: CurrentUser) -> FileResponse:
    ev = db.get(Evidence, evidence_id)
    if ev is None or not ev.file_path:
        raise NotFound("File not found.")
    event = db.get(Event, ev.event_id)
    allowed = user.role in ("reviewer", "admin") or ev.submitted_by == user.id or (event is not None and can_manage_event(db, user, event))
    if not allowed:
        raise Forbidden("You cannot open this file.", code="forbidden")
    root = Path(get_settings().upload_dir).resolve()
    path = (root / ev.file_path).resolve()
    if root not in path.parents or not path.exists():
        raise NotFound("File not found.")
    return FileResponse(path, media_type=ev.mime_type or "application/octet-stream", filename=ev.file_name or path.name,
                        headers={"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox"})


@router.post("/evidence/{evidence_id}/review")
def review_evidence(evidence_id: uuid.UUID, body: EvidenceReviewIn, db: DbSession, user: RequireReviewer, request: Request) -> dict[str, Any]:
    ev = db.get(Evidence, evidence_id)
    if ev is None:
        raise NotFound("Evidence not found.")
    event = db.get(Event, ev.event_id)
    assert event is not None
    if user.role == "reviewer" and has_conflict_of_interest(db, user, event):
        raise Forbidden("You belong to the organization that owns this event, so you cannot review its evidence.", code="conflict_of_interest")
    self_review = ev.submitted_by == user.id
    if self_review and user.role != "admin":
        raise Forbidden("You cannot review evidence you submitted yourself. Another reviewer must decide.", code="self_review")
    ev.review_status = ReviewStatus.ACCEPTED.value if body.decision == "accepted" else ReviewStatus.REJECTED.value
    ev.reviewed_by, ev.reviewed_at, ev.review_note = user.id, utcnow(), body.note
    audit(db, actor=user, action="evidence.reviewed", target_type="evidence", target_id=ev.id,
          details={"decision": body.decision, "claim_id": str(ev.claim_id) if ev.claim_id else None, "self_review": self_review, "kind": ev.kind}, ip=client_ip(request))
    return evidence_dict(ev, viewer=user)


# ------------------------------------------------------------------ disputes


def dispute_dict(d: Dispute) -> dict[str, Any]:
    return {"id": str(d.id), "event_id": str(d.event_id), "claim_id": str(d.claim_id) if d.claim_id else None, "kind": d.kind,
            "description": d.description, "status": d.status, "prior_claim_status": d.prior_claim_status, "created_at": d.created_at.isoformat(),
            "resolution_note": d.resolution_note, "resolved_at": d.resolved_at.isoformat() if d.resolved_at else None}


@router.post("/disputes", status_code=201)
def raise_dispute(body: DisputeIn, db: DbSession, user: CurrentUser, request: Request) -> dict[str, Any]:
    if user.role not in ("organizer", "admin"):
        raise Forbidden("Only the event's organizer can raise a dispute or correction request.", code="role_forbidden")
    event = get_event(db, body.event_id, include_unpublished_for=user)
    require_owner(db, user, event)
    claim = None
    if body.claim_id:
        claim = get_claim(db, body.claim_id)
        if claim.event_id != event.id:
            raise Unprocessable("That claim does not belong to this event.", code="claim_mismatch")
    if body.kind.value in ("claim_dispute", "appeal") and claim is None:
        raise Unprocessable("Choose the claim you are disputing.", code="claim_required")
    dup = db.scalar(select(Dispute.id).where(Dispute.event_id == event.id, Dispute.claim_id == body.claim_id, Dispute.kind == body.kind.value,
                                             Dispute.status.in_(["open", "under_review"]), Dispute.raised_by == user.id))
    if dup:
        raise Conflict("You already have an open dispute of this kind for this item.", code="duplicate_dispute")
    d = Dispute(event_id=event.id, claim_id=body.claim_id, kind=body.kind.value, description=body.description, raised_by=user.id)
    if claim is not None and body.kind.value == "claim_dispute":
        d.prior_claim_status = claim.status
        if claim.status != ClaimStatus.DISPUTED.value:
            pol = _policy(db)
            transition_claim(db, claim, user, ClaimStatus.DISPUTED, reason=body.description, ip=client_ip(request),
                             participant_threshold=pol["participant_threshold"], grace_days=pol["unverified_grace_days"])
    db.add(d)
    db.flush()
    audit(db, actor=user, action="dispute.raised", target_type="dispute", target_id=d.id, details={"kind": d.kind, "claim_id": str(body.claim_id) if body.claim_id else None}, ip=client_ip(request))
    return dispute_dict(d)


@router.get("/disputes")
def list_disputes(db: DbSession, user: CurrentUser, event_id: uuid.UUID | None = None, status: str | None = None) -> dict[str, Any]:
    q = select(Dispute).order_by(Dispute.created_at.desc()).limit(200)
    if event_id:
        q = q.where(Dispute.event_id == event_id)
    if status:
        q = q.where(Dispute.status == status)
    rows = list(db.scalars(q))
    if user.role not in ("reviewer", "admin"):
        orgs = user_org_ids(db, user)
        owned = {e for e in db.scalars(select(Event.id).where(Event.owner_org_id.in_(orgs)))} if orgs else set()
        rows = [d for d in rows if d.event_id in owned]
    titles = {e.id: e.title for e in db.scalars(select(Event).where(Event.id.in_({d.event_id for d in rows})))} if rows else {}
    return {"items": [{**dispute_dict(d), "event_title": titles.get(d.event_id)} for d in rows]}


@router.post("/disputes/{dispute_id}/resolve")
def resolve_dispute(dispute_id: uuid.UUID, body: DisputeResolveIn, db: DbSession, user: RequireReviewer, request: Request) -> dict[str, Any]:
    d = db.get(Dispute, dispute_id)
    if d is None:
        raise NotFound("Dispute not found.")
    event = db.get(Event, d.event_id)
    assert event is not None
    if user.role == "reviewer" and has_conflict_of_interest(db, user, event):
        raise Forbidden("You belong to the organization that owns this event, so you cannot resolve its disputes.", code="conflict_of_interest")
    if d.status in ("upheld", "rejected", "withdrawn") and body.outcome != "under_review":
        raise Conflict("This dispute is already closed.", code="dispute_closed")
    claim = db.get(Claim, d.claim_id) if d.claim_id else None
    pol = _policy(db)
    if body.outcome != "under_review" and claim is not None and claim.status == ClaimStatus.DISPUTED.value:
        target = body.restore_status or (ClaimStatus(d.prior_claim_status) if d.prior_claim_status and ClaimStatus(d.prior_claim_status) in (
            ClaimStatus.ADVERTISED, ClaimStatus.EVIDENCE_SUBMITTED, ClaimStatus.CORROBORATED, ClaimStatus.NEEDS_CLARIFICATION) else ClaimStatus.UNABLE_TO_DETERMINE)
        if body.withdraw_claim:
            target = ClaimStatus.UNABLE_TO_DETERMINE
        transition_claim(db, claim, user, target, reason=body.note, review_outcome=f"dispute_{body.outcome}", ip=client_ip(request),
                         participant_threshold=pol["participant_threshold"], grace_days=pol["unverified_grace_days"])
        if body.withdraw_claim:
            claim.is_active = False
            audit(db, actor=user, action="claim.withdrawn", target_type="claim", target_id=claim.id, details={"dispute_id": str(d.id), "reason": body.note}, ip=client_ip(request))
    d.status = body.outcome
    d.resolution_note = body.note
    if body.outcome != "under_review":
        d.resolved_by, d.resolved_at = user.id, utcnow()
    audit(db, actor=user, action="dispute.resolved", target_type="dispute", target_id=d.id, details={"outcome": body.outcome, "note": body.note}, ip=client_ip(request))
    return dispute_dict(d)


# ------------------------------------------------------------------ participant feedback


@router.post("/events/{event_id}/feedback", status_code=201, dependencies=[Depends(expensive_limit)])
def submit_feedback(event_id: uuid.UUID, body: FeedbackIn, db: DbSession, user: CurrentUser, request: Request) -> dict[str, Any]:
    event = get_event(db, event_id)
    part = db.scalar(select(Participation).where(Participation.user_id == user.id, Participation.event_id == event.id))
    if part is None:
        raise Forbidden("Declare that you took part in this event before giving feedback.", code="not_a_participant")
    if not event_has_ended(event):
        raise Unprocessable("Feedback opens once the event has ended.", code="event_not_ended")
    saved, skipped = [], []
    seen: set[uuid.UUID] = set()
    for item in body.items:
        if item.claim_id in seen:
            skipped.append({"claim_id": str(item.claim_id), "reason": "listed twice in this submission"})
            continue
        seen.add(item.claim_id)
        claim = db.get(Claim, item.claim_id)
        if claim is None or claim.event_id != event.id or not claim.is_active:
            skipped.append({"claim_id": str(item.claim_id), "reason": "not an active promise of this event"})
            continue
        if db.scalar(select(FeedbackResponse.id).where(FeedbackResponse.user_id == user.id, FeedbackResponse.claim_id == claim.id)):
            skipped.append({"claim_id": str(item.claim_id), "reason": "you already answered this question"})
            continue
        evidence_id = None
        if item.evidence_url:
            url = display_url(item.evidence_url)
            if not url:
                skipped.append({"claim_id": str(item.claim_id), "reason": "evidence URL must start with http(s)://"})
                continue
            ev = Evidence(event_id=event.id, claim_id=claim.id, kind=EvidenceKind.PARTICIPANT_REPORT.value, url=url, excerpt=item.comment,
                          submitted_by=user.id, claim_specific=True)
            db.add(ev)
            db.flush()
            evidence_id = ev.id
        fb = FeedbackResponse(event_id=event.id, claim_id=claim.id, user_id=user.id, participation_level=part.level, response=item.response.value,
                              comment=item.comment, evidence_id=evidence_id, status=ModerationStatus.PENDING.value)
        db.add(fb)
        db.flush()
        saved.append(str(fb.id))
    if not saved and skipped:
        raise Conflict("Nothing was saved.", details=[f"{s['claim_id']}: {s['reason']}" for s in skipped], code="nothing_saved")
    audit(db, actor=user, action="feedback.submitted", target_type="event", target_id=event.id, details={"count": len(saved)}, ip=client_ip(request))
    return {"saved": len(saved), "skipped": skipped,
            "note": "Your answers are checked by a moderator before they count towards the public outcome summary. Your name is never shown."}


@router.get("/events/{event_id}/feedback-form")
def feedback_form(event_id: uuid.UUID, db: DbSession, user: CurrentUser) -> dict[str, Any]:
    event = get_event(db, event_id)
    part = db.scalar(select(Participation).where(Participation.user_id == user.id, Participation.event_id == event.id))
    claims = list(db.scalars(select(Claim).where(Claim.event_id == event.id, Claim.is_active.is_(True), Claim.claim_type != "informational").order_by(Claim.created_at)))
    answered = {c for c in db.scalars(select(FeedbackResponse.claim_id).where(FeedbackResponse.user_id == user.id, FeedbackResponse.event_id == event.id))}
    return {"event": {"id": str(event.id), "title": event.title, "ended": event_has_ended(event)}, "participation": bool(part),
            "can_submit": bool(part) and event_has_ended(event),
            "claims": [{"id": str(c.id), "text": c.original_text, "category": c.category, "answered": c.id in answered} for c in claims]}


def outcome_summary(db, event: Event) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    pol = _policy(db)
    min_n = pol["min_outcome_responses"]
    claims = list(db.scalars(select(Claim).where(Claim.event_id == event.id, Claim.is_active.is_(True)).order_by(Claim.created_at)))
    rows = list(db.execute(select(FeedbackResponse.claim_id, FeedbackResponse.response, func.count(func.distinct(FeedbackResponse.user_id)))
                           .where(FeedbackResponse.event_id == event.id, FeedbackResponse.status == "published").group_by(FeedbackResponse.claim_id, FeedbackResponse.response)))
    by_claim: dict[Any, dict[str, int]] = defaultdict(dict)
    for cid, resp, n in rows:
        by_claim[cid][resp] = n
    ev_rows = list(db.execute(select(Evidence.claim_id, Evidence.kind, Evidence.review_status, func.count()).where(Evidence.event_id == event.id).group_by(Evidence.claim_id, Evidence.kind, Evidence.review_status)))
    ev_by_claim: dict[Any, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for cid, kind, rs, n in ev_rows:
        ev_by_claim[cid][f"{kind}:{rs}"] += n
    out = []
    for c in claims:
        resp = by_claim.get(c.id, {})
        n = sum(resp.values())
        ev = dict(ev_by_claim.get(c.id, {}))
        independent_accepted = sum(v for k, v in ev.items() if k.split(":")[0] in ("public_source", "independent_review") and k.endswith(":accepted"))
        sufficient = n >= min_n or independent_accepted > 0 or c.status in ("fulfilled", "partially_fulfilled", "corroborated")
        if not sufficient:
            verdict, why = "insufficient_evidence", f"Insufficient evidence: {n} published participant response(s) (at least {min_n} needed) and no accepted independent evidence."
        else:
            top = max(resp.items(), key=lambda kv: kv[1])[0] if resp else None
            verdict = {"delivered": "participants_report_delivered", "partially_delivered": "participants_report_partial", "not_delivered": "participants_report_not_delivered"}.get(top or "", "mixed_or_unclear")
            why = f"{n} participant response(s)" + (f"; most common answer: {top.replace('_', ' ')}" if top else "") + ". Participant reports are not independently verified."
        out.append({"claim_id": str(c.id), "text": c.original_text, "category": c.category, "status": c.status, "responses": resp, "responses_total": n,
                    "evidence": ev, "independent_evidence_accepted": independent_accepted, "verdict": verdict, "summary": why})
    counts = defaultdict(int)
    for c in claims:
        counts[c.status] += 1
    declared = db.scalar(select(func.count()).select_from(Participation).where(Participation.event_id == event.id)) or 0
    responded = db.scalar(select(func.count(func.distinct(FeedbackResponse.user_id))).where(FeedbackResponse.event_id == event.id)) or 0
    return {"claims": out, "status_counts": dict(counts), "participants_declared": declared, "participants_responded": responded,
            "response_rate": {"numerator": responded, "denominator": declared, "pct": round(100 * responded / declared) if declared else None},
            "min_responses_required": min_n,
            "caveat": "Participant reports and independently reviewed evidence are shown separately. A lack of evidence is not evidence of broken promises."}


@router.get("/events/{event_id}/outcomes")
def event_outcomes(event_id: uuid.UUID, db: DbSession, user: OptionalUser) -> dict[str, Any]:
    event = get_event(db, event_id, include_unpublished_for=user)
    summary = outcome_summary(db, event)
    comments = list(db.execute(select(FeedbackResponse, Claim.original_text).join(Claim, Claim.id == FeedbackResponse.claim_id)
                               .where(FeedbackResponse.event_id == event.id, FeedbackResponse.status == "published", FeedbackResponse.comment.is_not(None))
                               .order_by(FeedbackResponse.created_at.desc()).limit(50)))
    resp = defaultdict(list)
    for r in db.scalars(select(OrganizerResponse).where(OrganizerResponse.event_id == event.id, OrganizerResponse.feedback_id.is_not(None))):
        resp[r.feedback_id].append({"body": r.body, "created_at": r.created_at.isoformat()})
    summary["comments"] = [{"id": str(f.id), "claim": text, "response": f.response, "comment": f.comment, "participation_level": f.participation_level,
                            "created_at": f.created_at.isoformat(), "organizer_responses": resp.get(f.id, [])} for f, text in comments]
    return summary


# ------------------------------------------------------------------ reports (moderation flags)


@router.post("/reports", status_code=201)
def report_content(body: ReportIn, db: DbSession, user: CurrentUser) -> dict[str, Any]:
    existing = db.scalar(select(Report.id).where(Report.reporter_id == user.id, Report.target_type == body.target_type, Report.target_id == body.target_id))
    if existing:
        raise Conflict("You have already reported this item.", code="duplicate_report")
    r = Report(target_type=body.target_type, target_id=body.target_id, reporter_id=user.id, reason=body.reason)
    db.add(r)
    db.flush()
    return {"id": str(r.id), "status": r.status}



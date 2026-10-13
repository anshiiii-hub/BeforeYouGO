from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Query, Request
from sqlalchemy import delete, func, or_, select

from app.api.common import client_ip, get_event, page
from app.core.config import get_settings
from app.core.deps import DbSession, RequireAdmin, RequireReviewer
from app.core.errors import Conflict, NotFound, Unprocessable
from app.domain.enums import FieldOrigin, SourceStatus
from app.models import (
    AuditLog,
    Claim,
    DuplicateCandidate,
    Event,
    EventClaimRequest,
    EventFieldAssertion,
    Evidence,
    FeedbackResponse,
    Organization,
    OrganizationMember,
    Participation,
    Report,
    SavedEvent,
    Source,
    SourceRecord,
    SyncRun,
    SystemSetting,
    User,
)
from app.models.base import utcnow
from app.schemas.api import (
    ConfigIn,
    DuplicateResolveIn,
    ModerateIn,
    OwnershipDecisionIn,
    ReportHandleIn,
    SourceAdminIn,
    UserAdminIn,
)
from app.services import runtime_config
from app.services.audit import audit
from app.services.ingest import assert_fields, recompute_event
from app.services.outcomes import platform_analytics
from app.services.scoring import DEFAULT_WEIGHTS
from app.services.sources.registry import build_adapters, seed_sources
from app.services.sync import run_source_sync

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ------------------------------------------------------------------ sources


def source_dict(s: Source, *, events: int = 0, has_adapter: bool = False, last_run: SyncRun | None = None, admin: bool = False) -> dict[str, Any]:
    d = {
        "key": s.key, "name": s.name, "kind": s.kind, "homepage": s.homepage, "status": s.status, "status_detail": s.status_detail, "enabled": s.enabled,
        "access_method": s.access_method, "limitations": s.limitations, "rate_limit_note": s.rate_limit_note, "auth_requirement": s.auth_requirement,
        "attribution": s.attribution, "terms_url": s.terms_url, "license_note": s.license_note, "priority": s.priority,
        "connector_implemented": has_adapter, "events_linked": events,
        "last_attempt_at": s.last_attempt_at.isoformat() if s.last_attempt_at else None,
        "last_success_at": s.last_success_at.isoformat() if s.last_success_at else None,
        "last_error": s.last_error, "consecutive_failures": s.consecutive_failures,
        "last_run": ({"status": last_run.status, "fetched": last_run.records_fetched, "created": last_run.created_count, "updated": last_run.updated_count,
                      "unchanged": last_run.unchanged_count, "started_at": last_run.started_at.isoformat(), "errors": last_run.errors[:3]} if last_run else None),
    }
    if admin:
        d["config"] = {"ics_feed_urls": (s.config or {}).get("urls", []) if s.key == "ics_feeds" else None}
    return d


def list_sources(db, *, admin: bool) -> list[dict[str, Any]]:  # type: ignore[no-untyped-def]
    adapters = build_adapters()
    counts = dict(db.execute(select(SourceRecord.source_id, func.count(func.distinct(SourceRecord.event_id))).group_by(SourceRecord.source_id)).all())
    last: dict[Any, SyncRun] = {}
    for r in db.scalars(select(SyncRun).order_by(SyncRun.started_at.asc())):
        last[r.source_id] = r
    rows = list(db.scalars(select(Source).order_by(Source.kind == "platform", Source.name)))
    return [source_dict(s, events=counts.get(s.id, 0), has_adapter=s.key in adapters, last_run=last.get(s.id), admin=admin) for s in rows]


@router.get("/sources")
def sources(db: DbSession, user: RequireReviewer) -> dict[str, Any]:
    return {"items": list_sources(db, admin=user.role == "admin")}


@router.patch("/sources/{key}")
def update_source(key: str, body: SourceAdminIn, db: DbSession, user: RequireAdmin, request: Request) -> dict[str, Any]:
    s = db.scalar(select(Source).where(Source.key == key))
    if s is None:
        raise NotFound("Unknown source.")
    changes: dict[str, Any] = {}
    adapters = build_adapters()
    if body.enabled is not None:
        if body.enabled and key not in adapters:
            raise Unprocessable("This source has no connector, so it cannot be enabled.", code="no_connector")
        s.enabled = body.enabled
        changes["enabled"] = body.enabled
    if body.priority is not None:
        s.priority = body.priority
        changes["priority"] = body.priority
    if body.ics_feed_urls is not None:
        if key != "ics_feeds":
            raise Unprocessable("Feed URLs apply only to the ICS feeds connector.", code="not_ics")
        from app.services.safe_fetch import validate_url

        urls = []
        for u in body.ics_feed_urls:
            try:
                urls.append(validate_url(u))
            except Exception as exc:
                raise Unprocessable(f"{u}: {getattr(exc, 'message', str(exc))}", code="invalid_feed_url") from exc
        s.config = {**(s.config or {}), "urls": urls}
        if urls and s.status == SourceStatus.NOT_CONFIGURED.value:
            s.status, s.status_detail = SourceStatus.PENDING.value, None
        changes["ics_feed_urls"] = urls
    audit(db, actor=user, action="source.updated", target_type="source", target_id=s.id, details={"key": key, **changes}, ip=client_ip(request))
    return source_dict(s, has_adapter=key in adapters, admin=True)


def _sync_job(key: str, user_id: uuid.UUID) -> None:
    try:
        run_source_sync(key, trigger="manual", user_id=user_id)
    except Exception:  # surfaced through sync history; never crash the worker
        import logging

        logging.getLogger("byg.sync").exception("manual sync failed for %s", key)


@router.post("/sources/{key}/sync", status_code=202)
def trigger_sync(key: str, background: BackgroundTasks, db: DbSession, user: RequireAdmin) -> dict[str, Any]:
    if key not in build_adapters():
        raise Unprocessable("This source has no connector in this deployment.", code="no_connector")
    seed_sources(db)
    db.commit()  # the background job opens its own session and must see the catalogue row
    running = db.scalar(select(SyncRun.id).join(Source, Source.id == SyncRun.source_id).where(Source.key == key, SyncRun.status == "running",
                                                                                           SyncRun.started_at > utcnow() - __import__("datetime").timedelta(minutes=30)))
    if running:
        raise Conflict("A synchronisation for this source is already running.", code="sync_running")
    background.add_task(_sync_job, key, user.id)
    return {"status": "started", "source": key, "note": "Poll /api/admin/sync-runs for progress."}


@router.get("/sync-runs")
def sync_runs(db: DbSession, user: RequireReviewer, source: str | None = None, limit: int = Query(30, ge=1, le=200)) -> dict[str, Any]:
    q = select(SyncRun, Source.key, Source.name).join(Source, Source.id == SyncRun.source_id).order_by(SyncRun.started_at.desc()).limit(limit)
    if source:
        q = q.where(Source.key == source)
    return {"items": [{"id": str(r.id), "source": k, "source_name": n, "trigger": r.trigger, "status": r.status, "started_at": r.started_at.isoformat(),
                       "finished_at": r.finished_at.isoformat() if r.finished_at else None, "fetched": r.records_fetched, "created": r.created_count,
                       "updated": r.updated_count, "unchanged": r.unchanged_count, "skipped": r.skipped_count, "missing": r.missing_count, "errors": r.errors[:10]}
                      for r, k, n in db.execute(q)]}


# ------------------------------------------------------------------ users and organizations


@router.get("/users")
def users(db: DbSession, user: RequireAdmin, q: str | None = None, role: str | None = None, page_no: int = Query(1, alias="page", ge=1), page_size: int = Query(25, le=100)) -> dict[str, Any]:
    stmt = select(User).where(User.deleted_at.is_(None))
    if q:
        stmt = stmt.where(or_(User.email.ilike(f"%{q}%"), User.display_name.ilike(f"%{q}%")))
    if role:
        stmt = stmt.where(User.role == role)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(db.scalars(stmt.order_by(User.created_at.desc()).limit(page_size).offset((page_no - 1) * page_size)))
    return page(total, page_no, page_size, [{"id": str(u.id), "email": u.email, "display_name": u.display_name, "role": u.role, "is_active": u.is_active,
                                              "created_at": u.created_at.isoformat(), "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None} for u in rows])


@router.patch("/users/{user_id}")
def update_user(user_id: uuid.UUID, body: UserAdminIn, db: DbSession, admin: RequireAdmin, request: Request) -> dict[str, Any]:
    u = db.get(User, user_id)
    if u is None or u.deleted_at is not None:
        raise NotFound("User not found.")
    if u.id == admin.id and ((body.role and body.role.value != "admin") or body.is_active is False):
        raise Unprocessable("You cannot remove your own administrator access.", code="self_demotion")
    before = {"role": u.role, "is_active": u.is_active}
    if body.role:
        u.role = body.role.value
    if body.is_active is not None:
        u.is_active = body.is_active
    u.token_version += 1  # force re-authentication with the new permissions
    audit(db, actor=admin, action="user.updated", target_type="user", target_id=u.id, details={"before": before, "after": {"role": u.role, "is_active": u.is_active}}, ip=client_ip(request))
    return {"id": str(u.id), "role": u.role, "is_active": u.is_active}


@router.get("/orgs")
def orgs(db: DbSession, user: RequireAdmin) -> dict[str, Any]:
    rows = list(db.scalars(select(Organization).order_by(Organization.name)))
    members: dict[Any, list[str]] = {}
    for m, u in db.execute(select(OrganizationMember, User).join(User, User.id == OrganizationMember.user_id)):
        members.setdefault(m.organization_id, []).append(u.email)
    return {"items": [{"id": str(o.id), "name": o.name, "website": o.website, "members": members.get(o.id, [])} for o in rows]}


@router.post("/orgs/{org_id}/members", status_code=201)
def add_member(org_id: uuid.UUID, body: dict[str, str], db: DbSession, admin: RequireAdmin) -> dict[str, Any]:
    email = (body.get("email") or "").lower().strip()
    u = db.scalar(select(User).where(User.email == email, User.deleted_at.is_(None)))
    org = db.get(Organization, org_id)
    if u is None or org is None:
        raise NotFound("User or organization not found.")
    if db.scalar(select(OrganizationMember.id).where(OrganizationMember.organization_id == org.id, OrganizationMember.user_id == u.id)):
        raise Conflict("Already a member.", code="already_member")
    db.add(OrganizationMember(organization_id=org.id, user_id=u.id))
    audit(db, actor=admin, action="org.member_added", target_type="organization", target_id=org.id, details={"user_id": str(u.id)})
    return {"ok": True}


# ------------------------------------------------------------------ moderation queue


@router.get("/moderation")
def moderation(db: DbSession, user: RequireReviewer) -> dict[str, Any]:
    fb = list(db.execute(select(FeedbackResponse, Claim.original_text, Event.title).join(Claim, Claim.id == FeedbackResponse.claim_id)
                         .join(Event, Event.id == FeedbackResponse.event_id).where(FeedbackResponse.status == "pending").order_by(FeedbackResponse.created_at).limit(100)))
    ev = list(db.execute(select(Evidence, Event.title).join(Event, Event.id == Evidence.event_id).where(Evidence.review_status == "pending").order_by(Evidence.submitted_at).limit(100)))
    reports = list(db.scalars(select(Report).where(Report.status == "open").order_by(Report.created_at).limit(100)))
    own = list(db.execute(select(EventClaimRequest, Event.title, Organization.name).join(Event, Event.id == EventClaimRequest.event_id)
                          .join(Organization, Organization.id == EventClaimRequest.organization_id).where(EventClaimRequest.status == "pending").order_by(EventClaimRequest.created_at)))
    dups = list(db.execute(select(DuplicateCandidate).where(DuplicateCandidate.status == "open").order_by(DuplicateCandidate.similarity.desc()).limit(50)))
    titles = {e.id: e.title for e in db.scalars(select(Event).where(Event.id.in_({d[0].event_a_id for d in dups} | {d[0].event_b_id for d in dups})))} if dups else {}
    from app.models import Dispute

    disputes = db.scalar(select(func.count()).select_from(Dispute).where(Dispute.status.in_(["open", "under_review"]))) or 0
    return {
        "counts": {"feedback": len(fb), "evidence": len(ev), "reports": len(reports), "ownership_requests": len(own), "duplicates": len(dups), "disputes": disputes},
        "feedback": [{"id": str(f.id), "event_id": str(f.event_id), "event_title": t, "claim": c, "response": f.response, "comment": f.comment, "participation_level": f.participation_level,
                      "created_at": f.created_at.isoformat(), "has_evidence": f.evidence_id is not None} for f, c, t in fb],
        "evidence": [{"id": str(e.id), "event_id": str(e.event_id), "event_title": t, "claim_id": str(e.claim_id) if e.claim_id else None, "kind": e.kind, "url": e.url, "excerpt": e.excerpt,
                      "has_file": bool(e.file_path), "file_name": e.file_name, "submitted_at": e.submitted_at.isoformat(), "coi_declared": e.coi_declared} for e, t in ev],
        "reports": [{"id": str(r.id), "target_type": r.target_type, "target_id": str(r.target_id), "reason": r.reason, "created_at": r.created_at.isoformat()} for r in reports],
        "ownership_requests": [{"id": str(r.id), "event_id": str(r.event_id), "event_title": t, "organization": o, "justification": r.justification, "proof_url": r.proof_url,
                                "created_at": r.created_at.isoformat()} for r, t, o in own],
        "duplicates": [{"id": str(d[0].id), "a": {"id": str(d[0].event_a_id), "title": titles.get(d[0].event_a_id)}, "b": {"id": str(d[0].event_b_id), "title": titles.get(d[0].event_b_id)},
                        "similarity": d[0].similarity, "reasons": d[0].reasons} for d in dups],
    }


@router.post("/feedback/{feedback_id}/moderate")
def moderate_feedback(feedback_id: uuid.UUID, body: ModerateIn, db: DbSession, user: RequireReviewer, request: Request) -> dict[str, Any]:
    f = db.get(FeedbackResponse, feedback_id)
    if f is None:
        raise NotFound("Feedback not found.")
    event = db.get(Event, f.event_id)
    from app.core.deps import has_conflict_of_interest
    from app.core.errors import Forbidden

    if event is not None and user.role == "reviewer" and has_conflict_of_interest(db, user, event):
        raise Forbidden("You belong to the organization that owns this event, so you cannot moderate its feedback.", code="conflict_of_interest")
    f.status, f.moderated_by, f.moderated_at, f.moderation_note = body.status.value, user.id, utcnow(), body.note
    audit(db, actor=user, action="feedback.moderated", target_type="feedback", target_id=f.id, details={"status": body.status.value, "event_id": str(f.event_id)}, ip=client_ip(request))
    return {"id": str(f.id), "status": f.status}


@router.post("/reports/{report_id}/handle")
def handle_report(report_id: uuid.UUID, body: ReportHandleIn, db: DbSession, user: RequireReviewer, request: Request) -> dict[str, Any]:
    r = db.get(Report, report_id)
    if r is None:
        raise NotFound("Report not found.")
    effect = None
    if body.action == "upheld_hide":
        if r.target_type == "feedback":
            f = db.get(FeedbackResponse, r.target_id)
            if f:
                f.status, f.moderated_by, f.moderated_at, f.moderation_note = "hidden", user.id, utcnow(), body.note
                effect = "feedback hidden"
        elif r.target_type == "evidence":
            e = db.get(Evidence, r.target_id)
            if e:
                e.review_status, e.reviewed_by, e.reviewed_at, e.review_note = "rejected", user.id, utcnow(), body.note
                effect = "evidence rejected"
    r.status = "dismissed" if body.action == "dismiss" else "actioned"
    r.handled_by, r.handled_at = user.id, utcnow()
    audit(db, actor=user, action="report.handled", target_type="report", target_id=r.id, details={"action": body.action, "effect": effect, "note": body.note}, ip=client_ip(request))
    return {"id": str(r.id), "status": r.status, "effect": effect}


@router.post("/ownership-requests/{request_id}/decision")
def decide_ownership(request_id: uuid.UUID, body: OwnershipDecisionIn, db: DbSession, user: RequireReviewer, request: Request) -> dict[str, Any]:
    r = db.get(EventClaimRequest, request_id)
    if r is None:
        raise NotFound("Request not found.")
    if r.status != "pending":
        raise Conflict("This request has already been decided.", code="already_decided")
    event = db.get(Event, r.event_id)
    assert event is not None
    if body.approve:
        if event.owner_org_id is not None:
            raise Conflict("The event already has an owner.", code="already_owned")
        event.owner_org_id = r.organization_id
    r.status = "approved" if body.approve else "rejected"
    r.decided_by, r.decided_at, r.decision_note = user.id, utcnow(), body.note
    audit(db, actor=user, action="ownership.decided", target_type="event", target_id=event.id, details={"approved": body.approve, "org": str(r.organization_id), "note": body.note}, ip=client_ip(request))
    return {"id": str(r.id), "status": r.status}


def _can_merge(db, drop: Event) -> list[str]:  # type: ignore[no-untyped-def]
    problems = []
    if drop.owner_org_id is not None:
        problems.append("The event being merged away is owned by an organizer.")
    if db.scalar(select(func.count()).select_from(Claim).where(Claim.event_id == drop.id, Claim.status != "advertised")):
        problems.append("It has claims whose status has been changed.")
    for model, label in ((FeedbackResponse, "participant feedback"), (Participation, "participation declarations"), (SavedEvent, "saved-by-user entries"), (Evidence, "evidence")):
        if db.scalar(select(func.count()).select_from(model).where(model.event_id == drop.id)):
            problems.append(f"It has {label}.")
    return problems


@router.post("/duplicates/{dup_id}/resolve")
def resolve_duplicate(dup_id: uuid.UUID, body: DuplicateResolveIn, db: DbSession, user: RequireReviewer, request: Request) -> dict[str, Any]:
    d = db.get(DuplicateCandidate, dup_id)
    if d is None:
        raise NotFound("Candidate not found.")
    if d.status != "open":
        raise Conflict("Already resolved.", code="already_resolved")
    if body.action == "distinct":
        d.status = "distinct"
    else:
        if body.keep_event_id not in (d.event_a_id, d.event_b_id):
            raise Unprocessable("Choose which of the two events to keep.", code="keep_required")
        keep = db.get(Event, body.keep_event_id)
        drop = db.get(Event, d.event_b_id if body.keep_event_id == d.event_a_id else d.event_a_id)
        assert keep is not None and drop is not None
        problems = _can_merge(db, drop)
        if problems:
            raise Unprocessable("These events cannot be merged automatically.", details=problems, code="merge_blocked")
        moved = db.execute(select(func.count()).select_from(SourceRecord).where(SourceRecord.event_id == drop.id)).scalar() or 0
        for rec in db.scalars(select(SourceRecord).where(SourceRecord.event_id == drop.id)):
            rec.event_id = keep.id
        for a in db.scalars(select(EventFieldAssertion).where(EventFieldAssertion.event_id == drop.id)):
            a.event_id = keep.id
        drop_id = drop.id
        db.flush()
        db.expire_all()
        recompute_event(db, db.get(Event, keep.id), change_source="merge", actor_id=user.id, force_version=True)  # type: ignore[arg-type]
        db.execute(delete(Event).where(Event.id == drop_id))
        d.status = "merged"
        audit(db, actor=user, action="duplicate.merged", target_type="event", target_id=keep.id, details={"merged_away": str(drop_id), "source_records_moved": moved}, ip=client_ip(request))
        return {"status": "merged", "kept": str(keep.id)}
    d.resolved_by, d.resolved_at = user.id, utcnow()
    audit(db, actor=user, action="duplicate.resolved", target_type="duplicate", target_id=d.id, details={"action": body.action}, ip=client_ip(request))
    return {"status": d.status}


@router.post("/events/{event_id}/lifecycle")
def set_lifecycle(event_id: uuid.UUID, body: dict[str, str], db: DbSession, user: RequireReviewer, request: Request) -> dict[str, Any]:
    event = get_event(db, event_id, include_unpublished_for=user)
    status, reason = body.get("status"), (body.get("reason") or "").strip()
    if status not in ("scheduled", "cancelled", "postponed") or len(reason) < 5:
        raise Unprocessable("Provide a status (scheduled, cancelled, postponed) and a reason of at least 5 characters.", code="invalid_lifecycle")
    assert_fields(db, event, {"lifecycle_status": status}, {}, source=None, record=None, source_url=None, actor_id=user.id, default_origin=FieldOrigin.MANUAL.value)
    version = recompute_event(db, event, change_source="reviewer", actor_id=user.id)
    if version:
        version.summary = f"{version.summary} Reason: {reason}"
    audit(db, actor=user, action="event.lifecycle_set", target_type="event", target_id=event.id, details={"status": status, "reason": reason}, ip=client_ip(request))
    return {"lifecycle_status": event.lifecycle_status}


@router.post("/participations/{participation_id}/confirm")
def confirm_participation(participation_id: uuid.UUID, db: DbSession, user: RequireReviewer) -> dict[str, Any]:
    p = db.get(Participation, participation_id)
    if p is None:
        raise NotFound("Participation not found.")
    p.level, p.confirmed_by, p.confirmed_at = "reviewer_confirmed", user.id, utcnow()
    audit(db, actor=user, action="participation.confirmed", target_type="participation", target_id=p.id)
    return {"level": p.level}


# ------------------------------------------------------------------ audit log, config, analytics


@router.get("/audit-logs")
def audit_logs(db: DbSession, user: RequireAdmin, action: str | None = None, actor_role: str | None = None, target_type: str | None = None,
               page_no: int = Query(1, alias="page", ge=1), page_size: int = Query(50, le=200)) -> dict[str, Any]:
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action.ilike(f"{action}%"))
    if actor_role:
        stmt = stmt.where(AuditLog.actor_role == actor_role)
    if target_type:
        stmt = stmt.where(AuditLog.target_type == target_type)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(db.scalars(stmt.order_by(AuditLog.created_at.desc()).limit(page_size).offset((page_no - 1) * page_size)))
    return page(total, page_no, page_size, [{"id": str(a.id), "at": a.created_at.isoformat(), "actor_id": str(a.actor_id) if a.actor_id else None, "actor_role": a.actor_role,
                                              "action": a.action, "target_type": a.target_type, "target_id": a.target_id, "details": a.details} for a in rows])


@router.get("/config")
def get_config(db: DbSession, user: RequireAdmin) -> dict[str, Any]:
    s = get_settings()
    return {"effective": runtime_config.effective(db), "defaults": runtime_config.defaults(),
            "environment": {"env": s.env, "scheduler_enabled": s.enable_scheduler, "sync_interval_hours": s.sync_interval_hours, "max_upload_mb": s.max_upload_mb,
                            "llm_provider_configured": __import__("app.services.analyzer.llm", fromlist=["resolve_llm"]).resolve_llm(s) is not None},
            "weight_labels": {k: k.replace("_", " ") for k in DEFAULT_WEIGHTS}}


@router.put("/config")
def put_config(body: ConfigIn, db: DbSession, user: RequireAdmin, request: Request) -> dict[str, Any]:
    data = body.model_dump(exclude_none=True)
    if "scoring_weights" in data:
        w = data["scoring_weights"]
        bad = [k for k in w if k not in DEFAULT_WEIGHTS]
        if bad or any(v < 0 for v in w.values()) or sum(w.values()) <= 0:
            raise Unprocessable("Weights must use the known factor names, be non-negative and not all zero.", details=[f"unknown factor: {k}" for k in bad], code="invalid_weights")
        data["scoring_weights"] = runtime_config.normalised_weights({**DEFAULT_WEIGHTS, **w})
    row = db.get(SystemSetting, runtime_config.KEY)
    before = dict(row.value) if row else {}
    if row is None:
        row = SystemSetting(key=runtime_config.KEY, value={})
        db.add(row)
    row.value = {**(row.value or {}), **data}
    row.updated_by = user.id
    audit(db, actor=user, action="config.updated", target_type="config", target_id=runtime_config.KEY, details={"before": before, "after": row.value}, ip=client_ip(request))
    return {"effective": runtime_config.effective(db)}


@router.delete("/config")
def reset_config(db: DbSession, user: RequireAdmin) -> dict[str, Any]:
    row = db.get(SystemSetting, runtime_config.KEY)
    if row:
        db.delete(row)
    audit(db, actor=user, action="config.reset", target_type="config", target_id=runtime_config.KEY)
    return {"effective": runtime_config.defaults()}


@router.get("/analytics")
def analytics(db: DbSession, user: RequireReviewer) -> dict[str, Any]:
    return platform_analytics(db)



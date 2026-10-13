"""Claim creation and the claim lifecycle state machine.

Design rules (see docs/ARCHITECTURE.md, "Accountability"):

* Only reviewers/admins can establish verification outcomes. Organizers can supply
  evidence and respond; they cannot corroborate or fulfil their own claims.
* Organizer-provided evidence alone never satisfies corroboration or fulfilment.
* Missing evidence never makes a claim "broken". The strongest negative state is
  UNVERIFIED ("no evidence was established"), which says nothing about honesty.
* Every transition is appended to claim_status_history (immutable, DB trigger) and
  to the audit log.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import has_conflict_of_interest, user_org_ids
from app.core.errors import Forbidden, Unprocessable
from app.domain.enums import (
    ClaimStatus,
    EvidenceKind,
    ExtractionMethod,
    ModerationStatus,
    ReviewStatus,
    Role,
)
from app.domain.enums import (
    FeedbackResponse as FeedbackAnswer,
)
from app.models import Claim, ClaimStatusHistory, Event, Evidence, FeedbackResponse, Participation, User
from app.models.base import utcnow
from app.services.audit import audit

S = ClaimStatus
NON_TERMINAL = {S.ADVERTISED, S.NEEDS_CLARIFICATION, S.EVIDENCE_SUBMITTED, S.CORROBORATED, S.DISPUTED}
ANY_STATUS = set(ClaimStatus)

DEFAULT_PARTICIPANT_THRESHOLD = 3  # distinct published participant confirmations
DEFAULT_UNVERIFIED_GRACE_DAYS = 14


@dataclass(frozen=True)
class Rule:
    roles: frozenset[Role]
    evidence: str  # human-readable evidence requirement (shown in the UI and docs)
    needs_event_ended: bool = False
    owner_only_organizer: bool = True  # organizers may act only on events their organisation owns


R = Role
REVIEWERS = frozenset({R.REVIEWER, R.ADMIN})
ORGANIZER_OR_REVIEWER = frozenset({R.ORGANIZER, R.REVIEWER, R.ADMIN})

TRANSITIONS: dict[tuple[ClaimStatus, ClaimStatus], Rule] = {
    (S.ADVERTISED, S.NEEDS_CLARIFICATION): Rule(REVIEWERS, "A written reason describing what is unclear."),
    (S.NEEDS_CLARIFICATION, S.ADVERTISED): Rule(ORGANIZER_OR_REVIEWER, "A written organizer response or reviewer note resolving the question."),
    (S.ADVERTISED, S.EVIDENCE_SUBMITTED): Rule(ORGANIZER_OR_REVIEWER, "At least one evidence record attached to this claim."),
    (S.NEEDS_CLARIFICATION, S.EVIDENCE_SUBMITTED): Rule(ORGANIZER_OR_REVIEWER, "At least one evidence record attached to this claim."),
    (S.EVIDENCE_SUBMITTED, S.CORROBORATED): Rule(
        REVIEWERS,
        "At least one ACCEPTED, claim-specific evidence record from a public source or an independent review. "
        "Organizer-provided evidence alone is not enough.",
    ),
    (S.EVIDENCE_SUBMITTED, S.FULFILLED): Rule(
        REVIEWERS,
        "Event must have ended, plus accepted independent/public claim-specific evidence OR enough distinct published "
        "participant confirmations. Organizer-provided evidence alone is not enough.",
        needs_event_ended=True,
    ),
    (S.CORROBORATED, S.FULFILLED): Rule(
        REVIEWERS,
        "Event must have ended, plus accepted independent/public claim-specific evidence OR enough distinct published "
        "participant confirmations.",
        needs_event_ended=True,
    ),
    (S.EVIDENCE_SUBMITTED, S.PARTIALLY_FULFILLED): Rule(
        REVIEWERS,
        "Event must have ended, plus accepted claim-specific evidence or enough distinct published participant reports of partial delivery.",
        needs_event_ended=True,
    ),
    (S.CORROBORATED, S.PARTIALLY_FULFILLED): Rule(
        REVIEWERS,
        "Event must have ended, plus accepted claim-specific evidence or enough distinct published participant reports of partial delivery.",
        needs_event_ended=True,
    ),
    (S.DISPUTED, S.UNABLE_TO_DETERMINE): Rule(REVIEWERS, "A reviewer's written resolution note."),
    (S.DISPUTED, S.NEEDS_CLARIFICATION): Rule(REVIEWERS, "A reviewer's written resolution note."),
    # Terminal states may be reopened so appeals and new evidence are possible.
    (S.FULFILLED, S.DISPUTED): Rule(ORGANIZER_OR_REVIEWER, "A written dispute reason."),
    (S.PARTIALLY_FULFILLED, S.DISPUTED): Rule(ORGANIZER_OR_REVIEWER, "A written dispute reason."),
    (S.UNVERIFIED, S.DISPUTED): Rule(ORGANIZER_OR_REVIEWER, "A written dispute reason."),
    (S.UNABLE_TO_DETERMINE, S.NEEDS_CLARIFICATION): Rule(REVIEWERS, "A reviewer note on what new information is needed."),
    (S.UNVERIFIED, S.EVIDENCE_SUBMITTED): Rule(ORGANIZER_OR_REVIEWER, "At least one evidence record attached to this claim."),
    (S.UNVERIFIED, S.NEEDS_CLARIFICATION): Rule(REVIEWERS, "A reviewer note on what new information is needed."),
}
# Any non-terminal status may be disputed or marked unable_to_determine / unverified by the right actor.
for _src in NON_TERMINAL - {S.DISPUTED}:
    TRANSITIONS[(_src, S.DISPUTED)] = Rule(ORGANIZER_OR_REVIEWER, "A written dispute reason.")
    TRANSITIONS[(_src, S.UNABLE_TO_DETERMINE)] = Rule(REVIEWERS, "A reviewer's written reason.")
    TRANSITIONS[(_src, S.UNVERIFIED)] = Rule(
        REVIEWERS,
        "Event ended at least the configured grace period ago and no qualifying evidence has been established. "
        "This status does NOT mean the promise was broken.",
        needs_event_ended=True,
    )
TRANSITIONS[(S.DISPUTED, S.ADVERTISED)] = Rule(REVIEWERS, "A reviewer's written resolution note.")
TRANSITIONS[(S.DISPUTED, S.EVIDENCE_SUBMITTED)] = Rule(REVIEWERS, "A reviewer's written resolution note and attached evidence.")
TRANSITIONS[(S.DISPUTED, S.CORROBORATED)] = Rule(REVIEWERS, "Accepted public/independent claim-specific evidence.")


def allowed_transitions(status: ClaimStatus) -> list[dict[str, Any]]:
    return [
        {
            "to": to.value,
            "roles": sorted(r.value for r in rule.roles),
            "evidence_requirement": rule.evidence,
            "requires_event_ended": rule.needs_event_ended,
        }
        for (frm, to), rule in TRANSITIONS.items()
        if frm == status
    ]


def claim_text_hash(original_text: str, category: str) -> str:
    norm = re.sub(r"\s+", " ", original_text.strip().lower())
    return hashlib.sha256(f"{category}|{norm}".encode()).hexdigest()


def create_claim(
    db: Session,
    event: Event,
    *,
    original_text: str,
    normalized_text: str,
    category: str,
    claim_type: str,
    method: ExtractionMethod,
    confidence: float | None = None,
    responsible_party: str | None = None,
    conditions: list[Any] | None = None,
    numeric_values: list[Any] | None = None,
    missing_details: list[Any] | None = None,
    verification_questions: list[Any] | None = None,
    evidence_url: str | None = None,
    evidence_excerpt: str | None = None,
    analysis_run_id: uuid.UUID | None = None,
    actor: User | None = None,
) -> tuple[Claim, bool]:
    """Create a claim in the ADVERTISED state, or return the existing identical claim."""
    text_hash = claim_text_hash(original_text, category)
    existing = db.scalar(select(Claim).where(Claim.event_id == event.id, Claim.text_hash == text_hash))
    if existing:
        existing.last_checked_at = utcnow()
        if not existing.is_active and method != ExtractionMethod.MANUAL:
            return existing, False
        return existing, False
    claim = Claim(
        event_id=event.id,
        analysis_run_id=analysis_run_id,
        text_hash=text_hash,
        original_text=original_text,
        normalized_text=normalized_text,
        category=category,
        claim_type=claim_type,
        responsible_party=responsible_party,
        conditions=conditions or [],
        numeric_values=numeric_values or [],
        missing_details=missing_details or [],
        verification_questions=verification_questions or [],
        evidence_url=evidence_url,
        evidence_excerpt=evidence_excerpt,
        extraction_method=method.value,
        extraction_confidence=confidence,
        status=S.ADVERTISED.value,
        last_checked_at=utcnow(),
        created_by=actor.id if actor else None,
    )
    db.add(claim)
    db.flush()
    db.add(
        ClaimStatusHistory(
            claim_id=claim.id,
            actor_id=actor.id if actor else None,
            actor_role=actor.role if actor else "system",
            from_status=None,
            to_status=S.ADVERTISED.value,
            evidence_ids=[],
            reason=f"Extracted by {method.value} analysis. Advertised only; fulfilment is not established.",
        )
    )
    return claim, True


# --------------------------------------------------------------------- helpers


def event_has_ended(event: Event, today: date | None = None) -> bool:
    today = today or datetime.now(UTC).date()
    end = event.end_date or event.start_date
    return end is not None and end < today


def _claim_evidence(db: Session, claim: Claim) -> list[Evidence]:
    return list(db.scalars(select(Evidence).where(Evidence.claim_id == claim.id)))


def participant_confirmations(db: Session, claim: Claim, answer: FeedbackAnswer) -> int:
    """Distinct published participant responses for a claim with the given answer."""
    # Participants who declared a conflict of interest (e.g. volunteers or organisers) are shown but never counted.
    return int(
        db.scalar(
            select(func.count(func.distinct(FeedbackResponse.user_id)))
            .select_from(FeedbackResponse)
            .outerjoin(
                Participation,
                (Participation.user_id == FeedbackResponse.user_id) & (Participation.event_id == FeedbackResponse.event_id),
            )
            .where(
                FeedbackResponse.claim_id == claim.id,
                FeedbackResponse.status == ModerationStatus.PUBLISHED.value,
                FeedbackResponse.response == answer.value,
                FeedbackResponse.user_id.is_not(None),
                func.coalesce(Participation.conflict_of_interest, False).is_(False),
            )
        )
        or 0
    )


def _independent_accepted(evs: list[Evidence]) -> list[Evidence]:
    return [
        e
        for e in evs
        if e.review_status == ReviewStatus.ACCEPTED.value
        and e.claim_specific
        and e.kind in (EvidenceKind.PUBLIC_SOURCE.value, EvidenceKind.INDEPENDENT_REVIEW.value)
    ]


def evaluate_requirements(
    db: Session,
    claim: Claim,
    event: Event,
    to_status: ClaimStatus,
    *,
    today: date | None = None,
    participant_threshold: int = DEFAULT_PARTICIPANT_THRESHOLD,
    grace_days: int = DEFAULT_UNVERIFIED_GRACE_DAYS,
) -> list[str]:
    """Return a list of unmet requirements (empty means the transition's evidence rules are satisfied)."""
    today = today or datetime.now(UTC).date()
    unmet: list[str] = []
    evs = _claim_evidence(db, claim)
    rule = TRANSITIONS[(ClaimStatus(claim.status), to_status)]

    if rule.needs_event_ended and not event_has_ended(event, today):
        unmet.append("The event has not ended yet, so delivery cannot be assessed.")

    if to_status == S.EVIDENCE_SUBMITTED:
        usable = [e for e in evs if e.review_status != ReviewStatus.REJECTED.value]
        if not usable:
            unmet.append("Attach at least one evidence record (URL, excerpt or file) to this claim first.")
    elif to_status == S.CORROBORATED:
        if not _independent_accepted(evs):
            unmet.append(
                "Needs at least one accepted, claim-specific evidence record from a public source or independent review. "
                "Organizer-provided evidence cannot corroborate a claim on its own."
            )
    elif to_status in (S.FULFILLED, S.PARTIALLY_FULFILLED):
        answer = FeedbackAnswer.DELIVERED if to_status == S.FULFILLED else FeedbackAnswer.PARTIALLY_DELIVERED
        have_evidence = bool(_independent_accepted(evs))
        have_participants = participant_confirmations(db, claim, answer) >= participant_threshold
        if not (have_evidence or have_participants):
            unmet.append(
                "Needs accepted public/independent claim-specific evidence, or at least "
                f"{participant_threshold} distinct published participant reports of '{answer.value}'. "
                "A poster, announcement or organizer upload cannot establish delivery."
            )
    elif to_status == S.UNVERIFIED:
        end = event.end_date or event.start_date
        if end is not None and (today - end).days < grace_days:
            unmet.append(f"Wait at least {grace_days} days after the event before marking a claim unverified.")
        if _independent_accepted(evs):
            unmet.append("Qualifying evidence exists, so this claim cannot be marked unverified.")
    return unmet


def transition_claim(
    db: Session,
    claim: Claim,
    actor: User,
    to_status: ClaimStatus,
    *,
    reason: str,
    review_outcome: str | None = None,
    today: date | None = None,
    ip: str | None = None,
    participant_threshold: int = DEFAULT_PARTICIPANT_THRESHOLD,
    grace_days: int = DEFAULT_UNVERIFIED_GRACE_DAYS,
) -> Claim:
    event = db.get(Event, claim.event_id)
    assert event is not None
    from_status = ClaimStatus(claim.status)
    rule = TRANSITIONS.get((from_status, to_status))
    if rule is None:
        raise Unprocessable(
            f"A claim cannot move from '{from_status.value}' to '{to_status.value}'.", code="invalid_transition"
        )
    role = Role(actor.role)
    if role not in rule.roles:
        raise Forbidden(
            f"Your role ({role.value}) cannot move a claim from '{from_status.value}' to '{to_status.value}'.",
            code="transition_forbidden",
        )
    if role == Role.ORGANIZER:
        if event.owner_org_id is None or event.owner_org_id not in user_org_ids(db, actor):
            raise Forbidden("You can only act on claims for events your organization owns.", code="not_event_owner")
    if role in (Role.REVIEWER,) and has_conflict_of_interest(db, actor, event):
        raise Forbidden(
            "You belong to the organization that owns this event, so you cannot review its claims (conflict of interest).",
            code="conflict_of_interest",
        )
    reason = (reason or "").strip()
    if len(reason) < 5:
        raise Unprocessable("A reason of at least 5 characters is required for every status change.", code="reason_required")

    unmet = evaluate_requirements(
        db, claim, event, to_status, today=today, participant_threshold=participant_threshold, grace_days=grace_days
    )
    if unmet:
        raise Unprocessable("The evidence requirements for this change are not met.", details=unmet, code="evidence_requirements_not_met")

    evs = _claim_evidence(db, claim)
    claim.status = to_status.value
    claim.status_updated_at = utcnow()
    claim.last_checked_at = utcnow()
    history = ClaimStatusHistory(
        claim_id=claim.id,
        actor_id=actor.id,
        actor_role=actor.role,
        from_status=from_status.value,
        to_status=to_status.value,
        evidence_ids=[str(e.id) for e in evs if e.review_status != ReviewStatus.REJECTED.value],
        reason=reason,
        review_outcome=review_outcome,
    )
    db.add(history)
    audit(
        db,
        actor=actor,
        action="claim.status_changed",
        target_type="claim",
        target_id=claim.id,
        details={"from": from_status.value, "to": to_status.value, "reason": reason, "event_id": str(event.id)},
        ip=ip,
    )
    db.flush()
    return claim

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAt, UUIDPk, utcnow
from app.models.event import Event


class AnalysisRun(Base):
    """One execution of the promise-analysis pipeline over a piece of input."""

    __tablename__ = "analysis_runs"

    id: Mapped[UUIDPk]
    event_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    input_type: Mapped[str] = mapped_column(String(10))
    input_hash: Mapped[str] = mapped_column(String(64))
    source_url: Mapped[str | None] = mapped_column(String(1000))
    canonical_url: Mapped[str | None] = mapped_column(String(1000))
    source_text: Mapped[str | None] = mapped_column(Text)  # untrusted content, stored as data only
    file_name: Mapped[str | None] = mapped_column(String(300))
    provider: Mapped[str] = mapped_column(String(40), default="deterministic")
    model: Mapped[str | None] = mapped_column(String(80))
    used_fallback: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="completed")
    error: Mapped[str | None] = mapped_column(Text)
    injection_flags: Mapped[list[Any]] = mapped_column(default=list)
    result: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[CreatedAt]


class Claim(Base):
    __tablename__ = "claims"
    __table_args__ = (UniqueConstraint("event_id", "text_hash"),)

    id: Mapped[UUIDPk]
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    analysis_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="SET NULL")
    )
    text_hash: Mapped[str] = mapped_column(String(64))
    original_text: Mapped[str] = mapped_column(Text)
    normalized_text: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(30), index=True)
    claim_type: Mapped[str] = mapped_column(String(20))
    responsible_party: Mapped[str | None] = mapped_column(String(300))
    conditions: Mapped[list[Any]] = mapped_column(default=list)
    numeric_values: Mapped[list[Any]] = mapped_column(default=list)
    missing_details: Mapped[list[Any]] = mapped_column(default=list)
    verification_questions: Mapped[list[Any]] = mapped_column(default=list)
    evidence_url: Mapped[str | None] = mapped_column(String(1000))
    evidence_excerpt: Mapped[str | None] = mapped_column(Text)
    extraction_method: Mapped[str] = mapped_column(String(20))
    extraction_confidence: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(30), default="advertised", index=True)
    status_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)  # organizer may withdraw a wrongly extracted claim
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[CreatedAt]

    event: Mapped[Event] = relationship(back_populates="claims")
    history: Mapped[list[ClaimStatusHistory]] = relationship(
        back_populates="claim", order_by="ClaimStatusHistory.created_at"
    )


class ClaimStatusHistory(Base):
    """Append-only (enforced by a database trigger)."""

    __tablename__ = "claim_status_history"

    id: Mapped[UUIDPk]
    claim_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"), index=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    actor_role: Mapped[str | None] = mapped_column(String(20))
    from_status: Mapped[str | None] = mapped_column(String(30))
    to_status: Mapped[str] = mapped_column(String(30))
    evidence_ids: Mapped[list[Any]] = mapped_column(default=list)
    reason: Mapped[str] = mapped_column(Text)
    review_outcome: Mapped[str | None] = mapped_column(String(60))
    created_at: Mapped[CreatedAt]

    claim: Mapped[Claim] = relationship(back_populates="history")


class Evidence(Base):
    __tablename__ = "evidence"

    id: Mapped[UUIDPk]
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    claim_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    url: Mapped[str | None] = mapped_column(String(1000))
    excerpt: Mapped[str | None] = mapped_column(Text)
    file_path: Mapped[str | None] = mapped_column(String(500))
    file_name: Mapped[str | None] = mapped_column(String(300))
    file_sha256: Mapped[str | None] = mapped_column(String(64))
    mime_type: Mapped[str | None] = mapped_column(String(80))
    file_size: Mapped[int | None] = mapped_column(Integer)
    claim_specific: Mapped[bool] = mapped_column(Boolean, default=True)
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    coi_declared: Mapped[bool] = mapped_column(Boolean, default=False)
    coi_statement: Mapped[str | None] = mapped_column(Text)
    review_status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_note: Mapped[str | None] = mapped_column(Text)


class GapFinding(Base):
    __tablename__ = "gap_findings"
    __table_args__ = (Index("ix_gap_event_rule", "event_id", "rule_id"),)

    id: Mapped[UUIDPk]
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    analysis_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="SET NULL")
    )
    rule_id: Mapped[str] = mapped_column(String(10))
    gap: Mapped[str] = mapped_column(String(300))
    source_text: Mapped[str | None] = mapped_column(Text)
    why_it_matters: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(10))
    severity_rule: Mapped[str] = mapped_column(Text)
    student_question: Mapped[str] = mapped_column(Text)
    organizer_fix: Mapped[str] = mapped_column(Text)
    scope_note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(15), default="open", index=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    resolution_note: Mapped[str | None] = mapped_column(Text)


class AccessibilityItem(Base):
    __tablename__ = "accessibility_items"
    __table_args__ = (UniqueConstraint("event_id", "item_key"),)

    id: Mapped[UUIDPk]
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    item_key: Mapped[str] = mapped_column(String(40))
    state: Mapped[str] = mapped_column(String(30), default="not_documented")
    detail: Mapped[str | None] = mapped_column(Text)
    evidence_excerpt: Mapped[str | None] = mapped_column(Text)
    evidence_url: Mapped[str | None] = mapped_column(String(1000))
    origin: Mapped[str] = mapped_column(String(20), default="source")
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class SavedEvent(Base):
    __tablename__ = "saved_events"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), primary_key=True)
    note: Mapped[str | None] = mapped_column(Text)
    saved_at: Mapped[CreatedAt]
    last_seen_version: Mapped[int | None] = mapped_column(Integer)  # for "what changed since you saved"


class ComparisonHistory(Base):
    __tablename__ = "comparison_history"

    id: Mapped[UUIDPk]
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    event_ids: Mapped[list[Any]] = mapped_column(default=list)
    created_at: Mapped[CreatedAt]


class RecommendationFeedback(Base):
    __tablename__ = "recommendation_feedback"
    __table_args__ = (UniqueConstraint("user_id", "event_id"),)

    id: Mapped[UUIDPk]
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"))
    vote: Mapped[str] = mapped_column(String(10))  # helpful / not_relevant / hide
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[CreatedAt]


class Participation(Base):
    """A person's declaration (and optional confirmation) that they took part in an event."""

    __tablename__ = "participations"
    __table_args__ = (UniqueConstraint("user_id", "event_id"),)

    id: Mapped[UUIDPk]
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    level: Mapped[str] = mapped_column(String(25), default="self_declared")
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    conflict_of_interest: Mapped[bool] = mapped_column(Boolean, default=False)  # e.g. volunteer/organiser
    created_at: Mapped[CreatedAt]


class FeedbackResponse(Base):
    __tablename__ = "feedback_responses"
    __table_args__ = (
        UniqueConstraint("user_id", "claim_id", name="uq_feedback_user_claim"),
        Index("ix_feedback_event_status", "event_id", "status"),
    )

    id: Mapped[UUIDPk]
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"))
    claim_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    participation_level: Mapped[str] = mapped_column(String(25))
    response: Mapped[str] = mapped_column(String(25))
    comment: Mapped[str | None] = mapped_column(Text)
    evidence_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("evidence.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(15), default="pending")  # moderation status
    moderated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    moderated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    moderation_note: Mapped[str | None] = mapped_column(Text)  # internal; never exposed publicly
    created_at: Mapped[CreatedAt]


class OrganizerResponse(Base):
    __tablename__ = "organizer_responses"

    id: Mapped[UUIDPk]
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    claim_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"))
    feedback_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("feedback_responses.id", ondelete="CASCADE"))
    author_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[CreatedAt]


class Dispute(Base):
    __tablename__ = "disputes"

    id: Mapped[UUIDPk]
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    claim_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("claims.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(25))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(15), default="open", index=True)
    raised_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    prior_claim_status: Mapped[str | None] = mapped_column(String(30))  # preserved for restoration
    resolution_note: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[CreatedAt]


class Report(Base):
    """User-raised flag on content (feedback, evidence, listing) for the moderation queue."""

    __tablename__ = "reports"
    __table_args__ = (UniqueConstraint("reporter_id", "target_type", "target_id"),)

    id: Mapped[UUIDPk]
    target_type: Mapped[str] = mapped_column(String(30))
    target_id: Mapped[uuid.UUID] = mapped_column(index=True)
    reporter_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(15), default="open")
    handled_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    handled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[CreatedAt]


class AuditLog(Base):
    """Append-only (enforced by a database trigger)."""

    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_target", "target_type", "target_id"),)

    id: Mapped[UUIDPk]
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    actor_role: Mapped[str | None] = mapped_column(String(20))
    action: Mapped[str] = mapped_column(String(80), index=True)
    target_type: Mapped[str | None] = mapped_column(String(40))
    target_id: Mapped[str | None] = mapped_column(String(60))
    details: Mapped[dict[str, Any]] = mapped_column(default=dict)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[CreatedAt]

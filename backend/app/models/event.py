from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAt, UUIDPk, utcnow


class Source(Base):
    """A connector/source catalogue entry. Status is honest about what is actually reachable."""

    __tablename__ = "sources"

    id: Mapped[UUIDPk]
    key: Mapped[str] = mapped_column(String(60), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(30))  # github_json / ics / jsonld / platform
    homepage: Mapped[str | None] = mapped_column(String(500))
    access_method: Mapped[str] = mapped_column(Text)
    limitations: Mapped[str | None] = mapped_column(Text)
    rate_limit_note: Mapped[str | None] = mapped_column(Text)
    auth_requirement: Mapped[str | None] = mapped_column(Text)
    attribution: Mapped[str | None] = mapped_column(Text)
    terms_url: Mapped[str | None] = mapped_column(String(500))
    license_note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="not_configured")
    status_detail: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[int] = mapped_column(Integer, default=50)  # higher wins field conflicts
    config: Mapped[dict[str, Any]] = mapped_column(default=dict)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[CreatedAt]


class SyncRun(Base):
    __tablename__ = "sync_runs"

    id: Mapped[UUIDPk]
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), index=True)
    trigger: Mapped[str] = mapped_column(String(20), default="scheduled")  # scheduled/manual/startup
    triggered_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(20), default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    records_fetched: Mapped[int] = mapped_column(Integer, default=0)
    created_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, default=0)
    unchanged_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    missing_count: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[list[Any]] = mapped_column(default=list)


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_start_date", "start_date"),
        Index("ix_events_city", "city"),
        Index("ix_events_country", "country"),
        Index("ix_events_canonical_url_norm", "canonical_url_norm"),
    )

    id: Mapped[UUIDPk]
    title: Mapped[str] = mapped_column(String(400))
    description: Mapped[str | None] = mapped_column(Text)
    canonical_url: Mapped[str | None] = mapped_column(String(1000))
    canonical_url_norm: Mapped[str | None] = mapped_column(String(1000))
    organizer_name: Mapped[str | None] = mapped_column(String(300))
    organizer_url: Mapped[str | None] = mapped_column(String(1000))
    category: Mapped[str] = mapped_column(String(30), default="other", index=True)
    topics: Mapped[list[Any]] = mapped_column(default=list)  # normalised topic keys (ai, data, security...)
    tags: Mapped[list[Any]] = mapped_column(default=list)  # raw source tags [{key,value}]
    tags_text: Mapped[str | None] = mapped_column(Text)  # flattened for full-text search

    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    registration_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    registration_deadline_date_only: Mapped[bool] = mapped_column(Boolean, default=False)
    registration_url: Mapped[str | None] = mapped_column(String(1000))

    format: Mapped[str] = mapped_column(String(20), default="unknown", index=True)
    venue: Mapped[str | None] = mapped_column(String(400))
    city: Mapped[str | None] = mapped_column(String(160))
    state: Mapped[str | None] = mapped_column(String(160))
    country: Mapped[str | None] = mapped_column(String(160))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)

    eligibility: Mapped[str | None] = mapped_column(Text)
    eligibility_structured: Mapped[dict[str, Any]] = mapped_column(default=dict)
    prerequisites: Mapped[str | None] = mapped_column(Text)
    team_size_min: Mapped[int | None] = mapped_column(Integer)
    team_size_max: Mapped[int | None] = mapped_column(Integer)
    allows_cross_college_teams: Mapped[bool | None] = mapped_column(Boolean)

    fee_status: Mapped[str] = mapped_column(String(10), default="unknown", index=True)
    fee_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    fee_currency: Mapped[str | None] = mapped_column(String(3))
    other_costs: Mapped[str | None] = mapped_column(Text)
    prize_details: Mapped[str | None] = mapped_column(Text)
    time_commitment: Mapped[str | None] = mapped_column(Text)
    schedule_text: Mapped[str | None] = mapped_column(Text)
    judging_criteria: Mapped[str | None] = mapped_column(Text)
    refund_policy: Mapped[str | None] = mapped_column(Text)
    contact_info: Mapped[str | None] = mapped_column(String(500))
    accommodation_info: Mapped[str | None] = mapped_column(Text)
    offers_certificate: Mapped[bool | None] = mapped_column(Boolean)
    offers_mentorship: Mapped[bool | None] = mapped_column(Boolean)
    extras: Mapped[dict[str, Any]] = mapped_column(default=dict)  # source-specific facts (e.g. cfp deadline)

    origin_type: Mapped[str] = mapped_column(String(30), default="indexed", index=True)
    lifecycle_status: Mapped[str] = mapped_column(String(30), default="scheduled")
    verification_state: Mapped[str] = mapped_column(String(30), default="unverified")
    extraction_confidence: Mapped[float | None] = mapped_column(Float)
    owner_org_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"), index=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    is_published: Mapped[bool] = mapped_column(Boolean, default=True)

    first_discovered_at: Mapped[CreatedAt]
    last_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    last_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    source_records: Mapped[list[SourceRecord]] = relationship(back_populates="event")
    claims: Mapped[list[Claim]] = relationship(back_populates="event")  # noqa: F821


class SourceRecord(Base):
    """Verbatim record as retrieved from a source. Never rewritten, only appended/refreshed."""

    __tablename__ = "source_records"
    __table_args__ = (UniqueConstraint("source_id", "source_event_id"),)

    id: Mapped[UUIDPk]
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), index=True)
    source_event_id: Mapped[str] = mapped_column(String(300))
    source_url: Mapped[str | None] = mapped_column(String(1000))  # where this record was retrieved from
    event_url: Mapped[str | None] = mapped_column(String(1000))
    event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("events.id", ondelete="SET NULL"), index=True
    )
    raw: Mapped[dict[str, Any]] = mapped_column(default=dict)
    normalized: Mapped[dict[str, Any]] = mapped_column(default=dict)
    content_hash: Mapped[str] = mapped_column(String(64))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    first_seen_at: Mapped[CreatedAt]
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    missing_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    extraction_confidence: Mapped[float | None] = mapped_column(Float)

    event: Mapped[Event | None] = relationship(back_populates="source_records")


class EventFieldAssertion(Base):
    """Field-level provenance: who asserted what value for which field, and when."""

    __tablename__ = "event_field_assertions"
    __table_args__ = (Index("ix_efa_event_field", "event_id", "field_name"),)

    id: Mapped[UUIDPk]
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"))
    field_name: Mapped[str] = mapped_column(String(60))
    value: Mapped[Any] = mapped_column(Text)  # JSON-encoded scalar for uniform comparison
    origin: Mapped[str] = mapped_column(String(20))  # FieldOrigin
    source_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sources.id", ondelete="SET NULL"))
    source_record_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("source_records.id", ondelete="SET NULL")
    )
    source_url: Mapped[str | None] = mapped_column(String(1000))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EventVersion(Base):
    __tablename__ = "event_versions"
    __table_args__ = (UniqueConstraint("event_id", "version_no"),)

    id: Mapped[UUIDPk]
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    changed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    change_source: Mapped[str] = mapped_column(String(60))  # source key or "organizer"/"reviewer"
    snapshot: Mapped[dict[str, Any]] = mapped_column(default=dict)
    diff: Mapped[dict[str, Any]] = mapped_column(default=dict)  # {field: [old, new]}
    is_material: Mapped[bool] = mapped_column(Boolean, default=False)
    summary: Mapped[str | None] = mapped_column(Text)


class DuplicateCandidate(Base):
    """Possible duplicates that were NOT merged automatically; surfaced to reviewers."""

    __tablename__ = "duplicate_candidates"
    __table_args__ = (UniqueConstraint("event_a_id", "event_b_id"),)

    id: Mapped[UUIDPk]
    event_a_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"))
    event_b_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"))
    similarity: Mapped[float] = mapped_column(Float)
    reasons: Mapped[list[Any]] = mapped_column(default=list)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open/merged/distinct
    created_at: Mapped[CreatedAt]
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EventClaimRequest(Base):
    """An organizer asks to take ownership of an indexed event. Needs reviewer approval."""

    __tablename__ = "event_claim_requests"

    id: Mapped[UUIDPk]
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    requested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    justification: Mapped[str] = mapped_column(Text)
    proof_url: Mapped[str | None] = mapped_column(String(1000))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[CreatedAt]

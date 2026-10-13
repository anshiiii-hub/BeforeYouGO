"""Request schemas. Responses are plain dictionaries built by the service layer (see services/views.py)
so that every value shown to a user carries its provenance."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl, StringConstraints, field_validator

from app.domain.enums import (
    AccessState,
    ClaimCategory,
    ClaimStatus,
    ClaimType,
    DisputeKind,
    EventCategory,
    EventFormat,
    FeedbackResponse,
    ModerationStatus,
    Role,
)

Text = Annotated[str, StringConstraints(strip_whitespace=True)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ------------------------------------------------------------------ auth / profile


class RegisterIn(Strict):
    email: EmailStr
    password: str = Field(min_length=10, max_length=200)
    display_name: Text = Field(min_length=1, max_length=120)
    role: Literal["student", "organizer"] = "student"


class LoginIn(Strict):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class MeUpdateIn(Strict):
    display_name: Text | None = Field(None, min_length=1, max_length=120)
    current_password: str | None = None
    new_password: str | None = Field(None, min_length=10, max_length=200)


class DeleteAccountIn(Strict):
    password: str


class ProfileIn(Strict):
    education_level: Literal["diploma", "undergraduate", "postgraduate", "other"] | None = None
    year_of_study: int | None = Field(None, ge=1, le=8)
    institution: Text | None = Field(None, max_length=200)
    interests: list[Text] = Field(default_factory=list, max_length=30)
    skill_level: Literal["beginner", "intermediate", "advanced"] | None = None
    learning_goals: Text | None = Field(None, max_length=2000)
    career_goals: Text | None = Field(None, max_length=2000)
    available_from: date | None = None
    available_to: date | None = None
    max_budget_inr: Decimal | None = Field(None, ge=0, le=10_000_000)
    preferred_formats: list[Literal["online", "offline", "hybrid"]] = Field(default_factory=list)
    require_format: bool = False
    home_city: Text | None = Field(None, max_length=120)
    max_travel_km: int | None = Field(None, ge=0, le=20000)
    accessibility_needs: list[Text] = Field(default_factory=list, max_length=20)
    preferred_duration_days_max: int | None = Field(None, ge=1, le=365)
    team_preference: Literal["individual", "team", "either"] | None = None

    @field_validator("available_to")
    @classmethod
    def _window(cls, v: date | None, info):  # type: ignore[no-untyped-def]
        start = info.data.get("available_from")
        if v and start and v < start:
            raise ValueError("available_to must not be before available_from")
        return v


# ------------------------------------------------------------------ events


class CompareIn(Strict):
    event_ids: list[uuid.UUID] = Field(min_length=2, max_length=4)


class SubmitUrlIn(Strict):
    url: Text = Field(min_length=8, max_length=1000)


class SubmitTextIn(Strict):
    title: Text = Field(min_length=3, max_length=400)
    text: Text = Field(min_length=40, max_length=60000)
    url: Text | None = Field(None, max_length=1000)
    organizer_name: Text | None = Field(None, max_length=300)


class AnalyzeTextIn(Strict):
    text: Text = Field(min_length=20, max_length=60000)


class AnalyzeUrlIn(Strict):
    url: Text = Field(min_length=8, max_length=1000)


class ParticipationIn(Strict):
    conflict_of_interest: bool = False


class RecFeedbackIn(Strict):
    event_id: uuid.UUID
    vote: Literal["helpful", "not_relevant", "hide"]
    reason: Text | None = Field(None, max_length=500)


class SaveEventIn(Strict):
    note: Text | None = Field(None, max_length=1000)


class ReportIn(Strict):
    target_type: Literal["feedback", "evidence", "event", "claim"]
    target_id: uuid.UUID
    reason: Text = Field(min_length=10, max_length=1000)


# ------------------------------------------------------------------ organizer


class OrgIn(Strict):
    name: Text = Field(min_length=2, max_length=200)
    website: Text | None = Field(None, max_length=500)


class EventFieldsIn(Strict):
    """Everything an organizer can assert about their event. Omitted = unchanged (on update) / unknown (on create)."""

    title: Text | None = Field(None, min_length=3, max_length=400)
    description: Text | None = Field(None, max_length=30000)
    canonical_url: Text | None = Field(None, max_length=1000)
    registration_url: Text | None = Field(None, max_length=1000)
    organizer_name: Text | None = Field(None, max_length=300)
    organizer_url: Text | None = Field(None, max_length=1000)
    category: EventCategory | None = None
    start_date: date | None = None
    end_date: date | None = None
    registration_deadline: datetime | None = None
    format: EventFormat | None = None
    venue: Text | None = Field(None, max_length=400)
    city: Text | None = Field(None, max_length=160)
    state: Text | None = Field(None, max_length=160)
    country: Text | None = Field(None, max_length=160)
    eligibility: Text | None = Field(None, max_length=5000)
    prerequisites: Text | None = Field(None, max_length=5000)
    team_size_min: int | None = Field(None, ge=1, le=100)
    team_size_max: int | None = Field(None, ge=1, le=100)
    allows_cross_college_teams: bool | None = None
    fee_status: Literal["free", "paid", "unknown"] | None = None
    fee_amount: Decimal | None = Field(None, ge=0, le=10_000_000)
    fee_currency: Text | None = Field(None, min_length=3, max_length=3)
    other_costs: Text | None = Field(None, max_length=3000)
    prize_details: Text | None = Field(None, max_length=5000)
    time_commitment: Text | None = Field(None, max_length=2000)
    schedule_text: Text | None = Field(None, max_length=10000)
    judging_criteria: Text | None = Field(None, max_length=5000)
    refund_policy: Text | None = Field(None, max_length=3000)
    contact_info: Text | None = Field(None, max_length=500)
    accommodation_info: Text | None = Field(None, max_length=3000)
    offers_certificate: bool | None = None
    offers_mentorship: bool | None = None


class OrgEventCreateIn(EventFieldsIn):
    title: Text = Field(min_length=3, max_length=400)  # type: ignore[assignment]
    organization_id: uuid.UUID
    publish: bool = False


class OrgEventUpdateIn(EventFieldsIn):
    change_note: Text | None = Field(None, max_length=500)


class OwnershipRequestIn(Strict):
    organization_id: uuid.UUID
    justification: Text = Field(min_length=20, max_length=2000)
    proof_url: Text | None = Field(None, max_length=1000)


class ManualClaimIn(Strict):
    original_text: Text = Field(min_length=8, max_length=1500)
    category: ClaimCategory = ClaimCategory.OTHER
    claim_type: ClaimType = ClaimType.SPECIFIC
    responsible_party: Text | None = Field(None, max_length=300)
    conditions: list[Text] = Field(default_factory=list, max_length=10)


class ClaimCorrectionIn(Strict):
    normalized_text: Text | None = Field(None, min_length=8, max_length=1500)
    category: ClaimCategory | None = None
    claim_type: ClaimType | None = None
    responsible_party: Text | None = Field(None, max_length=300)
    conditions: list[Text] | None = Field(None, max_length=10)
    withdraw: bool | None = None
    reason: Text = Field(min_length=5, max_length=500)


class AccessibilityIn(Strict):
    state: AccessState
    detail: Text | None = Field(None, max_length=1500)
    evidence_url: Text | None = Field(None, max_length=1000)


class GapResolveIn(Strict):
    status: Literal["resolved", "dismissed", "open"]
    note: Text = Field(min_length=5, max_length=1000)


class OrganizerResponseIn(Strict):
    claim_id: uuid.UUID | None = None
    feedback_id: uuid.UUID | None = None
    event_id: uuid.UUID
    body: Text = Field(min_length=5, max_length=3000)


# ------------------------------------------------------------------ accountability


class TransitionIn(Strict):
    to_status: ClaimStatus
    reason: Text = Field(min_length=5, max_length=2000)
    review_outcome: Text | None = Field(None, max_length=60)


class EvidenceIn(Strict):
    url: Text | None = Field(None, max_length=1000)
    excerpt: Text | None = Field(None, max_length=4000)
    kind: Literal["organizer_provided", "public_source", "participant_report", "independent_review"] | None = None
    claim_specific: bool = True
    coi_declared: bool = False
    coi_statement: Text | None = Field(None, max_length=1000)


class EvidenceReviewIn(Strict):
    decision: Literal["accepted", "rejected"]
    note: Text = Field(min_length=5, max_length=1000)


class DisputeIn(Strict):
    event_id: uuid.UUID
    claim_id: uuid.UUID | None = None
    kind: DisputeKind
    description: Text = Field(min_length=15, max_length=3000)


class DisputeResolveIn(Strict):
    outcome: Literal["upheld", "rejected", "under_review"]
    note: Text = Field(min_length=5, max_length=2000)
    restore_status: ClaimStatus | None = None
    withdraw_claim: bool = False


class FeedbackItemIn(Strict):
    claim_id: uuid.UUID
    response: FeedbackResponse
    comment: Text | None = Field(None, max_length=2000)
    evidence_url: Text | None = Field(None, max_length=1000)


class FeedbackIn(Strict):
    items: list[FeedbackItemIn] = Field(min_length=1, max_length=40)


# ------------------------------------------------------------------ admin


class UserAdminIn(Strict):
    role: Role | None = None
    is_active: bool | None = None


class SourceAdminIn(Strict):
    enabled: bool | None = None
    ics_feed_urls: list[Text] | None = Field(None, max_length=20)
    priority: int | None = Field(None, ge=0, le=100)


class ModerateIn(Strict):
    status: ModerationStatus
    note: Text | None = Field(None, max_length=1000)


class ReportHandleIn(Strict):
    action: Literal["dismiss", "upheld_hide"]
    note: Text = Field(min_length=3, max_length=1000)


class OwnershipDecisionIn(Strict):
    approve: bool
    note: Text = Field(min_length=3, max_length=1000)


class DuplicateResolveIn(Strict):
    action: Literal["distinct", "merge"]
    keep_event_id: uuid.UUID | None = None


class ConfigIn(Strict):
    stale_after_days: int | None = Field(None, ge=1, le=365)
    participant_threshold: int | None = Field(None, ge=1, le=100)
    unverified_grace_days: int | None = Field(None, ge=1, le=365)
    min_outcome_responses: int | None = Field(None, ge=1, le=100)
    scoring_weights: dict[str, float] | None = None


_ = HttpUrl  # imported for downstream use

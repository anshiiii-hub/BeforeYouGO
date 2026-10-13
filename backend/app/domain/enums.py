"""Controlled vocabularies used across the platform.

Every status or category that business rules depend on lives here so the
database, the API schemas and the rules engine agree on one definition.
"""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    STUDENT = "student"
    ORGANIZER = "organizer"
    REVIEWER = "reviewer"
    ADMIN = "admin"


class EventFormat(StrEnum):
    ONLINE = "online"
    OFFLINE = "offline"
    HYBRID = "hybrid"
    UNKNOWN = "unknown"


class FeeStatus(StrEnum):
    FREE = "free"  # source/organizer explicitly states free
    PAID = "paid"  # a non-zero fee is stated
    UNKNOWN = "unknown"  # nothing stated: NEVER interpreted as free


class EventCategory(StrEnum):
    HACKATHON = "hackathon"
    WORKSHOP = "workshop"
    CONFERENCE = "conference"
    MEETUP = "meetup"
    COMPETITION = "competition"
    INTERNSHIP = "internship"
    OTHER = "other"


class OriginType(StrEnum):
    INDEXED = "indexed"  # pulled from a connected source
    ORGANIZER_SUBMITTED = "organizer_submitted"
    USER_SUBMITTED = "user_submitted"  # e.g. saved from the analyzer


class Lifecycle(StrEnum):
    SCHEDULED = "scheduled"
    CANCELLED = "cancelled"  # explicitly marked cancelled by a source/organizer
    POSTPONED = "postponed"
    REMOVED_FROM_SOURCE = "removed_from_source"  # source no longer lists it (NOT proof of cancellation)
    UNKNOWN = "unknown"


class ClaimStatus(StrEnum):
    ADVERTISED = "advertised"
    NEEDS_CLARIFICATION = "needs_clarification"
    EVIDENCE_SUBMITTED = "evidence_submitted"
    CORROBORATED = "corroborated"
    FULFILLED = "fulfilled"
    PARTIALLY_FULFILLED = "partially_fulfilled"
    DISPUTED = "disputed"
    UNVERIFIED = "unverified"
    UNABLE_TO_DETERMINE = "unable_to_determine"


class ClaimType(StrEnum):
    SPECIFIC = "specific"
    VAGUE = "vague"
    CONDITIONAL = "conditional"
    INFORMATIONAL = "informational"


class ClaimCategory(StrEnum):
    PRIZE = "prize"
    CERTIFICATE = "certificate"
    MENTORSHIP = "mentorship"
    CAREER = "career_opportunity"
    TRAINING = "training_workshop"
    RECORDINGS = "recordings_materials"
    RESULTS_TIMELINE = "results_timeline"
    NETWORKING = "networking"
    PERKS = "perks_swag"
    TRAVEL_STAY = "travel_accommodation"
    FOOD = "food"
    LEARNING_OUTCOME = "learning_outcome"
    FEE = "fee_cost"
    REFUND = "refund_policy"
    SCHOLARSHIP = "scholarship_discount"
    ACCESSIBILITY = "accessibility"
    OTHER = "other"


class ExtractionMethod(StrEnum):
    LLM = "llm"
    DETERMINISTIC = "deterministic"
    SOURCE_FIELD = "source_field"
    MANUAL = "manual"


class EvidenceKind(StrEnum):
    ORGANIZER_PROVIDED = "organizer_provided"
    PUBLIC_SOURCE = "public_source"
    PARTICIPANT_REPORT = "participant_report"
    INDEPENDENT_REVIEW = "independent_review"


class ReviewStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class AccessState(StrEnum):
    DOCUMENTED = "documented"
    NOT_DOCUMENTED = "not_documented"
    CONFIRMED_UNAVAILABLE = "confirmed_unavailable"
    CONFLICTING = "conflicting"
    REQUIRES_CONFIRMATION = "requires_confirmation"


class FeedbackResponse(StrEnum):
    DELIVERED = "delivered"
    PARTIALLY_DELIVERED = "partially_delivered"
    NOT_DELIVERED = "not_delivered"
    NOT_APPLICABLE = "not_applicable"
    UNSURE = "unsure"


class ModerationStatus(StrEnum):
    PENDING = "pending"
    PUBLISHED = "published"
    REJECTED = "rejected"
    HIDDEN = "hidden"


class ParticipationLevel(StrEnum):
    SELF_DECLARED = "self_declared"
    ORGANIZER_CONFIRMED = "organizer_confirmed"
    REVIEWER_CONFIRMED = "reviewer_confirmed"


class DisputeKind(StrEnum):
    CLAIM_DISPUTE = "claim_dispute"  # organizer disputes an extracted/reported claim
    CORRECTION_REQUEST = "correction_request"  # organizer says information is wrong
    APPEAL = "appeal"  # organizer appeals a reviewer decision


class DisputeStatus(StrEnum):
    OPEN = "open"
    UNDER_REVIEW = "under_review"
    UPHELD = "upheld"  # dispute accepted
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class Severity(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class GapStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class SourceStatus(StrEnum):
    PENDING = "pending_first_sync"  # connector implemented; no synchronisation has completed yet
    ACTIVE = "active"  # connector implemented and last synchronisation succeeded
    DEGRADED = "degraded"  # implemented, but the most recent synchronisation failed
    NEEDS_CREDENTIALS = "needs_credentials"
    NOT_CONFIGURED = "not_configured"
    BLOCKED = "blocked"  # network policy / robots / terms prevent automated access
    NOT_IMPLEMENTED = "not_implemented"  # no verified access method exists
    DISABLED = "disabled"


class SyncStatus(StrEnum):
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class AnalysisInput(StrEnum):
    TEXT = "text"
    URL = "url"
    FILE = "file"
    EVENT = "event"


class FieldOrigin(StrEnum):
    SOURCE = "source"  # read directly from a source record
    DERIVED = "derived"  # deterministic transformation of a source field
    AI_EXTRACTED = "ai_extracted"
    MANUAL = "manual"  # corrected by an authorised human
    ORGANIZER = "organizer"

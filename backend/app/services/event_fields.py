"""Registry of event fields that connectors may assert, with their types and rules.

Unknown stays unknown: a connector omits a field (value None) instead of guessing,
and the merge layer never invents a value for an omitted field.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class FieldSpec:
    kind: str  # str/text/date/datetime/decimal/bool/int/float/json
    material: bool = False  # change is flagged as a material change
    label: str = ""


FIELD_SPECS: dict[str, FieldSpec] = {
    "title": FieldSpec("str", False, "Title"),
    "description": FieldSpec("text", False, "Description"),
    "canonical_url": FieldSpec("str", True, "Event website"),
    "organizer_name": FieldSpec("str", False, "Organizer"),
    "organizer_url": FieldSpec("str", False, "Organizer website"),
    "category": FieldSpec("str", False, "Category"),
    "topics": FieldSpec("json", False, "Topics"),
    "tags": FieldSpec("json", False, "Tags"),
    "start_date": FieldSpec("date", True, "Start date"),
    "end_date": FieldSpec("date", True, "End date"),
    "start_at": FieldSpec("datetime", True, "Start time"),
    "end_at": FieldSpec("datetime", True, "End time"),
    "registration_deadline": FieldSpec("datetime", True, "Registration deadline"),
    "registration_deadline_date_only": FieldSpec("bool", False, "Deadline is date-only"),
    "registration_url": FieldSpec("str", True, "Registration link"),
    "format": FieldSpec("str", True, "Format"),
    "venue": FieldSpec("str", True, "Venue"),
    "city": FieldSpec("str", True, "City"),
    "state": FieldSpec("str", False, "State"),
    "country": FieldSpec("str", True, "Country"),
    "eligibility": FieldSpec("text", True, "Eligibility"),
    "eligibility_structured": FieldSpec("json", True, "Structured eligibility"),
    "prerequisites": FieldSpec("text", False, "Prerequisites"),
    "team_size_min": FieldSpec("int", False, "Minimum team size"),
    "team_size_max": FieldSpec("int", False, "Maximum team size"),
    "allows_cross_college_teams": FieldSpec("bool", False, "Cross-college teams"),
    "fee_status": FieldSpec("str", True, "Fee status"),
    "fee_amount": FieldSpec("decimal", True, "Registration fee"),
    "fee_currency": FieldSpec("str", True, "Fee currency"),
    "other_costs": FieldSpec("text", False, "Other costs"),
    "prize_details": FieldSpec("text", True, "Prize details"),
    "time_commitment": FieldSpec("text", False, "Time commitment"),
    "schedule_text": FieldSpec("text", False, "Schedule"),
    "judging_criteria": FieldSpec("text", False, "Judging criteria"),
    "refund_policy": FieldSpec("text", True, "Refund policy"),
    "contact_info": FieldSpec("str", False, "Contact"),
    "accommodation_info": FieldSpec("text", False, "Accommodation"),
    "offers_certificate": FieldSpec("bool", False, "Certificate offered"),
    "offers_mentorship": FieldSpec("bool", False, "Mentorship offered"),
    "lifecycle_status": FieldSpec("str", True, "Status"),
}

# Fields that, when absent from every assertion, simply remain at the column default / NULL.
DEFAULT_WHEN_UNASSERTED: dict[str, Any] = {
    "format": "unknown",
    "fee_status": "unknown",
    "lifecycle_status": "scheduled",
    "category": "other",
    "topics": [],
    "tags": [],
    "eligibility_structured": {},
    "registration_deadline_date_only": False,
}


def encode_value(value: Any) -> str:
    """JSON-encode a python value for storage/comparison in an assertion row."""

    def default(o: Any) -> Any:
        if isinstance(o, datetime):
            return o.isoformat()
        if isinstance(o, date):
            return o.isoformat()
        if isinstance(o, Decimal):
            return str(o)
        raise TypeError(f"not serialisable: {type(o)}")

    return json.dumps(value, default=default, sort_keys=True, ensure_ascii=False)


def decode_value(name: str, text: str) -> Any:
    raw = json.loads(text)
    if raw is None:
        return None
    kind = FIELD_SPECS[name].kind
    if kind == "date":
        return date.fromisoformat(raw)
    if kind == "datetime":
        return datetime.fromisoformat(raw)
    if kind == "decimal":
        return Decimal(str(raw))
    return raw


def jsonable(value: Any) -> Any:
    """Convert a python value to plain JSON types (used for snapshots/diffs)."""
    return json.loads(encode_value(value))


@dataclass
class NormalizedEvent:
    """What every connector produces. Missing information stays None."""

    source_event_id: str
    title: str
    values: dict[str, Any] = field(default_factory=dict)  # only FIELD_SPECS keys, only known values
    origins: dict[str, str] = field(default_factory=dict)  # field -> "source" | "derived"
    source_url: str | None = None  # where the record was retrieved from
    extras: dict[str, Any] = field(default_factory=dict)  # source-specific facts, never mapped to core fields
    accessibility: dict[str, dict[str, Any]] = field(default_factory=dict)  # item_key -> {state, detail, excerpt}
    field_claims: list[dict[str, Any]] = field(default_factory=list)  # claims straight from structured source fields
    extraction_confidence: float = 1.0

    def set(self, name: str, value: Any, origin: str = "source") -> None:
        """Record a known value. None / empty strings are ignored so unknown stays unknown."""
        if name not in FIELD_SPECS:
            raise KeyError(f"unknown event field: {name}")
        if value is None:
            return
        if isinstance(value, str) and not value.strip():
            return
        if isinstance(value, list | dict) and not value:
            return
        self.values[name] = value
        self.origins[name] = origin

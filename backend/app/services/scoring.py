"""Explainable decision engine.

* Hard constraints (explicit student requirements, stated eligibility, closed registration)
  exclude an event. They are never traded off against interest.
* Soft components are weighted preference matches. Components whose inputs are UNKNOWN are
  left out and the remaining weights renormalised (unknown is not penalised and not rewarded);
  the coverage is shown so a score built on little information looks that way.
* The result is a weighted preference match, NOT a probability of a good outcome.
* Suitability, completeness, evidence strength, organizer engagement and outcome quality are
  separate measures answering different questions. They are never merged into one "trust score".
All arithmetic is plain code; no model is involved.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.services.eligibility import parse_eligibility
from app.services.geo import approx_distance_km
from app.services.taxonomy import topics_from_interests, topics_from_text

DEFAULT_WEIGHTS: dict[str, float] = {
    "interest": 0.30,
    "skill_level": 0.15,
    "budget": 0.15,
    "schedule": 0.10,
    "location": 0.10,
    "goals": 0.10,
    "format": 0.05,
    "duration": 0.05,
}
LABELS = {
    "interest": "Interest alignment", "skill_level": "Skill-level suitability", "budget": "Budget",
    "schedule": "Schedule", "location": "Location and travel", "goals": "Learning / career goals",
    "format": "Preferred format", "duration": "Preferred duration",
}
MIN_COVERAGE = 0.40
LEVEL_ORDER = {"beginner": 0, "intermediate": 1, "advanced": 2}

_BEGINNER = ("beginner", "no prior experience", "no prior knowledge", "newcomer", "introductory", "intro to", "from scratch", "first-time")
_ADVANCED = ("advanced", "expert", "experienced", "senior", "deep dive", "production-grade", "research-level")
_INTERMEDIATE = ("intermediate", "some experience", "basic knowledge of", "working knowledge", "familiarity with")

GOAL_CLAIMS = {
    "career_opportunity": ("internship", "job", "career", "placement", "hired", "hiring", "work experience"),
    "certificate": ("certificate", "certification", "resume", "cv", "portfolio"),
    "mentorship": ("mentor", "guidance", "network", "connections", "industry"),
    "training_workshop": ("learn", "skill", "workshop", "hands-on", "upskill", "practical"),
    "prize": ("prize", "win", "money", "stipend", "scholarship"),
    "learning_outcome": ("learn", "skill", "project", "build", "portfolio"),
    "networking": ("network", "community", "connections", "peers"),
}


@dataclass
class Component:
    key: str
    label: str
    weight: float
    score: float | None  # 0..1, None when unknown
    reason: str
    known: bool = field(init=False)

    def __post_init__(self) -> None:
        self.known = self.score is not None


def _d(value: Any) -> Decimal | None:
    return Decimal(str(value)) if value is not None else None


def event_level(text: str) -> str | None:
    low = text.lower()
    hits = {
        "beginner": any(k in low for k in _BEGINNER),
        "intermediate": any(k in low for k in _INTERMEDIATE),
        "advanced": any(k in low for k in _ADVANCED),
    }
    found = [k for k, v in hits.items() if v]
    return found[0] if len(found) == 1 else None  # contradictory or silent -> unknown


def _event_text(event: Any) -> str:
    return " ".join(str(getattr(event, f) or "") for f in ("title", "description", "prerequisites", "eligibility", "tags_text"))


# ----------------------------------------------------------------- hard constraints


def hard_constraints(event: Any, profile: Any, *, now: datetime | None = None, access: dict[str, str] | None = None) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Return (violations, unknowns). A violation excludes the event; an unknown asks the student to check."""
    now = now or datetime.now(UTC)
    today = now.date()
    violations: list[dict[str, str]] = []
    unknowns: list[dict[str, str]] = []

    def v(key: str, msg: str) -> None:
        violations.append({"key": key, "message": msg})

    def u(key: str, msg: str) -> None:
        unknowns.append({"key": key, "message": msg})

    end = event.end_date or event.start_date
    if end is not None and end < today:
        v("event_ended", f"The event ended on {end.isoformat()}.")
    if event.lifecycle_status == "cancelled":
        v("cancelled", "The listing states this event is cancelled.")
    if event.registration_deadline is not None and event.registration_deadline < now:
        v("registration_closed", f"Registration closed on {event.registration_deadline.date().isoformat()}.")

    if profile is None:
        return violations, unknowns

    # budget (only comparable when the fee is a known INR amount)
    budget = _d(profile.max_budget_inr)
    if budget is not None:
        if event.fee_status == "paid" and event.fee_amount is not None:
            if (event.fee_currency or "INR").upper() == "INR":
                if _d(event.fee_amount) > budget:
                    v("budget", f"Registration fee ₹{event.fee_amount} is above your maximum budget of ₹{budget}.")
            else:
                u("budget", f"The fee is in {event.fee_currency}; it is not converted, so compare it with your budget yourself.")
        elif event.fee_status in ("unknown", "paid"):
            u("budget", "The fee is not stated, so it cannot be checked against your budget.")

    # format requirement
    if profile.require_format and profile.preferred_formats and event.format != "unknown":
        wanted = set(profile.preferred_formats)
        if event.format != "hybrid" and event.format not in wanted:
            v("format", f"This event is {event.format}; you required {', '.join(sorted(wanted))}.")
    elif profile.require_format and event.format == "unknown":
        u("format", "The format (online/offline) is not stated.")

    # availability window
    if profile.available_from or profile.available_to:
        if event.start_date is None:
            u("schedule", "The event dates are not stated.")
        else:
            e_end = event.end_date or event.start_date
            if profile.available_from and event.start_date < profile.available_from:
                v("schedule", f"Starts {event.start_date.isoformat()}, before your availability begins ({profile.available_from.isoformat()}).")
            elif profile.available_to and e_end > profile.available_to:
                v("schedule", f"Ends {e_end.isoformat()}, after your availability ends ({profile.available_to.isoformat()}).")

    # travel
    if profile.max_travel_km is not None and event.format in ("offline", "hybrid"):
        dist = approx_distance_km(profile.home_city, event.city)
        if dist is None:
            u("travel", "Distance from your city could not be determined (city missing or unknown).")
        elif dist > profile.max_travel_km:
            v("travel", f"About {dist:.0f} km from {profile.home_city}, beyond your {profile.max_travel_km} km limit (straight-line estimate).")

    # stated eligibility
    structured = dict(event.eligibility_structured or {})
    parsed = parse_eligibility(event.eligibility or event.description)
    years = structured.get("years") or parsed["years"]
    levels = structured.get("levels") or parsed["levels"]
    evidence = parsed["evidence"]
    if years:
        if profile.year_of_study is None:
            u("eligibility", f"Open only to year(s) {', '.join(map(str, years))}; add your year of study to check.")
        elif profile.year_of_study not in years:
            v("eligibility", f"Stated eligibility covers year(s) {', '.join(map(str, years))}; you are in year {profile.year_of_study}. Source: “{evidence}”")
    if levels:
        if not profile.education_level:
            u("eligibility_level", f"Open to {', '.join(levels)} students; add your education level to check.")
        elif profile.education_level not in levels:
            v("eligibility_level", f"Stated eligibility covers {', '.join(levels)}; your level is {profile.education_level}. Source: “{evidence}”")
    if not event.eligibility and not years and not levels:
        u("eligibility", "No eligibility rules were found; confirm you qualify before investing time.")

    # accessibility needs
    for need in profile.accessibility_needs or []:
        state = (access or {}).get(need, "not_documented")
        if state == "confirmed_unavailable":
            v(f"access_{need}", f"The organizer documents that '{need.replace('_', ' ')}' is not available.")
        elif state == "conflicting":
            u(f"access_{need}", f"Sources conflict about '{need.replace('_', ' ')}'. Ask the organizer.")
        elif state != "documented":
            u(f"access_{need}", f"'{need.replace('_', ' ')}' is not documented. This is unknown, not unavailable.")
    return violations, unknowns


# ----------------------------------------------------------------- soft components


def _interest(event: Any, profile: Any) -> Component:
    w = DEFAULT_WEIGHTS["interest"]
    wanted = topics_from_interests(profile.interests or [])
    if not wanted:
        return Component("interest", LABELS["interest"], w, None, "You have not listed interests.")
    have = set(event.topics or []) | set(topics_from_text(_event_text(event)))
    cat = event.category
    if not have and cat in ("other", None):
        return Component("interest", LABELS["interest"], w, None, "The event has no recognisable topic information.")
    overlap = sorted(wanted & have)
    if len(overlap) >= 2:
        return Component("interest", LABELS["interest"], w, 1.0, f"Matches {len(overlap)} of your interests: {', '.join(overlap)}.")
    if len(overlap) == 1:
        return Component("interest", LABELS["interest"], w, 0.7, f"Matches your interest in {overlap[0]}.")
    return Component("interest", LABELS["interest"], w, 0.15, f"Topics ({', '.join(sorted(have)) or 'none recognised'}) do not overlap your interests ({', '.join(sorted(wanted))}).")


def _skill(event: Any, profile: Any) -> Component:
    w = DEFAULT_WEIGHTS["skill_level"]
    ev = event_level(_event_text(event))
    if not profile.skill_level or ev is None:
        why = "Your skill level is not set." if not profile.skill_level else "The event does not clearly state a difficulty level."
        return Component("skill_level", LABELS["skill_level"], w, None, why)
    gap = abs(LEVEL_ORDER[ev] - LEVEL_ORDER[profile.skill_level])
    score = {0: 1.0, 1: 0.5}.get(gap, 0.1)
    if LEVEL_ORDER[ev] < LEVEL_ORDER[profile.skill_level] and gap == 1:
        score = 0.7  # slightly easier than your level is a milder mismatch than harder
    return Component("skill_level", LABELS["skill_level"], w, score, f"Event reads as {ev}; you are {profile.skill_level}.")


def _budget(event: Any, profile: Any) -> Component:
    w = DEFAULT_WEIGHTS["budget"]
    if profile.max_budget_inr is None:
        return Component("budget", LABELS["budget"], w, None, "You have not set a budget.")
    if event.fee_status == "free":
        return Component("budget", LABELS["budget"], w, 1.0, "Stated as free (travel and other costs may still apply).")
    if event.fee_status == "paid" and event.fee_amount is not None and (event.fee_currency or "INR").upper() == "INR":
        fee, budget = _d(event.fee_amount), _d(profile.max_budget_inr)
        if fee <= budget:
            score = 1.0 if budget == 0 or fee <= budget / 2 else 0.75
            return Component("budget", LABELS["budget"], w, score, f"Fee ₹{fee} is within your ₹{budget} budget.")
        return Component("budget", LABELS["budget"], w, 0.0, f"Fee ₹{fee} exceeds your ₹{budget} budget.")
    return Component("budget", LABELS["budget"], w, None, "The cost is unknown, so it is not counted for or against this event.")


def _schedule(event: Any, profile: Any) -> Component:
    w = DEFAULT_WEIGHTS["schedule"]
    if not (profile.available_from or profile.available_to):
        return Component("schedule", LABELS["schedule"], w, None, "You have not set availability dates.")
    if event.start_date is None:
        return Component("schedule", LABELS["schedule"], w, None, "The event dates are not stated.")
    return Component("schedule", LABELS["schedule"], w, 1.0, "Falls within your available dates.")  # violations were handled as hard constraints


def _location(event: Any, profile: Any) -> Component:
    w = DEFAULT_WEIGHTS["location"]
    if event.format == "online":
        return Component("location", LABELS["location"], w, 1.0, "Online: no travel needed.")
    if event.format == "unknown":
        return Component("location", LABELS["location"], w, None, "Whether the event is in person is not stated.")
    dist = approx_distance_km(profile.home_city, event.city)
    if dist is None:
        return Component("location", LABELS["location"], w, None, "Distance could not be determined; travel cost is unknown.")
    if profile.max_travel_km:
        score = max(0.0, 1.0 - 0.5 * dist / profile.max_travel_km)
        return Component("location", LABELS["location"], w, round(score, 2), f"About {dist:.0f} km away (limit {profile.max_travel_km} km). Travel cost is unknown.")
    score = 1.0 if dist < 100 else 0.6 if dist < 500 else 0.3
    return Component("location", LABELS["location"], w, score, f"About {dist:.0f} km away. Travel cost is unknown.")


def _goals(event: Any, profile: Any, claim_categories: set[str]) -> Component:
    w = DEFAULT_WEIGHTS["goals"]
    goals = f"{profile.learning_goals or ''} {profile.career_goals or ''}".lower().strip()
    if not goals:
        return Component("goals", LABELS["goals"], w, None, "You have not described learning or career goals.")
    cats = set(claim_categories)
    if event.offers_certificate:
        cats.add("certificate")
    if event.offers_mentorship:
        cats.add("mentorship")
    if not cats:
        return Component("goals", LABELS["goals"], w, None, "No advertised benefits are on record for this event yet.")
    matched = sorted(c for c, words in GOAL_CLAIMS.items() if c in cats and any(k in goals for k in words))
    if matched:
        return Component("goals", LABELS["goals"], w, min(1.0, 0.6 + 0.2 * len(matched)),
                         f"Advertised benefits relevant to your goals: {', '.join(m.replace('_', ' ') for m in matched)} (advertised, not verified).")
    return Component("goals", LABELS["goals"], w, 0.2, "Advertised benefits do not obviously relate to your stated goals.")


def _format(event: Any, profile: Any) -> Component:
    w = DEFAULT_WEIGHTS["format"]
    if not profile.preferred_formats:
        return Component("format", LABELS["format"], w, None, "You have not set a preferred format.")
    if event.format == "unknown":
        return Component("format", LABELS["format"], w, None, "Format not stated.")
    ok = event.format == "hybrid" or event.format in profile.preferred_formats
    return Component("format", LABELS["format"], w, 1.0 if ok else 0.3, f"Event is {event.format}; you prefer {', '.join(profile.preferred_formats)}.")


def _duration(event: Any, profile: Any) -> Component:
    w = DEFAULT_WEIGHTS["duration"]
    if not profile.preferred_duration_days_max:
        return Component("duration", LABELS["duration"], w, None, "You have not set a preferred duration.")
    if event.start_date is None:
        return Component("duration", LABELS["duration"], w, None, "Dates not stated.")
    days = ((event.end_date or event.start_date) - event.start_date).days + 1
    ok = days <= profile.preferred_duration_days_max
    return Component("duration", LABELS["duration"], w, 1.0 if ok else 0.3, f"{days} day(s); you prefer up to {profile.preferred_duration_days_max}.")


def suitability(event: Any, profile: Any, *, claim_categories: set[str] | None = None, now: datetime | None = None,
                access: dict[str, str] | None = None, weights: dict[str, float] | None = None) -> dict[str, Any]:
    violations, unknowns = hard_constraints(event, profile, now=now, access=access)
    result: dict[str, Any] = {"hard_violations": violations, "unknowns": unknowns, "eligible": not violations}
    if profile is None:
        result.update(score=None, label="Sign in and set preferences for a personal assessment", components=[], coverage=0.0, weights=weights or DEFAULT_WEIGHTS,
                      why_match=[], why_skip=[v["message"] for v in violations], tradeoffs=[], note=None)
        return result
    comps = [_interest(event, profile), _skill(event, profile), _budget(event, profile), _schedule(event, profile),
             _location(event, profile), _goals(event, profile, claim_categories or set()), _format(event, profile), _duration(event, profile)]
    wts = weights or DEFAULT_WEIGHTS
    for c in comps:
        c.weight = wts.get(c.key, c.weight)
    known = [c for c in comps if c.known]
    total_w = sum(c.weight for c in comps)
    known_w = sum(c.weight for c in known)
    coverage = known_w / total_w if total_w else 0.0
    score = round(100 * sum(c.weight * c.score for c in known) / known_w) if known_w else None  # type: ignore[operator]
    if violations:
        label = "Excluded by your constraints"
    elif score is None or coverage < MIN_COVERAGE:
        label = "Not enough information to rate"
    elif score >= 75:
        label = "Strong match"
    elif score >= 55:
        label = "Possible match"
    else:
        label = "Weak match"
    why_match = [c.reason for c in known if c.score is not None and c.score >= 0.7]
    why_skip = [x["message"] for x in violations] + [c.reason for c in known if c.score is not None and c.score <= 0.3]
    tradeoffs = [f"{a.label}: {a.reason} — but {b.label.lower()}: {b.reason}" for a in known if a.score is not None and a.score >= 0.7
                 for b in known if b.score is not None and b.score <= 0.3][:3]
    result.update(
        score=score, label=label, coverage=round(coverage, 2),
        components=[{"key": c.key, "label": c.label, "weight": round(c.weight, 3), "score": c.score, "known": c.known,
                     "reason": c.reason, "contribution": round(100 * c.weight * c.score / known_w, 1) if (c.known and known_w) else None} for c in comps],
        weights=wts, why_match=why_match, why_skip=why_skip, tradeoffs=tradeoffs,
        note="A weighted preference match, not a probability of success. Unknown factors are left out, not guessed. "
             f"Based on {len(known)} of {len(comps)} factors ({round(coverage * 100)}% of the weight).",
    )
    return result


# ----------------------------------------------------------------- separate, event-level measures


def completeness(event: Any, accessibility_documented: int) -> dict[str, Any]:
    offline = event.format in ("offline", "hybrid")
    checks: list[tuple[str, str, bool]] = [
        ("start_date", "Start date", event.start_date is not None),
        ("registration_deadline", "Registration deadline", event.registration_deadline is not None),
        ("registration_url", "Registration link", bool(event.registration_url or event.canonical_url)),
        ("eligibility", "Eligibility", bool(event.eligibility)),
        ("fee", "Fee stated (free or amount)", event.fee_status in ("free", "paid")),
        ("format", "Format (online/offline/hybrid)", event.format != "unknown"),
        ("organizer_name", "Organizer", bool(event.organizer_name)),
        ("description", "Description", bool(event.description)),
        ("schedule", "Schedule", bool(event.schedule_text)),
        ("contact", "Contact details", bool(event.contact_info)),
        ("accessibility", "Accessibility information", accessibility_documented > 0),
    ]
    if offline:
        checks += [("venue", "Venue", bool(event.venue)), ("city", "City", bool(event.city))]
    if event.category in ("hackathon", "competition"):
        checks += [("judging", "Judging criteria", bool(event.judging_criteria)), ("team_size", "Team size", event.team_size_max is not None)]
    filled = sum(1 for _, _, ok in checks if ok)
    return {
        "score": round(100 * filled / len(checks)), "filled": filled, "total": len(checks),
        "missing": [{"key": k, "label": label} for k, label, ok in checks if not ok],
        "note": f"{filled} of {len(checks)} applicable details are present in the record. Missing means not stated in the retrieved sources.",
    }


def evidence_strength(source_count: int, claims: list[Any], accepted_independent: int, origin_type: str) -> dict[str, Any]:
    active = [c for c in claims if c.is_active]
    corroborated = [c for c in active if c.status in ("corroborated", "fulfilled", "partially_fulfilled")]
    with_evidence = [c for c in active if c.status == "evidence_submitted"]
    if not active:
        level, why = "listing_only", "The listing has been retrieved, but no advertised claims have been analysed yet."
    elif corroborated and len(corroborated) * 2 >= len(active):
        level, why = "substantial", "At least half of the advertised claims have independent corroboration or documented outcomes."
    elif corroborated or with_evidence:
        level, why = "partial", "Some claims have evidence attached or have been corroborated; many remain advertised only."
    else:
        level, why = "advertised_only", "Claims are advertised by the organizer; no independent evidence has been reviewed."
    return {
        "level": level, "rule": why, "sources": source_count, "claims_total": len(active),
        "claims_corroborated_or_outcome": len(corroborated), "claims_with_evidence_pending": len(with_evidence),
        "accepted_independent_evidence": accepted_independent, "origin": origin_type,
        "note": "Evidence strength describes what has been checked, not whether the organizer is honest.",
    }

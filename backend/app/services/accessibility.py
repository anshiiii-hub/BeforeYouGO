"""Accessibility information panel: what is documented, never what is assumed.

States are explicit (documented / not_documented / confirmed_unavailable / conflicting /
requires_confirmation). A page that does not mention wheelchair access yields
``not_documented`` — never ``confirmed_unavailable``.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import AccessState
from app.models import AccessibilityItem, Event
from app.services.analyzer.deterministic import split_sentences

# key, label, applies ("physical" = in-person only, "any"), positive pattern, negative pattern, student question, organizer fix
ITEMS: list[dict[str, Any]] = [
    {"key": "step_free_entry", "label": "Step-free entry", "applies": "physical",
     "pos": r"\bstep[- ]free\b|\bramps?\b|\blevel access\b|\bground[- ]floor\b|\blift\b|\belevator\b",
     "neg": r"\b(no|without|not)\b[^.]{0,25}\b(step[- ]free|ramp|lift|elevator|level access)\b",
     "q": "Is the venue entrance step-free, and are lifts available to all session rooms?",
     "fix": "State whether the entrance and session rooms are step-free, and where lifts or ramps are."},
    {"key": "wheelchair_access", "label": "Wheelchair access", "applies": "physical",
     "pos": r"\bwheelchair[- ](accessible|friendly|access)\b|\bwheelchair users?\b[^.]{0,30}\b(welcome|can|supported)",
     "neg": r"\b(not|isn'?t|is not)\b[^.]{0,20}\bwheelchair[- ]accessible\b|\bno wheelchair\b|\binaccessible (to|for) wheelchair",
     "q": "Is the venue fully wheelchair accessible, including seating areas and the stage?",
     "fix": "Document wheelchair access for the entrance, rooms, seating and stage."},
    {"key": "accessible_toilets", "label": "Accessible toilets", "applies": "physical",
     "pos": r"\baccessible (toilets?|washrooms?|restrooms?)\b|\bdisabled toilets?\b",
     "neg": r"\bno accessible (toilets?|washrooms?|restrooms?)\b",
     "q": "Are accessible toilets available on the event floor?", "fix": "State where accessible toilets are located."},
    {"key": "venue_navigation", "label": "Venue navigation", "applies": "physical",
     "pos": r"\bdirections\b|\bhow to (reach|get)\b|\bnearest (metro|station|bus)|\bgoogle maps\b|\bsignage\b|\bvolunteers? will guide",
     "neg": None,
     "q": "Is there a step-by-step route from the nearest transport, and will on-site guidance be available?", "fix": "Provide directions from public transport and describe on-site wayfinding."},
    {"key": "online_alternative", "label": "Online participation alternative", "applies": "physical",
     "pos": r"\bhybrid\b|\bremote(ly)?\b[^.]{0,30}\b(participat|attend|join)|\blive ?stream\w*|\bonline option\b|\bvirtual (attendance|participation)",
     "neg": r"\bin[- ]person only\b|\bno (online|remote|virtual)\b",
     "q": "Is there an online or remote participation option for people who cannot attend in person?", "fix": "State whether remote participation is possible and how."},
    {"key": "captioning_interpretation", "label": "Captioning or sign-language interpretation", "applies": "any",
     "pos": r"\bcaptions?\b|\bcaptioning\b|\bsign language\b|\binterpret(er|ation)\b|\bsubtitles?\b|\btranscripts?\b",
     "neg": r"\bno (captions?|captioning|sign language|interpret\w*)\b",
     "q": "Will sessions have live captions or sign-language interpretation, and how do I request them?", "fix": "State which sessions have captions or interpretation and how to request them."},
    {"key": "accessible_materials", "label": "Accessible learning materials", "applies": "any",
     "pos": r"\baccessible (materials?|slides?|documents?|formats?)\b|\bscreen[- ]reader\b|\blarge[- ]print\b|\bbraille\b|\bslides? (will be )?(shared|available) in advance",
     "neg": None,
     "q": "Will slides and materials be shared in advance and be compatible with screen readers?", "fix": "Commit to sharing materials in advance in accessible formats."},
    {"key": "accommodation_request", "label": "How to request accommodations", "applies": "any",
     "pos": r"\b(request|ask for)\b[^.]{0,30}\b(accommodations?|adjustments?|assistance|support)\b|\baccess(ibility)? (needs|requirements|requests)\b|\bspecial (needs|requirements)\b",
     "neg": None,
     "q": "How and by when can I request accommodations or adjustments?", "fix": "Publish a request process and a response-time commitment."},
    {"key": "dietary_info", "label": "Dietary information", "applies": "any",
     "pos": r"\b(vegetarian|vegan|halal|jain|gluten[- ]free|allerg\w+|dietary)\b",
     "neg": None,
     "q": "Are vegetarian, vegan or allergen-aware options available, and how do I state requirements?", "fix": "List dietary options and how to declare requirements."},
    {"key": "emergency_assistance", "label": "Emergency and assistance arrangements", "applies": "physical",
     "pos": r"\bfirst[- ]aid\b|\bmedical (support|assistance|team|room)\b|\bemergency (exit|contact|plan|services?)\b|\bhelpdesk\b|\bhelp desk\b",
     "neg": None,
     "q": "What first-aid and emergency arrangements are in place at the venue?", "fix": "State first-aid, emergency contacts and evacuation assistance."},
    {"key": "accessibility_contact", "label": "Accessibility contact", "applies": "any",
     "pos": r"\baccessibility (contact|officer|coordinator|team|desk)\b|\bcontact\b[^.]{0,40}\b(accessibility|accommodation|access needs)\b",
     "neg": None,
     "q": "Who is the named contact for accessibility questions?", "fix": "Name an accessibility contact with email or phone."},
]
BY_KEY = {i["key"]: i for i in ITEMS}


def detect_accessibility(text: str) -> dict[str, dict[str, Any]]:
    """Only reports what the text actually says. Returns {item_key: {state, excerpt}}."""
    found: dict[str, dict[str, Any]] = {}
    sentences = split_sentences(text) or [text]
    for item in ITEMS:
        pos = re.compile(item["pos"], re.I) if item["pos"] else None
        neg = re.compile(item["neg"], re.I) if item["neg"] else None
        pos_hit = neg_hit = None
        for s in sentences:
            if neg and neg.search(s):
                neg_hit = neg_hit or s
            elif pos and pos.search(s):
                pos_hit = pos_hit or s
        if pos_hit and neg_hit:
            found[item["key"]] = {"state": AccessState.CONFLICTING.value, "excerpt": f"{pos_hit[:200]} | {neg_hit[:200]}"}
        elif neg_hit:
            found[item["key"]] = {"state": AccessState.CONFIRMED_UNAVAILABLE.value, "excerpt": neg_hit[:300]}
        elif pos_hit:
            found[item["key"]] = {"state": AccessState.DOCUMENTED.value, "excerpt": pos_hit[:300]}
    return found


def persist_detected(db: Session, event: Event, found: dict[str, dict[str, Any]], *, evidence_url: str | None = None) -> None:
    """Store detections without ever overwriting an organizer- or manually-entered row."""
    for key, f in found.items():
        row = db.scalar(select(AccessibilityItem).where(AccessibilityItem.event_id == event.id, AccessibilityItem.item_key == key))
        if row is None:
            db.add(AccessibilityItem(event_id=event.id, item_key=key, state=f["state"], detail=None, evidence_excerpt=f["excerpt"],
                                     evidence_url=evidence_url, origin="derived"))
        elif row.origin in ("derived", "source") and row.state != f["state"]:
            row.state, row.evidence_excerpt, row.evidence_url = f["state"], f["excerpt"], evidence_url or row.evidence_url
    db.flush()


def applicable_items(fmt: str | None) -> list[dict[str, Any]]:
    if fmt == "online":
        return [i for i in ITEMS if i["applies"] == "any"]
    return list(ITEMS)  # offline, hybrid and unknown: show everything rather than assume


def accessibility_panel(db: Session, event: Event) -> dict[str, Any]:
    rows = {r.item_key: r for r in db.scalars(select(AccessibilityItem).where(AccessibilityItem.event_id == event.id))}
    items = []
    for spec in applicable_items(event.format):
        r = rows.get(spec["key"])
        state = r.state if r else AccessState.NOT_DOCUMENTED.value
        items.append({
            "key": spec["key"], "label": spec["label"], "state": state,
            "detail": r.detail if r else None, "evidence_excerpt": r.evidence_excerpt if r else None,
            "evidence_url": r.evidence_url if r else None, "origin": r.origin if r else None,
            "updated_at": r.updated_at.isoformat() if r else None,
            "student_question": spec["q"] if state != AccessState.DOCUMENTED.value else None,
            "organizer_fix": spec["fix"] if state != AccessState.DOCUMENTED.value else None,
        })
    documented = sum(1 for i in items if i["state"] == AccessState.DOCUMENTED.value)
    resolved = sum(1 for i in items if i["state"] in (AccessState.DOCUMENTED.value, AccessState.CONFIRMED_UNAVAILABLE.value))
    open_items = [i for i in items if i["state"] not in (AccessState.DOCUMENTED.value, AccessState.CONFIRMED_UNAVAILABLE.value)]
    return {
        "items": items,
        "documented_count": documented,
        "answered_count": resolved,
        "total_count": len(items),
        "completeness_note": f"{documented} of {len(items)} items documented. Items marked 'not documented' are unknown, not unavailable.",
        "student_questions": [i["student_question"] for i in open_items if i["student_question"]],
        "organizer_checklist": [{"item": i["label"], "state": i["state"], "suggested_fix": i["organizer_fix"]} for i in open_items],
    }

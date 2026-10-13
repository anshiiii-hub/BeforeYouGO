"""Deterministic claim extraction: the always-available fallback and the numeric parser.

Wording-based and intentionally conservative: it only reports sentences that contain
recognisable promise language, quotes them verbatim, and never judges honesty.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.domain.enums import ClaimCategory as C
from app.domain.enums import ClaimType as T
from app.services.analyzer.injection import looks_like_instruction

# ----------------------------------------------------------------- numbers (code, never the model)

_SCALE = {"k": 1_000, "thousand": 1_000, "lakh": 100_000, "lakhs": 100_000, "lac": 100_000, "lacs": 100_000,
          "crore": 10_000_000, "crores": 10_000_000, "cr": 10_000_000, "m": 1_000_000, "million": 1_000_000}
_MONEY = re.compile(
    r"(?P<cur>₹|rs\.?|inr|\$|usd|€|eur|£|gbp)\s?(?P<num>\d[\d,]*(?:\.\d+)?)\s?(?P<scale>lakhs?|lacs?|crores?|cr|thousand|k|m|million)?\b"
    r"|(?P<num2>\d[\d,]*(?:\.\d+)?)\s?(?P<scale2>lakhs?|lacs?|crores?|thousand|k)?\s?(?P<cur2>rupees|inr|usd|dollars)\b",
    re.I,
)
_CUR = {"₹": "INR", "rs": "INR", "rs.": "INR", "inr": "INR", "rupees": "INR", "$": "USD", "usd": "USD", "dollars": "USD",
        "€": "EUR", "eur": "EUR", "£": "GBP", "gbp": "GBP"}
_WORDNUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
            "twelve": 12, "fourteen": 14, "fifteen": 15, "thirty": 30}
_NUM = r"(?:\d{1,3}|" + "|".join(_WORDNUM) + ")"
_DURATION = re.compile(rf"\b({_NUM})\s?[- ]?(hours?|hrs?|days?|weeks?|months?)\b", re.I)
_TOPN = re.compile(r"\b(top|first)\s(\d{1,3})\b", re.I)
_DATE = re.compile(
    r"\b(\d{1,2}(?:st|nd|rd|th)?\s(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?(?:,?\s20\d\d)?"
    r"|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s\d{1,2}(?:st|nd|rd|th)?(?:,?\s20\d\d)?"
    r"|\d{1,2}[/-]\d{1,2}[/-](?:20)?\d\d)\b",
    re.I,
)


def extract_numbers(text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in _MONEY.finditer(text):
        raw_num = m.group("num") or m.group("num2")
        scale = (m.group("scale") or m.group("scale2") or "").lower()
        cur = (m.group("cur") or m.group("cur2") or "").lower()
        try:
            value = float(raw_num.replace(",", ""))
        except ValueError:
            continue
        value *= _SCALE.get(scale, 1)
        out.append({"kind": "amount", "value": int(value) if value == int(value) else value,
                    "currency": _CUR.get(cur, cur.upper()), "text": m.group(0).strip()})
    for m in _DURATION.finditer(text):
        num = m.group(1).lower()
        out.append({"kind": "duration", "value": _WORDNUM.get(num) or int(num), "unit": m.group(2).lower().rstrip("s"), "text": m.group(0)})
    for m in _TOPN.finditer(text):
        out.append({"kind": "count", "value": int(m.group(2)), "unit": "top", "text": m.group(0)})
    for m in _DATE.finditer(text):
        out.append({"kind": "date_text", "value": m.group(0), "text": m.group(0)})
    return out


# ----------------------------------------------------------------- classification

_RULES: list[tuple[C, re.Pattern[str]]] = [
    (C.REFUND, re.compile(r"\brefund|cancellation (policy|charges)|non-refundable", re.I)),
    (C.RESULTS_TIMELINE, re.compile(r"\b(results?|winners?|shortlist\w*|selected (teams|candidates))\b[^.]{0,40}\b(announce|declare|publish|notif|shared|revealed)|\bwithin \d+\s?(days?|weeks?|hours?)\b[^.]{0,30}\b(result|announce|notif)", re.I)),
    (C.PRIZE, re.compile(r"\bprize|prizes|cash\s?(award|prize|reward)|prize pool|worth\s?(₹|rs|inr|\$)|\bwinners?\b[^.]{0,40}\b(receive|get|win|earn|awarded)|\bstipend\b|\bgrants?\b", re.I)),
    (C.CERTIFICATE, re.compile(r"\bcertificat\w*|\bcertification\b", re.I)),
    (C.CAREER, re.compile(r"\binternships?\b|\bjob (offers?|opportunit\w*)|\bplacements?\b|\bPPO\b|\bhiring\b|\bcareer opportunit\w*|\bfast-?track\w* interview", re.I)),
    (C.MENTORSHIP, re.compile(r"\bmentor\w*|\bindustry (experts?|leaders?|professionals?)\b|\bexpert (guidance|session|panel)|\bguest (speakers?|lectures?)|\bspeakers?\b", re.I)),
    (C.RECORDINGS, re.compile(r"\brecordings?\b|\blifetime access\b|\bsession (videos?|materials)\b|\bslides\b|\bstudy materials?\b", re.I)),
    (C.TRAVEL_STAY, re.compile(r"\baccommodation\b|\btravel (reimbursement|allowance|support)|\blodging\b|\bhostel\b|\bstay (is |will be )?(provided|arranged)", re.I)),
    (C.FOOD, re.compile(r"\bmeals?\b|\bfood (and|&)? ?(beverages?|drinks)?\b|\blunch\b|\bdinner\b|\bbreakfast\b|\brefreshments?\b|\bsnacks?\b", re.I)),
    (C.SCHOLARSHIP, re.compile(r"\bscholarships?\b|\bdiscounts?\b|\bfee waiver\b|\bconcession\b|\bearly[- ]bird\b", re.I)),
    (C.ACCESSIBILITY, re.compile(r"\bwheelchair\b|\bstep[- ]free\b|\bramps?\b|\baccessible (toilet|washroom|venue|entrance)|\bsign language\b|\bcaptions?\b|\bcaptioning\b|\binterpret(er|ation)\b", re.I)),
    (C.PERKS, re.compile(r"\bswag\b|\bgoodies\b|\bmerch(andise)?\b|\bt-?shirts?\b|\bgoodie bags?\b|\bcloud credits?\b|\bvouchers?\b|\bsubscriptions?\b|\bhampers?\b", re.I)),
    (C.NETWORKING, re.compile(r"\bnetwork(ing)?\b|\bmeet (and|&) connect\b|\bconnect with (peers|developers|professionals|industry)|\bcommunity of\b", re.I)),
    (C.FEE, re.compile(r"\bfree (of charge|entry|registration|to attend|for (all|students))|\bno (registration|entry) fee\b|\b(registration|entry|participation) fees?\b|\bticket price\b|\bfees? (is|are)\b", re.I)),
    (C.TRAINING, re.compile(r"\bhands-?on\b|\bbootcamp\b|\bmasterclass\b|\bworkshops?\b|\btraining (session|program)|\blive (session|demo|coding)", re.I)),
    (C.LEARNING_OUTCOME, re.compile(r"\byou (will|'ll) (learn|build|gain|master|walk away|leave)|\bgain (practical |real[- ]world |hands-on )?(skills?|experience|knowledge|exposure)\b|\blearn (how|to)\b|\bupskill\b|\bbuild (a |your )?(real|project|portfolio)", re.I)),
]

_CONDITIONAL = re.compile(r"\b(if|subject to|provided|eligible|only for|top \d+|first \d+|selected|shortlisted|based on|terms and conditions|t&c|on successful|upon completion|at (the )?discretion|minimum \d+% attendance|conditions apply)\b", re.I)
_VAGUE = re.compile(r"\b(shortly|soon|attractive|exciting|exclusive|amazing|lucrative|exposure|opportunit(y|ies)|industry (experts?|leaders?|professionals?)|top[- ]notch|several|many|various|numerous|best[- ]in|world[- ]class|great|surprise|goodies|and more|etc\.?|handsome|huge|big)\b", re.I)
_PROPER = re.compile(r"(?<![.!?]\s)(?<!^)\b[A-Z][a-zA-Z]{2,}(?:\s[A-Z][a-zA-Z]{2,})+")  # e.g. "Google Cloud"

# What a student needs to know per category when the sentence does not say.
CATEGORY_TEMPLATES: dict[C, dict[str, Any]] = {
    C.PRIZE: {"details": [("amount", "Exact prize amounts per position"), ("timeline", "Payment deadline"), ("conditions", "Eligibility conditions for receiving prizes")],
              "questions": {"timeline": "What is the expected payment date, and what conditions must winners satisfy?",
                            "amount": "What is the exact prize amount for each position, and is it before or after tax deductions?"}},
    C.CERTIFICATE: {"details": [("conditions", "Who qualifies (all registrants, attendees, or winners)"), ("format", "Certificate format and issuing date")],
                    "questions": {"conditions": "Who receives a certificate, what attendance or completion is required, and when will it be issued?"}},
    C.MENTORSHIP: {"details": [("names", "Names or organisations of the mentors/speakers"), ("format", "Session format, length and number of sessions")],
                   "questions": {"names": "Who are the mentors or speakers, and how many sessions will each team or participant get?"}},
    C.CAREER: {"details": [("conditions", "Selection criteria and the number of opportunities"), ("names", "Which companies are offering them"), ("terms", "Duration, stipend and location")],
               "questions": {"conditions": "Which companies offer these opportunities, how many, and how are candidates selected?"}},
    C.TRAINING: {"details": [("topics", "Specific topics and syllabus"), ("duration", "Duration of hands-on time")],
                 "questions": {"topics": "What exact topics will be covered, for how many hours, and what tools or prerequisites are needed?"}},
    C.RECORDINGS: {"details": [("duration", "How long access lasts and where it is hosted"), ("scope", "Which sessions are recorded")],
                   "questions": {"duration": "Which sessions will be recorded, where, and for how long will access last?"}},
    C.RESULTS_TIMELINE: {"details": [("date", "A concrete date for results")],
                         "questions": {"date": "On what date will results be announced and through which channel?"}},
    C.NETWORKING: {"details": [("format", "How networking is structured and who attends")],
                   "questions": {"format": "Who will be present, and is networking structured or informal?"}},
    C.PERKS: {"details": [("items", "Exact items and who receives them")],
              "questions": {"items": "Which items are included and who qualifies to receive them?"}},
    C.TRAVEL_STAY: {"details": [("scope", "What is covered, for whom, and any caps"), ("process", "Reimbursement process and timeline")],
                    "questions": {"scope": "Who is eligible for travel or accommodation support, what is covered, and how is it claimed?"}},
    C.FOOD: {"details": [("scope", "Which meals and dietary options")],
             "questions": {"scope": "Which meals are covered, and are vegetarian, vegan or allergen-aware options available?"}},
    C.LEARNING_OUTCOME: {"details": [("outcomes", "Measurable outcomes or deliverables")],
                         "questions": {"outcomes": "What specific skills or deliverables will participants have at the end, and how is that assessed?"}},
    C.FEE: {"details": [("amount", "Exact fee and what it includes")],
            "questions": {"amount": "What is the total cost to attend, including any additional charges?"}},
    C.REFUND: {"details": [("terms", "Refund conditions and deadlines")],
               "questions": {"terms": "Under what conditions, and until when, can I get a refund?"}},
    C.SCHOLARSHIP: {"details": [("criteria", "Eligibility criteria and how to apply")],
                    "questions": {"criteria": "Who qualifies for the discount or scholarship and how do I apply?"}},
    C.ACCESSIBILITY: {"details": [("scope", "Which sessions and areas it covers"), ("how", "How to request it")],
                      "questions": {"scope": "Which parts of the event does this cover and how can attendees request it?"}},
    C.OTHER: {"details": [], "questions": {}},
}

_TIMELINE_WORDS = re.compile(rf"\bwithin\s+{_NUM}\b|\bby\s+(the\s+)?(\d{1,2}(st|nd|rd|th)?\s)?(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)|\bon\s+\d{1,2}", re.I)


@dataclass
class DraftClaim:
    original_text: str
    normalized_text: str
    category: C
    claim_type: T
    confidence: float
    conditions: list[str] = field(default_factory=list)
    numeric_values: list[dict[str, Any]] = field(default_factory=list)
    missing_details: list[str] = field(default_factory=list)
    verification_questions: list[str] = field(default_factory=list)
    responsible_party: str | None = None
    method: str = "deterministic"


def split_sentences(text: str) -> list[str]:
    parts: list[str] = []
    for line in re.split(r"[\r\n]+", text):
        line = line.strip(" \t•*-–—▪●✓✔►→#>")
        if not line:
            continue
        for sent in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9₹])", line):
            sent = sent.strip()
            if 12 <= len(sent) <= 500:
                parts.append(sent)
    return parts


def classify_type(sentence: str, numbers: list[dict[str, Any]], category: C) -> T:
    if _CONDITIONAL.search(sentence):
        return T.CONDITIONAL
    has_specific = bool(numbers) or bool(_PROPER.search(sentence))
    if _VAGUE.search(sentence) and not (numbers and category in (C.PRIZE, C.FEE)):
        return T.VAGUE
    if has_specific:
        return T.SPECIFIC
    if category in (C.FEE, C.REFUND, C.ACCESSIBILITY) and re.search(r"\b(free|no fee|wheelchair|ramp|captions?)\b", sentence, re.I):
        return T.SPECIFIC
    return T.VAGUE


def missing_for(category: C, sentence: str, numbers: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    tpl = CATEGORY_TEMPLATES[category]
    missing: list[str] = []
    asks: list[str] = []
    has_amount = any(n["kind"] == "amount" for n in numbers)
    has_timeline = bool(_TIMELINE_WORDS.search(sentence)) or any(n["kind"] in ("duration", "date_text") for n in numbers)
    has_conditions = bool(_CONDITIONAL.search(sentence))
    for key, label in tpl["details"]:
        if key == "amount" and has_amount:
            continue
        if key == "timeline" and has_timeline:
            continue
        if key == "conditions" and has_conditions:
            continue
        if key == "date" and has_timeline:
            continue
        if key == "duration" and any(n["kind"] == "duration" for n in numbers):
            continue
        if key == "names" and _PROPER.search(sentence):
            continue
        missing.append(label)
        q = tpl["questions"].get(key)
        if q and q not in asks:
            asks.append(q)
    return missing, asks


def normalize_sentence(sentence: str, category: C) -> str:
    s = re.sub(r"\s+", " ", sentence).strip(" .!")
    return f"The organizer advertises: {s[0].lower() + s[1:] if s else s}."


def extract_claims_deterministic(text: str, max_claims: int = 40) -> list[DraftClaim]:
    claims: list[DraftClaim] = []
    seen: set[str] = set()
    for sent in split_sentences(text):
        if looks_like_instruction(sent):
            continue
        category = None
        for cat, pat in _RULES:
            if pat.search(sent):
                category = cat
                break
        if category is None:
            continue
        key = re.sub(r"\W+", " ", sent.lower()).strip()
        if key in seen:
            continue
        seen.add(key)
        numbers = extract_numbers(sent)
        ctype = classify_type(sent, numbers, category)
        missing, asks = missing_for(category, sent, numbers)
        conds = [m.group(0) for m in _CONDITIONAL.finditer(sent)][:5]
        conf = 0.7 if ctype in (T.SPECIFIC, T.CONDITIONAL) else 0.6
        claims.append(
            DraftClaim(
                original_text=sent,
                normalized_text=normalize_sentence(sent, category),
                category=category,
                claim_type=ctype,
                confidence=conf,
                conditions=conds,
                numeric_values=numbers,
                missing_details=missing,
                verification_questions=asks,
            )
        )
        if len(claims) >= max_claims:
            break
    return claims

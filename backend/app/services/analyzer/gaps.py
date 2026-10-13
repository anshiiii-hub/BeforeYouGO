"""Deterministic information-gap rules.

Each rule inspects structured event fields plus the available text. A finding means
"this was not stated in the sources we hold", never "this is absent from reality"; every
finding says so in ``scope_note``. Severity is computed by a stated rule so users can see why.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.services.analyzer.deterministic import split_sentences


@dataclass
class GapContext:
    event: dict[str, Any]
    corpus: str
    claims: list[dict[str, Any]] = field(default_factory=list)
    accessibility_documented: int = 0
    today: date = field(default_factory=date.today)
    source_label: str = "the retrieved sources"

    @property
    def days_to_start(self) -> int | None:
        s = self.event.get("start_date")
        return (s - self.today).days if isinstance(s, date) else None

    @property
    def category(self) -> str:
        return str(self.event.get("category") or "other")

    @property
    def is_offline(self) -> bool:
        return self.event.get("format") in ("offline", "hybrid")

    @property
    def duration_days(self) -> int | None:
        s, e = self.event.get("start_date"), self.event.get("end_date")
        return (e - s).days + 1 if isinstance(s, date) and isinstance(e, date) else None

    def mentions(self, pattern: str) -> str | None:
        """Return the first sentence matching the pattern (the evidence), or None."""
        rx = re.compile(pattern, re.I)
        for s in split_sentences(self.corpus):
            if rx.search(s):
                return s
        m = rx.search(self.corpus)
        if m:
            a = max(0, m.start() - 60)
            return self.corpus[a : m.end() + 60].replace("\n", " ").strip()
        return None

    def has(self, pattern: str) -> bool:
        return bool(re.search(pattern, self.corpus, re.I))


@dataclass
class GapResult:
    rule_id: str
    gap: str
    why_it_matters: str
    severity: str
    severity_rule: str
    student_question: str
    organizer_fix: str
    source_text: str | None = None
    scope_note: str = ""


Rule = Callable[[GapContext], GapResult | None]
RULES: list[Rule] = []


def rule(fn: Rule) -> Rule:
    RULES.append(fn)
    return fn


def _scope(ctx: GapContext) -> str:
    return f"Not stated in {ctx.source_label}. The organizer may publish this elsewhere; absence here is not evidence that it does not exist."


def _sev(ctx: GapContext, *, base: str, urgent: bool = False, bump_if: bool = False) -> tuple[str, str]:
    """Transparent severity: base level, raised one step when the event is <=14 days away or the stated condition holds."""
    order = ["low", "medium", "high"]
    idx = order.index(base)
    reasons = [f"Base severity '{base}' for this kind of gap."]
    soon = ctx.days_to_start is not None and 0 <= ctx.days_to_start <= 14
    if (urgent and soon) or bump_if:
        idx = min(2, idx + 1)
        reasons.append("Raised one level because " + ("the event starts within 14 days." if (urgent and soon) else "money or eligibility depends on it."))
    return order[idx], " ".join(reasons)


@rule
def r01_deadline(ctx: GapContext) -> GapResult | None:
    if ctx.event.get("registration_deadline") or ctx.has(r"\b(register|registration|apply|applications?)\b[^.\n]{0,40}\b(by|before|until|closes?|deadline|last date)\b|\bdeadline\b|\blast date\b"):
        return None
    sev, why = _sev(ctx, base="medium", urgent=True)
    return GapResult("R01", "Registration deadline not stated", "Without a deadline you cannot plan or know whether registration is still open.", sev, why,
                     "Until what date and time (and time zone) can I register?", "State the registration deadline with date, time and time zone, and say whether it can be extended.", None, _scope(ctx))


@rule
def r02_eligibility(ctx: GapContext) -> GapResult | None:
    if ctx.event.get("eligibility") or ctx.has(r"\beligib\w*|\bopen to\b|\bwho can (apply|participate|attend)\b|\b(undergraduate|postgraduate|b\.?tech|students? (of|from|in)|year students?|open for all|anyone can)\b"):
        return None
    sev, why = _sev(ctx, base="medium", bump_if=ctx.category in ("hackathon", "competition", "internship"))
    return GapResult("R02", "Eligibility requirements not stated", "You could invest time and be disqualified later (year of study, branch, college, age, team rules).", sev, why,
                     "Who is eligible (year of study, branch, institution type, location)?", "List eligibility rules explicitly, including any exclusions.", None, _scope(ctx))


@rule
def r03_prerequisites(ctx: GapContext) -> GapResult | None:
    if ctx.category not in ("workshop", "hackathon", "competition", "other") or ctx.event.get("prerequisites"):
        return None
    if ctx.has(r"\bprerequisites?\b|\bbeginner\w*\b|\bno (prior )?(experience|knowledge)\b|\bbring (your )?laptop|\brequired (skills?|knowledge)\b|\bshould (know|have)\b"):
        return None
    sev, why = _sev(ctx, base="low")
    return GapResult("R03", "Prerequisites and required skill level not stated", "You cannot tell whether the event suits a beginner or expects prior skills and equipment.", sev, why,
                     "What skills, tools or equipment (e.g. laptop, accounts) should I have beforehand?", "State the expected skill level and anything participants must bring or install.", None, _scope(ctx))


@rule
def r04_fee(ctx: GapContext) -> GapResult | None:
    if ctx.event.get("fee_status") in ("free", "paid"):
        return None
    if ctx.has(r"\bfree (of charge|entry|registration|to attend|for)\b|\bno (registration|entry) fee\b|(₹|rs\.?|inr|\$)\s?\d"):
        return None
    mention = ctx.mentions(r"\b(registration|entry|participation|ticket)\s(fee|price|charges?)\b")
    sev, why = _sev(ctx, base="high" if mention else "medium", bump_if=False)
    return GapResult("R04", "Registration fee unclear", "Unknown cost is not the same as free. You may only find out the price at checkout.", sev,
                     why + (" High because a fee is mentioned without an amount." if mention else ""),
                     "Is there a registration fee? If so, how much and what does it include?", "State the fee (or explicitly 'free') and what it covers.", mention, _scope(ctx))


@rule
def r05_other_costs(ctx: GapContext) -> GapResult | None:
    if not ctx.is_offline or ctx.event.get("other_costs") or ctx.has(r"\btravel\b|\baccommodation\b|\bmeals?\b|\bfood\b|\bmaterials?\b|\bno other costs\b|\bat your own (cost|expense)"):
        return None
    sev, why = _sev(ctx, base="low", bump_if=ctx.event.get("fee_status") == "unknown")
    return GapResult("R05", "Travel, stay, food and material costs not addressed", "For an in-person event, these often exceed the registration fee.", sev, why,
                     "Which costs (travel, stay, food, materials) must participants cover themselves?", "State what is provided and what attendees pay for separately.", None, _scope(ctx))


@rule
def r06_team_size(ctx: GapContext) -> GapResult | None:
    if ctx.category not in ("hackathon", "competition") or ctx.event.get("team_size_max") or ctx.event.get("team_size_min"):
        return None
    if ctx.has(r"\bteam(s)?\b[^.\n]{0,40}\b(of|up to|size|members?|max|min)\b|\b(solo|individual)\b|\b\d\s?(-|to)\s?\d\s?(members|people|participants)"):
        return None
    sev, why = _sev(ctx, base="low")
    return GapResult("R06", "Team-size rules not stated", "You cannot tell whether you may enter alone, and whether teams from different colleges are allowed.", sev, why,
                     "What are the minimum and maximum team sizes, and may team members come from different colleges?", "State team size limits, solo participation and cross-college rules.", None, _scope(ctx))


@rule
def r07_schedule(ctx: GapContext) -> GapResult | None:
    if ctx.event.get("schedule_text") or ctx.has(r"\bschedule\b|\bagenda\b|\bitinerary\b|\bday\s?[1-3]\b|\b\d{1,2}(:\d\d)?\s?(am|pm)\b|\bkeynote\b|\bsession\s?\d"):
        return None
    sev, why = _sev(ctx, base="medium" if (ctx.duration_days or 1) > 1 else "low", urgent=True)
    return GapResult("R07", "No schedule or agenda available", "Without session times you cannot plan travel, sleep or classes around the event.", sev, why,
                     "Is there a day-by-day schedule, including start and end times?", "Publish an agenda with times, even if provisional (mark it provisional).", None, _scope(ctx))


@rule
def r08_prize_timeline(ctx: GapContext) -> GapResult | None:
    prize_claims = [c for c in ctx.claims if c.get("category") == "prize"]
    prize_text = ctx.event.get("prize_details") or (prize_claims[0]["original_text"] if prize_claims else None)
    if not prize_text:
        return None
    if re.search(r"\bwithin\s+(\d+|one|two|three|four|five|six|seven|eight|nine|ten|fourteen|fifteen|thirty)\s?(working |business )?(days?|weeks?)\b|\bby\s+\d{1,2}\s?(st|nd|rd|th)?\s?(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)", str(prize_text) + " " + ctx.corpus, re.I):
        return None
    sev, why = _sev(ctx, base="medium", bump_if=True)
    return GapResult("R08", "Prize payment timeline and conditions not stated", "Prize money promised without a payment date or conditions cannot be held to account later.", sev, why,
                     "When will prizes be paid, how (bank transfer, voucher), and what must winners provide or satisfy?",
                     "State the payment deadline, method, taxes/deductions and winner conditions.", str(prize_text)[:300], _scope(ctx))


@rule
def r09_certificate(ctx: GapContext) -> GapResult | None:
    sent = ctx.mentions(r"\bcertificat\w*")
    if not sent and not ctx.event.get("offers_certificate"):
        return None
    text = sent or ""
    if re.search(r"\ball (participants|attendees|registrants)\b|\bwinners? only\b|\bon (completion|attendance)\b|\bminimum\b|\b\d+%\b|\bissued (within|by|on)\b", text, re.I):
        return None
    sev, why = _sev(ctx, base="low", bump_if=False)
    return GapResult("R09", "Certificate conditions not stated", "A certificate may be limited to winners or require attendance thresholds.", sev, why,
                     "Who gets a certificate, what is required to earn it, and when is it issued?", "State certificate eligibility, requirements and issue date.", sent, _scope(ctx))


@rule
def r10_judging(ctx: GapContext) -> GapResult | None:
    if ctx.category not in ("hackathon", "competition") or ctx.event.get("judging_criteria"):
        return None
    has_prize = bool(ctx.event.get("prize_details")) or any(c.get("category") == "prize" for c in ctx.claims)
    if ctx.has(r"\bjudging\b|\bevaluation criteria\b|\bcriteria\b|\bjudged (on|by)\b|\brubric\b|\bscor(ed|ing)\b"):
        return None
    sev, why = _sev(ctx, base="medium" if has_prize else "low")
    return GapResult("R10", "Judging criteria not stated", "You cannot tell what to optimise for or how fairly winners will be chosen.", sev, why,
                     "What are the judging criteria and weights, and who are the judges?", "Publish judging criteria with weights, and name the judging panel.", None, _scope(ctx))


@rule
def r11_credentials(ctx: GapContext) -> GapResult | None:
    sent = ctx.mentions(r"\bmentor\w*|\bindustry (experts?|leaders?|professionals?)\b|\bexperts?\b|\bguest speakers?\b|\bspeakers?\b")
    if not sent or ctx.event.get("offers_mentorship") is False:
        return None
    if re.search(r"\b[A-Z][a-z]+\s[A-Z][a-z]+\b[^.]*\b(at|from|of)\s[A-Z]|\b(google|microsoft|amazon|meta|adobe|nvidia|aws|ibm|intel)\b", sent):
        return None
    sev, why = _sev(ctx, base="low")
    return GapResult("R11", "Mentor or speaker credentials not given", "'Industry experts' can mean anything from senior engineers to recruiters.", sev, why,
                     "Who are the mentors/speakers and what are their roles and organisations?", "List mentors and speakers by name, role and organisation.", sent, _scope(ctx))


@rule
def r12_venue(ctx: GapContext) -> GapResult | None:
    if not ctx.is_offline or (ctx.event.get("venue") and ctx.event.get("city")):
        return None
    missing = [n for n, k in (("venue name/address", "venue"), ("city", "city")) if not ctx.event.get(k)]
    sev, why = _sev(ctx, base="medium", urgent=True, bump_if=not ctx.event.get("city"))
    return GapResult("R12", "Venue information incomplete", f"Missing: {', '.join(missing)}. You cannot judge travel time or cost.", sev, why,
                     "What is the full venue address and nearest transport?", "Provide the full venue name, address, map link and directions.", None, _scope(ctx))


@rule
def r13_accommodation(ctx: GapContext) -> GapResult | None:
    if not ctx.is_offline or (ctx.duration_days or 1) < 2 or ctx.event.get("accommodation_info"):
        return None
    if ctx.has(r"\baccommodation\b|\bstay\b|\blodging\b|\bhostel\b|\bhotel\b|\boffer(s|ed)? (a )?room"):
        return None
    sev, why = _sev(ctx, base="low", bump_if=False)
    return GapResult("R13", "Accommodation not addressed for a multi-day in-person event", "Multi-day events may require an overnight stay you must arrange and pay for.", sev, why,
                     "Is accommodation provided, recommended or entirely my responsibility?", "State whether accommodation is provided, subsidised or must be self-arranged.", None, _scope(ctx))


@rule
def r14_accessibility(ctx: GapContext) -> GapResult | None:
    if ctx.accessibility_documented > 0 or ctx.has(r"\bwheelchair\b|\baccessib\w*|\bstep[- ]free\b|\bcaptions?\b|\bsign language\b"):
        return None
    sev, why = _sev(ctx, base="medium" if ctx.is_offline else "low")
    return GapResult("R14", "No accessibility information documented", "Attendees with access needs cannot judge whether they can take part. This does not mean the venue is inaccessible.", sev, why,
                     "What accessibility arrangements exist (step-free access, accessible toilets, captioning), and who do I contact to request support?",
                     "Add an accessibility statement and a named contact for accommodation requests.", None, _scope(ctx))


@rule
def r15_refund(ctx: GapContext) -> GapResult | None:
    if ctx.event.get("fee_status") != "paid" or ctx.event.get("refund_policy") or ctx.has(r"\brefund|cancellation policy|non-refundable"):
        return None
    sev, why = _sev(ctx, base="medium")
    return GapResult("R15", "Refund and cancellation policy not stated", "If you pay and cannot attend, or the event is cancelled, you do not know what you get back.", sev, why,
                     "What happens to my fee if I cancel, or if the event is postponed or cancelled?", "State the refund policy and what happens if the organizer cancels.", None, _scope(ctx))


@rule
def r16_contact(ctx: GapContext) -> GapResult | None:
    if ctx.event.get("contact_info") or ctx.has(r"[\w.+-]+@[\w-]+\.[\w.]+|\bcontact\b|\bwhatsapp\b|\+?\d[\d\s-]{8,}\d"):
        return None
    sev, why = _sev(ctx, base="medium")
    return GapResult("R16", "No contact details found", "You have no direct way to ask the questions listed here.", sev, why,
                     "Who can I contact (email or phone) with questions before registering?", "Provide a monitored email address or phone number for queries.", None, _scope(ctx))


@rule
def r17_learning_outcomes(ctx: GapContext) -> GapResult | None:
    sent = ctx.mentions(r"\bhands-?on\b|\bgain (practical |real[- ]world )?(skills?|experience|knowledge|exposure)\b|\byou (will|'ll) learn\b|\blearn (how|to)\b|\bupskill\b")
    if not sent:
        return None
    if re.search(r"\b(python|java|docker|kubernetes|tensorflow|pytorch|react|sql|aws|flask|django|llm|transformer|api|git|figma|excel)\b", sent, re.I):
        return None
    sev, why = _sev(ctx, base="low")
    return GapResult("R17", "Learning outcomes are vague", "Phrases such as 'hands-on learning' do not tell you what you will actually be able to do afterwards.", sev, why,
                     "What specific topics, tools and deliverables will I leave with?", "List concrete topics, tools and the project or deliverable participants produce.", sent, _scope(ctx))


@rule
def r18_vague_promises(ctx: GapContext) -> GapResult | None:
    vague = [c for c in ctx.claims if c.get("claim_type") == "vague" and c.get("category") in ("career_opportunity", "prize", "mentorship", "perks_swag")]
    if not vague:
        return None
    first = vague[0]
    cats = sorted({c["category"].replace("_", " ") for c in vague})
    sev, why = _sev(ctx, base="medium" if any(c["category"] in ("career_opportunity", "prize") for c in vague) else "low")
    return GapResult("R18", f"Vague promise(s): {', '.join(cats)}", "Unquantified promises (no amounts, names or dates) cannot be checked afterwards. Vague is not the same as false.", sev, why,
                     "Can you quantify this promise (how many, how much, who, and by when)?", "Replace vague wording with concrete numbers, names and dates.", first["original_text"], _scope(ctx))


def evaluate_gaps(ctx: GapContext) -> list[GapResult]:
    results = [r for rule_fn in RULES if (r := rule_fn(ctx)) is not None]
    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(results, key=lambda g: (order[g.severity], g.rule_id))

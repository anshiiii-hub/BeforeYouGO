"""Promise Analyzer pipeline.

text -> sanitise -> injection scan -> (LLM claims | deterministic claims) -> validation ->
numbers computed in code -> deterministic gap rules -> accessibility scan -> persist.

Provenance labels returned with every item:
  ai_interpretation | deterministic_rule | source_field. None of them is verification.
"""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.domain.enums import AnalysisInput, ClaimCategory, ExtractionMethod
from app.models import AnalysisRun, Claim, Event, GapFinding, User
from app.models.base import utcnow
from app.services.accessibility import detect_accessibility, persist_detected
from app.services.analyzer.deterministic import (
    DraftClaim,
    classify_type,
    extract_claims_deterministic,
    extract_numbers,
    missing_for,
)
from app.services.analyzer.gaps import GapContext, GapResult, evaluate_gaps
from app.services.analyzer.injection import detect_injection, looks_like_instruction, sanitize_text
from app.services.analyzer.llm import LLMError, extract_claims_llm, resolve_llm
from app.services.claims import create_claim
from app.services.taxonomy import classify_category

logger = logging.getLogger("byg.analyzer")

EVENT_TEXT_FIELDS = (
    "title", "description", "eligibility", "prerequisites", "prize_details", "schedule_text", "judging_criteria",
    "refund_policy", "other_costs", "accommodation_info", "contact_info", "time_commitment",
)


def event_corpus(event: Event) -> str:
    parts = [getattr(event, f) for f in EVENT_TEXT_FIELDS if getattr(event, f)]
    return "\n".join(str(p) for p in parts)


def _ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().casefold()


def facts_from_text(text: str) -> dict[str, Any]:
    """Minimal structured facts for ad-hoc text so gap rules have context. Unknown stays unknown."""
    facts: dict[str, Any] = {"category": classify_category(text[:300], text[:2000]), "fee_status": "unknown", "format": "unknown"}
    if re.search(r"\bfree (of charge|entry|registration|to attend|for)\b|\bno (registration|entry) fee\b", text, re.I):
        facts["fee_status"] = "free"
    elif re.search(r"\b(registration|entry|participation|ticket)\s(fee|price|charges?)\b[^.\n]{0,30}(₹|rs\.?|inr|\$)\s?\d|(₹|rs\.?|inr)\s?\d[\d,]*\s?(per (person|team|head)|/-)", text, re.I):
        facts["fee_status"] = "paid"
    has_online = re.search(r"\bonline\b|\bvirtual\b|\bzoom\b|\bgoogle meet\b", text, re.I)
    has_offline = re.search(r"\bvenue\b|\boffline\b|\bin[- ]person\b|\bon[- ]campus\b|\bcampus\b", text, re.I)
    if has_online and has_offline:
        facts["format"] = "hybrid"
    elif has_online:
        facts["format"] = "online"
    elif has_offline:
        facts["format"] = "offline"
    return facts


def _validate_llm_claims(raw_claims: list[Any], source_text: str) -> tuple[list[DraftClaim], int]:
    """Keep only claims that quote the source verbatim and are not instructions. Numbers are recomputed in code."""
    haystack = _ws(source_text)
    kept: list[DraftClaim] = []
    dropped = 0
    seen: set[str] = set()
    for c in raw_claims:
        quote = c.original_text.strip()
        if _ws(quote) not in haystack or looks_like_instruction(quote) or _ws(quote) in seen:
            dropped += 1
            continue
        seen.add(_ws(quote))
        numbers = extract_numbers(quote)
        cat = ClaimCategory(c.category)
        det_missing, det_asks = missing_for(cat, quote, numbers)
        missing = list(dict.fromkeys([*c.missing_details, *det_missing]))[:10]
        asks = list(dict.fromkeys([*c.verification_questions, *det_asks]))[:6]
        kept.append(
            DraftClaim(
                original_text=quote, normalized_text=c.normalized_text.strip(), category=cat, claim_type=c.claim_type,
                confidence=round(min(c.confidence, 0.95), 2), conditions=c.conditions, numeric_values=numbers,
                missing_details=missing, verification_questions=asks, responsible_party=c.responsible_party, method="llm",
            )
        )
    return kept, dropped


def claim_to_dict(c: DraftClaim) -> dict[str, Any]:
    return {
        "original_text": c.original_text, "normalized_text": c.normalized_text, "category": c.category.value,
        "claim_type": c.claim_type.value, "responsible_party": c.responsible_party, "conditions": c.conditions,
        "numeric_values": c.numeric_values, "missing_details": c.missing_details,
        "verification_questions": c.verification_questions, "extraction_confidence": c.confidence,
        "extraction_method": c.method, "status": "advertised",
        "provenance": "ai_interpretation" if c.method == "llm" else "deterministic_rule",
        "evidence_excerpt": c.original_text,
    }


def gap_to_dict(g: GapResult) -> dict[str, Any]:
    return {
        "rule_id": g.rule_id, "gap": g.gap, "source_text": g.source_text, "why_it_matters": g.why_it_matters,
        "severity": g.severity, "severity_rule": g.severity_rule, "student_question": g.student_question,
        "organizer_fix": g.organizer_fix, "scope_note": g.scope_note, "provenance": "deterministic_rule",
    }


def analyze(
    db: Session,
    *,
    text: str,
    input_type: AnalysisInput,
    event: Event | None = None,
    source_url: str | None = None,
    canonical_url: str | None = None,
    file_name: str | None = None,
    actor: User | None = None,
    use_llm: bool = True,
    persist_claims: bool = True,
    source_label: str | None = None,
    extra_notes: list[str] | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    clean = sanitize_text(text, settings.llm_max_input_chars)
    flags = detect_injection(clean)
    notes = list(extra_notes or [])
    if len(text) > settings.llm_max_input_chars:
        notes.append(f"Input was truncated to {settings.llm_max_input_chars} characters.")
    if flags:
        notes.append("The document contains text that looks like instructions to an AI. It was treated as data and ignored.")

    drafts: list[DraftClaim] = []
    provider, model, used_fallback, llm_error = "deterministic", None, False, None
    cfg = resolve_llm(settings) if use_llm else None
    if cfg is not None:
        try:
            extraction = extract_claims_llm(clean, cfg, settings)
            drafts, dropped = _validate_llm_claims(extraction.claims, clean)
            if extraction.claims and not drafts:
                raise LLMError("Every claim from the model failed source-quote validation.")
            provider, model = cfg.provider, cfg.model
            if dropped:
                notes.append(f"{dropped} model-proposed claim(s) were discarded because they did not quote the source or looked like instructions.")
        except LLMError as exc:
            used_fallback, llm_error = True, str(exc)
            notes.append("The AI service was unavailable or returned unusable output, so rule-based extraction was used instead.")
    elif use_llm:
        notes.append("No AI provider is configured, so rule-based extraction was used. Results may miss unusual wording.")
    if not drafts:
        drafts = extract_claims_deterministic(clean)
        if cfg is not None and not used_fallback:  # LLM legitimately found nothing: do not mask that
            drafts = []
    claim_dicts = [claim_to_dict(d) for d in drafts]

    corpus = event_corpus(event) + "\n" + clean if event is not None else clean
    facts: dict[str, Any]
    if event is not None:
        facts = {f: getattr(event, f) for f in (
            "registration_deadline", "start_date", "end_date", "eligibility", "prerequisites", "fee_status", "fee_amount",
            "format", "venue", "city", "category", "team_size_min", "team_size_max", "schedule_text", "prize_details",
            "judging_criteria", "contact_info", "accommodation_info", "refund_policy", "offers_certificate",
            "offers_mentorship", "other_costs",
        )}
        existing = [
            {"category": c.category, "claim_type": c.claim_type, "original_text": c.original_text}
            for c in db.scalars(select(Claim).where(Claim.event_id == event.id, Claim.is_active.is_(True)))
        ]
        claim_dicts_for_gaps = existing + [c for c in claim_dicts if c["original_text"] not in {e["original_text"] for e in existing}]
    else:
        facts = facts_from_text(clean)
        claim_dicts_for_gaps = claim_dicts

    found_access = detect_accessibility(corpus)
    ctx = GapContext(
        event=facts, corpus=corpus, claims=claim_dicts_for_gaps, today=date.today(),
        accessibility_documented=sum(1 for f in found_access.values() if f["state"] == "documented"),
        source_label=source_label or ("the analyzed text" if event is None else "the stored event record and analyzed text"),
    )
    if event is not None:
        from app.models import AccessibilityItem

        ctx.accessibility_documented = max(
            ctx.accessibility_documented,
            len([1 for r in db.scalars(select(AccessibilityItem).where(AccessibilityItem.event_id == event.id)) if r.state == "documented"]),
        )
    gaps = evaluate_gaps(ctx)
    gap_dicts = [gap_to_dict(g) for g in gaps]
    access_list = [{"item_key": k, **v, "provenance": "deterministic_rule"} for k, v in found_access.items()]

    result = {
        "claims": claim_dicts,
        "gaps": gap_dicts,
        "accessibility_detected": access_list,
        "summary": {
            "claims": len(claim_dicts),
            "vague_claims": sum(1 for c in claim_dicts if c["claim_type"] == "vague"),
            "gaps": len(gap_dicts),
            "high_severity_gaps": sum(1 for g in gap_dicts if g["severity"] == "high"),
        },
        "notes": notes,
        "caveat": "Claims are advertised promises extracted from text. Extraction confidence is not evidence that a promise is true or will be kept.",
    }
    input_hash = hashlib.sha256(clean.encode()).hexdigest()
    run = AnalysisRun(
        event_id=event.id if event else None, input_type=input_type.value, input_hash=input_hash, source_url=source_url,
        canonical_url=canonical_url, source_text=clean, file_name=file_name, provider=provider, model=model,
        used_fallback=used_fallback or cfg is None, status="completed", error=llm_error, injection_flags=flags,
        result=result, created_by=actor.id if actor else None,
    )
    db.add(run)
    db.flush()

    if event is not None and persist_claims:
        created_claims = []
        for d in drafts:
            claim, _ = create_claim(
                db, event, original_text=d.original_text, normalized_text=d.normalized_text, category=d.category.value,
                claim_type=d.claim_type.value, method=ExtractionMethod.LLM if d.method == "llm" else ExtractionMethod.DETERMINISTIC,
                confidence=d.confidence, responsible_party=d.responsible_party, conditions=d.conditions,
                numeric_values=d.numeric_values, missing_details=d.missing_details,
                verification_questions=d.verification_questions, evidence_url=canonical_url or source_url or event.canonical_url,
                evidence_excerpt=d.original_text, analysis_run_id=run.id, actor=actor,
            )
            created_claims.append(claim)
        for c, d in zip(created_claims, claim_dicts, strict=False):
            d["claim_id"] = str(c.id)
        persist_detected(db, event, found_access, evidence_url=canonical_url or source_url)
        _upsert_gaps(db, event, gaps, run.id)
        event.last_updated_at = utcnow()
    result["run_id"] = str(run.id)
    result["analysis"] = {"provider": provider, "model": model, "used_fallback": run.used_fallback, "llm_error": llm_error,
                          "injection_flags": flags, "input_type": input_type.value}
    run.result = result
    return result


def _upsert_gaps(db: Session, event: Event, gaps: list[GapResult], run_id: uuid.UUID) -> None:
    existing: dict[str, GapFinding] = {}
    for g in db.scalars(select(GapFinding).where(GapFinding.event_id == event.id).order_by(GapFinding.detected_at)):
        existing[g.rule_id] = g
    triggered = set()
    for g in gaps:
        triggered.add(g.rule_id)
        row = existing.get(g.rule_id)
        if row is None:
            db.add(GapFinding(
                event_id=event.id, analysis_run_id=run_id, rule_id=g.rule_id, gap=g.gap, source_text=g.source_text,
                why_it_matters=g.why_it_matters, severity=g.severity, severity_rule=g.severity_rule,
                student_question=g.student_question, organizer_fix=g.organizer_fix, scope_note=g.scope_note,
            ))
        else:
            row.analysis_run_id = run_id
            row.gap, row.source_text, row.why_it_matters = g.gap, g.source_text, g.why_it_matters
            row.severity, row.severity_rule = g.severity, g.severity_rule
            row.student_question, row.organizer_fix, row.scope_note = g.student_question, g.organizer_fix, g.scope_note
            if row.status == "resolved":
                row.status, row.resolved_at, row.resolution_note = "open", None, None
    for rule_id, row in existing.items():
        if rule_id not in triggered and row.status == "open":
            row.status = "resolved"
            row.resolved_at = utcnow()
            row.resolution_note = "No longer detected on re-analysis (the information is now present in the record)."
    db.flush()


def reclassify(claim_type_input: str, numbers: list[dict[str, Any]], category: ClaimCategory):
    """Exposed for organizer corrections: recompute type after an edit."""
    return classify_type(claim_type_input, numbers, category)

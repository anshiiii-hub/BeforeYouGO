"""Parse who an event is for. Only reports restrictions the text clearly states."""

from __future__ import annotations

import re
from typing import Any

from app.services.analyzer.deterministic import split_sentences

_YEAR_WORDS = {
    1: r"(first|1st|fresher|freshman)[- ]?(year|yr)s?",
    2: r"(second|2nd|sophomore)[- ]?(year|yr)s?",
    3: r"(third|3rd|pre[- ]?final)[- ]?(year|yr)s?",
    4: r"(fourth|4th|final|last)[- ]?(year|yr)s?",
}
_RANGE = re.compile(r"\b(first|1st|second|2nd|third|3rd|fourth|4th)\s*(?:to|-|–|through)\s*(first|1st|second|2nd|third|3rd|fourth|4th|final)\s*[- ]?(?:year|yr)", re.I)
_ORD = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3, "fourth": 4, "4th": 4, "final": 4}
_SCOPE = re.compile(r"\b(open (to|for)|eligible|eligibility|only (for|to)|restricted to|meant for|for (the )?(students|participants)|who can|must be|should be)\b", re.I)
_OPEN = re.compile(r"\b(open to all|all (students|years|branches)|anyone (can|may)|no restrictions?|open for everyone)\b", re.I)
_LEVELS = {
    "undergraduate": r"\bundergrad\w*|\bb\.?\s?tech\b|\bb\.?\s?e\b|\bbca\b|\bbsc\b|\bbachelor'?s?\b",
    "postgraduate": r"\bpostgrad\w*|\bm\.?\s?tech\b|\bmca\b|\bmba\b|\bmsc\b|\bmaster'?s?\b|\bph\.?d\b",
    "diploma": r"\bdiploma\b|\bpolytechnic\b",
}


def parse_eligibility(text: str | None) -> dict[str, Any]:
    """Return {years, levels, open_to_all, evidence}. Empty lists mean 'no stated restriction found'."""
    out: dict[str, Any] = {"years": [], "levels": [], "open_to_all": False, "evidence": None}
    if not text:
        return out
    years: set[int] = set()
    levels: set[str] = set()
    evidence: list[str] = []
    for sent in split_sentences(text) or [text]:
        if _OPEN.search(sent) and not (_SCOPE.search(sent) and any(re.search(p, sent, re.I) for p in _YEAR_WORDS.values())):
            out["open_to_all"] = True
        if not _SCOPE.search(sent) and len(split_sentences(text)) > 1:
            continue
        hit = False
        m = _RANGE.search(sent)
        if m:
            a, b = _ORD[m.group(1).lower()], _ORD[m.group(2).lower()]
            years.update(range(min(a, b), max(a, b) + 1))
            hit = True
        for y, pat in _YEAR_WORDS.items():
            if re.search(pat, sent, re.I):
                years.add(y)
                hit = True
        for lvl, pat in _LEVELS.items():
            if re.search(pat, sent, re.I):
                levels.add(lvl)
                hit = True
        if hit:
            evidence.append(sent[:250])
    out["years"] = sorted(years)
    out["levels"] = sorted(levels)
    out["evidence"] = " ".join(evidence)[:400] or None
    if years or levels:
        out["open_to_all"] = False
    return out

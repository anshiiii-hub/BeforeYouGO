"""Prompt-injection defence for retrieved pages and uploaded documents.

Source content is untrusted DATA. Defences, in depth:
1. Detect instruction-like text and record flags (shown to the user, stored on the run).
2. Wrap content in explicit delimiters and tell the model it is data only.
3. Never let model output trigger actions: output is schema-validated claims only, every
   claim must quote the source verbatim, and claims that are themselves instructions are dropped.
4. Strip control characters and delimiter look-alikes so the content cannot close the data block.
"""

from __future__ import annotations

import re
import unicodedata

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("override_instructions", re.compile(r"(?i)\b(ignore|disregard|forget|override)\b[^.\n]{0,40}\b(previous|prior|above|earlier|all|any|system)\b[^.\n]{0,30}\b(instruction|prompt|rule|message|context)s?")),
    ("role_reassignment", re.compile(r"(?i)\byou are (now|no longer)\b|\bact as (an?|the)\b|\bpretend (to be|you are)\b|\bfrom now on,? you\b")),
    ("prompt_exfiltration", re.compile(r"(?i)\b(reveal|print|show|repeat|output|leak)\b[^.\n]{0,40}\b(system prompt|instructions|api key|secret|password|credentials)")),
    ("fake_role_marker", re.compile(r"(?im)^\s*(system|assistant|developer)\s*:|<\|?(im_start|im_end|system|assistant)\|?>|\[/?(INST|SYS)\]")),
    ("status_manipulation", re.compile(r"(?i)\b(mark|set|change|update)\b[^.\n]{0,40}\b(claims?|events?|status|score|trust)\b[^.\n]{0,40}\b(fulfilled|verified|corroborated|trusted|approved|100)")),
    ("tool_or_action_request", re.compile(r"(?i)\b(call|invoke|execute|run)\b[^.\n]{0,30}\b(tool|function|command|script|sql|shell)\b")),
    ("delimiter_spoof", re.compile(r"(?i)</?\s*(source_document|untrusted|system|instructions?)\s*>")),
]

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f​-‏‪-‮⁠-⁤﻿]")


def sanitize_text(text: str, max_chars: int) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = _CONTROL.sub("", text)
    text = re.sub(r"(?i)</?\s*(source_document|untrusted_content)\s*>", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()[:max_chars]


def detect_injection(text: str) -> list[dict[str, str]]:
    flags: list[dict[str, str]] = []
    for name, pat in PATTERNS:
        m = pat.search(text)
        if m:
            start = max(0, m.start() - 30)
            flags.append({"type": name, "excerpt": text[start : m.end() + 30].replace("\n", " ").strip()[:200]})
    return flags


def looks_like_instruction(sentence: str) -> bool:
    return any(pat.search(sentence) for _, pat in PATTERNS)

"""Neutralize stored / indirect prompt injection in untrusted text.

Tool results re-enter the model as function-result messages. Content that
originates from other users - product reviews, descriptions, order notes -
can carry adversarial instructions ("ignore previous instructions", role
reassignments, fake system turns, system-prompt exfiltration). This module
*defangs* those markers (replaces them with an inert ``[neutralized]`` token
rather than deleting them, so legitimate analysis still sees that the text
existed) and strips control / zero-width characters used to smuggle hidden
instructions.

Pure functions: no I/O, no LLM, no DB. Patterns are deliberately high
precision (low false-positive) - the prompt-layer rules and the inbound
injection detector are the other two layers of defense.
"""

from __future__ import annotations

import re
from typing import Any

# Codepoints to strip: C0 controls except TAB (0x09) / LF (0x0A) / CR (0x0D),
# DEL, the zero-width marks, line/paragraph separators, and the BOM. Declared
# numerically (via translate) so the source file never contains raw control
# bytes.
_STRIP_CODEPOINTS = (
    *range(0x00, 0x09),
    0x0B,
    0x0C,
    *range(0x0E, 0x20),
    0x7F,
    *range(0x200B, 0x2010),
    0x2028,
    0x2029,
    0xFEFF,
)
_CONTROL_TRANSLATION = dict.fromkeys(_STRIP_CODEPOINTS)

# High-precision injection signals. Case-insensitive; the fake-turn pattern is
# anchored to a line start so it does not fire on legitimate prose like
# "the System: Pro model".
_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"ignore\s+(?:all\s+|any\s+)?(?:the\s+)?(?:previous|prior|above|earlier)\s+"
        r"(?:instructions?|prompts?|rules?|messages?)",
        re.I,
    ),
    re.compile(
        r"disregard\s+(?:all\s+|any\s+)?(?:the\s+)?(?:previous|prior|above|earlier)\s+"
        r"(?:instructions?|prompts?|rules?)",
        re.I,
    ),
    re.compile(
        r"forget\s+(?:all\s+|everything\s+|your\s+)?(?:previous\s+|prior\s+)?"
        r"(?:instructions?|rules?)",
        re.I,
    ),
    re.compile(r"you\s+are\s+now\s+(?:a|an|the)\b", re.I),
    re.compile(r"new\s+(?:system\s+)?(?:instructions?|prompts?|rules?)\s*:", re.I),
    re.compile(r"(?m)^\s{0,6}(?:system|developer|assistant)\s*:", re.I),
    re.compile(r"reveal\s+(?:your\s+|the\s+)?(?:system\s+)?(?:prompt|instructions?)", re.I),
    re.compile(r"</?\s*(?:system|instructions?|prompt)\s*>", re.I),
    re.compile(r"\bact\s+as\s+(?:if\s+you\s+are\s+)?(?:an?\s+)?admin", re.I),
)

_MARK = "[neutralized]"


def contains_injection_markers(text: str) -> bool:
    """Return True if *text* matches any high-precision injection signal."""
    if not text:
        return False
    return any(pattern.search(text) for pattern in _INJECTION_PATTERNS)


def neutralize_text(text: str) -> str:
    """Defang injection markers and strip control/zero-width chars in one string."""
    if not text:
        return text
    cleaned = text.translate(_CONTROL_TRANSLATION)
    for pattern in _INJECTION_PATTERNS:
        cleaned = pattern.sub(_MARK, cleaned)
    return cleaned


def neutralize_value(value: Any, *, fields: set[str] | None = None, _key: str | None = None) -> Any:
    """Recursively neutralize untrusted strings inside a tool result.

    Args:
        value: tool result - ``str`` / ``dict`` / ``list`` / scalar.
        fields: if given, only strings whose immediate dict key is in this set
            (at any nesting depth) are neutralized; otherwise every string is.
        _key: internal - the dict key the current value sits under.
    """
    if isinstance(value, str):
        if fields is None or _key in fields:
            return neutralize_text(value)
        return value
    if isinstance(value, dict):
        return {k: neutralize_value(v, fields=fields, _key=k) for k, v in value.items()}
    if isinstance(value, list):
        return [neutralize_value(v, fields=fields, _key=_key) for v in value]
    if isinstance(value, tuple):
        return tuple(neutralize_value(v, fields=fields, _key=_key) for v in value)
    return value

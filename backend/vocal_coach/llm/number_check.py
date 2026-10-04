"""Number post-check: every numeric token the model cites must trace back to the payload.

Allowed forms come from:
- every numeric leaf of payload["metrics"], payload["transcript_derived"] and
  payload["comparison"], rendered as serialised (json.dumps / repr), at 0 to 6
  decimal places with trailing-zero-stripped variants, and with thousands
  separators for integers. So "17.3" for a stored 17.26 and "0.00001" for a
  stored 1e-05 are accepted, but an invented "17.5" is not. A negative value
  also licenses its unsigned forms (the words carry the direction).
- numbers in payload["transcript_text"] (the speaker said them);
- numbers in the bundled system prompt (e.g. "1 to 1.5 seconds");
- the small integers 0 to 10 (counts such as "3 times").

Only what_improved, what_is_lacking and next_steps are scanned:
marked_up_example is verified against the transcript by the markup check.
"""
from __future__ import annotations

import json
import re
from typing import Iterable

from vocal_coach.llm.prompts import load_system_prompt

# A number token: not preceded by a word char or "/", not followed by one
# either, so "F0" and "16k" are not matched, and "//" never contributes digits.
# Thousands-separated numbers ("1,200") match as one token.
NUMBER_RE = re.compile(
    r"(?<![\w/])[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?(?![\w/])"
    r"|(?<![\w/])[-+]?\d+(?:\.\d+)?(?![\w/])"
)

FIELDS = ("what_improved", "what_is_lacking", "next_steps")

SMALL_INTS = tuple(range(0, 11))


def numeric_leaves(obj) -> list[int | float]:
    """Recursively collect every int/float leaf of a dict/list structure, keeping the original
    type. Skips bools."""
    out: list[int | float] = []
    if isinstance(obj, bool):
        return out
    if isinstance(obj, (int, float)):
        out.append(obj)
    elif isinstance(obj, dict):
        for value in obj.values():
            out.extend(numeric_leaves(value))
    elif isinstance(obj, list):
        for item in obj:
            out.extend(numeric_leaves(item))
    return out


def _stripped(s: str) -> str | None:
    """"12.0" -> "12", "17.30" -> "17.3"; None when there is nothing to strip."""
    if "." not in s:
        return None
    stripped = s.rstrip("0").rstrip(".")
    return stripped if stripped and stripped != s else None


def _forms_of(value: int | float) -> set[str]:
    forms = {json.dumps(value), repr(value)}
    if isinstance(value, int):
        forms.add(f"{value:,}")
        return forms
    for precision in range(0, 7):
        rendered = f"{value:.{precision}f}"
        forms.add(rendered)
        alt = _stripped(rendered)
        if alt is not None:
            forms.add(alt)
    return forms


def allowed_forms(values: Iterable[int | float]) -> set[str]:
    forms: set[str] = set()
    for value in values:
        if isinstance(value, bool):
            continue
        forms |= _forms_of(value)
        if value < 0:
            forms |= _forms_of(-value)
    return forms


def extract_numbers(text: str) -> list[str]:
    return NUMBER_RE.findall(text)


def _text_numbers(text: str | None) -> set[str]:
    """Numeric tokens of free text, as written and with thousands separators removed."""
    out: set[str] = set()
    for token in extract_numbers(text or ""):
        out.add(token)
        out.add(token.replace(",", ""))
    return out


def _field_text(value) -> str:
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    if value is None:
        return ""
    return str(value)


def check_numbers(output: dict, payload: dict) -> list[str]:
    values: list[int | float] = list(SMALL_INTS)
    for key in ("metrics", "transcript_derived", "comparison"):
        section = payload.get(key)
        if section is not None:
            values.extend(numeric_leaves(section))
    allowed = allowed_forms(values)
    allowed |= _text_numbers(payload.get("transcript_text"))
    allowed |= _text_numbers(load_system_prompt())

    warnings: list[str] = []
    seen: set[tuple[str, str]] = set()
    for field in FIELDS:
        text = _field_text(output.get(field))
        for token in extract_numbers(text):
            if token in allowed or token.lstrip("+") in allowed:
                continue
            key = (field, token)
            if key in seen:
                continue
            seen.add(key)
            warnings.append(f"number {token} in {field} does not match any metric value")
    return warnings

"""Number post-check: every numeric token the model cites must trace back to the payload.

Allowed forms come from every numeric leaf of payload["metrics"],
payload["transcript_derived"], and payload["comparison"], rendered at 0, 1,
and 2 decimal places (so a re-rounding such as "17.3" for a stored 17.26 is
accepted, but an invented "17.5" is not). Sign matters: a negative value does
not license its unsigned form.
"""
from __future__ import annotations

import re
from typing import Iterable

# A number token: not preceded by a word char or "/", not followed by one
# either, so "F0" and "16k" are not matched, and "//" never contributes digits.
NUMBER_RE = re.compile(r"(?<![\w/])[-+]?\d+(?:\.\d+)?(?![\w/])")

FIELDS = ("what_improved", "what_is_lacking", "next_steps", "marked_up_example")


def numeric_leaves(obj) -> list[float]:
    """Recursively collect every int/float leaf of a dict/list structure. Skips bools."""
    out: list[float] = []
    if isinstance(obj, bool):
        return out
    if isinstance(obj, (int, float)):
        out.append(float(obj))
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


def allowed_forms(values: Iterable[float]) -> set[str]:
    forms: set[str] = set()
    for value in values:
        for precision in (0, 1, 2):
            rendered = f"{value:.{precision}f}"
            forms.add(rendered)
            alt = _stripped(rendered)
            if alt is not None:
                forms.add(alt)
    return forms


def extract_numbers(text: str) -> list[str]:
    return NUMBER_RE.findall(text)


def _field_text(value) -> str:
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    if value is None:
        return ""
    return str(value)


def check_numbers(output: dict, payload: dict) -> list[str]:
    values: list[float] = []
    for key in ("metrics", "transcript_derived", "comparison"):
        section = payload.get(key)
        if section is not None:
            values.extend(numeric_leaves(section))
    allowed = allowed_forms(values)

    warnings: list[str] = []
    seen: set[tuple[str, str]] = set()
    for field in FIELDS:
        text = _field_text(output.get(field))
        for token in extract_numbers(text):
            if token in allowed:
                continue
            key = (field, token)
            if key in seen:
                continue
            seen.add(key)
            warnings.append(f"number {token} in {field} does not match any metric value")
    return warnings

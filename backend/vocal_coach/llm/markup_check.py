"""Markup post-check: marked_up_example must be a contiguous word subsequence of the transcript."""
from __future__ import annotations

import re

MARKS = ("//", "↘")  # // for a pause, downwards-arrow for a falling finish

_PUNCT_RE = re.compile(r"[^\w\s']", re.UNICODE)


def demark(text: str) -> list[str]:
    """Remove marks, lowercase, strip punctuation (keeping apostrophes inside words), split on whitespace."""
    cleaned = text
    for mark in MARKS:
        cleaned = cleaned.replace(mark, " ")
    cleaned = cleaned.lower()
    cleaned = _PUNCT_RE.sub(" ", cleaned)
    tokens = [tok.strip("'") for tok in cleaned.split()]
    return [tok for tok in tokens if tok]


def _is_blank(text: str | None) -> bool:
    return not text or not text.strip()


def check_marked_up_example(example: str, transcript_text: str | None) -> str | None:
    example_is_empty = _is_blank(example)

    if not transcript_text:
        # The model was told to return "" when there is no transcript; only
        # warn when it produced an example anyway.
        if example_is_empty:
            return None
        return "no transcript available for marked_up_example"

    if example_is_empty:
        return "marked_up_example is empty"

    example_tokens = demark(example)
    if not example_tokens:
        # The example was non-blank (e.g. "!!!" or "// ↘") but demarks to no
        # words at all, so it cannot be a subsequence of the transcript.
        return "marked_up_example does not match the transcript"
    transcript_tokens = demark(transcript_text)
    n = len(example_tokens)
    m = len(transcript_tokens)
    for start in range(m - n + 1):
        if transcript_tokens[start:start + n] == example_tokens:
            return None
    return "marked_up_example does not match the transcript"

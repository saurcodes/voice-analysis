"""Deterministic English syllable estimate from spelling. No dictionary."""
from __future__ import annotations

import re

VOWELS = "aeiouy"
_STRIP_RE = re.compile(r"^[^a-z0-9']+|[^a-z0-9']+$")  # leading/trailing punctuation
_VOWEL_GROUP_RE = re.compile(rf"[{VOWELS}]+")
MIN_SYLLABLES_FOR_TOKEN = 1  # any real token has at least one nucleus, even "hmm"
HIATUS_ENDINGS = ("ia", "ea", "io", "ua")  # "idea", "media", "radio": the final two vowels are separate nuclei


def normalise_token(word: str) -> str:
    return _STRIP_RE.sub("", word.strip().lower()).strip("'")


def count_syllables(word: str) -> int:
    w = normalise_token(word)
    if not w:
        return 0
    groups = len(_VOWEL_GROUP_RE.findall(w))
    # Silent trailing 'e' ("make"), but keep consonant+"le" ("table").
    if w.endswith("e") and not w.endswith("le") and groups > 1 and w[-2] not in VOWELS:
        groups -= 1
    if w.endswith(HIATUS_ENDINGS):
        groups += 1
    return max(MIN_SYLLABLES_FOR_TOKEN, groups)

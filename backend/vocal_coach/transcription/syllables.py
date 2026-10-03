"""Deterministic English syllable estimate from spelling. No dictionary."""
from __future__ import annotations

import re

VOWELS = "aeiouy"
_STRIP_RE = re.compile(r"^[^a-z0-9']+|[^a-z0-9']+$")  # leading/trailing punctuation
_VOWEL_GROUP_RE = re.compile(rf"[{VOWELS}]+")
MIN_SYLLABLES_FOR_TOKEN = 1  # any real token has at least one nucleus, even "hmm"
HIATUS_ENDINGS = ("ia", "ea", "io", "ua")  # "idea", "media", "radio": the final two vowels are separate nuclei
SILENT_ED_EXCEPTIONS = ("ted", "ded")  # "-ed" after a consonant is silent except after t or d: wanted, added; after a vowel the "e" belongs to the stem (agreed)
SILENT_ED_MIN_LEN = 3  # "red", "bed": a three-letter word ending in "ed" has no suffix to drop


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
    # Silent past-tense "-ed" after a consonant ("assigned", "developed"), except after t/d
    # ("wanted", "added"); after a vowel ("agreed", "proceed") the vowel group is already merged.
    if (w.endswith("ed") and len(w) > SILENT_ED_MIN_LEN and w[-3] not in VOWELS
            and not w.endswith(SILENT_ED_EXCEPTIONS)):
        groups -= 1
    if w.endswith(HIATUS_ENDINGS):
        groups += 1
    return max(MIN_SYLLABLES_FOR_TOKEN, groups)

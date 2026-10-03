"""Filler-word counts and per-minute rates over whisper words."""
from __future__ import annotations

from vocal_coach.transcription.schema import TranscriptWord
from vocal_coach.transcription.syllables import normalise_token

SECONDS_PER_MINUTE = 60.0


def per_min(count: int, duration_s: float) -> float:
    return float(count / (duration_s / SECONDS_PER_MINUTE)) if duration_s > 0 else 0.0


def words_per_min(word_count: int, duration_s: float) -> float:
    return per_min(word_count, duration_s)


def count_fillers(words: list[TranscriptWord], fillers: list[str]) -> dict[str, int]:
    tokens = [normalise_token(w.word) for w in words]
    tokens = [t for t in tokens if t]
    patterns = [tuple(normalise_token(p) for p in f.split()) for f in fillers]
    # Longest patterns first so "you know" wins over "you".
    order = sorted(range(len(fillers)), key=lambda i: -len(patterns[i]))
    counts = {f: 0 for f in fillers}
    i = 0
    while i < len(tokens):
        matched = False
        for idx in order:
            pat = patterns[idx]
            n = len(pat)
            if tuple(tokens[i:i + n]) == pat:
                counts[fillers[idx]] += 1
                i += n
                matched = True
                break
        if not matched:
            i += 1
    return counts

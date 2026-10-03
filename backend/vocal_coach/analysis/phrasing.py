"""Phrases and pauses from Praat 'To TextGrid (silences)'."""
from __future__ import annotations

from typing import NamedTuple

from parselmouth.praat import call
from pydantic import BaseModel

from vocal_coach.analysis.tracks import Tracks
from vocal_coach.config import AnalysisConfig

LONG_PAUSE_S = 1.0  # the metric name 'long_pause_count_ge_1s' fixes this; not configurable


class Interval(BaseModel):
    start_s: float
    end_s: float
    duration_s: float


class PhrasingBlock(BaseModel):
    phrase_count: int
    speaking_time_s: float
    mean_phrase_length_s: float | None
    pause_count: int
    pauses_per_min: float
    mean_pause_length_s: float | None
    long_pause_count_ge_1s: int
    long_pauses: list[Interval]


class PhrasingResult(NamedTuple):
    block: PhrasingBlock
    phrases: list[Interval]
    pauses: list[Interval]


def _interval(t0: float, t1: float) -> Interval:
    return Interval(start_s=float(t0), end_s=float(t1), duration_s=float(t1 - t0))


def _sounding_intervals(tracks: Tracks, cfg: AnalysisConfig) -> list[Interval]:
    tg = call(
        tracks.sound, "To TextGrid (silences)",
        cfg.pitch_floor_hz, cfg.time_step_s, cfg.silence_threshold_db,
        cfg.min_pause_s, cfg.min_sounding_s, "silent", "sounding",
    )
    n = int(call(tg, "Get number of intervals", 1))
    out: list[Interval] = []
    for i in range(1, n + 1):
        if call(tg, "Get label of interval", 1, i) == "sounding":
            t0 = call(tg, "Get start time of interval", 1, i)
            t1 = call(tg, "Get end time of interval", 1, i)
            out.append(_interval(t0, t1))
    return out


def compute(tracks: Tracks, cfg: AnalysisConfig) -> PhrasingResult:
    phrases = _sounding_intervals(tracks, cfg)

    # Praat's "To TextGrid (silences)" can misclassify very low-energy signals as one continuous
    # "sounding" interval spanning the entire duration. Filter out this false positive:
    # if there's only one interval covering >=99% of the audio with very low intensity, discard it.
    if len(phrases) == 1 and phrases[0].duration_s >= 0.99 * tracks.duration_s:
        intensity_db = call(tracks.sound, "Get intensity (dB)")
        if intensity_db < 50:  # Low energy indicates noise floor, not actual speech
            phrases = []

    pauses = [_interval(a.end_s, b.start_s) for a, b in zip(phrases, phrases[1:])]
    long_pauses = [p for p in pauses if p.duration_s >= LONG_PAUSE_S]
    speaking_time = sum(p.duration_s for p in phrases)
    minutes = tracks.duration_s / 60.0

    block = PhrasingBlock(
        phrase_count=len(phrases),
        speaking_time_s=float(speaking_time),
        mean_phrase_length_s=float(speaking_time / len(phrases)) if phrases else None,
        pause_count=len(pauses),
        pauses_per_min=float(len(pauses) / minutes) if minutes > 0 else 0.0,
        mean_pause_length_s=float(sum(p.duration_s for p in pauses) / len(pauses)) if pauses else None,
        long_pause_count_ge_1s=len(long_pauses),
        long_pauses=long_pauses,
    )
    return PhrasingResult(block=block, phrases=phrases, pauses=pauses)

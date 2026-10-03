"""Phrases and pauses from Praat 'To TextGrid (silences)'."""
from __future__ import annotations

from typing import NamedTuple

import numpy as np
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
    # Gate on voicing: if no voiced frames detected, skip Praat and return empty result.
    # This avoids spurious silence detection on unvoiced audio and reuses config-driven pitch tracking.
    if not np.any(~np.isnan(tracks.f0_hz)):
        return PhrasingResult(
            block=PhrasingBlock(
                phrase_count=0,
                speaking_time_s=0.0,
                mean_phrase_length_s=None,
                pause_count=0,
                pauses_per_min=0.0,
                mean_pause_length_s=None,
                long_pause_count_ge_1s=0,
                long_pauses=[],
            ),
            phrases=[],
            pauses=[],
        )

    phrases = _sounding_intervals(tracks, cfg)

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

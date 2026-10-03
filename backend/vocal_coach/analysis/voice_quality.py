"""HNR, jitter, shimmer via Praat."""
from __future__ import annotations

import math

import numpy as np
from parselmouth.praat import call
from pydantic import BaseModel

from vocal_coach.analysis.tracks import Tracks
from vocal_coach.config import AnalysisConfig

# Praat's documented defaults for "To Harmonicity (cc)".
HARMONICITY_SILENCE_THRESHOLD = 0.1
HARMONICITY_PERIODS_PER_WINDOW = 1.0

# Praat's documented defaults for the jitter/shimmer period-window bounds.
JITTER_PERIOD_FLOOR_S = 0.0001
JITTER_PERIOD_CEILING_S = 0.02
JITTER_PERIOD_FACTOR = 1.3
SHIMMER_AMPLITUDE_FACTOR = 1.6


class VoiceQualityBlock(BaseModel):
    hnr_db: float | None
    jitter_local: float | None
    shimmer_local: float | None
    low_confidence: bool


def _finite(v: float) -> float | None:
    return float(v) if v is not None and math.isfinite(v) else None


def compute(tracks: Tracks, cfg: AnalysisConfig, low_confidence: bool) -> VoiceQualityBlock:
    if not np.any(~np.isnan(tracks.f0_hz)):
        return VoiceQualityBlock(hnr_db=None, jitter_local=None, shimmer_local=None, low_confidence=low_confidence)

    harmonicity = tracks.sound.to_harmonicity_cc(
        time_step=cfg.time_step_s,
        minimum_pitch=cfg.pitch_floor_hz,
        silence_threshold=HARMONICITY_SILENCE_THRESHOLD,
        periods_per_window=HARMONICITY_PERIODS_PER_WINDOW,
    )
    hnr = call(harmonicity, "Get mean", 0, 0)

    point_process = call(tracks.sound, "To PointProcess (periodic, cc)", cfg.pitch_floor_hz, cfg.pitch_ceiling_hz)
    jitter = call(
        point_process,
        "Get jitter (local)",
        0,
        0,
        JITTER_PERIOD_FLOOR_S,
        JITTER_PERIOD_CEILING_S,
        JITTER_PERIOD_FACTOR,
    )
    shimmer = call(
        [tracks.sound, point_process],
        "Get shimmer (local)",
        0,
        0,
        JITTER_PERIOD_FLOOR_S,
        JITTER_PERIOD_CEILING_S,
        JITTER_PERIOD_FACTOR,
        SHIMMER_AMPLITUDE_FACTOR,
    )

    return VoiceQualityBlock(
        hnr_db=_finite(hnr),
        jitter_local=_finite(jitter),
        shimmer_local=_finite(shimmer),
        low_confidence=low_confidence,
    )

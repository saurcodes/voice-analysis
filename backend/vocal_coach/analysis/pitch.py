"""Pitch metrics: median F0, robust range, creak share, opening vs overall."""
from __future__ import annotations

import numpy as np
from pydantic import BaseModel

from vocal_coach.analysis.tracks import Tracks, semitones
from vocal_coach.config import AnalysisConfig


class PitchBlock(BaseModel):
    f0_median_hz: float | None
    f0_p10_hz: float | None
    f0_p90_hz: float | None
    f0_range_st: float | None
    voiced_fraction: float
    creak_fraction_below_100hz: float | None
    opening_f0_median_hz: float | None
    opening_vs_overall_st: float | None


def compute(tracks: Tracks, cfg: AnalysisConfig) -> PitchBlock:
    f0 = tracks.f0_hz
    voiced = f0[~np.isnan(f0)]
    n_frames = len(f0)
    voiced_fraction = float(len(voiced) / n_frames) if n_frames else 0.0

    if len(voiced) == 0:
        return PitchBlock(
            f0_median_hz=None, f0_p10_hz=None, f0_p90_hz=None, f0_range_st=None,
            voiced_fraction=voiced_fraction, creak_fraction_below_100hz=None,
            opening_f0_median_hz=None, opening_vs_overall_st=None,
        )

    median = float(np.median(voiced))
    p10 = float(np.percentile(voiced, 10))
    p90 = float(np.percentile(voiced, 90))
    creak = float(np.mean(voiced < cfg.creak_threshold_hz))

    opening = tracks.f0_between(0.0, cfg.opening_window_s)
    if len(opening) == 0:
        opening_median = None
        opening_vs_overall = None
    else:
        opening_median = float(np.median(opening))
        opening_vs_overall = float(semitones(opening_median, median))

    return PitchBlock(
        f0_median_hz=median,
        f0_p10_hz=p10,
        f0_p90_hz=p90,
        f0_range_st=float(semitones(p90, p10)),
        voiced_fraction=voiced_fraction,
        creak_fraction_below_100hz=creak,
        opening_f0_median_hz=opening_median,
        opening_vs_overall_st=opening_vs_overall,
    )

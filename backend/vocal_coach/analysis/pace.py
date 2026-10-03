"""Syllable-rate estimate from voiced intensity peaks."""
from __future__ import annotations

from typing import NamedTuple

import numpy as np
from pydantic import BaseModel
from scipy.signal import find_peaks

from vocal_coach.analysis.tracks import Tracks
from vocal_coach.config import AnalysisConfig


class PaceBlock(BaseModel):
    syllable_count_est: int
    syllables_per_sec_overall: float
    articulation_rate_syl_per_sec: float | None


class PaceResult(NamedTuple):
    block: PaceBlock
    peak_times: np.ndarray
    peak_prominences_db: np.ndarray


def compute(tracks: Tracks, cfg: AnalysisConfig, speaking_time_s: float) -> PaceResult:
    intensity = tracks.intensity_db.copy()
    voiced = tracks.voiced_mask_at(tracks.int_times)
    # Push unvoiced frames far below everything so peaks can only form in voiced regions.
    floor = float(np.nanmin(intensity)) - 100.0 if len(intensity) else 0.0
    intensity[~voiced] = floor

    all_peaks, all_props = find_peaks(intensity, prominence=cfg.syllable_peak_prominence_db)
    keep = voiced[all_peaks]
    peak_idx = all_peaks[keep]
    prominences = all_props["prominences"][keep]

    count = int(len(peak_idx))
    overall = float(count / tracks.duration_s) if tracks.duration_s > 0 else 0.0
    articulation = float(count / speaking_time_s) if speaking_time_s > 0 else None

    return PaceResult(
        block=PaceBlock(
            syllable_count_est=count,
            syllables_per_sec_overall=overall,
            articulation_rate_syl_per_sec=articulation,
        ),
        peak_times=tracks.int_times[peak_idx],
        peak_prominences_db=prominences.astype(float),
    )

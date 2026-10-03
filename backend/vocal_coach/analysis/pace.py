"""Syllable-rate estimate from voiced intensity peaks."""
from __future__ import annotations

from typing import NamedTuple

import numpy as np
from pydantic import BaseModel
from scipy.signal import find_peaks

from vocal_coach.analysis.tracks import Tracks
from vocal_coach.config import AnalysisConfig

PEAK_WLEN_S = 0.4  # window for prominence bases: a syllable is judged against its ~400 ms neighbourhood, not against distant silence
MIN_WLEN_FRAMES = 3  # find_peaks needs a window of at least 3 samples (peak plus one each side)


class PaceBlock(BaseModel):
    syllable_count_est: int
    syllables_per_sec_overall: float
    articulation_rate_syl_per_sec: float | None


class PaceResult(NamedTuple):
    block: PaceBlock
    peak_times: np.ndarray
    peak_prominences_db: np.ndarray


def compute(tracks: Tracks, cfg: AnalysisConfig, speaking_time_s: float) -> PaceResult:
    voiced = tracks.voiced_mask_at(tracks.int_times)
    wlen_frames = max(MIN_WLEN_FRAMES, int(round(PEAK_WLEN_S / cfg.time_step_s)))
    all_peaks, all_props = find_peaks(
        tracks.intensity_db, prominence=cfg.syllable_peak_prominence_db, wlen=wlen_frames,
    )
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

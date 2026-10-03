"""Per-window F0 and intensity summary."""
from __future__ import annotations

import numpy as np
from pydantic import BaseModel

from vocal_coach.analysis.tracks import Tracks, semitones
from vocal_coach.config import AnalysisConfig


class TimelineWindow(BaseModel):
    start_s: float
    end_s: float
    f0_median_hz: float | None
    f0_sd_st: float | None
    intensity_median_db: float | None


class TimelineBlock(BaseModel):
    window_s: float
    windows: list[TimelineWindow]


def compute(tracks: Tracks, cfg: AnalysisConfig) -> TimelineBlock:
    windows: list[TimelineWindow] = []
    start = 0.0
    while start < tracks.duration_s:
        end = min(start + cfg.energy_window_s, tracks.duration_s)
        f0 = tracks.f0_between(start, end)
        inten = tracks.intensity_between(start, end)
        if len(f0):
            med = float(np.median(f0))
            sd = float(np.std(semitones(f0, med)))
        else:
            med, sd = None, None
        windows.append(TimelineWindow(
            start_s=float(start), end_s=float(end),
            f0_median_hz=med, f0_sd_st=sd,
            intensity_median_db=float(np.median(inten)) if len(inten) else None,
        ))
        start += cfg.energy_window_s
    return TimelineBlock(window_s=cfg.energy_window_s, windows=windows)

"""Energy: body vs final window, per-phrase trailing off.

Final window = last `energy_window_s` seconds of speech, anchored at the end of
the last phrase (trailing silence or a long tail after speech does not empty it).
Body = speaking frames before that window.
"""
from __future__ import annotations

import numpy as np
from pydantic import BaseModel

from vocal_coach.analysis.phrasing import Interval
from vocal_coach.analysis.tracks import Tracks
from vocal_coach.config import AnalysisConfig


class EnergyBlock(BaseModel):
    body_median_db: float | None
    final_15s_median_db: float | None
    final_vs_body_db: float | None
    trailing_off_count: int
    per_phrase_end_drop_db: list[float]


def speaking_mask(tracks: Tracks, phrases: list[Interval]) -> np.ndarray:
    mask = np.zeros(len(tracks.int_times), dtype=bool)
    for ph in phrases:
        mask |= (tracks.int_times >= ph.start_s) & (tracks.int_times <= ph.end_s)
    return mask


def _median_or_none(values: np.ndarray) -> float | None:
    return float(np.median(values)) if len(values) else None


def compute(tracks: Tracks, cfg: AnalysisConfig, phrases: list[Interval]) -> EnergyBlock:
    speaking = speaking_mask(tracks, phrases)
    times = tracks.int_times
    inten = tracks.intensity_db

    speech_end = max(ph.end_s for ph in phrases) if phrases else tracks.duration_s
    final_start = speech_end - cfg.energy_window_s
    final_mask = speaking & (times >= final_start)
    body_mask = speaking & (times < final_start)
    if not body_mask.any():
        body_mask = speaking  # recording shorter than two windows: body = all speech

    body = _median_or_none(inten[body_mask])
    final = _median_or_none(inten[final_mask])
    final_vs_body = float(final - body) if body is not None and final is not None else None

    drops: list[float] = []
    for ph in phrases:
        if ph.duration_s < cfg.phrase_end_tail_s:
            continue
        whole = tracks.intensity_between(ph.start_s, ph.end_s)
        tail = tracks.intensity_between(ph.end_s - cfg.phrase_end_tail_s, ph.end_s)
        if len(whole) == 0 or len(tail) == 0:
            continue
        drops.append(float(np.median(tail) - np.median(whole)))

    trailing = sum(d < -cfg.trailing_off_drop_db for d in drops)
    return EnergyBlock(
        body_median_db=body,
        final_15s_median_db=final,
        final_vs_body_db=final_vs_body,
        trailing_off_count=int(trailing),
        per_phrase_end_drop_db=drops,
    )

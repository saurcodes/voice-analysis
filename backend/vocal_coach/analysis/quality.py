"""Recording quality: noise floor, SNR estimate, low-confidence flag."""
from __future__ import annotations

import numpy as np
from pydantic import BaseModel

from vocal_coach.analysis.energy import speaking_mask
from vocal_coach.analysis.phrasing import Interval
from vocal_coach.analysis.tracks import Tracks
from vocal_coach.config import AnalysisConfig


class RecordingQualityBlock(BaseModel):
    noise_floor_db: float | None
    snr_estimate_db: float | None
    low_confidence: bool
    reasons: list[str]


def compute(tracks: Tracks, cfg: AnalysisConfig, phrases: list[Interval]) -> RecordingQualityBlock:
    inten = tracks.intensity_db
    # Percentile over ALL (0 dB-clamped) frames: a noise-gated export reports 0.0.
    noise_floor = float(np.percentile(inten, cfg.noise_floor_percentile)) if len(inten) else None
    speaking = speaking_mask(tracks, phrases)
    has_voiced = bool(np.any(~np.isnan(tracks.f0_hz)))

    reasons: list[str] = []
    snr: float | None = None
    if speaking.any() and has_voiced:
        if noise_floor is not None:
            snr = float(np.median(inten[speaking]) - noise_floor)
            if snr < cfg.low_confidence_snr_db:
                reasons.append("low_snr")
    else:
        reasons.append("no_voiced_speech")
    if noise_floor is not None and noise_floor > cfg.low_confidence_noise_floor_db:
        reasons.append("high_noise_floor")

    return RecordingQualityBlock(
        noise_floor_db=noise_floor,
        snr_estimate_db=snr,
        low_confidence=bool(reasons),
        reasons=reasons,
    )

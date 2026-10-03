"""Shared F0 and intensity contours extracted once per recording."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import parselmouth

from vocal_coach.config import AnalysisConfig

SEMITONES_PER_OCTAVE = 12.0  # equal temperament: 12 semitones per doubling of frequency
PRAAT_UNVOICED_HZ = 0.0  # parselmouth marks unvoiced frames with 0 Hz
INTENSITY_FLOOR_DB = 0.0  # Praat emits -300 dB for digital silence; 0 dB SPL is below any real room


def semitones(a, b):
    return SEMITONES_PER_OCTAVE * np.log2(np.asarray(a, dtype=float) / b)


@dataclass
class Tracks:
    sound: parselmouth.Sound
    samples: np.ndarray
    sr: int
    duration_s: float
    f0_times: np.ndarray
    f0_hz: np.ndarray
    int_times: np.ndarray
    intensity_db: np.ndarray

    def f0_between(self, t0: float, t1: float) -> np.ndarray:
        m = (self.f0_times >= t0) & (self.f0_times <= t1)
        vals = self.f0_hz[m]
        return vals[~np.isnan(vals)]

    def intensity_between(self, t0: float, t1: float) -> np.ndarray:
        m = (self.int_times >= t0) & (self.int_times <= t1)
        return self.intensity_db[m]

    def voiced_mask_at(self, times: np.ndarray) -> np.ndarray:
        """Voicing of the nearest pitch frame to each time."""
        times = np.asarray(times, dtype=float)
        n = len(self.f0_times)
        if n == 0:
            return np.zeros(times.shape, dtype=bool)
        if n > 1:
            step = self.f0_times[1] - self.f0_times[0]
            idx = np.clip(np.rint((times - self.f0_times[0]) / step).astype(int), 0, n - 1)
        else:
            idx = np.zeros(times.shape, dtype=int)
        return ~np.isnan(self.f0_hz[idx])


def extract_tracks(sound: parselmouth.Sound, cfg: AnalysisConfig) -> Tracks:
    pitch = sound.to_pitch_ac(
        time_step=cfg.time_step_s,
        pitch_floor=cfg.pitch_floor_hz,
        pitch_ceiling=cfg.pitch_ceiling_hz,
    )
    f0 = pitch.selected_array["frequency"].astype(float)
    f0[f0 == PRAAT_UNVOICED_HZ] = np.nan

    intensity = sound.to_intensity(minimum_pitch=cfg.pitch_floor_hz, time_step=cfg.time_step_s)
    return Tracks(
        sound=sound,
        samples=sound.values[0],
        sr=int(round(sound.sampling_frequency)),
        duration_s=float(sound.get_total_duration()),
        f0_times=pitch.xs(),
        f0_hz=f0,
        int_times=intensity.xs(),
        intensity_db=np.maximum(intensity.values[0].astype(float), INTENSITY_FLOOR_DB),
    )

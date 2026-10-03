"""Articulation proxies: spectral balance, envelope modulation, syllable peak strength, vowel space."""
from __future__ import annotations

import numpy as np
from pydantic import BaseModel
from scipy.signal import butter, sosfiltfilt, stft, welch
from scipy.spatial import ConvexHull, QhullError

from vocal_coach.analysis.energy import speaking_mask
from vocal_coach.analysis.phrasing import Interval
from vocal_coach.analysis.tracks import Tracks, semitones
from vocal_coach.config import AnalysisConfig, ArticulationConfig

# STFT framing: 25 ms Hann window, 10 ms hop (algorithm constants, not coaching thresholds).
STFT_WINDOW_S = 0.025
STFT_HOP_S = 0.010
TILT_BAND_HZ = (500.0, 8000.0)
WELCH_NPERSEG = 1024
FORMANT_TIME_STEP_S = 0.01
FORMANT_COUNT = 5
FORMANT_WINDOW_S = 0.025
FORMANT_PREEMPHASIS_HZ = 50.0

# A butter bandpass of order N decomposes into N second-order sections (sos),
# so scipy's sosfiltfilt default padlen is 3 * (2 * N + 1) -- see its source
# (`ntaps = 2 * n_sections + 1; edge = ntaps * 3`). We guard against calling it
# on input shorter than that, so the guard must track the same formula.
MODULATION_FILTER_ORDER = 2
MODULATION_FILTER_SECTIONS = MODULATION_FILTER_ORDER  # bandpass sos section count == order
MODULATION_PADLEN = 3 * (2 * MODULATION_FILTER_SECTIONS + 1)


class VowelSpace(BaseModel):
    f1_sd_hz: float | None
    f2_sd_hz: float | None
    vowel_space_area_hz2: float | None
    vowel_dispersion_st: float | None


class ArticulationBlock(BaseModel):
    hf_energy_ratio_db: float | None
    spectral_tilt_db_per_oct: float | None
    modulation_depth: float | None
    syllable_peak_prominence_mean_db: float | None
    syllable_peak_prominence_p25_db: float | None
    weak_peak_fraction: float | None
    vowel_space: VowelSpace
    low_confidence: bool


_EMPTY_VOWEL_SPACE = VowelSpace(
    f1_sd_hz=None, f2_sd_hz=None, vowel_space_area_hz2=None, vowel_dispersion_st=None
)


def _speaking_samples(tracks: Tracks, phrases: list[Interval]) -> np.ndarray:
    parts = [tracks.samples[int(p.start_s * tracks.sr): int(p.end_s * tracks.sr)] for p in phrases]
    return np.concatenate(parts) if parts else np.array([])


def _hf_ratio(x: np.ndarray, sr: int, art: ArticulationConfig) -> float | None:
    nper = int(STFT_WINDOW_S * sr)
    hop = int(STFT_HOP_S * sr)
    if len(x) < nper:
        return None
    f, _, z = stft(x, fs=sr, window="hann", nperseg=nper, noverlap=nper - hop, boundary=None)
    power = np.abs(z) ** 2
    hf = power[(f >= art.hf_band_hz[0]) & (f <= art.hf_band_hz[1])].sum(axis=0)
    lf = power[(f >= art.lf_band_hz[0]) & (f <= art.lf_band_hz[1])].sum(axis=0)
    ok = lf > 0
    if not ok.any():
        return None
    return float(np.median(10 * np.log10(hf[ok] / lf[ok])))


def _tilt(x: np.ndarray, sr: int) -> float | None:
    if len(x) < WELCH_NPERSEG:
        return None
    f, p = welch(x, fs=sr, nperseg=WELCH_NPERSEG)
    m = (f >= TILT_BAND_HZ[0]) & (f <= TILT_BAND_HZ[1]) & (p > 0)
    if m.sum() < 3:
        return None
    slope, _ = np.polyfit(np.log2(f[m]), 10 * np.log10(p[m]), 1)
    return float(slope)


def _modulation_depth(tracks: Tracks, speaking: np.ndarray, acfg: AnalysisConfig, art: ArticulationConfig) -> float | None:
    if speaking.sum() < 10:
        return None
    fs = 1.0 / acfg.time_step_s
    linear = 10 ** (tracks.intensity_db / 20.0)
    sos = butter(MODULATION_FILTER_ORDER, [art.modulation_band_hz[0], art.modulation_band_hz[1]], btype="band", fs=fs, output="sos")
    if len(linear) <= MODULATION_PADLEN:
        return None
    band = sosfiltfilt(sos, linear)
    mean = float(np.mean(linear[speaking]))
    if mean <= 0:
        return None
    return float(np.sqrt(np.mean(band[speaking] ** 2)) / mean)


def _vowel_space(tracks: Tracks, art: ArticulationConfig) -> VowelSpace:
    voiced_times = tracks.f0_times[~np.isnan(tracks.f0_hz)]
    if len(voiced_times) == 0:
        return _EMPTY_VOWEL_SPACE
    formant = tracks.sound.to_formant_burg(
        time_step=FORMANT_TIME_STEP_S, max_number_of_formants=FORMANT_COUNT,
        maximum_formant=art.formant_max_hz, window_length=FORMANT_WINDOW_S,
        pre_emphasis_from=FORMANT_PREEMPHASIS_HZ,
    )
    f1 = np.array([formant.get_value_at_time(1, t) for t in voiced_times])
    f2 = np.array([formant.get_value_at_time(2, t) for t in voiced_times])
    ok = ~np.isnan(f1) & ~np.isnan(f2)
    f1, f2 = f1[ok], f2[ok]
    if len(f1) < 3:
        return _EMPTY_VOWEL_SPACE
    lo, hi = art.formant_trim_pct, 100 - art.formant_trim_pct
    keep = (
        (f1 >= np.percentile(f1, lo)) & (f1 <= np.percentile(f1, hi))
        & (f2 >= np.percentile(f2, lo)) & (f2 <= np.percentile(f2, hi))
    )
    f1, f2 = f1[keep], f2[keep]
    if len(f1) < 3:
        return _EMPTY_VOWEL_SPACE
    pts = np.column_stack([f1, f2])
    try:
        area = float(ConvexHull(pts).volume)
    except QhullError:
        area = 0.0
    c1, c2 = float(np.mean(f1)), float(np.mean(f2))
    dispersion = float(np.mean(np.sqrt(semitones(f1, c1) ** 2 + semitones(f2, c2) ** 2)))
    return VowelSpace(
        f1_sd_hz=float(np.std(f1)), f2_sd_hz=float(np.std(f2)),
        vowel_space_area_hz2=area, vowel_dispersion_st=dispersion,
    )


def compute(
    tracks: Tracks,
    acfg: AnalysisConfig,
    art: ArticulationConfig,
    phrases: list[Interval],
    peak_prominences_db: np.ndarray,
    f0_median_hz: float | None,
    recording_low_confidence: bool,
) -> ArticulationBlock:
    speech = _speaking_samples(tracks, phrases)
    speaking = speaking_mask(tracks, phrases)
    proms = np.asarray(peak_prominences_db, dtype=float)

    low_conf = recording_low_confidence or (f0_median_hz is not None and f0_median_hz > acfg.low_confidence_f0_hz)

    return ArticulationBlock(
        hf_energy_ratio_db=_hf_ratio(speech, tracks.sr, art) if len(speech) else None,
        spectral_tilt_db_per_oct=_tilt(speech, tracks.sr) if len(speech) else None,
        modulation_depth=_modulation_depth(tracks, speaking, acfg, art),
        syllable_peak_prominence_mean_db=float(np.mean(proms)) if len(proms) else None,
        syllable_peak_prominence_p25_db=float(np.percentile(proms, 25)) if len(proms) else None,
        weak_peak_fraction=float(np.mean(proms < art.weak_peak_prominence_db)) if len(proms) else None,
        vowel_space=_vowel_space(tracks, art) if phrases else _EMPTY_VOWEL_SPACE,
        low_confidence=bool(low_conf),
    )

import numpy as np
from scipy.signal import butter, sosfiltfilt

from tests import synth
from vocal_coach.analysis import articulation
from vocal_coach.analysis.phrasing import Interval
from vocal_coach.analysis.tracks import extract_tracks


def _tracks(x, cfg):
    return extract_tracks(synth.to_sound(synth.with_noise_floor(x)), cfg.analysis)


def _phrase(t0, t1):
    return Interval(start_s=t0, end_s=t1, duration_s=t1 - t0)


def _run(x, cfg, proms=None, f0=120.0, low_conf=False):
    tr = _tracks(x, cfg)
    proms = np.array([6.0, 8.0, 7.0]) if proms is None else np.asarray(proms, dtype=float)
    return articulation.compute(tr, cfg.analysis, cfg.articulation, [_phrase(0.0, tr.duration_s)], proms, f0, low_conf)


def test_lowpass_reduces_hf_ratio_and_steepens_tilt(cfg):
    clear = synth.vowel(500, 1500, 120, 3.0)
    sos = butter(4, 1500, btype="low", fs=synth.SR, output="sos")
    muffled = sosfiltfilt(sos, clear)
    a = _run(clear, cfg)
    b = _run(muffled, cfg)
    assert b.hf_energy_ratio_db < a.hf_energy_ratio_db - 10
    assert b.spectral_tilt_db_per_oct < a.spectral_tilt_db_per_oct


def test_flattened_envelope_reduces_modulation_depth(cfg):
    modulated = synth.am(synth.vowel(500, 1500, 120, 4.0), 4.0)
    flat = synth.vowel(500, 1500, 120, 4.0)
    assert _run(flat, cfg).modulation_depth < _run(modulated, cfg).modulation_depth


def test_peak_prominence_stats(cfg):
    blk = _run(synth.vowel(500, 1500, 120, 2.0), cfg, proms=[2.0, 3.0, 5.0, 9.0])
    assert abs(blk.syllable_peak_prominence_mean_db - 4.75) < 1e-9
    assert abs(blk.syllable_peak_prominence_p25_db - 2.75) < 1e-9
    assert abs(blk.weak_peak_fraction - 0.5) < 1e-9


def test_two_vowels_have_larger_space_than_one(cfg):
    two = synth.concat(synth.vowel(300, 2300, 120, 2.0), synth.vowel(750, 1200, 120, 2.0))
    one = synth.vowel(500, 1500, 120, 4.0)
    a = _run(two, cfg).vowel_space
    b = _run(one, cfg).vowel_space
    assert a.vowel_space_area_hz2 > 5 * b.vowel_space_area_hz2
    assert a.f2_sd_hz > b.f2_sd_hz
    assert a.vowel_dispersion_st > b.vowel_dispersion_st


def test_low_confidence_from_recording_or_high_pitch(cfg):
    x = synth.vowel(500, 1500, 120, 2.0)
    assert _run(x, cfg, low_conf=True).low_confidence is True
    assert _run(x, cfg, f0=300.0).low_confidence is True
    assert _run(x, cfg).low_confidence is False


def test_silence_gives_nulls(cfg):
    tr = _tracks(synth.silence(2.0), cfg)
    blk = articulation.compute(tr, cfg.analysis, cfg.articulation, [], np.array([]), None, True)
    assert blk.hf_energy_ratio_db is None
    assert blk.modulation_depth is None
    assert blk.weak_peak_fraction is None
    assert blk.vowel_space.vowel_space_area_hz2 is None

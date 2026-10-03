import numpy as np

from tests import synth
from vocal_coach.analysis.tracks import Tracks, extract_tracks, semitones


def test_semitones_octave_is_twelve():
    assert abs(semitones(200.0, 100.0) - 12.0) < 1e-9
    assert abs(semitones(100.0, 200.0) + 12.0) < 1e-9


def test_extract_tracks_f0_and_intensity(cfg):
    x = synth.with_noise_floor(synth.tone(120, 2.0))
    tr = extract_tracks(synth.to_sound(x), cfg.analysis)
    assert isinstance(tr, Tracks)
    assert tr.sr == synth.SR
    assert abs(tr.duration_s - 2.0) < 0.01
    voiced = tr.f0_hz[~np.isnan(tr.f0_hz)]
    assert len(voiced) > 100
    assert abs(np.median(voiced) - 120) < 2
    assert tr.intensity_db.shape == tr.int_times.shape
    assert np.all(np.isfinite(tr.intensity_db))


def test_f0_between_and_voiced_mask(cfg):
    x = synth.with_noise_floor(synth.concat(synth.tone(120, 1.0), synth.silence(1.0), synth.tone(120, 1.0)))
    tr = extract_tracks(synth.to_sound(x), cfg.analysis)
    assert len(tr.f0_between(0.2, 0.8)) > 40
    assert len(tr.f0_between(1.2, 1.8)) == 0
    mask = tr.voiced_mask_at(np.array([0.5, 1.5, 2.5]))
    assert mask.tolist() == [True, False, True]


def test_digital_silence_intensity_is_clamped_at_zero(cfg):
    # 1 s of exact digital zeros in the middle: Praat would report -300 dB there.
    x = synth.concat(synth.tone(120, 1.0), synth.silence(1.0), synth.tone(120, 1.0))
    tr = extract_tracks(synth.to_sound(x), cfg.analysis)
    assert tr.intensity_db.min() == 0.0
    assert not np.any(tr.intensity_db < 0.0)


def test_voiced_mask_on_empty_track_is_all_false(cfg):
    tr = extract_tracks(synth.to_sound(synth.tone(120, 1.0)), cfg.analysis)
    tr.f0_times = np.array([])
    tr.f0_hz = np.array([])
    assert tr.voiced_mask_at(np.array([0.1, 0.5])).tolist() == [False, False]

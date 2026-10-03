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

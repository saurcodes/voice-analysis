import numpy as np

from tests import synth
from vocal_coach.analysis import pitch
from vocal_coach.analysis.tracks import extract_tracks


def _tracks(x, cfg):
    return extract_tracks(synth.to_sound(synth.with_noise_floor(x)), cfg.analysis)


def test_steady_tone_median(cfg):
    blk = pitch.compute(_tracks(synth.tone(120, 3.0), cfg), cfg.analysis)
    assert abs(blk.f0_median_hz - 120) < 2
    assert blk.voiced_fraction > 0.9
    assert blk.f0_range_st < 1.0


def test_two_tones_octave_apart_range(cfg):
    x = synth.concat(synth.tone(100, 2.0), synth.tone(200, 2.0))
    blk = pitch.compute(_tracks(x, cfg), cfg.analysis)
    assert abs(blk.f0_range_st - 12) < 1.0


def test_creak_fraction(cfg):
    x = synth.concat(synth.tone(85, 2.0), synth.tone(150, 2.0))
    blk = pitch.compute(_tracks(x, cfg), cfg.analysis)
    assert 0.4 < blk.creak_fraction_below_100hz < 0.6


def test_opening_vs_overall(cfg):
    x = synth.concat(synth.tone(200, 5.0), synth.tone(100, 10.0))
    blk = pitch.compute(_tracks(x, cfg), cfg.analysis)
    assert abs(blk.opening_f0_median_hz - 200) < 3
    assert blk.opening_vs_overall_st > 10


def test_long_leading_silence_gives_null_opening(cfg):
    x = synth.concat(synth.silence(6.0), synth.tone(120, 3.0))
    blk = pitch.compute(_tracks(x, cfg), cfg.analysis)
    assert blk.opening_f0_median_hz is None
    assert blk.opening_vs_overall_st is None
    assert abs(blk.f0_median_hz - 120) < 2


def test_no_voiced_frames_gives_nulls(cfg):
    blk = pitch.compute(_tracks(synth.silence(3.0), cfg), cfg.analysis)
    assert blk.f0_median_hz is None
    assert blk.f0_range_st is None
    assert blk.creak_fraction_below_100hz is None
    assert blk.voiced_fraction == 0.0

import numpy as np

from tests import synth
from vocal_coach.analysis import pace
from vocal_coach.analysis.tracks import extract_tracks


def _tracks(x, cfg):
    return extract_tracks(synth.to_sound(synth.with_noise_floor(x)), cfg.analysis)


def test_four_hz_am_gives_about_twenty_syllables(cfg):
    x = synth.am(synth.vowel(500, 1500, 120, 5.0), rate_hz=4.0)
    res = pace.compute(_tracks(x, cfg), cfg.analysis, speaking_time_s=5.0)
    assert 18 <= res.block.syllable_count_est <= 22
    assert 3.6 <= res.block.syllables_per_sec_overall <= 4.4
    assert abs(res.block.articulation_rate_syl_per_sec - res.block.syllables_per_sec_overall) < 1e-9
    assert len(res.peak_times) == res.block.syllable_count_est
    assert len(res.peak_prominences_db) == res.block.syllable_count_est
    assert res.peak_prominences_db.min() >= cfg.analysis.syllable_peak_prominence_db


def test_articulation_rate_uses_speaking_time(cfg):
    x = synth.concat(synth.am(synth.vowel(500, 1500, 120, 5.0), 4.0), synth.silence(5.0))
    res = pace.compute(_tracks(x, cfg), cfg.analysis, speaking_time_s=5.0)
    assert 1.8 <= res.block.syllables_per_sec_overall <= 2.2
    assert 3.6 <= res.block.articulation_rate_syl_per_sec <= 4.4


def test_silence_gives_zero(cfg):
    res = pace.compute(_tracks(synth.silence(3.0), cfg), cfg.analysis, speaking_time_s=0.0)
    assert res.block.syllable_count_est == 0
    assert res.block.syllables_per_sec_overall == 0.0
    assert res.block.articulation_rate_syl_per_sec is None


def test_prominence_matches_envelope_depth(cfg):
    x = synth.am(synth.vowel(500, 1500, 120, 5.0), 4.0)
    noisy = pace.compute(_tracks(x, cfg), cfg.analysis, speaking_time_s=5.0)
    zeros = synth.concat(synth.silence(0.5), x, synth.silence(0.5))  # EXACT digital zeros
    gated = pace.compute(extract_tracks(synth.to_sound(zeros), cfg.analysis), cfg.analysis, speaking_time_s=5.0)
    med_noisy = float(np.median(noisy.peak_prominences_db))
    med_gated = float(np.median(gated.peak_prominences_db))
    assert abs(med_noisy - med_gated) < 3.0
    assert med_noisy < 40.0
    assert med_gated < 40.0

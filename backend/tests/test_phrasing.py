from tests import synth
from vocal_coach.analysis import phrasing
from vocal_coach.analysis.tracks import extract_tracks


def _tracks(x, cfg):
    return extract_tracks(synth.to_sound(synth.with_noise_floor(x)), cfg.analysis)


def test_three_phrases_two_pauses_one_long(cfg):
    x = synth.concat(
        synth.tone(120, 2.0), synth.silence(0.5),
        synth.tone(120, 2.0), synth.silence(1.5),
        synth.tone(120, 2.0),
    )
    res = phrasing.compute(_tracks(x, cfg), cfg.analysis)
    blk = res.block
    assert blk.phrase_count == 3
    assert blk.pause_count == 2
    assert blk.long_pause_count_ge_1s == 1
    assert len(res.phrases) == 3
    assert len(res.pauses) == 2
    assert abs(blk.speaking_time_s - 6.0) < 0.3
    assert abs(blk.mean_phrase_length_s - 2.0) < 0.15
    assert abs(blk.mean_pause_length_s - 1.0) < 0.15
    assert abs(res.pauses[1].duration_s - 1.5) < 0.15
    assert len(blk.long_pauses) == 1 and abs(blk.long_pauses[0].start_s - 4.5) < 0.15


def test_leading_and_trailing_silence_not_pauses(cfg):
    x = synth.concat(synth.silence(1.0), synth.tone(120, 2.0), synth.silence(1.0))
    res = phrasing.compute(_tracks(x, cfg), cfg.analysis)
    assert res.block.phrase_count == 1
    assert res.block.pause_count == 0
    assert res.block.pauses_per_min == 0.0


def test_gap_shorter_than_min_pause_is_ignored(cfg):
    x = synth.concat(synth.tone(120, 2.0), synth.silence(0.1), synth.tone(120, 2.0))
    res = phrasing.compute(_tracks(x, cfg), cfg.analysis)
    assert res.block.phrase_count == 1


def test_all_silence(cfg):
    res = phrasing.compute(_tracks(synth.silence(3.0), cfg), cfg.analysis)
    assert res.block.phrase_count == 0
    assert res.block.mean_phrase_length_s is None
    assert res.block.speaking_time_s == 0.0

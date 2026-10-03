from tests import synth
from vocal_coach.analysis import energy
from vocal_coach.analysis.phrasing import Interval
from vocal_coach.analysis.tracks import extract_tracks


def _tracks(x, cfg):
    return extract_tracks(synth.to_sound(synth.with_noise_floor(x)), cfg.analysis)


def _phrase(t0, t1):
    return Interval(start_s=t0, end_s=t1, duration_s=t1 - t0)


def test_trailing_off_detected(cfg):
    quiet_end = synth.attenuate_tail(synth.tone(120, 2.0), tail_s=0.3, db=10)
    steady = synth.tone(120, 2.0)
    x = synth.concat(quiet_end, synth.silence(0.5), steady)
    blk = energy.compute(_tracks(x, cfg), cfg.analysis, [_phrase(0.0, 2.0), _phrase(2.5, 4.5)])
    assert blk.trailing_off_count == 1
    assert len(blk.per_phrase_end_drop_db) == 2
    assert blk.per_phrase_end_drop_db[0] < -6
    assert abs(blk.per_phrase_end_drop_db[1]) < 2


def test_final_window_vs_body(cfg):
    # 40 s: first 25 s at full level, last 15 s attenuated 6 dB.
    loud = synth.tone(120, 25.0)
    soft = synth.tone(120, 15.0) * 10 ** (-6 / 20)
    x = synth.concat(loud, soft)
    blk = energy.compute(_tracks(x, cfg), cfg.analysis, [_phrase(0.0, 40.0)])
    assert -7.5 < blk.final_vs_body_db < -4.5


def test_short_recording_body_falls_back_to_all_speech(cfg):
    x = synth.tone(120, 10.0)
    blk = energy.compute(_tracks(x, cfg), cfg.analysis, [_phrase(0.0, 10.0)])
    assert blk.body_median_db is not None
    assert blk.final_15s_median_db is not None
    assert abs(blk.final_vs_body_db) < 1.0


def test_no_phrases(cfg):
    blk = energy.compute(_tracks(synth.silence(3.0), cfg), cfg.analysis, [])
    assert blk.body_median_db is None
    assert blk.final_vs_body_db is None
    assert blk.trailing_off_count == 0
    assert blk.per_phrase_end_drop_db == []


def test_phrase_shorter_than_tail_is_skipped(cfg):
    # 0.2 s phrase (< phrase_end_tail_s 0.3) after 1 s of silence: tail window would
    # otherwise reach into the silence and fake a trailing-off drop.
    x = synth.concat(synth.tone(120, 2.0), synth.silence(1.0), synth.tone(120, 0.2))
    blk = energy.compute(_tracks(x, cfg), cfg.analysis, [_phrase(0.0, 2.0), _phrase(3.0, 3.2)])
    assert len(blk.per_phrase_end_drop_db) == 1
    assert blk.trailing_off_count == 0


def _raw_tracks(x, cfg):
    return extract_tracks(synth.to_sound(x), cfg.analysis)


def test_final_window_anchored_at_end_of_speech(cfg):
    # 25 s loud + 15 s soft (-6 dB) + 20 s EXACT zeros: the trailing silence must not null the final window.
    loud = synth.tone(120, 25.0)
    soft = synth.tone(120, 15.0) * 10 ** (-6 / 20)
    x = synth.concat(loud, soft, synth.silence(20.0))
    blk = energy.compute(_raw_tracks(x, cfg), cfg.analysis, [_phrase(0.0, 40.0)])
    assert blk.final_vs_body_db is not None
    assert -7.5 < blk.final_vs_body_db < -4.5


def test_final_window_present_when_file_ends_in_long_silence(cfg):
    x = synth.concat(synth.tone(120, 10.0), synth.silence(30.0))
    blk = energy.compute(_raw_tracks(x, cfg), cfg.analysis, [_phrase(0.0, 10.0)])
    assert blk.final_15s_median_db is not None

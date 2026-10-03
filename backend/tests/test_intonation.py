from tests import synth
from vocal_coach.analysis import intonation
from vocal_coach.analysis.phrasing import Interval
from vocal_coach.analysis.tracks import extract_tracks


def _tracks(x, cfg):
    return extract_tracks(synth.to_sound(synth.with_noise_floor(x)), cfg.analysis)


def _phrase(t0, t1):
    return Interval(start_s=t0, end_s=t1, duration_s=t1 - t0)


def test_rising_falling_flat(cfg):
    up = synth.tone_with_tail(120, 2.0, tail_s=0.3, tail_st=+3)
    down = synth.tone_with_tail(120, 2.0, tail_s=0.3, tail_st=-3)
    flat = synth.tone(120, 2.0)
    x = synth.concat(up, synth.silence(0.5), down, synth.silence(0.5), flat)
    phrases = [_phrase(0.0, 2.0), _phrase(2.5, 4.5), _phrase(5.0, 7.0)]
    blk = intonation.compute(_tracks(x, cfg), cfg.analysis, phrases)
    assert [p.class_ for p in blk.per_phrase] == ["up", "down", "flat"]
    assert blk.up_count == 1 and blk.down_count == 1 and blk.flat_count == 1
    assert blk.unclassified_count == 0
    assert abs(blk.flat_pct - 33.3333) < 0.01
    assert blk.per_phrase[0].end_delta_st > 1.5
    assert blk.per_phrase[1].end_delta_st < -1.5


def test_phrase_with_unvoiced_tail_is_unclassified(cfg):
    # 1 s tone then 0.3 s of silence inside the declared phrase -> no voiced frames in last 80 ms.
    x = synth.concat(synth.tone(120, 1.0), synth.silence(0.3))
    blk = intonation.compute(_tracks(x, cfg), cfg.analysis, [_phrase(0.0, 1.3)])
    assert blk.unclassified_count == 1
    assert blk.per_phrase == []
    assert blk.flat_pct is None


def test_per_phrase_serialises_class_key(cfg):
    x = synth.tone(120, 2.0)
    blk = intonation.compute(_tracks(x, cfg), cfg.analysis, [_phrase(0.0, 2.0)])
    dumped = blk.model_dump(by_alias=True)
    assert dumped["per_phrase"][0]["class"] == "flat"

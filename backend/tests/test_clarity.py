import numpy as np

from tests import synth
from vocal_coach.analysis.tracks import extract_tracks
from vocal_coach.transcription import clarity
from vocal_coach.transcription.schema import TranscriptSegment, TranscriptWord


def _tracks(x, cfg):
    return extract_tracks(synth.to_sound(synth.with_noise_floor(x)), cfg.analysis)


def _w(start, end, word, prob=0.95):
    return TranscriptWord(start_s=start, end_s=end, word=word, probability=prob)


def _seg(start, end, text, logprob=-0.3):
    return TranscriptSegment(start_s=start, end_s=end, text=text, avg_logprob=logprob, no_speech_prob=0.01)


def test_eaten_word_detected_by_tail_drop(cfg):
    # word A: 0.0–0.6 s steady; word B: 0.7–1.3 s with last 30 % attenuated 10 dB.
    a = synth.tone(120, 0.6)
    b = synth.attenuate_tail(synth.tone(120, 0.6), tail_s=0.18, db=10)
    x = synth.concat(a, synth.silence(0.1), b)
    words = [_w(0.0, 0.6, "steady"), _w(0.7, 1.3, "eaten")]
    blk = clarity.compute(words, [_seg(0.0, 1.3, "steady eaten")], _tracks(x, cfg), cfg.clarity)
    assert blk.word_final_drop_count == 1
    assert blk.eaten_words[0].word == "eaten"
    assert blk.eaten_words[0].drop_db < -6
    assert abs(blk.word_final_drop_fraction - 0.5) < 1e-9


def test_short_words_not_eligible_for_drop(cfg):
    x = synth.tone(120, 1.0)
    words = [_w(0.0, 0.2, "a"), _w(0.2, 0.4, "to")]  # both < min_word_duration_s 0.25
    blk = clarity.compute(words, [_seg(0.0, 0.4, "a to")], _tracks(x, cfg), cfg.clarity)
    assert blk.word_final_drop_count == 0
    assert blk.word_final_drop_fraction is None


def test_word_past_audio_end_is_skipped_not_raised(cfg):
    x = synth.tone(120, 1.0)
    words = [_w(0.0, 0.6, "ok"), _w(1.5, 2.2, "ghost")]  # second word entirely after the 1.0 s audio
    blk = clarity.compute(words, [_seg(0.0, 2.2, "ok ghost")], _tracks(x, cfg), cfg.clarity)
    assert blk.word_final_drop_count == 0
    assert abs(blk.word_final_drop_fraction - 0.0) < 1e-9  # one eligible word with data, not eaten


def test_low_confidence_words(cfg):
    x = synth.tone(120, 1.0)
    words = [_w(0.0, 0.3, "clear", 0.9), _w(0.3, 0.6, "mumble", 0.2), _w(0.6, 0.9, "ok", 0.6)]
    blk = clarity.compute(words, [_seg(0.0, 0.9, "clear mumble ok")], _tracks(x, cfg), cfg.clarity)
    assert [w.word for w in blk.low_conf_words] == ["mumble"]
    assert abs(blk.low_conf_word_fraction - 1 / 3) < 1e-9


def test_rushed_words_and_runs(cfg):
    x = synth.tone(120, 2.0)
    # "basically" (4 syl) in 0.3 s = 13.3 syl/s → rushed; three in a row form a run; a slow word breaks it.
    words = [
        _w(0.0, 0.3, "basically"), _w(0.3, 0.6, "actually"), _w(0.6, 0.9, "beautiful"),
        _w(0.9, 1.9, "slow"),
        _w(1.9, 2.0, "ok"),  # 1 syl / 0.1 s = 10 syl/s → rushed but alone
    ]
    blk = clarity.compute(words, [_seg(0.0, 2.0, "…")], _tracks(x, cfg), cfg.clarity)
    assert abs(blk.rushed_word_fraction - 4 / 5) < 1e-9
    assert len(blk.rushed_runs) == 1
    assert blk.rushed_runs[0].start_s == 0.0 and blk.rushed_runs[0].end_s == 0.9
    assert blk.rushed_runs[0].text == "basically actually beautiful"


def test_zero_duration_word_does_not_divide_by_zero(cfg):
    x = synth.tone(120, 1.0)
    words = [_w(0.5, 0.5, "glitch"), _w(0.5, 0.9, "fine")]
    blk = clarity.compute(words, [_seg(0.0, 1.0, "glitch fine")], _tracks(x, cfg), cfg.clarity)
    assert blk.rushed_word_fraction is not None  # computed over the one word with duration > 0
    assert np.isfinite(blk.rushed_word_fraction)


def test_segment_logprob_stats(cfg):
    x = synth.tone(120, 1.0)
    segs = [_seg(0.0, 0.5, "a", -0.2), _seg(0.5, 1.0, "b", -1.5)]
    blk = clarity.compute([_w(0.0, 0.5, "a"), _w(0.5, 1.0, "b")], segs, _tracks(x, cfg), cfg.clarity)
    assert abs(blk.segment_avg_logprob_mean + 0.85) < 1e-9
    assert abs(blk.low_logprob_segment_fraction - 0.5) < 1e-9


def test_empty_inputs(cfg):
    blk = clarity.compute([], [], _tracks(synth.tone(120, 1.0), cfg), cfg.clarity)
    assert blk.low_conf_word_fraction is None
    assert blk.word_final_drop_fraction is None
    assert blk.rushed_word_fraction is None
    assert blk.segment_avg_logprob_mean is None
    assert blk.low_logprob_segment_fraction is None
    assert blk.low_conf_words == [] and blk.eaten_words == [] and blk.rushed_runs == []

from tests import synth
from vocal_coach.analysis import quality, voice_quality
from vocal_coach.analysis.phrasing import Interval
from vocal_coach.analysis.tracks import extract_tracks


def _tracks(x, cfg, noise=1e-4):
    return extract_tracks(synth.to_sound(synth.with_noise_floor(x, level=noise)), cfg.analysis)


def _phrase(t0, t1):
    return Interval(start_s=t0, end_s=t1, duration_s=t1 - t0)


def test_clean_recording_not_low_confidence(cfg):
    x = synth.concat(synth.tone(120, 3.0), synth.silence(1.0))
    blk = quality.compute(_tracks(x, cfg), cfg.analysis, [_phrase(0.0, 3.0)])
    assert blk.low_confidence is False
    assert blk.reasons == []
    assert blk.snr_estimate_db > 15


def test_noisy_recording_flags_low_snr(cfg):
    x = synth.concat(synth.tone(120, 3.0, amp=0.05), synth.silence(1.0))
    blk = quality.compute(_tracks(x, cfg, noise=0.02), cfg.analysis, [_phrase(0.0, 3.0)])
    assert blk.low_confidence is True
    assert "low_snr" in blk.reasons


def test_silence_flags_no_voiced_speech(cfg):
    blk = quality.compute(_tracks(synth.silence(3.0), cfg), cfg.analysis, [])
    assert "no_voiced_speech" in blk.reasons
    assert blk.snr_estimate_db is None


def test_voice_quality_values_on_pure_tone(cfg):
    blk = voice_quality.compute(_tracks(synth.tone(120, 3.0), cfg), cfg.analysis, low_confidence=False)
    assert blk.hnr_db > 20
    assert 0 <= blk.jitter_local < 0.01
    assert 0 <= blk.shimmer_local < 0.05
    assert blk.low_confidence is False


def test_voice_quality_on_silence_is_null(cfg):
    blk = voice_quality.compute(_tracks(synth.silence(3.0), cfg), cfg.analysis, low_confidence=True)
    assert blk.hnr_db is None and blk.jitter_local is None and blk.shimmer_local is None
    assert blk.low_confidence is True

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


def _gated_speech(**kw):
    a = synth.am(synth.vowel(500, 1500, 120, 3.0, **kw), 4.0)
    # Gaps of EXACT digital zeros (noise-gated export): no with_noise_floor.
    return synth.concat(synth.silence(1.0), a, synth.silence(1.0), a, synth.silence(1.0))


def _quality_of_raw(x, cfg):
    tr = extract_tracks(synth.to_sound(x), cfg.analysis)
    return quality.compute(tr, cfg.analysis, [_phrase(1.0, 4.0), _phrase(5.0, 8.0)])


def test_digital_zero_gaps_give_zero_floor_and_no_flag(cfg):
    blk = _quality_of_raw(_gated_speech(), cfg)
    assert blk.noise_floor_db == 0.0
    assert 0 < blk.snr_estimate_db < 100
    assert blk.low_confidence is False
    assert blk.reasons == []


def test_digital_zero_gaps_loud_speech_not_flagged(cfg):
    blk = _quality_of_raw(_gated_speech(amp=0.9), cfg)
    assert blk.noise_floor_db == 0.0
    assert blk.low_confidence is False
    assert blk.reasons == []

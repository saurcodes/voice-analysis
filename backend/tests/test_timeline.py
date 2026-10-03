from tests import synth
from vocal_coach.analysis import timeline
from vocal_coach.analysis.tracks import extract_tracks


def _tracks(x, cfg):
    return extract_tracks(synth.to_sound(synth.with_noise_floor(x)), cfg.analysis)


def test_windows_cover_duration_and_track_pitch(cfg):
    x = synth.concat(synth.tone(100, 20.0), synth.tone(200, 20.0))
    blk = timeline.compute(_tracks(x, cfg), cfg.analysis)
    assert blk.window_s == 15
    assert len(blk.windows) == 3  # 0-15, 15-30, 30-40
    assert blk.windows[0].start_s == 0 and blk.windows[0].end_s == 15
    assert abs(blk.windows[2].end_s - 40.0) < 0.01
    assert abs(blk.windows[0].f0_median_hz - 100) < 2
    assert abs(blk.windows[2].f0_median_hz - 200) < 2
    assert blk.windows[0].f0_sd_st < 0.5
    assert blk.windows[1].f0_sd_st > 3  # contains the octave jump
    assert blk.windows[0].intensity_median_db is not None


def test_silent_window_has_null_f0(cfg):
    x = synth.concat(synth.tone(120, 15.0), synth.silence(15.0))
    blk = timeline.compute(_tracks(x, cfg), cfg.analysis)
    assert blk.windows[1].f0_median_hz is None
    assert blk.windows[1].f0_sd_st is None
    assert blk.windows[1].intensity_median_db is not None


def test_digital_silence_window_has_null_intensity(cfg):
    # Exact zeros (no noise floor): the clamped 0 dB frames are not real intensity.
    # The tone ends 0.1 s before the window edge: Praat's ~43 ms intensity window
    # (3.2 / pitch_floor) otherwise carries the tone's decay into window 1's first frames.
    x = synth.concat(synth.tone(120, 14.9), synth.silence(15.1))
    blk = timeline.compute(extract_tracks(synth.to_sound(x), cfg.analysis), cfg.analysis)
    assert blk.windows[1].intensity_median_db is None
    assert blk.windows[0].intensity_median_db is not None
    assert blk.windows[0].intensity_median_db > 0

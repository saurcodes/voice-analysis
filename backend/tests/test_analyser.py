import json
from pathlib import Path

from tests import synth
from tests.conftest import requires_ffmpeg
from vocal_coach.analysis.analyser import ANALYSER_VERSION, analyse_file, analyse_wav
from vocal_coach.analysis.schema import SCHEMA_VERSION, MetricsReport, SourceInfo
from vocal_coach.analysis.serialise import to_canonical_json
from vocal_coach.config import config_hash


def _speechlike(dur_each=3.0):
    a = synth.am(synth.vowel(500, 1500, 120, dur_each), 4.0)
    b = synth.am(synth.vowel(300, 2300, 130, dur_each), 4.5)
    return synth.with_noise_floor(synth.concat(a, synth.silence(0.6), b, synth.silence(1.2), a))


def _source(path: Path, dur: float) -> SourceInfo:
    return SourceInfo(file_name=path.name, drive_file_id=None, drive_modified_time=None,
                      content_sha256="x" * 64, duration_s=dur, original_channels=1, original_sample_rate=16000)


def test_analyse_wav_produces_full_report(cfg, tmp_path: Path):
    wav = synth.write_wav(tmp_path / "s.wav", _speechlike())
    report = analyse_wav(wav, cfg, _source(wav, 10.8))
    assert isinstance(report, MetricsReport)
    assert report.schema_version == SCHEMA_VERSION == "1.0"
    assert report.analyser_version == ANALYSER_VERSION == "0.1.0"
    assert report.config_hash == config_hash(cfg)
    assert report.phrasing.phrase_count == 3
    assert report.phrasing.long_pause_count_ge_1s == 1
    assert report.pitch.f0_median_hz is not None
    assert report.pace.syllable_count_est > 20
    assert len(report.timeline.windows) == 1
    assert report.recording_quality.low_confidence is False
    data = json.loads(to_canonical_json(report))
    assert set(data) == {"schema_version", "analyser_version", "config_hash", "source", "recording_quality",
                         "pitch", "phrasing", "pace", "intonation", "energy", "voice_quality",
                         "articulation", "timeline"}
    assert "class" in data["intonation"]["per_phrase"][0]


def test_silence_does_not_raise(cfg, tmp_path: Path):
    wav = synth.write_wav(tmp_path / "quiet.wav", synth.with_noise_floor(synth.silence(4.0)))
    report = analyse_wav(wav, cfg, _source(wav, 4.0))
    assert "no_voiced_speech" in report.recording_quality.reasons
    assert report.recording_quality.low_confidence is True
    assert report.pitch.f0_median_hz is None
    assert report.phrasing.phrase_count == 0
    to_canonical_json(report)  # must serialise without NaN errors


def test_too_short_recording_returns_empty_report(cfg, tmp_path: Path):
    wav = synth.write_wav(tmp_path / "short.wav", synth.tone(120, 0.5))
    report = analyse_wav(wav, cfg, _source(wav, 0.5))
    rq = report.recording_quality
    assert "too_short" in rq.reasons
    assert rq.low_confidence is True
    assert rq.noise_floor_db is None and rq.snr_estimate_db is None
    assert report.pitch.f0_median_hz is None and report.pitch.voiced_fraction == 0.0
    assert report.phrasing.phrase_count == 0
    assert report.pace.syllable_count_est == 0
    assert report.energy.final_vs_body_db is None
    assert report.voice_quality.low_confidence is True
    assert report.articulation.low_confidence is True
    assert report.articulation.vowel_space.vowel_space_area_hz2 is None
    assert report.timeline.windows == []
    to_canonical_json(report)


def test_tiny_recording_does_not_raise(cfg, tmp_path: Path):
    wav = synth.write_wav(tmp_path / "tiny.wav", synth.tone(120, 0.02))
    report = analyse_wav(wav, cfg, _source(wav, 0.02))
    assert "too_short" in report.recording_quality.reasons
    to_canonical_json(report)


def test_digital_silence_recording(cfg, tmp_path: Path):
    # Noise-gated export: EXACT zeros between and after speech, no with_noise_floor anywhere.
    a = synth.am(synth.vowel(500, 1500, 120, 3.0), 4.0)
    b = synth.am(synth.vowel(300, 2300, 130, 3.0), 4.5)
    x = synth.concat(a, synth.silence(1.0), b, synth.silence(20.0))
    wav = synth.write_wav(tmp_path / "gated.wav", x)
    report = analyse_wav(wav, cfg, _source(wav, 27.0))
    rq = report.recording_quality
    assert rq.noise_floor_db == 0.0
    assert 0 < rq.snr_estimate_db < 100
    assert rq.low_confidence is False
    assert report.articulation.syllable_peak_prominence_mean_db < 40
    for w in report.timeline.windows:
        assert w.intensity_median_db is None or w.intensity_median_db > 0
    assert report.energy.final_vs_body_db is not None
    to_canonical_json(report)


@requires_ffmpeg
def test_analyse_file_extracts_then_analyses(cfg, tmp_path: Path):
    src = synth.write_wav(tmp_path / "in.wav", _speechlike())
    report = analyse_file(src, cfg, work_dir=tmp_path / "work", drive_file_id="abc", drive_modified_time="2026-10-01T00:00:00Z")
    assert report.source.file_name == "in.wav"
    assert report.source.drive_file_id == "abc"
    assert report.source.original_sample_rate == 16000
    assert len(report.source.content_sha256) == 64
    assert (tmp_path / "work" / "in.wav").exists()


def test_analyse_wav_with_precomputed_tracks_is_identical(cfg, tmp_path: Path, monkeypatch):
    import parselmouth
    from vocal_coach.analysis import analyser as mod
    from vocal_coach.analysis.tracks import extract_tracks

    wav = synth.write_wav(tmp_path / "s.wav", _speechlike())
    src = _source(wav, 10.8)
    baseline = to_canonical_json(analyse_wav(wav, cfg, src))
    tracks = extract_tracks(parselmouth.Sound(str(wav)), cfg.analysis)

    def boom(*a, **k):  # analyse_wav must not re-extract when tracks are supplied
        raise AssertionError("extract_tracks called despite precomputed tracks")

    monkeypatch.setattr(mod, "extract_tracks", boom)
    assert to_canonical_json(analyse_wav(wav, cfg, src, tracks=tracks)) == baseline

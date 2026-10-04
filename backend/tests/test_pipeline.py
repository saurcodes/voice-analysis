import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tests import synth
from tests.conftest import requires_ffmpeg
from tests.fake_whisper import FakeWhisper, seg, word
from vocal_coach.pipeline import STAGES, JobRequest, run_pipeline
from vocal_coach.settings import Settings
from vocal_coach.storage import repo
from vocal_coach.storage.db import create_all, make_engine, make_session_factory


@pytest.fixture
def session():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    with make_session_factory(engine)() as s:
        yield s


def _speech():
    a = synth.am(synth.vowel(500, 1500, 120, 3.0), 4.0)
    return synth.with_noise_floor(synth.concat(a, synth.silence(0.6), a))


def _fake():
    return FakeWhisper([seg(0.0, 3.0, " So yes.", [word(0.0, 0.3, " So", 0.9), word(0.3, 0.8, " yes.", 0.9)])])


def _req(session, tmp_path, name="r.wav"):
    user = repo.upsert_user(session, "sub", None, None)
    job = repo.create_job(session, user.id)
    src = synth.write_wav(tmp_path / name, _speech())
    return JobRequest(job_id=job.id, user_id=user.id, source_path=src, file_name=name,
                      recorded_at=datetime(2026, 10, 1, tzinfo=timezone.utc)), user


@requires_ffmpeg
def test_pipeline_runs_all_stages_and_stores_analysis(cfg, session, tmp_path: Path):
    req, user = _req(session, tmp_path)
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    seen: list[tuple[str, int]] = []
    analysis_id = run_pipeline(req, cfg, settings, session, lambda s, p: seen.append((s, p)), whisper_model=_fake())
    assert [s for s, _ in seen] == list(STAGES)
    assert [p for _, p in seen] == sorted(p for _, p in seen) and seen[-1] == ("done", 100)
    row = repo.get_analysis(session, user.id, analysis_id)
    assert row.metrics_json["pitch"]["f0_median_hz"] is not None
    assert row.transcript_json["derived"]["filler_total"] == 1
    assert not (tmp_path / "data" / "work" / str(req.job_id)).exists()  # work dir cleaned up


@requires_ffmpeg
def test_pipeline_dedupes_same_file_same_config(cfg, session, tmp_path: Path):
    req1, user = _req(session, tmp_path, "a.wav")
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    first = run_pipeline(req1, cfg, settings, session, lambda s, p: None, whisper_model=_fake())
    job2 = repo.create_job(session, user.id)
    req2 = JobRequest(job_id=job2.id, user_id=user.id, source_path=req1.source_path, file_name="a.wav",
                      recorded_at=req1.recorded_at)
    seen = []
    second = run_pipeline(req2, cfg, settings, session, lambda s, p: seen.append(s), whisper_model=_fake())
    assert second == first
    assert seen == ["download", "extract", "done"]  # no analyse/transcribe on a dedupe hit


@requires_ffmpeg
def test_pipeline_survives_whisper_failure(cfg, session, tmp_path: Path):
    class Broken:
        def transcribe(self, *a, **k):
            raise RuntimeError("model exploded")

    req, user = _req(session, tmp_path)
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    analysis_id = run_pipeline(req, cfg, settings, session, lambda s, p: None, whisper_model=Broken())
    row = repo.get_analysis(session, user.id, analysis_id)
    assert row.transcript_json is None and row.metrics_json["pitch"] is not None


@requires_ffmpeg
def test_pipeline_bad_audio_raises_clear_error(cfg, session, tmp_path: Path):
    user = repo.upsert_user(session, "sub", None, None)
    job = repo.create_job(session, user.id)
    bad = tmp_path / "not_audio.mp3"
    bad.write_bytes(b"this is not audio")
    req = JobRequest(job_id=job.id, user_id=user.id, source_path=bad, file_name="not_audio.mp3",
                     recorded_at=datetime(2026, 10, 1, tzinfo=timezone.utc))
    with pytest.raises(Exception) as e:
        run_pipeline(req, cfg, Settings(_env_file=None, data_dir=tmp_path / "data"), session, lambda s, p: None, whisper_model=_fake())
    assert "ffmpeg" in str(e.value).lower() or "audio" in str(e.value).lower()

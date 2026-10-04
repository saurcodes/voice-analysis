from datetime import datetime, timezone
from pathlib import Path

import pytest

from tests import synth
from tests.conftest import requires_ffmpeg
from tests.fake_whisper import FakeWhisper, seg, word
from vocal_coach.config import load_config
from vocal_coach.jobs.runner import ERROR_MAX_CHARS, JobRunner, SyncExecutor, make_process_runner, run_job
from vocal_coach.pipeline import JobRequest
from vocal_coach.settings import Settings
from vocal_coach.storage import repo
from vocal_coach.storage.db import create_all, make_engine, make_session_factory


@pytest.fixture
def db(tmp_path):
    url = f"sqlite+pysqlite:///{tmp_path / 'jobs.db'}"
    engine = make_engine(url)
    create_all(engine)
    return url, make_session_factory(engine)


def _fake():
    return FakeWhisper([seg(0.0, 1.0, " Hi.", [word(0.0, 0.5, " Hi.", 0.9)])])


@requires_ffmpeg
def test_run_job_marks_done_with_analysis(db, tmp_path: Path, monkeypatch):
    url, factory = db
    with factory() as s:
        user = repo.upsert_user(s, "sub", None, None)
        job = repo.create_job(s, user.id)
    src = synth.write_wav(tmp_path / "r.wav", synth.with_noise_floor(synth.am(synth.vowel(500, 1500, 120, 3.0), 4.0)))
    req = JobRequest(job_id=job.id, user_id=user.id, source_path=src, file_name="r.wav",
                     recorded_at=datetime(2026, 10, 1, tzinfo=timezone.utc))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    run_job(req, url, None, whisper_model=_fake())
    with factory() as s:
        j = repo.get_job(s, user.id, job.id)
        assert (j.status, j.stage, j.progress_pct) == ("done", "done", 100)
        assert j.analysis_id is not None and repo.get_analysis(s, user.id, j.analysis_id) is not None


def test_run_job_marks_failed_on_bad_input(db, tmp_path: Path, monkeypatch):
    url, factory = db
    with factory() as s:
        user = repo.upsert_user(s, "sub", None, None)
        job = repo.create_job(s, user.id)
    bad = tmp_path / "x.mp3"
    bad.write_bytes(b"not audio")
    req = JobRequest(job_id=job.id, user_id=user.id, source_path=bad, file_name="x.mp3",
                     recorded_at=datetime(2026, 10, 1, tzinfo=timezone.utc))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    run_job(req, url, None, whisper_model=_fake())  # must not raise
    with factory() as s:
        j = repo.get_job(s, user.id, job.id)
        assert j.status == "failed" and j.error and len(j.error) <= ERROR_MAX_CHARS
        assert "ffmpeg" in j.error.lower() or "decode" in j.error.lower()


def test_run_job_failure_before_pipeline_is_recorded(db, tmp_path: Path):
    url, factory = db
    with factory() as s:
        user = repo.upsert_user(s, "sub", None, None)
        job = repo.create_job(s, user.id)
    req = JobRequest(job_id=job.id, user_id=user.id, source_path=tmp_path / "missing.wav", file_name="missing.wav",
                     recorded_at=datetime(2026, 10, 1, tzinfo=timezone.utc))
    run_job(req, url, None)
    with factory() as s:
        assert repo.get_job(s, user.id, job.id).status == "failed"


def test_sync_runner_submit_runs_job_fn(tmp_path):
    calls = []
    runner = JobRunner(Settings(_env_file=None, database_url="sqlite+pysqlite:///:memory:"), load_config(),
                       executor=SyncExecutor(), job_fn=lambda req, url, path: calls.append((req.file_name, url)))
    runner.start()
    req = JobRequest(job_id=__import__("uuid").uuid4(), user_id=__import__("uuid").uuid4(), source_path=tmp_path,
                     file_name="f.wav", recorded_at=datetime(2026, 10, 1, tzinfo=timezone.utc))
    fut = runner.submit(req)
    assert fut.done() and calls == [("f.wav", "sqlite+pysqlite:///:memory:")]
    runner.stop()


def test_make_process_runner_uses_spawn_pool():
    runner = make_process_runner(Settings(_env_file=None, job_workers=1), load_config())
    runner.start()
    try:
        ex = runner._executor
        assert type(ex).__name__ == "ProcessPoolExecutor" and ex._max_workers == 1
        assert ex._mp_context.get_start_method() == "spawn"
    finally:
        runner.stop()

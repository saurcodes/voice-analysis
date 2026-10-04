import os
import signal
import time
import uuid
from concurrent.futures.process import BrokenProcessPool
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tests import synth
from tests.conftest import requires_ffmpeg
from tests.fake_whisper import FakeWhisper, seg, word
from vocal_coach.config import load_config
from vocal_coach.jobs.runner import (
    ERROR_MAX_CHARS, JobRunner, RunnerUnavailable, SyncExecutor, make_process_runner, run_job,
)
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
        assert "/data/" not in j.error and str(tmp_path) not in j.error and "ffprobe" not in j.error


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


def crash_or_finish_job(req, database_url, config_path):
    """Module-level so the spawn pool can pickle it. 'crash*' files kill the worker outright."""
    if req.file_name.startswith("crash"):
        os.kill(os.getpid(), signal.SIGKILL)
    engine = make_engine(database_url)
    with make_session_factory(engine)() as s:
        repo.update_job(s, req.job_id, status="done", stage="done", progress_pct=100)
    engine.dispose()


def _wait_for_status(factory, user_id, job_id, wanted, timeout_s=30.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        with factory() as s:
            j = repo.get_job(s, user_id, job_id)
            if j.status in wanted:
                return j
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} never reached {wanted}")


def test_worker_crash_marks_job_failed_and_pool_is_rebuilt(db, tmp_path):
    url, factory = db
    with factory() as s:
        user = repo.upsert_user(s, "sub", None, None)
        crash_job, ok_job = repo.create_job(s, user.id), repo.create_job(s, user.id)
    runner = make_process_runner(Settings(_env_file=None, database_url=url, job_workers=1), load_config(),
                                 job_fn=crash_or_finish_job)
    runner.start()
    try:
        def req(job, name):
            return JobRequest(job_id=job.id, user_id=user.id, source_path=tmp_path / name, file_name=name,
                              recorded_at=datetime(2026, 10, 1, tzinfo=timezone.utc))

        fut = runner.submit(req(crash_job, "crash.wav"))
        assert isinstance(fut.exception(timeout=60), BrokenProcessPool)
        j = _wait_for_status(factory, user.id, crash_job.id, {"failed"})
        assert j.error.startswith("worker crashed")
        fut2 = runner.submit(req(ok_job, "fine.wav"))  # the broken pool is replaced transparently
        assert fut2.result(timeout=60) is None
        assert _wait_for_status(factory, user.id, ok_job.id, {"done", "failed"}).status == "done"
    finally:
        runner.stop()


class _AlwaysBroken:
    def submit(self, fn, /, *args, **kwargs):
        raise BrokenProcessPool("dead")

    def shutdown(self, wait=True, *, cancel_futures=False):
        return None


def test_submit_raises_runner_unavailable_after_one_rebuild(tmp_path):
    built = []

    def factory():
        built.append(_AlwaysBroken())
        return built[-1]

    runner = JobRunner(Settings(_env_file=None, database_url="sqlite+pysqlite:///:memory:"), load_config(),
                       executor=_AlwaysBroken(), executor_factory=factory, job_fn=lambda *a: None)
    req = JobRequest(job_id=uuid.uuid4(), user_id=uuid.uuid4(), source_path=tmp_path, file_name="f.wav",
                     recorded_at=datetime(2026, 10, 1, tzinfo=timezone.utc))
    with pytest.raises(RunnerUnavailable):
        runner.submit(req)
    assert len(built) == 1


@requires_ffmpeg
def test_run_job_on_already_terminal_job_keeps_its_error(db, tmp_path: Path, monkeypatch):
    """A restart marked the job failed while the worker was still running: keep 'server restarted'."""
    url, factory = db
    with factory() as s:
        user = repo.upsert_user(s, "sub", None, None)
        job = repo.create_job(s, user.id)
        repo.update_job(s, job.id, status="failed", error="server restarted")
    src = synth.write_wav(tmp_path / "r.wav", synth.with_noise_floor(synth.am(synth.vowel(500, 1500, 120, 3.0), 4.0)))
    req = JobRequest(job_id=job.id, user_id=user.id, source_path=src, file_name="r.wav",
                     recorded_at=datetime(2026, 10, 1, tzinfo=timezone.utc))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    run_job(req, url, None, whisper_model=_fake())  # must not raise
    with factory() as s:
        j = repo.get_job(s, user.id, job.id)
        assert (j.status, j.error) == ("failed", "server restarted")


def test_make_process_runner_uses_spawn_pool():
    runner = make_process_runner(Settings(_env_file=None, job_workers=1), load_config())
    runner.start()
    try:
        ex = runner._executor
        assert type(ex).__name__ == "ProcessPoolExecutor" and ex._max_workers == 1
        assert ex._mp_context.get_start_method() == "spawn"
    finally:
        runner.stop()

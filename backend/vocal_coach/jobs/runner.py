"""Job runner: hands JobRequests to an executor. Production uses a process pool (Task 4)."""
from __future__ import annotations

import functools
import logging
import multiprocessing
import threading
import traceback
import uuid
from concurrent.futures import Future, ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path
from typing import Any, Callable, Protocol

from sqlalchemy import Engine

from vocal_coach.config import AppConfig, load_config
from vocal_coach.pipeline import JobRequest, run_pipeline
from vocal_coach.settings import Settings, get_settings
from vocal_coach.storage import repo as _repo
from vocal_coach.storage.db import make_engine, make_session_factory
from vocal_coach.storage.paths import remove_upload

log = logging.getLogger(__name__)

JobFn = Callable[[JobRequest, str, str | None], None]  # (request, database_url, config_path)


class ExecutorLike(Protocol):
    def submit(self, fn: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Future: ...
    def shutdown(self, wait: bool = True, *, cancel_futures: bool = False) -> None: ...


class RunnerUnavailable(RuntimeError):
    """The executor is broken and could not be rebuilt; the job cannot be queued."""


class SyncExecutor:
    """Runs the callable immediately in the calling thread. Tests only."""

    def submit(self, fn, /, *args, **kwargs) -> Future:
        fut: Future = Future()
        try:
            fut.set_result(fn(*args, **kwargs))
        except BaseException as e:  # the fake job must surface failures like the real pool would
            fut.set_exception(e)
        return fut

    def shutdown(self, wait: bool = True, *, cancel_futures: bool = False) -> None:
        return None


class JobRunner:
    def __init__(self, settings: Settings, cfg: AppConfig, *, executor: ExecutorLike | None = None,
                 job_fn: JobFn | None = None, config_path: str | None = None,
                 executor_factory: Callable[[], ExecutorLike] | None = None):
        self._settings = settings
        self._cfg = cfg
        self._executor = executor
        self._executor_factory = executor_factory
        self._job_fn = job_fn
        self._config_path = config_path
        self._engine: Engine | None = None  # parent-side engine for recording worker crashes; created on first use
        self._lock = threading.Lock()

    def start(self) -> None:
        if self._executor is None:
            raise RuntimeError("no executor configured; the process pool is wired in jobs.runner.make_process_runner")

    def stop(self) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
        with self._lock:
            if self._engine is not None:
                self._engine.dispose()
                self._engine = None

    def submit(self, req: JobRequest) -> Future:
        assert self._executor is not None and self._job_fn is not None
        try:
            fut = self._submit_once(req)
        except BrokenProcessPool:
            # A worker died (OOM kill, SIGKILL, segfault in a native library): the pool refuses all new work.
            log.exception("process pool is broken; rebuilding it and retrying job %s once", req.job_id)
            self._rebuild()
            try:
                fut = self._submit_once(req)
            except BrokenProcessPool as e:
                raise RunnerUnavailable("job runner unavailable") from e
        fut.add_done_callback(functools.partial(self._on_done, req.job_id))
        return fut

    def _submit_once(self, req: JobRequest) -> Future:
        return self._executor.submit(self._job_fn, req, self._settings.database_url, self._config_path)

    def _rebuild(self) -> None:
        if self._executor_factory is None:
            raise RunnerUnavailable("job runner unavailable and cannot be rebuilt")
        old = self._executor
        self._executor = self._executor_factory()
        try:
            old.shutdown(wait=False, cancel_futures=True)
        except Exception:  # a broken pool may fail to shut down cleanly; the new pool is what matters
            log.exception("shutting down the broken pool failed")

    def _session_factory(self):
        with self._lock:
            if self._engine is None:
                self._engine = make_engine(self._settings.database_url)
            return make_session_factory(self._engine)

    def _on_done(self, job_id: uuid.UUID, fut: Future) -> None:
        """run_job never raises, so an exception here means the worker process itself died."""
        if fut.cancelled():
            return  # shutdown cancelled a queued job; fail_stale_jobs marks it at the next startup
        exc = fut.exception()
        if exc is None:
            return
        log.error("job %s: worker crashed", job_id, exc_info=exc)
        try:
            with self._session_factory()() as session:
                _repo.update_job(session, job_id, status="failed", error=f"worker crashed: {type(exc).__name__}")
        except ValueError:
            log.info("job %s already finished before the crash was recorded", job_id)
        except Exception:
            log.exception("job %s: could not record the worker crash", job_id)


ERROR_MAX_CHARS = 2000  # jobs.error is TEXT, but the UI shows one line; keep stack noise out of the row
MP_START_METHOD = "spawn"  # fork is unsafe with parselmouth/ctranslate2 threads already alive in the parent


def run_job(req: JobRequest, database_url: str, config_path: str | None, *, whisper_model=None) -> None:
    """Worker entry point: runs one job to completion and records its outcome. Never raises.

    Called in a separate process (spawned fresh, not forked), so it owns its own engine and
    session rather than reusing anything from the parent. The worker inherits the process
    environment (e.g. DATA_DIR) and reads it itself via `get_settings()`; the parent's in-memory
    `Settings` object is not available here — only `database_url` and `config_path` cross the
    process boundary as explicit arguments.
    """
    engine = None
    try:
        engine = make_engine(database_url)
        cfg = load_config(Path(config_path) if config_path else None)
        settings = get_settings().model_copy(update={"database_url": database_url})
        factory = make_session_factory(engine)
        with factory() as session:
            def progress(stage: str, pct: int) -> None:
                _repo.update_job(session, req.job_id, status="running", stage=stage, progress_pct=pct)

            analysis_id: uuid.UUID | None = None
            try:
                analysis_id = run_pipeline(req, cfg, settings, session, progress, whisper_model=whisper_model)
                _repo.update_job(
                    session, req.job_id, status="done", stage="done", progress_pct=100, analysis_id=analysis_id,
                )
            except Exception as e:
                session.rollback()
                if _repo.job_is_terminal(session, req.job_id):
                    # e.g. a restart marked it failed while this worker was still running: keep that
                    # outcome; the analysis (if one was stored) is logged so it can be recovered.
                    log.warning("job %s already terminal; analysis %s exists", req.job_id, analysis_id)
                    return
                log.error("job %s failed:\n%s", req.job_id, traceback.format_exc())
                _repo.update_job(session, req.job_id, status="failed", error=str(e)[:ERROR_MAX_CHARS])
                _release_upload(session, settings, req)
    except Exception:  # could not even reach the database/config: log, nothing else to do in a worker
        log.error("job %s could not be recorded:\n%s", req.job_id, traceback.format_exc())
    finally:
        if engine is not None:
            engine.dispose()


def _release_upload(session, settings: Settings, req: JobRequest) -> None:
    """After a pipeline failure, delete the upload unless an analysis or an unfinished job still needs it.

    Only the pipeline-failure path does this: a bad file fails the same way every time. Uploads of jobs
    failed by the infrastructure (worker crash, restart, runner unavailable) are kept so they can be retried."""
    if not req.source_sha256:
        return
    try:
        if not _repo.count_source_refs(session, req.user_id, req.source_sha256):
            removed = remove_upload(settings.data_dir, req.user_id, req.source_sha256)
            log.info("job %s: removed unreferenced upload %s", req.job_id, [p.name for p in removed])
    except Exception:  # cleanup is best effort; the job outcome is already recorded
        log.exception("job %s: could not remove the upload", req.job_id)


def make_process_runner(settings: Settings, cfg: AppConfig, config_path: str | None = None, *,
                        job_fn: JobFn = run_job) -> JobRunner:
    def factory() -> ProcessPoolExecutor:
        return ProcessPoolExecutor(
            max_workers=settings.job_workers, mp_context=multiprocessing.get_context(MP_START_METHOD),
        )

    return JobRunner(settings, cfg, executor=factory(), job_fn=job_fn, config_path=config_path,
                     executor_factory=factory)

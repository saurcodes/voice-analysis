"""Job runner: hands JobRequests to an executor. Production uses a process pool (Task 4)."""
from __future__ import annotations

import logging
import multiprocessing
import traceback
from concurrent.futures import Future, ProcessPoolExecutor
from pathlib import Path
from typing import Any, Callable, Protocol

from vocal_coach.config import AppConfig, load_config
from vocal_coach.pipeline import JobRequest, run_pipeline
from vocal_coach.settings import Settings, get_settings
from vocal_coach.storage import repo as _repo
from vocal_coach.storage.db import make_engine, make_session_factory

log = logging.getLogger(__name__)

JobFn = Callable[[JobRequest, str, str | None], None]  # (request, database_url, config_path)


class ExecutorLike(Protocol):
    def submit(self, fn: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Future: ...
    def shutdown(self, wait: bool = True, *, cancel_futures: bool = False) -> None: ...


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
                 job_fn: JobFn | None = None, config_path: str | None = None):
        self._settings = settings
        self._cfg = cfg
        self._executor = executor
        self._job_fn = job_fn
        self._config_path = config_path

    def start(self) -> None:
        if self._executor is None:
            raise RuntimeError("no executor configured; the process pool is wired in jobs.runner.make_process_runner")

    def stop(self) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)

    def submit(self, req: JobRequest) -> Future:
        assert self._executor is not None and self._job_fn is not None
        return self._executor.submit(self._job_fn, req, self._settings.database_url, self._config_path)


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

            try:
                analysis_id = run_pipeline(req, cfg, settings, session, progress, whisper_model=whisper_model)
                _repo.update_job(
                    session, req.job_id, status="done", stage="done", progress_pct=100, analysis_id=analysis_id,
                )
            except Exception as e:
                log.error("job %s failed:\n%s", req.job_id, traceback.format_exc())
                session.rollback()
                _repo.update_job(session, req.job_id, status="failed", error=str(e)[:ERROR_MAX_CHARS])
    except Exception:  # could not even reach the database/config: log, nothing else to do in a worker
        log.error("job %s could not be recorded:\n%s", req.job_id, traceback.format_exc())
    finally:
        if engine is not None:
            engine.dispose()


def make_process_runner(settings: Settings, cfg: AppConfig, config_path: str | None = None) -> JobRunner:
    pool = ProcessPoolExecutor(
        max_workers=settings.job_workers, mp_context=multiprocessing.get_context(MP_START_METHOD),
    )
    return JobRunner(settings, cfg, executor=pool, job_fn=run_job, config_path=config_path)

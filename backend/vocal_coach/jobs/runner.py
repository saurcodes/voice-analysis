"""Job runner: hands JobRequests to an executor. Production uses a process pool (Task 4)."""
from __future__ import annotations

import logging
from concurrent.futures import Future
from typing import Any, Callable, Protocol

from vocal_coach.config import AppConfig
from vocal_coach.pipeline import JobRequest
from vocal_coach.settings import Settings

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

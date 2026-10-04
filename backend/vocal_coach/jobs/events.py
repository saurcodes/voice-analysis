"""Server-sent events for one job: poll the row, emit on change, stop on a terminal status."""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import AsyncIterator

from vocal_coach.storage import repo

POLL_INTERVAL_S = 0.5  # spec §10
MAX_STREAM_S = 3600.0  # a 90-minute recording takes ~10 min; cap runaway streams at an hour
TERMINAL = {"done", "failed"}


def _event(name: str, data: dict) -> dict:
    return {"event": name, "data": json.dumps(data)}


async def job_events(session_factory, user_id: uuid.UUID, job_id: uuid.UUID, *,
                     poll_interval_s: float = POLL_INTERVAL_S, max_duration_s: float = MAX_STREAM_S) -> AsyncIterator[dict]:
    last_stage: str | None = None
    last_pct: int | None = None
    started = time.monotonic()
    while True:
        with session_factory() as session:  # one short session per poll (Plan 3 note)
            job = repo.get_job(session, user_id, job_id)
            snap = None if job is None else (job.status, job.stage, job.progress_pct, job.error, job.analysis_id)
        if snap is None:
            yield _event("error", {"message": "job not found"})
            return
        status, stage, pct, error, analysis_id = snap
        if stage != last_stage:
            yield _event("stage", {"stage": stage, "progress_pct": pct})
            last_stage = stage
        if pct != last_pct:
            yield _event("progress", {"progress_pct": pct, "stage": stage})
            last_pct = pct
        if status in TERMINAL:
            if status == "done":
                yield _event("done", {"analysis_id": str(analysis_id) if analysis_id else None})
            else:
                yield _event("error", {"message": error or "job failed"})
            return
        if time.monotonic() - started > max_duration_s:
            yield _event("error", {"message": "stream timeout"})
            return
        await asyncio.sleep(poll_interval_s)

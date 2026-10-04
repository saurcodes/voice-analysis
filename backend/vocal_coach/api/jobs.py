"""Job status and progress, including the SSE stream."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from vocal_coach.auth.deps import CurrentUser, get_current_user, get_session
from vocal_coach.jobs.events import job_events
from vocal_coach.storage import repo

router = APIRouter(tags=["jobs"])


class JobStatus(BaseModel):
    id: uuid.UUID
    status: str
    stage: str
    progress_pct: int
    error: str | None
    analysis_id: uuid.UUID | None


def _status(job) -> JobStatus:
    return JobStatus(id=job.id, status=job.status, stage=job.stage, progress_pct=job.progress_pct,
                     error=job.error, analysis_id=job.analysis_id)


@router.get("/jobs/{job_id}", response_model=JobStatus)
def get_job(job_id: uuid.UUID, user: CurrentUser = Depends(get_current_user), session: Session = Depends(get_session)):
    job = repo.get_job(session, user.id, job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    return _status(job)


@router.get("/jobs/{job_id}/events")
def job_event_stream(job_id: uuid.UUID, request: Request, user: CurrentUser = Depends(get_current_user),
                     session: Session = Depends(get_session)):
    if repo.get_job(session, user.id, job_id) is None:
        raise HTTPException(404, "job not found")
    return EventSourceResponse(job_events(request.app.state.session_factory, user.id, job_id))

"""Job status and progress, including the SSE stream, the jobs list and retry."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from vocal_coach.auth.deps import CurrentUser, get_current_user, get_session
from vocal_coach.jobs.events import job_events
from vocal_coach.jobs.runner import RunnerUnavailable
from vocal_coach.pipeline import JobRequest
from vocal_coach.storage import paths, repo

router = APIRouter(tags=["jobs"])

JobStatusName = Literal["queued", "running", "done", "failed"]
JobStage = Literal["download", "extract", "analyse", "transcribe", "coach", "done"]
JOBS_LIMIT_MIN, JOBS_LIMIT_MAX = 1, 200  # bounds for GET /jobs?limit=


class JobStatus(BaseModel):
    id: uuid.UUID
    status: JobStatusName
    stage: JobStage
    progress_pct: int
    error: str | None
    analysis_id: uuid.UUID | None
    file_name: str | None
    created_at: datetime


class JobId(BaseModel):
    job_id: uuid.UUID


def _status(job) -> JobStatus:
    return JobStatus(id=job.id, status=job.status, stage=job.stage, progress_pct=job.progress_pct,
                     error=job.error, analysis_id=job.analysis_id, file_name=job.file_name,
                     created_at=job.created_at)


def submit_or_503(request: Request, session: Session, job_id: uuid.UUID, req: JobRequest) -> None:
    """Hand the job to the runner; if the runner cannot take it, fail the job and answer 503."""
    try:
        request.app.state.runner.submit(req)
    except RunnerUnavailable:
        repo.update_job(session, job_id, status="failed", error="job runner unavailable")
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "job runner unavailable; try again")


@router.get("/jobs", response_model=list[JobStatus])
def list_jobs(
    status_filter: JobStatusName | None = Query(None, alias="status"),
    limit: int = Query(repo.JOB_PAGE_SIZE, ge=JOBS_LIMIT_MIN, le=JOBS_LIMIT_MAX),
    user: CurrentUser = Depends(get_current_user), session: Session = Depends(get_session),
):
    return [_status(j) for j in repo.list_jobs(session, user.id, status=status_filter, limit=limit)]


@router.get("/jobs/{job_id}", response_model=JobStatus)
def get_job(job_id: uuid.UUID, user: CurrentUser = Depends(get_current_user), session: Session = Depends(get_session)):
    job = repo.get_job(session, user.id, job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    return _status(job)


@router.post("/jobs/{job_id}/retry", status_code=status.HTTP_202_ACCEPTED, response_model=JobId,
             responses={404: {"description": "job not found"}, 409: {"description": "job is not finished"},
                        410: {"description": "the uploaded file is no longer stored"},
                        503: {"description": "job runner unavailable"}})
def retry_job(job_id: uuid.UUID, request: Request, user: CurrentUser = Depends(get_current_user),
              session: Session = Depends(get_session)):
    job = repo.get_job(session, user.id, job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    if job.status not in repo.TERMINAL_STATUSES:
        raise HTTPException(status.HTTP_409_CONFLICT, "job is not finished")
    found = paths.find_uploads(request.app.state.settings.data_dir, user.id, job.source_sha256) if job.source_sha256 else []
    if not found:
        raise HTTPException(status.HTTP_410_GONE, "the uploaded file is no longer stored; upload it again")
    new = repo.create_job(session, user.id, file_name=job.file_name, source_sha256=job.source_sha256,
                          recorded_at=job.recorded_at)
    req = JobRequest(job_id=new.id, user_id=user.id, source_path=found[0], file_name=job.file_name or found[0].name,
                     recorded_at=job.recorded_at or datetime.now(timezone.utc), source_sha256=job.source_sha256)
    submit_or_503(request, session, new.id, req)
    return JobId(job_id=new.id)


@router.get("/jobs/{job_id}/events")
def job_event_stream(job_id: uuid.UUID, request: Request, user: CurrentUser = Depends(get_current_user)):
    # No request-scoped session here: a dependency session would stay checked out for the whole
    # stream. The ownership check uses a short session; the generator opens one per poll.
    with request.app.state.session_factory() as s:
        exists = repo.get_job(s, user.id, job_id) is not None
    if not exists:
        raise HTTPException(404, "job not found")
    return EventSourceResponse(job_events(request.app.state.session_factory, user.id, job_id))

"""Job status and progress, including the SSE stream, the jobs list, retry and dismiss."""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from vocal_coach.auth.deps import CurrentUser, get_current_user, get_session
from vocal_coach.drive import cache as drive_cache
from vocal_coach.drive import service as drive_service
from vocal_coach.drive.client import DriveClient
from vocal_coach.drive.errors import DriveError, DriveNotConfigured, DriveNotConnected, DriveNotFound
from vocal_coach.jobs.events import job_events
from vocal_coach.jobs.runner import RunnerUnavailable
from vocal_coach.pipeline import JobRequest
from vocal_coach.storage import paths, repo

router = APIRouter(tags=["jobs"])

JobStatusName = Literal["queued", "running", "done", "failed"]
JobStage = Literal["download", "extract", "analyse", "transcribe", "coach", "done"]
JOBS_LIMIT_MIN, JOBS_LIMIT_MAX = 1, 200  # bounds for GET /jobs?limit=
DRIVE_GONE = "the Drive file is no longer available; analyse it again from the Drive tab"


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


async def _retry_drive_job(request: Request, session: Session, user: CurrentUser, job) -> JobId:
    """Retry a Drive-sourced job: refetch the file's current metadata (so a changed file downloads
    again under its new `modifiedTime`) before creating the new job. The Google calls run off the
    event loop; the old job is left `failed` either way."""
    settings = request.app.state.settings
    try:
        token = await asyncio.to_thread(drive_service.access_token_for, session, settings, user.id)
    except DriveNotConnected:
        raise HTTPException(status.HTTP_409_CONFLICT, "drive_not_connected") from None
    except DriveNotConfigured as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from None
    except DriveError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from None
    try:
        file = await asyncio.to_thread(DriveClient(token).get_file, job.drive_file_id)
    except DriveNotFound:
        raise HTTPException(status.HTTP_410_GONE, DRIVE_GONE) from None
    except DriveError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from None

    recorded_at = datetime.fromisoformat(file.modified_time.replace("Z", "+00:00"))
    path = drive_cache.cache_path(settings.data_dir, user.id, file)
    # The Job row keeps no speaker_context/LLM options, so a Drive retry cannot restore them; the
    # new job runs with coaching disabled, same as a fresh Drive analysis with no options passed.
    new = repo.create_job(session, user.id, file_name=file.name, source_sha256=None, recorded_at=recorded_at,
                          drive_file_id=file.id, drive_modified_time=file.modified_time)
    req = JobRequest(job_id=new.id, user_id=user.id, source_path=path, file_name=file.name,
                     recorded_at=recorded_at, drive_file_id=file.id, drive_modified_time=file.modified_time,
                     speaker_context=None, llm_enabled=False, llm_model=None, source_sha256=None)
    submit_or_503(request, session, new.id, req)
    return JobId(job_id=new.id)


@router.post("/jobs/{job_id}/retry", status_code=status.HTTP_202_ACCEPTED, response_model=JobId,
             responses={status.HTTP_404_NOT_FOUND: {"description": "job not found"},
                        status.HTTP_409_CONFLICT: {"description": "job is not finished, or Drive is not connected"},
                        status.HTTP_410_GONE: {"description": "the uploaded file, or the Drive file, is no longer available"},
                        status.HTTP_502_BAD_GATEWAY: {"description": "Google Drive returned an error"},
                        status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "job runner unavailable, or Drive is not configured"}})
async def retry_job(job_id: uuid.UUID, request: Request, user: CurrentUser = Depends(get_current_user),
                    session: Session = Depends(get_session)):
    job = repo.get_job(session, user.id, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    if job.status not in repo.TERMINAL_STATUSES:
        raise HTTPException(status.HTTP_409_CONFLICT, "job is not finished")
    if job.drive_file_id is not None:
        return await _retry_drive_job(request, session, user, job)
    if job.source_sha256 is None:  # legacy Drive job with no stored file id: nothing left to retry from
        raise HTTPException(status.HTTP_410_GONE, DRIVE_GONE)
    found = paths.find_upload(request.app.state.settings.data_dir, user.id, job.source_sha256)
    if found is None:
        raise HTTPException(status.HTTP_410_GONE, "the uploaded file is no longer stored; upload it again")
    new = repo.create_job(session, user.id, file_name=job.file_name, source_sha256=job.source_sha256,
                          recorded_at=job.recorded_at)
    req = JobRequest(job_id=new.id, user_id=user.id, source_path=found, file_name=job.file_name or found.name,
                     recorded_at=job.recorded_at or datetime.now(timezone.utc), source_sha256=job.source_sha256)
    submit_or_503(request, session, new.id, req)
    return JobId(job_id=new.id)


@router.delete("/jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT,
               responses={status.HTTP_404_NOT_FOUND: {
                   "description": "job not found, not owned by the caller, or not yet finished"}})
def dismiss_job(job_id: uuid.UUID, user: CurrentUser = Depends(get_current_user),
                session: Session = Depends(get_session)):
    if not repo.delete_job(session, user.id, job_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/jobs/{job_id}/events")
def job_event_stream(job_id: uuid.UUID, request: Request, user: CurrentUser = Depends(get_current_user)):
    # No request-scoped session here: a dependency session would stay checked out for the whole
    # stream. The ownership check uses a short session; the generator opens one per poll.
    with request.app.state.session_factory() as s:
        exists = repo.get_job(s, user.id, job_id) is not None
    if not exists:
        raise HTTPException(404, "job not found")
    return EventSourceResponse(job_events(request.app.state.session_factory, user.id, job_id))

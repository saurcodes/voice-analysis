"""Job status and progress (SSE arrives in Task 6)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from vocal_coach.auth.deps import CurrentUser, get_current_user, get_session
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

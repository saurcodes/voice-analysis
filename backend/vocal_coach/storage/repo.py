"""All database access, strictly scoped by user_id. Rows the user does not own are None.

Exception: `update_job` is called by the job runner, which owns job state and has no user in hand; reads (`get_job`) remain scoped."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from vocal_coach.storage.models import JOB_STATUSES, Analysis, Job, User

JOB_UPDATABLE = frozenset({"status", "stage", "progress_pct", "error", "analysis_id"})
STALE_STATUSES = ("queued", "running")  # a restart means these can never finish


def upsert_user(session: Session, keycloak_sub: str, email: str | None, username: str | None) -> User:
    user = session.scalar(select(User).where(User.keycloak_sub == keycloak_sub))
    if user is None:
        user = User(keycloak_sub=keycloak_sub, email=email, username=username)
        session.add(user)
    else:
        user.email = email
        user.username = username
    session.commit()
    return user


def find_analysis(
    session: Session, user_id: uuid.UUID, content_sha256: str, config_hash: str, analyser_version: str,
) -> Analysis | None:
    return session.scalar(
        select(Analysis).where(Analysis.user_id == user_id, Analysis.content_sha256 == content_sha256,
                               Analysis.config_hash == config_hash, Analysis.analyser_version == analyser_version)
    )


def create_analysis(
    session: Session, user_id: uuid.UUID, *, file_name: str, drive_file_id: str | None, content_sha256: str,
    recorded_at: datetime, analyser_version: str, config_hash: str, metrics_json: dict,
    transcript_json: dict | None = None, speaker_context: str | None = None,
) -> Analysis:
    row = Analysis(
        user_id=user_id, file_name=file_name, drive_file_id=drive_file_id, content_sha256=content_sha256,
        recorded_at=recorded_at, analyser_version=analyser_version, config_hash=config_hash,
        metrics_json=metrics_json, transcript_json=transcript_json, speaker_context=speaker_context,
    )
    session.add(row)
    session.commit()
    return row


def list_analyses(session: Session, user_id: uuid.UUID) -> list[Analysis]:
    return list(session.scalars(select(Analysis).where(Analysis.user_id == user_id).order_by(Analysis.recorded_at.desc(), Analysis.id.desc())))


def get_analysis(session: Session, user_id: uuid.UUID, analysis_id: uuid.UUID) -> Analysis | None:
    return session.scalar(select(Analysis).where(Analysis.user_id == user_id, Analysis.id == analysis_id))


def delete_analysis(session: Session, user_id: uuid.UUID, analysis_id: uuid.UUID) -> bool:
    row = get_analysis(session, user_id, analysis_id)
    if row is None:
        return False
    session.delete(row)
    session.commit()
    return True


def set_coaching(
    session: Session, user_id: uuid.UUID, analysis_id: uuid.UUID, *,
    speaker_context: str | None, coaching_json: dict | None, coaching_warnings: list | None,
) -> Analysis | None:
    row = get_analysis(session, user_id, analysis_id)
    if row is None:
        return None
    row.speaker_context = speaker_context
    row.coaching_json = coaching_json
    row.coaching_warnings = coaching_warnings
    session.commit()
    return row


def create_job(session: Session, user_id: uuid.UUID, stage: str = "queued") -> Job:
    job = Job(user_id=user_id, status="queued", stage=stage, progress_pct=0)
    session.add(job)
    session.commit()
    return job


def update_job(session: Session, job_id: uuid.UUID, **fields) -> Job | None:
    unknown = set(fields) - JOB_UPDATABLE
    if unknown:
        raise ValueError(f"unknown job fields: {sorted(unknown)}")
    if "status" in fields and fields["status"] not in JOB_STATUSES:
        raise ValueError(f"invalid job status {fields['status']!r}; expected one of {JOB_STATUSES}")
    job = session.get(Job, job_id)
    if job is None:
        return None
    for k, v in fields.items():
        setattr(job, k, v)
    session.commit()
    return job


def get_job(session: Session, user_id: uuid.UUID, job_id: uuid.UUID) -> Job | None:
    return session.scalar(select(Job).where(Job.user_id == user_id, Job.id == job_id))


def fail_stale_jobs(session: Session, message: str = "server restarted") -> int:
    result = session.execute(
        update(Job).where(Job.status.in_(STALE_STATUSES)).values(status="failed", error=message)
    )
    session.commit()
    return int(result.rowcount or 0)

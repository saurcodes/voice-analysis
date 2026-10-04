"""All database access, strictly scoped by user_id. Rows the user does not own are None.

Exception: `update_job` is called by the job runner, which owns job state and has no user in hand; reads (`get_job`) remain scoped.

Every writer leaves the session usable: a failed commit is rolled back before the error propagates."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from vocal_coach.storage.models import JOB_STATUSES, Analysis, Job, User

JOB_UPDATABLE = frozenset({"status", "stage", "progress_pct", "error", "analysis_id"})
STALE_STATUSES = ("queued", "running")  # a restart means these can never finish
TERMINAL_STATUSES = ("done", "failed")  # a finished job's status never changes again
PROGRESS_MIN = 0  # progress_pct is a percentage: 0 … 100 inclusive
PROGRESS_MAX = 100
FIRST_JOB_STAGE = "download"  # first pipeline stage (spec §10)
SUMMARY_PAGE_SIZE = 50  # default page for GET /analyses summaries
SUMMARY_FIRST_OFFSET = 0
ROWS_PER_ID = 1  # a scoped delete by primary key removes exactly one row when it succeeds


def _commit(session: Session) -> None:
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise


def upsert_user(session: Session, keycloak_sub: str, email: str | None, username: str | None) -> User:
    user = session.scalar(select(User).where(User.keycloak_sub == keycloak_sub))
    if user is None:
        user = User(keycloak_sub=keycloak_sub, email=email, username=username)
        session.add(user)
        try:
            session.commit()
            return user
        except IntegrityError:
            # Concurrent first login: another request inserted this sub between our select and insert.
            session.rollback()
            user = session.scalar(select(User).where(User.keycloak_sub == keycloak_sub))
            if user is None:
                raise
    user.email = email
    user.username = username
    _commit(session)
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
    """Insert an analysis. If the same (user, file, config, analyser version) already exists — e.g. the
    same file submitted from two tabs — the existing row is returned instead."""
    row = Analysis(
        user_id=user_id, file_name=file_name, drive_file_id=drive_file_id, content_sha256=content_sha256,
        recorded_at=recorded_at, analyser_version=analyser_version, config_hash=config_hash,
        metrics_json=metrics_json, transcript_json=transcript_json, speaker_context=speaker_context,
    )
    session.add(row)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = find_analysis(session, user_id, content_sha256, config_hash, analyser_version)
        if existing is None:  # some other constraint failed; nothing to dedupe to
            raise
        return existing
    except Exception:
        session.rollback()
        raise
    return row


def list_analyses(session: Session, user_id: uuid.UUID) -> list[Analysis]:
    return list(session.scalars(select(Analysis).where(Analysis.user_id == user_id).order_by(Analysis.recorded_at.desc(), Analysis.id.desc())))


class AnalysisSummary(BaseModel):
    """One analyses-list row: scalar columns plus a few headline metrics, without the JSON blobs."""
    id: uuid.UUID
    file_name: str
    drive_file_id: str | None
    recorded_at: datetime
    analysed_at: datetime
    analyser_version: str
    config_hash: str
    has_transcript: bool
    has_coaching: bool
    f0_median_hz: float | None
    f0_range_st: float | None
    flat_pct: float | None
    pauses_per_min: float | None
    articulation_rate_syl_per_sec: float | None
    trailing_off_count: int | None
    fillers_per_min: float | None


# Tuple paths compile to a single JSON_EXTRACT(col, '$."a"."b"') on SQLite (JSON1) and
# `col #>> '{a,b}'` on Postgres JSONB, then CAST to the numeric type; missing keys and JSON null give NULL.
_SUMMARY_COLUMNS = (
    Analysis.id, Analysis.file_name, Analysis.drive_file_id, Analysis.recorded_at, Analysis.analysed_at,
    Analysis.analyser_version, Analysis.config_hash,
    Analysis.transcript_json.is_not(None).label("has_transcript"),
    Analysis.coaching_json.is_not(None).label("has_coaching"),
    Analysis.metrics_json[("pitch", "f0_median_hz")].as_float().label("f0_median_hz"),
    Analysis.metrics_json[("pitch", "f0_range_st")].as_float().label("f0_range_st"),
    Analysis.metrics_json[("intonation", "flat_pct")].as_float().label("flat_pct"),
    Analysis.metrics_json[("phrasing", "pauses_per_min")].as_float().label("pauses_per_min"),
    Analysis.metrics_json[("pace", "articulation_rate_syl_per_sec")].as_float().label("articulation_rate_syl_per_sec"),
    Analysis.metrics_json[("energy", "trailing_off_count")].as_integer().label("trailing_off_count"),
    Analysis.transcript_json[("derived", "fillers_per_min")].as_float().label("fillers_per_min"),
)


def list_analysis_summaries(
    session: Session, user_id: uuid.UUID, *, limit: int = SUMMARY_PAGE_SIZE, offset: int = SUMMARY_FIRST_OFFSET,
) -> list[AnalysisSummary]:
    """Newest first, paginated, one query; never loads metrics/transcript/coaching blobs."""
    stmt = (select(*_SUMMARY_COLUMNS).where(Analysis.user_id == user_id)
            .order_by(Analysis.recorded_at.desc(), Analysis.id.desc()).limit(limit).offset(offset))
    return [AnalysisSummary.model_validate(row._mapping) for row in session.execute(stmt)]


def get_analyses(session: Session, user_id: uuid.UUID, ids: list[uuid.UUID]) -> list[Analysis]:
    """The user's analyses among `ids` (foreign or unknown ids dropped, duplicates collapsed), oldest first."""
    unique_ids = list(dict.fromkeys(ids))
    if not unique_ids:
        return []
    return list(session.scalars(
        select(Analysis).where(Analysis.user_id == user_id, Analysis.id.in_(unique_ids))
        .order_by(Analysis.recorded_at, Analysis.id)
    ))


def get_analysis(session: Session, user_id: uuid.UUID, analysis_id: uuid.UUID) -> Analysis | None:
    return session.scalar(
        select(Analysis).where(Analysis.user_id == user_id, Analysis.id == analysis_id)
        .execution_options(populate_existing=True)
    )


def delete_analysis(session: Session, user_id: uuid.UUID, analysis_id: uuid.UUID) -> bool:
    result = session.execute(delete(Analysis).where(Analysis.user_id == user_id, Analysis.id == analysis_id))
    _commit(session)
    return result.rowcount == ROWS_PER_ID


def count_analyses_with_sha(session: Session, user_id: uuid.UUID, content_sha256: str) -> int:
    return int(session.scalar(select(func.count()).select_from(Analysis).where(
        Analysis.user_id == user_id, Analysis.content_sha256 == content_sha256)) or 0)


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
    _commit(session)
    return row


def create_job(session: Session, user_id: uuid.UUID, stage: str = FIRST_JOB_STAGE) -> Job:
    job = Job(user_id=user_id, status="queued", stage=stage, progress_pct=PROGRESS_MIN)
    session.add(job)
    _commit(session)
    return job


def update_job(session: Session, job_id: uuid.UUID, **fields) -> Job | None:
    unknown = set(fields) - JOB_UPDATABLE
    if unknown:
        raise ValueError(f"unknown job fields: {sorted(unknown)}")
    if "status" in fields and fields["status"] not in JOB_STATUSES:
        raise ValueError(f"invalid job status {fields['status']!r}; expected one of {JOB_STATUSES}")
    if "progress_pct" in fields and not PROGRESS_MIN <= fields["progress_pct"] <= PROGRESS_MAX:
        raise ValueError(f"progress_pct must be in [{PROGRESS_MIN}, {PROGRESS_MAX}], got {fields['progress_pct']!r}")
    job = session.get(Job, job_id, populate_existing=True)
    if job is None:
        return None
    if job.status in TERMINAL_STATUSES and "status" in fields and fields["status"] != job.status:
        raise ValueError("job is terminal")
    for k, v in fields.items():
        setattr(job, k, v)
    _commit(session)
    return job


def get_job(session: Session, user_id: uuid.UUID, job_id: uuid.UUID) -> Job | None:
    # populate_existing: a poller holding one session must see the runner's committed updates.
    return session.scalar(
        select(Job).where(Job.user_id == user_id, Job.id == job_id).execution_options(populate_existing=True)
    )


def fail_stale_jobs(session: Session, message: str = "server restarted") -> int:
    result = session.execute(
        update(Job).where(Job.status.in_(STALE_STATUSES)).values(status="failed", error=message)
    )
    _commit(session)
    return int(result.rowcount or 0)

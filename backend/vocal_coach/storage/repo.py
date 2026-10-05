"""All database access, strictly scoped by user_id. Rows the user does not own are None.

Exception: `update_job` is called by the job runner, which owns job state and has no user in hand; reads (`get_job`) remain scoped.

Every writer leaves the session usable: a failed commit is rolled back before the error propagates."""
from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from vocal_coach.storage.models import JOB_STATUSES, Analysis, DriveConnection, Job, User, utcnow

JOB_UPDATABLE = frozenset({"status", "stage", "progress_pct", "error", "analysis_id"})
STALE_STATUSES = ("queued", "running")  # a restart means these can never finish
TERMINAL_STATUSES = ("done", "failed")  # a finished job's status never changes again
PROGRESS_MIN = 0  # progress_pct is a percentage: 0 … 100 inclusive
PROGRESS_MAX = 100
FIRST_JOB_STAGE = "download"  # first pipeline stage (spec §10)
SUMMARY_PAGE_SIZE = 50  # default page for GET /analyses summaries
JOB_PAGE_SIZE = 50  # default page for GET /jobs
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


def get_drive_connection(session: Session, user_id: uuid.UUID) -> DriveConnection | None:
    # populate_existing: a refresh-then-retry path and the caller that just upserted must see the latest row.
    return session.scalar(
        select(DriveConnection).where(DriveConnection.user_id == user_id).execution_options(populate_existing=True)
    )


def upsert_drive_connection(
    session: Session, user_id: uuid.UUID, *, encrypted_refresh_token: bytes, google_email: str | None,
) -> DriveConnection:
    """Link (or re-link) this user's Drive. A re-link replaces the token and email and resets
    `connected_at` to now, since a new refresh token means a new consent grant."""
    row = session.get(DriveConnection, user_id, populate_existing=True)
    if row is None:
        row = DriveConnection(user_id=user_id, encrypted_refresh_token=encrypted_refresh_token, google_email=google_email)
        session.add(row)
    else:
        row.encrypted_refresh_token = encrypted_refresh_token
        row.google_email = google_email
        row.connected_at = utcnow()
    _commit(session)
    return row


def delete_drive_connection(session: Session, user_id: uuid.UUID) -> bool:
    result = session.execute(delete(DriveConnection).where(DriveConnection.user_id == user_id))
    _commit(session)
    return result.rowcount == ROWS_PER_ID


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
    transcript_json: dict | None = None, speaker_context: str | None = None, source_sha256: str | None = None,
) -> Analysis:
    """Insert an analysis. If the same (user, file, config, analyser version) already exists — e.g. the
    same file submitted from two tabs — the existing row is returned instead."""
    row = Analysis(
        user_id=user_id, file_name=file_name, drive_file_id=drive_file_id, content_sha256=content_sha256,
        recorded_at=recorded_at, analyser_version=analyser_version, config_hash=config_hash,
        metrics_json=metrics_json, transcript_json=transcript_json, speaker_context=speaker_context,
        source_sha256=source_sha256,
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


def count_source_refs(session: Session, user_id: uuid.UUID, source_sha256: str) -> int:
    """How many things still need the uploaded file `source_sha256`: the user's analyses made from it plus
    their unfinished jobs for it. Zero means the upload can be deleted."""
    analyses = session.scalar(select(func.count()).select_from(Analysis).where(
        Analysis.user_id == user_id, Analysis.source_sha256 == source_sha256))
    jobs = session.scalar(select(func.count()).select_from(Job).where(
        Job.user_id == user_id, Job.source_sha256 == source_sha256, Job.status.not_in(TERMINAL_STATUSES)))
    return int(analyses) + int(jobs)  # COUNT(*) is never NULL


def count_drive_refs(session: Session, user_id: uuid.UUID, drive_file_id: str) -> int:
    """How many things still need this Drive file's cached download: the user's analyses that
    reference it plus their unfinished (queued or running) jobs for it. Zero means its cached
    download(s) can be removed (`vocal_coach.drive.cache.remove_for_file`)."""
    analyses = session.scalar(select(func.count()).select_from(Analysis).where(
        Analysis.user_id == user_id, Analysis.drive_file_id == drive_file_id))
    jobs = session.scalar(select(func.count()).select_from(Job).where(
        Job.user_id == user_id, Job.drive_file_id == drive_file_id, Job.status.not_in(TERMINAL_STATUSES)))
    return int(analyses) + int(jobs)  # COUNT(*) is never NULL


def _locking_enabled(session: Session) -> bool:
    """Postgres row-locks taken with `SELECT ... FOR UPDATE` are what make the delete-vs-retry
    serialisation below work; SQLite has no row locking (and the tests that run against it are
    single-threaded), so callers skip the lock there."""
    return session.bind.dialect.name != "sqlite"


def _lock_analyses_sharing(session: Session, user_id: uuid.UUID, column, value) -> None:
    """Takes `SELECT ... FOR UPDATE` on the user's analyses rows where `column == value`, skipped on
    SQLite. Shared by `lock_source_refs` and `delete_analysis_and_count_refs`'s own locking of the
    same two columns (`source_sha256`, `drive_file_id`)."""
    if not _locking_enabled(session):
        return
    session.execute(select(Analysis.id).where(Analysis.user_id == user_id, column == value).with_for_update())


def lock_source_refs(session: Session, user_id: uuid.UUID, source_sha256: str) -> None:
    """Serialises a retry against a concurrent delete of an analysis made from the same upload; the
    caller checks `paths.find_upload` after this, inside the same transaction."""
    _lock_analyses_sharing(session, user_id, Analysis.source_sha256, source_sha256)


def delete_analysis_and_count_refs(
    session: Session, user_id: uuid.UUID, analysis_id: uuid.UUID, source_sha256: str | None,
    drive_file_id: str | None = None, *,
    on_unreferenced: Callable[[], None] | None = None,
    on_drive_unreferenced: Callable[[], None] | None = None,
) -> tuple[bool, int, int]:
    """Delete one analysis and, in the same transaction, count what still references its upload
    (`source_sha256`) and its Drive source (`drive_file_id`).

    Doing this under one transaction (instead of `delete_analysis` then separate `count_source_refs`/
    `count_drive_refs` calls, which used to commit and release in between) closes a race with a
    concurrent retry that creates a new job for the same upload: on Postgres, the user's analyses rows
    sharing `source_sha256` (and, separately, those sharing `drive_file_id`) are locked with
    `SELECT ... FOR UPDATE` before the delete and the counts, so a concurrent transaction touching
    those same rows (another delete of an analysis made from the same bytes or the same Drive file, or
    a retry taking the same lock via `lock_source_refs`) serialises against this one rather than
    interleaving with it. SQLite has no row locking (and the tests that run against it are
    single-threaded), so the locks are skipped there.

    `on_unreferenced` (called when `source_sha256` is set and the post-delete count is zero) and
    `on_drive_unreferenced` (same, for `drive_file_id`) run BEFORE the commit, while the lock is still
    held, so the upload file (or Drive cache entry) is removed before the row that made it
    unreferenced is visible to anyone else. If a callback raises, the transaction is rolled back (the
    delete is not committed) and the error is re-raised.
    """
    if source_sha256 is not None:
        _lock_analyses_sharing(session, user_id, Analysis.source_sha256, source_sha256)
    if drive_file_id is not None:
        _lock_analyses_sharing(session, user_id, Analysis.drive_file_id, drive_file_id)
    result = session.execute(delete(Analysis).where(Analysis.user_id == user_id, Analysis.id == analysis_id))
    deleted = result.rowcount == ROWS_PER_ID
    refs = count_source_refs(session, user_id, source_sha256) if source_sha256 else 0
    drive_refs = count_drive_refs(session, user_id, drive_file_id) if drive_file_id else 0
    try:
        if source_sha256 is not None and not refs and on_unreferenced is not None:
            on_unreferenced()
        if drive_file_id is not None and not drive_refs and on_drive_unreferenced is not None:
            on_drive_unreferenced()
    except Exception:
        session.rollback()
        raise
    _commit(session)
    return deleted, refs, drive_refs


def previous_analysis(
    session: Session, user_id: uuid.UUID, *, before: datetime, exclude_id: uuid.UUID,
) -> Analysis | None:
    """The comparison baseline for coaching: the user's newest analysis with `recorded_at < before`,
    or (when none exists, e.g. two analyses share the same `recorded_at`) the newest with
    `recorded_at == before` that is not `exclude_id`. None when neither exists."""
    row = session.scalar(
        select(Analysis).where(Analysis.user_id == user_id, Analysis.recorded_at < before)
        .order_by(Analysis.recorded_at.desc(), Analysis.analysed_at.desc(), Analysis.id.desc())
        .execution_options(populate_existing=True)
    )
    if row is not None:
        return row
    return session.scalar(
        select(Analysis).where(Analysis.user_id == user_id, Analysis.recorded_at == before,
                               Analysis.id != exclude_id)
        .order_by(Analysis.recorded_at.desc(), Analysis.analysed_at.desc(), Analysis.id.desc())
        .execution_options(populate_existing=True)
    )


def set_speaker_context(session: Session, user_id: uuid.UUID, analysis_id: uuid.UUID, text: str | None) -> Analysis | None:
    row = get_analysis(session, user_id, analysis_id)
    if row is None:
        return None
    row.speaker_context = text
    _commit(session)
    return row


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


def create_job(session: Session, user_id: uuid.UUID, *, file_name: str | None = None,
               source_sha256: str | None = None, recorded_at: datetime | None = None,
               stage: str = FIRST_JOB_STAGE, drive_file_id: str | None = None,
               drive_modified_time: str | None = None) -> Job:
    job = Job(user_id=user_id, status="queued", stage=stage, progress_pct=PROGRESS_MIN,
              file_name=file_name, source_sha256=source_sha256, recorded_at=recorded_at,
              drive_file_id=drive_file_id, drive_modified_time=drive_modified_time)
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


def delete_job(session: Session, user_id: uuid.UUID, job_id: uuid.UUID) -> bool:
    """Dismiss a job: deletes it only when it belongs to `user_id` and has finished (`done`/`failed`).
    A non-terminal or unknown-or-foreign job is left alone and the caller gets False either way, so
    the API cannot distinguish "not yours" from "not finished" from "does not exist"."""
    result = session.execute(
        delete(Job).where(Job.user_id == user_id, Job.id == job_id, Job.status.in_(TERMINAL_STATUSES))
    )
    _commit(session)
    return result.rowcount == ROWS_PER_ID


def list_jobs(session: Session, user_id: uuid.UUID, *, status: str | None = None,
              limit: int = JOB_PAGE_SIZE) -> list[Job]:
    """The user's jobs, newest first, optionally filtered by status."""
    stmt = select(Job).where(Job.user_id == user_id)
    if status is not None:
        stmt = stmt.where(Job.status == status)
    return list(session.scalars(stmt.order_by(Job.created_at.desc(), Job.id.desc()).limit(limit)))


def job_is_terminal(session: Session, job_id: uuid.UUID) -> bool:
    """Runner-side check (unscoped, like `update_job`): has this job already finished?"""
    job = session.get(Job, job_id, populate_existing=True)
    return job is not None and job.status in TERMINAL_STATUSES


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

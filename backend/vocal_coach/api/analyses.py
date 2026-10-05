"""Upload, list, detail, raw download and delete for a user's analyses.

Upload size is enforced in three places: a declared `Content-Length` over the cap is rejected
before the body is read; the request's ASGI receive is wrapped so a body (chunked, with no
`Content-Length`) that grows past the cap plus some multipart slack is cut off with a 413 while
Starlette's `request.form()` is still spooling it; and `_store_upload` counts the file part's
exact bytes as the final check.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.responses import Response as RawResponse
from pydantic import BaseModel, Field, StringConstraints, ValidationError
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile as StarletteUploadFile

from vocal_coach.analysis.schema import MetricsReport
from vocal_coach.auth.deps import CurrentUser, get_current_user, get_session
from vocal_coach.api.drive import DRIVE_ID_PATTERN, drive_http_error
from vocal_coach.api.jobs import submit_or_503
from vocal_coach.drive import cache as drive_cache
from vocal_coach.drive import service as drive_service
from vocal_coach.drive.client import DriveClient, DriveFile, MEDIA_EXTENSIONS as ALLOWED_EXTENSIONS
from vocal_coach.drive.errors import DriveError
from vocal_coach.pipeline import JobRequest
from vocal_coach.settings import BYTES_PER_MB
from vocal_coach.storage import paths, repo
from vocal_coach.storage.repo import AnalysisSummary
from vocal_coach.transcription.schema import Transcript

router = APIRouter(tags=["analyses"])

UPLOAD_CHUNK_BYTES = 1024 * 1024
RAW_KINDS = ("metrics", "transcript", "coaching")
LIST_LIMIT_MIN, LIST_LIMIT_MAX, LIST_LIMIT_DEFAULT = 1, 200, repo.SUMMARY_PAGE_SIZE
SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]")
MAX_DOWNLOAD_STEM = 100  # keep Content-Disposition short and ASCII
SPEAKER_CONTEXT_MAX_CHARS = 2000  # also the CoachRequest limit (api/llm.py); it is sent to the LLM verbatim


class JobIds(BaseModel):
    job_ids: list[uuid.UUID]


class LlmOptions(BaseModel):
    enabled: bool = False
    model: str | None = None


class DriveAnalysisRequest(BaseModel):
    source: Literal["drive"]
    file_ids: list[Annotated[str, StringConstraints(pattern=DRIVE_ID_PATTERN)]] = Field(min_length=1, max_length=20)
    speaker_context: str | None = Field(default=None, max_length=SPEAKER_CONTEXT_MAX_CHARS)
    llm: LlmOptions = Field(default_factory=LlmOptions)


# Request models FastAPI cannot see (the route parses the body itself); main.py adds them to
# OpenAPI `components.schemas` so generated clients get named types.
EXTRA_OPENAPI_MODELS: tuple[type[BaseModel], ...] = (DriveAnalysisRequest, LlmOptions)


class AnalysisDetail(BaseModel):
    id: uuid.UUID
    file_name: str
    drive_file_id: str | None
    recorded_at: datetime
    analysed_at: datetime
    analyser_version: str
    config_hash: str
    metrics: MetricsReport
    transcript: Transcript | None
    speaker_context: str | None
    coaching: dict | None
    coaching_warnings: list | None


def _download_filename(stem: str, kind: str) -> str:
    """ASCII-safe `Content-Disposition` filename: no quotes, no CR/LF, no header injection."""
    safe_stem = SAFE_FILENAME_RE.sub("_", stem)[:MAX_DOWNLOAD_STEM] or "analysis"
    return f"{safe_stem}.{kind}.json"


def _reject_if_declared_too_large(request: Request, max_bytes: int) -> None:
    """413 before touching the body when `Content-Length` already declares an oversized upload.

    A non-numeric or absent header is ignored; the post-parse size check is the backstop."""
    declared = request.headers.get("content-length")
    if declared is None:
        return
    try:
        declared_bytes = int(declared)
    except ValueError:
        return
    if declared_bytes > max_bytes:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, f"declared size exceeds {max_bytes} bytes")


def _file_too_large(max_bytes: int) -> HTTPException:
    return HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, f"file too large (max {max_bytes // BYTES_PER_MB} MB)")


def _limit_request_body(request: Request, max_bytes: int) -> None:
    """Makes the request body raise 413 once more than `max_bytes + UPLOAD_CHUNK_BYTES` bytes have
    arrived (the slack covers multipart framing and the other form fields), so `request.form()`
    cannot spool an unbounded chunked upload to disk before `_store_upload` gets to count it."""
    limit = max_bytes + UPLOAD_CHUNK_BYTES
    receive = request.receive
    received = 0

    async def limited_receive():
        nonlocal received
        message = await receive()
        if message["type"] == "http.request":
            received += len(message.get("body", b""))
            if received > limit:
                raise _file_too_large(max_bytes)
        return message

    # Starlette has no public hook for wrapping the body stream; this only affects this route's request.
    request._receive = limited_receive


def to_detail(row) -> AnalysisDetail:
    return AnalysisDetail(id=row.id, file_name=row.file_name, drive_file_id=row.drive_file_id,
                          recorded_at=row.recorded_at, analysed_at=row.analysed_at, analyser_version=row.analyser_version,
                          config_hash=row.config_hash, metrics=row.metrics_json, transcript=row.transcript_json,
                          speaker_context=row.speaker_context, coaching=row.coaching_json,
                          coaching_warnings=row.coaching_warnings)


_detail = to_detail  # back-compat alias; api/llm.py imports to_detail directly


def _parse_recorded_at(raw) -> datetime:
    """Optional ISO-8601 `recorded_at` form field; must carry a timezone. Defaults to now (UTC)."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return datetime.now(timezone.utc)
    try:
        value = datetime.fromisoformat(str(raw).strip())
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "recorded_at must be an ISO-8601 datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "recorded_at must include a timezone offset")
    return value


async def _store_upload(file: UploadFile, data_dir: Path, user_id: uuid.UUID, max_bytes: int) -> tuple[Path, str, int]:
    """Stream to a temp file, hashing as we go. Returns (final_path, sha256, size). Raises 413 on overflow."""
    dest_dir = paths.uploads_dir(data_dir, user_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    tmp = dest_dir / f".upload-{uuid.uuid4().hex}.part"
    digest = hashlib.sha256()
    size = 0
    try:
        with open(tmp, "wb") as out:
            while chunk := await file.read(UPLOAD_CHUNK_BYTES):
                size += len(chunk)
                if size > max_bytes:
                    raise _file_too_large(max_bytes)
                digest.update(chunk)
                out.write(chunk)
    except BaseException:
        tmp.unlink(missing_ok=True)
        try:
            dest_dir.rmdir()  # only succeeds if empty; leaves existing uploads for this user untouched
        except OSError:
            pass
        raise
    finally:
        await file.close()
    sha = digest.hexdigest()
    ext = Path(file.filename or "").suffix.lower().lstrip(".")
    final = paths.upload_path(data_dir, user_id, sha, ext)
    if final.exists():
        tmp.unlink(missing_ok=True)
    else:
        tmp.replace(final)
    return final, sha, size


def _create_upload_job(
    session_factory, request: Request, user_id: uuid.UUID, *, file_name: str, source_sha256: str,
    recorded_at: datetime, source_path: Path, speaker_context: str | None, llm_enabled: bool, llm_model: str | None,
) -> uuid.UUID:
    """Create the job row and hand it to the runner off the event loop (mirrors `/coach` in api/llm.py):
    opens its own session so it is safe to run via `asyncio.to_thread` without sharing the request's
    (not thread-safe) session."""
    with session_factory() as session:
        job = repo.create_job(session, user_id, file_name=file_name, source_sha256=source_sha256,
                              recorded_at=recorded_at)
        req = JobRequest(job_id=job.id, user_id=user_id, source_path=source_path, file_name=file_name,
                         recorded_at=recorded_at, speaker_context=speaker_context,
                         llm_enabled=llm_enabled, llm_model=llm_model, source_sha256=source_sha256)
        submit_or_503(request, session, job.id, req)
        return job.id


# The route reads the body itself (multipart so it can 413 before parsing, or raw JSON for the Drive
# branch), which hides it from FastAPI's schema generation; declare it here so generated clients see
# the real contract.
UPLOAD_OPENAPI = {
    "requestBody": {"required": True, "content": {
        "multipart/form-data": {"schema": {
            "type": "object", "required": ["file"],
            "properties": {
                "file": {"type": "string", "format": "binary"},
                "speaker_context": {"type": "string", "maxLength": SPEAKER_CONTEXT_MAX_CHARS},
                "llm_enabled": {"type": "boolean"},
                "llm_model": {"type": "string"},
                "recorded_at": {"type": "string", "format": "date-time"},
            },
        }},
        # The model itself is registered under components.schemas by main.py's openapi override.
        "application/json": {"schema": {"$ref": "#/components/schemas/DriveAnalysisRequest"}},
    }},
    "responses": {
        "404": {"description": "drive file not found"},
        "409": {"description": "drive_not_connected"},
        "413": {"description": "file too large"},
        "415": {"description": "unsupported file type"},
        "503": {"description": "job runner unavailable"},
    },
}


async def _create_drive_analyses(request: Request, user: CurrentUser, session: Session) -> JobIds:
    """JSON branch of `POST /analyses`: one job per Drive file id, metadata fetched up front so a
    file the user cannot read aborts the whole request before any job is created."""
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid JSON body")
    try:
        body = DriveAnalysisRequest.model_validate(payload)
    except ValidationError as e:
        detail = "; ".join(err["msg"] for err in e.errors(include_url=False))
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail) from None

    settings = request.app.state.settings
    try:
        token = await asyncio.to_thread(drive_service.access_token_for, session, settings, user.id)
    except DriveError as e:
        raise drive_http_error(e) from None
    client = DriveClient(token)

    files: list[DriveFile] = []
    for file_id in body.file_ids:
        try:
            files.append(await asyncio.to_thread(client.get_file, file_id))
        except DriveError as e:
            raise drive_http_error(e) from None
    for file in files:  # every file is checked before any job exists, so a bad one aborts the batch
        if file.is_folder or file.ext not in ALLOWED_EXTENSIONS or file.size is None:
            raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, f"unsupported file type: {file.name}")
        if file.size > settings.drive_max_bytes:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, f"file too large: {file.name}")

    if not request.app.state.runner.available():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "job runner unavailable")

    job_ids: list[uuid.UUID] = []
    for file in files:
        recorded_at = datetime.fromisoformat(file.modified_time.replace("Z", "+00:00"))
        path = drive_cache.cache_path(settings.data_dir, user.id, file)
        job = repo.create_job(session, user.id, file_name=file.name, source_sha256=None, recorded_at=recorded_at,
                              drive_file_id=file.id, drive_modified_time=file.modified_time)
        req = JobRequest(job_id=job.id, user_id=user.id, source_path=path, file_name=file.name,
                         recorded_at=recorded_at, drive_file_id=file.id, drive_modified_time=file.modified_time,
                         speaker_context=body.speaker_context, llm_enabled=body.llm.enabled,
                         llm_model=body.llm.model, source_sha256=None)
        try:
            submit_or_503(request, session, job.id, req)
        except HTTPException:
            # The runner went away mid-batch: fail the jobs already handed over too, so the
            # caller's retry of the whole batch does not leave stray queued duplicates behind.
            for earlier in job_ids:
                repo.update_job(session, earlier, status="failed", error="job runner unavailable")
            raise
        job_ids.append(job.id)
    return JobIds(job_ids=job_ids)


@router.post("/analyses", status_code=status.HTTP_202_ACCEPTED, response_model=JobIds, openapi_extra=UPLOAD_OPENAPI)
async def create_analysis(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("application/json"):
        return await _create_drive_analyses(request, user, session)
    _reject_if_declared_too_large(request, request.app.state.settings.max_upload_bytes)
    _limit_request_body(request, request.app.state.settings.max_upload_bytes)
    async with request.form() as form:  # closes the UploadFile's spooled temp file on exit, even on error
        file = form.get("file")
        if not isinstance(file, StarletteUploadFile):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "file is required")
        speaker_context = form.get("speaker_context") or None
        if isinstance(speaker_context, str) and len(speaker_context) > SPEAKER_CONTEXT_MAX_CHARS:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                                f"speaker_context is too long (max {SPEAKER_CONTEXT_MAX_CHARS} characters)")
        recorded_at = _parse_recorded_at(form.get("recorded_at"))
        llm_enabled = str(form.get("llm_enabled", "false")).strip().lower() in {"1", "true", "yes", "on"}
        llm_model = form.get("llm_model") or None
        ext = Path(file.filename or "").suffix.lower().lstrip(".")
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, f"unsupported file type .{ext}; allowed: {sorted(ALLOWED_EXTENSIONS)}")
        if not request.app.state.runner.available():
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "job runner unavailable")
        settings = request.app.state.settings
        path, sha, _size = await _store_upload(file, settings.data_dir, user.id, settings.max_upload_bytes)
        file_name = Path(file.filename or "").name or path.name  # strip any client-side directories
        # Off the event loop, like /coach: a fresh session for the worker thread, since the
        # request's session is not thread-safe to share.
        job_id = await asyncio.to_thread(
            _create_upload_job, request.app.state.session_factory, request, user.id, file_name=file_name,
            source_sha256=sha, recorded_at=recorded_at, source_path=path, speaker_context=speaker_context,
            llm_enabled=llm_enabled, llm_model=llm_model,
        )
        return JobIds(job_ids=[job_id])


@router.get("/analyses", response_model=list[AnalysisSummary])
def list_analyses(
    limit: int = Query(LIST_LIMIT_DEFAULT, ge=LIST_LIMIT_MIN, le=LIST_LIMIT_MAX),
    offset: int = Query(0, ge=0),
    user: CurrentUser = Depends(get_current_user), session: Session = Depends(get_session),
):
    return repo.list_analysis_summaries(session, user.id, limit=limit, offset=offset)


@router.get("/analyses/{analysis_id}", response_model=AnalysisDetail)
def get_analysis(analysis_id: uuid.UUID, user: CurrentUser = Depends(get_current_user), session: Session = Depends(get_session)):
    row = repo.get_analysis(session, user.id, analysis_id)
    if row is None:
        raise HTTPException(404, "analysis not found")
    return _detail(row)


@router.get("/analyses/{analysis_id}/raw/{kind}")
def get_raw(analysis_id: uuid.UUID, kind: str, user: CurrentUser = Depends(get_current_user), session: Session = Depends(get_session)):
    if kind not in RAW_KINDS:
        raise HTTPException(404, f"unknown kind {kind!r}")
    row = repo.get_analysis(session, user.id, analysis_id)
    if row is None:
        raise HTTPException(404, "analysis not found")
    payload = {"metrics": row.metrics_json, "transcript": row.transcript_json, "coaching": row.coaching_json}[kind]
    if payload is None:
        raise HTTPException(404, f"no {kind} for this analysis")
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)  # JSONB reorders keys
    filename = _download_filename(Path(row.file_name).stem, kind)
    return RawResponse(body, media_type="application/json",
                       headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.delete("/analyses/{analysis_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_analysis(analysis_id: uuid.UUID, request: Request, user: CurrentUser = Depends(get_current_user),
                    session: Session = Depends(get_session)):
    row = repo.get_analysis(session, user.id, analysis_id)
    if row is None:
        raise HTTPException(404, "analysis not found")
    source_sha = row.source_sha256  # the upload's name; content_sha256 is the extracted WAV's hash
    drive_file_id = row.drive_file_id
    settings = request.app.state.settings
    repo.delete_analysis_and_count_refs(
        session, user.id, analysis_id, source_sha, drive_file_id,
        on_unreferenced=lambda: paths.remove_upload(settings.data_dir, user.id, source_sha),
        # Drive-sourced: once no analysis of this user's references the file any more, its cached
        # download(s) are removed too (bounded by Plan 8's cache lifecycle).
        on_drive_unreferenced=lambda: drive_cache.remove_for_file(settings.data_dir, user.id, drive_file_id),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)

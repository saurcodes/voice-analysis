"""Upload, list, detail, raw download and delete for a user's analyses.

NOTE: `Content-Length` is checked before `request.form()` so a declared-oversized upload is
rejected without reading the body, and the post-parse byte count in `_store_upload` remains the
backstop for chunked requests with no `Content-Length`. Starlette's `request.form()` still
buffers the whole multipart body to a spooled temp file before we ever see it, so this is not
true incremental/streaming multipart parsing — that's follow-up hardening (ledgered for Plan 8).
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.responses import Response as RawResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile as StarletteUploadFile

from vocal_coach.analysis.schema import MetricsReport
from vocal_coach.auth.deps import CurrentUser, get_current_user, get_session
from vocal_coach.api.jobs import submit_or_503
from vocal_coach.drive.client import MEDIA_EXTENSIONS as ALLOWED_EXTENSIONS
from vocal_coach.pipeline import JobRequest
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
                    raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, f"file exceeds {max_bytes} bytes")
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


# The route reads the multipart form itself (so it can 413 before parsing and 501 on JSON), which hides
# the body from FastAPI's schema generation; declare it here so generated clients see the real contract.
UPLOAD_OPENAPI = {
    "requestBody": {"required": True, "content": {"multipart/form-data": {"schema": {
        "type": "object", "required": ["file"],
        "properties": {
            "file": {"type": "string", "format": "binary"},
            "speaker_context": {"type": "string", "maxLength": SPEAKER_CONTEXT_MAX_CHARS},
            "llm_enabled": {"type": "boolean"},
            "llm_model": {"type": "string"},
            "recorded_at": {"type": "string", "format": "date-time"},
        },
    }}}},
    "responses": {
        "413": {"description": "file too large"},
        "415": {"description": "unsupported file type"},
        "501": {"description": "Drive source not available yet"},
        "503": {"description": "job runner unavailable"},
    },
}


@router.post("/analyses", status_code=status.HTTP_202_ACCEPTED, response_model=JobIds, openapi_extra=UPLOAD_OPENAPI)
async def create_analysis(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("application/json"):
        # JSON body (Drive source) — Plan 7
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "drive is not available yet")
    _reject_if_declared_too_large(request, request.app.state.settings.max_upload_bytes)
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
        settings = request.app.state.settings
        path, sha, _size = await _store_upload(file, settings.data_dir, user.id, settings.max_upload_bytes)
        file_name = Path(file.filename or "").name or path.name  # strip any client-side directories
        job = repo.create_job(session, user.id, file_name=file_name, source_sha256=sha, recorded_at=recorded_at)
        req = JobRequest(job_id=job.id, user_id=user.id, source_path=path, file_name=file_name,
                         recorded_at=recorded_at, speaker_context=speaker_context,
                         llm_enabled=llm_enabled, llm_model=llm_model, source_sha256=sha)
        submit_or_503(request, session, job.id, req)
        return JobIds(job_ids=[job.id])


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
    repo.delete_analysis(session, user.id, analysis_id)
    if source_sha and not repo.count_source_refs(session, user.id, source_sha):
        paths.remove_upload(request.app.state.settings.data_dir, user.id, source_sha)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

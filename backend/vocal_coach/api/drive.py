"""Per-user Google Drive OAuth: connect, callback, disconnect, and file listing.

`/drive/callback` is the one route with no bearer auth dependency: the browser arrives here by a
Google redirect, not an API call. It is authenticated by the signed `state` (bound to the user who
started the flow) together with the `vc_drive_oauth` HttpOnly cookie that `/drive/connect` set to
the state's nonce, which binds the flow to the browser that started it (login-CSRF). Each state
is single-use."""
from __future__ import annotations

import asyncio
import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from vocal_coach.auth.deps import CurrentUser, get_current_user, get_session
from vocal_coach.drive import service
from vocal_coach.drive.client import DriveFile
from vocal_coach.drive.errors import (
    DriveError, DriveNotConfigured, DriveNotConnected, DriveNotFound, DriveStateError,
)
from vocal_coach.drive.state import INVALID_STATE_MESSAGE, STATE_MAX_AGE_S

log = logging.getLogger(__name__)
router = APIRouter(prefix="/drive", tags=["drive"])

NOT_CONNECTED = "drive_not_connected"
OAUTH_COOKIE = "vc_drive_oauth"
OAUTH_COOKIE_PATH = "/api/drive/callback"
DRIVE_ID_PATTERN = r"^[A-Za-z0-9_-]{1,200}$"
_DRIVE_ID_RE = re.compile(DRIVE_ID_PATTERN)


class ConnectUrl(BaseModel):
    url: str


class DriveFileOut(BaseModel):
    id: str
    name: str
    mime_type: str
    modified_time: str
    size: int | None
    is_folder: bool


def _to_out(file: DriveFile) -> DriveFileOut:
    return DriveFileOut(id=file.id, name=file.name, mime_type=file.mime_type,
                        modified_time=file.modified_time, size=file.size, is_folder=file.is_folder)


def drive_http_error(e: DriveError) -> HTTPException:
    """The one place that turns a `DriveError` (or subclass) into an HTTP response, used by every
    route below so the mapping is identical everywhere."""
    if isinstance(e, DriveNotConfigured):
        return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, service.NOT_CONFIGURED)
    if isinstance(e, DriveNotConnected):
        return HTTPException(status.HTTP_409_CONFLICT, NOT_CONNECTED)
    if isinstance(e, DriveNotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(e))
    return HTTPException(status.HTTP_502_BAD_GATEWAY, str(e))


@router.get(
    "/connect", response_model=ConnectUrl,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "drive is not configured on this server"}},
)
def connect(request: Request, response: Response, user: CurrentUser = Depends(get_current_user)) -> ConnectUrl:
    settings = request.app.state.settings
    try:
        url, nonce = service.start_connect(settings, user.id)
    except DriveError as e:
        raise drive_http_error(e) from None
    response.set_cookie(OAUTH_COOKIE, nonce, max_age=STATE_MAX_AGE_S, path=OAUTH_COOKIE_PATH,
                        secure=_secure_cookie(settings), httponly=True, samesite="lax")
    return ConnectUrl(url=url)


def _secure_cookie(settings) -> bool:
    return settings.frontend_origin.startswith("https")


def _clear_cookie(response: Response, settings) -> Response:
    response.delete_cookie(OAUTH_COOKIE, path=OAUTH_COOKIE_PATH, secure=_secure_cookie(settings),
                           httponly=True, samesite="lax")
    return response


def _settings_redirect(settings, outcome: str) -> RedirectResponse:
    """`outcome` is one of connected, cancelled, error (the frontend's `?drive=` contract)."""
    return _clear_cookie(RedirectResponse(f"{settings.frontend_origin}/settings?drive={outcome}",
                                          status_code=status.HTTP_303_SEE_OTHER), settings)


def _invalid_state(settings) -> JSONResponse:
    return _clear_cookie(JSONResponse({"detail": INVALID_STATE_MESSAGE}, status_code=status.HTTP_400_BAD_REQUEST),
                         settings)


@router.get(
    "/callback",
    responses={
        status.HTTP_303_SEE_OTHER: {"description": "redirect to /settings?drive=connected, cancelled or error"},
        status.HTTP_400_BAD_REQUEST: {"description": "invalid or expired OAuth state"},
    },
)
async def callback(
    request: Request, code: str | None = None, state: str | None = None, error: str | None = None,
) -> Response:
    settings = request.app.state.settings
    if error == "access_denied":
        return _settings_redirect(settings, "cancelled")
    if error:
        return _settings_redirect(settings, "error")
    if not code or not state:
        return _invalid_state(settings)
    try:
        user_id, nonce = service.verify_callback_state(settings, state)
    except DriveStateError:
        return _invalid_state(settings)
    if request.cookies.get(OAUTH_COOKIE) != nonce:
        return _invalid_state(settings)
    if not request.app.state.drive_nonces.consume(nonce):
        return _invalid_state(settings)
    session_factory = request.app.state.session_factory

    def _run() -> None:
        with session_factory() as session:
            service.complete_connect(session, settings, code=code, user_id=user_id)

    try:
        await asyncio.to_thread(_run)
    except DriveError as e:  # state verified: the browser goes back to Settings, never a JSON page
        log.info("drive connect failed: %s", e)  # DriveError messages carry no token or body
        return _settings_redirect(settings, "error")
    return _settings_redirect(settings, "connected")


@router.delete(
    "/connect", status_code=status.HTTP_204_NO_CONTENT,
    responses={status.HTTP_404_NOT_FOUND: {"description": "drive_not_connected"}},
)
async def disconnect(
    request: Request, user: CurrentUser = Depends(get_current_user), session: Session = Depends(get_session),
) -> Response:
    settings = request.app.state.settings
    removed = await asyncio.to_thread(service.disconnect, session, settings, user.id)
    if not removed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_CONNECTED)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/files", response_model=list[DriveFileOut],
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "folder not found"},
        status.HTTP_409_CONFLICT: {"description": "drive_not_connected"},
        status.HTTP_502_BAD_GATEWAY: {"description": "Google drive error"},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "drive is not configured on this server"},
    },
)
async def list_files(
    request: Request, folder_id: str | None = None,
    user: CurrentUser = Depends(get_current_user), session: Session = Depends(get_session),
) -> list[DriveFileOut]:
    settings = request.app.state.settings
    if folder_id is not None and folder_id != "root" and not _DRIVE_ID_RE.fullmatch(folder_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "folder not found")
    try:
        files = await asyncio.to_thread(
            service.list_files, session, settings, user.id, folder_id, include_folders=True)
    except DriveError as e:
        raise drive_http_error(e) from None
    return [_to_out(f) for f in files]

"""Per-user Google Drive OAuth: connect, callback, disconnect, and file listing.

`/drive/callback` is the one route with no bearer auth dependency: the browser arrives here by a
Google redirect, not an API call, so the signed `state` (bound to the user who started the flow)
is the only thing authenticating this request."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from vocal_coach.auth.deps import CurrentUser, get_current_user, get_session
from vocal_coach.drive import service
from vocal_coach.drive.client import DriveFile
from vocal_coach.drive.errors import DriveError, DriveNotConfigured, DriveNotConnected, DriveNotFound
from vocal_coach.drive.state import INVALID_STATE_MESSAGE

router = APIRouter(prefix="/drive", tags=["drive"])

NOT_CONNECTED = "drive_not_connected"


class ConnectUrl(BaseModel):
    url: str


class DriveFileOut(BaseModel):
    id: str
    name: str
    mime_type: str
    modified_time: str
    size: int | None


def _to_out(file: DriveFile) -> DriveFileOut:
    return DriveFileOut(id=file.id, name=file.name, mime_type=file.mime_type,
                        modified_time=file.modified_time, size=file.size)


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
def connect(request: Request, user: CurrentUser = Depends(get_current_user)) -> ConnectUrl:
    settings = request.app.state.settings
    try:
        url = service.start_connect(settings, user.id)
    except DriveError as e:
        raise drive_http_error(e) from None
    return ConnectUrl(url=url)


@router.get(
    "/callback",
    responses={
        status.HTTP_303_SEE_OTHER: {"description": "redirect to the frontend settings page"},
        status.HTTP_400_BAD_REQUEST: {"description": "invalid or expired OAuth state"},
        status.HTTP_502_BAD_GATEWAY: {"description": "Google returned an error"},
    },
)
async def callback(
    request: Request, code: str | None = None, state: str | None = None, error: str | None = None,
) -> RedirectResponse:
    settings = request.app.state.settings
    if error == "access_denied":
        return RedirectResponse(f"{settings.frontend_origin}/settings?drive=cancelled", status_code=status.HTTP_303_SEE_OTHER)
    if not code or not state:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, INVALID_STATE_MESSAGE)
    session_factory = request.app.state.session_factory

    def _run() -> None:
        with session_factory() as session:
            service.complete_connect(session, settings, code=code, state=state)

    try:
        await asyncio.to_thread(_run)
    except DriveError as e:
        if str(e) == INVALID_STATE_MESSAGE:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, INVALID_STATE_MESSAGE) from None
        raise drive_http_error(e) from None
    return RedirectResponse(f"{settings.frontend_origin}/settings?drive=connected", status_code=status.HTTP_303_SEE_OTHER)


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
    try:
        files = await asyncio.to_thread(service.list_files, session, settings, user.id, folder_id)
    except DriveError as e:
        raise drive_http_error(e) from None
    return [_to_out(f) for f in files]

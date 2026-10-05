from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from vocal_coach.auth.deps import CurrentUser, get_current_user, get_session
from vocal_coach.drive import service as drive_service

router = APIRouter(tags=["me"])


class MeResponse(BaseModel):
    id: uuid.UUID
    email: str | None
    username: str | None
    drive_connected: bool
    drive_configured: bool
    google_email: str | None
    llm_enabled: bool
    llm_provider: str | None


@router.get("/me", response_model=MeResponse)
def me(request: Request, user: CurrentUser = Depends(get_current_user), session: Session = Depends(get_session)):
    cfg = request.app.state.cfg
    settings = request.app.state.settings
    connected, google_email = drive_service.connection_status(session, user.id)
    return MeResponse(id=user.id, email=user.email, username=user.username,
                      drive_connected=connected, drive_configured=settings.drive_configured,
                      google_email=google_email,
                      llm_enabled=cfg.llm.enabled,
                      llm_provider=cfg.llm.provider if cfg.llm.enabled else None)

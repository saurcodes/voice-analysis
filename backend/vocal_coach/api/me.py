from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from vocal_coach.auth.deps import CurrentUser, get_current_user

router = APIRouter(tags=["me"])


class MeResponse(BaseModel):
    id: uuid.UUID
    email: str | None
    username: str | None
    drive_connected: bool
    llm_enabled: bool
    llm_provider: str | None


@router.get("/me", response_model=MeResponse)
def me(request: Request, user: CurrentUser = Depends(get_current_user)):
    cfg = request.app.state.cfg
    return MeResponse(id=user.id, email=user.email, username=user.username,
                      drive_connected=False,  # Plan 7
                      llm_enabled=cfg.llm.enabled,
                      llm_provider=cfg.llm.provider if cfg.llm.enabled else None)

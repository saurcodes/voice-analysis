"""LLM endpoints. Stubs until Plan 6 wires providers."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from vocal_coach.auth.deps import CurrentUser, get_current_user, get_session
from vocal_coach.storage import repo

router = APIRouter(tags=["llm"])


class LlmModels(BaseModel):
    enabled: bool
    provider: str | None
    models: list[str]


@router.get("/llm/models", response_model=LlmModels)
def list_models(_user: CurrentUser = Depends(get_current_user)) -> LlmModels:
    return LlmModels(enabled=False, provider=None, models=[])


@router.post("/analyses/{analysis_id}/coach",
             responses={404: {"description": "analysis not found"}, 501: {"description": "coaching is not available yet"}})
def coach(analysis_id: uuid.UUID, user: CurrentUser = Depends(get_current_user), session: Session = Depends(get_session)):
    if repo.get_analysis(session, user.id, analysis_id) is None:
        raise HTTPException(404, "analysis not found")
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "coaching is not available yet")

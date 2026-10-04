"""LLM endpoints. Stubs until Plan 6 wires providers."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from vocal_coach.auth.deps import CurrentUser, get_current_user, get_session
from vocal_coach.storage import repo

router = APIRouter(tags=["llm"])


@router.get("/llm/models")
def list_models(_user: CurrentUser = Depends(get_current_user)) -> dict:
    return {"enabled": False, "provider": None, "models": []}


@router.post("/analyses/{analysis_id}/coach", status_code=501)
def coach(analysis_id: uuid.UUID, user: CurrentUser = Depends(get_current_user), session: Session = Depends(get_session)):
    if repo.get_analysis(session, user.id, analysis_id) is None:
        raise HTTPException(404, "analysis not found")
    raise HTTPException(501, "coaching is not available yet")

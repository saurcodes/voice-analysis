"""LLM endpoints: model discovery and an on-demand coaching re-run."""
from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from vocal_coach.api.analyses import AnalysisDetail, to_detail
from vocal_coach.auth.deps import CurrentUser, get_current_user, get_session
from vocal_coach.llm import service
from vocal_coach.llm.base import LLMError
from vocal_coach.storage import repo

router = APIRouter(tags=["llm"])


class LlmModels(BaseModel):
    enabled: bool
    provider: str | None
    models: list[str]


class CoachRequest(BaseModel):
    speaker_context: str | None = None
    model: str | None = None


@router.get("/llm/models", response_model=LlmModels,
            responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "LLM provider unavailable"}})
async def list_models(request: Request, _user: CurrentUser = Depends(get_current_user)) -> LlmModels:
    cfg = request.app.state.cfg
    if not cfg.llm.enabled:
        return LlmModels(enabled=False, provider=None, models=[])
    settings = request.app.state.settings
    try:
        models = await asyncio.to_thread(service.list_models, cfg.llm, settings)
    except LLMError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"LLM provider unavailable: {e}") from None
    return LlmModels(enabled=True, provider=cfg.llm.provider, models=models)


@router.post(
    "/analyses/{analysis_id}/coach", response_model=AnalysisDetail,
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "analysis not found"},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "requested model is not allowed on this server"},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "coaching is not enabled on this server"},
    },
)
async def coach(
    analysis_id: uuid.UUID, request: Request, body: CoachRequest = CoachRequest(),
    user: CurrentUser = Depends(get_current_user), session: Session = Depends(get_session),
) -> AnalysisDetail:
    if repo.get_analysis(session, user.id, analysis_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "analysis not found")
    cfg = request.app.state.cfg
    if not cfg.llm.enabled:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, service.DISABLED)
    _model, warning = service.resolve_model(cfg.llm, body.model)
    if warning is not None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, warning)

    settings = request.app.state.settings
    session_factory = request.app.state.session_factory

    def _run() -> None:
        # A new session for the worker thread: the request's session is not thread-safe to share.
        with session_factory() as worker_session:
            service.coach_analysis(worker_session, cfg, settings, user.id, analysis_id,
                                   model=body.model, speaker_context=body.speaker_context)

    await asyncio.to_thread(_run)
    row = repo.get_analysis(session, user.id, analysis_id)
    if row is None:  # deleted by another request while coaching was running
        raise HTTPException(status.HTTP_404_NOT_FOUND, "analysis not found")
    return to_detail(row)

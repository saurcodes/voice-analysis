from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from vocal_coach.auth.deps import CurrentUser, get_current_user

router = APIRouter(tags=["config"])


@router.get("/config/public")
def config_public(request: Request, _user: CurrentUser = Depends(get_current_user)) -> dict:
    cfg = request.app.state.cfg
    return {"analysis": cfg.analysis.model_dump(), "articulation": cfg.articulation.model_dump(),
            "clarity": cfg.clarity.model_dump(), "comparison": cfg.comparison.model_dump()}

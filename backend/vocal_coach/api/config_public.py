from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from vocal_coach.auth.deps import CurrentUser, get_current_user
from vocal_coach.config import AnalysisConfig, ArticulationConfig, ClarityConfig, ComparisonConfig

router = APIRouter(tags=["config"])


class PublicConfig(BaseModel):
    analysis: AnalysisConfig
    articulation: ArticulationConfig
    clarity: ClarityConfig
    comparison: ComparisonConfig


@router.get("/config/public", response_model=PublicConfig)
def config_public(request: Request, _user: CurrentUser = Depends(get_current_user)) -> PublicConfig:
    cfg = request.app.state.cfg
    return PublicConfig(analysis=cfg.analysis, articulation=cfg.articulation, clarity=cfg.clarity,
                        comparison=cfg.comparison)

"""Compare two or more of the user's analyses."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from vocal_coach.auth.deps import CurrentUser, get_current_user, get_session
from vocal_coach.storage import repo
from vocal_coach.storage.comparison import ComparisonResult, compare, from_row

router = APIRouter(tags=["comparisons"])
MIN_IDS = 2
MAX_COMPARE_IDS = 50  # keeps payloads and the N-row fetch bounded


def _parse_ids(raw: str) -> list[uuid.UUID]:
    try:
        ids = [uuid.UUID(part.strip()) for part in raw.split(",") if part.strip()]
    except ValueError:
        raise HTTPException(400, "ids must be comma-separated UUIDs")
    unique = list(dict.fromkeys(ids))
    if len(unique) < MIN_IDS:
        raise HTTPException(400, f"need at least {MIN_IDS} distinct ids")
    if len(unique) > MAX_COMPARE_IDS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"at most {MAX_COMPARE_IDS} ids per comparison")
    return unique


@router.get("/comparisons", response_model=ComparisonResult)
def get_comparison(request: Request, ids: str = Query(..., description="comma-separated analysis ids"),
                   user: CurrentUser = Depends(get_current_user), session: Session = Depends(get_session)):
    wanted = _parse_ids(ids)
    rows = repo.get_analyses(session, user.id, wanted)
    if len(rows) != len(wanted):
        raise HTTPException(404, "one or more analyses not found")
    return compare([from_row(r) for r in rows], request.app.state.cfg.comparison)

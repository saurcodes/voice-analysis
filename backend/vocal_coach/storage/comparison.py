"""Direction-aware comparison across a user's analyses (spec §9). Pure; no database access."""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from vocal_coach.config import ComparisonConfig, Direction

Verdict = Literal["improved", "worsened", "neutral", "unchanged", "unavailable"]
TRANSCRIPT_PREFIX = "transcript."  # paths under this prefix resolve into transcript_json
ARROW_UP, ARROW_DOWN, ARROW_FLAT, ARROW_NA = "↑", "↓", "→", "—"
PERCENT = 100.0


class ComparableAnalysis(BaseModel):
    id: str
    recorded_at: datetime
    config_hash: str
    metrics: dict
    transcript: dict | None


def from_row(row: Any) -> ComparableAnalysis:
    """Adapter from a storage.models.Analysis row (kept loose to avoid importing the ORM here)."""
    return ComparableAnalysis(id=str(row.id), recorded_at=row.recorded_at, config_hash=row.config_hash,
                              metrics=row.metrics_json, transcript=row.transcript_json)


class ComparisonRow(BaseModel):
    path: str
    direction: Direction
    values: list[float | None]
    step_deltas: list[float | None]
    delta: float | None
    arrow: str
    verdict: Verdict


class TrendPoint(BaseModel):
    analysis_id: str
    recorded_at: datetime
    value: float | None


class ComparisonResult(BaseModel):
    analysis_ids: list[str]
    recorded_at: list[datetime]
    config_mismatch: bool
    rows: list[ComparisonRow]
    trend: dict[str, list[TrendPoint]]


def _numeric(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value_float = float(value)
    if not math.isfinite(value_float):
        return None
    return value_float


def resolve_path(analysis: ComparableAnalysis, path: str) -> float | None:
    if path.startswith(TRANSCRIPT_PREFIX):
        node: Any = analysis.transcript
        parts = path[len(TRANSCRIPT_PREFIX):].split(".")
    else:
        node = analysis.metrics
        parts = path.split(".")
    for part in parts:
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return _numeric(node)


def _sub(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else float(a - b)


def _verdict(first: float | None, delta: float | None, direction: Direction, pct: float) -> tuple[Verdict, str]:
    if first is None or delta is None:
        return "unavailable", ARROW_NA
    unchanged = (delta == 0) if first == 0 else (abs(delta) < (pct / PERCENT) * abs(first))
    arrow = ARROW_FLAT if (unchanged or delta == 0) else (ARROW_UP if delta > 0 else ARROW_DOWN)
    if unchanged:
        return "unchanged", arrow
    if direction == "neutral":
        return "neutral", arrow
    improved = delta > 0 if direction == "up_good" else delta < 0
    return ("improved" if improved else "worsened"), arrow


def compare(analyses: list[ComparableAnalysis], cfg: ComparisonConfig) -> ComparisonResult:
    if len(analyses) < 2:
        raise ValueError("comparison needs at least two analyses")
    ordered = sorted(analyses, key=lambda a: a.recorded_at)
    rows: list[ComparisonRow] = []
    trend: dict[str, list[TrendPoint]] = {}
    for path, direction in cfg.directions.items():
        values = [resolve_path(a, path) for a in ordered]
        steps = [_sub(values[i + 1], values[i]) for i in range(len(values) - 1)]
        delta = _sub(values[-1], values[0])
        verdict, arrow = _verdict(values[0], delta, direction, cfg.min_meaningful_change_pct)
        rows.append(ComparisonRow(path=path, direction=direction, values=values, step_deltas=steps,
                                  delta=delta, arrow=arrow, verdict=verdict))
        trend[path] = [TrendPoint(analysis_id=a.id, recorded_at=a.recorded_at, value=v) for a, v in zip(ordered, values)]
    return ComparisonResult(
        analysis_ids=[a.id for a in ordered],
        recorded_at=[a.recorded_at for a in ordered],
        config_mismatch=len({a.config_hash for a in ordered}) > 1,
        rows=rows,
        trend=trend,
    )

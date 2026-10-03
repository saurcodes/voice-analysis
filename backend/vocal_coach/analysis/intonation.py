"""Phrase-final pitch movement: up / down / flat."""
from __future__ import annotations

from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from vocal_coach.analysis.phrasing import Interval
from vocal_coach.analysis.tracks import Tracks, semitones
from vocal_coach.config import AnalysisConfig


class PhraseContour(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    start_s: float
    end_s: float
    end_delta_st: float
    class_: Literal["up", "down", "flat"] = Field(alias="class")


class IntonationBlock(BaseModel):
    up_count: int
    down_count: int
    flat_count: int
    unclassified_count: int
    flat_pct: float | None
    per_phrase: list[PhraseContour]


def compute(tracks: Tracks, cfg: AnalysisConfig, phrases: list[Interval]) -> IntonationBlock:
    per_phrase: list[PhraseContour] = []
    unclassified = 0
    for ph in phrases:
        if ph.duration_s < cfg.intonation_tail_s:
            unclassified += 1
            continue
        whole = tracks.f0_between(ph.start_s, ph.end_s)
        tail = tracks.f0_between(ph.end_s - cfg.intonation_tail_s, ph.end_s)
        if len(whole) == 0 or len(tail) == 0:
            unclassified += 1
            continue
        delta = float(semitones(np.median(tail), float(np.median(whole))))
        if delta > cfg.intonation_threshold_st:
            cls = "up"
        elif delta < -cfg.intonation_threshold_st:
            cls = "down"
        else:
            cls = "flat"
        per_phrase.append(PhraseContour(start_s=ph.start_s, end_s=ph.end_s, end_delta_st=delta, class_=cls))

    up = sum(p.class_ == "up" for p in per_phrase)
    down = sum(p.class_ == "down" for p in per_phrase)
    flat = sum(p.class_ == "flat" for p in per_phrase)
    classified = up + down + flat
    return IntonationBlock(
        up_count=up,
        down_count=down,
        flat_count=flat,
        unclassified_count=unclassified,
        flat_pct=float(100.0 * flat / classified) if classified else None,
        per_phrase=per_phrase,
    )

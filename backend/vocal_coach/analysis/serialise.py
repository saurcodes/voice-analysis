"""Canonical, byte-stable JSON for metrics reports."""
from __future__ import annotations

import json
import math
from typing import Any

from pydantic import BaseModel

SIX_DECIMAL_FIELDS = frozenset({
    "voiced_fraction", "creak_fraction_below_100hz", "jitter_local", "shimmer_local",
    "modulation_depth", "weak_peak_fraction",
    # transcript.json ratio fields
    "probability", "avg_logprob", "no_speech_prob",
    "low_conf_word_fraction", "word_final_drop_fraction", "rushed_word_fraction",
    "low_logprob_segment_fraction",
})
DEFAULT_DECIMALS = 4
RATIO_DECIMALS = 6


def _round(value: float, decimals: int) -> float | None:
    if not math.isfinite(value):
        return None
    r = round(value, decimals)
    return 0.0 if r == 0 else r  # normalise -0.0


def round_floats(obj: Any, decimals: int = DEFAULT_DECIMALS) -> Any:
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, float):
        return _round(obj, decimals)
    if isinstance(obj, dict):
        return {
            k: round_floats(v, RATIO_DECIMALS if k in SIX_DECIMAL_FIELDS else DEFAULT_DECIMALS)
            for k, v in obj.items()
        }
    if isinstance(obj, (list, tuple)):
        return [round_floats(v, decimals) for v in obj]
    return obj


def to_canonical_json(report: BaseModel) -> str:
    data = round_floats(report.model_dump(mode="json", by_alias=True))
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)

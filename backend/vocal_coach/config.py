"""Load config.yaml, validate the analysis sections, compute config_hash."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.yaml"


class AnalysisConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pitch_floor_hz: float
    pitch_ceiling_hz: float
    time_step_s: float
    silence_threshold_db: float
    min_pause_s: float
    min_sounding_s: float
    creak_threshold_hz: float
    opening_window_s: float
    syllable_peak_prominence_db: float
    intonation_tail_s: float
    intonation_threshold_st: float
    energy_window_s: float
    phrase_end_tail_s: float
    trailing_off_drop_db: float
    noise_floor_percentile: float
    low_confidence_noise_floor_db: float
    low_confidence_snr_db: float
    low_confidence_f0_hz: float


class ArticulationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hf_band_hz: tuple[float, float]
    lf_band_hz: tuple[float, float]
    modulation_band_hz: tuple[float, float]
    weak_peak_prominence_db: float
    formant_max_hz: float
    formant_trim_pct: float


class AppConfig(BaseModel):
    analysis: AnalysisConfig
    articulation: ArticulationConfig
    raw: dict[str, Any]
    """The full YAML document, for sections validated by later plans."""


def load_config(path: Path | None = None) -> AppConfig:
    path = path or DEFAULT_CONFIG_PATH
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return AppConfig(
        analysis=AnalysisConfig(**raw["analysis"]),
        articulation=ArticulationConfig(**raw["articulation"]),
        raw=raw,
    )


def config_hash(cfg: AppConfig) -> str:
    payload = {
        "analysis": cfg.analysis.model_dump(mode="json"),
        "articulation": cfg.articulation.model_dump(mode="json"),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()

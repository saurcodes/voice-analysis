"""Wires the LLM package into the product: model resolution/allow-listing, the previous-analysis
comparison fed to the prompt, and `coach_analysis`, the single entry point the pipeline and the API
both call. This is the only `vocal_coach.llm` module the rest of the app imports.

Coaching never fails a job or a request: every failure path here ends by calling
`repo.set_coaching(..., coaching_json=None, coaching_warnings=[message])` and logging at WARNING
with the analysis id; this function itself never raises.
"""
from __future__ import annotations

import logging
import uuid

from sqlalchemy.orm import Session

from vocal_coach.config import AppConfig, LLMConfig
from vocal_coach.llm.base import LLMError, LLMProvider
from vocal_coach.llm.coach import run_coaching
from vocal_coach.llm.payload import build_payload
import vocal_coach.llm.providers  # noqa: F401 - import registers every built-in provider
from vocal_coach.llm.providers.anthropic_provider import DEFAULT_MODEL
from vocal_coach.llm.registry import get_provider
from vocal_coach.settings import Settings
from vocal_coach.storage import repo
from vocal_coach.storage.comparison import compare, from_row
from vocal_coach.storage.models import Analysis

log = logging.getLogger(__name__)

MODEL_NOT_ALLOWED = "model {model!r} is not allowed on this server"
NO_MODEL = "no LLM model configured"
DISABLED = "coaching is not enabled on this server"


def resolve_model(cfg: LLMConfig, requested: str | None) -> tuple[str | None, str | None]:
    """(model, warning). `requested` wins over `cfg.model`; an empty result is `NO_MODEL` unless the
    provider is `anthropic` (falls back to `DEFAULT_MODEL`). A non-empty `cfg.allowed_models` then
    filters the result, rejecting anything not in it."""
    model = requested or cfg.model
    if not model:
        if cfg.provider == "anthropic":
            model = DEFAULT_MODEL
        else:
            return None, NO_MODEL
    if cfg.allowed_models and model not in cfg.allowed_models:
        return None, MODEL_NOT_ALLOWED.format(model=model)
    return model, None


def _provider_config(cfg: LLMConfig, settings: Settings) -> LLMConfig:
    """`cfg` with `base_url` swapped for `settings.llm_base_url_override` when one is set (lets a
    container reach a host-run Ollama without changing config.yaml)."""
    if settings.llm_base_url_override:
        return cfg.model_copy(update={"base_url": settings.llm_base_url_override})
    return cfg


def coaching_comparison(session: Session, user_id: uuid.UUID, row: Analysis, cfg: AppConfig) -> dict | None:
    """Deltas vs. the user's previous analysis (by `recorded_at`, excluding `row` itself), or None
    when there is no previous analysis."""
    previous = repo.previous_analysis(session, user_id, before=row.recorded_at, exclude_id=row.id)
    if previous is None:
        return None
    result = compare([from_row(previous), from_row(row)], cfg.comparison).model_dump(mode="json")
    return {
        "previous_recorded_at": previous.recorded_at.isoformat(),
        "rows": [{"path": r["path"], "values": r["values"], "delta": r["delta"], "verdict": r["verdict"]}
                 for r in result["rows"]],
        "config_mismatch": result["config_mismatch"],
        "analyser_version_mismatch": result["analyser_version_mismatch"],
    }


def coach_analysis(
    session: Session, cfg: AppConfig, settings: Settings, user_id: uuid.UUID, analysis_id: uuid.UUID, *,
    model: str | None, speaker_context: str | None, provider: LLMProvider | None = None,
) -> Analysis | None:
    """Run (or re-run) coaching for one analysis and store the result. Returns the updated row, or
    None when the analysis does not exist (or does not belong to `user_id`). Never raises."""
    row = repo.get_analysis(session, user_id, analysis_id)
    if row is None:
        return None
    context = row.speaker_context if speaker_context is None else speaker_context

    resolved_model, warning = resolve_model(cfg.llm, model)
    if warning is not None:
        log.warning("analysis %s: coaching skipped: %s", analysis_id, warning)
        return repo.set_coaching(session, user_id, analysis_id, speaker_context=context,
                                 coaching_json=None, coaching_warnings=[warning])

    try:
        if provider is None:
            provider = get_provider(cfg.llm.provider, _provider_config(cfg.llm, settings), settings)
    except LLMError as e:
        message = f"coaching failed: {e}"
        log.warning("analysis %s: %s", analysis_id, message)
        return repo.set_coaching(session, user_id, analysis_id, speaker_context=context,
                                 coaching_json=None, coaching_warnings=[message])

    try:
        comparison = coaching_comparison(session, user_id, row, cfg)
        payload = build_payload(row.metrics_json, row.transcript_json, comparison, context)
        result = run_coaching(provider, payload, model=resolved_model)
    except Exception as e:  # run_coaching degrades known failures itself; this is a last resort
        message = f"coaching failed: {type(e).__name__}"
        log.warning("analysis %s: %s", analysis_id, message)
        return repo.set_coaching(session, user_id, analysis_id, speaker_context=context,
                                 coaching_json=None, coaching_warnings=[message])

    if result.coaching is None:
        log.warning("analysis %s: coaching failed: %s", analysis_id, "; ".join(result.warnings))
    return repo.set_coaching(session, user_id, analysis_id, speaker_context=context,
                             coaching_json=result.coaching, coaching_warnings=result.warnings or None)


def list_models(cfg: LLMConfig, settings: Settings) -> list[str]:
    """The provider's available models, filtered by `cfg.allowed_models` when it is non-empty.
    Raises LLMError when the provider cannot list (caller maps that to 503)."""
    provider = get_provider(cfg.provider, _provider_config(cfg, settings), settings)
    models = provider.list_models()
    if cfg.allowed_models:
        allowed = set(cfg.allowed_models)
        models = [m for m in models if m in allowed]
    return models

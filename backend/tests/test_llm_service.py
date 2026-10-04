"""Tests for vocal_coach.llm.service: model resolution/allow-listing, the previous-analysis
comparison, and coach_analysis (the pipeline/API entry point). No network: FakeProvider stands in
for a real provider everywhere a provider is needed."""
from __future__ import annotations

from datetime import timedelta

import pytest

from tests.fake_llm import FakeProvider
from vocal_coach.config import LLMConfig
from vocal_coach.llm import service
from vocal_coach.llm.base import LLMError
from vocal_coach.llm.providers.anthropic_provider import DEFAULT_MODEL
from vocal_coach.settings import Settings
from vocal_coach.storage import repo
from vocal_coach.storage.db import create_all, make_engine, make_session_factory
from vocal_coach.storage.models import utcnow

VALID_ANSWER = {
    "what_improved": ["steady pace"],
    "what_is_lacking": ["flat intonation"],
    "next_steps": ["vary pitch on key words"],
    "marked_up_example": "hello world",
}


@pytest.fixture
def session():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    with make_session_factory(engine)() as s:
        yield s


def _llm_cfg(**overrides) -> LLMConfig:
    return LLMConfig(**overrides)


def _settings() -> Settings:
    return Settings(_env_file=None)


def _mk(session, user, sha, when, *, f0_range_st=9.0, transcript=None):
    return repo.create_analysis(
        session, user.id, file_name="a.m4a", drive_file_id=None, content_sha256=sha,
        recorded_at=when, analyser_version="0.1.0", config_hash="sha256:c1",
        metrics_json={"pitch": {"f0_range_st": f0_range_st}}, transcript_json=transcript,
    )


# --- resolve_model -----------------------------------------------------------------------------

def test_resolve_model_requested_wins_and_is_allowed():
    cfg = _llm_cfg(allowed_models=["a", "b"])
    assert service.resolve_model(cfg, "b") == ("b", None)


def test_resolve_model_requested_not_allowed():
    cfg = _llm_cfg(allowed_models=["a"])
    model, warning = service.resolve_model(cfg, "z")
    assert model is None
    assert warning == "model 'z' is not allowed on this server"


def test_resolve_model_falls_back_to_configured_model():
    cfg = _llm_cfg(model="configured-model")
    assert service.resolve_model(cfg, None) == ("configured-model", None)


def test_resolve_model_empty_with_openai_compatible_has_no_default():
    cfg = _llm_cfg(provider="openai_compatible", model="")
    assert service.resolve_model(cfg, None) == (None, service.NO_MODEL)


def test_resolve_model_empty_with_anthropic_falls_back_to_default_model():
    cfg = _llm_cfg(provider="anthropic", model="")
    assert service.resolve_model(cfg, None) == (DEFAULT_MODEL, None)


def test_resolve_model_allowed_models_also_filters_the_anthropic_default():
    cfg = _llm_cfg(provider="anthropic", model="", allowed_models=["some-other-model"])
    model, warning = service.resolve_model(cfg, None)
    assert model is None
    assert warning == service.MODEL_NOT_ALLOWED.format(model=DEFAULT_MODEL)


# --- coaching_comparison ------------------------------------------------------------------------

def test_coaching_comparison_none_without_a_previous_row(cfg, session):
    user = repo.upsert_user(session, "u", None, None)
    row = _mk(session, user, "a" * 64, utcnow())
    assert service.coaching_comparison(session, user.id, row, cfg) is None


def test_coaching_comparison_shaped_rows_with_a_previous_row(cfg, session):
    user = repo.upsert_user(session, "u", None, None)
    t0 = utcnow()
    previous = _mk(session, user, "a" * 64, t0 - timedelta(days=1), f0_range_st=8.0)
    row = _mk(session, user, "b" * 64, t0, f0_range_st=10.0)

    result = service.coaching_comparison(session, user.id, row, cfg)

    assert result["previous_recorded_at"] == previous.recorded_at.isoformat()
    assert result["config_mismatch"] is False
    assert result["analyser_version_mismatch"] is False
    entry = next(r for r in result["rows"] if r["path"] == "pitch.f0_range_st")
    assert set(entry) == {"path", "values", "delta", "verdict"}
    assert entry["values"] == [8.0, 10.0]
    assert entry["delta"] == 2.0
    assert entry["verdict"] == "improved"


# --- coach_analysis -------------------------------------------------------------------------

def test_coach_analysis_stores_coaching_with_fake_provider(cfg, session):
    user = repo.upsert_user(session, "u", None, None)
    row = _mk(session, user, "a" * 64, utcnow(), transcript={"text": "hello world", "derived": None})
    provider = FakeProvider([VALID_ANSWER])

    updated = service.coach_analysis(session, cfg, _settings(), user.id, row.id, model="test-model",
                                     speaker_context="investor pitch", provider=provider)

    assert updated.coaching_json == VALID_ANSWER
    assert not updated.coaching_warnings
    assert updated.speaker_context == "investor pitch"


def test_coach_analysis_provider_failure_stores_null_and_warning(cfg, session):
    user = repo.upsert_user(session, "u", None, None)
    row = _mk(session, user, "a" * 64, utcnow())
    provider = FakeProvider([LLMError("down")])

    updated = service.coach_analysis(session, cfg, _settings(), user.id, row.id, model="test-model",
                                     speaker_context=None, provider=provider)

    assert updated.coaching_json is None
    assert updated.coaching_warnings == ["coaching failed: down"]


def test_coach_analysis_missing_transcript_runs_on_metrics_alone(cfg, session):
    user = repo.upsert_user(session, "u", None, None)
    row = _mk(session, user, "a" * 64, utcnow(), transcript=None)
    provider = FakeProvider([VALID_ANSWER])

    updated = service.coach_analysis(session, cfg, _settings(), user.id, row.id, model="test-model",
                                     speaker_context=None, provider=provider)

    sent_payload = provider.calls[0]
    assert sent_payload["transcript_text"] == ""
    assert sent_payload["transcript_derived"] is None
    assert updated.coaching_json == VALID_ANSWER  # coaching still runs on metrics alone
    assert "no transcript available for marked_up_example" in updated.coaching_warnings


def test_coach_analysis_model_not_allowed_stores_warning_without_calling_the_provider(cfg, session):
    user = repo.upsert_user(session, "u", None, None)
    row = _mk(session, user, "a" * 64, utcnow())
    restricted_cfg = cfg.model_copy(update={"llm": cfg.llm.model_copy(update={"allowed_models": ["x"]})})
    provider = FakeProvider([VALID_ANSWER])

    updated = service.coach_analysis(session, restricted_cfg, _settings(), user.id, row.id, model="y",
                                     speaker_context=None, provider=provider)

    assert updated.coaching_json is None
    assert updated.coaching_warnings == [service.MODEL_NOT_ALLOWED.format(model="y")]
    assert provider.calls == []  # rejected before the provider was ever called


def test_coach_analysis_unknown_analysis_returns_none(cfg, session):
    import uuid
    user = repo.upsert_user(session, "u", None, None)
    assert service.coach_analysis(session, cfg, _settings(), user.id, uuid.uuid4(), model="test-model",
                                  speaker_context=None, provider=FakeProvider([VALID_ANSWER])) is None

"""API tests for the LLM path: /llm/models, /me's llm fields, and POST /analyses/{id}/coach.

No network: the provider is always a FakeProvider, injected via monkeypatching
vocal_coach.llm.service.get_provider (the only place the API/pipeline look providers up)."""
from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from tests.api_fixtures import make_test_app
from tests.fake_llm import FakeProvider
from tests.test_api_analyses import _upload, fake_job_fn
from vocal_coach.config import load_config
from vocal_coach.llm import service
from vocal_coach.llm.base import LLMError

VALID_COACHING = {
    "what_improved": ["steady pace"],
    "what_is_lacking": ["flat intonation"],
    "next_steps": ["vary pitch on key words"],
    "marked_up_example": "hi",
}


def _cfg(**llm_overrides):
    cfg = load_config()
    return cfg.model_copy(update={"llm": cfg.llm.model_copy(update=llm_overrides)})


def _create_analysis(client, ctx) -> str:
    job_id = _upload(client, ctx["auth"]()).json()["job_ids"][0]
    return client.get(f"/api/jobs/{job_id}", headers=ctx["auth"]()).json()["analysis_id"]


def test_llm_models_disabled_reports_no_provider_and_does_not_call_it(tmp_path):
    app, ctx = make_test_app(tmp_path, cfg=_cfg(enabled=False))
    with TestClient(app) as client:
        r = client.get("/api/llm/models", headers=ctx["auth"]())
        assert r.status_code == 200
        assert r.json() == {"enabled": False, "provider": None, "models": []}


def test_llm_models_enabled_lists_the_providers_models(tmp_path, monkeypatch):
    app, ctx = make_test_app(tmp_path, cfg=_cfg(enabled=True, provider="openai_compatible"))
    monkeypatch.setattr("vocal_coach.llm.service.get_provider",
                        lambda *a, **k: FakeProvider([], models=["a", "b"]))
    with TestClient(app) as client:
        r = client.get("/api/llm/models", headers=ctx["auth"]())
        assert r.status_code == 200
        assert r.json() == {"enabled": True, "provider": "openai_compatible", "models": ["a", "b"]}


def test_llm_models_filtered_by_allowed_models(tmp_path, monkeypatch):
    app, ctx = make_test_app(tmp_path, cfg=_cfg(enabled=True, allowed_models=["b"]))
    monkeypatch.setattr("vocal_coach.llm.service.get_provider",
                        lambda *a, **k: FakeProvider([], models=["a", "b"]))
    with TestClient(app) as client:
        r = client.get("/api/llm/models", headers=ctx["auth"]())
        assert r.status_code == 200 and r.json()["models"] == ["b"]


def test_llm_models_provider_unavailable_is_503(tmp_path, monkeypatch):
    app, ctx = make_test_app(tmp_path, cfg=_cfg(enabled=True))

    def _raise(*_a, **_k):
        raise LLMError("connection refused")

    monkeypatch.setattr("vocal_coach.llm.service.get_provider", _raise)
    with TestClient(app) as client:
        r = client.get("/api/llm/models", headers=ctx["auth"]())
        assert r.status_code == 503
        assert "connection refused" in r.json()["detail"]


def test_me_llm_fields_mirror_config(tmp_path):
    app, ctx = make_test_app(tmp_path, cfg=_cfg(enabled=True, provider="anthropic"))
    with TestClient(app) as client:
        body = client.get("/api/me", headers=ctx["auth"]()).json()
        assert body["llm_enabled"] is True and body["llm_provider"] == "anthropic"

    app2, ctx2 = make_test_app(tmp_path, cfg=_cfg(enabled=False))
    with TestClient(app2) as client:
        body = client.get("/api/me", headers=ctx2["auth"]()).json()
        assert body["llm_enabled"] is False and body["llm_provider"] is None


def test_coach_404_when_analysis_does_not_exist(tmp_path):
    app, ctx = make_test_app(tmp_path, cfg=_cfg(enabled=True))
    with TestClient(app) as client:
        r = client.post(f"/api/analyses/{uuid.uuid4()}/coach", headers=ctx["auth"]())
        assert r.status_code == 404


def test_coach_503_when_disabled(tmp_path):
    app, ctx = make_test_app(tmp_path, cfg=_cfg(enabled=False), job_fn=fake_job_fn)
    with TestClient(app) as client:
        analysis_id = _create_analysis(client, ctx)
        r = client.post(f"/api/analyses/{analysis_id}/coach", headers=ctx["auth"]())
        assert r.status_code == 503
        assert r.json()["detail"] == "coaching is not enabled on this server"


def test_coach_422_when_model_not_allowed(tmp_path):
    app, ctx = make_test_app(tmp_path, cfg=_cfg(enabled=True, allowed_models=["ok-model"]), job_fn=fake_job_fn)
    with TestClient(app) as client:
        analysis_id = _create_analysis(client, ctx)
        r = client.post(f"/api/analyses/{analysis_id}/coach", headers=ctx["auth"](), json={"model": "nope"})
        assert r.status_code == 422
        assert r.json()["detail"] == service.MODEL_NOT_ALLOWED.format(model="nope")


def test_coach_200_stores_and_returns_coaching(tmp_path, monkeypatch):
    app, ctx = make_test_app(tmp_path, cfg=_cfg(enabled=True, model="test-model"), job_fn=fake_job_fn)
    monkeypatch.setattr("vocal_coach.llm.service.get_provider", lambda *a, **k: FakeProvider([VALID_COACHING]))
    with TestClient(app) as client:
        analysis_id = _create_analysis(client, ctx)
        r = client.post(f"/api/analyses/{analysis_id}/coach", headers=ctx["auth"](),
                        json={"speaker_context": "investor pitch"})
        assert r.status_code == 200
        body = r.json()
        assert body["coaching"] == VALID_COACHING
        assert body["speaker_context"] == "investor pitch"
        listing = client.get("/api/analyses", headers=ctx["auth"]()).json()
        assert listing[0]["has_coaching"] is True


def test_coach_200_with_provider_failure_stores_warning_not_an_error(tmp_path, monkeypatch):
    # Coaching never fails the request either: a provider failure during a re-run is a 200 with a
    # stored warning and coaching: null, exactly like the pipeline's degrade path (Review Focus 1).
    app, ctx = make_test_app(tmp_path, cfg=_cfg(enabled=True, model="test-model"), job_fn=fake_job_fn)
    monkeypatch.setattr("vocal_coach.llm.service.get_provider",
                        lambda *a, **k: FakeProvider([LLMError("down")]))
    with TestClient(app) as client:
        analysis_id = _create_analysis(client, ctx)
        r = client.post(f"/api/analyses/{analysis_id}/coach", headers=ctx["auth"]())
        assert r.status_code == 200
        body = r.json()
        assert body["coaching"] is None
        assert body["coaching_warnings"] == ["coaching failed: down"]

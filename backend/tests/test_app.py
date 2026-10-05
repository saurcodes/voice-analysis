from fastapi.testclient import TestClient

from tests.api_fixtures import make_test_app
from tests.auth_keys import mint
from vocal_coach.config import load_config
from vocal_coach.storage import repo


def _llm_disabled_cfg():
    """These smoke tests are not about the LLM path; keep it disabled so they stay independent of
    whatever config.yaml's defaults happen to be (dedicated LLM behaviour is in test_api_llm.py)."""
    cfg = load_config()
    return cfg.model_copy(update={"llm": cfg.llm.model_copy(update={"enabled": False})})


def test_me_requires_auth_and_upserts_user(tmp_path):
    app, ctx = make_test_app(tmp_path, cfg=_llm_disabled_cfg())
    with TestClient(app) as client:
        assert client.get("/api/me").status_code == 401
        assert client.get("/api/me", headers={"Authorization": "Bearer nope"}).status_code == 401
        r = client.get("/api/me", headers=ctx["auth"]("sub-42"))
        assert r.status_code == 200
        body = r.json()
        assert body["username"] == "user1" and body["drive_connected"] is False
        assert body["llm_enabled"] is False and body["llm_provider"] is None
        with ctx["session_factory"]() as s:
            user = repo.upsert_user(s, "sub-42", None, None)  # already exists; id stable
            assert str(user.id) == body["id"]


def test_account_only_audience_rejected_at_api(tmp_path):
    app, ctx = make_test_app(tmp_path)
    with TestClient(app) as client:
        token = mint(ctx["pem"], ctx["kid"], iss=ctx["iss"], aud="account")
        assert client.get("/api/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_config_public_and_llm_stub(tmp_path):
    app, ctx = make_test_app(tmp_path, cfg=_llm_disabled_cfg())
    with TestClient(app) as client:
        r = client.get("/api/config/public", headers=ctx["auth"]())
        assert r.status_code == 200
        assert r.json()["comparison"]["directions"]["pitch.f0_range_st"] == "up_good"
        assert r.json()["analysis"]["intonation_threshold_st"] == 1.5
        r = client.get("/api/llm/models", headers=ctx["auth"]())
        assert r.status_code == 200 and r.json() == {"enabled": False, "provider": None, "models": []}


def test_lifespan_fails_stale_jobs(tmp_path):
    app, ctx = make_test_app(tmp_path)
    with ctx["session_factory"]() as s:
        user = repo.upsert_user(s, "sub-1", None, None)
        stale = repo.create_job(s, user.id)
        repo.update_job(s, stale.id, status="running", stage="analyse", progress_pct=55)
    with TestClient(app) as client:
        r = client.get(f"/api/jobs/{stale.id}", headers=ctx["auth"]("sub-1"))
        assert r.status_code == 200
        assert r.json()["status"] == "failed" and r.json()["error"] == "server restarted"


def test_openapi_documents_the_contract_plan5_needs(tmp_path):
    app, ctx = make_test_app(tmp_path, cfg=_llm_disabled_cfg())
    with TestClient(app) as client:
        spec = client.get("/openapi.json").json()
        upload = spec["paths"]["/api/analyses"]["post"]
        form = upload["requestBody"]["content"]["multipart/form-data"]["schema"]
        assert form["required"] == ["file"] and form["properties"]["file"] == {"type": "string", "format": "binary"}
        assert form["properties"]["recorded_at"]["format"] == "date-time"
        assert {"202", "404", "409"} <= set(upload["responses"])
        assert "application/json" in upload["requestBody"]["content"]
        schemas = spec["components"]["schemas"]
        for name in ("MetricsReport", "Transcript", "PublicConfig", "LlmModels", "ComparisonResult",
                     "AnalysisSummary", "JobStatus", "AnalysisDetail"):
            assert name in schemas, name
        assert schemas["JobStatus"]["properties"]["status"]["enum"] == ["queued", "running", "done", "failed"]
        assert "class" in schemas["PhraseContour"]["properties"]  # serialised by alias, as stored
        assert {"404", "422", "503"} <= set(spec["paths"]["/api/analyses/{analysis_id}/coach"]["post"]["responses"])
        assert {"202", "409", "410"} <= set(spec["paths"]["/api/jobs/{job_id}/retry"]["post"]["responses"])
        assert "/api/jobs" in spec["paths"]
        assert client.get("/api/me", headers=ctx["auth"]()).json()["llm_enabled"] is False


def test_cors_allows_frontend_origin(tmp_path):
    app, ctx = make_test_app(tmp_path)
    with TestClient(app) as client:
        r = client.options("/api/me", headers={"Origin": ctx["settings"].frontend_origin,
                                               "Access-Control-Request-Method": "GET"})
        assert r.headers.get("access-control-allow-origin") == ctx["settings"].frontend_origin

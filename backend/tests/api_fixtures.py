"""Build a fully wired FastAPI app on SQLite with a synchronous fake job runner."""
from __future__ import annotations

from pathlib import Path

from tests.auth_keys import make_rsa_jwks, mint
from vocal_coach.auth.jwt import JWKSCache
from vocal_coach.config import load_config
from vocal_coach.jobs.runner import JobRunner, SyncExecutor
from vocal_coach.main import create_app
from vocal_coach.settings import Settings
from vocal_coach.storage.db import create_all, make_engine, make_session_factory

ISS = "http://kc.test/realms/vocal-coach"
AUD = "vocal-coach-web"


def make_test_app(tmp_path: Path, *, job_fn=None, max_upload_mb: int = 500):
    pem, jwks, kid = make_rsa_jwks()
    settings = Settings(_env_file=None, database_url=f"sqlite+pysqlite:///{tmp_path / 't.db'}",
                        keycloak_issuer=ISS, keycloak_audience=AUD, data_dir=tmp_path / "data",
                        max_upload_mb=max_upload_mb, require_ffmpeg=False, job_workers=1)
    cfg = load_config()
    engine = make_engine(settings.database_url)
    create_all(engine)
    runner = JobRunner(settings, cfg, executor=SyncExecutor(), job_fn=job_fn)
    app = create_app(settings, cfg, engine=engine, runner=runner,
                     jwks=JWKSCache(settings.jwks_url, fetch=lambda url: jwks, min_refresh_interval_s=0.0),
                     run_migrations=False)
    ctx = {
        "pem": pem, "kid": kid, "iss": ISS, "aud": AUD, "settings": settings, "cfg": cfg,
        "session_factory": make_session_factory(engine),
        "token": lambda sub="user-1", **kw: mint(pem, kid, iss=ISS, aud=AUD, sub=sub, **kw),
    }
    ctx["auth"] = lambda sub="user-1": {"Authorization": f"Bearer {ctx['token'](sub)}"}
    return app, ctx

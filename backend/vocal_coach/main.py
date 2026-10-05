"""FastAPI application factory. Everything heavy is injectable for tests."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import Engine

from vocal_coach.analysis.audio import check_ffmpeg
from vocal_coach.api import analyses, comparisons, config_public, drive, jobs, llm, me
from vocal_coach.auth.jwt import AuthError, JWKSCache
from vocal_coach.config import AppConfig, load_config
from vocal_coach.jobs.runner import JobRunner
from vocal_coach.settings import Settings, get_settings
from vocal_coach.storage import repo
from vocal_coach.storage.db import make_engine, make_session_factory
from vocal_coach.storage.migrate import upgrade_to_head

log = logging.getLogger(__name__)
API_PREFIX = "/api"


def create_app(
    settings: Settings | None = None, cfg: AppConfig | None = None, *,
    engine: Engine | None = None, runner: JobRunner | None = None, jwks: JWKSCache | None = None,
    run_migrations: bool = True,
) -> FastAPI:
    settings = settings or get_settings()
    cfg = cfg or load_config()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if settings.require_ffmpeg:
            check_ffmpeg()
        nonlocal engine, runner, jwks
        if engine is None:
            if run_migrations:
                upgrade_to_head(settings.database_url)
            engine = make_engine(settings.database_url)
        if runner is None:
            from vocal_coach.jobs.runner import make_process_runner  # Task 4
            runner = make_process_runner(settings, cfg)
        if jwks is None:
            jwks = JWKSCache(settings.jwks_url)
        app.state.settings, app.state.cfg, app.state.engine = settings, cfg, engine
        app.state.session_factory = make_session_factory(engine)
        app.state.runner, app.state.jwks = runner, jwks
        with app.state.session_factory() as session:
            failed = repo.fail_stale_jobs(session)
            if failed:
                log.warning("marked %d stale job(s) failed after restart", failed)
        runner.start()
        try:
            yield
        finally:
            runner.stop()

    app = FastAPI(title="Vocal Coach API", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=[settings.frontend_origin], allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])

    # Backstop: get_current_user already maps AuthError → 401; this catches any route raising it directly.
    @app.exception_handler(AuthError)
    async def _auth_error(_request, exc: AuthError):
        return JSONResponse({"detail": f"invalid token: {exc}"}, status_code=401, headers={"WWW-Authenticate": "Bearer"})

    for router in (me.router, config_public.router, llm.router, analyses.router, jobs.router, comparisons.router,
                   drive.router):
        app.include_router(router, prefix=API_PREFIX)
    return app


def _default_app() -> FastAPI:
    return create_app()

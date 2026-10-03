import logging
import os
import shutil
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect

from vocal_coach.storage.db import make_engine
from vocal_coach.storage.migrate import upgrade_to_head
from vocal_coach.storage.models import Base

EXPECTED_TABLES = {"users", "drive_connections", "analyses", "jobs", "alembic_version"}

# compare_metadata entry "op" strings that indicate a real schema drift between the models and
# the migration. Other ops (e.g. SQLite type-affinity noise) are filtered out and, if any show
# up, must be reported rather than silently ignored.
_SIGNIFICANT_DIFF_OPS = {
    "add_column",
    "remove_column",
    "modify_default",
    "modify_nullable",
    "add_constraint",
    "remove_constraint",
    "add_table",
    "remove_table",
    "add_index",
    "remove_index",
    "modify_type",
}


def _diff_op(entry) -> str:
    # Column-level modify_* entries come wrapped in a list of tuples; table-level ones are tuples.
    return entry[0][0] if isinstance(entry, list) else entry[0]


def test_upgrade_head_on_sqlite_creates_all_tables(tmp_path: Path):
    url = f"sqlite+pysqlite:///{tmp_path / 'm.db'}"
    upgrade_to_head(url)
    insp = inspect(make_engine(url))
    assert set(insp.get_table_names()) == EXPECTED_TABLES
    assert ["user_id", "content_sha256", "config_hash", "analyser_version"] in [
        u["column_names"] for u in insp.get_unique_constraints("analyses")]


def test_upgrade_head_is_idempotent(tmp_path: Path):
    url = f"sqlite+pysqlite:///{tmp_path / 'm.db'}"
    upgrade_to_head(url)
    upgrade_to_head(url)  # second run is a no-op, must not raise


def test_upgrade_head_does_not_disable_app_loggers(tmp_path: Path):
    probe = logging.getLogger("vocal_coach.test_probe")
    root_level = logging.getLogger().level
    upgrade_to_head(f"sqlite+pysqlite:///{tmp_path / 'm.db'}")
    assert probe.disabled is False
    assert logging.getLogger().level == root_level


def test_explicit_url_wins_over_database_url_env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'bogus.db'}")
    url = f"sqlite+pysqlite:///{tmp_path / 'm.db'}"
    upgrade_to_head(url)
    assert set(inspect(make_engine(url)).get_table_names()) == EXPECTED_TABLES
    assert not (tmp_path / "bogus.db").exists()
    assert os.environ["DATABASE_URL"].endswith("bogus.db")  # upgrade_to_head no longer touches the environment


def test_upgrade_head_matches_models_metadata(tmp_path: Path):
    """Pin models.py and the 0001 migration together: a future `alembic revision
    --autogenerate` should propose nothing. Diff ops outside _SIGNIFICANT_DIFF_OPS (e.g.
    SQLite type-affinity noise) are excluded; any such exclusion must be reported."""
    url = f"sqlite+pysqlite:///{tmp_path / 'm.db'}"
    upgrade_to_head(url)
    engine = make_engine(url)
    try:
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            diff = compare_metadata(ctx, Base.metadata)
    finally:
        engine.dispose()
    significant = [d for d in diff if _diff_op(d) in _SIGNIFICANT_DIFF_OPS]
    excluded = [d for d in diff if _diff_op(d) not in _SIGNIFICANT_DIFF_OPS]
    if excluded:
        print(f"compare_metadata entries excluded as non-significant: {excluded}")
    assert significant == [], f"models/migration drift: {significant}"


# Rancher Desktop's user-mode networking cannot start testcontainers' ryuk reaper; disable it by
# default. setdefault keeps any value CI or a developer already exported. PostgresContainer's
# __exit__ still removes the container.
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")

requires_docker = pytest.mark.skipif(shutil.which("docker") is None, reason="docker not installed")


@requires_docker
@pytest.mark.filterwarnings(
    "ignore:testcontainers.postgres is deprecated, use testcontainers.community.postgres instead:DeprecationWarning"
)
def test_upgrade_head_on_real_postgres():
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:16-alpine", driver="psycopg") as pg:
        url = pg.get_connection_url()
        upgrade_to_head(url)
        engine = make_engine(url)
        try:
            insp = inspect(engine)
            assert set(insp.get_table_names()) == EXPECTED_TABLES
            cols = {c["name"]: c["type"].__class__.__name__ for c in insp.get_columns("analyses")}
            assert cols["metrics_json"] == "JSONB"
            assert cols["id"] == "UUID"
            _postgres_repo_round_trip(engine)
            with engine.connect() as conn:
                ctx = MigrationContext.configure(conn, opts={"compare_type": True, "compare_server_default": True})
                diff = compare_metadata(ctx, Base.metadata)
            assert diff == [], f"models/migration drift on Postgres: {diff}"
        finally:
            engine.dispose()


def _postgres_repo_round_trip(engine) -> None:
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select, text

    from vocal_coach.storage import repo
    from vocal_coach.storage.db import make_session_factory
    from vocal_coach.storage.models import Analysis, Job

    factory = make_session_factory(engine)
    ist = datetime(2026, 10, 3, 9, 30, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    metrics = {"pitch": {"f0_median_hz": 118.5, "f0_range_st": 9.25, "track": [1.5, None, 2.25]},
               "intonation": {"flat_pct": 31.0}, "phrasing": {"pauses_per_min": 12.5},
               "pace": {"articulation_rate_syl_per_sec": 4.75}, "energy": {"trailing_off_count": 3},
               "nested": {"a": {"b": [{"c": None}, {"d": 0.125}]}}}
    with factory() as s:
        user = repo.upsert_user(s, "pg-sub", "pg@x.test", "pg")
        analysis = repo.create_analysis(
            s, user.id, file_name="a.m4a", drive_file_id=None, content_sha256="a" * 64, recorded_at=ist,
            analyser_version="0.1.0", config_hash="sha256:c1", metrics_json=metrics, transcript_json=None)
        job = repo.create_job(s, user.id)
        repo.update_job(s, job.id, status="done", progress_pct=100, analysis_id=analysis.id)
        user_id, analysis_id, job_id = user.id, analysis.id, job.id
    with factory() as s:
        loaded = repo.get_analysis(s, user_id, analysis_id)
        assert loaded.metrics_json == metrics
        assert loaded.transcript_json is None
        assert s.execute(text("select transcript_json is null from analyses where id = :i"), {"i": analysis_id}).scalar() is True
        assert loaded.recorded_at.tzinfo is not None and loaded.recorded_at == ist
        [summary] = repo.list_analysis_summaries(s, user_id)
        assert (summary.f0_median_hz, summary.f0_range_st, summary.flat_pct, summary.pauses_per_min,
                summary.articulation_rate_syl_per_sec, summary.trailing_off_count) == (118.5, 9.25, 31.0, 12.5, 4.75, 3)
        assert summary.fillers_per_min is None and summary.has_transcript is False and summary.has_coaching is False
        assert summary.recorded_at == ist
    with factory() as s:
        assert repo.delete_analysis(s, user_id, analysis_id) is True
        assert repo.get_job(s, user_id, job_id).analysis_id is None  # ON DELETE SET NULL
        repo.create_analysis(
            s, user_id, file_name="b.m4a", drive_file_id=None, content_sha256="b" * 64, recorded_at=ist,
            analyser_version="0.1.0", config_hash="sha256:c1", metrics_json={})
        s.execute(text("delete from users where id = :i"), {"i": user_id})
        s.commit()
        assert s.scalars(select(Analysis)).all() == []  # ON DELETE CASCADE
        assert s.scalars(select(Job)).all() == []

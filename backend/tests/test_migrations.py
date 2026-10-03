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
        finally:
            engine.dispose()

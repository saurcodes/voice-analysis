import shutil
from pathlib import Path

import pytest
from sqlalchemy import inspect

from vocal_coach.storage.db import make_engine
from vocal_coach.storage.migrate import upgrade_to_head

EXPECTED_TABLES = {"users", "drive_connections", "analyses", "jobs", "alembic_version"}


def test_upgrade_head_on_sqlite_creates_all_tables(tmp_path: Path):
    url = f"sqlite+pysqlite:///{tmp_path / 'm.db'}"
    upgrade_to_head(url)
    insp = inspect(make_engine(url))
    assert set(insp.get_table_names()) == EXPECTED_TABLES
    assert ["user_id", "content_sha256", "config_hash"] in [u["column_names"] for u in insp.get_unique_constraints("analyses")]


def test_upgrade_head_is_idempotent(tmp_path: Path):
    url = f"sqlite+pysqlite:///{tmp_path / 'm.db'}"
    upgrade_to_head(url)
    upgrade_to_head(url)  # second run is a no-op, must not raise


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

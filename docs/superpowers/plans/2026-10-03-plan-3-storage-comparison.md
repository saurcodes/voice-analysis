# Vocal Coach — Plan 3: Storage and Comparison Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist users, analyses and jobs in Postgres through SQLAlchemy 2 + Alembic with strict per-user scoping, and compute direction-aware comparisons and trend series across a user's recordings.

**Architecture:** New `backend/vocal_coach/storage/` package. `models.py` declares the four spec tables with types that work on both Postgres (JSONB, UUID) and SQLite (so unit tests run in-memory without Docker). `db.py` builds the engine from `DATABASE_URL`. `repo.py` is the only place that queries; every read takes a `user_id` and returns `None` for rows the user does not own. `comparison.py` is a pure function over in-memory analysis records driven by `config.yaml → comparison`. Alembic owns the schema; one initial migration creates everything. A single Docker-gated test runs that migration against a real Postgres container.

**Tech Stack:** SQLAlchemy ≥ 2.0, Alembic, psycopg 3, pydantic-settings, testcontainers (dev, Docker-gated), pytest.

**Spec:** `docs/superpowers/specs/2026-10-03-vocal-coach-design.md` — §8 (Storage), §9 (Comparison), §16 rows `test_comparison`, `test_repo`.

## Global Constraints

- Python ≥ 3.11; package at `backend/vocal_coach/storage`; tests at `backend/tests`; run from `backend/` with `.venv` (never the system python).
- Tables and columns exactly as spec §8: `users(id uuid pk, keycloak_sub text unique, email, username, created_at)`, `drive_connections(user_id uuid pk fk, encrypted_refresh_token bytea, google_email, connected_at)`, `analyses(id uuid pk, user_id fk, file_name, drive_file_id null, content_sha256, recorded_at, analysed_at, analyser_version, config_hash, metrics_json jsonb, transcript_json jsonb null, speaker_context null, coaching_json jsonb null, coaching_warnings jsonb null; unique (user_id, content_sha256, config_hash))`, `jobs(id uuid pk, user_id fk, status in queued|running|done|failed, stage, progress_pct int, error null, analysis_id fk null, created_at, updated_at)`.
- Strict per-user scoping: every repository read/write takes `user_id`; a row owned by another user is `None` to the caller (API layer maps to 404 in Plan 4).
- Comparison per spec §9: for each dotted path in `comparison.directions`, `values[]` ordered by `recorded_at`, `delta` = last − first, step deltas between consecutive recordings, arrow `↑ ↓ →`, verdict `improved | worsened | neutral | unchanged`; `unchanged` when `|delta| < min_meaningful_change_pct % of the earlier value`; `config_mismatch: true` when `config_hash` differs; trend series for every path.
- `transcript.*` paths resolve into `transcript_json`; all other paths into `metrics_json`. A missing or `null` value yields `None` in `values[]` and the row verdict `unavailable` — never an exception.
- Database URL from env `DATABASE_URL` (pydantic-settings); tests use `sqlite+pysqlite:///:memory:` unless the Docker-gated test runs.
- `config_hash` (analysis+articulation) unchanged; the new `comparison` config section is validated but not hashed.
- Test output pristine under `pytest -v -W error`. Commit after every task; messages end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

## Review Focus

1. **A metric missing in one recording** (older `analyser_version`, `null` from no-voiced-speech, transcript absent): row verdict `unavailable`, other rows unaffected, no exception. Test in Task 5.
2. **Earlier value exactly 0** (zero fillers, zero long pauses): the percent rule must not divide by zero; `unchanged` iff delta is 0. Test in Task 5.
3. **Cross-user access by id** (user B asks for user A's analysis or job): `None`, not the row and not an exception. Test in Task 4.
4. **Second upload of the same file with the same config**: `find_analysis` returns the existing row; inserting a duplicate raises `IntegrityError` (unique constraint actually present in the schema, not only in the ORM). Test in Task 2 and Task 4.
5. **Analyses passed out of order or with mixed `config_hash`**: comparison sorts by `recorded_at` itself and sets `config_mismatch`. Test in Task 5.

---

### Task 1: Settings, comparison config, dependencies

**Files:**
- Modify: `backend/pyproject.toml` (add `sqlalchemy>=2.0`, `alembic>=1.13`, `psycopg[binary]>=3.1`, `pydantic-settings>=2.2`; dev: `testcontainers[postgres]>=4.0`)
- Modify: `backend/requirements.lock` (regenerate: `pip freeze | grep -v '^-e' > requirements.lock`)
- Create: `backend/vocal_coach/settings.py`
- Modify: `backend/vocal_coach/config.py` (add `ComparisonConfig`, `AppConfig.comparison`)
- Modify: `backend/tests/test_config.py` (append)
- Create: `backend/tests/test_settings.py`

**Interfaces:**
- Produces: `class Settings(BaseSettings)` with `database_url: str = "postgresql+psycopg://vocal:vocal@localhost:5432/vocal_coach"`, `model_config = SettingsConfigDict(env_prefix="", env_file=".env", extra="ignore")`; `get_settings() -> Settings` (plain function, no caching — tests set env and call it).
- Produces: `Direction = Literal["up_good", "down_good", "neutral"]`; `class ComparisonConfig(BaseModel)`: `min_meaningful_change_pct: float`, `directions: dict[str, Direction]`; `AppConfig.comparison: ComparisonConfig`.

- [ ] **Step 1: Dependencies**

Edit `backend/pyproject.toml`:

```toml
dependencies = [
  "praat-parselmouth>=0.4.3",
  "numpy>=1.26",
  "scipy>=1.11",
  "pydantic>=2.5",
  "pyyaml>=6.0",
  "faster-whisper>=1.0",
  "sqlalchemy>=2.0",
  "alembic>=1.13",
  "psycopg[binary]>=3.1",
  "pydantic-settings>=2.2",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "testcontainers[postgres]>=4.0"]
```

Run: `pip install -e ".[dev]" && pip freeze | grep -v '^-e' > requirements.lock`. Confirm `praat-parselmouth`, `numpy`, `scipy` pins are unchanged (`git diff requirements.lock | grep -E '^[-+](praat|numpy|scipy)'` prints nothing).

- [ ] **Step 2: Write the failing tests**

Append to `backend/tests/test_config.py`:

```python
def test_comparison_section_loads():
    cfg = load_config()
    assert cfg.comparison.min_meaningful_change_pct == 5
    assert cfg.comparison.directions["pitch.f0_range_st"] == "up_good"
    assert cfg.comparison.directions["phrasing.pauses_per_min"] == "neutral"
    assert cfg.comparison.directions["transcript.derived.clarity.rushed_word_fraction"] == "down_good"
    assert len(cfg.comparison.directions) == 15


def test_comparison_direction_must_be_known():
    import pytest
    from vocal_coach.config import ComparisonConfig
    with pytest.raises(ValueError):
        ComparisonConfig(min_meaningful_change_pct=5, directions={"x": "sideways"})


def test_config_hash_ignores_comparison():
    src = load_config()
    changed = src.model_copy(deep=True)
    changed.comparison.min_meaningful_change_pct = 50
    assert config_hash(src) == config_hash(changed)
```

`backend/tests/test_settings.py`:

```python
from vocal_coach.settings import Settings, get_settings


def test_default_database_url_is_postgres():
    s = Settings(_env_file=None)
    assert s.database_url.startswith("postgresql+psycopg://")


def test_database_url_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    assert get_settings().database_url == "sqlite+pysqlite:///:memory:"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_config.py tests/test_settings.py -v`
Expected: FAIL (`AttributeError: comparison`, `ModuleNotFoundError: vocal_coach.settings`).

- [ ] **Step 4: Implement**

`backend/vocal_coach/settings.py`:

```python
"""Process-level settings from environment / .env (not from config.yaml)."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://vocal:vocal@localhost:5432/vocal_coach"


def get_settings() -> Settings:
    return Settings()
```

In `backend/vocal_coach/config.py` add (after `ClarityConfig`):

```python
Direction = Literal["up_good", "down_good", "neutral"]


class ComparisonConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_meaningful_change_pct: float
    directions: dict[str, Direction]
```

(`from typing import Any, Literal`.) Add `comparison: ComparisonConfig` to `AppConfig` and `comparison=ComparisonConfig(**raw["comparison"])` in `load_config`. `config_hash` untouched.

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_config.py tests/test_settings.py tests/test_determinism.py -v -W error`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/pyproject.toml backend/requirements.lock backend/vocal_coach/settings.py backend/vocal_coach/config.py backend/tests/test_config.py backend/tests/test_settings.py
git commit -m "feat(storage): settings, comparison config, SQLAlchemy/Alembic dependencies

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: SQLAlchemy models and engine

**Files:**
- Create: `backend/vocal_coach/storage/__init__.py` (empty)
- Create: `backend/vocal_coach/storage/models.py`
- Create: `backend/vocal_coach/storage/db.py`
- Create: `backend/tests/test_models.py`

**Interfaces:**
- Produces (`models.py`): `class Base(DeclarativeBase)`; `JSONType` (JSON with JSONB variant on postgresql); `User(id: uuid.UUID, keycloak_sub: str, email: str | None, username: str | None, created_at: datetime)`; `DriveConnection(user_id, encrypted_refresh_token: bytes, google_email: str | None, connected_at)`; `Analysis(id, user_id, file_name, drive_file_id, content_sha256, recorded_at, analysed_at, analyser_version, config_hash, metrics_json: dict, transcript_json: dict | None, speaker_context, coaching_json, coaching_warnings)` with `UniqueConstraint("user_id", "content_sha256", "config_hash", name="uq_analyses_user_sha_config")`; `Job(id, user_id, status, stage, progress_pct, error, analysis_id, created_at, updated_at)` with `CheckConstraint("status in ('queued','running','done','failed')", name="ck_jobs_status")`; `JOB_STATUSES = ("queued", "running", "done", "failed")`; `utcnow() -> datetime` (timezone-aware).
- Produces (`db.py`): `make_engine(url: str) -> Engine` (SQLite gets `connect_args={"check_same_thread": False}` and `StaticPool` for `:memory:`); `make_session_factory(engine) -> sessionmaker[Session]`; `create_all(engine)` (tests only; production uses Alembic).

- [ ] **Step 1: Write the failing test**

`backend/tests/test_models.py`:

```python
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from vocal_coach.storage.db import create_all, make_engine, make_session_factory
from vocal_coach.storage.models import Analysis, Job, User, utcnow


@pytest.fixture
def session():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    factory = make_session_factory(engine)
    with factory() as s:
        yield s


def test_tables_and_columns_match_spec(session):
    insp = inspect(session.get_bind())
    assert set(insp.get_table_names()) == {"users", "drive_connections", "analyses", "jobs"}
    cols = {c["name"] for c in insp.get_columns("analyses")}
    assert cols == {"id", "user_id", "file_name", "drive_file_id", "content_sha256", "recorded_at", "analysed_at",
                    "analyser_version", "config_hash", "metrics_json", "transcript_json", "speaker_context",
                    "coaching_json", "coaching_warnings"}
    assert {c["name"] for c in insp.get_columns("jobs")} == {"id", "user_id", "status", "stage", "progress_pct",
                                                              "error", "analysis_id", "created_at", "updated_at"}
    uniques = [u["column_names"] for u in insp.get_unique_constraints("analyses")]
    assert ["user_id", "content_sha256", "config_hash"] in uniques


def _user(session, sub="sub-1"):
    u = User(keycloak_sub=sub, email=f"{sub}@x.test", username=sub)
    session.add(u)
    session.commit()
    return u


def _analysis(user, sha="a" * 64, cfg="sha256:c1"):
    return Analysis(user_id=user.id, file_name="a.m4a", drive_file_id=None, content_sha256=sha,
                    recorded_at=utcnow(), analysed_at=utcnow(), analyser_version="0.1.0", config_hash=cfg,
                    metrics_json={"pitch": {"f0_median_hz": 120.0}}, transcript_json=None)


def test_round_trip_json_and_uuid(session):
    u = _user(session)
    a = _analysis(u)
    session.add(a)
    session.commit()
    loaded = session.get(Analysis, a.id)
    assert isinstance(loaded.id, uuid.UUID)
    assert loaded.metrics_json["pitch"]["f0_median_hz"] == 120.0
    assert loaded.transcript_json is None


def test_unique_user_sha_config_enforced_by_schema(session):
    u = _user(session)
    session.add(_analysis(u))
    session.commit()
    session.add(_analysis(u))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
    # same sha, different config → allowed
    session.add(_analysis(u, cfg="sha256:c2"))
    session.commit()


def test_same_file_two_users_allowed(session):
    a_user, b_user = _user(session, "a"), _user(session, "b")
    session.add_all([_analysis(a_user), _analysis(b_user)])
    session.commit()


def test_job_status_check_constraint(session):
    u = _user(session)
    session.add(Job(user_id=u.id, status="bogus", stage="download", progress_pct=0))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
    j = Job(user_id=u.id, status="queued", stage="download", progress_pct=0)
    session.add(j)
    session.commit()
    assert isinstance(j.created_at, datetime)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'vocal_coach.storage'`

- [ ] **Step 3: Implement models.py and db.py**

`backend/vocal_coach/storage/models.py`:

```python
"""SQLAlchemy models for spec §8. Portable across Postgres (JSONB/UUID) and SQLite (tests)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint, Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON

JOB_STATUSES = ("queued", "running", "done", "failed")
JSONType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    keycloak_sub: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    email: Mapped[str | None] = mapped_column(Text)
    username: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class DriveConnection(Base):
    __tablename__ = "drive_connections"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    encrypted_refresh_token: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    google_email: Mapped[str | None] = mapped_column(Text)
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Analysis(Base):
    __tablename__ = "analyses"
    __table_args__ = (UniqueConstraint("user_id", "content_sha256", "config_hash", name="uq_analyses_user_sha_config"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    file_name: Mapped[str] = mapped_column(Text, nullable=False)
    drive_file_id: Mapped[str | None] = mapped_column(Text)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    analysed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    analyser_version: Mapped[str] = mapped_column(Text, nullable=False)
    config_hash: Mapped[str] = mapped_column(Text, nullable=False)
    metrics_json: Mapped[dict] = mapped_column(JSONType, nullable=False)
    transcript_json: Mapped[dict | None] = mapped_column(JSONType)
    speaker_context: Mapped[str | None] = mapped_column(Text)
    coaching_json: Mapped[dict | None] = mapped_column(JSONType)
    coaching_warnings: Mapped[list | None] = mapped_column(JSONType)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (CheckConstraint("status in ('queued','running','done','failed')", name="ck_jobs_status"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    stage: Mapped[str] = mapped_column(Text, nullable=False)
    progress_pct: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    analysis_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("analyses.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
```

`backend/vocal_coach/storage/db.py`:

```python
"""Engine and session factory. Schema is owned by Alembic; create_all is for tests."""
from __future__ import annotations

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from vocal_coach.storage.models import Base


def make_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        engine = create_engine(url, connect_args={"check_same_thread": False},
                               poolclass=StaticPool if ":memory:" in url else None)

        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _record):  # SQLite ignores FKs unless asked
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

        return engine
    return create_engine(url, pool_pre_ping=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def create_all(engine: Engine) -> None:
    Base.metadata.create_all(engine)
```

- [ ] **Step 4: Run test**

Run: `pytest tests/test_models.py -v -W error`
Expected: 5 passed. If SQLAlchemy emits a `MovedIn20Warning`/`SAWarning` about the `poolclass=None` kwarg, pass `poolclass` only when `:memory:` is in the URL (build kwargs dict conditionally) rather than filtering the warning.

- [ ] **Step 5: Commit**

```bash
git add backend/vocal_coach/storage/__init__.py backend/vocal_coach/storage/models.py backend/vocal_coach/storage/db.py backend/tests/test_models.py
git commit -m "feat(storage): SQLAlchemy models for users, drive connections, analyses, jobs

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: Alembic initial migration (SQLite smoke + Docker-gated Postgres)

**Files:**
- Create: `backend/alembic.ini`
- Create: `backend/alembic/env.py`
- Create: `backend/alembic/script.py.mako`
- Create: `backend/alembic/versions/0001_initial.py`
- Create: `backend/vocal_coach/storage/migrate.py`
- Create: `backend/tests/test_migrations.py`

**Interfaces:**
- Produces: `migrate.upgrade_to_head(url: str) -> None` (programmatic `alembic upgrade head` using the repo's `alembic.ini`, overriding `sqlalchemy.url`); `migrate.ALEMBIC_INI: Path`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_migrations.py`:

```python
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
def test_upgrade_head_on_real_postgres():
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:16-alpine", driver="psycopg") as pg:
        url = pg.get_connection_url()
        upgrade_to_head(url)
        insp = inspect(make_engine(url))
        assert set(insp.get_table_names()) == EXPECTED_TABLES
        cols = {c["name"]: c["type"].__class__.__name__ for c in insp.get_columns("analyses")}
        assert cols["metrics_json"] == "JSONB"
        assert cols["id"] == "UUID"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_migrations.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'vocal_coach.storage.migrate'`

- [ ] **Step 3: Alembic scaffold**

`backend/alembic.ini`:

```ini
[alembic]
script_location = alembic
sqlalchemy.url = postgresql+psycopg://vocal:vocal@localhost:5432/vocal_coach
file_template = %%(rev)s_%%(slug)s

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = WARN
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

`backend/alembic/env.py`:

```python
from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from vocal_coach.storage.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Precedence: -x url=... (programmatic) > DATABASE_URL env > alembic.ini default.
_x = context.get_x_argument(as_dictionary=True)
_url = _x.get("url") or os.environ.get("DATABASE_URL")
if _url:
    config.set_main_option("sqlalchemy.url", _url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata,
                      literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(config.get_section(config.config_ini_section, {}),
                                     prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

`backend/alembic/script.py.mako`:

```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

`backend/alembic/versions/0001_initial.py`:

```python
"""initial schema: users, drive_connections, analyses, jobs

Revision ID: 0001
Revises:
Create Date: 2026-10-03
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

JSONType = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("keycloak_sub", sa.Text(), nullable=False, unique=True),
        sa.Column("email", sa.Text()),
        sa.Column("username", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "drive_connections",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("encrypted_refresh_token", sa.LargeBinary(), nullable=False),
        sa.Column("google_email", sa.Text()),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "analyses",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("file_name", sa.Text(), nullable=False),
        sa.Column("drive_file_id", sa.Text()),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("analysed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("analyser_version", sa.Text(), nullable=False),
        sa.Column("config_hash", sa.Text(), nullable=False),
        sa.Column("metrics_json", JSONType, nullable=False),
        sa.Column("transcript_json", JSONType),
        sa.Column("speaker_context", sa.Text()),
        sa.Column("coaching_json", JSONType),
        sa.Column("coaching_warnings", JSONType),
        sa.UniqueConstraint("user_id", "content_sha256", "config_hash", name="uq_analyses_user_sha_config"),
    )
    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("progress_pct", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text()),
        sa.Column("analysis_id", sa.Uuid(), sa.ForeignKey("analyses.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status in ('queued','running','done','failed')", name="ck_jobs_status"),
    )


def downgrade() -> None:
    op.drop_table("jobs")
    op.drop_table("analyses")
    op.drop_table("drive_connections")
    op.drop_table("users")
```

`backend/vocal_coach/storage/migrate.py`:

```python
"""Run Alembic programmatically (used by the backend at startup and by tests)."""
from __future__ import annotations

import os
from pathlib import Path

from alembic import command
from alembic.config import Config

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"
_URL_ENV = "DATABASE_URL"  # env.py gives this env var precedence over alembic.ini


def upgrade_to_head(url: str) -> None:
    """Upgrade the database at `url` to head. The explicit `url` always wins:
    env.py reads DATABASE_URL before alembic.ini, so set it for the duration of the call."""
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(ALEMBIC_INI.parent / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    previous = os.environ.get(_URL_ENV)
    os.environ[_URL_ENV] = url
    try:
        command.upgrade(cfg, "head")
    finally:
        if previous is None:
            os.environ.pop(_URL_ENV, None)
        else:
            os.environ[_URL_ENV] = previous
```

URL precedence in `env.py` is: `-x url=...` (CLI) → `DATABASE_URL` env → `alembic.ini`. `upgrade_to_head` uses the env slot so a programmatic caller's URL cannot be overridden by a stale shell variable.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_migrations.py -v -W error`
Expected: 3 passed (the Postgres test pulls `postgres:16-alpine` on first run; allow a minute). If `-W error` trips on a `DeprecationWarning` from `testcontainers` internals, report the exact message and mark it in the report; do not add a global filter — a targeted `pytest.mark.filterwarnings("ignore:<exact message>:DeprecationWarning")` on that one test is acceptable and must be mentioned in the report.

- [ ] **Step 5: Commit**

```bash
git add backend/alembic.ini backend/alembic backend/vocal_coach/storage/migrate.py backend/tests/test_migrations.py
git commit -m "feat(storage): Alembic initial migration with SQLite and Postgres tests

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: User-scoped repository

**Files:**
- Create: `backend/vocal_coach/storage/repo.py`
- Create: `backend/tests/test_repo.py`

**Interfaces:**
- Produces (all functions take a `Session` first):
  - `upsert_user(session, keycloak_sub: str, email: str | None, username: str | None) -> User` (insert or update email/username).
  - `find_analysis(session, user_id, content_sha256: str, config_hash: str) -> Analysis | None`.
  - `create_analysis(session, user_id, *, file_name, drive_file_id, content_sha256, recorded_at, analyser_version, config_hash, metrics_json, transcript_json=None, speaker_context=None) -> Analysis` (commits).
  - `list_analyses(session, user_id) -> list[Analysis]` ordered by `recorded_at` descending.
  - `get_analysis(session, user_id, analysis_id) -> Analysis | None` (None for another user's row).
  - `delete_analysis(session, user_id, analysis_id) -> bool`.
  - `set_coaching(session, user_id, analysis_id, *, speaker_context, coaching_json, coaching_warnings) -> Analysis | None`.
  - `create_job(session, user_id, stage: str = "queued") -> Job` (status `queued`, progress 0).
  - `update_job(session, job_id, **fields) -> Job | None` (fields among `status, stage, progress_pct, error, analysis_id`; validates `status in JOB_STATUSES`).
  - `get_job(session, user_id, job_id) -> Job | None`.
  - `fail_stale_jobs(session, message: str = "server restarted") -> int` (marks all `queued|running` → `failed` with `error=message`; returns count).

- [ ] **Step 1: Write the failing test**

`backend/tests/test_repo.py`:

```python
import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from vocal_coach.storage import repo
from vocal_coach.storage.db import create_all, make_engine, make_session_factory
from vocal_coach.storage.models import JOB_STATUSES, utcnow


@pytest.fixture
def session():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    with make_session_factory(engine)() as s:
        yield s


def _mk(session, user, sha="a" * 64, cfg="sha256:c1", when=None):
    return repo.create_analysis(
        session, user.id, file_name="a.m4a", drive_file_id=None, content_sha256=sha,
        recorded_at=when or utcnow(), analyser_version="0.1.0", config_hash=cfg,
        metrics_json={"pitch": {"f0_median_hz": 120.0}},
    )


def test_upsert_user_inserts_then_updates(session):
    u1 = repo.upsert_user(session, "sub-1", "a@x.test", "alice")
    u2 = repo.upsert_user(session, "sub-1", "new@x.test", "alice2")
    assert u1.id == u2.id
    assert u2.email == "new@x.test" and u2.username == "alice2"


def test_find_then_create_dedupes_same_file_same_config(session):
    u = repo.upsert_user(session, "sub-1", None, None)
    assert repo.find_analysis(session, u.id, "a" * 64, "sha256:c1") is None
    a = _mk(session, u)
    assert repo.find_analysis(session, u.id, "a" * 64, "sha256:c1").id == a.id
    assert repo.find_analysis(session, u.id, "a" * 64, "sha256:c2") is None
    with pytest.raises(IntegrityError):
        _mk(session, u)
    session.rollback()


def test_cross_user_get_returns_none(session):
    a_user = repo.upsert_user(session, "a", None, None)
    b_user = repo.upsert_user(session, "b", None, None)
    a = _mk(session, a_user)
    assert repo.get_analysis(session, a_user.id, a.id).id == a.id
    assert repo.get_analysis(session, b_user.id, a.id) is None
    assert repo.delete_analysis(session, b_user.id, a.id) is False
    assert repo.get_analysis(session, a_user.id, a.id) is not None
    assert repo.delete_analysis(session, a_user.id, a.id) is True
    assert repo.get_analysis(session, a_user.id, a.id) is None


def test_list_is_user_scoped_and_newest_first(session):
    from datetime import timedelta
    a_user = repo.upsert_user(session, "a", None, None)
    b_user = repo.upsert_user(session, "b", None, None)
    t0 = utcnow()
    old = _mk(session, a_user, sha="1" * 64, when=t0 - timedelta(days=2))
    new = _mk(session, a_user, sha="2" * 64, when=t0)
    _mk(session, b_user, sha="3" * 64)
    ids = [x.id for x in repo.list_analyses(session, a_user.id)]
    assert ids == [new.id, old.id]


def test_set_coaching_scoped(session):
    a_user = repo.upsert_user(session, "a", None, None)
    b_user = repo.upsert_user(session, "b", None, None)
    a = _mk(session, a_user)
    assert repo.set_coaching(session, b_user.id, a.id, speaker_context="x", coaching_json={"k": 1}, coaching_warnings=[]) is None
    updated = repo.set_coaching(session, a_user.id, a.id, speaker_context="pitch", coaching_json={"k": 1}, coaching_warnings=["17.3"])
    assert updated.speaker_context == "pitch" and updated.coaching_json == {"k": 1} and updated.coaching_warnings == ["17.3"]


def test_job_lifecycle_and_scoping(session):
    a_user = repo.upsert_user(session, "a", None, None)
    b_user = repo.upsert_user(session, "b", None, None)
    j = repo.create_job(session, a_user.id)
    assert j.status == "queued" and j.progress_pct == 0
    assert repo.get_job(session, b_user.id, j.id) is None
    j = repo.update_job(session, j.id, status="running", stage="analyse", progress_pct=40)
    assert (j.status, j.stage, j.progress_pct) == ("running", "analyse", 40)
    with pytest.raises(ValueError):
        repo.update_job(session, j.id, status="exploded")
    assert repo.update_job(session, uuid.uuid4(), status="done") is None
    a = _mk(session, a_user)
    j = repo.update_job(session, j.id, status="done", stage="done", progress_pct=100, analysis_id=a.id)
    assert j.analysis_id == a.id
    assert set(JOB_STATUSES) == {"queued", "running", "done", "failed"}


def test_fail_stale_jobs(session):
    u = repo.upsert_user(session, "a", None, None)
    q = repo.create_job(session, u.id)
    r = repo.update_job(session, repo.create_job(session, u.id).id, status="running")
    d = repo.update_job(session, repo.create_job(session, u.id).id, status="done")
    assert repo.fail_stale_jobs(session) == 2
    assert repo.get_job(session, u.id, q.id).status == "failed"
    assert repo.get_job(session, u.id, q.id).error == "server restarted"
    assert repo.get_job(session, u.id, r.id).status == "failed"
    assert repo.get_job(session, u.id, d.id).status == "done"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_repo.py -v`
Expected: FAIL with `ImportError: cannot import name 'repo'`

- [ ] **Step 3: Implement repo.py**

```python
"""All database access, strictly scoped by user_id. Rows the user does not own are None."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from vocal_coach.storage.models import JOB_STATUSES, Analysis, Job, User

JOB_UPDATABLE = frozenset({"status", "stage", "progress_pct", "error", "analysis_id"})
STALE_STATUSES = ("queued", "running")  # a restart means these can never finish


def upsert_user(session: Session, keycloak_sub: str, email: str | None, username: str | None) -> User:
    user = session.scalar(select(User).where(User.keycloak_sub == keycloak_sub))
    if user is None:
        user = User(keycloak_sub=keycloak_sub, email=email, username=username)
        session.add(user)
    else:
        user.email = email
        user.username = username
    session.commit()
    return user


def find_analysis(session: Session, user_id: uuid.UUID, content_sha256: str, config_hash: str) -> Analysis | None:
    return session.scalar(
        select(Analysis).where(Analysis.user_id == user_id, Analysis.content_sha256 == content_sha256,
                               Analysis.config_hash == config_hash)
    )


def create_analysis(
    session: Session, user_id: uuid.UUID, *, file_name: str, drive_file_id: str | None, content_sha256: str,
    recorded_at: datetime, analyser_version: str, config_hash: str, metrics_json: dict,
    transcript_json: dict | None = None, speaker_context: str | None = None,
) -> Analysis:
    row = Analysis(
        user_id=user_id, file_name=file_name, drive_file_id=drive_file_id, content_sha256=content_sha256,
        recorded_at=recorded_at, analyser_version=analyser_version, config_hash=config_hash,
        metrics_json=metrics_json, transcript_json=transcript_json, speaker_context=speaker_context,
    )
    session.add(row)
    session.commit()
    return row


def list_analyses(session: Session, user_id: uuid.UUID) -> list[Analysis]:
    return list(session.scalars(select(Analysis).where(Analysis.user_id == user_id).order_by(Analysis.recorded_at.desc())))


def get_analysis(session: Session, user_id: uuid.UUID, analysis_id: uuid.UUID) -> Analysis | None:
    return session.scalar(select(Analysis).where(Analysis.user_id == user_id, Analysis.id == analysis_id))


def delete_analysis(session: Session, user_id: uuid.UUID, analysis_id: uuid.UUID) -> bool:
    row = get_analysis(session, user_id, analysis_id)
    if row is None:
        return False
    session.delete(row)
    session.commit()
    return True


def set_coaching(
    session: Session, user_id: uuid.UUID, analysis_id: uuid.UUID, *,
    speaker_context: str | None, coaching_json: dict | None, coaching_warnings: list | None,
) -> Analysis | None:
    row = get_analysis(session, user_id, analysis_id)
    if row is None:
        return None
    row.speaker_context = speaker_context
    row.coaching_json = coaching_json
    row.coaching_warnings = coaching_warnings
    session.commit()
    return row


def create_job(session: Session, user_id: uuid.UUID, stage: str = "queued") -> Job:
    job = Job(user_id=user_id, status="queued", stage=stage, progress_pct=0)
    session.add(job)
    session.commit()
    return job


def update_job(session: Session, job_id: uuid.UUID, **fields) -> Job | None:
    unknown = set(fields) - JOB_UPDATABLE
    if unknown:
        raise ValueError(f"unknown job fields: {sorted(unknown)}")
    if "status" in fields and fields["status"] not in JOB_STATUSES:
        raise ValueError(f"invalid job status {fields['status']!r}; expected one of {JOB_STATUSES}")
    job = session.get(Job, job_id)
    if job is None:
        return None
    for k, v in fields.items():
        setattr(job, k, v)
    session.commit()
    return job


def get_job(session: Session, user_id: uuid.UUID, job_id: uuid.UUID) -> Job | None:
    return session.scalar(select(Job).where(Job.user_id == user_id, Job.id == job_id))


def fail_stale_jobs(session: Session, message: str = "server restarted") -> int:
    result = session.execute(
        update(Job).where(Job.status.in_(STALE_STATUSES)).values(status="failed", error=message)
    )
    session.commit()
    return int(result.rowcount or 0)
```

`update_job` is deliberately not user-scoped: the job runner (Plan 4) owns job state and has no user in hand; reads (`get_job`) are scoped. Note that in the module docstring.

- [ ] **Step 4: Run test**

Run: `pytest tests/test_repo.py -v -W error`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add backend/vocal_coach/storage/repo.py backend/tests/test_repo.py
git commit -m "feat(storage): user-scoped repository for users, analyses and jobs

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Comparison engine

**Files:**
- Create: `backend/vocal_coach/storage/comparison.py`
- Create: `backend/tests/test_comparison.py`

**Interfaces:**
- Consumes: `ComparisonConfig`, `Direction`.
- Produces: `class ComparableAnalysis(BaseModel)`: `id: str`, `recorded_at: datetime`, `config_hash: str`, `metrics: dict`, `transcript: dict | None`; `from_row(row: Analysis) -> ComparableAnalysis` (helper for Plan 4); `Verdict = Literal["improved", "worsened", "neutral", "unchanged", "unavailable"]`; `class ComparisonRow(BaseModel)`: `path: str`, `direction: Direction`, `values: list[float | None]`, `step_deltas: list[float | None]`, `delta: float | None`, `arrow: str` (one of `↑ ↓ → —`), `verdict: Verdict`; `class TrendPoint(BaseModel)`: `analysis_id: str`, `recorded_at: datetime`, `value: float | None`; `class ComparisonResult(BaseModel)`: `analysis_ids: list[str]`, `recorded_at: list[datetime]`, `config_mismatch: bool`, `rows: list[ComparisonRow]`, `trend: dict[str, list[TrendPoint]]`; `resolve_path(analysis: ComparableAnalysis, path: str) -> float | None`; `compare(analyses: list[ComparableAnalysis], cfg: ComparisonConfig) -> ComparisonResult` (raises `ValueError` for fewer than 2 analyses; sorts by `recorded_at` ascending).

Rules: `delta = last − first` (None if either None); `step_deltas[i] = values[i+1] − values[i]` (None if either None); `unchanged` if `first == 0 and delta == 0` or `first != 0 and |delta| < pct/100 · |first|`; else `up_good`: `improved` if delta > 0 else `worsened`; `down_good`: `improved` if delta < 0 else `worsened`; `neutral`: `neutral`. Arrow: `↑` if delta > 0, `↓` if delta < 0, `→` if delta == 0 or unchanged, `—` if unavailable. Only `int`/`float` (not `bool`) leaf values count; anything else is `None`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_comparison.py`:

```python
from datetime import datetime, timedelta, timezone

import pytest

from vocal_coach.config import ComparisonConfig
from vocal_coach.storage.comparison import ComparableAnalysis, ComparisonResult, compare, resolve_path

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
CFG = ComparisonConfig(min_meaningful_change_pct=5, directions={
    "pitch.f0_range_st": "up_good",
    "phrasing.long_pause_count_ge_1s": "down_good",
    "phrasing.pauses_per_min": "neutral",
    "transcript.derived.fillers_per_min": "down_good",
    "articulation.vowel_space.vowel_space_area_hz2": "up_good",
})


def _a(i, metrics, transcript=None, cfg="sha256:c1", day=0):
    return ComparableAnalysis(id=f"a{i}", recorded_at=T0 + timedelta(days=day), config_hash=cfg,
                              metrics=metrics, transcript=transcript)


def _m(f0_range=10.0, long_pauses=4, ppm=12.0, area=900000.0):
    return {"pitch": {"f0_range_st": f0_range}, "phrasing": {"long_pause_count_ge_1s": long_pauses, "pauses_per_min": ppm},
            "articulation": {"vowel_space": {"vowel_space_area_hz2": area}}}


def _t(fpm=3.0):
    return {"derived": {"fillers_per_min": fpm, "clarity": {}}}


def test_resolve_path_metrics_and_transcript():
    a = _a(1, _m(), _t(2.5))
    assert resolve_path(a, "pitch.f0_range_st") == 10.0
    assert resolve_path(a, "transcript.derived.fillers_per_min") == 2.5
    assert resolve_path(a, "pitch.nope") is None
    assert resolve_path(_a(2, _m(), None), "transcript.derived.fillers_per_min") is None
    assert resolve_path(_a(3, {"pitch": {"f0_range_st": True}}), "pitch.f0_range_st") is None  # bool is not a metric


def test_verdicts_and_arrows():
    r = compare([_a(1, _m(10.0, 4, 12.0), _t(3.0)), _a(2, _m(12.0, 2, 12.3), _t(3.0), day=1)], CFG)
    assert isinstance(r, ComparisonResult)
    rows = {row.path: row for row in r.rows}
    assert rows["pitch.f0_range_st"].verdict == "improved" and rows["pitch.f0_range_st"].arrow == "↑"
    assert rows["pitch.f0_range_st"].delta == 2.0 and rows["pitch.f0_range_st"].step_deltas == [2.0]
    assert rows["phrasing.long_pause_count_ge_1s"].verdict == "improved" and rows["phrasing.long_pause_count_ge_1s"].arrow == "↓"
    assert rows["phrasing.pauses_per_min"].verdict == "unchanged"  # 2.5 % < 5 %
    assert rows["phrasing.pauses_per_min"].arrow == "→"
    assert rows["transcript.derived.fillers_per_min"].verdict == "unchanged" and rows["transcript.derived.fillers_per_min"].delta == 0.0


def test_neutral_direction_with_meaningful_change():
    r = compare([_a(1, _m(ppm=10.0)), _a(2, _m(ppm=20.0), day=1)], CFG)
    row = next(x for x in r.rows if x.path == "phrasing.pauses_per_min")
    assert row.verdict == "neutral" and row.arrow == "↑"


def test_worsened_down_good():
    r = compare([_a(1, _m(long_pauses=2)), _a(2, _m(long_pauses=5), day=1)], CFG)
    row = next(x for x in r.rows if x.path == "phrasing.long_pause_count_ge_1s")
    assert row.verdict == "worsened" and row.arrow == "↑"


def test_zero_baseline_does_not_divide_by_zero():
    same = compare([_a(1, _m(long_pauses=0)), _a(2, _m(long_pauses=0), day=1)], CFG)
    assert next(x for x in same.rows if x.path == "phrasing.long_pause_count_ge_1s").verdict == "unchanged"
    worse = compare([_a(1, _m(long_pauses=0)), _a(2, _m(long_pauses=1), day=1)], CFG)
    assert next(x for x in worse.rows if x.path == "phrasing.long_pause_count_ge_1s").verdict == "worsened"


def test_missing_metric_is_unavailable_not_error():
    r = compare([_a(1, _m(), None), _a(2, _m(), _t(2.0), day=1)], CFG)
    row = next(x for x in r.rows if x.path == "transcript.derived.fillers_per_min")
    assert row.values == [None, 2.0] and row.delta is None and row.step_deltas == [None]
    assert row.verdict == "unavailable" and row.arrow == "—"
    assert next(x for x in r.rows if x.path == "pitch.f0_range_st").verdict == "unchanged"


def test_sorted_by_recorded_at_and_config_mismatch_flag():
    later = _a(1, _m(10.0), day=5)
    earlier = _a(2, _m(8.0), day=0, cfg="sha256:other")
    r = compare([later, earlier], CFG)
    assert r.analysis_ids == ["a2", "a1"]
    assert r.config_mismatch is True
    assert next(x for x in r.rows if x.path == "pitch.f0_range_st").delta == 2.0
    assert compare([_a(1, _m()), _a(2, _m(), day=1)], CFG).config_mismatch is False


def test_three_recordings_steps_and_trend():
    r = compare([_a(1, _m(10.0)), _a(2, _m(11.0), day=1), _a(3, _m(9.0), day=2)], CFG)
    row = next(x for x in r.rows if x.path == "pitch.f0_range_st")
    assert row.values == [10.0, 11.0, 9.0] and row.step_deltas == [1.0, -2.0] and row.delta == -1.0
    assert row.verdict == "worsened"
    assert [p.value for p in r.trend["pitch.f0_range_st"]] == [10.0, 11.0, 9.0]
    assert [p.analysis_id for p in r.trend["pitch.f0_range_st"]] == ["a1", "a2", "a3"]
    assert set(r.trend) == set(CFG.directions)


def test_requires_two_analyses():
    with pytest.raises(ValueError):
        compare([_a(1, _m())], CFG)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_comparison.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'vocal_coach.storage.comparison'`

- [ ] **Step 3: Implement comparison.py**

```python
"""Direction-aware comparison across a user's analyses (spec §9). Pure; no database access."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from vocal_coach.config import ComparisonConfig, Direction

Verdict = Literal["improved", "worsened", "neutral", "unchanged", "unavailable"]
TRANSCRIPT_PREFIX = "transcript."  # paths under this prefix resolve into transcript_json
ARROW_UP, ARROW_DOWN, ARROW_FLAT, ARROW_NA = "↑", "↓", "→", "—"
PERCENT = 100.0


class ComparableAnalysis(BaseModel):
    id: str
    recorded_at: datetime
    config_hash: str
    metrics: dict
    transcript: dict | None


def from_row(row: Any) -> ComparableAnalysis:
    """Adapter from a storage.models.Analysis row (kept loose to avoid importing the ORM here)."""
    return ComparableAnalysis(id=str(row.id), recorded_at=row.recorded_at, config_hash=row.config_hash,
                              metrics=row.metrics_json, transcript=row.transcript_json)


class ComparisonRow(BaseModel):
    path: str
    direction: Direction
    values: list[float | None]
    step_deltas: list[float | None]
    delta: float | None
    arrow: str
    verdict: Verdict


class TrendPoint(BaseModel):
    analysis_id: str
    recorded_at: datetime
    value: float | None


class ComparisonResult(BaseModel):
    analysis_ids: list[str]
    recorded_at: list[datetime]
    config_mismatch: bool
    rows: list[ComparisonRow]
    trend: dict[str, list[TrendPoint]]


def _numeric(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def resolve_path(analysis: ComparableAnalysis, path: str) -> float | None:
    if path.startswith(TRANSCRIPT_PREFIX):
        node: Any = analysis.transcript
        parts = path[len(TRANSCRIPT_PREFIX):].split(".")
    else:
        node = analysis.metrics
        parts = path.split(".")
    for part in parts:
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return _numeric(node)


def _sub(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else float(a - b)


def _verdict(first: float | None, delta: float | None, direction: Direction, pct: float) -> tuple[Verdict, str]:
    if first is None or delta is None:
        return "unavailable", ARROW_NA
    unchanged = (delta == 0) if first == 0 else (abs(delta) < (pct / PERCENT) * abs(first))
    arrow = ARROW_FLAT if (unchanged or delta == 0) else (ARROW_UP if delta > 0 else ARROW_DOWN)
    if unchanged:
        return "unchanged", arrow
    if direction == "neutral":
        return "neutral", arrow
    improved = delta > 0 if direction == "up_good" else delta < 0
    return ("improved" if improved else "worsened"), arrow


def compare(analyses: list[ComparableAnalysis], cfg: ComparisonConfig) -> ComparisonResult:
    if len(analyses) < 2:
        raise ValueError("comparison needs at least two analyses")
    ordered = sorted(analyses, key=lambda a: a.recorded_at)
    rows: list[ComparisonRow] = []
    trend: dict[str, list[TrendPoint]] = {}
    for path, direction in cfg.directions.items():
        values = [resolve_path(a, path) for a in ordered]
        steps = [_sub(values[i + 1], values[i]) for i in range(len(values) - 1)]
        delta = _sub(values[-1], values[0])
        verdict, arrow = _verdict(values[0], delta, direction, cfg.min_meaningful_change_pct)
        rows.append(ComparisonRow(path=path, direction=direction, values=values, step_deltas=steps,
                                  delta=delta, arrow=arrow, verdict=verdict))
        trend[path] = [TrendPoint(analysis_id=a.id, recorded_at=a.recorded_at, value=v) for a, v in zip(ordered, values)]
    return ComparisonResult(
        analysis_ids=[a.id for a in ordered],
        recorded_at=[a.recorded_at for a in ordered],
        config_mismatch=len({a.config_hash for a in ordered}) > 1,
        rows=rows,
        trend=trend,
    )
```

- [ ] **Step 4: Run test**

Run: `pytest tests/test_comparison.py -v -W error`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add backend/vocal_coach/storage/comparison.py backend/tests/test_comparison.py
git commit -m "feat(storage): direction-aware comparison and trend series

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: Round-trip from real reports, README

**Files:**
- Create: `backend/tests/test_storage_roundtrip.py`
- Modify: `backend/README.md` (append "Storage (Plan 3)" section)

**Interfaces:** none new. Verifies that a real `MetricsReport` and `Transcript` survive the JSON column and feed `compare` unchanged.

- [ ] **Step 1: Write the test**

`backend/tests/test_storage_roundtrip.py`:

```python
import json
from datetime import timedelta

import pytest

from tests import synth
from tests.fake_whisper import FakeWhisper, seg, word
from vocal_coach.analysis.analyser import analyse_wav
from vocal_coach.analysis.schema import SourceInfo
from vocal_coach.analysis.serialise import to_canonical_json
from vocal_coach.config import config_hash
from vocal_coach.storage import repo
from vocal_coach.storage.comparison import compare, from_row
from vocal_coach.storage.db import create_all, make_engine, make_session_factory
from vocal_coach.storage.models import utcnow
from vocal_coach.transcription.run import transcribe_file


@pytest.fixture
def session():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    with make_session_factory(engine)() as s:
        yield s


def _speech(tmp_path, name, f0):
    a = synth.am(synth.vowel(500, 1500, f0, 3.0), 4.0)
    x = synth.with_noise_floor(synth.concat(a, synth.silence(0.6), a))
    return synth.write_wav(tmp_path / name, x)


def _fake():
    return FakeWhisper([seg(0.0, 3.0, " So basically yes.", [word(0.0, 0.3, " So", 0.9), word(0.3, 0.8, " basically", 0.9), word(0.8, 1.2, " yes.", 0.9)])])


def test_metrics_and_transcript_round_trip_and_compare(cfg, session, tmp_path):
    user = repo.upsert_user(session, "sub", None, None)
    rows = []
    for i, f0 in enumerate((110, 140)):
        wav = _speech(tmp_path, f"r{i}.wav", f0)
        src = SourceInfo(file_name=wav.name, drive_file_id=None, drive_modified_time=None, content_sha256=str(i) * 64,
                         duration_s=6.6, original_channels=1, original_sample_rate=16000)
        report = analyse_wav(wav, cfg, src)
        transcript = transcribe_file(wav, cfg, model=_fake())
        rows.append(repo.create_analysis(
            session, user.id, file_name=wav.name, drive_file_id=None, content_sha256=str(i) * 64,
            recorded_at=utcnow() + timedelta(days=i), analyser_version=report.analyser_version,
            config_hash=report.config_hash, metrics_json=json.loads(to_canonical_json(report)),
            transcript_json=json.loads(to_canonical_json(transcript)),
        ))
    loaded = [repo.get_analysis(session, user.id, r.id) for r in rows]
    assert loaded[0].config_hash == config_hash(cfg)
    assert loaded[0].metrics_json["pitch"]["f0_median_hz"] is not None
    assert loaded[1].transcript_json["derived"]["filler_total"] == 2

    result = compare([from_row(r) for r in loaded], cfg.comparison)
    assert result.config_mismatch is False
    verdicts = {r.path: r.verdict for r in result.rows}
    assert verdicts["transcript.derived.fillers_per_min"] == "unchanged"
    assert all(v != "unavailable" for p, v in verdicts.items() if p.startswith("pitch."))
    # Every configured path resolves to a number or None without raising.
    assert set(result.trend) == set(cfg.comparison.directions)
```

- [ ] **Step 2: Run it**

Run: `pytest tests/test_storage_roundtrip.py -v -W error`
Expected: 1 passed. If a `pitch.` row is `unavailable`, print `result.rows` and check whether the fixture produced voiced frames; use `f0` values 110/140 as given.

- [ ] **Step 3: README**

Append to `backend/README.md`:

````markdown
## Storage (Plan 3)

Postgres via SQLAlchemy 2 + Alembic. Tables: `users`, `drive_connections`, `analyses` (unique on user + file hash + config hash), `jobs`. Every repository read is scoped by `user_id`; other users' rows read as missing.

```bash
export DATABASE_URL=postgresql+psycopg://vocal:vocal@localhost:5432/vocal_coach
alembic upgrade head          # or: python -c "from vocal_coach.storage.migrate import upgrade_to_head as u; import os; u(os.environ['DATABASE_URL'])"
```

Tests run the models on in-memory SQLite. `tests/test_migrations.py::test_upgrade_head_on_real_postgres` runs the migration against a throwaway Postgres container and is skipped when Docker is not installed.

Comparison (`vocal_coach/storage/comparison.py`) follows `config.yaml → comparison`: per metric path, `delta = last − first`, step deltas, arrow `↑ ↓ →`, verdict `improved / worsened / neutral / unchanged / unavailable`. `unchanged` means the change is below `min_meaningful_change_pct` of the first value. A metric missing in any recording yields `unavailable`, never an error. Analyses with different `config_hash` are still compared, with `config_mismatch: true`.
````

- [ ] **Step 4: Full suite and commit**

Run: `pytest -v -W error` → all green (the Postgres test skips without Docker).

```bash
git add backend/tests/test_storage_roundtrip.py backend/README.md
git commit -m "test(storage): real report round-trip through the database and comparison; README

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Self-review notes

- **Spec coverage:** §8 tables/constraints → Tasks 2–3; dedupe lookup → Task 4 (`find_analysis`); §9 comparison rules, `config_mismatch`, trend → Task 5; §16 `test_repo`, `test_comparison` present; `DATABASE_URL` settings → Task 1. Plan 4 will consume `repo.*`, `from_row`, `compare`, `upgrade_to_head`, `make_engine`, `make_session_factory`.
- **Deliberate choices:** SQLite in-memory for unit tests (portable types), one Docker-gated Postgres migration test — spec §16 allows "testcontainers (or `DATABASE_URL` override)". `update_job` is not user-scoped (the runner owns job state); documented. Added `unavailable` verdict and `—` arrow for missing values (spec silent; Review Focus 1). `step_deltas` added alongside spec's singular `delta` to carry the "between consecutive recordings" requirement.
- **Type consistency:** `ComparisonConfig`/`Direction` (Task 1) → Task 5; `Analysis`/`Job`/`User`/`JOB_STATUSES`/`utcnow` (Task 2) → Tasks 4, 6; `make_engine`/`create_all`/`make_session_factory` (Task 2) → Tasks 3, 4, 6; `upgrade_to_head` (Task 3) → README; `from_row`/`compare` (Task 5) → Task 6.
- **Review Focus pins:** 1 → `test_missing_metric_is_unavailable_not_error` (T5); 2 → `test_zero_baseline_does_not_divide_by_zero` (T5); 3 → `test_cross_user_get_returns_none`, `test_job_lifecycle_and_scoping` (T4); 4 → `test_unique_user_sha_config_enforced_by_schema` (T2), `test_find_then_create_dedupes_same_file_same_config` (T4); 5 → `test_sorted_by_recorded_at_and_config_mismatch_flag` (T5).
- **Known plan-text wrinkle fixed inline:** Task 3 `upgrade_to_head` must make the programmatic URL win over `DATABASE_URL`; the chosen mechanism is setting both the ini option and a temporary `DATABASE_URL` env inside try/finally.

"""Engine and session factory. Schema is owned by Alembic; create_all is for tests."""
from __future__ import annotations

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from vocal_coach.storage.models import Base


def make_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        # check_same_thread=False is needed because the StaticPool-backed :memory: fixture
        # hands the same connection across threads in tests; harmless for file-based SQLite.
        kwargs = {"connect_args": {"check_same_thread": False}}
        if ":memory:" in url:
            kwargs["poolclass"] = StaticPool
        engine = create_engine(url, **kwargs)

        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _record):  # SQLite ignores FKs unless asked
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

        return engine
    return create_engine(url, pool_pre_ping=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def create_all(engine: Engine) -> None:
    Base.metadata.create_all(engine)

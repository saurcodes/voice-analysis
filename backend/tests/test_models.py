import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError, StatementError

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
    original_recorded_at = a.recorded_at
    session.add(a)
    session.commit()
    session.expire_all()
    loaded = session.get(Analysis, a.id)
    assert isinstance(loaded.id, uuid.UUID)
    assert loaded.metrics_json["pitch"]["f0_median_hz"] == 120.0
    assert loaded.transcript_json is None
    assert loaded.recorded_at.tzinfo is not None
    assert loaded.recorded_at == original_recorded_at


def test_naive_datetime_rejected(session):
    u = _user(session)
    a = _analysis(u)
    a.recorded_at = datetime(2026, 1, 1)
    session.add(a)
    with pytest.raises((ValueError, StatementError)):
        session.commit()
    session.rollback()


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
    session.expire_all()
    assert isinstance(j.created_at, datetime)
    assert j.created_at.tzinfo is not None

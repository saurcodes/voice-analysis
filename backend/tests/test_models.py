import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import inspect, select, text
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
                    "coaching_json", "coaching_warnings", "source_sha256"}
    assert {c["name"] for c in insp.get_columns("jobs")} == {"id", "user_id", "status", "stage", "progress_pct",
                                                              "error", "analysis_id", "created_at", "updated_at",
                                                              "file_name", "source_sha256", "recorded_at"}
    uniques = [u["column_names"] for u in insp.get_unique_constraints("analyses")]
    assert ["user_id", "content_sha256", "config_hash", "analyser_version"] in uniques
    indexes = {i["name"]: i["column_names"] for i in insp.get_indexes("analyses")}
    assert indexes.get("ix_analyses_user_recorded") == ["user_id", "recorded_at"]


def _user(session, sub="sub-1"):
    u = User(keycloak_sub=sub, email=f"{sub}@x.test", username=sub)
    session.add(u)
    session.commit()
    return u


def _analysis(user, sha="a" * 64, cfg="sha256:c1", version="0.1.0"):
    return Analysis(user_id=user.id, file_name="a.m4a", drive_file_id=None, content_sha256=sha,
                    recorded_at=utcnow(), analysed_at=utcnow(), analyser_version=version, config_hash=cfg,
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


def test_unique_user_sha_config_version_enforced_by_schema(session):
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
    # same sha and config, different analyser version → allowed (new numbers, old row kept)
    session.add(_analysis(u, version="0.2.0"))
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


def test_none_json_is_sql_null_not_json_null(session):
    from vocal_coach.storage import repo
    u = _user(session)
    a = _analysis(u)
    a.coaching_json = {"k": 1}
    session.add(a)
    session.commit()
    assert session.execute(text("select count(*) from analyses where transcript_json is null")).scalar() == 1
    repo.set_coaching(session, u.id, a.id, speaker_context=None, coaching_json=None, coaching_warnings=None)
    assert session.execute(text("select count(*) from analyses where coaching_json is null")).scalar() == 1
    assert session.execute(text("select count(*) from analyses where coaching_warnings is null")).scalar() == 1


def test_user_delete_cascades_and_analysis_delete_sets_job_null(session):
    u = _user(session)
    a = _analysis(u)
    session.add(a)
    session.commit()
    j = Job(user_id=u.id, status="done", stage="done", progress_pct=100, analysis_id=a.id)
    session.add(j)
    session.commit()
    session.execute(text("delete from analyses where id = :i"), {"i": a.id.hex})
    session.commit()
    session.expire_all()
    assert session.get(Job, j.id).analysis_id is None
    session.add(_analysis(u))
    session.commit()
    session.execute(text("delete from users where id = :i"), {"i": u.id.hex})
    session.commit()
    session.expire_all()
    assert session.scalars(select(Analysis)).all() == []
    assert session.scalars(select(Job)).all() == []


def test_nan_in_json_rejected_on_sqlite(session):
    u = _user(session)
    a = _analysis(u)
    a.metrics_json = {"x": float("nan")}
    session.add(a)
    with pytest.raises((ValueError, StatementError)):
        session.commit()
    session.rollback()

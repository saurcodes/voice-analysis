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
    assert repo.find_analysis(session, u.id, "a" * 64, "sha256:c1", "0.1.0") is None
    a = _mk(session, u)
    assert repo.find_analysis(session, u.id, "a" * 64, "sha256:c1", "0.1.0").id == a.id
    assert repo.find_analysis(session, u.id, "a" * 64, "sha256:c2", "0.1.0") is None
    assert repo.find_analysis(session, u.id, "a" * 64, "sha256:c1", "0.2.0") is None
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


def test_list_tie_break_is_deterministic(session):
    u = repo.upsert_user(session, "a", None, None)
    when = utcnow()
    a1 = _mk(session, u, sha="1" * 64, when=when)
    a2 = _mk(session, u, sha="2" * 64, when=when)
    ids1 = [x.id for x in repo.list_analyses(session, u.id)]
    ids2 = [x.id for x in repo.list_analyses(session, u.id)]
    assert ids1 == ids2
    assert ids1 == sorted([a1.id, a2.id], reverse=True)

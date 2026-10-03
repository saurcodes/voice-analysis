import re
import uuid

import pytest
from sqlalchemy import select
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
    assert _mk(session, u).id == a.id  # duplicate create returns the existing row (dedupe race safe)


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


@pytest.fixture
def factory(tmp_path):
    """File-backed SQLite so two sessions use two real connections."""
    engine = make_engine(f"sqlite+pysqlite:///{tmp_path / 'repo.db'}")
    create_all(engine)
    yield make_session_factory(engine)
    engine.dispose()


def test_duplicate_create_analysis_returns_existing_and_session_stays_usable(session):
    u = repo.upsert_user(session, "sub-1", None, None)
    first = _mk(session, u)
    second = _mk(session, u)
    assert second.id == first.id
    assert len(repo.list_analyses(session, u.id)) == 1
    job = repo.create_job(session, u.id)  # session is still usable after the swallowed IntegrityError
    assert job.stage == "download"


def test_create_analysis_race_with_other_session_returns_existing(factory):
    with factory() as s1, factory() as s2:
        u = repo.upsert_user(s1, "sub-1", None, None)
        other = _mk(s2, u)  # the other tab won the race
        mine = _mk(s1, u)
        assert mine.id == other.id
        assert repo.create_job(s1, u.id).user_id == u.id


def test_create_analysis_reraises_unrelated_integrity_error(session):
    ghost = type("Ghost", (), {"id": uuid.uuid4()})()  # no such user: FK violation, nothing to dedupe to
    with pytest.raises(IntegrityError):
        _mk(session, ghost)
    assert repo.upsert_user(session, "after", None, None).keycloak_sub == "after"


def test_upsert_user_race_returns_existing_row(factory, monkeypatch):
    from vocal_coach.storage.models import User
    with factory() as s1:
        real_scalar = s1.scalar
        raced = []

        def racing_scalar(stmt, *args, **kwargs):
            if not raced:  # first lookup misses; meanwhile another request inserts the same sub
                raced.append(True)
                with factory() as s2:
                    s2.add(User(keycloak_sub="sub-r", email="old@x.test", username="old"))
                    s2.commit()
                return None
            return real_scalar(stmt, *args, **kwargs)

        monkeypatch.setattr(s1, "scalar", racing_scalar)
        user = repo.upsert_user(s1, "sub-r", "new@x.test", "new")
        monkeypatch.undo()
        assert raced == [True]
        assert (user.email, user.username) == ("new@x.test", "new")
    with factory() as s3:
        rows = s3.scalars(select(User).where(User.keycloak_sub == "sub-r")).all()
        assert len(rows) == 1 and rows[0].id == user.id and rows[0].email == "new@x.test"


def test_get_job_sees_updates_from_another_session(factory):
    with factory() as a, factory() as b:
        u = repo.upsert_user(a, "sub-1", None, None)
        job = repo.create_job(a, u.id)
        assert repo.get_job(a, u.id, job.id).status == "queued"
        repo.update_job(b, job.id, status="running", progress_pct=40)
        polled = repo.get_job(a, u.id, job.id)
        assert (polled.status, polled.progress_pct) == ("running", 40)


def test_update_job_rejects_out_of_range_progress(session):
    u = repo.upsert_user(session, "a", None, None)
    j = repo.create_job(session, u.id)
    with pytest.raises(ValueError):
        repo.update_job(session, j.id, progress_pct=101)
    with pytest.raises(ValueError):
        repo.update_job(session, j.id, progress_pct=-1)
    assert repo.update_job(session, j.id, progress_pct=100).progress_pct == 100


def test_terminal_job_status_is_final(session):
    u = repo.upsert_user(session, "a", None, None)
    done = repo.update_job(session, repo.create_job(session, u.id).id, status="done")
    failed = repo.update_job(session, repo.create_job(session, u.id).id, status="failed")
    with pytest.raises(ValueError, match="terminal"):
        repo.update_job(session, done.id, status="running")
    with pytest.raises(ValueError, match="terminal"):
        repo.update_job(session, failed.id, status="done")
    assert repo.get_job(session, u.id, done.id).status == "done"


def test_writer_failure_rolls_back_session(session, monkeypatch):
    u = repo.upsert_user(session, "a", None, None)
    j = repo.create_job(session, u.id)

    def boom():
        raise RuntimeError("commit failed")

    monkeypatch.setattr(session, "commit", boom)
    with pytest.raises(RuntimeError):
        repo.update_job(session, j.id, stage="analyse")
    monkeypatch.undo()
    assert not session.dirty
    assert repo.get_job(session, u.id, j.id).stage == "download"


_FULL_METRICS = {
    "pitch": {"f0_median_hz": 118.5, "f0_range_st": 9.25},
    "intonation": {"flat_pct": 31.0},
    "phrasing": {"pauses_per_min": 12.5},
    "pace": {"articulation_rate_syl_per_sec": 4.75},
    "energy": {"trailing_off_count": 3},
}


def _mk_full(session, user, sha, when, metrics=None, transcript=None):
    return repo.create_analysis(
        session, user.id, file_name=f"{sha[0]}.m4a", drive_file_id="drv", content_sha256=sha, recorded_at=when,
        analyser_version="0.1.0", config_hash="sha256:c1", metrics_json=metrics or _FULL_METRICS,
        transcript_json=transcript,
    )


def test_analysis_summaries_project_key_metrics_and_flags(session):
    from datetime import timedelta
    u = repo.upsert_user(session, "a", None, None)
    t0 = utcnow()
    with_all = _mk_full(session, u, "1" * 64, t0, transcript={"derived": {"fillers_per_min": 2.5}})
    repo.set_coaching(session, u.id, with_all.id, speaker_context=None, coaching_json={"k": 1}, coaching_warnings=[])
    bare = _mk_full(session, u, "2" * 64, t0 - timedelta(days=1),
                    metrics={"pitch": {"f0_median_hz": None}, "energy": {}})
    summaries = repo.list_analysis_summaries(session, u.id)
    assert all(isinstance(x, repo.AnalysisSummary) for x in summaries)
    assert [x.id for x in summaries] == [with_all.id, bare.id]
    full, empty = summaries
    assert (full.f0_median_hz, full.f0_range_st, full.flat_pct, full.pauses_per_min,
            full.articulation_rate_syl_per_sec, full.trailing_off_count, full.fillers_per_min) == (
        118.5, 9.25, 31.0, 12.5, 4.75, 3, 2.5)
    assert full.has_transcript is True and full.has_coaching is True
    assert (full.file_name, full.drive_file_id, full.analyser_version, full.config_hash) == (
        "1.m4a", "drv", "0.1.0", "sha256:c1")
    assert full.recorded_at == with_all.recorded_at and full.recorded_at.tzinfo is not None
    assert full.analysed_at.tzinfo is not None
    assert empty.has_transcript is False and empty.has_coaching is False
    assert (empty.f0_median_hz, empty.f0_range_st, empty.trailing_off_count, empty.fillers_per_min) == (
        None, None, None, None)


def test_analysis_summaries_paginate_and_are_user_scoped(session):
    from datetime import timedelta
    u = repo.upsert_user(session, "a", None, None)
    other = repo.upsert_user(session, "b", None, None)
    t0 = utcnow()
    rows = [_mk_full(session, u, str(i) * 64, t0 - timedelta(days=i)) for i in range(5)]
    _mk_full(session, other, "f" * 64, t0 + timedelta(days=1))
    assert [x.id for x in repo.list_analysis_summaries(session, u.id)] == [r.id for r in rows]
    assert [x.id for x in repo.list_analysis_summaries(session, u.id, limit=2)] == [r.id for r in rows[:2]]
    assert [x.id for x in repo.list_analysis_summaries(session, u.id, limit=2, offset=2)] == [r.id for r in rows[2:4]]
    assert repo.list_analysis_summaries(session, u.id, limit=2, offset=10) == []


def test_analysis_summaries_do_not_load_blobs(session):
    from sqlalchemy import event
    u = repo.upsert_user(session, "a", None, None)
    _mk_full(session, u, "1" * 64, utcnow())
    statements = []
    engine = session.get_bind()
    listener = lambda conn, cursor, stmt, params, ctx, many: statements.append(stmt)  # noqa: E731
    event.listen(engine, "before_cursor_execute", listener)
    try:
        repo.list_analysis_summaries(session, u.id)
    finally:
        event.remove(engine, "before_cursor_execute", listener)
    assert len(statements) == 1
    select_list = statements[0].split(" FROM ")[0]
    # Blob columns may appear only inside a JSON path extraction or an IS NOT NULL flag, never bare.
    bare = re.findall(r"(?<!JSON_EXTRACT\()analyses\.(?:metrics|transcript|coaching)_json(?! IS NOT NULL)", select_list)
    assert bare == [], select_list


def test_get_analyses_is_scoped_deduped_and_ordered(session):
    from datetime import timedelta
    u = repo.upsert_user(session, "a", None, None)
    other = repo.upsert_user(session, "b", None, None)
    t0 = utcnow()
    late = _mk(session, u, sha="1" * 64, when=t0)
    early = _mk(session, u, sha="2" * 64, when=t0 - timedelta(days=1))
    foreign = _mk(session, other, sha="3" * 64, when=t0)
    got = repo.get_analyses(session, u.id, [late.id, early.id, late.id, foreign.id, uuid.uuid4()])
    assert [a.id for a in got] == [early.id, late.id]
    assert repo.get_analyses(session, u.id, []) == []

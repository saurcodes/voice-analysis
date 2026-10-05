import json
import os
import shutil
import threading
import uuid
from datetime import timedelta

import pytest

from tests import synth
from tests.fake_whisper import FakeWhisper, seg, word
from vocal_coach.analysis.analyser import analyse_wav
from vocal_coach.analysis.schema import SourceInfo
from vocal_coach.analysis.serialise import to_canonical_json
from vocal_coach.config import config_hash
from vocal_coach.storage import paths, repo
from vocal_coach.storage.comparison import compare, from_row
from vocal_coach.storage.db import create_all, make_engine, make_session_factory
from vocal_coach.storage.models import utcnow
from vocal_coach.transcription.run import transcribe_file

# Rancher Desktop's user-mode networking cannot start testcontainers' ryuk reaper; disable it by
# default, matching tests/test_migrations.py (setdefault keeps any value CI already exported).
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")
requires_docker = pytest.mark.skipif(shutil.which("docker") is None, reason="docker not installed")


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


@requires_docker
@pytest.mark.filterwarnings(
    "ignore:testcontainers.postgres is deprecated, use testcontainers.community.postgres instead:DeprecationWarning"
)
def test_delete_and_retry_race_never_leaves_a_job_pointing_at_a_missing_upload(tmp_path):
    """`repo.delete_analysis_and_count_refs` (storage/repo.py) locks the user's analyses rows
    sharing `source_sha256` before counting references, removing the upload (via `on_unreferenced`)
    before the commit that releases the lock, so the decision to remove the upload is made from a
    consistent, committed view of who still needs it (spec amendment 3, Plan 8 Task 3).

    This only runs against real Postgres (`with_for_update()` is a no-op on SQLite, which the rest
    of the suite uses); it is skipped when Docker is unavailable.

    A full close of the race against `POST /jobs/{id}/retry` also needs that endpoint to hold the
    same per-hash lock across its own find-upload-then-create-job sequence; this test's
    `_retry_with_lock` helper exercises the real `repo.lock_source_refs`, the same helper the retry
    route calls, so the two sides here are coordinated the way production actually is.
    """
    from testcontainers.postgres import PostgresContainer

    from vocal_coach.storage.migrate import upgrade_to_head

    with PostgresContainer("postgres:16-alpine", driver="psycopg") as pg:
        url = pg.get_connection_url()
        upgrade_to_head(url)
        engine = make_engine(url)
        try:
            factory = make_session_factory(engine)
            data_dir = tmp_path / "data"
            source_sha256 = "f" * 64

            def _seed() -> tuple[uuid.UUID, uuid.UUID]:
                """A fresh user with one analysis and its upload file, both referencing the same hash."""
                with factory() as s:
                    user = repo.upsert_user(s, f"race-{uuid.uuid4()}", None, None)
                    row = repo.create_analysis(
                        s, user.id, file_name="r.wav", drive_file_id=None, content_sha256=str(uuid.uuid4()),
                        source_sha256=source_sha256, recorded_at=utcnow(), analyser_version="0.1.0",
                        config_hash="sha256:test", metrics_json={},
                    )
                    user_id, analysis_id = user.id, row.id
                paths.uploads_dir(data_dir, user_id).mkdir(parents=True, exist_ok=True)
                paths.upload_path(data_dir, user_id, source_sha256, "wav").write_bytes(b"fake wav bytes")
                return user_id, analysis_id

            def _delete(user_id: uuid.UUID, analysis_id: uuid.UUID) -> int:
                with factory() as s:
                    _deleted, refs, _drive_refs = repo.delete_analysis_and_count_refs(
                        s, user_id, analysis_id, source_sha256,
                        on_unreferenced=lambda: paths.remove_upload(data_dir, user_id, source_sha256),
                    )
                return refs

            def _retry_with_lock(user_id: uuid.UUID) -> uuid.UUID | None:
                """Stands in for `POST /jobs/{id}/retry`'s own guard (it already checks
                `paths.find_upload` before creating the job): calls the real `repo.lock_source_refs`,
                the same helper the retry route calls, so the two sides serialise."""
                with factory() as s:
                    repo.lock_source_refs(s, user_id, source_sha256)
                    found = paths.find_upload(data_dir, user_id, source_sha256)
                    if found is None:
                        s.rollback()
                        return None
                    job = repo.create_job(s, user_id, file_name="r.wav", source_sha256=source_sha256,
                                          recorded_at=utcnow())
                    return job.id

            # Case 1: the retry's job is created (and its lock released) before the delete's own
            # lock+count runs. The delete must then see the reference and keep the upload.
            user_id, analysis_id = _seed()
            job_id = _retry_with_lock(user_id)
            assert job_id is not None
            refs = _delete(user_id, analysis_id)
            assert refs > 0
            assert paths.find_upload(data_dir, user_id, source_sha256) is not None
            with factory() as s:
                repo.update_job(s, job_id, status="done", progress_pct=100)  # terminal: tidy up

            # Case 2: the delete (lock, count, commit, and file removal) fully completes first. The
            # retry's lock then matches no rows (the analysis is gone) and its own file check
            # correctly reports no upload, so it must not create a job.
            user_id, analysis_id = _seed()
            refs = _delete(user_id, analysis_id)
            assert refs == 0
            assert paths.find_upload(data_dir, user_id, source_sha256) is None
            assert _retry_with_lock(user_id) is None

            # Case 3: real concurrent threads, started together via a barrier, repeated several
            # times. Both sides take the same `with_for_update()` lock, so whichever starts first
            # wins the race and the other observes a consistent, post-commit state; the forbidden
            # outcome (something still referencing the hash while its upload is gone) must never
            # occur regardless of which side the scheduler favours.
            for _ in range(10):
                user_id, analysis_id = _seed()
                barrier = threading.Barrier(2)
                outcome: dict = {}

                def _run_delete():
                    barrier.wait()
                    outcome["refs"] = _delete(user_id, analysis_id)

                def _run_retry():
                    barrier.wait()
                    outcome["job_id"] = _retry_with_lock(user_id)

                t1 = threading.Thread(target=_run_delete)
                t2 = threading.Thread(target=_run_retry)
                t1.start()
                t2.start()
                t1.join()
                t2.join()

                upload_present = paths.find_upload(data_dir, user_id, source_sha256) is not None
                with factory() as s:
                    still_referenced = repo.count_source_refs(s, user_id, source_sha256) > 0
                assert not (still_referenced and not upload_present), (
                    "a job or analysis still references the upload but it is gone from disk "
                    f"(job_id={outcome.get('job_id')}, refs_after_delete={outcome.get('refs')})"
                )
                if outcome.get("job_id") is not None:
                    with factory() as s:
                        repo.update_job(s, outcome["job_id"], status="done", progress_pct=100)
        finally:
            engine.dispose()

import uuid
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from tests.api_fixtures import make_test_app
from tests.test_api_analyses import (
    _capturing_job_fn, _connect_drive, _drive_overrides, _mock_get_file, _upload, _wav_bytes,
    failing_job_fn, fake_job_fn,
)
from tests.test_api_jobs_sse import running_job_fn
from vocal_coach.drive import oauth
from vocal_coach.storage import repo
from vocal_coach.storage.db import make_engine, make_session_factory


def _capturing_failing_job_fn(captured):
    """Like `_capturing_job_fn`, but the job lands `failed` (as a real Drive download failure would),
    so the row is already terminal and ready to retry without a separate `update_job` call."""
    def job_fn(req, database_url, config_path):
        captured.append(req)
        engine = make_engine(database_url)
        with make_session_factory(engine)() as s:
            repo.update_job(s, req.job_id, status="failed", error="could not download from Google Drive")
        engine.dispose()
    return job_fn


def _job(client, ctx, job_id, sub="user-1"):
    return client.get(f"/api/jobs/{job_id}", headers=ctx["auth"](sub)).json()


def test_list_jobs_newest_first_and_filtered_by_status(tmp_path):
    app, ctx = make_test_app(tmp_path, job_fn=fake_job_fn)
    with TestClient(app) as client:
        done_ids = [_upload(client, ctx["auth"](), name=f"d{i}.wav", data=_wav_bytes(1.0 + 0.1 * i)).json()["job_ids"][0]
                    for i in range(2)]
        app.state.runner._job_fn = failing_job_fn  # the next upload fails
        failed_id = _upload(client, ctx["auth"](), name="f.wav", data=_wav_bytes(1.5)).json()["job_ids"][0]

        everything = client.get("/api/jobs", headers=ctx["auth"]()).json()
        assert [j["id"] for j in everything] == [failed_id, *reversed(done_ids)]
        assert everything[0]["file_name"] == "f.wav" and everything[0]["created_at"]

        done = client.get("/api/jobs?status=done", headers=ctx["auth"]()).json()
        assert {j["id"] for j in done} == set(done_ids) and all(j["status"] == "done" for j in done)
        assert [j["id"] for j in client.get("/api/jobs?status=failed", headers=ctx["auth"]()).json()] == [failed_id]
        assert len(client.get("/api/jobs?limit=1", headers=ctx["auth"]()).json()) == 1
        assert client.get("/api/jobs?status=bogus", headers=ctx["auth"]()).status_code == 422
        assert client.get("/api/jobs", headers=ctx["auth"]("someone-else")).json() == []


def test_retry_failed_job_creates_new_job(tmp_path):
    app, ctx = make_test_app(tmp_path, job_fn=failing_job_fn)
    with TestClient(app) as client:
        job_id = _upload(client, ctx["auth"](), name="talk.wav", recorded_at="2026-09-01T10:00:00+00:00").json()["job_ids"][0]
        assert _job(client, ctx, job_id)["status"] == "failed"
        app.state.runner._job_fn = fake_job_fn  # the cause is gone; the retry succeeds
        r = client.post(f"/api/jobs/{job_id}/retry", headers=ctx["auth"]())
        assert r.status_code == 202
        new_id = r.json()["job_id"]
        assert new_id != job_id
        new = _job(client, ctx, new_id)
        assert new["status"] == "done" and new["file_name"] == "talk.wav"
        detail = client.get(f"/api/analyses/{new['analysis_id']}", headers=ctx["auth"]()).json()
        assert detail["recorded_at"].startswith("2026-09-01T10:00:00")  # recorded_at carried over
        assert _job(client, ctx, job_id)["status"] == "failed"  # the original is untouched


def test_retry_rejects_running_foreign_and_missing_upload(tmp_path):
    app, ctx = make_test_app(tmp_path, job_fn=running_job_fn)
    with TestClient(app) as client:
        running_id = _upload(client, ctx["auth"]()).json()["job_ids"][0]
        assert client.post(f"/api/jobs/{running_id}/retry", headers=ctx["auth"]()).status_code == 409
        assert client.post(f"/api/jobs/{running_id}/retry", headers=ctx["auth"]("bob")).status_code == 404
        assert client.post(f"/api/jobs/{uuid.uuid4()}/retry", headers=ctx["auth"]()).status_code == 404

        with ctx["session_factory"]() as s:
            repo.update_job(s, uuid.UUID(running_id), status="failed", error="server restarted")
        for f in (tmp_path / "data" / "uploads").rglob("*.wav"):
            f.unlink()
        r = client.post(f"/api/jobs/{running_id}/retry", headers=ctx["auth"]())
        assert r.status_code == 410


def test_retry_of_a_legacy_drive_job_with_no_file_id_is_410(tmp_path):
    """A job with neither source_sha256 nor drive_file_id (pre-Plan-8 Drive job) has nothing to retry from."""
    app, ctx = make_test_app(tmp_path, job_fn=fake_job_fn)
    with TestClient(app) as client:
        with ctx["session_factory"]() as s:
            user = repo.upsert_user(s, "user-1", None, None)
            job = repo.create_job(s, user.id, file_name="take.wav", source_sha256=None)
            repo.update_job(s, job.id, status="failed", error="could not download from Google Drive")
        r = client.post(f"/api/jobs/{job.id}/retry", headers=ctx["auth"]())
        assert r.status_code == 410
        assert r.json()["detail"] == "the Drive file is no longer available; analyse it again from the Drive tab"


def _drive_app(tmp_path, captured):
    return make_test_app(tmp_path, job_fn=_capturing_failing_job_fn(captured), settings_overrides=_drive_overrides())


def _create_one_drive_job(client, ctx, *, httpx_mock, file_id="f1", name="one.wav",
                          modified_time="2026-10-01T00:00:00.000Z"):
    """Creates a Drive job that immediately fails (the fake job_fn marks it `failed`), ready to retry."""
    _connect_drive(ctx)
    httpx_mock.add_response(url=oauth.TOKEN_URL, json={"access_token": "listing-tok"})
    _mock_get_file(httpx_mock, file_id, name=name, modified_time=modified_time)
    r = client.post("/api/analyses", headers=ctx["auth"](), json={"source": "drive", "file_ids": [file_id]})
    assert r.status_code == 202
    job_id = r.json()["job_ids"][0]
    return job_id


def test_retry_of_a_drive_job_refreshes_metadata_and_keeps_the_old_job_failed(tmp_path, httpx_mock):
    captured = []
    app, ctx = _drive_app(tmp_path, captured)
    with TestClient(app) as client:
        job_id = _create_one_drive_job(client, ctx, httpx_mock=httpx_mock)
        old_path = captured[0].source_path

        app.state.runner._job_fn = _capturing_job_fn(captured)  # the cause is gone; the retry succeeds
        httpx_mock.add_response(url=oauth.TOKEN_URL, json={"access_token": "retry-tok"})
        _mock_get_file(httpx_mock, "f1", name="one.wav", modified_time="2026-10-05T00:00:00.000Z")

        r = client.post(f"/api/jobs/{job_id}/retry", headers=ctx["auth"]())
        assert r.status_code == 202
        new_id = r.json()["job_id"]
        assert new_id != job_id
        assert captured[-1].drive_modified_time == "2026-10-05T00:00:00.000Z"
        assert captured[-1].source_path != old_path  # the new modifiedTime names a new cache path

        with ctx["session_factory"]() as s:
            user = repo.upsert_user(s, "user-1", None, None)
            new_row = repo.get_job(s, user.id, uuid.UUID(new_id))
            assert new_row.drive_file_id == "f1"
            assert new_row.drive_modified_time == "2026-10-05T00:00:00.000Z"
            assert new_row.recorded_at == datetime(2026, 10, 5, tzinfo=timezone.utc)
        assert _job(client, ctx, new_id)["status"] == "done"
        assert _job(client, ctx, job_id)["status"] == "failed"  # the original is untouched


def test_retry_of_a_drive_job_404_from_google_is_410(tmp_path, httpx_mock):
    captured = []
    app, ctx = _drive_app(tmp_path, captured)
    with TestClient(app) as client:
        job_id = _create_one_drive_job(client, ctx, httpx_mock=httpx_mock)

        httpx_mock.add_response(url=oauth.TOKEN_URL, json={"access_token": "retry-tok"})
        _mock_get_file(httpx_mock, "f1", name="", modified_time="", status_code=404)

        r = client.post(f"/api/jobs/{job_id}/retry", headers=ctx["auth"]())
        assert r.status_code == 410
        assert r.json()["detail"] == "the Drive file is no longer available; analyse it again from the Drive tab"
        assert _job(client, ctx, job_id)["status"] == "failed"


def test_retry_of_a_drive_job_when_disconnected_is_409(tmp_path, httpx_mock):
    captured = []
    app, ctx = _drive_app(tmp_path, captured)
    with TestClient(app) as client:
        job_id = _create_one_drive_job(client, ctx, httpx_mock=httpx_mock)
        with ctx["session_factory"]() as s:
            user = repo.upsert_user(s, "user-1", None, None)
            repo.delete_drive_connection(s, user.id)

        r = client.post(f"/api/jobs/{job_id}/retry", headers=ctx["auth"]())
        assert r.status_code == 409
        assert r.json()["detail"] == "drive_not_connected"


def _job_fixture(client, ctx, name="clip.wav"):
    return _upload(client, ctx["auth"](), name=name).json()["job_ids"][0]


def test_delete_job_dismisses_a_terminal_job_then_404s(tmp_path):
    app, ctx = make_test_app(tmp_path, job_fn=fake_job_fn)
    with TestClient(app) as client:
        job_id = _job_fixture(client, ctx)
        assert _job(client, ctx, job_id)["status"] == "done"
        assert client.delete(f"/api/jobs/{job_id}", headers=ctx["auth"]()).status_code == 204
        assert client.get(f"/api/jobs/{job_id}", headers=ctx["auth"]()).status_code == 404
        assert client.delete(f"/api/jobs/{job_id}", headers=ctx["auth"]()).status_code == 404


def test_delete_job_other_users_job_and_non_terminal_job_are_404(tmp_path):
    app, ctx = make_test_app(tmp_path, job_fn=running_job_fn)
    with TestClient(app) as client:
        running_id = _upload(client, ctx["auth"]()).json()["job_ids"][0]
        assert client.delete(f"/api/jobs/{running_id}", headers=ctx["auth"]("bob")).status_code == 404
        assert client.delete(f"/api/jobs/{running_id}", headers=ctx["auth"]()).status_code == 404
        with ctx["session_factory"]() as s:
            repo.update_job(s, uuid.UUID(running_id), status="failed", error="server restarted")
        assert client.delete(f"/api/jobs/{running_id}", headers=ctx["auth"]()).status_code == 204

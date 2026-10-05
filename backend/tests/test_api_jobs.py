import uuid

from fastapi.testclient import TestClient

from tests.api_fixtures import make_test_app
from tests.test_api_analyses import _upload, _wav_bytes, failing_job_fn, fake_job_fn
from tests.test_api_jobs_sse import running_job_fn
from vocal_coach.storage import repo


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


def test_retry_of_a_drive_sourced_job_is_410_with_drive_message(tmp_path):
    app, ctx = make_test_app(tmp_path, job_fn=fake_job_fn)
    with TestClient(app) as client:
        with ctx["session_factory"]() as s:
            user = repo.upsert_user(s, "user-1", None, None)
            job = repo.create_job(s, user.id, file_name="take.wav", source_sha256=None)
            repo.update_job(s, job.id, status="failed", error="could not download from Google Drive")
        r = client.post(f"/api/jobs/{job.id}/retry", headers=ctx["auth"]())
        assert r.status_code == 410
        assert r.json()["detail"] == "Drive-sourced jobs cannot be retried yet; analyse the file again from the Drive tab"

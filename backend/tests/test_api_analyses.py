import io
import json
import uuid
from datetime import datetime, timezone

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request as StarletteRequest

from tests import synth
from tests.api_fixtures import fake_metrics, fake_transcript, make_test_app
from tests.conftest import requires_ffmpeg
from vocal_coach.api.analyses import _download_filename, _reject_if_declared_too_large
from vocal_coach.drive import crypto, oauth
from vocal_coach.drive.client import DRIVE_API
from vocal_coach.storage import repo
from vocal_coach.storage.db import make_engine, make_session_factory

DRIVE_GET_FIELDS = "id,name,mimeType,modifiedTime,size"


def _drive_overrides(**extra) -> dict:
    return {
        "google_client_id": "cid",
        "google_client_secret": "sec",
        "google_redirect_uri": "http://localhost:8000/api/drive/callback",
        "drive_token_key": crypto.generate_key(),
        "secret_key": "test-secret-key-0123456789abcdefghij",
        **extra,
    }


def _connect_drive(ctx, sub="user-1", email="singer@example.com"):
    """Stores a Drive connection directly (bypassing the OAuth consent flow), returning the user id."""
    with ctx["session_factory"]() as session:
        user = repo.upsert_user(session, sub, None, None)
        encrypted = crypto.encrypt_token(ctx["settings"].drive_token_key, "1//refresh")
        repo.upsert_drive_connection(session, user.id, encrypted_refresh_token=encrypted, google_email=email)
        return user.id


def _mock_get_file(httpx_mock, file_id, *, name, modified_time, mime_type="audio/wav", size="10", status_code=200):
    url = httpx.URL(f"{DRIVE_API}/{file_id}", params={"fields": DRIVE_GET_FIELDS})
    if status_code != 200:
        httpx_mock.add_response(url=url, status_code=status_code)
        return
    httpx_mock.add_response(url=url, json={
        "id": file_id, "name": name, "mimeType": mime_type, "modifiedTime": modified_time, "size": size,
    })


def _capturing_job_fn(captured):
    def job_fn(req, database_url, config_path):
        captured.append(req)
        engine = make_engine(database_url)
        with make_session_factory(engine)() as s:
            repo.update_job(s, req.job_id, status="done", stage="done", progress_pct=100)
        engine.dispose()
    return job_fn


def fake_job_fn(req, database_url, config_path):
    """Pretend the pipeline ran: store a tiny analysis and finish the job.

    Mirrors production hashing: the upload is named by the hash of its bytes (`source_sha256`), while
    `content_sha256` is the extracted WAV's hash — a DIFFERENT value, so cleanup must use the former.
    """
    import hashlib

    raw = req.source_path.read_bytes()
    source_sha = hashlib.sha256(raw).hexdigest()
    assert req.source_sha256 == source_sha
    wav_sha = hashlib.sha256(b"wav:" + raw).hexdigest()
    engine = make_engine(database_url)
    with make_session_factory(engine)() as s:
        row = repo.create_analysis(
            s, req.user_id, file_name=req.file_name, drive_file_id=None, content_sha256=wav_sha,
            source_sha256=source_sha,
            recorded_at=req.recorded_at, analyser_version="0.1.0", config_hash="sha256:test",
            metrics_json=fake_metrics(), transcript_json=fake_transcript(), speaker_context=req.speaker_context,
        )
        repo.update_job(s, req.job_id, status="done", stage="done", progress_pct=100, analysis_id=row.id)
    engine.dispose()


def failing_job_fn(req, database_url, config_path):
    engine = make_engine(database_url)
    with make_session_factory(engine)() as s:
        repo.update_job(s, req.job_id, status="failed", error="boom")
    engine.dispose()


def _wav_bytes(seconds=1.0) -> bytes:
    from scipy.io import wavfile
    buf = io.BytesIO()
    wavfile.write(buf, synth.SR, (synth.tone(120, seconds) * 32767).astype("int16"))
    return buf.getvalue()


def _upload(client, headers, name="clip.wav", data=None, **form):
    return client.post("/api/analyses", headers=headers, files={"file": (name, data or _wav_bytes(), "audio/wav")}, data=form)


def test_upload_creates_job_and_analysis_visible_in_list_and_detail(tmp_path):
    app, ctx = make_test_app(tmp_path, job_fn=fake_job_fn)
    with TestClient(app) as client:
        r = _upload(client, ctx["auth"](), speaker_context="sales pitch")
        assert r.status_code == 202
        job_id = r.json()["job_ids"][0]
        job = client.get(f"/api/jobs/{job_id}", headers=ctx["auth"]()).json()
        assert job["status"] == "done" and job["analysis_id"]
        listing = client.get("/api/analyses", headers=ctx["auth"]()).json()
        assert len(listing) == 1 and listing[0]["file_name"] == "clip.wav"
        assert listing[0]["f0_median_hz"] == 123.0 and listing[0]["has_transcript"] is True and listing[0]["has_coaching"] is False
        detail = client.get(f"/api/analyses/{job['analysis_id']}", headers=ctx["auth"]()).json()
        assert detail["metrics"]["pitch"]["f0_range_st"] == 9.0 and detail["speaker_context"] == "sales pitch"
        contours = detail["metrics"]["intonation"]["per_phrase"]
        assert contours and all("class" in c and "class_" not in c for c in contours)  # alias on the wire
        assert detail["transcript"]["derived"]["fillers_per_min"] == 1.5
        raw = client.get(f"/api/analyses/{job['analysis_id']}/raw/metrics", headers=ctx["auth"]())
        assert raw.status_code == 200 and raw.headers["content-disposition"].endswith('clip.metrics.json"')
        assert raw.text == json.dumps(detail["metrics"], sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        assert client.get(f"/api/analyses/{job['analysis_id']}/raw/coaching", headers=ctx["auth"]()).status_code == 404
        stored = list((tmp_path / "data" / "uploads").rglob("*.wav"))
        assert len(stored) == 1


def test_cross_user_is_404_everywhere(tmp_path):
    app, ctx = make_test_app(tmp_path, job_fn=fake_job_fn)
    with TestClient(app) as client:
        job_id = _upload(client, ctx["auth"]("alice")).json()["job_ids"][0]
        analysis_id = client.get(f"/api/jobs/{job_id}", headers=ctx["auth"]("alice")).json()["analysis_id"]
        bob = ctx["auth"]("bob")
        assert client.get(f"/api/jobs/{job_id}", headers=bob).status_code == 404
        assert client.get(f"/api/analyses/{analysis_id}", headers=bob).status_code == 404
        assert client.delete(f"/api/analyses/{analysis_id}", headers=bob).status_code == 404
        assert client.get("/api/analyses", headers=bob).json() == []
        assert client.post(f"/api/analyses/{analysis_id}/coach", headers=bob).status_code == 404
        # config.yaml's llm.model is empty and the provider is not anthropic: no default model, so this
        # is a 422 (no network call); see test_api_llm.py for the enabled/model-resolved paths.
        assert client.post(f"/api/analyses/{analysis_id}/coach", headers=ctx["auth"]("alice")).status_code == 422


def test_delete_removes_row_and_upload_file(tmp_path):
    app, ctx = make_test_app(tmp_path, job_fn=fake_job_fn)
    with TestClient(app) as client:
        job_id = _upload(client, ctx["auth"]()).json()["job_ids"][0]
        analysis_id = client.get(f"/api/jobs/{job_id}", headers=ctx["auth"]()).json()["analysis_id"]
        assert list((tmp_path / "data" / "uploads").rglob("*.wav"))
        assert client.delete(f"/api/analyses/{analysis_id}", headers=ctx["auth"]()).status_code == 204
        assert client.get(f"/api/analyses/{analysis_id}", headers=ctx["auth"]()).status_code == 404
        assert not list((tmp_path / "data" / "uploads").rglob("*.wav"))
        with ctx["session_factory"]() as s:
            user = repo.upsert_user(s, "user-1", None, None)
            assert repo.count_source_refs(s, user.id, repo.list_jobs(s, user.id)[0].source_sha256) == 0


def test_upload_validation(tmp_path):
    app, ctx = make_test_app(tmp_path, job_fn=fake_job_fn, max_upload_mb=1)
    with TestClient(app) as client:
        assert _upload(client, ctx["auth"](), name="notes.txt", data=b"hello").status_code == 415
        big = b"\0" * (1024 * 1024 + 1)
        r = _upload(client, ctx["auth"](), name="big.mp3", data=big)
        assert r.status_code == 413
        assert not list((tmp_path / "data" / "uploads").rglob("*"))  # partial upload removed
        r = client.post("/api/analyses", headers=ctx["auth"](), json={"source": "drive", "file_ids": ["x"]})
        assert r.status_code == 503  # this server has no Google credentials
        assert r.json()["detail"] == "drive is not configured on this server"
        assert client.post("/api/analyses", files={"file": ("a.wav", b"x", "audio/wav")}).status_code == 401


def test_drive_json_post_creates_one_job_per_file_in_order(tmp_path, httpx_mock):
    captured = []
    app, ctx = make_test_app(tmp_path, job_fn=_capturing_job_fn(captured), settings_overrides=_drive_overrides())
    with TestClient(app) as client:
        user_id = _connect_drive(ctx)
        httpx_mock.add_response(url=oauth.TOKEN_URL, json={"access_token": "listing-tok"})
        _mock_get_file(httpx_mock, "f1", name="one.wav", modified_time="2026-10-01T00:00:00.000Z")
        _mock_get_file(httpx_mock, "f2", name="two.m4a", modified_time="2026-10-02T00:00:00.000Z", mime_type="audio/mp4")

        r = client.post("/api/analyses", headers=ctx["auth"](),
                        json={"source": "drive", "file_ids": ["f1", "f2"], "speaker_context": "pitch",
                              "llm": {"enabled": True, "model": "m1"}})

        assert r.status_code == 202
        job_ids = r.json()["job_ids"]
        assert len(job_ids) == 2
        assert len(captured) == 2

        assert captured[0].file_name == "one.wav" and captured[1].file_name == "two.m4a"
        assert captured[0].drive_file_id == "f1" and captured[1].drive_file_id == "f2"
        assert captured[0].drive_modified_time == "2026-10-01T00:00:00.000Z"
        assert captured[0].recorded_at == datetime(2026, 10, 1, tzinfo=timezone.utc)
        assert captured[1].recorded_at == datetime(2026, 10, 2, tzinfo=timezone.utc)
        assert captured[0].speaker_context == "pitch" and captured[1].speaker_context == "pitch"
        assert captured[0].llm_enabled is True and captured[0].llm_model == "m1"
        assert captured[0].source_sha256 is None
        assert captured[0].user_id == user_id

        job1 = client.get(f"/api/jobs/{job_ids[0]}", headers=ctx["auth"]()).json()
        job2 = client.get(f"/api/jobs/{job_ids[1]}", headers=ctx["auth"]()).json()
        assert job1["file_name"] == "one.wav" and job2["file_name"] == "two.m4a"


def _jobs_for(ctx, sub="user-1"):
    with ctx["session_factory"]() as s:
        return repo.list_jobs(s, repo.upsert_user(s, sub, None, None).id)


@pytest.mark.parametrize("name, mime_type, size", [
    ("notes.pdf", "application/pdf", "10"),
    ("Meeting notes", "application/vnd.google-apps.document", None),  # Google Doc: no extension, no size
    ("take.wav", "audio/wav", None),  # media name but Drive reports no size
])
def test_drive_json_post_unsupported_file_is_415_with_zero_jobs(tmp_path, httpx_mock, name, mime_type, size):
    captured = []
    app, ctx = make_test_app(tmp_path, job_fn=_capturing_job_fn(captured), settings_overrides=_drive_overrides())
    with TestClient(app) as client:
        _connect_drive(ctx)
        httpx_mock.add_response(url=oauth.TOKEN_URL, json={"access_token": "tok"})
        _mock_get_file(httpx_mock, "ok1", name="good.wav", modified_time="2026-10-01T00:00:00.000Z")
        url = httpx.URL(f"{DRIVE_API}/bad1", params={"fields": DRIVE_GET_FIELDS})
        entry = {"id": "bad1", "name": name, "mimeType": mime_type, "modifiedTime": "2026-10-01T00:00:00.000Z"}
        if size is not None:
            entry["size"] = size
        httpx_mock.add_response(url=url, json=entry)

        r = client.post("/api/analyses", headers=ctx["auth"](), json={"source": "drive", "file_ids": ["ok1", "bad1"]})

        assert r.status_code == 415
        assert r.json()["detail"] == f"unsupported file type: {name}"
        assert captured == [] and _jobs_for(ctx) == []


def test_drive_json_post_oversized_file_is_413_with_zero_jobs(tmp_path, httpx_mock):
    captured = []
    app, ctx = make_test_app(tmp_path, job_fn=_capturing_job_fn(captured), max_upload_mb=1,
                             settings_overrides=_drive_overrides())
    with TestClient(app) as client:
        _connect_drive(ctx)
        httpx_mock.add_response(url=oauth.TOKEN_URL, json={"access_token": "tok"})
        _mock_get_file(httpx_mock, "ok1", name="good.wav", modified_time="2026-10-01T00:00:00.000Z",
                       size=str(1024 * 1024))
        _mock_get_file(httpx_mock, "big1", name="long take.mov", modified_time="2026-10-01T00:00:00.000Z",
                       size=str(1024 * 1024 + 1))

        r = client.post("/api/analyses", headers=ctx["auth"](), json={"source": "drive", "file_ids": ["ok1", "big1"]})

        assert r.status_code == 413
        assert r.json()["detail"] == "file too large: long take.mov"
        assert captured == [] and _jobs_for(ctx) == []


def test_drive_json_post_runner_failure_mid_batch_fails_the_whole_batch(tmp_path, httpx_mock):
    from vocal_coach.jobs.runner import RunnerUnavailable

    class DiesAfterFirst:
        def __init__(self):
            self.calls = 0

        def submit(self, req):
            self.calls += 1
            if self.calls > 1:
                raise RunnerUnavailable("job runner unavailable")

    app, ctx = make_test_app(tmp_path, job_fn=fake_job_fn, settings_overrides=_drive_overrides())
    with TestClient(app) as client:
        app.state.runner = DiesAfterFirst()
        _connect_drive(ctx)
        httpx_mock.add_response(url=oauth.TOKEN_URL, json={"access_token": "tok"})
        _mock_get_file(httpx_mock, "f1", name="one.wav", modified_time="2026-10-01T00:00:00.000Z")
        _mock_get_file(httpx_mock, "f2", name="two.wav", modified_time="2026-10-02T00:00:00.000Z")

        r = client.post("/api/analyses", headers=ctx["auth"](), json={"source": "drive", "file_ids": ["f1", "f2"]})

        assert r.status_code == 503
        jobs = _jobs_for(ctx)
        assert len(jobs) == 2
        assert {(j.status, j.error) for j in jobs} == {("failed", "job runner unavailable")}


def test_drive_json_post_422_detail_lists_messages_only(tmp_path):
    app, ctx = make_test_app(tmp_path, job_fn=fake_job_fn, settings_overrides=_drive_overrides())
    with TestClient(app) as client:
        _connect_drive(ctx)
        r = client.post("/api/analyses", headers=ctx["auth"](), json={"source": "drive", "file_ids": []})
        assert r.status_code == 422
        detail = r.json()["detail"]
        assert detail == "List should have at least 1 item after validation, not 0"
        assert "pydantic" not in detail and "https://" not in detail


def test_drive_json_post_404_aborts_with_zero_jobs(tmp_path, httpx_mock):
    captured = []
    app, ctx = make_test_app(tmp_path, job_fn=_capturing_job_fn(captured), settings_overrides=_drive_overrides())
    with TestClient(app) as client:
        _connect_drive(ctx)
        httpx_mock.add_response(url=oauth.TOKEN_URL, json={"access_token": "listing-tok"})
        _mock_get_file(httpx_mock, "missing", name="", modified_time="", status_code=404)

        r = client.post("/api/analyses", headers=ctx["auth"](), json={"source": "drive", "file_ids": ["missing"]})

        assert r.status_code == 404
        assert r.json()["detail"] == "drive file missing not found"
        assert captured == []
        assert client.get("/api/jobs", headers=ctx["auth"]()).json() == []


def test_drive_json_post_second_id_not_found_creates_no_jobs(tmp_path, httpx_mock):
    """Metadata is fetched for every id before any job is created: a later id failing still leaves zero jobs."""
    captured = []
    app, ctx = make_test_app(tmp_path, job_fn=_capturing_job_fn(captured), settings_overrides=_drive_overrides())
    with TestClient(app) as client:
        _connect_drive(ctx)
        httpx_mock.add_response(url=oauth.TOKEN_URL, json={"access_token": "listing-tok"})
        _mock_get_file(httpx_mock, "f1", name="one.wav", modified_time="2026-10-01T00:00:00.000Z")
        _mock_get_file(httpx_mock, "missing", name="", modified_time="", status_code=404)

        r = client.post("/api/analyses", headers=ctx["auth"](),
                        json={"source": "drive", "file_ids": ["f1", "missing"]})

        assert r.status_code == 404
        assert captured == []
        assert client.get("/api/jobs", headers=ctx["auth"]()).json() == []


def test_drive_json_post_not_connected_is_409(tmp_path):
    app, ctx = make_test_app(tmp_path, job_fn=fake_job_fn, settings_overrides=_drive_overrides())
    with TestClient(app) as client:
        r = client.post("/api/analyses", headers=ctx["auth"](), json={"source": "drive", "file_ids": ["f1"]})
        assert r.status_code == 409
        assert r.json()["detail"] == "drive_not_connected"


def test_drive_json_post_too_many_file_ids_is_422(tmp_path):
    app, ctx = make_test_app(tmp_path, job_fn=fake_job_fn, settings_overrides=_drive_overrides())
    with TestClient(app) as client:
        _connect_drive(ctx)
        r = client.post("/api/analyses", headers=ctx["auth"](),
                        json={"source": "drive", "file_ids": [f"f{i}" for i in range(21)]})
        assert r.status_code == 422


@pytest.mark.parametrize("bad_id", ["a/b", "../etc", "a b", "x" * 201, "", "id?alt=media"])
def test_drive_json_post_malformed_file_id_is_422_without_calling_google(tmp_path, httpx_mock, bad_id):
    app, ctx = make_test_app(tmp_path, job_fn=fake_job_fn, settings_overrides=_drive_overrides())
    with TestClient(app) as client:
        _connect_drive(ctx)
        r = client.post("/api/analyses", headers=ctx["auth"](), json={"source": "drive", "file_ids": [bad_id]})
        assert r.status_code == 422
        assert not httpx_mock.get_requests()
        with ctx["session_factory"]() as s:
            assert repo.list_jobs(s, repo.upsert_user(s, "user-1", None, None).id) == []


def test_drive_json_post_invalid_source_is_422(tmp_path):
    app, ctx = make_test_app(tmp_path, job_fn=fake_job_fn, settings_overrides=_drive_overrides())
    with TestClient(app) as client:
        _connect_drive(ctx)
        r = client.post("/api/analyses", headers=ctx["auth"](), json={"source": "nope", "file_ids": ["f1"]})
        assert r.status_code == 422


def test_failed_job_is_visible(tmp_path):
    app, ctx = make_test_app(tmp_path, job_fn=failing_job_fn)
    with TestClient(app) as client:
        job_id = _upload(client, ctx["auth"]()).json()["job_ids"][0]
        job = client.get(f"/api/jobs/{job_id}", headers=ctx["auth"]()).json()
        assert job["status"] == "failed" and job["error"] == "boom"


def test_upload_returns_503_and_fails_job_when_runner_unavailable(tmp_path):
    from vocal_coach.jobs.runner import RunnerUnavailable

    class DeadRunner:
        def submit(self, req):
            raise RunnerUnavailable("job runner unavailable")

    app, ctx = make_test_app(tmp_path, job_fn=fake_job_fn)
    with TestClient(app) as client:
        app.state.runner = DeadRunner()
        r = _upload(client, ctx["auth"]())
        assert r.status_code == 503 and r.json()["detail"] == "job runner unavailable; try again"
        with ctx["session_factory"]() as s:
            user = repo.upsert_user(s, "user-1", None, None)
            jobs = repo.list_jobs(s, user.id)
        assert len(jobs) == 1 and (jobs[0].status, jobs[0].error) == ("failed", "job runner unavailable")


def _uploads(tmp_path):
    return [p for p in (tmp_path / "data" / "uploads").rglob("*") if p.is_file()]


def test_delete_keeps_upload_while_another_analysis_uses_it(tmp_path):
    """Same bytes analysed under two configs (simulated by a second row) share one upload file."""
    app, ctx = make_test_app(tmp_path, job_fn=fake_job_fn)
    with TestClient(app) as client:
        job_id = _upload(client, ctx["auth"]()).json()["job_ids"][0]
        first = client.get(f"/api/jobs/{job_id}", headers=ctx["auth"]()).json()["analysis_id"]
        with ctx["session_factory"]() as s:
            user = repo.upsert_user(s, "user-1", None, None)
            src = repo.get_analysis(s, user.id, uuid.UUID(first))
            second = repo.create_analysis(
                s, user.id, file_name="clip.wav", drive_file_id=None, content_sha256=src.content_sha256,
                source_sha256=src.source_sha256, recorded_at=src.recorded_at, analyser_version="0.1.0",
                config_hash="sha256:other", metrics_json=src.metrics_json)
        assert client.delete(f"/api/analyses/{first}", headers=ctx["auth"]()).status_code == 204
        assert len(_uploads(tmp_path)) == 1
        assert client.delete(f"/api/analyses/{second.id}", headers=ctx["auth"]()).status_code == 204
        assert _uploads(tmp_path) == []


@requires_ffmpeg
def test_failed_pipeline_removes_the_upload(tmp_path, monkeypatch):
    """Real worker entry point (synchronously): a file ffmpeg cannot decode fails the job and the upload goes."""
    from vocal_coach.jobs.runner import run_job

    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    app, ctx = make_test_app(tmp_path, job_fn=run_job)
    with TestClient(app) as client:
        r = _upload(client, ctx["auth"](), name="talk.mp3", data=b"this is not audio")
        job = client.get(f"/api/jobs/{r.json()['job_ids'][0]}", headers=ctx["auth"]()).json()
        assert job["status"] == "failed"
        assert job["error"] == "could not decode talk.mp3: not a supported audio/video file"
        assert "/data/" not in job["error"] and "ffprobe" not in job["error"]
        assert _uploads(tmp_path) == []


def test_file_name_is_stripped_of_client_directories(tmp_path):
    app, ctx = make_test_app(tmp_path, job_fn=fake_job_fn)
    with TestClient(app) as client:
        job_id = _upload(client, ctx["auth"](), name="../../x/clip.wav").json()["job_ids"][0]
        job = client.get(f"/api/jobs/{job_id}", headers=ctx["auth"]()).json()
        assert job["file_name"] == "clip.wav"
        detail = client.get(f"/api/analyses/{job['analysis_id']}", headers=ctx["auth"]()).json()
        assert detail["file_name"] == "clip.wav"


def test_recorded_at_form_field(tmp_path):
    app, ctx = make_test_app(tmp_path, job_fn=fake_job_fn)
    with TestClient(app) as client:
        job_id = _upload(client, ctx["auth"](), recorded_at="2026-09-30T08:15:00+02:00").json()["job_ids"][0]
        analysis_id = client.get(f"/api/jobs/{job_id}", headers=ctx["auth"]()).json()["analysis_id"]
        detail = client.get(f"/api/analyses/{analysis_id}", headers=ctx["auth"]()).json()
        assert datetime.fromisoformat(detail["recorded_at"]) == datetime(2026, 9, 30, 6, 15, tzinfo=timezone.utc)
        naive = _upload(client, ctx["auth"](), name="b.wav", data=_wav_bytes(1.5), recorded_at="2026-09-30T08:15:00")
        assert naive.status_code == 422
        junk = _upload(client, ctx["auth"](), name="c.wav", data=_wav_bytes(1.7), recorded_at="last tuesday")
        assert junk.status_code == 422
        assert len(client.get("/api/jobs", headers=ctx["auth"]()).json()) == 1  # rejected uploads made no job


def test_list_pagination(tmp_path):
    app, ctx = make_test_app(tmp_path, job_fn=fake_job_fn)
    with TestClient(app) as client:
        for i in range(3):
            _upload(client, ctx["auth"](), name=f"c{i}.wav", data=_wav_bytes(1.0 + 0.1 * i))
        assert len(client.get("/api/analyses?limit=2", headers=ctx["auth"]()).json()) == 2
        assert len(client.get("/api/analyses?limit=2&offset=2", headers=ctx["auth"]()).json()) == 1
        assert client.get("/api/analyses?limit=0", headers=ctx["auth"]()).status_code == 422


def test_download_filename_sanitises_quotes_and_crlf():
    assert _download_filename('evil"na\r\nme', "metrics") == "evil_na__me.metrics.json"


def test_download_filename_empty_stem_falls_back_to_analysis():
    assert _download_filename("", "transcript") == "analysis.transcript.json"


def test_download_filename_is_truncated():
    assert _download_filename("a" * 500, "coaching") == ("a" * 100) + ".coaching.json"


def test_raw_download_filename_header_has_no_injected_quote_or_crlf(tmp_path):
    app, ctx = make_test_app(tmp_path, job_fn=fake_job_fn)
    with TestClient(app) as client:
        job_id = _upload(client, ctx["auth"](), name='we ird"name.wav').json()["job_ids"][0]
        analysis_id = client.get(f"/api/jobs/{job_id}", headers=ctx["auth"]()).json()["analysis_id"]
        raw = client.get(f"/api/analyses/{analysis_id}/raw/metrics", headers=ctx["auth"]())
        assert raw.status_code == 200
        cd = raw.headers["content-disposition"]
        assert cd.count('"') == 2  # only the two delimiters around the filename value
        filename_value = cd.split('filename="', 1)[1].rstrip('"')
        assert '"' not in filename_value and "\r" not in filename_value and "\n" not in filename_value


def test_reject_if_declared_too_large_raises_413_without_reading_body():
    req = StarletteRequest({"type": "http", "headers": [(b"content-length", b"999999999")]})
    with pytest.raises(HTTPException) as exc_info:
        _reject_if_declared_too_large(req, max_bytes=1000)
    assert exc_info.value.status_code == 413


def test_reject_if_declared_too_large_ignores_non_numeric_header():
    req = StarletteRequest({"type": "http", "headers": [(b"content-length", b"not-a-number")]})
    _reject_if_declared_too_large(req, max_bytes=1000)  # must not raise


def test_reject_if_declared_too_large_ignores_missing_header():
    req = StarletteRequest({"type": "http", "headers": []})
    _reject_if_declared_too_large(req, max_bytes=1000)  # must not raise
